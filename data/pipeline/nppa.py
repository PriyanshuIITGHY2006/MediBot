"""Parse NPPA ceiling prices into a table keyed by Composition ID.

Inputs (data/raw/nppa/):
  2845-fb-posts-*.pdf          NLEM 2022 category lists, "As on March, 2026"  -> status "current"
  Compendium-Prices-2022*.pdf  NLEM 2015 compendium, updated 10.08.2022      -> status "historical"
Output: data/processed/nppa_ceiling.parquet

Only "current" rows may drive the "price above the government ceiling" flag: the 2022 compendium
predates NLEM 2022, and medicines dropped from NLEM 2022 are no longer price-controlled.

Category lists are read from word coordinates (`pdftotext -bbox`): cells are vertically centred,
so a medicine name can sit above its serial number. Each word is attached to the nearest serial;
each price to the closest serial at or above it. Rows whose dosage text is ambiguous (two forms
or more strengths than ingredients) are dropped rather than guessed.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from jan_aushadhi import map_ingredient  # noqa: E402  (same strict salt rule)
from normalize import (  # noqa: E402
    composition_id,
    composition_key,
    composition_text,
    parse_composition,
    parse_form,
    parse_release,
)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw/nppa"
OUT = ROOT / "data/processed"

_WORD = re.compile(r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)<')
_PAGE = re.compile(r"<page [^>]*>(.*?)</page>", re.S)
_STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|gm|iu|%)(?:\s*/\s*(\d+(?:\.\d+)?)?\s*(ml|g|gm))?", re.I)
_FORM_START = re.compile(r"\b(tablet|capsule|injection|oral liquid|syrup|suspension|drops?|cream|ointment|gel|"
                         r"inhalation|powder|solution|lotion|spray|patch|suppository|granules)\b", re.I)
_UNIT = re.compile(r"^1\s*(tablet|capsule|ml|gm|g)$", re.I)


# ---------------------------------------------------------------- shared


def _ingredients_from_medicine(medicine: str) -> list[str]:
    m = re.sub(r"\(\s*[A-D]\s*\)", "", medicine)  # "Lignocaine (A) + Adrenaline (B)"
    m = re.sub(r"\b(disposable pen containing|premix|intermediate acting)\b", " ", m, flags=re.I)
    return [p.strip() for p in re.split(r"\s*\+\s*|\s+and\s+", m) if p.strip()]


_VOCAB: set[str] = set()


def to_row(medicine: str, dosage: str, unit: str, price: float, source: str, status: str) -> dict | None:
    """Build one ceiling row; None if the dosage text can't be read unambiguously."""
    dosage = re.sub(r"\s+", " ", dosage).strip()
    if len(_FORM_START.findall(dosage)) != 1:
        return None  # zero or several forms in one cell -> ambiguous
    names = _ingredients_from_medicine(medicine)
    strengths = list(_STRENGTH.finditer(dosage))
    if not names or len(strengths) != len(names):
        return None
    parts = []
    for name, s in zip(names, strengths):
        per = f"/{s[3] or 1}{s[4]}" if s[4] else ""
        unit_s = s[2].lower() + (" w/v" if s[2] == "%" and "ml" in dosage.lower() else "")
        parts.append(f"{map_ingredient(name, _VOCAB).title()} ({s[1]}{unit_s}{per})")
    comps = parse_composition(" + ".join(parts))
    form = parse_form(dosage.replace("Oral liquid", "Oral Solution").replace("oral liquid", "oral solution"))
    release = parse_release(dosage)
    key = composition_key(comps, form, release)
    u = unit.lower()
    per_unit = "unit" if re.search(r"tablet|capsule", u) else ("ml" if "ml" in u else ("g" if re.search(r"\bg|gm", u) else None))
    if key is None or per_unit is None:
        return None
    return {
        "medicine": medicine, "dosage": dosage, "unit": unit, "ceiling_price_inr": price, "per": per_unit,
        "composition": composition_text(comps), "form": form, "release": release,
        "composition_key": key, "composition_id": composition_id(key), "source": source, "status": status,
    }


# ---------------------------------------------------------------- NLEM 2022 category lists (coordinates)


def _words(pdf: Path) -> list[list[tuple[float, float, float, str]]]:
    html = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    pages = []
    for page in _PAGE.findall(html):
        pages.append([(float(m[1]), (float(m[2]) + float(m[4])) / 2, float(m[3]), m[5]) for m in _WORD.finditer(page)])
    return pages


