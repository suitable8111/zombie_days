# Zombie Days — 멀티플레이 가이드 (Phase 12)

자체 서버 IP 기반 실시간 멀티플레이. itch.io(웹) / 데스크톱 양쪽에서
플레이어 위치·차량 탑승·생존일수를 20Hz로 동기화한다.

```
┌──────────────┐   update_position (20Hz)   ┌──────────────┐
│  Client A    │ ─────────────────────────▶ │              │
│ (브라우저/PC)│                            │  server.py   │
│              │ ◀───────────────────────── │ (FastAPI +   │
│  remote_     │   update_player(broadcast) │  socketio)   │
│  players{}   │   init_players / leave     │              │
└──────────────┘                            └──────────────┘
                                                   ▲
                            update_player          │
                       ┌───────────────────────────┘
                  ┌──────────────┐
                  │  Client B    │
                  └──────────────┘
```

---

## 1. 서버 실행

### 의존성 설치
```bash
pip install -r requirements-server.txt
# 또는 uv:  uv pip install -r requirements-server.txt
```

### 실행
```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0` : 외부(다른 PC/브라우저)에서 접속 허용
- 정상 동작 확인: 브라우저에서 `http://<서버IP>:8000/health` → `{"ok":true,"count":0}`
- 접속자 수 확인: `http://<서버IP>:8000/`

### 방화벽
서버 PC의 **8000 포트(TCP)** 인바운드를 열어야 외부에서 접속된다.

---

## 2. 클라이언트 서버 주소 설정

`network.py` 상단:
```python
SERVER_URL = "http://localhost:8000"        # 로컬 테스트
# SERVER_URL = "http://203.0.113.7:8000"    # ← 자체 서버 IP 로 교체
MULTIPLAYER_ENABLED = True                   # False = 완전 싱글플레이
```

- **로컬 테스트**: `localhost` 그대로
- **실배포**: 보유한 서버의 공인 IP로 변경
- ⚠ **itch.io(https) 주의**: https 페이지는 보안상 `http/ws` 서버에 접속할 수 없다.
  itch.io 웹 배포로 멀티를 하려면 서버에 **TLS(https/wss)** 가 필요하다
  (예: Caddy/Nginx 리버스 프록시 + Let's Encrypt → `https://도메인` 으로 SERVER_URL 설정).

---

## 3. 로컬 멀티플레이 테스트 (가장 빠름 — 데스크톱 2창)

데스크톱에서는 `python-socketio` 클라이언트가 바로 작동한다.

```bash
# 터미널 1 — 서버
uvicorn server:app --host 0.0.0.0 --port 8000

# 터미널 2 — 플레이어 1
python3 main.py

# 터미널 3 — 플레이어 2
python3 main.py
```

두 창에서 각각 새 게임을 시작하고 같은 지역으로 이동하면
상대 캐릭터(초록 베스트)와 **닉네임 + 생존일수(Dn)** 가 보인다.

> 닉네임은 실행마다 `Player####` 로 자동 생성된다.
> 고정하려면 `network.py` 의 `local_player_name` 을 바꾸거나,
> `main.py` 진입부에서 `_net.local_player_name = "내닉네임"` 으로 설정.

---

## 4. 웹(itch.io) 멀티플레이 테스트

웹 빌드는 `build_web.sh` 가 자동으로 Socket.IO JS 브릿지를 주입한다.

```bash
./build_web.sh
python3 serve_local.py          # http://localhost:8080
```

브라우저 창을 **2개** 띄워 같은 주소(`http://localhost:8080`)로 접속하면
서로의 캐릭터가 동기화된다.

- 웹 클라이언트는 python-socketio 대신 **브라우저 Socket.IO JS**(`WebBridgeTransport`)를 사용한다.
- 브릿지 코드는 `inject_socketio.py` 가 `build/web/index.html` 에 삽입한다.

---

## 5. 동기화되는 데이터

| 항목 | 키 | 설명 |
|------|-----|------|
| 좌표 | `x, y` | 위치 (20Hz, 클라이언트 보간) |
| 조준 | `ax, ay` | 바라보는 방향 |
| 애니메이션 | `wp` | 걷기 페이즈 |
| 체력 | `hp, mhp` | HP 바 표시 |
| 생존일수 | `day` | 닉네임 옆 `Dn` |
| 차량 | `veh, vkind` | 탑승 중 차량 (Phase 12-2에서 차량 렌더링 예정) |
| 은신 | `hidden` | 반투명 표시 |
| 닉네임 | `name` | 머리 위 표시 |

---

## 6. 동작 원리 요약

- **송신**: 메인 루프가 `sync_network_data()` 를 매 프레임 호출 → 내부에서 20Hz로 throttle 해 `update_position` 전송.
- **수신**: `update_player` / `init_players` / `leave_player` 이벤트를 받아
  `remote_players{}` 딕셔너리를 갱신.
- **렌더링**: 원격 플레이어는 청크 스트리밍과 동일하게 **뷰포트 컬링(`_vis`)** 을 거쳐
  화면 안에 들어올 때만 그려진다.
- **오프라인 안전성**: 서버 접속 실패 시 `DummyTransport` 유지 → 게임은 그대로 싱글플레이로 동작.

---

## 7. 트러블슈팅

| 증상 | 원인 / 해결 |
|------|------------|
| 상대가 안 보임 | 서버 IP/포트 확인, 방화벽 8000 포트 개방 |
| `서버 접속 실패` 로그 | 서버 미실행 또는 주소 오타 |
| 웹에서만 안 됨 | itch.io(https) ↔ http 서버 혼합 차단 → 서버 TLS 필요 |
| 캐릭터가 끊겨 보임 | 정상(20Hz). 보간으로 완화돼 있으나 네트워크 지연 시 발생 |
| 접속자 수 확인 | `http://<서버IP>:8000/` |
