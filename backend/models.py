from sqlalchemy import Column, String, Float, Integer, Text, DateTime
from sqlalchemy.types import JSON
from sqlalchemy.sql import func
from database import Base


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    audio_path = Column(String)
    status = Column(String, default="pending")  # pending / processing / done / error
    speaker_names = Column(JSON, default={})    # {"SPEAKER_00": "张三", ...}
    hotwords = Column(Text, nullable=True)       # 用户填写的会议背景/热词
    mode = Column(String, default="meeting")     # meeting（含说话人分离）/ subtitle（字幕模式）
    auto_translate = Column(Integer, default=0)  # 转录完成后自动排队翻译字幕
    created_at = Column(DateTime, server_default=func.now())


class Utterance(Base):
    __tablename__ = "utterances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(String, nullable=False)
    speaker = Column(String)
    start = Column(Float)
    end = Column(Float)
    text = Column(Text)              # 识别原文
    text_zh = Column(Text, nullable=True)  # 中文译文（未翻译时为 NULL）
    order_index = Column(Integer)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    meeting_id = Column(String, nullable=False)
    kind = Column(String, default="transcribe")  # transcribe / translate
    status = Column(String, default="pending")  # pending / processing / done / error
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
