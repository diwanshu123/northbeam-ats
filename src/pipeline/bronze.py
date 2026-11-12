"""Bronze layer: load the 7 raw files exactly as landed.

Rules for this layer:
- No cleaning, no typing. Every column is stored as text (VARCHAR).
- Every row carries lineage: _source_file, _source_row, _source_sha256, _loaded_at.
- Re-running is safe: each bronze table is rebuilt from the file (CREATE OR REPLACE),
  so a second run gives the same rows, never duplicates.
- bronze__load_log has one row per source file (latest load), for audit.

Run:  python -m src.pipeline.bronze
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "warehouse.duckdb"

# source file -> bronze table name
SOURCES = {
    "candidates.csv": "bronze_candidates",
    "applications.csv": "bronze_applications",
    "stage_events.csv": "bronze_stage_events",
    "requisitions.json": "bronze_requisitions",
    "users.json": "bronze_users",
    "interviews.json": "bronze_interviews",
    "offers.xlsx": "bronze_offers",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sql_str(value: str) -> str:
    """Quote a value as a SQL string literal (views cannot take query parameters)."""
    return "'" + value.replace("'", "''") + "'"


def _register_source(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    """Expose the file as a view called _src, whatever its format."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        # all_varchar: keep text exactly as it is (spaces, case, odd dates)
        con.execute(
            "CREATE OR REPLACE TEMP VIEW _src AS "
            f"SELECT * FROM read_csv({_sql_str(str(path))}, header=true, all_varchar=true)"
        )
    elif suffix == ".json":
        con.execute(
            "CREATE OR REPLACE TEMP VIEW _src AS "
            f"SELECT * FROM read_json_auto({_sql_str(str(path))}, format='array')"
        )
    elif suffix == ".xlsx":
        df = pd.read_excel(path, sheet_name=0, dtype=object)
        con.register("_src_df", df)
        con.execute("CREATE OR REPLACE TEMP VIEW _src AS SELECT * FROM _src_df")
    else:
        raise ValueError(f"Unsupported source type: {path.name}")


def load_file(con: duckdb.DuckDBPyConnection, filename: str, table: str, loaded_at: datetime) -> int:
    path = RAW_DIR / filename
    if not path.exists():
        raise FileNotFoundError(path)

    _register_source(con, path)
    cols = [r[0] for r in con.execute("DESCRIBE _src").fetchall()]
    casts = ", ".join(f'CAST("{c}" AS VARCHAR) AS "{c}"' for c in cols)
    sha = _sha256(path)

    con.execute(
        f"""
        CREATE OR REPLACE TABLE {table} AS
        SELECT {casts},
               ? AS _source_file,
               row_number() OVER () AS _source_row,
               ? AS _source_sha256,
               ?::TIMESTAMP AS _loaded_at
        FROM _src
        """,
        [filename, sha, loaded_at],
    )
    n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    con.execute(
        "INSERT OR REPLACE INTO bronze__load_log VALUES (?, ?, ?, ?, ?)",
        [filename, table, n, sha, loaded_at],
    )
    return n


def run(db_path: Path = DB_PATH) -> dict[str, int]:
    """Load every source file. Returns {table: row_count}."""
    loaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS bronze__load_log (
                source_file VARCHAR PRIMARY KEY,
                table_name  VARCHAR,
                row_count   BIGINT,
                sha256      VARCHAR,
                loaded_at   TIMESTAMP
            )
            """
        )
        counts = {}
        for filename, table in SOURCES.items():
            counts[table] = load_file(con, filename, table, loaded_at)
        return counts
    finally:
        con.close()


if __name__ == "__main__":
    out = run()
    width = max(len(t) for t in out)
    for table, n in out.items():
        print(f"{table:<{width}}  {n:>6} rows")
    sys.exit(0)
