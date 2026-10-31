@echo off
cd /d "%~dp0"
set "SUDMS_HTTPS=0"
".venv\Scripts\python.exe" serve.py --host 0.0.0.0 --port 5057
pause
