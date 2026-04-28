# SoundGuard backend 코드 전체 설명서

이 문서는 업로드된 `backend.zip`의 Python 백엔드 코드를 기준으로, 프로젝트의 목적·전체 실행 흐름·파일별 역할·핵심 클래스/함수·현재 코드에서 주의할 점을 정리한 설명서입니다.

---

## 1. 프로젝트 한 줄 요약

이 백엔드는 마이크로 주변 소리를 일정 시간마다 녹음하고, BEATs 모델로 환경음을 1차 분류한 뒤, 필요한 경우 Whisper STT와 GPT 판단을 거쳐 위험구역의 `이상없음`, `무단침입`, `위험 감지` 상황을 판정하는 시스템입니다.

즉, 구조는 다음과 같습니다.

```text
마이크 입력
  ↓
5초 단위 녹음
  ↓
BEATs 환경음 분류
  ↓
자연음 / 말소리 / 발소리 / 위험음 / unknown 판정
  ↓
말소리 또는 unknown speech 후보면 Whisper STT 실행
  ↓
룰 기반 판단 + 필요 시 GPT 판단
  ↓
TTS 경고 방송
  ↓
로컬 로그 저장 및 상황실 Webhook 전송
```

---

## 2. 전체 폴더 구조

```text
backend/
├─ main.py                    # 프로그램 진입점, 전체 실행 루프
├─ config.py                  # .env 기반 설정값 관리
├─ environmental_sound.py     # BEATs 기반 환경음 분류기
├─ stt.py                     # OpenAI Whisper STT 처리
├─ decision.py                # 룰 기반 + GPT 상황 판단
├─ output.py                  # TTS 재생, 이벤트 로그 저장, Webhook 전송
├─ requirements.txt           # 필요한 Python 패키지 목록
├─ README.md                  # 현재 버전 핵심 변경 설명
│
├─ assets/tts/                # 고정 경고 음성 mp3 파일 저장 위치
│  ├─ INTRUSION_WARN_1.mp3
│  └─ INTRUSION_WARN_2.mp3
│
├─ beats/                     # BEATs 모델 원본 코드
│  ├─ BEATs.py
│  ├─ backbone.py
│  ├─ modules.py
│  ├─ quantizer.py
│  └─ Tokenizers.py
│
├─ beats_runtime/             # BEATs 실행/테스트용 코드
│  ├─ beats.py
│  ├─ beats_realtime.py
│  ├─ beats_label_check.py
│  ├─ down_ontology.py
│  ├─ record_audio.py
│  ├─ ontology.json
│  └─ input/test.wav
│
└─ tts_to_mp3/
   ├─ tts.py                  # Edge TTS로 mp3 경고음 생성
   └─ read.md
```

---

## 3. 실행 흐름 요약

실제 실행의 중심은 `main.py`의 `SoundGuardApp.run()`입니다.

```text
SoundGuardApp 생성
  ├─ BeatsEnvironmentClassifier 생성
  ├─ WhisperAPI 생성
  ├─ GPTDecisionEngine 생성
  ├─ FixedMessageSpeaker 생성
  ├─ EventLoggerAndMessenger 생성
  ├─ AuthorizationManager 생성
  └─ DwellTimeTracker 생성

run() 시작
  ├─ 관리자 입력 스레드 시작
  └─ 무한 반복
      ├─ 일시정지 상태인지 확인
      ├─ 마이크에서 chunk_seconds초 녹음
      ├─ outputs/temp/latest.wav 저장
      ├─ BEATs로 소리 분류
      ├─ speech 또는 unknown speech 후보면 STT 실행
      ├─ 체류시간 계산
      ├─ decision.py에서 상황 판단
      ├─ 필요 시 TTS 경고 재생
      └─ 필요 시 로그 저장/Webhook 전송
```

---

## 4. `config.py` 설명

`config.py`는 전체 시스템 설정을 한 곳에서 관리합니다. `.env` 파일을 읽고, 값이 없으면 기본값을 사용합니다.

### 핵심 설정값

