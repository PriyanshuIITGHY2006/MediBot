"""Bill split (Phase 15.1): a medicine list -> where to order what, so the total paid is lowest. Glue between the
catalog / live prices and the pure planner (billplan.py).

Per bill line:
  - the asked product is resolved (a product_id from the picker, else the same mention finder as the chat)
  - banned products get no plan; prescription medicines carry the mandated prompt
  - offers = every pharmacy quote with a known pack size that is not marked out of stock, for the asked product
    and (when allowed) its verified identical alternatives (same Composition ID; substitutes.py decides)
  - Jan Aushadhi is walk-in: priced as its own plan, never mixed into a delivery cart
Delivery terms come from data/reference/pharmacy_terms.csv; a blank value is unknown and reported, never guessed.
"""
from __future__ import annotations

import csv
import math
import re
from functools import lru_cache

from medibot.billplan import Item, Offer, Plan, Terms, plan, single_pharmacy_plans
from medibot.mentions import find_mentions
from medibot.safety import messages as msg
from medibot.safety.kernel import decide
from medibot.substitutes import ADVISORY, ROOT, find_substitutes, refresh_with_live

TERMS_CSV = ROOT / "data/reference/pharmacy_terms.csv"


@lru_cache(maxsize=1)
def pharmacy_terms() -> dict[str, Terms]:
    def num(v: str) -> float | None:
        v = (v or "").strip()
        return float(v) if v else None
    out = {}
    if TERMS_CSV.exists():
        with open(TERMS_CSV, newline="") as f:
            for r in csv.DictReader(f):
                out[r["platform"]] = Terms(num(r["delivery_fee"]), num(r["free_above"]), num(r["min_order"]),
                                           r.get("source") or None, r.get("as_of") or None)
    return out


def _offers(quotes: list[dict], product_id: str, name: str, asked: bool) -> list[Offer]:
    out = []
    for q in quotes:
        if q.get("in_stock") is False or not q.get("pack_quantity") or not q.get("price_inr"):
            continue
        out.append(Offer(q["platform"], product_id, name, float(q["price_inr"]), float(q["pack_quantity"]), True, asked,
                         q.get("url"), q.get("source") or "cached", q.get("observed"), q.get("pack_label")))
    return out


def _resolve(bot, name: str, product_id: str | None):
    cat = bot.catalog
    if product_id and product_id in cat.products:
        p = cat.products[product_id]
        dec = decide(p.name, cat)
        mv = next((m for m in dec.medicines if m.product.product_id == p.product_id), None)
        return p, dec, mv, True
    ms = [m for m in find_mentions(name, cat) if m.kind == "product"]
    if not ms:
        return None, None, None, False
    dec = decide(name, cat, mentions=ms[:1])
    return dec.medicines[0].product, dec, dec.medicines[0], ms[0].confident


def _plan_json(p: Plan | None, terms: dict[str, Terms]) -> dict | None:
    if p is None:
        return None
    return {
        "total_inr": p.total, "pharmacies": p.pharmacies, "swaps": p.swaps, "unplaced": p.unplaced,
        "carts": [{
            "platform": c.pharmacy, "subtotal_inr": c.subtotal, "delivery_fee_inr": c.delivery_fee,
            "total_inr": c.total, "delivery_fee_known": c.fee_known, "min_order_inr": c.min_order,
            "free_delivery_above_inr": terms.get(c.pharmacy, Terms()).free_above,
            "lines": [{"item_key": ln.item_key, "label": ln.label, "product_id": ln.offer.product_id,
                       "name": ln.offer.name, "is_asked_product": ln.offer.is_asked_product, "packs": ln.packs,
                       "pack_price_inr": ln.offer.pack_price, "pack_label": ln.offer.pack_label,
                       "pack_quantity": ln.offer.pack_qty, "cost_inr": ln.cost, "overbuy_units": ln.overbuy_units,
                       "url": ln.offer.url, "source": ln.offer.source, "observed": ln.offer.observed}
                      for ln in c.lines],
        } for c in p.carts],
    }


