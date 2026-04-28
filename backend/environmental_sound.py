from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import librosa
import numpy as np
import torch

from beats_runtime.beats import load_audioset_ontology, load_model
from config import settings


@dataclass
class SoundEvent:
    label: str
    confidence: float
    raw_label: str
    rms: float = 0.0
    peak: float = 0.0
    top_labels: List[Tuple[str, float]] | None = None

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
    BEATs 단일 모델 기반 1차 소리 분류기.

    역할:
    1. BEATs 체크포인트를 한 번만 로드한다.
    2. 입력 오디오를 BEATs 입력 형식으로 전처리한다.
    3. BEATs Top-K 예측 라벨을 얻는다.
    4. AudioSet 라벨명을 프로젝트 내부 라벨로 변환한다.

    내부 라벨:
    - nature: 자연음/배경음/pass
    - speech: 사람 말소리/STT 대상
    - footstep: 발소리/무단침입 대상
    - emergency_sound: 비명, 파손음, 폭발음 등 위급음
    - unknown: 확실하지 않은 소리. 음량 기준을 넘으면 STT 후보가 될 수 있음
    """

    def __init__(self) -> None:
        self.sample_rate = settings.sample_rate
        self.device = torch.device(settings.device)
        self.model = None
        self.label_dict = {}
        self.id_to_name = {}
        self.ready = False

        try:
            self.model, self.label_dict = load_model(settings.beats_checkpoint_path)
            self.model.to(self.device)
            self.model.eval()
            self.id_to_name = load_audioset_ontology()
            self.ready = True
            print("[BEATs] 단일 모델 로드 성공")
        except Exception as exc:
            print(f"[WARN] BEATs 모델 로드 실패. fallback 모드로 실행합니다: {exc}")

    def classify(self, audio: np.ndarray, sr: int) -> SoundEvent:
        rms, peak = get_audio_stats(audio)
        audio = self._prepare_audio(audio, sr)

        if audio.size == 0:
            return SoundEvent("nature", 0.0, "empty", rms, peak, [])

        if not self.ready or self.model is None:
            return self._fallback_classify(rms, peak)

        with torch.no_grad():
            wav = torch.tensor(audio, dtype=torch.float32).unsqueeze(0).to(self.device)
            padding_mask = torch.zeros(wav.shape, dtype=torch.bool, device=self.device)

            output = self.model.extract_features(wav, padding_mask=padding_mask)[0]

            # AudioSet finetuned BEATs는 일반적으로 multi-label 출력이므로 sigmoid를 사용한다.
            # 출력이 [B, T, C] 형태면 시간축 평균으로 [B, C]로 만든다.
            if output.ndim == 3:
                logits = output.mean(dim=1)
            else:
                logits = output

            probs = torch.sigmoid(logits)[0]
            top_k = min(5, probs.numel())
            top_values, top_indices = torch.topk(probs, k=top_k)

        top_labels = self._decode_top_labels(top_indices, top_values)
        raw_label = top_labels[0][0] if top_labels else "unknown"
        confidence = top_labels[0][1] if top_labels else 0.0
        refined_label = self._map_to_refined_label(top_labels, confidence, rms, peak)

        return SoundEvent(refined_label, confidence, raw_label, rms, peak, top_labels)

    def _prepare_audio(self, audio: np.ndarray, sr: int) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float32)

        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        if sr != self.sample_rate:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=self.sample_rate)

        # BEATs 입력을 안정화하기 위한 peak normalization.
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 0:
            audio = audio / peak

        return audio.astype(np.float32)

    def _decode_top_labels(self, indices: torch.Tensor, values: torch.Tensor) -> List[Tuple[str, float]]:
        top_labels: List[Tuple[str, float]] = []

        for idx, score in zip(indices.detach().cpu().tolist(), values.detach().cpu().tolist()):
            label_id = self.label_dict.get(int(idx), f"class_{int(idx)}")
            label_name = self.id_to_name.get(label_id, label_id)
            top_labels.append((str(label_name), float(score)))

        return top_labels

    def _map_to_refined_label(
        self,
        top_labels: List[Tuple[str, float]],
        confidence: float,
        rms: float,
        peak: float,
    ) -> str:
        joined = " ".join(label for label, _score in top_labels).lower()

        nature_keywords = [
            "silence", "ambient", "background", "wind", "rain", "water", "stream",
            "sea", "ocean", "waves", "bird", "birds", "insect", "cricket",
            "frog", "thunder", "rustling leaves", "leaves", "forest", "traffic",
            "engine", "air conditioning", "environmental noise", "quiet",
        ]
        speech_keywords = [
            "speech", "talk", "talking", "conversation", "human voice",
            "male speech", "female speech", "child speech", "narration", "monologue",
            "whispering", "murmur", "babbling", "voice",
        ]
        footstep_keywords = [
            "footstep", "footsteps", "walking", "walk", "steps", "step",
            "running", "run", "jogging", "stomp", "stomping", "shuffle",
        ]
        emergency_keywords = [
            "scream", "screaming", "yell", "cry", "crying", "shout",
            "crash", "bang", "thump", "slam", "impact", "explosion",
            "glass", "shatter", "breaking", "gunshot", "alarm", "siren",
            "fire alarm", "smash", "emergency",
        ]

        if any(k in joined for k in emergency_keywords):
            return "emergency_sound"
        if any(k in joined for k in footstep_keywords):
            return "footstep"
        if any(k in joined for k in speech_keywords):
            return "speech"
        if any(k in joined for k in nature_keywords):
            return "nature"

        if confidence < 0.01 and rms < settings.min_rms_for_stt and peak < settings.min_peak_for_stt:
            return "nature"

        return "unknown"

    def _fallback_classify(self, rms: float, peak: float) -> SoundEvent:
        if rms < settings.min_rms_for_stt and peak < settings.min_peak_for_stt:
            return SoundEvent("nature", 0.8, "fallback_silence_or_nature", rms, peak, [])

        return SoundEvent("unknown", min(0.95, rms * 10), "fallback_audio_detected", rms, peak, [])
