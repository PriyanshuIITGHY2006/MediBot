"""Hindi answers (Phase 15.4). The reply is built in English as always (kernel, cards, output check), then the
cards the UI shows are translated for display:

  - fixed safety texts -> the hand-written Hindi in safety/messages_hi.py (never a model)
  - the mandated prompt stays in English, verbatim, with the Hindi line added under it
  - every other line -> one batched call to a cheap model (MEDIBOT_TRANSLATE_MODEL), cached
  - a translated line must keep every number of the English line (prices, strengths, helplines, citation marks);
    otherwise that line stays in English. A translation can't add, drop or change a dose, a price or a number.
  - LLM off / slow / failed -> the English cards are returned unchanged, with "language": "en"

response_text, safety_guard and every other field stay English (the problem statement's schema). Medicine names,
ingredient names and pharmacy names are kept in Latin script.
"""
from __future__ import annotations

import copy
import json
import os
import re
from collections import Counter

from medibot.llm import get_llm
from medibot.safety import messages as en
from medibot.safety import messages_hi as hi

MODEL = os.environ.get("MEDIBOT_TRANSLATE_MODEL", "cline:google/gemini-3.5-flash-lite")
SKIP_TYPES = {"quick_replies", "prices"}            # quick replies are sent back as messages; prices are numbers

SYSTEM = """You translate an Indian medicine-information assistant's answer from English into simple, natural Hindi
(Devanagari) for ordinary readers. Input: JSON {"lines": [string]}. Output: JSON {"lines": [string]} - the same
number of lines, same order, one translation per line.
Rules:
- Translate faithfully. Do not add, remove, soften or strengthen anything. No advice of your own.
- Keep EVERY number exactly as written (prices like ₹24.53, strengths like 650 mg, phone numbers, [1] citation marks).
- Keep medicine brand names, ingredient names, pharmacy names, units (mg, ml) and URLs in Latin script as written.
- Keep leading "• " bullets and similar markers.
- Common words people use in Hindi may stay English (tablet, prescription, online)."""

_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(s: str) -> Counter:
    return Counter(n.replace(",", "") for n in _NUM.findall(s))


def _faithful(src: str, out: str) -> bool:
    return bool(out.strip()) and _numbers(src) == _numbers(out) and len(out) < 4 * len(src) + 40


def _strings(card: dict):
    """(getter, setter) pairs for every displayed string of a card."""
    if card.get("type") in SKIP_TYPES:
        return
    for k in ("text", "note"):
        if isinstance(card.get(k), str) and card[k]:
            yield card, k
    if isinstance(card.get("lines"), list):
        for i in range(len(card["lines"])):
            yield card["lines"], i
    for f in card.get("findings") or []:
        if isinstance(f.get("text"), str):
            yield f, "text"


def translate_cards(cards: list[dict], lang: str) -> tuple[list[dict], dict]:
    """English cards -> cards for display in `lang`. Returns (cards, receipt)."""
    if lang != "hi":
        return cards, {"language": "en"}
    out = copy.deepcopy(cards)
    slots = list(s for c in out for s in _strings(c))
    todo: list[str] = []
    for obj, k in slots:
        for line in obj[k].split("\n"):
            if line.strip() and not hi.fixed(line) and re.search(r"[A-Za-z]{2}", line) and line not in todo:
                todo.append(line)
    done: dict[str, str] = {}
    kept_en = 0
    if todo:
        r = get_llm().chat_json(SYSTEM, json.dumps({"lines": todo}, ensure_ascii=False), model=MODEL,
                                max_tokens=min(4000, 200 + sum(len(t) for t in todo) * 2), max_wait=1.0, timeout=12.0)
        got = r.get("lines") if isinstance(r, dict) else None
        if not isinstance(got, list) or len(got) != len(todo):
            return cards, {"language": "en", "reason": "translation unavailable"}
        for src, dst in zip(todo, got):
            if isinstance(dst, str) and _faithful(src, dst):
                done[src] = dst
            else:
                kept_en += 1

    def tr(line: str) -> str:
        return hi.fixed(line) or done.get(line, line)

    for obj, k in slots:
        obj[k] = "\n".join(tr(line) for line in obj[k].split("\n"))
    # the mandated prompt: English verbatim first, Hindi under it
    for c in out:
        if c.get("type") == "intercept_banner" and isinstance(c.get("lines"), list):
            c["lines"] = [x for ln in c["lines"] for x in ([en.MANDATED_PROMPT, ln] if ln == hi.MANDATED_PROMPT else [ln])]
    return out, {"language": "hi", "lines": len(todo), "kept_english": kept_en}
