import gc
from datetime import datetime
from typing import Callable

import torch


def _load_waveform(audio_path: str):
    """读取音频为 (waveform, sample_rate)。

    torchaudio 在本机的默认后端是 soundfile(libsndfile)，无法解码 m4a/AAC 等
    格式（报 "Format not recognised"）。遇到这种情况回退用 ffmpeg 解码为临时
    16k 单声道 WAV 再读，从而支持 m4a/mp3/ogg 等。原始文件不受影响（用于回放）。
    """
    import torchaudio
    try:
        return torchaudio.load(audio_path)
    except Exception:
        import os
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        try:
            subprocess.run(
                ["ffmpeg", "-i", audio_path, "-vn", "-ac", "1", "-ar", "16000",
                 "-acodec", "pcm_s16le", "-y", tmp],
                capture_output=True, check=True,
            )
            return torchaudio.load(tmp)
        finally:
            os.unlink(tmp)


def process_audio(
    audio_path: str,
    hf_token: str | None = None,   # 保留参数兼容性
    on_progress: Callable[[int, str], None] | None = None,
    log_func: Callable[[str], None] | None = None,
    hotwords: str = "",
) -> list[dict]:
    from model_manager import get_active_model
    active = get_active_model()
    if active == "sensevoice-multilingual":
        return _process_sensevoice_multilingual(audio_path, hotwords, on_progress, log_func)
    if active == "firered-aed":
        return _process_firered(audio_path, hotwords, on_progress, log_func)
    return _process_paraformer(audio_path, hotwords, on_progress, log_func)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_helpers(on_progress, log_func):
    def log(msg: str):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        if log_func:
            log_func(line)

    def progress(pct: int, label: str):
        log(label)
        if on_progress:
            on_progress(pct, label)

    return log, progress


# ── Paraformer (FunASR 完整流水线) ────────────────────────────────────────────

def _process_paraformer(audio_path, hotwords, on_progress, log_func) -> list[dict]:
    log, progress = _make_helpers(on_progress, log_func)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"设备: {device} | 模型: Paraformer-zh")

    progress(15, "加载模型（paraformer-zh + cam++）...")
    from funasr import AutoModel

    model = AutoModel(
        model="paraformer-zh",
        vad_model="fsmn-vad",
        punc_model="ct-punc",
        spk_model="cam++",
        device=device,
        disable_update=True,
    )
    log("模型加载完成")

    progress(30, "语音识别 + 说话人分离中...")
    kwargs: dict = dict(input=audio_path, batch_size_s=300)
    if hotwords:
        kwargs["hotword"] = hotwords
        log(f"热词/背景: {hotwords[:100]}")

    result = model.generate(**kwargs)
    sentences = result[0].get("sentence_info", []) if result else []
    log(f"识别完成，共 {len(sentences)} 段，识别到 {len({s.get('spk') for s in sentences})} 位说话人")

    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    progress(90, "整理结果...")
    segments = []
    for seg in sentences:
        text = seg.get("text", "").strip()
        if text:
            segments.append({
                "speaker": f"SPEAKER_{seg.get('spk', 0):02d}",
                "start":   seg["start"] / 1000.0,
                "end":     seg["end"]   / 1000.0,
                "text":    text,
            })

    raw = len(segments)
    segments = _merge_segments(segments)
    log(f"合并前 {raw} 段 → 合并后 {len(segments)} 段")
    return segments


# ── FireRedASR-AED + FunASR 说话人分离 ───────────────────────────────────────

