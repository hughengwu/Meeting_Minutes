import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import DATA_DIR, get_db
from models import Job, Meeting, Utterance

router = APIRouter()


class SpeakerNamesBody(BaseModel):
    speaker_names: Dict[str, str]


class UtteranceTextBody(BaseModel):
    text: Optional[str] = None
    text_zh: Optional[str] = None


class TitleBody(BaseModel):
    title: str


class TranslateBody(BaseModel):
    force: bool = False


def _fmt_time(s: float) -> str:
    m = int(s // 60)
    return f"{m:02d}:{int(s % 60):02d}"


def _latest_job(db: Session, meeting_id: str, kind: str):
    """取某类任务的最新一条。kind='transcribe' 时兼容 kind 列加上之前的历史数据（NULL）。"""
    q = db.query(Job).filter(Job.meeting_id == meeting_id)
    if kind == "transcribe":
        q = q.filter(or_(Job.kind == "transcribe", Job.kind.is_(None)))
    else:
        q = q.filter(Job.kind == kind)
    return q.order_by(Job.created_at.desc()).first()


def _job_dict(job) -> dict | None:
    if not job:
        return None
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress or 0,
        "error_message": job.error_message,
    }


@router.get("/")
def list_meetings(db: Session = Depends(get_db)):
    meetings = db.query(Meeting).order_by(Meeting.created_at.desc()).all()
    result = []
    for m in meetings:
        job = _latest_job(db, m.id, "transcribe")
        translate_job = _latest_job(db, m.id, "translate")
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
            "speaker_count": len({u.speaker for u in utterances if u.speaker}),
            "mode": m.mode or "meeting",
            "translated_count": sum(1 for u in utterances if (u.text_zh or "").strip()),
            "job": _job_dict(job),
            "translate_job": _job_dict(translate_job),
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
    job = _latest_job(db, meeting_id, "transcribe")
    translate_job = _latest_job(db, meeting_id, "translate")
    return {
        "id": meeting.id,
        "title": meeting.title,
        "status": meeting.status,
        "speaker_names": meeting.speaker_names or {},
        "created_at": meeting.created_at,
        "mode": meeting.mode or "meeting",
        "auto_translate": bool(meeting.auto_translate),
        "translated_count": sum(1 for u in utterances if (u.text_zh or "").strip()),
        "utterances": [
            {"id": u.id, "speaker": u.speaker, "start": u.start, "end": u.end,
             "text": u.text, "text_zh": u.text_zh}
            for u in utterances
        ],
        "job": _job_dict(job),
        "translate_job": _job_dict(translate_job),
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
    if body.text is not None:
        u.text = body.text
    if body.text_zh is not None:
        u.text_zh = body.text_zh.strip() or None
    db.commit()
    return {"ok": True}


@router.post("/{meeting_id}/translate")
def translate_meeting(meeting_id: str, body: TranslateBody, db: Session = Depends(get_db)):
    """把字幕翻译成中文（异步，进度通过 GET /api/jobs/{id} 或会议详情里的 translate_job 轮询）。"""
    m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")
    if m.status != "done":
        raise HTTPException(status_code=400, detail="转录尚未完成，无法翻译")

    running = _latest_job(db, meeting_id, "translate")
    if running and running.status in ("pending", "processing"):
        return {"ok": True, "job_id": running.id, "message": "already_running"}

    count = db.query(Utterance).filter(Utterance.meeting_id == meeting_id).count()
    if count == 0:
        raise HTTPException(status_code=400, detail="没有可翻译的内容")

    from worker import enqueue_translate

    job = Job(id=str(uuid.uuid4()), meeting_id=meeting_id, kind="translate",
              status="pending", progress=0)
    db.add(job)
    db.commit()
    enqueue_translate(meeting_id, job.id, body.force)
    return {"ok": True, "job_id": job.id}


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
def get_audio(meeting_id: str, request: Request, db: Session = Depends(get_db)):
    m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not m or not m.audio_path:
        raise HTTPException(status_code=404, detail="音频不存在")
    if not os.path.exists(m.audio_path):
        raise HTTPException(status_code=404, detail="音频文件已被删除")

    file_path = m.audio_path
    file_size = os.path.getsize(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    _MIME = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".mp4": "audio/mp4",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
    }
    content_type = _MIME.get(ext) or mimetypes.guess_type(file_path)[0] or "audio/mpeg"

    range_header = request.headers.get("range", "")
    match = re.match(r"bytes=(\d+)-(\d*)", range_header)

    if match:
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else file_size - 1
        end = min(end, file_size - 1)
        length = end - start + 1

        def stream_range():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    data = f.read(min(65536, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return StreamingResponse(
            stream_range(),
            status_code=206,
            headers={
                "Content-Type": content_type,
                "Content-Length": str(length),
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
            },
        )

    def stream_full():
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(
        stream_full(),
        headers={
            "Content-Type": content_type,
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        },
    )


@router.get("/{meeting_id}/logs")
def get_logs(meeting_id: str):
    log_path = DATA_DIR / "logs" / f"{meeting_id}.log"
    if not log_path.exists():
        return {"lines": []}
    with open(log_path, "r", encoding="utf-8") as f:
        lines = [l.rstrip() for l in f.readlines()]
    return {"lines": lines}


_LANG_SUFFIX = {"original": "原文", "zh": "中文", "bilingual": "双语"}
_EXT = {"markdown": "md", "text": "txt", "srt": "srt", "vtt": "vtt"}


@router.get("/{meeting_id}/export")
def export_meeting(
    meeting_id: str,
    format: str = "markdown",          # markdown / text / srt / vtt
    lang: str = "original",            # original / zh / bilingual
    speaker: bool = False,             # 字幕里是否带说话人前缀
    db: Session = Depends(get_db),
):
    if format not in _EXT:
        raise HTTPException(status_code=400, detail=f"不支持的导出格式: {format}")
    if lang not in _LANG_SUFFIX:
        raise HTTPException(status_code=400, detail=f"不支持的语言选项: {lang}")

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

    def name(sid: str | None) -> str:
        # 字幕模式下 speaker 为 NULL，导出文稿时不加说话人前缀
        return speaker_names.get(sid, sid) if sid else ""

    def body_text(u) -> str:
        zh = (u.text_zh or "").strip()
        if lang == "zh":
            return zh or u.text
        if lang == "bilingual" and zh and zh != u.text:
            return f"{zh}\n{u.text}"
        return u.text

    # 去掉文件名里的非法字符，避免浏览器保存失败
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", m.title or "meeting").rstrip(". ")
    base = safe_title
    if format in ("srt", "vtt") or lang != "original":
        base = f"{safe_title}.{_LANG_SUFFIX[lang]}"
    filename = f"{base}.{_EXT[format]}"

    if format in ("srt", "vtt"):
        from subtitle import build_cues, to_srt, to_vtt

        cues = build_cues(utterances, lang=lang, speaker_names=speaker_names,
                          show_speaker=speaker)
        content = to_srt(cues) if format == "srt" else to_vtt(cues)
    elif format == "markdown":
        lines = [f"# {m.title}\n"]
        for u in utterances:
            who = f"**{name(u.speaker)}** " if u.speaker else ""
            lines.append(f"{who}`{_fmt_time(u.start)}`\n\n{body_text(u)}\n")
        content = "\n".join(lines)
    else:
        lines = [m.title, "=" * 40, ""]
        for u in utterances:
            text = body_text(u).replace("\n", " / ")
            who = f"{name(u.speaker)}: " if u.speaker else ""
            lines.append(f"[{_fmt_time(u.start)}] {who}{text}")
        content = "\n".join(lines)

    return {"content": content, "title": m.title, "filename": filename}
