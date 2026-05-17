#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

source "$ROOT_DIR/.venv/bin/activate"

echo "========================================"
echo "  模型下载脚本（FunASR + ModelScope）"
echo "========================================"
echo ""
echo "将下载以下模型（首次约 1.6 GB，保存到 ~/.cache/modelscope）："
echo "  • paraformer-zh   — 中文语音识别主模型 (~900 MB)"
echo "  • fsmn-vad        — 语音端点检测 (~100 MB)"
echo "  • ct-punc         — 标点恢复 (~500 MB)"
echo "  • cam++           — 说话人分离 (~100 MB)"
echo ""

python3 - <<'PYEOF'
import sys

try:
    from funasr import AutoModel
except ImportError:
    print("错误: funasr 未安装，请先运行 ./setup.sh")
    sys.exit(1)

print("[1/1] 加载模型（将自动下载缺失的模型文件）...")
model = AutoModel(
    model="paraformer-zh",
    vad_model="fsmn-vad",
    punc_model="ct-punc",
    spk_model="cam++",
)
del model
print("✓ 所有模型下载完成")
PYEOF

echo ""
echo "========================================"
echo "  全部模型下载完成！"
echo "  现在可以运行 ./start.sh 启动服务"
echo "========================================"
