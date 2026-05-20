@echo off
title Construction KB - Start System

REM ========================================================
REM  Auto-elevate (Caddy may need admin to bind privileged ports)
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
REM  1/4 - Backend: foreground cmd (NOT PM2)
REM         Why: PM2-spawned python.exe hits COMODO EDR WSAEACCES
REM         when connecting to PostgreSQL on :5432. The user's
REM         interactive shell is COMODO-trusted; spawning backend
REM         from a foreground cmd inherits that trust. Until COMODO
REM         is reconfigured we keep this process tree.
REM ========================================================
echo [1/4] Stopping any old PM2 backend entry, then launching backend in new window...
call pm2 delete backend >nul 2>&1
start "Backend (FastAPI + PostgreSQL)" cmd /k "cd /d %~dp0 && start-backend.bat"
echo   Backend launched in a new cmd window. Do NOT close it.
echo.

REM ========================================================
REM  2/4 - Frontend via PM2 (no COMODO trouble with Next.js)
REM ========================================================
echo [2/4] Resetting + starting PM2 frontend...
call pm2 delete frontend >nul 2>&1
call pm2 start ecosystem.config.js --only frontend
if %errorLevel% NEQ 0 (
    echo [WARN] PM2 frontend start may have failed; continuing.
)
echo.

REM ========================================================
REM  2.5 - Wait until backend:8000 and frontend:3000 truly listen
REM ========================================================
echo Waiting for backend:8000 and frontend:3000 to be ready...
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(90); $ok=$false; while ((Get-Date) -lt $deadline) { $ns = (netstat -ano | Out-String); $b = $ns -match ':8000\s+0\.0\.0\.0:0\s+LISTENING'; $f = $ns -match ':3000\s+0\.0\.0\.0:0\s+LISTENING'; if ($b -and $f) { Write-Host '  Ready: 8000 + 3000 listening' -ForegroundColor Green; $ok=$true; break }; Start-Sleep -Seconds 1 }; if (-not $ok) { Write-Host ('  TIMEOUT after 90s  (8000=' + $b + ' 3000=' + $f + ')') -ForegroundColor Yellow; exit 1 }"
if %errorLevel% NEQ 0 (
    echo [WARN] Ports did not come up in time.
    echo        Check the Backend cmd window for errors,
    echo        and:  pm2 logs frontend --err
)
echo.

REM ========================================================
REM  3/4 - Ensure Caddy is NOT running
REM         (COMODO EDR blocks caddy.exe -> node.exe on this
REM          machine; we proxy /api via Next.js rewrites instead)
REM ========================================================
echo [3/4] Stopping any leftover Caddy...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://localhost:2019/stop' -Method POST -UseBasicParsing -TimeoutSec 3 | Out-Null } catch {}" >nul 2>&1
taskkill /F /IM caddy.exe >nul 2>&1
echo.

REM ========================================================
REM  4/4 - Tailscale Funnel directly to frontend :3000
REM         Next.js handles /api/* itself via next.config.ts rewrites
REM ========================================================
echo [4/4] Configuring Tailscale Funnel (port 3000)...
tailscale funnel reset >nul 2>&1
tailscale funnel --bg 3000
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

echo --- PM2 (frontend only — backend is in a separate cmd window) ---
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
echo NOTE:
echo   Backend runs in the separate 'Backend (FastAPI + PostgreSQL)'
echo   cmd window. Closing THAT window stops the backend.
echo   Closing THIS window does NOT stop services.
echo.
pause
