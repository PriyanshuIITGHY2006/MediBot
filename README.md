<div align="center">

<img src="web/public/brand/medibot-logo-animated.svg" alt="MediBot" width="520" />

### Pay less for the exact same medicine — safely.

An informational pharmacy assistant for India: live prices from five pharmacies, identical-composition
alternatives (including Jan Aushadhi), cited medicine information, and a prescription guard that follows Indian law.

<p>
  <a href="https://medibot-priyanshu.koreacentral.cloudapp.azure.com"><img alt="Live demo" src="https://img.shields.io/badge/Live_demo-open-0DA99E?style=for-the-badge&logo=googlechrome&logoColor=white" /></a>
  <a href="https://medibot-priyanshu.koreacentral.cloudapp.azure.com/docs"><img alt="API docs" src="https://img.shields.io/badge/API-docs-15384B?style=for-the-badge&logo=swagger&logoColor=white" /></a>
  <img alt="Rubric score" src="https://img.shields.io/badge/offline_rubric-80%2F80-19C6B4?style=for-the-badge" />
</p>

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python_3.14-3776AB?logo=python&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" />
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL_18_+_pgvector-4169E1?logo=postgresql&logoColor=white" />
  <img alt="React" src="https://img.shields.io/badge/React_19-20232A?logo=react&logoColor=61DAFB" />
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white" />
  <img alt="Tailwind CSS" src="https://img.shields.io/badge/Tailwind_CSS_4-06B6D4?logo=tailwindcss&logoColor=white" />
  <img alt="Vite" src="https://img.shields.io/badge/Vite-646CFF?logo=vite&logoColor=white" />
  <img alt="Docker" src="https://img.shields.io/badge/Docker_Compose-2496ED?logo=docker&logoColor=white" />
  <img alt="Caddy" src="https://img.shields.io/badge/Caddy-1F88C0?logo=caddy&logoColor=white" />
  <img alt="Azure" src="https://img.shields.io/badge/Azure-0078D4?logo=microsoftazure&logoColor=white" />
</p>

<img src="docs/screenshots/chat.png" alt="MediBot chat with the live medicine sheet" width="900" />

</div>

> [!IMPORTANT]
> MediBot is an informational tool. It does not diagnose medical conditions or prescribe medications.
> Always consult a qualified medical professional before taking any medication. Emergency: **112 / 108**.

---

## Contents

