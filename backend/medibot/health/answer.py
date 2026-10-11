"""Grounded, cited health answers (Phase 10.3).

Extractive by design: every sentence shown comes from a retrieved passage and carries its citation number.
Sentences with doses or quantities are dropped (MediBot never gives doses), and so is anything the output
check would flag. If no passage clears the bar, the answer says so instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from medibot.health.evidence import (Passage, SECTION_SOURCES, available, medicine_passages, product_passages,
                                     question_sections,
                                     set_key, topic_by_id, topic_passages)
from medibot.safety.output_check import violations

MIN_SIM = 0.55          # a passage below this similarity (with no section match) is not used
TOPIC_MIN_SIM = 0.72    # curated FAQ must match the question closely
DEFAULT_SECTIONS = ["uses", "side_effects"]
HEADINGS = {
    "uses": "Uses", "how_it_works": "How it works", "side_effects": "Side effects", "how_to_use": "How it is used",
    "warnings": "Warnings", "interactions": "Interactions", "pregnancy": "Pregnancy", "breastfeeding": "Breastfeeding",
    "alcohol": "Alcohol", "driving": "Driving", "kidney": "Kidney", "liver": "Liver", "children": "Children",
    "elderly": "Older people", "storage": "Storage", "habit_forming": "Habit forming", "composition": "Composition",
}
DOSE = re.compile(
    r"\b\d+(\.\d+)?\s*(mg|mcg|µg|g|gm|grams?|ml|mL|iu|units?|tablets?|tabs?|capsules?|caps?|doses?|times|hours?|hrs?|"
    r"puffs?|drops?|sachets?|spoons?|teaspoons?|kg)\b"
    r"|\b(one|two|three|four|five|six|eight|ten|twelve)\s+(doses?|tablets?|capsules?|times|hours|puffs|drops)\b"
    r"|\b(maximum|max|daily|recommended|usual|starting|initial|single) (daily )?(dose|dosage)\b|\bdosage\b"
    r"|\bdose (of|is|should|may)\b|mg/kg|\bevery \d", re.I)
NOISE = re.compile(r"\[see .*?\]|\(\s*\d+(\.\d+)*\s*\)|\(see .*?\)", re.I)


@dataclass
class Citation:
    n: int
    title: str
    url: str
    note: str | None = None          # "written for Crocin Advance Tablet (same ingredients)"

    def as_contract(self) -> dict:
        return {"n": self.n, "title": self.title, "url": self.url, "note": self.note}


@dataclass
class HealthAnswer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)   # asked, but no reliable passage
    grounded: bool = False

    def as_contract(self) -> dict:
        return {"sections": self.sections, "missing": self.missing, "grounded": self.grounded,
                "citations": [c.as_contract() for c in self.citations]}


INJECTABLE = re.compile(r"\s*(injection|infusion|application|administration|puncture|catheter) site [a-z ]+?"
                        r"\([^)]*\),?|\s*(injection|infusion|application) site [a-z ]+,", re.I)
INJECTABLE_SENT = re.compile(r"\b(intravenous|IV (acetaminophen|use|infusion|administration)|infusion|injection site|"
                             r"for injection)\b", re.I)
LABEL_HEAD = re.compile(r"^\s*(uses?|purpose|warnings?|directions|indications( and usage)?|other information)\b[:\s]*",
                        re.I)


def clean_label(text: str) -> str:
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff\xa0]", " ", text)
    text = re.sub(r"^\s*\d+(\.\d+)*\s+([A-Z][a-z]+\s){1,4}(?=[A-Z])", "", text)   # "8.1 Pregnancy Risk Summary Published ..."
    text = re.sub(r"^\s*(Data\s+)?(Human|Animal|Clinical) Data\s+", "", text)
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    return re.sub(r"\s+", " ", LABEL_HEAD.sub("", text)).strip()


def safe_sentences(text: str, max_sents: int = 3, max_chars: int = 420) -> str | None:
    text = re.sub(r"\s+([.,;:])", r"\1", NOISE.sub("", clean_label(text)))
    out, n = [], 0
    for s in re.split(r"(?<=[.!?])\s+", text):
        s = s.strip()
        s = re.sub(r"^(Data\s+)?(Human|Animal|Clinical|Pregnancy|Lactation) Data\s+", "", s)  # label sub-headings
        if not s or s[0].islower() or DOSE.search(s) or violations(s) or len(s) < 12:  # lowercase = mid-sentence cut
            continue
        if n + len(s) > max_chars and out:
            break
        out.append(s)
        n += len(s)
        if len(out) >= max_sents:
            break
    return " ".join(out) or None


class _Cites:
    def __init__(self):
        self.items: list[Citation] = []

    def add(self, title: str, url: str, note: str | None = None) -> int:
        for c in self.items:
            if c.title == title and c.url == url and c.note == note:
                return c.n
        self.items.append(Citation(len(self.items) + 1, title, url, note))
        return len(self.items)


def _prefix(p: Passage, key: str, multi: bool) -> str:
    if p.source == "openfda":
        return f"US label for {p.ref_id}: "
    if p.scope == "composition" and p.ref_id != key and multi:
        return f"About {p.ref_id} (one of its ingredients): "
    return ""


def _note(p: Passage, key: str) -> str | None:
    w = (p.meta or {}).get("written_for")
    if p.scope == "product" and w:
        return f"for {w} (this product)"
    if p.scope == "composition" and w:
        return f"written for {w} ({'same ingredients' if p.ref_id == key else 'single-ingredient medicine'})"
    return None


def answer_medicine(name: str, composition: str | None, ingredients: tuple[str, ...], question: str, *,
                    habit_forming: bool | None = None, max_sections: int = 3,
                    sections_override: list[str] | None = None, product_id: str | None = None,
                    form: str | None = None) -> HealthAnswer:
    asked = sections_override if sections_override is not None else question_sections(question)
    sections = [s for s in asked if s != "composition"][:max_sections] or ([] if "composition" in asked else
                                                                           DEFAULT_SECTIONS)
    # "is it safe in pregnancy" -> pregnancy, not generic warnings; the warnings are only a fallback when nothing
    # more specific is on record ("is Dettol safe to apply on skin" -> no how-to-use passage, but label warnings)
    warnings_fallback = "warnings" in sections and len(sections) > 1
    if warnings_fallback:
        sections.remove("warnings")
    cites, lines, used, missing = _Cites(), [], set(), []
    key, multi = set_key(ingredients), len(set(ingredients)) > 1

    if "composition" in asked and composition:
        n = cites.add("MediBot catalog (composition agreed across pharmacy datasets)",
                      "https://cdsco.gov.in/opencms/opencms/en/Home/")
        lines.append(f"Composition: {composition} [{n}]")
    if not ingredients:
        return HealthAnswer("\n".join(lines) or f"I don't have verified information about {name}.",
                            cites.items, ["composition"] if lines else [], sections, bool(lines))
    if not available():
        missing = sections
        return HealthAnswer("\n".join(lines + ["I can't reach the medicine-information index right now, so I won't "
                                               "guess. Please check the leaflet or ask your pharmacist."]),
                            cites.items, [], missing, bool(lines))

    wanted = (sections or DEFAULT_SECTIONS) + (["warnings"] if warnings_fallback else [])
    own = product_passages(product_id) if product_id else []
    # the product's own monograph replaces the ingredient-set representative for the sections it covers
    own_secs = {p.section for p in own}
    cands = own + [p for p in medicine_passages(ingredients, question, wanted)
                   if not (p.scope == "composition" and p.source in ("mid", "mohneesh", "k11") and p.section in own_secs)]
    oral = form is not None and "injection" not in form and "infusion" not in form
    if "habit_forming" in sections and habit_forming is not None:
        n = cites.add("Medicine monograph (MID dataset, 1mg-style information)",
                      "https://data.mendeley.com/datasets/2vk5khfn6v/2")
        lines.append(f"Habit forming: {'yes — medicine monographs list it as habit forming' if habit_forming else 'no — medicine monographs do not list it as habit forming'} [{n}]")
        used.add("habit_forming_flag")

    def fill(sec: str) -> bool:
        allowed = SECTION_SOURCES.get(sec, [sec])
        picks = [p for p in cands if p.section in allowed and p.id not in used and p.sim >= MIN_SIM - 0.1]
        # the section's own passages first ("Uses: Pain relief; Treatment of Fever"), the overview only as backup
        picks.sort(key=lambda p: (allowed.index(p.section), p.source == "openfda"))   # monograph / SIDER before US label text
        # side effects: the medicine's own list first, then label frequencies
        per_section = 2 if sec in ("side_effects", "pregnancy", "warnings") else 1
        # side effects: the product's own monograph list is enough; SIDER (pooled over every form of the drug, e.g.
        # newborn IV ibuprofen) is only a fallback when there is no monograph list
        if sec == "side_effects" and any(p.source in ("mid", "mohneesh", "k11") for p in picks):
            picks = [p for p in picks if p.source != "sider"]
        got = []
        for p in picks:
            text = p.text
            if oral and p.source in ("openfda", "sider"):  # US labels / SIDER mix in the IV form of the ingredient
                text = INJECTABLE.sub("", text) if p.source == "sider" else \
                    " ".join(s for s in re.split(r"(?<=[.!?])\s+", text) if not INJECTABLE_SENT.search(s))
            body = text if (p.section == "side_effects" and p.source in ("mid", "sider", "mohneesh", "k11")) \
                else safe_sentences(text, max_sents=3 if p.source != "openfda" else 2)
            if not body or violations(body):
                continue
            if p.source == "sider" and len(body) > 360:
                body = body[:360].rsplit(",", 1)[0] + " …"
            n = cites.add(p.title, p.url, _note(p, key))
            got.append(f"{_prefix(p, key, multi)}{body} [{n}]")
            used.add(p.id)
            if len(got) >= per_section:
                break
        if got:
            lines.append(f"{HEADINGS.get(sec, sec.title())}: " + " ".join(got) if len(got) == 1 else
                         f"{HEADINGS.get(sec, sec.title())}:\n" + "\n".join("• " + g for g in got))
        return bool(got)

    for sec in sections:
        if not fill(sec) and not (sec == "habit_forming" and "habit_forming_flag" in used):
            missing.append(sec)
    if warnings_fallback and missing and set(missing) == set(sections) and fill("warnings"):
        sections.append("warnings")
    if missing:
        lines.append("I don't have reliable information on " + ", ".join(HEADINGS.get(m, m).lower() for m in missing)
                     + " for this medicine — please check the leaflet or ask your pharmacist.")
    grounded = bool(cites.items) and len(missing) < max(1, len(sections))
    return HealthAnswer("\n".join(lines), cites.items, sections, missing, grounded)


def answer_topic(question: str) -> HealthAnswer | None:
    """General questions without a medicine (Jan Aushadhi, generics, storage, ORS ...): curated, cited FAQ only."""
    if not available():
        return None
    hits = topic_passages(question, k=2)
    if not hits or hits[0].sim < TOPIC_MIN_SIM:
        return None
    return _topic_answer(hits[0])


def answer_topic_id(ref: str) -> HealthAnswer | None:
    """A curated topic picked by a deterministic detector (e.g. "I missed a dose"), not by similarity."""
    p = topic_by_id(ref) if available() else None
    return _topic_answer(p) if p else None


def _topic_answer(p: Passage) -> HealthAnswer:
    cites = _Cites()
    n = cites.add(p.title, p.url)
    return HealthAnswer(f"{p.meta.get('question', '')}\n{p.text} [{n}]", cites.items, ["faq"], [], True)


def render_sources(ans: HealthAnswer) -> str:
    if not ans.citations:
        return ""
    return "Sources: " + " · ".join(f"[{c.n}] {c.title}" + (f" — {c.note}" if c.note else "") for c in ans.citations)
