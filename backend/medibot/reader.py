"""Model-first message reader: one LLM call per message turns ANY wording (slang, Hinglish, typos, chat noise)
into a typed reading. The model only READS - it never decides and never writes facts.

    "dude yoo....idk man wtf is crocin"            -> medicines ["crocin"], intents ["info"]
    "bro my head is killin me lol wat do i pop"    -> medicines [], asks_what_to_take
    "omg augmntin 625 sooo expensive any cheapr"   -> medicines ["augmntin 625"], intents ["substitute"]
    "my dad isnt waking up and hes breathing weird"-> emergency
    "who won the match yesterday"                  -> off_topic

Guards (everything the model returns is checked by our code):
- a medicine phrase is kept only if every word of it was typed by the user (whole words) -> the model can't add
  "Remo Tablet" for "varemo"; the phrase then goes through the deterministic resolver like any typed name
- only known keys and literal booleans are read; anything else is ignored
- no answer within the budget / bad JSON / LLM off -> None, and the rule-based reader is used alone
The reading is merged in assistant.query(): medicines are resolved by mentions.py, danger flags can only ADD
protection (kernel.apply_reading), and the Safety Kernel stays the only authority.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field

from medibot.llm import FAST, _env, get_llm
from medibot.mentions import tokenize

BUDGET = float(os.environ.get("MEDIBOT_READER_BUDGET", "3.5"))
# benchmark 2026-10-11 (15 slang / Hinglish / emergency messages): claude-haiku-5.5 via the Cline gateway 15/15,
# p50 1.5 s; gemini-3.8-flash 15/15 p50 2.8 s; gpt-6-luna 15/15 p50 2.9 s; groq gpt-oss-20b timed out under load
MODEL = os.environ.get("MEDIBOT_READER_MODEL",
                       "cline:anthropic/claude-haiku-5.5" if _env("MEDIBOT_LLM2_API_KEY") else FAST)
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="reader")

INTENTS = ("price", "substitute", "info", "interaction", "store", "compare")
FLAGS = ("emergency", "self_harm", "misuse", "asks_what_to_take", "asks_dose", "asks_diagnosis",
         "off_topic", "greeting", "refers_back")

SYSTEM = """You read messages sent to MediBot, an Indian medicine price + information assistant. Messages can be
English, Hindi, Hinglish, slang, typos or chat noise ("bro", "lol", "idk", "yaar", "wtf"). You do NOT answer.
Return only JSON with exactly these keys:
{"medicines": [string], "spelling": {string: string}, "intents": [string], "emergency": bool, "self_harm": bool, "misuse": bool,
 "asks_what_to_take": bool, "asks_dose": bool, "asks_diagnosis": bool, "off_topic": bool, "greeting": bool,
 "refers_back": bool}

medicines: medicine brand or generic names written in THIS message, copied EXACTLY as typed, typos included, with
  any strength/form words the user wrote ("augmntin 625", "dolo", "crocin advance", "cough syrup" is NOT a name).
  Never include slang, filler, symptoms, body parts, or words that only look like a brand ("lol", "ngl", "bro",
  "cheapr", "waking"). Never add a medicine the user did not write. Empty list if none.
spelling: for each name in "medicines" that looks misspelt, the correctly spelt Indian brand or generic name you
  believe was meant, e.g. {"naxodam": "Naxdom", "augmntin 625": "Augmentin 625", "dolo": "Dolo"}. Only a likely
  spelling fix of the SAME word, never a different medicine. Omit names that are already spelt correctly.
intents (any of): price (cost, rate, kitne ka, "is it available", milega / mil jayega / hai kya), substitute (cheaper / generic / alternative / sasta),
  info (what is it, uses, side effects, safety, pregnancy, alcohol, how to use), interaction (two medicines
  together, with alcohol/food), store (Jan Aushadhi / nearest shop / pincode), compare (difference between two).
emergency: someone needs urgent care NOW (not waking up, unconscious, breathing trouble or "breathing weird",
  blue lips, chest pain, seizure/fits, heavy bleeding, poisoning, overdose, severe allergic swelling, stroke signs).
