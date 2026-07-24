import os
import queue
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from database import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 单进程内的任务队列，替代 Celery + Redis：
# 本项目单机单 GPU 运行，任务本就串行处理（原 concurrency=1），
# 用标准库 threading + queue 即可满足需求，且原生 Windows 可直接运行。
# 队列里同时跑转录任务和模型下载任务，串行处理，与原来单 Celery worker 的行为一致。
_task_queue: "queue.Queue[tuple[str, tuple]]" = queue.Queue()
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()


def start_worker():
    """启动后台工作线程（幂等，重复调用无副作用）。"""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _worker_thread = threading.Thread(target=_worker_loop, name="audio-worker", daemon=True)
        _worker_thread.start()


def enqueue_task(meeting_id: str, audio_path: str, job_id: str, hotwords: str = ""):
    _task_queue.put(("process_audio", (meeting_id, audio_path, job_id, hotwords)))


def enqueue_model_download(model_id: str):
    _task_queue.put(("download_model", (model_id,)))


def _worker_loop():
    while True:
        kind, args = _task_queue.get()
        try:
            if kind == "process_audio":
                _process_audio_task(*args)
            elif kind == "download_model":
                _download_model_task(*args)
        except Exception:
            # 异常已在具体任务函数内记录到数据库/日志文件，这里仅防止工作线程退出
            pass
        finally:
            _task_queue.task_done()


def _process_audio_task(meeting_id: str, audio_path: str, job_id: str, hotwords: str = ""):
    from database import SessionLocal
    from models import Job, Meeting, Utterance
    from pipeline import process_audio

    log_path = LOG_DIR / f"{meeting_id}.log"
    db = SessionLocal()

    def write_log(msg: str):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    def set_progress(pct: int, label: str):
        write_log(f"[进度] {pct}% — {label}")
        try:
            j = db.query(Job).filter(Job.id == job_id).first()
            if j:
                j.progress = pct
                j.error_message = label
                db.commit()
        except Exception:
            pass

    write_log(f"[{datetime.now().strftime('%H:%M:%S')}] 任务开始 meeting={meeting_id}")

    _VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        job.status = "processing"
        job.progress = 5
        job.error_message = "初始化中..."
        meeting.status = "processing"
        db.commit()

        # 视频文件：先提取音轨为 WAV
        ext = os.path.splitext(audio_path)[1].lower()
        if ext in _VIDEO_EXTS:
            write_log(f"[{datetime.now().strftime('%H:%M:%S')}] 提取视频音轨...")
            job.error_message = "提取视频音轨..."
            job.progress = 8
            db.commit()

            wav_path = audio_path.rsplit(".", 1)[0] + ".wav"
            r = subprocess.run(
                ["ffmpeg", "-i", audio_path, "-vn", "-ac", "1", "-ar", "16000",
                 "-acodec", "pcm_s16le", "-y", wav_path],
                capture_output=True,
            )
            if r.returncode == 0:
                os.remove(audio_path)
                audio_path = wav_path
                meeting.audio_path = wav_path
                db.commit()
                write_log(f"[{datetime.now().strftime('%H:%M:%S')}] 音轨提取完成: {wav_path}")
            else:
                write_log(f"[警告] ffmpeg 提取音轨失败，尝试直接处理原文件")

        segments = process_audio(
            audio_path,
            hotwords=hotwords,
            on_progress=set_progress,
            log_func=write_log,
        )

        set_progress(85, "保存结果...")
        for i, seg in enumerate(segments):
            db.add(Utterance(
                meeting_id=meeting_id,
                speaker=seg.get("speaker", "SPEAKER_00"),
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
                order_index=i,
            ))

        meeting.status = "done"
        job.status = "done"
        job.progress = 100
        job.error_message = None
        db.commit()
        write_log(f"[{datetime.now().strftime('%H:%M:%S')}] 任务完成")

    except Exception as exc:
        db.rollback()
        err = str(exc)
        write_log(f"[错误] {err}")
        job = db.query(Job).filter(Job.id == job_id).first()
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if job:
            job.status = "error"
            job.error_message = err
        if meeting:
            meeting.status = "error"
        db.commit()
        raise
    finally:
        db.close()


# ── 模型下载任务 ──────────────────────────────────────────────────────────────

def _download_model_task(model_id: str):
    from model_manager import MODELS, is_model_downloaded, set_download_status

    m = MODELS.get(model_id)
    if not m:
        return

    if is_model_downloaded(model_id):
        set_download_status(model_id, {"status": "done", "progress": 100, "error": None, "label": "已下载"})
        return

    set_download_status(model_id, {"status": "downloading", "progress": 5, "error": None, "label": "初始化..."})
    print(f"[download] 开始下载 {model_id}")

    try:
        Path(m["local_dir"]).mkdir(parents=True, exist_ok=True)

        if model_id == "firered-aed":
            _download_firered(model_id, m)
        elif model_id == "paraformer":
            _download_paraformer(model_id, m)
        elif model_id == "sensevoice-multilingual":
            _download_sensevoice_multilingual(model_id, m)

        set_download_status(model_id, {"status": "done", "progress": 100, "error": None, "label": "下载完成"})
        print(f"[download] {model_id} 下载完成")

    except Exception as e:
        set_download_status(model_id, {"status": "error", "progress": 0, "error": str(e), "label": "下载失败"})
        print(f"[download] {model_id} 下载失败: {e}")
        raise