def parse_category_list(pdf: Path) -> list[dict]:
    rows = []
    for words in _words(pdf):
        serials = [(y, int(t)) for x, y, _, t in words if x < 120 and re.fullmatch(r"\d{1,3}", t)]
        if not serials:
            continue
        prices = [(y, float(t)) for x, y, _, t in words if x > 900 and re.fullmatch(r"\d+(?:\.\d+)?", t)]
        units: dict[float, list[str]] = {}
        cells: dict[int, dict[str, list[tuple[float, float, str]]]] = {s: {"medicine": [], "dosage": []} for _, s in serials}
        for x, y, _, t in words:
            if x < 120 or x > 900 or re.search(r"As on|Please note|medicines may|practitioner|www\.|nppa", t, re.I):
                continue
            if 780 <= x <= 900:
                units.setdefault(round(y, 0), []).append(t)
                continue
            col = "medicine" if x < 400 else "dosage"
            nearest = min(serials, key=lambda s: abs(s[0] - y))
            if abs(nearest[0] - y) <= 30:
                cells[nearest[1]][col].append((y, x, t))
        for py, price in prices:
            above = [s for s in serials if s[0] <= py + 5]
            if not above:
                continue
            sy, serial = max(above)
            unit = " ".join(units.get(round(py, 0), [])) or "1 Tablet"
            med = " ".join(t for _, _, t in sorted(cells[serial]["medicine"]))
            dos = " ".join(t for _, _, t in sorted(cells[serial]["dosage"]))
            med = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", med)  # "InsulinGlargine" -> "Insulin Glargine"
            row = to_row(med, dos, unit, price, pdf.name, "current")
            if row:
                row["serial"] = serial
                rows.append(row)
    return rows


# ---------------------------------------------------------------- 2022 compendium (text layout)

_COMP_ROW = re.compile(
    r"^\s*(?P<sec>\d+\.\d+(?:\.\d+)?)?\s*(?P<med>[A-Za-z][^\d]*?)?\s{2,}(?P<dos>\S.*?)\s{2,}(?P<unit>1\s*\S+|Each Pack[^\d]*)\s{2,}"
    r"(?P<price>\d+(?:\.\d+)?)\s+(?P<so>\d+\(E\))\s+(?P<date>\d{2}\.\d{2}\.\d{4})\s*$")


def parse_compendium(pdf: Path) -> list[dict]:
    text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    rows, medicine = [], None
    for line in text.splitlines():
        m = _COMP_ROW.match(line)
        if not m:
            continue
        if m["sec"] and m["med"]:
            medicine = m["med"].strip()
        elif m["med"] and not m["sec"]:
            continue  # name without section number: wrapped cell, unreliable
        if not medicine:
            continue
        row = to_row(medicine, m["dos"], m["unit"], float(m["price"]), pdf.name, "historical")
        if row:
            row.update(so_number=m["so"], notified=m["date"])
            rows.append(row)
    return rows


def build() -> dict:
    _VOCAB.update(pd.read_parquet(OUT / "ingredients.parquet")["ingredient"])
    current = [r for f in sorted(RAW.glob("2845-fb-posts-*.pdf")) for r in parse_category_list(f)]
    historical = [r for f in sorted(RAW.glob("Compendium-Prices-2022*.pdf")) for r in parse_compendium(f)]
    df = pd.DataFrame(current + historical)
    known = set(pd.read_parquet(OUT / "compositions.parquet")["composition_id"])
    df["matches_catalog"] = df["composition_id"].isin(known)
    df.to_parquet(OUT / "nppa_ceiling.parquet", index=False)
    # One ceiling per (composition, per-unit) for flagging: the HIGHEST current ceiling, because the
    # same composition can carry different ceilings by pack size (dexamethasone 4 mg/ml: Rs 0.93-5.21/ml).
    flag = (df[df.status == "current"].groupby(["composition_id", "per"], as_index=False)
            .agg(ceiling_price_inr=("ceiling_price_inr", "max"), composition=("composition", "first"),
                 n_rows=("ceiling_price_inr", "size")))
    flag.to_parquet(OUT / "nppa_ceiling_flag.parquet", index=False)
    by = df.groupby("status")
    return {
        "rows": by.size().to_dict(),
        "matches_catalog": by["matches_catalog"].sum().astype(int).to_dict(),
        "flaggable_compositions": int(len(flag)),
        "per_file_current": df[df.status == "current"].groupby("source").size().to_dict(),
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
