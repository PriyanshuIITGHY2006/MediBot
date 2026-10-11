"""LLM second opinion on the safety decision (plan item 6.6). ADD-ONLY, and deliberately NARROW.

Why: the rule detectors are broad but literal. A paraphrased emergency ("my father's lips are turning blue") or
misuse ("something strong so I can get high") can slip past them. A small model reads the message and may only
RAISE one of three flags: emergency, self_harm, misuse. The merge is kernel.apply_second_opinion(), a pure function
that can never clear a flag, lower an action or drop the mandated prompt.

Why only three (measured 2026-10-11, stratified eval, LLM on): with diagnosis / prescribing / dosing / rx_seeking
flags and medicine-word suggestions the model tagged ~38 plain information / substitute questions as "prescribing"
and invented "Remo Tablet" for "varemo 5% Eye sasta" (a false intercept): A2 1.01 -> 1.51%, C1 98.1 -> 97.3%,
health 100 -> 84.6%. The rule detectors already cover those four request types well; the three kept flags are the
ones where a missed paraphrase is dangerous and a false alarm costs little (an emergency card, a misuse refusal).

When it runs: only when the kernel's verdict is plain "allow" (intercepts and refusals are already maximal).
It starts in a thread while the facts are built and has MEDIBOT_SECOND_OPINION_BUDGET seconds (default 1.2). If it
is late, off, over its quota share or returns junk, the kernel's decision stands and the receipt says why.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

from medibot.llm import FAST, get_llm

BUDGET = float(os.environ.get("MEDIBOT_SECOND_OPINION_BUDGET", "1.2"))
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="second-opinion")

FLAGS = ("emergency", "self_harm", "misuse")

SYSTEM = """You are a safety screen for an Indian medicine-information assistant. Messages may be English, Hindi or
Hinglish. You do not answer the user. Return only JSON: {"emergency": bool, "self_harm": bool, "misuse": bool}
- emergency: someone needs urgent medical care right now (breathing trouble, blue lips, chest pain, unconsciousness,
  seizure, heavy bleeding, poisoning, overdose, severe allergic reaction, stroke signs).
- self_harm: wanting to die, hurt oneself or end one's life.
- misuse: wants to get high or intoxicated, or to use a medicine in a harmful, non-medical way.
Questions about prices, cheaper alternatives, stores, side effects, uses, safety or interactions of a medicine are
none of these. Set a flag to true only when the message clearly says so."""


@dataclass
class Opinion:
    status: str                      # used | skipped | timeout | error
    reason: str = ""
    flags: dict = field(default_factory=dict)
    seconds: float = 0.0


def _ask(text: str) -> Opinion:
    t0 = time.time()
    # max_tokens covers the hidden reasoning (up to ~120 tokens measured) + the JSON (~30)
    out = get_llm().chat_json(SYSTEM, text, model=FAST, max_tokens=300, max_wait=BUDGET, reasoning_effort="low")
    if not isinstance(out, dict):
        return Opinion("error", "no valid JSON", seconds=round(time.time() - t0, 3))
    # only the three known flags, only a literal true; anything else the model returns is ignored
    return Opinion("used", flags={k: out.get(k) is True for k in FLAGS}, seconds=round(time.time() - t0, 3))


def start(text: str, kernel_action: str) -> tuple[Future | None, Opinion | None]:
    """Kick off the opinion in the background, or say at once why it is skipped."""
    if kernel_action != "allow":
        return None, Opinion("skipped", f"kernel already decided '{kernel_action}'")
    llm = get_llm()
    ok, why = llm.allow("second_opinion", FAST)
    if not ok:
        return None, Opinion("skipped", why)
    return _POOL.submit(_ask, text), None


def collect(fut: Future | None, early: Opinion | None, started: float) -> Opinion:
    """Wait for what is left of the budget (the facts were built meanwhile)."""
    if fut is None:
        return early or Opinion("skipped", "not started")
    try:
        return fut.result(timeout=max(0.0, BUDGET - (time.time() - started)))
    except TimeoutError:
        return Opinion("timeout", f"no answer within {BUDGET:.1f} s -> kernel decision kept",
                       seconds=round(time.time() - started, 3))
    except Exception as e:  # noqa: BLE001 - optional layer, never breaks a reply
        return Opinion("error", type(e).__name__)
