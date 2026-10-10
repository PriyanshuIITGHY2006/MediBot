"""Brand / medicine name search index (Phase 2.7).

Builds data/processed/search_index.parquet and provides `MedicineIndex.resolve(query)`, the
reference implementation the backend's resolver must match. Handles typos ("augmantin"),
glued strengths ("dolo650"), extra words ("crocin tablet 650"), and ranks the commonly sold
product first when several names fit.

Two stages keep it fast on ~285k names: fuzzy-match the brand stem (first word) against the
much smaller stem vocabulary, then score full names only inside the best stems.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

sys.path.insert(0, str(Path(__file__).parent))
from normalize import parse_form, parse_release  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/processed"

_FAMILY = {f: "oral_liquid" for f in ("syrup", "dry_syrup", "suspension", "solution", "oral_drops", "emulsion")}
_FAMILY.update({f: "oral_solid" for f in ("tablet", "tablet_dispersible", "tablet_mouth_dissolving", "tablet_chewable",
                                          "tablet_effervescent", "capsule", "capsule_softgel")})
_FAMILY.update({f: "topical" for f in ("cream", "ointment", "gel", "lotion")})
_MENTIONS_FORM = re.compile(
    r"\b(tablets?|tab|capsules?|cap|syrup|suspension|injection|inj|drops?|cream|gel|ointment|lotion|"
    r"solution|soap|shampoo|spray|inhaler|powder|sachet|dt|sr|er)\b")

_FORM_NOISE = re.compile(
    r"\b(tablets?|tab|capsules?|cap|syrup|suspension|oral|injection|inj|drops?|cream|gel|ointment|"
    r"lotion|solution|strip|of|the|medicine|mg|ml|gm|mcg)\b"
)


def clean_query(text: str) -> str:
    t = str(text).lower()
    t = re.sub(r"([a-z])(\d)", r"\1 \2", t)  # dolo650 -> dolo 650
    t = re.sub(r"(\d)([a-z])", r"\1 \2", t)  # 650mg -> 650 mg
    t = re.sub(r"[^a-z0-9.+ ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def search_text(name: str) -> str:
    """Product name reduced to what people type: brand words + numbers."""
    return re.sub(r"\s+", " ", _FORM_NOISE.sub(" ", clean_query(name))).strip()


def stem_of(text: str) -> str:
    words = text.split()
    return words[0] if words else ""


def numbers_of(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


@dataclass
class Match:
    kind: str          # "product" or "ingredient"
    product_id: str | None
    name: str
    score: float
    confidence: float  # 0-100: how sure we are the brand/ingredient word itself was recognised

    @property
    def confident(self) -> bool:
        """Below this the caller must ask "Did you mean ...?" instead of acting on the match."""
        return self.confidence >= CONFIDENT


CONFIDENT = 88


class MedicineIndex:
    def __init__(self, df: pd.DataFrame, ingredients: list[str]):
        self.df = df.reset_index(drop=True)
        self.by_stem: dict[str, list[int]] = defaultdict(list)
        for i, stem in enumerate(self.df["stem"]):
            self.by_stem[stem].append(i)
        self.stems = list(self.by_stem)
        self.ingredients = ingredients
        self.numbers = [set(n) for n in self.df["numbers"]]

    @classmethod
    def load(cls) -> "MedicineIndex":
        ing = pd.read_parquet(OUT / "ingredients.parquet")["ingredient"].tolist()
        return cls(pd.read_parquet(OUT / "search_index.parquet"), ing)

    def resolve(self, query: str, limit: int = 5) -> list[Match]:
        q = search_text(query)
        if not q:
            return []
        q_stem, q_nums = stem_of(q), numbers_of(q)
        q_words = re.sub(r"[\d.+]+", " ", q).strip()

        # Generic-name query ("alprazolam", "paracetamol 650"): an ingredient beats a look-alike brand.
        ing_hit = process.extractOne(q_words, self.ingredients, scorer=fuzz.ratio, score_cutoff=88) if q_words else None

        # People rarely get the first letter wrong: re-score a wider candidate set with a first-letter bonus
        raw = process.extract(q_stem, self.stems, scorer=fuzz.ratio, limit=30, score_cutoff=60)
        stem_hits = sorted(((st, min(100.0, sc + (6 if st[:1] == q_stem[:1] else 0) + (10 if st == q_stem else 0)), sc)
                            for st, sc, _ in raw), key=lambda x: -x[1])[:10]
        raw_stem = {st: sc for st, _, sc in stem_hits}
        if not stem_hits:  # brand typed second ("tablet crocin") or very short query
            stem_hits = process.extract(q, self.stems, scorer=fuzz.partial_ratio, limit=8, score_cutoff=75)
            raw_stem = {st: sc for st, sc, _ in stem_hits}
        q_form = parse_form(query) if _MENTIONS_FORM.search(query.lower()) else None
        q_release = parse_release(q)  # cleaned query: "xr500" -> "xr 500"
        scored = []
        for stem, stem_score, _ in stem_hits:
            for i in self.by_stem[stem]:
                # token_sort penalises extra/missing words ("l montus" should not prefer "l montus abl sr")
                text = self.df.at[i, "search_text"]
                # blend: token_sort penalises extra words, token_set forgives them ("saridon" vs "saridon new")
                name_score = 0.3 * fuzz.token_sort_ratio(q, text) + 0.7 * fuzz.token_set_ratio(q, text)
                nums = self.numbers[i]
                num_bonus = 15 if q_nums and q_nums <= nums else (-25 if q_nums and not (q_nums & nums) else 0)
                pf = self.df.at[i, "form"]
                if q_form is None:
                    form_bonus = -8 if pf in ("other", "kit") else 0  # brand-only query: not the promo pack / kit
                elif pf == q_form:
                    form_bonus = 12
                elif _FAMILY.get(pf) and _FAMILY.get(pf) == _FAMILY.get(q_form):
                    form_bonus = 8   # "calpol syrup" -> the paediatric suspension, never "Calpol T Tablet"
                else:
                    form_bonus = -15
                rel = self.df.at[i, "release"] if "release" in self.df.columns else "IR"
                if q_release != "IR":  # user typed a release ("Exfaro 300 Tablet ER"): it must match
                    form_bonus += 8 if rel == q_release else -8
                elif rel == "IR":      # none typed: gentle preference for the ordinary tablet
                    form_bonus += 3
                # popularity breaks ties between near-identical names (e.g. Dolo 650 vs Dolo 650 MR)
                score = (0.4 * stem_score + 0.6 * name_score + num_bonus + form_bonus
                         + 6 * self.df.at[i, "popularity"])
                scored.append((score, stem_score, i))
        scored.sort(reverse=True)

        out: list[Match] = []
        top_raw = raw_stem.get(self.df.at[scored[0][2], "stem"], 0) if scored else 0
        if ing_hit and (not scored or ing_hit[1] >= top_raw):
            out.append(Match("ingredient", None, ing_hit[0], round(ing_hit[1] + 20, 1), ing_hit[1]))

        # Margin over the best candidate from a DIFFERENT brand stem: a typo that is clearly
        # closest to one brand ("augmantin" -> Augmentin, not Augmin) earns extra confidence.
        top_stem = self.df.at[scored[0][2], "stem"] if scored else None
        rival = next((s for s, _, i in scored if self.df.at[i, "stem"] != top_stem), None)
        seen = set()
        for rank, (score, stem_score, i) in enumerate(scored):
            pid = self.df.at[i, "canonical_id"]  # aliases (other listings of the same product) resolve to one product
            if pid in seen:
                continue
            seen.add(pid)
            conf = stem_score
            if rank == 0 and rival is not None and score - rival >= 5:
                conf = min(100.0, conf + min(10.0, score - rival))
            if rank == 0 and self.df.at[i, "stem"] != q_stem:
                # another REAL brand almost as close ("olemsar" ~ Olemar ~ Olmesar): the bot must ask
                rival_raw = max((sc for st, sc in raw_stem.items() if st != self.df.at[i, "stem"]), default=0)
                if raw_stem.get(self.df.at[i, "stem"], 0) - rival_raw < 6:
                    conf = min(conf, 80.0)
            if q_nums and not (q_nums & self.numbers[i]):
                conf = min(conf, 70.0)  # "liv 52" vs "Liv Z 5mg": brand word matches, numbers don't
            out.append(Match("product", pid, self.df.at[i, "name"], round(score, 1), round(conf, 1)))
            if len(out) == limit:
                break
        return out


def build() -> dict:
    p = pd.read_parquet(OUT / "products.parquet",
                        columns=["product_id", "canonical_id", "name", "form", "release", "all_discontinued", "url_1mg", "url_apollo",
                                 "review_excellent_pct", "rating_count", "composition"])
    skus = pd.read_parquet(OUT / "skus.parquet", columns=["product_id"])
    n_skus = skus.groupby("product_id").size()
    p["search_text"] = p["name"].map(search_text)
    p["stem"] = p["search_text"].map(stem_of)
    # popularity in [0,1]: still sold, on 1mg, in the curated 11k "popular" list, more pack variants
    p["popularity"] = (
        (~p["all_discontinued"].fillna(False)).astype(float) * 0.35
        + (p["url_1mg"].notna() | p["url_apollo"].notna()).astype(float) * 0.15
        + p["review_excellent_pct"].notna().astype(float) * 0.25
        + (p["rating_count"].fillna(0).clip(upper=1000) / 1000) * 0.15
        + p["product_id"].map(n_skus).fillna(0).clip(upper=3) / 3 * 0.1
    )
    # numbers a user might type: those in the name plus the strengths in the composition ("crocin 650")
    p["numbers"] = [sorted(numbers_of(t) | numbers_of(clean_query(c or ""))) for t, c in zip(p["search_text"], p["composition"])]
    idx = p[p["stem"].ne("")][["product_id", "canonical_id", "name", "form", "release", "search_text", "stem",
                                                        "numbers", "popularity"]]
    idx.to_parquet(OUT / "search_index.parquet", index=False)
    return {"indexed": len(idx), "stems": idx["stem"].nunique()}


if __name__ == "__main__":
    print(build())
    if len(sys.argv) > 1:
        ix = MedicineIndex.load()
        for q in sys.argv[1:]:
            print(f"{q:18} ->", [(m.kind[0], m.name, m.confidence, m.confident) for m in ix.resolve(q, 3)])
