"""Narrator (Phase 11.2): the one-line friendly opening ("lead") of a reply. Template by default; LLM optional.

What the LLM may do: write ONE short opening line for price / substitute / store / compare turns, from a small facts
JSON (names, prices, savings, store count). It never sees the safety texts, never writes health facts (InfoCards
stay copied from cited sources) and its line is NOT part of response_text: it is a separate Lead card the UI shows
above the fact cards. So the scored reply is identical with the LLM on or off.

Every draft must pass, else the template (no lead) is used and the reason goes in the receipt:
  1. output_check (no diagnosis / dosing / prescribing / "no prescription needed")
  2. every number in the draft appears in the facts (no invented prices or percentages)
  3. every medicine find_mentions() sees in the draft is one of the turn's medicines (no invented medicines)
  4. no prescription / schedule wording (that is the Safety Kernel's job, verbatim)
  5. at most MAX_WORDS words
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from medibot import cards as C
from medibot.llm import STRONG, get_llm
from medibot.safety.output_check import violations

MAX_WORDS = 45
INTENTS = {"price", "substitute", "store", "compare"}
RX_WORDS = re.compile(r"prescri|schedule|\brx\b|doctor'?s? (note|slip)|parchi|legal|banned|prohibit|controlled", re.I)
NUM = re.compile(r"\d+(?:[.,]\d+)?")

SYSTEM = """You write ONE short, warm opening line (max 30 words) for a reply from an Indian medicine-price assistant.
You get JSON facts. Summarise the most useful fact (cheapest price, biggest saving, or how many stores) in plain
words. Reply in Hinglish if "hinglish" is true, else English. Use only numbers and names that are in the facts.
Never give medical advice, doses, or say whether a prescription is needed. Return only JSON: {"lead": "..."}"""


@dataclass
class Narration:
    lead: C.Lead | None
    source: str                      # template | llm
    reason: str = ""                 # why the LLM draft was not used


def facts_json(cards: list[C.Card], intents: list[str], user_text: str) -> dict:
    f: dict = {"hinglish": bool(re.search(r"\b(kya|hai|kitne|kitna|sasta|sasti|milega|batao|wala|mein|ka|ki)\b",
                                          user_text.lower())), "medicines": [], "intents": intents}
    for c in cards:
        if isinstance(c, C.MedicineCard) and not c.generic:
            f["medicines"].append(c.name)
        elif isinstance(c, C.PriceStrip) and c.quotes:
            f["prices"] = [{"platform": q["platform"], "price_inr": q["price_inr"],
                            "per_unit_inr": q.get("price_per_unit_inr"), "when": q["freshness"]} for q in c.quotes]
        elif isinstance(c, C.SubstituteTable) and c.rows:
            f["alternatives"] = [{"name": r["brand_name"], "per_unit_inr": r["price_per_unit_inr"],
                                  "saving_pct": r["savings_percentage"]} for r in c.rows[:3]]
        elif isinstance(c, C.StoreCard) and c.stores:
            f["stores"] = {"pincode": c.pincode, "count": len(c.stores)}
    return f


def numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip("0").rstrip(".") if "." in n else n.replace(",", "") for n in NUM.findall(text)}


def check(draft: str, facts: dict, catalog=None) -> str:
    """'' if the draft may be shown, else the reason it was rejected."""
    if not draft or not draft.strip():
        return "empty draft"
    if len(draft.split()) > MAX_WORDS:
        return f"too long ({len(draft.split())} words)"
    if violations(draft):
        return "output check: " + ", ".join(violations(draft))
    if RX_WORDS.search(draft):
        return "prescription / schedule wording"
    allowed = numbers(json.dumps(facts))
    for n in numbers(draft):
        if n not in allowed:
            return f"number not in facts: {n}"
    if catalog is not None:
        bad = invented_medicine(draft, facts, catalog)
        if bad:
            return f"medicine not in facts: {bad}"
    return ""


def invented_medicine(draft: str, facts: dict, catalog) -> str | None:
    """A medicine the draft names that is not one of the turn's medicines, or None.
    Words that can't be a medicine name are ignored, with the same lists the resolver uses for user messages:
    Hinglish fillers ("kar", "tak"), English stop words and contractions ("couldnt"), numbers and form words, and
    everyday English words (the catalog has brands called "Total" and "Right")."""
    from medibot.mentions import FORM_WORDS, HINGLISH, NUMBER, STOP, _common, find_mentions, tokenize
    allowed = facts.get("medicines", []) + [a["name"] for a in facts.get("alternatives", [])]
    names = " ".join(allowed).lower()
    known = set(tokenize(names)) | {"netmeds", "apollo", "1mg", "pharmeasy", "truemeds", "jan", "aushadhi"}

    def can_be_name(w: str) -> bool:
        return not (w in STOP or w in HINGLISH or w in NARRATOR_FILLERS or NUMBER.match(w) or FORM_WORDS.match(w)
                    or _common(w))
    for m in find_mentions(draft, catalog):
        words = [w for w in tokenize(m.text) if can_be_name(w)]
        if not words or m.name.lower() in names or all(w in known for w in words):
            continue
        # a single filler word that only fuzzily resembles a brand ("sakte" ~ some brand) is not a medicine claim:
        # an invented medicine is either confidently resolved or more than one name-like word
        if not m.confident or (len(words) == 1 and m.kind == "product" and m.confidence < 95
                               and words[0] not in m.name.lower()):
            continue
        return m.text
    return None


# Hinglish words the model uses in leads that the user-side HINGLISH list doesn't contain (measured: kar, tak).
# Verb forms of "sakna / jaana / hona / milna / karna" are listed so a filler never reaches the brand resolver.
NARRATOR_FILLERS = set("""kar karo karen kare karke karna karein tak par pe sirf abhi bhi sabse sasta saste sasti mil
milega milegi milenge milta milti jayega jayegi jaega jaegi jaata jaati sakte sakti sakta sako sakoge ho hoga hogi
honge hua hui hue rupaye rupees rs per unit liye wahan yahan""".split())


def narrate(cards: list[C.Card], intents: list[str], user_text: str, *, safety_turn: bool, catalog=None) -> Narration:
    """Template = no lead (response_text is the cards). The LLM lead is optional and only on plain fact turns."""
    if safety_turn:
        return Narration(None, "template", "safety turn: fixed texts only")
    if not INTENTS & set(intents) or not any(isinstance(c, (C.PriceStrip, C.SubstituteTable, C.StoreCard, C.CompareCard))
                                             for c in cards):
        return Narration(None, "template", "no price / substitute / store facts")
    llm = get_llm()
    ok, why = llm.allow("narrator", STRONG)
    if not ok:
        return Narration(None, "template", why)
    facts = facts_json(cards, intents, user_text)
    out = llm.chat_json(SYSTEM, json.dumps(facts, ensure_ascii=False), model=STRONG, max_tokens=300, max_wait=1.5,
                        reasoning_effort="low")
    draft = (out or {}).get("lead") if isinstance(out, dict) else None
    if not isinstance(draft, str):
        return Narration(None, "template", "no LLM answer")
    bad = check(draft.strip(), facts, catalog)
    if bad:
        return Narration(None, "template", bad)
    return Narration(C.Lead(draft.strip(), "llm"), "llm")
