"""Extract Schedule H, H1 and X substance lists from the CDSCO Drugs and Cosmetics Rules PDF.

Input:  data/raw/regulatory/2016DrugsandCosmeticsAct1940Rules1945.pdf
Output: data/interim/regulatory/schedule_{h,h1,x}.csv  (columns: schedule, serial, substance, raw)

Requires `pdftotext` (poppler). The PDF layout prints Schedule H in two numbered columns,
H1 in two unnumbered columns and X as one name per line, so each has its own parser.
"""
import csv
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "data/raw/regulatory/2016DrugsandCosmeticsAct1940Rules1945.pdf"
OUT = ROOT / "data/interim/regulatory"

# Footnote/page furniture lines that sit inside the schedule pages.
NOISE = re.compile(
    r"(Subs\.|Omitted by|Omited|Ins\. by|Drugs and Cosmetics Rules|^\s*\d+\s*$|See Rules|PRESCRIPTION DRUGS)",
    re.I,
)


def pdf_text() -> list[str]:
    out = subprocess.run(["pdftotext", "-layout", str(PDF), "-"], capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def section(lines: list[str], start_pat: str, end_pat: str) -> list[str]:
    start = next(i for i, l in enumerate(lines) if re.search(start_pat, l))
    end = next(i for i in range(start + 1, len(lines)) if re.search(end_pat, lines[i]))
    return lines[start + 1 : end]


def clean(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("[", "").replace("]", "")).strip(" .,")


H_COLUMN_SPLIT = 35  # character offset separating the two printed columns of Schedule H


def parse_h(lines: list[str]) -> list[dict]:
    """Column-aware parse: a name may wrap onto the next line ("(acth)") or, for entries later
    moved to H1, sit two lines below an empty serial ("360." ... "[Nitrazepam]")."""
    rows: dict[int, str] = {}
    current: dict[int, int] = {}  # column -> serial whose name text is being collected
    for line in lines:
        if NOISE.search(line):
            continue
        for m in re.finditer(r"\S+(?: {1,2}\S+)*", line):
            token, col = m.group(), int(m.start() >= H_COLUMN_SPLIT)
            if re.fullmatch(r"\d+", token):  # footnote superscript
                continue
            serial = re.fullmatch(r"(\d{1,3})\.", token)
            if serial and 1 <= int(serial.group(1)) <= 536:
                current[col] = int(serial.group(1))
                rows.setdefault(current[col], "")
            elif col in current:
                rows[current[col]] = f"{rows[current[col]]} {token}".strip()
    return [
        {"schedule": "H", "serial": s, "substance": clean(n), "raw": n}
        for s, n in sorted(rows.items())
    ]


def parse_columns(lines: list[str], schedule: str) -> list[dict]:
    names = []
    for line in lines:
        if line.strip().startswith("Note") or "Preparations" in line or "topical" in line:
            break
        if NOISE.search(line) or not line.strip() or line.strip() in {"[***]"}:
            continue
        for part in re.split(r"\s{3,}", line.strip()):
            if re.fullmatch(r"\d+", part) or part == "[***]":
                continue
            names.append(part)
    return [
        {"schedule": schedule, "serial": i + 1, "substance": clean(n), "raw": n}
        for i, n in enumerate(names)
    ]


def main() -> int:
    lines = pdf_text()
    h = parse_h(section(lines, r"\[SCHEDULE - H\s*$", r"^\s*Note:- 1\. Preparations exempted"))
    h1 = parse_columns(section(lines, r"^\s*\[SCHEDULE H1\s*$", r"^\s*Note:- Preparations containing"), "H1")
    x = parse_columns(section(lines, r"^\s*\[SCHEDULE X\s*$", r"^\s*Note: 1\. Any stereoisometric"), "X")

    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in {"schedule_h": h, "schedule_h1": h1, "schedule_x": x}.items():
        with open(OUT / f"{name}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["schedule", "serial", "substance", "raw"])
            w.writeheader()
            w.writerows(rows)
        print(f"{name}: {len(rows)} rows")

    missing = sorted(set(range(1, 537)) - {r["serial"] for r in h})
    if missing:
        print(f"WARNING: Schedule H serials missing: {missing}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
