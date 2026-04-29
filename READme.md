# SoundGuard

SoundGuard는 소리를 기반으로 위험 구역의 무단침입과 응급상황을 감지하는 프로젝트입니다.

마이크로 5초 단위 음성을 수집한 뒤, 프로젝트 데이터로 전이학습한 BEATs 모델이 환경음을 5개 클래스로 분류합니다. 이후 Whisper STT와 상황 판단 로직을 함께 사용해 배경음, 침입 가능성, 긴급 구조 요청을 구분합니다.

## 최종 처리 흐름

```text
소리 수집
-> 16kHz mono 입력
-> BEATs 전이학습 모델 분류
-> background이면 이벤트 없음
-> intrusion이면 1차 경고 후 지속 감지 시 상황실 전송
-> emergency이면 즉시 긴급 알림
-> 필요 시 Whisper STT로 구조 요청 문장 확인
```

## 주요 폴더

```text
main.py             루트 실행 파일
backend/            최종 실행 코드
pre_processing/     학습 manifest 생성 및 데이터 전처리 코드
transfer_learning/  BEATs 전이학습 코드, 보고서, 성능 비교 그래프 생성 코드
GPT_tuning/         GPT 판단 방식 실험 코드
```

## 실행 방법

```powershell
cd C:\Users\Chan\Desktop\a
C:\Users\Chan\anaconda3\envs\firstaid-gpu\python.exe main.py
```

처음 받는 팀원은 `backend\.env.example`을 참고해 `backend\.env`를 만들고 API 키를 입력해야 합니다.

## 모델 파일

전이학습 모델과 원본 BEATs 체크포인트는 용량이 커서 git에 올리지 않습니다.

필요한 로컬 위치:

```text
backend/checkpoints/best_beats_project.pt
backend/checkpoints/BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt
```

팀원에게는 위 두 파일을 별도로 전달하거나 Git LFS/클라우드 링크를 사용하세요.

## 전이학습 클래스

```text
background
intrusion
emergency
impact_noise
loud_noise
```

최종 성능은 `transfer_learning/BEATs_전이학습_전처리_보고서.md`와 바탕화면의 `BEATs 성능지표 그래프` 자료를 참고하면 됩니다.
