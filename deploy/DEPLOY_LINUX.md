# 리눅스 서버 자동 실행 가이드

서버가 꺼지거나 재부팅돼도 **자동으로 다시 켜지게** 설정한다 (systemd).

---

## 1. 최초 설정

```bash
# 코드 받기
git clone https://github.com/suitable8111/zombie_days.git
cd zombie_days
git checkout multi

# 실행 스크립트 권한
chmod +x run_server.sh

# (테스트) 한 번 직접 실행해보기 — 가상환경/의존성 자동 설치됨
./run_server.sh
#   http://0.0.0.0:8000 뜨면 Ctrl+C 로 종료
```

> 포트는 기본 **8000**. ngrok도 `8000`으로 맞춰야 한다.

---

## 2. systemd 등록 (부팅 자동시작 + 크래시 자동재시작)

### (1) 게임 서버

`deploy/zombiedays-server.service` 파일에서 **User / WorkingDirectory / ExecStart 경로**를
본인 환경에 맞게 수정한다. (예: 계정이 `ubuntu`, 경로가 `/home/ubuntu/zombie_days`)

```bash
sudo cp deploy/zombiedays-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zombiedays-server

# 상태/로그 확인
systemctl status zombiedays-server
journalctl -u zombiedays-server -f
```

이제 서버가 죽으면 3초 뒤 자동 재시작, 재부팅하면 자동 시작된다.

### (2) ngrok 터널 (선택 — 같이 자동화)

먼저 ngrok 설치 + 인증:
```bash
ngrok config add-authtoken <당신의_토큰>
which ngrok                      # 경로 확인 (예: /usr/local/bin/ngrok)
```

`deploy/zombiedays-ngrok.service` 에서 **ngrok 경로 / 고정 도메인 / User** 수정 후:
```bash
sudo cp deploy/zombiedays-ngrok.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zombiedays-ngrok
journalctl -u zombiedays-ngrok -f
```

> 고정 도메인(`favorable-glutinous-droop.ngrok-free.dev`)을 쓰면 재시작해도 주소가
> 안 바뀌어서 클라이언트 재빌드가 필요 없다.

---

## 3. 자주 쓰는 명령

```bash
# 서버 재시작 / 정지 / 시작
sudo systemctl restart zombiedays-server
sudo systemctl stop    zombiedays-server
sudo systemctl start   zombiedays-server

# 코드 업데이트 후 재시작
cd zombie_days && git pull origin multi
sudo systemctl restart zombiedays-server

# 접속 로그 보기
tail -f connections.log

# 서버 살아있나 확인
curl http://localhost:8000/health          # {"ok":true,"count":N}
```

---

## 4. systemd 없이 간단히 (tmux)

systemd 설정이 부담되면 tmux로 상시 실행만 해도 된다 (단, 재부팅 자동시작은 안 됨):

```bash
tmux new -s game
./run_server.sh
# Ctrl+B 누른 뒤 D 로 빠져나오기 (서버는 계속 실행)

# 다시 보기:  tmux attach -t game
```

---

## 5. 트러블슈팅

| 증상 | 해결 |
|------|------|
| ngrok `ERR_NGROK_8012` | ngrok 포트 ≠ 서버 포트. 둘 다 8000 으로 통일 |
| `Address already in use` | `ss -tlnp \| grep 8000` 로 기존 프로세스 확인 후 종료 |
| 정원 초과로 접속 거부 | 유령 세션 누적 → `sudo systemctl restart zombiedays-server` |
| 권한 오류 | `chmod +x run_server.sh`, 서비스의 User 확인 |
