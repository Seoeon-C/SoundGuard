from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional
from beats_runtime.beats import load_model, load_audio
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

# model, label_dict = load_model(
#     "checkpoints/BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt"
# )
#wav = load_audio("test.wav")

# with torch.no_grad():
#     preds = model(wav)[0]
class AuthorizationManager:
    """
    관리자 버튼 방식의 일시정지/재개 관리자.

    사용 방법:
    - 프로그램 실행 중 콘솔에 p 입력 후 Enter
    - 비밀번호 입력
    - 인증 성공 시 RUNNING <-> PAUSED 토글

    기존 방식과 차이:
    - 사람이 감지될 때마다 비밀번호를 묻지 않음
    - 10초 제한 없음
    - 재시작 버튼을 누르기 전까지 계속 일시정지
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
        thread = threading.Thread(
            target=self._admin_button_loop,
            daemon=True,
        )
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

    - 발소리
    - 말소리
    - unknown이지만 speech 후보
    - STT 텍스트 존재

    위 조건 중 하나가 있으면 사람 존재로 보고 체류시간을 누적합니다.
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
        self.env_classifier = BeatsEnvironmentClassifier()
        self.stt = WhisperAPI()
        self.decision_engine = GPTDecisionEngine()
        self.speaker = FixedMessageSpeaker()
        self.logger = EventLoggerAndMessenger()
        self.auth = AuthorizationManager()
        self.dwell_tracker = DwellTimeTracker()

    def run(self) -> None:
        print("=" * 70)
        print("SoundGuard 실행 - 관리자 버튼 일시정지 버전")
        print("0 nature/pass | 1 speech/unknown-candidate->Whisper | 2 footstep->intrusion")
        print(f"위험구역: {settings.zone_name}")
        print(f"위치: {settings.location_text}")
        print(f"좌표: {settings.latitude}, {settings.longitude}")
        print(f"STT threshold: rms>={settings.min_rms_for_stt}, peak>={settings.min_peak_for_stt}")
        print(f"ALLOW_UNKNOWN_STT={settings.allow_unknown_stt}")
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

                sound_event = self.env_classifier.classify(audio, settings.sample_rate)
                print(
                    f"[BEATs] label={sound_event.label}, "
                    f"conf={sound_event.confidence:.3f}, "
                    f"raw={sound_event.raw_label}, "
                    f"rms={sound_event.rms:.5f}, peak={sound_event.peak:.5f}"
                )

                stt_text = ""

                if sound_event.is_nature:
                    print("[FLOW] 자연/배경 소리 → pass")

                elif sound_event.is_speech or sound_event.is_unknown_speech_candidate:
                    if sound_event.is_speech:
                        print("[FLOW] 말소리 감지 → Whisper STT")
                    else:
                        print("[FLOW] unknown이지만 음량 충분 → speech 후보로 보고 Whisper STT")

                    try:
                        if self.stt.should_transcribe(audio):
                            stt_text = self.stt.transcribe(audio_path)
                            print(f"[STT] {stt_text}" if stt_text else "[STT] 유효한 문장 없음")
                    except Exception as exc:
                        print(f"[WARN] STT 실패: {exc}")

                elif sound_event.is_footstep:
                    print("[FLOW] 발소리 감지 → 무단침입 로직")

                elif sound_event.is_emergency_sound:
                    print("[FLOW] 위험음 감지 → 위급 로직")

                elif sound_event.label == "unknown":
                    print("[FLOW] unknown이지만 음량 기준 미달 또는 ALLOW_UNKNOWN_STT=false → pass")

                dwell_seconds = self.dwell_tracker.update(sound_event, stt_text=stt_text)
                print(f"[ZONE] 체류 추정 시간: {dwell_seconds:.1f}초")

                # 기존 자동 비밀번호 요청 로직 제거:
                # 이제 인증/일시정지는 관리자 버튼(p 입력)으로만 수행됩니다.
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
