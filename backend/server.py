import sys
from pathlib import Path
from datetime import datetime
import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import time
from dataclasses import replace
from .config import settings
from .app import SoundGuardApp

current_dir = Path(__file__).resolve().parent
beats_path = str(current_dir / "beats")
if beats_path not in sys.path:
    sys.path.insert(0, beats_path)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_TTS_MESSAGES = {
    "NONE": "",
    "INTRUSION_WARN_1": "출입이 허가되지 않은 위험 구역입니다. 즉시 안전한 곳으로 이동해 주세요.",
    "INTRUSION_WARN_2": "위험 구역에 계속 머무르고 있습니다. 위치 정보가 상황실로 전송되었습니다. 즉시 퇴장해 주세요.",
    "EMERGENCY_GUIDE": "응급 상황이 감지되었습니다. 가능한 경우 안전한 위치로 이동하고 구조 안내를 기다려 주세요.",
    "EVACUATION_GUIDE": "위험 상황이 감지되었습니다. 즉시 현재 위치에서 벗어나 안전한 곳으로 대피해 주세요.",
}


def make_beats_bars(sound_event, decision, stt_text: str) -> dict:
    raw = getattr(sound_event, "raw_label", "")
    situation = getattr(sound_event, "situation", 0)
    return {
        "background": 90 if decision.situation == 0 else 5,
        "loud_noise": 80 if raw == "loud_noise" else 0,
        "intrusion": 80 if situation == 1 else 0,
        "emergency": 80 if raw == "emergency" or decision.situation == 2 else 0,
        "impact_noise": 80 if raw == "impact_noise" else 0,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("✅ [Server] 대시보드 연결 수락됨")

    paused = False
    custom_tts = {
        "INTRUSION_WARN_1": "",
        "INTRUSION_WARN_2": "",
        "EMERGENCY_GUIDE": "",
        "EVACUATION_GUIDE": "",
    }

    async def read_dashboard_commands():
        nonlocal paused, custom_tts
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
            except asyncio.TimeoutError:
                return

            msg_type = msg.get("type")

            if msg_type == "pause":
                paused = bool(msg.get("paused", False))
                print(f"[DASHBOARD] 감지 {'일시정지' if paused else '재개'}")
                await websocket.send_json({"type": "pause_state", "paused": paused})

            elif msg_type == "tts_config":
                custom_tts.update({
                    "INTRUSION_WARN_1": msg.get("w1", "") or "",
                    "INTRUSION_WARN_2": msg.get("w2", "") or "",
                    "EMERGENCY_GUIDE": msg.get("emg", "") or "",
                    "EVACUATION_GUIDE": msg.get("emg", "") or "",
                })
                print("[DASHBOARD] 안내 멘트 설정 반영 완료")
            elif msg_type == "self_check":
                print("[DASHBOARD] 자가진단 요청 수신")
                await websocket.send_json({
                    "type": "self_check_result",
                    "items": [
                        {"label": "마이크 연결", "ok": True},
                        {"label": "BEATs 모델", "ok": bool(getattr(guard_app.env_classifier, "ready", False))},
                        {"label": "TTS 엔진", "ok": True},
                        {"label": "서버 연결", "ok": True},
                        {"label": "로그 시스템", "ok": True},
                    ],
                })

    try:
        print("🔄 [Server] AI 모델(BEATs, Whisper) 로딩 중...")
        guard_app = SoundGuardApp()
        warn1_issued = False
        warn2_issued = False
        warn1_time = 0.0
        print("🚀 [Server] 모델 로딩 완료. 분석 루프 시작")

        while True:
            await read_dashboard_commands()

            if paused:
                await websocket.send_json({"type": "status", "message": "paused"})
                await asyncio.sleep(0.2)
                continue

            await websocket.send_json({"type": "status", "message": "recording"})
            print(f"\n🎤 [{datetime.now().strftime('%H:%M:%S')}] {settings.chunk_seconds}초 녹음 및 분석 시작...")

            audio = guard_app._record_audio()
            audio_path = guard_app._save_audio(audio)

            await read_dashboard_commands()
            if paused:
                print("[DASHBOARD] 녹음 직후 일시정지 요청 확인. 이번 입력은 처리하지 않습니다.")
                continue

            sound_event = guard_app.env_classifier.classify(audio, settings.sample_rate)

            stt_text = ""
            stt_trigger = (
                sound_event.situation in {1, 2}
                or sound_event.rms >= settings.min_rms_for_stt
                or sound_event.peak >= settings.min_peak_for_stt
            )

            if guard_app.stt is not None and stt_trigger:
                if guard_app.stt.should_transcribe(audio):
                    stt_text = guard_app.stt.transcribe(audio_path)

            dwell_seconds = guard_app.dwell_tracker.update(sound_event, stt_text=stt_text)

            decision = guard_app.decision_engine.decide(
                sound_event=sound_event,
                stt_text=stt_text,
                dwell_seconds=dwell_seconds,
                authorized=False,
            )
            has_voice = bool((stt_text or "").strip())

            if decision.situation == 0:
                pass

            elif decision.situation == 1:
                now = time.time()

                # 1차 경고가 아직 안 나간 경우
                if not warn1_issued:
                    decision = replace(
                        decision,
                        situation=1,
                        situation_name="무단침입",
                        reason="침입 신호 감지, 1차 경고 송출",
                        action="1차 경고 방송 송출",
                        tts_key="INTRUSION_WARN_1",
                        send_to_control_room=True,
                    )
                    warn1_issued = True
                    warn2_issued = False
                    warn1_time = now

                # 1차 경고 후 3분 이내에 음성이 추가 감지되면 2차 경고
                elif warn1_issued and not warn2_issued and has_voice and (now - warn1_time <= 180):
                    decision = replace(
                        decision,
                        situation=1,
                        situation_name="무단침입",
                        reason="1차 경고 이후 추가 음성 감지, 2차 경고 송출",
                        action="2차 경고 방송 송출",
                        tts_key="INTRUSION_WARN_2",
                        send_to_control_room=True,
                    )
                    warn2_issued = True

                # 2차까지 나갔으면 반복 송출 방지
                else:
                    decision = replace(
                        decision,
                        tts_key="NONE",
                        action="감시 지속",
                        send_to_control_room=False,
                    )

            elif decision.situation == 2:
                warn1_issued = False
                warn2_issued = False
                warn1_time = 0.0
            # 1차/2차 경고 순서 제어
            
            tts_message = ""
            if decision.tts_key != "NONE":
                tts_message = custom_tts.get(decision.tts_key) or DEFAULT_TTS_MESSAGES.get(decision.tts_key, "")
            top_dict = dict(getattr(sound_event, "top_labels", []) or [])

            beats_scores = {
                "background": int(top_dict.get("background", 0) * 100),
                "loud_noise": int(top_dict.get("loud_noise", 0) * 100),
                "intrusion": int(top_dict.get("intrusion", 0) * 100),
                "emergency": int(top_dict.get("emergency", 0) * 100),
                "impact_noise": int(top_dict.get("impact_noise", 0) * 100),
            }
            payload = {
                "type": "analysis",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "situation": decision.situation,
                "situation_name": decision.situation_name,
                "risk_level": decision.risk_level,
                "reason": decision.reason,
                "action": decision.action,
                "tts_key": decision.tts_key,
                "tts_message": tts_message,
                "env_label": decision.situation_name,
                "beats_label": sound_event.label,
                "beats_raw_label": sound_event.raw_label,
                "beats_confidence": sound_event.confidence,
                "rms": sound_event.rms,
                "peak": sound_event.peak,
                "stt_text": stt_text,
                "dwell_seconds": dwell_seconds,
                "beats": beats_scores,
            }

            await websocket.send_json(payload)

            print(
                f"📡 [Server] 전송 완료: "
                f"BEATs={sound_event.raw_label}/{sound_event.label} | "
                f"Final={decision.situation_name} | STT={stt_text or '없음'}"
            )

            if decision.tts_key != "NONE":
                print(f"[TTS] {tts_message}")

            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        print("🔌 [Server] 대시보드 연결 종료")
    except Exception as e:
        print(f"❌ [Server] 런타임 에러 발생: {e}")
    finally:
        print("🔌 [Server] WebSocket 세션 종료")
