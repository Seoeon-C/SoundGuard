import sys
import time
import asyncio
import json
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# 경로 설정
# backend/ 기준으로 프로젝트 루트를 sys.path에 추가해야 backend 패키지 임포트 가능
current_dir = Path(__file__).resolve().parent   # backend/
project_root = current_dir.parent               # Sound_Envader_Detect/

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(current_dir / "BEATs") not in sys.path:
    sys.path.insert(0, str(current_dir / "BEATs"))

from backend.app import SoundGuardApp
from backend.decision import DecisionResult
from backend.environmental_sound import SPEECH_LABELS, INTRUSION_LABELS
from backend.config import settings

# ── 소리 카테고리 분류 ─────────────────────────────────────────────────────────

_SCREAM_LABELS = {
    "Screaming", "Yell", "Shout", "Children shouting",
    "Wail, moan", "Whimper", "Crying, sobbing", "Baby cry, infant cry",
    "Groan", "Gasp",
}

_PROJECT_LABEL_MAP = {
    "intrusion":    "발소리",
    "impact_noise": "발소리",
    "emergency":    "비명소리",
    "background":   "환경음",
    "loud_noise":   "환경음",
}

_CATEGORIES = ["발소리", "말소리", "비명소리", "환경음"]


def _compute_category_scores(top_labels, model_kind: str) -> dict:
    """top_labels → 4개 고정 카테고리 점수 (합산 100%)."""
    scores = {c: 0.0 for c in _CATEGORIES}

    for name, score in top_labels:
        if model_kind == "project":
            cat = _PROJECT_LABEL_MAP.get(name, "환경음")
        else:
            if name in _SCREAM_LABELS:
                cat = "비명소리"
            elif name in SPEECH_LABELS:
                cat = "말소리"
            elif name in INTRUSION_LABELS:
                cat = "발소리"
            else:
                cat = "환경음"
        scores[cat] += score

    total = sum(scores.values())
    if total > 0:
        scores = {k: round(v / total * 100, 1) for k, v in scores.items()}

    return scores


# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

guard_app = None


