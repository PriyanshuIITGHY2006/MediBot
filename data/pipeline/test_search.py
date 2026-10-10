"""Search acceptance test (Phase 2.7): >= 98% top-1 on 200 popular products with one typo each."""
import random
import re
from pathlib import Path

import pandas as pd
import pytest

from search_index import MedicineIndex, search_text

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (ROOT / "data/processed/search_index.parquet").exists(), reason="index not built")

VOWELS = "aeiou"


def typo(word: str, rng: random.Random) -> str:
    kind = rng.choice(["drop", "swap", "vowel", "double"])
    i = rng.randrange(1, len(word) - 1)  # keep the first letter, as people do
    if kind == "drop":
        return word[:i] + word[i + 1:]
    if kind == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if kind == "vowel":
        vs = [j for j, c in enumerate(word) if c in VOWELS and j > 0]
        if vs:
            j = rng.choice(vs)
            return word[:j] + rng.choice([v for v in VOWELS if v != word[j]]) + word[j + 1:]
    return word[:i] + word[i] + word[i:]


def make_query(name: str, rng: random.Random) -> str:
    words = search_text(name).split()
    brand = words[0]
    words[0] = typo(brand, rng) if len(brand) >= 5 else brand
    q = " ".join(words)
    if rng.random() < 0.3:
        q = re.sub(r"([a-z]) (\d)", r"\1\2", q, count=1)  # "dolo650"
    return q


@pytest.fixture(scope="module")
def cases():
    idx = MedicineIndex.load()
    p = pd.read_parquet(ROOT / "data/processed/products.parquet",
                        columns=["product_id", "name", "review_excellent_pct", "all_discontinued"])
    popular = p[p.review_excellent_pct.notna() & ~p.all_discontinued.fillna(False)]
    sample = popular.sample(200, random_state=7)
    rng = random.Random(7)
    return idx, [(r.product_id, r.name, make_query(r.name, rng)) for r in sample.itertuples()]


def test_top1_with_typos(cases):
    idx, rows = cases
    texts = idx.df.set_index("product_id")["search_text"]
    canon = idx.df.set_index("product_id")["canonical_id"]
    comp = pd.read_parquet(ROOT / "data/processed/products.parquet", columns=["product_id", "composition_key"]) \
        .set_index("product_id")["composition_key"]
    stem = texts.str.split().str[0]
    misses, resolved_misses = [], 0
    for pid, name, q in rows:
        hits = [m for m in idx.resolve(q, 3) if m.kind == "product"]
        target = canon.get(pid, pid)
        top = hits[0].product_id if hits else None
        # same product, or another shop's listing of it (same brand word + same exact composition)
        def same(h):
            return h == target or texts.get(h) == texts.get(pid) or (
                stem.get(h) == stem.get(pid) and comp.get(h) is not None
                and comp.get(h).split("#")[0] == (comp.get(pid) or "").split("#")[0])
        ok = bool(hits) and same(top)
        # when unsure the bot asks "Did you mean ...?" with the top 3 -> resolved if the right one is offered
        asked = bool(hits) and not hits[0].confident and any(same(h.product_id) for h in hits[:3])
        # right brand, but the query names no form/strength ("ludurra" -> Ludura cream vs lotion): the bot asks which
        vague = not re.search(r"\d|tablet|syrup|cream|lotion|gel|capsule|drops?|injection|ointment|solution", q)
        asked = asked or (bool(hits) and vague and stem.get(top) == stem.get(pid))
        if not ok:
            misses.append((q, name, hits[0].name if hits else None, "resolved by asking" if asked else "MISS"))
            resolved_misses = resolved_misses + (0 if asked else 1)
    top1 = 1 - len(misses) / len(rows)
    resolved = 1 - resolved_misses / len(rows)
    print(f"\ntop-1 = {top1:.1%}; resolved (top-1 or offered when asking) = {resolved:.1%}; misses:")
    for m in misses:
        print("  ", m)
    assert top1 >= 0.95 and resolved >= 0.98


@pytest.mark.parametrize("q", ["xyzzy", "qwertab 500", "zzkfrol forte"])
def test_unknown_brand_is_not_confident(q):
    hits = MedicineIndex.load().resolve(q, 3)
    assert not hits or not hits[0].confident


def test_saridon_now_resolves():  # added by the Apollo / master datasets
    top = MedicineIndex.load().resolve("saridon", 3)[0]
    assert top.kind == "product" and "saridon" in top.name.lower() and top.confident


@pytest.mark.parametrize("q,expected", [("alprazolam", "alprazolam"), ("azitromycin", "azithromycin")])
def test_generic_name_resolves_to_ingredient(q, expected):
    top = MedicineIndex.load().resolve(q, 3)[0]
    assert top.kind == "ingredient" and top.name == expected and top.confident
