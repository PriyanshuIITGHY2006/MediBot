"""Bill split planner (Phase 15.1): the cheapest way to buy a whole medicine list across pharmacies. PURE: no
catalog, no network, no model - every input is data, so every plan can be checked by hand (tests/test_billplan.py).

"I need these medicines in these amounts. Where do I order what, so the TOTAL I pay (packs + delivery) is lowest?"
  - packs are whole: 15 tablets from strips of 10 = 2 strips (the overbuy is reported, never hidden)
  - an item may be bought as the asked product or as an IDENTICAL alternative (same Composition ID); the caller
    decides which offers exist - this module never invents one
  - each pharmacy has a delivery fee, a free-delivery threshold and a minimum order (unknown -> 0, flagged)
  - EXACT: item -> pharmacy assignments are searched with branch and bound (see plan()); a missed minimum order
    makes an assignment invalid; delivery fees and free-delivery thresholds are part of the total. Verified against
    a brute force over every assignment on random bills (tests/test_billplan.py).
  - Jan Aushadhi is walk-in (no delivery): reported as its own plan by the caller, never mixed into a delivery cart.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Offer:
    """One way to buy one item at one pharmacy."""
    pharmacy: str
    product_id: str
    name: str
    pack_price: float            # ₹ for one pack
    pack_qty: float              # units (tablets / ml / g) in one pack
    identical_to_asked: bool     # always True: only the asked product or a verified identical alternative
    is_asked_product: bool       # the exact product on the bill (False = an identical alternative)
    url: str | None = None
    source: str = "cached"       # live | cached | snapshot
    observed: str | None = None
    pack_label: str | None = None

    def packs_for(self, units: float) -> int:
        return max(1, math.ceil(units / self.pack_qty - 1e-9))

    def cost_for(self, units: float) -> float:
        return round(self.packs_for(units) * self.pack_price, 2)


@dataclass(frozen=True)
class Terms:
    """A pharmacy's delivery terms. None = unknown (treated as 0 and reported, never guessed)."""
    delivery_fee: float | None = None
    free_above: float | None = None
    min_order: float | None = None
    source: str | None = None
    as_of: str | None = None

    def fee_for(self, subtotal: float) -> float:
        if self.delivery_fee is None:
            return 0.0
        if self.free_above is not None and subtotal >= self.free_above - 1e-9:
            return 0.0
        return self.delivery_fee

    def meets_minimum(self, subtotal: float) -> bool:
        return self.min_order is None or subtotal >= self.min_order - 1e-9


@dataclass
class Item:
    key: str                     # stable id of the bill line
    label: str                   # what the user wrote / confirmed
    units: float                 # tablets / ml / g needed
    offers: list[Offer]          # delivery offers (any pharmacy; asked product + identical alternatives)


@dataclass
class Line:
    item_key: str
    label: str
    offer: Offer
    packs: int
    cost: float
    overbuy_units: float


@dataclass
class Cart:
    pharmacy: str
    lines: list[Line]
    subtotal: float
    delivery_fee: float
    total: float
    fee_known: bool
    min_order: float | None


@dataclass
class Plan:
    carts: list[Cart]
    total: float
    unplaced: list[str] = field(default_factory=list)   # items with no allowed offer in this plan

    @property
    def pharmacies(self) -> list[str]:
        return [c.pharmacy for c in self.carts]

    @property
    def swaps(self) -> int:
        return sum(not ln.offer.is_asked_product for c in self.carts for ln in c.lines)


def _cheapest(item: Item, allowed: set[str]) -> Offer | None:
    """Cheapest offer for this item among the allowed pharmacies; on a tie, the asked product beats an alternative."""
    best = None
    for o in item.offers:
        if o.pharmacy not in allowed or o.pack_qty <= 0 or o.pack_price <= 0:
            continue
        if best is None or (o.cost_for(item.units), not o.is_asked_product) < \
                (best.cost_for(item.units), not best.is_asked_product):
            best = o
    return best


def _rank(p: Plan) -> tuple:
    # most items placed, then lowest total, then fewer pharmacies, then fewer swaps to alternatives
    return len(p.unplaced), p.total, len(p.carts), p.swaps