def get_guard_app() -> SoundGuardApp:
    global guard_app
    if guard_app is None:
        guard_app = SoundGuardApp()
    return guard_app


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    app_instance = get_guard_app()
    print("✅ [Control Room] 연결 성공")

    try:
        while True:
            # 제어 중(자가진단·인증) 또는 일시정지 상태이면 감지 생략
            if app_instance.auth.is_control_active() or app_instance.auth.is_disabled():
                remain = round(app_instance.auth.remaining_seconds())
                await websocket.send_json({"type": "status", "message": "paused", "remain": remain})
                await asyncio.sleep(1)
                continue

            # 0.1초 동안 프론트엔드 명령 수신 대기
            try:
                raw_command = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                command = json.loads(raw_command)

                if command.get("type") == "CONTROL":
                    action = command.get("action")
                    if action == "FORCE_TTS":
                        key = command.get("key", "INTRUSION_WARN_1")
                        app_instance.speaker.speak(key)
                        print(f"📣 [CONTROL] 강제 방송 송출: {key}")
                    elif action == "PAUSE":
                        app_instance.auth._disable_until = datetime.now().timestamp() + 60
                        print("⏸ [CONTROL] 시스템 60초 일시정지")
            except asyncio.TimeoutError:
                pass

            # 명령 처리 후 재확인
            if app_instance.auth.is_control_active() or app_instance.auth.is_disabled():
                remain = round(app_instance.auth.remaining_seconds())
                await websocket.send_json({"type": "status", "message": "paused", "remain": remain})
                await asyncio.sleep(1)
                continue

            await websocket.send_json({"type": "status", "message": "recording"})

            # ── 녹음 및 분류 ────────────────────────────────────────────────
            audio = app_instance._record_audio()
            audio_path = app_instance._save_audio(audio)

            sound_event = app_instance.env_classifier.classify(audio, settings.sample_rate)

            # STT (app.py와 동일한 트리거 조건 사용)
            stt_text = ""
            stt_trigger = (
                sound_event.situation in {1, 2}
                or sound_event.rms >= settings.min_rms_for_stt
                or sound_event.peak >= settings.min_peak_for_stt
            )
            if stt_trigger:
                stt_text = app_instance._try_stt(audio, audio_path)

            dwell_seconds = app_instance.dwell_tracker.update(sound_event, stt_text=stt_text)
            decision = app_instance.decision_engine.decide(sound_event, stt_text, dwell_seconds, False)

            # ── 응급 잠금 적용 (app.py와 동일 로직) ─────────────────────────
            decision, should_emergency_announce = app_instance._apply_emergency_lock(decision)
            in_emergency_lock = time.time() < app_instance.emergency_active_until

            if not in_emergency_lock:
                # 1차 미발령 상태에서 2차 경고 → 1차로 강제 변환
                if decision.tts_key == "INTRUSION_WARN_2" and not app_instance.warn1_issued:
                    print("[WARN_ORDER] 1차 경고 미발령. INTRUSION_WARN_2 → INTRUSION_WARN_1 강제 변환")
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

                # 1차 이미 발령 + 추가 감지 → 2차로 에스컬레이션
                if decision.tts_key == "INTRUSION_WARN_1" and app_instance.warn1_issued:
                    print("[WARN_ORDER] 1차 이미 발령. INTRUSION_WARN_1 → INTRUSION_WARN_2 에스컬레이션")
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

            # ── warn1_issued / silence_cycles 상태 갱신 (app.py와 동일) ─────
            if decision.tts_key == "INTRUSION_WARN_1":
                app_instance.warn1_issued = True
                app_instance.silence_cycles = 0

            if decision.situation == 2:
                app_instance.warn1_issued = False
                app_instance.silence_cycles = 0

            if decision.situation == 0:
                app_instance.silence_cycles += 1
                if app_instance.silence_cycles >= 6:
                    app_instance.warn1_issued = False
                    app_instance.silence_cycles = 0
            else:
                app_instance.silence_cycles = 0

            # ── WebSocket payload 전송 ───────────────────────────────────────
            payload = {
                "type": "data",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "status": {
                    "level": decision.situation,
                    "name": decision.situation_name,
                    "duration": round(dwell_seconds),
                    "warn1_issued": app_instance.warn1_issued,
                    "emergency_lock": in_emergency_lock,
                },
                "analysis": {
                    "label": sound_event.label,
                    "confidence": round(sound_event.confidence * 100, 1),
                    "category_scores": _compute_category_scores(
                        sound_event.top_labels,
                        app_instance.env_classifier.model_kind,
                    ),
                },
                "decision": {
                    "risk_level": decision.risk_level,
                    "reason": decision.reason,
                    "tts_key": decision.tts_key,
                    "emergency_candidate": decision.emergency_candidate,
                    "send_to_control_room": decision.send_to_control_room,
                    "source": decision.source,
                },
                "stt_text": stt_text,
                "action_msg": decision.action,
            }
            await websocket.send_json(payload)

            # ── TTS 방송 ─────────────────────────────────────────────────────
            if decision.tts_key != "NONE":
                if decision.tts_key == "EMERGENCY_GUIDE" and not should_emergency_announce:
                    remaining = app_instance.emergency_active_until - time.time()
                    print(f"[EMERGENCY] 재안내 대기 중 (잠금 남은 시간 {remaining:.0f}초)")
                else:
                    app_instance.speaker.speak(decision.tts_key)

            # ── 이벤트 로깅 ──────────────────────────────────────────────────
            if decision.situation in {1, 2} or decision.send_to_control_room:
                app_instance.logger.record_and_send(
                    decision=decision,
                    sound_event=sound_event,
                    stt_text=stt_text,
                    dwell_seconds=dwell_seconds,
                )

    except WebSocketDisconnect:
        print("🔌 연결 종료")
    except Exception as e:
        print(f"❌ 에러: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
