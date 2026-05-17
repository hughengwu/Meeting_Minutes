import gc
from datetime import datetime
from typing import Callable

import torch


def process_audio(
    audio_path: str,
    hf_token: str | None = None,   # 保留参数兼容性，FunASR 不需要 HF Token
    on_progress: Callable[[int, str], None] | None = None,
    log_func: Callable[[str], None] | None = None,
    hotwords: str = "",
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
    if hotwords:
        kwargs["hotword"] = hotwords
        log(f"热词/背景: {hotwords[:100]}")

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

    raw_count = len(segments)
    segments = _merge_segments(segments)
    log(f"合并前 {raw_count} 段 → 合并后 {len(segments)} 段")

    log(f"处理完成，共 {len(segments)} 条发言")
    return segments


def _merge_segments(
    segments: list[dict],
    max_gap: float = 2.0,       # 同说话人间隔 ≤ 2s 则合并
    max_duration: float = 60.0, # 合并后单段最长不超过 60s
    min_duration: float = 1.0,  # 不足 1s 的极短段吸收到上一段
) -> list[dict]:
    """合并同一说话人的相邻碎片段，并吸收极短段，减少过度分割。"""
    if not segments:
        return segments

    # 第一步：合并同说话人相邻段
    merged = [dict(segments[0])]
    for seg in segments[1:]:
        prev = merged[-1]
        gap = seg["start"] - prev["end"]
        would_be = seg["end"] - prev["start"]

        if (seg["speaker"] == prev["speaker"]
                and gap <= max_gap
                and would_be <= max_duration):
            prev["end"] = seg["end"]
            prev["text"] = prev["text"] + seg["text"]
        else:
            merged.append(dict(seg))

    # 第二步：将不足 min_duration 的极短段吸收到上一段
    result = []
    for seg in merged:
        if result and (seg["end"] - seg["start"]) < min_duration:
            result[-1]["end"] = seg["end"]
            result[-1]["text"] = result[-1]["text"] + seg["text"]
        else:
            result.append(seg)

    return result
