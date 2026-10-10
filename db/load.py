"""Load data/processed/*.parquet into PostgreSQL (schema "medibot").

Usage:  .venv/bin/python db/load.py          (reads DATABASE_URL from .env)
Recreates the schema from db/migrations/*.sql, bulk-loads with COPY, then ANALYZE.
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data/processed"
REG = ROOT / "data/interim/regulatory"
sys.path.insert(0, str(ROOT / "data/pipeline"))


def database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL not set (.env)")


def _clean(v):
    """pandas/numpy values -> plain Python for COPY (NaN/NA -> NULL, arrays -> lists)."""
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, np.ndarray):
        return [_clean(x) for x in v.tolist()]
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if math.isnan(v) else float(v)
    return v


def copy_df(cur, table: str, df: pd.DataFrame, columns: list[str]) -> int:
    t0 = time.time()
    with cur.copy(f"COPY medibot.{table} ({', '.join(columns)}) FROM STDIN") as cp:
        for row in df[columns].itertuples(index=False, name=None):
            cp.write_row([_clean(v) for v in row])
    print(f"  {table:24} {len(df):>9,} rows  ({time.time() - t0:.1f}s)", flush=True)
    return len(df)


def load() -> dict:
    from sources import REGISTRY
    from normalize import parse_strength

    with psycopg.connect(database_url(), autocommit=False) as conn, conn.cursor() as cur:
        for mig in sorted((ROOT / "db/migrations").glob("*.sql")):
            print(f"applying {mig.name}", flush=True)
            cur.execute(mig.read_text())
        conn.commit()

        # ------------------------------------------------ sources
        base_sources = pd.DataFrame([
            ("az", "1mg", "2022-11", "CC BY-SA 4.0", "A-Z Medicine Dataset of India (Kaggle)"),
            ("mid", "1mg", "2024-09", "CC BY 4.0", "MID: Medicines Information Dataset (Mendeley)"),
            ("mohneesh", "1mg", "2023-08", "Apache 2.0", "Indian Medicine Data (Kaggle)"),
            ("k11", "1mg", "2024-06", "CC0 1.0", "11000 Medicine details (Kaggle)"),
            ("jan_aushadhi", "government", "2026-10", "Government of India", "PMBJP product & MRP list"),
            ("nppa", "government", "2026-03", "Government of India", "NPPA ceiling prices"),
            ("cdsco", "government", "2021-11", "Government of India", "Drugs Rules schedules; Sec. 26A prohibitions"),
        ], columns=["source", "platform", "observed", "licence", "description"])
        reg = pd.DataFrame([(s.name, s.platform, s.observed, s.licence, s.loader.__doc__ or s.name) for s in REGISTRY],
                           columns=base_sources.columns)
        copy_df(cur, "sources", pd.concat([base_sources, reg]), list(base_sources.columns))

        # ------------------------------------------------ ingredients
        ing = pd.read_parquet(P / "ingredient_safety.parquet")
        counts = pd.read_parquet(P / "ingredients.parquet").set_index("ingredient")["n_products"]
        ing["n_products"] = ing["ingredient"].map(counts).fillna(0).astype(int)
        ing = ing.rename(columns={"ingredient": "name", "is_antiinfective_other": "is_antiinfective"})
        ing["ingredient_id"] = range(1, len(ing) + 1)
        copy_df(cur, "ingredients", ing, ["ingredient_id", "name", "base", "n_products", "schedule", "schedule_refs",
                                          "controlled_category", "is_antibiotic", "is_corticosteroid", "is_sex_hormone",
                                          "is_antiinfective", "class_labels"])
        ing_id = dict(zip(ing["name"], ing["ingredient_id"]))

        # ------------------------------------------------ compositions + their ingredients
        comp = pd.read_parquet(P / "compositions.parquet")
        copy_df(cur, "compositions", comp, ["composition_id", "composition_key", "composition", "form", "release", "n_products"])
        rows = []
        for cid, key in zip(comp["composition_id"], comp["composition_key"]):
            for part in key.split("#")[0].split("|"):
                name, _, strength = part.rpartition(":")
                if name not in ing_id:
                    continue
                s = parse_strength(_strength_text(strength))
                rows.append((cid, ing_id[name], s.value if s else None, s.unit if s else None))
        ci = pd.DataFrame(rows, columns=["composition_id", "ingredient_id", "strength_value", "strength_unit"])
        ci = ci.drop_duplicates(["composition_id", "ingredient_id"])
        copy_df(cur, "composition_ingredients", ci, list(ci.columns))

        # ------------------------------------------------ products
        prod = pd.read_parquet(P / "products.parquet")
        sidx = pd.read_parquet(P / "search_index.parquet", columns=["product_id", "search_text", "stem", "popularity"])
        prod = prod.merge(sidx, on="product_id", how="left").rename(columns={"all_discontinued": "discontinued"})
        prod["ingredients"] = prod["ingredients"].map(lambda a: list(a) if a is not None else None)
        copy_df(cur, "products", prod, [
            "product_id", "canonical_id", "is_alias", "key", "name", "manufacturer", "form", "release", "composition",
            "composition_raw", "composition_id", "composition_key", "composition_source", "composition_status",
            "composition_votes", "n_components", "ingredients", "substitutable", "discontinued", "therapeutic_class",
            "action_class", "chemical_class", "sub_category", "habit_forming", "url_1mg", "url_apollo", "url_netmeds",
            "image_url", "rating_count", "popularity", "search_text", "stem"])

        # ------------------------------------------------ safety
        ps = pd.read_parquet(P / "product_safety.parquet")
        copy_df(cur, "product_safety", ps, ["product_id", "category", "requires_prescription", "reasons", "legal_refs"])
        flags = pd.read_parquet(P / "rx_flags.parquet")
        copy_df(cur, "rx_flags", flags, ["product_id", "source", "rx_required"])
        banned = pd.read_csv(REG / "banned_all.csv", keep_default_na=False).replace({"": None})
        copy_df(cur, "banned_entries", banned.drop_duplicates(["list", "serial"]),
                ["list", "serial", "text", "notification", "dated", "status", "form", "strengths", "source"])
        sched = pd.concat([pd.read_csv(REG / f"schedule_{s}.csv") for s in ["h", "h1", "x"]])
        copy_df(cur, "schedule_entries", sched, ["schedule", "serial", "substance", "raw"])

        # ------------------------------------------------ prices (outliers flagged against composition medians)
        po = pd.read_parquet(P / "price_observations.parquet")
        po = po.merge(prod[["product_id", "composition_id"]], on="product_id", how="left")
        med = po.groupby(["composition_id", "pack_unit"])["price_per_unit_inr"].agg(["median", "count"])
        po = po.join(med, on=["composition_id", "pack_unit"])
        ratio = po["price_per_unit_inr"] / po["median"]
        po["is_outlier"] = ((po["count"] >= 5) & ((ratio < 0.2) | (ratio > 5))).fillna(False) | (po["price_inr"] <= 0)
        po = po[po["price_inr"].notna() & (po["price_inr"] < 1e9)]
        po["platform"] = po["platform"].replace({"mixed": "reference"})  # master MRP is not a pharmacy price
        copy_df(cur, "price_observations", po, ["product_id", "source", "platform", "observed", "price_inr", "mrp_inr",
                                                "pack_label", "pack_quantity", "pack_unit", "price_per_unit_inr", "url",
                                                "is_outlier"])

        # ------------------------------------------------ Jan Aushadhi, NPPA
        ja = pd.read_parquet(P / "jan_aushadhi.parquet").rename(columns={"group": "product_group"})
        copy_df(cur, "jan_aushadhi", ja.drop_duplicates("drug_code"), [
            "drug_code", "generic_name", "product_group", "unit_size", "mrp_inr", "pack_quantity", "pack_unit",
            "price_per_unit_inr", "composition", "form", "release", "composition_key", "composition_id", "is_drug",
            "usable", "matches_catalog"])
        nppa = pd.read_parquet(P / "nppa_ceiling.parquet")
        for c in ("so_number", "notified"):
            if c not in nppa:
                nppa[c] = None
        copy_df(cur, "nppa_ceiling", nppa, ["medicine", "dosage", "unit", "ceiling_price_inr", "per", "composition", "form",
                                            "release", "composition_key", "composition_id", "source", "status",
                                            "so_number", "notified", "matches_catalog"])
        conn.commit()

        cur.execute("REFRESH MATERIALIZED VIEW medibot.latest_prices")
        cur.execute("ALTER DATABASE " + conn.info.dbname + " SET search_path = medibot, public")
        cur.execute("ANALYZE")
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        size = cur.fetchone()[0]
        conn.commit()
    print(f"database size: {size}")
    return {"size": size}


def _strength_text(key: str) -> str:
    """Strength.key() form '500mg' / '40mg/ml' / '2pct_ww' back to parseable text."""
    return (key.replace("pct_ww", "% w/w").replace("pct_wv", "% w/v").replace("pct_vv", "% v/v").replace("pct", "%")
            .replace("million_spores", " million spores").replace("billion_spores", " billion spores")
            .replace("billion_cfu", " billion cfu").replace("million_iu", " million iu").replace("mg/mg", "mg/1000mg"))


if __name__ == "__main__":
    load()
