import json
from dataclasses import dataclass
from openai import OpenAI
from config import settings


client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
MODEL = settings.openai_llm_model


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
    source: str


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
                        "enum": ["NONE", "INTRUSION_WARN_1", "INTRUSION_WARN_2", "EMERGENCY_GUIDE"],
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
- background는 정상상황이다.
- speech, footsteps, interaction은 무단침입 후보 신호다.
- impact_noise는 위험 감지 후보 신호다.
- 응급 키워드가 있으면 situation=2 (낮추지 마라)
- STT 문장이 구조 요청, 부상, 신체적 고통, 화재 등 응급 맥락이면 situation=2로 확정한다.
- danger_sound_detected=true 여도 STT가 "안녕하세요" 같은 일반 발화면 situation=1 무단침입으로 판단한다.
- 응급 키워드 예시: 도와주세요, 살려주세요, 119, 구조, 불이야, 쓰러졌, 구해주세요,
  아파, 아프다, 아파요, 다쳐, 다쳤, 부상, 피나, 윽, 으악, 헉 등
  → 신체적 고통·부상·구조 요청을 암시하는 모든 표현은 situation=2로 판단한다
- rule_based_result의 tts_key가 INTRUSION_WARN_2이면 반드시 INTRUSION_WARN_2를 유지하라.
  이는 1차 경고 이후 추가 소리가 감지된 상황이므로 절대 INTRUSION_WARN_1으로 낮추지 마라.
- 유튜브 자막형 STT("구독해주세요" 등)는 위험 판단에 사용하지 않는다

