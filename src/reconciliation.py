"""Reconcile the Gold layer against CONTROL_TOTALS.txt.

The figures are computed ONLY by functions in src/metrics/definitions.py.
If a figure does not tie, this prints it and exits with 1. Never adjust a number to fit.

Run:  python -m src.reconciliation
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import duckdb

from src.metrics import definitions as m
from src.pipeline.bronze import DB_PATH, RAW_DIR

CONTROL_FILE = RAW_DIR / "CONTROL_TOTALS.txt"
_LINE = re.compile(r"^(\d)\.\s+(.*?)\s+\.{3,}\s+([\d,\.]+)\s*$")


def read_controls(path: Path = CONTROL_FILE) -> dict[int, dict]:
    """Parse the five control figures out of CONTROL_TOTALS.txt (the single source of truth)."""
    controls = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _LINE.match(line.strip())
        if match:
            number, name, value = match.groups()
            controls[int(number)] = {"name": name, "expected": float(value.replace(",", ""))}
    return controls


def compute(con: duckdb.DuckDBPyConnection) -> dict[int, float | None]:
    everything = m.Scope.everything()
    return {
        1: m.unique_people(con, everything),
        2: m.applications_at_stage(con, "Offer", date(2026, 3, 31), everything),
        3: m.time_to_hire_days(con, date(2026, 1, 1), date(2026, 6, 30), everything)["median_days"],
        4: m.offered_salary_total(con, "Engineering", everything),
        5: m.offer_acceptance_rate(con, everything)["rate_pct"],
    }


def compare(db_path: Path = DB_PATH) -> list[dict]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        actual = compute(con)
    finally:
        con.close()
    rows = []
    for number, control in sorted(read_controls().items()):
        value = actual[number]
        rows.append(
            {
                "number": number,
                "name": control["name"],
                "control": control["expected"],
                "actual": value,
                "ties": value is not None and abs(value - control["expected"]) < 1e-9,
            }
        )
    return rows


if __name__ == "__main__":
    rows = compare()
    for r in rows:
        mark = "TIES" if r["ties"] else "DOES NOT TIE"
        print(f"{r['number']}. {r['name'][:48]:<48} control {r['control']:>15,.1f}  mine {r['actual']:>15,.1f}  {mark}")
    sys.exit(0 if all(r["ties"] for r in rows) else 1)
