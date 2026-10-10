"""Phase 9: price adapters + engine. Parsers are tested on real product-page snippets (tests/fixtures)."""
from pathlib import Path

import pytest

from medibot.prices.adapters import Fetcher, parse_1mg, parse_apollo, parse_netmeds

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
    ("pharmeasy", "https://pharmeasy.in/online-medicine-order/x"),
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
