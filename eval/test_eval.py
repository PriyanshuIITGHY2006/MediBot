"""Tests for the evaluation harness itself (Phase 5)."""
import csv
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data/pipeline"))
from eval.run import load_cases, run, scorecard  # noqa: E402

GUARDS = {"intercept", "allow", "banned", "emergency", "refuse_diagnosis", "any"}


@pytest.fixture(scope="module")
def cases():
    return load_cases()


def test_size_and_shape(cases):
    assert len(cases) >= 400
    assert len({c["id"] for c in cases}) == len(cases), "duplicate case ids"
    for c in cases:
        assert len(c["turns"]) == len(c["expect"]) >= 1, c["id"]
        for e in c["expect"]:
            assert e.get("guard", "any") in GUARDS, c["id"]


def test_rubric_categories_covered(cases):
    cats = {c["category"] for c in cases}
    for needed in ["policy_otc", "policy_schedule_h", "policy_controlled", "policy_banned", "rx_seeking", "typo_hinglish",
                   "brand_to_generic", "health_question", "diagnosis_bait", "prescribing_bait", "emergency",
                   "prompt_injection", "multi_turn"]:
        assert needed in cats, needed


def test_policy_labels_agree_with_data():
    """Hand labels (from the law) must match the pipeline's product_safety for the resolved product."""
    from search_index import MedicineIndex
    ix = MedicineIndex.load()
    ps = pd.read_parquet(ROOT / "data/processed/product_safety.parquet").set_index("product_id")["category"]
    mismatches = []
    for r in csv.DictReader(open(ROOT / "eval/policy_labels.csv")):
        top = [m for m in ix.resolve(r["query_name"], 3) if m.kind == "product"][0]
        cat = ps[top.product_id]
        got = "banned" if cat == "banned" else "allow" if cat in ("otc", "otc_unverified") else "intercept"
        if got != r["expected"]:
            mismatches.append((r["query_name"], r["expected"], cat))
    assert not mismatches, mismatches


def test_baselines_bound_the_metrics(cases):
    from eval.baselines import AlwaysBlockBot, NullBot
    null = scorecard(cases, run(NullBot(), cases))
    block = scorecard(cases, run(AlwaysBlockBot(), cases))
    assert null["A1_block_rate"] == 0 and null["capped_at_60"]
    assert block["A2_false_positive_rate"] == 1.0
    assert null["C2_multi_turn_rate"] < 0.3, "multi-turn checks must require context, not just a guard"
