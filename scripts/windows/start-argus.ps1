# Argus CLI Startup Script (Windows)
# Starts Redis, Celery workers, and launches the Argus CLI
#
# Usage: .\scripts\windows\start-argus.ps1
#        .\scripts\windows\start-argus.ps1 -NoTui
#        .\scripts\windows\start-argus.ps1 -Target example.com

param(
    [switch]$NoTui,
    [string]$Target = ""
)

$ScriptDir = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
Set-Location $ScriptDir

function Log-Info  { Write-Host "[INFO] $args" -ForegroundColor Blue }
function Log-Ok    { Write-Host "[OK]   $args" -ForegroundColor Green }
function Log-Warn  { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Log-Error { Write-Host "[FAIL] $args" -ForegroundColor Red }

function Die {
    Log-Error $args[0]
    Write-Host "Run .\scripts\windows\stop-argus.ps1 to clean up." -ForegroundColor Yellow
    exit 1
}

Write-Host "╔════════════════════════════════════════╗" -ForegroundColor Blue
Write-Host "║     Argus Security AI Agent            ║" -ForegroundColor Blue
Write-Host "╚════════════════════════════════════════╝" -ForegroundColor Blue
Write-Host ""

Write-Host "━━━ Checking Prerequisites ━━━" -ForegroundColor Yellow

$PyVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Die "Python 3 is not installed or not in PATH"
}
Log-Ok $PyVersion

$RedisExe = Join-Path $ScriptDir "redis\redis-cli.exe"
$RedisPing = & $RedisExe ping 2>$null
if ($LASTEXITCODE -eq 0 -and $RedisPing -eq "PONG") {
    Log-Ok "Redis running"
} else {
    Log-Warn "Redis not running, attempting to start..."
    $RedisServer = Join-Path $ScriptDir "redis\redis-server.exe"
    $RedisConf = Join-Path $ScriptDir "redis\redis.windows.conf"
    if (Test-Path $RedisServer) {
        $proc = Start-Process -FilePath $RedisServer -ArgumentList $RedisConf -PassThru -NoNewWindow
        Start-Sleep 2
        $ping = & $RedisExe ping 2>$null
        if ($ping -eq "PONG") {
            Log-Ok "Redis started"
        } else {
            Die "Could not start Redis from $RedisServer"
        }
    } else {
        Die "Redis not found at $RedisServer. Make sure redis/ is present."
    }
}

New-Item -ItemType Directory -Path "$ScriptDir\logs" -Force | Out-Null
Log-Ok "Log directory ready"

Write-Host ""
Write-Host "━━━ Starting Celery Workers ━━━" -ForegroundColor Yellow

Set-Location "$ScriptDir\argus-workers"

$VenvDir = "$ScriptDir\argus-workers\venv"
if (-not (Test-Path "$VenvDir\Scripts\python.exe")) {
    Log-Warn "Virtual environment not found. Creating one..."
    python -m venv $VenvDir | Out-Null
    if (-not (Test-Path "$VenvDir\Scripts\python.exe")) {
        Die "Failed to create Python venv"
    }
}

$PythonExe = "$VenvDir\Scripts\python.exe"
$PipExe = "$VenvDir\Scripts\pip.exe"

if (Test-Path "requirements.txt") {
    Log-Info "Checking Python dependencies..."
    $imports = & $PythonExe -c "import celery, redis" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Log-Warn "Missing dependencies — installing..."
        & $PipExe install -q -r requirements.txt 2>&1 | Out-Null
    }
}

$Env:PYTHONPATH = "$pwd;$Env:PYTHONPATH"

if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match "^\s*([^#].*?)\s*=\s*(.*)" -and $_ -notmatch "^\s*#") {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

$CeleryLog = "$ScriptDir\logs\celery.log"
$celery = Start-Process -FilePath $PythonExe -ArgumentList "-m celery -A celery_app worker --loglevel=info --concurrency=4 --prefetch-multiplier=1 -Q celery,recon,scan,analyze,report,repo_scan" -PassThru -NoNewWindow -RedirectStandardOutput $CeleryLog -RedirectStandardError $CeleryLog
$CeleryPid = $celery.Id
Set-Location $ScriptDir

Start-Sleep 3
$celeryRunning = Get-Process -Id $CeleryPid -ErrorAction SilentlyContinue
if (-not $celeryRunning) {
    Die "Celery failed to start. Check logs/celery.log"
}
$CeleryPid | Out-File -FilePath "$ScriptDir\logs\celery.pid" -Encoding ASCII
Log-Ok "Celery workers started (PID: $CeleryPid)"

Write-Host ""
Write-Host "━━━ Launching Argus CLI ━━━" -ForegroundColor Yellow

$importCheck = & $PythonExe -c "import argus_cli" 2>&1
if ($LASTEXITCODE -ne 0) {
    Log-Warn "argus-cli not installed — installing..."
    & $PipExe install -e "$ScriptDir\argus-cli" 2>&1 | Out-Null
}

Write-Host ""

$CliArgs = @()
if ($NoTui) { $CliArgs += "--no-tui" }
if ($Target) { $CliArgs += "--target"; $CliArgs += $Target }

if ($CliArgs.Count -gt 0) {
    & $PythonExe -m argus_cli $CliArgs
} else {
    & $PythonExe -m argus_cli
}

Write-Host ""
Write-Host "╔════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║     Argus CLI session ended            ║" -ForegroundColor Green
Write-Host "╚════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Log-Info "Run .\scripts\windows\stop-argus.ps1 to stop background services."
