# lifecycle: oneoff
# WB_Watchdog: 监控 515100 与黄金(GLD/518880/159934/518800/518850) 报告树，跑完即提前关机；
# 最迟 03:30 由计划任务 WB_AutoShutdown_0330 兜底强制关机。
$ErrorActionPreference = "SilentlyContinue"
$log = "D:\Antigravity\TradingAgents\scripts\_watchdog_shutdown.log"
$reportsRoot = "D:\Antigravity\TradingAgents\reports"
$cap = (Get-Date).Date.AddHours(3).AddMinutes(30)   # 今天 03:30
$targets = @{
    "515100" = @("515100")
    "GOLD"   = @("GLD","518880","159934","518800","518850")
}
function Log($m){ "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File -Append $log }

# 基线：仅统计启动后新建的报告树，避免把历史报告误判为本次完成
$baseline = @{}
foreach ($k in $targets.Keys) {
    $baseline[$k] = @()
    foreach ($t in $targets[$k]) {
        $dir = Join-Path $reportsRoot $t
        if (Test-Path $dir) { $baseline[$k] += @(Get-ChildItem $dir -Directory | Select-Object -ExpandProperty Name) }
    }
}
Log "Watchdog 启动. 兜底关机时刻=$cap. 基线已记录，仅统计此后新建的报告树。"

while ($true) {
    $now = Get-Date
    if ($now -ge $cap) { Log "已达兜底时刻，退出（由 WB_AutoShutdown_0330 执行关机）。"; break }
    $doneFlags = @{}
    foreach ($k in $targets.Keys) {
        $hit = $false; $hits = @()
        foreach ($t in $targets[$k]) {
            $dir = Join-Path $reportsRoot $t
            if (Test-Path $dir) {
                $cur = @(Get-ChildItem $dir -Directory | Select-Object -ExpandProperty Name)
                $new = $cur | Where-Object { $baseline[$k] -notcontains $_ }
                if ($new.Count -gt 0) { $hit = $true; $hits += "$t=>$($new -join '|')" }
            }
        }
        $doneFlags[$k] = $hit
        if ($hit) { Log "标的 $k 已完成（新建报告树）: $($hits -join ' ; ')" }
    }
    if ($doneFlags["515100"] -and $doneFlags["GOLD"]) {
        Log "515100 与黄金均已完成 -> 提前关机。"
        & shutdown.exe /s /f /t 30
        break
    }
    Start-Sleep -Seconds 60
}
Log "Watchdog 正常结束（未触发提前关机，等待兜底任务）。"
