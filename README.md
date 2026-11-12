<<<<<<< HEAD
# northbeam-ats
northbeam-assignment
=======
# Northbeam ATS data layer

Bronze / Silver / Gold pipeline over 7 raw ATS files, one metric layer, and a small API.
Status: Bronze done. See PLAN.md for the plan and AGENTS.md for the rules.

## Run
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python -m src.pipeline.bronze      # builds warehouse.duckdb
    pytest -q
>>>>>>> 73d478f (Add raw data, project rules and Bronze loader with tests)
