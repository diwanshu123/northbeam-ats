@echo off
setlocal
cd /d "%~dp0"

echo.
echo ===== Step 1 of 5: checking Python =====
python --version >nul 2>&1
if errorlevel 1 goto nopython

echo.
echo ===== Step 2 of 5: making the private Python folder (.venv) =====
if not exist .venv\Scripts\activate.bat python -m venv .venv
if errorlevel 1 goto fail
call .venv\Scripts\activate.bat
if errorlevel 1 goto fail

echo.
echo ===== Step 3 of 5: installing packages (1 to 3 minutes) =====
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 goto fail

echo.
echo ===== Step 4 of 5: building the data (Bronze, Silver, Gold) =====
python -m src.pipeline.bronze
if errorlevel 1 goto fail
python -m src.pipeline.silver
if errorlevel 1 goto fail
python -m src.pipeline.gold
if errorlevel 1 goto fail
python -m src.reconciliation
if errorlevel 1 goto fail

echo.
echo ===== Step 5 of 5: creating the demo logins =====
if "%DEMO_PASSWORD%"=="" set DEMO_PASSWORD=Northbeam-Demo-2026
python -m src.api.seed_auth
if errorlevel 1 goto fail

echo.
echo ============================================================
echo  SETUP FINISHED.  Now run:  run.bat
echo  Then open:  http://127.0.0.1:8000
echo  Demo password for every user:  %DEMO_PASSWORD%
echo    hiring manager:  uday.varma@northbeam.example
echo    recruiter:       rahul.singh@northbeam.example
echo    admin:           simran.jain@northbeam.example
echo ============================================================
exit /b 0

:nopython
echo.
echo Python was not found.
echo 1. Install Python 3.10 or newer from https://www.python.org/downloads/
echo 2. In the installer, TICK the box "Add python.exe to PATH".
echo 3. Close this window, open a NEW one, and run setup.bat again.
exit /b 1

:fail
echo.
echo Something went wrong in the step above. Read the last lines above this message.
echo Common fix: close this window, open a new one, and run setup.bat again.
exit /b 1
