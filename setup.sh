#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

echo "=== 会议记录 安装脚本 ==="

# ── 1. 系统依赖 ─────────────────────────────────────────────
echo ""
echo "[1/4] 安装系统依赖 (ffmpeg, redis, git)..."
sudo apt-get update -qq
sudo apt-get install -y ffmpeg redis-server curl git build-essential

# ── 2. 安装 uv ──────────────────────────────────────────────
echo ""
echo "[2/4] 安装 uv..."
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # 让当前 shell 能找到 uv
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "uv $(uv --version)"

# ── 3. Python 环境（uv 管理，固定 Python 3.12）────────────────
echo ""
echo "[3/4] 配置 Python 环境..."
uv python install 3.12
uv sync
echo "✓ Python 3.12 虚拟环境就绪（.venv）"

# ── 4. Node.js 20 + 前端 ─────────────────────────────────────
echo ""
echo "[4/4] 安装前端依赖..."
if ! command -v node &>/dev/null || [[ "$(node -v)" != v20* ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
echo "Node $(node -v)  NPM $(npm -v)"
cd frontend && npm install --silent && cd ..

mkdir -p data/uploads

echo ""
echo "=============================="
echo "✓ 安装完成！"
echo ""
echo "1. 运行 ./download_models.sh 下载模型（首次必须）"
echo "2. 运行 ./start.sh 启动服务"
echo "=============================="
