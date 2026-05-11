@echo off
title Construction KB - Start System

REM ========================================================
REM  Auto-elevate (Caddy needs admin to bind port 443)
REM ========================================================
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Requesting admin privilege via UAC...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

REM ========================================================
REM  Ensure PATH contains npm + Node.js
REM  (UAC-elevated session may not inherit User PATH)
REM ========================================================
SET "PATH=%PATH%;%APPDATA%\npm;C:\Program Files\nodejs"

cls
echo ============================================
echo   Construction Knowledge AI - Startup
echo ============================================
echo.

REM Sanity check: pm2 must be reachable
where pm2 >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [ERROR] pm2 not found in PATH.
    echo.
    echo Please verify:
    echo   1. "npm install -g pm2" was run
    echo   2. PATH contains %%APPDATA%%\npm
    echo.
    echo Expected: %APPDATA%\npm\pm2.cmd
    echo.
    pause
    exit /b 1
)

REM ========================================================
REM  1/3 - PM2 (backend + frontend)
REM ========================================================
echo [1/3] Starting PM2 (backend + frontend)...
call pm2 start ecosystem.config.js
if %errorLevel% NEQ 0 (
    echo.
    echo [WARN] PM2 start may have failed; continuing.
)
echo.

REM ========================================================
REM  2/3 - Caddy (minimized background window)
REM ========================================================
echo [2/3] Starting Caddy...
tasklist /FI "IMAGENAME eq caddy.exe" 2>nul | find /I "caddy.exe" >nul
if %errorLevel% EQU 0 (
    echo Caddy already running, skipped.
) else (
    start "Caddy" /MIN cmd /c "cd /d C:\caddy && caddy.exe run --config C:\caddy\Caddyfile"
    timeout /t 2 /nobreak >nul
    echo Caddy started in minimized window. Do NOT close it.
)
echo.

REM ========================================================
REM  3/3 - Tailscale Funnel
REM ========================================================
echo [3/3] Configuring Tailscale Funnel (port 9000)...
tailscale funnel --bg 9000
if %errorLevel% NEQ 0 (
    echo [WARN] Tailscale funnel may have failed.
)
echo.

REM ========================================================
REM  Summary
REM ========================================================
echo ============================================
echo   Startup complete - service status
echo ============================================
echo.

echo --- PM2 ---
call pm2 list
echo.

echo --- Tailscale Funnel ---
tailscale funnel status
echo.

echo ============================================
echo   Public URL
echo ============================================
echo.
echo   https://kccc3798.tail138ec9.ts.net
echo.
echo ============================================
echo.
echo Background services keep running.
echo Closing this window does NOT stop them.
echo.
pause
