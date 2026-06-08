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
import socketio
from fastapi import FastAPI

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


# ── 이벤트 핸들러 ──────────────────────────────────────────────────────────────

@sio.event
async def connect(sid, environ, auth=None):
    """신규 접속: 빈 슬롯 생성 + 기존 접속자 목록을 신규 유저에게 전송."""
    players[sid] = {"id": sid}
    # 현재 접속 중인 (나를 제외한) 다른 유저들의 마지막 상태를 신규 유저에게 보냄
    others = [st for other_sid, st in players.items()
              if other_sid != sid and len(st) > 1]   # 좌표가 한 번이라도 들어온 유저만
    await sio.emit("init_players", others, to=sid)
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
async def disconnect(sid):
    """접속 종료: 상태 삭제 + 다른 유저들에게 퇴장 통보."""
    players.pop(sid, None)
    await sio.emit("leave_player", {"id": sid})
    print(f"[-] disconnect: {sid}  (online={len(players)})")


# ── 직접 실행 시 (개발 편의) ───────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
