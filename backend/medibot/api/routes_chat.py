"""Chat endpoints: anonymous sessions, the query (PS schema), feedback, forget-me, metrics, health."""
from __future__ import annotations

import re
import time
import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from medibot.api import store
from medibot.api.deps import bot, touch
from medibot.api.ps import to_ps
from medibot.api.schemas import FeedbackIn, QueryIn, SessionRef
from medibot.safety import messages as msg

router = APIRouter()


@router.get("/health")
def health():
    from medibot.health.evidence import available as evidence_ok
    from medibot.llm import get_llm
    b = bot()
    return {"status": "ok", "catalog_products": len(b.catalog.products), "evidence_db": evidence_ok(),
            "storage": store.available(), "llm": get_llm().enabled, "live_prices": b.prices.live}


@router.post("/api/v1/session/start")
def session_start():
    s = bot().start_session()
    touch(s["session_id"])
    store.session_seen(s["session_id"])
    return s


@router.post("/api/v1/session/ack")
def session_ack(body: SessionRef):
    bot().acknowledge(body.session_id)
    store.acknowledged(body.session_id, msg.DISCLAIMER)
    return {"session_id": body.session_id, "disclaimer_acknowledged": True}


@router.post("/api/v1/medibot/query")
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
    if body.language != "en" and out.get("cards"):
        from medibot.translate import translate_cards
        out["cards"], out["translation"] = translate_cards(out["cards"], body.language)
    out["latency_ms"] = int((time.time() - t0) * 1000)
    return out


@router.post("/api/v1/feedback")
def feedback(body: FeedbackIn):
    return {"stored": store.feedback(body.session_id, body.turn_id, body.rating, body.comment)}


@router.delete("/api/v1/session/{session_id}")
def forget(session_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", session_id):
        return JSONResponse({"error": "bad session id"}, status_code=422)
    bot().sessions.pop(session_id, None)
    return {"forgotten": True, "rows_deleted": store.forget(session_id)}


@router.get("/api/v1/metrics")
def metrics():
    store.purge()
    return store.metrics()
