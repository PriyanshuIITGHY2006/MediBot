"""NPPA ceiling prices: values must equal the PDF exactly (NLEM 2022 lists, as on March 2026)."""
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "data/processed/nppa_ceiling.parquet"
pytestmark = pytest.mark.skipif(not PATH.exists(), reason="nppa not built")


@pytest.fixture(scope="module")
def current():
    d = pd.read_parquet(PATH)
    return d[d.status == "current"]


@pytest.mark.parametrize(
    "composition,form,release,price",
    [
        ("Glimepiride 1 mg", "tablet", "IR", 3.78),
        ("Glimepiride 2 mg", "tablet", "IR", 5.94),
        ("Metformin 500 mg", "tablet", "IR", 2.07),
        ("Metformin 1000 mg", "tablet", "IR", 3.57),
        ("Metformin 1000 mg", "tablet", "MR", 4.15),
        ("Teneligliptin 20 mg", "tablet", "IR", 11.35),
        ("Allopurinol 100 mg", "tablet", "IR", 1.93),
    ],
)
def test_known_ceiling(current, composition, form, release, price):
    rows = current[(current.composition == composition) & (current.form == form) & (current.release == release)]
    assert not rows.empty, composition
    assert price in set(rows.ceiling_price_inr)


def test_flag_table_uses_highest_ceiling():
    flag = pd.read_parquet(ROOT / "data/processed/nppa_ceiling_flag.parquet")
    d = pd.read_parquet(PATH)
    cur = d[d.status == "current"].groupby(["composition_id", "per"]).ceiling_price_inr.max()
    merged = flag.set_index(["composition_id", "per"]).ceiling_price_inr
    assert (merged == cur.loc[merged.index]).all()


def test_historical_never_in_flag_table():
    flag = pd.read_parquet(ROOT / "data/processed/nppa_ceiling_flag.parquet")
    d = pd.read_parquet(PATH)
    only_hist = set(d[d.status == "historical"].composition_id) - set(d[d.status == "current"].composition_id)
    assert not (set(flag.composition_id) & only_hist)
