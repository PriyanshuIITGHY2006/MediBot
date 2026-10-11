"""Eval adapter that talks to the running API over HTTP (same contract as medibot.assistant.Assistant).

    PYTHONPATH=backend .venv/bin/uvicorn medibot.api.app:app --port 8000 &
    MEDIBOT_API=http://127.0.0.1:8000 PYTHONPATH=backend .venv/bin/python eval/run.py --bot eval.http_bot:HttpBot
"""
from __future__ import annotations

import os

import httpx

API = os.environ.get("MEDIBOT_API", "http://127.0.0.1:8000")


class HttpBot:
    def __init__(self):
        self.c = httpx.Client(base_url=API, timeout=60)

    def start_session(self) -> dict:
        return self.c.post("/api/v1/session/start").json()

    def acknowledge(self, session_id: str) -> None:
        self.c.post("/api/v1/session/ack", json={"session_id": session_id})

    def query(self, session_id: str, text: str) -> dict:
        r = self.c.post("/api/v1/medibot/query", json={"user_query": text[:1000], "session_id": session_id})
        r.raise_for_status()
        return r.json()
