import time
from datetime import date

import duckdb
import jwt
import pytest
from fastapi.testclient import TestClient

from src.api import seed_auth
from src.api.main import create_app
from src.metrics import definitions as m
from src.pipeline import bronze, gold, silver

SECRET = "t" * 48
PASSWORD = "test-password-123"
HM_EMAIL = "uday.varma@northbeam.example"        # hiring manager U005: REQ-1003, REQ-1010, REQ-1024
HM_OTHER_REQ = "REQ-1001"                         # belongs to hiring manager U006
RECRUITER_EMAIL = "rahul.singh@northbeam.example"  # recruiter U003
ADMIN_EMAIL = "simran.jain@northbeam.example"      # admin U013


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    folder = tmp_path_factory.mktemp("api")
    warehouse, auth = folder / "wh.duckdb", folder / "auth.duckdb"
    bronze.run(warehouse); silver.run(warehouse); gold.run(warehouse)
    seed_auth.seed(auth, warehouse, shared_password=PASSWORD)
    return warehouse, auth


@pytest.fixture(scope="module")
def client(paths):
    return TestClient(create_app(paths[0], paths[1], SECRET))


def truth(paths, sql, params=()):
    con = duckdb.connect(str(paths[0]), read_only=True)
    try:
        return con.execute(sql, list(params)).fetchall()
    finally:
        con.close()


