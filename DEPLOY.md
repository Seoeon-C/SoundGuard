# SoundGuard 배포 및 운영 가이드

## 전체 구조

```
Flutter 센서 앱 (마이크 녹음)
    │  WebSocket ws://<서버_공인IP>:8000
    ▼
Oracle Cloud 서버 (<서버_공인IP>)
    │  nginx → 프론트엔드 서빙 (port 80)
    │  uvicorn → FastAPI 서버 (port 8000)
    ▼
브라우저 http://<서버_공인IP>
(팀원 대시보드 모니터링)
```

---

## 0. 사전 준비 — 변수 정의

| 변수 | 설명 | 확인 방법 |
|------|------|----------|
| `<서버_공인IP>` | Oracle Cloud 서버 IP | Oracle 콘솔 → Instance → Public IP |
| `<SSH_키_경로>` | Oracle SSH 키 파일 경로 | 키 발급 시 저장한 경로 |
| `<VWorld_API_키>` | VWorld 지도 API 키 | https://www.vworld.kr |

---

## 1. 서버 SSH 접속

```powershell
ssh -i <SSH_키_경로> ubuntu@<서버_공인IP>
```

---

## 2. Oracle Cloud 서버 최초 셋업

> 이미 완료된 상태라면 건너뜀. 새 서버로 교체할 때만 다시 진행.

### 2-1. 패키지 설치 및 디렉토리 생성

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y nginx

sudo mkdir -p /var/www/html
sudo chown -R ubuntu:ubuntu /var/www/html
```

### 2-2. nginx 설정

```bash
sudo tee /etc/nginx/sites-available/default << 'EOF'
server {
    listen 80;
    root /var/www/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx
```

### 2-3. 방화벽 설정

**Oracle 콘솔 (웹브라우저):**
```
Networking → VCN → Subnet → Default Security List
→ Add Ingress Rules
  Source CIDR: 0.0.0.0/0 / Protocol: TCP / Destination Port: 80
```

**서버 내부:**
```bash
sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo netfilter-persistent save
```

---

## 3. 백엔드 파일 업로드

### 단일 파일 업로드

```powershell
scp -i <SSH_키_경로> backend\server.py ubuntu@<서버_공인IP>:~/backend/
```

### 폴더 전체 업로드

```powershell
scp -i <SSH_키_경로> -r backend\* ubuntu@<서버_공인IP>:~/backend/
```

> `checkpoints/`, `.env`, `venv/`는 git에 없으므로 별도 관리 필요.

---

## 4. 프론트엔드 빌드 및 업로드

### 4-1. 환경변수 설정

`frontend/.env.production`:
```
VITE_BACKEND_IP=<서버_공인IP>:8000
VITE_VWORLD_KEY=<VWorld_API_키>
```

### 4-2. 빌드 및 업로드

```powershell
cd frontend
npm install
npm run build
cd ..

scp -i <SSH_키_경로> frontend\dist\index.html ubuntu@<서버_공인IP>:/var/www/html/
scp -i <SSH_키_경로> frontend\dist\assets\* ubuntu@<서버_공인IP>:/var/www/html/assets/
scp -i <SSH_키_경로> frontend\dist\map.html ubuntu@<서버_공인IP>:/var/www/html/
scp -i <SSH_키_경로> frontend\dist\*.png ubuntu@<서버_공인IP>:/var/www/html/
```

### 4-3. 서버 권한 설정 (assets 폴더가 새로 생겼을 때만)

```bash
sudo chown -R ubuntu:ubuntu /var/www/html
chmod 755 /var/www/html/assets
```

---

## 5. 백엔드 서비스 관리

```bash
sudo systemctl start soundguard    # 시작
sudo systemctl stop soundguard     # 중지
sudo systemctl restart soundguard  # 재시작 (파일 업로드 후 반드시 실행)
sudo systemctl status soundguard   # 상태 확인
```

---

## 6. 로그 확인

```bash
# 실시간 로그 (Ctrl+C로 종료)
sudo journalctl -u soundguard -f

# 최근 50줄
sudo journalctl -u soundguard -n 50 --no-pager

# 오늘 로그만
sudo journalctl -u soundguard --since today --no-pager

# 에러 로그만
sudo journalctl -u soundguard -p err --no-pager

# 키워드 필터
sudo journalctl -u soundguard --no-pager | grep "STT"
sudo journalctl -u soundguard --no-pager | grep "무단침입"
```

---

## 7. 서버 파일 확인

```bash
# TTS mp3 파일
ls -lh ~/backend/assets/tts/

# 수신된 오디오 파일
ls -lh ~/backend/received/

# 수신된 오디오 파일 삭제
rm ~/backend/received/*

# 구역 DB
ls -lh ~/backend/zones.db

# 디스크 / 메모리 사용량
df -h
free -h
```

---

## 8. 팀원 로컬 개발 (Vite dev server)

```bash
# 프론트엔드 실행
cd frontend
npm install
npm run dev
```

`frontend/.env`:
```
VITE_BACKEND_IP=localhost:8000      # 로컬 서버 사용 시
# VITE_BACKEND_IP=<서버_공인IP>:8000  # Oracle 서버 직접 연결 시
```

---

## 9. 수정 후 업데이트 방법

| 수정한 파일 | 해야 할 작업 |
|------------|------------|
| `backend/server.py` 등 Python 파일 | scp 업로드 → `systemctl restart soundguard` |
| `frontend/src/App.jsx` 등 React 파일 | 빌드 → scp 업로드 |
| `frontend/public/map.html` | scp 업로드 (빌드 불필요) |
| `frontend/.env.production` | 빌드 → scp 업로드 |

---

## 10. 접속 정보 요약

| 항목 | 값 |
|------|-----|
| 대시보드 URL | `http://<서버_공인IP>` |
| 로그인 ID | `admin` |
| 로그인 PW | (팀 내부 공유) |
| 백엔드 포트 | `8000` |
| SSH 유저 | `ubuntu` |

---

## 11. 트러블슈팅

### 대시보드 접속이 안 될 때
```bash
sudo systemctl status nginx
sudo systemctl restart nginx
sudo iptables -L INPUT -n | grep 80
```

### WebSocket 연결 실패 시
1. `systemctl status soundguard`로 서버 실행 중인지 확인
2. `.env.production`의 IP가 현재 서버 IP와 일치하는지 확인

### assets 권한 오류 시
```bash
sudo chown -R ubuntu:ubuntu /var/www/html
chmod 755 /var/www/html/assets
```

### 서버 시작 실패 시 (모델 로드 오류)
```bash
# 모델 파일 존재 확인
ls -lh ~/backend/checkpoints/
# .env 파일 확인
cat ~/backend/.env
```
