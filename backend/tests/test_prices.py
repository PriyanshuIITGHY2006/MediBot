"""Phase 9: price adapters + engine. Parsers are tested on real product-page snippets (tests/fixtures)."""
import re
from pathlib import Path

import pytest

from medibot.prices.adapters import (Fetcher, RobotsGuard, USER_AGENT, allowed_url, parse_1mg, parse_apollo,
                                     parse_netmeds, parse_pharmeasy, parse_truemeds)

F = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("parser,fixture,price,per_unit", [
    (parse_1mg, "1mg_augmentin_625.html", 183.0, 18.3),
    (parse_apollo, "apollo_augmentin_625.html", 196.5, 19.65),
    (parse_netmeds, "netmeds_augmentin_625.html", 166.08, 16.61),
])
def test_parsers_read_real_pages(parser, fixture, price, per_unit):
    q = parser((F / fixture).read_text(), "https://example/x")
    assert q.price_inr == price and q.price_per_unit_inr == per_unit and q.pack_quantity == 10 and q.in_stock is True


def test_1mg_reads_its_own_price_not_the_substitute_block():
    q = parse_1mg((F / "1mg_augmentin_625.html").read_text(), "u")
    assert q.mrp_inr == 196.65  # Augmentin's MRP; the page's substitute block lists other products at Rs 110 / 156


@pytest.mark.parametrize("platform,url", [
    ("1mg", "https://www.1mg.com/search/all?name=augmentin"),
    ("netmeds", "https://www.netmeds.com/api/product/123"),
    ("1mg", "https://www.1mg.com/cart"),
    ("apollo", "https://evil.example.com/medicine/x"),
    ("pharmeasy", "https://pharmeasy.in/search/all?name=dolo"),
    ("pharmeasy", "https://evil.example.com/pharmeasy.in/online-medicine-order/x"),   # host is compared exactly
    ("truemeds", "https://www.truemeds.in/api/v1/x"),
])
def test_fetcher_refuses_disallowed_or_unknown_urls(platform, url):
    assert Fetcher().get(platform, url) is None  # returns before any network call


@pytest.fixture(scope="module")
def engine():
    from medibot.assistant import price_book
    from medibot.prices.engine import PriceEngine
    return PriceEngine(price_book(), live=False)


def test_engine_falls_back_to_labelled_snapshot(engine, tmp_path, monkeypatch):
    from medibot.catalog import load_catalog
    import medibot.prices.engine as eng
    monkeypatch.setattr(eng, "CACHE_PATH", tmp_path / "cache.sqlite")
    e = eng.PriceEngine(engine.snapshot, live=False)
    p = next(x for x in load_catalog().products.values() if x.name == "Shelcal 500 Tablet")
    qs = e.quotes(p)
    assert qs and all(q["source"] == "snapshot" and q["observed"] for q in qs)
    assert [q["price_inr"] for q in qs] == sorted(q["price_inr"] for q in qs)


def test_nppa_flag_never_on_snapshot_prices(engine):
    from medibot.catalog import load_catalog
    p = next(x for x in load_catalog().products.values() if x.composition_id and engine.snapshot.get(x.product_id))
    assert all(engine._above_ceiling(p, dict(q, source="snapshot")) is None for q in engine.snapshot[p.product_id])


def test_nppa_flag_on_live_price_above_ceiling(engine):
    from medibot.catalog import Product
    from medibot.prices.engine import nppa_ceilings
    (cid, per), ceiling = next(iter(nppa_ceilings().items()))
    p = Product("p", "X", None, "tablet", "c", cid, (), "otc", False, "", "")
    q = {"source": "live", "price_per_unit_inr": ceiling * 2, "pack_label": "10 tablets" if per == "unit" else "100 ml"}
    flag = engine._above_ceiling(p, q)
    assert flag and flag["ceiling_per_unit_inr"] == ceiling


# ---------------------------------------------------------------- 9.7 PharmEasy + Truemeds


@pytest.mark.parametrize("parser,fixture,url,price,mrp,qty,stock", [
    (parse_pharmeasy, "pharmeasy_allmox_250.html", "https://pharmeasy.in/online-medicine-order/allmox-250mg-tab-33750",
     24.42, 33.0, 10, False),
    (parse_pharmeasy, "pharmeasy_cissq_500_otc.html", "https://pharmeasy.in/health-care/products/cissq-500mg-tab-10-s-1647",
     131.53, 162.38, 10, True),
    (parse_truemeds, "truemeds_himalaya_diaper.html",
     "https://www.truemeds.in/medicine/himalaya-baby-medium-diaper-54-tm-1-dec-000007", 692.0, 865.0, 54, False),
])
def test_new_parsers_read_the_products_own_price(parser, fixture, url, price, mrp, qty, stock):
    q = parser((F / fixture).read_text(), url)
    assert (q.price_inr, q.mrp_inr, q.pack_quantity, q.in_stock) == (price, mrp, qty, stock) and q.page_name


