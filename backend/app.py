from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

from .config import BACKEND_DIR, settings
from .decision import GPTDecisionEngine, DecisionResult
from .environmental_sound import BeatsEnvironmentClassifier, SoundEvent
from .output import EventLoggerAndMessenger, FixedMessageSpeaker
from .self_check import run_self_check
from .stt import WhisperAPI


TEMP_DIR = BACKEND_DIR / "outputs/temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

_EMERGENCY_LOCK_SECONDS = 180   # 응급 잠금 지속 시간 (3분)
_EMERGENCY_INTERVALS = (30, 60) # 2차 재안내: 30초, 3차+: 60초 간격


class AuthorizationManager:
    def __init__(self, self_check_callback: Optional[Callable[[], None]] = None) -> None:
        self._disable_until = 0.0
        self._control_active = False
        self._lock = threading.Lock()
        self._self_check_callback = self_check_callback

    def is_control_active(self) -> bool:
        with self._lock:
            return self._control_active

    def _set_control_active(self, active: bool) -> None:
        with self._lock:
            self._control_active = active

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
        print("[ADMIN] p 입력: 관리자 인증 | c 입력: 자가진단 | h 입력: 도움말")

        while True:
            try:
                command = input().strip().lower()

                if command in {"p", "pause", "admin"}:
                    self._run_control_command("관리자 인증", self.authenticate_and_disable)

                elif command in {"c", "check", "self-check", "selfcheck"}:
                    if self._self_check_callback is None:
                        print("[SELF_CHECK] 자가진단 기능이 연결되지 않았습니다.")
                    else:
                        self._run_control_command("자가진단", self._self_check_callback)

                elif command in {"h", "help"}:
                    print("[ADMIN] p 입력: 관리자 인증 후 일시 비활성화")
                    print("[ADMIN] c 입력: 실행 중 빠른 자가진단")

            except EOFError:
                break
            except Exception as exc:
                print(f"[ADMIN] 입력 처리 오류: {exc}")

    def _run_control_command(self, name: str, action: Callable[[], None]) -> None:
        self._set_control_active(True)
        print(f"[SYSTEM] {name} 처리 중입니다. 감지 로직을 일시정지합니다.")
        try:
            action()
        finally:
            self._set_control_active(False)
            print(f"[SYSTEM] {name} 처리가 끝났습니다. 감지 로직을 재개합니다.")


