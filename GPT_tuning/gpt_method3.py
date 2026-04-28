"""
[방식 3] 방식 1 + 방식 2 통합 (Rule-based → Function Calling + System Prompt)
- 1단계: 룰 기반 사전 판단 (API 비용 0, 응답 빠름)
  - authorized=True → 즉시 상황 0 반환 (GPT 호출 안 함)
  - danger_sound_detected=True → 즉시 상황 2 반환 (GPT 호출 안 함)
- 2단계: 애매한 경우만 GPT 호출
  - Function Calling으로 출력 형식 강제 (방식 2)
  - System Prompt로 판단 기준 전달 (방식 1)
  - 룰 기반 판단을 GPT 참고용으로 함께 전달
- 3단계: GPT 실패 시 룰 기반 결과로 폴백
  - 룰이 상황 2인데 GPT가 상황 0 → 룰 우선 (안전 우선 원칙)
"""

import json
import os
from dataclasses import dataclass
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(dotenv_path="soundguard_gpt_stt_balanced/.env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")


@dataclass
class DecisionResult:
    situation: int
    situation_name: str
    risk_level: str
    reason: str
    action: str
    tts_key: str
    send_to_control_room: bool
    emergency_candidate: bool
    source: str  # "rule" or "gpt"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "report_situation",
            "description": "BEATs 음향 분류 결과(label, person_detected, danger_sound_detected, confidence)와 Whisper STT 텍스트를 바탕으로 위험 상황을 판단하고 대응 방안을 결정한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "situation": {
                        "type": "integer",
                        "enum": [0, 1, 2],
                        "description": "0=이상없음, 1=무단침입, 2=위험감지",
                    },
                    "situation_name": {
                        "type": "string",
                        "enum": ["이상없음", "무단침입", "위험 감지"],
                    },
                    "risk_level": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "reason": {
                        "type": "string",
                        "description": "판단 이유 (한 문장)",
                    },
                    "action": {
                        "type": "string",
                        "description": "수행할 대응 조치",
                    },
                    "tts_key": {
                        "type": "string",
                        "enum": ["NONE", "INTRUSION_WARN_1", "INTRUSION_WARN_2", "EMERGENCY_GUIDE", "EVACUATION_GUIDE"],
                    },
                    "send_to_control_room": {"type": "boolean"},
                    "emergency_candidate": {"type": "boolean"},
                },
                "required": [
                    "situation", "situation_name", "risk_level",
                    "reason", "action", "tts_key",
                    "send_to_control_room", "emergency_candidate",
                ],
            },
        },
    }
]

SYSTEM_PROMPT = """
너는 음향 기반 위험구역 안전관리 시스템의 판단 모듈이다.
입력값은 BEATs 모델의 음향 분류 결과(label, person_detected, danger_sound_detected, confidence)와
Whisper STT 모델이 말소리를 텍스트로 변환한 stt_text다.
GPT는 날 음향을 직접 듣는 것이 아니라 두 모델의 출력값을 받아 최종 상황을 판단한다.
입력에는 룰 기반 사전 판단(rule_based_result)도 포함되어 있다.
이를 참고하되, 맥락상 더 합리적인 판단이 있으면 수정해도 된다.

단, 아래 원칙은 반드시 지킨다:
- authorized=true 이면 situation=0
- danger_sound_detected=true 이거나 응급 키워드가 있으면 situation=2 (낮추지 마라)
- 응급 키워드 예시: 도와주세요, 살려주세요, 119, 구조, 불이야, 쓰러졌, 구해주세요,
  아파, 아프다, 아파요, 다쳐, 다쳤, 부상, 피나, 윽, 으악, 헉 등
  → 신체적 고통·부상·구조 요청을 암시하는 모든 표현은 situation=2로 판단한다
- 유튜브 자막형 STT("구독해주세요" 등)는 위험 판단에 사용하지 않는다

반드시 report_situation 함수를 호출하여 결과를 반환하라.
"""

EMERGENCY_KEYWORDS = {
    "도와주세요", "살려주세요", "119", "구조", "불났", "불이야", "쓰러졌", "구해주세요",
    "아파", "아프다", "아파요", "아픔", "다쳐", "다쳤", "부상", "피나", "피나요",
    "윽", "으악", "헉", "신음", "못움직", "못움직여", "걷지못", "일어나지못",
}


