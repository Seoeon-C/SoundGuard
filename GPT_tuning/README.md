# GPT_tuning

GPT API 판단 모듈 개발 과정에서 방식별로 실험하고 정리한 파일 모음입니다.  
BEATs 음향 분류 결과 + Whisper STT 텍스트를 입력받아 상황(0 이상없음 / 1 무단침입 / 2 위험 감지)을 판단합니다.

---

## 파일 설명

### gpt_method1.py
**방식 1 - System Prompt + JSON 구조화 출력**

- GPT에게 역할과 판단 기준을 system prompt로 정의
- `response_format=json_object`로 JSON 출력 강제
- `temperature=0`으로 일관성 확보
- 터미널 실행 시 시나리오 선택 메뉴 제공 (1~4번)
- 장점: 구현 단순, 프롬프트 수정만으로 판단 기준 변경 가능
- 단점: 필드명/타입이 GPT 재량이라 드물게 파싱 오류 발생 가능

---

### gpt_method2.py
**방식 2 - Function Calling (Tool Use)**

- GPT가 반드시 미리 정의된 함수 스키마로만 응답하도록 강제
- `tool_choice="required"`로 함수 호출 필수화
- 터미널 실행 시 시나리오 선택 메뉴 제공 (1~4번)
- 장점: 출력 형식 100% 안정적, 필드명·타입·허용값 모두 보장, JSON 파싱 오류 없음
- 단점: 방식 1보다 코드가 약간 복잡

---

### gpt_method3.py
**방식 3 - Rule-based + Function Calling 통합 (실험용)**

- 방식 1 + 방식 2를 합친 구조
- 1단계: 룰 기반 사전 판단 (API 비용 0, 응답 빠름)
  - authorized=True → 즉시 상황 0 반환
  - 명백한 응급 키워드 감지 → 즉시 상황 2 반환
- 2단계: 애매한 경우만 GPT 호출 (Function Calling)
- 3단계: GPT 실패 시 룰 기반 결과로 자동 폴백
- 터미널 실행 시 Whisper STT 텍스트를 직접 입력하여 반복 테스트 가능 (`q` 입력 시 종료)

---

### decision_v2.py
**최종 모듈 - soundguard_refined_rules_v2에 통합된 버전**

- gpt_method3.py를 실제 프로젝트 구조에 맞게 정리한 모듈
- `SoundEvent`, `settings` 등 프로젝트 내부 객체를 직접 사용
- 테스트 코드 없이 `decide()` 함수만 제공
- `soundguard_refined_rules_v2/main2.py`에서 import하여 사용
- 방식 3과 동일한 로직: Rule fast-path → GPT Function Calling → 룰 폴백

---

## 최종 구동

실제 시스템 실행은 `soundguard_refined_rules_v2/` 폴더의 `main.py`로 합니다.

```bash
cd soundguard_refined_rules_v2
python main.py
```

- `main.py`: `decision_v2.py` (Function Calling 방식) 사용
- `main.py`: `decision.py` (기존 JSON 프롬프트 방식) 사용 — 원본 보존용

---

## 방식 비교 요약

| 파일 | GPT 출력 방식 | 형식 안정성 | 용도 |
|---|---|---|---|
| gpt_method1.py | System Prompt + JSON mode | 보통 | 실험 |
| gpt_method2.py | Function Calling | 높음 | 실험 |
| gpt_method3.py | Rule + Function Calling | 높음 | 실험/테스트 |
| decision_v2.py | Rule + Function Calling | 높음 | **실제 사용** |
