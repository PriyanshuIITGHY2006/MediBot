# Data Quality Report — Phase 2 (catalog normalisation)

Built 2026-10-09 with `make data`. Raw sources are listed in [SOURCES.md](SOURCES.md).
Numbers below come from `data/processed/quality_report.json` and the acceptance tests.

## Headline numbers

| Metric | Value |
|---|---|
| Products (unique normalised names, all sources) | **284,626** |
| SKUs (product × pack, with price) | 253,973 — pack size parsed for **100%** |
| Products with every strength stated | **98.2%** |
| Products eligible as substitutes | **216,659** |
| Distinct Composition IDs (substitutable) | 16,062 |
| Compositions with ≥ 2 brands (a cheaper alternative can exist) | 8,278, covering **208,875** products |
| Distinct ingredients | 1,824 |
| SKU prices flagged as outliers (excluded from "cheapest") | 1,678 (0.66%) |
| Jan Aushadhi drugs mapped to a catalog Composition ID | **1,304 / 1,789 (72.9%)** |
| Jan Aushadhi saving vs. median brand of the same composition | **median 67.4%**; 96.1% save ≥ 25% |
| Golden substitution pairs (hand-checked) | **49 / 49 pass** (1 skipped: product not in catalog) |
| Brand search top-1 with one typo (200 popular products) | **98.5%** |
| NPPA current ceiling prices parsed (NLEM 2022 lists, as on March 2026) | **210** rows → 203 flaggable compositions (164 rows match catalog) |

## Pipeline

```
data/raw ──► build_catalog.py ──► products / skus / compositions / ingredients (.parquet)
                 │                         │
                 │                         ├──► jan_aushadhi.py ──► jan_aushadhi.parquet
                 │                         └──► search_index.py ──► search_index.parquet
                 └── normalize.py (composition parser, units, form, release, pack, Composition ID)
```

## Composition ID

`composition_key = sorted(ingredient:strength) | ... # form # release`, e.g.

```
amoxicillin:500mg|clavulanic acid:125mg#tablet#IR      ->  c_<sha1[:16]>
```

- **Ingredients**: lower-cased, spelling unified via `data/reference/ingredient_synonyms.csv`
  (reviewed list only), aliases like `Paracetamol/Acetaminophen` reduced to the first name.
  Salt forms are **kept** (metoprolol succinate ≠ metoprolol tartrate).
- **Strengths**: converted to one unit per kind (g/mcg → mg; `200mg/5ml` → `40 mg/ml`; % w/w, % w/v,
  IU, spores kept as their own units). Unstated strength (`NA`) ⇒ product is never substitutable.
- **Form**: 40 canonical forms (tablet, tablet_dispersible, capsule, capsule_softgel, syrup, dry_syrup,
  suspension, eye_drops, injection, …). Different forms never match (tablet ≠ dispersible tablet ≠ capsule).
- **Release**: IR / SR / ER / PR / CR / MR / OD / DR / EC. "MR" before the form word is treated as a
  brand suffix (muscle-relaxant combos like *Zerodol MR*), after it as modified release.
  For molecules that are always enteric-coated (PPIs, mesalazine) an explicit EC/DR marker is ignored.

## Source of truth for compositions — and why

| Finding | Consequence |
|---|---|
| **A-Z dataset truncates every composition to 2 ingredients** (e.g. *Cheston Cold* listed as Cetirizine + Paracetamol; Phenylephrine missing) | A-Z is the lowest-priority composition source. Products whose only composition is A-Z with exactly 2 ingredients are `truncation_risk` (**57,642**) and are never substitutable. |
| MID (1mg scrape, 192k rows) has full compositions but sometimes writes `Mometasone+Fusidic Acid (0.1% w/w)` (strength only on the last ingredient) | The chosen source is the highest-priority one that states **every** strength; if a full source lacks strengths but A-Z has the same ingredient set with strengths, A-Z is used. |
| Sources disagree on 255 products (e.g. Pilocarpine 2% vs 0.5%; Lactobacillus 60 mg vs 2.5 bn spores) | Status `conflict`, never substitutable. |

