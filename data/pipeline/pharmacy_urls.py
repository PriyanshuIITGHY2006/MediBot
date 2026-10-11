"""Product-page URLs for PharmEasy and Truemeds from their published sitemaps (Phase 9.7). No search is used.

  1. read each site's sitemap index (listed in robots.txt), keep only the product sitemaps
  2. download them politely (robots.txt checked, >= 1 s apart per host, cached in data/raw/pharmacy_sitemaps/)
  3. keep product-page URLs that pass prices.adapters.allowed_url()
  4. match each URL to the catalog with prices.matching.match_key (exact brand + strength + form, no fuzzy);
     a key shared by products with different compositions is ambiguous and dropped

Output: data/processed/pharmacy_urls.parquet (platform, url, product_id, slug)
The match is re-checked on every fetch against the name / composition the page itself shows (engine.py).
"""
from __future__ import annotations

import gzip
import re
import sys
import time
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from medibot.prices.adapters import USER_AGENT, RobotsGuard, allowed_url  # noqa: E402
from medibot.prices.matching import match_key, slug_text  # noqa: E402

RAW = ROOT / "data/raw/pharmacy_sitemaps"
OUT = ROOT / "data/processed/pharmacy_urls.parquet"
SITES = {
    "pharmeasy": ("pharmeasy.in", "https://pharmeasy.in/sitemap.xml",
                  re.compile(r"sitemap-(otc-products?|prescription-medicines?)(-\d+)?\.xml$")),
    "truemeds": ("www.truemeds.in", "https://www.truemeds.in/sitemap.xml",
                 re.compile(r"sitemap-medicines-\d+\.xml$")),   # English pages only (not -hi / -bn / -image ...)
}
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


class Polite:
    def __init__(self):
        self.client = httpx.Client(timeout=60, follow_redirects=True,
                                   headers={"User-Agent": USER_AGENT, "Accept-Language": "en-IN"})
        self.robots = RobotsGuard(self.client)
        self.last: dict[str, float] = {}

    def get(self, host: str, url: str) -> str | None:
        name = re.sub(r"[^a-zA-Z0-9.-]+", "_", url.split("://", 1)[1])
        cache = RAW / name
        if cache.exists():
            return cache.read_text()
        if not self.robots.allows(host, url):
            print(f"  robots.txt disallows {url}")
            return None
        wait = 1.2 - (time.time() - self.last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self.last[host] = time.time()
        r = self.client.get(url)
        if r.status_code != 200:
            print(f"  {r.status_code} {url}")
            return None
        body = gzip.decompress(r.content).decode() if url.endswith(".gz") else r.text
        RAW.mkdir(parents=True, exist_ok=True)
        cache.write_text(body)
        return body


def sitemap_urls(p: Polite, platform: str) -> list[str]:
    host, index, wanted = SITES[platform]
    todo, seen, products = [index], set(), []
    while todo:
        u = todo.pop()
        if u in seen:
            continue
        seen.add(u)
        body = p.get(host, u)
        if not body:
            continue
        locs = LOC.findall(body)
        if "<sitemapindex" in body:
            todo += [x for x in locs if x == index or wanted.search(x)]
        else:
            products += [x for x in locs if allowed_url(platform, x)]
        print(f"  {platform}: {len(seen)} sitemaps read, {len(products):,} product URLs", flush=True)
    return sorted(set(products))


def catalog_keys() -> dict[tuple, str]:
    """match key -> canonical product id; keys shared by different compositions are ambiguous (dropped)."""
    p = pd.read_parquet(ROOT / "data/processed/products.parquet",
                        columns=["canonical_id", "name", "composition_id", "is_alias", "all_discontinued"])
    p = p[~p["is_alias"] & ~p["all_discontinued"].fillna(False)]
    by: dict[tuple, set] = {}
    first: dict[tuple, str] = {}
    for cid, name, comp in zip(p["canonical_id"], p["name"], p["composition_id"]):
        core, form = match_key(name)
        if not core:
            continue
        k = (core, form)
        by.setdefault(k, set()).add(comp or f"none:{cid}")
        first.setdefault(k, cid)
    return {k: first[k] for k, comps in by.items() if len(comps) == 1}


def build() -> pd.DataFrame:
    p = Polite()
    keys = catalog_keys()
    print(f"catalog keys: {len(keys):,} unambiguous")
    rows = []
    for platform in SITES:
        urls = sitemap_urls(p, platform)
        hit = 0
        for u in urls:
            slug = slug_text(platform, u)
            core, form = match_key(slug)
            pid = keys.get((core, form)) or (keys.get((core, None)) if form is None else None)
            if pid:
                hit += 1
                rows.append({"platform": platform, "url": u, "product_id": pid, "slug": slug})
        print(f"{platform}: {len(urls):,} product URLs, {hit:,} matched to the catalog")
    df = pd.DataFrame(rows).drop_duplicates(["platform", "product_id"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"-> {OUT.relative_to(ROOT)}: {len(df):,} rows")
    return df


if __name__ == "__main__":
    build()
