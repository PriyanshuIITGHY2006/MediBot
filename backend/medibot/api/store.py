"""Privacy-first persistence for the API (Phase 12.2 / 12.3).

What is stored, and only this:
- sessions: a SHA-256 of the anonymous session id (never the id itself), first/last seen, when the disclaimer was
  acknowledged and a hash of the disclaimer text that was shown
- turns: the OUTCOME of each turn (intent, safety action, intercepted?, emergency?, counts, latency). Never the
  message text, never the reply, never a medicine name
- feedback: a 1-5 rating and an optional comment, PII-scrubbed and capped at 500 characters

Retention: everything older than RETENTION_DAYS (30) is deleted (purge() runs at startup and daily).
Forget-me: forget(session_id) deletes that session's rows immediately.
If the database is unreachable the API keeps working; nothing is stored and /metrics says so.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time

from medibot.health.evidence import conn
from medibot.llm import scrub

RETENTION_DAYS = int(os.environ.get("MEDIBOT_RETENTION_DAYS", "30"))
_lock = threading.Lock()
_last_purge = 0.0


def h(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


def _exec(sql: str, params=()) -> list[tuple] | None:
    c = conn()
    if c is None:
        return None
    try:
        with _lock:
            cur = c.execute(sql, params)
            return cur.fetchall() if cur.description else []
    except Exception:  # noqa: BLE001 - storage is optional; the API never fails because of it
        return None


def available() -> bool:
    return _exec("SELECT 1") is not None


def session_seen(session_id: str) -> None:
    _exec("""INSERT INTO api_sessions (session_hash) VALUES (%s)
             ON CONFLICT (session_hash) DO UPDATE SET last_seen = now()""", (h(session_id),))


def acknowledged(session_id: str, disclaimer: str) -> None:
    _exec("""INSERT INTO api_sessions (session_hash, acknowledged_at, disclaimer_sha256) VALUES (%s, now(), %s)
             ON CONFLICT (session_hash) DO UPDATE SET acknowledged_at = now(), disclaimer_sha256 = EXCLUDED.disclaimer_sha256,
             last_seen = now()""", (h(session_id), hashlib.sha256(disclaimer.encode()).hexdigest()))


def turn(session_id: str, turn_id: str, r: dict, latency_ms: int) -> None:
    g = r.get("safety_guard") or {}
    _exec("""INSERT INTO api_turns (session_hash, turn_id, intent, action, intercepted, emergency, medicine_found,
                                    substitutes, price_quotes, latency_ms, reader, narrator)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (turn_id) DO NOTHING""",
          (h(session_id), turn_id, r.get("intent"), (r.get("second_opinion") or {}).get("after"),
           bool(g.get("intercept_triggered")), bool(g.get("is_emergency")), bool(r.get("detected_medication")),
           len(r.get("substitutes") or []), len(r.get("prices") or []), latency_ms,
           (r.get("reader") or {}).get("status"), (r.get("narrator") or {}).get("source")))


def feedback(session_id: str, turn_id: str | None, rating: int, comment: str | None) -> bool:
    text = scrub(comment)[:500] if comment else None
    return _exec("INSERT INTO api_feedback (session_hash, turn_id, rating, comment) VALUES (%s, %s, %s, %s)",
                 (h(session_id), turn_id, rating, text)) is not None


def forget(session_id: str) -> int:
    k = h(session_id)
    n = 0
    for t in ("api_turns", "api_feedback", "api_sessions"):
        rows = _exec(f"DELETE FROM {t} WHERE session_hash = %s RETURNING 1", (k,))
        n += len(rows or [])
    return n


def purge(force: bool = False) -> None:
    global _last_purge
    if not force and time.time() - _last_purge < 86400:
        return
    _last_purge = time.time()
    for t, col in (("api_turns", "ts"), ("api_feedback", "ts"), ("api_sessions", "last_seen")):
        _exec(f"DELETE FROM {t} WHERE {col} < now() - make_interval(days => %s)", (RETENTION_DAYS,))


def metrics() -> dict:
    """Aggregate, anonymous numbers for the trust dashboard (Phase 16)."""
    rows = _exec("""SELECT count(*), count(*) FILTER (WHERE intercepted), count(*) FILTER (WHERE emergency),
                           count(*) FILTER (WHERE medicine_found), avg(latency_ms),
                           percentile_disc(0.5) WITHIN GROUP (ORDER BY latency_ms),
                           percentile_disc(0.95) WITHIN GROUP (ORDER BY latency_ms),
                           count(DISTINCT session_hash)
                    FROM api_turns WHERE ts > now() - interval '30 days'""")
    fb = _exec("SELECT count(*), avg(rating) FROM api_feedback WHERE ts > now() - interval '30 days'")
    if rows is None:
        return {"storage": "unavailable"}
    n, inter, emerg, found, avg_ms, p50, p95, sessions = rows[0]
    fcount, favg = (fb or [(0, None)])[0]
    return {"storage": "ok", "window_days": 30, "turns": n, "sessions": sessions, "intercepted": inter,
            "emergencies": emerg, "medicine_recognised": found,
            "latency_ms": {"avg": round(float(avg_ms), 1) if avg_ms else None, "p50": p50, "p95": p95},
            "csat": {"ratings": fcount, "average": round(float(favg), 2) if favg else None},
            "retention_days": RETENTION_DAYS}
