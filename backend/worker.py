import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from celery import Celery
from database import DATA_DIR

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("worker", broker=REDIS_URL, backend=REDIS_URL)

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


@celery_app.task(name="process_audio")
def process_audio_task(meeting_id: str, audio_path: str, job_id: str, hotwords: str = ""):
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

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        job.status = "processing"
        job.progress = 10
        job.error_message = "初始化中..."
        meeting.status = "processing"
        db.commit()

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
