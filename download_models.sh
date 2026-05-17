#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

source venv/bin/activate

# 从 .env 读取配置
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
HF_TOKEN=""
if [ -f .env ]; then
    _val=$(grep '^HF_TOKEN=' .env | head -1 | cut -d= -f2-)
    if [ -n "$_val" ] && [ "$_val" != "填入你的HuggingFace_Token" ]; then
        HF_TOKEN="$_val"
        export HF_TOKEN
    fi
fi

echo "========================================"
echo "  模型下载脚本"
echo "  镜像源: $HF_ENDPOINT"
echo "  HF_TOKEN: ${HF_TOKEN:+已设置 ✓}${HF_TOKEN:-未设置 (将跳过 pyannote)}"
echo "========================================"
echo ""

# ── 1. Whisper large-v3 ─────────────────────────────────────────────
echo "[1/4] Whisper large-v3  (约 3 GB)"
hf download Systran/faster-whisper-large-v3
echo "✓ Whisper 完成"
echo ""

# ── 2. 中文对齐模型 ──────────────────────────────────────────────────
echo "[2/4] 中文语音对齐模型  (约 1.3 GB)"
hf download jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn
echo "✓ 对齐模型完成"
echo ""

# ── 3 & 4. pyannote 说话人分离（需要 HF_TOKEN）────────────────────────
if [ -n "$HF_TOKEN" ]; then
    echo "[3/4] pyannote/speaker-diarization-3.1  (约 70 MB)"
    hf download pyannote/speaker-diarization-3.1 --token "$HF_TOKEN"
    echo "✓ 说话人分离模型完成"
    echo ""

    echo "[4/4] pyannote/segmentation-3.0  (约 70 MB)"
    hf download pyannote/segmentation-3.0 --token "$HF_TOKEN"
    echo "✓ 音频分割模型完成"
else
    echo "[3/4] 跳过 pyannote（未设置 HF_TOKEN）"
    echo "[4/4] 跳过 pyannote（未设置 HF_TOKEN）"
fi

echo ""
echo "========================================"
echo "  全部模型下载完成！"
echo "  现在可以运行 ./start.sh 启动服务"
echo "========================================"
