"""My Cabinet (Phase 15.3): the medicines someone takes regularly -> monthly cost now, the cheapest identical option,
and interactions across the whole cabinet. The cabinet itself lives on the user's device; the server sees only
product ids and daily counts for this one request and stores nothing.

Doses per day are what the user enters (their prescription); nothing here suggests or changes a dose.
"""
from __future__ import annotations

from medibot.health import interactions as ix
from medibot.safety import messages as msg
from medibot.substitutes import ADVISORY, find_substitutes, refresh_with_live

DAYS = 30


def check_cabinet(bot, items: list[dict]) -> dict:
    """items: [{product_id, per_day}] -> per-medicine cost lines + cabinet-wide interaction findings."""
    from medibot.assistant import price_book
    cat = bot.catalog
    rows, ix_items = [], []
    now_total, best_total, complete = 0.0, 0.0, True
    for it in items:
        p = cat.products.get(it["product_id"])
        if p is None:
            rows.append({"product_id": it["product_id"], "status": "not_found"})
            continue
        units = float(it["per_day"]) * DAYS
        row = {"product_id": p.product_id, "name": p.name, "composition": p.composition, "form": p.form,
               "per_day": it["per_day"], "units_per_month": units, "requires_prescription": p.requires_prescription,
               "mandated_prompt": msg.MANDATED_PROMPT if p.requires_prescription else None}
        if p.ingredients:
            ix_items.append(ix.Item(p.name, tuple(p.ingredients)))
        if p.category == "banned":
            rows.append(dict(row, status="banned", note=msg.banned_notice((p.legal_refs or "Section 26A").split(" | ")[0])))
            complete = False
            continue
        res = refresh_with_live(find_substitutes(p, cat, price_book()), cat, bot.prices)
        ppu = res.target_price_per_unit
        best = next((s for s in res.substitutes if s.price_per_unit_inr and ppu and s.price_per_unit_inr < ppu), None)
        quotes = res.target_quotes or []
        cheapest_q = min((q for q in quotes if q.get("price_per_unit_inr")), key=lambda q: q["price_per_unit_inr"], default=None)
        row.update(
            status="ok" if ppu else "no_price", pack_unit=res.pack_unit, price_per_unit_inr=ppu,
            cheapest_platform=cheapest_q["platform"] if cheapest_q else None,
            observed=cheapest_q.get("observed") if cheapest_q else None,
            monthly_inr=round(ppu * units, 2) if ppu else None,
            best_alternative=None if not best else {
                "product_id": best.product_id, "brand_name": best.brand_name, "manufacturer": best.manufacturer,
                "tier": best.tier, "price_per_unit_inr": best.price_per_unit_inr,
                "monthly_inr": round(best.price_per_unit_inr * units, 2),
                "savings_percentage": best.savings_percentage, "composition_identically_verified": True},
        )
        if ppu:
            now_total += ppu * units
            best_total += (best.price_per_unit_inr if best else ppu) * units
        else:
            complete = False
        rows.append(row)
    findings = [f.as_contract() for f in ix.check(ix_items)] if len(ix_items) >= 2 else []
    return {
        "items": rows,
        "monthly_inr": round(now_total, 2),
        "monthly_best_inr": round(best_total, 2),
        "monthly_savings_inr": round(now_total - best_total, 2),
        "complete": complete,
        "interactions": findings,
        "interaction_advice": ix.ADVICE,
        "advisory": ADVISORY,
        "disclaimer": msg.DISCLAIMER,
    }
