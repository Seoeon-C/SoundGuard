from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import numpy as np
import torch
import torch.nn as nn
import librosa

from config import BACKEND_DIR, settings


beats_dir = Path(settings.beats_py_dir).resolve()
if str(beats_dir) not in sys.path:
    sys.path.insert(0, str(beats_dir))

from BEATs import BEATs, BEATsConfig


RESULT_LABELS = {
    0: "정상상황",
    1: "침입 신호",
    2: "위험 감지",
}


PROJECT_TASK_LABELS = ["background", "intrusion", "emergency", "impact_noise", "loud_noise"]


PROJECT_LABEL_TO_RESULT = {
    "background": (0, RESULT_LABELS[0]),
    "loud_noise": (0, RESULT_LABELS[0]),
    "intrusion": (1, RESULT_LABELS[1]),
    "emergency": (2, RESULT_LABELS[2]),
    "impact_noise": (2, RESULT_LABELS[2]),
}


SPEECH_LABELS = {
    "Speech",
    "Male speech, man speaking",
    "Female speech, woman speaking",
    "Child speech, kid speaking",
    "Conversation",
    "Narration, monologue",
    "Babbling",
    "Whispering",
    "Shout",
    "Yell",
    "Children shouting",
    "Screaming",
    "Crying, sobbing",
    "Baby cry, infant cry",
    "Laughter",
    "Baby laughter",
    "Giggle",
    "Snicker",
    "Chuckle, chortle",
    "Belly laugh",
    "Cough",
    "Sneeze",
    "Breathing",
    "Throat clearing",
    "Humming",
    "Sigh",
    "Whimper",
    "Groan",
    "Gasp",
    "Wail, moan",
    "Singing",
    "Male singing",
    "Female singing",
    "Child singing",
    "Synthetic singing",
    "Chant",
    "Choir",
    "Rapping",
}


NORMAL_LABELS = {
    "Silence",
    "Environmental noise",
    "Ambient music",
    "Background music",
    "Wind",
    "Wind noise (microphone)",
    "Rustling leaves",
    "Rain",
    "Raindrop",
    "Rain on surface",
    "Thunder",
    "Thunderstorm",
    "Water",
    "Stream",
    "Ocean",
    "Waves, surf",
    "Waterfall",
    "Bird",
    "Bird vocalization, bird call, bird song",
    "Bird flight, flapping wings",
    "Chirp, tweet",
    "Crow",
    "Caw",
    "Owl",
    "Hoot",
    "Pigeon, dove",
    "Coo",
    "Frog",
    "Croak",
    "Insect",
    "Cricket",
    "Bee, wasp, etc.",
    "Fly, housefly",
    "Mosquito",
    "Outside, rural or natural",
    "Outside, urban or manmade",
    "Inside, small room",
    "Inside, large room or hall",
    "Inside, public space",
    "Air conditioning",
    "Field recording",
}


INTRUSION_LABELS = {
    "Scratch",
    "Zipper (clothing)",
    "Slap, smack",
    "Tap",
    "Clatter",
    "Door",
    "Sliding door",
    "Slam",
    "Crackle",
    "Finger snapping",
    "Clang",
    "Smash, crash",
    "Scissors",
    "Rustle",
    "Crack",
    "Breaking",
    "Knock",
    "Walk, footsteps",
    "Clip-clop",
    "Thunk",
    "Splinter",
    "Wood",
    "Chop",
    "Shatter",
    "Rattle",
    "Boom",
    "Keys jangling",
    "Patter",
    "Bang",
    "Drawer open or close",
    "Scrape",
    "Tools",
    "Power tool",
    "Drill",
    "Squeak",
    "Thump, thud",
    "Creak",
    "Sanding",
    "Rub",
    "Squish",
    "Filing (rasp)",
    "Cutlery, silverware",
    "Dishes, pots, and pans",
    "Chink, clink",
    "Shuffle",
    "Crunch",
    "Glass",
    "Run",
    "Cupboard open or close",
    "Clicking",
    "Whack, thwack",
    "Coin (dropping)",
    "Crumpling, crinkling",
    "Vibration",
    "Hammer",
    "Doorbell",
    "Hands",
    "Applause",
    "Biting",
    "Crushing",
    "Tearing",
}


@dataclass
class SoundEvent:
    situation: int
    label: str
    confidence: float
    raw_label: str
    top_labels: List[Tuple[str, float]]
    rms: float = 0.0
    peak: float = 0.0

    @property
    def is_normal(self) -> bool:
        return self.situation == 0

    @property
    def is_speech(self) -> bool:
        return self.situation == 1

    @property
    def is_abnormal(self) -> bool:
        return self.situation == 2


