"""Enrichment: interactions (DDInter), side effects + ATC codes (SIDER 4.1) -> medibot.

Names are mapped to catalog ingredients by base molecule (salt words removed) after the reviewed
synonym list (acetaminophen -> paracetamol, albuterol -> salbutamol ...). No fuzzy matching.
"""
from __future__ import annotations

import gzip
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data/pipeline"))
sys.path.insert(0, str(ROOT / "db"))
from load import copy_df, database_url  # noqa: E402
from safety import base  # noqa: E402

RAW = ROOT / "data/raw"
SEVERITY_RANK = {"Major": 3, "Moderate": 2, "Minor": 1, "Unknown": 0}


def ingredient_index(cur) -> dict[str, list[int]]:
    cur.execute("SELECT ingredient_id, name, base FROM medibot.ingredients")
    idx: dict[str, list[int]] = defaultdict(list)
    for iid, name, b in cur.fetchall():
        for k in {name, b}:
            idx[k].append(iid)
    return idx


def ids_for(name: str, idx) -> list[int]:
    return idx.get(base(name), []) or idx.get(str(name).lower().strip(), [])


def interactions(idx) -> pd.DataFrame:
    df = pd.concat([pd.read_csv(f, usecols=["Drug_A", "Drug_B", "Level"]) for f in sorted((RAW / "ddinter").glob("code_*.csv"))])
    df = df[df["Level"].isin(SEVERITY_RANK)].drop_duplicates()
    names = pd.unique(pd.concat([df["Drug_A"], df["Drug_B"]]))
    m = {n: ids_for(n, idx) for n in names}
    best: dict[tuple[int, int], str] = {}
    for a, b, lvl in df.itertuples(index=False):
        for ia in m[a]:
            for ib in m[b]:
                if ia == ib:
                    continue
                k = (min(ia, ib), max(ia, ib))
                if k not in best or SEVERITY_RANK[lvl] > SEVERITY_RANK[best[k]]:
                    best[k] = lvl
    mapped = sum(1 for n in names if m[n])
    print(f"  DDInter drugs mapped to catalog ingredients: {mapped}/{len(names)}")
    return pd.DataFrame([(a, b, s, "ddinter") for (a, b), s in best.items()],
                        columns=["ingredient_a", "ingredient_b", "severity", "source"])


def sider(idx) -> tuple[pd.DataFrame, dict[int, list[str]]]:
    names = pd.read_csv(RAW / "sider/drug_names.tsv", sep="\t", header=None, names=["cid", "name"])
    cid_ids = {r.cid: ids_for(r.name, idx) for r in names.itertuples()}
    cols = ["cid_flat", "cid_stereo", "umls_label", "placebo", "freq", "lower", "upper", "meddra_type", "umls", "se"]
    with gzip.open(RAW / "sider/meddra_freq.tsv.gz", "rt") as f:
        fr = pd.read_csv(f, sep="\t", header=None, names=cols)
    fr = fr[(fr["meddra_type"] == "PT") & (fr["placebo"].isna())]
    fr = fr.sort_values("upper", ascending=False).drop_duplicates(["cid_flat", "se"])
    rows = []
    for cid, g in fr.groupby("cid_flat"):
        for iid in cid_ids.get(cid, []):
            for r in g.head(25).itertuples():   # the 25 most frequent per drug keep answers focused
                rows.append((iid, r.se.lower(), str(r.freq), "sider"))
    se = pd.DataFrame(rows, columns=["ingredient_id", "side_effect", "frequency", "source"]).drop_duplicates(
        ["ingredient_id", "side_effect", "source"])
    atc = pd.read_csv(RAW / "sider/drug_atc.tsv", sep="\t", header=None, names=["cid", "atc"])
    atc_by_ing: dict[int, set[str]] = defaultdict(set)
    for r in atc.itertuples():
        for iid in cid_ids.get(r.cid, []):
            atc_by_ing[iid].add(r.atc)
    print(f"  SIDER drugs mapped: {sum(1 for v in cid_ids.values() if v)}/{len(cid_ids)}")
    return se, {k: sorted(v) for k, v in atc_by_ing.items()}


def build() -> None:
    with psycopg.connect(database_url()) as conn, conn.cursor() as cur:
        idx = ingredient_index(cur)
        cur.execute("TRUNCATE medibot.interactions, medibot.ingredient_side_effects")
        copy_df(cur, "interactions", interactions(idx), ["ingredient_a", "ingredient_b", "severity", "source"])
        se, atc = sider(idx)
        copy_df(cur, "ingredient_side_effects", se, ["ingredient_id", "side_effect", "frequency", "source"])
        cur.executemany("UPDATE medibot.ingredients SET atc_codes = %s WHERE ingredient_id = %s",
                        [(codes, iid) for iid, codes in atc.items()])
        print(f"  ingredients with ATC codes: {len(atc)}")
        conn.commit()


if __name__ == "__main__":
    build()