| 설정 | 의미 | 기본값 |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API 키 | 빈 문자열 |
| `OPENAI_STT_MODEL` | STT 모델 | `whisper-1` |
| `OPENAI_LLM_MODEL` | GPT 판단 모델 | `gpt-4o-mini` |
| `BEATS_PY_DIR` | BEATs 코드 폴더 | `beats` |
| `BEATS_CHECKPOINT_PATH` | BEATs 체크포인트 경로 | `checkpoints/BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt` |
| `DEVICE` | 모델 실행 장치 | `cpu` |
| `SAMPLE_RATE` | 오디오 샘플레이트 | `16000` |
| `CHUNK_SECONDS` | 한 번 녹음하는 길이 | `5` |
| `MIN_RMS_FOR_STT` | STT 실행 최소 평균 음량 | `0.004` |
| `MIN_PEAK_FOR_STT` | STT 실행 최소 최대 음량 | `0.030` |
| `ALLOW_UNKNOWN_STT` | unknown도 음량 충분하면 STT할지 여부 | `true` |
| `ZONE_NAME` | 위험구역 이름 | `위험구역 A` |
| `LOCATION_TEXT` | 위치 설명 | `폐공사장 A구역 입구` |
| `CONTROL_ROOM_WEBHOOK` | 상황실 Webhook URL | 빈 문자열 |
| `AUTH_PASSWORD` | 관리자 일시정지 비밀번호 | `1234` |
| `INTRUSION_WARN_1_SECONDS` | 1차 경고 기준 | `5` |
| `INTRUSION_WARN_2_SECONDS` | 2차 경고 기준 | `15` |

### 중요한 포인트

`env_bool()` 함수는 `.env`의 문자열 값을 Boolean으로 바꿉니다.

```python
ALLOW_UNKNOWN_STT=true
```

처럼 설정하면 Python에서는 `True`로 처리됩니다.

---

## 5. `main.py` 설명

`main.py`는 실제 프로그램을 실행하는 중심 파일입니다.

### 5.1 `AuthorizationManager`

관리자가 콘솔에서 `p`를 입력하고 비밀번호를 입력하면 감지를 일시정지하거나 재개할 수 있습니다.

```text
p 입력 → 비밀번호 입력 → 성공 시 RUNNING / PAUSED 전환
```

이전 방식처럼 사람이 감지될 때마다 비밀번호를 묻는 구조가 아니라, 별도 관리자 입력 스레드가 계속 콘솔 입력을 기다리는 구조입니다.

주의할 점은 `input()`을 별도 스레드에서 계속 기다리기 때문에, 프로그램 종료 시 Windows 환경에서 `Ctrl+C`와 충돌하여 `forrtl: error (200)` 같은 메시지가 뜰 수 있습니다. 이 오류는 보통 Intel/Fortran 기반 라이브러리나 오디오/수치 연산 라이브러리가 Ctrl+C 이벤트를 받으면서 발생하는 종료 메시지입니다. 핵심 로직 오류라기보다는 종료 처리 방식 문제에 가깝습니다.

### 5.2 `DwellTimeTracker`

사람이 위험구역에 얼마나 머문 것으로 볼지 계산합니다.

사람 존재로 보는 조건은 다음입니다.

```python
sound_event.is_footstep
sound_event.is_speech
sound_event.is_unknown_speech_candidate
bool(stt_text)
```

위 조건 중 하나라도 만족하면 `person_detected_since`를 기준으로 체류시간을 누적합니다.

자연음이거나 의미 없는 unknown이면 체류시간을 초기화합니다.

### 5.3 `SoundGuardApp`

전체 시스템을 묶는 클래스입니다.

생성자에서 다음 객체를 초기화합니다.

```python
self.env_classifier = BeatsEnvironmentClassifier()
self.stt = WhisperAPI()
self.decision_engine = GPTDecisionEngine()
self.speaker = FixedMessageSpeaker()
self.logger = EventLoggerAndMessenger()
self.auth = AuthorizationManager()
self.dwell_tracker = DwellTimeTracker()
```

### 5.4 `run()` 실행 루프

핵심 루프는 다음 순서입니다.

1. 일시정지 상태인지 확인
2. 마이크에서 `CHUNK_SECONDS`초 녹음
3. `outputs/temp/latest.wav`로 저장
4. BEATs로 환경음 분류
5. 말소리 또는 speech 후보면 STT 실행
6. 체류시간 업데이트
7. 상황 판단
8. TTS 경고 재생
9. 이벤트 로그 저장 및 Webhook 전송

