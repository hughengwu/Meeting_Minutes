# 会议记录 - 下载 FunASR / ModelScope 模型（Windows 原生）
$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "找不到虚拟环境 .venv，请先运行 .\setup.ps1"
}

$env:MODELSCOPE_CACHE = Join-Path $RootDir "data\models"
New-Item -ItemType Directory -Force -Path $env:MODELSCOPE_CACHE | Out-Null

Write-Host "========================================"
Write-Host "  模型下载脚本（FunASR + ModelScope）"
Write-Host "========================================"
Write-Host ""
Write-Host "将下载以下模型（首次约 1.6 GB，保存到 data\models）："
Write-Host "  • paraformer-zh   — 中文语音识别主模型 (~900 MB)"
Write-Host "  • fsmn-vad        — 语音端点检测 (~100 MB)"
Write-Host "  • ct-punc         — 标点恢复 (~500 MB)"
Write-Host "  • cam++           — 说话人分离 (~100 MB)"
Write-Host ""

& $VenvPython (Join-Path $RootDir "download_models.py")

Write-Host ""
Write-Host "========================================"
Write-Host "  全部模型下载完成！"
Write-Host "  现在可以运行 .\start.ps1 启动服务"
Write-Host "========================================"