[Features](#features) · [Screenshots](#screenshots) · [How it works](#how-it-works) · [Architecture](#architecture) ·
[Safety](#safety) · [Data](#data) · [Evaluation](#evaluation) · [Getting started](#getting-started) ·
[API](#api) · [Deployment](#deployment) · [Project layout](#project-layout) · [Documentation](#documentation)

## Features

| | Feature | What it does |
|---|---|---|
| 💬 | **Chat** | Ask about any medicine — brand or generic, English, Hindi or Hinglish, typos welcome. Answers arrive as cards: prices, alternatives, information, interactions, stores. |
| 🔎 | **Search + medicine sheet** | `Ctrl/⌘ K` searches 570k products. A resizable side panel opens with composition, prices at five pharmacies, identical alternatives and an interaction check. |
| 🧾 | **Bill split** | Give a list and quantities; an exact planner finds the cheapest way to buy all of it across pharmacies in whole packs — vs the same brands, one pharmacy, and Jan Aushadhi. |
| 📷 | **Scan a bill or prescription** | Photo → medicine list. Read on the server with Tesseract and never stored; an opt-in AI reader handles handwriting. A misread strength is never matched to a different product. |
| 💊 | **My Cabinet** | Your regular medicines, kept only in your browser: monthly cost, cheapest identical option, refill dates with calendar (`.ics`) reminders, price-drop flags, interactions across everything. |
| 🪪 | **Pharmacist card** | Asked-for vs identical option side by side, quantities and Rx flags — share on WhatsApp, print, or let the pharmacist scan a QR (plain text, works offline). |
| 🇮🇳 | **Hindi** | Full interface and answers in Hindi. Safety texts are hand-written Hindi; any translated line that changes a number stays in English. |
| 📖 | **Wiki** | How MediBot works, its safety rules, data and API — inside the app. |

## Screenshots

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/home.png" alt="Start page" /><p align="center"><sub>Start page</sub></p></td>
    <td width="50%"><img src="docs/screenshots/bill-split.png" alt="Bill split" /><p align="center"><sub>Bill split — cheapest way across pharmacies</sub></p></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/pharmacist-card.png" alt="Pharmacist card" /><p align="center"><sub>Pharmacist card with QR</sub></p></td>
    <td><img src="docs/screenshots/cabinet.png" alt="My Cabinet" /><p align="center"><sub>My Cabinet — monthly cost and refills</sub></p></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/hindi.png" alt="Hindi interface" /><p align="center"><sub>Hindi interface</sub></p></td>
    <td><img src="docs/screenshots/wiki.png" alt="Wiki" /><p align="center"><sub>In-app wiki</sub></p></td>
  </tr>
</table>

## How it works

```mermaid
flowchart LR
  msg["Your message<br/><sub>any language, typos ok</sub>"] --> reader["Reader<br/><sub>medicines + intent</sub>"]
  reader --> kernel["Safety kernel<br/><sub>Rx · banned · emergency</sub>"]
  kernel --> facts["Facts<br/><sub>catalog · live prices · cited sources</sub>"]
  facts --> check["Output check<br/><sub>no dose, no diagnosis</sub>"]
  check --> reply["Reply<br/><sub>cards + citations · optional Hindi</sub>"]
  classDef safe fill:#ffe4e6,stroke:#e11d48,color:#881337
  classDef out fill:#ccfbf1,stroke:#0f766e,color:#134e4a
  class kernel,check safe
  class reply out
```

1. **Reader** — finds which medicines you mean (spelling fixes, Hinglish, follow-ups like *"the 500 one"*).
2. **Safety kernel** — decides *before* any fact is fetched: prescription medicines get the mandated prompt verbatim,
   banned ones a legal notice, emergencies the helplines first.
3. **Facts** — catalog, live prices and the evidence index. Health text is **copied from cited passages, never generated**.
4. **Output check** — any card that would read as a dose or a diagnosis is replaced with a fixed refusal.

An AI model may help read your message, translate the display into Hindi, or write a one-line lead-in — never the
medical facts or the safety texts.

## Architecture

```mermaid
flowchart TD
  user(("Medicine seeker"))
  ext(("Pharmacy sites<br/>1mg · Apollo · Netmeds<br/>PharmEasy · Truemeds"))
  ai(("LLM gateway<br/>optional"))

  subgraph web["Web app"]
    app["App shell<br/>App.tsx"]
    client["API client<br/>api.ts"]
    billui["Bill split + scan<br/>Bill.tsx"]
    cabui["My Cabinet<br/>Cabinet.tsx"]
    card["Pharmacist card<br/>PharmacistCard.tsx"]
    wiki["Wiki<br/>Wiki.tsx"]
    i18n["Hindi UI<br/>i18n.ts"]
  end

  subgraph api["HTTP API"]
    appy["App, rate limit, CORS<br/>app.py"]
    rchat["Chat + sessions<br/>routes_chat.py"]
    rmed["Search · sheet · cabinet<br/>routes_medicine.py"]
    rbill["Bill parse · plan · read<br/>routes_bill.py"]
  end

  subgraph core["Assistant and safety"]
    asst["Assistant<br/>assistant.py"]
    kernel["Safety kernel<br/>safety/kernel.py"]
    msgs["Fixed safety texts EN + HI<br/>messages.py · messages_hi.py"]
    health["Cited health answers<br/>health/answer.py"]
    ix["Interactions<br/>health/interactions.py"]
    tr["Hindi display<br/>translate.py"]
    llm["LLM client<br/>llm.py"]
  end

  subgraph cost["Prices, bills, cabinet"]
    price["Price engine<br/>prices/engine.py"]
    subs["Identical alternatives<br/>substitutes.py"]
    split["Bill split<br/>billsplit.py + billplan.py"]
    read["Photo reader<br/>billread.py"]
    cab["Cabinet check<br/>cabinet.py"]
  end

  subgraph data["Data"]
    cat[("Catalog in memory<br/>catalog.py · 570k products")]
    pg[("PostgreSQL + pgvector<br/>evidence · interactions")]
    pipe["Data pipeline<br/>data/pipeline/*"]
  end

  user --> app
  app --> billui & cabui & wiki & i18n
  billui --> card
  cabui --> card
  app & billui & cabui --> client
  client -.->|JSON over HTTPS| appy
  appy --> rchat & rmed & rbill
  rchat --> asst
  rchat --> tr
  rmed --> asst
  rmed --> cab
  rbill --> split
  rbill --> read
  asst --> kernel --> msgs
  asst --> health --> pg
  asst --> ix --> pg
  asst --> subs --> price
  asst --> llm
  tr --> msgs
  tr --> llm
  split --> subs
  cab --> subs
  cab --> ix
  read --> cat
  asst --> cat
  pipe --> cat
  pipe --> pg
  price -.->|product pages only| ext
  llm -.-> ai
  read -.->|opt-in, handwriting| ai

  classDef blue fill:#dbeafe,stroke:#2563eb,color:#172554
  classDef amber fill:#fef3c7,stroke:#d97706,color:#78350f
  classDef mint fill:#dcfce7,stroke:#16a34a,color:#14532d
  classDef indigo fill:#e0e7ff,stroke:#4f46e5,color:#312e81
  classDef rose fill:#ffe4e6,stroke:#e11d48,color:#881337
  class app,client,billui,cabui,card,wiki,i18n blue
  class appy,rchat,rmed,rbill amber
  class asst,kernel,msgs,health,ix,tr,llm mint
  class price,subs,split,read,cab indigo
  class cat,pg,pipe rose
```

## Safety

**Deny by default.** A product is OTC only if every ingredient is explicitly allowed for its route and strength.
Everything else needs a prescription, and MediBot says so first, word for word:

> This medication requires a valid prescription. Please consult your doctor.

| Category | Basis |
|---|---|
| Banned | In-force Section 26A prohibitions — CDSCO 2021 list, Gazette 2023 (14 FDCs), 2024 (156 FDCs) |
| Controlled / Schedule X | NDPS Act 1985, Drugs Rules Schedule X |
| Schedule H1 / H | Drugs Rules (46 / 536 entries) |
| Prescription | Not provably OTC: injectables, habit-forming, steroids, cough syrups, above OTC strength |
| OTC | Every ingredient on the sourced allowlist for this route, within its strength cap |

- **Emergencies** get 112 / 108 / Tele-MANAS 14416 before anything else.
- **No diagnosis, no prescribing, no doses** — fixed refusals, checked again on the way out.
- **Identical alternatives only**: same Composition ID = same ingredients, strengths, form and release. Never "similar".
- **Privacy**: anonymous sessions, no message text stored, photos never stored, cabinet kept in the browser,
  phone / email / Aadhaar / PAN removed before any text reaches an AI model.

Full policy: [`docs/SAFETY_POLICY.md`](docs/SAFETY_POLICY.md).

## Data

| | |
|---|---|
| **570,968** product listings | **37,785** exact compositions |
| **942,833** price observations | **208,446** graded interaction pairs (DDInter) |
| **21,286** Jan Aushadhi Kendras | **2,439** Jan Aushadhi generics |

Built from 26 public sources — Kaggle catalogs of 1mg, Apollo, Netmeds and PharmEasy; MID; SIDER; DDInter;
openFDA labels; Jan Aushadhi; CDSCO / Gazette notifications; NPPA ceiling prices — each listed with its licence in
[`docs/SOURCES.md`](docs/SOURCES.md). Live prices are read only from product pages allowed by each site's robots.txt,
at most one request per second per site, cached for 6 hours. Some sources are non-commercial (CC BY-NC-SA, SIDER,
DDInter): fine for this prototype, to be replaced for commercial use.

## Evaluation

An evaluation set of **631 cases (653 turns)** was built before the bot — policy medicines, *"without a
prescription"* requests, typos and Hinglish, diagnosis and dosing bait, emergencies, 20 prompt-injection attempts and
multi-turn conversations.

| Measure | Result |
|---|---|
| Restricted-drug block rate | **100%** |
| OTC false positives | 1.0% |
| Disclaimer shown | 100% |
| Average saving with identical alternatives | **76.9%** |
| Questions resolved | 98.5% |
| Multi-turn context kept | 100% |
| Diagnosis / dosing violations · uncited health answers | **0 · 0** |
| Score (measurable offline) | **80 / 80** |

Details: [`docs/EVAL.md`](docs/EVAL.md). Run it: `make eval-cases && make eval`.

## Getting started

**Requirements:** Python 3.14, Node 20+, PostgreSQL 18 with `pgvector` and `pg_trgm`, Tesseract (for photo scans).

```bash
git clone https://github.com/PriyanshuIITGHY2006/MediBot.git && cd MediBot

# backend
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cat > .env <<'ENV'
MEDIBOT_DB_PASSWORD=choose-a-password
DATABASE_URL=postgresql://medibot:choose-a-password@localhost:5432/medibot
ENV
sudo bash scripts/setup_postgres.sh          # creates the medibot role + database with pgvector, pg_trgm, unaccent

# data (raw sources go in data/raw — see docs/SOURCES.md)
make data                                    # build the processed catalog (~2 min)
make db                                      # load PostgreSQL + evidence index

# run
make api                                     # http://localhost:8000  (docs at /docs)
make web                                     # http://127.0.0.1:5173
```

Optional keys in `.env`: `GROQ_API_KEY` and/or `MEDIBOT_LLM2_API_KEY` (message reader, Hindi display, AI photo
reader). Everything works without them — `MEDIBOT_LLM=off` turns all AI help off.

Tests: `cd backend && ../.venv/bin/python -m pytest -q` (330 tests) · `make data-test` · `make db-test`.

## API

Interactive docs: [`/docs`](https://medibot-priyanshu.koreacentral.cloudapp.azure.com/docs) ·
[`/redoc`](https://medibot-priyanshu.koreacentral.cloudapp.azure.com/redoc) · reference: [`docs/API.md`](docs/API.md)

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/v1/medibot/query` | Ask a question → safety guard, detected medicine, cards, alternatives (`language`: `en` / `hi`) |
| `POST` | `/api/v1/session/start` · `/session/ack` | Anonymous session and disclaimer acknowledgement |
| `GET` | `/api/v1/search` | Medicine search |
| `GET` | `/api/v1/medicine/{id}` | Medicine sheet: composition, prices, alternatives, cited info |
| `POST` | `/api/v1/bill/plan` · `/bill/parse` · `/bill/read` | Cheapest split · parse a pasted list · read a photo |
| `POST` | `/api/v1/cabinet/check` | Monthly cost, cheapest identical option, interactions |
| `POST` | `/api/v1/feedback` | 1–5 rating |
| `DELETE` | `/api/v1/session/{id}` | Forget a session |

```bash
curl -s https://medibot-priyanshu.koreacentral.cloudapp.azure.com/api/v1/medibot/query \
  -H 'Content-Type: application/json' \
  -d '{"user_query": "Cheaper alternative to Augmentin 625 Duo", "disclaimer_acknowledged": true}'
```

## Deployment

One VM, Docker Compose: **Caddy** (automatic HTTPS, serves the web app) → **API** → **PostgreSQL + pgvector**.

```bash
bash deploy/azure_vm.sh                      # or create an Oracle Cloud VM with deploy/cloud-init-oracle.yml
cp deploy/.env.example deploy/.env           # DOMAIN, DB_PASSWORD, API keys
bash deploy/push.sh <host>                   # build web, dump DB, upload, restore, start
```

Guide: [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Project layout

```
backend/medibot/        assistant, safety kernel, prices, substitutes, bill split, photo reader, cabinet, Hindi
backend/medibot/api/    FastAPI app and routers
backend/tests/          330 tests
data/pipeline/          catalog build, normalisation, search index, schedules, banned list, NPPA
db/                     PostgreSQL schema, loaders, evidence index
eval/                   evaluation set, runner, scorecards
web/src/                React app (chat, bill split, cabinet, pharmacist card, wiki, i18n)
deploy/                 Dockerfile, Compose, Caddy, VM scripts
docs/                   policy, data, prices, health, eval, API and deploy docs
```

## Documentation

| Doc | |
|---|---|
| [`SAFETY_POLICY.md`](docs/SAFETY_POLICY.md) | Prescription guard rules and legal basis |
| [`SOURCES.md`](docs/SOURCES.md) | Every data source with licence and processing |
| [`DATABASE.md`](docs/DATABASE.md) | Schema and typical queries |
| [`PRICES.md`](docs/PRICES.md) | Price engine, robots.txt policy, accuracy audit |
| [`HEALTH.md`](docs/HEALTH.md) | Cited health answers and the evidence index |
| [`EVAL.md`](docs/EVAL.md) | Evaluation set and scorecard |
| [`API.md`](docs/API.md) | Endpoints and response shapes |
| [`DEPLOY.md`](docs/DEPLOY.md) | Hosting on one VM |

<div align="center">
<br/>
<img src="web/public/favicon.svg" width="40" alt="" />
<br/>
<sub>Built for Indian patients who deserve to know what their medicine really costs.<br/>
Not medical advice · Emergency 112 / 108 · Tele-MANAS 14416</sub>
</div>
