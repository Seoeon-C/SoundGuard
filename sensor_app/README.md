# SoundGuard 센서 앱 — Flutter

현장 마이크로 오디오를 녹음해 Oracle Cloud 서버로 WebSocket 전송하고, 서버의 분석 결과에 따라 TTS 경고 방송을 재생하는 모바일 센서 앱입니다.

---

## 주요 기능

- **마이크 녹음** — 5초 단위로 오디오 청크 녹음
- **WebSocket 전송** — 서버 `/sensor` 엔드포인트로 실시간 전송
- **최신 청크만 처리** — 밀림 방지를 위해 처리 중 도착한 청크는 최신 것만 유지
- **TTS 재생** — 서버로부터 mp3 URL 수신 시 해당 URL로 바로 스트리밍 재생
- **자동 재연결** — 연결 끊김 시 자동으로 재연결 시도

---

## 통신 흐름

```
앱 시작
  │  WebSocket 연결 + zone_info 전송
  ▼
서버 (/sensor)
  │  오디오 청크 (WAV) 전송 →
  │  ← TTS URL 수신 (침입/응급 발생 시)
  ▼
URL로 mp3 스트리밍 재생 (서버의 /tts/ 경로)
```

---

## 의존 패키지

| 패키지 | 용도 |
|--------|------|
| `record` | 마이크 녹음 |
| `web_socket_channel` | WebSocket 통신 |
| `audioplayers` | TTS mp3 재생 |
| `permission_handler` | 마이크 권한 요청 |
| `path_provider` | 임시 파일 저장 경로 |
| `http` | mp3 파일 다운로드 |

---

## 서버 주소 설정

[lib/main.dart](lib/main.dart) 상단의 `kServerHost` 값을 서버 IP로 변경:

```dart
const kServerHost = "<서버_공인IP>:8000";
```

---

## 실행 및 빌드

```bash
# 의존성 설치
flutter pub get

# 개발/테스트 — 연결된 기기에 디버그 모드로 바로 실행
flutter run

# 배포용 APK 빌드
flutter build apk --release
# 결과물: build/app/outputs/flutter-apk/app-release.apk
```

개발 중에는 `flutter run`, 배포할 때는 `flutter build apk --release`를 사용합니다.

---

## 권한

앱 실행 시 **마이크 권한** 허용이 필요합니다.
