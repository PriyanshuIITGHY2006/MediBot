"""Consolidate India's prohibited drugs / FDCs (Section 26A) into one table with legal status.

Inputs:
  data/raw/regulatory/cspc_banned_drugs_india_2023.pdf   itemised CDSCO list "as on 22.11.2021" (1983-2021)
  data/reference/banned_fdc_2023.csv                     14 FDCs, S.O. 2394-2407(E), 02.06.2023
  data/interim/regulatory/banned_fdc_2024.csv            156 FDCs, S.O. 3285-3440(E), Aug 2024
Output: data/interim/regulatory/banned_all.csv

Status matters: CDSCO footnotes mark entries that are stayed (1#), revoked with conditions (2#),
pre-1988 FDCs under examination (3#, 4#) or quashed by a High Court (5#). Only status
"prohibited" may be presented to users as banned. Example: Paracetamol + Phenylephrine + Caffeine
is in the 2016 list but marked 3# and was not part of the 2023 ban, so it is NOT reported as banned.
"""
from __future__ import annotations

import csv
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw/regulatory"
REF = ROOT / "data/reference"
OUT = ROOT / "data/interim/regulatory"

STATUS = {
    "1": "stayed_by_court",
    "2": "revoked_with_conditions",
    "3": "under_examination_pre1988",
    "4": "under_examination_pre1988",
    "5": "quashed_by_court",
}
_ENTRY = re.compile(r"^\s{0,6}(\d{1,3})\.(?:\s+|$)(.*)$")
_MARKER = re.compile(r"^\s*(\d)#\s*(.*)$")
_NOTIF = re.compile(r"(G\.?S\.?R\.?|S\.\s?[O0]\.?)\s*(?:No\.?\s*)?(\d{2,4})\s*\(E\)", re.I)
_DATE = re.compile(r"(\d{1,2})[.\-](\d{1,2})[.\-]\s*(\d{4})")
# Status text that appears inside the notification column instead of a footnote marker.
_INLINE_STATUS = [
    (re.compile(r"revoked", re.I), "revoked_with_conditions"),
    (re.compile(r"suspension", re.I), "suspended_then_revoked"),
]


def _split(line: str) -> tuple[str, str]:
    """Left column (drug text) vs right column (notification), split at the first wide gap past col 55."""
    for m in re.finditer(r"\s{5,}", line):
        if m.end() >= 55:
            return line[: m.start()], line[m.end():]
    return (line, "") if len(line.rstrip()) < 75 else (line[:62], line[62:])


def parse_cspc() -> list[dict]:
    text = subprocess.run(["pdftotext", "-layout", str(RAW / "cspc_banned_drugs_india_2023.pdf"), "-"],
                          capture_output=True, text=True, check=True).stdout
    body = text.split("1# Presently stayed")[0]  # footnote legend starts here
    entries: list[dict] = []
    cur = None
    for raw in body.splitlines():
        if not raw.strip() or re.search(r"LIST OF DRUGS PROHIBITED|GAZETTE NOTIFICATIONS|THEIR PRESENT STATUS|"
                                        r"Sr\. No\.|Notification\s*$|No\. & Date|^\s*\d+\s*$", raw):
            continue
        marker = _MARKER.match(raw)
        if marker and cur:
            cur["markers"].add(marker[1])
            raw = " " * 6 + marker[2]
        left, right = _split(raw)
        m = _ENTRY.match(left)
        if m and (not cur or int(m[1]) == cur["serial"] + 1):
            cur = {"serial": int(m[1]), "text": m[2].strip(), "notif": right.strip(), "markers": set()}
            entries.append(cur)
        elif cur:
            cur["text"] += " " + left.strip()
            cur["notif"] += " " + right.strip()
    rows = []
    for e in entries:
        text = re.sub(r"\bDated\S*|\b\d{1,2}\.\d{1,2}(?:\.\s?\d{4})?\b|^\d\s+", " ", e["text"])  # date fragments
        text = re.sub(r"\s+", " ", text).strip(" .")
        notif = re.sub(r"\s+", " ", e["notif"])
        status = "prohibited"
        if e["markers"]:
            status = STATUS[sorted(e["markers"])[0]]
        else:
            for rx, st in _INLINE_STATUS:
                if rx.search(notif):
                    status = st
                    break
        n = _NOTIF.search(notif)
        # dates wrap across lines in the PDF ("10.03.201" + "6"): join digit groups split by spaces
        d = _DATE.search(re.sub(r"(?<=[\d.])\s+(?=\d)", "", notif))
        rows.append({
            "list": "cdsco_2021", "serial": e["serial"], "text": text,
            "notification": f"{n[1].upper().replace('0', 'O') if n else ''} {n[2]}(E)".strip() if n else "",
            "dated": f"{int(d[1]):02d}.{int(d[2]):02d}.{d[3]}" if d else "",
            "status": status, "form": "", "strengths": "",
            "source": "CDSCO list of prohibited drugs (status as on 22.11.2021), CSPC copy",
        })
    return rows


def load_2023() -> list[dict]:
    with open(REF / "banned_fdc_2023.csv", newline="") as f:
        return [{"list": "gazette_2023", "serial": int(r["serial"]), "text": r["fdc"], "notification": r["notification"],
                 "dated": r["dated"], "status": "prohibited", "form": r["form"], "strengths": r["strengths"],
                 "source": r["source"]} for r in csv.DictReader(f)]


def load_2024() -> list[dict]:
    with open(OUT / "banned_fdc_2024.csv", newline="") as f:
        return [{"list": "gazette_2024", "serial": int(r["serial"]), "text": r["fdc"], "notification": r["notification"],
                 "dated": r["dated"], "status": "prohibited", "form": "", "strengths": "",
                 "source": r["source"]} for r in csv.DictReader(f)]


def apply_overrides(rows: list[dict]) -> list[dict]:
    """Reviewed manual status corrections (data/reference/banned_status_overrides.csv)."""
    with open(REF / "banned_status_overrides.csv", newline="") as f:
        fixes = {(r["list"], int(r["serial"])): r for r in csv.DictReader(f)}
    for r in rows:
        fix = fixes.get((r["list"], r["serial"]))
        if fix:
            r["status"] = fix["status"]
            r["source"] += f" | status override: {fix['reason']}"
    return rows


def build() -> dict:
    rows = apply_overrides(parse_cspc() + load_2023() + load_2024())
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "banned_all.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    return {"rows": len(rows), "by_list": dict(Counter(r["list"] for r in rows)),
            "by_status": dict(Counter(r["status"] for r in rows))}


if __name__ == "__main__":
    print(build())