---

## 6. `environmental_sound.py` 설명

이 파일은 BEATs 모델을 사용해서 오디오를 1차 분류합니다.

### 6.1 `SoundEvent`

환경음 분류 결과를 담는 데이터 클래스입니다.

```python
@dataclass
class SoundEvent:
    label: str
    confidence: float
    raw_label: str
    rms: float = 0.0
    peak: float = 0.0
```

각 필드의 의미는 다음과 같습니다.

| 필드 | 의미 |
|---|---|
| `label` | 시스템 내부에서 쓰는 정제된 라벨 |
| `confidence` | 모델 예측 신뢰도 |
| `raw_label` | BEATs 원본 라벨 |
| `rms` | 오디오 평균 음량 |
| `peak` | 오디오 최대 음량 |

정제된 라벨은 다음 중 하나입니다.

```text
nature
speech
footstep
emergency_sound
unknown
```

### 6.2 `is_unknown_speech_candidate`

현재 코드에서 중요한 속성입니다.

```python
return (
    self.label == "unknown"
    and settings.allow_unknown_stt
    and (self.rms >= settings.min_rms_for_stt or self.peak >= settings.min_peak_for_stt)
)
```

BEATs가 `unknown`으로 분류했더라도, 음량이 충분하면 말소리일 가능성이 있다고 보고 Whisper STT로 넘깁니다.

이 로직 때문에 `아파요`, `도와주세요` 같은 짧은 말이 BEATs에서 speech로 안 잡혀도 STT 기회를 얻을 수 있습니다.

### 6.3 `BeatsEnvironmentClassifier`

BEATs 모델을 로드하고 오디오를 분류하는 클래스입니다.

주요 메서드는 다음입니다.

| 메서드 | 역할 |
|---|---|
| `__init__()` | 모델 로드 준비 |
| `_load_beats()` | BEATs.py와 체크포인트를 직접 로드 |
| `classify(audio, sr)` | 오디오를 받아 최종 `SoundEvent` 반환 |
| `_prepare_audio(audio, sr)` | 모노 변환, 리샘플링, 정규화 |
| `_map_to_refined_label(...)` | BEATs 원본 라벨을 내부 라벨로 변환 |
| `_fallback_classify(...)` | 모델 로드 실패 시 음량 기반 fallback 분류 |

### 6.4 분류 로직

BEATs가 내놓은 원본 라벨 문자열에 특정 키워드가 포함되어 있는지 보고 내부 라벨로 변환합니다.

예시는 다음과 같습니다.

```text
Speech, Human voice, Conversation → speech
Footsteps, Walking, Running → footstep
Scream, Bang, Crash, Glass, Gunshot → emergency_sound
Wind, Rain, Bird, Water, Ambient → nature
그 외 → unknown
```

---

## 7. `stt.py` 설명

이 파일은 OpenAI Whisper API로 음성을 텍스트로 변환합니다.

### 7.1 `WhisperAPI`

```python
self.client = OpenAI(api_key=settings.openai_api_key)
self.model = settings.openai_stt_model
```

API 키와 STT 모델명을 설정값에서 가져옵니다.

### 7.2 `should_transcribe()`

STT를 실행할 만큼 소리가 충분한지 검사합니다.

```python
if rms < settings.min_rms_for_stt and peak < settings.min_peak_for_stt:
    return False
```

즉, RMS와 Peak가 둘 다 기준 미만이면 STT를 생략합니다.

### 7.3 `transcribe()`

저장된 wav 파일을 OpenAI STT API에 보내고 텍스트를 받습니다.

```python
result = self.client.audio.transcriptions.create(
    model=self.model,
    file=audio_file,
    language=language,
    temperature=0,
)
```

기본 언어는 한국어(`ko`)입니다.

### 7.4 `_clean_transcript()`

Whisper가 무음이나 잡음에서 자주 만드는 자막형 환각 문구를 제거합니다.

제거 대상 예시는 다음입니다.

```text
시청해주셔서 감사합니다
구독해주세요
좋아요와 구독
다음 영상에서 만나요
감사합니다
```

