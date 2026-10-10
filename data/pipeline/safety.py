"""Phase 3: tag every ingredient and product with its prescription / legal status.

Policy (docs/SAFETY_POLICY.md) — decided 2026-10-09:
  * Deny by default: a product is OTC only if EVERY ingredient is on a sourced OTC allowlist for the
    product's route (with strength caps), or is a Schedule H substance in a topical form (legal exemption).
  * Schedule H/H1/X and NDPS substances follow the law, including commonly "OTC-feeling" ones
    (cetirizine, fexofenadine, ibuprofen, pantoprazole, domperidone ...).
  * Topical exemption (Schedule H note) applies, EXCEPT corticosteroids, and except antibiotic/steroid
    (here: any anti-infective or steroid) eye / ear / nose preparations.
  * Every cough / cold oral liquid is prescription (Drugs (Fifth Amendment) Rules 2026 removed
    "Syrups" from the Schedule K cough-remedy exemption).
  * Injections are always prescription; MID "habit forming = yes" is always prescription.
  * Banned = matches an in-force Section 26A prohibition (status "prohibited" only).

Outputs (data/processed/): ingredient_safety.parquet, product_safety.parquet, safety_report.json
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from normalize import normalize_ingredient, parse_composition  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "data/reference"
REG = ROOT / "data/interim/regulatory"
OUT = ROOT / "data/processed"

# ---------------------------------------------------------------- routes

ROUTE_OF_FORM = {
    **{f: "oral_solid" for f in ["tablet", "tablet_dispersible", "tablet_mouth_dissolving", "tablet_chewable",
                                 "tablet_effervescent", "capsule", "capsule_softgel", "granules", "powder", "lozenge"]},
    **{f: "oral_liquid" for f in ["syrup", "dry_syrup", "suspension", "solution", "oral_drops", "emulsion"]},
    **{f: "topical" for f in ["cream", "ointment", "gel", "lotion", "dusting_powder", "shampoo", "soap", "spray", "patch"]},
    **{f: "oral_care" for f in ["mouthwash", "oral_gel"]},
    **{f: "eye" for f in ["eye_drops", "eye_ointment", "eye_gel", "eye_ear_drops"]},
    "ear_drops": "ear",
    **{f: "nasal" for f in ["nasal_drops", "nasal_spray"]},
    **{f: "inhalation" for f in ["inhaler", "nebuliser", "inhalation_capsule"]},
    "injection": "injection",
    **{f: "vaginal" for f in ["vaginal_tablet", "vaginal_cream"]},
    "suppository": "rectal",
    "kit": "other", "other": "other",
}
AMBIGUOUS_FORMS = {"solution", "spray", "powder", "emulsion"}
DISCRIMINATIVE_FLAG_SOURCES = {"apollo", "apollo_otc", "netmeds_rx", "curated_otc"}  # could be oral or applied to the skin
TOPICAL_EXEMPT_ROUTES = {"topical", "oral_care"}   # Schedule H note: "topical or external use"
EYE_EAR_NOSE = {"eye", "ear", "nasal"}             # exempt unless antibiotic/steroid

SEVERITY = {"banned": 6, "controlled": 5, "schedule_h1": 4, "schedule_x": 5, "schedule_h": 3,
            "prescription": 2, "otc_unverified": 1, "otc": 0}

# ---------------------------------------------------------------- names

SALT_WORDS = set("""hydrochloride hcl dihydrochloride sodium potassium maleate besylate besilate fumarate mesylate
mesilate citrate sulphate sulfate phosphate acetate bromide hydrobromide dihydrate monohydrate trihydrate hyclate
disodium calcium magnesium tromethamine arginine hemihydrate dipropionate propionate valerate nitrate furoate
pamoate embonate lactate oxalate succinate tartrate bitartrate malate tosylate gluconate its salts salt and
derivatives of preparations formulations for human use""".split())


@lru_cache(maxsize=None)
def base(name: str) -> str:
    """Molecule name without salt / packaging words: 'Cetirizine hydrochloride' -> 'cetirizine'."""
    n = normalize_ingredient(re.sub(r"\(.*?\)|\[|\]|\d+(\.\d+)?\s*(mg|mcg|g|%|iu)\b\S*", " ", str(name)))
    words = [w for w in re.split(r"[\s,]+", n) if w and w not in SALT_WORDS]
    return " ".join(words)


@lru_cache(maxsize=None)
def tokens(name: str) -> frozenset[str]:
    return frozenset(re.split(r"[\s\-,/]+", base(name))) - {""}


# ---------------------------------------------------------------- reference data


@dataclass
class OtcRule:
    routes: set[str]
    cap_value: float | None
    cap_unit: str | None
    source: str


def _cap(text: str) -> tuple[float | None, str | None]:
    m = re.match(r"\s*([\d.]+)\s*(mg|%|iu)\s*$", text or "", re.I)
    return (float(m[1]), m[2].lower()) if m else (None, None)


@lru_cache(maxsize=1)
def references() -> dict:
    sched = pd.concat([pd.read_csv(REG / f"schedule_{s}.csv") for s in ["h", "h1", "x"]])
    sched["base"] = sched["substance"].map(base)
    with open(REF / "otc_allowlist.csv", newline="") as f:
        otc = {}
        for r in csv.DictReader(f):
            v, u = _cap(r["max_strength"])
            otc[normalize_ingredient(r["ingredient"])] = OtcRule(set(r["routes"].split(";")), v, u, r["source"])
    with open(REF / "nutraceutical_patterns.csv", newline="") as f:
        nutra = []
        for r in csv.DictReader(f):
            v, u = _cap(r["max_strength"])
            nutra.append((re.compile(r["pattern"]), OtcRule(set(r["routes"].split(";")), v, u, r["source"])))
    with open(REF / "controlled_substances.csv", newline="") as f:
        controlled = {base(r["ingredient"]): (r["category"], r["source"]) for r in csv.DictReader(f)}
    with open(REF / "banned_single_rules.csv", newline="") as f:
        banned_single = [r for r in csv.DictReader(f)]
    banned = pd.read_csv(REG / "banned_all.csv", keep_default_na=False)
    return {"sched": sched, "otc": otc, "nutra": nutra, "controlled": controlled,
            "banned_single": banned_single, "banned": banned}


# ---------------------------------------------------------------- ingredient classes

_ANTIBIOTIC_CLASS = re.compile(r"antibiotic|penicillin|cephalosporin|quinolone|macrolide|aminoglycoside|tetracycline|"
                               r"carbapenem|glycopeptide|lincosamide|oxazolidinone|sulfonamide|sulphonamide|"
                               r"nitroimidazole|polymyxin|beta.?lactam|antibacterial|rifamycin", re.I)
_ANTIINFECTIVE_CLASS = re.compile(r"antifungal|fungal|antiviral|anti-?viral|antiprotozoal|anthelmintic|"
                                  r"antimalarial|antitubercular|anti.?tb|antiretroviral|nrti|nnrti|protease inhibitor", re.I)
_STEROID_CLASS = re.compile(r"glucocorticoid|corticosteroid|mineralocorticoid", re.I)
_SEX_HORMONE_CLASS = re.compile(r"estrogen|oestrogen|progest|androgen|anabolic|testosterone", re.I)
_ANTIBIOTIC_NAME = re.compile(r"cillin|^cef|^ceph|mycin|micin|cycline|floxacin|penem|bactam|^sulfa|^sulpha|"
                              r"trimethoprim|nitrofurantoin|fusidic|mupirocin|polymyxin|bacitracin|framycetin|"
                              r"linezolid|vancomycin|teicoplanin|colistin|metronidazole|ornidazole|tinidazole|"
                              r"secnidazole|rifaximin|chloramphenicol|nadifloxacin|ozenoxacin|retapamulin")
_STEROID_NAME = re.compile(r"(?:^|\s)(?:\w*(?:methasone|metasone|cortisone|nisolone|nisone|olone|cort\w*|betasol|"
                           r"clobetasol|clobetasone|fluticasone|budesonide|beclomethasone|beclometasone|mometasone|"
                           r"desonide|halcinonide|halobetasol|fluocinonide|fluocinolone|triamcinolone|deflazacort|"
                           r"difluprednate|loteprednol|ciclesonide|fluorometholone|desoximetasone|prednicarbate))(?:\s|$)")
_ANTIINFECTIVE_NAME = re.compile(r"conazole|^nystatin|amphotericin|terbinafine|butenafine|ciclopirox|amorolfine|"
                                 r"acyclovir|aciclovir|valacyclovir|ganciclovir|famciclovir|natamycin|"
                                 r"povidone iodine|silver sulfadiazine|silver sulphadiazine")


def ingredient_classes(products: pd.DataFrame) -> pd.DataFrame:
    """Per-ingredient class flags from MID classes of single-ingredient products + name patterns."""
    single = products[products["n_components"] == 1].copy()
    single["ingredient"] = single["ingredients"].str[0]
    labels = (single.assign(lbl=single["action_class"].fillna("") + " | " + single["chemical_class"].fillna("") + " | "
                            + single["therapeutic_class"].fillna(""))
              .groupby("ingredient")["lbl"].agg(lambda s: " || ".join(sorted(set(s)))[:2000]))
    vocab = sorted({i for ings in products["ingredients"] for i in ings})
    rows = []
    for ing in vocab:
        lbl = labels.get(ing, "")
        b = base(ing)
        rows.append({
            "ingredient": ing, "base": b, "class_labels": lbl,
            "is_antibiotic": bool(_ANTIBIOTIC_CLASS.search(lbl) or _ANTIBIOTIC_NAME.search(b)),
            "is_corticosteroid": bool(_STEROID_CLASS.search(lbl) or _STEROID_NAME.search(" " + b + " ")),
            "is_sex_hormone": bool(_SEX_HORMONE_CLASS.search(lbl)),
            "is_antiinfective_other": bool(_ANTIINFECTIVE_CLASS.search(lbl) or _ANTIINFECTIVE_NAME.search(b)),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- ingredient legal status


def schedule_hits(ing: str, cls: dict) -> list[tuple[str, int, str]]:
    """(schedule, serial, entry) for every schedule entry covering this ingredient."""
    ref = references()["sched"]
    t, b = tokens(ing), base(ing)
    hits = []
    for r in ref.itertuples():
        st = set(re.split(r"[\s\-,/]+", r.base)) - {""}
        if not st:
            continue
        # whole-token containment: "s-amlodipine" is covered by "amlodipine" (Schedule notes cover salts,
        # esters, derivatives and isomers); short tokens must match exactly to avoid "vitamin a" style noise
        if b == r.base or (len(r.base) >= 6 and st <= t):
            hits.append((r.schedule, int(r.serial), r.substance))
    if cls.get("is_antibiotic"):
        hits.append(("H", 32, "Antibiotics"))
    if cls.get("is_sex_hormone"):
        hits.append(("H", 31, "Androgenic anabolic, oestrogenic & progestational substances"))
    return hits


def build_ingredient_table(products: pd.DataFrame) -> pd.DataFrame:
    refs = references()
    cls = ingredient_classes(products)
    out = []
    for r in cls.to_dict("records"):
        hits = schedule_hits(r["ingredient"], r)
        ctrl = refs["controlled"].get(r["base"])
        if ctrl:
            hits.append(("NDPS", 0, f"{ctrl[0]}: {ctrl[1]}"))
        top = ("X" if any(h[0] == "X" for h in hits) else "NDPS" if ctrl else
               "H1" if any(h[0] == "H1" for h in hits) else "H" if hits else None)
        r.update({
            "schedule": top,
            "schedule_refs": "; ".join(sorted({f"{h[0]}#{h[1]} {h[2]}" if h[1] else f"{h[0]} {h[2]}" for h in hits})),
            "controlled_category": ctrl[0] if ctrl else None,
        })
        out.append(r)
    return pd.DataFrame(out)


# ---------------------------------------------------------------- OTC rules


_MG_TO_IU = {"vitamin d3": 40000.0, "cholecalciferol": 40000.0, "vitamin d": 40000.0, "vitamin d2": 40000.0,
             "vitamin a": 1 / 0.0003, "vitamin a acetate": 1 / 0.000344, "vitamin a palmitate": 1 / 0.00055}


def _within_cap(rule: OtcRule, strength, ingredient: str = "") -> bool:
    if rule.cap_value is None:
        return True
    if strength is None:
        return False
    unit = strength.unit
    if rule.cap_unit == "iu" and unit == "mg" and ingredient in _MG_TO_IU:  # "Vitamin D3 (0.00625mg)" = 250 IU
        return strength.value * _MG_TO_IU[ingredient] <= rule.cap_value + 1e-6
    if rule.cap_unit == "mg" and unit == "mg":
        return strength.value <= rule.cap_value + 1e-9
    if rule.cap_unit == "%" and unit.startswith("pct"):
        return strength.value <= rule.cap_value + 1e-9
    if rule.cap_unit == "iu" and unit.startswith("iu"):
        return strength.value <= rule.cap_value + 1e-9
    return False  # incompatible units -> cannot prove it is within the OTC cap


def otc_rule_for(ingredient: str) -> OtcRule | None:
    refs = references()
    if ingredient in refs["otc"]:
        return refs["otc"][ingredient]
    b = base(ingredient)
    if b in refs["otc"]:
        return refs["otc"][b]
    for rx, rule in refs["nutra"]:
        if rx.search(ingredient) or rx.search(b):
            return rule
    return None


# ---------------------------------------------------------------- product evaluation

COUGH_COLD = {"dextromethorphan", "chlorpheniramine", "chlorphenamine", "phenylephrine", "guaifenesin", "guaiphenesin",
              "ambroxol", "bromhexine", "terbutaline", "levosalbutamol", "salbutamol", "codeine", "pholcodine",
              "diphenhydramine", "triprolidine", "noscapine", "levocloperastine", "ammonium chloride", "sodium citrate",
              "pseudoephedrine", "cetirizine", "levocetirizine", "promethazine", "dextromethorphan hydrobromide",
              "chlorpheniramine maleate", "menthol", "acebrophylline", "doxofylline", "theophylline", "montelukast",
              "carbocisteine", "acetylcysteine", "glycodin", "vasaka"}


@dataclass
class Verdict:
    category: str = "otc"
    reasons: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)

    def raise_to(self, category: str, reason: str, ref: str | None = None):
        if SEVERITY[category] > SEVERITY[self.category]:
            self.category = category
        self.reasons.append(reason)
        if ref:
            self.refs.append(ref)

    @property
    def requires_prescription(self) -> bool:
        return SEVERITY[self.category] >= SEVERITY["prescription"]


_REL_Q = re.compile(r"\((SR|ER|XR|CR|MR|PR)\)|\b(SR|ER|XR|CR|MR|PR)\b|\b(sustained|extended|prolonged|controlled|"
                    r"modified)[- ]release\b", re.I)
_FORM_Q = [
    (re.compile(r"dispersible", re.I), "form", "tablet_dispersible"),
    (re.compile(r"syrup|suspension|oral liquid|liquid oral|drops|elixir|linctus|solution", re.I), "route", "oral_liquid"),
    (re.compile(r"injection|injectable|infusion|parenteral", re.I), "route", "injection"),
    (re.compile(r"cream|gel|ointment|lotion|topical", re.I), "route", "topical"),
    (re.compile(r"eye", re.I), "route", "eye"),
    (re.compile(r"tablets?|capsules?", re.I), "route", "oral_solid"),
]
_ENTRY_STRENGTH = re.compile(r"(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)\s*(mg|mcg|g|gm|%|iu)\b", re.I)
_REL_MAP = {"sustained": "SR", "extended": "ER", "prolonged": "PR", "controlled": "CR", "modified": "MR", "xr": "ER"}


def _strength_set(part: str) -> tuple[frozenset[float], str] | None:
    """'Glimepiride1mg/2mg/3mg' -> ({1,2,3}, 'mg'); 'Metformin 1000mg/1000mg' -> ({1000}, 'mg')."""
    vals, unit = set(), None
    for m in _ENTRY_STRENGTH.finditer(re.sub(r"(?<=\d)(mg|mcg|g|gm)\s*/\s*(?=\d)", "/", part, flags=re.I)):
        u = m[2].lower()
        mult = {"mcg": 0.001, "g": 1000.0, "gm": 1000.0}.get(u, 1.0)
        vals |= {round(float(x) * mult, 6) for x in m[1].replace(" ", "").split("/") if x}
        unit = "mg" if u in {"mg", "mcg", "g", "gm"} else ("pct" if u == "%" else u)
    return (frozenset(vals), unit) if vals else None


def _parse_entry(r: dict) -> dict | None:
    text = r["text"]
    if re.search(r"animal use|veterinary|combikit|\bkit\b|with any other|other than|except", text, re.I):
        return None  # descriptive / conditional entries are not machine-matched (see SAFETY_POLICY.md)
    text = re.sub(r"^fixed dose combinations? (of\s+)?", "", text, flags=re.I)
    qual = {"release": None, "form": r.get("form") or None, "route": None}
    if qual["form"] == "syrup":
        qual["form"], qual["route"] = None, "oral_liquid"
    m = _REL_Q.search(text)
    if m:
        word = (m[1] or m[2] or m[3]).lower()
        qual["release"] = _REL_MAP.get(word, word.upper())
    for rx, kind, val in _FORM_Q:
        if rx.search(text) and not qual[kind]:
            qual[kind] = val
            break
    parts = [p for p in re.split(r"\s*\+\s*", text) if p.strip()]
    ings = []
    for p in parts:
        name = _REL_Q.sub(" ", p)
        for rx, _, _ in _FORM_Q:
            name = rx.sub(" ", name)
        b = base(re.sub(r"\d+(?:\.\d+)?\s*(mg|mcg|g|gm|%|iu)?\s*(/\s*\d+(?:\.\d+)?\s*(mg|mcg|g|gm|%|iu|ml)?)*", " ", name, flags=re.I))
        if not b:
            return None
        ings.append((b, _strength_set(p)))
    if len({b for b, _ in ings}) < 2:
        return None
    if r.get("strengths"):  # 2023 entry 13: explicit strength alternatives per ingredient
        alts = [s.split("+") for s in r["strengths"].replace("/5ml", "").split(";")]
        ings = [(b, (frozenset(float(re.sub(r"[^\d.]", "", a[i])) for a in alts), "mg/5ml")) for i, (b, _) in enumerate(ings)]
    return {"ings": ings, "bases": frozenset(b for b, _ in ings), **qual, "notification": r["notification"],
            "dated": r["dated"], "status": r["status"], "text": r["text"], "list": r["list"]}


@lru_cache(maxsize=1)
def banned_entries() -> tuple[list[dict], list[dict]]:
    """(prohibited entries, court-relief entries). Relief = stayed/quashed/revoked/under examination."""
    b = references()["banned"]
    prohibited, relief = [], []
    for r in b[b["text"].str.contains(r"\+")].to_dict("records"):
        e = _parse_entry(r)
        if e:
            (prohibited if r["status"] == "prohibited" else relief).append(e)
    return prohibited, relief


@lru_cache(maxsize=1)
def _entry_index() -> tuple[dict, dict]:
    """Entries grouped by their exact ingredient set, so a product only checks entries that can match."""
    prohibited, relief = banned_entries()
    pi, ri = {}, {}
    for e in prohibited:
        pi.setdefault(e["bases"], []).append(e)
    for e in relief:
        ri.setdefault(e["bases"], []).append(e)
    return pi, ri


def _entry_matches(e: dict, comps, form: str, release: str, route: str) -> bool:
    by_base = {base(c.ingredient): c for c in comps}
    if set(by_base) != e["bases"] or len(by_base) != len(comps):
        return False
    if e["form"] and form != e["form"]:
        return False
    if e["route"] and route != e["route"]:
        return False
    if e["release"] and release != e["release"]:
        return False
    for b, strengths in e["ings"]:
        if not strengths:
            continue
        values, unit = strengths
        s = by_base[b].strength
        if s is None:
            return False
        if unit == "mg/5ml":
            if s.unit != "mg/ml" or round(s.value * 5, 4) not in {round(v, 4) for v in values}:
                return False
        elif unit == "mg":
            if s.unit != "mg" or round(s.value, 4) not in {round(v, 4) for v in values}:
                return False
        else:
            return False  # strength stated in units we can't compare -> no ban claim
    return True


def banned_match(comps, form: str, release: str, route: str) -> str | None:
    """Notification text if this product matches an IN-FORCE prohibition, else None."""
    refs = references()
    ing_tokens = [tokens(c.ingredient) for c in comps]
    ing_bases = [base(c.ingredient) for c in comps]
    for r in refs["banned_single"]:
        rb = base(r["ingredient"])
        if not any(rb == b or set(rb.split()) <= t for b, t in zip(ing_bases, ing_tokens)):
            continue
        if r["routes"] and route not in r["routes"].split(";"):
            continue
        if r["rule"] == "with_any_other" and len(comps) < 2:
            continue
        return f"CDSCO prohibited list #{r['list_serial']} ({r['ingredient']})"
    pi, ri = _entry_index()
    key = frozenset(ing_bases)
    relief = ri.get(key, [])
    for e in pi.get(key, []):
        if _entry_matches(e, comps, form, release, route):
            # a court stay / quashing for this exact strength combination overrides a general entry
            if any(_entry_matches(x, comps, form, release, route) and any(s for _, s in x["ings"]) for x in relief):
                return None
            return f"{e['notification']} ({e['dated']})" if e["dated"] else e["notification"]
    return None


_TOPICAL_NAME = re.compile(r"\b(skin|scalp|hair|topical|external|antiseptic|mouth ?wash|gargle|lotion|liniment|"
                           r"spray|dusting|wound|body|face|foot)\b", re.I)
_ORAL_NAME = re.compile(r"\b(oral|drink|sachet|syrup|ors|rehydration|suspension|drops?)\b", re.I)


def route_of(form: str, comps, name: str = "") -> str:
    """Route of administration. Ambiguous forms ("Betadine Solution", "Mintop 2% Solution") are
    topical when the name says so, or when no ingredient is ever taken by mouth per the allowlist."""
    route = ROUTE_OF_FORM.get(form, "other")
    if form == "kit":  # combo packs (e.g. ORS kits): oral if every ingredient is an oral OTC ingredient
        rules = [otc_rule_for(c.ingredient) for c in comps]
        if rules and all(r is not None and r.routes & {"oral_solid", "oral_liquid"} for r in rules):
            return "oral_liquid" if all("oral_liquid" in r.routes for r in rules) else "oral_solid"
        return route
    if form == "gel":  # "Digene Acidity & Gas Relief Gel": a gel of oral-only ingredients is an oral liquid
        rules = [otc_rule_for(c.ingredient) for c in comps]
        if rules and all(r is not None and "oral_liquid" in r.routes and "topical" not in r.routes for r in rules):
            return "oral_liquid"
    if form not in AMBIGUOUS_FORMS or _ORAL_NAME.search(name or ""):
        return route
    if _TOPICAL_NAME.search(name or ""):
        return "topical"
    rules = [otc_rule_for(c.ingredient) for c in comps]
    if rules and all(r is not None and "topical" in r.routes and not (r.routes & {"oral_solid", "oral_liquid"})
                     for r in rules):
        return "topical"
    return route


def evaluate(comps, form: str, ing_table: dict, *, release: str = "IR", habit_forming: bool = False,
             therapeutic_class: str | None = None, name: str = "", rx_flags: list[bool] | None = None) -> Verdict:
    """The Prescription Guard decision for one product. Pure function of its composition and form."""
    v = Verdict()
    route = route_of(form, comps, name)
    if not comps:
        # No verified composition. Only if every independent source says OTC (e.g. Apollo files it under /otc/)
        # is it "otc_unverified" (recognised, not blocked, no ingredient claims); anything else -> prescription.
        if rx_flags and not any(rx_flags) and route not in {"injection"}:
            v.category = "otc_unverified"
            v.reasons.append("composition not verified; all sources list it as OTC")
        else:
            v.raise_to("prescription", "composition unknown")
        return v

    hit = banned_match(comps, form, release, route)
    if hit:
        v.raise_to("banned", "prohibited under Section 26A", hit)

    if route == "injection":
        v.raise_to("prescription", "injectable")
    if route == "other":
        v.raise_to("prescription", f"form '{form}' not classifiable")
    if habit_forming:
        v.raise_to("prescription", "habit forming (MID)")
    if route == "oral_liquid" and (
        any(base(c.ingredient) in COUGH_COLD or c.ingredient in COUGH_COLD for c in comps)
        or (therapeutic_class or "").upper().startswith("RESPIRAT")
    ):
        v.raise_to("prescription", "cough/cold oral liquid (Drugs (Fifth Amendment) Rules 2026)")

    for c in comps:
        info = ing_table.get(c.ingredient, {})
        sched = info.get("schedule")
        steroid = info.get("is_corticosteroid", False)
        antiinf = info.get("is_antibiotic", False) or info.get("is_antiinfective_other", False)
        refs = info.get("schedule_refs") or ""
        if sched in {"X", "NDPS"}:
            v.raise_to("controlled" if sched == "NDPS" else "schedule_x", f"{c.ingredient}: controlled substance", refs)
            continue
        if sched == "H1":
            v.raise_to("schedule_h1", f"{c.ingredient}: Schedule H1", refs)
            continue
        if sched == "H":
            exempt = (route in TOPICAL_EXEMPT_ROUTES and not steroid) or \
                     (route in EYE_EAR_NOSE and not steroid and not antiinf)
            if not exempt:
                v.raise_to("schedule_h", f"{c.ingredient}: Schedule H", refs)
            continue
        if steroid:
            v.raise_to("prescription", f"{c.ingredient}: corticosteroid")
            continue
        if antiinf and route in EYE_EAR_NOSE:
            v.raise_to("prescription", f"{c.ingredient}: anti-infective eye/ear/nose preparation")
            continue
        rule = otc_rule_for(c.ingredient)
        if rule and route in rule.routes and _within_cap(rule, c.strength, c.ingredient):
            continue
        if rule and route in rule.routes:
            v.raise_to("prescription", f"{c.ingredient}: above OTC strength")
        else:
            v.raise_to("prescription", f"{c.ingredient}: not on the OTC list for {route}")
    return v


# ---------------------------------------------------------------- build


def build() -> dict:
    products = pd.read_parquet(OUT / "products.parquet",
                               columns=["product_id", "name", "form", "release", "composition_raw", "ingredients", "n_components",
                                        "action_class", "chemical_class", "therapeutic_class", "habit_forming"])
    ing = build_ingredient_table(products)
    ing.to_parquet(OUT / "ingredient_safety.parquet", index=False)
    ing_table = ing.set_index("ingredient").to_dict("index")

    # Only sources whose Rx flag actually discriminates count as evidence. Base rates measured 2026-10-10:
    # master 99.8%, india_flags 98.8%, onemg_salt 98.6%, onemg_2025 100% "Rx" -> uninformative, ignored;
    # apollo 75% (real /otc/ vs /medicine/ split) and netmeds_rx 92% are used.
    flags = pd.read_parquet(OUT / "rx_flags.parquet")
    flags = flags[flags["source"].isin(DISCRIMINATIVE_FLAG_SOURCES)].groupby("product_id")["rx_required"].agg(list).to_dict()
    rows = []
    for p in products.itertuples():
        comps = parse_composition(p.composition_raw) if isinstance(p.composition_raw, str) else []
        v = evaluate(comps, p.form, ing_table, release=p.release, habit_forming=bool(p.habit_forming) if pd.notna(p.habit_forming) else False,
                     therapeutic_class=p.therapeutic_class if isinstance(p.therapeutic_class, str) else None,
                     name=p.name, rx_flags=flags.get(p.product_id))
        rows.append({"product_id": p.product_id, "category": v.category,
                     "requires_prescription": v.requires_prescription,
                     "reasons": " | ".join(dict.fromkeys(v.reasons)), "legal_refs": " | ".join(dict.fromkeys(v.refs))})
    ps = pd.DataFrame(rows)
    ps.to_parquet(OUT / "product_safety.parquet", index=False)

    untagged = int(ps["category"].isna().sum())
    report = {
        "ingredients": len(ing),
        "ingredient_schedule": ing["schedule"].fillna("none").value_counts().to_dict(),
        "products": len(ps),
        "untagged_products": untagged,
        "product_category": ps["category"].value_counts().to_dict(),
        "otc_products": int((ps["category"] == "otc").sum()),
        "banned_fdc_rules": len(banned_entries()[0]),
        "court_relief_rules": len(banned_entries()[1]),
    }
    (OUT / "safety_report.json").write_text(json.dumps(report, indent=2))
    if untagged:
        raise SystemExit(f"{untagged} products have no safety category")
    return report


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
