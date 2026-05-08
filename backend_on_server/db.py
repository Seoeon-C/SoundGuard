import uuid
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, DateTime, String, Float, Integer, Text, create_engine
from sqlalchemy.dialects.postgresql import UUID

_cur = Path(__file__).resolve().parent
load_dotenv(_cur / ".env")

# SQLite (기본/개발용) or PostgreSQL (운영: DATABASE_URL 환경변수 설정)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_cur}/zones.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

ZONE_LABELS = ["산", "공사장", "저수지", "강", "논"]


class Zone(Base):
    __tablename__ = "zones"

    id         = Column(String,   primary_key=True, default=lambda: str(uuid.uuid4()))
    name       = Column(String,   nullable=False)
    label      = Column(String,   nullable=True)   # 산/공사장/저수지/강/논
    coord      = Column(String,   nullable=True)   # "37.5665° N, 126.9780° E"
    created_at = Column(DateTime, default=datetime.utcnow)


class AudioSample(Base):
    __tablename__ = "audio_samples"

    audio_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    zone_id = Column(String, nullable=True)
    zone_name = Column(String, nullable=True)
    sensor_id = Column(String, nullable=True)

    raw_audio_path = Column(Text, nullable=False)

    beats_label = Column(String, nullable=True)
    beats_raw_label = Column(String, nullable=True)
    beats_confidence = Column(Float, nullable=True)

    stt_text = Column(Text, nullable=True)
    final_result = Column(String, nullable=True)
    final_situation = Column(Integer, nullable=True)

    human_label = Column(String, nullable=True)
    review_status = Column(String, default="pending")

    model_version = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
