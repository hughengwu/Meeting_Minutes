import gc
import os
from datetime import datetime
from typing import Callable

import torch


def process_audio(
    audio_path: str,
    hf_token: str | None = None,   # 保留参数兼容性，FunASR 不需要 HF Token
    on_progress: Callable[[int, str], None] | None = None,
    log_func: Callable[[str], None] | None = None,
) -> list[dict]:

    def log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        if log_func:
            log_func(line)

    def progress(pct: int, label: str):
        log(label)
        if on_progress:
            on_progress(pct, label)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"设备: {device}")

    # 从环境变量读取热词（逗号分隔），用于提升专有名词识别率
    hotword = os.getenv("FUNASR_HOTWORDS", "")

    # ── 加载 FunASR 流水线 ────────────────────────────────────────────
    progress(15, "加载模型（paraformer-zh + cam++）...")
    from funasr import AutoModel

    model = AutoModel(
        model="paraformer-zh",
        vad_model="fsmn-vad",
        punc_model="ct-punc",
        spk_model="cam++",
        device=device,
        disable_update=True,   # 跳过启动时的版本检查
    )
    log("模型加载完成")

    # ── 转录 + 说话人分离（一次调用完成）────────────────────────────
    progress(30, "语音识别 + 说话人分离中...")
    kwargs = dict(input=audio_path, batch_size_s=300)
    if hotword:
        kwargs["hotword"] = hotword
        log(f"热词: {hotword}")

    result = model.generate(**kwargs)

    sentences = result[0].get("sentence_info", []) if result else []
    log(f"识别完成，共 {len(sentences)} 段")

    speakers = {s.get("spk", 0) for s in sentences}
    log(f"识别到 {len(speakers)} 位说话人")

    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    # ── 整理输出格式 ─────────────────────────────────────────────────
    progress(90, "整理结果...")
    segments = []
    for seg in sentences:
        text = seg.get("text", "").strip()
        if not text:
            continue
        segments.append({
            "speaker": f"SPEAKER_{seg.get('spk', 0):02d}",
            "start":   seg["start"] / 1000.0,
            "end":     seg["end"]   / 1000.0,
            "text":    text,
        })

    log(f"处理完成，共 {len(segments)} 条发言")
    return segments
