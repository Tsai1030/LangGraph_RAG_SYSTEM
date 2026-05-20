@echo off
title Backend - FastAPI + PostgreSQL
cd /d "%~dp0backend"

REM Launch backend in foreground cmd. Foreground parent chain is
REM (cmd.exe -> uv.exe -> python.exe), which COMODO EDR trusts.
REM PM2-spawned python.exe fails to connect to PostgreSQL on :5432
REM with WSAEACCES 10013 because COMODO does not trust pm2's
REM process chain. Until COMODO is reconfigured, keep this layout.
REM
REM Close this window or Ctrl+C to stop the backend.

echo ============================================
echo   Backend starting...
echo   Logs stream below. Do NOT close this
echo   window if you want backend to stay up.
echo ============================================
echo.

uv run python run_server.py

echo.
echo ============================================
echo   Backend stopped. Press any key to close.
echo ============================================
pause >nul
