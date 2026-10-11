# MediBot Price Engine (Phase 9)

Code: `backend/medibot/prices/` — `adapters.py` (per-pharmacy parsers + polite fetcher), `engine.py`
(live → cache → snapshot, NPPA flag), `refresh.py` (background refresh + B2 accuracy audit).

## Where prices come from

| Order | Source | Freshness label | When |
|---|---|---|---|
| 1 | **Cache** (`data/interim/price_cache.sqlite`) | "checked N h ago" | a live quote younger than 6 h exists |
| 2 | **Live product page** (1mg, Apollo, Netmeds) | "live now" | `MEDIBOT_LIVE_PRICES=on`; the reply waits at most 2.5 s (`MEDIBOT_LIVE_BUDGET`), slower fetches finish in the background and warm the cache |
| 3 | **Dated snapshot** (dataset prices) | "as of 2025-03" | nothing fresher exists |

Every quote carries platform, pack price, MRP (when shown), pack size, **price per unit**, stock status, URL,
and its source/time. Prices are compared **per tablet / ml / g**, never per pack.

## What is fetched — and what is not

robots.txt was checked on 2026-10-10 for all four pharmacies:

| Site | Fetched | Never requested |
|---|---|---|
| 1mg | product pages (`/drugs/...`) | `/search`, cart, checkout, interaction checker |
| Apollo | product pages (`/medicine/...`, `/otc/...`) | `/search/`, `/medicine/search-medicines/`, cart, account |
| Netmeds | product pages (redirects to `/product/...` followed) | `/search`, `/api/` (except `/api/service/`), cart |
| PharmEasy | product pages (`/online-medicine-order/...`, `/health-care/products/...`); URLs from its sitemaps | `/search/all*`, `/api/`, cart, account, offers, `/healthcare` |
| Truemeds | product pages (`/medicine/...`, `/otc/...`); URLs from its sitemaps | `/search`, `/api/*`, cart, login, profile |

The fetcher only accepts product-page URLs on these hosts (search / api / cart URLs are refused before any
request), identifies itself (`MediBotPriceCheck/0.1`), spaces requests ≥ 1 s per host, and caches for 6 h.
**The pharmacies' terms of use generally prohibit automated collection**: this is a low-volume hackathon
prototype; a production version needs partner APIs / data agreements. Delisted products (HTTP 404) are recorded.

## Parsing (tested on real page snippets in `backend/tests/fixtures/`)

| Site | Price | Pack | Stock |
|---|---|---|---|
| 1mg | `__INITIAL_STATE__ → drugPageReducer.dynamicData.priceBox` (selling price, MRP) — *not* the substitutes block | `priceData.sellingQuantity` | `priceData.isSkuInStock` |
| Apollo | schema.org `Offer` inside Next.js flight data | first `"mou"` (measure of unit) | `availability` |
| Netmeds | JSON-LD `Drug.offers.price` | from the name ("10's", "15gm") | `availability` |
| PharmEasy | Rx pages: Next.js `productDetails.salePrice` / `costPrice` (MRP); OTC pages: the page's **own** schema.org offer (offer url = page url) with its MRP price specification | `measurementUnit` ("10 Tablet(s) in Strip") / name | `productAvailabilityFlags.isAvailable` / offer availability |
| Truemeds | Next.js `currentMed.product.sellingPrice` / `mrp` (substitutes are separate) | `packSize` | `available` |

Example (live, 2026-10-10) — Augmentin 625 Duo, strip of 10: **Netmeds ₹166.08 (₹16.61/tab)**,
1mg ₹183.00 (₹18.30), Apollo ₹196.50 (₹19.65), all in stock.

## PharmEasy and Truemeds (9.7): URLs from sitemaps, every match verified

- **robots.txt** (re-read 2026-10-11): PharmEasy's `Disallow: /` group is for `EtaoSpider`, not for `*`; product pages
  are allowed for us. Truemeds has one `*` group; `/medicine/` and `/otc/` are allowed.
- **Three guards on every request** (`adapters.allowed_url` + `RobotsGuard`): the exact host (the old substring test
  let `evil.com/pharmeasy.in` through), a per-site allow-list of product paths, and the site's own robots.txt for
  our user agent, read at most once a day. If robots.txt can't be read, nothing is fetched from that host.
  Path rules match whole segments, so `/cart` no longer blocks `/drugs/cartigen-duo-tablet`, an old bug.
- **No search:** `data/pipeline/pharmacy_urls.py` reads the published sitemaps (PharmEasy: 7 OTC + 29 prescription
  files; Truemeds: 22 English medicine files) and keeps 432,502 product URLs (PharmEasy 220,965, Truemeds 211,537).
- **Exact matching** (`prices/matching.py`): slug, page name and catalog name reduce to the same key (brand words +
  strength + form; tab = tablet, 650mg = 650, pack counts and volumes dropped). A key shared by products with
  different compositions is dropped. **136,992 matches** (PharmEasy 65,928, Truemeds 77,291). Top-300 coverage:
  1mg 291, Apollo 199, PharmEasy 115, Netmeds 112, Truemeds 54.
- **Every fetched page is verified** (`engine.page_matches`): the page's own product name must give the same key, and
  every active ingredient the page lists must be in our composition. Otherwise the quote is not shown. On the top-300
  refresh, 108/115 PharmEasy and 51/54 Truemeds pages were verified. The rejected ones were real differences (e.g.
  Mixderm lists miconazole where our catalog has clotrimazole) or pages with too little detail. A wrong product's
  price is never shown.

## Substitutes use live prices

The substitute list is ranked from dated prices, then the target and the top 3 suggestions are re-priced live
in **one shared wait**; savings are computed against the **cheapest current** price of the original
(conservative). Augmentin 625 → Imclav: ₹16.61 → ₹4.74 per tablet live (72% cheaper).

## NPPA ceiling flag

Only on live / cached prices, per unit, against the **highest** current NLEM 2022 ceiling for that composition.
Never on dataset snapshots (they predate the 2022 ceilings — see DATA_QUALITY.md).

## Price-match accuracy (rubric B2) — `make prices-audit`

The audit samples popular products and compares the price the bot **would show** with a fresh live fetch of
the same page (≤ 1% difference = match, like-for-like only: per unit vs per unit or same pack vs same pack).

| Run | What the bot showed | Accuracy |
|---|---|---|
| Baseline (no live engine) | dataset snapshot (2025-03) | **0%** — median difference 89% |
| With live engine (cache refreshed by `make prices-refresh`, 2026-10-10) | cached live quotes (< 6 h) | **100%** — 70/70 pairs on 1mg, Apollo, Netmeds |
| 5 pharmacies (refresh 2026-10-11: 771 pages, 714 fetched, 4.9 min; audit 60 products) | cached live quotes | **100%** — 128/128 pairs; 1mg, Apollo, Netmeds, PharmEasy, Truemeds each 100% |

Refresh run: top 300 products, 602 product pages, 545 fetched (91%), 57 failed (mostly products delisted by the
pharmacy, HTTP 404), 5.4 min at ≤ 1 request/s per site. Caveat: accuracy reflects prices kept fresh (6 h cache +
on-demand live fetch); with a stale cache it falls back towards the snapshot baseline.

Lesson for the deck: dataset prices are not usable for price comparison; the live engine is what makes B2 possible.
