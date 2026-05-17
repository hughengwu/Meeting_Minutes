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
    # 兼容旧数据库：按需添加新列
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    existing = {c["name"] for c in inspector.get_columns("meetings")}
    with engine.begin() as conn:
        if "hotwords" not in existing:
            conn.execute(text("ALTER TABLE meetings ADD COLUMN hotwords TEXT"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
