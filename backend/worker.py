import os
import queue
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from database import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _patch_sentencepiece_for_unicode_paths():
    """sentencepiece 的 Load(model_file=...) 底层调用 LoadFromFile()，在 Windows 上
    用窄字符串按系统代码页打开文件；当项目路径含非 ASCII 字符（本仓库目录名里就有
    中文"IT项目"）时会报 'Not found: ... Error #2'，即便 Python 自己用
    os.path.exists()/open() 能正常读到同一个文件。
    这里把加载逻辑换成"Python 读字节 + LoadFromSerializedProto"，完全绕开
    sentencepiece 自身的文件打开逻辑，改用 Python 的 Unicode 路径处理。

    注意：SentencePieceProcessor 同时暴露 Load / load / Init 三个入口，FunASR 用的是
    小写 self.sp.load(path)，因此必须把这几个别名都替换掉，只补 Load 无效。
    SenseVoice、FireRedASR 的分词器都是 sentencepiece 模型，加载都会走到这里，
    在后端启动时打一次补丁即可全局生效。
    """
    try:
        import sentencepiece as spm
    except ImportError:
        return

    def _patched_load(self, model_file=None, model_proto=None):
        if model_file and model_proto:
            raise RuntimeError("model_file and model_proto must be exclusive.")
        if model_proto:
            return self.LoadFromSerializedProto(model_proto)
        with open(model_file, "rb") as f:
            return self.LoadFromSerializedProto(f.read())

    spm.SentencePieceProcessor.Load = _patched_load
    spm.SentencePieceProcessor.load = _patched_load

    # Init(model_file=...) 是新版 API 的构造入口，内部也会走 LoadFromFile；
    # 若存在则一并替换，只覆盖 model_file 这一条路径，其余参数原样透传。
    _orig_init = getattr(spm.SentencePieceProcessor, "Init", None)
    if _orig_init is not None:
        def _patched_init(self, model_file=None, model_proto=None, *args, **kwargs):
            if model_file is not None and model_proto is None:
                with open(model_file, "rb") as f:
                    model_proto = f.read()
                model_file = None
            return _orig_init(self, model_file=model_file, model_proto=model_proto, *args, **kwargs)
        spm.SentencePieceProcessor.Init = _patched_init
        spm.SentencePieceProcessor.init = _patched_init


_patch_sentencepiece_for_unicode_paths()

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


def enqueue_task(meeting_id: str, audio_path: str, job_id: str, hotwords: str = "",
                 mode: str = "meeting"):
    _task_queue.put(("process_audio", (meeting_id, audio_path, job_id, hotwords, mode)))


def enqueue_model_download(model_id: str):
    _task_queue.put(("download_model", (model_id,)))


def enqueue_translate(meeting_id: str, job_id: str, force: bool = False):
    _task_queue.put(("translate_meeting", (meeting_id, job_id, force)))


def _worker_loop():
    while True:
        kind, args = _task_queue.get()
        try:
            if kind == "process_audio":
                _process_audio_task(*args)
            elif kind == "download_model":
                _download_model_task(*args)
            elif kind == "translate_meeting":
                _translate_task(*args)
        except Exception:
            # 异常已在具体任务函数内记录到数据库/日志文件，这里仅防止工作线程退出
            pass
        finally:
            _task_queue.task_done()


def _process_audio_task(meeting_id: str, audio_path: str, job_id: str, hotwords: str = "",
                        mode: str = "meeting"):
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
            diarize=(mode != "subtitle"),
        )

        set_progress(85, "保存结果...")
        for i, seg in enumerate(segments):
            db.add(Utterance(
                meeting_id=meeting_id,
                speaker=seg.get("speaker", "SPEAKER_00"),   # 字幕模式为 None
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
                text_zh=(seg.get("text_zh") or "").strip() or None,
                order_index=i,
            ))

        # 勾选了「自动翻译」时，转录一结束就排队翻译（同一个后台队列，串行执行）。
        # 翻译任务行和转录完成状态放在同一次 commit 里落库，否则前端可能刚好轮询到
        # 「转录已完成、翻译任务还没建」的空档，从而不会启动翻译进度轮询。
        translate_job = None
        if meeting.auto_translate:
            translate_job = Job(
                id=str(uuid.uuid4()), meeting_id=meeting_id,
                kind="translate", status="pending", progress=0,
            )
            db.add(translate_job)

        meeting.status = "done"
        job.status = "done"
        job.progress = 100
        job.error_message = None
        db.commit()
        write_log(f"[{datetime.now().strftime('%H:%M:%S')}] 任务完成")

        if translate_job:
            enqueue_translate(meeting_id, translate_job.id)
            write_log(f"[{datetime.now().strftime('%H:%M:%S')}] 已排队：翻译字幕为中文")

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


