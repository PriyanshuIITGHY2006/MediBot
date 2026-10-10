"""Background price jobs (Phase 9.4 / 9.5).

  refresh  keep the most-asked products' live prices in the cache (polite: 1 req/s per host)
  audit    B2 "price match accuracy": the price the bot WOULD show vs a fresh live fetch of the same page

Usage:
  PYTHONPATH=backend .venv/bin/python -m medibot.prices.refresh refresh --top 300
  PYTHONPATH=backend .venv/bin/python -m medibot.prices.refresh audit --sample 40
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd

from medibot.catalog import load_catalog
from medibot.prices.adapters import Fetcher
from medibot.prices.engine import CACHE_TTL, PriceEngine

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "eval/reports"


def popular_products(n: int) -> list:
    """Most likely to be asked: the eval's policy medicines first, then by popularity, with pharmacy URLs."""
    cat = load_catalog()
    idx = pd.read_parquet(ROOT / "data/processed/search_index.parquet", columns=["canonical_id", "popularity"])
    ranked = idx.sort_values("popularity", ascending=False)["canonical_id"].drop_duplicates()
    out, seen = [], set()
    for pid in ranked:
        p = cat.products.get(pid)
        if p and p.urls and pid not in seen and not p.discontinued:
            out.append(p)
            seen.add(pid)
        if len(out) >= n:
            break
    return out


def refresh(top: int) -> dict:
    from medibot.assistant import price_book
    engine = PriceEngine(price_book(), live=True)
    prods = popular_products(top)
    jobs = [(pl, u) for p in prods for pl, u in p.urls
            if not ((h := engine._cached(u)) and time.time() - h[1] < CACHE_TTL)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as ex:  # one worker per host in practice; Fetcher spaces requests
        results = list(ex.map(lambda pu: engine._fetch_and_store(*pu), jobs))
    ok = sum(1 for r in results if r)
    return {"products": len(prods), "fetched": len(jobs), "ok": ok, "failed": len(jobs) - ok,
            "seconds": round(time.time() - t0, 1)}


def audit(sample: int, seed: int = 7) -> dict:
    """For each sampled (product, platform): shown price (cache if fresh, else snapshot) vs a fresh live fetch."""
    from medibot.assistant import price_book
    engine = PriceEngine(price_book(), live=False)  # what the bot shows without fetching
    fetcher = Fetcher()
    prods = popular_products(max(sample * 4, 200))
    random.Random(seed).shuffle(prods)
    rows = []
    for p in prods[:sample]:
        shown = {q["platform"]: q for q in engine.quotes(p, allow_live=False)}
        for platform, url in p.urls:
            live = fetcher.get(platform, url)
            if live is None:
                status = "delisted" if url in fetcher.delisted else "live_failed"
                rows.append({"product": p.name, "platform": platform, "status": status})
                continue
            s = shown.get(platform)
            if s is None:
                rows.append({"product": p.name, "platform": platform, "status": "no_shown_price",
                             "live": live.price_inr})
                continue
            # compare like with like: per-unit vs per-unit, or the same pack vs the same pack; otherwise skip
            if s.get("price_per_unit_inr") and live.price_per_unit_inr:
                a, b = s["price_per_unit_inr"], live.price_per_unit_inr
            elif s.get("pack_label") and live.pack_label and s["pack_label"] == live.pack_label:
                a, b = s["price_inr"], live.price_inr
            else:
                rows.append({"product": p.name, "platform": platform, "status": "not_comparable"})
                continue
            diff = abs(a - b) / b if b else 1.0
            rows.append({"product": p.name, "platform": platform, "shown": a, "live": b, "source": s.get("source"),
                         "observed": s.get("observed"), "rel_diff": round(diff, 4),
                         "status": "match" if diff <= 0.01 else "mismatch"})
    df = pd.DataFrame(rows)
    comparable = df[df["status"].isin(["match", "mismatch"])]
    by_source = comparable.groupby("source")["status"].apply(lambda s: round((s == "match").mean(), 4)).to_dict() \
        if len(comparable) else {}
    report = {
        "sampled_products": sample, "pairs": len(df), "comparable": len(comparable),
        "price_match_accuracy": round((comparable["status"] == "match").mean(), 4) if len(comparable) else None,
        "accuracy_by_source": by_source,
        "by_platform": comparable.groupby("platform")["status"].apply(lambda s: round((s == "match").mean(), 4)).to_dict()
        if len(comparable) else {},
        "live_failed": int((df["status"] == "live_failed").sum()) if len(df) else 0,
        "delisted": int((df["status"] == "delisted").sum()) if len(df) else 0,
        "not_comparable": int((df["status"] == "not_comparable").sum()) if len(df) else 0,
        "no_shown_price": int((df["status"] == "no_shown_price").sum()) if len(df) else 0,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"price-audit-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"report": report, "rows": rows}, indent=1, default=str))
    report["file"] = str(path.relative_to(ROOT))
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--top", type=int, default=300)
    a = sub.add_parser("audit")
    a.add_argument("--sample", type=int, default=40)
    args = ap.parse_args()
    out = refresh(args.top) if args.cmd == "refresh" else audit(args.sample)
    print(json.dumps(out, indent=2))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
