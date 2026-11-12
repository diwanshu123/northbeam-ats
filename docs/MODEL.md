# Gold model (star schema)

Built by `src/pipeline/gold.py` from the silver tables. Surrogate keys (`*_sk`) are integers
made from the natural key order, so a re-run gives the same keys.

## Fact tables and their grain

| Table | Grain (one row per...) |
|---|---|
| `fact_application` | application tied to a valid requisition |
| `fact_stage_history` | stage an application sat in (one per stage-change event), with `valid_from` / `valid_to` |
| `fact_offer` | offer made against a valid application |
| `fact_interview` | scheduled interview against a valid application |

## Dimensions

| Table | Meaning |
|---|---|
| `dim_person` | one row per real person (601 candidate records -> 560 people, matched on phone) |
| `dim_requisition` | one row per requisition, with hiring manager and recruiter ids (used for access control) |
| `dim_user` | recruiters, hiring managers, admins |
| `dim_stage` | the 7 stages with their order and whether they end the process |
| `dim_date` | one row per calendar day in the data range |

## Stage history, not a stage column

`fact_stage_history` stores every stage an application was in and for how long.
`valid_to` is empty for the current stage (`is_current = true`). The stage on any date is the
row whose interval covers that date. The one place this logic is written is
`src/metrics/definitions.py`.

`fact_application.reported_stage` is the source system's own `current_stage` column.
It disagrees with the events for 96 applications, so it is kept only as evidence and
must not be used for reporting. `latest_stage` is the last stage from the events.

## Deliberate choices

- Applications whose requisition does not exist are quarantined (`quarantine_applications`,
  23 rows) and are not in Gold. Their events, offers and interviews are quarantined too.
- Candidates who appear more than once are one row in `dim_person`; each application points
  to the person, so counting people never counts records.
- Engineering salaries were stored in paise in the source. `fact_offer.annual_salary_inr` is
  already in rupees (`salary_was_paise` marks the converted rows).
- Not done: SCD Type 2 on `dim_requisition` (the extract has no change history for it).
- Seen, not changed: 58 pairs where the same candidate record applied to the same
  requisition more than once. The control totals tie without merging them.
