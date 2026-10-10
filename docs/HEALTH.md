# MediBot Health Assistant (Phase 10)

Code: `backend/medibot/health/` — `evidence.py` (filtered hybrid retrieval), `answer.py` (grounded, cited answers),
`interactions.py` (pair + cabinet checker). Index builder: `db/build_evidence.py` (`make evidence`).

## Principle

Every sentence of a health answer is **copied from a retrieved, cited passage**. Nothing is generated: there is no
model writing medical text. When no passage clears the bar, MediBot says *"I don't have reliable information on …
— please check the leaflet or ask your pharmacist"* instead of guessing.

## Evidence index (`medibot.evidence_chunks`, pgvector)

| Scope | Source | What | Citation |
|---|---|---|---|
| `composition` | MID / 1mg-style monographs (+ mohneesh, k11) | one representative monograph per **ingredient set** (strength-agnostic): overview, uses, benefits, side effects, how to use, how it works, tips, and safety advice for alcohol / pregnancy / breastfeeding / driving / kidney / liver | "Medicine monograph (MID dataset) — written for *brand* (same ingredients)"; the brand name in the text becomes "this medicine" |
| `ingredient` | openFDA single-ingredient labels (1,122 ingredients) | uses, warnings, contraindications, interactions, pregnancy, lactation, children, elderly, storage, dependence — **never dosage / overdosage** | "US FDA label (DailyMed) — US labelling may differ from India", link by set id |
| `ingredient` | SIDER 4.1 | side effects with frequency (very common → rare) | SIDER |
| `composition` | verbatim official label sentences (`data/reference/label_passages.jsonl`) | sections a monograph lacks, copied word for word (e.g. Strepsils: "Not suitable for children under 6 years.", UK SmPC) | the label, with its revision date and "UK labelling may differ from India" |
| `topic` | curated FAQ (24 topics) | Jan Aushadhi, generics, Schedules, red line, antibiotics, banned FDCs, NPPA, PvPI, eSanjeevani, Tele-MANAS, ORS, storage, expiry, missed doses, splitting … | the official source of each entry |

Embeddings: BAAI/bge-small-en-v1.5 (384-d), run locally (ONNX); HNSW index + Postgres full-text (`tsv`).

## Retrieval (filter → rank)

1. **Filter** to passages about *this* medicine: its exact ingredient-set monograph (else each single-ingredient
   monograph), plus US-label / SIDER passages of each ingredient. Curated topics only when no medicine is named.
2. **Question → sections** with EN + Hinglish rules (`pregnan|garbh`, `daru|sharab|alcohol`, `khali pet`, `neend`,
   `bacch`, `aadat` …). No section → overview card (uses + side effects).
3. **Rank** = cosine similarity + section match (primary 0.25 / secondary 0.12) + 0.1 × lexical rank + source prior
   (exact-set monograph +0.06, US label −0.02).
4. **Compose**: per section the best 1–2 passages, ≤ 3 sentences each. Sentences with doses or quantities are
   dropped (`mg`, `tablets`, `times`, `hours`, "four doses", "maximum dose" …) and so is anything the output check
   flags. Citations are numbered across the whole reply.

## Interactions

- **Pairs / cabinet**: all ingredient pairs across the medicines named, graded by DDInter (Major / Moderate /
  Minor / Unknown) with fixed severity texts; when one ingredient's US label names the other, that sentence is quoted
  with its DailyMed link.
- **Same ingredient twice** (Saridon + Combiflam → paracetamol) is flagged first: a double-dose risk.
- **"Which medicines interact with warfarin?"** → the most common catalog ingredients with a Major / Moderate grade.
- No listed interaction → said plainly, with "this does not prove the combination is safe".
- Always ends with "ask your doctor or pharmacist" — never "you can take them together".

## Safety boundaries

- Restricted medicines: mandated prompt first, then general information (allowed by policy), never doses.
- Prescribing / diagnosis / dosing requests: no health passages at all, only the fixed refusal.
- **Missed dose** ("I missed a dose of Thyronorm", "dose bhool gaya"): `detectors.MISSED_DOSE` takes the phrase out
  of the message before the dosing check runs, so the only answer is the cited NHS guidance (check the leaflet,
  never double up, ask your pharmacist). If the rest of the message still asks for an amount ("… how many should I
  take now?", "double dose?"), it is refused as before. The mandated prompt is never removed.
- **Generic name typed** ("is cetirizine habit forming?"): the habit-forming flag comes from every monograph with
  exactly that ingredient set (yes if any says yes).
- **Brand typed alone with an unverified listing** ("Dettol" → a soap): information comes from the brand's verified
  product only when all of that brand's verified products share one ingredient set and none needs a prescription,
  and the reply names the product it used. The Safety Kernel's verdict is unchanged.
- **Warnings fallback**: "is X safe to apply on skin" asks how-to-use first. Label warnings are shown only if no
  specific section can be answered.
- **Own monograph first**: when the asked product has its own monograph, its sections replace the ingredient-set
  representative (brands with the same ingredients can carry different advice). Its brand name becomes "this
  medicine" before the dose filter, so "Dolo 650 Tablet may be unsafe…" is not dropped as a dose sentence.
- **Oral products** never show injection-only content from US labels / SIDER ("IV acetaminophen", "injection site pain").
- **Brand typed alone** ("crocin", "combiflam"): the prescription verdict is still the majority of the brand's
  variants; the product shown is the brand's flagship (most common ingredient set, plain tablet, popular), unless
  the message names a specific listing ("Deriva I 10mg Capsule"), which is kept.
- **Quantities are dosing questions**: "can I take 2 tablets", "2 tablets together?", "double dose", "do goli ek saath"
  are refused, also after a missed-dose phrase is removed. "2 tablets" is never read as a brand (it matched "Of-2 Tab").
- The reply still passes the global output check.

## Results

Measured 2026-10-11 with `make eval` (631 cases / 653 turns, live prices and LLM off) and `make kernel-test`.

| Metric | Before Phase 10 tuning | After |
|---|---|---|
| Health questions answered grounded + cited | 25/30 (83.3%) | **30/30 (100%)** |
| Uncited answers | 0 | **0** |
| C1 resolution | 97.6% | **98.3%** |
| A1 restricted block / A2 false positives | 100% / 1.01% | **100% / 1.01%** |
| Diagnosis / dosing violations · errors | 0 · 0 | **0 · 0** |
| Backend tests | 90 passed, 1 skipped | **101 passed, 1 skipped** |

The five fixed misses: cetirizine habit forming (generic-name flag), antacids with milk (new NHS FAQ), missed dose of
Thyronorm (missed-dose guidance under the mandated prompt), Strepsils for children (UK SmPC sentence), Dettol on
skin (brand's verified product + warnings fallback). The 11 failures left are medicine recognition
(`typo_hinglish`, `catalog_otc_unverified`), not health answers.

Limitations: openFDA and the UK SmPC describe US/UK labelling and may differ from Indian labels (shown in each
citation). SIDER is non-commercial. Monograph text comes from 1mg-style datasets, not regulator labels.
