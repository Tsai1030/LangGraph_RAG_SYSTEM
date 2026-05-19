# CIM-free version, ASCII-only. Uses netsh + netstat + curl.
# Run from ADMIN PowerShell:
#   cd C:\Users\226376\Desktop\data
#   powershell -ExecutionPolicy Bypass -File .\fix-caddy-blocked.ps1

$ErrorActionPreference = "Continue"

function Sec($t) { Write-Host ""; Write-Host "==== $t ====" -ForegroundColor Cyan }

# 0. Admin check
Sec "0. Admin check"
$adm = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host "  IsAdmin: $adm"
if (-not $adm) { Write-Host "  ABORT: run as admin." -ForegroundColor Red; exit 1 }

$ruleNames = @(
    'codex_sandbox_offline_block_loopback_tcp',
    'codex_sandbox_offline_block_loopback_udp'
)

# 1. Try to delete via netsh (idempotent — netsh prints an error if rule doesn't exist, which is fine)
Sec "1. Delete codex_sandbox rules"
foreach ($name in $ruleNames) {
    Write-Host ""
    Write-Host "  > netsh advfirewall firewall delete rule name=$name" -ForegroundColor DarkGray
    $out = & netsh advfirewall firewall delete rule name=$name 2>&1
    foreach ($line in $out) { Write-Host "    $line" }
    Write-Host "    (exit code: $LASTEXITCODE)" -ForegroundColor DarkGray
}

# 2. Verify by listing
Sec "2. Verify rules gone"
foreach ($name in $ruleNames) {
    $out = (& netsh advfirewall firewall show rule name=$name 2>&1) -join "`n"
    # netsh returns exit code 1 when no rule found
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  GONE: $name" -ForegroundColor Green
    } else {
        Write-Host "  STILL PRESENT: $name" -ForegroundColor Red
        Write-Host $out
    }
}

# 3. Port listener check
Sec "3. Port listeners"
$ns = (netstat -ano | Out-String)
foreach ($p in 8000,3000,9000) {
    if ($ns -match ":$p\s+0\.0\.0\.0:0\s+LISTENING\s+(\d+)") {
        Write-Host "  :$p listening  (PID $($Matches[1]))" -ForegroundColor Green
    } else {
        Write-Host "  :$p NOT listening" -ForegroundColor Yellow
    }
}

# 4. End-to-end test
Sec "4. Test Caddy -> upstream"
$caddyUp = $ns -match ':9000\s+0\.0\.0\.0:0\s+LISTENING'
if (-not $caddyUp) {
    Write-Host "  Caddy not on :9000. Start it then re-run this script."
} else {
    $r1 = (curl.exe -s -o NUL -w "%{http_code}" --max-time 5 http://127.0.0.1:9000/api/health 2>&1)
    Write-Host "  GET 9000/api/health  HTTP $r1"
    $r2 = (curl.exe -s -o NUL -w "%{http_code}" --max-time 5 http://127.0.0.1:9000/ 2>&1)
    Write-Host "  GET 9000/           HTTP $r2"
    if ($r2 -eq '502') {
        Write-Host ""
        Write-Host "  Still 502 on frontend." -ForegroundColor Red
        Write-Host "  -> COMODO EDR is likely blocking caddy.exe -> node.exe."
        Write-Host "  Open COMODO UI -> Settings -> Firewall -> Application Rules"
        Write-Host "  Find C:\caddy\caddy.exe and set 'Trusted Application' (or allow outbound)."
        Write-Host "  Or temporarily disable COMODO Firewall to confirm it's the cause."
    } elseif ($r2 -in '200','301','302','307','308') {
        Write-Host "  SUCCESS - refresh the browser now." -ForegroundColor Green
    }
}

Sec "Done"
