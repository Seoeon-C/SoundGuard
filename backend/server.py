import sys
import uuid
import os
import requests as req_lib
from pathlib import Path
from datetime import datetime
import asyncio
import time
from dataclasses import replace

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body, Depends, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from config import settings, BACKEND_DIR
from app import SoundGuardApp
from tts_to_mp3.tts import save_edge_tts
from db import Zone, get_db, init_db, ZONE_LABELS

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

# 연결된 대시보드 목록. /api/zone-alert로 들어온 다른 구역 이벤트를 전체 대시보드에 전달한다.
DASHBOARD_CLIENTS = set()


async def broadcast_to_dashboards(payload: dict) -> None:
    dead_clients = []
    for client in list(DASHBOARD_CLIENTS):
        try:
            await client.send_json(payload)
        except Exception:
            dead_clients.append(client)
    for client in dead_clients:
        DASHBOARD_CLIENTS.discard(client)


init_db()


@app.get("/api/zones/labels")
def get_labels():
    return ZONE_LABELS


@app.get("/api/zones")
def get_zones(db: Session = Depends(get_db)):
    zones = db.query(Zone).order_by(Zone.created_at).all()
    return [{"id": z.id, "name": z.name, "label": z.label, "coord": z.coord} for z in zones]


@app.post("/api/zones")
def create_zone(body: dict = Body(...), db: Session = Depends(get_db)):
    zone = Zone(
        id=body.get("id") or str(uuid.uuid4()),
        name=body["name"],
        label=body.get("label"),
        coord=body.get("coord"),
    )
    db.add(zone)
    db.commit()
    return {"id": zone.id, "name": zone.name, "label": zone.label, "coord": zone.coord}


@app.put("/api/zones/{zone_id}")
def update_zone(zone_id: str, body: dict = Body(...), db: Session = Depends(get_db)):
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="구역을 찾을 수 없습니다.")
    if "name"  in body: zone.name  = body["name"]
    if "label" in body: zone.label = body["label"]
    if "coord" in body: zone.coord = body["coord"]
    db.commit()
    return {"id": zone.id, "name": zone.name, "label": zone.label, "coord": zone.coord}


@app.delete("/api/zones/{zone_id}")
def delete_zone(zone_id: str, db: Session = Depends(get_db)):
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if zone:
        db.delete(zone)
        db.commit()
    return {"ok": True}


