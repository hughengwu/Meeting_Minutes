import mimetypes
import os
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import DATA_DIR, get_db
from models import Job, Meeting, Utterance

router = APIRouter()


class SpeakerNamesBody(BaseModel):
    speaker_names: Dict[str, str]


class UtteranceTextBody(BaseModel):
    text: str


class TitleBody(BaseModel):
    title: str


def _fmt_time(s: float) -> str:
    m = int(s // 60)
    return f"{m:02d}:{int(s % 60):02d}"


@router.get("/")
def list_meetings(db: Session = Depends(get_db)):
    meetings = db.query(Meeting).order_by(Meeting.created_at.desc()).all()
    result = []
    for m in meetings:
        job = (
            db.query(Job)
            .filter(Job.meeting_id == m.id)
            .order_by(Job.created_at.desc())
            .first()
        )
        utterances = (
            db.query(Utterance).filter(Utterance.meeting_id == m.id).all()
            if m.status == "done"
            else []
        )
        result.append({
            "id": m.id,
            "title": m.title,
            "status": m.status,
            "created_at": m.created_at,
            "utterance_count": len(utterances),
            "speaker_count": len({u.speaker for u in utterances}),
            "job": {
                "status": job.status,
                "progress": job.progress or 0,
                "error_message": job.error_message,
            } if job else None,
        })
    return result


@router.get("/{meeting_id}")
def get_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="会议不存在")

    utterances = (
        db.query(Utterance)
        .filter(Utterance.meeting_id == meeting_id)
        .order_by(Utterance.order_index)
        .all()
    )
    job = (
        db.query(Job)
        .filter(Job.meeting_id == meeting_id)
        .order_by(Job.created_at.desc())
        .first()
    )
    return {
        "id": meeting.id,
        "title": meeting.title,
        "status": meeting.status,
        "speaker_names": meeting.speaker_names or {},
        "created_at": meeting.created_at,
        "utterances": [
            {"id": u.id, "speaker": u.speaker, "start": u.start, "end": u.end, "text": u.text}
            for u in utterances
        ],
        "job": {
            "status": job.status,
            "progress": job.progress or 0,
            "error_message": job.error_message,
        } if job else None,
    }


@router.patch("/{meeting_id}/title")
def update_title(meeting_id: str, body: TitleBody, db: Session = Depends(get_db)):
    m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")
    m.title = body.title
    db.commit()
    return {"ok": True}


@router.patch("/{meeting_id}/speakers")
def update_speaker_names(meeting_id: str, body: SpeakerNamesBody, db: Session = Depends(get_db)):
    m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")
    m.speaker_names = body.speaker_names
    db.commit()
    return {"ok": True}


@router.patch("/{meeting_id}/utterances/{utterance_id}")
def update_utterance(
    meeting_id: str, utterance_id: int, body: UtteranceTextBody, db: Session = Depends(get_db)
):
    u = db.query(Utterance).filter(
        Utterance.id == utterance_id, Utterance.meeting_id == meeting_id
    ).first()
    if not u:
        raise HTTPException(status_code=404, detail="片段不存在")
    u.text = body.text
    db.commit()
    return {"ok": True}


@router.delete("/{meeting_id}")
def delete_meeting(meeting_id: str, db: Session = Depends(get_db)):
    m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")

    # 删除音频文件
    if m.audio_path and os.path.exists(m.audio_path):
        os.remove(m.audio_path)

    # 删除日志文件
    log_path = DATA_DIR / "logs" / f"{meeting_id}.log"
    if log_path.exists():
        log_path.unlink()

    db.query(Utterance).filter(Utterance.meeting_id == meeting_id).delete()
    db.query(Job).filter(Job.meeting_id == meeting_id).delete()
    db.delete(m)
    db.commit()
    return {"ok": True}


@router.get("/{meeting_id}/audio")
def get_audio(meeting_id: str, db: Session = Depends(get_db)):
    m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not m or not m.audio_path:
        raise HTTPException(status_code=404, detail="音频不存在")
    if not os.path.exists(m.audio_path):
        raise HTTPException(status_code=404, detail="音频文件已被删除")
    content_type, _ = mimetypes.guess_type(m.audio_path)
    return FileResponse(m.audio_path, media_type=content_type or "audio/mpeg")


@router.get("/{meeting_id}/logs")
def get_logs(meeting_id: str):
    log_path = DATA_DIR / "logs" / f"{meeting_id}.log"
    if not log_path.exists():
        return {"lines": []}
    with open(log_path, "r", encoding="utf-8") as f:
        lines = [l.rstrip() for l in f.readlines()]
    return {"lines": lines}


@router.get("/{meeting_id}/export")
def export_meeting(meeting_id: str, format: str = "markdown", db: Session = Depends(get_db)):
    m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")

    utterances = (
        db.query(Utterance)
        .filter(Utterance.meeting_id == meeting_id)
        .order_by(Utterance.order_index)
        .all()
    )
    speaker_names: dict = m.speaker_names or {}

    def name(sid: str) -> str:
        return speaker_names.get(sid, sid)

    if format == "markdown":
        lines = [f"# {m.title}\n"]
        for u in utterances:
            lines.append(f"**{name(u.speaker)}** `{_fmt_time(u.start)}`\n\n{u.text}\n")
        content = "\n".join(lines)
    else:
        lines = [m.title, "=" * 40, ""]
        for u in utterances:
            lines.append(f"[{_fmt_time(u.start)}] {name(u.speaker)}: {u.text}")
        content = "\n".join(lines)

    return {"content": content, "title": m.title}
