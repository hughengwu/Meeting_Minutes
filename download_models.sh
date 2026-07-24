#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

source "$ROOT_DIR/.venv/bin/activate"

export MODELSCOPE_CACHE="$ROOT_DIR/data/models"
mkdir -p "$MODELSCOPE_CACHE"

echo "========================================"
echo "  模型下载脚本（FunASR + ModelScope）"
echo "========================================"
echo ""
echo "将下载以下模型（首次约 1.6 GB，保存到 data/models）："
echo "  • paraformer-zh   — 中文语音识别主模型 (~900 MB)"
echo "  • fsmn-vad        — 语音端点检测 (~100 MB)"
echo "  • ct-punc         — 标点恢复 (~500 MB)"
echo "  • cam++           — 说话人分离 (~100 MB)"
echo ""

python3 "$ROOT_DIR/download_models.py"

echo ""
echo "========================================"
echo "  全部模型下载完成！"
echo "  现在可以运行 ./start.sh 启动服务"
echo "========================================"
