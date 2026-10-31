@echo off
cd /d "%~dp0"
echo SUDMS alternate port: http://127.0.0.1:5055/login
echo Keep this window open while using SUDMS.
".venv\Scripts\python.exe" -c "from app import app; app.run(host='127.0.0.1', port=5055, debug=False)"
pause
