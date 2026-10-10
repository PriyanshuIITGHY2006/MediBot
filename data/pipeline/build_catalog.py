"""Phase 2: merge the raw catalogs into one normalised medicine catalog.

Inputs  (data/raw/):  A-Z India, MID, mohneesh7, 1mg-11k, 250k
Outputs (data/processed/):
  products.parquet      one row per medicine (normalised brand name)
  skus.parquet          one row per pack of a product (price, pack, price per unit)
  compositions.parquet  one row per Composition ID
  ingredients.parquet   ingredient vocabulary with product counts
and data/processed/quality_report.json (summarised in docs/DATA_QUALITY.md).

Composition source of truth: the A-Z dataset truncates compositions to two ingredients,
so MID > mohneesh7 > 1mg-11k > A-Z. A product whose only composition comes from A-Z
with exactly two ingredients is marked `truncation_risk` and is never substitutable.
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from sources import load_all  # noqa: E402
from normalize import (  # noqa: E402
    composition_id,
    composition_key,
    composition_text,
    normalize_name,
    parse_composition,
    parse_form,
    parse_pack,
    parse_release,
)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw"
INTERIM = ROOT / "data/interim"
OUT = ROOT / "data/processed"

# Composition sources (complete compositions) and their tie-break rank; A-Z is handled separately (truncated).
FULL_RANK = {"mid": 1, "curated_otc": 2, "mohneesh": 2, "k11": 2, "apollo": 3, "tata1mg": 4, "netmeds_rx": 5, "master": 6,
             "netmeds_2021": 7, "onemg_salt": 8}
FULL_SOURCES = sorted(FULL_RANK, key=FULL_RANK.get)


@lru_cache(maxsize=None)
def comps_of(text: str | None):
    return tuple(parse_composition(text))


def ingredient_key(comps) -> str | None:
    """Composition without form/release, used to compare sources. None if empty."""
    return "|".join(c.key() for c in comps) or None


def clean_str(s: pd.Series) -> pd.Series:
    return s.astype("string").str.replace(r"\s+", " ", regex=True).str.strip().replace({"": pd.NA, "~": pd.NA, ".": pd.NA})


# ---------------------------------------------------------------- loaders


def load_az() -> pd.DataFrame:
    df = pd.read_csv(RAW / "kaggle_az-medicine-dataset-of-india/A_Z_medicines_dataset_of_India.csv")
    comp = df["short_composition1"].fillna("").str.strip()
    second = df["short_composition2"].fillna("").str.strip()
    df["composition_az"] = comp.where(second.eq(""), comp + " + " + second)
    df["az_n_components"] = (comp.ne("")).astype(int) + (second.ne("")).astype(int)
    return pd.DataFrame({
        "name": clean_str(df["name"]),
        "key": df["name"].map(normalize_name),
        "manufacturer": clean_str(df["manufacturer_name"]),
        "price_inr": pd.to_numeric(df["price(₹)"], errors="coerce"),
        "is_discontinued": df["Is_discontinued"].astype(bool),
        "pack_label": clean_str(df["pack_size_label"]),
        "composition_az": df["composition_az"],
        "az_n_components": df["az_n_components"],
        "az_id": df["id"],
    })


def load_mid() -> pd.DataFrame:
    path = INTERIM / "mid.parquet"
    if not path.exists():  # first run: convert the 200 MB Excel once
        INTERIM.mkdir(parents=True, exist_ok=True)
        pd.read_excel(RAW / "mid/MID.xlsx", dtype=str).to_parquet(path, index=False)
    df = pd.read_parquet(path)
    out = pd.DataFrame({
        "key": df["Name"].map(normalize_name),
        "mid_name": clean_str(df["Name"]),
        "composition_mid": clean_str(df["Contains"]),
        "url_1mg": clean_str(df["Link"]),
        "therapeutic_class": clean_str(df["Therapeutic_Class"]),
        "action_class": clean_str(df["Action_Class"]),
        "chemical_class": clean_str(df["Chemical_Class"]),
        "habit_forming_mid": clean_str(df["Habit_Forming"]).str.lower().map({"yes": True, "no": False}),
    })
    return out.drop_duplicates("key")


def load_mohneesh() -> pd.DataFrame:
    df = pd.read_csv(
        RAW / "kaggle_indian-medicine-data/medicine_data.csv",
        usecols=["sub_category", "product_name", "salt_composition", "product_price", "product_manufactured"],
    )
    out = pd.DataFrame({
        "key": df["product_name"].map(normalize_name),
        "mo_name": clean_str(df["product_name"]),
        "composition_mohneesh": clean_str(df["salt_composition"]),
        "price_mohneesh_inr": pd.to_numeric(df["product_price"].astype("string").str.replace(r"[₹,\s]", "", regex=True), errors="coerce"),
        "manufacturer_mohneesh": clean_str(df["product_manufactured"]),
        "sub_category": clean_str(df["sub_category"]),
    })
    return out.dropna(subset=["key"]).drop_duplicates("key")


def load_k11() -> pd.DataFrame:
    df = pd.read_csv(RAW / "kaggle_11000-medicine-details/Medicine_Details.csv")
    return pd.DataFrame({
        "key": df["Medicine Name"].map(normalize_name),
        "k11_name": clean_str(df["Medicine Name"]),
        "composition_k11": clean_str(df["Composition"]),
        "manufacturer_k11": clean_str(df["Manufacturer"]),
        "image_url": clean_str(df["Image URL"]),
        "review_excellent_pct": pd.to_numeric(df["Excellent Review %"], errors="coerce"),
    }).drop_duplicates("key")


def load_250k() -> pd.DataFrame:
    df = pd.read_csv(
        RAW / "kaggle_250k-medicines-usage-side-effects-and-substitutes/medicine_dataset.csv",
        usecols=["name", "Chemical Class", "Habit Forming", "Therapeutic Class", "Action Class"],
    )
    return pd.DataFrame({
        "key": df["name"].map(normalize_name),
        "therapeutic_class_250k": clean_str(df["Therapeutic Class"]),
        "action_class_250k": clean_str(df["Action Class"]),
        "habit_forming_250k": clean_str(df["Habit Forming"]).str.lower().map({"yes": True, "no": False}),
    }).drop_duplicates("key")


# ---------------------------------------------------------------- composition resolution


def _complete(comps) -> bool:
    return bool(comps) and all(c.strength is not None for c in comps)


def _ingredient_set(comps) -> frozenset[str]:
    return frozenset(c.ingredient for c in comps)


def resolve_composition(row) -> tuple[str | None, str, str, int]:
    """Return (composition text, source, status, votes).

    Every source that states every strength votes for its ingredient key; the key with the most
    votes wins (ties broken by source rank). A tie between different keys is a conflict.
    The master dataset is a merge that includes the truncated A-Z text, so its vote is ignored
    when it merely repeats A-Z's two-ingredient version.
    """
    texts = {s: row.get(f"composition_{s}") for s in FULL_SOURCES}
    texts = {s: t for s, t in texts.items() if isinstance(t, str) and t.strip()}
    parsed = {s: comps_of(t) for s, t in texts.items()}

    az_text = row.get("composition_az")
    az_text = az_text if isinstance(az_text, str) and az_text.strip() else None
    az_comps = comps_of(az_text) if az_text else ()
    az_key = ingredient_key(az_comps) if az_comps else None

    complete = {s: c for s, c in parsed.items() if _complete(c)}
    if "master" in complete and az_key and len(az_comps) == 2 and ingredient_key(complete["master"]) == az_key:
        complete.pop("master")
    if complete:
        votes: dict[str, list[str]] = {}
        for s_, c in complete.items():
            votes.setdefault(ingredient_key(c), []).append(s_)
        ranked = sorted(votes.items(), key=lambda kv: (-len(kv[1]), min(FULL_RANK[x] for x in kv[1])))
        best_key, supporters = ranked[0]
        source = min(supporters, key=FULL_RANK.get)
        n = len(supporters)
        if len(ranked) > 1 and len(ranked[1][1]) >= n:
            status = "conflict"
        elif n >= 2:
            status = "verified"
        elif az_key and _az_consistent(az_key, best_key) and len(complete) == 1:
            status = "verified"  # one full source + A-Z's (possibly truncated) components agree
        elif az_key and not _az_consistent(az_key, best_key):
            status = "conflict"
        else:
            status = "single_source"
        return texts[source], source, status, n

    if parsed:  # full sources exist but none states every strength
        source = min(parsed, key=FULL_RANK.get)
        if _complete(az_comps) and _ingredient_set(az_comps) == _ingredient_set(parsed[source]):
            return az_text, "az", "verified", 1
        return texts[source], source, "single_source", 0

    if az_text:
        n = row.get("az_n_components") or 0
        return az_text, "az", "truncation_risk" if n >= 2 else "single_source", 1
    return None, "none", "missing", 0


def _az_consistent(az_key: str, full_key: str) -> bool:
    """A-Z keeps at most the first two components, so they must be a subset of the full set."""
    return set(az_key.split("|")) <= set(full_key.split("|"))


# ---------------------------------------------------------------- build


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    print("loading sources ...", flush=True)
    az, mid, mo, k11, k250 = load_az(), load_mid(), load_mohneesh(), load_k11(), load_250k()
    extra = load_all()  # Apollo, tata_1mg, Netmeds, master, 1mg flags/prices ... (sources.py)

    # Product universe = every normalised name seen in any source. Display name from the first source that has it.
    az_products = (
        az.sort_values(["is_discontinued", "az_id"])
        .groupby("key", as_index=False)
        .agg(az_name=("name", "first"), manufacturer=("manufacturer", "first"),
             composition_az=("composition_az", "first"), az_n_components=("az_n_components", "max"),
             all_discontinued=("is_discontinued", "all"))
    )
    # Only sources that carry compositions may ADD products; price/flag-only sources just enrich.
    adders = [df.loc[df["composition"].notna(), "key"] for df in extra.values() if "composition" in df]
    adders += [df["key"] for df in extra.values() if "add_without_composition" in df]
    products = pd.DataFrame({"key": pd.concat([az.key, mid.key, mo.key, k11.key, *adders]).dropna().unique()})
    for df in (az_products, mid, mo, k11, k250):
        products = products.merge(df, on="key", how="left")
    for name, df in extra.items():
        cols = {"name": f"{name}_name"}
        if "composition" in df:
            cols["composition"] = f"composition_{name}"
        if "manufacturer" in df:
            cols["manufacturer"] = f"manufacturer_{name}"
        sub = df.drop_duplicates("key").set_index("key")[list(cols)].rename(columns=cols)
        products = products.merge(sub, left_on="key", right_index=True, how="left")
    pop = extra["onemg_orders"].groupby("key")["popularity"].max()
    products["rating_count"] = products["key"].map(pop)
    products["url_apollo"] = products["key"].map(extra["apollo"].drop_duplicates("key").set_index("key")["url"])
    products["url_netmeds"] = products["key"].map(extra["netmeds_rx"].drop_duplicates("key").set_index("key")["url"])
    products["url_1mg"] = products["url_1mg"].fillna(
        products["key"].map(extra["onemg_2025"].drop_duplicates("key").set_index("key")["url"]))
    form_hint = extra["apollo"].drop_duplicates("key").set_index("key")["form_hint"]

    products["name"] = products["az_name"].fillna(products["mid_name"]).fillna(products["mo_name"]).fillna(products["k11_name"])
    for n in extra:
        products["name"] = products["name"].fillna(products[f"{n}_name"])
    products["manufacturer"] = (products["manufacturer"].fillna(products["manufacturer_mohneesh"])
                                .fillna(products["manufacturer_k11"]))
    for n in extra:
        if f"manufacturer_{n}" in products:
            products["manufacturer"] = products["manufacturer"].fillna(products[f"manufacturer_{n}"])
    products["therapeutic_class"] = products["therapeutic_class"].fillna(products["therapeutic_class_250k"])
    products["action_class"] = products["action_class"].fillna(products["action_class_250k"])
    products["habit_forming"] = products["habit_forming_mid"].fillna(products["habit_forming_250k"])
    products["all_discontinued"] = products["all_discontinued"].astype("boolean")

    print(f"resolving compositions for {len(products):,} products ...", flush=True)
    resolved = products.apply(resolve_composition, axis=1, result_type="expand")
    products[["composition_raw", "composition_source", "composition_status", "composition_votes"]] = resolved

    # A representative pack label helps classify the form for names that don't say it.
    first_pack = az.groupby("key")["pack_label"].first()
    for n in ("tata1mg", "netmeds_rx", "master"):
        first_pack = first_pack.combine_first(extra[n].dropna(subset=["pack_label"]).groupby("key")["pack_label"].first())
    labels = products["key"].map(first_pack).fillna(products["key"].map(form_hint))
    products["form"] = [parse_form(n, l) for n, l in zip(products["name"], labels)]
    products["release"] = [parse_release(n, l) for n, l in zip(products["name"], labels)]

    comps = products["composition_raw"].map(lambda t: comps_of(t) if isinstance(t, str) else ())
    products["n_components"] = comps.map(len)
    products["ingredients"] = comps.map(lambda cs: [c.ingredient for c in cs])
    products["composition"] = comps.map(lambda cs: composition_text(list(cs)) if cs else None)
    keys = [composition_key(list(c), f, r) for c, f, r in zip(comps, products["form"], products["release"])]
    products["composition_key"] = keys
    products["composition_id"] = [composition_id(k) for k in keys]
    products["strengths_complete"] = products["composition_key"].notna()
    products["substitutable"] = (
        products["strengths_complete"]
        & products["composition_status"].isin(["verified", "single_source"])
        & ~products["all_discontinued"].fillna(False)
    )
    products["product_id"] = "p_" + pd.util.hash_pandas_object(products["key"], index=False).astype("uint64").map(lambda h: f"{h:016x}")

    # Aliases: the same product listed under different names (Apollo marketing names, pack suffixes)
    # shares brand word + exact composition key. One canonical product per group; others point to it.
    stem = products["name"].astype("string").str.lower().str.extract(r"^([a-z0-9][a-z0-9\-]*)")[0]
    # manufacturer's first meaningful word: different makers of "Paracetamol 650mg Tablet" must stay distinct
    maker = (products["manufacturer"].astype("string").str.lower()
             .str.replace(r"^(m/s\.?|dr\.?|the)\s+", "", regex=True).str.extract(r"^([a-z0-9]+)")[0])
    grp_key = (stem + "§" + maker + "§" + products["composition_key"]).where(
        products["composition_key"].notna() & maker.notna() & stem.notna())
    order = products.assign(_g=grp_key, _pref=products["composition_source"].map(FULL_RANK).fillna(9)
                            - products["az_name"].notna().astype(int) * 10)
    canon = order.sort_values("_pref").dropna(subset=["_g"]).groupby("_g")["product_id"].first()
    products["canonical_id"] = grp_key.map(canon).fillna(products["product_id"])
    products["is_alias"] = products["canonical_id"] != products["product_id"]
    products.loc[products["is_alias"], "substitutable"] = False  # never list a product as its own alternative

    # ------------------------------------------------------------ SKUs (A-Z packs)
    skus = az.merge(products[["key", "product_id", "form"]], on="key", how="left")
    packs = skus["pack_label"].map(parse_pack)
    skus["pack_quantity"] = packs.map(lambda p: p.quantity if p else None)
    skus["pack_unit"] = packs.map(lambda p: p.unit if p else None)
    skus["price_per_unit_inr"] = skus["price_inr"] / skus["pack_quantity"]
    skus["price_source"] = "az_2022_snapshot"
    skus["sku_id"] = "s_" + skus["az_id"].astype(str)

    # Price outliers: far from the median unit price of the same composition (bad records, wrong pack).
    skus = skus.merge(products[["product_id", "composition_id", "substitutable"]], on="product_id", how="left")
    grp = skus[skus["substitutable"] & ~skus["is_discontinued"]].groupby(["composition_id", "pack_unit"])["price_per_unit_inr"]
    stats = grp.agg(group_median="median", group_size="count").reset_index()
    skus = skus.merge(stats, on=["composition_id", "pack_unit"], how="left")
    ratio = skus["price_per_unit_inr"] / skus["group_median"]
    skus["price_outlier"] = (skus["group_size"] >= 5) & ((ratio < 0.2) | (ratio > 5))
    skus["price_outlier"] |= skus["price_inr"].fillna(0) <= 0
    skus = skus[["sku_id", "product_id", "name", "manufacturer", "pack_label", "pack_quantity", "pack_unit",
                 "price_inr", "price_per_unit_inr", "price_source", "price_outlier", "is_discontinued"]]

    # ------------------------------------------------------------ price observations (every platform & date)
    pid = products.set_index("key")["product_id"]
    obs = [skus.assign(source="az", platform="1mg", observed="2022-11", url=None, mrp_inr=skus["price_inr"])
           [["product_id", "source", "platform", "observed", "price_inr", "mrp_inr", "pack_label", "url"]]]
    for name, df in extra.items():
        if not ({"price_inr", "mrp_inr"} & set(df)):
            continue
        o = df.assign(product_id=df["key"].map(pid))
        for c in ("price_inr", "mrp_inr", "pack_label", "url"):
            if c not in o:
                o[c] = None
        o["price_inr"] = o["price_inr"].fillna(o["mrp_inr"])
        obs.append(o.dropna(subset=["product_id", "price_inr"])
                   [["product_id", "source", "platform", "observed", "price_inr", "mrp_inr", "pack_label", "url"]])
    price_obs = pd.concat(obs, ignore_index=True)
    packs_o = price_obs["pack_label"].map(parse_pack)
    price_obs["pack_quantity"] = packs_o.map(lambda p: p.quantity if p else None)
    price_obs["pack_unit"] = packs_o.map(lambda p: p.unit if p else None)
    price_obs["price_per_unit_inr"] = price_obs["price_inr"] / price_obs["pack_quantity"]
    price_obs.to_parquet(OUT / "price_observations.parquet", index=False)

    # ------------------------------------------------------------ independent prescription flags
    flags = pd.concat([df.dropna(subset=["rx_required"]).assign(product_id=df["key"].map(pid))
                       [["product_id", "source", "rx_required"]] for df in extra.values() if "rx_required" in df])
    flags = flags.dropna(subset=["product_id"]).drop_duplicates(["product_id", "source"])
    flags["rx_required"] = flags["rx_required"].astype(bool)
    flags.to_parquet(OUT / "rx_flags.parquet", index=False)

    # ------------------------------------------------------------ compositions & ingredients
    sub = products[products["substitutable"]]
    compositions = (
        sub.groupby("composition_id")
        .agg(composition_key=("composition_key", "first"), composition=("composition", "first"),
             form=("form", "first"), release=("release", "first"), n_products=("product_id", "nunique"))
        .reset_index()
    )
    ingredients = (
        products.explode("ingredients").dropna(subset=["ingredients"])
        .groupby("ingredients").agg(n_products=("product_id", "nunique")).reset_index()
        .rename(columns={"ingredients": "ingredient"}).sort_values("n_products", ascending=False)
    )

    product_cols = [
        "product_id", "key", "name", "manufacturer", "form", "release", "composition", "composition_raw",
        "composition_source", "composition_status", "composition_votes", "n_components", "ingredients",
        "composition_key", "composition_id", "strengths_complete", "substitutable", "canonical_id", "is_alias",
        "all_discontinued", "therapeutic_class", "action_class", "chemical_class", "sub_category", "habit_forming",
        "url_1mg", "url_apollo", "url_netmeds", "image_url", "price_mohneesh_inr", "review_excellent_pct",
        "rating_count",
    ]
    products = products[product_cols]
    products.to_parquet(OUT / "products.parquet", index=False)
    skus.to_parquet(OUT / "skus.parquet", index=False)
    compositions.to_parquet(OUT / "compositions.parquet", index=False)
    ingredients.to_parquet(OUT / "ingredients.parquet", index=False)

    report = quality_report(products, skus, compositions, ingredients, az, mid, mo, k11)
    (OUT / "quality_report.json").write_text(json.dumps(report, indent=2, default=str))
    return report


def quality_report(products, skus, compositions, ingredients, az, mid, mo, k11) -> dict:
    multi = compositions[compositions["n_products"] > 1]
    return {
        "sources": {"az_rows": len(az), "mid_unique": len(mid), "mohneesh_unique": len(mo), "k11_unique": len(k11)},
        "products": len(products),
        "skus": len(skus),
        "composition_source": products["composition_source"].value_counts().to_dict(),
        "composition_status": products["composition_status"].value_counts().to_dict(),
        "strengths_complete_pct": round(100 * products["strengths_complete"].mean(), 2),
        "substitutable": int(products["substitutable"].sum()),
        "form": products["form"].value_counts().to_dict(),
        "release": products["release"].value_counts().to_dict(),
        "compositions_substitutable": len(compositions),
        "compositions_with_alternatives": len(multi),
        "products_with_alternatives": int(multi["n_products"].sum()),
        "distinct_ingredients": len(ingredients),
        "skus_pack_parsed_pct": round(100 * skus["pack_quantity"].notna().mean(), 2),
        "skus_price_per_unit_pct": round(100 * skus["price_per_unit_inr"].notna().mean(), 2),
        "skus_price_outlier": int(skus["price_outlier"].sum()),
        "aliases": int(products["is_alias"].sum()),
        "with_apollo_url": int(products["url_apollo"].notna().sum()),
        "with_rating_count": int(products["rating_count"].notna().sum()),
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, default=str))