# ── 字幕翻译任务 ──────────────────────────────────────────────────────────────

def _translate_task(meeting_id: str, job_id: str, force: bool = False):
    """把某次会议的所有片段翻译成目标语言（默认中文），写入 utterances.text_zh。

    force=False 时只补翻还没有译文的片段——上次失败/新增的片段可以直接重跑，
    已翻译的部分不会重复消耗在线翻译额度。
    """
    from database import SessionLocal
    from models import Job, Meeting, Utterance
    from translator import get_settings, translate_texts

    log_path = LOG_DIR / f"{meeting_id}.log"
    db = SessionLocal()

    def write_log(msg: str):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    def set_progress(pct: int, label: str):
        try:
            j = db.query(Job).filter(Job.id == job_id).first()
            if j:
                j.progress = pct
                j.error_message = label
                db.commit()
        except Exception:
            pass

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not job or not meeting:
            return

        job.status = "processing"
        job.progress = 3
        job.error_message = "准备翻译..."
        db.commit()

        utterances = (
            db.query(Utterance)
            .filter(Utterance.meeting_id == meeting_id)
            .order_by(Utterance.order_index)
            .all()
        )
        pending = [
            u for u in utterances
            if (u.text or "").strip() and (force or not (u.text_zh or "").strip())
        ]
        write_log(f"开始翻译字幕：{len(pending)}/{len(utterances)} 条待处理"
                  f"{'（强制重译）' if force else ''}")

        if not pending:
            job.status = "done"
            job.progress = 100
            job.error_message = None
            db.commit()
            write_log("没有需要翻译的片段")
            return

        settings = get_settings()

        def on_progress(done: int, total: int):
            set_progress(3 + int(92 * done / max(total, 1)), f"翻译中 {done}/{total}")

        results = translate_texts(
            [u.text for u in pending],
            settings=settings,
            on_progress=on_progress,
            log=write_log,
        )

        ok = 0
        for u, zh in zip(pending, results):
            if zh and zh.strip():
                u.text_zh = zh.strip()
                ok += 1
        db.commit()

        job.status = "done"
        job.progress = 100
        job.error_message = None
        db.commit()
        write_log(f"翻译完成：成功 {ok}/{len(pending)} 条")

    except Exception as exc:
        db.rollback()
        err = str(exc)
        write_log(f"[错误] 翻译失败: {err}")
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "error"
            job.error_message = err
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

    print(f"[download] 开始下载 {model_id}", flush=True)

    # funasr 的 AutoModel() 在文件刚下载完时偶尔会立刻尝试加载分词器等文件，
    # 出现过 "Not found: ...bpe.model" 这类瞬时竞争错误——原封不动重试一次
    # 就能成功（modelscope 会跳过已下载完整的文件，重试代价很小）。
    attempts = 2
    for attempt in range(1, attempts + 1):
        set_download_status(model_id, {
            "status": "downloading", "progress": 5, "error": None,
            "label": "初始化..." if attempt == 1 else f"初始化...（第 {attempt} 次尝试）",
        })
        try:
            Path(m["local_dir"]).mkdir(parents=True, exist_ok=True)

            if model_id == "firered-aed":
                _download_firered(model_id, m)
            elif model_id == "paraformer":
                _download_paraformer(model_id, m)
            elif model_id == "sensevoice-multilingual":
                _download_sensevoice_multilingual(model_id, m)

            set_download_status(model_id, {"status": "done", "progress": 100, "error": None, "label": "下载完成"})
            print(f"[download] {model_id} 下载完成", flush=True)
            return

        except Exception as e:
            print(f"[download] {model_id} 第 {attempt} 次尝试失败: {e}", flush=True)
            if attempt == attempts:
                set_download_status(model_id, {"status": "error", "progress": 0, "error": str(e), "label": "下载失败"})
                raise
            time.sleep(3)


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
    """通过 FunASR AutoModel 触发模型自动下载，与 download_models.ps1 行为一致。"""
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
