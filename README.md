# Northbeam ATS data layer

A Bronze / Silver / Gold pipeline over 7 raw ATS files, one metric layer, and a small
API + page with role-based access. Fictional company, synthetic data.

Rules for contributors and the coding agent: `AGENTS.md`. Plan and estimates: `PLAN.md`.
Model and grain: `docs/MODEL.md`. The five control totals: `docs/RECONCILIATION.md`.
How I used AI: `docs/WORKLOG.md`.

## Run it (10 minutes)

    python -m venv .venv
    .venv\Scripts\activate        # Windows.  Mac/Linux: source .venv/bin/activate
    pip install -r requirements.txt

    python -m src.pipeline.bronze     # raw files -> bronze tables (warehouse.duckdb)
    python -m src.pipeline.silver     # bronze -> silver + quarantine tables
    python -m src.pipeline.gold       # silver -> star schema
    python -m src.reconciliation      # the 5 control totals (exit code 1 if any fails)
    python -m src.api.seed_auth       # creates auth.duckdb and demo_credentials.csv
    pytest -q                         # 48 tests

    # start the app (set a secret of 32+ characters; if you skip it, a random one is used per start)
    set JWT_SECRET=<long random text>           # Mac/Linux: export JWT_SECRET=...
    uvicorn src.api.main:app
    # open http://127.0.0.1:8000 and log in with an email and password from demo_credentials.csv

`demo_credentials.csv` is git-ignored. Every user gets a random password unless `DEMO_PASSWORD` is set.
Try a hiring manager (`uday.varma@northbeam.example`), a recruiter (`rahul.singh@northbeam.example`)
and the admin (`simran.jain@northbeam.example`) and compare what each one sees.

## Where things live

| What | Where |
|---|---|
| Pipeline | `src/pipeline/bronze.py`, `silver.py`, `gold.py` (re-running never duplicates rows) |
| Every metric formula | `src/metrics/definitions.py` (the only place) |
| Access rules | `src/api/access.py` (user -> Scope), applied by `Scope.clause()` inside every query |
| API | `src/api/main.py` |
| Page | `web/` (no calculations, only shows what the API returns) |

A test (`test_no_metric_math_outside_the_metric_layer`) fails if metric math appears in the API
or the page. If time to hire changes definition, only `definitions.py` changes.

## Access control: how it works and how I know it holds

Rules: a hiring manager sees only requisitions where they are the hiring manager, and the
candidates on them. A recruiter sees only the requisitions they own. Admin sees all
(my assumption, because the brief does not say; it is one branch in `scope_for`).
Anyone else, or an unknown role, sees nothing.

How it is enforced:

1. The token carries only a user id (`sub`), signed with HS256. The algorithm is fixed when reading
   it, and expiry is required, so unsigned, expired or wrongly signed tokens are refused.
2. Role and ownership are never read from the token body, headers or query string. After the token is
   verified, the user is loaded from the database and the list of allowed requisitions is built
   from the database (`access.scope_for`). A token that claims `role: admin` is ignored.
3. That list (a `Scope`) is used inside the SQL of every metric and every data read:
   `list_contains(?, r.req_id)` with a bound parameter. Nothing is fetched first and filtered
   afterwards in Python. An empty scope becomes `FALSE`, so it returns nothing.
4. Asking for a requisition that is not yours returns the same 404 as one that does not exist.
5. The API opens the warehouse read-only, so a bug cannot change data.
6. Candidate lists leave out email and phone number (data minimisation).

How I satisfied myself:

- Metric tests: the numbers for each requisition on its own add up to the unfiltered total
  (nothing leaks in or out); an empty scope sees nothing; a scope value that looks like SQL
  matches nothing.
- API tests: no token, garbage, expired, wrongly signed, unsigned and unknown-user tokens are all refused on
  every endpoint; a hiring manager gets exactly their requisitions; another manager's requisition
  looks exactly like a missing one; extra headers and query parameters (`X-Role`, `user_id`,
  `req_ids`) change nothing; a validly signed token with a forged role stays a hiring manager;
  metrics for a manager match the metric layer called with that manager's scope.
- A real server run with `curl` gave the same results.

What this does not prove: it is not a penetration test. See "Before real users".

## What I left out, on purpose

- SCD Type 2 on requisitions (the extract has no change history for them).
- Incremental loads (each layer is rebuilt; fine for this size, noted in the model doc).
- A React front end and charts (the brief says design is not scored).
- Pagination (a user sees tens of requisitions, not thousands).
- The optional extension.
- A deployed URL (see below).

## Deployment

Not deployed. The brief says not to spend money, and I chose to describe the deployment instead of
risking a bill. The plan: a small container that installs `requirements.txt`, runs the three
pipeline steps and `seed_auth` at start (a few seconds), and runs `uvicorn`. Set `JWT_SECRET`
as a secret environment variable, put it behind the host's HTTPS, and keep `ENABLE_DOCS` off.
Any free host that runs a Python web service would do. I have not tested a specific host.

## Before real users touched it

- HTTPS only, and a real identity provider with single sign-on and multi-factor login, instead of
  passwords stored here. Short-lived tokens with refresh, kept in secure cookies.
- A secrets manager and key rotation. Password reset and a password policy if local passwords stay.
- An audit log of who viewed which candidate. This is personal data.
- Login throttling shared across servers (today it is in memory for one process), plus a gateway rate limit.
- Row-level security in the database too, as a second layer behind the API.
- Encryption at rest, retention rules, and tighter masking of personal data.
- Dependency pinning and scanning, CI that runs the tests, monitoring and alerts, backups.
- Confirm the open data questions in `docs/RECONCILIATION.md` with the client: paise salaries and the
  rounding rule for the acceptance rate.