def split_bill(bot, lines: list[dict], allow_alternatives: bool = True, max_pharmacies: int | None = None) -> dict:
    """lines: [{name, quantity (units), product_id?}] -> resolved items + the cheapest plans."""
    from medibot.assistant import price_book
    cat, terms = bot.catalog, pharmacy_terms()
    items: list[Item] = []
    asked_items: list[Item] = []
    rows: list[dict] = []
    ja_total, ja_lines, ja_complete = 0.0, [], True
    for k, ln in enumerate(lines):
        key = f"i{k}"
        p, dec, mv, confident = _resolve(bot, ln["name"], ln.get("product_id"))
        row = {"key": key, "input": ln["name"], "quantity": ln["quantity"]}
        if p is None:
            rows.append(dict(row, status="not_recognised"))
            continue
        row.update(product_id=p.product_id, name=p.name, composition=p.composition, form=p.form,
                   requires_prescription=p.requires_prescription, confident=confident,
                   mandated_prompt=msg.MANDATED_PROMPT if (dec and dec.intercept) or p.requires_prescription else None)
        if p.category == "banned" or (mv and mv.banned):
            rows.append(dict(row, status="banned", note=msg.banned_notice((mv.legal_ref if mv else "").split(" | ")[0] or "Section 26A")))
            continue
        res = refresh_with_live(find_substitutes(p, cat, price_book()), cat, bot.prices)
        asked = _offers(res.target_quotes or [], p.product_id, p.name, True)
        alts: list[Offer] = []
        ja = None
        for s in res.substitutes:
            if s.tier == "jan_aushadhi":
                ja = ja or s
            elif allow_alternatives:
                alts += _offers(s.quotes, s.product_id, s.brand_name, False)
        units = float(ln["quantity"])
        items.append(Item(key, p.name, units, asked + alts))
        asked_items.append(Item(key, p.name, units, asked))
        # Jan Aushadhi (walk-in) for this line: whole packs at MRP
        if ja and ja.quotes and ja.price_per_unit_inr:
            q = ja.quotes[0]
            per_pack = max(1, round(q["price_inr"] / ja.price_per_unit_inr))
            packs = max(1, math.ceil(units / per_pack - 1e-9))
            cost = round(packs * q["price_inr"], 2)
            ja_total += cost
            ja_lines.append({"item_key": key, "label": p.name, "name": ja.brand_name, "packs": packs,
                             "pack_label": q.get("pack_label"), "pack_price_inr": q["price_inr"], "cost_inr": cost})
        else:
            ja_complete = False
        row.update(status="ok" if asked or alts else "no_price", offers=len(asked) + len(alts),
                   pharmacies=sorted({o.pharmacy for o in asked + alts}), has_alternatives=bool(alts),
                   alternatives_note=res.note)
        rows.append(row)

    best = plan(items, terms, max_pharmacies) if items else None
    as_asked = plan(asked_items, terms, max_pharmacies) if asked_items else None
    singles = single_pharmacy_plans(items, terms)
    one_stop = singles[0] if singles else None
    used = {c.pharmacy for p in (best, as_asked, one_stop) if p for c in p.carts}
    return {
        "items": rows,
        "best": _plan_json(best, terms),
        "as_asked": _plan_json(as_asked, terms),
        "one_stop": _plan_json(one_stop, terms),
        "single_pharmacy": [{"platform": s.carts[0].pharmacy, "total_inr": s.total} for s in singles if s.carts],
        "jan_aushadhi": {"total_inr": round(ja_total, 2), "lines": ja_lines, "complete": ja_complete and bool(ja_lines),
                         "note": "Walk-in at a Jan Aushadhi Kendra, at MRP. No delivery."} if ja_lines else None,
        "savings_inr": round(as_asked.total - best.total, 2) if best and as_asked and not as_asked.unplaced
        and not best.unplaced else None,
        "delivery_terms": {ph: {"delivery_fee_inr": t.delivery_fee, "free_above_inr": t.free_above,
                                "min_order_inr": t.min_order, "source": t.source, "as_of": t.as_of}
                           for ph, t in terms.items() if ph in used},
        "unknown_delivery_terms": sorted(ph for ph in used if terms.get(ph, Terms()).delivery_fee is None),
        "advisory": ADVISORY,
        "disclaimer": msg.DISCLAIMER,
    }


_QTY = re.compile(r"(?:[x×*]\s*(\d{1,4})|(\d{1,4})\s*(?:tabs?|tablets?|caps?(?:ules)?|ml|nos?|units?|pcs?)\b)\s*$", re.I)


def parse_list(text: str) -> list[dict]:
    """A pasted list -> lines. "Dolo 650 x 30", "Pan 40 - 15 tabs", "Augmentin 625 Duo" (quantity unknown -> 10)."""
    out = []
    for raw in re.split(r"[\n;]+|,(?!\d)", text):
        s = raw.strip(" -•*\t")
        if len(s) < 2:
            continue
        m = _QTY.search(s)
        qty = int(m.group(1) or m.group(2)) if m else None
        name = s[:m.start()].strip(" -:,") if m else s
        if len(name) >= 2:
            out.append({"name": name[:120], "quantity": max(1, min(qty or 10, 1000)), "quantity_given": qty is not None})
    return out[:25]
