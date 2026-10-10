"""Interaction checker (Phase 10.4): pairs and a whole "medicine cabinet".

Ingredient pairs come from DDInter (208k graded pairs); where the US label of one ingredient names the other in
its interaction section, that sentence is quoted with its citation. Same ingredient in two products is flagged
as a double dose risk. Severity texts are fixed - nothing here tells the user to start, stop or change a dose.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations

from medibot.health.answer import safe_sentences
from medibot.health.evidence import query

DDINTER = ("DDInter drug–drug interaction database", "https://ddinter.scbdd.com/")
SEVERITY_ORDER = {"Major": 0, "Moderate": 1, "Minor": 2, "Unknown": 3}
SEVERITY_TEXT = {
    "Major": "Major interaction — these are usually not used together, or only under close medical supervision.",
    "Moderate": "Moderate interaction — the combination may need monitoring or a change by your doctor.",
    "Minor": "Minor interaction — usually of limited clinical importance.",
    "Unknown": "An interaction is recorded, but its severity is not graded.",
}
ADVICE = "Please ask your doctor or pharmacist before taking these together."
US_NAMES = {"paracetamol": "acetaminophen", "salbutamol": "albuterol", "glibenclamide": "glyburide",
            "adrenaline": "epinephrine", "rifampicin": "rifampin", "ciclosporin": "cyclosporine",
            "mesalazine": "mesalamine", "levosalbutamol": "levalbuterol"}


@dataclass
class Item:
    """One medicine in the check: a product or a generic ingredient name."""
    label: str
    ingredients: tuple[str, ...]


@dataclass
class Finding:
    kind: str                       # interaction | duplicate
    a: str                          # medicine labels
    b: str
    ingredient_a: str
    ingredient_b: str
    severity: str                   # Major | Moderate | Minor | Unknown | duplicate
    text: str
    citations: list[tuple[str, str]] = field(default_factory=list)

    def as_contract(self) -> dict:
        return {"kind": self.kind, "medicine_a": self.a, "medicine_b": self.b, "ingredient_a": self.ingredient_a,
                "ingredient_b": self.ingredient_b, "severity": self.severity, "text": self.text,
                "citations": [{"title": t, "url": u} for t, u in self.citations]}


def _ids(names: set[str]) -> dict[str, int]:
    rows = query("SELECT name, base, ingredient_id FROM ingredients WHERE name = ANY(%s) OR base = ANY(%s)",
                 (list(names), list(names)))
    out: dict[str, int] = {}
    for name, base, iid in rows:
        for n in (name, base):
            if n in names:
                out.setdefault(n, iid)
    return out


def _label_sentence(ingredient: str, other: str) -> tuple[str, str] | None:
    """A sentence from ingredient's US label interaction section that names the other ingredient."""
    names = [other] + ([US_NAMES[other]] if other in US_NAMES else [])
    pat = "|".join(re.escape(n) for n in names)
    rows = query("""SELECT text, title, url FROM evidence_chunks WHERE scope = 'ingredient' AND ref_id = %s
                    AND source = 'openfda' AND section IN ('interactions', 'warnings') AND text ~* %s LIMIT 3""",
                 (ingredient, rf"\m({pat})"))
    for text, title, url in rows:
        for s in re.split(r"(?<=[.!?])\s+", text):
            if re.search(rf"\b({pat})", s, re.I):
                safe = safe_sentences(s, max_sents=1, max_chars=300)
                if safe:
                    return f'US label for {ingredient}: "{safe}"', url
    return None


def check(items: list[Item]) -> list[Finding]:
    findings: list[Finding] = []
    for x, y in combinations(items, 2):
        for ing in sorted(set(x.ingredients) & set(y.ingredients)):
            findings.append(Finding("duplicate", x.label, y.label, ing, ing, "duplicate",
                                    f"Both {x.label} and {y.label} contain {ing}. Taking both means taking more {ing} "
                                    "than either one alone, which can be harmful.", []))
    names = {i for it in items for i in it.ingredients}
    ids = _ids(names)
    if len(ids) < 2:
        return findings
    rows = query("""SELECT ingredient_a, ingredient_b, severity FROM interactions
                    WHERE ingredient_a = ANY(%s) AND ingredient_b = ANY(%s)""", (list(ids.values()), list(ids.values())))
    graded = {}
    for a, b, sev in rows:
        k = (min(a, b), max(a, b))
        if k not in graded or SEVERITY_ORDER[sev] < SEVERITY_ORDER[graded[k]]:
            graded[k] = sev
    for x, y in combinations(items, 2):
        for ia in x.ingredients:
            for ib in y.ingredients:
                if ia == ib or ia not in ids or ib not in ids:
                    continue
                sev = graded.get((min(ids[ia], ids[ib]), max(ids[ia], ids[ib])))
                if not sev:
                    continue
                cites = [DDINTER]
                text = f"{ia} ({x.label}) + {ib} ({y.label}): {SEVERITY_TEXT[sev]}"
                quote = _label_sentence(ia, ib) or _label_sentence(ib, ia)
                if quote:
                    text += " " + quote[0]
                    cites.append(("US FDA label (DailyMed)", quote[1]))
                findings.append(Finding("interaction", x.label, y.label, ia, ib, sev, text, cites))
    findings.sort(key=lambda f: (f.kind != "duplicate", SEVERITY_ORDER.get(f.severity, 9)))
    return findings


def known_partners(ingredient: str, limit: int = 8) -> list[tuple[str, str]]:
    """'Which medicines interact with warfarin?' -> the most common catalog ingredients with a graded interaction."""
    ids = _ids({ingredient})
    if not ids:
        return []
    iid = ids[ingredient]
    rows = query("""SELECT i.name, x.severity FROM interactions x
                    JOIN ingredients i ON i.ingredient_id = CASE WHEN x.ingredient_a = %s THEN x.ingredient_b
                                                                 ELSE x.ingredient_a END
                    WHERE (x.ingredient_a = %s OR x.ingredient_b = %s) AND x.severity IN ('Major', 'Moderate')
                    ORDER BY CASE x.severity WHEN 'Major' THEN 0 ELSE 1 END, i.n_products DESC LIMIT %s""",
                 (iid, iid, iid, limit))
    seen, out = set(), []
    for name, sev in rows:
        if name not in seen:
            seen.add(name)
            out.append((name, sev))
    return out


def render(items: list[Item], findings: list[Finding]) -> tuple[str, list[tuple[str, str]]]:
    """Reply text + its numbered citations ([1] DDInter, then any US label quoted)."""
    labels = " + ".join(i.label for i in items)
    cites: list[tuple[str, str]] = [DDINTER]

    def num(c: tuple[str, str]) -> int:
        if c not in cites:
            cites.append(c)
        return cites.index(c) + 1
    if not findings:
        return (f"No interaction between {labels} is listed in DDInter (208,000+ graded pairs) [1]. "
                "That does not prove the combination is safe for you — " + ADVICE), cites
    lines = [f"Interaction check for {labels}:"]
    for f in findings:
        mark = {"duplicate": "⚠ Same ingredient", "Major": "⛔ Major", "Moderate": "⚠ Moderate",
                "Minor": "• Minor", "Unknown": "• Recorded"}[f.severity]
        refs = "".join(f" [{num(c)}]" for c in f.citations)
        lines.append(f"{mark}: {f.text}{refs}")
    lines.append(ADVICE)
    return "\n".join(lines), cites
