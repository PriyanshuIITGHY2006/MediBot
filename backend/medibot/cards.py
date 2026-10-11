"""Reply cards (Phase 11.1): the structured facts of one reply, one dataclass per card type.

Why cards: the web app (Phases 13-14) draws each card as its own component (banner, medicine sheet, substitute
table, price strip ...), and the safety checks can judge and replace ONE card instead of the whole reply.

Rules:
  - A card holds facts from data or fixed texts only. Nothing in a card is written by a model.
  - render() is the card's plain-text form. response_text = safety texts + rendered cards, so with the narrator's
    LLM lead off the text is byte-identical to the reply before cards existed (eval/snapshots/*.jsonl).
  - as_contract() is the JSON the API returns in cards[]: {"type": ..., ...fields, "text": render()}.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from medibot.safety import messages as msg


@dataclass
class Card:
    type = "card"

    def render(self) -> str:  # pragma: no cover - every card overrides this
        raise NotImplementedError

    def as_contract(self) -> dict:
        return {"type": self.type, **asdict(self), "text": self.render()}


# ---------------------------------------------------------------- safety
@dataclass
class InterceptBanner(Card):
    """The fixed safety texts of a turn, in order. When intercepting, lines[0] is the mandated prompt verbatim."""
    lines: list[str]
    intercept: bool = False
    banned: bool = False
    type = "intercept_banner"

    def render(self) -> str:
        return "\n\n".join(self.lines)


@dataclass
class EmergencyCard(Card):
    text: str
    self_harm: bool = False
    type = "emergency"

    def render(self) -> str:
        return self.text


@dataclass
class RefusalCard(Card):
    """Replaces an informational card the output check rejected (never reworded, see output_check.py)."""
    text: str = msg.PRESCRIBING_REFUSAL
    replaced: str = ""                      # type of the card it replaced
    type = "refusal"

    def render(self) -> str:
        return self.text


# ---------------------------------------------------------------- facts
@dataclass
class StoreCard(Card):
    pincode: str | None
    stores: list[dict] = field(default_factory=list)
    asked_for_pincode: bool = False
    type = "stores"

    def render(self) -> str:
        if self.asked_for_pincode:
            return "Please share your 6-digit pincode and I'll find the nearest Jan Aushadhi Kendras."
        if not self.stores:
            return f"I couldn't find a Jan Aushadhi Kendra listed for pincode {self.pincode}."
        return "Jan Aushadhi Kendras near " + str(self.pincode) + ":\n" + "\n".join(
            f"• {k['store_code']}: {k['address']}, {k['district']} {k['pincode']}" for k in self.stores)


@dataclass
class MedicineCard(Card):
    name: str
    product_id: str | None = None
    composition: str | None = None
    category: str | None = None
    generic: bool = False                   # a generic name was typed (no product)
    info_from: str | None = None            # brand typed alone, unverified listing -> info from this verified product
    brand: str | None = None
    type = "medicine"

    def render(self) -> str:
        if self.generic:
            return f"{self.name.title()} is a generic medicine name."
        out = f"{self.name} — contains {self.composition or 'composition not verified'}."
        if self.info_from:
            out += (f"\n{self.name} has no verified composition, so the information below is for {self.info_from}, "
                    f"the {self.brand} product with a verified composition — other {self.brand} products may differ.")
        return out


@dataclass
class InfoCard(Card):
    """A grounded health answer: the text is copied from cited passages (health/answer.py), never generated."""
    text: str
    sections: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    grounded: bool = False
    kind: str = "medicine"                  # medicine | topic
    type = "info"

    def render(self) -> str:
        return self.text


@dataclass
class InteractionCard(Card):
    text: str
    kind: str = "check"                     # check | known_partners
    findings: list[dict] = field(default_factory=list)
    type = "interactions"

    def render(self) -> str:
        return self.text


@dataclass
class SubstituteTable(Card):
    text: str                               # substitutes.render(): the ✓ list + advisory, wording owned there
    target_product_id: str | None = None
    rows: list[dict] = field(default_factory=list)
    note: str | None = None
    type = "substitutes"

    def render(self) -> str:
        return self.text


@dataclass
class PriceStrip(Card):
    """Pharmacy quotes for one product, cheapest first (first 4), each with its freshness label."""
    product_id: str
    quotes: list[dict] = field(default_factory=list)
    type = "prices"

    def render(self) -> str:
        if not self.quotes:
            return "• No recent price on record for this pack."
        lines = []
        for q in self.quotes:
            unit = f", ₹{q['price_per_unit_inr']:.2f}/unit" if q.get("price_per_unit_inr") else ""
            stock = "" if q.get("in_stock") is None else (" · in stock" if q["in_stock"] else " · out of stock")
            lines.append(f"• {q['platform']}: ₹{q['price_inr']:.2f} ({q.get('pack_label') or 'pack'}{unit}) — "
                         f"{q['freshness']}{stock}")
            if q.get("above_nppa_ceiling"):
                c = q["above_nppa_ceiling"]
                lines.append(f"  ⚠ above the government ceiling price of ₹{c['ceiling_per_unit_inr']:.2f}/unit "
                             f"({c['source']})")
        return "\n".join(lines)


@dataclass
class CompareCard(Card):
    names: tuple[str, str]
    same_ingredients: bool
    same_strengths: bool = True
    extra: list[tuple[str, list[str]]] = field(default_factory=list)   # (medicine, ingredients only it has)
    type = "compare"

    def render(self) -> str:
        if self.same_ingredients:
            return (f"{self.names[0]} and {self.names[1]} have the same active ingredients"
                    + ("." if self.same_strengths else " (check the strengths above)."))
        return "\n".join(f"{n} also contains {', '.join(ings)}." for n, ings in self.extra)


@dataclass
class SourcesCard(Card):
    """Numbered citations of every grounded card in the reply ("Sources: [1] ... · [2] ...")."""
    text: str
    citations: list[dict] = field(default_factory=list)
    type = "sources"

    def render(self) -> str:
        return self.text


@dataclass
class Clarify(Card):
    options: list[str]
    type = "clarify"

    def render(self) -> str:
        return "Did you mean: " + " / ".join(self.options[:3]) + "?"


@dataclass
class Fallback(Card):
    text: str = ("I can help with medicine prices, identical cheaper alternatives, general medicine information "
                 "and Jan Aushadhi stores. Which medicine are you asking about?")
    type = "fallback"

    def render(self) -> str:
        return self.text


# ---------------------------------------------------------------- shown by the UI, not part of response_text
@dataclass
class Lead(Card):
    """Optional one-line friendly opening from the narrator (template: none). Shown before the fact cards."""
    text: str
    source: str = "template"                # template | llm
    type = "lead"

    def render(self) -> str:
        return self.text


@dataclass
class Disclaimer(Card):
    text: str
    full: bool = False
    requires_acknowledgement: bool = False
    type = "disclaimer"

    def render(self) -> str:
        return self.text


@dataclass
class QuickReplies(Card):
    """Fixed follow-up buttons chosen by code from the turn's facts, never by a model."""
    options: list[str]
    type = "quick_replies"

    def render(self) -> str:
        return " · ".join(self.options)


SAFETY_CARDS = (InterceptBanner, EmergencyCard, RefusalCard)
UI_ONLY = (Disclaimer, QuickReplies)


def facts_text(cards: list[Card]) -> str | None:
    """The informational block exactly as before Phase 11: fact cards joined by single newlines."""
    parts = [c.render() for c in cards if not isinstance(c, SAFETY_CARDS + UI_ONLY + (Lead, Clarify, Fallback))]
    return "\n".join(p for p in parts if p) or None


def quick_replies(cards: list[Card], intercept: bool) -> QuickReplies | None:
    """Follow-ups that make sense after these facts. Fixed texts; the kernel still judges whatever is typed next."""
    types = {c.type for c in cards}
    if "emergency" in types or "refusal" in types:
        return None
    has_med = any(isinstance(c, MedicineCard) and not c.generic for c in cards)
    opts = []
    if has_med and "substitutes" not in types:
        opts.append("Cheaper identical options")
    if has_med and "prices" not in types:
        opts.append("Compare prices")
    if has_med and "info" not in types:
        opts.append("Side effects")
    if has_med or "substitutes" in types:
        opts.append("Nearest Jan Aushadhi")
    return QuickReplies(opts[:4]) if opts else None
