"""Gold layer: dimensional model (star schema) built from silver_*.

Grain of every fact table (one sentence each):
- fact_application   : one row per application that is tied to a valid requisition.
- fact_stage_history : one row per stage an application sat in (one per stage-change event),
                       with valid_from / valid_to, so the stage on ANY date can be answered.
- fact_offer         : one row per offer made against a valid application.
- fact_interview     : one row per scheduled interview against a valid application.

Dimensions: dim_date, dim_stage, dim_user, dim_person, dim_requisition.

Design notes
- Surrogate keys (*_sk) are integers made with row_number() over the natural key,
  so the same input always gives the same keys (re-running is safe).
- A stage is a history, not a column. fact_stage_history holds the intervals.
  "reported_stage" on fact_application is the source system's own column, kept only
  to show it disagrees with history; never use it for reporting.
- Applications without a valid requisition are NOT in Gold. They sit in quarantine_*.
- Metric arithmetic does NOT live here. See src/metrics/definitions.py.
- People are one row per real person (phone-matched). Applications point at the person.

Run:  python -m src.pipeline.gold     (run bronze and silver first)
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

from src.pipeline.bronze import DB_PATH


def _date_key(expr: str) -> str:
    """yyyymmdd integer for a date or timestamp expression (NULL stays NULL)."""
    return f"CAST(strftime({expr}, '%Y%m%d') AS INTEGER)"


STATEMENTS = {
    "dim_date": rf"""
        CREATE OR REPLACE TABLE dim_date AS
        WITH all_dates AS (
            SELECT CAST(applied_at AS DATE)   AS d FROM silver_applications
            UNION ALL SELECT CAST(changed_at AS DATE)   FROM silver_stage_events
            UNION ALL SELECT offered_at                 FROM silver_offers
            UNION ALL SELECT decided_at                 FROM silver_offers WHERE decided_at IS NOT NULL
            UNION ALL SELECT CAST(scheduled_at AS DATE) FROM silver_interviews
            UNION ALL SELECT opened_date                FROM silver_requisitions
            UNION ALL SELECT closed_date                FROM silver_requisitions WHERE closed_date IS NOT NULL
        ),
        bounds AS (SELECT min(d) AS lo, max(d) AS hi FROM all_dates),
        days AS (
            SELECT CAST(unnest(generate_series(CAST(lo AS TIMESTAMP), CAST(hi AS TIMESTAMP),
                                               INTERVAL 1 DAY)) AS DATE) AS d
            FROM bounds
        )
        SELECT {_date_key('d')}        AS date_key,
               d                       AS date,
               year(d)                 AS year,
               quarter(d)              AS quarter,
               month(d)                AS month,
               strftime(d, '%B')       AS month_name,
               day(d)                  AS day,
               dayofweek(d) IN (0, 6)  AS is_weekend
        FROM days
    """,
    "dim_stage": r"""
        CREATE OR REPLACE TABLE dim_stage AS
        SELECT * FROM (VALUES
            (1, 'Applied',   1, FALSE),
            (2, 'Screen',    2, FALSE),
            (3, 'Interview', 3, FALSE),
            (4, 'Offer',     4, FALSE),
            (5, 'Hired',     5, TRUE),
            (6, 'Rejected',  6, TRUE),
            (7, 'Withdrawn', 7, TRUE)
        ) AS t(stage_sk, stage_name, stage_order, is_terminal)
    """,
    "dim_user": r"""
        CREATE OR REPLACE TABLE dim_user AS
        SELECT row_number() OVER (ORDER BY user_id) AS user_sk,
               user_id, name, email, role, department
        FROM silver_users
    """,
    "dim_person": r"""
        CREATE OR REPLACE TABLE dim_person AS
        SELECT row_number() OVER (ORDER BY person_key) AS person_sk,
               person_key, full_name, email, phone, source,
               first_seen_at, candidate_record_count
        FROM silver_people
    """,
    "dim_requisition": r"""
        CREATE OR REPLACE TABLE dim_requisition AS
        SELECT row_number() OVER (ORDER BY r.req_id) AS req_sk,
               r.req_id, r.title, r.department, r.location,
               r.hiring_manager_id, hm.user_sk AS hiring_manager_user_sk,
               r.recruiter_id,      rc.user_sk AS recruiter_user_sk,
               r.headcount, r.opened_date, r.closed_date, r.status
        FROM silver_requisitions r
        LEFT JOIN dim_user hm ON hm.user_id = r.hiring_manager_id
        LEFT JOIN dim_user rc ON rc.user_id = r.recruiter_id
    """,
    "fact_application": rf"""
        CREATE OR REPLACE TABLE fact_application AS
        WITH latest AS (
            SELECT application_id, arg_max(to_stage, event_seq) AS latest_stage
            FROM silver_stage_events GROUP BY application_id
        )
        SELECT row_number() OVER (ORDER BY a.application_id) AS application_sk,
               a.application_id,
               p.person_sk,
               r.req_sk,
               a.applied_at,
               {_date_key('a.applied_at')}  AS applied_date_key,
               l.latest_stage,
               a.current_stage              AS reported_stage,
               a.is_active
        FROM silver_applications a
        JOIN dim_person p       ON p.person_key = a.person_key
        JOIN dim_requisition r  ON r.req_id = a.req_id
        LEFT JOIN latest l      ON l.application_id = a.application_id
    """,
    "fact_stage_history": rf"""
        CREATE OR REPLACE TABLE fact_stage_history AS
        SELECT row_number() OVER (ORDER BY e.event_id)       AS stage_event_sk,
               e.event_id,
               fa.application_sk,
               s.stage_sk,
               fs.stage_sk                                   AS from_stage_sk,
               e.event_seq,
               e.changed_at                                  AS valid_from,
               lead(e.changed_at) OVER (PARTITION BY e.application_id ORDER BY e.event_seq) AS valid_to,
               lead(e.changed_at) OVER (PARTITION BY e.application_id ORDER BY e.event_seq) IS NULL AS is_current,
               {_date_key('e.changed_at')}                   AS date_key,
               u.user_sk                                     AS changed_by_user_sk
        FROM silver_stage_events e
        JOIN fact_application fa ON fa.application_id = e.application_id
        JOIN dim_stage s         ON s.stage_name = e.to_stage
        LEFT JOIN dim_stage fs   ON fs.stage_name = e.from_stage
        LEFT JOIN dim_user u     ON u.user_id = e.changed_by
    """,
    "fact_offer": rf"""
        CREATE OR REPLACE TABLE fact_offer AS
        SELECT row_number() OVER (ORDER BY o.offer_id) AS offer_sk,
               o.offer_id,
               fa.application_sk,
               fa.person_sk,
               fa.req_sk,
               o.department                  AS offer_department_reported,
               o.offered_at,
               {_date_key('o.offered_at')}   AS offered_date_key,
               o.decided_at,
               {_date_key('o.decided_at')}   AS decided_date_key,
               o.annual_salary_inr,
               o.salary_was_paise,
               o.currency,
               o.status
        FROM silver_offers o
        JOIN fact_application fa ON fa.application_id = o.application_id
    """,
    "fact_interview": rf"""
        CREATE OR REPLACE TABLE fact_interview AS
        SELECT row_number() OVER (ORDER BY i.interview_id) AS interview_sk,
               i.interview_id,
               fa.application_sk,
               u.user_sk                       AS interviewer_user_sk,
               i.scheduled_at,
               {_date_key('i.scheduled_at')}   AS date_key,
               i.interview_type,
               i.outcome,
               i.score
        FROM silver_interviews i
        JOIN fact_application fa ON fa.application_id = i.application_id
        LEFT JOIN dim_user u     ON u.user_id = i.interviewer_id
    """,
}


def run(db_path: Path = DB_PATH) -> dict[str, int]:
    """Build every gold table in dependency order. Returns {table: row_count}."""
    con = duckdb.connect(str(db_path))
    try:
        counts = {}
        for name, sql in STATEMENTS.items():
            con.execute(sql)
            counts[name] = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        return counts
    finally:
        con.close()


if __name__ == "__main__":
    for table, n in run().items():
        print(f"{table:<20}{n:>7} rows")
    sys.exit(0)
