@echo off
title Enter Maintenance Mode
cd /d "%~dp0"

echo ============================================
echo   Switching site to MAINTENANCE mode
echo ============================================
echo.

echo [1/3] Stopping PM2 frontend + backend...
call pm2 stop frontend >nul 2>&1
call pm2 stop backend >nul 2>&1
echo   Done.
echo.

echo [2/3] Waiting for :3000 to release...
:wait_release
netstat -ano | findstr ":3000 " | findstr LISTENING >nul 2>&1
if %errorLevel% EQU 0 (
    timeout /t 1 /nobreak >nul
    goto wait_release
)
echo   :3000 is free.
echo.

echo [3/3] Launching maintenance HTTP server on :3000...
start "Maintenance Server - DO NOT CLOSE during migration" cmd /k "%~dp0backend\.venv\Scripts\python.exe %~dp0maintenance_server.py"
timeout /t 2 /nobreak >nul

REM Sanity check the server actually bound
netstat -ano | findstr ":3000 " | findstr LISTENING >nul
if %errorLevel% NEQ 0 (
    echo   [WARN] :3000 did not bind. Check the 'Maintenance Server' window for errors.
) else (
    echo   :3000 is now serving the maintenance page.
)
echo.

echo ============================================
echo   Maintenance mode is ACTIVE
echo ============================================
echo   URL: https://kccw0077.tail138ec9.ts.net:8443/
echo.
echo   When migration is done:
echo     1. Close the 'Maintenance Server' window  (Ctrl+C inside it)
echo     2. Run  exit-maintenance.bat
echo ============================================
echo.
pause
