# Reconciliation note

All five figures are produced by `src/metrics/definitions.py` and compared with
`data/raw/CONTROL_TOTALS.txt` by `python -m src.reconciliation` (also a pytest test).
No number was adjusted to fit. Where my first answer was wrong, the cause is below.

| # | Control | Mine | Ties |
|---|---|---|---|
| 1 | Unique people in the candidate pool | 560 | yes |
| 2 | Applications at Offer as at 2026-03-31 | 32 | yes |
| 3 | Median time to hire, days (hires 1 Jan - 30 Jun 2026) | 58 | yes |
| 4 | Total annual offered salary, Engineering, INR | 200,700,000 | yes |
| 5 | Offer acceptance rate, % | 51.2 | yes |

## 1. Unique people: 560

- Plausible wrong answers: 601 (candidate records), 574 (unique emails), 466 (unique names).
- Cause: one person can have several candidate records, with different candidate_id and
  sometimes a different email. Every phone number has the same format, so the phone is the
  stable identifier.
- Action: person key = last 10 digits of the phone. Silver keeps all 601 records and points
  each at its person; `dim_person` has one row per person.
- Not checked: whether two phone numbers could belong to one person (24 emails have more than
  one phone). The control total matches without merging them, so I left them separate.

## 2. Applications at Offer on 2026-03-31: 32

- Plausible wrong answers: 151 (applications whose current_stage is Offer today), 43 (from
  history, but counting 11 applications with no valid requisition), 39 (ordering events by
  timestamp alone).
- Cause: `current_stage` is today's position, not the position on 31 March. 23 applications point to
  requisitions that do not exist. 60 applications have two or more events in the same second,
  so the timestamp cannot decide their order; `event_seq` can. (The same-second ties are my
  explanation for the 39; I did not trace each case.)
- Action: stage history with `valid_from` / `valid_to` built in `event_seq` order, quarantine
  of applications without a valid requisition. The metric reads the interval that covers the
  close of the day.

## 3. Median time to hire: 58 days

- Plausible wrong answers: 58.5 (fractional days from the timestamps), 59.0 (fractional days
  with the 7 hires on invalid requisitions included, 104 hires instead of 97).
- Cause: the control counts whole calendar days (date of hire minus date of application) and
  only hires tied to a valid requisition. Also, 24 applications have a Hired event but a
  different `current_stage`, so hires must come from events, not from the column.
- Action: median of whole calendar days between the application date and the Hired event date,
  97 hires.

## 4. Engineering offered salary: 200,700,000 INR

- Plausible wrong answers: 20,070,000,000 (100 times too large), 20,330,000,000 (using the
  offer's own department column and not checking the requisition).
- Cause: every Engineering offer is stored in paise, not rupees (smallest value 90,000,000, while
  every other department is at most 3,000,000). Dividing by 100 gives exactly the control.
  The offer's department column can also disagree with the requisition's department.
- Action: Silver divides Engineering salaries by 100 and keeps the raw value
  (`annual_salary_raw`, `salary_was_paise`). The metric uses the requisition's department and
  counts offers of any status.
- Open question for the client: the paise assumption is inferred from the values and from the
  control total. It should be confirmed with whoever owns the ATS export.

## 5. Offer acceptance rate: 51.2%

- Plausible wrong answers: 52.1 (including 10 decided offers on invalid requisitions), and any
  rate that treats open offers as decided, because every open offer still carries a decided_at date.
- Cause and action: use `status`, not `decided_at`. Accepted / (accepted + declined) = 164 / 320.
- Rounding: 164 / 320 is exactly 51.25, a tie. The control (51.2) only ties with round-half-to-even
  (or by cutting off the second decimal). Round-half-up would give 51.3. I fixed the rule in one
  place (`_pct` in `definitions.py`) and a test locks it. This should be confirmed with the client,
  because it means the control was produced with a specific rounding rule.

## Seen, not changed

- 58 pairs where the same candidate record applied to the same requisition more than once.
  The controls tie without merging them.
- 96 applications where `current_stage` disagrees with the last event. The column is kept in
  Gold as `reported_stage` as evidence only.
- The hires period-over-period comparison for the first half of 2026 looks at 4 Jul - 31 Dec 2025, and the extract
  starts on 4 Sep 2025, so the earlier period is incomplete (9 hires against 97). Treat the
  percentage change with care.
