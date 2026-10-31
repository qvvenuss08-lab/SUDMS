@echo off
cd /d "%~dp0"
echo === SUDMS connection diagnostics ===
echo.
echo 1. Listening ports:
netstat -ano -p tcp | findstr /C:":5000 " /C:":5055 "
echo.
echo 2. Python processes:
tasklist /FI "IMAGENAME eq python.exe"
echo.
echo 3. HTTP port 5000 without proxy:
curl.exe --noproxy "*" --connect-timeout 5 --max-time 10 -sS -o NUL -w "HTTP status: %%{http_code}\n" http://127.0.0.1:5000/login
echo.
echo 4. HTTP port 5055 without proxy:
curl.exe --noproxy "*" --connect-timeout 5 --max-time 10 -sS -o NUL -w "HTTP status: %%{http_code}\n" http://127.0.0.1:5055/login
echo.
echo Send a screenshot of this window for diagnosis.
pause
