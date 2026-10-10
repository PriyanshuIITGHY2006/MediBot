"""Source registry: one loader per raw dataset, all returning the same columns.

Columns (any may be missing for a source):
  key, name, manufacturer, composition (1mg-style text), composition_full (bool: complete vs truncated),
  pack_label, price_inr, mrp_inr, observed (YYYY-MM of the scrape), platform, url,
  rx_required (True/False/None), popularity (e.g. rating count), form_hint

build_catalog.py merges these by `key`; prices become price observations; rx flags become the
independent cross-check for the Prescription Guard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from normalize import normalize_name, to_standard_composition

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw"
INTERIM = ROOT / "data/interim"

_PACK_SUFFIX = re.compile(r"(\s+\d+\s*'?s|\s*,\s*\d+(?:\.\d+)?\s*(?:ml|gm|g|kg|count|s|'s|tablets?|capsules?|kit|each)\b.*"
                          r"|\s+\d+(?:\.\d+)?\s*(?:ml|gm|g)$)\s*$", re.I)


def strip_pack(name: str) -> str:
    """'Atrest 25mg Tablet 10'S' -> 'Atrest 25mg Tablet'; 'Digene Gel Orange, 200 ml' -> 'Digene Gel Orange'."""
    return _PACK_SUFFIX.sub("", str(name)).strip(" ,")


def key_of(name) -> str:
    return normalize_name(strip_pack(name))


def _money(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype("string").str.replace(r"[^\d.]", "", regex=True).str.replace(r"^\.+|\.+$", "", regex=True),
                         errors="coerce")


def _clean(s: pd.Series) -> pd.Series:
    return s.astype("string").str.replace(r"\s+", " ", regex=True).str.strip().replace({"": pd.NA, "nan": pd.NA})


@dataclass
class Source:
    name: str
    platform: str
    observed: str          # when the data was scraped (YYYY-MM), from the dataset page
    licence: str
    loader: Callable[[], pd.DataFrame]
    composition_rank: int  # lower = more trusted for compositions; 99 = no compositions


# ---------------------------------------------------------------- loaders


def apollo() -> pd.DataFrame:
    df = pd.read_csv(RAW / "kaggle_apollo-pharmacy-drug-details-india/apollo_medicine_details.csv")
    return pd.DataFrame({
        "key": df["drug_name"].map(key_of), "name": _clean(df["drug_name"].map(strip_pack)),
        "manufacturer": _clean(df["legal_manufacturer_name"]),
        "composition": df["active_ingredient"].map(to_standard_composition), "composition_full": True,
        "form_hint": _clean(df["dosage_form"]).str.lower(), "url": df["url"],
        # Apollo files consumer products under /otc/ and medicines under /medicine/
        "rx_required": df["url"].str.contains("/medicine/", na=False).where(df["url"].str.contains("/(?:otc|medicine)/", na=False)),
    })


def master() -> pd.DataFrame:
    df = pd.read_csv(RAW / "kaggle_indian-medicine-master-dataset/Indian-Medicine-Dataset (1)/out_india/medicines.csv",
                     usecols=["medicine_name", "manufacturer", "dosage_form", "pack_size", "price_inr", "is_discontinued",
                              "prescription", "composition"], low_memory=False)
    rx = df["prescription"].astype("string").str.lower()
    return pd.DataFrame({
        "key": df["medicine_name"].map(key_of), "name": _clean(df["medicine_name"]),
        "manufacturer": _clean(df["manufacturer"]),
        "composition": df["composition"].map(to_standard_composition), "composition_full": True,
        "pack_label": _clean(df["pack_size"]), "mrp_inr": pd.to_numeric(df["price_inr"], errors="coerce"),
        "rx_required": rx.map(lambda v: None if pd.isna(v) else ("no prescription" not in v)),
    })


def tata1mg() -> pd.DataFrame:
    df = pd.read_csv(RAW / "kaggle_medicines-dataset/tata_1mg_Medicine_data.csv",
                     usecols=["Name", "MRP", "Quantity", "Manufacturer", "Salt_Composition"])
    return pd.DataFrame({
        "key": df["Name"].map(key_of), "name": _clean(df["Name"]), "manufacturer": _clean(df["Manufacturer"]),
        "composition": df["Salt_Composition"].map(to_standard_composition), "composition_full": True,
        "pack_label": _clean(df["Quantity"]), "mrp_inr": _money(df["MRP"]),
    })


