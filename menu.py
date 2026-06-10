"""
Zombie Days — title screen, options screen, save/load helpers.
"""
import os
import sys
import json
import math
import random
import pygame

import lang
import fonts

SAVE_PATH  = os.path.join(os.path.dirname(__file__), "save.dat")
_LSKEY     = "zombiedays_save"      # localStorage key (browser)
_SKEY      = "zombiedays_settings"  # settings localStorage key
_SPATH     = os.path.join(os.path.dirname(__file__), "settings.json")
_IS_WEB    = sys.platform == "emscripten"

# ── 게임 설정 (joystick 등) ───────────────────────────────────────────────────

_DEFAULTS: dict = {"joystick": False}
_cfg: dict = dict(_DEFAULTS)


def load_settings() -> dict:
    global _cfg
    raw = None
    if _IS_WEB:
        try:
            from platform import window
            raw = window.localStorage.getItem(_SKEY)
        except Exception:
            pass
    else:
        try:
            if os.path.isfile(_SPATH):
                with open(_SPATH, encoding="utf-8") as f:
                    raw = f.read()
        except Exception:
            pass
    if raw:
        try:
            _cfg = {**_DEFAULTS, **json.loads(raw)}
        except Exception:
            _cfg = dict(_DEFAULTS)
    return _cfg


def save_settings() -> None:
    data = json.dumps(_cfg)
    if _IS_WEB:
        try:
            from platform import window
            window.localStorage.setItem(_SKEY, data)
        except Exception:
            pass
    else:
        try:
            with open(_SPATH, "w", encoding="utf-8") as f:
                f.write(data)
        except Exception:
            pass


def get_setting(key: str, default=None):
    return _cfg.get(key, default if default is not None else _DEFAULTS.get(key))


def set_setting(key: str, value) -> None:
    _cfg[key] = value
    save_settings()

# ── Animated background state ─────────────────────────────────────────────────

class _Particle:
    __slots__ = ("x", "y", "vx", "vy", "r", "col", "alpha")
    def __init__(self, x, y, vx, vy, r, col, alpha):
        self.x = x; self.y = y; self.vx = vx; self.vy = vy
        self.r = r; self.col = col; self.alpha = alpha


_particles: list[_Particle] = []
_drips:     list[dict]      = []   # blood-drip effects under title
_time       = 0.0
_W, _H      = 1024, 768

_rng = random.Random(77)

def _init(W: int, H: int):
    global _particles, _drips, _W, _H
    _W, _H = W, H
    if _particles:
        return
    for _ in range(55):
        _particles.append(_Particle(
            x   = _rng.uniform(0, W),
            y   = _rng.uniform(0, H),
            vx  = _rng.uniform(-14, 14),
            vy  = _rng.uniform(-10, 10),
            r   = _rng.randint(2, 9),
            col = (_rng.randint(20, 70), _rng.randint(70, 130), _rng.randint(10, 50)),
            alpha = _rng.randint(40, 120),
        ))
    # Blood drips under the title — fixed decorative elements
    for i in range(12):
        _drips.append({
            "x":   W * 0.18 + i * (W * 0.64 / 11),
            "y0":  228,
            "len": _rng.randint(14, 52),
            "w":   _rng.randint(2, 5),
        })


def update(dt: float):
    global _time
    _time += dt
    W, H = _W, _H
    for p in _particles:
        p.x = (p.x + p.vx * dt) % (W + 40) - 20
        p.y = (p.y + p.vy * dt) % (H + 40) - 20


# ── Drawing helpers ───────────────────────────────────────────────────────────

