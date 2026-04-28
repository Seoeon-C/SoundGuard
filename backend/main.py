from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

from audio_detectors import SignalDetector
from config import settings
from decision import GPTDecisionEngine
from environmental_sound import BeatsEnvironmentClassifier, SoundEvent
from output import EventLoggerAndMessenger, FixedMessageSpeaker
from stt import WhisperAPI


TEMP_DIR = Path("outputs/temp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


class AuthorizationManager:
    """
    관리자 버튼 방식의 일시정지/재개 관리자.

    사용 방법:
    - 프로그램 실행 중 콘솔에 p 입력 후 Enter
    - 비밀번호 입력
    - 인증 성공 시 RUNNING <-> PAUSED 토글
    """

    def __init__(self) -> None:
        self._paused = False
        self._lock = threading.Lock()

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def toggle_with_auth(self) -> None:
        print("\n[ADMIN] 관리자 버튼이 눌렸습니다.")
        password = input("[ADMIN] password: ").strip()

        if password != settings.auth_password:
            print("[ADMIN] 인증 실패")
            return

        with self._lock:
            self._paused = not self._paused
            paused = self._paused

        if paused:
            print("[SYSTEM] 감지 일시정지 상태로 전환되었습니다.")
            print("[SYSTEM] 다시 p 입력 후 비밀번호를 입력하면 감지를 재개합니다.")
        else:
            print("[SYSTEM] 감지를 재개합니다.")

    def start_admin_button_listener(self) -> None:
        thread = threading.Thread(target=self._admin_button_loop, daemon=True)
        thread.start()

    def _admin_button_loop(self) -> None:
        print("[ADMIN] 관리자 버튼: 콘솔에 p 입력 후 Enter")

        while True:
            try:
                command = input().strip().lower()
                if command in {"p", "pause", "admin"}:
                    self.toggle_with_auth()
                elif command in {"help", "h"}:
                    print("[ADMIN] p 입력 후 Enter: 일시정지/재개")
            except EOFError:
                break
            except Exception as exc:
                print(f"[ADMIN] 관리자 입력 처리 오류: {exc}")


class DwellTimeTracker:
    """
    체류시간 계산기.

    사람 목소리, 발소리, STT 텍스트가 있으면 사람 존재로 보고 체류시간을 누적한다.
    자연음/배경음이면 체류시간을 초기화한다.
    """

    def __init__(self) -> None:
        self.person_detected_since: Optional[float] = None

    def reset(self) -> None:
        self.person_detected_since = None

    def update(self, sound_event: SoundEvent, stt_text: str = "") -> float:
        now = time.time()

        if (
            sound_event.is_footstep
            or sound_event.is_speech
            or sound_event.is_unknown_speech_candidate
            or bool(stt_text)
        ):
            if self.person_detected_since is None:
                self.person_detected_since = now
            return now - self.person_detected_since

        if not sound_event.is_emergency_sound:
            self.reset()

        return 0.0


class SoundGuardApp:
    def __init__(self) -> None:
        self.signal_detector = SignalDetector()
        self.env_classifier = BeatsEnvironmentClassifier()
        self.stt = WhisperAPI()
        self.decision_engine = GPTDecisionEngine()
        self.speaker = FixedMessageSpeaker()
        self.logger = EventLoggerAndMessenger()
        self.auth = AuthorizationManager()
        self.dwell_tracker = DwellTimeTracker()

    def run(self) -> None:
        print("=" * 70)
        print("SoundGuard 실행 - VAD/발소리 보강 + BEATs 단일 모델 버전")
        print("흐름: 1) VAD 목소리 후보 → Whisper  2) 발소리 패턴 → 무단침입  3) BEATs 위험음/자연음")
        print(f"위험구역: {settings.zone_name}")
        print(f"위치: {settings.location_text}")
        print(f"좌표: {settings.latitude}, {settings.longitude}")
        print(f"VAD: rms>={settings.vad_min_rms}, peak>={settings.vad_min_peak}, score>={settings.vad_voice_score_threshold}")
        print(f"Footstep: peaks>={settings.footstep_min_peaks}, score>={settings.footstep_score_threshold}")
        print("[ADMIN] p 입력 후 Enter: 관리자 비밀번호 입력 후 일시정지/재개")
        print("종료: Ctrl+C")
        print("=" * 70)

        self.auth.start_admin_button_listener()

        try:
            while True:
                if self.auth.is_paused():
                    self.dwell_tracker.reset()
                    print("[SYSTEM] 감지 일시정지 중... p 입력 후 비밀번호를 입력하면 재개됩니다.")
                    time.sleep(2)
                    continue

                audio = self._record_audio()
                audio_path = self._save_audio(audio)

                if self.auth.is_paused():
                    self.dwell_tracker.reset()
                    print("[SYSTEM] 녹음 후 일시정지 상태 확인됨. 이번 입력은 처리하지 않습니다.")
                    continue

                sound_event, stt_text = self._detect_and_transcribe(audio, audio_path)

                dwell_seconds = self.dwell_tracker.update(sound_event, stt_text=stt_text)
                print(f"[ZONE] 체류 추정 시간: {dwell_seconds:.1f}초")

                decision = self.decision_engine.decide(
                    sound_event=sound_event,
                    stt_text=stt_text,
                    dwell_seconds=dwell_seconds,
                    authorized=False,
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

    def _detect_and_transcribe(self, audio: np.ndarray, audio_path: Path) -> tuple[SoundEvent, str]:
        """
        추천 감지 흐름 구현부.

        1. SignalDetector로 작은 목소리 후보를 먼저 잡는다.
        2. 목소리 후보이면 Whisper API를 호출한다.
        3. 목소리가 아니면 발소리 반복 peak 패턴을 확인한다.
        4. 둘 다 아니면 BEATs로 폭발/비명/유리파손/자연음 등을 분류한다.
        """
        signal = self.signal_detector.analyze(audio, settings.sample_rate)
        print(
            f"[SIGNAL] rms={signal.rms:.5f}, peak={signal.peak:.5f}, "
            f"voice_score={signal.voice_score:.2f}, footstep_score={signal.footstep_score:.2f}, "
            f"active={signal.active_ratio:.2f}, impulse={signal.impulse_ratio:.1f}, zcr={signal.zero_crossing_rate:.3f}, "
            f"peaks={signal.peak_count}, reason={signal.reason}"
        )

        stt_text = ""

        if signal.voice_detected:
            sound_event = SoundEvent(
                label="speech",
                confidence=signal.voice_score,
                raw_label="vad_voice_candidate",
                rms=signal.rms,
                peak=signal.peak,
                top_labels=[("vad_voice_candidate", signal.voice_score)],
            )
            print("[FLOW] VAD가 사람 목소리 후보 감지 → Whisper STT")
            try:
                if self.stt.should_transcribe(audio):
                    stt_text = self.stt.transcribe(audio_path)
                    print(f"[STT] {stt_text}" if stt_text else "[STT] 유효한 문장 없음")
            except Exception as exc:
                print(f"[WARN] STT 실패: {exc}")
            return sound_event, stt_text

        if signal.footstep_detected:
            sound_event = SoundEvent(
                label="footstep",
                confidence=signal.footstep_score,
                raw_label="energy_peak_footstep_pattern",
                rms=signal.rms,
                peak=signal.peak,
                top_labels=[("energy_peak_footstep_pattern", signal.footstep_score)],
            )
            print(f"[FLOW] 발소리 반복 peak 감지 → 무단침입 로직 | peak_times={signal.peak_times[:8]}")
            return sound_event, stt_text

        sound_event = self.env_classifier.classify(audio, settings.sample_rate)
        top_text = ""
        if sound_event.top_labels:
            top_text = " | top=" + ", ".join(
                f"{label}:{score:.3f}" for label, score in sound_event.top_labels[:3]
            )

        print(
            f"[BEATs] label={sound_event.label}, "
            f"conf={sound_event.confidence:.3f}, "
            f"raw={sound_event.raw_label}, "
            f"rms={sound_event.rms:.5f}, peak={sound_event.peak:.5f}"
            f"{top_text}"
        )

        if signal.loud_impulse_detected and sound_event.label == "unknown":
            sound_event = SoundEvent(
                label="emergency_sound",
                confidence=max(sound_event.confidence, 0.70),
                raw_label="loud_impulse_unknown",
                rms=signal.rms,
                peak=signal.peak,
                top_labels=sound_event.top_labels,
            )
            print("[FLOW] 매우 큰 impulse인데 BEATs가 unknown → 보수적으로 위험음 처리")
        elif sound_event.is_nature:
            print("[FLOW] 자연/배경 소리 → pass")
        elif sound_event.is_speech or sound_event.is_unknown_speech_candidate:
            # 중요: BEATs의 Speech 라벨만으로는 Whisper를 호출하지 않는다.
            # 발소리/마찰음/기계음도 BEATs에서 Speech로 오인될 수 있고,
            # Whisper가 "안녕", "시청해주셔서 감사합니다" 같은 환각 문장을 만들 수 있기 때문이다.
            print("[FLOW] BEATs speech 후보지만 VAD 미검출 → Whisper 호출 안 함, pass")
            sound_event = SoundEvent(
                label="unknown",
                confidence=sound_event.confidence,
                raw_label=f"beats_speech_without_vad:{sound_event.raw_label}",
                rms=sound_event.rms,
                peak=sound_event.peak,
                top_labels=sound_event.top_labels,
            )
        elif sound_event.is_footstep:
            print("[FLOW] BEATs가 발소리 감지 → 무단침입 로직")
        elif sound_event.is_emergency_sound:
            print("[FLOW] BEATs가 위험음 감지 → 위급 로직")
        else:
            print("[FLOW] unknown → pass")

        return sound_event, stt_text

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
