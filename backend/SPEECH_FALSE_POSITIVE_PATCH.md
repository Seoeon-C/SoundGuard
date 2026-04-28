# BEATs Speech 오인 및 발소리 미검출 수정

## 문제

로그 예시:

```text
[SIGNAL] rms=0.00036, peak=0.02109, voice_score=0.30, footstep_score=0.20, peaks=0
[BEATs] label=speech, raw=Silence | top=Silence, Music, Speech
[FLOW] BEATs가 말소리 후보 감지 → Whisper STT
[STT] 안녕
```

실제로는 발소리였지만, BEATs의 Top-K에 Speech가 포함되어 Whisper를 호출했고, Whisper가 짧은 잡음에서 환각 문장을 만든 상황입니다.

## 수정 내용

1. Whisper 호출 조건을 VAD 중심으로 고정했습니다.
   - `SignalDetector`가 `voice_detected=True`를 반환한 경우에만 Whisper를 호출합니다.
   - BEATs가 `speech`라고 분류해도 VAD가 목소리를 못 잡았으면 Whisper를 호출하지 않습니다.

2. 발소리 감지를 더 민감하게 바꿨습니다.
   - 기존에는 프레임 RMS만 보아서 작은 발소리를 놓쳤습니다.
   - 이제 프레임 peak envelope도 함께 봅니다.
   - 기본 `FOOTSTEP_MIN_PEAKS`를 2에서 1로 낮췄습니다.

## 권장 .env 튜닝값

발소리가 아직 안 잡히면 아래 값을 더 낮춰보세요.

```env
FOOTSTEP_MIN_PEAKS=1
FOOTSTEP_MIN_PEAK=0.010
FOOTSTEP_FRAME_RMS_THRESHOLD=0.00035
FOOTSTEP_FRAME_PEAK_THRESHOLD=0.008
FOOTSTEP_SCORE_THRESHOLD=0.55
```

오탐이 많으면 반대로 올리세요.

```env
FOOTSTEP_MIN_PEAKS=2
FOOTSTEP_MIN_PEAK=0.018
FOOTSTEP_SCORE_THRESHOLD=0.70
```

## 핵심 원칙

- 작은 목소리 감지: VAD → Whisper
- 발소리 감지: peak/RMS 패턴 → 무단침입
- 폭발/비명/유리파손: BEATs → 위험감지
- BEATs의 Speech 라벨만으로는 Whisper 호출 금지