def login(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def headers_for(client, email):
    return {"Authorization": "Bearer " + login(client, email).json()["access_token"]}


def token_for(sub, secret=SECRET, **extra):
    now = int(time.time())
    return jwt.encode({"sub": sub, "iat": now, "exp": now + 3600, **extra}, secret, algorithm="HS256")


def bearer(token):
    return {"Authorization": "Bearer " + token}


def req_ids(client, headers, **params):
    response = client.get("/requisitions", headers=headers, params=params)
    assert response.status_code == 200
    return sorted(r["req_id"] for r in response.json()["requisitions"])


# ------------------------------------------------------------------ login

def test_login_returns_token_and_role(client):
    body = login(client, HM_EMAIL).json()
    assert body["token_type"] == "bearer" and body["access_token"]
    assert body["user"]["role"] == "hiring_manager"


def test_wrong_password_and_unknown_user_look_the_same(client):
    wrong = login(client, HM_EMAIL, "nope")
    unknown = login(client, "nobody@northbeam.example", "nope")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_is_locked_after_repeated_failures(paths):
    fresh = TestClient(create_app(paths[0], paths[1], SECRET))
    for _ in range(5):
        assert login(fresh, RECRUITER_EMAIL, "bad").status_code == 401
    assert login(fresh, RECRUITER_EMAIL, "bad").status_code == 429
    assert login(fresh, RECRUITER_EMAIL).status_code == 429  # even the right password waits


# ------------------------------------------------------------------ tokens

def test_requests_without_a_valid_token_are_refused(client):
    now = int(time.time())
    bad_tokens = [
        "garbage",
        token_for("U005", secret="x" * 48),                                              # wrong signature
        jwt.encode({"sub": "U005", "iat": now - 7200, "exp": now - 3600}, SECRET, "HS256"),  # expired
        jwt.encode({"sub": "U013", "iat": now, "exp": now + 3600}, None, algorithm="none"),  # unsigned
        token_for("U999"),                                                               # no such user
    ]
    assert client.get("/me").status_code == 401
    for path in ("/me", "/metrics", "/requisitions", "/requisitions/REQ-1003/candidates"):
        assert client.get(path).status_code == 401, path
        for token in bad_tokens:
            assert client.get(path, headers=bearer(token)).status_code == 401, (path, token[:20])


# ------------------------------------------------------------------ who sees what

def test_hiring_manager_sees_only_their_requisitions(client, paths):
    expected = sorted(r[0] for r in truth(paths, "SELECT req_id FROM silver_requisitions WHERE hiring_manager_id = 'U005'"))
    assert expected == ["REQ-1003", "REQ-1010", "REQ-1024"]
    assert req_ids(client, headers_for(client, HM_EMAIL)) == expected


def test_recruiter_sees_only_requisitions_they_own(client, paths):
    expected = sorted(r[0] for r in truth(paths, "SELECT req_id FROM silver_requisitions WHERE recruiter_id = 'U003'"))
    got = req_ids(client, headers_for(client, RECRUITER_EMAIL))
    assert got == expected and 0 < len(got) < 26


def test_admin_sees_every_requisition(client):
    assert len(req_ids(client, headers_for(client, ADMIN_EMAIL))) == 26


def test_someone_elses_requisition_looks_exactly_like_a_missing_one(client):
    h = headers_for(client, HM_EMAIL)
    other = client.get(f"/requisitions/{HM_OTHER_REQ}/candidates", headers=h)
    missing = client.get("/requisitions/REQ-9999/candidates", headers=h)
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()


def test_own_candidates_are_returned_without_contact_details(client, paths):
    h = headers_for(client, HM_EMAIL)
    rows = truth(paths, "SELECT r.req_id, count(*) FROM fact_application a JOIN dim_requisition r USING (req_sk) "
                        "WHERE r.hiring_manager_id = 'U005' GROUP BY 1 ORDER BY 2 DESC")
    req_id, n = rows[0]
    body = client.get(f"/requisitions/{req_id}/candidates", headers=h).json()
    assert len(body["candidates"]) == n > 0
    assert set(body["candidates"][0]) == {"name", "source", "applied_at", "stage"}


def test_editing_the_request_cannot_widen_access(client):
    h = headers_for(client, HM_EMAIL)
    baseline = req_ids(client, h)
    tampered_headers = {**h, "X-User-Id": "U013", "X-Role": "admin", "X-Req-Ids": "REQ-1001"}
    response = client.get("/requisitions", headers=tampered_headers,
                          params={"hiring_manager_id": "U006", "recruiter_id": "U003",
                                  "req_ids": "REQ-1001", "role": "admin", "user_id": "U013"})
    assert sorted(r["req_id"] for r in response.json()["requisitions"]) == baseline
    assert client.get(f"/requisitions/{HM_OTHER_REQ}/candidates", headers=tampered_headers,
                      params={"user_id": "U006"}).status_code == 404


def test_role_claims_inside_a_validly_signed_token_are_ignored(client):
    # even a token signed with the real secret cannot grant a role: role comes from the database
    forged = token_for("U005", role="admin", scope="all", req_ids=["REQ-1001"])
    assert req_ids(client, bearer(forged)) == ["REQ-1003", "REQ-1010", "REQ-1024"]
    assert client.get("/me", headers=bearer(forged)).json()["role"] == "hiring_manager"


def test_metrics_are_limited_to_the_users_scope(client, paths):
    h = headers_for(client, HM_EMAIL)
    body = client.get("/metrics", headers=h).json()
    con = duckdb.connect(str(paths[0]), read_only=True)
    try:
        scope = m.Scope.requisitions(["REQ-1003", "REQ-1010", "REQ-1024"])
        expected = m.headline_metrics(con, scope, period_start=date(2026, 1, 1),
                                      period_end=date(2026, 6, 30), as_at=date(2026, 3, 31))
        everyone = m.unique_people(con, m.Scope.everything())
    finally:
        con.close()
    assert body["unique_people"] == expected["unique_people"] < everyone
    assert body["offer_acceptance"] == expected["offer_acceptance"]
    admin_body = client.get("/metrics", headers=headers_for(client, ADMIN_EMAIL)).json()
    assert admin_body["unique_people"] == everyone == 560


# ------------------------------------------------------------------ input checks and hygiene

def test_bad_input_is_rejected(client):
    h = headers_for(client, ADMIN_EMAIL)
    assert client.get("/requisitions/REQ-1003'; DROP TABLE x;--/candidates", headers=h).status_code in (404, 422)
    assert client.get("/requisitions/REQ-12/candidates", headers=h).status_code == 422
    assert client.get("/metrics", headers=h, params={"period_start": "2026-06-30", "period_end": "2026-01-01"}).status_code == 422
    assert client.get("/metrics", headers=h, params={"period_start": "not-a-date"}).status_code == 422
    assert client.post("/auth/login", json={"email": "a@b.c"}).status_code == 422


def test_security_headers_and_no_public_docs(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/me", headers=headers_for(client, HM_EMAIL)).headers["Cache-Control"] == "no-store"


def test_short_jwt_secret_is_refused(paths):
    with pytest.raises(ValueError):
        create_app(paths[0], paths[1], "short")
