#!/usr/bin/env bash
# One-time setup for Mac and Linux. Run:  bash setup.sh
set -e
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/ and run this again."
  exit 1
fi

echo; echo "===== Step 1 of 4: making the private Python folder (.venv) ====="
[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo; echo "===== Step 2 of 4: installing packages (1 to 3 minutes) ====="
python -m pip install --upgrade pip >/dev/null 2>&1 || true
pip install -r requirements.txt

echo; echo "===== Step 3 of 4: building the data (Bronze, Silver, Gold) ====="
python -m src.pipeline.bronze
python -m src.pipeline.silver
python -m src.pipeline.gold
python -m src.reconciliation

echo; echo "===== Step 4 of 4: creating the demo logins ====="
export DEMO_PASSWORD="${DEMO_PASSWORD:-Northbeam-Demo-2026}"
python -m src.api.seed_auth

cat <<MSG

============================================================
 SETUP FINISHED.  Now run:  bash run.sh
 Then open:  http://127.0.0.1:8000
 Demo password for every user:  $DEMO_PASSWORD
   hiring manager:  uday.varma@northbeam.example
   recruiter:       rahul.singh@northbeam.example
   admin:           simran.jain@northbeam.example
============================================================
MSG
