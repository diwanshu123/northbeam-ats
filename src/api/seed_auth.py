"""Create auth.duckdb with a password hash for every user.

Passwords are random per user unless DEMO_PASSWORD is set. The plain passwords are written
once to demo_credentials.csv (git-ignored) so a reviewer can log in. Never commit that file.

Run:  python -m src.api.seed_auth
"""
from __future__ import annotations

import csv
import os
import secrets
from pathlib import Path

import duckdb

from src.api.security import hash_password
from src.pipeline.bronze import DB_PATH, ROOT

AUTH_PATH = ROOT / "auth.duckdb"
CREDENTIALS_CSV = ROOT / "demo_credentials.csv"


def seed(auth_path: Path = AUTH_PATH, warehouse_path: Path = DB_PATH,
         shared_password: str | None = None, credentials_csv: Path | None = None) -> list[dict]:
    wh = duckdb.connect(str(warehouse_path), read_only=True)
    try:
        users = wh.execute("SELECT user_id, email, role, name FROM dim_user ORDER BY user_id").fetchall()
    finally:
        wh.close()

    issued = []
    con = duckdb.connect(str(auth_path))
    try:
        con.execute("CREATE OR REPLACE TABLE credentials "
                    "(user_id VARCHAR PRIMARY KEY, email VARCHAR UNIQUE, password_hash VARCHAR)")
        for user_id, email, role, name in users:
            password = shared_password or secrets.token_urlsafe(12)
            con.execute("INSERT INTO credentials VALUES (?, ?, ?)", [user_id, email.lower(), hash_password(password)])
            issued.append({"user_id": user_id, "email": email, "role": role, "name": name, "password": password})
    finally:
        con.close()

    if credentials_csv is not None:
        with credentials_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["user_id", "email", "role", "name", "password"])
            writer.writeheader()
            writer.writerows(issued)
    return issued


if __name__ == "__main__":
    rows = seed(shared_password=os.environ.get("DEMO_PASSWORD"), credentials_csv=CREDENTIALS_CSV)
    print(f"{len(rows)} users seeded. Passwords written to {CREDENTIALS_CSV.name} (git-ignored).")
