from __future__ import annotations

from pathlib import Path
import numpy as np
from openai import OpenAI

from config import settings


SUBTITLE_HALLUCINATION_PHRASES = [
    "시청해주셔서 감사합니다",
    "시청해 주셔서 감사합니다",
    "구독해주세요",
    "구독해 주세요",
    "좋아요와 구독",
    "다음 영상에서 만나요",
    "감사합니다",
    "네 감사합니다",
    "여러분 감사합니다",
]


class WhisperAPI:
    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY가 .env에 필요합니다.")
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_stt_model

    def should_transcribe(self, audio: np.ndarray) -> bool:
        audio = np.asarray(audio, dtype=np.float32)
        if audio.size == 0:
            return False

        rms = float(np.sqrt(np.mean(audio ** 2)))
        peak = float(np.max(np.abs(audio)))

        if rms < settings.min_rms_for_stt and peak < settings.min_peak_for_stt:
            print(f"[STT] 무음/저음량으로 판단하여 STT 생략: rms={rms:.5f}, peak={peak:.5f}")
            return False
        return True

    def transcribe(self, audio_path: str | Path, language: str = "ko") -> str:
        audio_path = Path(audio_path)
        with audio_path.open("rb") as audio_file:
            result = self.client.audio.transcriptions.create(
                model=self.model,
                file=audio_file,
                language=language,
                temperature=0,
            )
        return self._clean_transcript((result.text or "").strip())

    def _clean_transcript(self, text: str) -> str:
        compact = text.replace(" ", "").replace(".", "").replace("!", "").replace("?", "")

        hallucination_compacts = [
            phrase.replace(" ", "").replace(".", "").replace("!", "").replace("?", "")
            for phrase in SUBTITLE_HALLUCINATION_PHRASES
        ]

        for phrase in hallucination_compacts:
            if compact == phrase:
                print(f"[STT] 자막형 환각 문구로 판단하여 무시: {text}")
                return ""

        emergency_keywords = [
            "아파", "아파요", "도와", "살려", "119", "구조", "불났",
            "쓰러", "다쳤", "갇혔", "위험", "피", "넘어졌"
        ]

        if any(k in compact for k in emergency_keywords):
            return text

        if len(compact) <= 1:
            return ""

        return text
