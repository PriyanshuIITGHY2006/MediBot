"""Evidence index for grounded health answers (Phase 10.1) -> medibot.evidence_chunks.

Every passage keeps its citation (title + url) and is embedded with BAAI/bge-small-en-v1.5 (384-d, local ONNX).

  scope 'composition'  medicine monographs (MID / 1mg-style text) per ingredient SET (strength-agnostic): one
                       representative monograph per set; the brand it was written for becomes "this medicine"
  scope 'ingredient'   US FDA label sections (openFDA, single-ingredient labels; dosing sections never kept)
                       and SIDER 4.1 side-effect frequencies
  scope 'topic'        curated general-health FAQ (data/reference/health_faq.jsonl), each with an official source

                       + verbatim official label sentences (data/reference/label_passages.jsonl, source 'label')

Usage: .venv/bin/python db/build_evidence.py      (needs data/interim/openfda_sections.parquet, see openfda.py)
       .venv/bin/python db/build_evidence.py --curated   (reload only the FAQ + label passages, seconds)
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "db"))
from load import database_url  # noqa: E402

MODEL = "BAAI/bge-small-en-v1.5"
MODEL_DIR = ROOT / "data/interim/models"
SOURCE_RANK = {"mid": 0, "mohneesh": 1, "k11": 2}
SAFETY_KEYS = {"alcohol", "pregnancy", "breastfeeding", "driving", "kidney", "liver"}
MID_TITLE = "Medicine monograph (MID dataset, 1mg-style information)"
MID_URL = "https://data.mendeley.com/datasets/2vk5khfn6v/2"
FREQ_RANK = {"very common": 0, "common": 1, "frequent": 1, "uncommon": 3, "infrequent": 3, "rare": 4,
             "very rare": 5, "postmarketing": 6}


def set_key(ingredients) -> str:
    return " + ".join(sorted(set(ingredients)))


def neutral(text: str, name: str) -> str:
    """Replace the brand the monograph was written for by 'this medicine' (the text applies to the whole set)."""
    if not isinstance(text, str) or not text.strip():
        return None
    stem = re.sub(r"\s+(tablet|capsule|syrup|suspension|injection|cream|gel|ointment|drops?|solution|lotion|"
                  r"powder|sachet|spray|inhaler|respules|kit)\b.*$", "", name, flags=re.I).strip()
    for n in sorted({name, stem}, key=len, reverse=True):
        if len(n) >= 3:
            text = re.sub(re.escape(n) + r"(?:\s+(?:tablets?|capsules?|syrup|suspension|injection|cream|gel|"
                          r"ointment|drops?|solution|lotion|powder|sachet|spray)\b)?", "this medicine", text, flags=re.I)
    text = re.sub(r"(^|[.!?]\s+)this medicine", lambda m: m.group(1) + "This medicine", text)
    return re.sub(r"\s+", " ", text).strip()


def sentences_chunks(text: str, limit: int = 600) -> list[str]:
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z(•])", text)
    out, cur = [], ""
    for s in sents:
        if cur and len(cur) + len(s) > limit:
            out.append(cur.strip())
            cur = ""
        cur += " " + s
    if cur.strip():
        out.append(cur.strip())
    return [c[:1200] for c in out]


# ---------------------------------------------------------------- monographs
def monograph_chunks(cur) -> list[dict]:
    pop = pd.read_parquet(ROOT / "data/processed/search_index.parquet", columns=["product_id", "popularity"]) \
        .groupby("product_id")["popularity"].max()
    cur.execute("""SELECT i.product_id, i.source, p.name, p.ingredients, i.introduction, i.uses, i.benefits,
                          i.side_effects, i.how_to_use, i.how_it_works, i.quick_tips, i.safety_advice
                   FROM product_info i JOIN products p USING (product_id)
                   WHERE p.ingredients IS NOT NULL AND cardinality(p.ingredients) > 0""")
    cols = [d.name for d in cur.description]
    df = pd.DataFrame(cur.fetchall(), columns=cols)
    df = df.astype(object).where(df.notna(), None)
    for c in ["introduction", "uses", "benefits", "side_effects", "how_to_use", "how_it_works", "quick_tips"]:
        df[c] = df[c].map(lambda v: v if isinstance(v, str) and v.strip() else None)
    df["key"] = df["ingredients"].map(set_key)
    df["rank"] = df["source"].map(SOURCE_RANK)
    df["filled"] = df[["introduction", "uses", "side_effects", "how_to_use", "how_it_works", "safety_advice"]] \
        .notna().sum(axis=1)
    df["pop"] = df["product_id"].map(pop).fillna(0)
    best = df.sort_values(["rank", "filled", "pop"], ascending=[True, False, False]).drop_duplicates("key")
    print(f"  monographs: {len(df):,} rows -> {len(best):,} ingredient sets", flush=True)

    out = []
    for r in best.itertuples(index=False):
        title = MID_TITLE if r.source == "mid" else f"Medicine information ({r.source} dataset, 1mg-style)"
        meta = {"written_for": r.name, "dataset": r.source}

        def add(section, text):
            t = neutral(text, r.name)
            if t and len(t) >= 25:
                out.append({"scope": "composition", "ref_id": r.key, "section": section, "text": t,
                            "source": r.source, "title": title, "url": MID_URL, "meta": meta})
        txt = lambda v: v if isinstance(v, str) else ""  # noqa: E731
        for para in txt(r.introduction).split("\n"):
            for c in sentences_chunks(para):
                add("overview", c)
        if txt(r.uses):
            add("uses", "Uses: " + "; ".join(u.strip() for u in re.split(r";|,", r.uses) if u.strip()) + ".")
        if txt(r.benefits):  # alternating "heading" / "paragraph" lines
            lines = [x.strip() for x in r.benefits.split("\n") if x.strip()]
            for i, x in enumerate(lines):
                if len(x) > 80:
                    head = lines[i - 1] if i and len(lines[i - 1]) <= 80 else None
                    add("uses", (f"{head}: " if head else "") + x)
        if txt(r.side_effects):
            se = [s.strip() for s in re.split(r";|,", r.side_effects) if s.strip()]
            add("side_effects", "Common side effects: " + ", ".join(se[:20]) + ".")
        if r.how_to_use:
            add("how_to_use", r.how_to_use)
        if r.how_it_works:
            add("how_it_works", r.how_it_works)
        for tip in txt(r.quick_tips).split("\n"):
            if tip.strip() and not tip.startswith("Interactions (source text)"):
                add("tips", tip.strip().rstrip(".") + ".")
        sa = r.safety_advice if isinstance(r.safety_advice, dict) else (json.loads(r.safety_advice) if r.safety_advice else {})
        for k, v in (sa or {}).items():
            if k in SAFETY_KEYS and v:
                add(k, re.sub(r"\.(?=[A-Z])", ". ", v))
    return out


# ---------------------------------------------------------------- ingredient level
def sider_chunks(cur) -> list[dict]:
    cur.execute("""SELECT i.name, s.side_effect, s.frequency FROM ingredient_side_effects s
                   JOIN ingredients i USING (ingredient_id)""")
    df = pd.DataFrame(cur.fetchall(), columns=["ingredient", "effect", "freq"])

    def rank(f):
        if not isinstance(f, str):
            return 7
        f = f.lower().strip()
        if f in FREQ_RANK:
            return FREQ_RANK[f]
        m = re.match(r"([\d.]+)\s*%", f)
        return 0 if m and float(m.group(1)) >= 10 else 2 if m and float(m.group(1)) >= 1 else 3 if m else 7

    df["r"] = df["freq"].map(rank)
    df = df.sort_values("r").drop_duplicates(["ingredient", "effect"])
    out = []
    for ing, g in df.groupby("ingredient"):
        g = g[g["r"] < 6].head(25)
        if len(g) < 3:
            continue
        items = [f"{e.lower()} ({f})" if isinstance(f, str) and f else e.lower() for e, f in zip(g["effect"], g["freq"])]
        out.append({"scope": "ingredient", "ref_id": ing, "section": "side_effects",
                    "text": f"Side effects of {ing} reported in drug labels, with frequency where known: "
                            + ", ".join(items) + ".",
                    "source": "sider", "title": "SIDER 4.1 side-effect resource (from drug labels)",
                    "url": "http://sideeffects.embl.de/", "meta": {"n_effects": len(g)}})
    return out


def openfda_chunks() -> list[dict]:
    p = ROOT / "data/interim/openfda_sections.parquet"
    if not p.exists():
        print("  openFDA sections missing (run data/pipeline/openfda.py) - skipped")
        return []
    df = pd.read_parquet(p)
    out = []
    for (ing, kind, field), g in df.groupby(["ingredient", "label_type", "field"], sort=False):
        r = g.iloc[0]
        chunks = [c for t in g["text"] for c in sentences_chunks(t)][:4]
        for c in chunks:
            out.append({"scope": "ingredient", "ref_id": ing, "section": r["section"], "text": c, "source": "openfda",
                        "title": f"US FDA {'prescribing' if kind == 'rx' else 'OTC'} label (DailyMed) — US labelling "
                                 "may differ from India",
                        "url": f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={r['set_id']}",
                        "meta": {"label_type": kind, "field": field, "effective_time": r["effective_time"]}})
    return out


def faq_chunks() -> list[dict]:
    out = []
    for line in (ROOT / "data/reference/health_faq.jsonl").read_text().splitlines():
        if line.strip():
            f = json.loads(line)
            out.append({"scope": "topic", "ref_id": f["id"], "section": "faq", "text": f["answer"],
                        "source": "curated", "title": f["source"], "url": f["url"],
                        "meta": {"question": f["title"], "questions": f["questions"]}})
    return out


def label_chunks() -> list[dict]:
    """Hand-copied official label sentences (data/reference/label_passages.jsonl) for medicines whose monograph
    lacks a section (e.g. the children's age limit for Strepsils). Verbatim text only, each with its label URL."""
    out = []
    for line in (ROOT / "data/reference/label_passages.jsonl").read_text().splitlines():
        if line.strip():
            f = json.loads(line)
            out.append({"scope": "composition", "ref_id": set_key(f["ingredients"]), "section": f["section"],
                        "text": f["text"], "source": "label", "title": f["title"], "url": f["url"],
                        "meta": {"written_for": f["written_for"], "dataset": "label"}})
    return out


CURATED_SOURCES = ("curated", "label")


def embed_text(c: dict) -> str:
    if c["scope"] == "topic":
        return f"{c['meta']['question']} {' | '.join(c['meta']['questions'])}. {c['text']}"
    return f"{c['ref_id']} — {c['section'].replace('_', ' ')}: {c['text']}"


def cached_embeddings(model, texts: list[str]):
    """Yield one vector per text; vectors are cached by text hash so a rebuild only embeds new / changed passages."""
    import hashlib
    import sqlite3

    import numpy as np
    db = sqlite3.connect(ROOT / "data/interim/evidence_embeddings.sqlite")
    db.execute("CREATE TABLE IF NOT EXISTS emb (h TEXT PRIMARY KEY, v BLOB)")
    hashes = [hashlib.sha1((MODEL + t).encode()).hexdigest() for t in texts]
    have = {}
    for i in range(0, len(hashes), 900):
        part = hashes[i:i + 900]
        have.update(db.execute(f"SELECT h, v FROM emb WHERE h IN ({','.join('?' * len(part))})", part).fetchall())
    todo = [i for i, h in enumerate(hashes) if h not in have]
    print(f"  {len(texts) - len(todo):,} cached, {len(todo):,} to embed", flush=True)
    new = model.embed((texts[i] for i in todo), batch_size=32)
    for n, (i, v) in enumerate(zip(todo, new)):
        have[hashes[i]] = np.asarray(v, dtype=np.float32).tobytes()
        db.execute("INSERT OR REPLACE INTO emb VALUES (?, ?)", (hashes[i], have[hashes[i]]))
        if n % 2000 == 0:
            db.commit()
    db.commit()
    db.close()
    for h in hashes:
        yield np.frombuffer(have[h], dtype=np.float32)


def build() -> None:
    from fastembed import TextEmbedding
    t0 = time.time()
    with psycopg.connect(database_url()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path = medibot, public")
        chunks = monograph_chunks(cur) + sider_chunks(cur) + openfda_chunks() + faq_chunks() + label_chunks()
        df = pd.DataFrame(chunks)
        print(df.groupby(["scope", "source"]).size().to_string(), flush=True)
        print(f"  embedding {len(df):,} passages ...", flush=True)
        # ONE process, capped threads, small batches: parallel workers each load the model and exhausted RAM
        model = TextEmbedding(MODEL, cache_dir=str(MODEL_DIR), threads=6)
        vecs = cached_embeddings(model, [embed_text(c) for c in chunks])
        cur.execute("TRUNCATE evidence_chunks")
        cur.execute("DROP INDEX IF EXISTS evidence_chunks_vec_idx")
        with cur.copy("COPY evidence_chunks (scope, ref_id, section, text, source, title, url, meta, embedding) "
                      "FROM STDIN") as cp:
            for i, (c, v) in enumerate(zip(chunks, vecs)):
                cp.write_row([c["scope"], c["ref_id"], c["section"], c["text"], c["source"], c["title"], c["url"],
                              json.dumps(c["meta"], default=str), "[" + ",".join(f"{x:.5f}" for x in v) + "]"])
                if i and i % 50_000 == 0:
                    print(f"    {i:,} ({time.time() - t0:.0f}s)", flush=True)
        print("  building HNSW index ...", flush=True)
        cur.execute("SET maintenance_work_mem = '1GB'")
        cur.execute("CREATE INDEX evidence_chunks_vec_idx ON evidence_chunks USING hnsw (embedding vector_cosine_ops)")
        cur.execute("ANALYZE evidence_chunks")
    print(f"evidence: {len(chunks):,} passages in {time.time() - t0:.0f}s")


def refresh_curated() -> None:
    """Reload only the hand-written passages (FAQ + label sentences) in seconds; the HNSW index takes the inserts."""
    from fastembed import TextEmbedding
    chunks = faq_chunks() + label_chunks()
    model = TextEmbedding(MODEL, cache_dir=str(MODEL_DIR), threads=2)
    vecs = list(cached_embeddings(model, [embed_text(c) for c in chunks]))
    with psycopg.connect(database_url()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path = medibot, public")
        cur.execute("DELETE FROM evidence_chunks WHERE source = ANY(%s)", (list(CURATED_SOURCES),))
        with cur.copy("COPY evidence_chunks (scope, ref_id, section, text, source, title, url, meta, embedding) "
                      "FROM STDIN") as cp:
            for c, v in zip(chunks, vecs):
                cp.write_row([c["scope"], c["ref_id"], c["section"], c["text"], c["source"], c["title"], c["url"],
                              json.dumps(c["meta"], default=str), "[" + ",".join(f"{x:.5f}" for x in v) + "]"])
    print(f"curated: {len(chunks)} passages reloaded")


def seed_cache() -> None:
    """Fill the embedding cache from vectors already in the database (after a run made before the cache existed)."""
    import hashlib
    import sqlite3

    import numpy as np
    db = sqlite3.connect(ROOT / "data/interim/evidence_embeddings.sqlite")
    db.execute("CREATE TABLE IF NOT EXISTS emb (h TEXT PRIMARY KEY, v BLOB)")
    with psycopg.connect(database_url()) as conn, conn.cursor(name="seed") as cur:
        cur.execute("SELECT scope, ref_id, section, text, meta, embedding::text FROM medibot.evidence_chunks")
        n = 0
        for scope, ref, sec, text, meta, emb in cur:
            h = hashlib.sha1((MODEL + embed_text({"scope": scope, "ref_id": ref, "section": sec, "text": text,
                                                   "meta": meta or {}})).encode()).hexdigest()
            v = np.array(emb.strip("[]").split(","), dtype=np.float32)
            db.execute("INSERT OR REPLACE INTO emb VALUES (?, ?)", (h, v.tobytes()))
            n += 1
    db.commit()
    print(f"seeded {n:,} embeddings")


if __name__ == "__main__":
    args = sys.argv[1:]
    seed_cache() if args == ["--seed-cache"] else refresh_curated() if args == ["--curated"] else build()
