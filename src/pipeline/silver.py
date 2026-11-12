"""Silver layer: cleaned, typed, de-duplicated, conformed.

Reads bronze_* tables, writes silver_* tables and quarantine_* tables.
Nothing is deleted silently: a row either lands in silver or in quarantine with a reason.

Cleaning rules (all found by profiling the raw files, see AGENTS.md):
- people:       one person = the last 10 digits of the phone number.
                601 candidate records -> 560 people.
- names:        trim, collapse repeated spaces, Capitalise Each Word.
- applications: req_id must exist in requisitions, else quarantine (23 rows).
- child rows:   stage events, offers and interviews whose application is not in
                silver_applications go to quarantine (missing vs quarantined parent).
- offers:       Engineering salaries are stored in paise -> divide by 100.
                Open offers carry a decided_at date; it is nulled (status is the truth).
- Re-running is safe: every table is rebuilt (CREATE OR REPLACE).

Run:  python -m src.pipeline.silver     (run bronze first)
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

from src.pipeline.bronze import DB_PATH

PAISE_PER_RUPEE = 100
PAISE_DEPARTMENT = "Engineering"  # all 111 Engineering offers are in paise (min 90,000,000)

def clean_name(value: str | None) -> str | None:
    """'  vikram   AGARWAL ' -> 'Vikram Agarwal' (trim, collapse spaces, Capitalise Each Word)."""
    if value is None:
        return None
    return " ".join(word.capitalize() for word in value.split())


STATEMENTS = {
    "silver_requisitions": r"""
        CREATE OR REPLACE TABLE silver_requisitions AS
        SELECT trim(req_id)                       AS req_id,
               trim(title)                        AS title,
               trim(department)                   AS department,
               trim(location)                     AS location,
               trim(hiring_manager_id)            AS hiring_manager_id,
               trim(recruiter_id)                 AS recruiter_id,
               CAST(headcount AS INTEGER)         AS headcount,
               CAST(opened_date AS DATE)          AS opened_date,
               CAST(closed_date AS DATE)          AS closed_date,
               lower(trim(status))                AS status
        FROM bronze_requisitions
    """,
    "silver_users": r"""
        CREATE OR REPLACE TABLE silver_users AS
        SELECT trim(user_id)           AS user_id,
               trim(name)              AS name,
               lower(trim(email))      AS email,
               lower(trim(role))       AS role,
               trim(department)        AS department
        FROM bronze_users
    """,
    # one row per candidate RECORD (601), each pointing at its person
    "silver_candidates": r"""
        CREATE OR REPLACE TABLE silver_candidates AS
        SELECT trim(candidate_id) AS candidate_id,
               right(regexp_replace(phone, '[^0-9]', '', 'g'), 10) AS person_key,
               clean_name(full_name)                  AS full_name,
               lower(trim(email))                     AS email,
               right(regexp_replace(phone, '[^0-9]', '', 'g'), 10) AS phone,
               trim(source)                           AS source,
               CAST(created_at AS TIMESTAMP)          AS created_at,
               _source_row
        FROM bronze_candidates
    """,
    # one row per real PERSON (560): keep the earliest record as the survivor
    "silver_people": r"""
        CREATE OR REPLACE TABLE silver_people AS
        WITH ranked AS (
            SELECT *,
                   row_number() OVER (PARTITION BY person_key ORDER BY created_at, candidate_id) AS rn,
                   count(*)     OVER (PARTITION BY person_key)                                   AS n_records
            FROM silver_candidates
        )
        SELECT person_key, full_name, email, phone, source,
               created_at AS first_seen_at,
               n_records  AS candidate_record_count
        FROM ranked WHERE rn = 1
    """,
    "silver_applications": r"""
        CREATE OR REPLACE TABLE silver_applications AS
        SELECT trim(a.application_id)               AS application_id,
               trim(a.candidate_id)                 AS candidate_id,
               c.person_key                         AS person_key,
               trim(a.req_id)                       AS req_id,
               CAST(a.applied_at AS TIMESTAMP)      AS applied_at,
               trim(a.current_stage)                AS current_stage,
               lower(trim(a.is_active)) = 'true'    AS is_active,
               a._source_row
        FROM bronze_applications a
        JOIN silver_candidates c ON c.candidate_id = trim(a.candidate_id)
        WHERE trim(a.req_id) IN (SELECT req_id FROM silver_requisitions)
    """,
    "quarantine_applications": r"""
        CREATE OR REPLACE TABLE quarantine_applications AS
        SELECT a.*, 'req_id not found in requisitions' AS quarantine_reason
        FROM bronze_applications a
        WHERE trim(a.req_id) NOT IN (SELECT req_id FROM silver_requisitions)
           OR trim(a.candidate_id) NOT IN (SELECT candidate_id FROM silver_candidates)
    """,
    "silver_stage_events": r"""
        CREATE OR REPLACE TABLE silver_stage_events AS
        SELECT trim(event_id)                         AS event_id,
               trim(application_id)                   AS application_id,
               NULLIF(trim(from_stage), '')           AS from_stage,
               trim(to_stage)                         AS to_stage,
               CAST(changed_at AS TIMESTAMP)          AS changed_at,
               CAST(event_seq AS INTEGER)             AS event_seq,
               trim(changed_by)                       AS changed_by,
               _source_row
        FROM bronze_stage_events
        WHERE trim(application_id) IN (SELECT application_id FROM silver_applications)
    """,
    "quarantine_stage_events": r"""
        CREATE OR REPLACE TABLE quarantine_stage_events AS
        SELECT e.*,
               CASE WHEN trim(e.application_id) IN (SELECT application_id FROM bronze_applications)
                    THEN 'application is quarantined' ELSE 'application not found' END AS quarantine_reason
        FROM bronze_stage_events e
        WHERE trim(e.application_id) NOT IN (SELECT application_id FROM silver_applications)
    """,
    "silver_offers": rf"""
        CREATE OR REPLACE TABLE silver_offers AS
        SELECT trim(offer_id)                          AS offer_id,
               trim(application_id)                    AS application_id,
               trim(department)                        AS department,
               CAST(offered_at AS DATE)                AS offered_at,
               CAST(annual_salary AS DOUBLE)           AS annual_salary_raw,
               CASE WHEN trim(department) = '{PAISE_DEPARTMENT}'
                    THEN CAST(annual_salary AS DOUBLE) / {PAISE_PER_RUPEE}
                    ELSE CAST(annual_salary AS DOUBLE) END AS annual_salary_inr,
               trim(department) = '{PAISE_DEPARTMENT}' AS salary_was_paise,
               trim(currency)                          AS currency,
               lower(trim(status))                     AS status,
               CASE WHEN lower(trim(status)) = 'open' THEN NULL
                    ELSE CAST(decided_at AS DATE) END  AS decided_at,
               _source_row
        FROM bronze_offers
        WHERE trim(application_id) IN (SELECT application_id FROM silver_applications)
    """,
    "quarantine_offers": r"""
        CREATE OR REPLACE TABLE quarantine_offers AS
        SELECT o.*,
               CASE WHEN trim(o.application_id) IN (SELECT application_id FROM bronze_applications)
                    THEN 'application is quarantined' ELSE 'application not found' END AS quarantine_reason
        FROM bronze_offers o
        WHERE trim(o.application_id) NOT IN (SELECT application_id FROM silver_applications)
    """,
    "silver_interviews": r"""
        CREATE OR REPLACE TABLE silver_interviews AS
        SELECT trim(interview_id)                      AS interview_id,
               trim(application_id)                    AS application_id,
               CAST(scheduled_at AS TIMESTAMP)         AS scheduled_at,
               trim(interviewer_id)                    AS interviewer_id,
               trim(type)                              AS interview_type,
               lower(trim(outcome))                    AS outcome,
               CAST(score AS INTEGER)                  AS score,
               _source_row
        FROM bronze_interviews
        WHERE trim(application_id) IN (SELECT application_id FROM silver_applications)
    """,
    "quarantine_interviews": r"""
        CREATE OR REPLACE TABLE quarantine_interviews AS
        SELECT i.*,
               CASE WHEN trim(i.application_id) IN (SELECT application_id FROM bronze_applications)
                    THEN 'application is quarantined' ELSE 'application not found' END AS quarantine_reason
        FROM bronze_interviews i
        WHERE trim(i.application_id) NOT IN (SELECT application_id FROM silver_applications)
    """,
}

# (bronze table, silver table, quarantine table or None) for the in / out / quarantined report
REPORT = [
    ("bronze_requisitions", "silver_requisitions", None),
    ("bronze_users", "silver_users", None),
    ("bronze_candidates", "silver_candidates", None),
    ("bronze_applications", "silver_applications", "quarantine_applications"),
    ("bronze_stage_events", "silver_stage_events", "quarantine_stage_events"),
    ("bronze_offers", "silver_offers", "quarantine_offers"),
    ("bronze_interviews", "silver_interviews", "quarantine_interviews"),
]


def run(db_path: Path = DB_PATH) -> list[tuple[str, int, int, int]]:
    """Build every silver table. Returns [(name, rows_in, rows_out, rows_quarantined)]."""
    con = duckdb.connect(str(db_path))
    try:
        con.create_function("clean_name", clean_name, ["VARCHAR"], "VARCHAR")
        for name, sql in STATEMENTS.items():
            con.execute(sql)
        report = []
        for bronze, silver, quarantine in REPORT:
            n_in = con.execute(f"SELECT count(*) FROM {bronze}").fetchone()[0]
            n_out = con.execute(f"SELECT count(*) FROM {silver}").fetchone()[0]
            n_q = con.execute(f"SELECT count(*) FROM {quarantine}").fetchone()[0] if quarantine else 0
            report.append((silver, n_in, n_out, n_q))
        n_people = con.execute("SELECT count(*) FROM silver_people").fetchone()[0]
        report.append(("silver_people", report[2][2], n_people, 0))
        return report
    finally:
        con.close()


if __name__ == "__main__":
    print(f"{'table':<24}{'in':>8}{'out':>8}{'quarantined':>13}")
    for name, n_in, n_out, n_q in run():
        print(f"{name:<24}{n_in:>8}{n_out:>8}{n_q:>13}")
    sys.exit(0)
