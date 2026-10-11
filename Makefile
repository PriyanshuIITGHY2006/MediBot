PY := .venv/bin/python

.PHONY: data data-test schedules

## Rebuild the processed catalog from data/raw (≈2 min)
data: schedules
	$(PY) data/pipeline/build_catalog.py > /dev/null
	$(PY) data/pipeline/jan_aushadhi.py
	$(PY) data/pipeline/search_index.py
	$(PY) data/pipeline/nppa.py
	$(PY) data/pipeline/banned.py
	$(PY) data/pipeline/safety.py
	$(MAKE) data-test

schedules:
	$(PY) data/pipeline/extract_schedules.py

## Normaliser unit tests + catalog acceptance tests (golden pairs, search top-1)
data-test:
	cd data/pipeline && ../../$(PY) -m pytest -q

.PHONY: db db-test

## Recreate the PostgreSQL database from data/processed + enrichments (needs DATABASE_URL in .env)
db:
	$(PY) db/load.py
	$(PY) db/enrich_info.py
	$(PY) db/enrich_clinical.py
	$(PY) db/enrich_kendras.py
	$(PY) db/enrich_images.py
	$(MAKE) evidence
	$(MAKE) db-test

db-test:
	$(PY) -m pytest -q db/test_db.py

.PHONY: eval-cases eval eval-test

## Build the evaluation set (eval/cases/*.jsonl) and run it: make eval BOT=eval.baselines:NullBot
eval-cases:
	$(PY) eval/build_cases.py

BOT ?= medibot.assistant:Assistant
ARGS ?=
eval:
	PYTHONPATH=backend $(PY) eval/run.py --bot $(BOT) $(ARGS)

## Phase 11: replies must stay byte-identical with the LLM off (cards + template narrator refactor guard)
eval-snapshot:
	MEDIBOT_LLM=off $(PY) eval/snapshot.py --check eval/snapshots/phase11_baseline_llm_off.jsonl

## Phase 11: the same stratified turns with the LLM off and on (background; cached; quota-guarded)
eval-llm-compare:
	MEDIBOT_LLM=off PYTHONPATH=backend $(PY) eval/run.py --bot $(BOT) --sample stratified --tag llm-off
	MEDIBOT_LLM=on PYTHONPATH=backend $(PY) eval/run.py --bot $(BOT) --sample stratified --tag llm-on --pace 5

eval-test:
	$(PY) -m pytest -q eval/test_eval.py

.PHONY: kernel-test
## Safety Kernel unit tests
kernel-test:
	cd backend && ../$(PY) -m pytest -q tests

.PHONY: prices-refresh prices-audit
## Live price cache for the most-asked products (polite: 1 req/s per pharmacy) and the B2 accuracy audit
prices-refresh:
	PYTHONPATH=backend $(PY) -m medibot.prices.refresh refresh --top 300

prices-audit:
	PYTHONPATH=backend $(PY) -m medibot.prices.refresh audit --sample 40

## Phase 10 evidence index: openFDA label sections + monographs + SIDER + FAQ, embedded locally (memory-capped)
evidence:
	$(PY) data/pipeline/openfda.py
	systemd-run --user --scope -q -p MemoryMax=6G $(PY) db/build_evidence.py

## Reload only the hand-written passages (health_faq.jsonl + label_passages.jsonl) — seconds, no full rebuild
evidence-curated:
	systemd-run --user --scope -q -p MemoryMax=3G $(PY) db/build_evidence.py --curated
