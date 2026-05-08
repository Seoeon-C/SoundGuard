"""
server.py - Oracle Cloud 서버에서 실행

역할:
  - /sensor  WebSocket: 현장 sensor.py로부터 오디오 수신 → AI 분석
  - /ws      WebSocket: 대시보드 브라우저에 분석 결과 전송
  - /api/zone-alert REST: 다른 구역 이벤트 수신 → 전체 대시보드 브로드캐스트

실행:
  python -m uvicorn server:app --host 0.0.0.0 --port 8000
"""

import sys
import uuid
import os
import asyncio
import json
import time
import tempfile
import requests as req_lib
from datetime import datetime
from dataclasses import replace
from pathlib import Path

import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body, Depends, Query, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

# 현재 폴더(backend_on_server) 모듈 참조
_cur = Path(__file__).resolve().parent
sys.path.insert(0, str(_cur))
sys.path.insert(0, str(_cur / "BEATs"))

from config import settings, BACKEND_DIR
from environmental_sound import BeatsEnvironmentClassifier, SoundEvent
from stt import WhisperAPI
from decision import GPTDecisionEngine, DecisionResult
from output import EventLoggerAndMessenger
from db import Zone, get_db, init_db, ZONE_LABELS
from tts_to_mp3.tts import save_edge_tts

# ── FastAPI 앱 ────────────────────────────────────────────────────
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

# 핸드폰 센서 앱 관련 설정
SERVER_PUBLIC_URL = os.getenv("SERVER_PUBLIC_URL", "http://168.107.31.37:8000")

_tts_dir      = BACKEND_DIR / "assets/tts"
_received_dir = BACKEND_DIR / "received"
_tts_dir.mkdir(parents=True, exist_ok=True)
_received_dir.mkdir(parents=True, exist_ok=True)

# 대시보드에서 생성한 안내방송 .mp3 를 핸드폰에서 다운로드 가능하게 노출
app.mount("/tts", StaticFiles(directory=str(_tts_dir)), name="tts")


def looks_like_device_name(name: str | None) -> bool:
    text = (name or "").strip().lower()
    def numbered(prefix: str) -> bool:
        if text == prefix:
            return True
        if not text.startswith(prefix):
            return False
        suffix = text[len(prefix):].strip(" -_()")
        return suffix.isdigit()
    return (
        text.startswith("핸드폰 센서")
        or numbered("센서")
        or numbered("기계")
        or numbered("machine")
        or numbered("device")
    )


def resolve_zone_display(
    db: Session,
    zone_id: str,
    fallback_name: str | None = None,
    fallback_coord: str | None = None,
    fallback_addr: str | None = None,
) -> tuple[str, str, str]:
    zone = db.query(Zone).filter(Zone.id == zone_id).first() if zone_id else None
    if zone:
        return zone.name, zone.coord or fallback_coord or "", fallback_addr or settings.location_text
    if fallback_name and not looks_like_device_name(fallback_name):
        return fallback_name, fallback_coord or "", fallback_addr or settings.location_text
    return settings.zone_name, fallback_coord or "", fallback_addr or settings.location_text


# ── 구역 CRUD API ─────────────────────────────────────────────────
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


# 구역별 일시정지 상태 (전역)
PAUSED_ZONES: set[str] = set()

# ── 공유 AI 모델 (서버 시작 시 1회만 로드) ───────────────────────
class SharedAI:
    def __init__(self):
        print("🔄 [Server] AI 모델 로딩 중...")
        print(f"📦 [Server] 사용 모델: {settings.beats_checkpoint_path}")
        self.env_classifier = BeatsEnvironmentClassifier()
        try:
            self.stt = WhisperAPI()
        except Exception as exc:
            print(f"[WARN] STT 비활성화: {exc}")
            self.stt = None
        self.decision_engine = GPTDecisionEngine()
        self.logger = EventLoggerAndMessenger()
        print("✅ [Server] AI 모델 로딩 완료")

ai: SharedAI | None = None


