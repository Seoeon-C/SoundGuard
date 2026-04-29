from __future__ import annotations

# backend/server.py
import sys
import os
from pathlib import Path

# --- 중요: main.py와 동일한 경로 로직 추가 ---
current_dir = Path(__file__).resolve().parent
beats_path = str(current_dir / "beats")
if beats_path not in sys.path:
    sys.path.insert(0, beats_path)
# ------------------------------------------

import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

app = FastAPI()

import getpass
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

from config import settings
from decision import GPTDecisionEngine
from environmental_sound import BeatsEnvironmentClassifier, SoundEvent
from output import EventLoggerAndMessenger, FixedMessageSpeaker
from stt import WhisperAPI


TEMP_DIR = Path("outputs/temp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


class AuthorizationManager:
    def __init__(self) -> None:
        self.disabled_until = 0.0

    def is_disabled(self) -> bool:
        return time.time() < self.disabled_until

    def remaining_seconds(self) -> int:
        return max(0, int(self.disabled_until - time.time()))

    def request_auth_if_needed(self) -> bool:
        print("[AUTH] 허가 사용자라면 비밀번호를 입력하세요. 아니면 Enter를 누르세요.")
        password = getpass.getpass("password: ")

        if not password:
            return False

        if password == settings.auth_password:
            self.disabled_until = time.time() + settings.auth_disable_seconds
            print(f"[AUTH] 인증 성공. {settings.auth_disable_seconds}초 동안 감지 로직을 끕니다.")
            return True

        print("[AUTH] 인증 실패.")
        return False


class DwellTimeTracker:
    def __init__(self) -> None:
        self.person_detected_since: Optional[float] = None

    def update(self, sound_event: SoundEvent, stt_text: str = "") -> float:
        now = time.time()

        # 명확한 사람 소리이거나 STT 텍스트가 있으면 체류로 인정
        if sound_event.person_detected or sound_event.label in {"footstep", "speech"} or bool(stt_text):
            if self.person_detected_since is None:
                self.person_detected_since = now
            return now - self.person_detected_since

        # unknown은 누적하지 않음. 단, STT가 나온 경우는 위에서 누적됨.
        if not sound_event.danger_sound_detected:
            self.person_detected_since = None

        return 0.0


class SoundGuardApp:
    def __init__(self) -> None:
        self.env_classifier = BeatsEnvironmentClassifier()
        self.stt = WhisperAPI()
        self.decision_engine = GPTDecisionEngine()
        self.speaker = FixedMessageSpeaker()
        self.logger = EventLoggerAndMessenger()
        self.auth = AuthorizationManager()
        self.dwell_tracker = DwellTimeTracker()

    def run(self) -> None:
        print("=" * 70)
        print("SoundGuard 실행 - GPT 판단 / STT 균형 버전")
        print(f"위험구역: {settings.zone_name}")
        print(f"위치: {settings.location_text}")
        print(f"좌표: {settings.latitude}, {settings.longitude}")
        print(f"STT 무음 필터: RMS>={settings.min_rms_for_stt}, PEAK>={settings.min_peak_for_stt}")
        print(f"ALLOW_UNKNOWN_STT={settings.allow_unknown_stt}")
        print("종료: Ctrl+C")
        print("=" * 70)

        try:
            while True:
                if self.auth.is_disabled():
                    print(f"[AUTH] 허가 사용자 통과 중. 남은 시간: {self.auth.remaining_seconds()}초")
                    time.sleep(1)
                    continue

                audio = self._record_audio()
                audio_path = self._save_audio(audio)

                sound_event = self.env_classifier.classify(audio, settings.sample_rate)
                print(
                    f"[ENV] label={sound_event.label}, "
                    f"conf={sound_event.confidence:.3f}, "
                    f"raw={sound_event.raw_label}, "
                    f"rms={sound_event.rms:.5f}, peak={sound_event.peak:.5f}"
                )

                stt_text = ""
                should_try_stt = (
                    sound_event.label == "speech"
                    or (
                        settings.allow_unknown_stt
                        and sound_event.label == "unknown"
                        and (sound_event.rms >= settings.min_rms_for_stt or sound_event.peak >= settings.min_peak_for_stt)
                    )
                )

                if should_try_stt:
                    try:
                        if self.stt.should_transcribe(audio):
                            stt_text = self.stt.transcribe(audio_path)
                            if stt_text:
                                print(f"[STT] {stt_text}")
                            else:
                                print("[STT] 인식된 유효 문장 없음")
                    except Exception as exc:
                        print(f"[WARN] STT 실패: {exc}")

                dwell_seconds = self.dwell_tracker.update(sound_event, stt_text=stt_text)
                print(f"[ZONE] 체류 추정 시간: {dwell_seconds:.1f}초")

                authorized = False
                if (sound_event.person_detected or bool(stt_text)) and dwell_seconds < 5:
                    authorized = self.auth.request_auth_if_needed()

                decision = self.decision_engine.decide(
                    sound_event=sound_event,
                    stt_text=stt_text,
                    dwell_seconds=dwell_seconds,
                    authorized=authorized,
                )

                print(
                    f"[DECISION] 상황 {decision.situation}: {decision.situation_name} | "
                    f"위험도={decision.risk_level} | {decision.reason}"
                )
                print(f"[ACTION] {decision.action}")

                if decision.tts_key != "NONE":
                    self.speaker.speak(decision.tts_key)

                if decision.situation in {1, 2} or decision.send_to_control_room:
                    event = self.logger.record_and_send(
                        decision=decision,
                        sound_event=sound_event,
                        stt_text=stt_text,
                        dwell_seconds=dwell_seconds,
                    )
                    print(f"[EVENT] 기록/전송 대상 이벤트: {event['event_time']}")

                print("-" * 70)

        except KeyboardInterrupt:
            print("\nSoundGuard 종료")

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
    app = SoundGuardApp()
    app.run()
