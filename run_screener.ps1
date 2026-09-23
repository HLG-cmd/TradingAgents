$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] Virtual environment not found at $VenvPython" -ForegroundColor Red
    Pause
    Exit 1
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   TradingAgents Smart Screener (Nasdaq 100 / S&P 500)    " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

& $VenvPython quant\smart_screener.py
