# 会议记录 - Windows 原生安装脚本
# 用法：在 PowerShell 中执行 .\setup.ps1
# 若提示"无法加载脚本，因为在此系统上禁止运行脚本"，先执行：
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

Write-Host "=== 会议记录 安装脚本（Windows 原生） ==="

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

# ── 1. ffmpeg ────────────────────────────────────────────────
Write-Host "`n[1/4] 检查 ffmpeg..."
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Host "ffmpeg 已安装: $((Get-Command ffmpeg).Source)"
} elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "未检测到 ffmpeg，尝试通过 winget 安装..."
    winget install --id Gyan.FFmpeg -e --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        Write-Warning "ffmpeg 安装后仍未在 PATH 中找到，请重新打开一个新的 PowerShell 窗口后重试"
    }
} else {
    Write-Warning "未检测到 ffmpeg 且系统没有 winget，请手动下载并加入 PATH: https://www.gyan.dev/ffmpeg/builds/"
}

# ── 2. 安装 uv ──────────────────────────────────────────────
Write-Host "`n[2/4] 安装 uv..."
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv 安装失败，请手动安装后重试: https://docs.astral.sh/uv/getting-started/installation/"
}
uv --version

# ── 3. Python 环境（uv 管理，固定 Python 3.12）────────────────
Write-Host "`n[3/4] 配置 Python 环境..."
uv python install 3.12
uv sync
Write-Host "✓ Python 3.12 虚拟环境就绪（.venv）"

# ── 4. Node.js 20 + 前端 ─────────────────────────────────────
Write-Host "`n[4/4] 安装前端依赖..."
$nodeOk = $false
if (Get-Command node -ErrorAction SilentlyContinue) {
    if ((node -v) -like "v20*") { $nodeOk = $true }
}
if (-not $nodeOk) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "未检测到 Node.js 20，尝试通过 winget 安装..."
        winget install --id OpenJS.NodeJS.LTS -e --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
    } else {
        Write-Warning "请手动安装 Node.js 20: https://nodejs.org/"
    }
}
if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Host "Node $(node -v)  NPM $(npm -v)"
} else {
    Write-Warning "未检测到 Node.js，请安装后重新运行本脚本的第 4 步（或手动执行 cd frontend; npm install）"
}

Push-Location frontend
npm install --silent
Pop-Location

New-Item -ItemType Directory -Force -Path "data\uploads" | Out-Null

Write-Host ""
Write-Host "=============================="
Write-Host "✓ 安装完成！"
Write-Host ""
Write-Host "1. 运行 .\download_models.ps1 下载模型（首次必须）"
Write-Host "2. 运行 .\start.ps1 启动服务"
Write-Host "=============================="
