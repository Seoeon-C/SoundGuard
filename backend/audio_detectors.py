from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from config import settings


@dataclass
class SignalDetectionResult:
    voice_detected: bool
    footstep_detected: bool
    loud_impulse_detected: bool
    voice_score: float
    footstep_score: float
    rms: float
    peak: float
    peak_count: int
    peak_times: List[float]
    active_ratio: float
    impulse_ratio: float
    zero_crossing_rate: float
    reason: str


class SignalDetector:
    """
    BEATs 앞단에서 동작하는 가벼운 신호 기반 감지기.

    이번 패치의 핵심:
    - 사람 목소리의 음절/파열음도 peak를 만들기 때문에, 반복 peak만으로 발소리 처리하지 않는다.
    - 발소리는 active_ratio가 낮고, voice_score가 낮은 경우에만 인정한다.
    - 작은 목소리는 VAD 기준을 낮춰 Whisper 후보로 먼저 보낸다.
    """

    def analyze(self, audio: np.ndarray, sr: int) -> SignalDetectionResult:
        x = self._mono_float(audio)
        rms = self._rms(x)
        peak = self._peak(x)
        active_ratio = self._active_ratio(x, sr)
        zcr = self._zero_crossing_rate(x)
        impulse_ratio = peak / max(rms, 1e-6)

        voice_score = self._voice_score(x, sr, rms, peak, active_ratio, zcr)
        footstep_score, peak_times = self._footstep_score(x, sr)
        loud_impulse = self._loud_impulse(x, sr, peak_times, rms, peak)

        voice_detected = voice_score >= settings.vad_voice_score_threshold
        footstep_detected = (
            not voice_detected
            and voice_score <= settings.footstep_max_voice_score
            and active_ratio <= settings.footstep_max_active_ratio
            and footstep_score >= settings.footstep_score_threshold
            and len(peak_times) >= settings.footstep_min_peaks
        )

        reasons = []
        if voice_detected:
            reasons.append(f"voice_score={voice_score:.2f}")
        if footstep_detected:
            reasons.append(f"footstep_score={footstep_score:.2f}, peaks={len(peak_times)}")
        elif footstep_score >= settings.footstep_score_threshold:
            if voice_score > settings.footstep_max_voice_score:
                reasons.append(f"footstep_blocked_by_voice_score={voice_score:.2f}")
            if active_ratio > settings.footstep_max_active_ratio:
                reasons.append(f"footstep_blocked_by_active_ratio={active_ratio:.2f}")
        if loud_impulse:
            reasons.append("loud_impulse")
        if not reasons:
            reasons.append("no_signal_candidate")

        return SignalDetectionResult(
            voice_detected=voice_detected,
            footstep_detected=footstep_detected,
            loud_impulse_detected=loud_impulse,
            voice_score=voice_score,
            footstep_score=footstep_score,
            rms=rms,
            peak=peak,
            peak_count=len(peak_times),
            peak_times=peak_times,
            active_ratio=active_ratio,
            impulse_ratio=impulse_ratio,
            zero_crossing_rate=zcr,
            reason=", ".join(reasons),
        )

    def _mono_float(self, audio: np.ndarray) -> np.ndarray:
        x = np.asarray(audio, dtype=np.float32)
        if x.ndim > 1:
            x = x.mean(axis=1)
        return x

    def _rms(self, x: np.ndarray) -> float:
        if x.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(x ** 2)))

    def _peak(self, x: np.ndarray) -> float:
        if x.size == 0:
            return 0.0
        return float(np.max(np.abs(x)))

    def _frame_rms(self, x: np.ndarray, sr: int, frame_ms: float = 30.0, hop_ms: float = 10.0) -> np.ndarray:
        frame = max(1, int(sr * frame_ms / 1000.0))
        hop = max(1, int(sr * hop_ms / 1000.0))
        if x.size < frame:
            return np.array([self._rms(x)], dtype=np.float32)
        values = []
        for start in range(0, x.size - frame + 1, hop):
            chunk = x[start:start + frame]
            values.append(np.sqrt(np.mean(chunk ** 2)))
        return np.asarray(values, dtype=np.float32)

    def _frame_peak(self, x: np.ndarray, sr: int, frame_ms: float = 40.0, hop_ms: float = 20.0) -> np.ndarray:
        frame = max(1, int(sr * frame_ms / 1000.0))
        hop = max(1, int(sr * hop_ms / 1000.0))
        if x.size < frame:
            return np.array([self._peak(x)], dtype=np.float32)
        values = []
        for start in range(0, x.size - frame + 1, hop):
            chunk = x[start:start + frame]
            values.append(np.max(np.abs(chunk)))
        return np.asarray(values, dtype=np.float32)

    def _active_ratio(self, x: np.ndarray, sr: int) -> float:
        frames = self._frame_rms(x, sr)
        if frames.size == 0:
            return 0.0
        return float(np.mean(frames >= settings.vad_frame_rms_threshold))

    def _zero_crossing_rate(self, x: np.ndarray) -> float:
        if x.size < 2:
            return 0.0
        signs = np.signbit(x)
        return float(np.mean(signs[1:] != signs[:-1]))

    def _voice_score(self, x: np.ndarray, sr: int, rms: float, peak: float, active_ratio: float, zcr: float) -> float:
        if x.size == 0:
            return 0.0

        score = 0.0
        if rms >= settings.vad_min_rms:
            score += 0.30
        if peak >= settings.vad_min_peak:
            score += 0.15
        if active_ratio >= settings.vad_min_active_ratio:
            score += 0.40
        if settings.vad_min_zcr <= zcr <= settings.vad_max_zcr:
            score += 0.15
        return min(1.0, score)

    def _footstep_score(self, x: np.ndarray, sr: int) -> tuple[float, List[float]]:
        if x.size == 0:
            return 0.0, []

        rms_frames = self._frame_rms(x, sr, frame_ms=40.0, hop_ms=20.0)
        peak_frames = self._frame_peak(x, sr, frame_ms=40.0, hop_ms=20.0)
        if rms_frames.size < 3 or peak_frames.size < 3:
            return 0.0, []

        rms_threshold = max(
            settings.footstep_frame_rms_threshold,
            float(np.median(rms_frames) * settings.footstep_dynamic_ratio),
        )
        peak_threshold = max(
            settings.footstep_frame_peak_threshold,
            float(np.median(peak_frames) * settings.footstep_dynamic_ratio),
        )
        min_gap_frames = max(1, int(settings.footstep_min_gap_seconds / 0.02))
        peak_indices: List[int] = []
        last_idx = -10_000

        combined = peak_frames + (rms_frames * 2.0)
        for i in range(1, len(combined) - 1):
            is_peak_frame = peak_frames[i] >= peak_threshold
            is_rms_frame = rms_frames[i] >= rms_threshold
            if not (is_peak_frame or is_rms_frame):
                continue
            if combined[i] < combined[i - 1] or combined[i] < combined[i + 1]:
                continue
            if i - last_idx < min_gap_frames:
                if peak_indices and combined[i] > combined[peak_indices[-1]]:
                    peak_indices[-1] = i
                    last_idx = i
                continue
            peak_indices.append(i)
            last_idx = i

        peak_times = [round(i * 0.02, 3) for i in peak_indices]
        valid_intervals = 0
        for a, b in zip(peak_times, peak_times[1:]):
            interval = b - a
            if settings.footstep_min_interval_seconds <= interval <= settings.footstep_max_interval_seconds:
                valid_intervals += 1

        global_peak = self._peak(x)
        global_rms = self._rms(x)
        impulse_ratio = global_peak / max(global_rms, 1e-6)

        score = 0.0
        if len(peak_times) >= settings.footstep_min_peaks:
            score += 0.45
        if settings.footstep_min_peaks <= 1 or valid_intervals >= max(1, settings.footstep_min_peaks - 1):
            score += 0.20
        if global_peak >= settings.footstep_min_peak:
            score += 0.25
        if impulse_ratio >= 8.0:
            score += 0.10
        return min(1.0, score), peak_times

    def _loud_impulse(self, x: np.ndarray, sr: int, peak_times: List[float], rms: float, peak: float) -> bool:
        if peak < settings.loud_impulse_peak_threshold:
            return False
        active_ratio = self._active_ratio(x, sr)
        return active_ratio <= settings.loud_impulse_max_active_ratio or len(peak_times) <= 2
