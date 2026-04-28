from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_stt_model: str = os.getenv("OPENAI_STT_MODEL", "whisper-1")
    openai_llm_model: str = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")

    beats_py_dir: str = os.getenv("BEATS_PY_DIR", "beats")
    beats_checkpoint_path: str = os.getenv(
        "BEATS_CHECKPOINT_PATH",
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

    # 앞단 신호 감지기 설정: 작은 목소리와 발소리 후보를 BEATs 전에 잡는다.
    vad_min_rms: float = float(os.getenv("VAD_MIN_RMS", "0.0012"))
    vad_min_peak: float = float(os.getenv("VAD_MIN_PEAK", "0.014"))
    vad_frame_rms_threshold: float = float(os.getenv("VAD_FRAME_RMS_THRESHOLD", "0.0010"))
    vad_min_active_ratio: float = float(os.getenv("VAD_MIN_ACTIVE_RATIO", "0.06"))
    vad_min_zcr: float = float(os.getenv("VAD_MIN_ZCR", "0.015"))
    vad_max_zcr: float = float(os.getenv("VAD_MAX_ZCR", "0.35"))
    vad_voice_score_threshold: float = float(os.getenv("VAD_VOICE_SCORE_THRESHOLD", "0.45"))

    # 발소리는 전체 RMS가 작고 순간 peak만 튀는 경우가 많아서 기본값을 낮게 둔다.
    # 실제 환경에서 오탐이 많으면 FOOTSTEP_MIN_PEAK, FOOTSTEP_FRAME_RMS_THRESHOLD를 올린다.
    footstep_min_peaks: int = int(os.getenv("FOOTSTEP_MIN_PEAKS", "2"))
    footstep_min_peak: float = float(os.getenv("FOOTSTEP_MIN_PEAK", "0.012"))
    footstep_frame_rms_threshold: float = float(os.getenv("FOOTSTEP_FRAME_RMS_THRESHOLD", "0.00045"))
    footstep_frame_peak_threshold: float = float(os.getenv("FOOTSTEP_FRAME_PEAK_THRESHOLD", "0.010"))
    footstep_dynamic_ratio: float = float(os.getenv("FOOTSTEP_DYNAMIC_RATIO", "2.0"))
    footstep_min_gap_seconds: float = float(os.getenv("FOOTSTEP_MIN_GAP_SECONDS", "0.16"))
    footstep_min_interval_seconds: float = float(os.getenv("FOOTSTEP_MIN_INTERVAL_SECONDS", "0.20"))
    footstep_max_interval_seconds: float = float(os.getenv("FOOTSTEP_MAX_INTERVAL_SECONDS", "1.30"))
    footstep_score_threshold: float = float(os.getenv("FOOTSTEP_SCORE_THRESHOLD", "0.65"))
    footstep_max_voice_score: float = float(os.getenv("FOOTSTEP_MAX_VOICE_SCORE", "0.40"))
    footstep_max_active_ratio: float = float(os.getenv("FOOTSTEP_MAX_ACTIVE_RATIO", "0.28"))

    loud_impulse_peak_threshold: float = float(os.getenv("LOUD_IMPULSE_PEAK_THRESHOLD", "0.60"))
    loud_impulse_max_active_ratio: float = float(os.getenv("LOUD_IMPULSE_MAX_ACTIVE_RATIO", "0.20"))


settings = Settings()
