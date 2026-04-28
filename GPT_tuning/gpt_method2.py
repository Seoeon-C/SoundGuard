"""
[방식 2] Function Calling (Tool Use)
- GPT가 반드시 정해진 함수 스키마로만 응답하도록 강제
- tool_choice="required" 로 함수 호출을 필수화
- 장점: 출력 형식 100% 안정적, JSON 파싱 오류 없음, 필드 타입 보장
- 단점: 방식 1보다 코드가 약간 복잡
"""

import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(dotenv_path="soundguard_gpt_stt_balanced/.env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")

# GPT가 반드시 호출해야 하는 함수 스키마 정의
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
                        "description": "재생할 TTS 키",
                    },
                    "send_to_control_room": {
                        "type": "boolean",
                        "description": "관제실 전송 여부",
                    },
                    "emergency_candidate": {
                        "type": "boolean",
                        "description": "응급 후보 여부",
                    },
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

판단 기준:
- authorized=true 이면 무조건 situation=0
- danger_sound_detected=true 이거나 STT에 응급 키워드(도와주세요, 살려주세요, 119, 구조, 불이야)가 있으면 situation=2
- person_detected=true 이거나 STT가 있고 dwell_seconds >= 15 이면 situation=1, tts_key=INTRUSION_WARN_2
- person_detected=true 이거나 STT가 있고 dwell_seconds >= 5 이면 situation=1, tts_key=INTRUSION_WARN_1
- 유튜브 자막형 STT("구독해주세요" 등)는 위험 판단에 사용하지 않는다

반드시 report_situation 함수를 호출하여 결과를 반환하라.
"""


def decide(payload: dict) -> dict | None:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
        tools=TOOLS,
        tool_choice={"type": "function", "function": {"name": "report_situation"}},  # 함수 호출 강제
        temperature=0,
    )

    message = response.choices[0].message
    if not message.tool_calls:
        print("[ERROR] GPT가 함수를 호출하지 않았습니다.")
        return None

    args = message.tool_calls[0].function.arguments
    try:
        return json.loads(args)
    except Exception:
        print(f"[ERROR] 함수 인자 파싱 실패:\n{args}")
        return None


# ── 테스트 실행 ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=== [방식 2] Function Calling 테스트 ===\n")
    print("테스트 시나리오:")
    print("  1) 무단침입 (체류 8초, 발소리 감지)")
    print("  2) 위험 감지 (비명 + STT 구조 요청)")
    print("  3) 이상없음 (허가 사용자)")
    print("  4) 직접 입력")

    choice = input("\n선택 (1~4): ").strip()

    if choice == "1":
        payload = {
            "zone_name": "폐공사장 A구역",
            "sound_event": {"label": "footstep", "person_detected": True, "danger_sound_detected": False, "confidence": 0.87},
            "stt_text": "",
            "dwell_seconds": 8.0,
            "authorized": False,
        }
    elif choice == "2":
        payload = {
            "zone_name": "폐공사장 A구역",
            "sound_event": {"label": "scream", "person_detected": True, "danger_sound_detected": True, "confidence": 0.95},
            "stt_text": "도와주세요 다쳤어요",
            "dwell_seconds": 12.0,
            "authorized": False,
        }
    elif choice == "3":
        payload = {
            "zone_name": "폐공사장 A구역",
            "sound_event": {"label": "speech", "person_detected": True, "danger_sound_detected": False, "confidence": 0.80},
            "stt_text": "안전모 착용 확인합니다",
            "dwell_seconds": 20.0,
            "authorized": True,
        }
    else:
        stt = input("STT 텍스트 입력 (없으면 엔터): ").strip()
        dwell = float(input("체류 시간 (초): ").strip())
        authorized = input("허가 사용자? (y/n): ").strip().lower() == "y"
        payload = {
            "zone_name": "폐공사장 A구역",
            "sound_event": {"label": "speech", "person_detected": True, "danger_sound_detected": False, "confidence": 0.75},
            "stt_text": stt,
            "dwell_seconds": dwell,
            "authorized": authorized,
        }

    print(f"\n[입력 payload]\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n")
    print("GPT 판단 중...")

    result = decide(payload)

    if result:
        print(f"\n[GPT 판단 결과]")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("[ERROR] 판단 결과 없음")
