# SoundGuard Dashboard — 관제 프론트엔드

음향 기반 위험 감지 시스템의 실시간 관제 대시보드입니다.  
WebSocket으로 백엔드 서버와 연결해 음향 분석 결과·경보·이벤트 로그를 실시간으로 시각화합니다.

---

## 기술 스택

| 항목 | 내용 |
|------|------|
| Framework | React 18 |
| Bundler | Vite |
| 지도 | Leaflet.js + VWorld WMTS 타일 |
| 아이콘 | lucide-react |
| 스타일 | CSS Variables (다크/라이트 테마) |
| 통신 | WebSocket, REST API |

---

## 주요 화면

### 로그인 (`LoginScreen`)
- 관리자 계정 인증 (데모: admin / 1234)

### 안내 멘트 설정 (`ConfigScreen`)
- 1차 경고 · 2차 경고 · 응급 상황별 방송 멘트 입력
- 실시간 미리보기 제공

### 메인 대시보드 (`MainScreen`)
- **좌측 플로팅 패널**: 구역 상태 / 시스템 헬스 / 구역 정보 / 감지 인물 / 이벤트 로그
- **지도 (iframe)**: Leaflet 2D 지도, 구역별 상태 마커 실시간 업데이트 (postMessage)
- **하단 플로팅 팝업**: 음향 분석 바 차트 / 감지 판단 요약 / CCTV 영상
- **헤더 중앙**: 현재 송출 중인 TTS 안내 메시지 표시

---

## 화면 상태 흐름

```
정상 (situation: 0) → 초록
무단침입 (situation: 1) → 노랑 · 1차/2차 경고 방송
위험감지 (situation: 2) → 빨강 · 응급 안내 방송 (180초 잠금)
```

---

## 환경변수

| 파일 | 용도 |
|------|------|
| `.env` | 로컬 개발용 (`VITE_BACKEND_IP=localhost:8000`) |
| `.env.production` | 배포용 (`VITE_BACKEND_IP=서버IP:8000`) |

`.env.example` 참고해서 `.env` 생성 후 사용.

---

## 로컬 개발 실행

```bash
npm install
npm run dev
```

백엔드 서버(`backend/server.py`)가 실행 중이어야 WebSocket 연결이 됩니다.

---

## 빌드 및 배포

```bash
npm run build
```

`dist/` 폴더를 서버 `/var/www/html/`에 업로드합니다.  
자세한 배포 방법은 루트의 [DEPLOY.md](../DEPLOY.md) 참고.

---

## 주요 파일

| 파일 | 설명 |
|------|------|
| `src/App.jsx` | 전체 UI 컴포넌트 (로그인 · 설정 · 메인 대시보드) |
| `src/styles/dashboard.css` | CSS 변수 기반 다크/라이트 테마, 플로팅 패널 스타일 |
| `public/map.html` | Leaflet 지도 (iframe으로 삽입, postMessage로 상태 수신) |
| `public/SoundGuardLogo.png` | 헤더 로고 (34×34) |
| `public/SoundGuardLogo_0.png` | 로그인 로고 (90×90) |
