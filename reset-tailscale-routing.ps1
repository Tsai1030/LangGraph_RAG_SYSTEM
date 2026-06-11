# reset-tailscale-routing.ps1
#
# One-shot script to restore the Tailscale Funnel routing for this project.
# Use when SSE streaming breaks because the /api path rule got wiped
# (any stray `tailscale serve` / `tailscale funnel` command overwrites the
# whole config — Tailscale's CLI mutates global state, not per-rule).
#
# Expected end state:
#   https://kccw0077.tail138ec9.ts.net:8443 (Funnel on)
#   |-- /    proxy http://127.0.0.1:3000
#   |-- /api proxy http://localhost:8000/api
#
# Why port 8443 (not 443):
#   This machine (kccw0077) runs IIS + SSTP VPN, which already own OS port
#   443 and serve the corporate *.bes.com.tw cert. Funnel on 443 would lose
#   to them, so external visitors got the wrong cert (ERR_TLS_CERT_ALTNAME_
#   INVALID). 8443 is free, so tailscaled serves the correct kccw0077 cert.
#   Public URL therefore carries the :8443 suffix.
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

$cmd = Get-Command tailscale -ErrorAction SilentlyContinue
if ($cmd) {
    $tailscale = $cmd.Source
} else {
    $candidate = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
    if (-not (Test-Path $candidate)) {
        throw "tailscale CLI not found. Expected it at $candidate"
    }
    $tailscale = $candidate
}

& $tailscale serve reset

Write-Host "Adding rule: / -> http://localhost:3000 (frontend)" -ForegroundColor Cyan
& $tailscale funnel --bg --https=8443 http://localhost:3000

Write-Host "Adding rule: /api -> http://localhost:8000/api (backend, SSE-safe)" -ForegroundColor Cyan
& $tailscale funnel --bg --https=8443 --set-path=/api http://localhost:8000/api

Write-Host ""
Write-Host "Current routing:" -ForegroundColor Green
& $tailscale serve status

Write-Host ""
Write-Host "Done. Public URL: https://kccw0077.tail138ec9.ts.net:8443" -ForegroundColor Green
Write-Host "If SSE still buffers, hard-refresh the browser (Ctrl+Shift+R)."
Write-Host ""
