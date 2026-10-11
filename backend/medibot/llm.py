"""LLM client (Groq, OpenAI-compatible). Optional by design: every caller must work when this returns None.

- Kill switch: MEDIBOT_LLM=off
- Hard timeout (default 4 s) and one retry; never raises to the caller
- Token-per-minute limiter for the free tier (gpt-oss-20b: 8k TPM, 1k requests/day)
- Disk cache keyed by (model, messages): repeat eval runs cost no quota and are deterministic
- Personal data (phone, email, Aadhaar, PAN) is removed before anything leaves the machine
- Daily quota guard (Phase 11): requests per model per UTC day are counted in the cache DB (cache hits are free).
  Optional features (narrator, second opinion) call allow(feature, model) and stand down at QUOTA_SHARE (70%) of the
  free-tier daily limit, so the rest is kept for live use / the demo. understanding.py is not capped by the guard.
- Kill switches: MEDIBOT_LLM=off (everything), MEDIBOT_NARRATOR=off, MEDIBOT_SECOND_OPINION=off
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
# second provider: Cline's OpenAI-compatible gateway (458 models). Model names "cline:<id>", key MEDIBOT_LLM2_API_KEY.
CLINE_URL = "https://api.cline.bot/api/v1/chat/completions"
CLINE_DAILY_LIMIT = int(os.environ.get("MEDIBOT_CLINE_DAILY_LIMIT", "5000"))   # paid credits: our own cap
DAILY_LIMIT = {FAST: 1000, STRONG: 1000}     # Groq free tier, requests per day (checked 2026-10-11)
QUOTA_SHARE = float(os.environ.get("MEDIBOT_LLM_QUOTA_SHARE", "0.7"))
FEATURE_SWITCH = {"narrator": "MEDIBOT_NARRATOR", "second_opinion": "MEDIBOT_SECOND_OPINION",
                  "reader": "MEDIBOT_READER"}
FEATURE_SHARE = {"reader": 0.95}   # the reader is core understanding, not an extra: it may use more quota

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


def _env(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return None


def route(model: str) -> tuple[str, str | None, str]:
    """(url, key, model id) for a model name: "cline:google/gemini-3.8-flash" -> Cline gateway, else Groq."""
    if model.startswith("cline:"):
        return CLINE_URL, _env("MEDIBOT_LLM2_API_KEY"), model.split(":", 1)[1]
    return URL, _env("GROQ_API_KEY"), model


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
        self.enabled = bool(self.key or _env("MEDIBOT_LLM2_API_KEY")) and os.environ.get("MEDIBOT_LLM", "on") != "off"
        self.client = httpx.Client(timeout=float(os.environ.get("MEDIBOT_LLM_TIMEOUT", "4")))  # thread-safe
        self.limiters = {FAST: _Limiter(7000), STRONG: _Limiter(7000)}
        self.stats = {"calls": 0, "cache_hits": 0, "failures": 0}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(CACHE, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT, model TEXT, n INTEGER, PRIMARY KEY (day, model))")
        self.db_lock = threading.Lock()

    # ------------------------------------------------ quota guard
    @staticmethod
    def _day() -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def used_today(self, model: str) -> int:
        with self.db_lock:
            row = self.db.execute("SELECT n FROM usage WHERE day = ? AND model = ?", (self._day(), model)).fetchone()
        return row[0] if row else 0

    def _count(self, model: str) -> None:
        with self.db_lock:
            self.db.execute("INSERT INTO usage VALUES (?, ?, 1) ON CONFLICT (day, model) DO UPDATE SET n = n + 1",
                            (self._day(), model))
            self.db.commit()

    def allow(self, feature: str, model: str) -> tuple[bool, str]:
        """May an optional feature call the model now? (False, reason) when switched off or over its quota share."""
        if not self.enabled:
            return False, "LLM off"
        sw = FEATURE_SWITCH.get(feature)
        if sw and os.environ.get(sw, "on") == "off":
            return False, f"{sw}=off"
        limit = CLINE_DAILY_LIMIT if model.startswith("cline:") else DAILY_LIMIT.get(model, 1000)
        cap = int(limit * FEATURE_SHARE.get(feature, QUOTA_SHARE))
        used = self.used_today(model)
        if used >= cap:
            return False, f"daily quota guard: {used}/{DAILY_LIMIT.get(model, 1000)} used (cap {cap})"
        return True, ""

    def usage_line(self) -> str:
        short = {FAST: "20b", STRONG: "120b"}
        return "LLM today: " + ", ".join(f"{short.get(m, m)} {self.used_today(m)}/{DAILY_LIMIT[m]}" for m in DAILY_LIMIT)

    def cached(self, system: str, user: str, model: str) -> dict | None:
        """The cached answer for exactly this request, without calling the API (or None)."""
        k = self._k(system, user, model)
        with self.db_lock:
            row = self.db.execute("SELECT v FROM cache WHERE k = ?", (k,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _k(system: str, user: str, model: str) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": scrub(user)}]
        return hashlib.sha256(json.dumps([model, messages], ensure_ascii=False).encode()).hexdigest()

    def chat_json(self, system: str, user: str, *, model: str = FAST, max_tokens: int = 300,
                  max_wait: float = 2.0, reasoning_effort: str | None = None) -> dict | None:
        """Ask for a JSON object. Returns None on any problem (disabled, timeout, rate limit, bad JSON).
        reasoning_effort="low" (gpt-oss): fewer hidden reasoning tokens -> ~0.6 s instead of 1-3 s; used by the
        latency-budgeted callers (second opinion, narrator). Not part of the cache key when None (old entries stay)."""
        if not self.enabled:
            return None
        messages = [{"role": "system", "content": system}, {"role": "user", "content": scrub(user)}]
        k = self._k(system, user, model + (f"|effort={reasoning_effort}" if reasoning_effort else ""))
        with self.db_lock:
            row = self.db.execute("SELECT v FROM cache WHERE k = ?", (k,)).fetchone()
        if row:
            self.stats["cache_hits"] += 1
            return json.loads(row[0])
        est = (len(system) + len(user)) // 3 + max_tokens
        # the token-per-minute limiter protects the Groq free tier; the Cline gateway is paid per use
        if not model.startswith("cline:") and not self.limiters.setdefault(model, _Limiter(7000)).wait(est, max_wait):
            self.stats["failures"] += 1
            return None
        url, key, model_id = route(model)
        if not key:
            return None
        body = {"model": model_id, "messages": messages, "temperature": 0, "max_tokens": max_tokens,
                "response_format": {"type": "json_object"}}
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        for attempt in range(2):
            try:
                self.stats["calls"] += 1
                self._count(model)   # every request that reaches Groq counts against the daily limit
                r = self.client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
                if r.status_code == 429:
                    break
                r.raise_for_status()
                payload = r.json()
                if "choices" not in payload and isinstance(payload.get("data"), dict):
                    payload = payload["data"]                    # Cline gateway wraps the OpenAI shape in {"data": ...}
                content = payload["choices"][0]["message"]["content"] or ""
                found = re.search(r"\{.*\}", content, re.S)       # some models wrap the JSON in prose / code fences
                out = json.loads(found.group(0) if found else content)
                with self.db_lock:
                    self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)",
                                    (k, json.dumps(out, ensure_ascii=False)))
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
