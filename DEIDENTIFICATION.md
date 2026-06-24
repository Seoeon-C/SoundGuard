# SoundGuard DB 비식별화 현황

## `zones` (구역 정보 — 실시간 라우팅용 운영 테이블)

| 컬럼 | 상태 | 비고 |
|---|---|---|
| `id` | 평문 | 구역 PK, 실시간 WebSocket 라우팅/TTS 파일명에 쓰여서 암호화 불가 |
| `name` | 평문 | 구역 라벨명(예: "서울역"). `server.py`에서 `Zone.name == ...` 동등 조회를 하기 때문에 암호화하면 매번 다른 암호문이 생겨 조회가 깨짐 → 평문 유지 |
| `label` | 평문 | 산/공사장/저수지/강/논 — 민감정보 아님 |
| `coord` | **암호화** | 정밀 GPS 좌표 — 가장 민감한 위치 정보라 Fernet 암호화 |
| `region_code` | 평문(일반화됨) | `coord`에서 자동 계산된 약 1km 단위 좌표 (예: "37.55° N, 126.97° E") — 대시보드 등에서 정밀 위치 없이도 대략적 표시 가능 |
| `created_at` | 평문 | 타임스탬프, 민감정보 아님 |

## `audio_samples` (분석 결과 저장 — 분석/리뷰용 테이블)

| 컬럼 | 상태 | 비고 |
|---|---|---|
| `audio_id` | 평문 | 단순 UUID PK |
| `zone_name` | **암호화** | 표시용 사본이라 조회 키로 안 쓰여서 암호화 가능했음 |
| `zone_label` | 평문 | 구역 환경 유형(산/공사장/저수지 등) — 위치를 특정하지 못하는 범주값이라 평문 유지, 구역 유형별 모델 재학습 분석에 활용 |
| `sensor_id_hash` | **HMAC 해시** | 원본 zone_id/sensor_id 대신 비밀키 기반 해시만 저장 (역추적 불가) |
| `raw_audio_path` | **암호화** | Supabase Storage 내 오디오 파일 경로 |
| `beats_label` / `beats_raw_label` / `beats_confidence` | 평문 | 분류 결과일 뿐 개인정보 아님 |
| `stt_text` | **암호화** | 음성 인식 원문 — 가장 민감한 데이터라 반드시 암호화 |
| `final_result` / `final_situation` | 평문 | "무단침입" 같은 판단 결과 라벨 |
| `human_label` / `review_status` | 평문 | 사람 검수용 필드, 아직 사용 안 함(`NULL`/`pending`) |
| `model_version` | 평문 | 모델 버전 태그 |
| `is_pseudonymized` | 평문(`1`) | 이 행이 비식별화 적용됐다는 표시 플래그 |
| `retention_until` | 평문 | 생성일 + 90일, 보존기한 — 서버가 하루 1회 자동으로 이 기한 지난 행을 삭제 |
| `created_at` | 평문 | 타임스탬프 |

## `audit_logs` (감사 로그)

| 컬럼 | 상태 | 비고 |
|---|---|---|
| `id` | 평문 | UUID PK |
| `actor` | 평문 | `"system"`(자동 분석 저장) 또는 `"dashboard"`(구역 CRUD) |
| `action` | 평문 | create / update / delete |
| `target_table` / `target_id` | 평문 | 어떤 테이블/행이 변경됐는지 |
| `created_at` | 평문 | 타임스탬프 |

누가(자동 시스템인지 대시보드 조작인지) 언제 어떤 데이터를 만들거나 지웠는지 추적 가능. 감사 로그 자체는 개인정보를 담지 않아서 암호화 불필요.

---

## 한 줄 요약

- **암호화 (Fernet, `FIELD_ENCRYPTION_KEY`)**: 정밀 좌표(`coord`), 음성 원문(`stt_text`), 오디오 파일 경로(`raw_audio_path`), `zone_name`
- **가명화 (HMAC, `SENSOR_ID_HASH_KEY`)**: 디바이스/구역 식별자 → `sensor_id_hash`
- **평문 유지**: 분류 라벨, 타임스탬프, 감사 로그, 그리고 실시간 조회/라우팅에 쓰이는 `Zone.id`/`Zone.name`
- **보존기간**: `audio_samples`는 생성 후 90일이 지나면 서버가 자동으로 삭제 (`db.py`의 `purge_expired_audio_samples`, `server.py`의 `_retention_purge_loop`가 하루 1회 실행)
- **타임스탬프**: 모든 `created_at`/`retention_until`은 한국 시간(KST, UTC+9) 기준으로 저장 (`db.py`의 `now_kst()`)

## 관련 코드

- `backend/db.py` — `EncryptedText` 타입, `hash_sensor_id()`, `generalize_coord()`, `log_audit()`, `purge_expired_audio_samples()`
- `backend/server.py` — `Zone`/`AudioSample` 생성·수정·삭제 지점에서 위 함수들을 호출
- `.env` 필요 값: `FIELD_ENCRYPTION_KEY`, `SENSOR_ID_HASH_KEY` (절대 공유/커밋 금지)
