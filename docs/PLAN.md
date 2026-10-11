# MediBot — Execution Plan

> Core principle: **the LLM never decides.** Code decides safety, substitutes and prices; the LLM only parses text into a typed request and narrates verified facts.
>
> Order: Data → Composition ID → safety tags → graph DB → eval set → Safety Kernel → understanding + context → substitutes → prices → health assistant → response builder → API → design system → screens → hero features → trust layer → hardening → deploy → docs/deck. Mobile last.

## Phase 0 — Setup & decisions
- [ ] 0.1 Confirm deadline, team split, LLM key/budget, hosting accounts
- [x] 0.2 Repo layout: `data/`, `backend/`, `web/`, `eval/`, `docs/`
- [ ] 0.2 Git, README skeleton, `.env.example`, lint/format, CI
- [ ] 0.3 Lock decisions in `docs/DECISIONS.md` (FastAPI + PostgreSQL + pg_trgm + pgvector + Next.js/Tailwind + Groq-hosted open models (optional); snapshot + live prices; PS JSON schema + `cards[]`)

## Phase 1 — Data acquisition
- [x] 1.1 Core catalogs → `data/raw/` (A-Z India, mohneesh7, 1mg 11k, 250k + substitutes, MID)
- [x] 1.2 Safety & clinical: Schedule H/H1/X (extracted to CSV), banned FDCs (2021 list, 2023, 2024), DDInter, SIDER 4.1
- [ ] 1.2b NDPS curated list → moved to Phase 3; openFDA labels → fetched per ingredient in Phase 10
- [x] 1.3 Jan Aushadhi product & MRP list (2,439)
- [x] 1.3b NPPA ceiling prices (Compendium 2022 + 5 NLEM 2022 category lists, from nppa.gov.in)
- [ ] 1.3c Pharmacy price snapshot → built with price adapters in Phase 9
- [x] 1.4 `docs/SOURCES.md`
- Done when: every raw file is registered in SOURCES.md

## Phase 2 — Cleaning & normalisation
- [x] 2.1 Unified product table — 284,626 products, 253,973 SKUs (`build_catalog.py`)
- [x] 2.2 Composition parser — 98.2% of products with every strength parsed (`normalize.py`)
- [x] 2.3 Ingredient synonyms — reviewed list only; fuzzy merging rejected (77 near-pairs, 7 real typos)
- [x] 2.4 Form (40 canonical) + release (IR/SR/ER/PR/CR/MR/OD/DR/EC)
- [x] 2.5 Composition ID — 49/49 golden pairs pass (`data/reference/golden_pairs.csv`)
- [x] 2.6 Price per unit — 100% of SKUs; 1,678 outliers flagged
- [x] 2.7 Search index — 98.5% top-1 with typos; ingredient (generic) matches; confidence for "did you mean"
- [x] 2.8 Data quality report → `docs/DATA_QUALITY.md`
- [x] 2.x Jan Aushadhi mapped to Composition IDs — 1,304 drugs; median 67% cheaper than brands
- [x] 2.x NPPA ceiling prices — 210 current rows (NLEM 2022, Mar 2026) → 203 flaggable compositions; 2022 compendium kept as historical only
- Rebuild everything: `make data` (~3 min, 26 datasets) · tests: `make data-test` (166 pass)

