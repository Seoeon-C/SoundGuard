import sys
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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # 클라이언트(React)의 연결을 먼저 수락
    await websocket.accept()
    print("✅ [Server] 리액트 대시보드 연결 수락됨")

    try:
        # 순환 참조 방지를 위해 함수 내부에서 임포트
        import main
        print("🔄 [Server] AI 모델(BEATs, Whisper) 로딩 중... (잠시만 기다려주세요)")
        guard_app = main.SoundGuardApp()
        print("🚀 [Server] 모델 로딩 완료! 분석 루프를 시작합니다.")

        while True:
            # A. 리액트에게 현재 상태 전송 (녹음 시작 알림)
            await websocket.send_json({"type": "status", "message": "recording"})
            print(f"\n🎤 [{datetime.now().strftime('%H:%M:%S')}] 5초 녹음 및 분석 시작...")

            # B. 실제 분석 수행 (main.py의 핵심 메서드들 호출)
            audio = guard_app._record_audio()
            audio_path = guard_app._save_audio(audio)
            
            # 1. 환경 소리 분류 (BEATs)
            sound_event = guard_app.env_classifier.classify(audio, main.settings.sample_rate)
            
            # 2. 음성 텍스트화 (Whisper) - 말소리일 경우에만
            stt_text = ""
            if sound_event.label in ["speech", "unknown"]:
                if guard_app.stt.should_transcribe(audio):
                    stt_text = guard_app.stt.transcribe(audio_path)

            # 3. 상황 판단 (Gemini/Decision Engine)
            dwell_seconds = guard_app.dwell_tracker.update(sound_event, stt_text=stt_text)
            decision = guard_app.decision_engine.decide(
                sound_event=sound_event,
                stt_text=stt_text,
                dwell_seconds=dwell_seconds,
                authorized=False
            )

            # C. 분석된 최종 데이터를 JSON 형태로 구성
            payload = {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "env_label": sound_event.label,           # 소리 종류 (scream, speech 등)
                "stt_text": stt_text,                    # 텍스트화된 내용
                "situation": decision.situation,          # 위험도 코드 (0: 정상, 1: 주의, 2: 위험)
                "situation_name": decision.situation_name, # 상황명 (비명 감지 등)
                "reason": decision.reason,                # AI가 판단한 이유
                "action": decision.action                 # 권장 조치
            }

            # D. 리액트로 전송
            await websocket.send_json(payload)
            print(f"📡 [Server] 전송 완료: {sound_event.label} ({decision.situation_name})")

            # E. TTS 스피커 출력 (백엔드 PC 스피커에서 소리 재생)
            if decision.tts_key != "NONE":
                guard_app.speaker.speak(decision.tts_key)
            
            # 루프 간의 아주 짧은 휴식 (연결 안정성)
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        print("🔌 [Server] 리액트 클라이언트가 연결을 종료했습니다.")
    except Exception as e:
        print(f"❌ [Server] 런타임 에러 발생: {e}")
    finally:
        print("🔌 [Server] WebSocket 세션 종료")