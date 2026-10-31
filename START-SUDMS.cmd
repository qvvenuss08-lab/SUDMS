@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment .venv not found. See README.md.
  pause
  exit /b 1
)
echo SUDMS: http://127.0.0.1:5000
echo Keep this window open while using SUDMS.
".venv\Scripts\python.exe" app.py
pause