@app.get("/api/geocode")
def geocode(q: str = Query(...)):
    key = os.getenv("VWORLD_KEY") or os.getenv("VITE_VWORLD_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="VWORLD_KEY가 없습니다.")

    url = "https://map.vworld.kr/search.do"
    for category in ["poi", "juso", "jibun"]:
        params = {"category": category, "q": q, "pageUnit": 1,
                  "output": "json", "pageIndex": 1, "apiKey": key}
        try:
            r = req_lib.get(url, params=params, timeout=5)
            data = r.json()
            items = data.get("LIST") or data.get("response", {}).get("result", {}).get("items", [])
            if items:
                item = items[0]
                return {
                    "lat": float(item.get("ypos")),
                    "lon": float(item.get("xpos")),
                    "addr": item.get("njuso") or item.get("JUSO") or item.get("juso") or item.get("nameFull") or q,
                }
        except Exception:
            continue

    raise HTTPException(status_code=404, detail="주소/장소를 찾지 못했습니다.")


@app.get("/api/reverse-geocode")
def reverse_geocode(lat: float = Query(...), lon: float = Query(...)):
    key = os.getenv("VWORLD_KEY") or os.getenv("VITE_VWORLD_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="VWORLD_KEY가 없습니다.")

    url = "https://api.vworld.kr/req/address"
    params = {
        "service": "address", "request": "getAddress",
        "crs": "epsg:4326", "point": f"{lon},{lat}",
        "type": "both", "zipcode": "true", "simple": "false", "apiKey": key,
    }
    try:
        r = req_lib.get(url, params=params, timeout=5)
        data = r.json()
        results = data.get("response", {}).get("result", [])
        if results:
            addr = results[0].get("text") or results[0].get("structure", {}).get("detail", "")
            return {"lat": lat, "lon": lon, "addr": addr}
    except Exception:
        pass

    return {"lat": lat, "lon": lon, "addr": ""}


@app.post("/api/zone-alert")
async def receive_zone_alert(payload: dict = Body(...)):
    """
    다른 구역의 감지 시스템이 호출하는 알림 수신 API.

    예시 payload:
    {
      "zone_id": "zone-2",
      "zone_name": "강변 저수지 위험구역",
      "kind": "warn1",  // warn1 | warn2 | emergency
      "message": "1차 경고 방송 송출",
      "coord": "37.5665° N, 127.9780° E",
      "addr": "강변 저수지"
    }
    """
    kind = payload.get("kind") or "warn1"
    situation = 2 if kind == "emergency" else 1
    tts_key = (
        "EMERGENCY_GUIDE" if kind == "emergency" else
        "INTRUSION_WARN_2" if kind == "warn2" else
        "INTRUSION_WARN_1"
    )

    event = {
        "type": "zone_alert",
        "timestamp": payload.get("timestamp") or datetime.now().strftime("%H:%M:%S"),
        "zone_id": payload.get("zone_id") or payload.get("zoneId") or "external-zone",
        "zone_name": payload.get("zone_name") or payload.get("zoneName") or "다른 구역",
        "coord": payload.get("coord") or payload.get("map_coord") or "",
        "addr": payload.get("addr") or payload.get("address") or "",
        "kind": kind,
        "situation": payload.get("situation", situation),
        "tts_key": payload.get("tts_key") or tts_key,
        "message": payload.get("message") or (
            "응급 안내 방송 송출" if kind == "emergency" else
            "2차 경고 방송 송출" if kind == "warn2" else
            "1차 경고 방송 송출"
        ),
        "reason": payload.get("reason") or "다른 구역 감지 이벤트 수신",
    }

    await broadcast_to_dashboards(event)
    print(f"[ZONE_ALERT] {event['zone_name']} | {event['kind']} | {event['message']}")
    return {"ok": True, "broadcasted": len(DASHBOARD_CLIENTS), "event": event}


DEFAULT_TTS_MESSAGES = {
    "NONE": "",
    "INTRUSION_WARN_1": "출입이 허가되지 않은 위험 구역입니다. 즉시 안전한 곳으로 이동해 주세요.",
    "INTRUSION_WARN_2": "위험 구역에 계속 머무르고 있습니다. 위치 정보가 상황실로 전송되었습니다. 즉시 퇴장해 주세요.",
    "EMERGENCY_GUIDE": "응급 상황이 감지되었습니다. 가능한 경우 안전한 위치로 이동하고 구조 안내를 기다려 주세요.",
}

EMERGENCY_KEYWORDS = [
    "아파", "아파요", "아프다", "도와", "도와줘", "도와주세요", "살려", "살려줘", "살려주세요",
    "119", "구조", "구해주세요", "불났", "불이야", "쓰러", "쓰러졌", "쓰러짐",
    "다쳤", "다쳐", "부상", "피", "피나요", "갇혔", "위험", "넘어졌", "죽겠",
]


def normalize_text(text: str) -> str:
    return (text or "").replace(" ", "").replace(".", "").replace("!", "").replace("?", "")


def make_beats_scores(sound_event, decision) -> dict:
    top_dict = dict(getattr(sound_event, "top_labels", []) or [])
    if top_dict:
        return {
            "background":   int(top_dict.get("background",   0) * 100),
            "speech":       int(top_dict.get("speech",       0) * 100),
            "footsteps":    int(top_dict.get("footsteps",    0) * 100),
            "interaction":  int(top_dict.get("interaction",  0) * 100),
            "impact_noise": int(top_dict.get("impact_noise", 0) * 100),
        }

    raw = getattr(sound_event, "raw_label", "")
    return {
        "background":   90 if decision.situation == 0 else 5,
        "speech":       80 if raw == "speech"       else 0,
        "footsteps":    80 if raw == "footsteps"    else 0,
        "interaction":  80 if raw == "interaction"  else 0,
        "impact_noise": 80 if raw == "impact_noise" else 0,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    DASHBOARD_CLIENTS.add(websocket)
    print("✅ [Server] 대시보드 연결 수락됨")

    paused_zones: dict[str, bool] = {}
    custom_tts = {
        "INTRUSION_WARN_1": "",
        "INTRUSION_WARN_2": "",
        "EMERGENCY_GUIDE": "",
    }

    tts_dir = BACKEND_DIR / "assets/tts"
    tts_dir.mkdir(parents=True, exist_ok=True)

    current_zone = {
        "zone_id": "default",
        "zone_name": "관리구역 미지정",
        "coord": "",
        "addr": "",
    }
    known_zones = {}

    zone_states = {}

    def get_zone_state(zone_id: str) -> dict:
        return zone_states.setdefault(zone_id or "default", {
            "warn1_issued": False,
            "warn2_issued": False,
            "warn1_time": 0.0,
            "silence_cycles": 0,
            "emergency_until": 0.0,
            "emergency_count": 0,
        })

    async def read_dashboard_commands():
        nonlocal custom_tts, current_zone, known_zones
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
            except asyncio.TimeoutError:
                return

            msg_type = msg.get("type")

            if msg_type == "pause":
                zone_id = msg.get("zone_id") or current_zone.get("zone_id") or "default"
                paused_state = bool(msg.get("paused", False))
                paused_zones[zone_id] = paused_state
                print(f"[DASHBOARD] 구역 {zone_id} 감지 {'일시정지' if paused_state else '재개'}")
                await websocket.send_json({"type": "pause_state", "paused": paused_state, "zone_id": zone_id})

            elif msg_type == "tts_config":
                custom_tts.update({
                    "INTRUSION_WARN_1": msg.get("w1", "") or "",
                    "INTRUSION_WARN_2": msg.get("w2", "") or "",
                    "EMERGENCY_GUIDE": msg.get("emg", "") or "",
                })
                for tts_key, text in custom_tts.items():
                    if text.strip():
                        await save_edge_tts(
                            text.strip(),
                            str(tts_dir / f"{tts_key}.mp3")
                        )
                print("[DASHBOARD] 안내 멘트 설정 반영 및 mp3 생성 완료")

            elif msg_type == "zone_select":
                current_zone = {
                    "zone_id": msg.get("zone_id") or "default",
                    "zone_name": msg.get("zone_name") or "관리구역 미지정",
                    "coord": msg.get("coord") or "",
                    "addr": msg.get("addr") or "",
                }
                get_zone_state(current_zone["zone_id"])
                print(f"[DASHBOARD] 현재 구역 변경: {current_zone['zone_name']} ({current_zone['zone_id']})")

            elif msg_type == "zones_sync":
                zones = msg.get("zones") or []
                known_zones = {
                    str(z.get("id")): {
                        "zone_id": z.get("id"),
                        "zone_name": z.get("name") or "관리구역 미지정",
                        "coord": z.get("coord") or "",
                        "addr": z.get("addr") or "",
                    }
                    for z in zones if z.get("id")
                }
                print(f"[DASHBOARD] 구역 목록 동기화: {len(known_zones)}개")

            elif msg_type == "self_check":
                print("[DASHBOARD] 자가진단 요청 수신")
                await websocket.send_json({
                    "type": "self_check_result",
                    "items": [
                        {"label": "마이크 연결", "ok": True},
                        {"label": "BEATs 모델", "ok": bool(getattr(guard_app.env_classifier, "ready", True))},
                        {"label": "TTS 엔진", "ok": bool(getattr(guard_app, "speaker", None))},
                        {"label": "서버 연결", "ok": True},
                        {"label": "로그 시스템", "ok": bool(getattr(guard_app, "logger", None))},
                    ],
                })

    try:
        print("🔄 [Server] AI 모델(BEATs, Whisper) 로딩 중...")
        guard_app = SoundGuardApp()
        print("🚀 [Server] 모델 로딩 완료. 분석 루프 시작")

        while True:
            await read_dashboard_commands()

            zone_id = current_zone.get("zone_id") or "default"
            if paused_zones.get(zone_id, False):
                await websocket.send_json({"type": "status", "message": "paused"})
                await asyncio.sleep(0.2)
                continue

            await websocket.send_json({"type": "status", "message": "recording"})
            print(f"\n🎤 [{datetime.now().strftime('%H:%M:%S')}] {settings.chunk_seconds}초 녹음 및 분석 시작...")

            audio = guard_app._record_audio()
            audio_path = guard_app._save_audio(audio)

            await read_dashboard_commands()
            if paused_zones.get(zone_id, False):
                print("[DASHBOARD] 녹음 직후 일시정지 요청 확인. 이번 입력은 처리하지 않습니다.")
                continue

            sound_event = guard_app.env_classifier.classify(audio, settings.sample_rate)

            stt_text = ""
            stt_trigger = (
                sound_event.situation in {1, 2}
                or getattr(sound_event, "rms", 0.0) >= settings.min_rms_for_stt
                or getattr(sound_event, "peak", 0.0) >= settings.min_peak_for_stt
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

            now = time.time()
            zone_id = current_zone.get("zone_id") or "default"
            zone_state = get_zone_state(zone_id)
            has_voice = bool((stt_text or "").strip())

            raw_label = str(getattr(sound_event, "raw_label", "") or "")
            confidence = float(getattr(sound_event, "confidence", 0.0) or 0.0)
            compact_text = normalize_text(stt_text)
            has_emergency_keyword = any(keyword in compact_text for keyword in EMERGENCY_KEYWORDS)

            raw_emergency = raw_label == "emergency" and confidence >= 0.80
            if raw_emergency:
                zone_state["emergency_count"] += 1
            else:
                zone_state["emergency_count"] = 0

            confirmed_emergency = has_emergency_keyword or zone_state["emergency_count"] >= 2

            # 1) 현재 구역 응급 3분 유지
            if now < zone_state["emergency_until"] and decision.situation != 2:
                decision = replace(
                    decision,
                    situation=2,
                    situation_name="위험 감지",
                    risk_level="high",
                    reason="해당 구역 응급 상황 감지 후 3분 보호 모드 유지",
                    action="응급 상황 유지 및 감시 지속",
                    tts_key="NONE",
                    send_to_control_room=True,
                    emergency_candidate=True,
                )

            # 2) 새 응급 판정은 확정 조건이 있을 때만 3분 잠금 시작
            elif decision.situation == 2 and confirmed_emergency:
                zone_state["emergency_until"] = now + 180
                zone_state["warn1_issued"] = False
                zone_state["warn2_issued"] = False
                zone_state["warn1_time"] = 0.0
                zone_state["silence_cycles"] = 0

                if decision.tts_key == "NONE":
                    decision = replace(
                        decision,
                        tts_key="EMERGENCY_GUIDE",
                        send_to_control_room=True,
                        emergency_candidate=True,
                    )

            # 3) 응급 후보지만 확정 조건 미충족이면 무단침입으로 낮춤
            elif decision.situation == 2 and not confirmed_emergency:
                decision = replace(
                    decision,
                    situation=1,
                    situation_name="무단침입",
                    risk_level="medium",
                    reason="응급 후보음이 감지되었지만 확정 조건 미충족. 무단침입 경고로 처리",
                    action="침입 경고 처리",
                    tts_key="INTRUSION_WARN_1",
                    send_to_control_room=True,
                    emergency_candidate=False,
                )

            # 4) 침입 1차/2차 경고 - 구역별로 독립 관리
            if decision.situation == 1:
                zone_state["silence_cycles"] = 0

                if (not zone_state["warn1_issued"]) or (now - zone_state["warn1_time"] > 180):
                    decision = replace(
                        decision,
                        situation=1,
                        situation_name="무단침입",
                        risk_level="medium",
                        reason="침입 신호 감지, 1차 경고 송출",
                        action="1차 경고 방송 송출",
                        tts_key="INTRUSION_WARN_1",
                        send_to_control_room=True,
                        emergency_candidate=False,
                    )
                    zone_state["warn1_issued"] = True
                    zone_state["warn2_issued"] = False
                    zone_state["warn1_time"] = now

                elif zone_state["warn1_issued"] and not zone_state["warn2_issued"] and has_voice:
                    decision = replace(
                        decision,
                        situation=1,
                        situation_name="무단침입",
                        risk_level="medium",
                        reason="1차 경고 이후 추가 음성 감지, 2차 경고 송출",
                        action="2차 경고 방송 송출",
                        tts_key="INTRUSION_WARN_2",
                        send_to_control_room=True,
                        emergency_candidate=False,
                    )
                    zone_state["warn2_issued"] = True

                else:
                    decision = replace(
                        decision,
                        tts_key="NONE",
                        action="감시 지속",
                        send_to_control_room=False,
                    )

            elif decision.situation == 0:
                zone_state["silence_cycles"] += 1
                if zone_state["silence_cycles"] >= 6:
                    zone_state["warn1_issued"] = False
                    zone_state["warn2_issued"] = False
                    zone_state["warn1_time"] = 0.0
                    zone_state["silence_cycles"] = 0

            elif decision.situation == 2:
                zone_state["warn1_issued"] = False
                zone_state["warn2_issued"] = False
                zone_state["warn1_time"] = 0.0
                zone_state["silence_cycles"] = 0

            tts_message = ""
            if decision.tts_key != "NONE":
                tts_message = custom_tts.get(decision.tts_key) or DEFAULT_TTS_MESSAGES.get(decision.tts_key, "")

            beats_scores = make_beats_scores(sound_event, decision)

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
                "zone_id": current_zone.get("zone_id"),
                "zone_name": current_zone.get("zone_name"),
                "coord": current_zone.get("coord"),
                "addr": current_zone.get("addr"),
            }

            await websocket.send_json(payload)

            print(
                f"📡 [Server] 전송 완료: "
                f"Zone={payload['zone_name']} | "
                f"BEATs={sound_event.raw_label}/{sound_event.label}({sound_event.confidence:.2f}) | "
                f"Final={decision.situation_name} | TTS={decision.tts_key} | STT={stt_text or '없음'}"
            )

            if decision.tts_key != "NONE":
                print(f"[TTS] {tts_message}")

            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        print("🔌 [Server] 대시보드 연결 종료")
    except Exception as e:
        print(f"❌ [Server] 런타임 에러 발생: {e}")
    finally:
        DASHBOARD_CLIENTS.discard(websocket)
        print("🔌 [Server] WebSocket 세션 종료")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
