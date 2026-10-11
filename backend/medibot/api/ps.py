"""The problem statement's response schema (exact field names), built from the Assistant's reply."""
from __future__ import annotations

from medibot.safety import messages as msg

SCHEDULE_LABEL = {"schedule_h": "Schedule H", "schedule_h1": "Schedule H1", "schedule_x": "Schedule X",
                  "controlled": "Controlled (NDPS)", "prescription": "Prescription only", "banned": "Banned (Section 26A)",
                  "otc": "OTC", "otc_unverified": "OTC (composition not verified)", "unknown": "Prescription by default"}

_tclass: dict | None = None
_images: dict | None = None


def therapeutic_class(product_id: str | None) -> str | None:
    global _tclass
    if not product_id:
        return None
    if _tclass is None:
        import pandas as pd
        from medibot.catalog import P
        t = pd.read_parquet(P / "products.parquet", columns=["product_id", "therapeutic_class"]).dropna()
        _tclass = dict(zip(t["product_id"], t["therapeutic_class"].astype(str).str.title()))
    return _tclass.get(product_id)


def image_of(product_id: str) -> str | None:
    global _images
    if _images is None:
        import pandas as pd
        from medibot.catalog import P
        t = pd.read_parquet(P / "products.parquet", columns=["product_id", "image_url"]).dropna()
        _images = dict(zip(t["product_id"], t["image_url"]))
    return _images.get(product_id)


def _mrp(quotes: list[dict]) -> float | None:
    vals = [q.get("mrp_inr") for q in quotes or [] if q.get("mrp_inr")]
    return round(min(vals), 2) if vals else None


def to_ps(user_query: str, r: dict) -> dict:
    """The PS response schema first (exact field names), then MediBot's extra fields."""
    dm = r.get("detected_medication")
    ps = {
        "user_query": user_query,
        "session_id": r["session_id"],
        "disclaimer_acknowledged": bool(r.get("disclaimer_acknowledged")),
        "safety_guard": r["safety_guard"],
        "detected_medication": None if not dm else {
            "brand_name": dm["brand_name"], "active_composition": dm["active_composition"],
            "therapeutic_class": therapeutic_class(dm.get("product_id")),
            "schedule": SCHEDULE_LABEL.get(dm.get("schedule") or "", dm.get("schedule")),
            "mrp_inr": _mrp(r.get("prices")), "product_id": dm.get("product_id"),
            "composition_id": dm.get("composition_id")},
        "substitutes": [{
            "brand_name": s["brand_name"], "manufacturer": s.get("manufacturer"),
            "active_composition": s.get("active_composition"), "composition_id": s.get("composition_id"),
            "composition_identically_verified": bool(s.get("composition_identically_verified")),
            "mrp_inr": _mrp(s.get("partner_price_comparison")),
            "price_per_unit_inr": s.get("price_per_unit_inr"), "savings_percentage": s.get("savings_percentage"),
            "user_advisory": s.get("user_advisory"), "tier": s.get("tier"),
            "partner_price_comparison": [{"platform": q.get("platform"), "price_inr": q.get("price_inr"),
                                          "delivery_eta": q.get("delivery_eta"), "url": q.get("url"),
                                          "price_per_unit_inr": q.get("price_per_unit_inr"),
                                          "freshness": q.get("source")}
                                         for q in s.get("partner_price_comparison") or []]}
            for s in r.get("substitutes") or []],
        "disclaimer": r.get("disclaimer") or msg.DISCLAIMER,
    }
    for k in ("turn_id", "response_text", "intent", "cards", "prices", "stores", "clarification_options",
              "health_answer", "interactions", "receipt"):
        if k in r:
            ps[k] = r[k]
    return ps