Priority: MID → mohneesh7 → 1mg-11k → A-Z. Status counts: verified 114,992 · single source 111,737 ·
truncation risk 57,642 · conflict 255.

## Why there is no fuzzy matching of ingredient names

A scan of the ingredient vocabulary for near-identical spellings (score ≥ 88) found 77 pairs; **only 7 were
real duplicates** (typos such as *clinidipine/cilnidipine*). The rest are different drugs:
omeprazole / **es**omeprazole, artemether / arteether, cloxacillin / **di**cloxacillin,
amlodipine / **S-**amlodipine, interferon alfa-2a / 2b. A 94% fuzzy threshold would have merged
artemether with arteether. Typos are therefore fixed only through the reviewed synonym list.

## Price data

- Baseline MRP from the A-Z dataset (**Nov 2022 snapshot**) — never presented as current; live / snapshot
  prices come from the price engine (Phase 9).
- Price per unit = price ÷ pack quantity (tablets/capsules/vials, ml, or g).
- Outliers: unit price < 0.2× or > 5× the median of the same Composition ID (groups ≥ 5), or price ≤ 0.
  Example: *Apcil Tablet* at ₹0.70/tablet vs. ~₹22 for amoxicillin-clavulanate 625.

## Search index

Two-stage: fuzzy brand-stem match (134k stems) → full-name scoring (token-sort ratio, strength numbers
from the name **and** the composition, dosage-form bonus, popularity tiebreak). Generic names resolve to
an ingredient (`alprazolam`, `azitromycin` → azithromycin). Every match carries a confidence; below 88
the bot must ask "Did you mean…?" — unknown brands (*Saridon*, *Liv 52*) are never resolved confidently.

## NPPA ceiling prices

- **Current** (drives the flag): five NLEM 2022 therapeutic-category lists "As on March, 2026" — anti-cancer,
  anti-diabetes, anti-HIV, anti-TB, cardiovascular. Read from word coordinates because cells are vertically
  centred; rows whose dosage cell is ambiguous (two forms, or strength count ≠ ingredient count) are dropped,
  not guessed (210 of ~261 rows kept). Values are pinned by tests against the PDF (e.g. Glimepiride 1 mg ₹3.78).
- **Historical** (reference only): the 2022 Compendium (NLEM 2015, updated 10.08.2022). It predates NLEM 2022,
  so molecules dropped from the list (e.g. ranitidine) are no longer price-controlled — never used for the flag.
- The flag compares against the **highest** current ceiling for a composition, since ceilings differ by pack
  (dexamethasone 4 mg/ml: ₹0.93–5.21 per ml).
- **Apply only to live prices.** On the Nov-2022 A-Z prices, 3,379 of 10,211 price-controlled SKUs exceed today's
  ceiling — because NLEM 2022 lowered ceilings after those prices were recorded, not because of overcharging.

## Price source caveats (found in Phase 8)

- `onemg_2025` (1mg Medicine Dataset 2025): its "Selling_Price" column is a **per-unit** price and "Pack_Size" holds
  the strength ("625 Tablet"), so no pack price can be derived — used for URLs and Rx flags only, never for prices.
- `netmeds_2026` has no pack sizes: kept, but a newer pack-less price never replaces an older price that has a
  pack size (price per unit must be computable).
- Master-dataset prices are MRP references (`platform = reference`), never shown as a pharmacy's selling price.

## Known limitations

- **Name/composition mismatches in source data**: e.g. *Allerhin D Plus 120mg* is listed as fexofenadine
  only although "D Plus" suggests a combination. Substitute ranking (Phase 8) will down-rank such names.
- **57,642 products** (mostly A-Z-only, 2-ingredient) cannot be offered as substitutes or matched until a
  full composition is found.
- Jan Aushadhi: 27% of drug rows don't match a catalog composition — mostly strength combinations no brand
  sells, kits/combi-packs, and multi-release combinations.
- NPPA ceilings cover only the five published category lists, not all ~900 NLEM 2022 formulations.
- Some popular brands are absent from all sources (e.g. Saridon; Ayurvedic products such as Liv 52).
- Ambiguous typos where two real brands are one edit apart (*oelanz* → Oleanz / Olanz) are resolved by
  asking the user.
