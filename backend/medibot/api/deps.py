"""Shared state of the API process: the one Assistant, session activity, the client identity used for rate limits.

Kept apart from the routers so every router uses the same Assistant (the catalog is ~2 GB; it is loaded once).
"""
from __future__ import annotations

import ipaddress
import os
import threading
import time

from fastapi import Request

SESSION_IDLE_S = int(os.environ.get("MEDIBOT_SESSION_IDLE_S", str(6 * 3600)))   # in-memory context is dropped after
# X-Forwarded-For is only believed when the direct peer is one of these proxies (comma-separated IPs or CIDRs,
# e.g. "127.0.0.1,10.0.0.0/8"). Default: none -> the header is ignored and the socket address is used, so a client
# can't dodge the rate limit by sending a fake header.
TRUSTED_PROXIES = [ipaddress.ip_network(p.strip(), strict=False)
                   for p in os.environ.get("MEDIBOT_TRUSTED_PROXIES", "").split(",") if p.strip()]

_bot = None
_bot_lock = threading.Lock()
_seen: dict[str, float] = {}
_seen_lock = threading.Lock()


def bot():
    global _bot
    with _bot_lock:
        if _bot is None:
            from medibot.assistant import Assistant
            _bot = Assistant()
        return _bot


def touch(sid: str) -> None:
    """Remember activity; every ~500 touches, drop conversation context idle for longer than SESSION_IDLE_S."""
    now = time.time()
    with _seen_lock:
        _seen[sid] = now
        if len(_seen) % 500 == 0:
            for k in [k for k, t in _seen.items() if now - t > SESSION_IDLE_S]:
                _seen.pop(k, None)
                bot().sessions.pop(k, None)


def _trusted(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in net for net in TRUSTED_PROXIES)


def client_id(request: Request) -> str:
    """The client address for rate limiting. X-Forwarded-For counts only behind a configured trusted proxy, and
    then the right-most address that is NOT one of our proxies is used (the left-most entries are client-supplied
    and can be forged)."""
    peer = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for", "")
    if not fwd or not _trusted(peer):
        return peer or "unknown"
    for hop in reversed([h.strip() for h in fwd.split(",") if h.strip()]):
        if not _trusted(hop):
            return hop
    return peer or "unknown"
