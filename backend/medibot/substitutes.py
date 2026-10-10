"""Substitute engine (Phase 8): identical-composition alternatives, cheapest first, plus the Jan Aushadhi generic.

Identity is structural: a substitute shares the target's Composition ID (same ingredients, strengths,
dosage form and release type). Nothing here is fuzzy and nothing comes from an LLM.

Excluded: discontinued products, alias listings (same product listed twice), the target itself,
outlier prices (< 0.2x the group median), and listings whose name suggests an ingredient the composition
lacks (e.g. "Allerhin D Plus" listed as fexofenadine only) - those are data errors we refuse to recommend.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from statistics import median

import pandas as pd

from medibot.catalog import Catalog, Product

ROOT = Path(__file__).resolve().parents[2]
ADVISORY = ("Active composition is identical (same ingredients, strengths and form). Please confirm the switch with "
            "your doctor or pharmacist before changing medicines.")
# brand suffixes that usually mean an extra ingredient (D = domperidone, M = montelukast, H = hydrochlorothiazide ...)
COMBO_SUFFIX = re.compile(r"\b(d|m|h|am|ls|sp|mr|dsr|th|p|az|cv|cl|gm|lb|plus|forte|xt|ct|trio|duo)\b", re.I)


@dataclass
class Substitute:
    product_id: str
    brand_name: str
    manufacturer: str | None
    composition: str
    composition_id: str
    price_per_unit_inr: float | None
    pack_unit: str | None
    savings_percentage: float | None
    quotes: list[dict]
    tier: str                      # "brand" | "jan_aushadhi"

    def as_contract(self) -> dict:
        return {"product_id": self.product_id, "brand_name": self.brand_name, "manufacturer": self.manufacturer,
                "active_composition": self.composition, "composition_id": self.composition_id,
                "composition_identically_verified": True, "price_per_unit_inr": self.price_per_unit_inr,
                "pack_unit": self.pack_unit, "savings_percentage": self.savings_percentage,
                "user_advisory": ADVISORY, "partner_price_comparison": self.quotes, "tier": self.tier}


@dataclass
class SubstituteResult:
    target: Product
    target_price_per_unit: float | None
    pack_unit: str | None
    substitutes: list[Substitute]
    note: str | None = None        # "already the cheapest", "no identical alternative", ...
    target_quotes: list | None = None


@lru_cache(maxsize=1)
def jan_aushadhi_by_composition() -> dict[str, list[dict]]:
    ja = pd.read_parquet(ROOT / "data/processed/jan_aushadhi.parquet")
    ja = ja[ja["usable"] & ja["price_per_unit_inr"].notna() & (ja["mrp_inr"] > 0)]
    out: dict[str, list[dict]] = {}
    for r in ja.itertuples():
        out.setdefault(r.composition_id, []).append({
            "drug_code": int(r.drug_code), "generic_name": r.generic_name, "mrp_inr": float(r.mrp_inr),
            "unit_size": r.unit_size, "price_per_unit_inr": round(float(r.price_per_unit_inr), 2), "pack_unit": r.pack_unit})
    return out


def _unit_price(quotes: list[dict], unit: str | None) -> float | None:
    vals = [q["price_per_unit_inr"] for q in quotes
            if q.get("price_per_unit_inr") and (unit is None or q.get("pack_unit") == unit)]
    return round(min(vals), 2) if vals else None


def _main_unit(quotes: list[dict]) -> str | None:
    units = [q.get("pack_unit") for q in quotes if q.get("pack_unit")]
    return max(set(units), key=units.count) if units else None


def _name_mismatch(target: Product, cand: Product) -> bool:
    """A combo-style suffix the target doesn't have, on a single-ingredient product -> likely a data error."""
    if len(cand.ingredients) > 1:
        return False
    extra = set(m.lower() for m in COMBO_SUFFIX.findall(cand.name)) - set(m.lower() for m in COMBO_SUFFIX.findall(target.name))
    return bool(extra)


