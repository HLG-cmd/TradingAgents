@echo off
cd /d "%~dp0"
echo Starting TradingAgents Smart Screener...
powershell.exe -ExecutionPolicy Bypass -NoExit -File ".\scripts\run_screener.ps1"
