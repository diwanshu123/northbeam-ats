Subject: OpenBI take-home exercise - Diwanshu - repository link

Hello Harry and Divyansh,

Here is my submission for the AI & Analytics Engineer exercise.

Repository: https://github.com/diwanshu123/northbeam-ats

How to run it: read SETUP.md. On Windows run setup.bat and then run.bat. On Mac or Linux run bash setup.sh and then bash run.sh. It needs only Python, and the demo password is in SETUP.md.

What is in it:
- Bronze, Silver and Gold pipeline in DuckDB. Re-running does not duplicate rows.
- Gold is a star schema. Stage is a history table, so "at Offer on 31 March" can be answered.
- All five control totals tie: 560, 32, 58, 200,700,000 and 51.2. docs/RECONCILIATION.md explains what each wrong answer was and why. Two points still need the client to confirm: the Engineering salaries look like paise, and 51.2 only ties with round-half-to-even (the exact value is 51.25).
- One metric layer (src/metrics/definitions.py). A test fails if metric math appears anywhere else.
- FastAPI with login and a thin page. Access is enforced inside the SQL, using a scope built on the server from the logged-in user. The README explains how I checked it cannot be bypassed.
- 48 tests.

What I left out: deployment (the README describes the plan, to avoid any cost), SCD Type 2, incremental loads, and the optional extension.

How I used AI: I built this in a Claude chat session, not in a terminal coding agent, because I wanted to avoid a paid subscription. docs/WORKLOG.md says plainly what the AI did, what I ran and checked myself, and the mistakes that were caught. I would use a terminal agent next time and write the plan and prompts myself.

Thank you for your time. I am ready for the 60-minute review.

Best regards,
Diwanshu