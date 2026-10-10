"""Enrichment: Jan Aushadhi Kendra locations -> medibot.kendras.

Source: janaushadhi.gov.in public store locator (endpoint getAllKendraByStateDistrict, guest token),
raw file data/raw/jan_aushadhi/kendras.json (21,286 stores, fetched 2026-10-10).
Privacy: the raw records contain the store owner's name and personal phone number; they are
deliberately NOT loaded (PS: collect no personal data beyond what is required).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "db"))
from load import copy_df, database_url  # noqa: E402


def build() -> None:
    raw = json.loads((ROOT / "data/raw/jan_aushadhi/kendras.json").read_text())["responseBody"]["addKendraResponseList"]
    df = pd.DataFrame(raw)
    df = df[df["status"].eq(1)]
    out = pd.DataFrame({
        "kendra_code": df["storeCode"].astype(str).str.strip(),
        "name": "Jan Aushadhi Kendra " + df["storeCode"].astype(str).str.strip(),
        "state": df["stateName"], "district": df["districtName"],
        "pincode": df["pinCode"].astype("Int64").astype("string"),
        "address": df["kendraAddress"].astype("string").str.strip(),
        "lat": pd.to_numeric(df["latitude"], errors="coerce"), "lon": pd.to_numeric(df["longitude"], errors="coerce"),
        "source": "janaushadhi.gov.in store locator (2026-10-10)",
    })
    # coordinates outside India are data-entry errors -> drop the coordinates, keep the store
    bad = ~out["lat"].between(6, 38) | ~out["lon"].between(68, 98)
    out.loc[bad, ["lat", "lon"]] = None
    out = out.dropna(subset=["kendra_code"]).drop_duplicates("kendra_code")
    with psycopg.connect(database_url()) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE medibot.kendras")
        copy_df(cur, "kendras", out, ["kendra_code", "name", "state", "district", "pincode", "address", "lat", "lon", "source"])
        conn.commit()
    print(f"  active stores: {len(out):,}; with valid coordinates: {out['lat'].notna().sum():,}")


if __name__ == "__main__":
    build()
