import sys
import os
import asyncio
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# 1. 경로 설정 (BEATs 폴더가 있는 backend 폴더를 패스에 추가)
current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir))

app = FastAPI()

from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from datetime import datetime

# 1. BEATs 모델 경로 설정 (main.py와 동일)
current_dir = Path(__file__).resolve().parent
beats_path = str(current_dir / "beats")
if beats_path not in sys.path:
    sys.path.insert(0, beats_path)

app = FastAPI()

# 2. CORS 설정: 리액트 앱의 접속 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

guard_app = None

def get_guard_app():
    global guard_app
    if guard_app is None:
        import main
        guard_app = main.SoundGuardApp()
    return guard_app

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("✅ [Server] 리액트 대시보드 연결 성공")

    try:
        app_instance = get_guard_app() # 한 번 생성된 인스턴스 재사용
        import main # settings 등을 참조하기 위해 필요
        
        while True:
            # 리액트에게 녹음 중임을 알림
            await websocket.send_json({"type": "status", "message": "recording"})
            
            # A. 녹음 및 저장
            audio = guard_app._record_audio()
            audio_path = guard_app._save_audio(audio)

            '''
            # B. 환경 소리 분석 (튜닝된 BEATs)
            sound_event = guard_app.env_classifier.classify(audio, main.settings.sample_rate)
            
            # C. 튜닝된 STT 트리거 로직 적용
            stt_text = ""
            stt_trigger = (
                sound_event.situation in {1, 2}
                or sound_event.rms >= main.settings.min_rms_for_stt
                or sound_event.peak >= main.settings.min_peak_for_stt
            )
            '''

            # 수정 후 (guard_app이 가지고 있는 속성을 확인)
            # 만약 main.py에서 sample_rate를 별도로 정의했다면 그 값을 직접 써주거나 guard_app에서 가져옵니다.
            sample_rate = getattr(guard_app, 'sample_rate', 16000) # 기본값 16000, 없을 경우 대비
            sound_event = guard_app.env_classifier.classify(audio, sample_rate)

            # C. STT 트리거 로직 부분도 수정
            # main.settings.min_rms_for_stt 대신 직접 수치를 입력하거나 guard_app의 속성을 사용하세요.
            min_rms = 0.004  # 로그에 찍혔던 기준값
            min_peak = 0.03
            stt_trigger = (
                sound_event.situation in {1, 2}
                or sound_event.rms >= min_rms
                or sound_event.peak >= min_peak
            )

            if stt_trigger:
                stt_text = guard_app._try_stt(audio, audio_path)

            # D. 체류 시간 및 상황 판단 (튜닝된 main.py의 로직 그대로 사용)
            dwell_seconds = guard_app.dwell_tracker.update(sound_event, stt_text=stt_text)
            
            # 웹에서는 인증 입력을 받을 수 없으므로 authorized=False 고정
            decision = guard_app.decision_engine.decide(
                sound_event=sound_event,
                stt_text=stt_text,
                dwell_seconds=dwell_seconds,
                authorized=False,
            )

            # [튜닝 로직 반영] 1차 경고 미발령 시 2차 경고 강제 변환
            if decision.tts_key == "INTRUSION_WARN_2" and not guard_app.dwell_tracker.warn1_issued:
                from main import DecisionResult
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

            # 1차 발령 기록 업데이트
            if decision.tts_key == "INTRUSION_WARN_1" and sound_event.situation in {1, 2}:
                guard_app.dwell_tracker.warn1_issued = True

            # E. 데이터 전송
            payload = {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "env_label": sound_event.label,
                "stt_text": stt_text,
                "situation": decision.situation,
                "situation_name": decision.situation_name,
                "reason": decision.reason,
                "action": decision.action,
                "dwell_seconds": round(dwell_seconds, 1)
            }
            await websocket.send_json(payload)
            print(f"📡 [보냄] {sound_event.label} ({decision.situation_name})")

            # F. TTS 출력
            if decision.tts_key != "NONE":
                guard_app.speaker.speak(decision.tts_key)

            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        print("🔌 [Server] 리액트 연결 종료")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ [Server] 에러 발생: {e}")
    finally:
        print("🔌 [Server] WebSocket 세션 종료")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
