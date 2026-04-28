# Voice / Footstep Gate Patch

## 문제
사람 목소리의 음절, 파열음, 마찰음도 짧은 peak를 여러 번 만들 수 있어서 기존 발소리 감지기가 목소리를 발소리로 오인할 수 있었습니다.

## 수정 내용

1. VAD 민감도를 올려 작은 목소리를 먼저 잡도록 조정했습니다.
2. 발소리는 단순 peak 반복만으로 인정하지 않고 아래 조건을 모두 만족해야 합니다.
   - VAD가 목소리로 판단하지 않음
   - voice_score가 `FOOTSTEP_MAX_VOICE_SCORE` 이하
   - active_ratio가 `FOOTSTEP_MAX_ACTIVE_RATIO` 이하
   - 반복 peak 개수가 `FOOTSTEP_MIN_PEAKS` 이상
   - footstep_score가 `FOOTSTEP_SCORE_THRESHOLD` 이상
3. 로그에 `active`, `impulse`, `zcr`를 추가했습니다.

## 새 로그 해석

```text
[SIGNAL] rms=..., peak=..., voice_score=..., footstep_score=..., active=..., impulse=..., zcr=..., peaks=..., reason=...
```

- `active`: 소리가 지속적으로 난 비율입니다. 목소리는 보통 높고, 발소리는 보통 낮습니다.
- `impulse`: RMS 대비 peak 비율입니다. 발소리/충격음은 보통 높습니다.
- `zcr`: zero crossing rate입니다. 목소리 후보 판단에 보조로 씁니다.

## 튜닝

목소리가 아직 발소리로 잡히면 `.env`에서 아래 값을 더 낮추거나 올립니다.

```env
FOOTSTEP_MAX_ACTIVE_RATIO=0.20
FOOTSTEP_MAX_VOICE_SCORE=0.30
FOOTSTEP_MIN_PEAKS=3
```

발소리가 너무 안 잡히면 아래처럼 조금 완화합니다.

```env
FOOTSTEP_MAX_ACTIVE_RATIO=0.35
FOOTSTEP_MAX_VOICE_SCORE=0.45
FOOTSTEP_MIN_PEAKS=2
```
