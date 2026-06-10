"""
Zombie Days — Mobile Touch Controls  v2
────────────────────────────────────────
• 가상 조이스틱  : 이동 (멀티터치)
• 터치 버튼      : FIRE / R / E / SPC / RUN
• 무기 슬롯 탭   : 1~6 슬롯 전환
• PAUSE 버튼     : ESC 역할
• 레이아웃 편집  : 꾹 누르기(0.8s) → 드래그로 재배치 → DONE 저장
"""
import sys, math, json, os
import pygame

_IS_WEB   = sys.platform == "emscripten"
_LAY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "touch_layout.json")
_LAY_KEY  = "zombiedays_layout"

# ── 레이아웃 저장/불러오기 ────────────────────────────────────────────────────

def _save_layout(data: dict):
    raw = json.dumps(data)
    if _IS_WEB:
        try:
            from platform import window
            window.localStorage.setItem(_LAY_KEY, raw)
        except Exception:
            pass
    else:
        try:
            with open(_LAY_FILE, "w", encoding="utf-8") as f:
                f.write(raw)
        except Exception:
            pass


def _load_layout() -> dict:
    if _IS_WEB:
        try:
            from platform import window
            raw = window.localStorage.getItem(_LAY_KEY)
            return json.loads(raw) if raw else {}
        except Exception:
            return {}
    else:
        try:
            if os.path.isfile(_LAY_FILE):
                with open(_LAY_FILE, encoding="utf-8") as f:
                    return json.loads(f.read())
        except Exception:
            pass
        return {}


# ── 유틸 ─────────────────────────────────────────────────────────────────────

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ── 가상 조이스틱 ─────────────────────────────────────────────────────────────

