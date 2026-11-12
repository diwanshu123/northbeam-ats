# PLAN.md - Northbeam ATS take-home

Deadline: 13 Nov 2026. Send repo link to harry@openbi.ai and divyansh@OpenBI.AI.
Time cap: 16 hours over at most 2 days.

## Reconciliation status (profiled before coding)

| # | Control | Naive answer | What fixes it | Result |
|---|---|---|---|---|
| 1 | 560 people | 601 rows (574 by email) | Match on last 10 digits of phone | 560 |
| 2 | 32 at Offer on 2026-03-31 | 151 (current_stage) | Use stage events, order by event_seq, drop invalid requisitions | 32 |
| 3 | median 58 days | 58.54 (fractional days) | Whole calendar days, valid requisitions, 97 hires | 58 |
| 4 | 200,700,000 Engineering salary | 20,070,000,000 | Engineering salaries are in paise: divide by 100 | 200,700,000 |
| 5 | 51.2% acceptance | 52.1% | Exclude offers on invalid requisitions, and open offers | 51.2% |

Not yet checked: interviews.json (not used in the 5 numbers), users.json mapping,
and whether people matched by phone also need an email-based merge.
Re-prove every row of this table from the Gold layer. A profiling script is not the answer.

## Gold model (proposal, change if the data says otherwise)

- dim_person (one row per real person) - surrogate key, matched on phone
- dim_requisition (one row per requisition)
- dim_user (one row per user)
- dim_date
- fact_application (grain: one row per application)
- fact_stage_history (grain: one row per stage change of an application, with valid_from, valid_to)
- fact_offer (grain: one row per offer)
- fact_interview (grain: one row per interview)
- quarantine_application (applications without a valid requisition, with reason)

## Estimate vs actual (fill the Actual column as you go)

| # | Section | Estimate (h) | Actual (h) |
|---|---|---|---|
| 0 | Setup, data profiling, AGENTS.md, plan | 1 | |
| 1 | Bronze / Silver / Gold pipeline | 3 | |
| 2 | Star schema with stage history | 2 | |
| 3 | Reconciliation + note | 2.5 | |
| 4 | Metric layer | 1.5 | |
| 5 | API, login, access rules, thin frontend | 3.5 | |
| 6 | Deployment (run locally, write the plan) | 0.5 | |
| 7 | Worklog + README | 1.5 | |
| 8 | Estimate table + buffer | 0.5 | |
| | Total | 16 | |

Two lines at the end: where I was most wrong, and why.

## Prompts for the agent (give them one at a time, commit after each)

1. "Read AGENTS.md. Create the folder layout and a pyproject/requirements file.
   Do not write pipeline code yet. Show me the plan for bronze.py first."
2. "Write bronze.py. Load all 7 files as landed into DuckDB with loaded_at and
   source_file. Re-running must not duplicate rows. Add a test that runs it twice."
3. "Write silver.py using the data traps in AGENTS.md. Quarantine bad rows with a reason.
   Print row counts in, out and quarantined for each table."
4. "Write gold.py with the tables in PLAN.md. State the grain of each fact table in a
   comment. Build fact_stage_history with valid_from and valid_to."
5. "Write src/metrics/definitions.py with the 4 metrics from AGENTS.md. Write a test
   that checks the 5 control totals using only this file."
6. "Write the FastAPI app: login (JWT), /metrics, /requisitions. Enforce access in the
   SQL query using the user from the token. Write tests where manager A asks for
   manager B's data and gets 404."
7. "Write web/index.html: login box, 4 or 5 numbers, one table. No calculations."

After each prompt: read the diff, run the tests, and write one line in docs/WORKLOG.md
about anything the agent got wrong. Specific notes score. Generic notes score zero.

## Do not cut
Reconciliation, metric layer (defined once), stage history, access control with tests,
worklog, estimate table.

## Cut first
Frontend polish, deployment (describe it in README), the extension (skip it).
