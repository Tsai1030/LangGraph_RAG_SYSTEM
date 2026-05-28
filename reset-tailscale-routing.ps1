# reset-tailscale-routing.ps1
#
# One-shot script to restore the Tailscale Funnel routing for this project.
# Use when SSE streaming breaks because the /api path rule got wiped
# (any stray `tailscale serve` / `tailscale funnel` command overwrites the
# whole config — Tailscale's CLI mutates global state, not per-rule).
#
# Expected end state:
#   https://kccc3798.tail138ec9.ts.net (Funnel on)
#   |-- /    proxy http://127.0.0.1:3000
#   |-- /api proxy http://localhost:8000/api
#
# Why two rules:
#   /    -> Next.js frontend (3000), serves all pages.
#   /api -> FastAPI backend (8000) directly, bypassing Next.js rewrites
#           because Next.js buffers SSE responses (token streaming breaks).
#   The /api target keeps the `/api` prefix in the URL because Tailscale
#   strips the mount path before forwarding — appending `/api` to the
#   target URL adds it back so backend routes match.

Write-Host ""
Write-Host "Resetting Tailscale serve/funnel config..." -ForegroundColor Cyan

tailscale serve reset

Write-Host "Adding rule: / -> http://localhost:3000 (frontend)" -ForegroundColor Cyan
tailscale funnel --bg http://localhost:3000

Write-Host "Adding rule: /api -> http://localhost:8000/api (backend, SSE-safe)" -ForegroundColor Cyan
tailscale funnel --bg --set-path=/api http://localhost:8000/api

Write-Host ""
Write-Host "Current routing:" -ForegroundColor Green
tailscale serve status

Write-Host ""
Write-Host "Done. Public URL: https://kccc3798.tail138ec9.ts.net" -ForegroundColor Green
Write-Host "If SSE still buffers, hard-refresh the browser (Ctrl+Shift+R)."
Write-Host ""
