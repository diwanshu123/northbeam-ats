import duckdb
import pytest

from src.pipeline import bronze

# Row counts read straight from the raw files when this repo was set up.
EXPECTED = {
    "bronze_candidates": 601,
    "bronze_applications": 1450,
    "bronze_stage_events": 4774,
    "bronze_requisitions": 26,
    "bronze_users": 14,
    "bronze_interviews": 1284,
    "bronze_offers": 421,
}


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "test.duckdb"


def _snapshot(db):
    con = duckdb.connect(str(db))
    snap = {
        t: con.execute(
            f"SELECT * EXCLUDE (_loaded_at) FROM {t} ORDER BY _source_row"
        ).fetchall()
        for t in EXPECTED
    }
    log_rows = con.execute("SELECT count(*) FROM bronze__load_log").fetchone()[0]
    con.close()
    return snap, log_rows


def test_bronze_loads_every_file(db):
    assert bronze.run(db) == EXPECTED


def test_bronze_is_idempotent(db):
    """Running twice must not duplicate rows or change the data."""
    first = bronze.run(db)
    snap1, _ = _snapshot(db)
    second = bronze.run(db)
    snap2, log_rows = _snapshot(db)

    assert first == second == EXPECTED
    assert snap1 == snap2
    assert log_rows == len(EXPECTED)  # one log row per file, not per run


def test_bronze_keeps_data_as_landed(db):
    """No cleaning here: messy candidate names keep their extra spaces."""
    bronze.run(db)
    con = duckdb.connect(str(db))
    padded = con.execute(
        "SELECT count(*) FROM bronze_candidates WHERE full_name <> trim(full_name)"
    ).fetchone()[0]
    con.close()
    assert padded > 0


def test_lineage_columns_filled(db):
    bronze.run(db)
    con = duckdb.connect(str(db))
    for t in EXPECTED:
        nulls = con.execute(
            f"SELECT count(*) FROM {t} WHERE _source_file IS NULL OR _source_row IS NULL "
            f"OR _source_sha256 IS NULL OR _loaded_at IS NULL"
        ).fetchone()[0]
        assert nulls == 0, t
    con.close()