단, `아파`, `도와`, `살려`, `119`, `다쳤`, `갇혔` 같은 응급 키워드는 짧아도 제거하지 않습니다.

따라서 이전에 보였던 `[STT] 시청해주셔서 감사합니다.` 문제를 줄이기 위해 이미 필터가 들어가 있습니다. 다만 완전히 방지하려면 STT 실행 전 음량 기준과 무음 판단을 더 강화해야 합니다.

---

## 8. `decision.py` 설명

이 파일은 최종 상황 판단을 담당합니다.

판단 결과는 `DecisionResult`로 반환됩니다.

```python
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
    raw_gpt: str = ""
```

### 8.1 상황 코드

| situation | 의미 |
|---:|---|
| `0` | 이상없음 |
| `1` | 무단침입 |
| `2` | 위험 감지 |

### 8.2 판단 방식

판단은 2단계입니다.

```text
1차: 룰 기반 판단
2차: 애매한 경우 GPT 판단
```

단, 강한 규칙에 해당하면 GPT를 호출하지 않고 바로 결과를 반환합니다.

### 8.3 강한 규칙

다음은 강한 규칙으로 처리됩니다.

```text
nature → 이상없음
footstep → 무단침입
emergency_sound → 위험 감지
응급 키워드 포함 STT → 위험 감지
speech인데 STT 없음 → 이상없음
unknown인데 STT 없음 → 이상없음
```

### 8.4 룰 기반 판단

`_rule_based_decision()`에서 실제 판단이 이루어집니다.

#### 자연음

```python
if sound_event.label == "nature":
    return self._normal("자연/배경 소리로 판단하여 pass")
```

#### 발소리

```python
if sound_event.label == "footstep":
    return self._intrusion(dwell_seconds, "발소리 감지로 무단침입 판단")
```

#### 위험음

```python
if sound_event.label == "emergency_sound":
    return self._emergency("비명/충격음/파손음 등 위험음 감지")
```

#### 말소리 또는 unknown + STT

STT 텍스트에서 응급 키워드가 나오면 위험 감지입니다.

```text
아파, 도와, 살려, 119, 구조, 불났, 쓰러, 다쳤, 피, 갇혔, 위험, 사고, 넘어졌
```

침입/탐색 키워드가 나오면 무단침입입니다.

```text
들어가, 가보자, 몰래, 넘어가, 열어, 문열, 누구없, 안에, 들어왔, 사람있, 뭐야, 여기
```

키워드가 없어도 사람 음성 텍스트가 있으면 무단침입으로 봅니다.

### 8.5 TTS 키

판단 결과에 따라 다음 TTS 키가 반환됩니다.

| 키 | 의미 |
|---|---|
| `NONE` | 음성 출력 없음 |
| `INTRUSION_WARN_1` | 1차 무단침입 경고 |
| `INTRUSION_WARN_2` | 2차 무단침입 경고 |
| `EMERGENCY_GUIDE` | 응급 안내 |

---

## 9. `output.py` 설명

이 파일은 결과를 외부로 출력하는 역할입니다.

### 9.1 `FIXED_TTS_MESSAGES`

TTS 키별 문구를 정의합니다.

```python
"INTRUSION_WARN_1": "출입이 허가되지 않은 위험 구역입니다..."
"INTRUSION_WARN_2": "위험 구역에 계속 머무르고 있습니다..."
"EMERGENCY_GUIDE": "응급 상황이 감지되었습니다..."
```

### 9.2 `FixedMessageSpeaker`

`assets/tts` 폴더에 있는 mp3 파일을 재생합니다.

```text
tts_key = INTRUSION_WARN_1
→ assets/tts/INTRUSION_WARN_1.mp3 재생
```

주의할 점은 `FIXED_TTS_MESSAGES`에 `EMERGENCY_GUIDE` 문구는 있지만, 현재 zip 안의 `assets/tts`에는 `INTRUSION_WARN_1.mp3`, `INTRUSION_WARN_2.mp3`만 있습니다. 따라서 위험 감지 시 `EMERGENCY_GUIDE.mp3`가 없으면 콘솔에 `음성 파일 없음`이 출력될 수 있습니다.

### 9.3 `EventLoggerAndMessenger`

