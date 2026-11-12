"""Access control: turn a logged-in user into a Scope (the requisitions they may see).

The user comes from the verified token and is then loaded from the database. Role and
requisition ownership are NEVER taken from the token body, headers or query string.
Unknown roles get an empty scope (deny by default).
"""
from __future__ import annotations

import duckdb

from src.metrics.definitions import Scope


def load_user(con: duckdb.DuckDBPyConnection, user_id: str) -> dict | None:
    row = con.execute(
        "SELECT user_id, name, email, role, department FROM dim_user WHERE user_id = ?", [user_id]
    ).fetchone()
    if row is None:
        return None
    return dict(zip(("user_id", "name", "email", "role", "department"), row))


def scope_for(con: duckdb.DuckDBPyConnection, user: dict) -> Scope:
    role = user["role"]
    if role == "admin":
        return Scope.everything()
    column = {"hiring_manager": "hiring_manager_id", "recruiter": "recruiter_id"}.get(role)
    if column is None:
        return Scope.requisitions([])
    rows = con.execute(f"SELECT req_id FROM dim_requisition WHERE {column} = ?", [user["user_id"]]).fetchall()
    return Scope.requisitions([r[0] for r in rows])
