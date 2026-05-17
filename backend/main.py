import os
import uuid
from pathlib import Path

import aiofiles
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).parent.parent / ".env")

from api import jobs, meetings
from database import DATA_DIR, SessionLocal, init_db
from models import Job, Meeting
from worker import process_audio_task

app = FastAPI(title="会议记录")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meetings.router, prefix="/api/meetings")
app.include_router(jobs.router, prefix="/api/jobs")

UPLOAD_DIR = str(DATA_DIR / "uploads")
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4", ".webm"}


@app.on_event("startup")
def startup():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    init_db()
    _recover_pending_jobs()


def _recover_pending_jobs():
    """服务重启后，把 Redis 里丢失的 pending/processing job 重新入队。"""
    db = SessionLocal()
    try:
        stuck = (
            db.query(Job)
            .filter(Job.status.in_(["pending", "processing"]))
            .all()
        )
        for job in stuck:
            meeting = db.query(Meeting).filter(Meeting.id == job.meeting_id).first()
            if not meeting or not meeting.audio_path:
                continue
            # 重置为 pending，避免前端看到 processing 但实际没在跑
            job.status = "pending"
            job.progress = 0
            job.error_message = None
            meeting.status = "pending"
            db.commit()
            process_audio_task.delay(meeting.id, meeting.audio_path, job.id)
            print(f"[startup] re-queued job {job.id} for meeting {meeting.id}")
    finally:
        db.close()


@app.post("/api/upload")
async def upload_audio(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}")

    meeting_id = str(uuid.uuid4())
    file_path = f"{UPLOAD_DIR}/{meeting_id}{ext}"

    async with aiofiles.open(file_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            await f.write(chunk)

    db = SessionLocal()
    try:
        meeting = Meeting(
            id=meeting_id,
            title=file.filename or "未命名会议",
            audio_path=file_path,
            status="pending",
            speaker_names={},
        )
        db.add(meeting)

        job_id = str(uuid.uuid4())
        job = Job(id=job_id, meeting_id=meeting_id, status="pending", progress=0)
        db.add(job)
        db.commit()
    finally:
        db.close()

    process_audio_task.delay(meeting_id, file_path, job_id)
    return {"meeting_id": meeting_id, "job_id": job_id}
