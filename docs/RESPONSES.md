# MediBot replies: cards, narrator, output check, disclaimer (Phase 11)

Code: `backend/medibot/cards.py`, `narrator.py`, `safety/output_check.py`, `safety/second_opinion.py`,
`assistant.py` (`compose()`, `disclaimer_card()`).

## Cards

Each reply is a list of cards. Every card holds facts from data or fixed texts, never model text. `cards[]` in
the response gives each card's `type`, its fields, and its plain `text`.

| Card | Contents | In `response_text` |
|---|---|---|
| `intercept_banner` | fixed safety texts in order. When intercepting, `lines[0]` is the mandated prompt verbatim | yes, first |
| `emergency` | 112 / 108 / 14416 text (self-harm variant with Tele-MANAS) | yes, the only card |
| `refusal` | fixed refusal that replaced a card the output check rejected | yes |
| `medicine` | name, composition, category; generic name; "information below is for …" note | yes |
| `info` | grounded health answer copied from cited passages | yes |
| `interactions` | DDInter pair / cabinet check or known partners | yes |
| `substitutes` | ✓ identical alternatives, ₹ per unit, % saved, Jan Aushadhi tier, advisory | yes |
| `prices` | first 4 pharmacy quotes with freshness label and NPPA ceiling flag | yes |
| `compare` | same / different ingredients | yes |
| `stores` | Jan Aushadhi Kendras for a pincode, or the pincode question | yes |
| `sources` | numbered citations | yes |
| `clarify` | "Did you mean …?" | yes, last |
| `fallback` | "I can help with medicine prices …" | yes, if nothing else |
| `lead` | optional one-line opening from the narrator | **no** (UI only) |
| `disclaimer` | short or full disclaimer (see policy) | **no** (UI + `disclaimer` field) |
| `quick_replies` | fixed follow-ups: Cheaper identical options · Compare prices · Side effects · Nearest Jan Aushadhi | **no** |

`response_text` = `compose(cards)`. With the LLM off it is byte-identical to the replies before cards existed:
`make eval-snapshot` checks all 653 eval turns against `eval/snapshots/phase11_baseline_llm_off.jsonl`.

## Narrator

- **Template (default).** No lead. The reply is the cards.
- **LLM lead (optional, gpt-oss-120b, `reasoning_effort=low`).** Used only on price / substitute / store / compare
  turns that are not safety turns. The model sees a small facts JSON: names, prices, freshness, savings, store
  count. It never sees the safety texts and never writes health facts.
- Every draft must pass five checks, or the template is used and the reason goes in the receipt:
  1. output check
  2. every number in the draft is in the facts
  3. every medicine the resolver finds in the draft is one of the turn's medicines (brands made only of common
     English words, like "Total" or "Right", are ignored)
  4. no prescription / schedule wording
  5. at most 45 words
- The lead is a separate card and is **not** part of `response_text`, so the scored reply is the same with the LLM
  on or off.

## Output check

`violations()` covers diagnosis, personal dosing, prescribing / "safe for you" claims, and "no prescription
needed", in English and Hinglish ("aapko typhoid hai", "din mein do baar lo", "ye le lo", "bina parchi mil
jayegi"). `check_cards()` replaces only the failing card with the fixed refusal; the other cards are kept.

It is tested against 33 unsafe and 16 safe sentences, and against all 653 current replies. Kept safe on purpose,
because these are cited monograph wording or conditions, not claims: "You can take it at any time of the day …"
and "If you have diabetes, tell your doctor …".

## Model-first reader (`backend/medibot/reader.py`)

Every message is read by a model first, so any wording works: slang, Hinglish, typos, chat noise, off-topic.
The model only **reads**. It returns JSON, and our code checks every part of it:

| The model returns | What our code does with it |
|---|---|
| `medicines`: names exactly as typed ("augmntin 625", "dolo") | kept only if every word was typed by the user (whole words), then resolved by `mentions.py` like any typed name. The model can't invent "Remo Tablet" for "varemo". |
| `intents`: price / substitute / info / interaction / store / compare | replace the rule intents for this turn |
| `emergency`, `self_harm`, `misuse`, `asks_dose`, `asks_what_to_take`, `asks_diagnosis` | `kernel.apply_reading()`: **add-only**. Emergency also overrides an intercept; prescribing / diagnosis are added only when no medicine was named (asking about a named medicine is not prescribing). |
| `off_topic`, `greeting`, `refers_back` | off-topic and greetings get the help text and no lookups; refers-back feeds the context resolver |

