"""
Zombie Days — 멀티플레이 중계 서버 (Phase 12)
═══════════════════════════════════════════════════════════════════════════════
기술 스택 : Python FastAPI + python-socketio (ASGI, 비동기)
역할      : 접속자 좌표 / 차량 탑승 / 생존일수 를 실시간 중계(broadcast)

실행:
    pip install -r requirements-server.txt
    uvicorn server:app --host 0.0.0.0 --port 8000

  ※ uvicorn 의 진입점 `app` 은 아래에서 socketio.ASGIApp 으로 노출한다.
"""
import time
import socketio
from fastapi import FastAPI

# 서버 가동 시각 — 모든 클라이언트의 게임 시간 기준점 (단조 시계)
SERVER_EPOCH = time.monotonic()

# 동시 접속 최대 인원 (서버 보호). 초과 시 신규 접속 거부.
MAX_PLAYERS = 10

# ── Socket.IO 서버 (CORS 완전 개방: itch.io + localhost 모두 허용) ────────────
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",      # 모든 출처 허용
    ping_interval=20,
    ping_timeout=25,
)

# 헬스체크/상태용 FastAPI 앱 (선택적)
fastapi_app = FastAPI(title="Zombie Days Multiplayer Server")


@fastapi_app.get("/")
async def root():
    return {"status": "ok", "players_online": len(players)}


@fastapi_app.get("/health")
async def health():
    return {"ok": True, "count": len(players)}


# uvicorn 진입점: `uvicorn server:app`
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)


# ── 서버 메모리 상태 ───────────────────────────────────────────────────────────
# sid → 마지막으로 받은 플레이어 상태 dict
players: dict[str, dict] = {}

# 청크 소유권: "cx,cy" → sid (해당 청크의 좀비를 시뮬레이션·중계하는 클라)
chunk_owners: dict[str, str] = {}


# ── 이벤트 핸들러 ──────────────────────────────────────────────────────────────

@sio.event
async def connect(sid, environ, auth=None):
    """신규 접속: 빈 슬롯 생성 + 기존 접속자 목록을 신규 유저에게 전송."""
    # 정원 초과 시 접속 거부 (클라이언트는 ConnectionError 로 받아 싱글 진행)
    if len(players) >= MAX_PLAYERS:
        print(f"[!] 정원 초과 거부: {sid}  ({len(players)}/{MAX_PLAYERS})")
        raise socketio.exceptions.ConnectionRefusedError(
            f"server full ({MAX_PLAYERS} max)")
    players[sid] = {"id": sid}
    # 현재 접속 중인 (나를 제외한) 다른 유저들의 마지막 상태를 신규 유저에게 보냄
    others = [st for other_sid, st in players.items()
              if other_sid != sid and len(st) > 1]   # 좌표가 한 번이라도 들어온 유저만
    await sio.emit("init_players", others, to=sid)
    # 서버 가동 경과 시간(초) → 클라가 동일 시간대(낮/밤) 계산에 사용
    await sio.emit("sync_time", {"elapsed": time.monotonic() - SERVER_EPOCH}, to=sid)
    print(f"[+] connect: {sid}  (online={len(players)})")


@sio.event
async def update_position(sid, data):
    """
    좌표/상태 동기화. 클라이언트가 보낸 데이터를 저장하고,
    나(sid)를 제외한 모든 접속자에게 브로드캐스트한다.
    data 예: {x, y, ax, ay, wp, hp, mhp, day, veh, vkind, hidden, name}
    """
    if not isinstance(data, dict):
        return
    data["id"] = sid                 # 서버가 신뢰하는 식별자로 덮어씀
    players[sid] = data              # 최신 상태 저장
    # 나를 제외한 전원에게 전달
    await sio.emit("update_player", data, skip_sid=sid)


@sio.event
async def hit_player(sid, data):
    """
    PvP 피격. 공격자(sid)가 특정 대상에게 피해를 입혔다고 보고하면,
    서버가 피해 대상에게만 'take_damage' 를 전달한다.
    data: {"target": <피해자 sid>, "dmg": <피해량>, "kx","ky": 넉백 방향}
    """
    if not isinstance(data, dict):
        return
    target = data.get("target")
    if target and target in players:
        payload = {
            "from": sid,
            "dmg":  int(data.get("dmg", 0)),
            "kx":   float(data.get("kx", 0.0)),
            "ky":   float(data.get("ky", 0.0)),
        }
        await sio.emit("take_damage", payload, to=target)


# ── 좀비 공유: 청크 소유권 + 이벤트 중계 ───────────────────────────────────────

@sio.event
async def claim_chunks(sid, data):
    """클라가 활성 청크 소유를 요청 → 비어있거나 내 것이면 부여."""
    keys = data.get("keys", []) if isinstance(data, dict) else []
    granted = []
    for k in keys:
        owner = chunk_owners.get(k)
        if owner is None or owner == sid or owner not in players:
            chunk_owners[k] = sid
            granted.append(k)
    if granted:
        await sio.emit("chunk_grant", {"owned": granted}, to=sid)


@sio.event
async def release_chunks(sid, data):
    """클라가 활성 범위를 벗어난 청크 소유를 반납."""
    keys = data.get("keys", []) if isinstance(data, dict) else []
    for k in keys:
        if chunk_owners.get(k) == sid:
            del chunk_owners[k]


@sio.event
async def zombie_event(sid, data):
    """소유 클라의 좀비 스폰/위치/사망 → 다른 모든 접속자에게 중계."""
    await sio.emit("zombie_event", data, skip_sid=sid)


@sio.event
async def zombie_hit(sid, data):
    """타 소유 좀비를 공격 → 해당 좀비 소유자에게만 피해 전달."""
    if not isinstance(data, dict):
        return
    owner = data.get("owner")
    if owner and owner in players:
        await sio.emit("zombie_hit", data, to=owner)


@sio.event
async def disconnect(sid):
    """접속 종료: 상태/소유권 삭제 + 다른 유저들에게 퇴장 통보."""
    players.pop(sid, None)
    # 이 클라가 소유하던 청크 해제 (다른 클라가 이어받을 수 있도록)
    for k in [k for k, o in chunk_owners.items() if o == sid]:
        del chunk_owners[k]
    await sio.emit("leave_player", {"id": sid})
    print(f"[-] disconnect: {sid}  (online={len(players)})")


# ── 직접 실행 시 (개발 편의) ───────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
