#!/usr/bin/env bash
# Start the app on Mac and Linux. Run:  bash run.sh   (after bash setup.sh)
set -e
cd "$(dirname "$0")"

if [ ! -f .venv/bin/activate ] || [ ! -f warehouse.duckdb ] || [ ! -f auth.duckdb ]; then
  echo "Please run  bash setup.sh  first (it only needs to be done once)."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# A fresh random secret for signing logins, made every time you start.
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"

echo
echo "Starting the app. Open this in your browser:  http://127.0.0.1:8000"
echo "To stop it, press Ctrl+C in this window."
echo
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
