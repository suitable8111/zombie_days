"""
Zombie Days — 멀티플레이 네트워크 레이어 (Phase 12-1: 아키텍처 스캐폴딩)
═══════════════════════════════════════════════════════════════════════════════

브라우저(Pygbag/emscripten) 환경에서는 표준 `socket` 을 쓸 수 없으므로,
비동기 WebSocket 기반 **중앙 서버(authoritative-lite)** 방식을 전제로 설계한다.

이 파일은 1단계로 다음을 제공한다:
  1. NetworkPlayer       — 원격 유저 1명의 상태 + 렌더링 (보간 포함)
  2. remote_players      — 전역 원격 플레이어 레지스트리 {pid: NetworkPlayer}
  3. NetworkTransport    — 전송 계층 추상화 (Dummy → 추후 socketio 로 교체)
  4. sync_network_data() — 메인 루프가 20Hz 로 호출하는 송수신 진입점

실제 서버/소켓이 붙기 전까지 게임은 그대로 싱글플레이로 동작하며,
이 모듈은 "구조만" 자리잡아 둔다 (no-op 더미).
"""
from __future__ import annotations

import sys
import time
import random
import pygame

# entities 의 휴머노이드 렌더러를 재사용 → 원격 플레이어도 내 캐릭터와 동일하게 그림
from entities import _draw_human_anim


# ═══════════════════════════════════════════════════════════════════════════════
# 서버 주소 설정
# ───────────────────────────────────────────────────────────────────────────────
#   로컬 테스트 : "http://localhost:8000"
#   자체 서버   : "http://<보유한_서버_IP>:8000"  (예: "http://203.0.113.7:8000")
#   ⚠ Socket.IO 는 http(s) 스킴을 쓰며 내부적으로 ws 로 업그레이드한다.
#     itch.io(https) 에서 접속하려면 서버도 https(wss) 여야 한다 → 배포 시 TLS 필요.
# ═══════════════════════════════════════════════════════════════════════════════
SERVER_URL = "http://localhost:8000"
# SERVER_URL = "http://203.0.113.7:8000"   # ← 자체 서버 IP 로 교체

MULTIPLAYER_ENABLED = True   # False 면 완전 싱글플레이 (네트워크 비활성)

_IS_WEB = sys.platform == "emscripten"


# ── 전역 레지스트리 ────────────────────────────────────────────────────────────
# 키: 서버가 발급한 고유 플레이어 ID (sid)
# 값: NetworkPlayer 인스턴스
remote_players: dict[str, "NetworkPlayer"] = {}

# 내 플레이어 ID — 서버 접속(handshake) 시 sid 로 채워진다. None 이면 오프라인.
local_player_id: str | None = None

# 내 닉네임 — 화면에 표시 + 서버로 전송. main 에서 설정.
local_player_name: str = f"Player{random.randint(1000, 9999)}"

# 송신 빈도 제어 (20Hz = 0.05s)
SYNC_HZ       = 20.0
SYNC_INTERVAL = 1.0 / SYNC_HZ

# 원격 플레이어가 이 시간(s) 동안 갱신이 없으면 접속 끊긴 것으로 보고 제거
STALE_TIMEOUT = 5.0


# ── NetworkPlayer ──────────────────────────────────────────────────────────────

