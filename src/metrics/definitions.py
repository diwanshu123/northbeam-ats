"""THE ONLY PLACE METRIC MATH LIVES.

Every number shown anywhere (API, frontend, reconciliation, tests) comes from a function in
this file. If a definition changes, this is the one file that changes.

Every metric takes a Scope. The Scope is built on the server from the logged-in user
(never from request input) and is applied inside the SQL, so a metric can only ever
see the requisitions the user is allowed to see.

Definitions (plain words):
- unique_people        people (not candidate records) in the pool. Scoped: people with an
                       application on an in-scope requisition.
- applications_at_stage  applications whose stage on the close of a given day was X, read from
                       stage HISTORY (never from the current_stage column).
- time_to_hire_days    median whole calendar days from application date to Hired date, for
                       hires inside a date range.
- offered_salary_total sum of annual offered salary (INR) for offers against requisitions in
                       a department, any offer status.
- offer_acceptance_rate  accepted / (accepted + declined) in per cent. Open offers excluded.
- stage_conversion     of applications that reached a stage, the share that reached the next.
- hires_period_over_period  hires in a period vs the equally long period just before it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import duckdb

FUNNEL = ["Applied", "Screen", "Interview", "Offer", "Hired"]

DEFINITIONS = {
    "unique_people": "People in the candidate pool. Candidate records are merged by phone number.",
    "applications_at_stage": "Applications that were in a stage at the close of a given day, from stage history.",
    "time_to_hire_days": "Median whole days from application date to Hired date, for hires in the period.",
    "offered_salary_total": "Total annual offered salary in INR for a department's requisitions, any offer status.",
    "offer_acceptance_rate": "Accepted offers as a percentage of accepted plus declined, to one decimal (a tie rounds to even). Open offers excluded.",
    "stage_conversion": "For each funnel stage, the share of applications that reached it from the stage before.",
    "hires_period_over_period": "Hires in the period compared with the equally long period immediately before.",
}


@dataclass(frozen=True)
class Scope:
    """Which requisitions a caller may see. None means all of them."""

    req_ids: tuple[str, ...] | None = None

    @classmethod
    def everything(cls) -> "Scope":
        return cls(None)

    @classmethod
    def requisitions(cls, req_ids) -> "Scope":
        return cls(tuple(sorted(set(req_ids))))

    def clause(self, alias: str = "r") -> tuple[str, list[Any]]:
        """SQL condition (and its parameters) limiting rows to this scope."""
        if self.req_ids is None:
            return "TRUE", []
        if len(self.req_ids) == 0:
            return "FALSE", []
        return f"list_contains(?, {alias}.req_id)", [list(self.req_ids)]


# ---------------------------------------------------------------- helpers

def _start_of(day: date) -> datetime:
    return datetime.combine(day, time.min)


def _start_of_next_day(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min)


def _pct(part: float, whole: float) -> float | None:
    """Percentage to one decimal place, or None when there is nothing to divide by.

    Rounding rule: Python's round(), so an exact tie goes to the even digit (51.25 -> 51.2).
    The control total for offer acceptance (51.2) only ties under this rule. See docs/RECONCILIATION.md.
    """
    if not whole:
        return None
    return round(100.0 * part / whole, 1)


_HISTORY_JOINS = """
    FROM fact_stage_history h
    JOIN dim_stage s        ON s.stage_sk = h.stage_sk
    JOIN fact_application a ON a.application_sk = h.application_sk
    JOIN dim_requisition r  ON r.req_sk = a.req_sk