## Phase 3 — Safety data
- [x] 3.1 Ingredient restriction master — 1,824 ingredients (473 H, 31 H1, 2 X, 33 NDPS) → `ingredient_safety.parquet`
- [x] 3.2 Class rules — antibiotics (H #32), sex hormones (H #31), corticosteroids, anti-infectives (MID classes + names)
- [x] 3.3 OTC allowlist (sourced: Schedule K, 2022 OTC draft, FSSAI nutraceuticals) with route + strength caps; deny by default
- [x] 3.4 Policy decisions (strict Schedule H; cough syrups Rx per 2026 rule; topical exemption except steroids) → `docs/SAFETY_POLICY.md`
- [x] 3.5 Every product tagged (0 untagged, build fails otherwise) → `product_safety.parquet`; 36 safety tests incl. invariants
- [x] 3.6 Banned FDCs with legal status (658 in force; court relief honoured; qualifiers SR/dispersible/strength) — `banned.py`
- [x] 3.7 OTC consumer brands — 12 more datasets added (Apollo 259k, tata_1mg 274k, Netmeds, master 543k …): Digene, Electral, Becosules, Gelusil, Volini, Shelcal, Saridon now with full compositions; 41k Apollo /otc/ products without composition added as `otc_unverified` (recognised, never blocked, no ingredient claims); 6 curated label entries (`otc_brands_curated.csv`)
- [ ] 3.7b Verified compositions for the ~41k `otc_unverified` products — needs product-page fetch (Phase 9, same adapters as live prices)
- [x] 3.8 Rx-flag sources measured: only Apollo (75% Rx) and Netmeds (92%) discriminate; master / India / 1mg sets (≥ 98.6% Rx) ignored as evidence

## Phase 4 — Medicine Graph DB
- [x] 4.0 Local PostgreSQL 18 + pgvector + pg_trgm (`scripts/setup_postgres.sh`); Azure for Students for deployment
- [x] 4.1 Schema (`db/migrations/001_core.sql`): products, compositions, ingredients, safety, rx_flags, banned/schedule entries, price_observations + latest_prices (materialised), jan_aushadhi, nppa_ceiling, product_info, interactions, side effects, kendras, evidence_chunks
- [x] 4.2 Loader with COPY (`db/load.py`) + enrichments: medicine info (167k monographs), DDInter (208k pairs), SIDER (19k side effects) + ATC codes, 21,286 Jan Aushadhi Kendras (no personal data), 243k product images
- [x] 4.3 Indexes: substitutes 29 ms, fuzzy candidates 13 ms, nearest kendra 19 ms; `make db` + `make db-test` (10 pass) → `docs/DATABASE.md`

## Phase 5 — Eval suite (before the bot)
- [x] 5.1 631 cases / 653 turns (`eval/build_cases.py` → `eval/cases/*.jsonl`): 56 hand-labelled policy medicines, catalog sample per safety category, typos/Hinglish, brand→generic, health Qs, diagnosis & prescribing bait, emergencies, prompt injection, 20 multi-turn scripts
- [x] 5.2 Runner + rubric scorecard (`eval/run.py`, 60-point cap, −10 penalties, failure list); response contract `eval/contract.py`; baselines NullBot / AlwaysBlockBot; policy audit 56/56 agree → `docs/EVAL.md`

## Phase 6 — Safety Kernel
- [x] 6.1 Ordered policy (`backend/medibot/safety/kernel.py`): emergency → banned → restricted → misuse → diagnosis → prescribing/dosing → allow
- [x] 6.2 Detectors EN + Hinglish (`detectors.py`); medicine mentions in free text (`mentions.py`: typos, multi-medicine, English-word brands, unsure-still-blocks, brand-majority)
- [x] 6.3 Mandated prompt verbatim, always first (`messages.py`); output check (`output_check.py`)
- [x] 6.4 Safety receipt per decision
- [x] 6.5 Gate met on eval: **A1 100%**, FP **1.0%**, **0** violations, C1 89% → measurable 57/80 (`make eval`, `make kernel-test` 29 pass)
- [x] 6.6 Add-only LLM safety layer → superseded by the model-first reader (Phase 11): emergency / self-harm / misuse / dose / what-to-take / diagnosis flags, add-only (`kernel.apply_reading`); the broad second opinion was measured and narrowed (it raised A2 to 1.51%)

## Phase 7 — Understanding + context
- [x] 7.1 Rules first (`backend/medibot/understanding.py`): multi-intent, ordinals, "500 wala", "gel one", pincode, back-references (EN + Hinglish)
- [x] 7.2 LLM (Groq gpt-oss-20b, `llm.py`) only when rules find nothing; suggests medicine words/intents only → deterministic resolver + kernel. Timeout, cache, TPM limiter, PII scrub, kill switch; bot fully works with LLM off
- [x] 7.3 "Did you mean" for unsure matches (unsure still blocks)
- [x] 7.4 Session working set (`context.py`): focus, last list, pending question, last intents
- [x] 7.5 Reference resolver: strength/form variants, ordinals, follow-ups inherit medicine + guard + question type; store locator (pincode → nearest Kendras). **Multi-turn 95%** (gate ≥ 90%); eval A1 100%, FP 1.0%, C1 90%, 0 violations → 60/80; backend tests 47 + live LLM test

## Phase 8 — Substitute engine
- [x] 8.1 Same Composition ID (ingredients + strengths + form + release), cheapest per unit first, one listing per maker, + Jan Aushadhi tier (`backend/medibot/substitutes.py`)
- [x] 8.2 Card payload: ✓ verified, maker, price per unit, ₹/% saved, per-platform quotes, doctor/pharmacist advisory
- [x] 8.3 Edge cases: banned → none, no price → no savings claim, already cheapest, outlier prices, discontinued, alias duplicates, name-suggests-extra-ingredient data errors excluded; "the cheapest one" / "the second one" follow-ups
- Gate met: **B1 avg savings 76.9%** (≥ 25%), **B3 100%** identical + advised; eval **80 / 80** measurable (A1 100%, FP 1.0%, C1 98%, C2 100%, 0 violations); backend tests 58

## Phase 9 — Price engine + background jobs
- [x] 9.0 robots.txt checked: product pages only on 1mg / Apollo / Netmeds; no search / api; PharmEasy not fetched
- [x] 9.1 Adapters with pure parsers tested on real page snippets (`backend/medibot/prices/adapters.py`)
- [x] 9.2 Cache (6 h) → live (2.5 s reply budget, background completion) → dated snapshot; freshness labels
- [x] 9.3 Per-product URLs from the catalog (no search); per-unit prices; delisted (404) recorded
- [x] 9.4 Refresher (`make prices-refresh`): top 300 → 545/602 pages in 5.4 min
- [x] 9.5 Accuracy audit (`make prices-audit`): **B2 100%** (70/70) with live cache vs **0%** with dataset snapshots
- [x] 9.6 NPPA ceiling flag on live/cached prices only; substitutes re-priced live; works with live off (eval) → `docs/PRICES.md`
- [x] 9.7 PharmEasy + Truemeds: URLs from their sitemaps (no search), exact matching (136,992 URLs), per-page verification (94% of fetched pages verified, wrong products never shown), exact-host + path + robots.txt guards; **B2 100%** on all 5 pharmacies (128/128 pairs)

## Phase 10 — Health assistant + interactions
- [x] 10.1 Evidence index (MID, SIDER, openFDA, curated FAQ, verbatim label sentences) by ingredient set & section — 95,243 passages, pgvector HNSW + full text (`make evidence`; `make evidence-curated` reloads hand-written passages in seconds)
- [x] 10.2 Filtered hybrid retrieval (ingredient-set filter → cosine + section match + lexical + source prior)
- [x] 10.3 Grounded, cited answers; "no reliable info" otherwise — extractive only, dose sentences dropped; missed-dose questions get cited guidance (amount requests still refused)
- [x] 10.4 DDInter pair + cabinet checker (duplicate ingredient first, graded pairs, known partners)
- Gate met: health questions **30/30 grounded + cited (100%)**, uncited 0; C1 98.3%, A1 100%, A2 1.01%, violations 0, errors 0, 80/80 measurable; backend tests 101 passed, 1 skipped

## Phase 11 — Response builder
- [x] 11.1 Card types (InterceptBanner, EmergencyCard, MedicineCard, SubstituteTable, PriceStrip, InteractionCard, InfoCard, Clarify, Disclaimer, QuickReplies); cards check 100% of turns (`backend/medibot/cards.py`)
- [x] 11.2 Narrator with template fallback (`narrator.py`): LLM lead only on price / substitute / store / compare turns, 5 checks, 116 leads shipped on the sample with 0 invented facts
- [x] 11.3 Output check: EN + Hinglish patterns, per-card replacement; 0 false flags on the 653 replies
- [x] 11.4 Disclaimer policy: A3 rate 0.9936 → **1.0**
- [x] 11.5 Model-first reader (`reader.py`, claude-haiku-5.5 via Cline, Groq / rules fallback): any wording (slang, Hinglish, typos, off-topic). Typed-words guard on medicine names; rule matches on exact rare brand words stay authoritative
- Gate met (2026-10-11), stratified 366 turns, model on vs off: A1 1.0 / 1.0, A2 0.0101 / 0.0101, C1 0.9809 / 0.9809, health 1.0, B3 1.0, 0 violations; full eval model off: A1 1.0, A2 0.0101, C1 **0.9847**, 80/80; live latency p50 1.9 s / p95 3.5 s with the reader; backend tests 241 → `docs/RESPONSES.md`

## Phase 12 — API, sessions, privacy
- [x] 12.1 `/api/v1/medibot/query` (PS schema field for field + cards / citations / receipt), `/session/start`, `/session/ack`, `/feedback`, `/optimize` (bill optimizer), `/metrics`, `/health`, `DELETE /session/{id}` (FastAPI, `backend/medibot/api/`)
- [x] 12.2 Anonymous sessions (UUID; only a SHA-256 is stored; context dropped after 6 h idle)
- [x] 12.3 No message text stored (outcomes only), PII-scrubbed feedback, forget-me, 30-day retention
- [x] 12.4 Rate limit 30/min, input ≤ 1,000 chars, control characters stripped, CORS allow-list; never a 500 (safe 503 fallback)
- Gate met (2026-10-11): 16 API tests; the full eval **through HTTP** = in-process (A1 1.0, A2 0.0101, C1 0.9847, 0 violations, 80/80; p50 31 ms) → `docs/API.md`

## Phase 13 — Design system
- [ ] 13.1 Tokens (warm paper / charcoal, ink, pharmacy green, amber, red; light + dark)
- [ ] 13.2 Type: Geist/Inter Tight + Geist Mono, tabular numbers
- [ ] 13.3 Restyled shadcn primitives
- [ ] 13.4 Rules: hairlines not shadows, spacing scale, one icon set, short motion; `/styleguide`

## Phase 14 — Web app
- [ ] 14.1 Onboarding disclaimer + logged ack, empty state
- [ ] 14.2 Chat panel (streaming lead, cards, quick replies, voice, retry)
- [ ] 14.3 Live Medicine Sheet (Overview / Substitutes / Prices / Interactions)
- [ ] 14.4 ⌘K search
- [ ] 14.5 All card components with loading/empty/error states
- [ ] 14.6 Responsive drawer
- [ ] 14.7 Accessibility pass

## Phase 15 — Hero features
- [ ] 15.1 Bill Optimizer (text → photo/OCR; cheapest cart incl. split, delivery fee, min order)
- [ ] 15.2 Pharmacist Card (side-by-side, QR, WhatsApp share, print)
- [ ] 15.3 My Cabinet (local; monthly cost, refill .ics, interactions, price-drop flag)
- [ ] 15.4 Hindi / Hinglish

## Phase 16 — Trust layer
- [ ] 16.1 "Why this answer?" safety receipt
- [ ] 16.2 `/trust` live rubric dashboard
- [ ] 16.3 Red-team generator → regression tests
- [ ] 16.4 Feedback + CSAT

## Phase 17 — Hardening
- [ ] 17.1 Chaos drills (LLM / prices / DB down)
- [ ] 17.2 Fuzzing
- [ ] 17.3 Load test: 50 concurrent, p95 < 3 s
- [ ] 17.4 Frontend error boundaries, offline banner

## Phase 18 — Deploy
- [ ] 18.1 Vercel + Render/Railway + Supabase
- [ ] 18.2 Health checks, warm-up, error tracking
- [ ] 18.3 Eval against production

## Phase 19 — Deliverables
- [ ] 19.1 README
- [ ] 19.2 Technical document
- [ ] 19.3 Benchmark report
- [ ] 19.4 Deck
- [ ] 19.5 Recorded demo

## Phase 20 — Rehearsal & freeze

## Later — Mobile (Expo, same API + tokens)
