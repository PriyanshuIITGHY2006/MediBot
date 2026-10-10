-- MediBot core schema (PostgreSQL 18 + pgvector + pg_trgm). Portable: no vendor-specific features.
-- Loaded by db/load.py from data/processed/*.parquet. Re-runnable: drops and recreates schema "medibot".

DROP SCHEMA IF EXISTS medibot CASCADE;
CREATE SCHEMA medibot;
SET search_path = medibot, public;

-- ---------------------------------------------------------------- provenance
CREATE TABLE sources (
    source       text PRIMARY KEY,           -- e.g. 'apollo', 'mid', 'az'
    platform     text,                       -- 1mg / apollo / netmeds / pharmeasy / government / label
    observed     text,                       -- YYYY-MM when scraped / published
    licence      text,
    description  text
);

-- ---------------------------------------------------------------- ingredients
CREATE TABLE ingredients (
    ingredient_id        serial PRIMARY KEY,
    name                 text NOT NULL UNIQUE,      -- canonical lowercase, e.g. 'amoxicillin'
    base                 text NOT NULL,             -- without salt words, e.g. 'cetirizine'
    n_products           int  NOT NULL DEFAULT 0,
    schedule             text,                      -- 'H' | 'H1' | 'X' | 'NDPS' | NULL
    schedule_refs        text,                      -- 'H#104 Cetirizine hydrochloride; ...'
    controlled_category  text,                      -- 'narcotic' | 'psychotropic' | NULL
    is_antibiotic        boolean NOT NULL DEFAULT false,
    is_corticosteroid    boolean NOT NULL DEFAULT false,
    is_sex_hormone       boolean NOT NULL DEFAULT false,
    is_antiinfective     boolean NOT NULL DEFAULT false,
    atc_codes            text[],                    -- WHO ATC (enrichment)
    class_labels         text
);
CREATE INDEX ingredients_base_idx ON ingredients (base);
CREATE INDEX ingredients_name_trgm ON ingredients USING gin (name gin_trgm_ops);

-- ---------------------------------------------------------------- compositions (exact-equivalence groups)
CREATE TABLE compositions (
    composition_id   text PRIMARY KEY,              -- 'c_' + sha1(composition_key)[:16]
    composition_key  text NOT NULL UNIQUE,          -- 'amoxicillin:500mg|clavulanic acid:125mg#tablet#IR'
    composition      text NOT NULL,                 -- human readable
    form             text NOT NULL,
    release          text NOT NULL,
    n_products       int  NOT NULL
);

CREATE TABLE composition_ingredients (
    composition_id   text NOT NULL REFERENCES compositions ON DELETE CASCADE,
    ingredient_id    int  NOT NULL REFERENCES ingredients,
    strength_value   double precision,
    strength_unit    text,
    PRIMARY KEY (composition_id, ingredient_id)
);
CREATE INDEX composition_ingredients_ing_idx ON composition_ingredients (ingredient_id);

-- ---------------------------------------------------------------- products
CREATE TABLE products (
    product_id          text PRIMARY KEY,
    canonical_id        text NOT NULL,              -- = product_id unless this is an alias listing
    is_alias            boolean NOT NULL,
    key                 text NOT NULL,              -- normalised name (join key)
    name                text NOT NULL,
    manufacturer        text,
    form                text NOT NULL,
    release             text NOT NULL,
    composition         text,
    composition_raw     text,
    composition_id      text,                       -- NULL when not substitutable / strengths incomplete
    composition_key     text,
    composition_source  text,
    composition_status  text NOT NULL,              -- verified | single_source | conflict | truncation_risk | missing
    composition_votes   int,
    n_components        int,
    ingredients         text[],
    substitutable       boolean NOT NULL,
    discontinued        boolean,
    therapeutic_class   text,
    action_class        text,
    chemical_class      text,
    sub_category        text,
    habit_forming       boolean,
    url_1mg             text,
    url_apollo          text,
    url_netmeds         text,
    image_url           text,
    rating_count        double precision,
    popularity          double precision,
    search_text         text,
    stem                text
);
CREATE INDEX products_canonical_idx   ON products (canonical_id);
CREATE INDEX products_composition_idx ON products (composition_id) WHERE substitutable;
CREATE INDEX products_key_idx         ON products (key);
CREATE INDEX products_stem_idx        ON products (stem);
CREATE INDEX products_search_trgm     ON products USING gin (search_text gin_trgm_ops);
CREATE INDEX products_ingredients_gin ON products USING gin (ingredients);

-- ---------------------------------------------------------------- safety (Prescription Guard data)
CREATE TABLE product_safety (
    product_id             text PRIMARY KEY REFERENCES products ON DELETE CASCADE,
    category               text NOT NULL,           -- banned | controlled | schedule_x | schedule_h1 | schedule_h
                                                    -- | prescription | otc_unverified | otc
    requires_prescription  boolean NOT NULL,
    reasons                text,
    legal_refs             text
);
CREATE INDEX product_safety_category_idx ON product_safety (category);

CREATE TABLE rx_flags (                             -- independent "prescription required" labels, for cross-checks
    product_id   text NOT NULL REFERENCES products ON DELETE CASCADE,
    source       text NOT NULL,
    rx_required  boolean NOT NULL,
    PRIMARY KEY (product_id, source)
);

CREATE TABLE banned_entries (
    list          text NOT NULL,                    -- cdsco_2021 | gazette_2023 | gazette_2024
    serial        int  NOT NULL,
    text          text NOT NULL,
    notification  text,
    dated         text,
    status        text NOT NULL,                    -- prohibited | quashed_by_court | under_examination_pre1988 | ...
    form          text,
    strengths     text,
    source        text,
    PRIMARY KEY (list, serial)
);

CREATE TABLE schedule_entries (
    schedule   text NOT NULL,                       -- H | H1 | X
    serial     int  NOT NULL,
    substance  text NOT NULL,
    raw        text,
    PRIMARY KEY (schedule, serial)
);

-- ---------------------------------------------------------------- prices
CREATE TABLE price_observations (
    id                  bigserial PRIMARY KEY,
    product_id          text NOT NULL REFERENCES products ON DELETE CASCADE,
    source              text NOT NULL,
    platform            text NOT NULL,              -- 1mg | apollo | netmeds | pharmeasy
    observed            text NOT NULL,              -- YYYY-MM (live fetches later: full timestamp in fetched_at)
    fetched_at          timestamptz,
    price_inr           numeric(12,2) NOT NULL,
    mrp_inr             numeric(12,2),
    pack_label          text,
    pack_quantity       double precision,
    pack_unit           text,
    price_per_unit_inr  double precision,
    url                 text,
    is_outlier          boolean NOT NULL DEFAULT false
);
CREATE INDEX price_obs_product_idx ON price_observations (product_id, platform, observed DESC);

-- latest usable observation per product and platform. Materialised (DISTINCT ON over ~1M rows is ~1 s);
-- refreshed by db/load.py and after live price fetches: REFRESH MATERIALIZED VIEW CONCURRENTLY latest_prices
CREATE MATERIALIZED VIEW latest_prices AS
SELECT DISTINCT ON (product_id, platform) *
FROM price_observations
WHERE NOT is_outlier AND platform <> 'reference'
ORDER BY product_id, platform, coalesce(fetched_at, to_timestamp(observed, 'YYYY-MM')) DESC, id DESC
WITH NO DATA;
CREATE UNIQUE INDEX latest_prices_pk ON latest_prices (product_id, platform);
CREATE INDEX latest_prices_ppu_idx ON latest_prices (product_id, price_per_unit_inr);

CREATE TABLE jan_aushadhi (
    drug_code            int PRIMARY KEY,
    generic_name         text NOT NULL,
    product_group        text,
    unit_size            text,
    mrp_inr              numeric(12,2),
    pack_quantity        double precision,
    pack_unit            text,
    price_per_unit_inr   double precision,
    composition          text,
    form                 text,
    release              text,
    composition_key      text,
    composition_id       text,
    is_drug              boolean,
    usable               boolean,
    matches_catalog      boolean
);
CREATE INDEX jan_aushadhi_composition_idx ON jan_aushadhi (composition_id) WHERE usable;

CREATE TABLE nppa_ceiling (
    id                 serial PRIMARY KEY,
    medicine           text,
    dosage             text,
    unit               text,
    ceiling_price_inr  numeric(12,2) NOT NULL,
    per                text NOT NULL,               -- unit | ml | g
    composition        text,
    form               text,
    release            text,
    composition_key    text,
    composition_id     text,
    source             text,
    status             text NOT NULL,               -- current (drives the flag) | historical (reference only)
    so_number          text,
    notified           text,
    matches_catalog    boolean
);
CREATE INDEX nppa_ceiling_composition_idx ON nppa_ceiling (composition_id) WHERE status = 'current';

-- ---------------------------------------------------------------- enrichment (filled by db/enrich_*.py)
CREATE TABLE product_info (                         -- 1mg-style monograph text per product
    product_id     text NOT NULL REFERENCES products ON DELETE CASCADE,
    source         text NOT NULL,
    introduction   text,
    uses           text,
    benefits       text,
    side_effects   text,
    how_to_use     text,
    how_it_works   text,
    quick_tips     text,
    safety_advice  jsonb,                           -- {"alcohol": "...", "pregnancy": "...", ...}
    PRIMARY KEY (product_id, source)
);

CREATE TABLE interactions (                         -- drug-drug interactions between ingredients
    ingredient_a  int  NOT NULL REFERENCES ingredients,
    ingredient_b  int  NOT NULL REFERENCES ingredients,
    severity      text NOT NULL,                    -- Major | Moderate | Minor | Unknown
    source        text NOT NULL,
    PRIMARY KEY (ingredient_a, ingredient_b, source),
    CHECK (ingredient_a < ingredient_b)
);

CREATE TABLE ingredient_side_effects (
    ingredient_id  int  NOT NULL REFERENCES ingredients,
    side_effect    text NOT NULL,
    frequency      text,                            -- e.g. 'common', '1%-10%', from SIDER when known
    source         text NOT NULL,
    PRIMARY KEY (ingredient_id, side_effect, source)
);

CREATE TABLE kendras (                              -- Jan Aushadhi Kendras (store locator)
    kendra_code  text PRIMARY KEY,
    name         text,
    state        text,
    district     text,
    pincode      text,
    address      text,
    lat          double precision,
    lon          double precision,
    source       text
);
CREATE INDEX kendras_pincode_idx ON kendras (pincode);

CREATE TABLE evidence_chunks (                      -- grounded health-assistant retrieval (Phase 10)
    id           bigserial PRIMARY KEY,
    scope        text NOT NULL,                     -- 'ingredient' | 'product' | 'composition'
    ref_id       text NOT NULL,
    section      text NOT NULL,                     -- uses | side_effects | how_to_use | warnings | interactions ...
    text         text NOT NULL,
    source       text NOT NULL,
    embedding    vector(384)
);
CREATE INDEX evidence_chunks_ref_idx ON evidence_chunks (scope, ref_id, section);
