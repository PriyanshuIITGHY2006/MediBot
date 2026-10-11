"""Conversation memory and reference resolution (Phase 7). Deterministic.

Working set per session:
  focus       the medicine(s) the conversation is about
  last_list   products just shown to the user (substitutes / price list), for "the second one"
  pending     an open question the bot asked ("need_pincode", "which_variant")
References handled: "it / this / iska", "the second one", "the cheapest one", "the 500 one" / "500 wala",
"the gel one" / "syrup wala", "and dolo 650?" (new focus, previous intent carried over).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from medibot.catalog import Catalog
from medibot.mentions import Mention
from medibot.understanding import Request

FAMILY = {f: "oral_liquid" for f in ("syrup", "dry_syrup", "suspension", "solution", "oral_drops", "emulsion")}
FAMILY.update({f: "oral_solid" for f in ("tablet", "tablet_dispersible", "tablet_mouth_dissolving", "tablet_chewable",
                                         "tablet_effervescent", "capsule", "capsule_softgel", "granules", "powder")})
FAMILY.update({f: "topical" for f in ("cream", "ointment", "gel", "lotion")})
WORD_TO_FORMS = {
    "gel": {"gel", "suspension"}, "syrup": {"syrup", "suspension", "solution"}, "suspension": {"suspension", "syrup"},
    "liquid": {"syrup", "suspension", "solution"}, "tablet": {"tablet", "tablet_dispersible", "tablet_chewable"},
    "tab": {"tablet"}, "capsule": {"capsule", "capsule_softgel"}, "cream": {"cream"}, "ointment": {"ointment"},
    "drop": {"eye_drops", "oral_drops", "ear_drops", "nasal_drops"}, "drops": {"eye_drops", "oral_drops", "ear_drops", "nasal_drops"},
    "injection": {"injection"}, "spray": {"nasal_spray", "spray"}, "lotion": {"lotion"}, "powder": {"powder", "granules"},
    "sachet": {"granules", "powder"}, "chewable": {"tablet_chewable"},
}


@dataclass
class Session:
    acknowledged: bool = False
    focus: list[Mention] = field(default_factory=list)
    last_list: list[str] = field(default_factory=list)
    last_intents: list[str] = field(default_factory=list)
    pending: str | None = None
    turns: int = 0
    # disclaimer policy (Phase 11.4): when the full text was acknowledged, and which text (hash) was shown
    acknowledged_at: str | None = None
    disclaimer_hash: str | None = None
    medical_turns: int = 0
    full_shown_for: set = field(default_factory=set)   # "intercept" / "health": first time each gets the full text


def _mention_for(catalog: Catalog, product_id: str, text: str) -> Mention:
    p = catalog.products[product_id]
    return Mention("product", product_id, p.name, (0, 0), text, 100.0)


def variant_of(catalog: Catalog, focus: Mention, strength: str | None, form_word: str | None) -> str | None:
    """Same brand, different strength or form: "Dolo 650" + "the 500 one" -> Dolo 500 Tablet."""
    df = catalog.index.df
    rows = df[df["canonical_id"] == focus.ref]
    if rows.empty:
        return None
    stem = rows["stem"].iloc[0]
    base = catalog.products.get(focus.ref)
    cand = df[df["stem"] == stem]
    if strength:
        cand = cand[cand["numbers"].map(lambda ns: strength in set(ns))]
    if form_word:
        forms = WORD_TO_FORMS.get(form_word.rstrip("s") if form_word not in WORD_TO_FORMS else form_word, {form_word})
        by_name = cand["name"].str.lower().str.contains(rf"\b{re.escape(form_word)}", regex=True)
        cand = cand[cand["form"].isin(forms) | by_name]
    elif base is not None:  # strength change keeps the form family ("the 500 one" of a tablet is a tablet)
        fam = FAMILY.get(base.form)
        same = cand[cand["form"].map(lambda f: FAMILY.get(f) == fam)] if fam else cand
        cand = same if len(same) else cand
    if cand.empty:
        return None
    cand = cand.assign(_extra=cand["search_text"].str.split().str.len())
    best = cand.sort_values(["popularity", "_extra"], ascending=[False, True]).iloc[0]
    return best["canonical_id"]


def resolve(req: Request, mentions_now: list[Mention], s: Session, catalog: Catalog) -> tuple[list[Mention], list[str]]:
    """Mentions the turn is about + receipt notes."""
    notes: list[str] = []
    if mentions_now:
        if (req.strength or req.form) and len(mentions_now) == 1 and mentions_now[0].brand_only:
            v = variant_of(catalog, mentions_now[0], req.strength, req.form)
            if v:
                notes.append(f"variant of {mentions_now[0].name}: {catalog.products[v].name}")
                return [_mention_for(catalog, v, req.text)], notes
        return mentions_now, notes
    if req.ordinal is not None and s.last_list:
        idx = req.ordinal - 1 if req.ordinal > 0 else len(s.last_list) - 1
        if 0 <= idx < len(s.last_list):
            notes.append(f"'{req.text}' -> item {idx + 1} of the last list")
            if "substitute" in req.intents and not re.search(r"cheaper|alternative|substitute|sasta", req.text.lower()):
                req.intents = [i for i in req.intents if i != "substitute"] or ["price"]
            return [_mention_for(catalog, s.last_list[idx], req.text)], notes
    if req.superlative == "cheapest" and s.last_list:
        # "where is the cheapest one available?" -> the top of the list we just showed; the user now wants its price
        notes.append("'the cheapest one' -> first item of the last (price-sorted) list")
        req.intents = ["price"]
        return [_mention_for(catalog, s.last_list[0], req.text)], notes
    if (req.strength or req.form) and s.focus and s.focus[0].kind == "product":
        v = variant_of(catalog, s.focus[0], req.strength, req.form)
        if v:
            notes.append(f"'{req.text}' -> {catalog.products[v].name} (variant of {s.focus[0].name})")
            return [_mention_for(catalog, v, req.text)], notes
    if s.focus:
        notes.append("no medicine named -> continuing with " + ", ".join(m.name for m in s.focus))
        return list(s.focus), notes
    return [], notes


def update(s: Session, req: Request, used: list[Mention], shown: list[str] | None = None) -> None:
    s.turns += 1
    if used:
        s.focus = used
    if shown is not None:
        s.last_list = shown
    s.last_intents = req.intents
