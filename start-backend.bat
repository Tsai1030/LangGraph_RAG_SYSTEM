@echo off
title Backend (FastAPI + PostgreSQL)
cd /d "%~dp0backend"

REM ─────────────────────────────────────────────────────────────
REM Launch backend in foreground cmd. Foreground parent chain is
REM (cmd.exe → uv.exe → python.exe), which COMODO EDR trusts
REM consistently. PM2-spawned python (parent = pm2 node daemon)
REM intermittently fails to connect to PostgreSQL on :5432 with
REM WSAEACCES 10013. Until COMODO is reconfigured, keep this
REM process tree.
REM
REM Close this window or Ctrl+C to stop the backend.
REM ─────────────────────────────────────────────────────────────

echo ============================================
echo   Backend starting...
echo   Logs will stream below. Do NOT close this
echo   window if you want the backend to stay up.
echo ============================================
echo.

uv run python run_server.py

REM If uv exits, pause so user can read the error
echo.
echo ============================================
echo   Backend stopped. Press any key to close.
echo ============================================
pause >nul
