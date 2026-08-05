# 会议记录 - 启动所有服务（Windows）
# 本脚本以后台进程方式启动服务后立即返回，不会阻塞当前终端；
# 停止服务请用 stop.ps1（PowerShell 对 Ctrl+C/信号的处理不可靠）。

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

$PidDir = Join-Path $RootDir ".pids"
$LogDir = Join-Path $RootDir ".logs"
New-Item -ItemType Directory -Force -Path $PidDir, $LogDir | Out-Null

$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "找不到虚拟环境 .venv，请先运行 .\setup.ps1"
}

$Vite = Join-Path $RootDir "frontend\node_modules\.bin\vite.cmd"
if (-not (Test-Path $Vite)) {
    throw "找不到前端依赖，请先运行 .\setup.ps1（或在 frontend 目录执行 npm install）"
}

$env:MODELSCOPE_CACHE = Join-Path $RootDir "data\models"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONUTF8 = "1"

function Start-Tracked($name, $filePath, $argList, $workDir) {
    $stdout = Join-Path $LogDir "$name.log"
    $stderr = Join-Path $LogDir "$name.err.log"
    $proc = Start-Process -FilePath $filePath -ArgumentList $argList `
        -WorkingDirectory $workDir `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -WindowStyle Hidden -PassThru
    $proc.Id | Out-File -FilePath (Join-Path $PidDir "$name.pid") -Encoding ascii
    return $proc
}

Write-Host "[backend] 启动中 -> http://localhost:8000（含转录后台线程，无需单独 worker 进程）"
Start-Tracked "backend" $VenvPython `
    @("-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000") `
    (Join-Path $RootDir "backend") | Out-Null

Write-Host "[frontend] 启动中 -> http://localhost:5173"
Start-Tracked "frontend" $Vite `
    @("--host", "0.0.0.0") `
    (Join-Path $RootDir "frontend") | Out-Null

Write-Host ""
Write-Host "=============================="
Write-Host "  前端:  http://localhost:5173"
Write-Host "  后端:  http://localhost:8000"
Write-Host "  日志目录: .logs\"
Write-Host "=============================="
Write-Host "停止服务: .\stop.ps1"
Write-Host ""
