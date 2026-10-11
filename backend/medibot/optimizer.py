"""Bill optimizer: a monthly medicine list -> the cheapest IDENTICAL option for each item, and the total saving.

Same rules as the chat: identity is the Composition ID (same ingredients, strengths, form, release), banned
products get no alternative, prescription medicines carry the mandated prompt, and every switch must be
confirmed with a doctor or pharmacist. Prices are per unit (tablet / ml / g) times the monthly quantity.
"""
from __future__ import annotations

from medibot.mentions import find_mentions
from medibot.safety import messages as msg
from medibot.safety.kernel import decide
from medibot.substitutes import ADVISORY, find_substitutes, refresh_with_live


def optimize_bill(bot, items: list[tuple[str, int]]) -> dict:
    from medibot.assistant import price_book
    cat = bot.catalog
    rows, now_total, best_total = [], 0.0, 0.0
    for name, qty in items:
        ms = [m for m in find_mentions(name, cat) if m.kind == "product"]
        if not ms:
            rows.append({"input": name, "status": "not_recognised"})
            continue
        dec = decide(name, cat, mentions=ms[:1])
        mv = dec.medicines[0]
        p = mv.product
        row = {"input": name, "quantity": qty, "product_id": p.product_id, "brand_name": p.name,
               "active_composition": p.composition, "intercept": dec.intercept,
               "mandated_prompt": msg.MANDATED_PROMPT if dec.intercept else None,
               "confident": ms[0].confident}
        if dec.banned:
            rows.append(dict(row, status="banned", note=msg.banned_notice(mv.legal_ref.split(" | ")[0] or "Section 26A")))
            continue
        res = refresh_with_live(find_substitutes(p, cat, price_book()), cat, bot.prices)
        cur = res.target_price_per_unit
        best = next((s for s in res.substitutes if s.savings_percentage and s.savings_percentage > 0), None)
        if not cur:
            rows.append(dict(row, status="no_price", note=res.note))
            continue
        row.update(status="ok", pack_unit=res.pack_unit, current_price_per_unit_inr=cur,
                   current_monthly_inr=round(cur * qty, 2))
        now_total += cur * qty
        if best:
            row.update(best_alternative={"brand_name": best.brand_name, "manufacturer": best.manufacturer,
                                         "tier": best.tier, "price_per_unit_inr": best.price_per_unit_inr,
                                         "composition_identically_verified": True},
                       best_monthly_inr=round(best.price_per_unit_inr * qty, 2),
                       savings_percentage=best.savings_percentage)
            best_total += best.price_per_unit_inr * qty
        else:
            row.update(best_alternative=None, best_monthly_inr=round(cur * qty, 2), savings_percentage=0.0,
                       note=res.note)
            best_total += cur * qty
        rows.append(row)
    return {
        "items": rows,
        "current_monthly_inr": round(now_total, 2),
        "optimised_monthly_inr": round(best_total, 2),
        "monthly_savings_inr": round(now_total - best_total, 2),
        "savings_percentage": round(100 * (1 - best_total / now_total), 1) if now_total else 0.0,
        "advisory": ADVISORY,
        "disclaimer": msg.DISCLAIMER,
    }
