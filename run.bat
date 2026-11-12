@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\activate.bat goto needsetup
if not exist warehouse.duckdb goto needsetup
if not exist auth.duckdb goto needsetup

call .venv\Scripts\activate.bat

rem A fresh random secret for signing logins, made every time you start.
for /f %%i in ('python -c "import secrets; print(secrets.token_urlsafe(48))"') do set JWT_SECRET=%%i

echo.
echo Starting the app. Open this in your browser:  http://127.0.0.1:8000
echo To stop it, press Ctrl+C in this window.
echo.
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
exit /b 0

:needsetup
echo.
echo Please run setup.bat first (it only needs to be done once).
exit /b 1
