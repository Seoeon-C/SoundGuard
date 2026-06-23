import hashlib
import hmac
import re
import uuid
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, DateTime, String, Float, Integer, Text, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import TypeDecorator

from cryptography.fernet import Fernet, InvalidToken

_cur = Path(__file__).resolve().parent
load_dotenv(_cur / ".env")

# SQLite (기본/개발용) or PostgreSQL (운영: DATABASE_URL 환경변수 설정)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_cur}/zones.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

ZONE_LABELS = ["산", "공사장", "저수지", "강", "논"]


# -----------------------------------------------------------------------------
# 비식별화 유틸
# -----------------------------------------------------------------------------
# .env에 필요한 값:
#   FIELD_ENCRYPTION_KEY=<Fernet key>   (민감 컬럼 암호화)
#   SENSOR_ID_HASH_KEY=<임의의 긴 문자열>  (sensor_id 해시용 HMAC 비밀키)
# 생성 명령: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEY = os.getenv("FIELD_ENCRYPTION_KEY")
SENSOR_ID_HASH_KEY = os.getenv("SENSOR_ID_HASH_KEY", "")


def _get_fernet() -> Optional[Fernet]:
    if not FIELD_ENCRYPTION_KEY:
        return None
    return Fernet(FIELD_ENCRYPTION_KEY.encode())


class EncryptedText(TypeDecorator):
    """민감 컬럼용 암호화 타입. DB에는 암호문이 저장되고 Python에서는 평문처럼 다룸.

    FIELD_ENCRYPTION_KEY가 없으면 평문 그대로 저장(로컬 개발용). 운영 배포 시 반드시 키를 설정한다.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        fernet = _get_fernet()
        if fernet is None:
            return str(value)
        return fernet.encrypt(str(value).encode("utf-8")).decode("utf-8")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        fernet = _get_fernet()
        if fernet is None:
            return value
        try:
            return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            return value  # 키 설정 전에 저장된 평문 데이터 호환


def hash_sensor_id(sensor_id: str) -> str:
    """zone_id/sensor_id를 비밀키 기반 HMAC으로 가명화한다 (단순 SHA256은 후보군이 적어 역추적 가능)."""
    if not SENSOR_ID_HASH_KEY:
        raise RuntimeError("SENSOR_ID_HASH_KEY 환경변수가 설정되지 않았습니다")
    return hmac.new(SENSOR_ID_HASH_KEY.encode(), sensor_id.encode(), hashlib.sha256).hexdigest()


def default_retention(days: int = 90) -> datetime:
    """민감 데이터 기본 보존 기한 계산 (배치 삭제 작업에서 사용)."""
    return datetime.utcnow() + timedelta(days=days)


_COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\D*([NS])\D*?(-?\d+(?:\.\d+)?)\D*([EW])", re.IGNORECASE)


def generalize_coord(coord: Optional[str]) -> Optional[str]:
    """정밀 좌표를 약 1km 단위(소수점 2자리)로 일반화한다. 예) "37.5665° N, 126.9780° E" → "37.57° N, 126.98° E" """
    if not coord:
        return None
    m = _COORD_RE.search(coord)
    if not m:
        return None
    lat, ns, lon, ew = m.groups()
    return f"{float(lat):.2f}° {ns.upper()}, {float(lon):.2f}° {ew.upper()}"


class Zone(Base):
    __tablename__ = "zones"

    id         = Column(String,        primary_key=True, default=lambda: str(uuid.uuid4()))
    name       = Column(String,        nullable=False)   # 구역 라벨명 (예: "위험구역 A") — name으로 조회되므로 평문 유지
    label      = Column(String,        nullable=True)    # 산/공사장/저수지/강/논
    coord      = Column(EncryptedText, nullable=True)    # 정밀 좌표 → 암호화
    region_code = Column(String,       nullable=True)    # 정밀 좌표 대신 쓰는 광역 단위(예: "서울특별시 강남구")
    created_at = Column(DateTime,      default=datetime.utcnow)


class AudioSample(Base):
    __tablename__ = "audio_samples"

    audio_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    zone_id = Column(String, nullable=True)
    zone_name = Column(String, nullable=True)
    sensor_id_hash = Column(String, nullable=True)   # 원본 sensor_id 대신 HMAC 해시 저장

    raw_audio_path = Column(EncryptedText, nullable=False)

    beats_label = Column(String, nullable=True)
    beats_raw_label = Column(String, nullable=True)
    beats_confidence = Column(Float, nullable=True)

    stt_text = Column(EncryptedText, nullable=True)
    final_result = Column(String, nullable=True)
    final_situation = Column(Integer, nullable=True)

    human_label = Column(String, nullable=True)
    review_status = Column(String, default="pending")

    model_version = Column(String, nullable=True)
    is_pseudonymized = Column(Integer, default=1)
    retention_until = Column(DateTime, nullable=True, default=default_retention)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """누가/언제/어떤 데이터에 접근·수정했는지 기록하는 최소 감사 로그."""

    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    actor = Column(String, nullable=True)
    action = Column(String, nullable=False)        # create/read/update/delete/review/export
    target_table = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
