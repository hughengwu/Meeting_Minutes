import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

_default_data_dir = Path(__file__).parent.parent / "data"
DATA_DIR = Path(os.getenv("DATA_DIR", str(_default_data_dir)))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR}/meetings.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # 兼容旧数据库：按需添加新列（SQLite 的 ADD COLUMN ... DEFAULT 会自动回填已有行）
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    migrations = [
        ("meetings",   "hotwords",       "ALTER TABLE meetings ADD COLUMN hotwords TEXT"),
        ("meetings",   "auto_translate", "ALTER TABLE meetings ADD COLUMN auto_translate INTEGER DEFAULT 0"),
        ("meetings",   "mode",           "ALTER TABLE meetings ADD COLUMN mode TEXT DEFAULT 'meeting'"),
        ("utterances", "text_zh",        "ALTER TABLE utterances ADD COLUMN text_zh TEXT"),
        ("jobs",       "kind",           "ALTER TABLE jobs ADD COLUMN kind TEXT DEFAULT 'transcribe'"),
    ]
    with engine.begin() as conn:
        for table, column, ddl in migrations:
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column not in existing:
                conn.execute(text(ddl))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
