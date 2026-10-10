"""Enrichment: medicine monograph text -> medibot.product_info.

Sources (all already in data/raw):
  mid       MID (Mendeley, CC BY 4.0): introduction, uses, benefits, side effects, how to use, how it works,
            quick tips, structured safety advice (alcohol / pregnancy / breast feeding / driving / kidney / liver)
  mohneesh  Indian Medicine Data (Apache 2.0): description, side effects, drug-interaction text
  k11       1mg 11k (CC0): uses, side effects

Note: texts may contain label dosing ("no more than four doses in 24 hours"). Stored as reference;
the Safety Kernel / output check (Phase 6) must never turn it into a personal dosing instruction.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data/pipeline"))
sys.path.insert(0, str(ROOT / "db"))
from load import copy_df, database_url  # noqa: E402
from normalize import normalize_name  # noqa: E402

SAFETY_KEYS = {"alcohol": "alcohol", "pregnancy": "pregnancy", "breast feeding": "breastfeeding",
               "breastfeeding": "breastfeeding", "driving": "driving", "kidney": "kidney", "liver": "liver"}


def clean(t) -> str | None:
    if not isinstance(t, str):
        return None
    t = html.unescape(t).replace("\\n", "\n").replace('\\"', '"')
    t = re.sub(r'\bul\s*""', " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t).strip()
    return t or None


def list_items(t) -> list[str]:
    """Lines of a scraped list, without index numbers / empty markers."""
    t = clean(t)
    if not t:
        return []
    return [ln.strip(" .,") for ln in t.split("\n") if ln.strip(" .,") and not re.fullmatch(r"\d+", ln.strip())]


def side_effects(t) -> str | None:
    t = clean(t)
    if not t:
        return None
    m = re.search(r"(?:common|serious|rare) side effects of .*?\n", t, re.I)
    items = [ln for ln in (t[m.end():] if m else t).split("\n") if ln and len(ln) < 80 and not ln.lower().startswith("common side")]
    return "; ".join(dict.fromkeys(items)) or t


def safety_advice(t) -> dict | None:
    t = clean(t)
    if not t:
        return None
    parts = [p.strip(" ,\n") for p in re.split(r",\s*\n", t)]
    out, key = {}, None
    for p in parts:
        k = SAFETY_KEYS.get(p.lower())
        if k:
            key = k
        elif key and p:
            out[key] = p.rstrip(",")
            key = None
    return out or None


def from_mid() -> pd.DataFrame:
    m = pd.read_parquet(ROOT / "data/interim/mid.parquet")
    return pd.DataFrame({
        "key": m["Name"].map(normalize_name), "source": "mid",
        "introduction": m["ProductIntroduction"].map(clean),
        "uses": m["ProductUses"].map(lambda t: "; ".join(list_items(t)) or None),
        "benefits": m["ProductBenefits"].map(clean),
        "side_effects": m["SideEffect"].map(side_effects),
        "how_to_use": m["HowToUse"].map(clean),
        "how_it_works": m["HowWorks"].map(clean),
        "quick_tips": m["QuickTips"].map(lambda t: "\n".join(list_items(t)) or None),
        "safety_advice": m["SafetyAdvice"].map(lambda t: json.dumps(safety_advice(t)) if safety_advice(t) else None),
    })


def from_mohneesh() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data/raw/kaggle_indian-medicine-data/medicine_data.csv",
                     usecols=["product_name", "medicine_desc", "side_effects", "drug_interactions"])
    df = df.drop_duplicates("product_name")
    return pd.DataFrame({
        "key": df["product_name"].map(normalize_name), "source": "mohneesh",
        "introduction": df["medicine_desc"].map(clean), "side_effects": df["side_effects"].map(clean),
        "quick_tips": df["drug_interactions"].map(lambda t: f"Interactions (source text): {clean(t)}" if clean(t) else None),
    })


def from_k11() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data/raw/kaggle_11000-medicine-details/Medicine_Details.csv",
                     usecols=["Medicine Name", "Uses", "Side_effects"]).drop_duplicates("Medicine Name")
    return pd.DataFrame({"key": df["Medicine Name"].map(normalize_name), "source": "k11",
                         "uses": df["Uses"].map(clean), "side_effects": df["Side_effects"].map(clean)})


def build() -> None:
    cols = ["product_id", "source", "introduction", "uses", "benefits", "side_effects", "how_to_use",
            "how_it_works", "quick_tips", "safety_advice"]
    with psycopg.connect(database_url()) as conn, conn.cursor() as cur:
        cur.execute("SELECT key, product_id FROM medibot.products")
        pid = dict(cur.fetchall())
        cur.execute("TRUNCATE medibot.product_info")
        for df in (from_mid(), from_mohneesh(), from_k11()):
            df["product_id"] = df["key"].map(pid)
            df = df.dropna(subset=["product_id"]).drop_duplicates(["product_id", "source"])
            for c in cols:
                if c not in df:
                    df[c] = None
            copy_df(cur, "product_info", df, cols)
        conn.commit()
        cur.execute("SELECT source, count(*), count(safety_advice) FROM medibot.product_info GROUP BY 1 ORDER BY 1")
        for r in cur.fetchall():
            print("  ", r)


if __name__ == "__main__":
    build()