def netmeds_rx() -> pd.DataFrame:
    """netmeds.com disease pages: Netmeds' own 'Rx required' flag, price and generic composition."""
    df = pd.read_csv(RAW / "kaggle_medicines-dataset/medicines.csv",
                     usecols=["med_name", "med_url", "final_price", "price", "prescription_required",
                              "drug_varient", "drug_manufacturer", "generic_name"])
    df = df.drop_duplicates("med_url")
    return pd.DataFrame({
        "key": df["med_name"].map(key_of), "name": _clean(df["med_name"].map(strip_pack)),
        "manufacturer": _clean(df["drug_manufacturer"].astype("string").str.replace(r"^\*\s*Mkt:\s*", "", regex=True)),
        "composition": df["generic_name"].map(lambda g: to_standard_composition(
            re.sub(r"(\d)\s+(mg|mcg|gm|g|iu|ml)\b", r"\1\2", str(g), flags=re.I)) if isinstance(g, str) else None),
        "composition_full": True,
        "pack_label": _clean(df["drug_varient"].astype("string").str.replace(r"^\*\s*", "", regex=True)),
        "price_inr": _money(df["final_price"]),
        "mrp_inr": _money(df["price"].astype("string").str.extract(r"MRP\s*₹?\s*([\d,.]+)")[0]),
        "url": df["med_url"],
        "rx_required": df["prescription_required"].astype("string").str.contains("Rx", na=False),
    })


def netmeds_2021() -> pd.DataFrame:
    df = pd.read_csv(RAW / "kaggle_medicine-dataset-of-netmeds/Medicine_details.csv")
    return pd.DataFrame({
        "key": df["Medicine Name"].map(key_of), "name": _clean(df["Medicine Name"].map(strip_pack)),
        "manufacturer": _clean(df["Manufacturer"]),
        "composition": df["Composition"].map(to_standard_composition), "composition_full": True,
        "price_inr": _money(df["Best Price"]), "mrp_inr": _money(df["MRP"]),
    })


def netmeds_2026() -> pd.DataFrame:
    df = pd.read_csv(RAW / "kaggle_netmedsdata/netmeds_products.csv", encoding="utf-8-sig")
    return pd.DataFrame({"key": df["ProductName"].map(key_of), "name": _clean(df["ProductName"].map(strip_pack)),
                         "price_inr": _money(df["Price"]), "category": _clean(df["Category"])})


def pharmeasy_2022() -> pd.DataFrame:
    # the file embeds JSON with unquoted commas; only the first 8 fields are reliable
    import csv as _csv
    rows = []
    with open(RAW / "kaggle_pharmeasy-dataset/Pharmeasy.csv", newline="", encoding="utf-8", errors="ignore") as f:
        rd = _csv.reader(f, skipinitialspace=True)
        next(rd)
        for r in rd:
            if len(r) >= 8 and re.fullmatch(r"\d+(\.\d+)?", r[5].strip() or "x"):
                rows.append({"name": r[1], "manufacturer": r[3], "mrpDecimal": r[5], "salePriceDecimal": r[6]})
    df = pd.DataFrame(rows)
    return pd.DataFrame({"key": df["name"].map(key_of), "name": _clean(df["name"].map(strip_pack)),
                         "manufacturer": _clean(df["manufacturer"]),
                         "price_inr": _money(df["salePriceDecimal"]), "mrp_inr": _money(df["mrpDecimal"])})


def onemg_2025() -> pd.DataFrame:
    df = pd.read_csv(RAW / "kaggle_1mg-medicine-dataset/onemg.csv",
                     usecols=["Drug_Name", "Drug_URL", "Prescription_Required", "MRP", "Selling_Price", "Pack_Size", "Manufacturer"])
    return pd.DataFrame({
        "key": df["Drug_Name"].map(key_of), "name": _clean(df["Drug_Name"]), "manufacturer": _clean(df["Manufacturer"]),
        # NOTE: in this file "Selling_Price" is a per-unit price and "Pack_Size" holds the strength ("625 Tablet"),
        # so no pack price is taken from it - only URLs and the prescription flag.
        "url": df["Drug_URL"],
        "rx_required": df["Prescription_Required"].astype("string").str.lower().map({"yes": True, "no": False}),
    })


