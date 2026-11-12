import duckdb
import pytest

from src.pipeline import bronze, gold, silver

EXPECTED_COUNTS = {
    "dim_stage": 7,
    "dim_user": 14,
    "dim_person": 560,
    "dim_requisition": 26,
    "fact_application": 1427,
    "fact_stage_history": 4677,
    "fact_offer": 404,
    "fact_interview": 1242,
}


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "test.duckdb"
    bronze.run(path)
    silver.run(path)
    gold.run(path)
    return path


def q(db, sql):
    con = duckdb.connect(str(db))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_row_counts(db):
    for table, expected in EXPECTED_COUNTS.items():
        assert q(db, f"SELECT count(*) FROM {table}")[0][0] == expected, table


def test_surrogate_keys_are_unique_and_not_null(db):
    keys = {
        "dim_date": "date_key",
        "dim_stage": "stage_sk",
        "dim_user": "user_sk",
        "dim_person": "person_sk",
        "dim_requisition": "req_sk",
        "fact_application": "application_sk",
        "fact_stage_history": "stage_event_sk",
        "fact_offer": "offer_sk",
        "fact_interview": "interview_sk",
    }
    for table, key in keys.items():
        n, distinct, nulls = q(
            db, f"SELECT count(*), count(DISTINCT {key}), count(*) FILTER ({key} IS NULL) FROM {table}"
        )[0]
        assert n == distinct and nulls == 0, f"{table}.{key}"


def test_grain_one_row_per_natural_key(db):
    natural = {
        "dim_person": "person_key",
        "dim_requisition": "req_id",
        "fact_application": "application_id",
        "fact_offer": "offer_id",
        "fact_interview": "interview_id",
        "fact_stage_history": "event_id",
    }
    for table, key in natural.items():
        dup = q(db, f"SELECT count(*) - count(DISTINCT {key}) FROM {table}")[0][0]
        assert dup == 0, table


def test_foreign_keys_resolve(db):
    checks = [
        ("fact_application", "person_sk", "dim_person", "person_sk"),
        ("fact_application", "req_sk", "dim_requisition", "req_sk"),
        ("fact_application", "applied_date_key", "dim_date", "date_key"),
        ("fact_stage_history", "application_sk", "fact_application", "application_sk"),
        ("fact_stage_history", "stage_sk", "dim_stage", "stage_sk"),
        ("fact_stage_history", "date_key", "dim_date", "date_key"),
        ("fact_offer", "application_sk", "fact_application", "application_sk"),
        ("fact_offer", "req_sk", "dim_requisition", "req_sk"),
        ("fact_offer", "offered_date_key", "dim_date", "date_key"),
        ("fact_interview", "application_sk", "fact_application", "application_sk"),
        ("fact_interview", "interviewer_user_sk", "dim_user", "user_sk"),
        ("fact_interview", "date_key", "dim_date", "date_key"),
        ("dim_requisition", "hiring_manager_user_sk", "dim_user", "user_sk"),
        ("dim_requisition", "recruiter_user_sk", "dim_user", "user_sk"),
    ]
    for fact, fk, dim, pk in checks:
        orphans = q(
            db,
            f"SELECT count(*) FROM {fact} WHERE {fk} IS NOT NULL "
            f"AND {fk} NOT IN (SELECT {pk} FROM {dim})",
        )[0][0]
        nulls = q(db, f"SELECT count(*) FROM {fact} WHERE {fk} IS NULL")[0][0]
        # decided_date_key is the only key allowed to be empty (not in this list)
        assert orphans == 0 and nulls == 0, f"{fact}.{fk} -> {dim}.{pk}"


def test_stage_history_is_a_proper_timeline(db):
    # every application has exactly one open (current) row
    bad = q(
        db,
        "SELECT count(*) FROM (SELECT application_sk FROM fact_stage_history "
        "WHERE is_current GROUP BY 1 HAVING count(*) <> 1)",
    )[0][0]
    assert bad == 0
    assert q(db, "SELECT count(DISTINCT application_sk) FROM fact_stage_history")[0][0] == 1427

    # every timeline starts at Applied
    not_applied = q(
        db,
        "SELECT count(*) FROM (SELECT application_sk, arg_min(stage_sk, event_seq) AS s "
        "FROM fact_stage_history GROUP BY 1) WHERE s <> 1",
    )[0][0]
    assert not_applied == 0

    # no gaps: each row ends exactly where the next row starts
    gaps = q(
        db,
        "SELECT count(*) FROM (SELECT valid_to, lead(valid_from) OVER "
        "(PARTITION BY application_sk ORDER BY event_seq) AS next_from "
        "FROM fact_stage_history) WHERE valid_to IS NOT NULL AND valid_to <> next_from",
    )[0][0]
    assert gaps == 0

    # no interval runs backwards
    backwards = q(
        db, "SELECT count(*) FROM fact_stage_history WHERE valid_to IS NOT NULL AND valid_to < valid_from"
    )[0][0]
    assert backwards == 0


def test_reported_stage_column_is_not_trustworthy(db):
    """Documents why history exists: the source column disagrees with the events."""
    differs = q(db, "SELECT count(*) FROM fact_application WHERE latest_stage <> reported_stage")[0][0]
    assert differs > 0


def test_quarantined_applications_are_not_in_gold(db):
    leaked = q(
        db,
        "SELECT count(*) FROM fact_application "
        "WHERE application_id IN (SELECT application_id FROM quarantine_applications)",
    )[0][0]
    assert leaked == 0


def test_gold_is_idempotent(db):
    tables = list(EXPECTED_COUNTS) + ["dim_date"]

    def snap():
        return {t: q(db, f"SELECT * FROM {t} ORDER BY 1") for t in tables}

    first = snap()
    gold.run(db)
    assert snap() == first
