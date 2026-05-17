import gc
import re
import sys
from contextlib import contextmanager
from datetime import datetime
from typing import Callable

import torch
import whisperx


# ── stderr 劫持，捕获 tqdm 下载进度 ─────────────────────────────────

class _StderrCapture:
    """
    将 stderr 同时写到原始流和 log_func。
    tqdm 用 \\r 覆写同一行；这里把每个 \\r/\\n 段落转成独立日志行，
    并按 10% 粒度去重，避免刷屏。
    """
    _ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
    _BAR  = re.compile(r'\|[█▉▊▋▌▍▎▏ ]+\|')

    def __init__(self, log_func: Callable, original):
        self._log = log_func
        self._orig = original
        self._buf = ''
        self._last_pct: dict[str, int] = {}

    def write(self, text: str):
        self._orig.write(text)
        self._buf += text
        # 按 \r 或 \n 切割，逐段处理
        while True:
            for sep in ('\r', '\n'):
                i = self._buf.find(sep)
                if i >= 0:
                    self._handle(self._buf[:i])
                    self._buf = self._buf[i + 1:]
                    break
            else:
                break

    def _handle(self, raw: str):
        line = self._ANSI.sub('', raw).strip()
        if not line:
            return
        m = re.search(r'(\d+)%', line)
        if not m:
            return
        pct = int(m.group(1))
        # 用文件名作 key，每 10% 记录一次
        fname = line.split(':')[0].strip() if ':' in line else '文件'
        last = self._last_pct.get(fname, -1)
        if pct >= last + 10 or (pct == 100 and last < 100):
            self._last_pct[fname] = pct
            clean = self._BAR.sub('', line)           # 去掉进度条方块
            clean = re.sub(r' {2,}', ' ', clean).strip()
            self._log(f"  ↓ {clean}")

    def flush(self):   self._orig.flush()
    def fileno(self):  return self._orig.fileno()
    def isatty(self):  return False


@contextmanager
def _capture_downloads(log_func: Callable):
    """劫持 stderr 以捕获 tqdm 下载进度到日志。"""
    cap = _StderrCapture(log_func, sys.stderr)
    old = sys.stderr
    sys.stderr = cap
    try:
        yield
    finally:
        sys.stderr = old


# ── 主流程 ───────────────────────────────────────────────────────────

def process_audio(
    audio_path: str,
    hf_token: str | None = None,
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
    compute_type = "float16" if device == "cuda" else "int8"
    log(f"设备: {device}  精度: {compute_type}")

    # 1. Whisper 转录
    progress(15, "加载 Whisper large-v3 模型...")
    with _capture_downloads(log):
        model = whisperx.load_model(
            "large-v3", device, compute_type=compute_type, language="zh"
        )

    progress(30, "语音转文字中...")
    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(audio, batch_size=16, language="zh")
    log(f"转录完成，共 {len(result['segments'])} 段")
    del model
    gc.collect()
    torch.cuda.empty_cache()

    # 2. 词级对齐
    progress(50, "加载对齐模型...")
    try:
        with _capture_downloads(log):
            align_model, metadata = whisperx.load_align_model(
                language_code="zh", device=device
            )
        progress(55, "词级时间对齐中...")
        result = whisperx.align(
            result["segments"], align_model, metadata, audio, device,
            return_char_alignments=False,
        )
        log("词级对齐完成")
        del align_model
        gc.collect()
        torch.cuda.empty_cache()
    except Exception as e:
        log(f"词级对齐跳过: {e}")

    # 3. 说话人分离
    if hf_token:
        progress(65, "加载说话人分离模型...")
        try:
            from whisperx.diarize import DiarizationPipeline
            with _capture_downloads(log):
                diarize_model = DiarizationPipeline(
                    model_name="pyannote/speaker-diarization-3.1",
                    token=hf_token,
                    device=torch.device(device),
                )
            progress(75, "说话人分离中...")
            diarize_segments = diarize_model(audio_path)
            result = whisperx.assign_word_speakers(diarize_segments, result)
            speakers = {s.get("speaker") for s in result.get("segments", [])}
            log(f"说话人分离完成，识别到 {len(speakers)} 位说话人")
            del diarize_model
            gc.collect()
            torch.cuda.empty_cache()
        except Exception as e:
            log(f"说话人分离失败: {e}")
    else:
        log("未配置 HF_TOKEN，跳过说话人分离")

    progress(90, "整理结果...")
    segments = result.get("segments", [])
    for seg in segments:
        if "speaker" not in seg:
            seg["speaker"] = "SPEAKER_00"

    log(f"处理完成，共 {len(segments)} 条发言")
    return segments
