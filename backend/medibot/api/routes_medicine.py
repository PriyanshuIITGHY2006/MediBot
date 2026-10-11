"""Medicine endpoints: ⌘K search, the Live Medicine Sheet, the monthly bill optimizer and My Cabinet."""
from __future__ import annotations

import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from medibot.api.deps import bot
from medibot.api.ps import SCHEDULE_LABEL, image_of, therapeutic_class
from medibot.api.schemas import CabinetIn, OptimizeIn
from medibot.safety import messages as msg

router = APIRouter()


@router.post("/api/v1/optimize")
def optimize(body: OptimizeIn):
    from medibot.optimizer import optimize_bill
    return optimize_bill(bot(), [(i.name, i.quantity) for i in body.items])


@router.post("/api/v1/cabinet/check")
def cabinet_check(body: CabinetIn):
    """My Cabinet: monthly cost, cheapest identical option and cabinet-wide interactions. Nothing is stored."""
    from medibot.cabinet import check_cabinet
    return check_cabinet(bot(), [i.model_dump() for i in body.items])


@router.get("/api/v1/search")
def search(q: str = "", limit: int = 8):
    q = re.sub(r"[\x00-\x1f\x7f]", " ", q).strip()[:80]
    if len(q) < 2:
        return {"query": q, "results": []}
    cat = bot().catalog
    out, seen = [], set()
    for m in cat.index.resolve(q, max(1, min(limit, 15)) * 2):
        if m.kind != "product" or m.product_id in seen or m.product_id not in cat.products:
            continue
        seen.add(m.product_id)
        p = cat.products[m.product_id]
        out.append({"product_id": p.product_id, "name": p.name, "composition": p.composition, "form": p.form,
                    "schedule": SCHEDULE_LABEL.get(p.category, p.category), "requires_prescription": p.requires_prescription,
                    "confident": m.confident})
        if len(out) >= limit:
            break
    return {"query": q, "results": out}


@router.get("/api/v1/medicine/{product_id}")
def medicine(product_id: str):
    """Everything the Live Medicine Sheet shows for one product. Same safety rules as the chat: the mandated prompt
    for restricted medicines, no doses, cited information only, identical substitutes only."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,40}", product_id):
        return JSONResponse({"error": "bad product id"}, status_code=422)
    from medibot.assistant import habit_forming, price_book
    from medibot.health.answer import answer_medicine
    from medibot.substitutes import find_substitutes, refresh_with_live
    b = bot()
    p = b.catalog.products.get(product_id)
    if p is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    info = answer_medicine(p.name, p.composition, p.ingredients, "uses and side effects",
                           habit_forming=habit_forming(p.product_id) if p.product_id else None,
                           sections_override=["uses", "side_effects", "how_it_works"], product_id=p.product_id,
                           form=p.form) if p.ingredients else None
    subs = refresh_with_live(find_substitutes(p, b.catalog, price_book()), b.catalog, b.prices) \
        if p.composition_id and p.category != "banned" else None
    return {
        "product_id": p.product_id, "name": p.name, "manufacturer": p.manufacturer, "form": p.form,
        "composition": p.composition, "composition_id": p.composition_id,
        "schedule": SCHEDULE_LABEL.get(p.category, p.category), "category": p.category,
        "requires_prescription": p.requires_prescription, "banned": p.category == "banned",
        "mandated_prompt": msg.MANDATED_PROMPT if p.requires_prescription or p.category == "banned" else None,
        "safety_reason": p.reasons, "legal_refs": p.legal_refs,
        "therapeutic_class": therapeutic_class(p.product_id),
        "habit_forming": habit_forming(p.product_id) if p.ingredients else None,
        "image_url": image_of(p.product_id), "image_credit": "Image: Tata 1mg" if image_of(p.product_id) else None,
        "info": None if not info else {"text": info.text, "sections": info.sections, "missing": info.missing,
                                       "citations": [c.as_contract() for c in info.citations]},
        "prices": b.prices.quotes(p) if p.category != "banned" else [],
        "substitutes": None if subs is None else {
            "current_price_per_unit_inr": subs.target_price_per_unit, "pack_unit": subs.pack_unit, "note": subs.note,
            "rows": [s.as_contract() for s in subs.substitutes]},
        "disclaimer": msg.SHORT_DISCLAIMER,
    }