self_harm: wants to die or hurt themselves.
misuse: wants to get high / intoxicated or use a medicine in a harmful non-medical way.
asks_what_to_take: asks which medicine to take or buy for a symptom/condition ("what should I take for fever",
  "wat do i pop", "koi dawai batao"). Asking about a medicine they named is NOT this.
asks_dose: asks how much / how many / how often / how long to take ("2 tablets ok?", "kitni goli").
  Asking a price ("kitne ka hai") is NOT a dose question.
asks_diagnosis: asks what condition/disease they have ("do I have dengue", "what is wrong with me").
off_topic: nothing to do with medicines, health or pharmacies (cricket, poems, maths, coding).
greeting: only a greeting / thanks / small talk.
refers_back: uses "it", "this", "iska", "the second one", "same one" etc. for something said earlier.
Set a flag true only when the message clearly says so."""


@dataclass
class Reading:
    status: str                              # used | skipped | timeout | error
    reason: str = ""
    medicines: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    flags: dict = field(default_factory=dict)
    seconds: float = 0.0
    dropped: list[str] = field(default_factory=list)   # model phrases rejected by the typed-words guard
    spelling: dict = field(default_factory=dict)         # typed phrase -> model's spelling fix (checked by merge)

    @property
    def ok(self) -> bool:
        return self.status == "used"

    def as_receipt(self) -> dict:
        return {"status": self.status, "reason": self.reason, "medicines": self.medicines, "spelling": self.spelling,
                "intents": self.intents,
                "flags": {k: v for k, v in self.flags.items() if v}, "dropped": self.dropped, "seconds": self.seconds}


def typed(phrase: str, text: str) -> bool:
    """Every word of the phrase was typed by the user, as a whole word (numbers/units included)."""
    words = set(tokenize(text))
    p = tokenize(phrase)
    return bool(p) and all(w in words for w in p)


def _ask(text: str, context: str | None) -> Reading:
    t0 = time.time()
    user = text if not context else f"(earlier in this chat the user talked about: {context})\nMessage: {text}"
    out = get_llm().chat_json(SYSTEM, user, model=MODEL, max_tokens=int(os.environ.get("MEDIBOT_READER_MAX_TOKENS", "1200")), max_wait=BUDGET,
                              reasoning_effort="low" if "gpt-oss" in MODEL else None)
    secs = round(time.time() - t0, 3)
    if not isinstance(out, dict):
        return Reading("error", "no valid JSON", seconds=secs)
    meds, dropped = [], []
    for m in out.get("medicines") or []:
        if isinstance(m, str) and 2 <= len(m) <= 60:
            (meds if typed(m, text) else dropped).append(m.strip())
    intents = [i for i in out.get("intents") or [] if isinstance(i, str) and i in INTENTS]
    flags = {k: out.get(k) is True for k in FLAGS}
    sp = out.get("spelling") if isinstance(out.get("spelling"), dict) else {}
    spelling = {k.strip(): v.strip() for k, v in sp.items()
                if isinstance(k, str) and isinstance(v, str) and k.strip() in meds and 2 <= len(v) <= 60}
    return Reading("used", medicines=meds[:4], intents=list(dict.fromkeys(intents)), flags=flags, seconds=secs,
                   dropped=dropped, spelling=spelling)


def start(text: str, context: str | None = None):
    llm = get_llm()
    ok, why = llm.allow("reader", MODEL)
    if not ok:
        return None, Reading("skipped", why)
    return _POOL.submit(_ask, text, context), None


def collect(fut, early: Reading | None, started: float) -> Reading:
    if fut is None:
        return early or Reading("skipped", "not started")
    try:
        return fut.result(timeout=max(0.0, BUDGET - (time.time() - started)))
    except TimeoutError:
        return Reading("timeout", f"no answer within {BUDGET:.1f} s -> rules only", seconds=round(time.time() - started, 3))
    except Exception as e:  # noqa: BLE001 - optional layer, never breaks a reply
        return Reading("error", type(e).__name__)


def read(text: str, context: str | None = None) -> Reading:
    t0 = time.time()
    fut, early = start(text, context)
    return collect(fut, early, t0)
