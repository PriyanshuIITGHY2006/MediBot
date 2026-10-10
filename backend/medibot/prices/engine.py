"""Price engine (Phase 9): live -> cache -> snapshot, every quote labelled with where and when it came from.

  cache     data/interim/price_cache.sqlite, fresh for CACHE_TTL (6 h); a fresh entry is used without fetching
  live      polite product-page fetch (1 req/s per host, 3 s timeout), only when MEDIBOT_LIVE_PRICES=on
  snapshot  the dated dataset prices (A-Z 2022, tata_1mg 2025, Netmeds 2025/2026) when nothing fresher exists
Also: NPPA ceiling check on live/cached prices only (never on old snapshots, see DATA_QUALITY.md).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

from medibot.catalog import Product
from medibot.prices.adapters import Fetcher, Quote

ROOT = Path(__file__).resolve().parents[3]
CACHE_TTL = 6 * 3600
LIVE_BUDGET = float(os.environ.get("MEDIBOT_LIVE_BUDGET", "2.5"))  # seconds a reply may wait for live prices
CACHE_PATH = ROOT / "data/interim/price_cache.sqlite"


@lru_cache(maxsize=1)
def nppa_ceilings() -> dict[tuple[str, str], float]:
    f = pd.read_parquet(ROOT / "data/processed/nppa_ceiling_flag.parquet")
    return {(r.composition_id, r.per): float(r.ceiling_price_inr) for r in f.itertuples()}


class PriceEngine:
    def __init__(self, snapshot: dict[str, list[dict]], live: bool | None = None):
        self.snapshot = snapshot
        self.live = (os.environ.get("MEDIBOT_LIVE_PRICES", "off") == "on") if live is None else live
        self.fetcher = Fetcher()
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(CACHE_PATH, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS quotes (url TEXT PRIMARY KEY, platform TEXT, ts REAL, quote TEXT)")
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=6)  # slow fetches keep running after the reply and warm the cache
        self.stats = {"live": 0, "cache": 0, "snapshot": 0, "live_failed": 0, "live_late": 0}

    # ------------------------------------------------ cache
    def _cached(self, url: str) -> tuple[dict, float] | None:
        with self.lock:
            row = self.db.execute("SELECT quote, ts FROM quotes WHERE url = ?", (url,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def _store(self, q: Quote) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO quotes VALUES (?, ?, ?, ?)",
                            (q.url, q.platform, time.time(), json.dumps(q.as_dict())))
            self.db.commit()

    def _fetch_and_store(self, platform: str, url: str) -> Quote | None:
        q = self.fetcher.get(platform, url)
        if q:
            self._store(q)
        return q

    # ------------------------------------------------ public
    def quotes_many(self, products: list[Product], allow_live: bool = True) -> dict[str, list[dict]]:
        """Quotes for several products with ONE shared wait: all live fetches start together."""
        if self.live and allow_live:
            pending = []
            for p in products:
                for platform, url in p.urls:
                    hit = self._cached(url)
                    if not (hit and time.time() - hit[1] < CACHE_TTL):
                        pending.append(self.pool.submit(self._fetch_and_store, platform, url))
            if pending:
                done, late = wait(pending, timeout=LIVE_BUDGET)
                self.stats["live_late"] += len(late)
        # everything that arrived in time is now in the cache; assemble without fetching again
        return {p.product_id: self.quotes(p, allow_live=False) for p in products}

    def quotes(self, product: Product, allow_live: bool = True) -> list[dict]:
        """One quote per platform, cheapest first. Each has 'source' (live|cached|snapshot) and 'observed'."""
        by_platform: dict[str, dict] = {}
        todo: list[tuple[str, str]] = []
        for platform, url in product.urls:
            hit = self._cached(url)
            if hit and time.time() - hit[1] < CACHE_TTL:
                q = dict(hit[0], source="cached", observed=hit[0]["fetched_at"])
                by_platform[platform] = q
                self.stats["cache"] += 1
            else:
                todo.append((platform, url))
        if todo and self.live and allow_live:
            futures = {self.pool.submit(self._fetch_and_store, pl, u): pl for pl, u in todo}
            done, late = wait(futures, timeout=LIVE_BUDGET)  # never make the user wait longer than the budget
            self.stats["live_late"] += len(late)
            for f in done:
                q = f.result()
                if q:
                    by_platform[futures[f]] = dict(q.as_dict(), source="live", observed=q.fetched_at)
                    self.stats["live"] += 1
                else:
                    self.stats["live_failed"] += 1
        for q in self.snapshot.get(product.product_id, []):  # fill platforms with no fresher quote
            if q["platform"] not in by_platform:
                by_platform[q["platform"]] = dict(q, source="snapshot", in_stock=None)
                self.stats["snapshot"] += 1
        out = sorted(by_platform.values(), key=lambda q: q["price_inr"])
        for q in out:
            q["above_nppa_ceiling"] = self._above_ceiling(product, q)
        return out

    def _above_ceiling(self, product: Product, q: dict) -> dict | None:
        if q.get("source") == "snapshot" or not product.composition_id or not q.get("price_per_unit_inr"):
            return None  # old snapshot prices predate NLEM 2022 ceilings -> never flagged
        unit = "unit" if (q.get("pack_label") or "").lower().find("ml") < 0 else "ml"
        ceiling = nppa_ceilings().get((product.composition_id, unit))
        if ceiling and q["price_per_unit_inr"] > ceiling * 1.0001:
            return {"ceiling_per_unit_inr": ceiling, "source": "NPPA ceiling price (NLEM 2022, as on March 2026)"}
        return None


def freshness(q: dict) -> str:
    """Human label: 'live now', 'checked 2 h ago', 'as of 2025-03'."""
    if q.get("source") == "live":
        return "live now"
    if q.get("source") == "cached":
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(q["observed"])
            hours = int(age.total_seconds() // 3600)
            return "checked just now" if hours < 1 else f"checked {hours} h ago"
        except Exception:  # noqa: BLE001
            return "recently checked"
    return f"as of {q.get('observed', 'an earlier date')}"
