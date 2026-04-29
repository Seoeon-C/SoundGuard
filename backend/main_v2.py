from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

from config import BACKEND_DIR, settings
from decision_v2_v2 import GPTDecisionEngine, DecisionResult
from environmental_sound import BeatsEnvironmentClassifier, SoundEvent
from output_v2 import EventLoggerAndMessenger, FixedMessageSpeaker
from stt import WhisperAPI


TEMP_DIR = BACKEND_DIR / "outputs/temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


class AuthorizationManager:
    def __init__(self) -> None:
        self._disable_until = 0.0
        self._lock = threading.Lock()

    def is_disabled(self) -> bool:
        with self._lock:
            return time.time() < self._disable_until

    def remaining_seconds(self) -> float:
        with self._lock:
            return max(0.0, self._disable_until - time.time())

    def authenticate_and_disable(self) -> None:
        print("\n[ADMIN] 관리자 인증 요청")
        password = input("[ADMIN] password: ").strip()

        if password != settings.auth_password:
            print("[ADMIN] 인증 실패")
            return

        with self._lock:
            self._disable_until = time.time() + settings.auth_disable_seconds

        print(f"[ADMIN] 인증 성공. {settings.auth_disable_seconds}초 동안 감지 로직이 꺼집니다.")

    def start_listener(self) -> None:
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()

    def _loop(self) -> None:
        print("[ADMIN] p 입력 후 Enter: 관리자 인증")

        while True:
            try:
                command = input().strip().lower()

                if command in {"p", "pause", "admin"}:
                    self.authenticate_and_disable()

                elif command in {"h", "help"}:
                    print("[ADMIN] p 입력 후 Enter: 관리자 인증 후 일시 비활성화")

            except EOFError:
                break
            except Exception as exc:
                print(f"[ADMIN] 입력 처리 오류: {exc}")


class DwellTimeTracker:
    def __init__(self) -> None:
        self.detected_since: Optional[float] = None
        self.warn1_issued: bool = False

    def reset(self) -> None:
        self.detected_since = None
        self.warn1_issued = False

    def update(self, sound_event: SoundEvent, stt_text: str = "") -> float:
        now = time.time()

        # BEATs가 확인한 경우만 dwell 누적 (stt_text 단독으로는 dwell 안 쌓임)
        # 배경 소음 STT가 dwell을 채워 2차 경고를 앞당기는 문제 방지
        person_or_risk_detected = sound_event.situation in {1, 2}

        if person_or_risk_detected:
            if self.detected_since is None:
                self.detected_since = now

            return now - self.detected_since

        self.reset()
        return 0.0


