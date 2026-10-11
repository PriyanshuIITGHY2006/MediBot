"""Pharmacy price adapters (Phase 9): parse a product page into a Quote. Product pages only.

robots.txt (checked 2026-10-10 / 2026-10-11): product pages are allowed on 1mg, Apollo, Netmeds, PharmEasy and
Truemeds; search pages and /api/ endpoints are disallowed and are never requested. Product URLs for PharmEasy and
Truemeds come from their published sitemaps (data/pipeline/pharmacy_urls.py), never from search.
Every request passes three guards: the exact host, a per-site allow-list of product paths, and the site's own
robots.txt for our user agent (read at most once a day; if it can't be read, nothing is fetched from that host).
Requests are low-volume, identified, rate-limited per host and cached.

Each adapter has a pure `parse(html, url)` (unit-tested on saved page snippets) and shares one polite fetcher.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import threading
import time
import urllib.robotparser
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit
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
    page_name: str | None = None         # the product name the page shows (match verification)
    page_composition: str | None = None  # the composition the page shows (match verification)

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


def _next_data(page: str) -> dict | None:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1)).get("props", {}).get("pageProps", {})
    except json.JSONDecodeError:
        return None


def _own_offer(page: str, url: str) -> tuple[dict, dict] | None:
    """The schema.org offer for THIS page (its url equals the page URL), never a substitute's offer below it."""
    canon = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', page)
    want = {url.rstrip("/"), (canon.group(1).rstrip("/") if canon else "")}
    for item, offer in _ld_offers(page):
        if str(offer.get("url", "")).rstrip("/") in want and _money(offer.get("price")) is not None:
            return item, offer
    return None


def _pack_from_unit(text: str | None) -> tuple[float | None, str | None]:
    """PharmEasy "10 Tablet(s) in Strip" / "100 ml in Bottle" -> (10, "strip of 10")."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(tablet|capsule|ml|gm|g|sachet|unit|piece|lozenge)", text or "", re.I)
    if not m:
        return None, None
    return float(m.group(1)), (text or "").strip()


def parse_pharmeasy(page: str, url: str) -> Quote | None:
    """Prescription pages: Next.js productDetails (sale price, MRP, pack, stock, composition).
    OTC pages: the page's own schema.org offer with its MRP price specification."""
    pp = _next_data(page) or {}
    d = pp.get("productDetails") if isinstance(pp.get("productDetails"), dict) else None
    if d and _money(d.get("salePrice")) is not None:
        qty, label = _pack_from_unit(d.get("measurementUnit"))
        if qty is None:
            qty, label = _pack_from_name(d.get("name") or "")
        comps = d.get("compositions") or []
        comp = " + ".join(f"{c.get('name', '')} {c.get('strength', '') or ''}".strip()
                          for c in comps if isinstance(c, dict)) or None
        stock = (d.get("productAvailabilityFlags") or {}).get("isAvailable", d.get("isAvailable"))
        return Quote("pharmeasy", url, _money(d["salePrice"]), _money(d.get("costPrice")), qty, label,
                     None if stock is None else bool(stock), None, _now(), d.get("name"), comp)
    own = _own_offer(page, url)
    if not own:
        return None
    item, offer = own
    mrp = next((_money(s.get("price")) for s in offer.get("priceSpecification") or []
                if isinstance(s, dict) and str(s.get("name", "")).upper() == "MRP"), None)
    name = htmllib.unescape(item.get("name") or "")
    qty, label = _pack_from_name(name)
    if qty is None:
        m = re.search(r"(?:strip|pack|bottle|box) of (\d+)", name, re.I)
        qty, label = (float(m.group(1)), m.group(0)) if m else (None, None)
    stock = None if not offer.get("availability") else str(offer["availability"]).endswith("InStock")
    return Quote("pharmeasy", url, _money(offer["price"]), mrp, qty, label, stock, None, _now(), name, None)


def parse_truemeds(page: str, url: str) -> Quote | None:
    """Next.js currentMed.product: selling price, MRP, pack size, stock, composition (substitutes are separate)."""
    pp = _next_data(page) or {}
    p = ((pp.get("currentMed") or {}).get("product")) or {}
    price = _money(p.get("sellingPrice"))
    if price is None:
        own = _own_offer(page, url)
        if not own:
            return None
        price = _money(own[1].get("price"))
    qty = _money(p.get("packSize"))
    stock = p.get("available")
    return Quote("truemeds", url, price, _money(p.get("mrp")), qty, p.get("packForm"),
                 None if stock is None else bool(stock), None, _now(), p.get("skuName"), p.get("composition"))


PARSERS = {"1mg": parse_1mg, "netmeds": parse_netmeds, "apollo": parse_apollo, "pharmeasy": parse_pharmeasy,
           "truemeds": parse_truemeds}
HOSTS = {"1mg": "www.1mg.com", "netmeds": "www.netmeds.com", "apollo": "www.apollopharmacy.in",
         "pharmeasy": "pharmeasy.in", "truemeds": "www.truemeds.in"}
# product-page paths only (stricter than robots.txt); anything else is refused before any request
PRODUCT_PATHS = {
    "1mg": ("/drugs/", "/otc/"),
    "netmeds": ("/prescriptions/", "/non-prescriptions/", "/product/"),
    "apollo": ("/medicine/", "/otc/"),
    "pharmeasy": ("/online-medicine-order/", "/health-care/products/"),
    "truemeds": ("/medicine/", "/otc/"),
}
# whole path segments only: "/cart" must not block "/drugs/cartigen-duo-tablet"
DISALLOWED = re.compile(r"/(search|cart|checkout|account|my-account|login|offers?|upload[\w-]*)(/|$)|/api/(?!service/)")


def allowed_url(platform: str, url: str) -> bool:
    """Exact host (not a substring test: "evil.com/pharmeasy.in" fails), product path, no search/api/cart."""
    try:
        u = urlsplit(url)
    except ValueError:
        return False
    return (platform in PARSERS and u.scheme == "https" and u.hostname == HOSTS[platform]
            and u.path.startswith(PRODUCT_PATHS[platform]) and not DISALLOWED.search(u.path) and not u.query)


class RobotsGuard:
    """Each host's robots.txt for our user agent, read at most once a day. Fail-closed: unreadable -> no fetch."""
    TTL = 24 * 3600

    def __init__(self, client: httpx.Client):
        self.client, self.lock = client, threading.Lock()
        self.parsers: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}

    def allows(self, host: str, url: str) -> bool:
        with self.lock:
            hit = self.parsers.get(host)
            if hit is None or time.time() - hit[0] > self.TTL:
                rp = None
                try:
                    r = self.client.get(f"https://{host}/robots.txt")
                    if r.status_code == 200:
                        rp = urllib.robotparser.RobotFileParser()
                        rp.parse(r.text.splitlines())
                except Exception:  # noqa: BLE001 - unreadable robots.txt -> fetch nothing from that host
                    rp = None
                hit = self.parsers[host] = (time.time(), rp)
        rp = hit[1]
        return bool(rp and rp.can_fetch(USER_AGENT, url))


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
        self.robots = RobotsGuard(self.client)

    def get(self, platform: str, url: str) -> Quote | None:
        if not allowed_url(platform, url):
            return None  # only product pages on the exact known host, never search / api / cart
        host = HOSTS[platform]
        if not self.robots.allows(host, url):
            return None
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
