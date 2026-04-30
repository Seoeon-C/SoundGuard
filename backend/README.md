# SoundGuard Backend

최종 실행 코드는 이 폴더에 있습니다.

## 실행

```powershell
cd C:\Users\Chan\Desktop\a
C:\Users\Chan\anaconda3\envs\firstaid-gpu\python.exe main.py
```

## 자가진단

```powershell
C:\Users\Chan\anaconda3\envs\firstaid-gpu\python.exe -m backend.self_check
```

자가진단은 스피커에서 테스트 소리를 출력하고 마이크 입력으로 다시 감지되는지 확인합니다.

루트의 `main.py`가 최종 구현인 `backend\app.py`를 실행합니다.

## 주요 파일

```text
../main.py               루트 실행 진입점
app.py                   녹음, BEATs 분류, STT, 상황 판단 전체 흐름
config.py                .env 설정 로드 및 경로 관리
environmental_sound.py   전이학습 BEATs 모델 로드 및 환경음 분류
decision.py              상황 0/1/2 판단 로직
output.py                TTS 재생, 로그 저장, Webhook 전송
stt.py                   Whisper STT 호출 및 STT 후처리
self_check/              실행 환경 자가진단
beats/                   BEATs 모델 코드
ontology.json            원본 BEATs fallback 라벨 정보
.env.example             팀원용 환경변수 예시
```

## 로컬에 따로 필요한 파일

다음 파일은 용량 또는 보안 문제로 git에 올리지 않습니다.

```text
backend/.env
backend/checkpoints/best_beats_project.pt
backend/checkpoints/BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt
backend/outputs/
backend/assets/tts/
```
