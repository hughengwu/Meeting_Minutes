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
    created_at = Column(DateTime, server_default=func.now())


class Utterance(Base):
    __tablename__ = "utterances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(String, nullable=False)
    speaker = Column(String)
    start = Column(Float)
    end = Column(Float)
    text = Column(Text)
    order_index = Column(Integer)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    meeting_id = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending / processing / done / error
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
