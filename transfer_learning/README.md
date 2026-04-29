# BEATs 전이학습 실행 안내

이 폴더는 프로젝트 판단 흐름 기준 5클래스 BEATs 전이학습 코드입니다.

## 학습 클래스

```text
background   : 이벤트 없음
intrusion    : 발소리/사람소리, 경고 후 지속 시 신고
emergency    : 비명/고통/도움요청/응급 음성, 즉시 신고
impact_noise : 충격음 후보
loud_noise   : 큰 환경소음 hard negative
```

## 사용 manifest

```text
C:\Users\Chan\Desktop\test\pre_processing\outputs\project_task\project_train_balanced_manifest.csv
C:\Users\Chan\Desktop\test\pre_processing\outputs\project_task\project_val_balanced_manifest.csv
C:\Users\Chan\Desktop\test\pre_processing\outputs\project_task\project_val_full_manifest.csv
```

## 실행 전 확인

CUDA PyTorch와 torchaudio가 설치되어 있어야 합니다.

```powershell
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
python -c "import torchaudio; print(torchaudio.__version__)"
```

## 권장 첫 실행

학습 실행은 직접 아래 명령으로 시작하면 됩니다.

```powershell
cd C:\Users\Chan\Desktop\a\transfer_learning
C:\Users\Chan\anaconda3\envs\firstaid-gpu\python.exe -u train_beats_project.py --epochs 10 --batch-size 16 --num-workers 0 --log-every 25
```

4070 Ti 12GB에서 메모리가 부족하면 `--batch-size 8`로 낮추세요.

현재 Codex 실행 환경에서는 Windows 권한 문제로 PyTorch DataLoader의 multiprocessing worker가 막히므로 `--num-workers 0`을 기본값으로 사용합니다. VSCode 터미널에서 `--num-workers 2` 이상이 정상 동작하면 속도를 위해 올려도 됩니다.

## 결과물

기본 출력 폴더:

```text
C:\Users\Chan\Desktop\a\transfer_learning\outputs
```

주요 파일:

- `best_beats_project.pt`: balanced validation macro F1 기준 best checkpoint
- `last_beats_project.pt`: 마지막 epoch checkpoint
- `history.json`: epoch별 train/val 지표
- `run_config.json`: 실행 설정

## 코드가 하는 전처리

학습 시점에 원본 WAV를 읽고 아래 처리를 합니다.

```text
WAV load -> mono 변환 -> 16kHz resample -> 5초 crop/pad -> BEATs 입력
```

원본 데이터는 복사하거나 수정하지 않습니다.

## 남은 시간 예측

학습 로그에 `eta=...`가 표시됩니다. 이 값은 전체 epoch 기준 남은 시간 예측입니다.