def _process_firered(audio_path, hotwords, on_progress, log_func) -> list[dict]:
    log, progress = _make_helpers(on_progress, log_func)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"设备: {device} | 模型: FireRedASR-AED")

    # Step 1: FunASR VAD + 说话人分离，得到自然句段边界
    progress(12, "加载 FunASR（说话人分离）...")
    from funasr import AutoModel

    funasr_model = AutoModel(
        model="paraformer-zh",
        vad_model="fsmn-vad",
        punc_model="ct-punc",
        spk_model="cam++",
        device=device,
        disable_update=True,
    )

    progress(25, "说话人分离中...")
    kwargs: dict = dict(input=audio_path, batch_size_s=300)
    if hotwords:
        kwargs["hotword"] = hotwords

    funasr_result = funasr_model.generate(**kwargs)
    funasr_sentences = funasr_result[0].get("sentence_info", []) if funasr_result else []
    log(f"说话人分离完成，共 {len(funasr_sentences)} 段，"
        f"识别到 {len({s.get('spk') for s in funasr_sentences})} 位说话人")

    del funasr_model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    # Step 2: 加载 FireRedASR-AED
    progress(40, "加载 FireRedASR-AED...")
    import os
    import tempfile
    import torchaudio
    from fireredasr.models.fireredasr import FireRedAsr, load_fireredasr_aed_model
    from fireredasr.data.asr_feat import ASRFeatExtractor
    from fireredasr.tokenizer.aed_tokenizer import ChineseCharEnglishSpmTokenizer
    from model_manager import MODELS

    model_dir = str(MODELS["firered-aed"]["local_dir"])
    feat_extractor = ASRFeatExtractor(os.path.join(model_dir, "cmvn.ark"))
    aed_model = load_fireredasr_aed_model(os.path.join(model_dir, "model.pth.tar"))
    tokenizer = ChineseCharEnglishSpmTokenizer(
        os.path.join(model_dir, "dict.txt"),
        os.path.join(model_dir, "train_bpe1000.model"),
    )
    firered_model = FireRedAsr("aed", feat_extractor, aed_model, tokenizer)

    # Step 3: 逐 VAD 句段跑 FireRedASR，每段独立识别，无需文本分配
    progress(55, "FireRedASR 逐段识别中...")
    DECODE_ARGS = {
        "use_gpu": int(device == "cuda"),
        "beam_size": 3,
        "nbest": 1,
        "decode_max_len": 0,
        "softmax_smoothing": 1.25,
        "aed_length_penalty": 0.6,
        "eos_penalty": 1.0,
    }
    MIN_SAMPLES = 3200  # < 0.2s 的极短段直接用 FunASR 文本

    waveform, sr = _load_waveform(audio_path)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sr != 16000:
        waveform = torchaudio.functional.resample(waveform, sr, 16000)
    total_samples = waveform.shape[1]

    segments = []
    n = len(funasr_sentences)
    for i, s in enumerate(funasr_sentences):
        start_sample = min(int(s["start"] / 1000.0 * 16000), total_samples)
        end_sample   = min(int(s["end"]   / 1000.0 * 16000), total_samples)
        funasr_text  = s.get("text", "").strip()

        if end_sample - start_sample < MIN_SAMPLES:
            text = funasr_text
        else:
            seg_wav = waveform[:, start_sample:end_sample]
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            torchaudio.save(tmp_path, seg_wav, 16000, encoding="PCM_S", bits_per_sample=16)
            try:
                results = firered_model.transcribe(["utt"], [tmp_path], DECODE_ARGS)
                text = results[0].get("text", "").strip() if results else funasr_text
            except Exception as e:
                log(f"段 {i+1}/{n} FireRedASR 失败，回退 Paraformer: {e}")
                text = funasr_text
            finally:
                os.unlink(tmp_path)

        if not text:
            text = funasr_text
        if text:
            segments.append({
                "speaker": f"SPEAKER_{s.get('spk', 0):02d}",
                "start":   s["start"] / 1000.0,
                "end":     s["end"]   / 1000.0,
                "text":    text,
            })

        if (i + 1) % 50 == 0 or (i + 1) == n:
            pct = 55 + int(30 * (i + 1) / n)
            progress(pct, f"FireRedASR 逐段识别... {i+1}/{n}")

    del firered_model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    progress(90, "整理结果...")
    raw = len(segments)
    segments = _merge_segments(segments)
    log(f"合并前 {raw} 段 → 合并后 {len(segments)} 段")
    return segments


# ── SenseVoice 多语言 + 翻译 ──────────────────────────────────────────────────

