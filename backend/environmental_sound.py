from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List
from beats_runtime.beats import load_model
import librosa
import numpy as np
import torch

from config import settings


@dataclass
class SoundEvent:
    label: str
    confidence: float
    raw_label: str
    rms: float = 0.0
    peak: float = 0.0

    @property
    def is_nature(self) -> bool:
        return self.label == "nature"

    @property
    def is_speech(self) -> bool:
        return self.label == "speech"

    @property
    def is_footstep(self) -> bool:
        return self.label == "footstep"

    @property
    def is_emergency_sound(self) -> bool:
        return self.label == "emergency_sound"

    @property
    def is_unknown_speech_candidate(self) -> bool:
        return (
            self.label == "unknown"
            and settings.allow_unknown_stt
            and (self.rms >= settings.min_rms_for_stt or self.peak >= settings.min_peak_for_stt)
        )


def get_audio_stats(audio: np.ndarray) -> tuple[float, float]:
    audio = np.asarray(audio, dtype=np.float32)
    if audio.size == 0:
        return 0.0, 0.0
    return float(np.sqrt(np.mean(audio ** 2))), float(np.max(np.abs(audio)))


class BeatsEnvironmentClassifier:
    """
    BEATs 1차 분류:
    0. nature: 자연/배경 소리 -> pass
    1. speech: 말소리 -> Whisper STT
    2. footstep: 발소리 -> 무단침입
    + emergency_sound: 비명/충격음/파손음 -> 위급
    + unknown_speech_candidate: unknown이지만 음량 충분 -> Whisper STT
    """

    def __init__(self) -> None:
        self.sample_rate = settings.sample_rate
        self.device = torch.device(settings.device)
        self.model = None
        self.labels: List[str] = []
        self.ready = False
        self.model, self.label_dict = load_model(settings.beats_checkpoint_path)
        try:
            self._load_beats()
            self.ready = True
            print("[BEATs] 모델 로드 성공")
        except Exception as exc:
            print(f"[WARN] BEATs 모델 로드 실패. fallback 모드로 실행합니다: {exc}")

    def _load_beats(self) -> None:
        beats_py = Path(settings.beats_py_dir) / "BEATs.py"
        checkpoint_path = Path(settings.beats_checkpoint_path)
        beats_dir = Path(settings.beats_py_dir).resolve()

        if str(beats_dir) not in sys.path:
            sys.path.insert(0, str(beats_dir))

        if not beats_py.exists():
            raise FileNotFoundError(f"BEATs.py 파일을 찾을 수 없습니다: {beats_py}")
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"BEATs 체크포인트를 찾을 수 없습니다: {checkpoint_path}")

        spec = importlib.util.spec_from_file_location("beats_module", str(beats_py))
        if spec is None or spec.loader is None:
            raise RuntimeError("BEATs.py import 준비 실패")

        module = importlib.util.module_from_spec(spec)
        sys.modules["beats_module"] = module
        spec.loader.exec_module(module)

        checkpoint = torch.load(checkpoint_path, map_location="cpu")
        cfg = module.BEATsConfig(checkpoint["cfg"])

        model = module.BEATs(cfg)
        model.load_state_dict(checkpoint["model"])
        model.eval()
        model.to(self.device)

        self.model = model
        self.labels = checkpoint.get("label_names", [])

    def classify(self, audio: np.ndarray, sr: int) -> SoundEvent:
        rms, peak = get_audio_stats(audio)
        audio = self._prepare_audio(audio, sr)

        if audio.size == 0:
            return SoundEvent("nature", 0.0, "empty", rms, peak)

        if not self.ready:
            return self._fallback_classify(rms, peak)

        with torch.no_grad():
            wav = torch.tensor(audio, dtype=torch.float32).unsqueeze(0).to(self.device)
            padding_mask = torch.zeros(wav.shape, dtype=torch.bool).to(self.device)
            result = self.model.extract_features(wav, padding_mask=padding_mask)[0]

            if result.ndim == 3:
                logits = result.mean(dim=1)
            else:
                logits = result

            probs = torch.softmax(logits, dim=-1).cpu().numpy()[0]
            idx = int(np.argmax(probs))
            confidence = float(probs[idx])

        raw_label = self.labels[idx] if self.labels and idx < len(self.labels) else f"class_{idx}"
        refined_label = self._map_to_refined_label(raw_label, confidence, rms, peak)
        return SoundEvent(refined_label, confidence, raw_label, rms, peak)

    def _prepare_audio(self, audio: np.ndarray, sr: int) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        if sr != self.sample_rate:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=self.sample_rate)

        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 0:
            audio = audio / peak

        return audio.astype(np.float32)

    def _map_to_refined_label(self, raw_label: str, confidence: float, rms: float, peak: float) -> str:
        text = raw_label.lower()

        nature_keywords = [
            "silence", "ambient", "background", "wind", "rain", "water", "stream",
            "sea", "ocean", "waves", "bird", "birds", "insect", "cricket",
            "frog", "thunder", "rustling leaves", "leaves", "forest", "traffic",
            "engine", "air conditioning"
        ]
        speech_keywords = [
            "speech", "talk", "talking", "conversation", "human voice",
            "male speech", "female speech", "child speech", "narration", "monologue",
            "whispering", "murmur", "babbling"
        ]
        footstep_keywords = [
            "footstep", "footsteps", "walking", "walk", "steps", "step",
            "running", "run", "jogging", "stomp", "stomping"
        ]
        emergency_keywords = [
            "scream", "screaming", "yell", "cry", "crying", "shout",
            "crash", "bang", "thump", "slam", "impact", "explosion",
            "glass", "shatter", "breaking", "gunshot"
        ]

        if any(k in text for k in footstep_keywords):
            return "footstep"
        if any(k in text for k in emergency_keywords):
            return "emergency_sound"
        if any(k in text for k in speech_keywords):
            return "speech"
        if any(k in text for k in nature_keywords):
            return "nature"

        if confidence < 0.01 and rms < settings.min_rms_for_stt and peak < settings.min_peak_for_stt:
            return "nature"

        return "unknown"

    def _fallback_classify(self, rms: float, peak: float) -> SoundEvent:
        if rms < settings.min_rms_for_stt and peak < settings.min_peak_for_stt:
            return SoundEvent("nature", 0.8, "fallback_silence_or_nature", rms, peak)
        # fallback은 실제로 speech/footstep 구분이 불가능하므로 unknown으로 둔다.
        # main에서 unknown_speech_candidate이면 STT로 보낸다.
        return SoundEvent("unknown", min(0.95, rms * 10), "fallback_audio_detected", rms, peak)
