#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

echo "=== 会议记录 WSL 安装脚本 ==="

# ── 1. 系统依赖 ─────────────────────────────────────────────
echo ""
echo "[1/4] 安装系统依赖 (ffmpeg, redis, git)..."
sudo apt-get update -qq
sudo apt-get install -y ffmpeg redis-server curl git python3 python3-pip python3-venv build-essential

# ── 2. Node.js 20 ───────────────────────────────────────────
echo ""
echo "[2/4] 安装 Node.js 20..."
if ! command -v node &>/dev/null || [[ "$(node -v)" != v20* ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
echo "Node $(node -v)  NPM $(npm -v)"

# ── 3. Python 虚拟环境 ───────────────────────────────────────
echo ""
echo "[3/4] 配置 Python 环境..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q

# 先装 PyTorch (CUDA 12.1)，再装其余依赖
echo "安装 PyTorch (CUDA 12.1)..."
pip install torch==2.5.1 torchaudio==2.5.1 \
    --extra-index-url https://download.pytorch.org/whl/cu121 -q

echo "安装后端依赖..."
pip install -r backend/requirements.txt -q

# ── 4. 前端 ────────────────────────────────────────────────
echo ""
echo "[4/4] 安装前端依赖..."
cd frontend && npm install --silent && cd ..

# 数据目录
mkdir -p data/uploads

echo ""
echo "=============================="
echo "✓ 安装完成！"
echo ""
echo "1. 编辑 .env 填入 HF_TOKEN"
echo "2. 运行 ./start.sh 启动服务"
echo "=============================="