class NetworkPlayer:
    """
    다른 유저의 캐릭터. 서버에서 받은 스냅샷으로 상태를 갱신하고,
    20Hz 수신 ↔ 60fps 렌더링 사이를 위치 보간(interpolation)으로 메운다.
    """
    __slots__ = (
        "pid", "name",
        "pos", "render_pos", "prev_pos",     # 목표 좌표 / 보간된 좌표 / 직전 좌표
        "aim_dir", "_walk_phase",
        "hp", "max_hp", "survival_day",
        "vehicle_id", "vehicle_kind",        # 탑승 차량 (None = 도보)
        "is_hidden", "_dmg_flash",
        "radius", "_last_update", "_interp_t",
    )

    def __init__(self, pid: str, x: float = 0.0, y: float = 0.0, name: str = ""):
        self.pid          = pid
        self.name         = name or f"P{str(pid)[-4:]}"
        self.pos          = pygame.Vector2(x, y)   # 서버가 알려준 최신(목표) 좌표
        self.render_pos   = pygame.Vector2(x, y)   # 화면에 실제로 그릴 좌표(보간 결과)
        self.prev_pos     = pygame.Vector2(x, y)   # 직전 스냅샷 좌표
        self.aim_dir      = pygame.Vector2(1, 0)
        self._walk_phase  = 0.0
        self.hp           = 100
        self.max_hp       = 100
        self.survival_day = 1
        self.vehicle_id   = None     # 탑승 중인 차량의 네트워크 ID (없으면 None)
        self.vehicle_kind = None     # "car" / "tank" / ... (렌더링 분기용)
        self.is_hidden    = False
        self._dmg_flash   = 0.0
        self.radius       = 12
        self._last_update = time.monotonic()
        self._interp_t    = 0.0      # 0→1: prev_pos → pos 보간 진행도

    # ── 서버 스냅샷 적용 ───────────────────────────────────────────────────────

    def apply_snapshot(self, snap: dict) -> None:
        """
        서버에서 받은 한 명분 상태 dict 를 반영.
        snap 예시:
          {"id","x","y","ax","ay","wp","hp","mhp","day","veh","vkind","hidden"}
        """
        self.prev_pos.update(self.render_pos)   # 보간 시작점 = 현재 화면 위치
        self.pos.update(snap.get("x", self.pos.x), snap.get("y", self.pos.y))
        self._interp_t = 0.0

        ax = snap.get("ax", self.aim_dir.x)
        ay = snap.get("ay", self.aim_dir.y)
        if ax or ay:
            self.aim_dir.update(ax, ay)
        self._walk_phase  = snap.get("wp",  self._walk_phase)
        self.hp           = snap.get("hp",  self.hp)
        self.max_hp       = snap.get("mhp", self.max_hp)
        self.survival_day = snap.get("day", self.survival_day)
        self.vehicle_id   = snap.get("veh",   self.vehicle_id)
        self.vehicle_kind = snap.get("vkind", self.vehicle_kind)
        self.is_hidden    = snap.get("hidden", self.is_hidden)
        if "name" in snap:
            self.name = snap["name"]
        self._last_update = time.monotonic()

    # ── 매 프레임 보간 ─────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        """수신 간격(0.05s)에 맞춰 prev_pos → pos 로 부드럽게 이동."""
        if self._interp_t < 1.0:
            self._interp_t = min(1.0, self._interp_t + dt / SYNC_INTERVAL)
            self.render_pos.update(self.prev_pos.lerp(self.pos, self._interp_t))
        else:
            self.render_pos.update(self.pos)
        if self._dmg_flash > 0:
            self._dmg_flash = max(0.0, self._dmg_flash - dt)

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def is_stale(self) -> bool:
        return (time.monotonic() - self._last_update) > STALE_TIMEOUT

    # ── 렌더링 ─────────────────────────────────────────────────────────────────

    def draw(self, surface, ox: int = 0, oy: int = 0, font=None) -> None:
        """도보 상태일 때만 휴머노이드를 그린다. 차량 탑승 중이면 차량 렌더러가
        대신 표시하므로 여기서는 그리지 않는다 (vehicle_id 가 있으면 skip)."""
        if self.vehicle_id is not None:
            return   # 탑승 중 → 차량으로 표시 (Phase 12-2 에서 차량 동기화 시 처리)

        r      = self.radius
        sx     = int(self.render_pos.x) - ox
        sy     = int(self.render_pos.y) - oy
        alpha  = 110 if self.is_hidden else 255

        # 원격 플레이어는 색상으로 구분 (아군: 초록 계열 베스트)
        if self._dmg_flash > 0:
            shirt_col, skin_col, pants_col, helm_col = \
                (240, 70, 70), (255, 120, 120), (190, 45, 45), (200, 55, 55)
        else:
            shirt_col, skin_col, pants_col, helm_col = \
                (46, 138, 74), (195, 160, 125), (28, 92, 48), (22, 78, 40)

        pad = r + 22
        s = pygame.Surface((pad * 2, pad * 2))
        s.fill((2, 2, 2))
        s.set_colorkey((2, 2, 2))
        _draw_human_anim(s, pad, pad, r, self.aim_dir, self._walk_phase,
                         shirt_col, skin_col, pants_col,
                         gun_dir=None, gun_col=(45, 45, 45),
                         helmet_col=helm_col, sprinting=False)
        if alpha < 255:
            s.set_alpha(alpha)
        surface.blit(s, (sx - pad, sy - pad))

        # 이름표 + 생존일수
        if font is not None:
            label = f"{self.name}  D{self.survival_day}"
            nl = font.render(label, True, (180, 255, 190))
            # 가독성용 어두운 배경
            bg = pygame.Surface((nl.get_width() + 6, nl.get_height() + 2),
                                pygame.SRCALPHA)
            bg.fill((0, 0, 0, 120))
            surface.blit(bg, (sx - nl.get_width() // 2 - 3, sy - r - 28))
            surface.blit(nl, (sx - nl.get_width() // 2, sy - r - 27))

        # HP 바
        if self.hp < self.max_hp:
            bw    = r * 2 + 8
            ratio = max(0.0, self.hp / self.max_hp)
            bx, by = sx - r - 4, sy - r - 14
            pygame.draw.rect(surface, (60, 18, 18), (bx, by, bw, 4))
            hp_col = ((60, 200, 60) if ratio > 0.5
                      else (210, 200, 50) if ratio > 0.25 else (220, 55, 55))
            pygame.draw.rect(surface, hp_col, (bx, by, int(bw * ratio), 4))


# ── 전송 계층 추상화 ───────────────────────────────────────────────────────────

class NetworkTransport:
    """
    송수신 인터페이스. 실제 구현(예: SocketIOTransport)이 이 클래스를 상속해
    send()/poll() 만 채우면 게임 로직은 그대로 동작한다.
    """
    connected: bool = False

    async def connect(self, url: str) -> bool:
        raise NotImplementedError

    async def send(self, packet: dict) -> None:
        """내 상태 패킷을 서버로 전송."""
        raise NotImplementedError

    async def poll(self) -> list[dict]:
        """서버에서 도착한 다른 유저들의 스냅샷 목록을 가져온다."""
        raise NotImplementedError


class DummyTransport(NetworkTransport):
    """서버가 없을 때 쓰는 no-op 전송기. 항상 빈 수신, 송신은 버린다."""
    connected = False

    async def connect(self, url: str) -> bool:
        # TODO(phase12-2): pygbag 의 platform.window 로 JS WebSocket 핸들 획득,
        #                  또는 python-socketio AsyncClient 연결.
        self.connected = False
        return False

    async def send(self, packet: dict) -> None:
        return  # no-op

    async def poll(self) -> list[dict]:
        return []  # 받은 데이터 없음


# ── 데스크톱(CPython) 전송기: python-socketio AsyncClient ──────────────────────

class SocketIOTransport(NetworkTransport):
    """
    데스크톱 CPython 용. `python-socketio` 의 AsyncClient 로 서버에 접속한다.
    수신 이벤트는 콜백에서 _inbox 에 쌓고, 메인 루프가 poll() 로 가져간다.
    (스레드가 아니라 같은 asyncio 루프에서 돌기 때문에 락이 필요 없다.)
    """
    def __init__(self):
        import socketio   # 데스크톱에만 설치되어 있으면 됨
        self._sio   = socketio.AsyncClient(reconnection=True,
                                           reconnection_attempts=0)
        self._inbox: list[dict] = []
        self.connected = False

        @self._sio.event
        async def connect():
            self.connected = True

        @self._sio.event
        async def disconnect():
            self.connected = False

        @self._sio.on("init_players")
        async def _on_init(others):
            for snap in (others or []):
                self._inbox.append(snap)

        @self._sio.on("update_player")
        async def _on_update(data):
            self._inbox.append(data)

        @self._sio.on("leave_player")
        async def _on_leave(data):
            self._inbox.append({"_leave": data.get("id")})

    async def connect(self, url: str) -> bool:
        try:
            await self._sio.connect(url, transports=["websocket"])
            global local_player_id
            local_player_id = self._sio.get_sid()
            self.connected = True
            return True
        except Exception as e:
            print(f"[network] 서버 접속 실패: {e}")
            self.connected = False
            return False

    async def send(self, packet: dict) -> None:
        if self.connected:
            try:
                await self._sio.emit("update_position", packet)
            except Exception:
                self.connected = False

    async def poll(self) -> list[dict]:
        out = self._inbox
        self._inbox = []
        return out


# ── 웹(Pygbag/emscripten) 전송기: 브라우저 Socket.IO JS 브릿지 ──────────────────

class WebBridgeTransport(NetworkTransport):
    """
    Pygbag 환경 전용. python-socketio 클라이언트(aiohttp 의존)는 브라우저에서
    동작하지 않으므로, HTML 에 로드된 Socket.IO **JS 라이브러리**를 호출한다.

    필요 조건 (build 후 자동 처리 — build_web.sh 참고):
      build/web/index.html <head> 에 아래가 있어야 함:
        <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
        <script>
          window._zd_inbox = [];
          window.zdConnect = function(url){
            window._zd_sock = io(url, {transports:["websocket"]});
            window._zd_sock.on("connect", ()=>{ window._zd_sid = window._zd_sock.id; });
            const push = (d)=> window._zd_inbox.push(JSON.stringify(d));
            window._zd_sock.on("init_players", (arr)=>{ (arr||[]).forEach(push); });
            window._zd_sock.on("update_player", push);
            window._zd_sock.on("leave_player", (d)=> window._zd_inbox.push(
                JSON.stringify({_leave: d.id})));
          };
          window.zdSend = function(s){ if(window._zd_sock) window._zd_sock.emit(
                "update_position", JSON.parse(s)); };
        </script>
    """
    def __init__(self):
        self.connected = False
        self._window   = None

    async def connect(self, url: str) -> bool:
        try:
            from platform import window
            self._window = window
            window.zdConnect(url)
            # sid 는 connect 콜백 이후 들어오므로 잠시 대기
            import asyncio
            for _ in range(50):                 # 최대 ~5초 대기
                await asyncio.sleep(0.1)
                sid = getattr(window, "_zd_sid", None)
                if sid:
                    global local_player_id
                    local_player_id = str(sid)
                    self.connected = True
                    return True
            return False
        except Exception as e:
            print(f"[network] 웹 브릿지 접속 실패: {e}")
            return False

    async def send(self, packet: dict) -> None:
        if self.connected and self._window is not None:
            import json
            self._window.zdSend(json.dumps(packet))

    async def poll(self) -> list[dict]:
        if self._window is None:
            return []
        import json
        out = []
        inbox = self._window._zd_inbox
        # JS 배열에서 모두 꺼내 비운다
        try:
            n = inbox.length
            for _ in range(n):
                out.append(json.loads(inbox.shift()))
        except Exception:
            pass
        return out


# 현재 활성 전송기 — 기본은 더미(오프라인). 접속 성공 시 교체.
transport: NetworkTransport = DummyTransport()

# 송신 누적 타이머 (메인 루프가 dt 를 넘겨 누적)
_sync_accum = 0.0


# ── 접속 진입점 ────────────────────────────────────────────────────────────────

async def connect_to_server(url: str | None = None) -> bool:
    """
    환경에 맞는 transport 를 생성해 서버에 접속한다.
    성공하면 전역 transport 를 교체하고 True, 실패하면 더미 유지 후 False.
    메인 루프 진입 전 또는 백그라운드 task 로 호출.
    """
    global transport
    if not MULTIPLAYER_ENABLED:
        return False
    target = url or SERVER_URL
    new_tr: NetworkTransport = (WebBridgeTransport() if _IS_WEB
                                else SocketIOTransport())
    ok = await new_tr.connect(target)
    if ok:
        transport = new_tr
        print(f"[network] 멀티플레이 접속 성공: {target}  (id={local_player_id})")
    return ok


# ── 내 상태 → 패킷 직렬화 ──────────────────────────────────────────────────────

def build_local_snapshot(player, survival_day: int,
                         current_vehicle=None) -> dict:
    """
    내 Player 상태를 네트워크 패킷(dict, JSON 직렬화 가능)으로 변환.
    좌표/조준/애니메이션/생존일수/탑승차량을 포함한다.
    """
    veh_id   = id(current_vehicle) if current_vehicle is not None else None
    veh_kind = getattr(current_vehicle, "_kind", None) if current_vehicle else None
    return {
        "id":     local_player_id,
        "name":   local_player_name,
        "x":      round(player.pos.x, 1),
        "y":      round(player.pos.y, 1),
        "ax":     round(player.aim_dir.x, 3),
        "ay":     round(player.aim_dir.y, 3),
        "wp":     round(player._walk_phase, 2),
        "hp":     int(player.hp),
        "mhp":    int(player.max_hp),
        "day":    survival_day,
        "veh":    veh_id,
        "vkind":  veh_kind,
        "hidden": bool(player.is_hidden),
    }


# ── 메인 루프 진입점 ──────────────────────────────────────────────────────────

async def sync_network_data(player, survival_day: int, dt: float,
                            current_vehicle=None) -> None:
    """
    메인 루프가 매 프레임 호출. 내부에서 20Hz 로 송신을 throttle 하고,
    매 프레임 수신 폴링 + 원격 플레이어 보간/정리를 수행한다.

    실제 서버가 없으면(DummyTransport) 모든 호출이 즉시 no-op 으로 반환되어
    싱글플레이 성능에 영향을 주지 않는다.
    """
    global _sync_accum

    # 1) 원격 플레이어 보간은 항상(매 프레임) 진행 → 부드러운 움직임
    for rp in remote_players.values():
        rp.update(dt)

    # 오프라인이면 여기서 끝 (네트워크 비용 0)
    if not transport.connected:
        return

    # 2) 송신 — 20Hz throttle
    _sync_accum += dt
    if _sync_accum >= SYNC_INTERVAL:
        _sync_accum = 0.0
        snapshot = build_local_snapshot(player, survival_day, current_vehicle)
        await transport.send(snapshot)

    # 3) 수신 — 도착한 스냅샷/이벤트 처리
    incoming = await transport.poll()
    for snap in incoming:
        # 퇴장 이벤트
        leave_id = snap.get("_leave")
        if leave_id is not None:
            remote_players.pop(leave_id, None)
            continue
        pid = snap.get("id")
        if pid is None or pid == local_player_id:
            continue   # 내 것/잘못된 패킷 무시
        rp = remote_players.get(pid)
        if rp is None:
            rp = NetworkPlayer(pid, snap.get("x", 0.0), snap.get("y", 0.0),
                               name=snap.get("name", ""))
            remote_players[pid] = rp
        rp.apply_snapshot(snap)

    # 4) 오래 갱신 없는(접속 끊긴) 원격 플레이어 정리
    stale = [pid for pid, rp in remote_players.items() if rp.is_stale()]
    for pid in stale:
        del remote_players[pid]


def reset_network() -> None:
    """새 게임 시작 / 메인 메뉴 복귀 시 원격 상태 초기화."""
    remote_players.clear()
    global _sync_accum
    _sync_accum = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 12-2+ 청크/스폰 동기화 아키텍처 메모 (구현 시 참고)
# ═══════════════════════════════════════════════════════════════════════════════
#
# ● 청크 활성화 범위
#   - 싱글플레이는 "내 플레이어 주변 3x3 청크"만 활성화한다.
#   - 멀티에서는 각 유저가 자기 주변 3x3 을 필요로 하므로, 클라이언트는
#     remote_players 의 좌표까지 합쳐 "활성 청크 합집합"을 계산해야 한다.
#     단, 화면에 안 보이는 원격 유저 주변 청구는 *렌더링*은 건너뛰고
#     *시뮬레이션 권한*만 서버에 위임하는 게 대역폭상 유리하다.
#
# ● 좀비 스폰 권한 (authority)
#   - 같은 청크에 여러 유저가 있으면 좀비를 중복 스폰하면 안 된다.
#   - 권장: 서버가 각 청크의 "소유 클라이언트"를 1명 지정(보통 청크에
#     먼저 진입했거나 가장 가까운 유저)하고, 그 클라이언트만 해당 청크의
#     좀비를 스폰·시뮬레이션해 결과를 서버로 올린다(host-migration 가능).
#   - 클라이언트는 chunk_manager.update() 호출 시 "내가 소유한 청크"
#     목록을 받아 좀비 스폰 루프를 그 청크로 제한한다.
#
# ● 화면 밖 원격 플레이어 처리
#   - 뷰포트 밖 원격 플레이어는 draw 를 건너뛰되(이미 _vis 컬링), 보간
#     update 는 저빈도(예: 5Hz)로 낮춰 CPU 를 아낀다.
#   - 아주 멀리(2~3 청크 밖) 있는 유저는 remote_players 에서 잠시 내리고
#     서버의 "관심 영역(AOI, Area-Of-Interest)" 구독에서 제외하면
#     수신 패킷 자체가 줄어든다.
#
# ● 엔티티 동기화 우선순위 (대역폭 예산)
#   1순위: 플레이어 좌표/HP (20Hz)
#   2순위: 차량 좌표 (탑승 시 10~20Hz, 빈 차량은 이벤트성)
#   3순위: 좀비는 "소유 클라이언트→서버→타 클라이언트" 로 저빈도(5~10Hz)
#          + 클라이언트 측 보간. 죽음/스폰은 이벤트로 즉시 전달.
# ═══════════════════════════════════════════════════════════════════════════════
