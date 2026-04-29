# BEATs 전이학습 전처리 및 학습 설계 보고서

## 1. 프로젝트 판단 흐름

본 프로젝트는 위험구역에서 수집된 소리를 분석하여 이벤트 여부와 대응 단계를 판단한다.

```text
배경/백색소음 -> 이벤트 없음
발소리/사람소리 -> 침입 후보, 1차 경고
사람 존재가 지속됨 -> 신고 또는 관제 전송
비명/도움 요청/응급 음성 -> 즉시 신고
충격음/큰 위험음 -> 위험 후보로 판단
```

따라서 BEATs 전이학습의 목적은 데이터셋 원본 이름을 맞히는 것이 아니라, 실제 서비스 판단에 필요한 소리 유형을 안정적으로 구분하는 것이다.

## 2. 초기 데이터 확인 결과

데이터 위치:

```text
C:\Users\Chan\Desktop\test\dataset
```

확인 결과:

```text
전체 파일 수: 572,236개
WAV 파일 수: 289,333개
JSON 라벨 파일 수: 280,009개
전체 WAV 용량: 약 716GiB
전체 오디오 길이: 약 1,568시간
```

데이터셋 구성:

```text
Emergency_Voice_Sound
Extreme_Noise_Environment Sound
Ground Truth
Living_noise
```

주요 문제:

- sample rate가 44.1kHz, 48kHz, 96kHz, 16kHz로 섞여 있음
- mono/stereo/3ch가 섞여 있음
- 오디오 길이가 1초 미만부터 60초 이상까지 다양함
- 클래스별 파일 수 불균형이 큼

## 3. 트러블슈팅 1: 전체 변환을 먼저 하지 않은 이유

처음에는 모든 WAV를 16kHz mono로 변환하는 방법도 고려했다. 그러나 계산 결과 전체 변환 시 예상 용량이 약 168GiB, 일반 GB 기준 약 181GB로 추정되었다.

현재 남은 디스크 용량이 약 170GB 수준이었기 때문에 전체 변환은 실패 가능성이 높았다. 또한 변환 과정에서 임시 파일, 재시도 파일, 학습 결과 checkpoint까지 고려하면 저장공간이 안전하지 않았다.

따라서 먼저 원본 WAV는 유지하고, WAV 헤더만 읽어 manifest를 만드는 방식으로 전처리했다.

## 4. 전처리 1단계: 메타데이터 manifest 생성

생성 파일:

```text
C:\Users\Chan\Desktop\test\pre_processing\outputs\audio_manifest.csv
C:\Users\Chan\Desktop\test\pre_processing\outputs\dataset_summary.json
C:\Users\Chan\Desktop\test\pre_processing\outputs\class_counts.csv
C:\Users\Chan\Desktop\test\pre_processing\outputs\errors.csv
```

처리 결과:

```text
처리 WAV 수: 289,333개
읽기 오류: 0개
걸린 시간: 약 27분 27초
manifest 크기: 약 115MB
```

이 단계에서는 원본 오디오를 디코딩하거나 변환하지 않고, sample rate, 채널 수, bit depth, 길이, frame 수, 파일 크기만 추출했다.

## 5. 트러블슈팅 2: 클래스 불균형 문제

초기 라벨 분포는 다음과 같이 불균형이 컸다.

```text
help_voice: 98,311
loud_noise: 78,422
danger_voice: 52,518
background: 48,020
impact_noise: 4,905
background_noise: 2,819
human_sound: 2,414
footstep: 1,924
```

이 상태로 학습하면 많은 클래스인 help_voice, loud_noise 중심으로 편향되고, 실제 프로젝트에서 중요한 footstep, human_sound 감지 성능이 낮아질 위험이 있다.

따라서 전체 manifest를 그대로 학습에 사용하지 않고, 학습용 균형 manifest를 추가로 생성했다.

## 6. 트러블슈팅 3: 8클래스 대신 5클래스로 재정의한 이유

초기에는 다음 8개 라벨을 사용했다.

```text
background
background_noise
danger_voice
footstep
help_voice
human_sound
impact_noise
loud_noise
```

그러나 이 구분은 데이터셋 분석에는 유용하지만, 실제 서비스 판단 흐름과 완전히 일치하지 않는다. 예를 들어 danger_voice와 help_voice는 둘 다 즉시 신고 계열이며, footstep과 human_sound는 모두 침입 후보로 처리된다.

그래서 최종 학습 라벨을 프로젝트 판단 기준 5클래스로 다시 묶었다.

```text
background   : 이벤트 없음
intrusion    : 발소리/사람소리, 경고 후 지속 시 신고
emergency    : 비명/고통/도움요청/응급 음성, 즉시 신고
impact_noise : 충격음 후보
loud_noise   : 큰 환경소음 hard negative
```

이렇게 바꾼 이유는 모델의 목표를 "데이터셋 원본 분류"가 아니라 "현장 대응 판단에 필요한 분류"로 맞추기 위해서다.

