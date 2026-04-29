from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent

load_dotenv(BACKEND_DIR / ".env")


def backend_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(BACKEND_DIR / path)


def env_backend_path(name: str, default: str) -> str:
    return backend_path(os.getenv(name, default))


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_stt_model: str = os.getenv("OPENAI_STT_MODEL", "whisper-1")
    openai_llm_model: str = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")

    beats_py_dir: str = env_backend_path("BEATS_PY_DIR", "beats")
    beats_checkpoint_path: str = env_backend_path(
        "BEATS_CHECKPOINT_PATH",
        "checkpoints/BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt",
    )
    beats_base_checkpoint_path: str = env_backend_path(
        "BEATS_BASE_CHECKPOINT_PATH",
        "checkpoints/BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt",
    )

    device: str = os.getenv("DEVICE", "cpu")
    sample_rate: int = int(os.getenv("SAMPLE_RATE", "16000"))
    chunk_seconds: int = int(os.getenv("CHUNK_SECONDS", "5"))

    min_rms_for_stt: float = float(os.getenv("MIN_RMS_FOR_STT", "0.004"))
    min_peak_for_stt: float = float(os.getenv("MIN_PEAK_FOR_STT", "0.030"))
    allow_unknown_stt: bool = env_bool("ALLOW_UNKNOWN_STT", "true")

    zone_name: str = os.getenv("ZONE_NAME", "위험구역 A")
    location_text: str = os.getenv("LOCATION_TEXT", "폐공사장 A구역 입구")
    latitude: str = os.getenv("LATITUDE", "37.000000")
    longitude: str = os.getenv("LONGITUDE", "127.000000")

    control_room_webhook: str = os.getenv("CONTROL_ROOM_WEBHOOK", "")
    auth_password: str = os.getenv("AUTH_PASSWORD", "1234")
    auth_disable_seconds: int = int(os.getenv("AUTH_DISABLE_SECONDS", "10"))

    intrusion_warn_1_seconds: int = int(os.getenv("INTRUSION_WARN_1_SECONDS", "5"))
    intrusion_warn_2_seconds: int = int(os.getenv("INTRUSION_WARN_2_SECONDS", "15"))


settings = Settings()
