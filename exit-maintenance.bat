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

echo [2/2] Starting PM2 backend + frontend...
call pm2 start backend
call pm2 start frontend
echo.

echo ============================================
echo   Maintenance mode OFF.
echo   Frontend will be live in ~20 seconds.
echo   URL: https://kccc3798.tail138ec9.ts.net/
echo ============================================
echo.
pause
