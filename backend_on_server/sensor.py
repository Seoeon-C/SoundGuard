"""
sensor.py - 로컬 PC / 현장 기기에서 실행

역할:
  - 마이크로 오디오 녹음
  - 오디오 데이터를 Oracle 서버로 WebSocket 전송
  - 서버로부터 일시정지 명령 수신

실행 전 .env 또는 환경변수 설정:
  SERVER_WS   = ws://<서버_공인IP>:8000/sensor
  ZONE_ID     = 구역 고유 ID (겹치지 않게)
  ZONE_NAME   = 구역 이름
  ZONE_COORD  = 37.5665° N, 126.9780° E
  ZONE_ADDR   = 구역 주소

실행:
  py -3.11 sensor.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
import websockets
from dotenv import load_dotenv

load_dotenv()

# ── 설정 ─────────────────────────────────────────────────────────
SERVER_WS    = os.getenv("SERVER_WS",    "ws://localhost:8000/sensor")
SAMPLE_RATE  = int(os.getenv("SAMPLE_RATE",  "16000"))
CHUNK_SECONDS = int(os.getenv("CHUNK_SECONDS", "5"))
ZONE_ID      = os.getenv("ZONE_ID",      "zone-default")
ZONE_NAME    = os.getenv("ZONE_NAME",    "관리구역")
ZONE_COORD   = os.getenv("ZONE_COORD",   "37.5665° N, 126.9780° E")
ZONE_ADDR    = os.getenv("ZONE_ADDR",    "관리구역 주소")

TEMP_DIR = Path("outputs/temp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


def record_audio() -> np.ndarray:
    audio = sd.rec(
        int(SAMPLE_RATE * CHUNK_SECONDS),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    return audio.squeeze()


async def run():
    print("=" * 60)
    print("SoundGuard Sensor 시작")
    print(f"서버 주소  : {SERVER_WS}")
    print(f"구역       : {ZONE_NAME} ({ZONE_ID})")
    print(f"좌표       : {ZONE_COORD}")
    print(f"녹음 단위  : {CHUNK_SECONDS}초 / {SAMPLE_RATE}Hz")
    print("종료: Ctrl+C")
    print("=" * 60)

    zone_info = {
        "type": "zone_info",
        "zone_id": ZONE_ID,
        "zone_name": ZONE_NAME,
        "coord": ZONE_COORD,
        "addr": ZONE_ADDR,
        "sample_rate": SAMPLE_RATE,
        "chunk_seconds": CHUNK_SECONDS,
    }

    while True:
        try:
            async with websockets.connect(SERVER_WS) as ws:
                print(f"[Sensor] ✅ 서버 연결됨: {SERVER_WS}")
                await ws.send(json.dumps(zone_info))

                paused = False

                async def recv_command():
                    nonlocal paused
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=0.01)
                        msg = json.loads(raw)
                        if msg.get("type") == "pause":
                            paused = msg.get("paused", False)
                            state = "일시정지" if paused else "재개"
                            print(f"[Sensor] 서버 명령: 감지 {state}")
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        pass

                loop = asyncio.get_event_loop()

                while True:
                    await recv_command()

                    if paused:
                        await asyncio.sleep(0.2)
                        continue

                    print(f"\n[Sensor] 🎤 {CHUNK_SECONDS}초 녹음 중...")
                    _t_rec_start = time.time()
                    audio = await loop.run_in_executor(None, record_audio)
                    _t_rec_end = time.time()

                    sf.write(TEMP_DIR / "latest.wav", audio, SAMPLE_RATE)

                    audio_bytes = audio.astype(np.float32).tobytes()
                    _t_send_start = time.time()
                    await ws.send(audio_bytes)
                    _t_send_end = time.time()
                    print(
                        f"[Sensor] 📤 전송 완료 ({len(audio_bytes):,} bytes)"
                        f" | 녹음={_t_rec_end-_t_rec_start:.2f}s"
                        f" | 전송={_t_send_end-_t_send_start:.2f}s"
                    )

        except websockets.ConnectionClosed:
            print("[Sensor] 서버 연결 끊김. 3초 후 재연결...")
            await asyncio.sleep(3)
        except Exception as exc:
            print(f"[Sensor] 오류: {exc}. 3초 후 재연결...")
            await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[Sensor] 종료")