## 7. 전처리 2단계: 프로젝트 기준 manifest 생성

생성 파일:

```text
C:\Users\Chan\Desktop\test\pre_processing\outputs\project_task\project_train_balanced_manifest.csv
C:\Users\Chan\Desktop\test\pre_processing\outputs\project_task\project_val_balanced_manifest.csv
C:\Users\Chan\Desktop\test\pre_processing\outputs\project_task\project_val_full_manifest.csv
C:\Users\Chan\Desktop\test\pre_processing\outputs\project_task\project_summary.json
```

학습용 분포:

```text
총 train 수: 50,000개
background: 10,000
intrusion: 10,000
emergency: 10,000
impact_noise: 10,000
loud_noise: 10,000
```

검증용은 두 종류로 만들었다.

```text
project_val_balanced_manifest.csv
- 클래스별 성능 비교용
- 총 4,013개

project_val_full_manifest.csv
- 실제 validation 전체 분포 평가용
- 총 29,413개
```

balanced val과 full val을 분리한 이유는, 모델이 클래스별로 고르게 잘 맞히는지와 실제 데이터 분포에서 오탐/미탐이 어떤지 모두 확인하기 위해서다.

## 8. 오버샘플링 처리

intrusion과 impact_noise는 원본 수가 부족하여 일부 오버샘플링이 필요했다.

```text
intrusion 원본 train: 3,857 -> 10,000
impact_noise 원본 train: 4,373 -> 10,000
총 oversampled row: 11,770개
```

오버샘플링 행은 manifest에 다음 필드로 표시했다.

```text
is_oversampled=True
augmentation_policy=random_crop_gain_noise
```

학습 코드에서는 이 표시를 보고 random crop, gain, noise augmentation을 적용하도록 설계했다.

## 9. 학습 코드 설계

학습 코드 위치:

```text
C:\Users\Chan\Desktop\a\transfer_learning\train_beats_project.py
```

학습 시점 전처리:

```text
원본 WAV 로드
mono 변환
16kHz resample
5초 crop/pad
BEATs 입력
```

전체 16kHz 변환 파일을 미리 만들지 않은 대신, 학습 DataLoader에서 on-the-fly로 처리한다. 이 방식은 디스크 용량을 절약하고, random crop augmentation을 적용하기 쉽다.

## 10. BEATs 모델 연결 방식

기존 BEATs checkpoint는 backbone으로 사용하고, 기존 predictor head는 제거한다. 그 위에 프로젝트 5클래스 classifier head를 새로 붙인다.

```text
BEATs backbone -> mean pooling -> LayerNorm -> Dropout -> Linear(5)
```

초기 epoch에서는 backbone을 freeze하고 classifier head 중심으로 학습한다. 이후 backbone을 unfreeze하여 전체 모델을 미세조정한다.

기본 설정:

```text
epochs: 10
batch size: 16
num workers: 6
sample rate: 16kHz
clip length: 5초
freeze backbone epochs: 2
mixed precision: 사용
```

## 11. 남은 시간 예측 기능

학습 로그에는 다음 형식의 진행률과 ETA가 표시된다.

```text
[train] epoch=1/10 step=50/3125 loss=... acc=... epoch_time=... eta=...
```

ETA는 전체 학습 step 기준 남은 시간을 추정한다.

## 12. 기대 효과

이번 변경으로 기대되는 효과는 다음과 같다.

- 프로젝트 판단 흐름과 학습 라벨이 일치함
- 발소리/사람소리 침입 후보 recall 개선 가능
- 비명/도움요청/응급 음성을 즉시 신고 계열로 통합하여 안정성 향상
- 큰 환경소음을 hard negative로 사용하여 배경 소음 오탐 감소 기대
- full validation을 따로 평가하여 실제 분포에서의 성능 확인 가능

## 13. 향후 보완점

- 실제 현장 녹음 데이터로 별도 테스트셋 구성
- intrusion 데이터 추가 수집
- impact_noise 데이터 추가 수집
- STT와 결합하여 "살려주세요", "도와주세요", "119" 키워드 즉시 신고 룰 구현
- 모델 출력 확률 threshold를 조정하여 오탐/미탐 균형 최적화
- FastAPI MVP의 `audio_analyzer.py`에 BEATs 추론 모듈 연결

## 14. 결론

초기 데이터는 규모가 크지만 형식, 길이, 라벨 수, 클래스 분포가 섞여 있어 그대로 학습하기에는 위험이 있었다. 따라서 먼저 전체 metadata manifest를 만들고, 이후 프로젝트 판단 흐름에 맞는 5클래스 균형 manifest를 생성했다.

이 구조는 단순한 실험용 분류가 아니라 실제 서비스 판단 로직과 연결되는 전이학습 설계다. 이제 BEATs backbone을 기반으로 5클래스 전이학습을 수행하고, balanced validation과 full validation을 함께 사용하여 성능을 평가할 수 있다.
