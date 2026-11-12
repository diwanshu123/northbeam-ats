import re
from datetime import date
from pathlib import Path

import duckdb
import pytest

from src import reconciliation
from src.metrics import definitions as m
from src.pipeline import bronze, gold, silver

ROOT = Path(__file__).resolve().parents[1]
H1 = (date(2026, 1, 1), date(2026, 6, 30))


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("warehouse") / "test.duckdb"
    bronze.run(path)
    silver.run(path)
    gold.run(path)
    return path


@pytest.fixture()
def con(db):
    connection = duckdb.connect(str(db), read_only=True)
    yield connection
    connection.close()


def all_req_ids(con):
    return [r[0] for r in con.execute("SELECT req_id FROM dim_requisition").fetchall()]


# ---------------------------------------------------------------- control totals

def test_five_control_totals_tie(db):
    rows = reconciliation.compare(db)
    assert [r["number"] for r in rows] == [1, 2, 3, 4, 5]
    failing = [(r["number"], r["control"], r["actual"]) for r in rows if not r["ties"]]
    assert failing == []


def test_controls_are_read_from_the_control_file():
    controls = reconciliation.read_controls()
    assert controls[1]["expected"] == 560
    assert controls[4]["expected"] == 200_700_000
    assert controls[5]["expected"] == 51.2


def test_acceptance_rounding_rule_is_half_to_even():
    # 164 / 320 is exactly 51.25. The control figure (51.2) only ties under round-half-to-even.
    assert m._pct(164, 320) == 51.2
    assert m._pct(0, 0) is None


# ---------------------------------------------------------------- scope (access) behaviour

def test_scoped_totals_add_up_to_the_unscoped_total(con):
    ids = all_req_ids(con)
    everything = m.Scope.everything()

    assert sum(m.hires(con, *H1, m.Scope.requisitions([i])) for i in ids) == m.hires(con, *H1, everything)
    assert sum(m.offered_salary_total(con, None, m.Scope.requisitions([i])) for i in ids) == \
        m.offered_salary_total(con, None, everything)
    assert sum(
        m.applications_at_stage(con, "Offer", date(2026, 3, 31), m.Scope.requisitions([i])) for i in ids
    ) == m.applications_at_stage(con, "Offer", date(2026, 3, 31), everything)


def test_an_empty_scope_sees_nothing(con):
    nothing = m.Scope.requisitions([])
    assert m.unique_people(con, nothing) == 0
    assert m.hires(con, *H1, nothing) == 0
    assert m.offered_salary_total(con, None, nothing) == 0
    assert m.applications_at_stage(con, "Offer", date(2026, 3, 31), nothing) == 0
    assert m.offer_acceptance_rate(con, nothing)["rate_pct"] is None
    assert m.time_to_hire_days(con, *H1, nothing)["median_days"] is None


def test_a_hiring_manager_scope_is_a_strict_subset(con):
    mine = [r[0] for r in con.execute(
        "SELECT req_id FROM dim_requisition WHERE hiring_manager_id = 'U005'").fetchall()]
    assert mine, "test data should have requisitions for U005"
    scoped = m.unique_people(con, m.Scope.requisitions(mine))
    assert 0 < scoped < m.unique_people(con, m.Scope.everything())


def test_scope_cannot_be_widened_by_a_sneaky_value(con):
    # a value that looks like SQL is just a string that matches nothing
    scope = m.Scope.requisitions(["REQ-1003' OR '1'='1"])
    assert m.hires(con, *H1, scope) == 0
    assert m.unique_people(con, scope) == 0


# ---------------------------------------------------------------- other metrics

def test_stage_conversion_is_an_ordered_funnel(con):
    rows = m.stage_conversion(con, m.Scope.everything())
    assert [r["stage"] for r in rows] == m.FUNNEL
    assert rows[0]["reached"] == 1427 and rows[0]["conversion_from_previous_pct"] is None
    reached = [r["reached"] for r in rows]
    assert reached == sorted(reached, reverse=True)


def test_period_over_period_uses_an_equally_long_previous_period(con):
    result = m.hires_period_over_period(con, *H1, m.Scope.everything())
    assert result["current"] == m.time_to_hire_days(con, *H1, m.Scope.everything())["hires"]
    assert result["change"] == result["current"] - result["previous"]
    cur_start, cur_end = (date.fromisoformat(d) for d in result["current_period"])
    prev_start, prev_end = (date.fromisoformat(d) for d in result["previous_period"])
    assert (prev_end - prev_start) == (cur_end - cur_start)
    assert (cur_start - prev_end).days == 1


def test_headline_metrics_has_everything_the_dashboard_needs(con):
    result = m.headline_metrics(
        con, m.Scope.everything(), period_start=H1[0], period_end=H1[1], as_at=date(2026, 3, 31)
    )
    assert set(result) == {
        "unique_people", "applications_at_offer", "time_to_hire", "offer_acceptance",
        "offered_salary_total_inr", "stage_conversion", "hires_period_over_period", "period",
    }


# ---------------------------------------------------------------- one definition only

def test_no_metric_math_outside_the_metric_layer():
    """The API, frontend and reconciliation must call definitions.py, never re-implement it."""
    forbidden = re.compile(r"median\(|date_diff\(|annual_salary_inr|FILTER\s*\(|valid_from|valid_to")
    allowed_dirs = [ROOT / "src" / "metrics", ROOT / "src" / "pipeline"]
    offenders = []
    for folder in (ROOT / "src", ROOT / "web"):
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.suffix not in {".py", ".js", ".html", ".ts", ".tsx"}:
                continue
            if any(d in path.parents for d in allowed_dirs):
                continue
            if forbidden.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
