"""Reply snapshot: every turn's full response_text, so a refactor can prove it changed nothing (Phase 11).

  .venv/bin/python eval/snapshot.py --save  eval/snapshots/phase11_baseline.jsonl
  .venv/bin/python eval/snapshot.py --check eval/snapshots/phase11_baseline.jsonl

Why this exists: Phase 11 moves reply assembly into cards + a narrator. With the narrator's LLM lead off, the text
must stay byte-identical. Two things would make the text change for reasons unrelated to the code, so both are
pinned here:
  - price cache expiry: cached live prices are "fresh" for 6 h; after that the engine falls back to dated
    snapshots (different prices). The cache is treated as fresh for the whole run.
  - freshness labels: "checked 2 h ago" depends on the clock -> normalised to "checked <age>".
The scorecard of the same run is printed and saved next to the snapshot (…jsonl -> …scorecard.json).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
from eval.run import load_cases, run, scorecard  # noqa: E402

AGE = re.compile(r"checked (just now|\d+ h ago)")


def normalise(text: str) -> str:
    return AGE.sub("checked <age>", text or "")


class Recorder:
    """Wraps a bot and keeps every full reply (eval.run keeps only the first 300 characters)."""

    def __init__(self, bot):
        self.bot, self.rows, self.case_id, self.turn = bot, [], None, 0

    def start_session(self):
        return self.bot.start_session()

    def acknowledge(self, sid):
        return self.bot.acknowledge(sid)

    def query(self, sid, text):
        resp = self.bot.query(sid, text)
        self.rows.append({"text": text, "response_text": normalise(resp.get("response_text"))})
        return resp


def pin_prices() -> None:
    from medibot.prices import engine
    engine.CACHE_TTL = 10 ** 9


def collect(cases: list[dict]) -> tuple[list[dict], dict]:
    pin_prices()
    from medibot.assistant import Assistant
    rec = Recorder(Assistant())
    out = run(rec, cases)
    sc = scorecard(cases, out)
    ids = [(c["id"], i) for c in cases for i in range(len(c["turns"]))]
    if len(ids) != len(rec.rows):  # a crashed case records fewer turns; keep alignment honest
        raise SystemExit(f"turn count mismatch: {len(ids)} expected, {len(rec.rows)} recorded (errors: {sc['errors']})")
    rows = [{"id": cid, "turn": i, **r} for (cid, i), r in zip(ids, rec.rows)]
    return rows, sc


def summary(sc: dict) -> dict:
    keep = ["A1_block_rate", "A2_false_positive_rate", "A3_disclaimer_rate", "B1_avg_savings_pct",
            "B3_alternative_quality", "C1_resolution_rate", "C2_multi_turn_rate", "health_grounded_answer_rate",
            "uncited_answers", "violations_diagnosis_or_dosing", "errors", "score_measurable"]
    return {k: sc[k] for k in keep}


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--save")
    g.add_argument("--check")
    a = ap.parse_args()
    cases = load_cases()
    rows, sc = collect(cases)
    mode = {"MEDIBOT_LLM": os.environ.get("MEDIBOT_LLM", "on"),
            "MEDIBOT_LIVE_PRICES": os.environ.get("MEDIBOT_LIVE_PRICES", "off")}
    print(json.dumps({"mode": mode, **summary(sc)}, indent=1))
    if a.save:
        p = ROOT / a.save
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        p.with_suffix(".scorecard.json").write_text(json.dumps({"mode": mode, **summary(sc)}, indent=1))
        print(f"saved {len(rows)} turns -> {p.relative_to(ROOT)}")
        return
    base = [json.loads(line) for line in (ROOT / a.check).read_text().splitlines()]
    want = {(b["id"], b["turn"]): b for b in base}
    diffs = [(r, want.get((r["id"], r["turn"]))) for r in rows
             if want.get((r["id"], r["turn"]), {}).get("response_text") != r["response_text"]]
    print(f"{len(rows) - len(diffs)}/{len(rows)} turns identical to {a.check}")
    for r, b in diffs[:10]:
        print(f"--- {r['id']}#{r['turn']}: {r['text']}\n  before: {(b or {}).get('response_text', '<missing>')[:400]!r}"
              f"\n  after:  {r['response_text'][:400]!r}")
    sys.exit(1 if diffs else 0)


if __name__ == "__main__":
    main()
