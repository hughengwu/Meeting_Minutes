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
    diarize: bool = True,
) -> list[dict]:
    """diarize=False 即「字幕模式」：跳过说话人分离，只用 VAD 切句，速度快很多。"""
    from model_manager import get_active_model
    active = get_active_model()
    if not diarize:
        return _process_subtitle(audio_path, active, hotwords, on_progress, log_func)
    if active == "sensevoice-multilingual":
        return _process_sensevoice_multilingual(audio_path, hotwords, on_progress, log_func)
    if active == "firered-aed":
        return _process_firered(audio_path, hotwords, on_progress, log_func)
    return _process_paraformer(audio_path, hotwords, on_progress, log_func)


def _load_mono16k(audio_path: str):
    """读成单声道 16k，供逐段切片使用。"""
    import torchaudio
    waveform, sr = _load_waveform(audio_path)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sr != 16000:
        waveform = torchaudio.functional.resample(waveform, sr, 16000)
    return waveform


def _clean_sensevoice(text: str) -> str:
    """去掉 SenseVoice 输出里的 <|zh|><|NEUTRAL|> 之类语言/情感/事件标签。"""
    import re
    return re.sub(r"<\|[^|]+\|>", "", text).strip()


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

    waveform = _load_mono16k(audio_path)
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
            # 原文保留在 text，译文写进 text_zh：导出字幕时「原文/中文/双语」三种都要用到，
            # 覆盖掉原文就再也拿不回翻译前的字幕了。
            for (idx, seg), zh_text in zip(batch, zh_texts):
                if zh_text:
                    segments[idx]["text_zh"] = zh_text

            done = min(b + BATCH, len(to_translate))
            if done % (BATCH * 4) == 0 or done == len(to_translate):
                progress(72 + int(12 * done / max(len(to_translate), 1)),
                         f"翻译进度 {done}/{len(to_translate)}")

        del trans_model, tokenizer
        gc.collect()

    for seg in segments:
        seg.pop("_needs_translation", None)
    translated = sum(1 for s in segments if s.get("text_zh"))
    if translated:
        log(f"本地翻译完成 {translated} 段（原文保留，可在会议页导出原文/中文/双语字幕）")

    progress(88, "整理结果...")
    segments = [s for s in segments if s["text"]]
    raw = len(segments)
    segments = _merge_segments(segments)
    log(f"合并前 {raw} 段 → 合并后 {len(segments)} 段，语言: {lang_code}")
    return segments


# ── 字幕模式：VAD 切句 + 逐段识别，不做说话人分离 ────────────────────────────

# VAD 单段上限。默认 60s 对字幕来说太长（一条字幕横跨一分钟），
# 压到 15s 让每个语音段本身就接近一条字幕的粒度。
_SUBTITLE_MAX_SEG_MS = 15000
_SUBTITLE_BATCH = 32       # 每批写多少个临时 wav 再一起识别，控制临时文件占用
_SUBTITLE_BATCH_S = 60     # 单次送入模型的音频总时长上限（秒），压低激活值峰值显存
_MIN_SAMPLES = 3200        # < 0.2s 的段直接丢弃，识别不出有效内容


def _process_subtitle(audio_path, model_id, hotwords, on_progress, log_func) -> list[dict]:
    """字幕模式：fsmn-vad 切出语音段 → 逐段跑 ASR。

    相比会议模式省掉了 cam++ 声纹提取和聚类（说话人分离），FireRedASR 路径下
    还额外省掉了整段 Paraformer 识别（原本只为拿句子边界），速度提升明显。
    """
    log, progress = _make_helpers(on_progress, log_func)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"设备: {device} | 模型: {model_id} | 字幕模式（不做说话人分离）")

    progress(12, "VAD 切分语音段...")
    from funasr import AutoModel

    vad = AutoModel(
        model="fsmn-vad",
        device=device,
        disable_update=True,
        max_single_segment_time=_SUBTITLE_MAX_SEG_MS,
    )
    vad_result = vad.generate(input=audio_path)
    spans = vad_result[0].get("value", []) if vad_result else []
    del vad
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    log(f"VAD 切分完成，共 {len(spans)} 个语音段")
    if not spans:
        log("[警告] 未检测到语音内容")
        return []

    waveform = _load_mono16k(audio_path)
    total_samples = waveform.shape[1]

    progress(30, "加载识别模型...")
    if model_id == "firered-aed":
        transcribe_batch, release = _make_firered_transcriber(device, log)
    else:
        transcribe_batch, release = _make_funasr_transcriber(model_id, device, hotwords, log)

    segments: list[dict] = []
    try:
        n = len(spans)
        for done, (indices, paths) in enumerate(
            _iter_segment_batches(waveform, spans, total_samples), start=1
        ):
            texts = transcribe_batch(paths)
            for idx, text in zip(indices, texts):
                text = (text or "").strip()
                if not text:
                    continue
                start_ms, end_ms = spans[idx][0], spans[idx][1]
                segments.append({
                    "speaker": None,          # 字幕模式不区分说话人
                    "start": start_ms / 1000.0,
                    "end": end_ms / 1000.0,
                    "text": text,
                })
            finished = min(done * _SUBTITLE_BATCH, n)
            progress(30 + int(55 * finished / n), f"识别中... {finished}/{n}")
    finally:
        release()
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()

    progress(88, "整理结果...")
    # 字幕模式不做碎片合并：VAD 段本身就是天然的字幕边界，
    # 合并只会拼出横跨几十秒的长条字幕。
    segments.sort(key=lambda s: s["start"])
    log(f"字幕生成完成，共 {len(segments)} 条")
    return segments


