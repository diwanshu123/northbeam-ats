"""FastAPI app: login, then metrics and requisitions limited to what the user may see.

Run:  uvicorn src.api.main:app
Env:  JWT_SECRET (32+ chars; random per start if missing), WAREHOUSE_PATH, AUTH_DB_PATH, ENABLE_DOCS=1

No metric math here: numbers come from src/metrics/definitions.py. Access is decided in
src/api/access.py and applied inside the SQL by the Scope.
"""
from __future__ import annotations

import os
import secrets
from datetime import date
from pathlib import Path

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Path as ApiPath, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.api import access, data, security
from src.api.seed_auth import AUTH_PATH
from src.metrics import definitions as m
from src.pipeline.bronze import DB_PATH, ROOT

WEB_DIR = ROOT / "web"
MAX_PERIOD_DAYS = 800


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


def create_app(warehouse_path: Path | None = None, auth_path: Path | None = None,
               jwt_secret: str | None = None) -> FastAPI:
    warehouse = Path(warehouse_path or os.environ.get("WAREHOUSE_PATH") or DB_PATH)
    auth_db = Path(auth_path or os.environ.get("AUTH_DB_PATH") or AUTH_PATH)
    secret = jwt_secret or os.environ.get("JWT_SECRET") or secrets.token_urlsafe(48)
    if len(secret) < 32:
        raise ValueError("JWT_SECRET must be at least 32 characters")

    docs_on = os.environ.get("ENABLE_DOCS") == "1"
    app = FastAPI(title="Northbeam hiring metrics",
                  docs_url="/docs" if docs_on else None,
                  redoc_url=None,
                  openapi_url="/openapi.json" if docs_on else None)
    guard = security.LoginGuard()
    bearer = HTTPBearer(auto_error=False)

    # ------------------------------------------------------------ plumbing
    @app.middleware("http")
    async def secure_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if not request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def warehouse_connection():
        con = duckdb.connect(str(warehouse), read_only=True)  # the API can never write data
        try:
            yield con
        finally:
            con.close()

    def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                     con: duckdb.DuckDBPyConnection = Depends(warehouse_connection)) -> dict:
        unauthenticated = HTTPException(status_code=401, detail="Not authenticated",
                                        headers={"WWW-Authenticate": "Bearer"})
        if creds is None:
            raise unauthenticated
        user_id = security.read_token(creds.credentials, secret)
        user = access.load_user(con, user_id) if user_id else None
        if user is None:
            raise unauthenticated
        return user

    def current_scope(user: dict = Depends(current_user),
                      con: duckdb.DuckDBPyConnection = Depends(warehouse_connection)) -> m.Scope:
        return access.scope_for(con, user)

    # ------------------------------------------------------------ routes
    @app.post("/auth/login")
    def login(body: LoginRequest, request: Request,
              con: duckdb.DuckDBPyConnection = Depends(warehouse_connection)):
        email = body.email.strip().lower()
        key = f"{email}|{request.client.host if request.client else 'unknown'}"
        if guard.blocked(key):
            raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")

        auth = duckdb.connect(str(auth_db), read_only=True)
        try:
            row = auth.execute("SELECT user_id, password_hash FROM credentials WHERE email = ?", [email]).fetchone()
        finally:
            auth.close()

        stored = row[1] if row else security.DUMMY_HASH          # same work for unknown emails
        password_ok = security.verify_password(body.password, stored)
        if not (row and password_ok):
            guard.record_failure(key)
            raise HTTPException(status_code=401, detail="Wrong email or password")

        guard.reset(key)
        user = access.load_user(con, row[0])
        if user is None:
            raise HTTPException(status_code=401, detail="Wrong email or password")
        return {
            "access_token": security.make_token(user["user_id"], secret),
            "token_type": "bearer",
            "user": {"name": user["name"], "role": user["role"]},
        }

    @app.get("/me")
    def me(user: dict = Depends(current_user)):
        return {"name": user["name"], "email": user["email"], "role": user["role"]}

    @app.get("/metrics")
    def metrics(
        period_start: date = Query(date(2026, 1, 1)),
        period_end: date = Query(date(2026, 6, 30)),
        as_at: date = Query(date(2026, 3, 31)),
        scope: m.Scope = Depends(current_scope),
        con: duckdb.DuckDBPyConnection = Depends(warehouse_connection),
    ):
        if period_end < period_start or (period_end - period_start).days > MAX_PERIOD_DAYS:
            raise HTTPException(status_code=422, detail="Invalid period")
        return m.headline_metrics(con, scope, period_start=period_start, period_end=period_end, as_at=as_at)

    @app.get("/requisitions")
    def requisitions(scope: m.Scope = Depends(current_scope),
                     con: duckdb.DuckDBPyConnection = Depends(warehouse_connection)):
        return {"requisitions": m.requisition_summary(con, scope)}

    @app.get("/requisitions/{req_id}/candidates")
    def candidates(req_id: str = ApiPath(pattern=r"^REQ-[0-9]{4}$"),
                   scope: m.Scope = Depends(current_scope),
                   con: duckdb.DuckDBPyConnection = Depends(warehouse_connection)):
        # Same answer for "does not exist" and "not yours": nothing to learn from the difference.
        if not data.requisition_visible(con, req_id, scope):
            raise HTTPException(status_code=404, detail="Requisition not found")
        return {"req_id": req_id, "candidates": data.candidates_for_requisition(con, req_id, scope)}

    # ------------------------------------------------------------ frontend
    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
