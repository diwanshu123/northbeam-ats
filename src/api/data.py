"""Scoped reads of people data. Every query carries the scope clause inside the SQL."""
from __future__ import annotations

import duckdb

from src.metrics.definitions import Scope


def requisition_visible(con: duckdb.DuckDBPyConnection, req_id: str, scope: Scope) -> bool:
    clause, params = scope.clause()
    sql = f"SELECT count(*) FROM dim_requisition r WHERE r.req_id = ? AND {clause}"
    return con.execute(sql, [req_id, *params]).fetchone()[0] > 0


def candidates_for_requisition(con: duckdb.DuckDBPyConnection, req_id: str, scope: Scope) -> list[dict]:
    """People with an application on one requisition. Only fields a reviewer needs: no email, no phone."""
    clause, params = scope.clause()
    sql = f"""
        SELECT p.full_name AS name, p.source, a.applied_at, a.latest_stage AS stage
        FROM fact_application a
        JOIN dim_person p      ON p.person_sk = a.person_sk
        JOIN dim_requisition r ON r.req_sk = a.req_sk
        WHERE r.req_id = ? AND {clause}
        ORDER BY a.applied_at, a.application_id
    """
    rows = con.execute(sql, [req_id, *params]).fetchall()
    return [{"name": n, "source": s, "applied_at": t.isoformat(sep=" "), "stage": st} for n, s, t, st in rows]