async def _generate_tts_files(tts_dir: Path) -> None:
    """TTS mp3 파일 생성 (백그라운드 실행)"""
    messages = {
        k: (CUSTOM_TTS_MESSAGES.get(k) or DEFAULT_TTS_MESSAGES.get(k, ""))
        for k in ["INTRUSION_WARN_1", "INTRUSION_WARN_2", "EMERGENCY_GUIDE"]
    }
    tasks = [
        save_edge_tts(text.strip(), str(tts_dir / f"{key}.mp3"))
        for key, text in messages.items() if text.strip()
    ]
    if tasks:
        await asyncio.gather(*tasks)
    print("[TTS] mp3 생성 완료")


@app.on_event("startup")
async def startup():
    global ai
    ai = SharedAI()
    tts_dir = BACKEND_DIR / "assets/tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    asyncio.create_task(_generate_tts_files(tts_dir))


# ── 연결 관리 ─────────────────────────────────────────────────────
DASHBOARD_CLIENTS: set[WebSocket] = set()

# 구역별 상태
ZONE_STATES: dict[str, dict] = {}

# 업로드 중복 처리 방지 (최신 청크만 처리)
ZONE_UPLOAD_LOCKS: dict[str, asyncio.Lock] = {}
ZONE_LAST_URL: dict[str, str] = {}

# 구역별 대시보드 클라이언트 (채널 분리)
ZONE_CLIENTS: dict[str, set] = {}

def _zone_clients_add(zone_id: str, ws) -> None:
    ZONE_CLIENTS.setdefault(zone_id, set()).add(ws)

def _zone_clients_remove(ws) -> None:
    for s in ZONE_CLIENTS.values():
        s.discard(ws)

EMERGENCY_KEYWORDS = [
    "아파", "아파요", "아프다", "도와", "도와줘", "도와주세요",
    "살려", "살려줘", "살려주세요", "119", "구조", "구해주세요",
    "불났", "불이야", "쓰러", "쓰러졌", "다쳤", "다쳐", "갇혔",
    "위험", "넘어졌", "죽겠",
]

DEFAULT_TTS_MESSAGES = {
    "NONE": "",
    "INTRUSION_WARN_1": "출입이 허가되지 않은 위험 구역입니다. 즉시 안전한 곳으로 이동해 주세요.",
    "INTRUSION_WARN_2": "위험 구역에 계속 머무르고 있습니다. 위치 정보가 상황실로 전송되었습니다. 즉시 퇴장해 주세요.",
    "EMERGENCY_GUIDE": "응급 상황이 감지되었습니다. 가능한 경우 안전한 위치로 이동하고 구조 안내를 기다려 주세요.",
}

# 웹 대시보드에서 설정한 멘트 - 전역으로 관리하여 sensor 처리에도 반영
CUSTOM_TTS_MESSAGES = {
    "INTRUSION_WARN_1": "",
    "INTRUSION_WARN_2": "",
    "EMERGENCY_GUIDE": "",
}

_TTS_CONFIG_PATH = BACKEND_DIR / "assets/tts_config.json"


def _load_custom_tts():
    """서버 시작 시 저장된 멘트 설정 복원"""
    if _TTS_CONFIG_PATH.exists():
        try:
            import json as _json
            data = _json.loads(_TTS_CONFIG_PATH.read_text(encoding="utf-8"))
            for k in CUSTOM_TTS_MESSAGES:
                if data.get(k):
                    CUSTOM_TTS_MESSAGES[k] = data[k]
            print("[TTS] 저장된 안내 멘트 설정 복원 완료")
        except Exception:
            pass


