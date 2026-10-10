"""Parse the Jan Aushadhi (PMBJP) product list and map it onto catalog Composition IDs.

Input:  data/raw/jan_aushadhi/products_mrp.json
        data/processed/ingredients.parquet, compositions.parquet (from build_catalog.py)
Output: data/processed/jan_aushadhi.parquet

Jan Aushadhi names are free text, e.g.
  "Amoxycillin 500mg and Potassium Clavulanate 125mg Tablets IP"
  "Aceclofenac Tablets IP 100 mg"
  "Sucralfate 1g and Oxetacaine 10mg Suspension per 10ml"
so they are rewritten into the catalog's "Ingredient (strength) + ..." form and run through
the same normaliser, which guarantees identical Composition IDs for identical medicines.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from normalize import (  # noqa: E402
    composition_id,
    composition_key,
    composition_text,
    normalize_ingredient,
    parse_composition,
    parse_form,
    parse_release,
)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw/jan_aushadhi/products_mrp.json"
OUT = ROOT / "data/processed"

NON_DRUG_GROUPS = {"Surgical & Medical Consumables", "Nutraceuticals", "Ayush", "Food Products", "Cosmetics"}

_STRENGTH = (r"(\d+(?:\.\d+)?)\s*(million spores|billion spores|billion cfu|mg|mcg|µg|gm|g|iu|i\.u\.|"
             r"%\s*w/w|%\s*w/v|%\s*v/v|%)(?![a-z])")
_FORM_WORDS = re.compile(
    r"\b(film[- ]coated|uncoated|sugar[- ]coated|enteric[- ]coated|gastro[- ]resistant|sustained[- ]release|"
    r"prolonged[- ]release|extended[- ]release|controlled[- ]release|modified[- ]release|delayed[- ]release|"
    r"orally disintegrating|mouth dissolving|dispersible|chewable|effervescent|soft gelatin|hard gelatin|"
    r"tablets?|capsules?|injection|infusion|for injection|powder|oral|suspension|syrup|dry syrup|solution|"
    r"cream|gel|ointment|lotion|drops?|eye|ear|nasal|ophthalmic|opthalmic|spray|sachet|granules|respirator|"
    r"respiratory|inhaler|inhalation|respules|vial|pfs|prefilled syringe|kit|ip|bp|usp|i\.p\.?|"
    r"sr|er|xr|cr|pr|dt|md|mr)\b",
    re.I,
)
_SALT_WORDS = (
    "hydrochloride", "hcl", "sodium", "potassium", "maleate", "besylate", "besilate", "fumarate", "mesylate",
    "citrate", "sulphate", "sulfate", "phosphate", "acetate", "bromide", "dihydrate", "monohydrate",
    "trihydrate", "hyclate", "disodium", "calcium", "magnesium", "tromethamine", "arginine", "hemihydrate",
    "dipropionate", "propionate", "valerate", "nitrate", "furoate", "pamoate", "embonate", "lactate",
)
_EXTRA_SALTS = ("oxalate", "hydrobromide", "succinate", "tartrate", "mononitrate", "dinitrate", "bitartrate",
                "malate", "tosylate", "camsylate", "napsylate", "olamine", "teoclate")


def _vocab() -> set[str]:
    return set(pd.read_parquet(OUT / "ingredients.parquet")["ingredient"])


def map_ingredient(name: str, vocab: set[str]) -> str:
    """Catalog spelling for a Jan Aushadhi ingredient, tried in order:
    exact -> drop salt words -> add a salt word (only if exactly one catalog candidate).
    Salt words change only when the catalog uses the other form, so metoprolol succinate/tartrate stay distinct."""
    n = normalize_ingredient(name)
    if n in vocab:
        return n
    words = n.split()
    for drop_from_end in range(1, len(words)):
        tail = words[-drop_from_end:]
        if all(w in _SALT_WORDS for w in tail):
            cand = normalize_ingredient(" ".join(words[:-drop_from_end]))
            if cand in vocab:
                return cand
    for i, w in enumerate(words):  # leading salt: "potassium clavulanate", "sodium valproate"
        if w in _SALT_WORDS:
            cand = normalize_ingredient(" ".join(words[:i] + words[i + 1:]))
            if cand in vocab:
                return cand
    with_salt = [v for v in vocab if v.startswith(n + " ") and all(w in _SALT_WORDS + _EXTRA_SALTS for w in v[len(n) + 1:].split())]
    if len(with_salt) == 1:  # "escitalopram" -> "escitalopram oxalate"; ambiguous "metoprolol" is left alone
        return with_salt[0]
    # No fuzzy matching: near-identical names are often different drugs (omeprazole/esomeprazole,
    # artemether/arteether, cloxacillin/dicloxacillin). Typos go into data/reference/ingredient_synonyms.csv.
    return n


def to_catalog_composition(generic_name: str, vocab: set[str]) -> str | None:
    text = generic_name.replace(" ", " ")
    text = re.sub(r"\([^()]*\)", lambda m: m[0] if re.search(_STRENGTH, m[0], re.I) else " ", text)  # drop "(Alkalyser)"
    text = re.sub(r"(?<=\d),(?=\d)", "", text)  # Indian digit grouping: 15,00,000 IU
    text = re.sub(r"\s+", " ", text).strip()
    per = re.search(r"\bper\s*(\d+(?:\.\d+)?)?\s*ml\b", text, re.I)
    per_ml = f"/{per[1] or 1}ml" if per else ""
    text = re.sub(r"\bper\s*(\d+(?:\.\d+)?)?\s*ml\b", " ", text, flags=re.I)

    segments = re.split(r"\s+and\s+|\s*\+\s*|,\s*(?=[A-Za-z])", text, flags=re.I)
    parts = []
    for seg in segments:
        strengths = list(re.finditer(_STRENGTH, seg, re.I))
        if not strengths:
            return None  # every component needs a stated strength
        m = strengths[-1]
        name = (seg[: m.start()] + " " + seg[m.end():])
        name = re.sub(_STRENGTH, " ", name, flags=re.I)
        name = re.sub(r"\b\d+(?:\.\d+)?\s*ml\b", " ", name, flags=re.I)  # pack volume inside the name
        name = _FORM_WORDS.sub(" ", name)
        name = re.sub(r"[^A-Za-z0-9\-' ]", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            return None
        unit = re.sub(r"\s+", " ", m[2].lower()).replace("% w", "% w")
        parts.append(f"{map_ingredient(name, vocab).title()} ({m[1]}{unit}{per_ml if '%' not in unit else ''})")
    return " + ".join(parts) if parts else None


def parse_unit_size(s: str) -> tuple[float | None, str | None]:
    s = (s or "").lower()
    if m := re.search(r"(\d+)\s*'s", s):
        return float(m[1]), "unit"
    if m := re.search(r"(\d+(?:\.\d+)?)\s*ml", s):
        return float(m[1]), "ml"
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gm)\b", s):
        return float(m[1]), "g"
    if re.search(r"vial|one|single|1 ?no", s):
        return 1.0, "unit"
    return None, None


def build() -> dict:
    vocab = _vocab()
    known = set(pd.read_parquet(OUT / "compositions.parquet")["composition_id"])
    rows = json.loads(RAW.read_text())["responseBody"]["newProductResponsesList"]
    out = []
    for r in rows:
        name = r["genericName"].replace(" ", " ").strip()
        mrp = r.get("mrp") or 0
        is_drug = r.get("groupName") not in NON_DRUG_GROUPS
        comp_text = to_catalog_composition(name, vocab) if is_drug else None
        comps = parse_composition(comp_text) if comp_text else []
        form, release = parse_form(name), parse_release(name)
        key = composition_key(comps, form, release)
        cid = composition_id(key)
        qty, unit = parse_unit_size(r.get("unitSize", ""))
        out.append({
            "drug_code": r["drugCode"], "generic_name": name, "group": r.get("groupName"),
            "unit_size": r.get("unitSize"), "mrp_inr": mrp, "pack_quantity": qty, "pack_unit": unit,
            "price_per_unit_inr": (mrp / qty) if (mrp and qty) else None,
            "composition": composition_text(comps) if comps else None, "form": form, "release": release,
            "composition_key": key, "composition_id": cid,
            "is_drug": is_drug, "usable": bool(is_drug and mrp > 0 and cid),
            "matches_catalog": cid in known,
        })
    df = pd.DataFrame(out)
    df.to_parquet(OUT / "jan_aushadhi.parquet", index=False)
    drugs = df[df.is_drug & (df.mrp_inr > 0)]
    return {
        "rows": len(df), "drug_rows_with_mrp": len(drugs),
        "parsed_composition": int(drugs.composition_id.notna().sum()),
        "matches_catalog": int(drugs.matches_catalog.sum()),
        "match_rate_pct": round(100 * drugs.matches_catalog.mean(), 1),
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
