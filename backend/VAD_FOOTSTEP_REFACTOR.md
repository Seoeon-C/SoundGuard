# SoundGuard 감지 흐름 개선본

## 변경 목적

기존 구조는 BEATs 분류 결과에 많이 의존했기 때문에 다음 문제가 있었다.

- 발소리가 BEATs 라벨에서 잘 잡히지 않으면 무단침입으로 이어지지 않음
- 작은 사람 목소리가 BEATs에서 speech로 분류되지 않으면 Whisper API가 호출되지 않음
- 폭발음/비명/유리 파손음은 BEATs가 담당해야 하지만, unknown으로 나오면 무시될 수 있음

이번 수정본은 BEATs 하나만 믿지 않고 앞단에 가벼운 신호 감지기를 추가했다.

## 새 감지 순서

```text
마이크 입력
  ↓
SignalDetector
  ├─ 사람 목소리 후보 → Whisper API → STT 텍스트 분석
  ├─ 발소리 반복 peak → 무단침입
  └─ 둘 다 아니면 BEATs 분류
        ├─ explosion / scream / glass / siren / bang → 위험 감지
        ├─ nature / background → 이상없음
        └─ unknown + 큰 impulse → 위험음 후보
```

## 추가된 파일

### `audio_detectors.py`

BEATs 앞에서 실행되는 신호 기반 감지기다.

주요 기능:

- `voice_detected`: 작은 사람 목소리 후보 감지
- `footstep_detected`: 발소리처럼 짧은 충격음이 반복되는 패턴 감지
- `loud_impulse_detected`: 폭발음/큰 충격음 같은 매우 큰 impulse 후보 감지

정밀한 딥러닝 모델은 아니고, BEATs와 Whisper 호출을 보완하는 후보 검출기다.

## 수정된 파일

### `main.py`

기존 흐름:

```text
녹음 → BEATs → speech이면 Whisper → decision
```

수정 후 흐름:

```text
녹음 → SignalDetector
       ├─ voice → Whisper → decision
       ├─ footstep → decision
       └─ BEATs → decision
```

### `config.py`

다음 튜닝값이 추가되었다.

```env
VAD_MIN_RMS=0.0025
VAD_MIN_PEAK=0.018
VAD_FRAME_RMS_THRESHOLD=0.0018
VAD_MIN_ACTIVE_RATIO=0.12
VAD_VOICE_SCORE_THRESHOLD=0.55

FOOTSTEP_MIN_PEAKS=2
FOOTSTEP_MIN_PEAK=0.020
FOOTSTEP_FRAME_RMS_THRESHOLD=0.003
FOOTSTEP_SCORE_THRESHOLD=0.65

LOUD_IMPULSE_PEAK_THRESHOLD=0.60
```

발소리가 여전히 안 잡히면 먼저 아래 값을 낮춰본다.

```env
FOOTSTEP_FRAME_RMS_THRESHOLD=0.002
FOOTSTEP_MIN_PEAK=0.012
FOOTSTEP_SCORE_THRESHOLD=0.55
```

작은 목소리가 잘 안 잡히면 아래 값을 낮춘다.

```env
VAD_MIN_RMS=0.0015
VAD_MIN_PEAK=0.010
VAD_FRAME_RMS_THRESHOLD=0.0012
VAD_VOICE_SCORE_THRESHOLD=0.45
```

오탐이 많으면 반대로 값을 올린다.

## 테스트 방법

1. 조용한 상태
   - `[SIGNAL]` 로그의 rms/peak가 낮아야 한다.
   - 최종 decision은 이상없음이어야 한다.

2. 작은 목소리
   - `voice_score`가 올라가야 한다.
   - `[FLOW] VAD가 사람 목소리 후보 감지 → Whisper STT`가 출력되어야 한다.

3. 발소리
   - `footstep_score`와 `peaks`가 올라가야 한다.
   - `[FLOW] 발소리 반복 peak 감지 → 무단침입 로직`이 출력되어야 한다.

4. 폭발음/유리 깨짐/큰 충격음
   - BEATs top 라벨에 `explosion`, `glass`, `crash`, `bang`, `scream`, `siren` 계열이 나오면 위험 감지로 처리된다.
   - BEATs가 unknown으로 놓치더라도 매우 큰 impulse면 보수적으로 위험음으로 처리한다.

## 주의점

전동 마사지기처럼 계속 이어지는 진동음은 발소리나 폭발음이 아니라 일반 기계음일 수 있다. 이 경우에는 위험감지로 처리하지 않는 것이 맞다. 다만 위험구역에서 “큰 비정상 소리도 상황실 전송”으로 처리하고 싶다면 `loud_impulse` 기준을 더 민감하게 조정하거나 별도 `suspicious_noise` 상황을 추가하는 방식이 좋다.
