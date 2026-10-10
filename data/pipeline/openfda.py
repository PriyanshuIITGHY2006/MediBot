"""openFDA drug labels (bulk download, public domain) -> label sections per catalog ingredient.

Input : data/raw/openfda/drug-label-*.json.zip   (https://open.fda.gov/apis/drug/label/download/)
Output: data/interim/openfda_sections.parquet    (ingredient, set_id, product_type, effective_time, section, text)

Only single-ingredient labels are used, matched to catalog ingredients by base molecule after the reviewed
synonym list (acetaminophen -> paracetamol, albuterol -> salbutamol ...). No fuzzy matching.
Per ingredient we keep the most recent, most complete prescription label and the most recent OTC label.
Dosing sections are never kept (MediBot does not give doses).
"""
from __future__ import annotations

import re
import sys
import time
import zipfile
from pathlib import Path

import ijson
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data/pipeline"))
from normalize import _synonyms  # noqa: E402
from safety import base  # noqa: E402

RAW = ROOT / "data/raw/openfda"
OUT = ROOT / "data/interim/openfda_sections.parquet"

# openFDA field -> MediBot section. Dosage / overdosage / strengths are deliberately absent.
SECTIONS = {
    "indications_and_usage": "uses", "purpose": "uses",
    "mechanism_of_action": "how_it_works",
    "adverse_reactions": "side_effects",
    "boxed_warning": "warnings", "warnings": "warnings", "warnings_and_cautions": "warnings",
    "precautions": "warnings", "general_precautions": "warnings", "when_using": "warnings", "stop_use": "warnings",
    "ask_doctor": "warnings", "ask_doctor_or_pharmacist": "interactions",
    "contraindications": "contraindications", "do_not_use": "contraindications",
    "drug_interactions": "interactions",
    "pregnancy": "pregnancy", "teratogenic_effects": "pregnancy", "pregnancy_or_breast_feeding": "pregnancy",
    "lactation": "breastfeeding", "nursing_mothers": "breastfeeding",
    "pediatric_use": "children", "keep_out_of_reach_of_children": "children",
    "geriatric_use": "elderly",
    "storage_and_handling": "storage",
    "information_for_patients": "patient_info", "patient_counseling_information": "patient_info",
    "drug_abuse_and_dependence": "habit_forming", "dependence": "habit_forming", "abuse": "habit_forming",
}


def to_catalog(name: str) -> str:
    b = base(name)
    return _synonyms().get(b, b)


def catalog_ingredients() -> set[str]:
    ing = pd.read_parquet(ROOT / "data/processed/ingredients.parquet")
    col = "ingredient"
    return {to_catalog(n) for n in ing[col].astype(str)} | set(ing[col].astype(str))


def clean(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip()
    # drop the leading section heading that labels repeat ("8.1 Pregnancy Risk Summary ...", "WARNINGS ...")
    t = re.sub(r"^(\d+(\.\d+)*\s+)?[A-Z][A-Z &/,\-]{3,60}(?=\s[A-Z][a-z])", "", t).strip()
    return t


def score(r: dict) -> tuple:
    return (r.get("effective_time", ""), sum(1 for k in r if k in SECTIONS))


def build() -> pd.DataFrame:
    wanted = catalog_ingredients()
    best: dict[tuple[str, str], dict] = {}   # (ingredient, rx|otc) -> label
    seen = 0
    t0 = time.time()
    for z in sorted(RAW.glob("drug-label-*.json.zip")):
        with zipfile.ZipFile(z) as zf, zf.open(zf.namelist()[0]) as fh:
            for r in ijson.items(fh, "results.item"):
                seen += 1
                of = r.get("openfda") or {}
                subs, gens = of.get("substance_name") or [], of.get("generic_name") or []
                if len(subs) != 1 or len(gens) != 1 or re.search(r"\band\b|,", gens[0], re.I):
                    continue
                ing = to_catalog(gens[0])
                if ing not in wanted:
                    ing = to_catalog(subs[0])
                    if ing not in wanted:
                        continue
                kind = "rx" if "PRESCRIPTION" in " ".join(of.get("product_type") or []) else "otc"
                key = (ing, kind)
                if key not in best or score(r) > score(best[key]):
                    best[key] = {k: r[k] for k in r if k in SECTIONS or k in ("set_id", "effective_time")}
                    best[key]["_type"] = kind
        print(f"  {z.name}: {seen:,} labels read, {len(best):,} kept ({time.time() - t0:.0f}s)", flush=True)
    rows = []
    for (ing, kind), r in best.items():
        for field, section in SECTIONS.items():
            for txt in r.get(field) or []:
                t = clean(str(txt))
                if len(t) >= 40:
                    rows.append({"ingredient": ing, "set_id": r.get("set_id"), "label_type": kind,
                                 "effective_time": r.get("effective_time"), "field": field, "section": section,
                                 "text": t})
    df = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"openFDA: {df['ingredient'].nunique():,} ingredients, {len(df):,} sections -> {OUT.relative_to(ROOT)}")
    return df


if __name__ == "__main__":
    build()
