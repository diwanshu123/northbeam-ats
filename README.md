<<<<<<< HEAD
# northbeam-ats
northbeam-assignment
=======
# Northbeam ATS data layer

Bronze / Silver / Gold pipeline over 7 raw ATS files, one metric layer, and a small API.
Status: Bronze, Silver and Gold done. Next: metric layer, reconciliation, API. See PLAN.md for the plan and AGENTS.md for the rules.

## Run
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python -m src.pipeline.bronze      # raw files -> bronze tables in warehouse.duckdb
    python -m src.pipeline.silver      # bronze -> silver + quarantine tables
    python -m src.pipeline.gold        # silver -> star schema (see docs/MODEL.md)
    pytest -q
>>>>>>> 73d478f (Add raw data, project rules and Bronze loader with tests)