class DwellTimeTracker:
    def __init__(self) -> None:
        self.detected_since: Optional[float] = None

    def reset(self) -> None:
        self.detected_since = None

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
        self.auth = AuthorizationManager(self_check_callback=self._run_self_check)
        self.dwell_tracker = DwellTimeTracker()
        self.warn1_issued: bool = False  # DwellTracker와 분리: BEATs 오분류로 reset되지 않도록
        self.silence_cycles: int = 0    # 연속 situation=0 카운트
        self.emergency_active_until: float = 0.0   # 응급 잠금 만료 타임스탬프
        self.last_emergency_announce: float = 0.0  # 마지막 응급 안내 시각
        self.emergency_announce_count: int = 0     # 응급 안내 횟수 (back-off 계산용)
        self.cycle_no = 0
        self.audio_lock = threading.Lock()
        self.control_pause_notified = False

    def _safe_create_stt(self):
        try:
            return WhisperAPI()
        except Exception as exc:
            print(f"[WARN] STT 비활성화: {exc}")
            return None

    def _run_self_check(self) -> None:
        print("\n[SELF_CHECK] 실행 중 자가진단을 시작합니다.")
        print("[SELF_CHECK] 스피커 테스트 소리가 짧게 재생됩니다.")
        print("[SELF_CHECK] 이미 로드된 모델이 있으므로 모델 재로딩은 생략합니다.")
        print("[SELF_CHECK] 현재 녹음이 끝나면 자가진단을 시작합니다.")
        with self.audio_lock:
            run_self_check(load_model=False, audio_loopback=True)

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
        print(f"1차 경고 → 2차 경고 전환: {settings.intrusion_warn_2_seconds}초 체류 후")
        print(f"응급 잠금: {_EMERGENCY_LOCK_SECONDS}초 | 재안내 간격: 즉시→{_EMERGENCY_INTERVALS[0]}초→{_EMERGENCY_INTERVALS[1]}초")
        print(f"관리자 인증: p 입력 후 Enter")
        print("종료: Ctrl+C")
        print("=" * 70)

        self.auth.start_listener()

        try:
            while True:
                if self.auth.is_control_active():
                    self.dwell_tracker.reset()
                    if not self.control_pause_notified:
                        print("[SYSTEM] 제어 명령 처리 중... 감지를 일시정지합니다.")
                        self.control_pause_notified = True
                    time.sleep(0.2)
                    continue

                if self.control_pause_notified:
                    print("[SYSTEM] 감지를 재개합니다.")
                    self.control_pause_notified = False

                if self.auth.is_disabled():
                    self.dwell_tracker.reset()
                    remain = self.auth.remaining_seconds()
                    print(f"[SYSTEM] 관리자 인증으로 감지 비활성화 중... 남은 시간 {remain:.1f}초")
                    time.sleep(1)
                    continue

                audio = self._record_audio()
                audio_path = self._save_audio(audio)

                if self.auth.is_disabled() or self.auth.is_control_active():
                    self.dwell_tracker.reset()
                    print("[SYSTEM] 제어/비활성화 상태 확인됨. 이번 녹음은 처리하지 않습니다.")
                    continue

                sound_event = self.env_classifier.classify(audio, settings.sample_rate)
                stt_text = ""
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

                # 응급 잠금 처리 (침입 경고 가드보다 먼저 실행)
                decision, should_emergency_announce = self._apply_emergency_lock(decision)
                in_emergency_lock = time.time() < self.emergency_active_until

                if not in_emergency_lock:
                    # 1차 경고 미발령 상태에서 2차 경고가 나오면 → 1차 경고로 강제 변환
                    if decision.tts_key == "INTRUSION_WARN_2" and not self.warn1_issued:
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

                    # 1차 경고 이미 발령 + 사람이 계속 감지됨 → 2차 경고로 에스컬레이션
                    if decision.tts_key == "INTRUSION_WARN_1" and self.warn1_issued:
                        print("[WARN_ORDER] 1차 경고 이미 발령. INTRUSION_WARN_1 → INTRUSION_WARN_2 에스컬레이션")
                        decision = DecisionResult(
                            situation=decision.situation,
                            situation_name=decision.situation_name,
                            risk_level="medium",
                            reason=decision.reason,
                            action="2차 경고 방송 및 상황실 전송",
                            tts_key="INTRUSION_WARN_2",
                            send_to_control_room=True,
                            emergency_candidate=decision.emergency_candidate,
                            source=decision.source + " (escalated warn2)",
                        )

                if decision.tts_key == "INTRUSION_WARN_1":
                    self.warn1_issued = True
                    self.silence_cycles = 0

                # 응급 상황 발생 시 침입 경고 상태 초기화
                if decision.situation == 2:
                    self.warn1_issued = False
                    self.silence_cycles = 0

                if decision.situation == 0:
                    self.silence_cycles += 1
                    # 30초(6사이클) 연속 이상없음 → 새 상황으로 리셋
                    if self.silence_cycles >= 6:
                        if self.warn1_issued:
                            print(f"[RESET] {self.silence_cycles * settings.chunk_seconds}초 연속 이상없음. 경고 상태 초기화.")
                        self.warn1_issued = False
                        self.silence_cycles = 0
                else:
                    self.silence_cycles = 0

                self._print_cycle_summary(sound_event, stt_text, dwell_seconds, decision)

                if decision.tts_key != "NONE":
                    if decision.tts_key == "EMERGENCY_GUIDE" and not should_emergency_announce:
                        remaining = self.emergency_active_until - time.time()
                        print(f"[EMERGENCY] 재안내 대기 중 (잠금 남은 시간 {remaining:.0f}초)")
                    else:
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

    def _apply_emergency_lock(self, decision: DecisionResult) -> tuple[DecisionResult, bool]:
        """응급 잠금 상태를 관리하고, 이번 사이클에 TTS를 재생할지 여부를 반환."""
        now = time.time()
        in_lock = now < self.emergency_active_until

        if decision.situation == 2:
            if in_lock:
                print("[EMERGENCY] 새 응급 신호 감지 → 잠금 연장, 재안내 간격 리셋")
            self.emergency_active_until = now + _EMERGENCY_LOCK_SECONDS
            self.last_emergency_announce = 0.0  # 즉시 재안내 트리거
            self.emergency_announce_count = 0
            in_lock = True
        elif in_lock:
            remaining = self.emergency_active_until - now
            decision = DecisionResult(
                situation=2, situation_name="위험 감지", risk_level="high",
                reason=f"응급 잠금 유지 중 (남은 시간 {remaining:.0f}초)",
                action="응급 안내 지속",
                tts_key="EMERGENCY_GUIDE",
                send_to_control_room=True, emergency_candidate=True,
                source=decision.source + " (emergency lock)",
            )

        if not in_lock:
            return decision, True

        # Back-off 재안내 타이밍 계산
        elapsed = now - self.last_emergency_announce
        count = self.emergency_announce_count
        if count == 0:
            should_announce = True                          # 1차: 즉시
        elif count == 1:
            should_announce = elapsed >= _EMERGENCY_INTERVALS[0]  # 2차: 30초 후
        else:
            should_announce = elapsed >= _EMERGENCY_INTERVALS[1]  # 3차+: 60초 간격

        if should_announce:
            self.last_emergency_announce = now
            self.emergency_announce_count += 1

        return decision, should_announce

    def _print_cycle_summary(
        self,
        sound_event: SoundEvent,
        stt_text: str,
        dwell_seconds: float,
        decision: DecisionResult,
    ) -> None:
        self.cycle_no += 1
        print("-" * 70)
        print(f"[CYCLE {self.cycle_no}] 최종 판단: {decision.situation} {decision.situation_name}")
        print(
            f"  BEATs: {sound_event.raw_label} "
            f"(conf={sound_event.confidence:.3f}, rms={sound_event.rms:.5f}, peak={sound_event.peak:.5f})"
        )
        print(f"  STT: {stt_text or '없음'}")
        print(f"  dwell: {dwell_seconds:.1f}s | source: {decision.source} | tts: {decision.tts_key}")
        print("-" * 70)

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
        print(f"\n[REC] {settings.chunk_seconds}초 녹음 중...")

        with self.audio_lock:
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
