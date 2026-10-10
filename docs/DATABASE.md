# MediBot Database (Phase 4)

PostgreSQL 18 + pgvector 0.8 + pg_trgm, schema `medibot`. Local for development
(`sudo bash scripts/setup_postgres.sh`), Azure Database for PostgreSQL for the deployed demo.
Schema: [`db/migrations/001_core.sql`](../db/migrations/001_core.sql). Rebuild: `make db` (≈3 min). Tests: `make db-test`.

## Tables

| Table | Rows | What it holds |
|---|---|---|
| `products` | 570,968 | Every listing: name, maker, form, release, composition, Composition ID, aliases (`canonical_id`), URLs (1mg / Apollo / Netmeds), image, popularity |
| `compositions` | 37,785 | Exact-equivalence groups (same ingredients, strengths, form, release) |
| `composition_ingredients` | 88,029 | Ingredient + strength per composition |
| `ingredients` | 4,664 | Schedule (H / H1 / X / NDPS), class flags, WHO ATC codes |
| `product_safety` | 570,968 | Prescription Guard category + reasons + legal citation |
| `rx_flags` | 795,049 | Independent "prescription required" labels per source (cross-check) |
| `banned_entries`, `schedule_entries` | 688 / 598 | Section 26A prohibitions with legal status; Schedules H/H1/X |
| `price_observations` | 942,833 | Every price seen (platform, date, pack, price per unit, outlier flag) |
| `latest_prices` (materialised view) | ~387k | Latest usable price per product per platform |
| `jan_aushadhi` | 2,439 | Government generics mapped to Composition IDs |
| `nppa_ceiling` | 963 | Ceiling prices (`current` drives the flag, `historical` is reference) |
| `product_info` | 166,789 | Monograph text: uses, side effects, how to use, how it works, tips, structured safety advice |
| `interactions` | 208,446 | Ingredient-pair interactions with severity (DDInter) |
| `ingredient_side_effects` | 19,324 | Side effects with frequency (SIDER) |
| `kendras` | 21,286 | Jan Aushadhi stores with pincode and coordinates (no personal data) |
| `evidence_chunks` | — | Retrieval chunks + embeddings for the health assistant (Phase 10) |

## Typical queries (all < 50 ms)

```sql
-- cheapest identical substitutes with latest prices
WITH t AS (SELECT composition_id FROM products WHERE key = 'augmentin 625 duo tablet')
SELECT p.name, lp.platform, lp.price_per_unit_inr, lp.observed
FROM products p JOIN t USING (composition_id)
JOIN latest_prices lp ON lp.product_id = p.product_id
WHERE p.substitutable ORDER BY lp.price_per_unit_inr LIMIT 5;

-- nearest Jan Aushadhi Kendras
SELECT kendra_code, address, pincode FROM kendras WHERE lat IS NOT NULL
ORDER BY (lat - :lat)^2 + ((lon - :lon) * cos(radians(:lat)))^2 LIMIT 3;

-- interactions between two medicines' ingredients
SELECT a.name, b.name, x.severity FROM interactions x
JOIN ingredients a ON a.ingredient_id = x.ingredient_a JOIN ingredients b ON b.ingredient_id = x.ingredient_b
WHERE a.name = ANY(:ings) AND b.name = ANY(:ings);
```

Fuzzy name search: `products.search_text` has a trigram index for **candidate retrieval**; ranking uses the
tested resolver in `data/pipeline/search_index.py` (98% top-1 with typos), not raw trigram similarity.

## Data handling notes

- `kendras`: the government source includes store owners' names and phone numbers — **not loaded**.
- `products.image_url` points at 1mg's CDN — UI must attribute and fall back to a placeholder.
- Price rows from the master dataset are MRP references (`platform = 'reference'`) and are excluded from
  `latest_prices`; they never appear as a pharmacy's selling price.
