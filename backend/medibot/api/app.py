"""MediBot HTTP API (Phase 12). Run: PYTHONPATH=backend .venv/bin/uvicorn medibot.api.app:app --port 8000

This file only assembles the app: CORS, the rate limit, the never-a-500 handler and the routers.
  routes_chat.py      POST /api/v1/session/start · /session/ack · /medibot/query · /feedback,
                      DELETE /api/v1/session/{id} (forget-me), GET /api/v1/metrics, GET /health
  routes_medicine.py  GET /api/v1/search (⌘K), GET /api/v1/medicine/{id} (Live Medicine Sheet), POST /api/v1/optimize
  routes_bill.py      bill split: POST /api/v1/bill/parse · /bill/plan · /bill/read (photo, opt-in)
  schemas.py          request bodies (control characters stripped, length caps -> 422, never a crash)
  ps.py               the problem statement's response schema
  deps.py             the one Assistant, session activity, the client identity for rate limits

Hard rules: never a 500 with a stack trace (every failure returns a safe JSON reply), input capped at 1,000
characters, per-client rate limit (X-Forwarded-For only behind MEDIBOT_TRUSTED_PROXIES), CORS only for configured
origins, no message text stored (store.py).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from medibot.api import store
from medibot.api.deps import bot, client_id, touch  # noqa: F401 - re-exported (tests / scripts use api.bot)
from medibot.api.routes_bill import router as bill_router
from medibot.api.routes_chat import router as chat_router
from medibot.api.routes_medicine import router as medicine_router
from medibot.safety import messages as msg

log = logging.getLogger("medibot.api")
RATE = int(os.environ.get("MEDIBOT_RATE_PER_MIN", "30"))          # requests per minute per client
ORIGINS = [o for o in os.environ.get("MEDIBOT_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://127.0.0.1:5173,http://127.0.0.1:4173,http://localhost:4173").split(",") if o]


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot()                       # load the catalog once (~14 s, ~2 GB) before taking traffic
    store.purge(force=True)     # retention on every start
    yield


app = FastAPI(title="MediBot API", version="1.1", lifespan=lifespan,
              description="Informational pharmacy assistant for India. " + msg.DISCLAIMER)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Content-Type"], allow_credentials=False)


# ---------------------------------------------------------------- guards
_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method != "OPTIONS":   # CORS preflights are free
        now, key = time.time(), client_id(request)
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


app.include_router(chat_router)
app.include_router(medicine_router)
app.include_router(bill_router)
