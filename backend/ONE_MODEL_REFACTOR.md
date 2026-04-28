# BEATs 단일 모델 통합 리팩터링 설명

## 수정 목적

기존 `environmental_sound.py`는 BEATs 체크포인트를 두 번 로드하는 구조였습니다.

1. `beats_runtime.beats.load_model()` 호출
2. `_load_beats()` 내부에서 `BEATs.py`를 직접 import한 뒤 같은 체크포인트 재로드

이 구조는 `self.model`이 중간에 덮어써질 수 있고, 메모리 사용량과 초기 로딩 시간이 증가합니다. 그래서 BEATs 모델은 하나만 로드하고, 그 모델의 출력 라벨을 프로젝트 내부 라벨로 변환하는 방식으로 통합했습니다.

## 변경된 핵심 구조

```text
마이크 입력
  ↓
BeatsEnvironmentClassifier.classify()
  ↓
BEATs 단일 모델 예측
  ↓
Top-K AudioSet 라벨 추출
  ↓
프로젝트 내부 라벨로 변환
  ↓
nature / speech / footstep / emergency_sound / unknown
  ↓
STT / 체류시간 / 판단 엔진 / TTS / 로그 전송
```

## 수정 파일

### 1. `environmental_sound.py`

핵심 변경 사항:

- `_load_beats()` 제거
- `importlib.util`, `sys`, `Path` 기반 직접 로드 제거
- `beats_runtime.beats.load_model()`만 사용
- `load_audioset_ontology()`를 사용해 AudioSet ID를 사람이 읽을 수 있는 라벨명으로 변환
- `softmax` 대신 `sigmoid` 사용
- Top 5 예측 결과를 `SoundEvent.top_labels`에 저장
- Top-K 라벨 전체를 보고 `nature`, `speech`, `footstep`, `emergency_sound`, `unknown`으로 매핑

### 2. `main.py`

핵심 변경 사항:

- 사용하지 않는 `load_model`, `load_audio` import 제거
- BEATs 로그에 Top 3 예측 라벨을 같이 출력

예시 출력:

```text
[BEATs] label=speech, conf=0.842, raw=Speech, rms=0.01342, peak=0.22130 | top=Speech:0.842, Conversation:0.531, Inside small room:0.242
```

## 왜 sigmoid를 사용하는가?

AudioSet 기반 BEATs fine-tuned 모델은 보통 하나의 소리만 고르는 단일 분류가 아니라, 한 오디오 안에 여러 소리 라벨이 동시에 존재할 수 있는 multi-label 분류 구조입니다.

따라서 클래스 전체 합이 1이 되는 `softmax`보다, 각 라벨별 존재 가능성을 독립적으로 계산하는 `sigmoid`가 더 적합합니다.

## 현재 분류 기준

### `nature`

바람, 비, 물소리, 새소리, 곤충, 배경음, 정적, 환경 잡음 등입니다.

### `speech`

Speech, Conversation, Human voice, Male speech, Female speech, Whispering 등입니다.

### `footstep`

Footsteps, Walking, Running, Stomp, Shuffle 등입니다.

### `emergency_sound`

Scream, Crying, Shout, Crash, Bang, Explosion, Glass, Shatter, Gunshot, Alarm, Siren 등입니다.

### `unknown`

위 키워드에 확실히 들어가지 않는 소리입니다. 단, 음량 기준을 넘으면 `unknown_speech_candidate`로 보고 Whisper STT에 넘길 수 있습니다.

## 주의할 점

1. `BEATS_CHECKPOINT_PATH`는 AudioSet fine-tuned 체크포인트를 가리켜야 합니다.
2. `beats_runtime/ontology.json`이 있어야 라벨 ID를 영어 라벨명으로 바꿀 수 있습니다.
3. 실제 커스텀 학습 모델의 라벨 체계가 AudioSet이 아니라면 `label_dict`/ontology 처리 방식을 바꿔야 합니다.
4. `emergency_keywords`, `speech_keywords`, `nature_keywords`, `footstep_keywords`는 테스트하면서 계속 보정하는 것이 좋습니다.
5. 비명, 울음, 고함은 사람 음성이기도 하지만 프로젝트 목적상 위험음 우선순위가 높기 때문에 `emergency_sound`를 먼저 판정합니다.

## 실행

기존과 동일하게 실행합니다.

```bash
python main.py
```

또는 uvicorn/FastAPI 구조로 연결했다면 기존 실행 방식을 그대로 사용하면 됩니다.

## 추천 다음 단계

정확도를 더 높이려면 다음 순서로 개선하는 것이 좋습니다.

1. 실제 환경에서 `top_labels` 로그를 수집한다.
2. 오탐이 많은 라벨을 확인한다.
3. 키워드 매핑 목록을 보정한다.
4. 그래도 부족하면 위험음/정상음 데이터셋으로 BEATs를 fine-tuning한다.