def get_audio_stats(audio: np.ndarray) -> tuple[float, float]:
    audio = np.asarray(audio, dtype=np.float32)

    if audio.size == 0:
        return 0.0, 0.0

    rms = float(np.sqrt(np.mean(audio ** 2)))
    peak = float(np.max(np.abs(audio)))

    return rms, peak


class ProjectBeatsClassifier(nn.Module):
    """
    BEATs backbone + project 5-class classifier.

    This matches the architecture used in transfer_learning/train_beats_project.py.
    """

    def __init__(self, beats_model: nn.Module, embed_dim: int, num_classes: int) -> None:
        super().__init__()
        self.beats = beats_model
        self.classifier = nn.Sequential(
            nn.LayerNorm(embed_dim),
            nn.Dropout(0.2),
            nn.Linear(embed_dim, num_classes),
        )

    def forward(self, waveforms: torch.Tensor) -> torch.Tensor:
        waveforms = torch.nan_to_num(waveforms.float(), nan=0.0, posinf=0.0, neginf=0.0)
        padding_mask = torch.zeros(waveforms.shape, dtype=torch.bool, device=waveforms.device)
        features, _ = self.beats.extract_features(waveforms, padding_mask=padding_mask)
        pooled = features.mean(dim=1)
        return self.classifier(pooled)


