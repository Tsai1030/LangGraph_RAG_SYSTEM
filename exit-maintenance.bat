@echo off
title Exit Maintenance Mode
cd /d "%~dp0"

echo ============================================
echo   Exiting MAINTENANCE mode
echo ============================================
echo.

echo [1/2] Checking :3000 is released (maintenance server stopped)...
netstat -ano | findstr ":3000 " | findstr LISTENING >nul
if %errorLevel% EQU 0 (
    echo.
    echo   [WARN] :3000 is STILL listening.
    echo          Please close the 'Maintenance Server' window first ^(Ctrl+C inside it^),
    echo          then re-run this script.
    echo.
    pause
    exit /b 1
)
echo   :3000 is free.
echo.

echo [2/2] Starting backend (foreground cmd) and PM2 frontend...
REM Backend runs in foreground cmd window so it inherits the user
REM session's COMODO-trusted parent chain. PM2-spawned python.exe
REM is intermittently blocked by COMODO when connecting to PG.
start "Backend (FastAPI + PostgreSQL)" cmd /k "cd /d %~dp0 && start-backend.bat"
call pm2 start frontend
echo.

echo ============================================
echo   Maintenance mode OFF.
echo   Frontend will be live in ~20 seconds.
echo   URL: https://kccw0077.tail138ec9.ts.net:8443/
echo ============================================
echo.
pause
