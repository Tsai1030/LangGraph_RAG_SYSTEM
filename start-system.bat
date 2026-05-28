@echo off
title Construction KB - Start System
setlocal enableextensions

REM ========================================================
REM  start-system.bat
REM
REM  What this DOES (automated):
REM    1. PM2 frontend (Next.js on :3000)
REM    2. Tailscale Funnel routing (/ -> 3000, /api -> 8000/api)
REM
REM  What this does NOT do (manual, COMODO-imposed):
REM    Backend (FastAPI on :8000). COMODO EDR distrusts both
REM    PM2-spawned python and double-clicked start-backend.bat.
REM    Only an interactive IDE terminal launch survives COMODO's
REM    parent-chain check. So you must run it yourself:
REM
REM        cd C:\Users\226376\Desktop\data\backend
REM        uv run python run_server.py
REM
REM    The IDE terminal that runs that command MUST stay open.
REM ========================================================

REM Auto-elevate (UAC) -- some PM2 / Tailscale ops want admin.
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Requesting admin privilege via UAC...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

REM UAC-elevated session may not inherit User PATH.
SET "PATH=%PATH%;%APPDATA%\npm;C:\Program Files\nodejs"

cls
echo ============================================
echo   Construction Knowledge AI - Startup
echo ============================================
echo.

REM Sanity check: pm2 must be reachable.
where pm2 >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [ERROR] pm2 not found in PATH.
    echo   1. "npm install -g pm2" was run?
    echo   2. PATH contains %%APPDATA%%\npm ?
    pause
    exit /b 1
)

REM ========================================================
REM  1/3 - Frontend via PM2
REM ========================================================
echo [1/3] Resetting + starting PM2 frontend...
call pm2 delete frontend >nul 2>&1
call pm2 start ecosystem.config.js --only frontend
if %errorLevel% NEQ 0 (
    echo [WARN] PM2 frontend start may have failed. Check: pm2 logs frontend --err
)
echo.

REM ========================================================
REM  2/3 - Tailscale Funnel routing
REM         /    -> 3000 (Next.js)
REM         /api -> 8000/api (FastAPI direct -- SSE-safe, bypasses Next.js buffer)
REM ========================================================
echo [2/3] Configuring Tailscale Funnel...
tailscale serve reset >nul 2>&1
tailscale funnel --bg http://localhost:3000
tailscale funnel --bg --set-path=/api http://localhost:8000/api
if %errorLevel% NEQ 0 (
    echo [WARN] Tailscale funnel command failed. Run reset-tailscale-routing.ps1 manually.
)
echo.

REM ========================================================
REM  3/3 - Wait for :3000 and check :8000 (info only)
REM ========================================================
echo [3/3] Waiting up to 60s for frontend :3000 to listen...
powershell -NoProfile -Command "$d=(Get-Date).AddSeconds(60); $ok=$false; while ((Get-Date) -lt $d) { if (Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue) { Write-Host '  Frontend :3000 LISTENING' -ForegroundColor Green; $ok=$true; break }; Start-Sleep -Seconds 1 }; if (-not $ok) { Write-Host '  TIMEOUT waiting for :3000 -- check pm2 logs frontend' -ForegroundColor Yellow }"

echo.
echo Checking backend :8000...
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) { Write-Host '  Backend  :8000 LISTENING (good)' -ForegroundColor Green } else { Write-Host '  Backend  :8000 NOT listening -- start it manually in your IDE terminal:' -ForegroundColor Yellow; Write-Host '      cd C:\Users\226376\Desktop\data\backend' -ForegroundColor Yellow; Write-Host '      uv run python run_server.py' -ForegroundColor Yellow }"
echo.

REM ========================================================
REM  Summary
REM ========================================================
echo ============================================
echo   Startup status
echo ============================================
echo.

echo --- PM2 (frontend only -- backend runs in your IDE terminal) ---
call pm2 list
echo.

echo --- Tailscale Funnel ---
tailscale serve status
echo.

echo ============================================
echo   Public URL: https://kccc3798.tail138ec9.ts.net
echo ============================================
echo.
echo REMINDER:
echo   If backend :8000 is NOT listening above, open your IDE terminal:
echo       cd %~dp0backend
echo       uv run python run_server.py
echo   Keep that terminal open -- closing it stops backend.
echo.
echo   If SSE breaks (responses appear all-at-once instead of token-by-token),
echo   run:   powershell -ExecutionPolicy Bypass -File reset-tailscale-routing.ps1
echo.
pause
