"""Phase 8: substitute engine. Protects rubric B1 (savings) and B3 (identical composition + advisory)."""
import pytest

from medibot.assistant import price_book
from medibot.catalog import load_catalog
from medibot.substitutes import ADVISORY, find_substitutes


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def product(cat, name):
    return next(p for p in cat.products.values() if p.name == name)


@pytest.mark.parametrize("name", ["Augmentin 625 Duo Tablet", "Dolo 650 Tablet", "Shelcal 500 Tablet", "PAN 40 Tablet"])
def test_identical_and_cheapest_first(cat, name):
    t = product(cat, name)
    res = find_substitutes(t, cat, price_book())
    assert res.substitutes, name
    assert all(s.composition_id == t.composition_id for s in res.substitutes)
    prices = [s.price_per_unit_inr for s in res.substitutes]
    assert prices == sorted(prices)
    assert all(s.savings_percentage > 0 for s in res.substitutes)
    assert all(s.product_id != t.product_id for s in res.substitutes)


def test_augmentin_savings_and_jan_aushadhi(cat):
    res = find_substitutes(product(cat, "Augmentin 625 Duo Tablet"), cat, price_book())
    assert res.substitutes[0].savings_percentage >= 50
    ja = [s for s in res.substitutes if s.tier == "jan_aushadhi"]
    assert ja and ja[0].price_per_unit_inr == pytest.approx(9.64, abs=0.01)


def test_every_card_is_verified_and_advised(cat):
    res = find_substitutes(product(cat, "Dolo 650 Tablet"), cat, price_book())
    for s in res.substitutes:
        c = s.as_contract()
        assert c["composition_identically_verified"] is True
        assert c["user_advisory"] == ADVISORY and "doctor or pharmacist" in ADVISORY


def test_banned_product_gets_no_substitutes(cat):
    res = find_substitutes(product(cat, "Cheston Cold Tablet"), cat, price_book())
    assert not res.substitutes and "banned" in res.note


def test_release_type_must_match(cat):
    """The Composition ID encodes the release type, so an SR tablet's substitutes are SR tablets."""
    t = product(cat, "Glycomet 500 SR Tablet")
    res = find_substitutes(t, cat, price_book())
    assert res.substitutes
    for s in res.substitutes:
        if s.tier == "brand":
            sub = cat.products[s.product_id]
            assert sub.composition_id == t.composition_id
            assert "sr" in sub.name.lower() or "sustained" in sub.name.lower() or "er" in sub.name.lower().split()


def test_name_suggesting_extra_ingredient_is_excluded(cat):
    res = find_substitutes(product(cat, "Allegra 120mg Tablet"), cat, price_book(), limit=50)
    assert not any("d plus" in s.brand_name.lower() for s in res.substitutes)  # "Allerhin D Plus" data error


def test_discontinued_never_suggested(cat):
    res = find_substitutes(product(cat, "Augmentin 625 Duo Tablet"), cat, price_book(), limit=50)
    assert not any(cat.products[s.product_id].discontinued for s in res.substitutes if s.tier == "brand")


def test_ordinal_follow_up_uses_the_list(cat):
    from medibot.assistant import Assistant
    a = Assistant()
    sid = a.start_session()["session_id"]
    first = a.query(sid, "cheaper alternative to augmentin 625")
    cheapest = a.query(sid, "where is the cheapest one available?")
    assert cheapest["detected_medication"]["product_id"] == first["substitutes"][0]["product_id"] \
        or first["substitutes"][0]["tier"] == "jan_aushadhi"
    assert cheapest["safety_guard"]["intercept_triggered"]  # still an antibiotic -> still the mandated prompt
