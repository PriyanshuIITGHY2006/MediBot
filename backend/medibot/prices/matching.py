"""Exact product matching for pharmacies that are reached through their sitemaps (PharmEasy, Truemeds).

One key function is applied to a sitemap slug, the product name a page shows, and our catalog name:

    "allmox-250mg-tab-33750"            -> ("allmox", "250"), "tablet"
    "Allmox 250Mg Strip Of 10 Tablets"  -> ("allmox", "250"), "tablet"
    "Allmox 250mg Tablet"               -> ("allmox", "250"), "tablet"

Nothing is fuzzy: the brand words and strengths must be identical after normalising spelling of forms
(tab = tablet), mg units (650mg = 650) and pack counts (strip of 10, 15's). Ambiguous keys are not used.
"""
from __future__ import annotations

import re

FORMS = {
    "tab": "tablet", "tabs": "tablet", "tablet": "tablet", "tablets": "tablet",
    "cap": "capsule", "caps": "capsule", "capsule": "capsule", "capsules": "capsule",
    "syp": "syrup", "syrup": "syrup", "susp": "suspension", "suspension": "suspension",
    "inj": "injection", "injection": "injection", "oint": "ointment", "ointment": "ointment",
    "crm": "cream", "cream": "cream", "gel": "gel", "drop": "drops", "drops": "drops",
    "sol": "solution", "soln": "solution", "solution": "solution", "lotion": "lotion", "spray": "spray",
    "pwd": "powder", "powder": "powder", "sachet": "sachet", "sachets": "sachet", "lozenge": "lozenge",
    "lozenges": "lozenge", "inhaler": "inhaler", "respules": "respules", "shampoo": "shampoo", "soap": "soap",
    "mouthwash": "mouthwash", "liquid": "liquid",
}
PACK_HEADS = ("strip", "pack", "bottle", "box", "packet", "tube", "ampoule", "ampule", "vial", "jar", "sachet")
PACK_WORDS = {"strip", "of", "bottle", "box", "pack", "packet", "tube", "jar", "vial", "piece", "pieces", "units",
              "unit", "s", "in"}
MASS = re.compile(r"^(\d+(?:\.\d+)?)mg$")
ID_TAIL = {"pharmeasy": re.compile(r"-\d+$"), "truemeds": re.compile(r"-tm(-[a-z0-9]+){1,3}$")}   # tm-tacr1-000062 / tm-1-dec-000007


def slug_text(platform: str, url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    rx = ID_TAIL.get(platform)
    return rx.sub("", slug) if rx else slug


def match_key(name: str) -> tuple[tuple[str, ...], str | None]:
    t = re.sub(r"[-_/]+", " ", str(name).lower().replace("'", ""))      # slugs: "75-mg" == "75 mg"
    t = re.sub(r"\bmouth wash\b", "mouthwash", t)
    t = re.sub(r"\boral liquid\b", "liquid", t)
    t = re.sub(r"(\d)\s+(mg|mcg|ml|gm|g|iu|%)\b", r"\1\2", t)          # "250 mg" -> "250mg"
    words = [w for w in re.split(r"[^a-z0-9.%]+", t) if w and w != "."]
    core: list[str] = []
    form = None
    i = 0
    while i < len(words):
        w = words[i]
        if w in FORMS:
            form = form or FORMS[w]
            i += 1
            continue
        if w in PACK_HEADS and i + 1 < len(words) and words[i + 1] == "of":
            # "strip of 10", "bottle of 100 ml": the pack, not the product
            j = i + 1
            while j < len(words) and (words[j] in PACK_WORDS or re.fullmatch(r"\d+(\.\d+)?(ml|gm|g)?", words[j])):
                j += 1
            i = j
            continue
        if re.fullmatch(r"\d+s", w) or (w.isdigit() and i + 1 < len(words) and words[i + 1] == "s"):
            i += 2 if w.isdigit() else 1                                 # "10's" / "10 s" pack count
            continue
        if w in PACK_WORDS:
            i += 1
            continue
        if re.fullmatch(r"\d+(\.\d+)?(ml|gm|g|kg|l)", w):
            i += 1                                                       # "60ml", "200gm": pack size, priced per unit
            continue
        m = MASS.match(w)
        core.append(m.group(1) if m else w)
        i += 1
    # a bare number right after the form word at the very end is a pack count ("dolo 650 tablet 15")
    if form and len(core) >= 2 and core[-1].isdigit() and words and words[-1] == core[-1]:
        last_form = max((k for k, w in enumerate(words) if w in FORMS), default=-1)
        if last_form == len(words) - 2:
            core = core[:-1]
    return tuple(core), form


def same_product(a: str, b: str) -> bool:
    ka, fa = match_key(a)
    kb, fb = match_key(b)
    return bool(ka) and ka == kb and (fa is None or fb is None or fa == fb)