def _save_custom_tts():
    """멘트 설정을 파일에 저장"""
    import json as _json
    _TTS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TTS_CONFIG_PATH.write_text(
        _json.dumps(CUSTOM_TTS_MESSAGES, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


_load_custom_tts()


_EMERGENCY_LOCK_SECONDS = 180
_EMERGENCY_INTERVALS   = (30, 60)  # 응급 재안내: 2차→30초, 3차+→60초

def get_zone_state(zone_id: str) -> dict:
    return ZONE_STATES.setdefault(zone_id or "default", {
        "warn1_issued": False,
        "warn2_issued": False,
        "warn1_time": 0.0,
        "warn2_time": 0.0,
        "silence_cycles": 0,
        "emergency_until": 0.0,
        "emergency_count": 0,
        "last_emergency_announce": 0.0,
        "emergency_announce_count": 0,
        "created_at": time.time(),
    })


def normalize_text(text: str) -> str:
    return (text or "").replace(" ", "").replace(".", "").replace("!", "").replace("?", "")


def make_beats_scores(sound_event, decision) -> dict:
    top_dict = dict(getattr(sound_event, "top_labels", []) or [])
    if top_dict:
        scores = {k: int(top_dict.get(k, 0) * 100)
                  for k in ("background", "speech", "footsteps", "interaction", "impact_noise")}
        scores["emergency"] = 0
        return scores
    raw = getattr(sound_event, "raw_label", "")
    scores = {
        "background":   90 if decision.situation == 0 else 5,
        "speech":       80 if raw == "speech"       else 0,
        "footsteps":    80 if raw == "footsteps"    else 0,
        "interaction":  80 if raw == "interaction"  else 0,
        "impact_noise": 80 if raw == "impact_noise" else 0,
    }
    scores["emergency"] = 0
    return scores


async def broadcast(payload: dict):
    dead = []
    for client in list(DASHBOARD_CLIENTS):
        try:
            await client.send_json(payload)
        except Exception:
            dead.append(client)
    for c in dead:
        DASHBOARD_CLIENTS.discard(c)


async def broadcast_to_zone(zone_id: str, payload: dict):
    """해당 구역 클라이언트에게 전송. 아무도 없으면 전체에 전송(폴백)"""
    targets = list(ZONE_CLIENTS.get(zone_id, set()))
    all_registered = set().union(*ZONE_CLIENTS.values()) if ZONE_CLIENTS else set()
    unregistered = list(DASHBOARD_CLIENTS - all_registered)
    recipients = (targets + unregistered) or list(DASHBOARD_CLIENTS)
    dead = []
    for client in recipients:
        try:
            await client.send_json(payload)
        except Exception:
            dead.append(client)
    for c in dead:
        DASHBOARD_CLIENTS.discard(c)
        _zone_clients_remove(c)


async def broadcast_zone_alert(zone_id: str, payload: dict):
    """다른 구역 보고 있는 클라이언트에게 알림 전송"""
    tts_key = payload.get("tts_key", "NONE")
    kind = (
        "emergency" if tts_key in {"EMERGENCY_GUIDE", "EVACUATION_GUIDE"} else
        "warn2"     if tts_key == "INTRUSION_WARN_2" else
        "warn1"     if tts_key == "INTRUSION_WARN_1" else None
    )
    if not kind:
        return  # 정상 상황은 알림 불필요
    alert = {
        "type":      "zone_alert",
        "timestamp": payload.get("timestamp", ""),
        "zone_id":   payload.get("zone_id", ""),
        "zone_name": payload.get("zone_name", ""),
        "coord":     payload.get("coord", ""),
        "addr":      payload.get("addr", ""),
        "kind":      kind,
        "situation": payload.get("situation", 0),
        "tts_key":   tts_key,
        "message":   payload.get("tts_message", ""),
    }
    monitoring = ZONE_CLIENTS.get(zone_id, set())
    dead = []
    for client in list(DASHBOARD_CLIENTS):
        if client in monitoring:
            continue
        try:
            await client.send_json(alert)
        except Exception:
            dead.append(client)
    for c in dead:
        DASHBOARD_CLIENTS.discard(c)


# ── /api/zone-alert ───────────────────────────────────────────────
@app.post("/api/zone-alert")
async def receive_zone_alert(payload: dict = Body(...), db: Session = Depends(get_db)):
    """다른 구역 감지 시스템이 호출하는 알림 수신 API."""
    kind = payload.get("kind") or "warn1"
    zone_id = payload.get("zone_id") or payload.get("zoneId") or "external-zone"
    zone_name, coord, addr = resolve_zone_display(
        db=db,
        zone_id=zone_id,
        fallback_name=payload.get("zone_name") or payload.get("zoneName"),
        fallback_coord=payload.get("coord") or payload.get("map_coord"),
        fallback_addr=payload.get("addr") or payload.get("address"),
    )
    event = {
        "type": "zone_alert",
        "timestamp": payload.get("timestamp") or datetime.now().strftime("%H:%M:%S"),
        "zone_id":   zone_id,
        "zone_name": zone_name,
        "coord":     coord,
        "addr":      addr,
        "kind":      kind,
        "situation": payload.get("situation", 2 if kind == "emergency" else 1),
        "tts_key":   payload.get("tts_key") or (
            "EMERGENCY_GUIDE"   if kind == "emergency" else
            "INTRUSION_WARN_2"  if kind == "warn2"     else
            "INTRUSION_WARN_1"
        ),
        "message": payload.get("message") or (
            "응급 안내 방송 송출" if kind == "emergency" else
            "2차 경고 방송 송출" if kind == "warn2"     else
            "1차 경고 방송 송출"
        ),
    }
    await broadcast(event)
    return {"ok": True, "broadcasted": len(DASHBOARD_CLIENTS)}


# ── /ws (대시보드) ────────────────────────────────────────────────
@app.websocket("/ws")
async def dashboard_endpoint(websocket: WebSocket):
    await websocket.accept()
    DASHBOARD_CLIENTS.add(websocket)
    print("✅ [Dashboard] 대시보드 연결됨")

    tts_dir = BACKEND_DIR / "assets/tts"
    tts_dir.mkdir(parents=True, exist_ok=True)

    try:
        async for raw in websocket.iter_json():
            msg_type = raw.get("type")

            if msg_type == "tts_config":
                changed = False
                for key, env_key in [("INTRUSION_WARN_1","w1"),("INTRUSION_WARN_2","w2"),("EMERGENCY_GUIDE","emg")]:
                    val = (raw.get(env_key) or "").strip()
                    if val and val != CUSTOM_TTS_MESSAGES.get(key):
                        CUSTOM_TTS_MESSAGES[key] = val
                        changed = True
                if changed:
                    _save_custom_tts()
                    asyncio.create_task(_generate_tts_files(tts_dir))
                    print("[DASHBOARD] 안내 멘트 변경 감지 → mp3 백그라운드 생성 중")
                else:
                    print("[DASHBOARD] 안내 멘트 변경 없음 → mp3 재생성 생략")

            elif msg_type == "pause":
                zone_id = raw.get("zone_id") or "default"
                paused_state = bool(raw.get("paused", False))
                if paused_state:
                    PAUSED_ZONES.add(zone_id)
                else:
                    PAUSED_ZONES.discard(zone_id)
                print(f"[DASHBOARD] 구역 {zone_id} 감지 {'일시정지' if paused_state else '재개'}")
                await broadcast({"type": "pause_state", "paused": paused_state, "zone_id": zone_id})

            elif msg_type == "zone_select":
                new_zone_id = raw.get("zone_id") or "default"
                _zone_clients_remove(websocket)
                _zone_clients_add(new_zone_id, websocket)
                print(f"[DASHBOARD] 클라이언트 구역 등록: {new_zone_id}")

            elif msg_type == "self_check":
                await websocket.send_json({
                    "type": "self_check_result",
                    "items": [
                        {"label": "BEATs 모델",  "ok": ai is not None},
                        {"label": "STT 엔진",    "ok": ai is not None and ai.stt is not None},
                        {"label": "서버 연결",   "ok": True},
                        {"label": "로그 시스템", "ok": ai is not None},
                    ],
                })

    except WebSocketDisconnect:
        pass
    finally:
        DASHBOARD_CLIENTS.discard(websocket)
        _zone_clients_remove(websocket)
        print("🔌 [Dashboard] 대시보드 연결 종료")


# ── /sensor (현장 sensor.py) ──────────────────────────────────────
@app.websocket("/sensor")
async def sensor_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("🎤 [Sensor] 센서 연결됨")

    zone_info: dict = {
        "zone_id":       "default",
        "zone_name":     "관리구역 미지정",
        "coord":         "",
        "addr":          "",
        "sample_rate":   settings.sample_rate,
        "chunk_seconds": settings.chunk_seconds,
    }
    paused = False

    try:
        # 첫 메시지: zone_info JSON 수신
        first = await websocket.receive_text()
        meta = json.loads(first)
        if meta.get("type") == "zone_info":
            zone_info.update({k: meta[k] for k in meta if k != "type"})

            # DB에서 zone_name으로 구역 조회 → 없으면 자동 생성
            db = next(get_db())
            try:
                db_zone = db.query(Zone).filter(Zone.name == zone_info["zone_name"]).first()
                if db_zone:
                    zone_info["zone_id"] = db_zone.id
                    print(f"[Sensor] DB 구역 매핑: {zone_info['zone_name']} → {db_zone.id}")
                else:
                    new_zone = Zone(
                        id=str(uuid.uuid4()),
                        name=zone_info["zone_name"],
                        coord=zone_info.get("coord", ""),
                    )
                    db.add(new_zone)
                    db.commit()
                    db.refresh(new_zone)
                    zone_info["zone_id"] = new_zone.id
                    print(f"[Sensor] DB 구역 자동 생성: {zone_info['zone_name']} → {new_zone.id}")
                    await broadcast({"type": "zones_updated"})
            finally:
                db.close()

            # zone_id 확정 후 표시용 zone_name/coord/addr 보정
            db2 = next(get_db())
            try:
                zone_name_disp, coord_disp, addr_disp = resolve_zone_display(
                    db=db2,
                    zone_id=zone_info["zone_id"],
                    fallback_name=zone_info.get("zone_name"),
                    fallback_coord=zone_info.get("coord"),
                    fallback_addr=zone_info.get("addr"),
                )
                zone_info.update({"zone_name": zone_name_disp, "coord": coord_disp, "addr": addr_disp})
            finally:
                db2.close()

            # 최초 zone 상태 강제 초기화
            get_zone_state(zone_info["zone_id"])
            print(f"[ZONE INIT] {zone_info['zone_id']} 상태 초기화 완료")
            print(
                f"[Sensor] 구역 등록: {zone_info['zone_name']} ({zone_info['zone_id']}) "
                f"| {zone_info['sample_rate']}Hz / {zone_info['chunk_seconds']}s"
            )

        sample_rate   = int(zone_info.get("sample_rate",   settings.sample_rate))
        zone_id       = zone_info["zone_id"]
        zone_state    = get_zone_state(zone_id)
        tmp_path      = Path(tempfile.gettempdir()) / f"sensor_{zone_id}.wav"

        # ── 최신 청크만 처리 (밀림 방지) ──
        latest_chunk: bytes | None = None
        is_processing = False

        async def process_worker():
            nonlocal latest_chunk, is_processing
            while latest_chunk is not None:
                chunk = latest_chunk
                latest_chunk = None
                try:
                    await _process_audio(chunk, sample_rate, zone_info, zone_state, tmp_path)
                except Exception as exc:
                    print(f"[Sensor] 처리 오류: {exc}")
            is_processing = False

        # 분석 루프
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive(), timeout=0.01)
                if raw["type"] == "websocket.receive":
                    if "text" in raw and raw["text"]:
                        msg = json.loads(raw["text"])
                        if msg.get("type") == "pause":
                            paused = msg.get("paused", False)
                            print(f"[Sensor:{zone_id}] 감지 {'일시정지' if paused else '재개'}")
                            await websocket.send_text(json.dumps({"type": "pause", "paused": paused}))
                    elif "bytes" in raw and raw["bytes"]:
                        if not paused:
                            if latest_chunk is not None:
                                print(f"[Sensor:{zone_id}] 구 청크 건너뜀 → 최신 청크로 교체")
                            latest_chunk = raw["bytes"]
                            if not is_processing:
                                is_processing = True
                                asyncio.create_task(process_worker())
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[Sensor] 오류: {exc}")
    finally:
        print(f"🔌 [Sensor] 센서 연결 종료: {zone_info['zone_name']}")


async def _process_audio(
    audio_bytes: bytes,
    sample_rate: int,
    zone_info: dict,
    zone_state: dict,
    tmp_path: Path,
):
    """오디오 bytes → AI 분석 → 대시보드 전송"""
    import soundfile as sf

    zone_id   = zone_info["zone_id"]
    zone_name = zone_info["zone_name"]
    now       = time.time()

    # bytes → numpy
    audio = np.frombuffer(audio_bytes, dtype=np.float32)

    # 임시 wav 저장 (STT용)
    sf.write(tmp_path, audio, sample_rate)

    _t0 = time.time()
    loop = asyncio.get_event_loop()

    # rms/peak 사전 계산 (BEATs 결과 없이 STT 실행 여부 판단)
    pre_rms  = float(np.sqrt(np.mean(audio ** 2)))
    pre_peak = float(np.max(np.abs(audio)))
    stt_worthy = (
        ai.stt is not None and
        not (pre_rms < settings.min_rms_for_stt and pre_peak < settings.min_peak_for_stt)
    )

    if stt_worthy:
        # ── BEATs + STT 병렬 실행 ──
        beats_task = loop.run_in_executor(None, ai.env_classifier.classify, audio, sample_rate)
        stt_task   = loop.run_in_executor(None, ai.stt.transcribe, tmp_path)
        results    = await asyncio.gather(beats_task, stt_task, return_exceptions=True)

        sound_event = results[0] if not isinstance(results[0], Exception) \
                      else ai.env_classifier._fallback_classify(pre_rms, pre_peak)
        if isinstance(results[1], Exception):
            print(f"[STT] 실패: {results[1]}")
            stt_text = ""
        else:
            stt_text = results[1] or ""
    else:
        # ── BEATs만 실행 (저음량) ──
        sound_event = await loop.run_in_executor(None, ai.env_classifier.classify, audio, sample_rate)
        stt_text = ""

    _t_beats = time.time()
    stt_ran = stt_worthy

    # ── DwellTracker ──
    if sound_event.situation in {1, 2}:
        if zone_state.get("detected_since") is None:
            zone_state["detected_since"] = now
        dwell_seconds = now - zone_state["detected_since"]
    else:
        zone_state["detected_since"] = None
        dwell_seconds = 0.0

    # ── GPT 판단 ──
    decision = ai.decision_engine.decide(
        sound_event=sound_event,
        stt_text=stt_text,
        dwell_seconds=dwell_seconds,
        authorized=False,
    )
    _t_gpt = time.time()

    print(
        f"⏱ [{zone_name}] 병렬(BEATs+STT)={_t_beats-_t0:.2f}s ({'STT포함' if stt_ran else 'STT생략'})"
        f" | GPT={_t_gpt-_t_beats:.2f}s"
        f" | 합계={_t_gpt-_t0:.2f}s"
    )

    # ── 구역별 경고/응급 상태 관리 ──
    has_voice       = bool((stt_text or "").strip())
    compact_text    = normalize_text(stt_text)
    has_emg_keyword = any(kw in compact_text for kw in EMERGENCY_KEYWORDS)
    raw_label       = str(getattr(sound_event, "raw_label", "") or "")
    confidence      = float(getattr(sound_event, "confidence", 0.0) or 0.0)

    raw_danger_candidate = raw_label == "impact_noise" and confidence >= 0.80
    zone_state["emergency_count"] = (zone_state.get("emergency_count", 0) + 1) if raw_danger_candidate else 0
    gpt_confirmed_emergency = (
        decision.situation == 2
        and decision.emergency_candidate
        and str(decision.source).startswith("gpt")
    )
    emergency_voice_confirmed = has_emg_keyword or gpt_confirmed_emergency
    confirmed_emergency = emergency_voice_confirmed or zone_state["emergency_count"] >= 2

    # ── 응급 잠금 처리 (app.py _apply_emergency_lock 동일 로직) ──
    in_emergency_lock = False

    if decision.situation == 2 and confirmed_emergency:
        # 응급 확정 → 잠금 (재)설정 + 즉시 재안내 트리거 (잠금 중이어도 동일)
        zone_state["emergency_until"]          = now + _EMERGENCY_LOCK_SECONDS
        zone_state["last_emergency_announce"]  = 0.0  # count==0 → 즉시 재생 트리거
        zone_state["emergency_announce_count"] = 0
        zone_state["warn1_issued"]             = False
        zone_state["silence_cycles"]           = 0
        in_emergency_lock = True

    elif decision.situation == 2 and not confirmed_emergency:
        if now < zone_state.get("emergency_until", 0.0):
            in_emergency_lock = True          # 잠금 유지
        else:
            decision = replace(decision, situation=1, situation_name="무단침입",
                               risk_level="medium", tts_key="INTRUSION_WARN_1",
                               send_to_control_room=True, emergency_candidate=False)

    elif now < zone_state.get("emergency_until", 0.0):
        in_emergency_lock = True              # situation≠2인데 잠금 유지 중

    # 잠금 상태: back-off 재안내 타이밍 계산 (app.py _apply_emergency_lock 동일)
    if in_emergency_lock:
        elapsed = now - zone_state.get("last_emergency_announce", 0.0)
        count   = zone_state.get("emergency_announce_count", 0)
        if count == 0:
            should_announce = True
        elif count == 1:
            should_announce = elapsed >= _EMERGENCY_INTERVALS[0]
        else:
            should_announce = elapsed >= _EMERGENCY_INTERVALS[1]

        if should_announce:
            zone_state["last_emergency_announce"]  = now
            zone_state["emergency_announce_count"] = count + 1
            emg_tts = "EMERGENCY_GUIDE"
        else:
            emg_tts = "NONE"

        remaining = zone_state["emergency_until"] - now
        decision = replace(decision, situation=2, situation_name="위험 감지",
                           risk_level="high", tts_key=emg_tts,
                           reason=f"응급 잠금 유지 중 (남은 시간 {remaining:.0f}초)",
                           send_to_control_room=True)

    # ── 침입 경고 상태 관리 ──
    if not in_emergency_lock:
        if zone_state.get("warn2_issued"):
            # 2차 경고 진행 중 → 감지 여부 무관하게 30초마다 반복
            if now - zone_state.get("warn2_time", 0.0) >= 30:
                decision = replace(decision, tts_key="INTRUSION_WARN_2", action="2차 경고 반복")
                zone_state["warn2_time"] = now
            else:
                decision = replace(decision, tts_key="NONE", action="감시 지속", send_to_control_room=False)
        elif decision.situation == 1:
            if not zone_state.get("warn1_issued"):
                # 1차 경고
                decision = replace(decision, tts_key="INTRUSION_WARN_1", action="1차 경고 방송 송출")
                zone_state["warn1_issued"] = True
            else:
                # 1차 이후 감지 → 즉시 2차 경고 (타이머 없음)
                decision = replace(decision, tts_key="INTRUSION_WARN_2",
                                   action="2차 경고 방송 송출", send_to_control_room=True)
                zone_state["warn2_issued"] = True
                zone_state["warn2_time"] = now

    # ── 정상상황 연속 카운트 (situation 기준) → 6회면 전체 리셋 ──
    if decision.situation == 2:
        # 응급 전환 시 침입 경고 상태 초기화
        zone_state.update({"warn1_issued": False, "warn2_issued": False,
                           "warn2_time": 0.0, "silence_cycles": 0})

    if decision.situation == 0:
        zone_state["silence_cycles"] = zone_state.get("silence_cycles", 0) + 1
        if zone_state["silence_cycles"] >= 6:
            zone_state.update({"warn1_issued": False, "warn2_issued": False,
                               "warn2_time": 0.0, "silence_cycles": 0})
    else:
        zone_state["silence_cycles"] = 0

    tts_message = ""
    if decision.tts_key != "NONE":
        tts_message = (
            CUSTOM_TTS_MESSAGES.get(decision.tts_key)
            or DEFAULT_TTS_MESSAGES.get(decision.tts_key, "")
        )

    # ── 대시보드 전송 ──
    payload = {
        "type":              "analysis",
        "timestamp":         datetime.now().strftime("%H:%M:%S"),
        "situation":         decision.situation,
        "situation_name":    decision.situation_name,
        "risk_level":        decision.risk_level,
        "reason":            decision.reason,
        "action":            decision.action,
        "tts_key":           decision.tts_key,
        "tts_message":       tts_message,
        "emergency_candidate":       decision.emergency_candidate,
        "emergency_voice_confirmed": emergency_voice_confirmed,
        "decision_source":           decision.source,
        "beats_label":       sound_event.label,
        "beats_raw_label":   sound_event.raw_label,
        "beats_confidence":  sound_event.confidence,
        "rms":               sound_event.rms,
        "peak":              sound_event.peak,
        "stt_text":          stt_text,
        "dwell_seconds":     dwell_seconds,
        "beats":             {**make_beats_scores(sound_event, decision),
                              "emergency": 100 if decision.situation == 2 and emergency_voice_confirmed else 0},
        "zone_id":           zone_id,
        "zone_name":         zone_name,
        "coord":             zone_info.get("coord", ""),
        "addr":              zone_info.get("addr", ""),
    }

    await broadcast_to_zone(zone_id, payload)
    if decision.situation in {1, 2}:
        await broadcast_zone_alert(zone_id, payload)

    print(
        f"📡 [{zone_name}] BEATs={sound_event.raw_label}/{sound_event.label}"
        f"({sound_event.confidence:.2f}) | Final={decision.situation_name}"
        f" | TTS={decision.tts_key} | STT={stt_text or '없음'}"
    )

    return decision


# ── /upload (핸드폰 센서 앱) ──────────────────────────────────────
@app.post("/upload")
async def upload_audio(file: UploadFile = File(...), device_id: str = Form(...), db: Session = Depends(get_db)):
    """
    핸드폰 센서 앱에서 녹음 WAV 파일을 받아 AI 분석 후 안내방송 .mp3 URL 반환.

    반환값:
      - announcement_url: 재생할 .mp3 URL (위험 없음이면 빈 문자열 "")
    """
    if device_id in PAUSED_ZONES:
        return {"status": "paused", "announcement_url": ""}

    lock = ZONE_UPLOAD_LOCKS.setdefault(device_id, asyncio.Lock())
    if lock.locked():
        print(f"[UPLOAD] {device_id} 처리 중 → 청크 건너뜀 (최신 청크 우선)")
        return {"status": "busy", "announcement_url": ZONE_LAST_URL.get(device_id, "")}

    import soundfile as sf

    # WAV 저장
    content = await file.read()
    received_path = _received_dir / file.filename
    received_path.write_bytes(content)

    # WAV → numpy float32 (sensor WebSocket과 동일 포맷으로 변환)
    audio_np, sample_rate = sf.read(received_path)
    if audio_np.ndim > 1:
        audio_np = audio_np[:, 0]
    audio_np = audio_np.astype(np.float32)

    tmp_path   = Path(tempfile.gettempdir()) / f"upload_{device_id}.wav"
    sf.write(tmp_path, audio_np, sample_rate)

    zone_name_disp, coord_disp, addr_disp = resolve_zone_display(db=db, zone_id=device_id)
    zone_info  = {
        "zone_id":   device_id,
        "zone_name": zone_name_disp,
        "coord":     coord_disp,
        "addr":      addr_disp,
    }
    zone_state = get_zone_state(device_id)

    # AI 분석 + 대시보드 브로드캐스트 (Lock으로 중복 처리 방지)
    async with lock:
        decision = await _process_audio(
            audio_np.tobytes(), sample_rate, zone_info, zone_state, tmp_path
        )

    # tts_key → .mp3 URL
    announcement_url = ""
    if decision and decision.tts_key not in ("NONE", None, ""):
        mp3_path = _tts_dir / f"{decision.tts_key}.mp3"
        if mp3_path.exists():
            announcement_url = f"{SERVER_PUBLIC_URL}/tts/{decision.tts_key}.mp3"
    ZONE_LAST_URL[device_id] = announcement_url

    print(f"[UPLOAD] tts_key={decision.tts_key if decision else 'None'} → url={announcement_url or '(없음)'}")
    return {"status": "success", "announcement_url": announcement_url}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