def _download_firered(model_id: str, m: dict):
    """从 HuggingFace 下载 FireRedASR-AED-L，用后台线程定期更新进度。"""
    from huggingface_hub import snapshot_download
    import huggingface_hub.constants as _hf_const
    from model_manager import set_download_status

    _OFFLINE_KEYS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "MODELSCOPE_OFFLINE")
    _saved = {k: os.environ.pop(k, None) for k in _OFFLINE_KEYS}
    _saved_hf_offline = _hf_const.HF_HUB_OFFLINE
    _hf_const.HF_HUB_OFFLINE = False

    stop = threading.Event()
    pct = [8]

    def _ping():
        while not stop.is_set():
            pct[0] = min(pct[0] + 3, 88)
            set_download_status(model_id, {
                "status": "downloading", "progress": pct[0],
                "error": None, "label": "下载模型文件（约 350MB）...",
            })
            stop.wait(timeout=10)

    t = threading.Thread(target=_ping, daemon=True)
    t.start()
    try:
        hf_endpoint = os.getenv("HF_ENDPOINT", "https://huggingface.co")
        snapshot_download(
            repo_id=m["hf_repo"],
            local_dir=str(m["local_dir"]),
            endpoint=hf_endpoint,
        )
    finally:
        stop.set()
        t.join(timeout=2)
        _hf_const.HF_HUB_OFFLINE = _saved_hf_offline
        for k, v in _saved.items():
            if v is not None:
                os.environ[k] = v


def _download_paraformer(model_id: str, m: dict):
    """通过 FunASR AutoModel 触发模型自动下载，与 download_models.sh 行为一致。"""
    from funasr import AutoModel
    from model_manager import set_download_status

    _OFFLINE_KEYS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "MODELSCOPE_OFFLINE")
    _saved = {k: os.environ.pop(k, None) for k in _OFFLINE_KEYS}
    os.environ["MODELSCOPE_CACHE"] = str(DATA_DIR / "models")

    stop = threading.Event()
    pct = [8]

    def _ping():
        while not stop.is_set():
            pct[0] = min(pct[0] + 2, 88)
            set_download_status(model_id, {
                "status": "downloading", "progress": pct[0],
                "error": None, "label": "下载 FunASR 模型（约 1.6GB）...",
            })
            stop.wait(timeout=10)

    t = threading.Thread(target=_ping, daemon=True)
    t.start()
    try:
        funasr_model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            spk_model="cam++",
        )
        del funasr_model
    finally:
        stop.set()
        t.join(timeout=2)
        for k, v in _saved.items():
            if v is not None:
                os.environ[k] = v


def _download_sensevoice_multilingual(model_id: str, m: dict):
    """通过 FunASR 下载 SenseVoice Small（ModelScope），再从 HF 下载 opus-mt-en-zh 翻译模型。"""
    from huggingface_hub import snapshot_download
    import huggingface_hub.constants as _hf_const
    from model_manager import set_download_status

    _OFFLINE_KEYS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "MODELSCOPE_OFFLINE")
    _saved = {k: os.environ.pop(k, None) for k in _OFFLINE_KEYS}
    _saved_hf_offline = _hf_const.HF_HUB_OFFLINE
    _hf_const.HF_HUB_OFFLINE = False
    os.environ["MODELSCOPE_CACHE"] = str(DATA_DIR / "models")

    stop = threading.Event()
    pct = [5]

    def _ping():
        while not stop.is_set():
            pct[0] = min(pct[0] + 2, 82)
            set_download_status(model_id, {
                "status": "downloading", "progress": pct[0],
                "error": None, "label": "下载 SenseVoice Small + FunASR 模型（约 400MB）...",
            })
            stop.wait(timeout=10)

    t = threading.Thread(target=_ping, daemon=True)
    t.start()
    try:
        from funasr import AutoModel
        funasr_model = AutoModel(
            model="iic/SenseVoiceSmall",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            spk_model="cam++",
        )
        del funasr_model

        stop.set()
        t.join(timeout=2)
        set_download_status(model_id, {
            "status": "downloading", "progress": 88,
            "error": None, "label": "下载翻译模型（opus-mt-en-zh，约 320MB）...",
        })

        hf_endpoint = os.getenv("HF_ENDPOINT", "https://huggingface.co")
        Path(m["translation_dir"]).mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id="Helsinki-NLP/opus-mt-en-zh",
            local_dir=str(m["translation_dir"]),
            endpoint=hf_endpoint,
        )
    finally:
        stop.set()
        t.join(timeout=2)
        _hf_const.HF_HUB_OFFLINE = _saved_hf_offline
        for k, v in _saved.items():
            if v is not None:
                os.environ[k] = v
