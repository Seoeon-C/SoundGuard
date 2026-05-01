# SoundGuard 배포 및 운영 가이드

## 전체 구조

```
현장 PC (마이크 + server.py 실행)
    │
    │  WebSocket ws://<현장PC_공인IP>:8000
    ▼
Oracle Cloud 서버 (<서버_공인IP>)
    │  nginx → 프론트엔드 서빙
    ▼
브라우저 http://<서버_공인IP>
(팀원 대시보드 모니터링)
```

---

## 0. 사전 준비 - 변수 정의

아래 값을 본인 환경에 맞게 확인 후 이후 명령어에서 치환해서 사용하세요.

| 변수 | 설명 | 확인 방법 |
|------|------|----------|
| `<서버_공인IP>` | Oracle Cloud 서버 IP | Oracle 콘솔 → Instance → Public IP |
| `<현장PC_공인IP>` | 현장 PC 공인 IP | https://api.ipify.org |
| `<현장PC_사설IP>` | 현장 PC 사설 IP | `ipconfig` → IPv4 주소 |
| `<SSH_키_경로>` | Oracle SSH 키 파일 경로 | 키 발급 시 저장한 경로 |
| `<공유기_관리_주소>` | 공유기 관리 페이지 URL | 공유기 제조사별 상이 |

---

## 1. Oracle Cloud 서버 최초 셋업

> 이미 완료된 상태라면 건너뜀. 새 서버로 교체할 때만 다시 진행.

### 1-1. SSH 접속

```powershell
ssh -i <SSH_키_경로> ubuntu@<서버_공인IP>
```

### 1-2. 패키지 설치 및 디렉토리 생성

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y nginx

sudo mkdir -p /var/www/html
sudo chown -R ubuntu:ubuntu /var/www/html
```

### 1-3. nginx 설정

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

### 1-4. 방화벽 설정

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

## 2. 프론트엔드 최초 배포

### 2-1. 환경변수 설정

`frontend/.env.production` 파일 생성:
```
VITE_BACKEND_IP=<현장PC_공인IP>:8000
VITE_VWORLD_KEY=<VWorld_API_키>
```

> 공인 IP 확인: https://api.ipify.org

### 2-2. 빌드 및 업로드

```powershell
# 프로젝트 루트에서 실행
cd frontend
npm install
npm run build
cd ..

scp -i <SSH_키_경로> -r frontend\dist\* ubuntu@<서버_공인IP>:/var/www/html/
```

### 2-3. 서버 assets 권한 설정

```bash
# 서버에서 실행
chmod 755 /var/www/html/assets
```

---

## 3. 프론트엔드 수정 후 업데이트

> App.jsx, map.html 등 프론트엔드 파일을 수정했을 때

```powershell
# 1. 빌드
cd frontend
npm run build
cd ..

# 2. 서버 업로드
scp -i <SSH_키_경로> -r frontend\dist\* ubuntu@<서버_공인IP>:/var/www/html/

# 3. 서버에서 권한 확인 (assets 폴더가 새로 생겼을 때만)
# ssh 접속 후:
chmod 755 /var/www/html/assets
```

> 백엔드(server.py, app.py) 수정 시에는 빌드·업로드 불필요. server.py만 재실행하면 됨.

---

## 4. 백엔드 실행 (현장 PC)

```bash
cd backend

# 가상환경 사용 시
venv\Scripts\activate   # Windows

# 실행
py -3.11 server.py  # 파이썬 3.11버전으로 구동
```

### 공유기 포트포워딩 확인

현장 PC에서 외부 접속이 가능하려면 공유기 포트포워딩 필요:
```
공유기 관리 페이지(<공유기_관리_주소>) → 포트포워딩
외부포트: 8000 → 내부IP: <현장PC_사설IP> → 내부포트: 8000 / TCP
```

---

## 5. 팀원 로컬 개발 (Vite)

> 팀원이 `npm run dev`로 프론트엔드를 띄울 때

### 5-1. 환경 준비

```bash
# 백엔드 실행 (본인 PC에서)
cd backend
py -3.11 server.py

# 프론트엔드 실행 (별도 터미널)
cd frontend
npm install
npm run dev
```

### 5-2. 환경변수 (.env)

`frontend/.env` 파일이 이미 로컬 개발용으로 설정되어 있음:
```
VITE_BACKEND_IP=localhost:8000
```

본인 PC가 아닌 현장 PC의 server.py에 연결하고 싶을 때:
```
# frontend/.env 에서 아래 줄 주석 해제 후 IP 변경
VITE_BACKEND_IP=<현장PC_공인IP>:8000
```

---

## 6. 접속 정보 요약

| 항목 | 값 |
|------|-----|
| 대시보드 URL | http://`<서버_공인IP>` |
| 로그인 ID | admin |
| 로그인 PW | (팀 내부 공유) |
| 서버 SSH | `ssh -i <SSH_키_경로> ubuntu@<서버_공인IP>` |
| 백엔드 포트 | 8000 |
| 현장 PC 공인 IP | `<현장PC_공인IP>` |

---

## 7. 수정 시 어떤 파일을 다시 올려야 하나?

| 수정한 파일 | 해야 할 작업 |
|------------|------------|
| `backend/server.py` | 현장 PC에서 server.py 재실행 |
| `backend/app.py` | 현장 PC에서 server.py 재실행 |
| `frontend/src/App.jsx` | 빌드 → scp 업로드 → chmod |
| `frontend/public/map.html` | 빌드 → scp 업로드 |
| `frontend/.env.production` | 빌드 → scp 업로드 |

---

## 8. 트러블슈팅

### 대시보드 접속이 안 될 때
```bash
# 서버에서 nginx 상태 확인
sudo systemctl status nginx

# nginx 재시작
sudo systemctl restart nginx

# iptables 확인
sudo iptables -L INPUT -n | grep 80
```

### WebSocket 연결 실패 시
1. 현장 PC에서 `py -3.11 server.py` 실행 중인지 확인
2. 공유기 포트포워딩 8000 설정 확인
3. `.env.production`의 IP가 현재 공인 IP와 일치하는지 확인
   - 공인 IP 확인: https://api.ipify.org

### assets 권한 오류 시
```bash
chmod 755 /var/www/html/assets
```