상황이 발생하면 JSON 형태의 이벤트를 만듭니다.

저장 위치는 다음과 같습니다.

```text
outputs/logs/events_YYYYMMDD.jsonl
```

각 줄마다 하나의 이벤트 JSON이 저장되는 JSONL 방식입니다.

`CONTROL_ROOM_WEBHOOK`이 설정되어 있으면 `requests.post()`로 상황실 서버에 전송합니다. 설정이 비어 있으면 로컬 로그만 저장합니다.

---

## 10. `beats_runtime/beats.py` 설명

이 파일은 BEATs 모델을 파일 기반으로 테스트하기 위한 코드입니다.

### 역할

1. BEATs 체크포인트 로드
2. `ontology.json`으로 AudioSet 라벨 ID를 실제 이름으로 변환
3. wav 파일 로드
4. BEATs 예측 실행
5. Top 3 라벨 출력
6. 최종 3분류로 변환

### 최종 3분류

```python
RESULT_LABELS = {
    0: "정상상황",
    1: "말소리",
    2: "기타 이상 소리"
}
```

이 파일은 현재 `main.py`의 실시간 운영 로직과는 조금 다른 테스트용 코드에 가깝습니다. 실제 운영에서는 `environmental_sound.py`의 `BeatsEnvironmentClassifier`가 더 중요합니다.

---

## 11. `beats_runtime/beats_realtime.py` 설명

이 파일은 독립형 실시간 BEATs 테스트 코드입니다.

`main.py`와 별도로, 마이크 소리를 짧게 감시하다가 소리가 일정 기준 이상이면 녹음하고 BEATs로 분류하는 구조입니다.

주요 설정은 다음입니다.

```python
SOUND_THRESHOLD = 0.015
RECORD_SECONDS = 3
CHECK_SECONDS = 0.5
```

현재 메인 실행 파일이라기보다는 BEATs 성능 테스트 및 라벨 확인용으로 보는 것이 맞습니다.

---

## 12. `beats_runtime/down_ontology.py`

AudioSet ontology 파일을 다운로드합니다.

```text
https://raw.githubusercontent.com/audioset/ontology/master/ontology.json
```

다운로드된 파일은 `ontology.json`으로 저장됩니다.

---

## 13. `beats_runtime/beats_label_check.py`

BEATs 체크포인트 안의 라벨 인덱스와 AudioSet 라벨 이름을 확인하는 디버그용 파일입니다.

모델이 어떤 라벨을 출력할 수 있는지 확인할 때 사용합니다.

---

## 14. `beats_runtime/record_audio.py`

마이크에서 5초 녹음한 뒤 `./input/test.wav`로 저장하는 간단한 테스트 도구입니다.

---

## 15. `tts_to_mp3/tts.py` 설명

Edge TTS를 사용해서 경고 문구를 mp3로 생성하고 재생하는 도구입니다.

현재 설정은 다음입니다.

```python
VOICE = "ko-KR-InJoonNeural"
SPEED = "+20%"
```

실행하면 장소명과 1차/2차 경고 문구를 입력받고 다음 파일을 생성합니다.

```text
male_warning_status1.mp3
male_warning_status2.mp3
```

단, 현재 메인 시스템은 `assets/tts/INTRUSION_WARN_1.mp3`, `assets/tts/INTRUSION_WARN_2.mp3`, `assets/tts/EMERGENCY_GUIDE.mp3` 같은 파일명을 기대합니다. 따라서 생성 후 파일명을 맞춰서 옮겨야 합니다.

---

## 16. 현재 코드의 핵심 장점

### 16.1 BEATs + STT + GPT 조합 구조

소리 자체는 BEATs로 보고, 말의 내용은 Whisper로 보고, 최종 판단은 룰과 GPT를 섞는 구조입니다.

이 구조는 단순 소리 분류보다 확장성이 좋습니다.

### 16.2 unknown speech 후보 처리

짧은 음성이나 애매한 사람 소리가 BEATs에서 `unknown`으로 나와도, 음량이 충분하면 STT로 넘기는 보완 로직이 들어가 있습니다.

이전의 `아파요` 같은 짧은 위급 표현 누락 문제를 줄이려는 방향입니다.

### 16.3 자막형 STT 환각 필터

