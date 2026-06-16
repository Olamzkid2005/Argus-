# Argus CLI Stop Script (Windows)
# Stops Celery workers and cleans up

$ScriptDir = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
Set-Location $ScriptDir

Write-Host "╔════════════════════════════════════════╗" -ForegroundColor Blue
Write-Host "║   Stopping Argus Services              ║" -ForegroundColor Blue
Write-Host "╚════════════════════════════════════════╝" -ForegroundColor Blue
Write-Host ""

$PidFile = "$ScriptDir\logs\celery.pid"
if (Test-Path $PidFile) {
    $CeleryPid = Get-Content $PidFile
    Write-Host "Stopping Celery workers (PID: $CeleryPid)..." -ForegroundColor Yellow
    $proc = Get-Process -Id $CeleryPid -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $CeleryPid -Force -ErrorAction SilentlyContinue
        Start-Sleep 2
        Write-Host "✓ Celery workers stopped" -ForegroundColor Green
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

Write-Host "Final cleanup..." -ForegroundColor Yellow
Get-Process | Where-Object { $_.ProcessName -like "*celery*" } | Stop-Process -Force -ErrorAction SilentlyContinue

Remove-Item "$ScriptDir\logs\celery.pid" -Force -ErrorAction SilentlyContinue
Remove-Item "$ScriptDir\logs\celery_beat.pid" -Force -ErrorAction SilentlyContinue

Write-Host "✓ Cleanup complete" -ForegroundColor Green
Write-Host ""
Write-Host "All services stopped!" -ForegroundColor Green
Write-Host ""