def test_pharmeasy_otc_ignores_offers_for_other_urls():
    page = (F / "pharmeasy_cissq_500_otc.html").read_text()
    assert parse_pharmeasy(page, "https://pharmeasy.in/health-care/products/some-other-product-1") is not None  # canonical
    # the only offer on the page now belongs to another product (a substitute block); the canonical stays ours
    fake = re.sub(r'("url": *")https://pharmeasy\.in/health-care/products/cissq-500mg-tab-10-s-1647',
                  r'\1https://pharmeasy.in/health-care/products/other-product-99', page)
    assert fake != page
    assert parse_pharmeasy(fake, "https://pharmeasy.in/health-care/products/cissq-500mg-tab-10-s-1647") is None


def test_every_existing_catalog_url_passes_the_path_guard():
    import pandas as pd
    p = pd.read_parquet(Path(__file__).parents[2] / "data/processed/products.parquet",
                        columns=["url_1mg", "url_apollo", "url_netmeds"]).sample(20000, random_state=3)
    for col, pl in [("url_1mg", "1mg"), ("url_apollo", "apollo"), ("url_netmeds", "netmeds")]:
        urls = p[col].dropna()
        assert all(allowed_url(pl, u) for u in urls if u), col    # "/cart" no longer blocks "/drugs/cartigen-…"


class _Resp:
    def __init__(self, text):
        self.status_code, self.text = 200, text


class _Client:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def get(self, url):
        self.calls += 1
        return _Resp(self.text)


@pytest.mark.parametrize("robots,host,url,ok", [
    ("robots_pharmeasy.txt", "pharmeasy.in", "https://pharmeasy.in/online-medicine-order/allmox-250mg-tab-33750", True),
    ("robots_pharmeasy.txt", "pharmeasy.in", "https://pharmeasy.in/health-care/products/cissq-500mg-tab-10-s-1647", True),
    ("robots_pharmeasy.txt", "pharmeasy.in", "https://pharmeasy.in/search/all?name=dolo", False),
    ("robots_pharmeasy.txt", "pharmeasy.in", "https://pharmeasy.in/cart/", False),
    ("robots_truemeds.txt", "www.truemeds.in", "https://www.truemeds.in/medicine/dolo-650-tm-1-tab-1", True),
    ("robots_truemeds.txt", "www.truemeds.in", "https://www.truemeds.in/search?q=dolo", False),
])
def test_robots_guard_reads_the_real_files(robots, host, url, ok):
    g = RobotsGuard(_Client((F / robots).read_text()))
    assert g.allows(host, url) is ok


def test_robots_guard_is_cached_and_fail_closed():
    c = _Client((F / "robots_truemeds.txt").read_text())
    g = RobotsGuard(c)
    g.allows("www.truemeds.in", "https://www.truemeds.in/medicine/a")
    g.allows("www.truemeds.in", "https://www.truemeds.in/medicine/b")
    assert c.calls == 1

    class Down:
        def get(self, url):
            raise OSError("no network")
    assert RobotsGuard(Down()).allows("www.truemeds.in", "https://www.truemeds.in/medicine/a") is False


@pytest.mark.parametrize("a,b,same", [
    ("allmox-250mg-tab", "Allmox 250mg Tablet", True),
    ("Allmox 250Mg Strip Of 10 Tablets", "Allmox 250mg Tablet", True),
    ("dolo-650-tablet-15", "Dolo 650 Tablet", True),
    ("augmentin-625-duo-tab-10s", "Augmentin 625 Duo Tablet", True),
    ("calpol-250mg-susp-60ml", "Calpol 250mg Suspension", True),
    ("allmox-500mg-tab", "Allmox 250mg Tablet", False),       # strength differs
    ("pan-40-tab", "Pan 40 Injection", False),                 # form differs
    ("pan-d-cap", "Pan 40 Tablet", False),
])
def test_exact_matching(a, b, same):
    from medibot.prices.matching import same_product
    assert same_product(a, b) is same


def test_page_must_show_the_same_product():
    from medibot.catalog import Product
    from medibot.prices.engine import page_matches
    p = Product("p", "Allmox 250mg Tablet", None, "tablet", "Amoxycillin 250mg", "c", ("amoxicillin",), "schedule_h",
                True, "", "")
    assert page_matches(p, {"page_name": "Allmox 250Mg Strip Of 10 Tablets", "page_composition": None})
    assert not page_matches(p, {"page_name": "Allmox 500Mg Strip Of 10 Tablets"})
    assert not page_matches(p, {"page_name": "Allmox 250Mg Tablets", "page_composition": "Cefixime 200mg"})
    assert not page_matches(p, {"page_name": None})
