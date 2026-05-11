# SoundGuard — 음향 기반 위험 예방·구조 시스템

마이크로 수집한 오디오를 AI로 실시간 분석해 무단침입·응급 상황을 감지하고, 경고 방송 송출 및 관제 대시보드에 상황을 전달하는 시스템입니다.

---

## 주요 기능

- **실시간 음향 분류** — Microsoft BEATs 모델로 배경음 / 사람 목소리 / 발소리 / 충격음 등 5가지 클래스 분류
- **음성 인식(STT)** — OpenAI Whisper로 음성 내용 텍스트 변환, 응급 키워드 감지
- **AI 상황 판단** — 규칙 기반 + GPT-4o-mini를 결합한 2단계 판단 엔진
- **자동 경고 방송** — 1차 → 2차 경고 에스컬레이션, 응급 시 180초 잠금 후 반복 안내
- **실시간 관제 대시보드** — WebSocket 기반 지도·로그·음향 분석 시각화
- **다중 구역 관제** — 여러 구역을 동시에 모니터링, 구역별 로그·알림 분리

---

## 시스템 구조

```
[Flutter 센서 앱]         [Oracle Cloud 서버]        [관제 대시보드]
 sensor_app/         →        backend/           →     frontend/
                           server.py (FastAPI)
 마이크 녹음                                           실시간 모니터링
 WebSocket 전송    ←→    AI 분석 + 상황 판단    ←→    지도 + 이벤트 로그
 TTS mp3 재생            TTS 생성 + DB 저장            구역 관리
```

### 오디오 처리 흐름

```
Flutter 앱 (마이크 녹음, 5초 단위)
    │  WebSocket /sensor
    ▼
server.py
    ├── BEATs 음향 분류  ─┐ (병렬 실행)
    └── Whisper STT     ─┘
            │
            ▼
    GPT 판단 엔진
    (규칙 기반 우선 → 애매한 경우 GPT 호출)
            │
            ├── 상황 0 : 이상없음
            ├── 상황 1 : 무단침입 → 1차/2차 경고 방송
            └── 상황 2 : 위험감지 → 응급 안내 방송 (180초 잠금)
            │
            ├── TTS URL → Flutter 앱 (스피커 재생)
            ├── 분석 결과 → 대시보드 (실시간 표시)
            └── 오디오 샘플 → Supabase DB/Storage 저장
```

---

## 폴더 구조

```
SoundGuard/
├── backend/               Oracle Cloud 서버 (핵심)
│   ├── server.py          메인 서버 (FastAPI, WebSocket 엔드포인트)
│   ├── app.py             로컬 PC 단독 실행용 앱 (서버 없이 동작)
│   ├── decision.py        GPT 판단 엔진
│   ├── environmental_sound.py  BEATs 음향 분류 모듈
│   ├── stt.py             Whisper STT 모듈
│   ├── tts.py             Edge TTS mp3 생성
│   ├── db.py              DB 모델 (Zone, AudioSample)
│   ├── supabase_audio.py  Supabase Storage 업로드
│   ├── config.py          환경변수 로드 및 설정 관리
│   ├── output.py          이벤트 로거 (app.py 전용)
│   ├── ontology.json      AudioSet 분류 체계 (BEATs 라벨 변환용)
│   ├── requirements.txt   Python 패키지 목록
│   ├── .env.example       환경변수 예시
│   ├── self_check/        시스템 자가진단 모듈
│   ├── BEATs/             Microsoft BEATs 모델 코드
│   └── checkpoints/       AI 모델 가중치 파일 (git 제외)
│
├── frontend/              관제 대시보드 (React + Vite)
│   ├── src/
│   │   ├── App.jsx        대시보드 메인 컴포넌트
│   │   ├── main.jsx       React 진입점
│   │   ├── index.css      기본 CSS 리셋
│   │   └── styles/
│   │       └── dashboard.css  다크/라이트 테마 스타일
│   ├── public/
│   │   ├── map.html       Leaflet 2D 지도
│   │   └── SoundGuardLogo*.png  로고 이미지
│   ├── index.html         Vite HTML 진입점
│   ├── package.json       의존성 정의
│   └── README.md          프론트엔드 상세 설명
│
├── sensor_app/            Flutter 모바일 센서 앱
│   └── lib/main.dart      마이크 녹음 → WebSocket 전송 → TTS 재생
│
├── DEPLOY.md              배포 및 운영 가이드
└── READme.md              프로젝트 설명 (이 파일)
```

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| 서버 | Python, FastAPI, uvicorn, WebSocket |
| AI 음향 분류 | Microsoft BEATs (파인튜닝) |
| 음성 인식 | OpenAI Whisper API |
| 상황 판단 | OpenAI GPT-4o-mini |
| TTS | Microsoft Edge TTS |
| 프론트엔드 | React, Vite, Leaflet.js |
| 모바일 센서 | Flutter, Dart |
| DB | Supabase (PostgreSQL) / SQLite |
| 스토리지 | Supabase Storage |
| 지도 | VWorld WMTS |
| 인프라 | Oracle Cloud (Ubuntu), nginx |

---

## 실행 환경 설정

### 1. 환경변수 설정

`backend/.env.example`을 복사해 `backend/.env` 생성 후 값 입력:

```env
OPENAI_API_KEY=sk-...
VWORLD_KEY=...
DATABASE_URL=postgresql://...
SUPABASE_URL=https://...
SUPABASE_SERVICE_ROLE_KEY=sb_secret_...
ZONE_NAME=위험구역 A
```

### 2. AI 모델 파일 준비

git에 포함되지 않으므로 별도 보관 경로에서 복사:

```
backend/checkpoints/best_beats_fine.pt          (파인튜닝 모델)
backend/checkpoints/BEATs_iter3_plus_...pt      (베이스 모델)
```

### 3. 서버 실행

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

### 4. 프론트엔드 빌드 및 배포

```bash
cd frontend
npm install
npm run build
# 빌드 결과물(dist/)을 nginx /var/www/html/에 배포
```

### 5. Flutter 앱 빌드

```bash
cd sensor_app
flutter build apk --release
```

---

## 배포 구조

자세한 배포 방법 및 서버 운영 명령어는 [DEPLOY.md](DEPLOY.md) 참고.

```
로컬 PC
├── frontend/   →  빌드 후 nginx (Oracle Cloud)
└── backend/    →  scp 후 uvicorn (Oracle Cloud)

Oracle Cloud 서버
├── nginx       →  대시보드 서빙 (port 80)
└── uvicorn     →  FastAPI 서버 (port 8000)

Flutter 앱     →  WebSocket으로 Oracle Cloud 서버 연결
```

---

## 로그인 정보 (데모)

| 항목 | 값 |
|------|-----|
| 관리자 ID | `admin` |
| 비밀번호 | `1234` |