Whisper가 무음에서 `시청해주셔서 감사합니다` 같은 문장을 만드는 문제를 필터링하려는 코드가 들어가 있습니다.

### 16.4 관리자 일시정지 기능

위험구역 점검자나 관리자 진입 시 콘솔에서 감지를 일시정지할 수 있습니다.

---

## 17. 현재 코드에서 주의해야 할 문제점

### 17.1 `BeatsEnvironmentClassifier.__init__()`의 모델 로드 위치 문제

현재 `environmental_sound.py`의 생성자에는 다음 코드가 있습니다.

```python
self.model, self.label_dict = load_model(settings.beats_checkpoint_path)
try:
    self._load_beats()
    self.ready = True
except Exception as exc:
    ...
```

문제는 `load_model()`이 `try` 밖에 있다는 점입니다. 체크포인트 파일이 없거나 로드에 실패하면 fallback으로 넘어가지 못하고 프로그램이 바로 중단될 수 있습니다.

개선하려면 `load_model()` 호출도 `try` 안으로 넣거나, 중복 로드를 제거하는 것이 좋습니다.

### 17.2 BEATs 모델을 두 번 로드할 가능성

`environmental_sound.py`는 `beats_runtime.beats.load_model()`을 한 번 호출하고, 다시 `_load_beats()`에서 직접 체크포인트를 로드합니다.

즉, 현재 구조상 모델 로드가 중복될 가능성이 있습니다.

개선 방향은 하나입니다.

```text
운영용은 _load_beats() 하나로 통일
또는 beats_runtime.beats.load_model() 하나로 통일
```

### 17.3 `self.labels = checkpoint.get("label_names", [])` 문제

BEATs 체크포인트에 `label_names`가 없으면 `self.labels`가 빈 리스트가 됩니다.

그러면 원본 라벨이 다음처럼 나올 수 있습니다.

```text
class_0
class_1
class_2
```

이 경우 `_map_to_refined_label()`이 `speech`, `footstep`, `nature` 같은 실제 의미를 알 수 없어서 대부분 `unknown`이 될 수 있습니다.

이미 `beats_runtime/beats.py`에는 `label_dict`와 `ontology.json`을 이용해 AudioSet ID를 이름으로 바꾸는 코드가 있습니다. 운영용 `environmental_sound.py`에도 이 방식을 반영하는 것이 좋습니다.

### 17.4 `EMERGENCY_GUIDE.mp3` 없음

위험 감지 시 `tts_key`는 `EMERGENCY_GUIDE`가 되지만, 현재 zip의 `assets/tts`에는 해당 mp3가 없습니다.

필요 파일은 다음입니다.

```text
assets/tts/EMERGENCY_GUIDE.mp3
```

없으면 위험 감지 상황에서 안내 방송이 재생되지 않습니다.

### 17.5 `Ctrl+C` 종료 메시지

Windows에서 다음 메시지가 보일 수 있습니다.

```text
forrtl: error (200): program aborting due to control-C event
```

이는 보통 Python 로직 예외라기보다, 오디오/수치연산 라이브러리 내부에서 Ctrl+C 이벤트를 받으면서 출력하는 종료 메시지입니다.

완화하려면 관리자 입력 스레드, pygame mixer, sounddevice stream을 종료 시 명시적으로 정리하는 구조로 바꾸는 것이 좋습니다.

### 17.6 STT 환각 필터는 완전하지 않음

현재 `시청해주셔서 감사합니다`는 필터링하지만, Whisper가 다른 형태의 환각 문구를 만들면 통과될 수 있습니다.

예를 들어 다음 같은 문구도 추가 필터 대상이 될 수 있습니다.

```text
자막 제공
끝까지 시청해주셔서 감사합니다
구독과 좋아요 부탁드립니다
```

또한 가장 좋은 방법은 STT 후 필터만이 아니라 STT 전 단계에서 무음/잡음 판단을 더 엄격하게 하는 것입니다.

---

## 18. 추천 개선 방향

### 18.1 BEATs 라벨 변환 개선

현재 운영용 `environmental_sound.py`는 `label_names`가 없을 때 라벨 이름을 제대로 못 얻을 수 있습니다.

추천 구조는 다음입니다.

