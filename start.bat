@echo off
cd /d "%~dp0"
echo Starting TradingAgents...
powershell.exe -ExecutionPolicy Bypass -NoExit -File ".\run_tradingagents.ps1"