def _iter_segment_batches(waveform, spans, total_samples):
    """按批把语音段切出来写成临时 wav，每批用完立刻删除，避免堆积几百个文件。"""
    import os
    import tempfile
    import torchaudio

    for beg in range(0, len(spans), _SUBTITLE_BATCH):
        batch = list(range(beg, min(beg + _SUBTITLE_BATCH, len(spans))))
        indices, paths = [], []
        tmp_dir = tempfile.mkdtemp(prefix="subtitle_")
        try:
            for i in batch:
                start_sample = min(int(spans[i][0] / 1000.0 * 16000), total_samples)
                end_sample = min(int(spans[i][1] / 1000.0 * 16000), total_samples)
                if end_sample - start_sample < _MIN_SAMPLES:
                    continue
                path = os.path.join(tmp_dir, f"{i:06d}.wav")
                torchaudio.save(path, waveform[:, start_sample:end_sample], 16000,
                                encoding="PCM_S", bits_per_sample=16)
                indices.append(i)
                paths.append(path)
            if paths:
                yield indices, paths
        finally:
            for p in paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass


def _make_funasr_transcriber(model_id, device, hotwords, log):
    """加载不带 vad/spk 的 FunASR 模型，返回批量识别函数。"""
    from funasr import AutoModel

    is_sensevoice = model_id == "sensevoice-multilingual"
    model_name = "iic/SenseVoiceSmall" if is_sensevoice else "paraformer-zh"

    # ct-punc（punc_ct-transformer_cn-en-common-vocab471067-large）词表 47 万，
    # 光 embedding + 输出层就要 1.5GB 以上显存，是这条流水线里最大的一块。
    # SenseVoice 开 use_itn 后自身就输出标点，没必要再挂标点模型；
    # paraformer 原始输出不带标点，才需要它。
    model_kwargs: dict = dict(model=model_name, device=device, disable_update=True)
    if not is_sensevoice:
        model_kwargs["punc_model"] = "ct-punc"
    model = AutoModel(**model_kwargs)
    log(f"已加载 {model_name}"
        f"（{'自带标点' if is_sensevoice else '含 ct-punc 标点恢复'}，无说话人分离）")

    kwargs: dict = {"batch_size_s": _SUBTITLE_BATCH_S}
    if is_sensevoice:
        kwargs.update(language="auto", use_itn=True)
    elif hotwords:
        kwargs["hotword"] = hotwords
        log(f"热词/背景: {hotwords[:100]}")

    def transcribe(paths: list[str]) -> list[str]:
        try:
            results = model.generate(input=paths, **kwargs)
        except Exception as e:  # noqa: BLE001 — 整批失败时退回逐条，避免整段字幕丢失
            log(f"[警告] 批量识别失败，改为逐条识别: {e}")
            results = []
            for p in paths:
                try:
                    results.extend(model.generate(input=p, **kwargs))
                except Exception as inner:  # noqa: BLE001
                    log(f"[警告] 片段识别失败: {inner}")
                    results.append({"text": ""})

        texts = [r.get("text", "") for r in results]
        if is_sensevoice:
            texts = [_clean_sensevoice(t) for t in texts]
        # 结果条数理论上与输入一致；万一模型少返回，用空串补齐防止时间轴错位
        if len(texts) < len(paths):
            texts += [""] * (len(paths) - len(texts))
        return texts[:len(paths)]

    def release():
        nonlocal model
        del model

    return transcribe, release


def _make_firered_transcriber(device, log):
    """加载 FireRedASR-AED，返回批量（逐条循环）识别函数。"""
    import os
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
    model = FireRedAsr("aed", feat_extractor, aed_model, tokenizer)
    log("已加载 FireRedASR-AED（无说话人分离）")

    decode_args = {
        "use_gpu": int(device == "cuda"),
        "beam_size": 3,
        "nbest": 1,
        "decode_max_len": 0,
        "softmax_smoothing": 1.25,
        "aed_length_penalty": 0.6,
        "eos_penalty": 1.0,
    }

    def transcribe(paths: list[str]) -> list[str]:
        texts = []
        for p in paths:
            try:
                results = model.transcribe([os.path.basename(p)], [p], decode_args)
                texts.append(results[0].get("text", "") if results else "")
            except Exception as e:  # noqa: BLE001
                log(f"[警告] 片段识别失败: {e}")
                texts.append("")
        return texts

    def release():
        nonlocal model
        del model

    return transcribe, release


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

    def _absorb(prev: dict, seg: dict):
        prev["end"] = seg["end"]
        prev["text"] = prev["text"] + seg["text"]
        # 译文（SenseVoice 本地翻译产出）跟着原文一起合并，否则两者会错位
        if seg.get("text_zh") or prev.get("text_zh"):
            prev["text_zh"] = (prev.get("text_zh") or "") + (seg.get("text_zh") or "")

    merged = [dict(segments[0])]
    for seg in segments[1:]:
        prev = merged[-1]
        gap = seg["start"] - prev["end"]
        would_be = seg["end"] - prev["start"]
        if (seg["speaker"] == prev["speaker"]
                and gap <= max_gap
                and would_be <= max_duration):
            _absorb(prev, seg)
        else:
            merged.append(dict(seg))

    result = []
    for seg in merged:
        if result and (seg["end"] - seg["start"]) < min_duration:
            _absorb(result[-1], seg)
        else:
            result.append(seg)
    return result