def find_substitutes(target: Product, catalog: Catalog, price_book: dict[str, list[dict]], limit: int = 5) -> SubstituteResult:
    if target.composition_id is None or target.category == "banned":
        why = "banned product: no alternatives are suggested" if target.category == "banned" else \
            "composition not verified for this product, so no identical alternative can be confirmed"
        return SubstituteResult(target, None, None, [], why)

    t_quotes = price_book.get(target.product_id, [])
    unit = _main_unit(t_quotes)
    t_ppu = _unit_price(t_quotes, unit)

    cands: list[Substitute] = []
    for pid in catalog.composition_members.get(target.composition_id, []):
        if pid == target.product_id:
            continue
        p = catalog.products.get(pid)
        if p is None or p.discontinued or _name_mismatch(target, p):
            continue
        quotes = sorted(price_book.get(pid, []), key=lambda q: q["price_inr"])
        u = unit or _main_unit(quotes)
        ppu = _unit_price(quotes, u)
        if ppu is None:
            continue
        cands.append(Substitute(pid, p.name, p.manufacturer, p.composition or "", target.composition_id, ppu, u,
                                None, quotes[:4], "brand"))

    # outlier unit prices (bad records, wrong pack) never become "the cheapest"
    if len(cands) >= 5:
        med = median(c.price_per_unit_inr for c in cands)
        cands = [c for c in cands if c.price_per_unit_inr >= 0.2 * med]
    # one listing per maker (the same company often lists a product several times)
    best_by_maker: dict[str, Substitute] = {}
    for c in sorted(cands, key=lambda c: c.price_per_unit_inr):
        key = (c.manufacturer or c.brand_name).lower().split()[0]
        best_by_maker.setdefault(key, c)
    ranked = sorted(best_by_maker.values(), key=lambda c: c.price_per_unit_inr)

    for ja in jan_aushadhi_by_composition().get(target.composition_id, []):
        if unit is None or ja["pack_unit"] == unit:
            ranked.append(Substitute(f"ja_{ja['drug_code']}", f"Jan Aushadhi: {ja['generic_name']}",
                                     "PMBI (Govt. of India)", target.composition or "", target.composition_id,
                                     ja["price_per_unit_inr"], ja["pack_unit"], None,
                                     [{"platform": "jan_aushadhi", "price_inr": ja["mrp_inr"], "pack_label": ja["unit_size"],
                                       "price_per_unit_inr": ja["price_per_unit_inr"], "observed": "2026-10",
                                       "delivery_eta": "at Jan Aushadhi Kendras"}], "jan_aushadhi"))
    ranked.sort(key=lambda c: c.price_per_unit_inr)

    if t_ppu:
        for c in ranked:
            c.savings_percentage = round(100 * (1 - c.price_per_unit_inr / t_ppu), 1)
        cheaper = [c for c in ranked if c.savings_percentage and c.savings_percentage > 0]
        note = None if cheaper else "this is already the cheapest identical option we know of"
        shown = cheaper[:limit] if cheaper else ranked[:2]
    else:
        note = "no recent price for this pack, so savings can't be calculated"
        shown = ranked[:limit]
    # always keep the Jan Aushadhi option visible if it exists and is cheaper
    ja_opts = [c for c in ranked if c.tier == "jan_aushadhi" and c not in shown and (c.savings_percentage or 0) > 0]
    if ja_opts:
        shown = shown[: limit - 1] + ja_opts[:1]
        shown.sort(key=lambda c: c.price_per_unit_inr)
    if not ranked:
        note = "no identical alternative with a known price"
    return SubstituteResult(target, t_ppu, unit, shown, note)


def render(res: SubstituteResult) -> str:
    unit = {"unit": "tablet/capsule", "ml": "ml", "g": "g"}.get(res.pack_unit or "", "unit")
    lines = []
    head = f"Identical alternatives to {res.target.name} ({res.target.composition})"
    if res.target_price_per_unit:
        head += f" — current ₹{res.target_price_per_unit:.2f} per {unit}"
    lines.append(head + ":")
    for c in res.substitutes:
        save = f" — save {c.savings_percentage:.0f}%" if c.savings_percentage and c.savings_percentage > 0 else ""
        who = "" if c.tier == "jan_aushadhi" else f" ({c.manufacturer})" if c.manufacturer else ""
        lines.append(f"• ✓ {c.brand_name}{who}: ₹{c.price_per_unit_inr:.2f} per {unit}{save}")
    if res.note:
        lines.append(f"Note: {res.note}.")
    if res.substitutes:
        lines.append(ADVISORY)
    return "\n".join(lines)


def refresh_with_live(res: SubstituteResult, catalog: Catalog, engine, top: int = 3) -> SubstituteResult:
    """Re-price the target and the top suggestions with live / cached pharmacy prices (one shared wait),
    then recompute savings. Snapshot prices remain where nothing fresher arrived."""
    brands = [c for c in res.substitutes if c.tier == "brand"][:top]
    prods = [res.target] + [catalog.products[c.product_id] for c in brands if c.product_id in catalog.products]
    quotes = engine.quotes_many(prods)

    def best_unit(qs: list[dict], unit: str | None) -> float | None:
        vals = [q["price_per_unit_inr"] for q in qs if q.get("price_per_unit_inr")
                and (unit is None or q.get("pack_unit") in (None, unit))]
        return round(min(vals), 2) if vals else None

    t_live = best_unit(quotes.get(res.target.product_id, []), res.pack_unit)
    if t_live:
        res.target_price_per_unit = t_live
    for c in brands:
        qs = quotes.get(c.product_id, [])
        if qs:
            c.quotes = qs[:4]
            c.price_per_unit_inr = best_unit(qs, c.pack_unit) or c.price_per_unit_inr
    if res.target_price_per_unit:
        for c in res.substitutes:
            c.savings_percentage = round(100 * (1 - c.price_per_unit_inr / res.target_price_per_unit), 1)
    res.substitutes.sort(key=lambda c: c.price_per_unit_inr)
    res.target_quotes = quotes.get(res.target.product_id, [])
    return res