def _assemble(items: list[Item], choice: list[Offer | None], terms: dict[str, Terms]) -> Plan | None:
    by_ph: dict[str, list[Line]] = {}
    unplaced = []
    for it, o in zip(items, choice):
        if o is None:
            unplaced.append(it.key)
            continue
        packs = o.packs_for(it.units)
        by_ph.setdefault(o.pharmacy, []).append(
            Line(it.key, it.label, o, packs, round(packs * o.pack_price, 2), round(packs * o.pack_qty - it.units, 2)))
    carts = []
    for ph in sorted(by_ph):
        t = terms.get(ph, Terms())
        sub = round(sum(ln.cost for ln in by_ph[ph]), 2)
        if not t.meets_minimum(sub):
            return None
        fee = t.fee_for(sub)
        carts.append(Cart(ph, by_ph[ph], sub, fee, round(sub + fee, 2), t.delivery_fee is not None, t.min_order))
    return Plan(carts, round(sum(c.total for c in carts), 2), unplaced)


def plan(items: list[Item], terms: dict[str, Terms], max_pharmacies: int | None = None) -> Plan | None:
    """The cheapest plan (exact). Searches item -> pharmacy assignments directly, because the greedy "each item at its
    cheapest pharmacy" is NOT optimal once minimum orders and free-delivery thresholds exist: moving one item to a
    dearer pharmacy can lift that cart over a threshold (found by test_planner_matches_brute_force_on_random_bills).
    Per item only the cheapest offer per pharmacy is a candidate (any other offer at the same pharmacy costs more and
    changes nothing else). Branch and bound: a partial assignment whose pack cost alone already exceeds the best
    complete total is cut. Bills are small (<= 25 items x <= 5 pharmacies after the cut, typically 5-10 items)."""
    cands: list[list[Offer]] = []
    for it in items:
        per_ph: dict[str, Offer] = {}
        for o in it.offers:
            if o.pack_qty <= 0 or o.pack_price <= 0:
                continue
            cur = per_ph.get(o.pharmacy)
            if cur is None or (o.cost_for(it.units), not o.is_asked_product) < \
                    (cur.cost_for(it.units), not cur.is_asked_product):
                per_ph[o.pharmacy] = o
        cands.append(sorted(per_ph.values(), key=lambda o: (o.cost_for(it.units), not o.is_asked_product)))
    order = sorted(range(len(items)), key=lambda i: len(cands[i]))      # fewest choices first -> earlier pruning
    placeable = [i for i in order if cands[i]]
    floor = [0.0] * (len(placeable) + 1)                                # cheapest possible cost of the remaining items
    for pos in range(len(placeable) - 1, -1, -1):
        i = placeable[pos]
        floor[pos] = floor[pos + 1] + cands[i][0].cost_for(items[i].units)
    best: list[Plan | None] = [None]
    choice: list[Offer | None] = [None] * len(items)

    def walk(pos: int, spent: float, used: frozenset):
        if best[0] is not None and spent + floor[pos] > best[0].total + 1e-9:
            return
        if pos == len(placeable):
            p = _assemble(items, choice, terms)
            if p is not None and (best[0] is None or _rank(p) < _rank(best[0])):
                best[0] = p
            return
        i = placeable[pos]
        for o in cands[i]:
            nxt = used | {o.pharmacy}
            if max_pharmacies and len(nxt) > max_pharmacies:
                continue
            choice[i] = o
            walk(pos + 1, spent + o.cost_for(items[i].units), nxt)
        choice[i] = None

    walk(0, 0.0, frozenset())
    if best[0] is None and not placeable:
        return Plan([], 0.0, [it.key for it in items]) if items else None
    return best[0]


def single_pharmacy_plans(items: list[Item], terms: dict[str, Terms]) -> list[Plan]:
    """For comparison: everything from one pharmacy (only pharmacies that can supply every item), cheapest first."""
    out = []
    for ph in sorted({o.pharmacy for it in items for o in it.offers}):
        choice = [_cheapest(it, {ph}) for it in items]
        if any(c is None for c in choice):
            continue
        p = _assemble(items, choice, terms)
        if p is not None:
            out.append(p)
    return sorted(out, key=lambda p: p.total)

