import sys

try:
    from funasr import AutoModel
except ImportError:
    print("错误: funasr 未安装，请先运行安装脚本 (./setup.sh 或 .\\setup.ps1)")
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
