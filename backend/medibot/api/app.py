"""MediBot HTTP API (Phase 12). Run: PYTHONPATH=backend .venv/bin/uvicorn medibot.api.app:app --port 8000

  POST /api/v1/session/start         anonymous session + the full disclaimer (must be acknowledged)
  POST /api/v1/session/ack           acknowledge the disclaimer
  POST /api/v1/medibot/query         the PS response schema (+ cards, citations, receipt)
  POST /api/v1/feedback              1-5 rating (CSAT, rubric C3) + optional comment
  POST /api/v1/optimize              bill optimizer: cheapest identical option for each medicine on a list
  DELETE /api/v1/session/{id}        forget-me: deletes the session and everything stored about it
  GET  /api/v1/metrics               anonymous aggregates for the trust dashboard
  GET  /health                       liveness + what is available (catalog, evidence DB, LLM, live prices)

Hard rules: never a 500 with a stack trace (every failure returns a safe JSON reply), input capped at 1,000
characters, per-client rate limit, CORS only for configured origins, no message text stored (store.py).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from medibot.api import store
from medibot.safety import messages as msg

log = logging.getLogger("medibot.api")
MAX_CHARS = int(os.environ.get("MEDIBOT_MAX_INPUT_CHARS", "1000"))
RATE = int(os.environ.get("MEDIBOT_RATE_PER_MIN", "30"))          # requests per minute per client
ORIGINS = [o for o in os.environ.get("MEDIBOT_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if o]
SCHEDULE_LABEL = {"schedule_h": "Schedule H", "schedule_h1": "Schedule H1", "schedule_x": "Schedule X",
                  "controlled": "Controlled (NDPS)", "prescription": "Prescription only", "banned": "Banned (Section 26A)",
                  "otc": "OTC", "otc_unverified": "OTC (composition not verified)", "unknown": "Prescription by default"}

_bot = None
_bot_lock = threading.Lock()
SESSION_IDLE_S = int(os.environ.get("MEDIBOT_SESSION_IDLE_S", str(6 * 3600)))   # in-memory context is dropped after
_seen: dict[str, float] = {}
_seen_lock = threading.Lock()


def touch(sid: str) -> None:
    """Remember activity; every ~500 touches, drop conversation context idle for longer than SESSION_IDLE_S."""
    now = time.time()
    with _seen_lock:
        _seen[sid] = now
        if len(_seen) % 500 == 0:
            for k in [k for k, t in _seen.items() if now - t > SESSION_IDLE_S]:
                _seen.pop(k, None)
                bot().sessions.pop(k, None)


def bot():
    global _bot
    with _bot_lock:
        if _bot is None:
            from medibot.assistant import Assistant
            _bot = Assistant()
        return _bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot()                       # load the catalog once (~14 s, ~2 GB) before taking traffic
    store.purge(force=True)     # retention on every start
    yield


app = FastAPI(title="MediBot API", version="1.0", lifespan=lifespan,
              description="Informational pharmacy assistant for India. " + msg.DISCLAIMER)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Content-Type"], allow_credentials=False)


# ---------------------------------------------------------------- guards
_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def _client(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")) or "unknown"


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        now, key = time.time(), _client(request)
        with _hits_lock:
            q = _hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= RATE:
                return JSONResponse({"error": "rate_limited", "detail": f"at most {RATE} requests per minute",
                                     "disclaimer": msg.DISCLAIMER}, status_code=429)
            q.append(now)
    return await call_next(request)


@app.exception_handler(Exception)
async def never_500(request: Request, exc: Exception):
    """A crash must never leak a stack trace or leave the user without guidance."""
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"error": "internal", "response_text": msg.FALLBACK_ERROR, "disclaimer": msg.DISCLAIMER},
                        status_code=503)


class _Text(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            v = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", v).strip()   # control characters out
        return v


class SessionRef(_Text):
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class QueryIn(_Text):
    user_query: str = Field(min_length=1, max_length=MAX_CHARS)
    session_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    disclaimer_acknowledged: bool = False


class FeedbackIn(SessionRef):
    turn_id: str | None = Field(default=None, max_length=64)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)


class OptimizeItem(_Text):
    name: str = Field(min_length=2, max_length=120)
    quantity: int = Field(default=1, ge=1, le=1000)          # units (tablets / ml) per month


class OptimizeIn(_Text):
    items: list[OptimizeItem] = Field(min_length=1, max_length=25)


# ---------------------------------------------------------------- PS schema mapping
_tclass: dict | None = None


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


# ---------------------------------------------------------------- endpoints
@app.get("/health")
def health():
    from medibot.health.evidence import available as evidence_ok
    from medibot.llm import get_llm
    b = bot()
    return {"status": "ok", "catalog_products": len(b.catalog.products), "evidence_db": evidence_ok(),
            "storage": store.available(), "llm": get_llm().enabled, "live_prices": b.prices.live}


@app.post("/api/v1/session/start")
def session_start():
    s = bot().start_session()
    touch(s["session_id"])
    store.session_seen(s["session_id"])
    return s


@app.post("/api/v1/session/ack")
def session_ack(body: SessionRef):
    bot().acknowledge(body.session_id)
    store.acknowledged(body.session_id, msg.DISCLAIMER)
    return {"session_id": body.session_id, "disclaimer_acknowledged": True}


@app.post("/api/v1/medibot/query")
def query(body: QueryIn):
    b = bot()
    sid = body.session_id or b.start_session()["session_id"]
    touch(sid)
    if body.disclaimer_acknowledged:
        b.acknowledge(sid)
    t0 = time.time()
    r = b.query(sid, body.user_query)
    ms = int((time.time() - t0) * 1000)
    r["turn_id"] = uuid.uuid4().hex[:16]
    store.session_seen(sid)
    store.turn(sid, r["turn_id"], r, ms)
    out = to_ps(body.user_query, r)
    out["latency_ms"] = ms
    return out


@app.post("/api/v1/feedback")
def feedback(body: FeedbackIn):
    return {"stored": store.feedback(body.session_id, body.turn_id, body.rating, body.comment)}


@app.delete("/api/v1/session/{session_id}")
def forget(session_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", session_id):
        return JSONResponse({"error": "bad session id"}, status_code=422)
    bot().sessions.pop(session_id, None)
    return {"forgotten": True, "rows_deleted": store.forget(session_id)}


@app.get("/api/v1/metrics")
def metrics():
    store.purge()
    return store.metrics()


@app.post("/api/v1/optimize")
def optimize(body: OptimizeIn):
    from medibot.optimizer import optimize_bill
    return optimize_bill(bot(), [(i.name, i.quantity) for i in body.items])
