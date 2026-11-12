import duckdb
import pytest

from src.pipeline import bronze, silver


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "test.duckdb"
    bronze.run(path)
    silver.run(path)
    return path


def q(db, sql):
    con = duckdb.connect(str(db))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_people_are_deduplicated_by_phone(db):
    # 601 candidate records are really 560 people (control total 1)
    assert q(db, "SELECT count(*) FROM silver_candidates")[0][0] == 601
    assert q(db, "SELECT count(*) FROM silver_people")[0][0] == 560
    assert q(db, "SELECT count(*) - count(DISTINCT person_key) FROM silver_people")[0][0] == 0


def test_nothing_is_lost_between_bronze_and_silver_plus_quarantine(db):
    pairs = [
        ("bronze_applications", "silver_applications", "quarantine_applications"),
        ("bronze_stage_events", "silver_stage_events", "quarantine_stage_events"),
        ("bronze_offers", "silver_offers", "quarantine_offers"),
        ("bronze_interviews", "silver_interviews", "quarantine_interviews"),
    ]
    for b, s, qt in pairs:
        n_b = q(db, f"SELECT count(*) FROM {b}")[0][0]
        n_s = q(db, f"SELECT count(*) FROM {s}")[0][0]
        n_q = q(db, f"SELECT count(*) FROM {qt}")[0][0]
        assert n_s + n_q == n_b, b


def test_applications_without_valid_requisition_are_quarantined(db):
    assert q(db, "SELECT count(*) FROM silver_applications")[0][0] == 1427
    assert q(db, "SELECT count(*) FROM quarantine_applications")[0][0] == 23
    orphans = q(
        db,
        "SELECT count(*) FROM silver_applications "
        "WHERE req_id NOT IN (SELECT req_id FROM silver_requisitions)",
    )[0][0]
    assert orphans == 0


def test_no_child_row_points_at_a_missing_application(db):
    for table in ("silver_stage_events", "silver_offers", "silver_interviews"):
        bad = q(
            db,
            f"SELECT count(*) FROM {table} "
            f"WHERE application_id NOT IN (SELECT application_id FROM silver_applications)",
        )[0][0]
        assert bad == 0, table


def test_quarantine_rows_always_have_a_reason(db):
    for table in (
        "quarantine_applications",
        "quarantine_stage_events",
        "quarantine_offers",
        "quarantine_interviews",
    ):
        nulls = q(db, f"SELECT count(*) FROM {table} WHERE quarantine_reason IS NULL")[0][0]
        assert nulls == 0, table


def test_names_are_clean(db):
    bad = q(
        db,
        "SELECT count(*) FROM silver_candidates "
        "WHERE full_name <> trim(full_name) OR full_name LIKE '%  %' "
        "OR full_name = upper(full_name) OR full_name = lower(full_name)",
    )[0][0]
    assert bad == 0


def test_engineering_salary_converted_from_paise(db):
    top = q(db, "SELECT max(annual_salary_inr) FROM silver_offers")[0][0]
    assert top < 10_000_000
    converted = q(db, "SELECT count(*) FROM silver_offers WHERE salary_was_paise")[0][0]
    assert converted > 0
    # raw value is kept next to the fixed one
    ratio = q(
        db,
        "SELECT count(*) FROM silver_offers WHERE salary_was_paise "
        "AND annual_salary_raw <> annual_salary_inr * 100",
    )[0][0]
    assert ratio == 0


def test_open_offers_have_no_decision_date(db):
    bad = q(
        db, "SELECT count(*) FROM silver_offers WHERE status = 'open' AND decided_at IS NOT NULL"
    )[0][0]
    assert bad == 0


def test_types_are_real_types(db):
    types = dict(
        (r[0], r[1])
        for r in q(db, "SELECT column_name, data_type FROM information_schema.columns "
                       "WHERE table_name = 'silver_applications'")
    )
    assert types["applied_at"] == "TIMESTAMP"
    assert types["is_active"] == "BOOLEAN"


def test_silver_is_idempotent(db):
    def snap():
        return {
            t: q(db, f"SELECT * FROM {t} ORDER BY 1, 2")
            for t in (
                "silver_people",
                "silver_applications",
                "silver_stage_events",
                "silver_offers",
                "silver_interviews",
                "quarantine_applications",
            )
        }

    first = snap()
    silver.run(db)
    assert snap() == first