class SoundGuardApp:
    def __init__(self) -> None:
        self.env_classifier = BeatsEnvironmentClassifier()
        self.stt = self._safe_create_stt()
        self.decision_engine = GPTDecisionEngine()
        self.speaker = FixedMessageSpeaker()
        self.logger = EventLoggerAndMessenger()
        self.auth = AuthorizationManager()
        self.dwell_tracker = DwellTimeTracker()

    def _safe_create_stt(self):
        try:
            return WhisperAPI()
        except Exception as exc:
            print(f"[WARN] STT 비활성화: {exc}")
            return None

    def run(self) -> None:
        print("=" * 70)
        print("SoundGuard 실행 (v2)")
        print("음향 기반 위험 예방·구조 시스템")
        print("0 정상상황 | 1 무단침입 | 2 위험 감지")
        print(f"위험구역: {settings.zone_name}")
        print(f"위치: {settings.location_text}")
        print(f"좌표: {settings.latitude}, {settings.longitude}")
        print(f"녹음 단위: {settings.chunk_seconds}초")
        print(f"STT 기준: rms>={settings.min_rms_for_stt}, peak>={settings.min_peak_for_stt}")
        print(f"관리자 인증: p 입력 후 Enter")
        print("종료: Ctrl+C")
        print("=" * 70)

        self.auth.start_listener()

        try:
            while True:
                if self.auth.is_disabled():
                    self.dwell_tracker.reset()
                    remain = self.auth.remaining_seconds()
                    print(f"[SYSTEM] 관리자 인증으로 감지 비활성화 중... 남은 시간 {remain:.1f}초")
                    time.sleep(1)
                    continue

                audio = self._record_audio()
                audio_path = self._save_audio(audio)

                if self.auth.is_disabled():
                    self.dwell_tracker.reset()
                    print("[SYSTEM] 녹음 후 비활성화 상태 확인됨. 이번 입력은 처리하지 않습니다.")
                    continue

                sound_event = self.env_classifier.classify(audio, settings.sample_rate)

                stt_text = ""

                # [FIX] BEATs가 situation=0으로 오분류해도 충분한 음량이면 STT 실행
                # 기존: situation in {1, 2} 일 때만 STT 호출
                # 수정: situation in {1, 2} 이거나 음량이 STT 기준 이상이면 호출
                stt_trigger = (
                    sound_event.situation in {1, 2}
                    or sound_event.rms >= settings.min_rms_for_stt
                    or sound_event.peak >= settings.min_peak_for_stt
                )
                if stt_trigger:
                    stt_text = self._try_stt(audio, audio_path)

                dwell_seconds = self.dwell_tracker.update(sound_event, stt_text=stt_text)

                decision = self.decision_engine.decide(
                    sound_event=sound_event,
                    stt_text=stt_text,
                    dwell_seconds=dwell_seconds,
                    authorized=False,
                )

                # [FIX] 2차 경고는 반드시 1차 경고 발령 이후에만 가능
                if decision.tts_key == "INTRUSION_WARN_2" and not self.dwell_tracker.warn1_issued:
                    print("[WARN_ORDER] 1차 경고 미발령 상태. INTRUSION_WARN_2 → INTRUSION_WARN_1 강제 변환")
                    decision = DecisionResult(
                        situation=decision.situation,
                        situation_name=decision.situation_name,
                        risk_level="low",
                        reason=decision.reason,
                        action="1차 경고 방송",
                        tts_key="INTRUSION_WARN_1",
                        send_to_control_room=decision.send_to_control_room,
                        emergency_candidate=decision.emergency_candidate,
                        source=decision.source + " (forced warn1)",
                    )

                # BEATs가 실제 사람을 감지했을 때만 1차 발령 기록
                # 배경 소음 STT 단독으로 warn1_issued가 세팅되면 2차가 바로 나올 수 있음
                if decision.tts_key == "INTRUSION_WARN_1" and sound_event.situation in {1, 2}:
                    self.dwell_tracker.warn1_issued = True

                print(
                    f"[RESULT] {decision.situation_name} | "
                    f"sound={sound_event.raw_label} | "
                    f"stt={stt_text or '없음'}"
                )

                if decision.tts_key != "NONE":
                    self.speaker.speak(decision.tts_key)

                if decision.situation in {1, 2} or decision.send_to_control_room:
                    self.logger.record_and_send(
                        decision=decision,
                        sound_event=sound_event,
                        stt_text=stt_text,
                        dwell_seconds=dwell_seconds,
                    )

        except KeyboardInterrupt:
            print("\nSoundGuard 종료")

    def _try_stt(self, audio: np.ndarray, audio_path: Path) -> str:
        if self.stt is None:
            print("[STT] STT 객체 없음. 생략")
            return ""

        try:
            if self.stt.should_transcribe(audio):
                text = self.stt.transcribe(audio_path)
                print(f"[STT] {text}" if text else "[STT] 유효한 문장 없음")
                return text

        except Exception as exc:
            print(f"[WARN] STT 실패: {exc}")

        return ""

    def _record_audio(self) -> np.ndarray:
        print(f"[REC] {settings.chunk_seconds}초 녹음 중...")

        audio = sd.rec(
            int(settings.sample_rate * settings.chunk_seconds),
            samplerate=settings.sample_rate,
            channels=1,
            dtype="float32",
        )

        sd.wait()
        return audio.squeeze()

    def _save_audio(self, audio: np.ndarray) -> Path:
        path = TEMP_DIR / "latest.wav"
        sf.write(path, audio, settings.sample_rate)
        return path


if __name__ == "__main__":
    SoundGuardApp().run()
