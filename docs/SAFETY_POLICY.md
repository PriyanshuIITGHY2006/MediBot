# MediBot Safety Policy — Prescription Guard

Decided 2026-10-09. Implemented in `data/pipeline/safety.py` (data tagging) and, from Phase 6, in the
backend Safety Kernel, which must reproduce these decisions exactly. Tests: `data/pipeline/test_safety.py`.

## Principle: deny by default

A product is **OTC only if every ingredient is explicitly allowed for the product's route** — on the
sourced OTC allowlist (with strength caps), a nutraceutical pattern, or a Schedule H substance in a
legally exempt topical form. **Everything else requires a prescription**, including drugs approved after
the 2006 Schedule H list (which carry the "Rx" label under the New Drugs rules).

This makes Restricted Drug Block Rate (rubric A1, and the 60-point cap) hold by construction; the work
goes into keeping the OTC false-positive rate (A2) low through the allowlist.

When a product requires a prescription, the bot outputs the mandated prompt first, verbatim:
> This medication requires a valid prescription. Please consult your doctor.

## Categories (highest wins)

| Category | Severity | Meaning | Source |
|---|---|---|---|
| `banned` | 6 | Matches an **in-force** Section 26A prohibition | CDSCO list (status 22.11.2021), Gazette 2023 (14 FDCs), Gazette 2024 (156 FDCs) |
| `controlled` / `schedule_x` | 5 | NDPS narcotic/psychotropic, Schedule X | NDPS Act 1985; Drugs Rules Schedule X |
| `schedule_h1` | 4 | Schedule H1 | Drugs Rules Schedule H1 (46 entries) |
| `schedule_h` | 3 | Schedule H, incl. class entries "Antibiotics" (#32) and sex hormones (#31) | Drugs Rules Schedule H (536 entries) |
| `prescription` | 2 | Not on any OTC list, injectable, habit-forming, corticosteroid, cough/cold liquid, above OTC strength | Deny-by-default rules below |
| `otc` | 0 | Every ingredient allowed for this route | `otc_allowlist.csv`, `nutraceutical_patterns.csv`, topical exemption |

## Policy decisions

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | Legally Schedule H medicines commonly sold OTC — cetirizine (#104), levocetirizine (#285), fexofenadine/Allegra (#197), ibuprofen/Combiflam (#244), pantoprazole (#386), omeprazole, ranitidine, famotidine, domperidone (#161) | **Follow the law: intercept** | One miss caps the score at 60; a false positive costs ≤ 3–6 points. None of these is on the 2022 OTC draft list. |
| 2 | Cough & cold syrups | **All cough/cold oral liquids require a prescription** | Drugs (Fifth Amendment) Rules 2026 (notified 9 June 2026) removed "Syrups" from Schedule K item 13(7) ("Syrups, lozenges, pills and tablets for cough"). Cough **tablets and lozenges** of unscheduled ingredients remain OTC. |
| 3 | Topical products | **Legal topical exemption, except corticosteroids** | Schedule H note exempts "topical or external use (except ophthalmic and ear/nose preparations containing antibiotics and/or steroids)". Steroid creams stay restricted because of widespread misuse. Eye/ear/nose: exempt unless the product contains any anti-infective or steroid. |

## Rules applied to every product

1. **Banned** — exact ingredient-set match with an in-force entry, respecting the entry's qualifiers:
   release (`Aceclofenac (SR) + Paracetamol` bans only SR), form (`dispersible tablets`, `syrup`), and
   stated strengths. A court stay / quashing for a specific strength combination overrides a general entry.
   Single-drug bans and "X with any other drug" rules are listed in `banned_single_rules.csv`.
   Descriptive or conditional entries ("FDC of vitamins with analgesics", "letrozole for ovulation
   induction", veterinary diclofenac) are **not machine-matched**.
2. **Injectables** → prescription. **Unclassifiable forms / kits** → prescription.
3. **Habit-forming** (MID flag) → prescription.
4. **Cough/cold oral liquid** (any cough/cold ingredient or respiratory therapeutic class) → prescription.
5. Per ingredient: NDPS/X → controlled; H1 → H1 (no topical exemption); H → H unless topically exempt;
   corticosteroid → prescription on any route; anti-infective in eye/ear/nose → prescription;
   otherwise allowed only if on the allowlist for this route **and within the strength cap**
   (e.g. paracetamol ≤ 1000 mg, caffeine ≤ 65 mg, vitamin D3 ≤ 2000 IU, folic acid ≤ 1 mg,
   oxymetazoline ≤ 0.05%). Incomparable units ⇒ not provably within cap ⇒ prescription.
6. **Ambiguous forms** (solution, spray, powder, emulsion): topical when the name says so ("skin",
   "gargle", "lotion"…) or when no ingredient is ever taken by mouth (e.g. *Betadine Solution*).

## Legal status of prohibitions

Only entries with status `prohibited` are ever described to users as banned.

| Status | Meaning (CDSCO footnote) | Count |
|---|---|---|
| prohibited | in force | 658 |
| under_examination_pre1988 | 3#/4#: pre-1988 FDCs referred back by the Supreme Court (14 of the 15 were later banned in 2023) | 19 |
| quashed_by_court | 5#: quashed by Delhi High Court, appeal sub judice | 6 |
| revoked_with_conditions / suspended_then_revoked | 2#: analgin, pioglitazone, dextropropoxyphene allowed with conditions | 3 |
| stayed_by_court | 1#: phenylpropanolamine, stayed by Madras High Court | 1 |
| uncertain | manual override (#215 Glimepiride + Pioglitazone + Metformin — see `banned_status_overrides.csv`) | 1 |

Example: *Paracetamol + Phenylephrine + Caffeine* (2016, S.O. 713(E)) is 3# and was not in the 2023
ban, so cold tablets such as *D Cold Total* are **not** reported as banned.

## Safety Kernel (runtime, Phase 6) — `backend/medibot/safety/`

The kernel makes every safety decision in code; no LLM is involved in it. Order per message:

1. **Emergency / self-harm** (`detectors.EMERGENCY`, `EMERGENCY_SELF_HARM`) → emergency card (112 / 108, Tele-MANAS 14416) only.
2. **Medicine mentions** (`mentions.py`): brands and generic names inside free text, typos, Hinglish, several
   medicines per message. Brands that are English words ("Cold", "Pan", "Refresh") need a strength, form or
   the full multi-word name next to them; filler words ("and", "with", "don't") never join a brand.
3. **Banned** → mandated prompt + banned notice. **Restricted** (any mentioned medicine) → mandated prompt first.
   - *Unsure* matches (look-alike brands) still count for the guard — unsure never means "no medicine" — and
     the bot asks "Did you mean …?".
   - *Brand typed alone* ("calpol", "digene"): decided by the majority of that brand's variants (injections /
     kits excluded unless typed), so "Calpol" is not judged by "Calpol T" (tramadol).
   - Generic name typed ("cetirizine", "warfarin"): restricted unless the ingredient is allowed OTC by mouth.
   - Follow-up without a medicine ("is it safe in pregnancy?") inherits the conversation's medicine and its guard.
4. **Misuse** ("to get high") → intercept + refusal. **Prescription-seeking** → refusal under the mandated prompt.
5. **Diagnosis request / symptom statement** → `DIAGNOSIS_REFUSAL` (no condition named).
6. **Prescribing / dosing request** → `PRESCRIBING_REFUSAL` / `DOSING_REFUSAL`.
7. **Output check** (`output_check.py`) on every card: diagnosis phrases, personal dosing, "you should take",
   "safe for you", "doesn't need a prescription" (English + Hinglish) → the failing card is replaced by the fixed
   refusal, never reworded; the other cards stay (Phase 11, `docs/RESPONSES.md`).
8. Every decision returns a **safety receipt** (what fired, which data, legal reference).
9. **Second opinion** (optional LLM, add-only). See below.

### Model-first reader and second opinion (plan 6.6, Phase 11)

The rule detectors are broad but literal, so slang and paraphrases get past them ("my dad isnt waking up", "wat do
i pop", "lol" read as the brand Lol 200mg). Since Phase 11, **a model reads every message first**
(`backend/medibot/reader.py`, claude-haiku-5.5 through the Cline gateway, 3.5 s budget). It returns JSON only; it
never decides and never writes facts.

- **Medicine names** are kept only if every word was typed by the user, then resolved by `find_mentions` and judged
  by `judge_medicine`. The model can't add a medicine ("Remo Tablet" for "varemo" is dropped).
- **Rule matches stay authoritative for exact names:** a rule match the model didn't list is kept if it is an exact
  name made of rare words, so a real restricted brand the model missed keeps its intercept (A1 can't drop). Slang
  and English look-alikes are dropped.
- **Danger flags are add-only** (`kernel.apply_reading()`, a pure function): emergency and self-harm on every turn,
  even over an intercept; misuse and dosing always; prescribing and diagnosis only when no medicine was named.
  Nothing is cleared or lowered, and the mandated prompt is never removed.
- **Fallback:** on timeout, error, no key or `MEDIBOT_READER=off`, the rules work alone. The rules themselves were
  hardened for this case (slang stop list, English-word guard, wider emergency and prescribing patterns).

**The older second opinion** (`safety/second_opinion.py`, gpt-oss-20b) now runs only when the reader is
unavailable. It is narrowed to emergency, self_harm and misuse. Measured 2026-10-11 on the stratified LLM-on
sample, its broader version (diagnosis / prescribing / dosing / rx_seeking flags + medicine names) tagged about 38
plain information questions as "prescribing" and invented "Remo Tablet" for "varemo 5% Eye sasta". That raised A2
from 1.01% to 1.51% and cut grounded health answers from 100% to 84.6%, so those flags were removed.

Fixed safety texts live in `messages.py` and avoid trigger phrases even inside refusals.

**Results on the eval set (631 cases):** A1 block rate **100%** (343/343), OTC false positives **1.0%**,
diagnosis/dosing violations **0**, resolution 89%. Unit tests: `make kernel-test` (29).

## What the bot says

| Category | Response |
|---|---|
| banned | "This combination is prohibited in India (S.O. …, date). Please consult your doctor for an alternative." No prices or substitutes for the banned product. |
| controlled / X / H1 / H / prescription | Mandated prompt first, verbatim. Then general information, verified substitutes and prices are allowed; never dosing, never "you can take it". |
| otc | Full help, plus the disclaimer; no personal dosing for children, pregnancy, elderly, kidney/liver disease. |

## Coverage numbers (from `data/processed/safety_report.json`)

All 284,626 products tagged (0 untagged). Ingredients: 473 Schedule H, 31 H1, 2 X, 33 NDPS, 1,285
unscheduled. Products: ~145k Schedule H, ~79k prescription (default), ~31k H1, ~12k controlled,
~7.3k banned, ~10k OTC.

## Known limitations

- **OTC brand coverage**: the drug datasets (1mg "drugs" pages) omit many consumer OTC brands
  (Digene, Eno, Strepsils, Vicks VapoRub, Electral, Becosules…). Unknown brands are never resolved
  confidently, so they are not intercepted by mistake — but they cannot be answered precisely either.
- The 2006 Schedule H list predates many drugs; those are prescription by default (correct for A1, and
  in line with "Rx" labelling of new drugs), but legal citation for them is "not on OTC list", not a
  schedule entry.
- Descriptive FDC bans are not machine-matched (they still get intercepted when any ingredient is
  restricted, which is almost always the case).
- Policy follows the Drugs Rules as available on 2026-10-09; CDSCO's prohibited list is "as on
  22.11.2021" plus the 2023 and 2024 Gazette notifications.
