"""Pharmacy price adapters (Phase 9): parse a product page into a Quote. Product pages only.

robots.txt (checked 2026-10-10): product pages are allowed on 1mg, Apollo and Netmeds; search pages and
/api/ endpoints are disallowed and are never requested. PharmEasy is not fetched (no product URLs without
its disallowed search). Requests are low-volume, identified, rate-limited per host and cached.

Each adapter has a pure `parse(html, url)` (unit-tested on saved page snippets) and shares one polite fetcher.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import httpx

USER_AGENT = "MediBotPriceCheck/0.1 (hackathon prototype; low-volume product-page price checks)"


@dataclass
class Quote:
    platform: str
    url: str
    price_inr: float                 # selling price for the pack
    mrp_inr: float | None
    pack_quantity: float | None      # units in the pack (tablets / ml)
    pack_label: str | None
    in_stock: bool | None
    delivery_eta: str | None
    fetched_at: str                  # ISO time of the fetch

    @property
    def price_per_unit_inr(self) -> float | None:
        return round(self.price_inr / self.pack_quantity, 2) if self.pack_quantity else None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["price_per_unit_inr"] = self.price_per_unit_inr
        return d


def _money(text) -> float | None:
    if text is None:
        return None
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", str(text))
    return float(m.group(1).replace(",", "")) if m else None


def _pack_from_name(name: str) -> tuple[float | None, str | None]:
    """"Augmentin 625 Duo Tablet 10's" -> (10, "10's"); "Syrup 100ml" -> (100, "100 ml")."""
    m = re.search(r"\b(\d+)\s*['’]?\s*s\b", name, re.I)
    if m:
        return float(m.group(1)), f"{m.group(1)}'s"
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*ml\b", name, re.I)
    if m:
        return float(m.group(1)), f"{m.group(1)} ml"
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:gm|g|grams?)\b", name, re.I)
    if m:
        return float(m.group(1)), f"{m.group(1)} g"
    return None, None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- parsers


def parse_1mg(page: str, url: str) -> Quote | None:
    i = page.find("__INITIAL_STATE__")
    if i < 0:
        return None
    st, _ = json.JSONDecoder().raw_decode(page[page.index("{", i):])
    dyn = st.get("drugPageReducer", {}).get("dynamicData", {})
    box = (dyn.get("priceBox") or {}).get("priceList") or [{}]
    first = box[0]
    price = _money(htmllib.unescape(((first.get("discount") or {}).get("price")) or ""))
    mrp = _money(((first.get("mrp") or {}).get("price")))
    if price is None:  # no discount shown -> selling at MRP
        price = mrp
    if price is None:  # fall back to the schema.org offer embedded in the page
        offer = (st.get("drugPageReducer", {}).get("staticData", {}).get("metaData", {}).get("schema", {})
                 .get("drug", {}).get("offers") or {})
        price = _money(offer.get("price"))
    if price is None:
        return None
    pd_ = dyn.get("priceData") or {}
    qty = pd_.get("sellingQuantity")
    return Quote("1mg", url, price, mrp, float(qty) if qty else None, pd_.get("packSizes"),
                 pd_.get("isSkuInStock"), None, _now())


def _ld_offers(page: str) -> list[tuple[dict, dict]]:
    out = []
    for block in re.findall(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", page, re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for x in (data if isinstance(data, list) else data.get("@graph", [data])):
            if isinstance(x, dict) and isinstance(x.get("offers"), dict):
                out.append((x, x["offers"]))
    return out


def parse_netmeds(page: str, url: str) -> Quote | None:
    for item, offer in _ld_offers(page):
        price = _money(offer.get("price"))
        if price is None:
            continue
        name = htmllib.unescape(item.get("name") or "")
        qty, label = _pack_from_name(name)
        stock = None if not offer.get("availability") else offer["availability"].endswith("InStock")
        return Quote("netmeds", url, price, None, qty, label, stock, None, _now())
    return None


def parse_apollo(page: str, url: str) -> Quote | None:
    """Apollo is a Next.js app: the schema.org Drug offer sits inside escaped flight data."""
    text = page.replace('\\"', '"')
    m = re.search(r'"offers":\{"@type":"Offer".*?"price":([\d.]+).*?\}', text, re.S)
    if not m:
        for _, offer in _ld_offers(page):
            if _money(offer.get("price")):
                m = re.match(r"([\d.]+)", str(offer["price"]))
                break
    if not m:
        return None
    price = float(m.group(1))
    avail = re.search(r'"availability":"https?://schema\.org/(\w+)"', text)
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    name = htmllib.unescape(title.group(1)) if title else ""
    nm = re.search(r'"name":"([^"]+)"', text[m.end():m.end() + 400])
    # the product's own pack: first "mou" (measure of unit) / "pack_size"; later ones belong to substitutes
    mou = re.search(r'"mou":"?(\d+(?:\.\d+)?)', text) or re.search(r'"pack_size":"?(\d+(?:\.\d+)?)', text)
    if mou:
        qty, label = float(mou.group(1)), f"{mou.group(1)}'s"
    else:
        qty, label = _pack_from_name(name + " " + (nm.group(1) if nm else ""))
    return Quote("apollo", url, price, None, qty, label, (avail.group(1) == "InStock") if avail else None, None, _now())


PARSERS = {"1mg": parse_1mg, "netmeds": parse_netmeds, "apollo": parse_apollo}
HOSTS = {"1mg": "www.1mg.com", "netmeds": "www.netmeds.com", "apollo": "www.apollopharmacy.in"}
DISALLOWED = re.compile(r"/search|/api/(?!service/)|/cart|/checkout")


# ---------------------------------------------------------------- polite fetcher


class Fetcher:
    def __init__(self, min_interval: float = 1.0, timeout: float = 12.0):
        # Generous transfer timeout (Netmeds pages are ~3.5 MB). The user never waits for this: replies wait at most
        # LIVE_BUDGET (engine.py) and a slower fetch finishes in the background to warm the cache.
        self.min_interval = min_interval
        self.client = httpx.Client(timeout=timeout, follow_redirects=True,
                                   headers={"User-Agent": USER_AGENT, "Accept-Language": "en-IN"})
        self.last: dict[str, float] = {}
        self.lock = threading.Lock()
        self.delisted: set[str] = set()

    def get(self, platform: str, url: str) -> Quote | None:
        if platform not in PARSERS or HOSTS[platform] not in url or DISALLOWED.search(url):
            return None  # only product pages on known hosts, never search / api / cart
        host = HOSTS[platform]
        with self.lock:
            wait = self.min_interval - (time.time() - self.last.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            self.last[host] = time.time()
        try:
            r = self.client.get(url)
            if r.status_code == 404:
                self.delisted.add(url)  # the pharmacy no longer lists this product
                return None
            if r.status_code != 200:
                return None
            return PARSERS[platform](r.text, url)  # keyed by the URL we asked for (cache), not the redirect
        except Exception:  # noqa: BLE001 - a failed live fetch falls back to cache / snapshot
            return None