def _glow_text(surface, font, text, col, glow_col, cx, cy, glow_r=3):
    """Render text with a coloured glow by drawing offset copies first."""
    s = font.render(text, True, glow_col)
    for dx in range(-glow_r, glow_r + 1):
        for dy in range(-glow_r, glow_r + 1):
            if dx == 0 and dy == 0:
                continue
            surface.blit(s, (cx - s.get_width() // 2 + dx,
                              cy - s.get_height() // 2 + dy))
    s = font.render(text, True, col)
    surface.blit(s, (cx - s.get_width() // 2, cy - s.get_height() // 2))


def _draw_bg(surface):
    """Dark animated background with floating zombie particles."""
    surface.fill((8, 8, 8))

    # Subtle grid
    grid_col = (16, 16, 16)
    for gx in range(0, _W + 1, 48):
        pygame.draw.line(surface, grid_col, (gx, 0), (gx, _H))
    for gy in range(0, _H + 1, 48):
        pygame.draw.line(surface, grid_col, (0, gy), (_W, gy))

    # Floating zombie particles
    ps = pygame.Surface((30, 30), pygame.SRCALPHA)
    for p in _particles:
        ps.fill((0, 0, 0, 0))
        pygame.draw.circle(ps, (*p.col, p.alpha), (15, 15), p.r)
        surface.blit(ps, (int(p.x) - 15, int(p.y) - 15))

    # Corner vignette (dark-red glow top, pure black bottom)
    vig = pygame.Surface((_W, _H), pygame.SRCALPHA)
    for i in range(200):
        a = int(120 * (1 - i / 200))
        pygame.draw.rect(vig, (80, 0, 0, a), (i, i, _W - 2*i, _H - 2*i), 1)
    surface.blit(vig, (0, 0))


def _draw_title_art(surface):
    """Draw the 'ZOMBIE DAYS' title with shadow + red glow + blood drips."""
    cx = _W // 2

    # Drop shadow
    f_main = fonts.get(92)
    shadow = f_main.render("ZOMBIE DAYS", True, (0, 0, 0))
    sx = cx - shadow.get_width() // 2
    surface.blit(shadow, (sx + 5, 105))

    # Glow + main text
    _glow_text(surface, f_main, "ZOMBIE DAYS",
               col      = (240, 230, 220),
               glow_col = (160, 10, 10),
               cx=cx, cy=140, glow_r=4)

    # Red underline
    tw   = shadow.get_width()
    lx   = cx - tw // 2
    pygame.draw.rect(surface, (170, 15, 15), (lx, 192, tw, 3))
    pygame.draw.rect(surface, (220, 40, 40), (lx, 195, tw, 2))

    # Blood drips
    pulse = 0.5 + 0.5 * math.sin(_time * 1.8)
    for d in _drips:
        col = (int(160 + 30 * pulse), 8, 8)
        drip_len = int(d["len"] * (0.7 + 0.3 * pulse))
        pygame.draw.rect(surface, col,
                         (int(d["x"] - d["w"] // 2), int(d["y0"]),
                          d["w"], drip_len))
        pygame.draw.circle(surface, col,
                           (int(d["x"]), int(d["y0"]) + drip_len),
                           d["w"] + 1)

    # Korean subtitle
    f_sub = fonts.get(28)
    _glow_text(surface, f_sub, "좀비 데이즈",
               col=(200, 195, 185), glow_col=(100, 8, 8),
               cx=cx, cy=232, glow_r=2)


def _draw_btn(surface, rect, label, hovered, disabled=False):
    """Draw a single menu button, returns rect."""
    bg_a  = 170 if hovered else 120
    bg    = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    bg.fill((18, 8, 8, bg_a))
    surface.blit(bg, rect.topleft)

    # Border
    border_col = (90, 18, 18) if disabled else ((220, 55, 20) if hovered else (110, 25, 25))
    pygame.draw.rect(surface, border_col, rect, 2)

    # Hover accent bar on left
    if hovered and not disabled:
        pygame.draw.rect(surface, (220, 55, 20),
                         (rect.x, rect.y + 6, 5, rect.h - 12))
        # Inner glow
        glow = pygame.Surface((rect.w - 2, rect.h - 2), pygame.SRCALPHA)
        glow.fill((180, 35, 10, 18))
        surface.blit(glow, (rect.x + 1, rect.y + 1))

    # Label
    text_col = (100, 95, 90) if disabled else ((255, 235, 60) if hovered else (215, 208, 195))
    f = fonts.get(28)
    ts = f.render(label, True, text_col)
    surface.blit(ts, (rect.x + rect.w // 2 - ts.get_width() // 2,
                      rect.y + rect.h // 2 - ts.get_height() // 2))

    # Sub-hint when disabled
    if disabled:
        fh = fonts.get(13)
        hint = fh.render(lang.t("menu_no_save"), True, (90, 85, 80))
        surface.blit(hint, (rect.x + rect.w // 2 - hint.get_width() // 2,
                             rect.y + rect.h - 18))
    return rect


# ── Public: title screen ──────────────────────────────────────────────────────

def draw_title(surface, mouse_pos: tuple, W: int, H: int, version: str = "") -> list[tuple[str, pygame.Rect]]:
    """
    Draw the full title screen.
    Returns [(action_id, rect), ...] for clickable areas.
    """
    _init(W, H)
    _draw_bg(surface)
    _draw_title_art(surface)

    cx = W // 2
    bw, bh, gap = 330, 68, 18
    btn_x  = cx - bw // 2
    btn_y0 = 290

    labels = [
        ("singleplayer", lang.t("menu_singleplayer")),
        ("multiplayer",  lang.t("menu_multiplayer")),
        ("options",      lang.t("menu_options")),
    ]
    mx, my = mouse_pos
    buttons = []
    for i, (action, label) in enumerate(labels):
        r = pygame.Rect(btn_x, btn_y0 + i * (bh + gap), bw, bh)
        disabled = False
        hovered  = r.collidepoint(mx, my)
        _draw_btn(surface, r, label, hovered, disabled)
        buttons.append((action, r, disabled))

    # Bottom hint bar
    f_hint = fonts.get(14)
    hint   = f_hint.render(lang.t("menu_hint_bar"), True, (140, 130, 110))
    surface.blit(hint, (cx - hint.get_width() // 2, H - 28))

    # Version
    fv   = fonts.get(13)
    ver  = fv.render(f"Zombie Days  {version}" if version else "Zombie Days", True, (160, 148, 120))
    surface.blit(ver, (12, H - 22))

    return [(a, r) for a, r, _ in buttons if not _]


def draw_mode_select(surface, mouse_pos: tuple, W: int, H: int,
                     is_multiplayer: bool) -> list[tuple[str, pygame.Rect]]:
    """싱글/멀티 선택 후 조작 방식(모바일/PC)을 고르는 화면."""
    _init(W, H)
    _draw_bg(surface)
    cx = W // 2
    mx, my = mouse_pos

    # 제목
    f_title = fonts.get(36)
    sub     = lang.t("menu_multiplayer" if is_multiplayer else "menu_singleplayer")
    ts = f_title.render(lang.t("mode_select_title"), True, (220, 210, 195))
    surface.blit(ts, (cx - ts.get_width() // 2, 150))
    f_sub = fonts.get(18)
    ss = f_sub.render(sub, True, (200, 90, 50))
    surface.blit(ss, (cx - ss.get_width() // 2, 198))

    # 두 개의 큰 선택 버튼
    bw, bh, gap = 300, 110, 30
    total = bw * 2 + gap
    bx0   = cx - total // 2
    by    = 270
    buttons = []
    opts = [("mode_mobile", lang.t("mode_mobile"), lang.t("mode_mobile_desc"),
             (40, 120, 60)),
            ("mode_pc",     lang.t("mode_pc"),     lang.t("mode_pc_desc"),
             (40, 80, 150))]
    for i, (action, label, desc, accent) in enumerate(opts):
        r = pygame.Rect(bx0 + i * (bw + gap), by, bw, bh)
        hov = r.collidepoint(mx, my)
        bg = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        bg.fill((*accent, 150) if hov else (18, 18, 22, 160))
        surface.blit(bg, r.topleft)
        pygame.draw.rect(surface, (*accent, 255) if hov else (90, 90, 100), r,
                         3 if hov else 2)
        fl = fonts.get(28)
        lt = fl.render(label, True, (255, 245, 200) if hov else (210, 205, 195))
        surface.blit(lt, (r.centerx - lt.get_width() // 2, r.y + 26))
        fd = fonts.get(14)
        dt_ = fd.render(desc, True, (220, 220, 210) if hov else (150, 150, 145))
        surface.blit(dt_, (r.centerx - dt_.get_width() // 2, r.y + 68))
        buttons.append((action, r))

    # 뒤로
    back_r = pygame.Rect(cx - 110, by + bh + 50, 220, 50)
    _draw_btn(surface, back_r, lang.t("opt_back"), back_r.collidepoint(mx, my))
    buttons.append(("mode_back", back_r))
    return buttons


# ── Public: options screen ────────────────────────────────────────────────────

_OPT_BINDINGS = [
    ("WASD",        "opt_bind_move"),
    ("Mouse",       "opt_bind_aim"),
    ("Left Click",  "opt_bind_fire"),
    ("Shift",       "opt_bind_sprint"),
    ("E",           "opt_bind_interact"),
    ("R",           "opt_bind_reload"),
    ("1 – 5",       "opt_bind_slots"),
    ("0",           "opt_bind_melee"),
    ("M",           "opt_bind_map"),
    ("F1",          "opt_bind_debug"),
    ("Space",       "opt_bind_fly"),
]


def draw_options(surface, mouse_pos: tuple, W: int, H: int) -> list[tuple[str, pygame.Rect]]:
    """
    Draw the options / key-bindings screen.
    Returns [(action_id, rect), ...] for clickable areas.
    """
    _init(W, H)
    _draw_bg(surface)

    cx = W // 2

    # Title
    f_title = fonts.get(40)
    ts = f_title.render(lang.t("opt_title"), True, (210, 200, 185))
    surface.blit(ts, (cx - ts.get_width() // 2, 28))
    pygame.draw.rect(surface, (110, 25, 25),
                     (cx - ts.get_width() // 2, 74, ts.get_width(), 2))

    # ── Language toggle ───────────────────────────────────────────────────────
    f_sec = fonts.get(18)
    sec = f_sec.render(lang.t("opt_language"), True, (160, 50, 30))
    surface.blit(sec, (80, 100))

    cur_lang = lang.current()
    lang_labels = [("ko", "한국어"), ("en", "English")]
    mx, my = mouse_pos
    lang_btns = []
    for j, (lid, lname) in enumerate(lang_labels):
        r    = pygame.Rect(80 + j * 165, 128, 150, 46)
        sel  = (lid == cur_lang)
        hov  = r.collidepoint(mx, my)
        bg   = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        bg.fill((40, 10, 10, 200) if sel else (18, 8, 8, 130))
        surface.blit(bg, r.topleft)
        border_col = (220, 55, 20) if sel else ((140, 30, 20) if hov else (70, 18, 18))
        pygame.draw.rect(surface, border_col, r, 2)
        if sel:
            pygame.draw.rect(surface, (220, 55, 20), (r.x, r.y + 6, 4, r.h - 12))
        fl  = fonts.get(22)
        lt  = fl.render(lname, True, (255, 235, 60) if sel else (190, 185, 175))
        surface.blit(lt, (r.x + r.w // 2 - lt.get_width() // 2,
                          r.y + r.h // 2 - lt.get_height() // 2))
        lang_btns.append(("lang_" + lid, r))

    # (조이스틱 선택은 게임 시작 시 '모바일/PC' 화면에서 처리)

    # ── Key bindings table ────────────────────────────────────────────────────
    f_sec2 = fonts.get(18)
    sec2 = f_sec2.render(lang.t("opt_controls"), True, (160, 50, 30))
    surface.blit(sec2, (80, 248))
    pygame.draw.line(surface, (80, 18, 18), (80, 272), (W - 80, 272), 1)

    col1_x = 80
    col2_x = 230
    col3_x = cx + 40
    col4_x = cx + 200

    fk  = fonts.get(16)
    fkd = fonts.get(16)
    row_h = 28
    rows_per_col = (len(_OPT_BINDINGS) + 1) // 2

    for i, (key, desc_key) in enumerate(_OPT_BINDINGS):
        col  = i // rows_per_col
        row  = i % rows_per_col
        y    = 284 + row * row_h
        kx   = col1_x if col == 0 else col3_x
        dx   = col2_x if col == 0 else col4_x

        key_s  = fk.render(key,  True, (210, 200, 100))
        desc_s = fkd.render(lang.t(desc_key), True, (190, 185, 175))
        surface.blit(key_s,  (kx, y))
        surface.blit(desc_s, (dx, y))

    # Separator before back button
    sep_y = 284 + rows_per_col * row_h + 14
    pygame.draw.line(surface, (60, 15, 15), (80, sep_y), (W - 80, sep_y), 1)

    # ── Back button ───────────────────────────────────────────────────────────
    bw, bh = 220, 56
    back_r = pygame.Rect(cx - bw // 2, sep_y + 14, bw, bh)
    hov    = back_r.collidepoint(mx, my)
    _draw_btn(surface, back_r, lang.t("opt_back"), hov)
    buttons = lang_btns + [("back", back_r)]

    return buttons


# ── Public: pause menu ───────────────────────────────────────────────────────

def draw_pause_menu(surface, mouse_pos: tuple, W: int, H: int,
                    save_feedback: str = "") -> list[tuple[str, pygame.Rect]]:
    """
    Semi-transparent pause overlay drawn over the frozen game world.
    Returns [(action_id, rect), ...] for clickable buttons.
    """
    # Dim overlay
    ov = pygame.Surface((W, H), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 170))
    surface.blit(ov, (0, 0))

    PW, PH = 288, 370
    px = W // 2 - PW // 2
    py = H // 2 - PH // 2

    # Panel
    panel = pygame.Surface((PW, PH), pygame.SRCALPHA)
    panel.fill((10, 5, 5, 252))
    surface.blit(panel, (px, py))
    pygame.draw.rect(surface, (120, 22, 22), (px, py, PW, PH), 2, border_radius=5)
    # Top accent line
    pygame.draw.rect(surface, (180, 30, 30), (px, py, PW, 4), border_radius=5)

    # Title
    f_title = fonts.get(26)
    title = f_title.render(lang.t("pause_title"), True, (225, 210, 190))
    surface.blit(title, (px + PW // 2 - title.get_width() // 2, py + 14))
    pygame.draw.line(surface, (80, 18, 18),
                     (px + 20, py + 50), (px + PW - 20, py + 50), 1)

    # Save feedback message (e.g. "✓ 저장 완료")
    fb_y = py + 56
    if save_feedback:
        fh = fonts.get(14)
        fb = fh.render(save_feedback, True, (80, 220, 120))
        surface.blit(fb, (px + PW // 2 - fb.get_width() // 2, fb_y))

    # Buttons
    labels = [
        ("resume",   lang.t("pause_resume")),
        ("save",     lang.t("pause_save")),
        ("settings", lang.t("pause_settings")),
        ("mainmenu", lang.t("pause_mainmenu")),
        ("quit",     lang.t("pause_quit")),
    ]
    bw, bh, gap = PW - 34, 50, 8
    bx  = px + 17
    by0 = py + 74
    mx, my = mouse_pos
    buttons = []
    for i, (action, label) in enumerate(labels):
        r = pygame.Rect(bx, by0 + i * (bh + gap), bw, bh)
        hovered = r.collidepoint(mx, my)
        # Quit button gets a red tint
        if action == "quit" and hovered:
            bg = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
            bg.fill((40, 5, 5, 200))
            surface.blit(bg, r.topleft)
            pygame.draw.rect(surface, (200, 30, 30), r, 2)
            ft = fonts.get(28)
            ts = ft.render(label, True, (255, 90, 70))
            surface.blit(ts, (r.x + r.w // 2 - ts.get_width() // 2,
                               r.y + r.h // 2 - ts.get_height() // 2))
        else:
            _draw_btn(surface, r, label, hovered)
        buttons.append((action, r))

    return buttons


# ── Save / Load ───────────────────────────────────────────────────────────────

def save_game(state: dict) -> None:
    data = json.dumps(state)
    if _IS_WEB:
        try:
            from platform import window
            window.localStorage.setItem(_LSKEY, data)
        except Exception:
            pass
    else:
        try:
            with open(SAVE_PATH, "w", encoding="utf-8") as f:
                f.write(data)
        except Exception:
            pass


def load_game() -> dict | None:
    if _IS_WEB:
        try:
            from platform import window
            raw = window.localStorage.getItem(_LSKEY)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            return None
    else:
        # Try new JSON format first, fall back to old pickle file
        json_path = SAVE_PATH.replace(".dat", ".json")
        for path in (json_path, SAVE_PATH):
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.loads(f.read())
            except Exception:
                pass
        # Legacy pickle fallback
        if os.path.isfile(SAVE_PATH):
            try:
                import pickle
                with open(SAVE_PATH, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass
        return None


def delete_save() -> None:
    if _IS_WEB:
        try:
            from platform import window
            window.localStorage.removeItem(_LSKEY)
        except Exception:
            pass
    else:
        for path in (SAVE_PATH, SAVE_PATH.replace(".dat", ".json")):
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
