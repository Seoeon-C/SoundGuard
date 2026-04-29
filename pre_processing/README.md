# BEATs 전이학습 데이터 메타데이터 전처리

이 폴더는 전처리 2번 방식, 즉 원본 WAV를 변환하지 않고 메타데이터 manifest를 만드는 용도입니다.

## 하는 일

- `C:\Users\Chan\Desktop\test\dataset` 아래 WAV 파일을 스캔합니다.
- WAV 헤더에서 sample rate, 채널, bit depth, 길이, frame 수를 읽습니다.
- 폴더 구조에서 `source_dataset`, `split`, `source_class`를 추출합니다.
- 프로젝트용 초안 라벨인 `project_label`을 붙입니다.
- 원본 오디오는 복사, 변환, 삭제하지 않습니다.

## 실행

빠른 테스트:

```powershell
python build_manifest.py --limit 1000
```

전체 실행:

```powershell
python build_manifest.py
```

## 결과 파일

결과는 `outputs/`에 저장됩니다.

- `audio_manifest.csv`: 학습 manifest 초안
- `class_counts.csv`: 클래스별 WAV 수
- `dataset_summary.json`: 전체 요약 통계
- `errors.csv`: 읽기 실패 WAV 목록
- `label_map_draft.json`: 프로젝트 라벨 매핑 초안

## 클래스 불균형 보정 manifest 생성

원본 WAV는 그대로 두고, 학습에 사용할 CSV만 균형 있게 다시 만듭니다.

```powershell
python make_balanced_manifest.py
```

기본값:

- train: 클래스별 3,000개
- val: 클래스별 최대 300개
- train에서 부족한 클래스는 중복 행으로 채우고 `is_oversampled=True`로 표시
- val은 평가용이므로 중복 증강하지 않음

결과는 `outputs/balanced/`에 저장됩니다.

- `balanced_train_manifest.csv`
- `balanced_val_manifest.csv`
- `balanced_counts.csv`
- `balanced_summary.json`

## 프로젝트 판단 흐름 기준 5클래스 manifest

우리 시스템의 실제 처리 흐름에 맞춰 라벨을 다시 묶습니다.

- `background`: 이벤트 없음
- `intrusion`: 발소리/사람소리, 1차 경고 후 지속 시 신고
- `emergency`: 비명/고통/도움요청/낙상/붕괴/응급 음성, 즉시 신고
- `impact_noise`: 충격음 후보
- `loud_noise`: 큰 환경소음 hard negative

```powershell
python make_project_task_manifest.py
```

기본값:

- train: 5개 task label 각각 10,000개
- val balanced: 각 label 최대 1,000개, 중복 없음
- val full: 전체 validation을 모두 포함한 실제 분포 평가용

결과는 `outputs/project_task/`에 저장됩니다.

- `project_train_balanced_manifest.csv`
- `project_val_balanced_manifest.csv`
- `project_val_full_manifest.csv`
- `project_counts.csv`
- `project_source_class_counts.csv`
- `project_summary.json`
- `project_label_map.json`

## 주의

이 단계는 16kHz 변환이나 5초 chunk 생성을 하지 않습니다. 남은 디스크 용량이 적을 때도 안전하게 실행할 수 있는 메타데이터 확인 단계입니다.