def _process_sensevoice_multilingual(audio_path, hotwords, on_progress, log_func) -> list[dict]:
    log, progress = _make_helpers(on_progress, log_func)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"设备: {device} | 模型: SenseVoice 多语言")

    # Step 1: SenseVoice + cam++ 一次调用完成多语言 ASR + 说话人分离
    progress(12, "加载 SenseVoice Small（多语言 + 说话人分离）...")
    from funasr import AutoModel

    model = AutoModel(
        model="iic/SenseVoiceSmall",
        vad_model="fsmn-vad",
        punc_model="ct-punc",
        spk_model="cam++",
        device=device,
        disable_update=True,
    )
    progress(28, "多语言识别 + 说话人分离中...")
    result = model.generate(
        input=audio_path,
        batch_size_s=300,
        language="auto",
        use_itn=True,
    )
    sentences = result[0].get("sentence_info", []) if result else []
    log(f"识别完成，共 {len(sentences)} 段，{len({s.get('spk') for s in sentences})} 位说话人")
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    # Step 2: 清理 SenseVoice 可能带的情感/事件标签，检测语言
    import re
    def _clean(text: str) -> str:
        return re.sub(r'<\|[^|]+\|>', '', text).strip()

    from langdetect import detect as _langdetect, LangDetectException
    sample = " ".join(_clean(s.get("text", "")) for s in sentences[:30])
    try:
        lang_code = _langdetect(sample) if len(sample) > 5 else "zh-cn"
    except LangDetectException:
        lang_code = "zh-cn"

    is_chinese = lang_code.startswith("zh")
    log(f"检测语言: {lang_code}，{'无需翻译' if is_chinese else '将翻译为中文'}")
    if not is_chinese and lang_code != "en":
        log(f"注意: 当前仅支持英文→中文翻译，{lang_code} 语言内容将保留原文")

    # Step 3: 构建段落
    segments = []
    for s in sentences:
        text = _clean(s.get("text", ""))
        if text:
            segments.append({
                "speaker":            f"SPEAKER_{s.get('spk', 0):02d}",
                "start":              s["start"] / 1000.0,
                "end":                s["end"]   / 1000.0,
                "text":               text,
                "_needs_translation": (not is_chinese and lang_code == "en"),
            })

    # Step 4: 批量翻译（英文 → 中文）
    if not is_chinese and lang_code == "en":
        progress(72, "加载翻译模型（英文→中文）...")
        from model_manager import MODELS
        from transformers import MarianMTModel, MarianTokenizer

        translation_dir = str(MODELS["sensevoice-multilingual"]["translation_dir"])
        tokenizer = MarianTokenizer.from_pretrained(translation_dir)
        trans_model = MarianMTModel.from_pretrained(translation_dir).eval()

        to_translate = [(i, seg) for i, seg in enumerate(segments) if seg.get("_needs_translation")]
        log(f"翻译 {len(to_translate)} 段...")

        BATCH = 16
        for b in range(0, len(to_translate), BATCH):
            batch = to_translate[b:b + BATCH]
            texts = [seg["text"] for _, seg in batch]
            inputs = tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=512)
            with torch.no_grad():
                translated = trans_model.generate(**inputs)
            zh_texts = [tokenizer.decode(t, skip_special_tokens=True) for t in translated]
            for (idx, seg), zh_text in zip(batch, zh_texts):
                segments[idx]["text"] = zh_text or seg["text"]

            done = min(b + BATCH, len(to_translate))
            if done % (BATCH * 4) == 0 or done == len(to_translate):
                progress(72 + int(12 * done / max(len(to_translate), 1)),
                         f"翻译进度 {done}/{len(to_translate)}")

        del trans_model, tokenizer
        gc.collect()

    for seg in segments:
        seg.pop("_needs_translation", None)

    progress(88, "整理结果...")
    segments = [s for s in segments if s["text"]]
    raw = len(segments)
    segments = _merge_segments(segments)
    log(f"合并前 {raw} 段 → 合并后 {len(segments)} 段，语言: {lang_code}")
    return segments


# ── 合并碎片段 ────────────────────────────────────────────────────────────────

def _merge_segments(
    segments: list[dict],
    max_gap: float = 2.0,
    max_duration: float = 60.0,
    min_duration: float = 1.0,
) -> list[dict]:
    """合并同说话人相邻碎片段，吸收极短段。"""
    if not segments:
        return segments

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

    result = []
    for seg in merged:
        if result and (seg["end"] - seg["start"]) < min_duration:
            result[-1]["end"] = seg["end"]
            result[-1]["text"] = result[-1]["text"] + seg["text"]
        else:
            result.append(seg)
    return result
