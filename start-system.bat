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
REM  1/4 - PM2: clean slate then start backend + frontend
REM         (delete first to clear zombie entries from prior run)
REM ========================================================
echo [1/4] Resetting PM2 and starting backend + frontend...
call pm2 delete all >nul 2>&1
call pm2 start ecosystem.config.js
if %errorLevel% NEQ 0 (
    echo [WARN] PM2 start may have failed; continuing.
)
echo.

REM ========================================================
REM  2/4 - Wait until backend:8000 and frontend:3000 truly listen
REM         (Caddy must NOT start before these ports are open,
REM          otherwise it can cache failure and keep returning 502)
REM ========================================================
echo [2/4] Waiting for backend:8000 and frontend:3000 to be ready...
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(90); $ok=$false; while ((Get-Date) -lt $deadline) { $b = (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) -ne $null; $f = (Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue) -ne $null; if ($b -and $f) { Write-Host '  Ready: 8000 + 3000 listening' -ForegroundColor Green; $ok=$true; break }; Start-Sleep -Seconds 1 }; if (-not $ok) { Write-Host ('  TIMEOUT after 90s  (8000=' + $b + ' 3000=' + $f + ')') -ForegroundColor Yellow; exit 1 }"
if %errorLevel% NEQ 0 (
    echo [WARN] Ports did not come up in time; Caddy will serve 502 until they do.
    echo        Check: pm2 logs backend --err   /   pm2 logs frontend --err
)
echo.

REM ========================================================
REM  3/4 - Caddy: stop any old instance, then start fresh
REM         (avoids stale connection state if Caddy was running
REM          while upstreams were down)
REM ========================================================
echo [3/4] Restarting Caddy...
REM Graceful stop via admin API (no error if Caddy is not running)
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://localhost:2019/stop' -Method POST -UseBasicParsing -TimeoutSec 3 | Out-Null } catch {}" >nul 2>&1
REM Belt-and-suspenders kill in case admin API was unreachable
taskkill /F /IM caddy.exe >nul 2>&1
timeout /t 1 /nobreak >nul
start "Caddy" /MIN cmd /c "cd /d C:\caddy && caddy.exe run --config C:\caddy\Caddyfile"
echo   Caddy launched in minimized window. Do NOT close it.
REM Wait for 9000 to bind
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(15); $ok=$false; while ((Get-Date) -lt $deadline) { if (Get-NetTCPConnection -State Listen -LocalPort 9000 -ErrorAction SilentlyContinue) { Write-Host '  Caddy listening on :9000' -ForegroundColor Green; $ok=$true; break }; Start-Sleep -Seconds 1 }; if (-not $ok) { Write-Host '  Caddy did not bind :9000 within 15s' -ForegroundColor Yellow; exit 1 }"
echo.

REM ========================================================
REM  4/4 - Tailscale Funnel
REM ========================================================
echo [4/4] Configuring Tailscale Funnel (port 9000)...
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
