from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Job

router = APIRouter()


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "id": job.id,
        "meeting_id": job.meeting_id,
        "status": job.status,
        "progress": job.progress,
        "error_message": job.error_message,
    }
