# Data Sources Register

Every file under `data/raw/` must be listed here (PS §4.2: document all external sources, licences and preprocessing).
Raw files are kept untouched; all processing happens in `data/` pipeline scripts and is described in the "Processing" column.

| # | Source | Local path | Licence | Downloaded | Used for | Processing |
|---|---|---|---|---|---|---|
| 1 | **A-Z Medicine Dataset of India** — Kaggle `shudhanshusingh/az-medicine-dataset-of-india` (~254k rows; prices as of Nov 2022) | `data/raw/kaggle_az-medicine-dataset-of-india/` | CC BY-SA 4.0 | 2026-10-09 | Primary product catalog: brand, price, manufacturer, pack size, composition, discontinued flag | Planned (Phase 2) |
| 2 | **Indian Medicine Data** — Kaggle `mohneesh7/indian-medicine-data` (~196k rows) | `data/raw/kaggle_indian-medicine-data/` | Apache 2.0 | 2026-10-09 | Catalog cross-check, sub-category, descriptions, side effects, drug-interaction text | Planned (Phase 2) |
| 3 | **11000 Medicine Details** (scraped from 1mg) — Kaggle `singhnavjot2062001/11000-medicine-details` | `data/raw/kaggle_11000-medicine-details/` | CC0 1.0 | 2026-10-09 | Uses, side effects, review sentiment for common medicines | Planned (Phase 2) |
| 4 | **250k Medicines Usage, Side Effects and Substitutes** — Kaggle `shudhanshusingh/250k-medicines-usage-side-effects-and-substitutes` | `data/raw/kaggle_250k-medicines-usage-side-effects-and-substitutes/` | CC BY-SA 4.0 | 2026-10-09 | Side effects, uses, therapeutic/action class, habit-forming flag; substitute lists used only as candidates (re-verified by Composition ID) | Planned (Phase 2) |
| 5 | **MID: Medicines Information Dataset** v2 — Mendeley Data, DOI [10.17632/2vk5khfn6v.2](https://data.mendeley.com/datasets/2vk5khfn6v/2) (192k medicines) | `data/raw/mid/` (`MID.xlsx`, sha256 `07fd281c…0f48e` verified) | CC BY 4.0 | 2026-10-09 | Uses, side effects, how-to-use, safety advice, habit-forming flag, therapeutic & action class | Planned (Phase 2) |
| 6 | **SIDER 4.1** — EMBL, [sideeffects.embl.de](http://sideeffects.embl.de/download/) | `data/raw/sider/` | CC BY-NC-SA 4.0 | 2026-10-09 | Side effects with frequencies, indications, ATC codes | Planned (Phase 10) |
| 7 | **DDInter** — [ddinter.scbdd.com](https://ddinter.scbdd.com/) (drug–drug interactions with severity, by ATC group A–V) | `data/raw/ddinter/` (14 files) | Free for academic/non-commercial use — confirm before any commercial use | 2026-10-09 | Interaction checker (pair + cabinet) | Planned (Phase 10) |

| 8 | **Jan Aushadhi (PMBJP) Product & MRP list** — official site janaushadhi.gov.in, endpoint used by its public "Product & MRP List" page (`/api/v1/website/getAllProductForWeb`, guest token) | `data/raw/jan_aushadhi/products_mrp.json` (2,439 products) | Government of India public information | 2026-10-09 | Cheapest-generic tier for substitutes and savings | Planned: drop MRP = 0 rows; parse generic name → composition |
| 9 | **Drugs and Cosmetics Act 1940 & Rules 1945** (CDSCO consolidated PDF, 635 pp) — Schedules H (536), H1 (46), X (16), J | `data/raw/regulatory/2016DrugsandCosmeticsAct1940Rules1945.pdf` | Government of India legal text | 2026-10-09 | Prescription Guard restriction master | `data/pipeline/extract_schedules.py` → `data/interim/regulatory/schedule_{h,h1,x}.csv` |
| 10 | **CDSCO list of drugs prohibited under Sec. 26A**, status as on 22.11.2021 | `data/raw/regulatory/cdsco_banned_drugs_list_2021.pdf` | Government of India public information | 2026-10-09 | Banned-drug / banned-FDC notice | Planned (Phase 3) |
| 11 | **Banned drugs list** (CSPC compilation incl. itemised 2018 FDC bans) | `data/raw/regulatory/cspc_banned_drugs_india_2023.pdf` | Compilation of government notifications | 2026-10-09 | Itemised banned FDCs (2016/2018) | Planned (Phase 3) |
| 12 | **14 FDCs prohibited, S.O. 2394(E)–2407(E), June 2023** (IDMA circular reproducing Gazette text) | `data/raw/regulatory/idma_2023_06_14_14fdc.pdf` | Reproduction of Gazette notification | 2026-10-09 | Banned FDCs (2023) | Planned (Phase 3) |
| 13 | **156 FDCs prohibited, S.O. 3285(E)–3440(E), Aug 2024** — table from laafon.com (secondary; S.O. range matches Rajya Sabha answer PQ 267, 11.03.2025) | `data/raw/regulatory/laafon_156_fdc_2024.html` | Third-party compilation — verify against Gazette | 2026-10-09 | Banned FDCs (2024) | Parsed → `data/interim/regulatory/banned_fdc_2024.csv` |

| 14 | **NPPA Compendium of Prices 2022** — ceiling prices per unit (tablet / ml / pack) with S.O. number and date; [nppa.gov.in/en/compendiumofprice](https://www.nppa.gov.in/en/compendiumofprice) | `data/raw/nppa/Compendium-Prices-2022pdf-*.pdf` | Government of India public information | 2026-10-09 | Historical reference only (predates NLEM 2022) — never used for the flag | `data/pipeline/nppa.py` → `nppa_ceiling.parquet` (753 rows, status `historical`) |
| 15 | **NPPA therapeutic-category ceiling price lists** (NLEM 2022): anti-cancer, anti-diabetes, anti-HIV, anti-TB, cardiovascular; [nppa.gov.in/en/therapeuticcategorywiseceilingpricelist](https://www.nppa.gov.in/en/therapeuticcategorywiseceilingpricelist) | `data/raw/nppa/2845-fb-posts-*.pdf` (5 files) | Government of India public information | 2026-10-09 | NPPA ceiling-price flag ("price above legal cap"), "As on March, 2026" | `data/pipeline/nppa.py` (word coordinates) → `nppa_ceiling.parquet` (210 rows, status `current`) + `nppa_ceiling_flag.parquet` (203 compositions, highest ceiling per composition) |

NPPA moved from `nppaindia.nic.in` (no longer resolves) to `nppa.gov.in`. The new site's TLS chain is incomplete (missing intermediate certificate), so files were fetched with certificate verification disabled; they are public PDFs and were checked to be valid PDF documents.

## Additional catalogs (added 2026-10-10, loaders in `data/pipeline/sources.py`)

| # | Source (Kaggle ref) | Local path | Licence | Scraped | Used for |
|---|---|---|---|---|---|
| 16 | Apollo Pharmacy Drug Details — `gshreya5/apollo-pharmacy-drug-details-india` (259k) | `kaggle_apollo-pharmacy-drug-details-india/` | CC0 1.0 | 2025-08 | Compositions (incl. OTC consumer brands), Apollo URLs, Apollo's OTC/medicine split as an Rx cross-check |
| 17 | Tata 1mg medicine data — `ujjwalgupta23/medicines-dataset` (274k) | `kaggle_medicines-dataset/tata_1mg_Medicine_data.csv` | unknown (stated on Kaggle) | ~2025 | Compositions, MRP, pack labels |
| 18 | Netmeds disease pages — `drowsyng/medicines-dataset` (24k) | `kaggle_medicines-dataset/medicines.csv` | unknown | ~2025 | Netmeds prices, URLs, "Rx required" flags, compositions |
| 19 | Indian Medicine Master Dataset — `zayedkhan6898738/indian-medicine-master-dataset` (543k) | `kaggle_indian-medicine-master-dataset/` | MIT (merge; some inputs CC BY-NC-SA) | 2026-09 | Compositions, prescription flags, prices |
| 20 | Netmeds medicine dataset — `supriyochowdhury/medicine-dataset-of-netmeds` (27k) | `kaggle_medicine-dataset-of-netmeds/` | © original authors | 2021-04 | Compositions, Netmeds MRP / best price |
| 21 | Netmeds products — `sumitharit/netmedsdata` (9k) | `kaggle_netmedsdata/` | MIT | 2026-05 | Recent Netmeds prices (OTC categories) |
| 22 | 1mg Medicine Dataset 2025 — `prothomeshmistry/1mg-medicine-dataset` (780) | `kaggle_1mg-medicine-dataset/` | CC BY-NC-SA 4.0 | 2025-10 | 1mg MRP / selling price, URLs, Rx flag |
| 23 | 1mg medicines order online — `mukuldeshantri/1mg-medicines-order-online-dataset` (17k) | `kaggle_1mg-medicines-order-online-dataset/` | other (see dataset) | 2022-07 | Rating counts (popularity), prices |
| 24 | 1mg Medicine Data — `rushil09/1mg-medicine-data` (10k) | `kaggle_1mg-medicine-data/` | CC0 1.0 | 2025-06 | Salt, prescription flag, price |
| 25 | India Medicines and Drug Info — `apkaayush/india-medicines-and-drug-info-dataset` (348k) | `kaggle_india-medicines-and-drug-info-dataset/` | CC BY-NC-SA 4.0 | 2025-10 | Prescription flags (cross-check) |
| 26 | PharmEasy dataset — `devshahoff/pharmeasy-dataset` (20 distinct products) | `kaggle_pharmeasy-dataset/` | CC BY-NC-SA 4.0 | 2022-04 | Minor price source |

Downloaded but not used (duplicates of sources above): `riturajsingh2004/extensive-a-z-medicines-dataset-of-india`, `rishgeeky/indian-pharmaceutical-products`, `ankushpoddar/all-india-drug-bank-database` (= 250k dataset), `poojach7611/1mg-data`, `akibuddinnayan/pharmeasy-web-product-data`, `syedahmadrayyan/indian-pharmaceutical-price-data-nppa` (official NPPA PDFs used instead).

**Non-commercial licences** (CC BY-NC-SA, SIDER, DDInter): fine for the hackathon; must be replaced or licensed for any commercial use.

## Reviewed reference lists (hand-curated, in `data/reference/`)

| File | Content | Basis |
|---|---|---|
| `otc_allowlist.csv` | Ingredients allowed OTC per route, with strength caps | Schedule K (household remedies), 2022 draft OTC list (G.S.R. 393(E), 25.05.2022), Schedule H topical exemption, unscheduled status |
| `nutraceutical_patterns.csv` | Vitamins, minerals, supplements (oral) with caps | FSSAI (Health Supplements, Nutraceuticals…) Regulations 2016 |
| `controlled_substances.csv` | Narcotic & psychotropic ingredients | NDPS Act 1985 schedules; Schedules H1/X |
| `banned_fdc_2023.csv` | 14 FDCs prohibited 02.06.2023 | Gazette S.O. 2394(E)–2407(E) |
| `banned_single_rules.csv` | Single-drug and "with any other drug" prohibitions | CDSCO prohibited list (serials cited per row) |
| `banned_status_overrides.csv` | Manual legal-status corrections with reasons | Footnotes of the CDSCO list |
| `ingredient_synonyms.csv` | Reviewed spelling variants | Catalog review (no fuzzy merging) |
| `golden_pairs.csv` | Hand-checked substitution pairs | Manual review |

Also used: Drugs (Fifth Amendment) Rules 2026 (notified 09.06.2026) removing "Syrups" from Schedule K 13(7) — reported by [The South First](https://thesouthfirst.com/health/doctors-prescription-now-mandatory-for-cough-syrups-as-centre-ends-otc-exemption/); Gazette text to be attached.

## Pending
- **NDPS Act schedule**: Schedule H #346 already covers all NDPS narcotics; H1 and X cover the common psychotropics. Curated NDPS ingredient list to be built in Phase 3 from the Act's schedule.
- **openFDA drug label API** (api.fda.gov/drug/label.json, public domain): fetched per ingredient when building the evidence index (Phase 10), not bulk-downloaded.
- **Pharmacy price snapshot** (1mg, PharmEasy, Netmeds, Apollo): built with the price adapters in Phase 9; check each site's terms first.

## Notes
- Kaggle catalogs (1, 4) are CC BY-SA: derived datasets we redistribute must keep the same licence and give attribution.
- SIDER is non-commercial (NC); fine for the hackathon, flag in the limitations section.
- **Schedule H (2006 list) legally includes common "OTC-feeling" drugs** — cetirizine (#104), levocetirizine (#285), fexofenadine (#197), plus class entries "Antibiotics" (#32) and hormones (#31). The OTC vs. restricted policy for these is a deliberate decision in Phase 3 (`docs/SAFETY_POLICY.md`).
- Prices in source 1 are a 2022 snapshot and are never shown to users as current; live/snapshot prices come from the price engine (Phase 9).


## Phase 10 additions (health assistant)

| Source | Where | Licence | Used for |
|---|---|---|---|
| **openFDA drug labels** — bulk download, 262,895 SPL labels (export 2026-10-09), [open.fda.gov](https://open.fda.gov/apis/drug/label/download/) | `data/raw/openfda/` (14 zips, 1.8 GB) → `data/interim/openfda_sections.parquet` | Public domain (US Gov) | Single-ingredient label sections for 1,122 catalog ingredients (948 Rx, 270 OTC labels): uses, warnings, contraindications, interactions, pregnancy, lactation, children, elderly, storage, dependence. Dosing / overdosage sections never kept. Cited to DailyMed by set id. US labelling may differ from India — shown in the citation. |
| **Curated FAQ** — 24 general topics | `data/reference/health_faq.jsonl` | Own text, each with an official source | Jan Aushadhi (PMBI), Schedules H/H1/X and OTC (CDSCO), red-line packs, antibiotics (WHO), banned FDCs, NPPA ceilings, PvPI side-effect reporting, eSanjeevani, Tele-MANAS, 112/108, ORS (WHO), storage / opened shelf life (NHS), expired-medicine disposal (US FDA), missed doses (NHS SPS), tablet splitting (US FDA), FSSAI, AYUSH, antacids with food / other medicines ([NHS – Antacids](https://www.nhs.uk/medicines/antacids/), reviewed 24 Mar 2023, checked 2026-10-11) |
| **Verbatim label sentences** — UK SmPC, Strepsils Original Lozenges ([emc 5638](https://www.medicines.org.uk/emc/product/5638/smpc), revised 05/07/2022, checked 2026-10-11) | `data/reference/label_passages.jsonl` | Short factual quotations with attribution | Sections a monograph lacks (children's age limit, indication, contraindication, warnings), copied word for word. Dosing sentences are never copied. Cited as UK labelling that may differ from India. (MedlinePlus encyclopedia pages were rejected: their terms forbid use in retrieval indexes.) |
| **Embedding model** BAAI/bge-small-en-v1.5 (384-d, ONNX via fastembed) | `data/interim/models/` | MIT | Local passage / query embeddings — no data leaves the machine |
