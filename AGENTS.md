# AGENTS.md - Northbeam ATS data layer (OpenBI take-home)

Read this file first. Follow it in every task.
If a rule here conflicts with a prompt, stop and ask.

## Goal
Build a Bronze/Silver/Gold data layer over 7 raw ATS files, one metric layer,
and a small API + frontend with role-based access. Hit 5 control totals exactly.
Time cap is 16 hours, so keep everything thin. Less code is better.

## Stack (do not add more without asking)
- Python 3.11, DuckDB (single file: warehouse.duckdb), pandas only for reading xlsx
- FastAPI for the API, JWT for login, pytest for tests
- Frontend: one static HTML + JS page served by FastAPI. No build step. No math in it.
- No paid services. No secrets in the repo (use .env, add .env to .gitignore).

## Folder layout
data/raw/                 the 7 input files (never edit them)
src/pipeline/bronze.py    load as landed + loaded_at + source_file
src/pipeline/silver.py    clean, type, dedupe, quarantine bad rows
src/pipeline/gold.py      star schema
src/metrics/definitions.py   THE ONLY place metric math lives
src/api/                  FastAPI app, auth, access control
web/index.html            thin frontend
tests/                    pytest
docs/RECONCILIATION.md    figure vs control, cause, action
docs/WORKLOG.md           what I delegated, what I did not, one agent mistake

## Hard rules
1. Metric math exists once, in src/metrics/definitions.py. API imports it.
   Frontend only shows numbers the API returns. No second copy anywhere.
2. Pipeline is idempotent: running it twice gives identical row counts. Test this.
3. A stage is a history. Gold has a stage-history fact (one row per stage change,
   with valid_from / valid_to). Never answer "as at date" questions from current_stage.
4. Bad rows go to quarantine_* tables with a reason column. Never delete silently.
5. Never change a number to match a control total. If it does not tie, find the cause
   and write it in docs/RECONCILIATION.md.
6. Access control is enforced in the query layer using the user from the verified
   token, never from a request parameter. A hiring manager sees only their own
   requisitions and candidates. A recruiter sees only requisitions they own.
   Another user's ID returns 404.
7. Small commits, each with a message saying what and why.

## Known data traps (found by profiling before any code was written)
- candidates.csv: 601 rows, but 560 people. Same person appears with different
  candidate_id and sometimes different email. Match on the last 10 digits of phone.
  Email alone gives 574 (wrong). Name alone gives 466 (wrong). Names have extra spaces.
- applications.csv: 23 rows point to req_id values that are not in requisitions.json
  (REQ-2xxx). Quarantine them. Exclude them from all five control totals.
- applications.current_stage is not trustworthy: 24 applications have a Hired event
  but a different current_stage. Use stage_events.
- stage_events.csv: 60 applications have two or more events in the same second.
  Order by event_seq, never by timestamp alone.
- offers.xlsx: all 111 Engineering salaries are 100x too large (paise, not rupees).
  Divide by 100. Other departments are max 3,000,000.
- offers.xlsx: all 91 "open" offers still have a decided_at date. Use status, not decided_at.
- offers.department can disagree with the requisition's department. Use the
  requisition's department.

## Metric definitions (agreed)
- Time to hire (days): whole calendar days from date(applied_at) to date(Hired event),
  hires between 2026-01-01 and 2026-06-30, valid requisitions only. Report the median.
- Offer acceptance rate: accepted / (accepted + declined). Open offers excluded.
- Stage "as at" date: last event with event_seq order up to end of that day.
