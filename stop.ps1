# 会议记录 - 停止所有服务（Windows 原生）
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidDir = Join-Path $RootDir ".pids"

Write-Host "停止服务..."

function Stop-Tracked($name) {
    $pidFile = Join-Path $PidDir "$name.pid"
    if (-not (Test-Path $pidFile)) { return }
    $procId = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($procId) {
        # taskkill /T 会连同子进程一起结束（vite/uvicorn 可能有子进程）
        taskkill /PID $procId /T /F 2>$null | Out-Null
        Write-Host "  $name 停止"
    }
}

Stop-Tracked "backend"
Stop-Tracked "frontend"

Remove-Item -Recurse -Force $PidDir -ErrorAction SilentlyContinue
Write-Host "完成"