def _rule_based(payload: dict) -> dict:
    authorized = payload.get("authorized", False)
    stt_text = payload.get("stt_text", "") or ""
    dwell = payload.get("dwell_seconds", 0)
    sound = payload.get("sound_event", {})
    person = sound.get("person_detected", False)
    danger = sound.get("danger_sound_detected", False)
    label = sound.get("label", "")

    if authorized:
        return {
            "situation": 0, "situation_name": "이상없음", "risk_level": "low",
            "reason": "허가된 사용자", "action": "감지 비활성",
            "tts_key": "NONE", "send_to_control_room": False, "emergency_candidate": False,
        }

    normalized = stt_text.replace(" ", "")
    if danger or any(k in normalized for k in EMERGENCY_KEYWORDS):
        return {
            "situation": 2, "situation_name": "위험 감지", "risk_level": "high",
            "reason": "위험음 또는 응급 키워드 감지", "action": "긴급 알림 전송 및 대피 안내",
            "tts_key": "EMERGENCY_GUIDE", "send_to_control_room": True, "emergency_candidate": True,
        }

    person_signal = person or label in {"footstep", "speech"} or bool(stt_text)
    if person_signal:
        if dwell >= 15:
            return {
                "situation": 1, "situation_name": "무단침입", "risk_level": "medium",
                "reason": "위험구역 15초 이상 체류", "action": "2차 경고 방송 및 상황실 전송",
                "tts_key": "INTRUSION_WARN_2", "send_to_control_room": True, "emergency_candidate": False,
            }
        if dwell >= 5 or bool(stt_text):
            return {
                "situation": 1, "situation_name": "무단침입", "risk_level": "low",
                "reason": "사람 신호 또는 5초 이상 체류", "action": "1차 경고 방송",
                "tts_key": "INTRUSION_WARN_1", "send_to_control_room": True, "emergency_candidate": False,
            }

    return {
        "situation": 0, "situation_name": "이상없음", "risk_level": "low",
        "reason": "위험 조건 미충족", "action": "감시 지속",
        "tts_key": "NONE", "send_to_control_room": False, "emergency_candidate": False,
    }


def _ask_gpt(payload: dict) -> dict | None:
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
            ],
            tools=TOOLS,
            tool_choice={"type": "function", "function": {"name": "report_situation"}},
            temperature=0,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            return None
        return json.loads(message.tool_calls[0].function.arguments)
    except Exception as e:
        print(f"[WARN] GPT 호출 실패, 룰 기반으로 폴백: {e}")
        return None


def decide(payload: dict) -> DecisionResult:
    rule = _rule_based(payload)

    # 명확한 케이스는 GPT 호출 없이 즉시 반환
    if payload.get("authorized") or rule["situation"] == 2:
        source = "rule (fast-path)"
        final = rule
    else:
        # 애매한 경우: 룰 판단을 참고용으로 붙여서 GPT에 전달
        gpt_payload = {**payload, "rule_based_result": rule}
        gpt = _ask_gpt(gpt_payload)

        if gpt:
            # 안전 우선: 룰이 위험 2인데 GPT가 0으로 낮추면 룰 우선
            if rule["situation"] == 2 and gpt.get("situation", 0) == 0:
                final, source = rule, "rule (safety override)"
            else:
                final, source = gpt, "gpt"
        else:
            final, source = rule, "rule (gpt fallback)"

    return DecisionResult(
        situation=int(final["situation"]),
        situation_name=str(final["situation_name"]),
        risk_level=str(final["risk_level"]),
        reason=str(final["reason"]),
        action=str(final["action"]),
        tts_key=str(final["tts_key"]),
        send_to_control_room=bool(final["send_to_control_room"]),
        emergency_candidate=bool(final["emergency_candidate"]),
        source=source,
    )


# ── 테스트 실행 ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=== [방식 3] STT 텍스트 입력 테스트 ===")
    print("BEATs 분류 결과: 말소리(speech) 고정")
    print("종료하려면 'q' 입력\n")

    while True:
        stt = input("Whisper STT 텍스트 입력: ").strip()
        if stt.lower() == "q":
            print("종료합니다.")
            break

        dwell = input("체류 시간 (초, 기본값 10): ").strip()
        dwell = float(dwell) if dwell else 10.0

        payload = {
            "zone_name": "폐공사장 A구역",
            "sound_event": {
                "label": "speech",
                "person_detected": True,
                "danger_sound_detected": False,
                "confidence": 0.90,
            },
            "stt_text": stt,
            "dwell_seconds": dwell,
            "authorized": False,
        }

        print("\n판단 중...", end=" ", flush=True)
        result = decide(payload)

        print(f"\n[결과] (판단 주체: {result.source})")
        print(f"  상황: {result.situation} - {result.situation_name}")
        print(f"  위험도: {result.risk_level}")
        print(f"  이유: {result.reason}")
        print(f"  대응: {result.action}")
        print(f"  TTS: {result.tts_key}")
        print(f"  관제실 전송: {result.send_to_control_room}")
        print(f"  응급 후보: {result.emergency_candidate}")
        print("-" * 50)
