"""Acceptance tests on the built catalog (run build_catalog.py first)."""
import csv
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "data/processed/products.parquet"

pytestmark = pytest.mark.skipif(not PRODUCTS.exists(), reason="catalog not built")


@pytest.fixture(scope="module")
def by_key():
    p = pd.read_parquet(PRODUCTS, columns=["key", "product_id", "canonical_id", "composition_id", "substitutable",
                                           "composition_status"])
    canon = p.set_index("product_id")
    # the bot always works on the canonical product of an alias (same brand, maker and composition)
    p = p.assign(substitutable=p["canonical_id"].map(canon["substitutable"]))
    return p.set_index("key")


def _pairs():
    with open(ROOT / "data/reference/golden_pairs.csv", newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("pair", _pairs(), ids=lambda r: f"{r['a']} ~ {r['b']}")
def test_golden_pair(by_key, pair):
    a, b = pair["a"].lower(), pair["b"].lower()
    if pair["expected"] == "different" and (a not in by_key.index or b not in by_key.index):
        pytest.skip("one side not in catalog")
    assert a in by_key.index, f"missing {pair['a']}"
    assert b in by_key.index, f"missing {pair['b']}"
    ra, rb = by_key.loc[a], by_key.loc[b]
    if pair["expected"] == "same":
        assert ra.substitutable and rb.substitutable, "both must be substitutable"
        assert ra.composition_id == rb.composition_id, pair["reason"]
    else:
        assert ra.composition_id is None or ra.composition_id != rb.composition_id, pair["reason"]


def test_no_truncation_risk_is_substitutable():
    p = pd.read_parquet(PRODUCTS, columns=["composition_status", "substitutable"])
    assert not p.loc[p.composition_status.isin(["truncation_risk", "conflict", "missing"]), "substitutable"].any()


def test_unstated_strength_is_not_substitutable():
    p = pd.read_parquet(PRODUCTS, columns=["strengths_complete", "substitutable"])
    assert not p.loc[~p.strengths_complete, "substitutable"].any()
