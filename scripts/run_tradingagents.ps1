$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] Virtual environment not found at $VenvPython" -ForegroundColor Red
    Pause
    Exit 1
}

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "   Starting TradingAgents (Multi-Agent Trading CLI)  " -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan

& $VenvPython -m cli.main