class VirtualJoystick:
    def __init__(self, cx, cy, outer_r=72, inner_r=30):
        self.cx = cx;  self.cy = cy
        self.outer_r = outer_r;  self.inner_r = inner_r
        self._kx = float(cx);  self._ky = float(cy)
        self._active = False
        self.dx = 0.0;  self.dy = 0.0

    def contains(self, sx, sy):
        return math.hypot(sx - self.cx, sy - self.cy) <= self.outer_r + 28

    def press(self, sx, sy):   self._active = True;  self._mv(sx, sy)
    def move(self,  sx, sy):
        if self._active: self._mv(sx, sy)
    def release(self):
        self._active = False
        self._kx = float(self.cx);  self._ky = float(self.cy)
        self.dx = self.dy = 0.0

    def _mv(self, sx, sy):
        rx, ry = sx - self.cx, sy - self.cy
        d = math.hypot(rx, ry)
        if d > self.outer_r:
            rx, ry = rx/d*self.outer_r, ry/d*self.outer_r
        self._kx, self._ky = self.cx + rx, self.cy + ry
        self.dx, self.dy   = rx/self.outer_r, ry/self.outer_r

    def draw(self, surface, edit_mode=False):
        r = self.outer_r
        cx, cy = self.cx, self.cy

        # 드롭 섀도우
        sh = pygame.Surface((r*2+14, r*2+14), pygame.SRCALPHA)
        pygame.draw.circle(sh, (0, 0, 0, 75), (r+7, r+9), r)
        surface.blit(sh, (cx-r-7, cy-r-7))

        # 베이스 (어두운 반투명 + 동심 가이드 링)
        base = pygame.Surface((r*2+4, r*2+4), pygame.SRCALPHA)
        c = r + 2
        if edit_mode:
            pygame.draw.circle(base, (60, 50, 20, 150), (c, c), r)
            pygame.draw.circle(base, (255, 215, 90, 230), (c, c), r, 3)
        else:
            pygame.draw.circle(base, (22, 24, 30, 150), (c, c), r)
            pygame.draw.circle(base, (255, 255, 255, 70), (c, c), r, 2)
            pygame.draw.circle(base, (255, 255, 255, 30), (c, c), int(r*0.62), 1)
        surface.blit(base, (cx-c, cy-c))

        if edit_mode:
            return

        # 방향 힌트 (비활성일 때만, 은은하게)
        if not self._active:
            for adx, ady, ang in [(0,-1,0),(1,0,90),(0,1,180),(-1,0,270)]:
                ax = cx + int(adx*(r-15))
                ay = cy + int(ady*(r-15))
                arr = pygame.Surface((14, 14), pygame.SRCALPHA)
                pygame.draw.polygon(arr, (255, 255, 255, 45),
                                    [(7, 1), (12, 10), (7, 8), (2, 10)])
                arr = pygame.transform.rotate(arr, -ang)
                surface.blit(arr, (ax-arr.get_width()//2, ay-arr.get_height()//2))

        # 노브 (그라데이션 느낌 + 광택)
        ki = self.inner_r
        kx, ky = int(self._kx), int(self._ky)
        knob = pygame.Surface((ki*2+4, ki*2+4), pygame.SRCALPHA)
        kc = ki + 2
        base_a = 230 if self._active else 180
        accent = (90, 200, 255) if self._active else (210, 215, 225)
        pygame.draw.circle(knob, (*accent, base_a), (kc, kc), ki)
        pygame.draw.circle(knob, (255, 255, 255, 90),
                           (kc, int(kc*0.72)), int(ki*0.7))
        pygame.draw.circle(knob, (255, 255, 255, 235), (kc, kc), ki, 2)
        surface.blit(knob, (kx-kc, ky-kc))


# ── 터치 버튼 ─────────────────────────────────────────────────────────────────

class TouchButton:
    def __init__(self, cx, cy, r, label, color=(180,180,180)):
        self.cx = cx;  self.cy = cy;  self.r = r
        self.label = label;  self.color = color
        self.pressed = False

    def contains(self, sx, sy):
        return math.hypot(sx-self.cx, sy-self.cy) <= self.r

    def draw(self, surface, font, edit_mode=False):
        r, g, b = self.color
        cx, cy, rad = self.cx, self.cy, self.r
        press = self.pressed

        # 부드러운 드롭 섀도우
        sh = pygame.Surface((rad*2+12, rad*2+12), pygame.SRCALPHA)
        pygame.draw.circle(sh, (0, 0, 0, 90), (rad+6, rad+8), rad)
        surface.blit(sh, (cx-rad-6, cy-rad-6))

        # 본체 (반투명 컬러) + 상단 광택
        body = pygame.Surface((rad*2, rad*2), pygame.SRCALPHA)
        fa = 250 if press else 175
        pygame.draw.circle(body, (r, g, b, fa), (rad, rad), rad)
        # 하단을 살짝 어둡게 (입체감)
        pygame.draw.circle(body, (max(0, r-45), max(0, g-45), max(0, b-45),
                                  fa), (rad, int(rad*1.35)), int(rad*0.92))
        pygame.draw.circle(body, (r, g, b, fa), (rad, int(rad*0.78)),
                           int(rad*0.9))
        # 원형 마스크로 잘라내기
        mask = pygame.Surface((rad*2, rad*2), pygame.SRCALPHA)
        pygame.draw.circle(mask, (255, 255, 255, 255), (rad, rad), rad)
        body.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        # 상단 광택 하이라이트
        gloss = pygame.Surface((rad*2, rad*2), pygame.SRCALPHA)
        pygame.draw.ellipse(gloss, (255, 255, 255, 55 if not press else 28),
                            (int(rad*0.32), int(rad*0.16),
                             int(rad*1.36), int(rad*0.78)))
        gloss.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        body.blit(gloss, (0, 0))
        surface.blit(body, (cx-rad, cy-rad))

        # 테두리 링
        if edit_mode:
            bc = (255, 215, 90)
        elif press:
            bc = (255, 255, 255)
        else:
            bc = (235, 235, 240)
        pygame.draw.circle(surface, bc, (cx, cy), rad, 3 if press else 2)

        # 라벨
        txt = font.render(self.label, True,
                          (255, 255, 255) if press else (240, 240, 245))
        surface.blit(txt, (cx - txt.get_width()//2, cy - txt.get_height()//2))


# ── 메인 오버레이 ─────────────────────────────────────────────────────────────

class TouchOverlay:
    _HOLD_SEC = 0.8   # 꾹 누르기 → 편집 모드 진입

    def __init__(self, screen_w, screen_h):
        self.W = screen_w;  self.H = screen_h
        self.visible  = _IS_WEB
        self.edit_mode = False

        W, H = screen_w, screen_h
        # 기존 UI 안전 구역:
        #   무기 패널  y=580-680, x=10-220
        #   슬롯 바    y=684-736
        #   슬롯 우끝  x≈762

        # 조이스틱 (좌하단 — 무기 패널 위, outer_r=68 → 하단=500+68=568 < 580)
        self.joystick = VirtualJoystick(cx=115, cy=H-268, outer_r=68)

        # 액션 버튼 (우하단 — 슬롯 바·무기 패널·서로 겹치지 않게 배치)
        #   FIRE (대) : c(936,508) r58
        #   RUN       : c(824,548) r40
        #   E(탑승/문): c(932,368) r34
        #   T(상호작용): c(839,396) r34
        self.buttons: dict[str, TouchButton] = {
            "fire":  TouchButton(W-88,  H-260, 58, "FIRE", (210, 55, 35)),
            "shift": TouchButton(W-200, H-220, 40, "RUN",  (160, 100, 210)),
            "e":     TouchButton(W-92,  H-400, 34, "E",    (70, 120, 210)),
            "t":     TouchButton(W-185, H-372, 34, "T",    (210, 160, 50)),
        }

        # 고정 버튼 (항상 표시) — 우상단 접속인원 표시(y10~32)와 겹치지 않게 내림
        self.pause_btn = TouchButton(W-38, 78,  26, "II",   (80, 80, 80))
        self.edit_btn  = TouchButton(W-38, 124, 20, "✎",    (80, 80, 80))
        self.done_btn  = TouchButton(W//2, 32, 32, "DONE", (50, 180, 80))

        # 슬롯 탭 감지용 rect 목록
        self._slot_rects = self._mk_slot_rects()

        # 멀티터치 핑거 추적
        self._joy_fid:  int|None     = None
        self._btn_fid:  dict[int,str] = {}
        self._tap_fid:  dict[int, tuple] = {}  # fid → (down_sx, down_sy, time)

        # 편집 모드 드래그 추적
        self._edit_target: str|None  = None  # "joy" | btn_name
        self._edit_fid:    int|None  = None
        self._edit_off:    tuple     = (0,0)
        self._hold_fid:    int|None  = None
        self._hold_timer:  float     = 0.0
        self._hold_pos:    tuple     = (0,0)

        # 단발 출력 플래그
        self.just_reload  = False
        self.just_e       = False
        self.just_t       = False
        self.just_space   = False
        self.just_pause   = False
        self.just_slot:   int|None = None

        self._load()

    # ── 슬롯 rect 계산 ────────────────────────────────────────────────────────

    def _mk_slot_rects(self):
        SW, SH, SG = 80, 52, 4
        total = SW*6 + SG*5
        bx = (self.W - total) // 2
        by = self.H - SH - 32
        return [pygame.Rect(bx + i*(SW+SG), by, SW, SH) for i in range(6)]

    # ── 레이아웃 저장/불러오기 ────────────────────────────────────────────────

    def _save(self):
        d = {"joy_cx": self.joystick.cx, "joy_cy": self.joystick.cy}
        for n, b in self.buttons.items():
            d[f"b_{n}_cx"] = b.cx;  d[f"b_{n}_cy"] = b.cy
        _save_layout(d)

    def _load(self):
        d = _load_layout()
        if not d:
            return
        if "joy_cx" in d:
            self.joystick.cx = d["joy_cx"];  self.joystick.cy = d["joy_cy"]
            self.joystick._kx = float(self.joystick.cx)
            self.joystick._ky = float(self.joystick.cy)
        for n, b in self.buttons.items():
            if f"b_{n}_cx" in d:
                b.cx = d[f"b_{n}_cx"];  b.cy = d[f"b_{n}_cy"]

    # ── 이벤트 처리 ───────────────────────────────────────────────────────────

    def handle_event(self, event) -> bool:
        if not self.visible:
            return False
        t = pygame.time.get_ticks() / 1000.0

        if event.type == pygame.FINGERDOWN:
            sx = int(event.x * self.W);  sy = int(event.y * self.H)
            return self._down(event.finger_id, sx, sy, t)
        if event.type == pygame.FINGERMOTION:
            sx = int(event.x * self.W);  sy = int(event.y * self.H)
            return self._move(event.finger_id, sx, sy)
        if event.type == pygame.FINGERUP:
            sx = int(event.x * self.W);  sy = int(event.y * self.H)
            return self._up(event.finger_id, sx, sy, t)
        return False

    def update(self, dt: float):
        """매 프레임 호출 — 꾹 누르기 타이머."""
        if not self.visible:
            return
        if self._hold_fid is not None:
            self._hold_timer += dt
            if self._hold_timer >= self._HOLD_SEC and not self.edit_mode:
                self.edit_mode = True
                self._hold_fid = None
                self._hold_timer = 0.0

    # ── 내부 DOWN / MOVE / UP ─────────────────────────────────────────────────

    def _down(self, fid, sx, sy, t) -> bool:
        # ── 편집 모드 ──────────────────────────────────────────────────────
        if self.edit_mode:
            if self.done_btn.contains(sx, sy):
                self.done_btn.pressed = True
                return True
            if self.joystick.contains(sx, sy):
                self._edit_fid    = fid
                self._edit_target = "joy"
                self._edit_off    = (sx - self.joystick.cx, sy - self.joystick.cy)
                return True
            for n, b in self.buttons.items():
                if math.hypot(sx-b.cx, sy-b.cy) <= b.r + 20:
                    self._edit_fid    = fid
                    self._edit_target = n
                    self._edit_off    = (sx - b.cx, sy - b.cy)
                    return True
            return False

        # ── 고정 버튼 ──────────────────────────────────────────────────────
        if self.pause_btn.contains(sx, sy):
            self.pause_btn.pressed = True
            self.just_pause = True
            return True
        if self.edit_btn.contains(sx, sy):
            self._hold_fid   = fid
            self._hold_timer = 0.0
            self._hold_pos   = (sx, sy)
            return True

        # ── 슬롯 탭 ────────────────────────────────────────────────────────
        for i, r in enumerate(self._slot_rects):
            if r.collidepoint(sx, sy):
                self._tap_fid[fid] = (sx, sy, t, i)
                return True

        # ── 조이스틱 ───────────────────────────────────────────────────────
        if self._joy_fid is None and self.joystick.contains(sx, sy):
            self._joy_fid = fid
            self.joystick.press(sx, sy)
            # 꾹 누르기 시작
            self._hold_fid   = fid
            self._hold_timer = 0.0
            self._hold_pos   = (sx, sy)
            return True

        # ── 액션 버튼 ──────────────────────────────────────────────────────
        for n, b in self.buttons.items():
            if b.contains(sx, sy):
                self._btn_fid[fid] = n
                b.pressed = True
                if n == "e": self.just_e = True
                if n == "t": self.just_t = True
                return True

        return False

    def _move(self, fid, sx, sy) -> bool:
        # 편집 모드 드래그
        if self.edit_mode and fid == self._edit_fid:
            ox, oy = self._edit_off
            nx, ny = sx - ox, sy - oy
            nx = _clamp(nx, 40, self.W - 40)
            ny = _clamp(ny, 40, self.H - 40)
            if self._edit_target == "joy":
                self.joystick.cx = nx;  self.joystick.cy = ny
                self.joystick._kx = float(nx);  self.joystick._ky = float(ny)
            elif self._edit_target in self.buttons:
                b = self.buttons[self._edit_target]
                b.cx, b.cy = nx, ny
            return True

        # 조이스틱 이동 + 꾹 누르기 취소 (움직임 감지)
        if fid == self._joy_fid:
            self.joystick.move(sx, sy)
            if self._hold_fid == fid:
                hx, hy = self._hold_pos
                if math.hypot(sx-hx, sy-hy) > 10:
                    self._hold_fid = None  # 움직이면 꾹 누르기 취소
            return True

        return False

    def _up(self, fid, sx, sy, t) -> bool:
        # 편집 모드 DONE
        if self.edit_mode:
            if self.done_btn.pressed:
                self.done_btn.pressed = False
                self.edit_mode = False
                self._edit_fid = None
                self._save()
                return True
            if fid == self._edit_fid:
                self._edit_fid    = None
                self._edit_target = None
                return True
            return False

        # 꾹 누르기 (edit_btn 또는 조이스틱)
        if fid == self._hold_fid:
            self._hold_fid   = None
            self._hold_timer = 0.0

        # Pause 버튼 해제
        if self.pause_btn.pressed and self.pause_btn.contains(sx, sy):
            self.pause_btn.pressed = False
            return True

        # 슬롯 탭 완료 (< 0.4s, 이동 없음)
        if fid in self._tap_fid:
            ds, ts, dt_down, slot_i = self._tap_fid.pop(fid)
            elapsed = t - dt_down
            dist    = math.hypot(sx - ds, sy - ts)
            if elapsed < 0.4 and dist < 30:
                self.just_slot = slot_i
            return True

        # 조이스틱 해제
        if fid == self._joy_fid:
            self._joy_fid = None
            self.joystick.release()
            return True

        # 버튼 해제
        if fid in self._btn_fid:
            n = self._btn_fid.pop(fid)
            self.buttons[n].pressed = False
            return True

        return False

    # ── 상태 조회 ─────────────────────────────────────────────────────────────

    @property
    def fire_held(self):
        return self.visible and self.buttons["fire"].pressed

    @property
    def shift_held(self):
        return self.visible and self.buttons["shift"].pressed

    def key_overrides(self) -> dict:
        if not self.visible or not self.joystick._active:
            return {}
        dx, dy = self.joystick.dx, self.joystick.dy
        dz = 0.25
        sprint = abs(dx) > 0.75 or abs(dy) > 0.75 or self.shift_held
        ov = {}
        if dy < -dz: ov[pygame.K_w]      = True
        if dy >  dz: ov[pygame.K_s]      = True
        if dx < -dz: ov[pygame.K_a]      = True
        if dx >  dz: ov[pygame.K_d]      = True
        if sprint:   ov[pygame.K_LSHIFT] = True
        return ov

    def aim_dir(self):
        if not self.visible or not self.joystick._active:
            return None
        dx, dy = self.joystick.dx, self.joystick.dy
        if abs(dx) < 0.15 and abs(dy) < 0.15:
            return None
        return pygame.Vector2(dx, dy).normalize()

    def consume_frame_flags(self):
        self.just_reload = self.just_e = self.just_t = False
        self.just_space = self.just_pause = False
        self.just_slot = None

    # ── 렌더링 ───────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, font: pygame.font.Font):
        if not self.visible:
            return

        edit = self.edit_mode

        # 편집 모드 배경 힌트
        if edit:
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 80))
            surface.blit(ov, (0, 0))
            hint = font.render("드래그로 위치 조정  |  DONE 으로 저장", True, (255,200,50))
            surface.blit(hint,(self.W//2 - hint.get_width()//2, 70))

        self.joystick.draw(surface, edit)
        for b in self.buttons.values():
            b.draw(surface, font, edit)

        # 고정 UI
        self.pause_btn.draw(surface, font)
        if not edit:
            self.edit_btn.draw(surface, font)
        else:
            self.done_btn.draw(surface, font)