```text
checkpoint["label_dict"]로 index → AudioSet ID 변환
ontology.json으로 AudioSet ID → 실제 라벨명 변환
실제 라벨명을 _map_to_refined_label()에 전달
```

### 18.2 모델 로드 중복 제거

`environmental_sound.py`에서 BEATs 모델 로드 방식을 하나로 통일하는 것이 좋습니다.

### 18.3 TTS 파일명 통일

현재 메인 시스템이 기대하는 파일명은 다음입니다.

```text
INTRUSION_WARN_1.mp3
INTRUSION_WARN_2.mp3
EMERGENCY_GUIDE.mp3
```

`tts_to_mp3/tts.py`가 생성하는 이름도 이와 맞추면 관리가 편합니다.

### 18.4 종료 처리 개선

`SoundGuardApp.run()`의 `except KeyboardInterrupt`에서 다음 처리를 추가하면 안정성이 좋아집니다.

```text
pygame.mixer.music.stop()
pygame.mixer.quit()
sounddevice 관련 스트림 정리
관리자 입력 스레드 종료 플래그 처리
```

### 18.5 로그에 원본 오디오 파일 경로 저장

현재 로그에는 소리 분류 결과와 STT 텍스트는 저장되지만, 해당 이벤트의 실제 wav 파일은 별도로 보존되지 않습니다.

분석/시연/디버깅을 위해서는 이벤트 발생 시점의 wav 파일을 다음처럼 저장하는 것이 좋습니다.

```text
outputs/events/audio_YYYYMMDD_HHMMSS.wav
```

---

## 19. 발표나 포트폴리오용 설명 문장

이 프로젝트는 위험구역 내 소리를 실시간으로 감지하여 사람의 접근, 발소리, 구조 요청, 충격음 등을 분류하고, 상황에 따라 경고 방송과 상황실 알림을 수행하는 음향 기반 안전 모니터링 백엔드 시스템입니다. BEATs 기반 환경음 분류, Whisper 기반 음성 인식, GPT 기반 상황 판단을 결합하여 단순 소음 감지가 아니라 실제 위험 상황 여부를 판단하도록 설계되었습니다.

---

## 20. 핵심 실행 명령 예시

가상환경 생성 후 패키지를 설치합니다.

```bash
pip install -r requirements.txt
```

`.env` 파일 예시는 다음과 같습니다.

```env
OPENAI_API_KEY=본인_API_KEY
OPENAI_STT_MODEL=whisper-1
OPENAI_LLM_MODEL=gpt-4o-mini

BEATS_PY_DIR=beats
BEATS_CHECKPOINT_PATH=checkpoints/BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt
DEVICE=cpu
SAMPLE_RATE=16000
CHUNK_SECONDS=5

MIN_RMS_FOR_STT=0.004
MIN_PEAK_FOR_STT=0.030
ALLOW_UNKNOWN_STT=true

ZONE_NAME=위험구역 A
LOCATION_TEXT=폐공사장 A구역 입구
LATITUDE=37.000000
LONGITUDE=127.000000

AUTH_PASSWORD=1234
CONTROL_ROOM_WEBHOOK=

INTRUSION_WARN_1_SECONDS=5
INTRUSION_WARN_2_SECONDS=15
```

실행은 다음입니다.

```bash
python main.py
```

실행 중 관리자 일시정지는 다음입니다.

```text
p 입력 → Enter → 비밀번호 입력
```

종료는 다음입니다.

```text
Ctrl + C
```

---

## 21. 최종 정리

현재 백엔드는 다음 역할을 수행합니다.

```text
1. 마이크 녹음
2. BEATs 환경음 분류
3. speech/unknown 후보에 대한 Whisper STT
4. 룰 기반 + GPT 기반 상황 판단
5. TTS 경고 방송
6. 로그 저장
7. 상황실 Webhook 전송
8. 관리자 일시정지/재개
```

코드 구조 자체는 프로젝트 시연용으로 충분히 이해하기 좋은 형태입니다. 다만 실제 안정적인 동작을 위해서는 BEATs 라벨 매핑, 모델 로드 중복, 응급 TTS 파일 누락, 종료 처리, STT 환각 방지 부분을 추가로 정리하는 것이 좋습니다.