반드시 report_situation 함수를 호출하여 결과를 반환하라.
"""

EMERGENCY_KEYWORDS = {
    "도와주세요", "살려주세요", "119", "구조", "불났", "불이야", "쓰러졌", "구해주세요",
    "아파", "아프다", "아파요", "아픔", "다쳐", "다쳤", "부상", "피나", "피나요",
    "윽", "으악", "헉", "신음", "못움직", "못움직여", "걷지못", "일어나지못",
}

INTRUSION_CANDIDATE_LABELS = {"speech", "footsteps", "interaction"}
DANGER_CANDIDATE_LABELS = {"impact_noise"}


def _normalize_text(text: str) -> str:
    return (text or "").replace(" ", "")


def _has_emergency_keyword(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(keyword in normalized for keyword in EMERGENCY_KEYWORDS)


def _rule_based(payload: dict) -> dict:
    authorized = payload.get("authorized", False)
    stt_text = payload.get("stt_text", "") or ""
    dwell = payload.get("dwell_seconds", 0)
    sound = payload.get("sound_event", {})
    person = sound.get("person_detected", False)
    danger = sound.get("danger_sound_detected", False)
    abnormal = sound.get("abnormal_sound_detected", False)
    label = sound.get("label", "")
    raw_label = sound.get("raw_label", "")

    if authorized:
        return {
            "situation": 0, "situation_name": "이상없음", "risk_level": "low",
            "reason": "허가된 사용자", "action": "감지 비활성",
            "tts_key": "NONE", "send_to_control_room": False, "emergency_candidate": False,
        }

    normalized = _normalize_text(stt_text)
    emergency_text = _has_emergency_keyword(stt_text)
    clear_non_emergency_speech = bool(normalized) and not emergency_text

    if emergency_text or (danger and not clear_non_emergency_speech):
        return {
            "situation": 2, "situation_name": "위험 감지", "risk_level": "high",
            "reason": "위험 후보음 또는 응급 키워드 감지", "action": "긴급 알림 전송 및 대피 안내",
            "tts_key": "EMERGENCY_GUIDE", "send_to_control_room": True, "emergency_candidate": True,
        }

    person_signal = (
        person
        or raw_label in INTRUSION_CANDIDATE_LABELS
        or bool(stt_text)
        or (abnormal and raw_label not in DANGER_CANDIDATE_LABELS)
        or (danger and clear_non_emergency_speech)
        or label in {"footstep", "speech", "말소리", "기타 이상 소리"}
    )
    if person_signal:
        # settings.intrusion_warn_1_seconds 이상 체류 시 2차 경고
        # (실제 에스컬레이션 타이밍은 app의 warn1_issued 플래그가 최종 결정)
        if dwell >= settings.intrusion_warn_1_seconds:
            return {
                "situation": 1, "situation_name": "무단침입", "risk_level": "medium",
                "reason": "1차 경고 이후 추가 소리 감지", "action": "2차 경고 방송 및 상황실 전송",
                "tts_key": "INTRUSION_WARN_2", "send_to_control_room": True, "emergency_candidate": False,
            }

        return {
            "situation": 1, "situation_name": "무단침입", "risk_level": "low",
            "reason": "사람 신호 또는 이상 소리 감지", "action": "1차 경고 방송",
            "tts_key": "INTRUSION_WARN_1", "send_to_control_room": True, "emergency_candidate": False,
        }

    return {
        "situation": 0, "situation_name": "이상없음", "risk_level": "low",
        "reason": "위험 조건 미충족", "action": "감시 지속",
        "tts_key": "NONE", "send_to_control_room": False, "emergency_candidate": False,
    }


def _ask_gpt(payload: dict) -> dict | None:
    if client is None:
        print("[WARN] OPENAI_API_KEY 미설정. 룰 기반으로 판단합니다.")
        return None

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
    stt_text = payload.get("stt_text", "") or ""
    sound = payload.get("sound_event", {})
    clear_non_emergency_speech = bool(_normalize_text(stt_text)) and not _has_emergency_keyword(stt_text)
    raw_label = sound.get("raw_label", "")
    acoustic_emergency_candidate = sound.get("acoustic_emergency_candidate", False) or raw_label in DANGER_CANDIDATE_LABELS

    if payload.get("authorized") or rule["situation"] in {0, 2}:
        final, source = rule, "rule (fast-path)"
    else:
        gpt_payload = {**payload, "rule_based_result": rule}
        gpt = _ask_gpt(gpt_payload)

        if gpt:
            if rule["situation"] == 2 and gpt.get("situation", 0) == 0:
                final, source = rule, "rule (safety override)"
            # 2차 경고를 GPT가 1차 경고로 다운그레이드하지 못하게 방지
            elif rule.get("tts_key") == "INTRUSION_WARN_2" and gpt.get("tts_key") == "INTRUSION_WARN_1":
                final, source = rule, "rule (warn2 guard)"
            elif clear_non_emergency_speech and acoustic_emergency_candidate and gpt.get("situation", 0) == 2:
                final, source = rule, "rule (speech override)"
            else:
                final, source = gpt, "gpt"
        else:
            final, source = rule, "rule (gpt fallback)"

    # situation=2인데 tts_key가 없거나 침입 경고 키면 EMERGENCY_GUIDE로 보정
    if int(final.get("situation", 0)) == 2 and str(final.get("tts_key", "")) != "EMERGENCY_GUIDE":
        final = {**final, "tts_key": "EMERGENCY_GUIDE", "send_to_control_room": True, "emergency_candidate": True}
        source += " (emergency tts fix)"

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


class GPTDecisionEngine:
    def decide(self, sound_event, stt_text: str, dwell_seconds: float, authorized: bool) -> DecisionResult:
        raw_label = getattr(sound_event, "raw_label", "")
        is_intrusion_candidate = raw_label in INTRUSION_CANDIDATE_LABELS
        is_danger_candidate = raw_label in DANGER_CANDIDATE_LABELS
        clear_non_emergency_speech = bool(_normalize_text(stt_text)) and not _has_emergency_keyword(stt_text)
        
        if is_danger_candidate and clear_non_emergency_speech:
            sound_event.situation = 1
            sound_event.label = "침입 신호"
        payload = {
            "sound_event": {
                "label": sound_event.label,
                "person_detected": sound_event.situation == 1 or is_intrusion_candidate,
                "abnormal_sound_detected": sound_event.situation == 2 or is_danger_candidate,
                "danger_sound_detected": is_danger_candidate and not clear_non_emergency_speech,
                "acoustic_emergency_candidate": is_danger_candidate,
                "raw_label": raw_label,
                "confidence": sound_event.confidence,
            },
            "stt_text": stt_text,
            "dwell_seconds": dwell_seconds,
            "authorized": authorized,
        }

        return decide(payload)
