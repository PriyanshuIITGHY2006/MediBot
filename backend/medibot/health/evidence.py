"""Filtered hybrid retrieval over medibot.evidence_chunks (Phase 10.2).

Filter first (only passages about THIS medicine's ingredient set / its ingredients / curated topics), then rank by
  cosine similarity (bge-small, local) + section match from the question + lexical overlap (Postgres full text)
  + a small source prior (a monograph for the exact ingredient set beats a single-ingredient US label).
Nothing is generated here: callers get passages with their citation.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODEL = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# question words -> sections (EN + Hinglish). Order = priority; the first match is the primary section.
SECTION_RULES: list[tuple[str, str]] = [
    ("pregnancy", r"pregnan|garbh|expecting a baby|trying to conceive|conceiv"),
    ("breastfeeding", r"breast ?feed|lactat|nursing mother|feeding (mother|my baby)|doodh pila"),
    ("alcohol", r"alcohol|\bbeer\b|\bwine\b|\bdrinks?\b|drinking|sharab|shara?ab|daa?ru|\bpeg\b|whisky"),
    ("driving", r"\bdriv(e|ing)\b|operate machin|bike chala|gaadi chala"),
    ("habit_forming", r"habit|addict|aadat|dependen|withdrawal"),
    ("kidney", r"kidney|renal|gurd"),
    ("liver", r"\bliver\b|hepat|jigar"),
    ("children", r"\bchild|\bkids?\b|\bbaby\b|infant|bacch|\d+\s*(year|yr|month)s?[\s-]*old|toddler|p(a)?ediatric"),
    ("elderly", r"elderly|old age|senior citizen|grand(mother|father|parent)|bujurg|\bold (people|person)"),
    ("storage", r"\bstore\b|storage|fridge|refrigerat|shelf life|expir|room temperature|keep it"),
    ("how_to_use", r"how to (take|use|apply)|empty stomach|with food|before food|after food|before meal|after meal|"
                   r"khane se pehle|khane ke baad|khali pet|crush|chew|\bbreak\b|split|swallow|\bapply\b|lagana|"
                   r"with milk|with water"),
    ("side_effects", r"side ?-?effects?|nuksan|nuksaan|reaction|adverse|\bcause[sd]?\b|make (me|you)|hair ?(loss|fall)|"
                     r"weight (gain|loss)|drows|sleepy|neend|dizz|nause|vomit|ulti|constipat|headache from|rash"),
    ("how_it_works", r"how (does|do|will) .*work|mechanism|kaise kaam|what does it do|how it works"),
    ("uses", r"used for|use of|\buses?\b|kis (kaam|liye|cheez)|what (is|are) .* for\b|\btreat|purpose|benefit|"
             r"indicat|what is\b|kya hai|tell me about|information|details|good for"),
    ("interactions", r"interact|together|along with|saath|combine|mix"),
    ("warnings", r"\bsafe\b|safety|danger|risk|warning|precaution|avoid|who should not|contraindicat|allerg|"
                 r"harmful|problem"),
    ("composition", r"contain|ingredient|composition|\bsalt\b|generic name|made of|sugar|lactose|gluten"),
]
# which stored sections can answer a question section
SECTION_SOURCES = {
    "uses": ["uses", "overview"], "how_it_works": ["how_it_works", "overview"],
    "side_effects": ["side_effects"], "how_to_use": ["how_to_use", "tips"],
    "warnings": ["warnings", "contraindications", "tips", "overview"], "interactions": ["interactions", "tips"],
    "pregnancy": ["pregnancy"], "breastfeeding": ["breastfeeding", "pregnancy"], "alcohol": ["alcohol"],
    "driving": ["driving"], "kidney": ["kidney"], "liver": ["liver"], "children": ["children"],
    "elderly": ["elderly"], "storage": ["storage"], "habit_forming": ["habit_forming"],
}


def question_sections(text: str) -> list[str]:
    t = text.lower()
    return [name for name, rx in SECTION_RULES if re.search(rx, t)]


@dataclass
class Passage:
    id: int
    scope: str
    ref_id: str
    section: str
    text: str
    source: str
    title: str
    url: str
    meta: dict = field(default_factory=dict)
    score: float = 0.0
    sim: float = 0.0


# ---------------------------------------------------------------- infrastructure (lazy, optional)
_local = threading.local()


def database_url() -> str | None:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return None


def conn():
    """One connection per thread; None if the database is not reachable (callers then say 'no reliable info')."""
    c = getattr(_local, "conn", None)
    if c is not None and not c.closed:
        return c
    url = database_url()
    if not url:
        return None
    try:
        import psycopg
        c = psycopg.connect(url, autocommit=True, connect_timeout=3)
        c.execute("SET search_path = medibot, public")
    except Exception:
        return None
    _local.conn = c
    return c


def query(sql: str, params=()) -> list[tuple]:
    c = conn()
    if c is None:
        return []
    try:
        return c.execute(sql, params).fetchall()
    except Exception:
        _local.conn = None
        try:
            c.close()
        except Exception:
            pass
        return []


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding
    return TextEmbedding(MODEL, cache_dir=str(ROOT / "data/interim/models"))


@lru_cache(maxsize=4096)
def embed_query(text: str) -> str:
    v = next(iter(_model().embed([QUERY_PREFIX + text])))
    return "[" + ",".join(f"{x:.5f}" for x in v) + "]"


# ---------------------------------------------------------------- retrieval
_COLS = "id, scope, ref_id, section, text, source, title, url, meta"


def _rows(rows) -> list[Passage]:
    return [Passage(*r[:8], meta=r[8] or {}, sim=float(r[9]), score=float(r[10]) if len(r) > 10 else 0.0)
            for r in rows]


def set_key(ingredients) -> str:
    return " + ".join(sorted(set(ingredients)))


def medicine_passages(ingredients: tuple[str, ...], question: str, sections: list[str], k: int = 40) -> list[Passage]:
    """Candidate passages about one medicine: its exact ingredient-set monograph, else each single-ingredient
    monograph; plus US label / SIDER passages for each ingredient. Ranked by the hybrid score."""
    if not ingredients:
        return []
    key = set_key(ingredients)
    keys = [key] + ([i for i in ingredients] if len(set(ingredients)) > 1 else [])
    q = embed_query(question)
    rows = query(f"""
        SELECT {_COLS}, 1 - (embedding <=> %s::vector) AS sim,
               ts_rank_cd(tsv, websearch_to_tsquery('english', %s)) AS lex
        FROM evidence_chunks
        WHERE (scope = 'composition' AND ref_id = ANY(%s)) OR (scope = 'ingredient' AND ref_id = ANY(%s))""",
                 (q, question, keys, list(ingredients)))
    wanted = {s: i for i, s in enumerate(x for sec in sections for x in SECTION_SOURCES.get(sec, []))}
    primary = set(SECTION_SOURCES.get(sections[0], [])) if sections else set()
    out = []
    for r in rows:
        p = Passage(*r[:8], meta=r[8] or {}, sim=float(r[9]))
        lex = min(float(r[10]), 1.0)
        prior = 0.06 if (p.scope == "composition" and p.ref_id == key) else 0.0 if p.scope == "composition" else \
            -0.02 if p.source == "openfda" else 0.0
        sec = 0.25 if p.section in primary else 0.12 if p.section in wanted else 0.0
        p.score = p.sim + sec + 0.1 * lex + prior
        out.append(p)
    out.sort(key=lambda p: p.score, reverse=True)
    return out[:k]


def topic_passages(question: str, k: int = 3) -> list[Passage]:
    q = embed_query(question)
    rows = query(f"""SELECT {_COLS}, 1 - (embedding <=> %s::vector) AS sim FROM evidence_chunks
                     WHERE scope = 'topic' ORDER BY embedding <=> %s::vector LIMIT %s""", (q, q, k))
    return _rows(rows)


def topic_by_id(ref: str) -> Passage | None:
    rows = query(f"SELECT {_COLS}, 1.0 AS sim FROM evidence_chunks WHERE scope = 'topic' AND ref_id = %s LIMIT 1",
                 (ref,))
    return _rows(rows)[0] if rows else None


def available() -> bool:
    return bool(query("SELECT 1 FROM evidence_chunks LIMIT 1"))


OWN_TITLE = "Medicine monograph (MID dataset, 1mg-style information)"
OWN_URL = "https://data.mendeley.com/datasets/2vk5khfn6v/2"
_SAFETY_KEYS = ("alcohol", "pregnancy", "breastfeeding", "driving", "kidney", "liver")


def product_passages(product_id: str) -> list[Passage]:
    """The asked product's OWN monograph, section by section (brands with the same ingredients can carry different
    advice - Dolo 650's monograph and another paracetamol brand's disagree on pregnancy). Used before the
    ingredient-set representative; empty if the product has no monograph."""
    rows = query("""SELECT i.introduction, i.uses, i.side_effects, i.how_to_use, i.how_it_works, i.quick_tips,
                           i.safety_advice, p.name
                    FROM product_info i JOIN products p USING (product_id)
                    WHERE i.source = 'mid' AND (i.product_id = %s OR p.canonical_id = %s)
                    -- the asked listing first, then a fixed order: aliases of one product (PAN 40 / PAN 40mg) must
                    -- not swap from run to run, and a sibling listing (Alprax MT) is only a fallback
                    ORDER BY (i.product_id = %s) DESC, i.product_id LIMIT 1""",
                 (product_id, product_id, product_id))
    if not rows:
        return []
    intro, uses, se, how, works, tips, sa, name = rows[0]
    out: list[Passage] = []

    stem = re.sub(r"\s+(tablets?|capsules?|syrup|suspension|injection|cream|gel|ointment|drops?|solution|lotion|"
                  r"powder|sachet|spray|inhaler)\b.*$", "", name, flags=re.I).strip()
    names = [n for n in sorted({name, stem}, key=len, reverse=True) if len(n) >= 3]

    def neutral(t: str) -> str:  # "Dolo 650 Tablet may be unsafe" -> "This medicine may be unsafe" (no "650 Tablet")
        for n in names:
            t = re.sub(re.escape(n) + r"(\s+(tablets?|capsules?|syrup|suspension|gel|cream|drops?))?", "this medicine",
                       t, flags=re.I)
        return re.sub(r"(^|[.!?]\s+)this medicine", lambda m: m.group(1) + "This medicine", t)

    def add(section, text):
        if isinstance(text, str) and len(text.strip()) >= 25:
            out.append(Passage(-(len(out) + 1), "product", product_id, section, neutral(text.strip()), "mid", OWN_TITLE,
                               OWN_URL, {"written_for": name, "own": True}, score=9.0 - 0.01 * len(out), sim=1.0))
    for para in (intro or "").split("\n"):
        add("overview", para)
    if uses:
        add("uses", "Uses: " + "; ".join(u.strip() for u in re.split(r";|,", uses) if u.strip()) + ".")
    if se:
        add("side_effects", "Common side effects: " + ", ".join(x.strip() for x in re.split(r";|,", se) if x.strip())[:600] + ".")
    add("how_to_use", how)
    add("how_it_works", works)
    for tip in (tips or "").split("\n"):
        if tip.strip() and not tip.startswith("Interactions (source text)"):
            add("tips", tip.strip().rstrip(".") + ".")
    if isinstance(sa, str):
        import json
        try:
            sa = json.loads(sa)
        except ValueError:
            sa = None
    for k in _SAFETY_KEYS:
        v = (sa or {}).get(k)
        if v:
            add(k, re.sub(r"\.(?=[A-Z])", ". ", v))
    return out