class BeatsEnvironmentClassifier:
    def __init__(self) -> None:
        self.sample_rate = settings.sample_rate
        self.device = torch.device(settings.device)

        self.model = None
        self.model_kind = "audioset"
        self.project_labels = PROJECT_TASK_LABELS
        self.label_dict = {}
        self.id_to_name = {}

        self.ready = False

        try:
            self._load_beats()
            self.ready = True
            print(f"[BEATs] 모델 로드 성공 ({self.model_kind})")

        except Exception as exc:
            print(f"[WARN] BEATs 모델 로드 실패. fallback 모드로 실행합니다: {exc}")

    def _load_beats(self) -> None:
        checkpoint_path = Path(settings.beats_checkpoint_path)

        if not checkpoint_path.exists():
            raise FileNotFoundError(f"BEATs 체크포인트를 찾을 수 없습니다: {checkpoint_path}")

        checkpoint = self._torch_load(checkpoint_path)

        if "model_state" in checkpoint and "labels" in checkpoint:
            self._load_project_checkpoint(checkpoint, checkpoint_path)
            return

        self._load_audioset_checkpoint(checkpoint)

    def _load_project_checkpoint(self, checkpoint: dict, checkpoint_path: Path) -> None:
        base_checkpoint_path = Path(settings.beats_base_checkpoint_path)

        if not base_checkpoint_path.exists():
            raise FileNotFoundError(
                "프로젝트 전이학습 모델을 로드하려면 원본 BEATs cfg가 필요합니다. "
                f"BEATS_BASE_CHECKPOINT_PATH를 확인하세요: {base_checkpoint_path}"
            )

        base_checkpoint = self._torch_load(base_checkpoint_path)
        cfg = BEATsConfig(base_checkpoint["cfg"])
        cfg.finetuned_model = False

        beats = BEATs(cfg)
        model = ProjectBeatsClassifier(
            beats_model=beats,
            embed_dim=cfg.encoder_embed_dim,
            num_classes=len(checkpoint["labels"]),
        )
        model.load_state_dict(checkpoint["model_state"])
        model.eval()
        model.to(self.device)

        self.model = model
        self.model_kind = "project"
        self.project_labels = list(checkpoint["labels"])
        print(f"[BEATs] 프로젝트 전이학습 체크포인트 사용: {checkpoint_path}")

    def _load_audioset_checkpoint(self, checkpoint: dict) -> None:
        ontology_path = BACKEND_DIR / "ontology.json"

        if not ontology_path.exists():
            raise FileNotFoundError("ontology.json 파일을 찾을 수 없습니다.")

        with ontology_path.open("r", encoding="utf-8") as f:
            ontology_data = json.load(f)

        self.id_to_name = {item["id"]: item["name"] for item in ontology_data}

        cfg = BEATsConfig(checkpoint["cfg"])
        model = BEATs(cfg)
        model.load_state_dict(checkpoint["model"])
        model.eval()
        model.to(self.device)

        self.model = model
        self.model_kind = "audioset"
        self.label_dict = checkpoint["label_dict"]

    @staticmethod
    def _torch_load(path: Path):
        try:
            return torch.load(path, map_location="cpu", weights_only=False)
        except TypeError:
            return torch.load(path, map_location="cpu")

    def classify(self, audio: np.ndarray, sr: int) -> SoundEvent:
        rms, peak = get_audio_stats(audio)
        audio = self._prepare_audio(audio, sr)

        # 🔥 추가: 저소음이면 무조건 정상
        if rms < 0.003 and peak < 0.02:
            return SoundEvent(
                situation=0,
                label="정상상황",
                confidence=1.0,
                raw_label="low_volume",
                top_labels=[],
                rms=rms,
                peak=peak,
            )

        if audio.size == 0:
            return SoundEvent(
                situation=0,
                label="정상상황",
                confidence=0.0,
                raw_label="empty",
                top_labels=[],
                rms=rms,
                peak=peak,
            )

        if not self.ready:
            return self._fallback_classify(rms, peak)

        wav = torch.tensor(audio, dtype=torch.float32).unsqueeze(0).to(self.device)

        if self.model_kind == "project":
            with torch.no_grad():
                logits = self.model(wav)[0]
                probs = torch.softmax(logits, dim=0)
                topk = torch.topk(probs, k=min(3, probs.numel()))

            top_labels = [
                (self.project_labels[int(idx)], float(score))
                for idx, score in zip(topk.indices, topk.values)
            ]
            situation, label, reason_label, confidence = self._classify_project_labels(top_labels)

            return SoundEvent(
                situation=situation,
                label=label,
                confidence=confidence,
                raw_label=reason_label,
                top_labels=top_labels,
                rms=rms,
                peak=peak,
            )

        padding_mask = torch.zeros(wav.shape, dtype=torch.bool).to(self.device)

        with torch.no_grad():
            output = self.model.extract_features(wav, padding_mask=padding_mask)[0]

            if output.ndim == 3:
                output = output.mean(dim=1)

            probs = torch.sigmoid(output[0])
            topk = torch.topk(probs, k=3)

        top_labels: List[Tuple[str, float]] = []

        for idx, score in zip(topk.indices, topk.values):
            label_id = self.label_dict[int(idx)]
            label_name = self.id_to_name.get(label_id, label_id)
            top_labels.append((label_name, float(score)))

        situation, label, reason_label, confidence = self._classify_top_labels(top_labels)

        return SoundEvent(
            situation=situation,
            label=label,
            confidence=confidence,
            raw_label=reason_label,
            top_labels=top_labels,
            rms=rms,
            peak=peak,
        )

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

    def _classify_project_labels(self, top_labels: List[Tuple[str, float]]) -> tuple[int, str, str, float]:
        if not top_labels:
            return 0, RESULT_LABELS[0], "project_empty", 0.0

        task_label, confidence = top_labels[0]
        situation, label = PROJECT_LABEL_TO_RESULT.get(task_label, (0, RESULT_LABELS[0]))
        return situation, label, task_label, confidence

    # 🔥 수정: 합산 방식으로 변경
    def _classify_top_labels(self, top_labels: List[Tuple[str, float]]) -> tuple[int, str, str, float]:
        speech_score = 0.0
        normal_score = 0.0
        intrusion_score = 0.0

        speech_reason = None
        normal_reason = None
        intrusion_reason = None

        for label_name, score in top_labels:
            if label_name in SPEECH_LABELS:
                speech_score += score
                speech_reason = label_name

            elif label_name in INTRUSION_LABELS:
                intrusion_score += score
                intrusion_reason = label_name

            elif label_name in NORMAL_LABELS:
                normal_score += score
                normal_reason = label_name

            else:
                normal_score += score
                normal_reason = label_name

        if speech_score > intrusion_score and speech_score > normal_score:
            return 1, RESULT_LABELS[1], speech_reason or "speech", speech_score

        if intrusion_score > normal_score:
            return 2, RESULT_LABELS[2], intrusion_reason or "intrusion_sound", intrusion_score

        return 0, RESULT_LABELS[0], normal_reason or "normal", normal_score

    def _fallback_classify(self, rms: float, peak: float) -> SoundEvent:
        if rms < settings.min_rms_for_stt and peak < settings.min_peak_for_stt:
            return SoundEvent(
                situation=0,
                label="정상상황",
                confidence=0.8,
                raw_label="fallback_silence_or_normal",
                top_labels=[],
                rms=rms,
                peak=peak,
            )

        return SoundEvent(
            situation=2,
            label="기타 이상 소리",
            confidence=min(0.95, rms * 10),
            raw_label="fallback_audio_detected",
            top_labels=[],
            rms=rms,
            peak=peak,
        )