"""


# ---------------------------------------------------------------- metrics

def unique_people(con: duckdb.DuckDBPyConnection, scope: Scope) -> int:
    if scope.req_ids is None:
        return con.execute("SELECT count(*) FROM dim_person").fetchone()[0]
    clause, params = scope.clause()
    sql = f"""
        SELECT count(DISTINCT a.person_sk)
        FROM fact_application a
        JOIN dim_requisition r ON r.req_sk = a.req_sk
        WHERE {clause}
    """
    return con.execute(sql, params).fetchone()[0]


def applications_at_stage(con: duckdb.DuckDBPyConnection, stage: str, as_at: date, scope: Scope) -> int:
    """Applications in `stage` at the close of day `as_at` (the stage row that covers that moment)."""
    cutoff = _start_of_next_day(as_at)
    clause, params = scope.clause()
    sql = f"""
        SELECT count(*)
        {_HISTORY_JOINS}
        WHERE s.stage_name = ?
          AND h.valid_from < ?
          AND (h.valid_to IS NULL OR h.valid_to >= ?)
          AND {clause}
    """
    return con.execute(sql, [stage, cutoff, cutoff, *params]).fetchone()[0]


def hires(con: duckdb.DuckDBPyConnection, start: date, end: date, scope: Scope) -> int:
    """Hires whose Hired date is between start and end, both days included."""
    clause, params = scope.clause()
    sql = f"""
        SELECT count(*)
        {_HISTORY_JOINS}
        WHERE s.stage_name = 'Hired'
          AND h.valid_from >= ? AND h.valid_from < ?
          AND {clause}
    """
    return con.execute(sql, [_start_of(start), _start_of_next_day(end), *params]).fetchone()[0]


def time_to_hire_days(con: duckdb.DuckDBPyConnection, start: date, end: date, scope: Scope) -> dict:
    """Median whole calendar days from applied date to Hired date, for hires in [start, end]."""
    clause, params = scope.clause()
    sql = f"""
        SELECT median(date_diff('day', CAST(a.applied_at AS DATE), CAST(h.valid_from AS DATE))),
               count(*)
        {_HISTORY_JOINS}
        WHERE s.stage_name = 'Hired'
          AND h.valid_from >= ? AND h.valid_from < ?
          AND {clause}
    """
    median, n = con.execute(sql, [_start_of(start), _start_of_next_day(end), *params]).fetchone()
    return {"median_days": None if median is None else float(median), "hires": n}


def offered_salary_total(con: duckdb.DuckDBPyConnection, department: str | None, scope: Scope) -> int:
    """Total annual offered salary in INR, any offer status. department=None means all departments."""
    clause, params = scope.clause()
    dept_sql, dept_params = ("TRUE", []) if department is None else ("r.department = ?", [department])
    sql = f"""
        SELECT sum(o.annual_salary_inr)
        FROM fact_offer o
        JOIN dim_requisition r ON r.req_sk = o.req_sk
        WHERE {dept_sql} AND {clause}
    """
    total = con.execute(sql, [*dept_params, *params]).fetchone()[0]
    return int(round(total)) if total is not None else 0


def offer_acceptance_rate(con: duckdb.DuckDBPyConnection, scope: Scope) -> dict:
    """accepted / (accepted + declined) as a percentage. Open offers are not decided, so excluded."""
    clause, params = scope.clause()
    sql = f"""
        SELECT count(*) FILTER (WHERE o.status = 'accepted'),
               count(*) FILTER (WHERE o.status = 'declined')
        FROM fact_offer o
        JOIN dim_requisition r ON r.req_sk = o.req_sk
        WHERE {clause}
    """
    accepted, declined = con.execute(sql, params).fetchone()
    return {"rate_pct": _pct(accepted, accepted + declined), "accepted": accepted, "declined": declined}


def stage_conversion(con: duckdb.DuckDBPyConnection, scope: Scope) -> list[dict]:
    """For each funnel stage: applications that ever reached it, and the share of the previous stage."""
    clause, params = scope.clause()
    sql = f"""
        SELECT s.stage_name, count(DISTINCT a.application_sk)
        {_HISTORY_JOINS}
        WHERE s.stage_name IN (SELECT unnest(?)) AND {clause}
        GROUP BY s.stage_name
    """
    reached = dict(con.execute(sql, [FUNNEL, *params]).fetchall())
    rows, previous = [], None
    for stage in FUNNEL:
        count = reached.get(stage, 0)
        rows.append(
            {
                "stage": stage,
                "reached": count,
                "conversion_from_previous_pct": None if previous is None else _pct(count, previous),
            }
        )
        previous = count
    return rows


def hires_period_over_period(con: duckdb.DuckDBPyConnection, start: date, end: date, scope: Scope) -> dict:
    """Hires in [start, end] against the same number of days immediately before start.

    Caveat: the extract starts on 2025-09-04, so a comparison period that begins before then is incomplete.
    """
    length = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=length - 1)
    current = hires(con, start, end, scope)
    previous = hires(con, previous_start, previous_end, scope)
    change_pct = None if previous == 0 else round(100.0 * (current - previous) / previous, 1)
    data_starts = con.execute("SELECT min(date) FROM dim_date").fetchone()[0]
    return {
        "previous_period_incomplete": previous_start < data_starts,
        "current": current,
        "previous": previous,
        "change": current - previous,
        "change_pct": change_pct,
        "current_period": [start.isoformat(), end.isoformat()],
        "previous_period": [previous_start.isoformat(), previous_end.isoformat()],
    }


def requisition_summary(con: duckdb.DuckDBPyConnection, scope: Scope) -> list[dict]:
    """One row per in-scope requisition with its application, offer and hire counts."""
    clause, params = scope.clause()
    sql = f"""
        WITH apps AS (
            SELECT req_sk, count(*) AS applications FROM fact_application GROUP BY req_sk
        ),
        offers AS (
            SELECT req_sk, count(*) AS offers FROM fact_offer GROUP BY req_sk
        ),
        hired AS (
            SELECT a.req_sk, count(*) AS hires
            FROM fact_stage_history h
            JOIN dim_stage s        ON s.stage_sk = h.stage_sk
            JOIN fact_application a ON a.application_sk = h.application_sk
            WHERE s.stage_name = 'Hired'
            GROUP BY a.req_sk
        )
        SELECT r.req_id, r.title, r.department, r.location, r.status, r.headcount,
               hm.name AS hiring_manager, rc.name AS recruiter,
               coalesce(apps.applications, 0) AS applications,
               coalesce(offers.offers, 0)     AS offers,
               coalesce(hired.hires, 0)       AS hires
        FROM dim_requisition r
        LEFT JOIN dim_user hm ON hm.user_sk = r.hiring_manager_user_sk
        LEFT JOIN dim_user rc ON rc.user_sk = r.recruiter_user_sk
        LEFT JOIN apps   ON apps.req_sk   = r.req_sk
        LEFT JOIN offers ON offers.req_sk = r.req_sk
        LEFT JOIN hired  ON hired.req_sk  = r.req_sk
        WHERE {clause}
        ORDER BY r.req_id
    """
    cursor = con.execute(sql, params)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def headline_metrics(
    con: duckdb.DuckDBPyConnection,
    scope: Scope,
    *,
    period_start: date,
    period_end: date,
    as_at: date,
) -> dict:
    """Everything the dashboard shows, in one call. The API returns this untouched."""
    return {
        "unique_people": unique_people(con, scope),
        "applications_at_offer": {
            "as_at": as_at.isoformat(),
            "count": applications_at_stage(con, "Offer", as_at, scope),
        },
        "time_to_hire": time_to_hire_days(con, period_start, period_end, scope),
        "offer_acceptance": offer_acceptance_rate(con, scope),
        "offered_salary_total_inr": offered_salary_total(con, None, scope),
        "stage_conversion": stage_conversion(con, scope),
        "hires_period_over_period": hires_period_over_period(con, period_start, period_end, scope),
        "period": [period_start.isoformat(), period_end.isoformat()],
    }
