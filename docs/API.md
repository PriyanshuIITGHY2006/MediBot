# MediBot API (Phase 12)

Run: `make api` → http://127.0.0.1:8000 (interactive docs at `/docs`). Code: `backend/medibot/api/`.
The catalog loads once at startup (~14 s, ~2 GB RAM) before the server takes traffic.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/session/start` | anonymous session id + the full disclaimer (`requires_acknowledgement: true`) |
| POST | `/api/v1/session/ack` | `{session_id}` → disclaimer acknowledged (time + hash of the shown text stored) |
| POST | `/api/v1/medibot/query` | `{user_query, session_id?, disclaimer_acknowledged?}` → the PS response schema |
| POST | `/api/v1/feedback` | `{session_id, turn_id?, rating 1-5, comment?}` → CSAT (rubric C3) |
| POST | `/api/v1/optimize` | `{items: [{name, quantity}]}` → cheapest identical option per medicine + monthly saving |
| POST | `/api/v1/bill/parse` | `{text}` → `{lines: [{name, quantity, quantity_given}]}` from a pasted list ("Dolo 650 x 30") |
| POST | `/api/v1/bill/plan` | `{items: [{name, quantity, product_id?}], allow_alternatives, max_pharmacies}` → the cheapest split across pharmacies (exact, whole packs), plus `as_asked`, `one_stop`, `jan_aushadhi`, savings and unknown delivery terms |
| POST | `/api/v1/bill/read` | raw image body (JPG / PNG / WebP, ≤ 8 MB) → proposed `lines` to review. Tesseract on the server by default; `?vision=1` opts in to the AI reader (`MEDIBOT_OCR_MODEL`, photo sent to the Cline gateway). Never stored. |
| POST | `/api/v1/cabinet/check` | `{items: [{product_id, per_day}]}` → monthly cost, cheapest identical option per medicine, cabinet-wide interactions (DDInter + duplicates). Nothing stored; the cabinet lives in the browser. |
| DELETE | `/api/v1/session/{id}` | forget-me: conversation context and every stored row for the session deleted |
| GET | `/api/v1/metrics` | anonymous 30-day aggregates: turns, sessions, intercepts, emergencies, latency p50/p95, CSAT |
| GET | `/health` | catalog size, evidence DB, storage, LLM, live prices |

## `/api/v1/medibot/query` response

The PS schema field for field (`user_query`, `session_id`, `disclaimer_acknowledged`, `safety_guard{…}`,
`detected_medication{brand_name, active_composition, therapeutic_class, schedule, mrp_inr}`,
`substitutes[{brand_name, manufacturer, active_composition, composition_identically_verified, mrp_inr,
savings_percentage, user_advisory, partner_price_comparison[{platform, price_inr, delivery_eta}]}]`, `disclaimer`),
followed by MediBot's extra fields: `turn_id`, `response_text` (mandated prompt first when intercepting), `cards[]`
(see `RESPONSES.md`), `prices`, `stores`, `health_answer` (citations), `interactions`, `clarification_options`,
`receipt` (why each decision was made), `latency_ms`. Substitutes also carry `composition_id`, `price_per_unit_inr`,
`tier` (brand / jan_aushadhi), and per-platform `url` and `freshness`.

## Safety and robustness

- **Never a 500 with a stack trace:** any failure returns `503 {"response_text": FALLBACK_ERROR, "disclaimer": …}`,
  which tells the user to retry, to consult a doctor for prescription medicines, and to call 112 / 108 in an emergency.
- **Input:** `user_query` 1–1,000 characters (`MEDIBOT_MAX_INPUT_CHARS`), control characters removed; session ids
  `[A-Za-z0-9_-]{8,64}`; anything else is a 422 validation error, never a crash.
- **Rate limit:** 30 requests / minute per client (`MEDIBOT_RATE_PER_MIN`) → 429 with the disclaimer.
- **CORS:** only `MEDIBOT_CORS_ORIGINS` (default localhost:3000 / 5173); GET, POST, DELETE; no credentials.
- **Sessions:** anonymous UUIDs; the in-memory conversation context is dropped after 6 h idle
  (`MEDIBOT_SESSION_IDLE_S`).

## Privacy (12.3)

| Stored (PostgreSQL, `db/migrations/003_api.sql`) | Never stored |
|---|---|
| SHA-256 of the session id; first / last seen; acknowledgement time + disclaimer hash | the session id itself |
| per turn: intent, safety action, intercepted?, emergency?, medicine found?, counts, latency, reader / narrator source | message text, reply text, medicine names, IP addresses |
| feedback: rating + comment (PII-scrubbed: phone, email, Aadhaar, PAN; max 500 chars) | |

Retention: 30 days (`MEDIBOT_RETENTION_DAYS`), purged at startup and daily. Forget-me deletes immediately. Text sent
to the LLM reader is PII-scrubbed first (`llm.scrub`). If the database is down the API still answers; nothing is
stored and `/metrics` reports `storage: unavailable`.

## Results (2026-10-11)

- `backend/tests/test_api.py`: 16 tests. They cover the PS example (Augmentin 625 → intercept, mandated prompt,
  identical substitutes with > 25% savings), OTC not intercepted, emergency, multi-turn over HTTP, bad input → 422,
  a simulated crash → safe 503, the rate limit, feedback PII scrub, metrics, forget-me, the optimizer and health.
- **The full eval through HTTP** (`make eval-http`, 631 cases / 653 turns, model off) gives numbers identical to
  in-process: A1 1.0, A2 0.0101, A3 1.0, B1 76.9%, B3 1.0, C1 0.9847, C2 1.0, 0 violations, 0 errors, 80/80;
  latency p50 31 ms / p95 0.62 s.


### Hindi display (`language`)
`POST /api/v1/medibot/query` accepts `language: "en" | "hi"` (default `en`). With `hi`, `cards[]` are translated for display: fixed safety texts use the hand-written Hindi in `safety/messages_hi.py` (never a model), the mandated prompt stays in English verbatim with the Hindi line under it, other lines go to `MEDIBOT_TRANSLATE_MODEL` and any line whose numbers change is kept in English. `response_text`, `safety_guard` and the rest stay English. `translation` reports what happened.