def onemg_orders() -> pd.DataFrame:
    """1mg listing pages with rating counts — the best popularity signal we have."""
    df = pd.read_csv(RAW / "kaggle_1mg-medicines-order-online-dataset/1mgData.csv")
    mrp = _money(df["mrp"]).fillna(_money(df["price"]))
    price = _money(df["price"]).where(_money(df["price"]).notna() & df["price"].astype("string").str.contains("₹", na=False))
    return pd.DataFrame({
        "key": df["Name"].map(key_of), "name": _clean(df["Name"]), "pack_label": _clean(df["pack_size"]),
        "mrp_inr": mrp, "price_inr": price.fillna(mrp),
        "popularity": pd.to_numeric(df["rating_count"].astype("string").str.replace(r"[^\d]", "", regex=True), errors="coerce"),
    })


def india_flags() -> pd.DataFrame:
    df = pd.read_csv(RAW / "kaggle_india-medicines-and-drug-info-dataset/India Medicines and Drug Info Dataset.csv",
                     usecols=["Medicine Name", "Is Prescription Required?"])
    return pd.DataFrame({"key": df["Medicine Name"].map(key_of), "name": _clean(df["Medicine Name"]),
                         "rx_required": df["Is Prescription Required?"].map({True: True, False: False})})


def onemg_salt_flags() -> pd.DataFrame:
    df = pd.read_csv(RAW / "kaggle_1mg-medicine-data/medicine_data.csv")
    return pd.DataFrame({
        "key": df["Name"].map(key_of), "name": _clean(df["Name"]), "manufacturer": _clean(df["Company"]),
        "composition": df["Salt"].map(to_standard_composition), "composition_full": True,
        "price_inr": _money(df["Price"]),
        "rx_required": df["Prescription Required"].astype("string").str.lower().map(
            lambda v: None if pd.isna(v) else ("not" not in v and ("yes" in v or "required" in v or "true" in v))),
    })


def curated_otc() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data/reference/otc_brands_curated.csv")
    return pd.DataFrame({"key": df["name"].map(key_of), "name": df["name"],
                         "composition": df["composition"], "composition_full": True, "rx_required": False})


def apollo_otc_unverified() -> pd.DataFrame:
    """Apollo /otc/ products with no composition: added so the bot RECOGNISES them (no false block),
    labelled 'otc_unverified' (no ingredient claims, no substitutes)."""
    a = apollo()
    a = a[a["composition"].isna() & a["rx_required"].eq(False)]
    return a[["key", "name", "manufacturer", "url", "rx_required"]].assign(add_without_composition=True)


REGISTRY: list[Source] = [
    Source("curated_otc", "label", "2026-10", "curated from public pack labels", curated_otc, 2),
    Source("apollo_otc", "apollo", "2025-08", "CC0-1.0", apollo_otc_unverified, 99),
    Source("apollo", "apollo", "2025-08", "CC0-1.0", apollo, 3),
    Source("tata1mg", "1mg", "2025-03", "unknown (Kaggle: ujjwalgupta23/medicines-dataset)", tata1mg, 4),
    Source("netmeds_rx", "netmeds", "2025-03", "unknown (Kaggle: drowsyng/medicines-dataset)", netmeds_rx, 5),
    Source("master", "reference", "2026-09", "MIT (merge incl. CC BY-NC-SA inputs)", master, 6),
    Source("netmeds_2021", "netmeds", "2021-04", "copyright original authors", netmeds_2021, 7),
    Source("onemg_salt", "1mg", "2025-06", "CC0-1.0", onemg_salt_flags, 8),
    Source("onemg_2025", "1mg", "2025-10", "CC BY-NC-SA 4.0", onemg_2025, 99),
    Source("onemg_orders", "1mg", "2022-07", "other (see dataset)", onemg_orders, 99),
    Source("netmeds_2026", "netmeds", "2026-05", "MIT", netmeds_2026, 99),
    Source("pharmeasy_2022", "pharmeasy", "2022-04", "CC BY-NC-SA 4.0", pharmeasy_2022, 99),
    Source("india_flags", "1mg", "2025-10", "CC BY-NC-SA 4.0", india_flags, 99),
]


def load_all() -> dict[str, pd.DataFrame]:
    out = {}
    for s in REGISTRY:
        df = s.loader()
        df = df[df["key"].notna() & df["key"].ne("")].copy()
        df["source"], df["platform"], df["observed"] = s.name, s.platform, s.observed
        out[s.name] = df
    return out