**Merging with the rules:** the rules still run on every message. A rule match is kept if the model named it,
or if it is an **exact** name made of rare words. That way, a real brand the model missed ("alprax") keeps its
intercept, and A1 can't drop. Slang and English look-alikes ("lol" → Lol 200mg, "ngl" → NGL, "waking" → Making,
"cheapr" → Chear, "wid" → Wid-Q) are dropped.

**Model:** `cline:anthropic/claude-haiku-5.5` through the Cline gateway (`MEDIBOT_LLM2_API_KEY`), with a 3.5 s
budget. On timeout, error or no key, the rules work alone and the receipt says so. Benchmark on 15 slang /
Hinglish / emergency messages (2026-10-11):

| Model | Correct | p50 | max |
|---|---|---|---|
| claude-haiku-5.5 (Cline) | 15/15 | 1.5 s | 3.4 s |
| gemini-3.8-flash (Cline) | 15/15 | 2.8 s | 4.9 s |
| gpt-6-luna (Cline) | 15/15 | 2.9 s | 5.2 s |
| deepseek-v4.1-flash (Cline) | 14/15 | 3.4 s | 6 s (timeout) |
| gpt-oss-20b (Groq free) | timed out under load (8k tokens/min) | | |

**Rule fallback, hardened for when the model is down:**
- slang and pronouns can't start a medicine
- an unsure single word that is an English word, or one edit away from one, is not a medicine ("slumped", "killin")
- an unsure first hit gives way to a confident one right behind it ("augmntin 625" → Augmentin 625 Duo)
- wider emergency patterns: not waking up, breathing weird, blue lips, slumped, won't respond, swallowed 15 pills
- "wat do i pop" / "suggest smthng" count as prescribing requests

## Second opinion (plan 6.6)

When the reader answers, it replaces the second opinion (its flags cover emergency, self-harm and misuse on
**every** turn, including intercepted ones). The second opinion only runs when the reader is unavailable. See
`docs/SAFETY_POLICY.md` → "Second opinion".

## Disclaimer policy (11.4)

- **Session start:** full text plus "I understand". The acknowledgement time and a hash of the text are kept on
  the session (`disclaimer_acknowledged_at`); they are stored server-side in Phase 12.
- **Every medical turn** gets the `disclaimer` field and a Disclaimer card. A medical turn is one with a medicine,
  a safety action, a health answer, or medicine wording we couldn't resolve. Greetings and off-topic turns don't
  get one.
- **The full text** appears on the first intercept of a session, the first health answer, every 5th medical turn,
  and every medical turn until the user acknowledges.

## LLM budget

- `llm.py` counts requests per model per UTC day (cache hits are free).
- Optional features (narrator, second opinion) stop at 70% of the free-tier daily limit (1,000 requests per model),
  so the rest stays free for live use. The receipt shows "LLM today: 20b n/1000, 120b n/1000".
- Kill switches: `MEDIBOT_LLM=off` (everything), `MEDIBOT_NARRATOR=off`, `MEDIBOT_SECOND_OPINION=off`,
  `MEDIBOT_READER=off`; quota share `MEDIBOT_LLM_QUOTA_SHARE`.
- The reader may use 95% of a model's daily cap (it is core understanding, not an extra). Cline gateway models are
  paid per use: the Groq per-minute limiter doesn't apply, and our own daily cap is `MEDIBOT_CLINE_DAILY_LIMIT`
  (default 5,000).

## Results

Measured 2026-10-11.

| | Full eval, model off | Stratified 366 turns, model off | Same 366, model on (reader) |
|---|---|---|---|
| A1 restricted blocked | 1.0 | 1.0 | **1.0** |
| A2 false positives | 0.0101 | 0.0101 | **0.0101** |
| A3 disclaimer | 1.0 | 1.0 | 1.0 |
| C1 resolution | **0.9847** | 0.9809 | **0.9809** |
| Health answers grounded + cited | 1.0 | 1.0 | 1.0 |
| B3 alternative quality | 1.0 | 1.0 | 1.0 |
| Violations / errors | 0 / 0 | 0 / 0 | 0 / 0 |
| Latency p50 / p95 | 0.05 s / 0.7 s | | 1.9 s / 3.5 s live (cached rerun 0.15 s) |

The broad second opinion (before the reader) on the same sample: A2 0.0151, C1 0.9727, health 0.846, B3 0.985 —
which is why it was narrowed and then superseded. Manual slang set (11 messages: "wtf is crocin", "wat do i pop",
"augmntin 625 cheapr", "dad isnt waking up", "pan 40 wid daaru", off-topic, greeting …): 11/11 correct with the
reader, and the rules alone also get the safety right (emergencies caught, no slang read as a medicine).
