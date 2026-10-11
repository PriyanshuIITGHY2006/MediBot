"""In-process read access to the medicine catalog for the Safety Kernel.

Loads the processed parquet files once (≈5 s, ≈1.5 GB RAM). The kernel deliberately depends on these
facts only — never on an LLM — so its decisions are deterministic and testable.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "data/pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

from search_index import MedicineIndex  # noqa: E402

P = ROOT / "data/processed"


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    manufacturer: str | None
    form: str
    composition: str | None
    composition_id: str | None
    ingredients: tuple[str, ...]
    category: str                    # product_safety category
    requires_prescription: bool
    reasons: str
    legal_refs: str
    discontinued: bool = False
    urls: tuple[tuple[str, str], ...] = ()   # (platform, product-page URL) for live price checks


@dataclass(frozen=True)
class Ingredient:
    name: str
    schedule: str | None             # H | H1 | X | NDPS | None
    schedule_refs: str
    is_corticosteroid: bool
    oral_otc: bool                   # allowed OTC by mouth (allowlist / nutraceutical rule)
    products: int = 0


@dataclass
class Catalog:
    index: MedicineIndex
    products: dict[str, Product]
    ingredients: dict[str, Ingredient]
    composition_members: dict[str, list[str]] = field(default_factory=dict)

    def product(self, product_id: str) -> Product | None:
        return self.products.get(product_id)

    def ingredient(self, name: str) -> Ingredient | None:
        return self.ingredients.get(name)


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    from safety import otc_rule_for  # data/pipeline/safety.py: the same rules that tagged the catalog

    p = pd.read_parquet(P / "products.parquet", columns=["product_id", "canonical_id", "is_alias", "name", "manufacturer",
                                                         "form", "composition", "composition_id", "ingredients",
                                                         "all_discontinued", "substitutable", "url_1mg", "url_apollo",
                                                         "url_netmeds"])
    s = pd.read_parquet(P / "product_safety.parquet")
    d = p.merge(s, on="product_id", how="left")
    # PharmEasy / Truemeds product pages matched from their sitemaps (data/pipeline/pharmacy_urls.py)
    extra: dict[str, list[tuple[str, str]]] = {}
    if (P / "pharmacy_urls.parquet").exists():
        for pl, u, pid in pd.read_parquet(P / "pharmacy_urls.parquet", columns=["platform", "url", "product_id"]) \
                .itertuples(index=False):
            extra.setdefault(pid, []).append((pl, u))
    products = {
        r.product_id: Product(r.product_id, r.name, r.manufacturer if isinstance(r.manufacturer, str) else None, r.form,
                              r.composition if isinstance(r.composition, str) else None,
                              r.composition_id if isinstance(r.composition_id, str) else None,
                              tuple(r.ingredients) if r.ingredients is not None else (), r.category,
                              bool(r.requires_prescription), r.reasons or "", r.legal_refs or "",
                              bool(r.all_discontinued) if pd.notna(r.all_discontinued) else False,
                              tuple((pl, u) for pl, u in (("1mg", r.url_1mg), ("apollo", r.url_apollo),
                                                          ("netmeds", r.url_netmeds)) if isinstance(u, str))
                              + tuple(extra.get(r.product_id, ())))
        for r in d.itertuples()
    }
    ing = pd.read_parquet(P / "ingredient_safety.parquet")
    counts = pd.read_parquet(P / "ingredients.parquet").set_index("ingredient")["n_products"]
    ingredients = {}
    for r in ing.itertuples():
        rule = otc_rule_for(r.ingredient)
        oral = bool(rule and rule.routes & {"oral_solid", "oral_liquid"})
        ingredients[r.ingredient] = Ingredient(r.ingredient, r.schedule if isinstance(r.schedule, str) else None,
                                               r.schedule_refs or "", bool(r.is_corticosteroid), oral,
                                               int(counts.get(r.ingredient, 0)))
    members: dict[str, list[str]] = {}
    for pid, cid, alias, sub in zip(p.product_id, p.composition_id, p.is_alias, p.substitutable):
        if isinstance(cid, str) and not alias and sub:
            members.setdefault(cid, []).append(pid)
    return Catalog(MedicineIndex.load(), products, ingredients, members)
