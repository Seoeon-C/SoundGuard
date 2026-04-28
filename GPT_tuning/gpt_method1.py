"""
[방식 1] System Prompt + JSON 구조화 출력
- GPT에게 역할과 판단 기준을 system prompt로 정의
- response_format=json_object 로 JSON 출력 강제
- temperature=0 으로 일관성 확보
- 장점: 구현 단순, 프롬프트 수정만으로 기준 변경 가능
- 단점: 드물게 JSON 형식이 깨질 수 있음 (방식 2보다 불안정)
"""

import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(dotenv_path="soundguard_gpt_stt_balanced/.env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """
너는 음향 기반 위험구역 안전관리 시스템의 판단 모듈이다.
입력값은 BEATs 모델의 음향 분류 결과(label, person_detected, danger_sound_detected, confidence)와
Whisper STT 모델이 말소리를 텍스트로 변환한 stt_text다.
GPT는 날 음향을 직접 듣는 것이 아니라 두 모델의 출력값을 받아 최종 상황을 판단한다.

상황 정의:
- 상황 0 (이상없음): 위험 징후 없음
- 상황 1 (무단침입): 허가 없이 위험구역에 사람이 존재하는 것으로 추정
- 상황 2 (위험 감지): 비명, 충격음, 응급구조 신호 등 즉각 대응 필요

판단 기준:
- authorized=true 이면 무조건 상황 0
- danger_sound_detected=true 이거나 STT에 응급 키워드(도와주세요, 살려주세요, 119, 구조, 불이야 등)가 있으면 상황 2
- person_detected=true 이거나 STT 텍스트가 있고 dwell_seconds >= 15 이면 상황 1 (2차 대응)
- person_detected=true 이거나 STT 텍스트가 있고 dwell_seconds >= 5 이면 상황 1 (1차 대응)
- STT가 유튜브 자막 형태("구독해주세요" 등)이고 환경음 신뢰도가 낮으면 위험 판단에 사용하지 않는다

tts_key 선택 기준:
- 상황 0: "NONE"
- 상황 1 (1차): "INTRUSION_WARN_1"
- 상황 1 (2차): "INTRUSION_WARN_2"
- 상황 2: "EMERGENCY_GUIDE" 또는 "EVACUATION_GUIDE"

반드시 아래 JSON만 출력하라. 마크다운 코드블록 없이 순수 JSON만.

{
  "situation": 0 또는 1 또는 2,
  "situation_name": "이상없음" 또는 "무단침입" 또는 "위험 감지",
  "risk_level": "low" 또는 "medium" 또는 "high",
  "reason": "판단 이유 (한 문장)",
  "action": "수행할 대응",
  "tts_key": "NONE" 또는 "INTRUSION_WARN_1" 또는 "INTRUSION_WARN_2" 또는 "EMERGENCY_GUIDE" 또는 "EVACUATION_GUIDE",
  "send_to_control_room": true 또는 false,
  "emergency_candidate": true 또는 false
}
"""


def decide(payload: dict) -> dict | None:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
        response_format={"type": "json_object"},  # JSON 출력 강제
        temperature=0,
    )
    raw = response.choices[0].message.content or ""
    try:
        return json.loads(raw)
    except Exception:
        print(f"[ERROR] JSON 파싱 실패:\n{raw}")
        return None


# ── 테스트 실행 ──────────────────────────────────────────────
if __name__ == "__main__":
    # 시나리오 선택
    print("=== [방식 1] System Prompt + JSON 출력 테스트 ===\n")
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
