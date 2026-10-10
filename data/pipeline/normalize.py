"""Normalisation primitives for the medicine catalog.

Everything that decides whether two products are "the same medicine" lives here:
composition parsing, ingredient canonicalisation, strength units, dosage form,
release type, pack size, and the Composition ID built from them.

Design rule: when in doubt, keep things DIFFERENT. A false split only hides a
cheaper substitute; a false merge recommends a non-identical medicine.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "reference"

# ---------------------------------------------------------------- ingredients


@lru_cache(maxsize=1)
def _synonyms() -> dict[str, str]:
    path = REFERENCE / "ingredient_synonyms.csv"
    if not path.exists():
        return {}
    with open(path, newline="") as f:
        return {r["variant"].strip().lower(): r["canonical"].strip().lower() for r in csv.DictReader(f)}


def normalize_ingredient(name: str) -> str:
    n = name.lower().replace(" ", " ")
    n = re.sub(r"[‐-―]", "-", n)
    n = re.sub(r"\s+", " ", n).strip(" .,;:-")
    n = re.sub(r"\s*-\s*", "-", n)
    n = re.sub(r"\s+(ip|bp|usp|ph\.?\s?eur|i\.p\.?|b\.p\.?)$", "", n)  # "Chloroxylenol IP" -> "chloroxylenol"
    # "Vitamin B6 (Pyridoxine)", "Paracetamol(Acetaminophen)": alias in brackets (letters only)
    n = re.sub(r"\s*\(([a-z][a-z\s\-]*)\)", "", n).strip()
    # "Paracetamol/Acetaminophen", "Insulin Isophane/NPH": one ingredient written with its alias.
    if "/" in n and re.search(r"[a-z]{3,}\s*/\s*[a-z]", n):
        n = n.split("/")[0].strip()
    return _synonyms().get(n, n)


# ---------------------------------------------------------------- strengths

_MASS_TO_MG = {"mg": 1.0, "mcg": 0.001, "µg": 0.001, "ug": 0.001, "gm": 1000.0, "g": 1000.0, "kg": 1e6}
_VOLUME_TO_ML = {"ml": 1.0, "l": 1000.0}
_UNIT_ALIASES = {
    "i.u": "iu", "i.u.": "iu", "iu": "iu", "units": "unit", "unit": "unit", "u": "unit",
    "million iu": "million_iu", "millioniu": "million_iu",
    "million spores": "million_spores", "millionspores": "million_spores", "mspores": "million_spores",
    "billion spores": "billion_spores", "billionspores": "billion_spores",
    "billion cfu": "billion_cfu", "billioncfu": "billion_cfu",
    "million cells": "million_cells", "millioncells": "million_cells", "billion cells": "billion_cells",
    "% w/w": "pct_ww", "%w/w": "pct_ww", "% w/v": "pct_wv", "%w/v": "pct_wv",
    "% v/v": "pct_vv", "%v/v": "pct_vv", "%": "pct",
}


@dataclass(frozen=True)
class Strength:
    value: float
    unit: str  # canonical, e.g. "mg", "mg/ml", "pct_ww", "iu", "million_spores"

    def key(self) -> str:
        return f"{self.value:.6g}{self.unit}"

    def __str__(self) -> str:  # human readable
        return f"{self.value:g} {self.unit.replace('pct_', '% ').replace('_', ' ')}"


_NUM = r"(\d+(?:\.\d+)?)"


def parse_strength(raw: str | None) -> Strength | None:
    """'500mg' -> 500 mg; '200mg/5ml' -> 40 mg/ml; '2% w/w' -> 2 pct_ww; 'NA' -> None."""
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw).strip().lower())
    if not s or s in {"na", "n/a", "-", "nil"}:
        return None

    # mass per volume / mass:  500mg/5ml, 1gm/10ml, 50mcg/ml, 10mg/gm
    m = re.fullmatch(rf"{_NUM} ?(mg|mcg|µg|ug|gm|g)\s*/\s*{_NUM}? ?(ml|l|gm|g)", s)
    if m:
        val, mass, per, per_unit = float(m[1]), m[2], float(m[3] or 1), m[4]
        mg = val * _MASS_TO_MG[mass]
        if per_unit in _VOLUME_TO_ML:
            return Strength(round(mg / (per * _VOLUME_TO_ML[per_unit]), 6), "mg/ml")
        return Strength(round(mg / (per * 1000.0), 6), "mg/mg")  # per gram -> fraction

    # IU per volume: 1000IU/ml, 2000iu/5ml
    m = re.fullmatch(rf"{_NUM} ?(iu|i\.u\.?|units?|u)\s*/\s*{_NUM}? ?(ml|gm|g)", s)
    if m:
        per = float(m[3] or 1)
        return Strength(round(float(m[1]) / per, 6), f"iu/{'ml' if m[4] == 'ml' else 'g'}")

    # plain mass: 500mg, 1.2gm, 50 mcg
    m = re.fullmatch(rf"{_NUM} ?(mg|mcg|µg|ug|gm|g|kg)", s)
    if m:
        return Strength(round(float(m[1]) * _MASS_TO_MG[m[2]], 6), "mg")

    # plain volume (e.g. "5ml" of a liquid ingredient)
    m = re.fullmatch(rf"{_NUM} ?(ml)", s)
    if m:
        return Strength(float(m[1]), "ml")

    # everything else: number + recognised unit token
    m = re.fullmatch(rf"{_NUM} ?(.+)", s)
    if m:
        unit = _UNIT_ALIASES.get(m[2].strip())
        if unit:
            return Strength(float(m[1]), unit)
    return None  # unknown format -> treated as "strength not stated"


# ---------------------------------------------------------------- composition


@dataclass(frozen=True)
class Component:
    ingredient: str            # canonical lowercase name
    strength: Strength | None  # None = not stated / unparseable
    raw: str

    def key(self) -> str:
        return f"{self.ingredient}:{self.strength.key() if self.strength else '?'}"


_COMPONENT = re.compile(r"^(?P<ing>.*?)\s*\((?P<str>[^()]*)\)\s*$")


def parse_composition(text: str | None) -> list[Component]:
    """'Amoxycillin  (500mg)+  Clavulanic Acid (125mg)' -> two Components (sorted by ingredient)."""
    if text is None or (isinstance(text, float)) or not str(text).strip():
        return []
    comps = []
    for part in re.split(r"\s*\+\s*", str(text).strip()):
        part = part.strip()
        if not part:
            continue
        m = _COMPONENT.match(part)
        if m:
            comps.append(Component(normalize_ingredient(m["ing"]), parse_strength(m["str"]), part))
        else:
            comps.append(Component(normalize_ingredient(part), None, part))
    return sorted(comps, key=lambda c: (c.ingredient, c.strength.key() if c.strength else ""))


_UNIT_TOKEN = r"(?:mg|mcg|µg|gm|g|iu|i\.u\.|%\s*w/w|%\s*w/v|%\s*v/v|%|ml|million spores|billion spores|billion cfu|lac|units?)"
_INLINE_PART = re.compile(rf"^(?P<name>.*?[a-z\)])[\s\-]+(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT_TOKEN})(?P<per>\s*/\s*\d*(?:\.\d+)?\s*(?:ml|gm|g))?\s*$", re.I)


def to_standard_composition(text: str | None) -> str | None:
    """Rewrite other sources' composition formats into the 1mg form "Name (500mg) + Name (125mg)".

    Handles three styles:
      1mg:     "Paracetamol (650mg) + Caffeine (50mg)"                 (returned unchanged)
      inline:  "DOMPERIDONE 30MG+RABEPRAZOLE SODIUM 20MG", "LEVOCETIRIZINE-5MG"
      zipped:  "DEXTROSE+ POTASSIUM CHLORIDE+ SODIUM CHLORIDE-2.7+ 0.3+ 0.52GM+ GM+ GM"   (Apollo)
    Returns None when the text can't be read unambiguously (no guessing).
    """
    if not isinstance(text, str):
        return None
    t = re.sub(r"\s+", " ", text.replace(" ", " ")).strip(" +,;")
    if t.startswith("[") and t.endswith("]"):  # JSON-style list: ["cefixime (200mg) ", " lactobacillus (na)"]
        items = re.findall(r'"([^"]*)"', t) or re.findall(r"'([^']*)'", t)
        t = " + ".join(i.strip() for i in items if i.strip())
        if not t:
            return None
    t = re.sub(r"^generic name\s*", "", t, flags=re.I)
    t = re.split(r"\s+also known as", t, flags=re.I)[0].strip()
    if not t or re.fullmatch(r"(?i)ayurvedic|homeopathic|unani|siddha|na|nan|none|-", t):
        return None
    if "(" in t and re.search(r"\(\s*[\d.]", t):
        return t  # already 1mg style

    # zipped (Apollo): names joined by "+", then "-", then values, then units, each list "+"-joined
    m = re.fullmatch(r"(?P<names>[^-]+?)-(?P<rest>[\d.\s+]+[a-z%/\s.+0-9]*)", t, re.I)
    if m and "+" in m["names"]:
        names = [n.strip() for n in m["names"].split("+") if n.strip()]
        rest = m["rest"].replace(" ", "")
        vals = re.findall(r"\d+(?:\.\d+)?", rest.split(re.findall(r"[a-z%]", rest, re.I)[0])[0]) if re.search(r"[a-z%]", rest, re.I) else []
        units_part = rest[len("+".join(vals)):] if vals else ""
        units = [u for u in re.split(r"\+", units_part) if u]
        if len(names) == len(vals) and len(units) in (1, len(vals)):
            units = units * len(vals) if len(units) == 1 else units
            return " + ".join(f"{n.title()} ({v}{u.lower()})" for n, v, u in zip(names, vals, units))
        return None

    # inline: each "+"-part ends with a strength
    parts, out = [p.strip() for p in t.split("+") if p.strip()], []
    for p in parts:
        mm = _INLINE_PART.match(p)
        if not mm:
            return None
        per = (mm["per"] or "").replace(" ", "").lower()
        out.append(f"{mm['name'].strip(' -').title()} ({mm['val']}{mm['unit'].lower()}{per})")
    return " + ".join(out) if out else None


def composition_text(comps: list[Component]) -> str:
    return " + ".join(f"{c.ingredient.title()} {c.strength}" if c.strength else c.ingredient.title() for c in comps)


# ---------------------------------------------------------------- form & release

# Ordered: first match wins, so specific phrases come before generic ones.
_FORMS: list[tuple[str, str]] = [
    (r"powder for (?:injection|infusion)|for injection", "injection"),
    (r"injection|injections|infusion|\bvial\b|ampoule|prefilled syringe|\bpen\b|\bcartridge\b", "injection"),
    (r"(antacid|antigas|acidity|gas relief|heartburn).{0,40}\bgel\b|\bgel\b.{0,40}(antacid|acidity)|antigas gel", "suspension"),
    (r"dry syrup", "dry_syrup"),
    (r"syrup|linctus|elixir|\btonic\b|expectorant", "syrup"),
    (r"oral suspension|suspension", "suspension"),
    (r"oral drops?|paediatric drops?|pediatric drops?", "oral_drops"),
    (r"eye/ear drops?|eye ?& ?ear drops?", "eye_ear_drops"),
    (r"eye drops?|ophthalmic solution|opthalmic solution|ophthalmic suspension|opthalmic suspension", "eye_drops"),
    (r"eye ointment|ophthalmic ointment", "eye_ointment"),
    (r"eye gel", "eye_gel"),
    (r"ear drops?", "ear_drops"),
    (r"nasal drops?", "nasal_drops"),
    (r"nasal spray", "nasal_spray"),
    (r"respules?|nebuli[sz]er|nebuli[sz]ing solution|inhalation solution", "nebuliser"),
    (r"rotacaps?|transcaps?|redicaps?|inhalation capsule", "inhalation_capsule"),
    (r"inhaler|\bmdi\b|evohaler|autohaler|synchrobreathe|accuhaler|turbuhaler|diskus", "inhaler"),
    (r"oral solution|solution|liquid", "solution"),
    (r"mouth ?wash|gargle", "mouthwash"),
    (r"oral gel|gum paint", "oral_gel"),
    (r"vaginal (?:tablet|insert)|pessary", "vaginal_tablet"),
    (r"vaginal (?:cream|gel)", "vaginal_cream"),
    (r"suppository|suppositories", "suppository"),
    (r"dispersible tablet|tablet dt|dt tablet|\bdt\b", "tablet_dispersible"),
    (r"mouth dissolving|orally disintegrating|tablet md|md tablet|\bmd\b|\bodt\b", "tablet_mouth_dissolving"),
    (r"chewable", "tablet_chewable"),
    (r"effervescent", "tablet_effervescent"),
    (r"soft ?gelatin capsules?|softgels?|soft gel", "capsule_softgel"),
    (r"capsules?", "capsule"),
    (r"tablets?|\btab\b|caplets?", "tablet"),
    (r"granules?|sachet", "granules"),
    (r"dusting powder", "dusting_powder"),
    (r"powder", "powder"),
    (r"cream", "cream"),
    (r"ointment", "ointment"),
    (r"lotion", "lotion"),
    (r"emulsion", "emulsion"),
    (r"gel|jelly", "gel"),
    (r"shampoo", "shampoo"),
    (r"soap|body wash|face wash|cleanser", "soap"),
    (r"transdermal patch|patch", "patch"),
    (r"spray", "spray"),
    (r"lozenges?", "lozenge"),
    (r"kit", "kit"),
]
_FORM_RES = [(re.compile(p, re.I), f) for p, f in _FORMS]

# Release words AFTER the form word ("Tablet SR") are reliable. Before the form word,
# "MR" is usually a brand suffix (muscle relaxant combos), so it is ignored there.
_RELEASE = {
    "sr": "SR", "sustained release": "SR",
    "er": "ER", "xr": "ER", "xl": "ER", "extended release": "ER", "la": "ER", "retard": "ER",
    "pr": "PR", "prolonged release": "PR",
    "cr": "CR", "cd": "CR", "controlled release": "CR",
    "mr": "MR", "modified release": "MR",
    "dr": "DR", "delayed release": "DR",
    "ec": "EC", "enteric coated": "EC", "gastro-resistant": "EC", "gastro resistant": "EC",
    "od": "OD",
}
_RELEASE_AFTER_FORM = re.compile(
    r"\b(?:tablets?|capsules?)\s+(sustained release|extended release|prolonged release|controlled release|"
    r"modified release|delayed release|sr|er|xr|xl|pr|cr|cd|mr|dr|ec|od|la)\b", re.I)
# Before/without a form word only unambiguous markers count ("Dr. Ortho", "Calcimax CD" are brands).
_RELEASE_ANYWHERE = re.compile(
    r"\b(sustained release|extended release|prolonged release|controlled release|modified release|"
    r"delayed release|enteric coated|gastro[- ]resistant|sr|er|xr|xl|pr|cr|ec|od|retard)\b", re.I)


def parse_form(name: str, pack_label: str | None = None) -> str:
    """Dosage form from the product name, falling back to the pack label. Name first so that
    products from sources without pack labels (MID, mohneesh7) are classified the same way."""
    for text in (name, pack_label):
        if not isinstance(text, str) or not text:
            continue
        for rx, form in _FORM_RES:
            if rx.search(text):
                return form
    return "other"


# When several markers appear (e.g. "Omeprazole Gastro-resistant + Domperidone Sustained Release"),
# the product-level release is the sustained one; a coating marker alone is weaker information.
_RELEASE_PRIORITY = ["SR", "ER", "PR", "CR", "MR", "OD", "DR", "EC"]


def parse_release(name: str, pack_label: str | None = None) -> str:
    """'IR' unless a modified-release marker is present. Returns SR/ER/PR/CR/MR/DR/EC/OD."""
    for text in (name, pack_label):
        if not isinstance(text, str) or not text:
            continue
        found = {_RELEASE[m[1].lower().replace("-", " ")] for m in _RELEASE_AFTER_FORM.finditer(text)}
        found |= {_RELEASE[m[1].lower().replace("-", " ")] for m in _RELEASE_ANYWHERE.finditer(text)}
        if found:
            return min(found, key=_RELEASE_PRIORITY.index)
    return "IR"


# ---------------------------------------------------------------- pack size


@dataclass(frozen=True)
class Pack:
    quantity: float  # number of units in the pack
    unit: str        # "unit" (tablet/capsule/vial/...), "ml", "g"


_PACK = re.compile(r"of\s+(\d+(?:\.\d+)?)\s*(ml|gm|g|kg|l|mg)?\b", re.I)


def parse_pack(label: str | None) -> Pack | None:
    """'strip of 10 tablets' -> 10 unit; 'bottle of 100 ml Syrup' -> 100 ml; 'tube of 20 gm Gel' -> 20 g."""
    if not isinstance(label, str) or not label:
        return None
    m = _PACK.search(label)
    if not m:
        return None
    qty, unit = float(m[1]), (m[2] or "").lower()
    if qty <= 0:
        return None
    if unit in {"ml"}:
        return Pack(qty, "ml")
    if unit == "l":
        return Pack(qty * 1000, "ml")
    if unit in {"gm", "g"}:
        return Pack(qty, "g")
    if unit == "kg":
        return Pack(qty * 1000, "g")
    if unit == "mg":
        return Pack(qty / 1000, "g")
    return Pack(qty, "unit")


# ---------------------------------------------------------------- composition ID


# Molecules whose oral solid forms are always enteric-coated / delayed-release, so an explicit
# "gastro-resistant" / "DR" marker carries no extra information. Kept deliberately small:
# aspirin is NOT here because plain (non-EC) aspirin tablets are marketed too.
IMPLIED_EC = frozenset({
    "pantoprazole", "rabeprazole", "esomeprazole", "omeprazole", "lansoprazole", "dexlansoprazole",
    "dexrabeprazole", "ilaprazole", "mesalazine",
})


def composition_key(comps: list[Component], form: str, release: str) -> str | None:
    """Canonical, human-readable fingerprint. None when the product must never be matched
    (no components, or any component without a stated strength)."""
    if not comps or any(c.strength is None for c in comps):
        return None
    if release in {"EC", "DR"} and all(c.ingredient in IMPLIED_EC for c in comps):
        release = "IR"
    return "|".join(c.key() for c in comps) + f"#{form}#{release}"


def composition_id(key: str | None) -> str | None:
    return None if key is None else "c_" + hashlib.sha1(key.encode()).hexdigest()[:16]


def normalize_name(name: str) -> str:
    """Join key across sources: lowercase, unify spacing/punctuation."""
    n = str(name).lower().replace(" ", " ")
    n = re.sub(r"[‐-―]", "-", n)
    n = re.sub(r"\s+", " ", n)
    return n.strip()
