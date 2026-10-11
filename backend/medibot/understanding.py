"""Understanding layer: message -> typed Request. Rules first; the LLM only for messages the rules can't read.

The LLM never decides anything: it may only suggest (a) intents and (b) medicine words as the user typed
them. Those words still go through the tested resolver (mentions.py) and the Safety Kernel.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from medibot.llm import FAST, get_llm

INTENT_RULES = [
    ("substitute", r"cheaper|\bcheap\b|sasta|sasti|saste|alternative|substitute|generic|same as|similar|option|replacement|jan aushadhi"),
    ("price", r"price|cost|rate|kitne|kitna|how much (is|does|for)|mrp|buy|where can i|available|milega|milegi|kaha|kahan"),
    ("interaction", r"together|interact|with alcohol|alcohol ke saath|mix(ed)? with|along with|saath mein|combine"),
    ("store", r"jan aushadhi (store|kendra|shop)|kendra|nearest (jan aushadhi|store|shop|pharmacy|chemist|medical)|near me|nearby|pincode|pin code"),
    ("compare", r"compare|difference between|vs\.?\b|versus|better than|which is better"),
    ("info", r"used for|use of|what is|side effect|how (does|do) .* work|kis kaam|safe|pregnan|breastfeed|drive|habit|"
             r"tell me about|information|details|composition|ingredient|contains|generic name"),
    ("greeting", r"^(hi|hello|hey|namaste|thanks|thank you|ok|okay)\b"),
]
ORDINALS = {"first": 1, "1st": 1, "pehla": 1, "pehli": 1, "second": 2, "2nd": 2, "dusra": 2, "doosra": 2, "dusri": 2,
            "third": 3, "3rd": 3, "teesra": 3, "tisra": 3, "teesri": 3, "last": -1, "aakhri": -1}
FORM_VARIANT = r"(gel|syrup|suspension|tablet|tab|capsule|cream|ointment|drops?|injection|spray|lotion|powder|sachet|liquid|chewable)"


@dataclass
class Request:
    text: str
    intents: list[str] = field(default_factory=list)
    medicine_words: list[str] = field(default_factory=list)   # LLM-suggested, to be resolved deterministically
    ordinal: int | None = None                                # "the second one" -> 2
    superlative: str | None = None                            # "cheapest"
    strength: str | None = None                               # "the 500 one" -> "500"
    form: str | None = None                                   # "the gel one" -> "gel"
    pincode: str | None = None
    refers_back: bool = False                                 # "it", "this", "iska"
    used_llm: bool = False


def rules(text: str) -> Request:
    t = text.lower().strip()
    r = Request(text=text)
    for name, rx in INTENT_RULES:
        if re.search(rx, t):
            r.intents.append(name)
    m = re.search(r"\b(" + "|".join(ORDINALS) + r")\b(?:\s+(one|wala|wali|option|medicine|item))?", t)
    if m:
        r.ordinal = ORDINALS[m.group(1)]
    if re.search(r"\b(cheapest|sabse sasta|lowest price|best price)\b", t):
        r.superlative = "cheapest"
    m = re.search(r"\b(?:the |wo |woh |ye )?(\d+(?:\.\d+)?)\s*(?:mg|ml|mcg)?\s*(?:one|wala|vala|wali|version|variant|strength)\b", t) \
        or re.search(r"\bwhat about (?:the )?(\d+(?:\.\d+)?)\b", t)
    if m:
        r.strength = m.group(1)
    m = re.search(rf"\b(?:the |wo |woh |ye )?{FORM_VARIANT}\s*(?:one|wala|vala|wali|version|variant|form)\b", t) \
        or re.search(rf"\b(?:in|as) (?:a )?{FORM_VARIANT}\b", t)
    if m:
        r.form = m.group(1)
    m = re.search(r"\b([1-9]\d{5})\b", t)
    if m:
        r.pincode = m.group(1)
    r.refers_back = bool(re.search(r"\b(it|this|that|these|those|iska|iski|iske|uska|uski|isko|usko|ye|yeh|wo|woh|same|"
                                   r"the one|this one|that one)\b", t))
    return r


_SYSTEM = """You read short messages sent to an Indian medicine-information assistant (English, Hindi or Hinglish).
Return JSON: {"intents": [...], "medicines": [...]}.
- intents: any of price, substitute, info, interaction, store, compare, symptom, other.
- medicines: medicine names (brands or generic names) EXACTLY as the user wrote them, including any strength/form
  words they wrote (e.g. "augmantin 625", "dolo"). Do not correct spelling. Do not add medicines that are not written.
  Do not include symptoms, diseases or body parts. Empty list if none.
Return only the JSON."""


def understand(text: str, *, have_mentions: bool, have_context: bool, allow_llm: bool = True) -> Request:
    """Rules first. The LLM is asked only when the rules found no medicine, no reference to the conversation
    and no other handle — and the message is long enough to plausibly name one."""
    r = rules(text)
    needs_llm = (not have_mentions and r.ordinal is None and r.strength is None and r.form is None
                 and r.pincode is None and not (r.refers_back and have_context)
                 and len(text.split()) >= 3 and "greeting" not in r.intents)
    if needs_llm and allow_llm:
        out = get_llm().chat_json(_SYSTEM, text, model=FAST, max_tokens=200)
        if isinstance(out, dict):
            r.used_llm = True
            for i in out.get("intents") or []:
                if isinstance(i, str) and i in {"price", "substitute", "info", "interaction", "store", "compare",
                                                "symptom", "other"} and i not in r.intents:
                    r.intents.append(i)
            r.medicine_words = [m for m in (out.get("medicines") or []) if isinstance(m, str) and 2 <= len(m) <= 60][:4]
    if not r.intents:
        r.intents = ["info"]
    return r
