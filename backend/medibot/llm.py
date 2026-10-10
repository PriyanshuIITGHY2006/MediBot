"""LLM client (Groq, OpenAI-compatible). Optional by design: every caller must work when this returns None.

- Kill switch: MEDIBOT_LLM=off
- Hard timeout (default 4 s) and one retry; never raises to the caller
- Token-per-minute limiter for the free tier (gpt-oss-20b: 8k TPM, 1k requests/day)
- Disk cache keyed by (model, messages): repeat eval runs cost no quota and are deterministic
- Personal data (phone, email, Aadhaar, PAN) is removed before anything leaves the machine
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data/interim/llm_cache.sqlite"
FAST = os.environ.get("MEDIBOT_LLM_FAST", "openai/gpt-oss-20b")
STRONG = os.environ.get("MEDIBOT_LLM_STRONG", "openai/gpt-oss-120b")
URL = "https://api.groq.com/openai/v1/chat/completions"

_PII = [
    (re.compile(r"\b[6-9]\d{9}\b"), "[phone]"),                      # Indian mobile
    (re.compile(r"\+?91[\s-]?\d{5}[\s-]?\d{5}\b"), "[phone]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[aadhaar]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[pan]"),
]


def scrub(text: str) -> str:
    for rx, sub in _PII:
        text = rx.sub(sub, text)
    return text


def _key() -> str | None:
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("GROQ_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


class _Limiter:
    """Simple sliding-window token budget per minute."""

    def __init__(self, tpm: int):
        self.tpm, self.events, self.lock = tpm, [], threading.Lock()

    def wait(self, tokens: int, max_wait: float) -> bool:
        deadline = time.time() + max_wait
        while True:
            with self.lock:
                now = time.time()
                self.events = [(t, n) for t, n in self.events if now - t < 60]
                if sum(n for _, n in self.events) + tokens <= self.tpm:
                    self.events.append((now, tokens))
                    return True
            if time.time() > deadline:
                return False
            time.sleep(0.5)


class LLM:
    def __init__(self):
        self.key = _key()
        self.enabled = bool(self.key) and os.environ.get("MEDIBOT_LLM", "on") != "off"
        self.client = httpx.Client(timeout=float(os.environ.get("MEDIBOT_LLM_TIMEOUT", "4")))
        self.limiters = {FAST: _Limiter(7000), STRONG: _Limiter(7000)}
        self.stats = {"calls": 0, "cache_hits": 0, "failures": 0}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(CACHE, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT)")

    def chat_json(self, system: str, user: str, *, model: str = FAST, max_tokens: int = 300,
                  max_wait: float = 2.0) -> dict | None:
        """Ask for a JSON object. Returns None on any problem (disabled, timeout, rate limit, bad JSON)."""
        if not self.enabled:
            return None
        messages = [{"role": "system", "content": system}, {"role": "user", "content": scrub(user)}]
        k = hashlib.sha256(json.dumps([model, messages], ensure_ascii=False).encode()).hexdigest()
        row = self.db.execute("SELECT v FROM cache WHERE k = ?", (k,)).fetchone()
        if row:
            self.stats["cache_hits"] += 1
            return json.loads(row[0])
        est = (len(system) + len(user)) // 3 + max_tokens
        if not self.limiters.setdefault(model, _Limiter(7000)).wait(est, max_wait):
            self.stats["failures"] += 1
            return None
        body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens,
                "response_format": {"type": "json_object"}}
        for attempt in range(2):
            try:
                self.stats["calls"] += 1
                r = self.client.post(URL, json=body, headers={"Authorization": f"Bearer {self.key}"})
                if r.status_code == 429:
                    break
                r.raise_for_status()
                out = json.loads(r.json()["choices"][0]["message"]["content"])
                self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (k, json.dumps(out, ensure_ascii=False)))
                self.db.commit()
                return out
            except Exception:  # noqa: BLE001 - the LLM is optional; any failure falls back to rules
                if attempt == 1:
                    break
        self.stats["failures"] += 1
        return None


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm
