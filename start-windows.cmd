@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 app.py --port 0 --open
) else (
  python app.py --port 0 --open
)
if errorlevel 1 pause
