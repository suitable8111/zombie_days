import asyncio
import gc
import importlib
import os
import pygame
import random
import sys
import math

# GC를 수동으로 제어해 프레임 중 GC 일시정지 방지
gc.disable()

import lang
import fonts
from camera import Camera
import entities as _entities_mod
from entities import Player, NPC, Zombie, ZOMBIE_TYPES, Sheriff, ShopkeeperNPC
import difficulty
from chunks import (ChunkManager, GhostNPC, GhostZombie, GhostVehicle,
                    WORLD_W, WORLD_H, ACTIVE_RADIUS, DESPAWN_RADIUS)
from items import ItemManager
from projectiles import Bullet, Grenade, Flame, ProjectileManager
from touchcontrols import TouchOverlay
from particles import ParticleManager
from spatial import SpatialGrid
from vehicle import (Vehicle, Motorcycle, Tank, Helicopter, Airplane,
                     VEH_EXPLODE_R, TANK_CANNON_R, TANK_CANNON_RNG,
                     VEH_ROADKILL_SPEED, PLANE_BOMB_R)
from shop import draw_shop_ui, try_purchase
from minimap import Minimap
from map import draw_zone_labels, HideoutCompound
from melee import MeleeWeapon, MeleeDrop
import menu as _menu_mod
import network as _net
from network import remote_players, sync_network_data

# ── Window / game constants ───────────────────────────────────────────────────
WIDTH, HEIGHT = 1024, 768
FPS           = 60
TITLE         = "Zombie Days"

BG_COLOR   = (30, 32, 28)
GRID_COLOR = (40, 42, 38)
GRID_SIZE  = 48

# Entity counts are now driven by ChunkManager — no fixed globals needed.

# Fog of War
VISION_RADIUS = 280
FOG_ALPHA     = 218
FOG_COLOR     = (5, 8, 12)

# Zombie wave config
ZOMBIE_KINDS  = ["regular", "regular", "regular", "speed", "giant", "runner", "runner"]
WAVE_INTERVAL = 12.0

# ── Day / Night cycle ─────────────────────────────────────────────────────────
REAL_DAY_SECS      = 30 * 60           # 30 real minutes = 24 game hours
GAME_HOURS_PER_SEC = 24.0 / REAL_DAY_SECS   # ≈ 0.01333 h/s
GAME_START_HOUR    = 8.0               # game starts at 8 AM

DAY_START  = 6.0    # fully bright from here
DAY_END    = 18.0   # dusk begins
DUSK_END   = 20.0   # fully dark
DAWN_START = 4.0    # starts brightening before DAY_START

BG_NIGHT   = (30,  32,  28)
BG_DAY     = (54,  58,  46)
GRID_NIGHT = (40,  42,  38)
GRID_DAY   = (64,  68,  56)

LANTERN_VISION_R = 460          # px — extended radius when lantern active

# Lantern is passive; pressing fire does nothing
PASSIVE_WEAPONS = {"lantern"}

# Grenade throw range cap (world px)
GRENADE_MAX_RANGE = 300
GRENADE_THROW_DUR = 0.38   # arm animation duration (matches entities.py _THROW_DUR)

# Gunshot noise radius per weapon kind (world pixels)
GUN_NOISE_RADII = {
    "pistol":     320,
    "rifle":      560,
    "shotgun":    480,
    "machinegun": 300,
    "grenade":    0,      # explosion alert handled separately
    "heal_pack":  0,
}

# Slot bar layout constants
SLOT_W      = 80
SLOT_H      = 52
SLOT_GAP    = 4
SLOT_BAR_Y  = HEIGHT - SLOT_H - 32   # 684 — sits above hint text

_SLOT_CAT_KEYS = ["slot_cat_0", "slot_cat_1", "slot_cat_2",
                  "slot_cat_3", "slot_cat_4", "slot_cat_5"]

VERSION = "v1.0.7"

# ── Korean IME–safe keyboard input ────────────────────────────────────────────
# SDL2 scancodes = physical key positions, unaffected by IME / keyboard layout.
_SC = {
     4: pygame.K_a,  22: pygame.K_s,   7: pygame.K_d,  26: pygame.K_w,
     8: pygame.K_e,   9: pygame.K_f,  10: pygame.K_g,  12: pygame.K_i,
    14: pygame.K_k,  15: pygame.K_l,  16: pygame.K_m,  21: pygame.K_r,
    23: pygame.K_t,  25: pygame.K_v,  27: pygame.K_x,
    30: pygame.K_1,  31: pygame.K_2,  32: pygame.K_3,  33: pygame.K_4,
    34: pygame.K_5,
    40: pygame.K_RETURN,  41: pygame.K_ESCAPE,  42: pygame.K_BACKSPACE,
    43: pygame.K_TAB,     44: pygame.K_SPACE,
    79: pygame.K_RIGHT,   80: pygame.K_LEFT,
    81: pygame.K_DOWN,    82: pygame.K_UP,
   224: pygame.K_LCTRL,  225: pygame.K_LSHIFT,
}
_scan_held: set = set()   # scancodes currently held


class _Keys:
    """Wraps pygame.key.get_pressed() with scancode + touch-control fallback."""
    __slots__ = ("_r", "_extra", "_touch")
    def __init__(self, real, scan_held, touch_overrides=None):
        self._r     = real
        self._extra = {_SC[sc] for sc in scan_held if sc in _SC}
        self._touch = touch_overrides or {}
    def __getitem__(self, k):
        return bool(self._r[k]) or k in self._extra or self._touch.get(k, False)


def _ek(event, k) -> bool:
    """KEYDOWN match: checks event.key AND scancode fallback."""
    return event.key == k or _SC.get(event.scancode) == k


# Game states
STATE_MENU    = "menu"
STATE_OPTIONS = "options"
STATE_PAUSE   = "pause"
STATE_PLAY    = "play"
STATE_OVER    = "over"


# ── Day/Night helpers ─────────────────────────────────────────────────────────

def _day_factor(game_time: float) -> float:
    """1.0 = full daylight, 0.0 = full night."""
    h = game_time % 24
    if DAY_START <= h <= DAY_END:
        return 1.0
    if DAY_END < h <= DUSK_END:
        return 1.0 - (h - DAY_END) / (DUSK_END - DAY_END)
    if DUSK_END < h or h < DAWN_START:
        return 0.0
    return (h - DAWN_START) / (DAY_START - DAWN_START)   # dawn ramp


def _lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def _fmt_gametime(h: float) -> str:
    hh = int(h) % 24
    mm = int((h % 1) * 60)
    return f"{hh:02d}:{mm:02d}"


# ── FOW ───────────────────────────────────────────────────────────────────────

def _make_vision_mask(radius: int, fog_alpha: int) -> pygame.Surface:
    size = radius * 2
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    mask.fill((0, 0, 0, 0))
    for r in range(radius, 0, -1):
        ratio = (radius - r) / radius
        alpha = int(fog_alpha * ratio ** 0.42)
        pygame.draw.circle(mask, (0, 0, 0, alpha), (radius, radius), r)
    return mask


def draw_fog(surface, player_screen_pos, fog_surf, vision_mask,
             vision_radius: int, fog_alpha: float, debug: bool):
    if debug or fog_alpha < 1:
        return
    fog_surf.fill((*FOG_COLOR, int(fog_alpha)))
    mx = int(player_screen_pos.x) - vision_radius
    my = int(player_screen_pos.y) - vision_radius
    fog_surf.blit(vision_mask, (mx, my), special_flags=pygame.BLEND_RGBA_SUB)
    surface.blit(fog_surf, (0, 0))


# ── Bullet factory ────────────────────────────────────────────────────────────

def _create_bullets(weapon, origin: pygame.Vector2, direction: pygame.Vector2) -> list[Bullet]:
    bullets = []
    spd = weapon.bullet_speed
    dmg = weapon.damage
    col = weapon.bullet_color

    if weapon.kind in ("pistol", "rifle"):
        bullets.append(Bullet(origin, direction * spd, dmg, col))

    elif weapon.kind == "shotgun":
        n    = weapon.spread_count
        half = weapon.spread_angle / 2
        for i in range(n):
            angle = -half + (weapon.spread_angle / (n - 1)) * i if n > 1 else 0
            bullets.append(Bullet(origin, direction.rotate(angle) * spd, dmg, col))

    elif weapon.kind == "machinegun":
        spread = random.uniform(-weapon.spread_angle, weapon.spread_angle)
        bullets.append(Bullet(origin, direction.rotate(spread) * spd, dmg, col))

    return bullets


# ── Background ────────────────────────────────────────────────────────────────

def draw_background(surface, ox: int, oy: int, bg=BG_COLOR, grid=GRID_COLOR):
    surface.fill(bg)
    start_x = -(ox % GRID_SIZE)
    start_y = -(oy % GRID_SIZE)
    for x in range(start_x, WIDTH + GRID_SIZE, GRID_SIZE):
        pygame.draw.line(surface, grid, (x, 0), (x, HEIGHT))
    for y in range(start_y, HEIGHT + GRID_SIZE, GRID_SIZE):
        pygame.draw.line(surface, grid, (0, y), (WIDTH, y))


# ── HUD helpers ───────────────────────────────────────────────────────────────

def _bar(surface, x, y, w, h, ratio, fg, bg=(50, 50, 50)):
    pygame.draw.rect(surface, bg, (x, y, w, h), border_radius=2)
    if ratio > 0:
        pygame.draw.rect(surface, fg, (x, y, int(w * ratio), h), border_radius=2)
    pygame.draw.rect(surface, (100, 100, 100), (x, y, w, h), 1, border_radius=2)


def _draw_slot_bar(surface, player, font_sm, font_md):
    n_slots = 6
    total_w = SLOT_W * n_slots + SLOT_GAP * (n_slots - 1)
    bar_x   = (WIDTH - total_w) // 2

    for i in range(n_slots):
        sx        = bar_x + i * (SLOT_W + SLOT_GAP)
        sy        = SLOT_BAR_Y
        active    = (i == player.active_slot)
        w         = player.slot_weapon(i)
        n_weapons = len(player.weapon_slots[i])

        box = pygame.Surface((SLOT_W, SLOT_H), pygame.SRCALPHA)
        # Melee slot gets a slightly different tint
        if i == 5:
            box.fill((30, 10, 0, 170 if active else 90))
        else:
            box.fill((0, 0, 0, 170 if active else 100))
        surface.blit(box, (sx, sy))

        if i == 5 and active:
            border_col = (255, 160, 50)   # orange tint for melee
        elif active:
            border_col = (255, 215, 80)
        else:
            border_col = (70, 70, 70)
        pygame.draw.rect(surface, border_col, (sx, sy, SLOT_W, SLOT_H),
                         2 if active else 1, border_radius=3)

        cat     = lang.t(_SLOT_CAT_KEYS[i])
        cat_col = (220, 150, 60) if (active and i == 5) else \
                  (190, 175, 90) if active else (90, 90, 80)
        cs = font_sm.render(cat, True, cat_col)
        surface.blit(cs, (sx + SLOT_W // 2 - cs.get_width() // 2, sy + 3))

        if w is not None:
            abbrev = lang.t(f"slot_abbrev_{w.kind}")
            a_col  = (255, 200, 80) if (active and i == 5) else \
                     (255, 220, 80) if active else (150, 130, 50)
            ab = font_md.render(abbrev, True, a_col)
            surface.blit(ab, (sx + SLOT_W // 2 - ab.get_width() // 2, sy + 18))

            if isinstance(w, MeleeWeapon):
                if not w.is_default:
                    lv_txt = f"Lv.{w.level}/{w.mag_size}"
                    lv_col = (220, 160, 60) if w.level > 0 else (100, 100, 90)
                    lm = font_sm.render(lv_txt, True, lv_col)
                    surface.blit(lm, (sx + SLOT_W // 2 - lm.get_width() // 2, sy + 36))
            elif w.kind == "lantern":
                if w.fuel > 0:
                    gh = w.fuel / 75.0
                    ammo_txt = f"{int(gh)}:{int((gh%1)*60):02d}"
                    ammo_col = (220, 180, 60) if w.fuel / w.max_fuel > 0.3 else (220, 100, 50)
                else:
                    ammo_txt = "OFF"
                    ammo_col = (180, 60, 60)
                am = font_sm.render(ammo_txt, True, ammo_col)
                surface.blit(am, (sx + SLOT_W // 2 - am.get_width() // 2, sy + 36))
            elif w.kind == "heal_pack":
                ammo_txt = f"{w.mag}"
                ammo_col = (200, 60, 60) if w.mag == 0 else (110, 110, 100)
                am = font_sm.render(ammo_txt, True, ammo_col)
                surface.blit(am, (sx + SLOT_W // 2 - am.get_width() // 2, sy + 36))
            else:
                ammo_txt = f"{w.mag}/{w.mag_size}"
                ammo_col = (200, 60, 60) if w.mag == 0 else (110, 110, 100)
                am = font_sm.render(ammo_txt, True, ammo_col)
                surface.blit(am, (sx + SLOT_W // 2 - am.get_width() // 2, sy + 36))

            if n_weapons > 1:
                cyc = font_sm.render(f"{player._slot_idx[i]+1}/{n_weapons}",
                                     True, (160, 200, 255))
                surface.blit(cyc, (sx + SLOT_W - cyc.get_width() - 3, sy + 3))

            # ── Cooldown / reload bar at bottom of slot ────────────────
            _bar_h  = 4
            _bar_y  = sy + SLOT_H - _bar_h - 1
            _bar_x  = sx + 2
            _bar_w  = SLOT_W - 4
            if hasattr(w, 'is_reloading') and w.is_reloading and w.reload_time > 0:
                # Reload: bar fills left→right, orange
                _ratio = 1.0 - w._reload_timer / w.reload_time
                _bar(surface, _bar_x, _bar_y, _bar_w, _bar_h,
                     max(0.0, min(1.0, _ratio)), (230, 140, 30))
            elif (hasattr(w, 'cooldown') and hasattr(w, 'fire_rate')
                  and w.cooldown > 0 and w.fire_rate > 0):
                # Shot cooldown: bar fills left→right, red (only noticeable cooldowns)
                _shot_dur = 1.0 / w.fire_rate
                if _shot_dur >= 0.3:
                    _ratio = 1.0 - w.cooldown / _shot_dur
                    _bar(surface, _bar_x, _bar_y, _bar_w, _bar_h,
                         max(0.0, min(1.0, _ratio)), (200, 60, 60))
        else:
            em = font_sm.render("---", True, (50, 50, 50))
            surface.blit(em, (sx + SLOT_W // 2 - em.get_width() // 2, sy + 22))


def _draw_weapon_panel(surface, player, font_md, font_sm):
    pw      = player.weapon
    PANEL_X = 10
    PANEL_Y = SLOT_BAR_Y - 100 - 4
    PANEL_W = 210
    PANEL_H = 100

    panel = pygame.Surface((PANEL_W, PANEL_H), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 110))
    surface.blit(panel, (PANEL_X, PANEL_Y))
    lx, ly = PANEL_X + 8, PANEL_Y + 6

    if pw is None:
        surface.blit(font_sm.render(lang.t("upg_no_weapon"), True, (100, 100, 90)), (lx, ly + 14))
        return

    surface.blit(font_md.render(pw.name, True, (255, 215, 80)), (lx, ly))

    # ── Melee weapon info ─────────────────────────────────────────────
    if isinstance(pw, MeleeWeapon):
        if pw.is_default:
            surface.blit(font_sm.render(
                f"DMG {int(pw.damage)}  RPS {pw.attack_rate:.1f}",
                True, (200, 180, 130)), (lx, ly + 22))
            surface.blit(font_sm.render(
                lang.t("hud_screws", player.screws), True, (190, 190, 190)),
                (lx, ly + 44))
        else:
            stat_lbl = pw.upgrade_stat_label
            stat_val = pw.upgrade_stat_value
            surface.blit(font_sm.render(
                f"{stat_lbl}: {stat_val}", True, (200, 180, 130)), (lx, ly + 22))
            lv_ratio = pw.level / pw.mag_size if pw.mag_size else 0
            _bar(surface, lx, ly + 38, PANEL_W - 20, 5, lv_ratio, (220, 155, 50))
            surface.blit(font_sm.render(
                lang.t("upg_melee_lv", pw.level, pw.mag_size), True, (160, 140, 100)),
                (lx, ly + 48))
            surface.blit(font_sm.render(lang.t("hud_screws", player.screws),
                                        True, (190, 190, 190)), (lx, ly + 66))
            if pw.level >= pw.mag_size:
                surface.blit(font_sm.render(lang.t("upg_maxed"), True, (255, 200, 50)),
                             (lx, ly + 84))
            else:
                surface.blit(font_sm.render(lang.t("shop_enter_hint"), True, (120, 120, 100)),
                             (lx, ly + 84))
        return

    # Shot cooldown indicator in panel (only for slow-fire weapons)
    _shot_dur = (1.0 / pw.fire_rate) if hasattr(pw, 'fire_rate') and pw.fire_rate > 0 else 0
    _cd_ratio = max(0.0, 1.0 - (pw.cooldown / _shot_dur)) if _shot_dur >= 0.3 else 1.0
    if (hasattr(pw, 'is_reloading') and not pw.is_reloading
            and hasattr(pw, 'cooldown') and pw.cooldown > 0 and _shot_dur >= 0.3):
        surface.blit(font_sm.render(lang.t("hud_cooldown"), True, (200, 80, 80)),
                     (lx, ly + 22))
        _bar(surface, lx, ly + 38, PANEL_W - 20, 5, _cd_ratio, (200, 80, 60))

    if pw.is_reloading:
        surface.blit(font_sm.render(lang.t("hud_reload"), True, (255, 180, 60)), (lx, ly + 22))
        _bar(surface, lx, ly + 38, PANEL_W - 20, 5, pw.reload_progress, (255, 180, 60))
    elif pw.kind == "lantern":
        if pw.fuel > 0:
            gh    = pw.fuel / 75.0
            ftxt  = f"{int(gh)}h {int((gh % 1) * 60):02d}m"
            ratio = pw.fuel / pw.max_fuel
            fc    = (220, 180, 60) if ratio > 0.3 else (220, 80, 50)
            surface.blit(font_sm.render(lang.t("lantern_fuel", ftxt), True, fc),
                         (lx, ly + 22))
            _bar(surface, lx, ly + 38, PANEL_W - 20, 5, ratio,
                 (220, 180, 60) if ratio > 0.3 else (200, 80, 40))
        else:
            surface.blit(font_sm.render(lang.t("lantern_off"), True, (150, 70, 50)),
                         (lx, ly + 22))
    elif pw.kind == "heal_pack":
        ht = f"x{pw.mag}  +{pw.reserves}"
        surface.blit(font_sm.render(ht, True, (100, 220, 120)), (lx, ly + 22))
    else:
        mag_txt = f"{lang.t('hud_mag')}: {pw.mag}/{pw.mag_size}  +{pw.reserves}"
        col     = (200, 60, 60) if pw.mag == 0 else (160, 160, 150)
        surface.blit(font_sm.render(mag_txt, True, col), (lx, ly + 22))
        ratio   = pw.mag / pw.mag_size if pw.mag_size else 0
        bar_col = ((80, 200, 80)  if ratio > 0.5 else
                   (220, 200, 50) if ratio > 0.2 else (200, 60, 60))
        _bar(surface, lx, ly + 38, PANEL_W - 20, 5, ratio, bar_col)

    surface.blit(font_sm.render(lang.t("hud_screws", player.screws), True, (190, 190, 190)),
                 (lx, ly + 52))

    if pw.upgradeable:
        surface.blit(font_sm.render(lang.t("shop_enter_hint"), True, (120, 120, 100)),
                     (lx, ly + 70))


# ── Vehicle HUD ───────────────────────────────────────────────────────────────

def _draw_vehicle_hud(surface, vehicle, font_sm):
    alt      = getattr(vehicle, 'altitude', None)
    mg_ratio = getattr(vehicle, 'mg_spinup_ratio', None)   # heli minigun charge
    has_alt  = alt is not None
    has_mg   = mg_ratio is not None
    W_BOX    = 170
    H_BOX    = (72 if has_alt else 52) + (12 if has_mg else 0)
    bx = WIDTH // 2 - W_BOX // 2
    by = SLOT_BAR_Y - H_BOX - 8

    box = pygame.Surface((W_BOX, H_BOX), pygame.SRCALPHA)
    box.fill((0, 0, 0, 150))
    surface.blit(box, (bx, by))
    pygame.draw.rect(surface, (90, 80, 50), (bx, by, W_BOX, H_BOX), 1, border_radius=2)

    lx     = bx + 8
    hp_r   = vehicle.hp   / vehicle._max_hp
    fuel_r = vehicle.fuel / vehicle._max_fuel

    surface.blit(font_sm.render(lang.t("veh_hud_hp"),   True, (200, 200, 180)), (lx, by + 5))
    hp_col = (80, 200, 80) if hp_r > 0.5 else (220, 160, 40) if hp_r > 0.25 else (220, 60, 60)
    _bar(surface, lx + 50, by + 8, W_BOX - 58, 8, hp_r, hp_col)

    surface.blit(font_sm.render(lang.t("veh_hud_fuel"), True, (200, 200, 180)), (lx, by + 26))
    fuel_col = (80, 160, 220) if fuel_r > 0.3 else (220, 130, 40)
    _bar(surface, lx + 50, by + 29, W_BOX - 58, 8, fuel_r, fuel_col)

    if has_alt:
        surface.blit(font_sm.render(lang.t("veh_hud_alt"), True, (200, 200, 180)),
                     (lx, by + 47))
        alt_col = (80, 180, 255) if alt > 0.3 else (180, 120, 60)
        _bar(surface, lx + 50, by + 50, W_BOX - 58, 8, alt, alt_col)

    if has_mg:
        _mg_y = by + (69 if has_alt else 49)
        mg_col = (255, 210, 50) if mg_ratio >= 1.0 else (120, 200, 255)
        _lbl = font_sm.render("MG", True, mg_col)
        surface.blit(_lbl, (lx, _mg_y))
        _bar(surface, lx + 30, _mg_y + 3, W_BOX - 38, 6, mg_ratio, mg_col)

    if vehicle.fuel <= 0:
        warn = font_sm.render(lang.t("veh_fuel_empty"), True, (220, 80, 60))
        surface.blit(warn, (bx + W_BOX // 2 - warn.get_width() // 2, by - 20))

    # Water warning for tank
    _ford_t = getattr(vehicle, '_ford_timer', 0.0)
    if getattr(vehicle, '_in_water', False) and _ford_t > 0:
        _remaining = max(0.0, 6.0 - _ford_t)
        t_now = pygame.time.get_ticks() / 1000.0
        if _ford_t >= 6.0 or math.sin(t_now * 8) > 0:  # blink when dangerous
            _wc  = (220, 60, 40) if _ford_t >= 6.0 else (220, 180, 40)
            _txt = (lang.t("tank_flooding") if _ford_t >= 6.0
                    else lang.t("tank_water_warn", int(_remaining)))
            warn = font_sm.render(_txt, True, _wc)
            surface.blit(warn, (bx + W_BOX // 2 - warn.get_width() // 2, by - 20))


# ── Exploration HUD panel ─────────────────────────────────────────────────────

def _draw_explore_hud(surface, player, font_sm,
                      zombie_count: int, npc_count: int,
                      chunk_active: int, chunk_loaded: int):
    W_BOX, H_BOX = 170, 68
    bx = WIDTH - W_BOX - 10
    by = 52    # sits just below the clock box

    box = pygame.Surface((W_BOX, H_BOX), pygame.SRCALPHA)
    box.fill((0, 0, 0, 130))
    surface.blit(box, (bx, by))
    pygame.draw.rect(surface, (55, 55, 45), (bx, by, W_BOX, H_BOX), 1, border_radius=2)

    lx = bx + 6
    col_dim  = (120, 120, 110)
    col_val  = (200, 200, 185)

    rows = [
        (f"X {int(player.pos.x):>6}  Y {int(player.pos.y):>6}", col_val),
        (lang.t("dbg_chunk", chunk_active, chunk_loaded), col_dim),
        (lang.t("dbg_entities", zombie_count, npc_count), col_dim),
    ]
    for i, (text, col) in enumerate(rows):
        surface.blit(font_sm.render(text, True, col), (lx, by + 6 + i * 20))


# ── Full HUD ──────────────────────────────────────────────────────────────────

def _draw_clock(surface, game_time: float, day_t: float, day_speed: int = 1):
    import math as _math
    font_md = fonts.get(18)
    font_sm = fonts.get(13)
    W_BOX, H_BOX = 80, 36
    bx = WIDTH - W_BOX - 10
    by = 10

    # Box background — shifts blue→amber→blue with day
    if day_t > 0.7:
        bg_c = (75, 65, 25, 190)
    elif day_t > 0.2:
        bg_c = (60, 40, 20, 190)
    else:
        bg_c = (18, 22, 55, 190)

    box = pygame.Surface((W_BOX, H_BOX), pygame.SRCALPHA)
    box.fill(bg_c)
    surface.blit(box, (bx, by))
    pygame.draw.rect(surface, (80, 80, 60), (bx, by, W_BOX, H_BOX), 1, border_radius=2)

    # Sun / Moon icon
    ix, iy = bx + 13, by + H_BOX // 2
    if day_t > 0.5:
        # Sun — filled circle + short rays
        sc = (255, 220, 60)
        pygame.draw.circle(surface, sc, (ix, iy), 6)
        for ang in range(0, 360, 45):
            rad = _math.radians(ang)
            x1 = ix + int(_math.cos(rad) * 8)
            y1 = iy + int(_math.sin(rad) * 8)
            x2 = ix + int(_math.cos(rad) * 11)
            y2 = iy + int(_math.sin(rad) * 11)
            pygame.draw.line(surface, sc, (x1, y1), (x2, y2), 1)
    else:
        # Moon — crescent using two-circle subtraction on a temp surface
        ms = pygame.Surface((14, 14), pygame.SRCALPHA)
        mc = (200, 210, 255, 220)
        pygame.draw.circle(ms, mc, (7, 7), 6)
        pygame.draw.circle(ms, (0, 0, 0, 0), (10, 5), 5)
        surface.blit(ms, (ix - 7, iy - 7))

    # Time text
    ts = font_md.render(_fmt_gametime(game_time), True,
                        (255, 240, 160) if day_t > 0.5 else (170, 190, 255))
    surface.blit(ts, (bx + 26, by + H_BOX // 2 - ts.get_height() // 2))

    if day_speed > 1:
        badge = font_sm.render(f"×{day_speed}", True, (255, 160, 40))
        surface.blit(badge, (bx + W_BOX - badge.get_width() - 3,
                             by + H_BOX - badge.get_height() - 1))


def draw_hud(surface, player, zombies, npcs, debug, kills, civilian_kills,
             game_time: float = 8.0, day_t: float = 1.0,
             chunk_active: int = 0, chunk_loaded: int = 0,
             survival_day: int = 1, day_speed: int = 1,
             speed_mult: float = 1.0):
    font_lg = fonts.get(20)
    font_md = fonts.get(17)
    font_sm = fonts.get(14)
    font_xs = fonts.get(12)

    # ── Top-left: Day / Danger card ───────────────────────────────────────
    danger_key, danger_col = difficulty.get_danger(survival_day)
    CARD_W, CARD_H = 190, 54
    card = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
    card.fill((0, 0, 0, 145))
    surface.blit(card, (10, 10))
    pygame.draw.rect(surface, (60, 55, 45), (10, 10, CARD_W, CARD_H), 1, border_radius=3)
    # Left accent coloured by danger
    pygame.draw.rect(surface, danger_col, (10, 10, 3, CARD_H), border_radius=3)

    day_txt = f"{lang.t('hud_day')} {survival_day:02d}"
    dt_surf = fonts.get(22).render(day_txt, True, (240, 230, 200))
    surface.blit(dt_surf, (20, 15))
    dng_surf = font_sm.render(lang.t(danger_key), True, danger_col)
    surface.blit(dng_surf, (20, 38))
    kill_surf = font_sm.render(lang.t("hud_kills", kills), True, (175, 160, 130))
    surface.blit(kill_surf, (CARD_W - kill_surf.get_width() - 4, 38))

    # Debug additions to day card
    if debug:
        alive_npcs    = sum(1 for n in npcs if n.state == NPC.STATE_ALIVE)
        infected_npcs = sum(1 for n in npcs if n.state == NPC.STATE_INFECTED)
        dbg_lines = [
            (f"Z:{len(zombies)}  NPC:{alive_npcs}  I:{infected_npcs}", (170, 200, 160)),
            (f"X{int(player.pos.x):>6}  Y{int(player.pos.y):>6}",     (130, 130, 120)),
            (lang.t("dbg_chunk_s", chunk_active, chunk_loaded),          (120, 120, 110)),
        ]
        for i, (txt, col) in enumerate(dbg_lines):
            s = font_xs.render(txt, True, col)
            surface.blit(s, (12, 68 + i * 16))

    # ── Top-center: HP + Stamina bars ─────────────────────────────────────
    BAR_W  = 240
    bar_cx = WIDTH // 2
    bar_x  = bar_cx - BAR_W // 2

    # HP
    hp_ratio = player.hp / player.max_hp
    hp_col   = ((55, 200, 55) if hp_ratio > 0.5 else
                (215, 195, 45) if hp_ratio > 0.25 else (225, 50, 50))
    hp_lbl = font_sm.render(lang.t("hud_hp"), True, (190, 190, 185))
    surface.blit(hp_lbl, (bar_x - hp_lbl.get_width() - 6, 13))
    _bar(surface, bar_x, 14, BAR_W, 13, hp_ratio, hp_col, bg=(30, 30, 30))
    hp_val = font_xs.render(f"{int(player.hp)}/{int(player.max_hp)}", True, (220, 220, 215))
    surface.blit(hp_val, (bar_x + BAR_W // 2 - hp_val.get_width() // 2, 15))

    # Stamina
    st_ratio = player.stamina / player.max_stamina
    st_lbl   = font_xs.render(lang.t("hud_stamina"), True, (110, 150, 210))
    surface.blit(st_lbl, (bar_x - st_lbl.get_width() - 6, 32))
    _bar(surface, bar_x, 32, BAR_W, 7, st_ratio, (75, 150, 250), bg=(25, 25, 35))

    # Contextual status badge (below bars — only when relevant)
    if player.in_water:
        badge_txt, badge_col = lang.t("st_swimming"), (60, 160, 255)
    elif player.is_hidden:
        badge_txt, badge_col = lang.t("st_hidden"), (70, 215, 85)
    elif player._quiet and player._moving:
        badge_txt, badge_col = lang.t("st_quiet"), (80, 215, 165)
    else:
        badge_txt = badge_col = None

    if badge_txt:
        bs = font_sm.render(badge_txt, True, badge_col)
        bpw, bph = bs.get_width() + 18, bs.get_height() + 6
        bpx = bar_cx - bpw // 2
        bpy = 44
        badge_bg = pygame.Surface((bpw, bph), pygame.SRCALPHA)
        badge_bg.fill((0, 0, 0, 150))
        surface.blit(badge_bg, (bpx, bpy))
        pygame.draw.rect(surface, badge_col, (bpx, bpy, bpw, bph), 1, border_radius=10)
        surface.blit(bs, (bpx + 9, bpy + 3))

    # Civilian kills — dialogue notification below the day card
    if civilian_kills > 0:
        NF_W = CARD_W          # same width as day card
        NF_X = 10
        NF_Y = 10 + CARD_H + 6
        ACCENT = (200, 45, 35)

        line1 = font_sm.render(lang.t("civ_killed", civilian_kills), True, (240, 130, 120))
        line2 = font_xs.render(lang.t("civ_penalty", civilian_kills * 5), True, (190, 80, 70))
        NF_H  = 10 + line1.get_height() + 4 + line2.get_height() + 6

        nf_bg = pygame.Surface((NF_W, NF_H), pygame.SRCALPHA)
        nf_bg.fill((45, 5, 5, 185))
        surface.blit(nf_bg, (NF_X, NF_Y))
        pygame.draw.rect(surface, (80, 20, 18), (NF_X, NF_Y, NF_W, NF_H), 1, border_radius=3)
        pygame.draw.rect(surface, ACCENT, (NF_X, NF_Y, 3, NF_H), border_radius=3)

        # Small tail pointing up toward the day card
        tail_x = NF_X + 20
        tail_y = NF_Y
        pygame.draw.polygon(surface, ACCENT,
                            [(tail_x, tail_y - 5), (tail_x + 5, tail_y), (tail_x - 5, tail_y)])

        surface.blit(line1, (NF_X + 12, NF_Y + 8))
        surface.blit(line2, (NF_X + 12, NF_Y + 8 + line1.get_height() + 4))

    # ── Bottom: weapon slot bar ────────────────────────────────────────────
    _draw_slot_bar(surface, player, font_sm, font_md)

    # ── Bottom-left: active weapon panel ──────────────────────────────────
    _draw_weapon_panel(surface, player, font_md, font_sm)

    # ── Bottom-right: screws counter + ESC hint ────────────────────────────
    sc_txt  = f"⚙ {player.screws}"
    sc_surf = font_lg.render(sc_txt, True, (210, 195, 120))
    sc_x    = WIDTH - sc_surf.get_width() - 14
    sc_y    = SLOT_BAR_Y - sc_surf.get_height() - 6
    sc_bg   = pygame.Surface((sc_surf.get_width() + 16, sc_surf.get_height() + 6),
                              pygame.SRCALPHA)
    sc_bg.fill((0, 0, 0, 130))
    surface.blit(sc_bg, (sc_x - 8, sc_y - 3))
    surface.blit(sc_surf, (sc_x, sc_y))

    esc_s = font_xs.render(lang.t("hud_esc_hint"), True, (80, 75, 68))
    surface.blit(esc_s, (WIDTH - esc_s.get_width() - 10, HEIGHT - 20))

    # ── Clock (top-right, always visible) ─────────────────────────────────
    _draw_clock(surface, game_time, day_t, day_speed)

    # ── Debug extras ──────────────────────────────────────────────────────
    if debug:
        legend = [
            (lang.t("leg_noise"),  (255, 220, 0)),
            (lang.t("leg_sight"),  (200, 60,  60)),
            (lang.t("leg_loot"),   (200, 165, 60)),
            (lang.t("leg_states"), (180, 180, 160)),
        ]
        if speed_mult != 1.0:
            legend.append((f"SPD ×{speed_mult:g}", (100, 220, 255)))
        lx0 = WIDTH - 12
        for i, (text, color) in enumerate(legend):
            s = font_sm.render(text, True, color)
            surface.blit(s, (lx0 - s.get_width(), 56 + i * 20))

        dbg_hint = font_xs.render(
            lang.t("hint", lang.t("dbg_off"), lang.t("lang_switch")), True, (80, 80, 70))
        surface.blit(dbg_hint, (12, HEIGHT - 18))


# ── Screens ───────────────────────────────────────────────────────────────────

def draw_day_banner(surface, day_banner):
    """Large fading '— DAY N —' banner shown at the start of each day."""
    if not day_banner:
        return
    elapsed  = day_banner["max"] - day_banner["timer"]
    fade_in  = 0.5
    fade_out = 0.8
    if elapsed < fade_in:
        ratio = elapsed / fade_in
    elif day_banner["timer"] < fade_out:
        ratio = day_banner["timer"] / fade_out
    else:
        ratio = 1.0

    font_xl = fonts.get(58)
    font_sm = fonts.get(20)

    day_txt = f"— DAY {day_banner['day']} —"
    sub_txt = day_banner.get("sub", "")
    PH      = 140 if sub_txt else 106
    # Measure actual text width to size panel
    tw      = font_xl.size(day_txt)[0]
    PW      = max(480, tw + 80)
    px      = (WIDTH  - PW) // 2
    py      = HEIGHT // 2 - 190

    banner = pygame.Surface((PW, PH), pygame.SRCALPHA)
    banner.fill((4, 14, 4, int(245 * ratio)))
    pygame.draw.rect(banner,
                     (int(55 * ratio), int(195 * ratio), int(55 * ratio), int(210 * ratio)),
                     (0, 0, PW, PH), 2, border_radius=6)

    # "— DAY N —" in large warm-white
    tc = (int(255 * ratio), int(252 * ratio), int(190 * ratio))
    ts = font_xl.render(day_txt, True, tc)
    banner.blit(ts, (PW // 2 - ts.get_width() // 2, 18))

    if sub_txt:
        sc = (int(170 * ratio), int(230 * ratio), int(150 * ratio))
        ss = font_sm.render(sub_txt, True, sc)
        banner.blit(ss, (PW // 2 - ss.get_width() // 2, 90))

    surface.blit(banner, (px, py))


def draw_notifications(surface, notifications):
    """Stacked warning/event text near the top-center of the screen."""
    if not notifications:
        return
    font_sm  = fonts.get(17)
    base_y   = HEIGHT // 2 - 120
    for i, n in enumerate(notifications):
        ratio = min(1.0, n["timer"] / 1.2)
        c = n["color"]
        col = (int(c[0] * ratio), int(c[1] * ratio), int(c[2] * ratio))
        txt = font_sm.render(n["text"], True, col)
        x   = WIDTH // 2 - txt.get_width() // 2
        y   = base_y + i * 24
        # subtle dark backing strip
        backing = pygame.Surface((txt.get_width() + 16, txt.get_height() + 4),
                                 pygame.SRCALPHA)
        backing.fill((0, 0, 0, int(130 * ratio)))
        surface.blit(backing, (x - 8, y - 2))
        surface.blit(txt, (x, y))


def draw_quit_confirm(surface):
    """Semi-transparent quit confirmation dialog."""
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    surface.blit(overlay, (0, 0))

    font_lg = fonts.get(26)
    font_sm = fonts.get(18)
    PW, PH = 360, 140
    px = (WIDTH  - PW) // 2
    py = (HEIGHT - PH) // 2

    panel = pygame.Surface((PW, PH), pygame.SRCALPHA)
    panel.fill((20, 18, 14, 240))
    surface.blit(panel, (px, py))
    pygame.draw.rect(surface, (160, 60, 60), (px, py, PW, PH), 2, border_radius=4)

    ts = font_lg.render(lang.t("quit_title"), True, (240, 220, 180))
    surface.blit(ts, (px + PW // 2 - ts.get_width() // 2, py + 20))
    ys = font_sm.render(lang.t("quit_yes"), True, (220, 100, 100))
    surface.blit(ys, (px + PW // 2 - ys.get_width() // 2, py + 65))
    ns = font_sm.render(lang.t("quit_no"), True, (140, 180, 140))
    surface.blit(ns, (px + PW // 2 - ns.get_width() // 2, py + 95))


def draw_menu(surface, mouse_pos):
    return _menu_mod.draw_title(surface, mouse_pos, WIDTH, HEIGHT, VERSION)


def draw_options_screen(surface, mouse_pos):
    return _menu_mod.draw_options(surface, mouse_pos, WIDTH, HEIGHT)


def draw_game_over(surface, kills, screws):
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 190))
    surface.blit(overlay, (0, 0))

    cx = WIDTH // 2
    title_font = fonts.get(72)
    sub_font   = fonts.get(26)
    hint_font  = fonts.get(18)

    # Title with red glow
    import menu as _m
    _m._glow_text(surface, title_font, lang.t("over_title"),
                  col=(230, 55, 55), glow_col=(100, 10, 10),
                  cx=cx, cy=HEIGHT // 2 - 130, glow_r=4)

    for i, text in enumerate([
        lang.t("over_kills",  kills),
        lang.t("over_screws", screws),
    ]):
        s = sub_font.render(text, True, (200, 195, 185))
        surface.blit(s, (cx - s.get_width() // 2, HEIGHT // 2 - 30 + i * 42))

    # Hint
    hint = hint_font.render(lang.t("over_restart"), True, (140, 215, 140))
    surface.blit(hint, (cx - hint.get_width() // 2, HEIGHT // 2 + 80))


# ── Ghost ↔ entity converters ─────────────────────────────────────────────────

def _npc_from_ghost(g: GhostNPC) -> NPC:
    if getattr(g, 'is_shopkeeper', False):
        npc = ShopkeeperNPC(g.x, g.y, g.shopkeeper_type or "mart")
        return npc
    if getattr(g, 'is_sheriff', False):
        npc = Sheriff(g.x, g.y)
    else:
        npc = NPC(g.x, g.y)
    npc.hp               = max(1, g.hp)
    npc.state            = g.state if g.state != NPC.STATE_DEAD else NPC.STATE_ALIVE
    npc.infection_timer  = g.infection_timer
    npc._zombie_on_death = g.zombie_on_death
    npc.armed            = g.armed
    return npc


def _zombie_from_ghost(g: GhostZombie, day: int = 1) -> Zombie:
    z    = Zombie(g.x, g.y, g.kind, day=day)
    z.hp = max(1, min(g.hp, z.max_hp))
    return z


# ── New game ──────────────────────────────────────────────────────────────────

_VEH_CLS = {'car': Vehicle, 'motorcycle': Motorcycle,
            'tank': Tank, 'helicopter': Helicopter, 'airplane': Airplane}

# Debug speed multiplier — set from --speed-mult=N CLI arg
_DBG_SPEED_MULT: float = 1.0

def _vehicle_from_ghost(g: GhostVehicle) -> Vehicle:
    cls  = _VEH_CLS.get(getattr(g, 'kind', 'car'), Vehicle)
    v    = cls(g.x, g.y)
    v.hp   = max(1, min(g.hp, v._max_hp))
    v.fuel = max(0.0, min(g.fuel, v._max_fuel))
    if _DBG_SPEED_MULT != 1.0:
        v._max_speed *= _DBG_SPEED_MULT
        v._accel     *= _DBG_SPEED_MULT
    return v


_DBG_SPAWN_VEH:  str  = ""   # set from --tank/--heli/--airplane/--motor/--car
_DBG_SPAWN_WPNS: list = []   # set from --pistol/--rifle/--shotgun/... (can stack)

_DBG_WPN_FLAGS = {
    "--pistol":      "pistol",
    "--rifle":       "rifle",
    "--shotgun":     "shotgun",
    "--machinegun":  "machinegun",
    "--grenade":     "grenade",
    "--firegun":     "flamethrower",
    "--heal":        "heal_pack",
    "--lantern":     "lantern",
}


def _new_game():
    from entities import PLAYER_SPEED
    from items import WeaponDrop
    _net.reset_network()   # 멀티플레이 원격 상태 초기화
    chunk_manager = ChunkManager()
    px, py        = chunk_manager.find_safe_start()
    player        = Player(px, py)
    if _DBG_SPEED_MULT != 1.0:
        player.speed = int(PLAYER_SPEED * _DBG_SPEED_MULT)

    zones, gnpcs, gzombies, new_items, new_gvehs = chunk_manager.update(player.pos)
    npcs     = [_npc_from_ghost(g)     for g in gnpcs]
    zombies  = [_zombie_from_ghost(g)  for g in gzombies]
    vehicles = [_vehicle_from_ghost(g) for g in new_gvehs]

    if _DBG_SPAWN_VEH:
        cls = _VEH_CLS.get(_DBG_SPAWN_VEH, Vehicle)
        vehicles.append(cls(px + 80, py))

    for _wkind in _DBG_SPAWN_WPNS:
        player.pickup(WeaponDrop(_wkind, px, py))

    item_manager = ItemManager([])
    item_manager.items.extend(new_items)

    proj_manager = ProjectileManager()
    ptcl_manager = ParticleManager()
    spatial      = SpatialGrid(cell_size=200)

    camera   = Camera(WORLD_W, WORLD_H, WIDTH, HEIGHT)
    camera.x = player.pos.x - WIDTH / 2
    camera.y = player.pos.y - HEIGHT / 2

    minimap = Minimap(WORLD_W, WORLD_H)

    return (player, npcs, zombies, zones, vehicles,
            item_manager, proj_manager, ptcl_manager,
            camera, chunk_manager, spatial, minimap)


def _save_state(player, kills, civilian_kills, survival_day, game_time):
    _menu_mod.save_game({
        "px": player.pos.x, "py": player.pos.y,
        "hp": player.hp,    "screws": player.screws,
        "kills": kills,     "civilian_kills": civilian_kills,
        "survival_day": survival_day,
        "game_time": game_time,
        "gym_levels": player.gym_levels,
    })


def _apply_gym_levels(player):
    """Re-apply all gym upgrades from gym_levels dict (used on load)."""
    from shop import GYM_UPGRADES
    for stat_key, effect, _costs, _eff in GYM_UPGRADES:
        lv = player.gym_levels.get(stat_key, 0)
        if lv <= 0:
            continue
        total = effect * lv
        if stat_key == "stamina_regen":
            player._gym_stamina_bonus = total
        elif stat_key == "speed":
            player.speed += total
        elif stat_key == "max_hp":
            player.max_hp += int(total)
            player.hp = min(player.hp, player.max_hp)
        elif stat_key == "fist_dmg":
            fist = player.weapon_slots[5][0] if player.weapon_slots[5] else None
            if fist is not None:
                fist.damage += total


def _load_into_game(save, player, kills_ref, civil_ref, day_ref, gtime_ref):
    """Apply save dict onto a freshly created player; returns updated scalars."""
    player.pos.x  = save["px"]
    player.pos.y  = save["py"]
    player.hp     = max(1, save.get("hp", player.hp))
    player.screws = save.get("screws", player.screws)
    player.gym_levels = save.get("gym_levels", player.gym_levels)
    _apply_gym_levels(player)
    return (save.get("kills", 0), save.get("civilian_kills", 0),
            save.get("survival_day", 1), save.get("game_time", 8.0))


# ── Hot-reload (desktop only; skipped on Pygbag/WASM) ────────────────────────
_HR_POLL_FRAMES = 30
_HR_SAFE = {"lang"}   # modules that reload in-place without restart


def _hr_mtimes() -> dict:
    if sys.platform == "emscripten":
        return {}
    base = os.path.dirname(os.path.abspath(__file__))
    out: dict = {}
    for name in os.listdir(base):
        if name.endswith(".py"):
            path = os.path.join(base, name)
            try:
                out[path] = os.path.getmtime(path)
            except OSError:
                pass
    return out


def _hr_check(mtimes: dict, game_state: str, player,
              kills: int, civilian_kills: int,
              survival_day: int, game_time: float) -> bool:
    """Poll for changed .py files; return True if a restart was triggered."""
    if not mtimes:
        return False
    changed: list[str] = []
    for path, old in list(mtimes.items()):
        try:
            new = os.path.getmtime(path)
        except OSError:
            continue
        if new != old:
            changed.append(path)
            mtimes[path] = new
    if not changed:
        return False

    modules = {os.path.splitext(os.path.basename(p))[0] for p in changed}

    if "lang" in modules:
        try:
            importlib.reload(lang)
            print("[hot-reload] lang reloaded")
        except Exception as exc:
            print(f"[hot-reload] lang reload error: {exc}")

    if modules <= _HR_SAFE:
        return False

    if game_state == STATE_PLAY:
        try:
            _save_state(player, kills, civilian_kills, survival_day, game_time)
        except Exception:
            pass
    print(f"[hot-reload] restarting ({', '.join(sorted(modules - _HR_SAFE))})")
    os.execv(sys.executable, [sys.executable] + sys.argv)
    return True


# ── Main loop ─────────────────────────────────────────────────────────────────

async def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(TITLE)
    clock = pygame.time.Clock()

    fog_surf         = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    vision_mask_norm = _make_vision_mask(VISION_RADIUS,    FOG_ALPHA)
    vision_mask_lntn = _make_vision_mask(LANTERN_VISION_R, FOG_ALPHA)

    # Dynamic zoom for helicopter / airplane
    _zoom      = 1.0   # current smooth zoom (1.0 = normal, 2.0 = 2× zoom-out)
    _zoom_tgt  = 1.0
    _world_surf = pygame.Surface((WIDTH, HEIGHT))

    night_mode     = "--night" in sys.argv
    start_hour     = 22.0 if night_mode else GAME_START_HOUR
    _entities_mod.night_mode = night_mode   # zombies get night buffs

    # Day-speed multiplier: --fast-day = 20×, --day-speed N = N×
    _DAY_SPEED_CYCLE = [1, 5, 20, 60]
    day_speed = 1
    if "--fast-day" in sys.argv:
        day_speed = 20
    for _a in sys.argv:
        if _a.startswith("--day-speed="):
            try: day_speed = int(_a.split("=", 1)[1])
            except ValueError: pass

    # Debug speed multiplier: --speed-mult=N  (e.g. 3 = 3× walk + vehicle speed)
    global _DBG_SPEED_MULT, _DBG_SPAWN_VEH
    for _a in sys.argv:
        if _a.startswith("--speed-mult="):
            try: _DBG_SPEED_MULT = float(_a.split("=", 1)[1])
            except ValueError: pass

    # Debug vehicle spawn: --tank / --heli / --airplane / --motor / --car
    _DBG_VEH_FLAGS = {"--tank": "tank", "--heli": "helicopter",
                      "--airplane": "airplane", "--motor": "motorcycle", "--car": "car"}
    for _flag, _kind in _DBG_VEH_FLAGS.items():
        if _flag in sys.argv:
            _DBG_SPAWN_VEH = _kind
            break

    # Debug weapon spawn (stackable): --pistol --rifle --shotgun --machinegun
    #                                 --grenade --firegun --heal --lantern
    global _DBG_SPAWN_WPNS
    _DBG_SPAWN_WPNS = [_wkind for _flag, _wkind in _DBG_WPN_FLAGS.items()
                       if _flag in sys.argv]

    debug          = False
    game_state     = STATE_MENU
    _menu_buttons: list[tuple[str, pygame.Rect]] = []

    # ── Survival day system ────────────────────────────────────────────────
    survival_day   = 1
    # First dawn triggers after (DAY_START - GAME_START_HOUR + 24) % 24 hours
    _dawn_interval = (DAY_START - GAME_START_HOUR + 24) % 24  # = 22h for 8AM start
    _total_game_h  = 0.0          # cumulative in-game hours elapsed
    _next_dawn_h   = _dawn_interval  # game-hours until first dawn
    _mp_synced     = False        # 서버 시간 최초 동기화 완료 여부 (멀티)
    _zid_counter   = 0            # 내가 스폰한 좀비의 네트워크 ID 카운터
    _zpos_accum    = 0.0          # 좀비 위치 브로드캐스트 누적 (6Hz)
    _chunk_sync_accum = 0.0       # 청크 소유권 동기화 누적 (~0.5s)
    day_banner     = {"day": 1, "sub": "", "timer": 3.2, "max": 3.2}
    notifications  = []           # [{"text","color","timer"}, ...]
    kills          = 0
    civilian_kills = 0
    game_time      = start_hour

    # ── Loading screen: yield to browser before heavy world generation ────
    _lf = fonts.get(22)
    screen.fill((22, 24, 20))
    _lt = _lf.render(lang.t("loading"), True, (180, 180, 160))
    screen.blit(_lt, (WIDTH // 2 - _lt.get_width() // 2,
                       HEIGHT // 2 - _lt.get_height() // 2))
    pygame.display.flip()
    await asyncio.sleep(0)

    (player, npcs, zombies, zones, vehicles,
     item_manager, proj_manager, ptcl_manager,
     camera, chunk_manager, spatial, minimap) = _new_game()

    current_vehicle = None
    shop_mode       = False
    current_shop    = None
    shop_feedback   = ""
    shop_selected   = 0
    show_minimap    = False   # M key toggles full-screen minimap
    _current_town  = None   # town name of chunk player is currently in

    wave_timer         = WAVE_INTERVAL
    mouse_just_pressed = False
    space_just_pressed = False
    _frozen_frame      = None    # screenshot captured when entering pause
    _prev_state        = STATE_PLAY   # used so OPTIONS knows where to return
    _pause_feedback    = ""      # "✓ 저장 완료" transient message
    _pause_fb_timer    = 0.0

    _hr_watch   = _hr_mtimes()   # empty dict on WASM
    _hr_frame   = 0
    _gc_timer   = 0.0            # 수동 GC 타이머
    _canopy_surf: pygame.Surface | None = None  # 포레스트 캐노피 재사용

    _menu_mod.load_settings()
    touch = TouchOverlay(WIDTH, HEIGHT)
    touch.visible = _menu_mod.get_setting("joystick", False)

    # 멀티플레이 접속은 메인 메뉴의 "멀티플레이" 버튼에서 트리거된다.

    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        mouse_just_pressed = False
        space_just_pressed = False
        touch.update(dt)

        # ── Events ─────────────────────────────────────────────────────────
        for event in pygame.event.get():
            # Touch controls consume FINGER events first
            if touch.handle_event(event):
                continue

            if event.type == pygame.KEYDOWN:
                _scan_held.add(event.scancode)
            elif event.type == pygame.KEYUP:
                _scan_held.discard(event.scancode)

            if event.type == pygame.QUIT:
                if game_state == STATE_PLAY:
                    _save_state(player, kills, civilian_kills,
                                survival_day, game_time)
                running = False

            if event.type == pygame.KEYDOWN:
                # ── Title / Options screens: mouse-driven, ESC goes back ───
                if game_state in (STATE_MENU, STATE_OPTIONS):
                    if _ek(event, pygame.K_ESCAPE) and game_state == STATE_OPTIONS:
                        game_state = _prev_state
                    continue

                # ── Pause: ESC resumes ─────────────────────────────────────
                if game_state == STATE_PAUSE:
                    if _ek(event, pygame.K_ESCAPE):
                        game_state    = STATE_PLAY
                        _frozen_frame = None
                    continue

                # ── Game Over: any confirm key → main menu ─────────────────
                if game_state == STATE_OVER:
                    if _ek(event, pygame.K_RETURN) or _ek(event, pygame.K_ESCAPE):
                        (player, npcs, zombies, zones, vehicles,
                         item_manager, proj_manager, ptcl_manager,
                         camera, chunk_manager, spatial, minimap) = _new_game()
                        kills = 0; civilian_kills = 0
                        game_time = start_hour; current_vehicle = None
                        shop_mode = False; current_shop = None
                        show_minimap = False; _current_town = None
                        survival_day = 1; _total_game_h = 0.0
                        _next_dawn_h = _dawn_interval
                        day_banner   = {"day": 1, "sub": "", "timer": 3.2, "max": 3.2}
                        notifications = []; difficulty.current_day = 1
                        game_state = STATE_MENU
                    continue

                # ── Play keys ─────────────────────────────────────────────
                if game_state == STATE_PLAY:
                    if _ek(event, pygame.K_ESCAPE):
                        if (isinstance(current_vehicle, Airplane)
                                and current_vehicle.targeting):
                            current_vehicle.targeting = False  # 타겟팅 취소
                        elif shop_mode:
                            shop_mode    = False
                            current_shop = None
                            shop_feedback = ""
                        elif show_minimap:
                            show_minimap = False
                        else:
                            game_state    = STATE_PAUSE
                            _frozen_frame = screen.copy()
                            _pause_feedback = ""
                            _pause_fb_timer = 0.0
                    if event.key == pygame.K_F1:
                        debug = not debug
                    if event.key == pygame.K_RIGHTBRACKET:
                        idx = _DAY_SPEED_CYCLE.index(day_speed) \
                              if day_speed in _DAY_SPEED_CYCLE else 0
                        day_speed = _DAY_SPEED_CYCLE[(idx + 1) % len(_DAY_SPEED_CYCLE)]
                    if _ek(event, pygame.K_l):
                        lang.toggle()
                    if _ek(event, pygame.K_m):
                        show_minimap = not show_minimap
                        shop_mode    = False   # close shop if open
                    # Weapon slot switching: 0 = melee, 1–5 = ranged slots
                    slot_keys = {
                        pygame.K_0: 5,
                        pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2,
                        pygame.K_4: 3, pygame.K_5: 4,
                    }
                    for _sk, _si in slot_keys.items():
                        if _ek(event, _sk):
                            player.switch_slot(_si)
                            break

                    # R — reload
                    if _ek(event, pygame.K_r):
                        w = player.weapon
                        if w and not isinstance(w, MeleeWeapon):
                            w.start_reload()

                    # Space fires (single-shot pulse)
                    if _ek(event, pygame.K_SPACE):
                        space_just_pressed = True

                    # E — vehicle enter/exit OR door toggle
                    if _ek(event, pygame.K_e):
                        if current_vehicle is not None:
                            # Block exit when helicopter/airplane is airborne
                            if getattr(current_vehicle, 'altitude', 0.0) > 0.1:
                                pass   # can't exit mid-air
                            else:
                                exit_spd = abs(current_vehicle.speed)
                                exit_pos = current_vehicle.leave()
                                player.pos = exit_pos
                                current_vehicle = None
                                # Roll damage: speed > 200 px/s hurts
                                if exit_spd > 200:
                                    roll_dmg = int((exit_spd - 200) / 8)
                                    roll_dmg = min(roll_dmg, 60)
                                    player.take_damage(roll_dmg)
                                    camera.add_shake(roll_dmg * 0.25)
                        else:
                            # Try boarding a nearby vehicle first
                            boarded = False
                            for v in vehicles:
                                if v.is_near(player.pos):
                                    if v.enter():
                                        current_vehicle = v
                                        boarded = True
                                    break
                            # Otherwise toggle nearest hideout door (non-shop)
                            if not boarded:
                                for zone in zones:
                                    if (zone.zone_type == "hideout"
                                            and not getattr(zone, 'shop_type', None)
                                            and zone.near_door(player.pos)):
                                        zone.toggle_door()
                                        break

                    # T — open/close shop via nearby shopkeeper NPC
                    if _ek(event, pygame.K_t):
                        if shop_mode:
                            shop_mode    = False
                            current_shop = None
                            shop_feedback = ""
                        elif current_vehicle is None:
                            from entities import SHOPKEEPER_INTERACT_R
                            for _npc in npcs:
                                if (isinstance(_npc, ShopkeeperNPC)
                                        and _npc.pos.distance_to(player.pos)
                                            < SHOPKEEPER_INTERACT_R):
                                    shop_mode     = True
                                    current_shop  = _npc
                                    shop_selected = 0
                                    shop_feedback = ""
                                    break

                    # Shop navigation & purchase (only when shop_mode)
                    if shop_mode and current_shop is not None:
                        from shop import SHOP_CATALOG, _get_upgrade_items, GYM_UPGRADES
                        if current_shop.shop_type == "gym":
                            catalog_len = len(GYM_UPGRADES)
                        else:
                            base_len    = len(SHOP_CATALOG.get(current_shop.shop_type, []))
                            upg_len     = len(_get_upgrade_items(player)) if current_shop.shop_type == "weapon" else 0
                            catalog_len = base_len + upg_len
                        if _ek(event, pygame.K_UP):
                            shop_selected = (shop_selected - 1) % max(1, catalog_len)
                        elif _ek(event, pygame.K_DOWN):
                            shop_selected = (shop_selected + 1) % max(1, catalog_len)
                        else:
                            # Number keys 1–9
                            num_map = {
                                pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2,
                                pygame.K_4: 3, pygame.K_5: 4, pygame.K_6: 5,
                                pygame.K_7: 6, pygame.K_8: 7, pygame.K_9: 8,
                            }
                            for _nk, _ni in num_map.items():
                                if _ek(event, _nk):
                                    shop_feedback = try_purchase(
                                        player, current_shop.shop_type, _ni,
                                        current_vehicle)
                                    break
                            else:
                                if _ek(event, pygame.K_RETURN):
                                    shop_feedback = try_purchase(
                                        player, current_shop.shop_type, shop_selected,
                                        current_vehicle)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_just_pressed = True
                # ── Pause menu clicks ─────────────────────────────────────────
                if game_state == STATE_PAUSE:
                    mx, my = pygame.mouse.get_pos()
                    for action, rect in _menu_buttons:
                        if rect.collidepoint(mx, my):
                            if action == "resume":
                                game_state    = STATE_PLAY
                                _frozen_frame = None
                            elif action == "save":
                                _save_state(player, kills, civilian_kills,
                                            survival_day, game_time)
                                _pause_feedback = lang.t("pause_saved")
                                _pause_fb_timer = 2.5
                            elif action == "settings":
                                _prev_state = STATE_PAUSE
                                game_state  = STATE_OPTIONS
                            elif action == "mainmenu":
                                _save_state(player, kills, civilian_kills,
                                            survival_day, game_time)
                                _frozen_frame = None
                                game_state    = STATE_MENU
                            elif action == "quit":
                                _save_state(player, kills, civilian_kills,
                                            survival_day, game_time)
                                running = False
                            break

                # ── Menu / Options button clicks ──────────────────────────────
                if game_state in (STATE_MENU, STATE_OPTIONS):
                    mx, my = pygame.mouse.get_pos()
                    for action, rect in _menu_buttons:
                        if rect.collidepoint(mx, my):
                            if action in ("singleplayer", "multiplayer"):
                                _is_mp = (action == "multiplayer")
                                if _is_mp:
                                    # 서버 접속 (백그라운드). 실패해도 게임은 진행.
                                    asyncio.ensure_future(_net.connect_to_server())
                                else:
                                    _net.go_offline()   # 싱글: 네트워크 차단
                                (player, npcs, zombies, zones, vehicles,
                                 item_manager, proj_manager, ptcl_manager,
                                 camera, chunk_manager, spatial, minimap) = _new_game()
                                kills = 0; civilian_kills = 0
                                game_time = start_hour; current_vehicle = None
                                shop_mode = False; current_shop = None
                                show_minimap = False; _current_town = None
                                survival_day = 1; _total_game_h = 0.0
                                _next_dawn_h = _dawn_interval
                                _mp_synced = False
                                day_banner = {"day": 1, "sub": "", "timer": 3.2, "max": 3.2}
                                notifications = []
                                difficulty.current_day = 1
                                game_state = STATE_PLAY
                            elif action == "options":
                                _prev_state = STATE_MENU
                                game_state  = STATE_OPTIONS
                            elif action == "back":
                                game_state = _prev_state
                            elif action.startswith("lang_"):
                                lang.set_lang(action[5:])
                            elif action == "toggle_joystick":
                                _menu_mod.set_setting("joystick",
                                    not _menu_mod.get_setting("joystick", False))
                                touch.visible = _menu_mod.get_setting("joystick", False)
                            break

        # ── Non-play states that skip simulation entirely ──────────────────
        if game_state not in (STATE_PLAY, STATE_PAUSE):
            _menu_mod.update(dt)
            mpos = pygame.mouse.get_pos()
            if game_state == STATE_MENU:
                _menu_buttons = draw_menu(screen, mpos)
            elif game_state == STATE_OPTIONS:
                _menu_buttons = draw_options_screen(screen, mpos)
            else:  # STATE_OVER
                _menu_mod._draw_bg(screen)
                draw_game_over(screen, kills, player.screws)
            pygame.display.flip()
            await asyncio.sleep(0)
            continue

        # ── Pause: show frozen frame + overlay (no simulation) ────────────
        if game_state == STATE_PAUSE:
            if _frozen_frame:
                screen.blit(_frozen_frame, (0, 0))
            _pause_fb_timer = max(0.0, _pause_fb_timer - dt)
            fb = _pause_feedback if _pause_fb_timer > 0 else ""
            mpos = pygame.mouse.get_pos()
            _menu_buttons = _menu_mod.draw_pause_menu(screen, mpos, WIDTH, HEIGHT, fb)
            pygame.display.flip()
            await asyncio.sleep(0)
            continue

        # ── Aiming ─────────────────────────────────────────────────────────
        mouse_pos = pygame.Vector2(pygame.mouse.get_pos())
        if _zoom > 1.001:
            # Zoom-corrected: mouse position maps to a wider world area
            world_mouse = pygame.Vector2(
                camera.x - (WIDTH * _zoom - WIDTH) * 0.5 + mouse_pos.x * _zoom,
                camera.y - (HEIGHT * _zoom - HEIGHT) * 0.5 + mouse_pos.y * _zoom,
            )
        else:
            world_mouse = camera.to_world(mouse_pos.x, mouse_pos.y)
        aim_vec     = world_mouse - player.pos
        if aim_vec.length_squared() > 0:
            player.aim_dir = aim_vec.normalize()

        keys   = _Keys(pygame.key.get_pressed(), _scan_held, touch.key_overrides())
        bounds = (WORLD_W, WORLD_H)

        # Tell zombie contact-damage system which vehicle the player is in
        player._riding = current_vehicle

        # ── Vehicle driving (overrides player movement) ─────────────────────
        if current_vehicle is not None:
            if current_vehicle.alive:
                wall_dmg = current_vehicle.update_drive(dt, keys, bounds, zones)
                player.pos = pygame.Vector2(current_vehicle.pos)
                player._moving = False
                if wall_dmg > 0:
                    player.take_damage(wall_dmg // 2)
                    camera.add_shake(wall_dmg * 0.15)
                # Tank rams a building → instant destroy
                _rammed = current_vehicle._last_hit_zone
                if (_rammed is not None
                        and isinstance(current_vehicle, Tank)
                        and abs(current_vehicle.speed) > 60):
                    _rammed.take_damage(9999)
                    ptcl_manager.vehicle_explosion(current_vehicle.pos, 90)
                    camera.add_shake(12.0)
                # Tank / any vehicle crushes parked vehicles
                if isinstance(current_vehicle, Tank) and abs(current_vehicle.speed) > 40:
                    for _v in vehicles:
                        if _v.alive and _v is not current_vehicle:
                            if current_vehicle.pos.distance_to(_v.pos) < current_vehicle._hl + _v._hl:
                                _v.take_damage(9999)
                if not current_vehicle.alive:
                    current_vehicle._exploded = True
                    ptcl_manager.vehicle_explosion(current_vehicle.pos, VEH_EXPLODE_R)
                    camera.add_shake(14.0)
                    player.take_damage(player.max_hp)
                    current_vehicle = None

                # ── Tank: turret tracking + cannon fire ────────────────────
                elif isinstance(current_vehicle, Tank):
                    current_vehicle.update_turret(world_mouse)
                    if mouse_just_pressed or space_just_pressed:
                        result = current_vehicle.fire_cannon(world_mouse)
                        if result is not None:
                            blast_pos, blast_r = result
                            bvec = pygame.Vector2(blast_pos)
                            ptcl_manager.explosion(bvec, blast_r)
                            camera.add_shake(10.0)
                            for _z in zombies:
                                if _z.alive:
                                    d = _z.pos.distance_to(bvec)
                                    if d < blast_r:
                                        kv = ((_z.pos - bvec).normalize()
                                              if (_z.pos - bvec).length_squared() > 0
                                              else pygame.Vector2(1, 0))
                                        _z.take_hit(int(260 * (1 - d / blast_r)), kv)
                            # NPC (civilian) damage
                            for _npc in npcs:
                                if _npc.state != "dead":
                                    _dn = _npc.pos.distance_to(bvec)
                                    if _dn < blast_r:
                                        _npc.take_hit(int(260 * (1 - _dn / blast_r)),
                                                      from_player=True, from_bullet=True)
                                        if _npc.state == "dead":
                                            civilian_kills += 1
                            # Building damage
                            for _zone in zones:
                                if isinstance(_zone, HideoutCompound) and not _zone.destroyed:
                                    _cx = max(_zone.rect.left, min(bvec.x, _zone.rect.right))
                                    _cy = max(_zone.rect.top,  min(bvec.y, _zone.rect.bottom))
                                    _db = math.sqrt((_cx - bvec.x)**2 + (_cy - bvec.y)**2)
                                    if _db < blast_r:
                                        _zone.take_damage(int(200 * (1 - _db / blast_r)))
                            # Vehicle damage from cannon
                            for _v in vehicles:
                                if _v.alive and _v is not current_vehicle:
                                    _dv = _v.pos.distance_to(bvec)
                                    if _dv < blast_r + _v._hl:
                                        _v.take_damage(int(300 * max(0, 1 - _dv / blast_r)))

                # ── Helicopter: player-aimed minigun ──────────────────────
                elif isinstance(current_vehicle, Helicopter):
                    _held_space = keys[pygame.K_SPACE]
                    _shots = current_vehicle.fire_weapon(dt, _held_space, world_mouse)
                    for _orig, _dir, _dmg, _spd in _shots:
                        _b = Bullet(_orig, _dir * _spd, _dmg,
                                    (120, 220, 255), owner="player")
                        _b.radius = 4
                        proj_manager.add([_b])
                        ptcl_manager.muzzle_flash(_orig, _dir)
                        camera.add_shake(0.4)

                # ── Airplane: Space①=목표표시 / Space②=투하 / ESC=취소 ────
                elif isinstance(current_vehicle, Airplane):
                    if space_just_pressed:
                        if not current_vehicle.targeting:
                            # 1차 Space: 타겟 모드 진입
                            if current_vehicle._bomb_cd <= 0 and current_vehicle.is_airborne:
                                current_vehicle.targeting = True
                        else:
                            # 2차 Space: 투하
                            _bombs = current_vehicle.carpet_bomb()
                            if _bombs:
                                camera.add_shake(18.0)
                                for _bpos, _br in _bombs:
                                    _bvec = pygame.Vector2(_bpos)
                                    ptcl_manager.vehicle_explosion(_bvec, _br)
                                    for _z in zombies:
                                        if _z.alive:
                                            _d = _z.pos.distance_to(_bvec)
                                            if _d < _br:
                                                _kv = ((_z.pos - _bvec).normalize()
                                                       if (_z.pos - _bvec).length_squared() > 0
                                                       else pygame.Vector2(0, 1))
                                                _z.take_hit(int(300 * (1 - _d / _br)), _kv)
                                    for _npc in npcs:
                                        if _npc.state != "dead":
                                            _dn = _npc.pos.distance_to(_bvec)
                                            if _dn < _br:
                                                _npc.take_hit(int(300 * (1 - _dn / _br)),
                                                              from_player=True, from_bullet=True)
                                                if _npc.state == "dead":
                                                    civilian_kills += 1
                                    for _zone in zones:
                                        if isinstance(_zone, HideoutCompound):
                                            _cx = max(_zone.rect.left, min(_bvec.x, _zone.rect.right))
                                            _cy = max(_zone.rect.top,  min(_bvec.y, _zone.rect.bottom))
                                            _db = math.sqrt((_cx-_bvec.x)**2+(_cy-_bvec.y)**2)
                                            if _db < _br:
                                                _zone.take_damage(9999)
                                    for _v in vehicles:
                                        if _v.alive and _v is not current_vehicle:
                                            if _v.pos.distance_to(_bvec) < _br + _v._hl:
                                                _v.take_damage(9999)

            else:
                # Vehicle destroyed externally (roadkill overflow)
                current_vehicle._exploded = True
                ptcl_manager.vehicle_explosion(current_vehicle.pos, VEH_EXPLODE_R)
                camera.add_shake(12.0)
                player.take_damage(player.max_hp)
                current_vehicle = None

        # ── Touch: 단발 버튼 → 게임 액션 주입 ─────────────────────────────
        if touch.visible:
            # PAUSE 버튼 — 상태 무관하게 작동
            if touch.just_pause:
                if game_state == STATE_PLAY:
                    game_state    = STATE_PAUSE
                    _frozen_frame = screen.copy()
                    _pause_feedback = ""
                    _pause_fb_timer  = 0.0
                elif game_state == STATE_PAUSE:
                    game_state    = STATE_PLAY
                    _frozen_frame = None

        if touch.visible and game_state == STATE_PLAY:
            # 무기 슬롯 탭
            if touch.just_slot is not None:
                player.switch_slot(touch.just_slot)

            if touch.just_reload:
                w = player.weapon
                if w and not isinstance(w, MeleeWeapon):
                    w.start_reload()
            if touch.just_e:
                # 차량 탑승/하차 또는 문 열기
                if current_vehicle is not None:
                    if getattr(current_vehicle, 'altitude', 0.0) <= 0.1:
                        exit_spd = abs(current_vehicle.speed)
                        player.pos = current_vehicle.leave()
                        current_vehicle = None
                        if exit_spd > 200:
                            player.take_damage(min(60, int((exit_spd-200)/8)))
                else:
                    for v in vehicles:
                        if v.is_near(player.pos) and v.enter():
                            current_vehicle = v; break
                    else:
                        for zone in zones:
                            if (zone.zone_type == "hideout"
                                    and not getattr(zone,'shop_type',None)
                                    and zone.near_door(player.pos)):
                                zone.toggle_door(); break
            if touch.just_space:
                space_just_pressed = True
            # 조이스틱 방향 → aim 방향 동기화
            _tdir = touch.aim_dir()
            if _tdir is not None:
                player.aim_dir = _tdir
            # fire 버튼 → held_mouse 처럼 처리
            if touch.fire_held:
                mouse_just_pressed = True

        # ── Update: player ──────────────────────────────────────────────────
        if current_vehicle is None:
            player.handle_input(keys, dt, bounds, zones)
        player.is_hidden = any(z.hidden and z.contains(player.pos) for z in zones)

        # Tick all weapon slots (cooldowns + reload timers)
        for slot_list in player.weapon_slots:
            for w in slot_list:
                w.tick(dt)

        # ── Multiplayer sync (20Hz 송신 + 매 프레임 원격 보간) ──────────────
        # 오프라인(DummyTransport)이면 원격 보간만 돌고 즉시 반환 → 비용 0.
        await sync_network_data(player, survival_day, dt, current_vehicle)

        # 접속 결과 알림 (한 번만)
        if _net.connect_status:
            _st = _net.connect_status
            _net.connect_status = ""
            _msg = {"connected": ("mp_connected", (90, 255, 120)),
                    "full":      ("mp_full",      (255, 120, 60)),
                    "failed":    ("mp_failed",    (255, 180, 60))}.get(_st)
            if _msg:
                notifications.append({"text": lang.t(_msg[0]),
                                      "color": _msg[1], "timer": 4.0})

        # ── Exploration tracking ────────────────────────────────────────────
        # Vehicles are loud — reveal more around them
        extra_r = 300 if current_vehicle is not None else 0
        minimap.explore(player.pos, extra_r)

        # ── Camera ──────────────────────────────────────────────────────────
        camera.update(player.pos, dt)
        camera.begin_frame()
        ox, oy = camera.offset()

        # ── Zoom (wide view when helicopter / airplane is in use) ────────────
        if current_vehicle is not None and isinstance(current_vehicle, Helicopter):
            # Helicopter: always zoom out (1.4× base) + extra by altitude
            _zoom_tgt = 1.4 + getattr(current_vehicle, 'altitude', 0.0) * 0.7
        elif current_vehicle is not None and isinstance(current_vehicle, Airplane):
            # Airplane: zoom increases as it climbs (auto-altitude)
            _zoom_tgt = 1.0 + getattr(current_vehicle, 'altitude', 0.0) * 1.3
        else:
            _zoom_tgt = 1.0
        _zoom += (_zoom_tgt - _zoom) * min(1.0, 4.0 * dt)
        _zoom  = max(1.0, min(2.5, _zoom))
        _vw    = int(WIDTH  * _zoom)
        _vh    = int(HEIGHT * _zoom)
        if _world_surf.get_size() != (_vw, _vh):
            _world_surf = pygame.Surface((_vw, _vh))
        if fog_surf.get_size() != (_vw, _vh):
            fog_surf = pygame.Surface((_vw, _vh), pygame.SRCALPHA)
        # Viewport top-left in world coords — expand outward from camera centre
        _vox = max(0, min(max(0, WORLD_W - _vw),
                          camera._ox - (_vw - WIDTH)  // 2))
        _voy = max(0, min(max(0, WORLD_H - _vh),
                          camera._oy - (_vh - HEIGHT) // 2))

        def _vis(pos, margin=60):
            sx = pos.x - _vox; sy = pos.y - _voy
            return -margin < sx < _vw + margin and -margin < sy < _vh + margin

        # ── Vehicle noise (attracts zombies when engine is running) ────────
        if current_vehicle is not None and abs(current_vehicle.speed) > 30:
            player.noise_radius = min(500.0,
                                      abs(current_vehicle.speed) * 0.6)
            for _z in zombies:
                if (_z.alive
                        and _z.pos.distance_to(player.pos) <= player.noise_radius):
                    _z.alert(player.pos)
        elif current_vehicle is None:
            pass  # normal noise set by player.handle_input already

        # ── Firing / Melee ──────────────────────────────────────────────────
        # On foot: any weapon. In vehicle: ranged only (no melee swing).
        # Tank uses LMB for cannon, so suppress player gun there.
        if current_vehicle is None:
            w = player.weapon
        elif isinstance(current_vehicle, Tank):
            w = None
        else:
            w = player.weapon
            if w and isinstance(w, MeleeWeapon):
                w = None  # can't swing melee from a vehicle
        if w and isinstance(w, MeleeWeapon):
            # ── Melee attack ─────────────────────────────────────────────
            one_shot = mouse_just_pressed or space_just_pressed
            if one_shot and w.can_attack():
                w.start_swing()
            # Hit detection every frame (arc is active for swing_dur)
            hit_zs = w.get_hits(player.pos, player.aim_dir, zombies)
            kd = player.aim_dir if player.aim_dir.length_squared() > 0.01 \
                 else pygame.Vector2(0, -1)
            is_strong = (w.kind == "fist" and
                         getattr(w, '_active_combo', 0) == 2)
            shake = (3.5 if is_strong else
                     1.8 if w.kind == "knuckle" else 1.2)
            for z in hit_zs:
                z.take_melee_hit(int(w.hit_damage), kd, w.hit_knockback)
                ptcl_manager.muzzle_flash(z.pos, -kd)
                camera.add_shake(shake)

            # NPC melee hit — same arc check, reuse swing state
            if w.is_swinging:
                _ad      = player.aim_dir.normalize() if player.aim_dir.length_squared() > 0.01 else pygame.Vector2(0,-1)
                _half_a  = __import__('math').radians(w.arc_deg / 2)
                for _npc in npcs:
                    if _npc.state == NPC.STATE_DEAD or id(_npc) in w._hit_ids:
                        continue
                    _d = player.pos.distance_to(_npc.pos)
                    if _d > w.reach + _npc.radius:
                        continue
                    _to = _npc.pos - player.pos
                    if _to.length_squared() > 0.01:
                        import math as _m
                        _cos = _ad.dot(_to.normalize())
                        if _m.acos(max(-1.0, min(1.0, _cos))) > _half_a:
                            continue
                    w._hit_ids.add(id(_npc))
                    _npc.take_hit(int(w.hit_damage), from_player=True)
                    # Set flee direction away from player immediately
                    if _npc.state == NPC.STATE_PANIC:
                        _away = _npc.pos - player.pos
                        if _away.length_squared() > 0:
                            _npc._direction = _away.normalize()
                    ptcl_manager.muzzle_flash(_npc.pos, -kd)
                    camera.add_shake(shake)
                    if _npc.state == NPC.STATE_DEAD:
                        civilian_kills += 1
                        player.screws = max(0, player.screws - 5)
                    Sheriff.alert_nearby(npcs, _npc.pos)

            # ── PvP 근접: 원격 플레이어 적중 (멀티) ──────────────────────
            if w.is_swinging and remote_players:
                import math as _m
                _ad     = player.aim_dir.normalize() if player.aim_dir.length_squared() > 0.01 else pygame.Vector2(0, -1)
                _half_a = _m.radians(w.arc_deg / 2)
                for _pid, _rp in remote_players.items():
                    _hid = ("mp", _pid)
                    if not _rp.alive or _hid in w._hit_ids:
                        continue
                    _d = player.pos.distance_to(_rp.render_pos)
                    if _d > w.reach + _rp.radius:
                        continue
                    _to = _rp.render_pos - player.pos
                    if _to.length_squared() > 0.01:
                        _cos = _ad.dot(_to.normalize())
                        if _m.acos(max(-1.0, min(1.0, _cos))) > _half_a:
                            continue
                    w._hit_ids.add(_hid)
                    _net.send_hit(_pid, int(w.hit_damage), kd)
                    ptcl_manager.muzzle_flash(_rp.render_pos, -kd)
                    camera.add_shake(shake)

            # ── 멀티 근접: 원격 좀비 타격 → 소유자에 보고 ────────────────
            if w.is_swinging and _net.remote_zombies:
                import math as _m
                _ad     = player.aim_dir.normalize() if player.aim_dir.length_squared() > 0.01 else pygame.Vector2(0, -1)
                _half_a = _m.radians(w.arc_deg / 2)
                for _zid, _rz in _net.remote_zombies.items():
                    _hid = ("mz", _zid)
                    if not _rz.alive or _hid in w._hit_ids:
                        continue
                    _d = player.pos.distance_to(_rz.pos)
                    if _d > w.reach + _rz.radius:
                        continue
                    _to = _rz.pos - player.pos
                    if _to.length_squared() > 0.01:
                        _cos = _ad.dot(_to.normalize())
                        if _m.acos(max(-1.0, min(1.0, _cos))) > _half_a:
                            continue
                    w._hit_ids.add(_hid)
                    _net.send_zombie_hit(getattr(_rz, '_owner', None), _zid,
                                         int(w.hit_damage), kd)
                    ptcl_manager.muzzle_flash(_rz.pos, -kd)
                    camera.add_shake(shake)

        elif w:
            # ── Ranged attack ─────────────────────────────────────────────
            held_mouse = pygame.mouse.get_pressed()[0] or touch.fire_held
            held_space = keys[pygame.K_SPACE]
            one_shot   = mouse_just_pressed or space_just_pressed
            auto_fire  = held_mouse or held_space

            fire = (w.kind in ("machinegun", "flamethrower") and auto_fire) or \
                   (w.kind not in ("machinegun", "flamethrower") and one_shot)

            if fire and w.can_fire() and w.kind not in PASSIVE_WEAPONS:
                if w.kind == "grenade":
                    # Clamp throw target to max range
                    _gvec = world_mouse - player.pos
                    _gdist = _gvec.length()
                    if _gdist > GRENADE_MAX_RANGE:
                        _gtgt = player.pos + _gvec.normalize() * GRENADE_MAX_RANGE
                    else:
                        _gtgt = pygame.Vector2(world_mouse)
                    _gdist_clamped = max(20, (_gtgt - player.pos).length())
                    _gdir  = (_gtgt - player.pos).normalize()
                    # Speed scales with distance — grenade reaches ~target pos at fuse
                    _gspeed = min(w.bullet_speed * 2.2,
                                  _gdist_clamped / (w.fuse_time * 0.52))
                    g = Grenade(
                        origin=pygame.Vector2(player.pos),
                        vel=_gdir * _gspeed,
                        damage=w.damage,
                        blast_radius=w.blast_radius,
                        fuse_time=w.fuse_time,
                    )
                    proj_manager.add([g])
                    w.consume_shot()
                    player._throw_anim = GRENADE_THROW_DUR
                    camera.add_shake(1.5)

                elif w.kind == "heal_pack":
                    player.hp = min(player.max_hp, player.hp + w.heal_amount)
                    w.consume_shot()
                    ptcl_manager.heal_effect(player.pos)

                elif w.kind == "flamethrower":
                    # Spawn a cone of flame particles
                    import math as _m
                    _base_ang = _m.atan2(player.aim_dir.y, player.aim_dir.x)
                    _half     = _m.radians(w.spread_angle / 2)
                    _flames   = []
                    for _ in range(w.spread_count):
                        _ang = _base_ang + random.uniform(-_half, _half)
                        _spd = w.bullet_speed * random.uniform(0.85, 1.15)
                        _dir = pygame.Vector2(_m.cos(_ang), _m.sin(_ang))
                        _flames.append(Flame(player.pos, _dir, _spd, w.damage))
                    proj_manager.add(_flames)
                    w.consume_shot()
                    player._flamethrowing = True
                    camera.add_shake(0.3)

                else:
                    bullets = _create_bullets(w, player.pos, player.aim_dir)
                    proj_manager.add(bullets)
                    w.consume_shot()
                    ptcl_manager.muzzle_flash(player.pos, player.aim_dir)
                    camera.add_shake(2.5 if w.kind == "shotgun" else 1.2)
                    noise_r = GUN_NOISE_RADII.get(w.kind, 0)
                    if noise_r > 0:
                        for _z in zombies:
                            if _z.alive and _z.pos.distance_to(player.pos) <= noise_r:
                                _z.alert(player.pos)
                        for _npc in npcs:
                            if _npc.pos.distance_to(player.pos) <= noise_r:
                                _npc.hear_gunshot(player.pos)

        # ── Chunk streaming (멀티: 소유 청크에서만 좀비 스폰) ───────────────
        zones, new_gnpcs, new_gzombies, new_items, new_gvehs = \
            chunk_manager.update(player.pos, chunk_allowed=_net.is_chunk_owned)

        # 청크 소유권 동기화 (~0.5s 주기)
        _chunk_sync_accum += dt
        if _net.transport.connected and _chunk_sync_accum >= 0.5:
            _chunk_sync_accum = 0.0
            _akeys = {f"{cx},{cy}" for (cx, cy) in chunk_manager._active_keys}
            await _net.sync_chunk_ownership(_akeys)
        npcs.extend    (_npc_from_ghost(g)                    for g in new_gnpcs)
        zombies.extend (_zombie_from_ghost(g, day=survival_day) for g in new_gzombies)
        vehicles.extend(_vehicle_from_ghost(g) for g in new_gvehs)
        item_manager.items.extend(new_items)

        # Despawn entities beyond DESPAWN_RADIUS → serialize to chunk
        _desp2 = DESPAWN_RADIUS * DESPAWN_RADIUS
        far_npcs    = [n for n in npcs
                       if n.pos.distance_squared_to(player.pos) > _desp2]
        far_zombies = [z for z in zombies
                       if z.alive and z.pos.distance_squared_to(player.pos) > _desp2]
        far_vehs    = [v for v in vehicles
                       if (v is not current_vehicle and v.alive
                           and v.pos.distance_squared_to(player.pos) > _desp2)]
        for n in far_npcs:    chunk_manager.serialize_npc(n)
        for z in far_zombies: chunk_manager.serialize_zombie(z)
        for v in far_vehs:    chunk_manager.serialize_vehicle(v)
        npcs    = [n for n in npcs    if n.pos.distance_squared_to(player.pos) <= _desp2]
        zombies = [z for z in zombies
                   if not z.alive or z.pos.distance_squared_to(player.pos) <= _desp2]
        # Keep wrecks (not alive) within despawn range; only serialize/remove alive far vehicles
        vehicles = [v for v in vehicles
                    if v is current_vehicle
                    or v.pos.distance_squared_to(player.pos) <= _desp2]

        # Build spatial grid for this frame
        spatial.clear()
        for z in zombies:
            if z.alive: spatial.insert(z)
        for n in npcs:
            if n.state != NPC.STATE_DEAD: spatial.insert(n)

        # Only entities within ACTIVE_RADIUS actually simulate
        _act2 = ACTIVE_RADIUS * ACTIVE_RADIUS

        # ── Update: NPCs ────────────────────────────────────────────────────
        nearby_zombies = spatial.query_radius(player.pos, ACTIVE_RADIUS + 200)
        nearby_zombies = [e for e in nearby_zombies if isinstance(e, Zombie) and e.alive]

        for npc in npcs:
            if npc.pos.distance_squared_to(player.pos) > _act2:
                continue
            fired = npc.update(dt, bounds, zones=zones,
                               zombies=nearby_zombies, player=player)
            if fired:
                proj_manager.add(fired)

        new_zombies, surviving_npcs = [], []
        for npc in npcs:
            if npc.state == NPC.STATE_DEAD:
                if npc._zombie_on_death:
                    new_zombies.append(Zombie(npc.pos.x, npc.pos.y,
                                              kind=random.choice(difficulty.get_zombie_pool(survival_day)),
                                              day=survival_day))
                if shop_mode and current_shop is npc:
                    shop_mode    = False
                    current_shop = None
                # Burn-kill penalty (same as bullet/explosion kills)
                if getattr(npc, '_burn_kill', False):
                    civilian_kills     += 1
                    player.screws       = max(0, player.screws - 5)
            else:
                surviving_npcs.append(npc)
        npcs = surviving_npcs
        zombies.extend(new_zombies)

        # ── Update: zombies ─────────────────────────────────────────────────
        nearby_npcs = [e for e in spatial.query_radius(player.pos, ACTIVE_RADIUS + 200)
                       if isinstance(e, NPC)]
        for zombie in zombies:
            if zombie.pos.distance_squared_to(player.pos) > _act2:
                continue
            zombie.update(dt, player, nearby_npcs, bounds, zones)

        # ── Roadkill (zombies) ───────────────────────────────────────────────
        if current_vehicle is not None and current_vehicle.alive:
            rk_hits = current_vehicle.check_roadkill(zombies)
            for _z, knock in rk_hits:
                ptcl_manager.blood_hit(_z.pos, knock * 120)
                camera.add_shake(3.0)
                if not _z.alive:
                    kills += 1
            if not current_vehicle.alive:
                current_vehicle._exploded = True
                ptcl_manager.vehicle_explosion(current_vehicle.pos, VEH_EXPLODE_R)
                camera.add_shake(14.0)
                player.take_damage(player.max_hp)
                current_vehicle = None

        # ── Parked vehicle explosions (killed by cannon / grenade / ramming) ──
        _newly_dead_vehs = [v for v in vehicles
                            if v is not current_vehicle
                            and not v.alive and not v._exploded]
        for _dv in _newly_dead_vehs:
            _dv._exploded = True
            ptcl_manager.vehicle_explosion(_dv.pos, VEH_EXPLODE_R)
            camera.add_shake(10.0)
            # Chain blast: damage zombies / NPCs near the exploding vehicle
            for _z in zombies:
                if _z.alive and _z.pos.distance_to(_dv.pos) < VEH_EXPLODE_R:
                    _z.take_hit(180, pygame.Vector2(0, 0))
            for _n in npcs:
                if _n.state != NPC.STATE_DEAD and _n.pos.distance_to(_dv.pos) < VEH_EXPLODE_R:
                    _n.take_hit(180, from_player=True, from_bullet=True)
                    if _n.state == NPC.STATE_DEAD:
                        civilian_kills += 1
        # Wrecks remain — do NOT remove dead vehicles from list

        # ── Roadkill (civilians / NPCs) ──────────────────────────────────────
        if current_vehicle is not None and current_vehicle.alive:
            if abs(current_vehicle.speed) >= VEH_ROADKILL_SPEED:
                _vfwd = current_vehicle._fwd()
                for _npc in npcs:
                    if _npc.state == NPC.STATE_DEAD:
                        continue
                    if current_vehicle.pos.distance_to(_npc.pos) > current_vehicle._hl + _npc.radius:
                        continue
                    _offs  = _npc.pos - current_vehicle.pos
                    _knock = (_vfwd * 0.7 + _offs.normalize() * 0.3
                              ) if _offs.length() > 0.1 else _vfwd
                    _npc.take_hit(80, from_player=True)
                    ptcl_manager.blood_hit(_npc.pos, _knock * 80)
                    camera.add_shake(2.5)
                    if _npc.state == NPC.STATE_DEAD:
                        civilian_kills += 1
                        player.screws = max(0, player.screws - 5)
                    Sheriff.alert_nearby(npcs, _npc.pos)

        dead_zombies = [z for z in zombies if not z.alive]
        zombies      = [z for z in zombies if z.alive]

        for z in dead_zombies:
            kills  += 1
            screws  = z.screw_count()
            player.screws += screws
            ptcl_manager.death_explosion(z.pos, ZOMBIE_TYPES[z.kind]["color"])
            if screws > 0:
                ptcl_manager.screw_pop(z.pos)

        # ── 좀비 공유 (멀티: 내 소유 좀비를 브로드캐스트) ────────────────────
        if _net.transport.connected:
            # 1) 사망 브로드캐스트
            _dead_ids = [z._zid for z in dead_zombies
                         if getattr(z, '_zid', None) and not getattr(z, '_remote', False)]
            _net.broadcast_zombie_death(_dead_ids)
            # 2) 신규 좀비 태깅 + 스폰 브로드캐스트
            _spawn_batch = []
            for z in zombies:
                if not getattr(z, '_remote', False) and not getattr(z, '_zid', None):
                    z._zid   = f"{_net.local_player_id}#{_zid_counter}"
                    z._owner = _net.local_player_id
                    _zid_counter += 1
                    _spawn_batch.append({"zid": z._zid, "x": round(z.pos.x, 1),
                                         "y": round(z.pos.y, 1), "kind": z.kind,
                                         "hp": z.hp, "owner": z._owner})
            _net.broadcast_zombie_spawn(_spawn_batch)
            # 3) 위치 브로드캐스트 (6Hz)
            _zpos_accum += dt
            if _zpos_accum >= 1.0 / 6.0:
                _zpos_accum = 0.0
                _pos_batch = [{"zid": z._zid, "x": round(z.pos.x, 1),
                               "y": round(z.pos.y, 1), "hp": z.hp}
                              for z in zombies if getattr(z, '_zid', None)]
                _net.broadcast_zombie_positions(_pos_batch)
            # 4) 내 소유 좀비가 받은 원격 피해 적용
            for _zh in _net.consume_zombie_hits():
                for z in zombies:
                    if getattr(z, '_zid', None) == _zh.get("zid"):
                        z.take_hit(int(_zh.get("dmg", 0)),
                                   pygame.Vector2(_zh.get("kx", 0), _zh.get("ky", 0)))
                        break
            # 5) 원격 좀비 접촉 피해 (타 클라 소유 좀비가 내게 닿으면 물림)
            for _rz in _net.remote_zombies.values():
                if not _rz.alive:
                    continue
                _rz._contact_cd = max(0.0, _rz._contact_cd - dt)
                if (player.pos.distance_to(_rz.pos)
                        < player.radius + _rz.radius + 6 and _rz._contact_cd <= 0):
                    _rz._contact_cd = _rz.contact_rate
                    player.take_damage(_rz.contact_dmg)
                    camera.add_shake(2.0)

        # ── Update: projectiles ─────────────────────────────────────────────
        _pvp_hits = []
        _zhit_out = []
        hits, explosions = proj_manager.update(dt, bounds, zones, zombies, npcs,
                                               player, remote_players, _pvp_hits,
                                               _net.remote_zombies, _zhit_out)
        # PvP: 내 총알이 원격 플레이어 적중 → 서버로 피해 보고
        for _tgt, _dmg, _knock in _pvp_hits:
            _net.send_hit(_tgt, _dmg, _knock)
        # 멀티: 원격 좀비 적중 → 소유자에게 피해 보고
        for _zowner, _zid, _zdmg, _zknock in _zhit_out:
            _net.send_zombie_hit(_zowner, _zid, _zdmg, _zknock)

        # PvP: 다른 플레이어에게 받은 피해 적용
        for _hit in _net.consume_damage():
            player.take_damage(int(_hit.get("dmg", 0)))
            camera.add_shake(4.0)
            _kx, _ky = _hit.get("kx", 0.0), _hit.get("ky", 0.0)
            if _kx or _ky:
                player.pos.x += _kx * 14
                player.pos.y += _ky * 14
            ptcl_manager.blood_hit(player.pos, pygame.Vector2(_kx, _ky) * 100)

        for hit in hits:
            ptcl_manager.blood_hit(hit.pos, hit.vel)
            if hit.target == "player":
                camera.add_shake(3.0)
            elif hit.target == "npc":
                # Player bullet hit a civilian or sheriff → alert nearby sheriffs
                Sheriff.alert_nearby(npcs, hit.pos)
                if hit.killed:
                    camera.add_shake(4.0)
                    civilian_kills += 1
                    player.screws   = max(0, player.screws - 5)
                else:
                    camera.add_shake(1.0)
            elif hit.killed:
                camera.add_shake(4.0)
            else:
                camera.add_shake(1.0)

        # Grenade explosions: area damage + particles
        for g in explosions:
            ptcl_manager.explosion(g.pos, g.blast_radius)
            camera.add_shake(8.0)
            alert_r = g.blast_radius * 5   # boom heard far away
            for z in zombies:
                if not z.alive:
                    continue
                d = z.pos.distance_to(g.pos)
                if d < g.blast_radius:
                    z.take_hit(g.damage, pygame.Vector2(0, 0))
                elif d < alert_r:
                    z.alert(g.pos)
            _grenade_hit_npc = False
            for npc in npcs:
                if npc.state == "dead":
                    continue
                d_npc = npc.pos.distance_to(g.pos)
                if d_npc < g.blast_radius:
                    npc.take_hit(g.damage, from_player=True, from_bullet=True)
                    if npc.state == "panic":
                        away = npc.pos - g.pos
                        if away.length_squared() > 0:
                            npc._direction = away.normalize()
                    _grenade_hit_npc = True
                    if npc.state == "dead":
                        civilian_kills += 1
                        player.screws   = max(0, player.screws - 5)
                elif d_npc < alert_r:
                    npc.hear_gunshot(g.pos)
            if _grenade_hit_npc:
                Sheriff.alert_nearby(npcs, g.pos)
            # Building damage from grenade
            for _zone in zones:
                if isinstance(_zone, HideoutCompound) and not _zone.destroyed:
                    _cx = max(_zone.rect.left, min(g.pos.x, _zone.rect.right))
                    _cy = max(_zone.rect.top,  min(g.pos.y, _zone.rect.bottom))
                    _db = math.sqrt((_cx - g.pos.x)**2 + (_cy - g.pos.y)**2)
                    if _db < g.blast_radius:
                        _zone.take_damage(int(g.damage * (1 - _db / g.blast_radius)))
            # Vehicle damage from grenade
            for _v in vehicles:
                if _v.alive and _v is not current_vehicle:
                    _dv = _v.pos.distance_to(g.pos)
                    if _dv < g.blast_radius + _v._hl:
                        _v.take_damage(int(g.damage * max(0, 1 - _dv / g.blast_radius)))

        ptcl_manager.update(dt)

        # ── Update: items ───────────────────────────────────────────────────
        item_manager.collect(player)

        # ── Wave spawning (ring-based, no hardcoded _safe_pos) ─────────────
        wave_timer -= dt
        if wave_timer <= 0:
            wave_timer = WAVE_INTERVAL
            for _ in range(random.randint(1, 3)):
                angle = random.uniform(0, 6.2832)
                dist  = random.uniform(ACTIVE_RADIUS * 0.75, ACTIVE_RADIUS)
                sx    = max(0, min(WORLD_W, player.pos.x + dist * pygame.math.Vector2(1, 0).rotate_rad(angle).x))
                sy    = max(0, min(WORLD_H, player.pos.y + dist * pygame.math.Vector2(1, 0).rotate_rad(angle).y))
                pos   = pygame.Vector2(sx, sy)
                if not any(z.zone_type in ("hideout", "lake") and z.contains(pos)
                           for z in zones):
                    kind = random.choice(difficulty.get_zombie_pool(survival_day))
                    zombies.append(Zombie(sx, sy, kind=kind, day=survival_day))

        # ── Player death ────────────────────────────────────────────────────
        if not player.alive:
            game_state = STATE_OVER

        # ── Day / Night — 멀티 시 서버 권위 시간, 싱글 시 로컬 진행 ─────────
        _srv_secs = _net.server_elapsed_seconds()
        if _srv_secs is not None:
            # 모든 플레이어가 서버 가동시간 기준 동일 시간대
            _total_game_h = _srv_secs * GAME_HOURS_PER_SEC
            game_time     = (GAME_START_HOUR + _total_game_h) % 24
            if not _mp_synced:
                # 첫 동기화 — 현재 날짜를 효과 없이 맞춤 (배너/보너스 스팸 방지)
                _mp_synced = True
                _dp = (0 if _total_game_h < _dawn_interval
                       else 1 + int((_total_game_h - _dawn_interval) // 24))
                survival_day = 1 + _dp
                _next_dawn_h = _dawn_interval + 24.0 * _dp
        else:
            _gh = GAME_HOURS_PER_SEC * dt * day_speed
            game_time = (game_time + _gh) % 24
            _total_game_h += _gh
        day_t = _day_factor(game_time)
        difficulty.current_day = survival_day

        # ── Town entry detection ────────────────────────────────────────────
        _town_now = chunk_manager.get_town_name(player.pos)
        if _town_now != _current_town:
            _current_town = _town_now
            if _town_now is not None:
                notifications.append({
                    "text":  lang.t("town_enter", _town_now),
                    "color": (255, 225, 90),
                    "timer": 4.0,
                })

        while _total_game_h >= _next_dawn_h:
            _next_dawn_h += 24.0
            completed = survival_day
            survival_day += 1
            bonus = difficulty.screw_bonus(completed)
            player.screws += bonus
            day_banner = {
                "day":   survival_day,
                "sub":   lang.t("day_bonus", bonus),
                "timer": 4.5, "max": 4.5,
            }
            ev = difficulty.get_day_event(survival_day)
            if ev:
                notifications.append({"text": lang.t(ev),
                                       "color": (255, 210, 60), "timer": 6.0})

        # Tick notification timers
        notifications = [n for n in notifications
                         if (n.__setitem__("timer", n["timer"] - dt) or True)
                         and n["timer"] > 0]
        if day_banner:
            day_banner["timer"] -= dt
            if day_banner["timer"] <= 0:
                day_banner = None
        fog_alpha = FOG_ALPHA * (1.0 - day_t)

        active_item = player.slot_weapon(4)
        has_lantern = (player.active_slot == 4 and active_item is not None
                       and active_item.kind == "lantern" and active_item.fuel > 0)
        if has_lantern and fog_alpha > 0:
            active_item.fuel = max(0.0, active_item.fuel - dt * (fog_alpha / FOG_ALPHA))
        v_radius = LANTERN_VISION_R if has_lantern else VISION_RADIUS
        v_mask   = vision_mask_lntn if has_lantern else vision_mask_norm

        # ── Draw (world → _world_surf, then scale to screen) ────────────────
        draw_background(_world_surf, _vox, _voy,
                        bg=_lerp_color(BG_NIGHT, BG_DAY, day_t),
                        grid=_lerp_color(GRID_NIGHT, GRID_DAY, day_t))

        font_dbg = fonts.get(16)
        for zone in zones:
            cull = getattr(zone, '_bounds', zone.rect)
            if _vis(pygame.Vector2(cull.centerx, cull.centery),
                    margin=max(cull.w, cull.h)):
                zone.draw(_world_surf, _vox, _voy,
                          player_inside=zone.contains(player.pos),
                          debug=debug,
                          font=font_dbg if debug else None)

        item_manager.draw(_world_surf, _vox, _voy, debug=debug,
                          player_pos=player.pos, zones=zones)

        # ── Vehicles ──────────────────────────────────────────────────────
        hint_font = fonts.get(15)
        for v in vehicles:
            if _vis(v.pos, margin=v._hl + 10):
                if v.alive:
                    v.draw(_world_surf, _vox, _voy, debug=debug)
                    if (current_vehicle is None and v.is_near(player.pos)):
                        v.draw_enter_hint(_world_surf, _vox, _voy, hint_font)
                else:
                    v.draw_wreck(_world_surf, _vox, _voy)
            # Damage smoke: emit when HP < 50%
            hp_ratio = v.hp / max(1, v._max_hp)
            if v.alive and hp_ratio < 0.5:
                smoke_chance = 0.6 if hp_ratio < 0.25 else 0.25
                if random.random() < smoke_chance:
                    ptcl_manager.vehicle_smoke(v.pos)
        # Same for current (driven) vehicle
        if current_vehicle is not None and current_vehicle.alive:
            _cv_ratio = current_vehicle.hp / max(1, current_vehicle._max_hp)
            if _cv_ratio < 0.5:
                _cv_chance = 0.6 if _cv_ratio < 0.25 else 0.25
                if random.random() < _cv_chance:
                    ptcl_manager.vehicle_smoke(current_vehicle.pos)

        # ── Tank aim indicator ─────────────────────────────────────────────
        if isinstance(current_vehicle, Tank) and current_vehicle.alive:
            _tank   = current_vehicle
            _tr     = math.radians(_tank.turret_angle)
            _tfwd   = pygame.Vector2(math.sin(_tr), -math.cos(_tr))
            _diff   = world_mouse - _tank.pos
            _dist   = _diff.length() if _diff.length_squared() > 0 else 1
            _aim    = _tank.pos + _tfwd * min(_dist, TANK_CANNON_RNG)
            _ax, _ay = int(_aim.x) - _vox, int(_aim.y) - _voy
            _tx, _ty = int(_tank.pos.x) - _vox, int(_tank.pos.y) - _voy
            _ready  = _tank._cannon_cd <= 0
            _col    = (255, 210, 55) if _ready else (160, 130, 40)
            _alpha  = 200 if _ready else 90
            # Barrel line: tank centre → aim point
            pygame.draw.line(_world_surf, (*_col, _alpha), (_tx, _ty), (_ax, _ay), 1)
            # Blast-radius circle at aim point
            _br    = TANK_CANNON_R
            _aim_s = pygame.Surface((_br * 2 + 4, _br * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(_aim_s, (*_col, _alpha), (_br + 2, _br + 2), _br, 2)
            _world_surf.blit(_aim_s, (_ax - _br - 2, _ay - _br - 2))
            # Crosshair at aim point
            pygame.draw.line(_world_surf, _col, (_ax - 12, _ay), (_ax + 12, _ay), 1)
            pygame.draw.line(_world_surf, _col, (_ax, _ay - 12), (_ax, _ay + 12), 1)

        # ── Airplane bomb-targeting overlay ───────────────────────────────
        if (isinstance(current_vehicle, Airplane)
                and current_vehicle.targeting):
            _t_now = pygame.time.get_ticks() / 1000.0
            _blink = math.sin(_t_now * 7) > 0
            _preview = current_vehicle.bomb_preview()
            for _bp, _br in _preview:
                _bsx = int(_bp.x) - _vox
                _bsy = int(_bp.y) - _voy
                # Fill
                _fill_s = pygame.Surface((_br * 2 + 2, _br * 2 + 2), pygame.SRCALPHA)
                pygame.draw.circle(_fill_s, (220, 60, 10, 45),
                                   (_br + 1, _br + 1), _br)
                _world_surf.blit(_fill_s, (_bsx - _br - 1, _bsy - _br - 1))
                # Blinking border
                _bcol = (255, 80, 20) if _blink else (255, 200, 50)
                _ring_s = pygame.Surface((_br * 2 + 4, _br * 2 + 4), pygame.SRCALPHA)
                pygame.draw.circle(_ring_s, (*_bcol, 200),
                                   (_br + 2, _br + 2), _br, 2)
                _world_surf.blit(_ring_s, (_bsx - _br - 2, _bsy - _br - 2))
                # Crosshair
                pygame.draw.line(_world_surf, _bcol,
                                 (_bsx - 14, _bsy), (_bsx + 14, _bsy), 1)
                pygame.draw.line(_world_surf, _bcol,
                                 (_bsx, _bsy - 14), (_bsx, _bsy + 14), 1)
            # Screen hint
            _hf  = fonts.get(16)
            _ht  = _hf.render("SPACE: 투하  /  ESC: 취소", True, (255, 200, 50))
            screen.blit(_ht, (WIDTH // 2 - _ht.get_width() // 2, HEIGHT - 60))

        for npc in npcs:
            if _vis(npc.pos):
                npc.draw(_world_surf, _vox, _voy)

        for zombie in zombies:
            if _vis(zombie.pos, margin=zombie.radius + 10):
                zombie.draw(_world_surf, _vox, _voy, debug=debug,
                            font=font_dbg if debug else None)

        # ── 원격 좀비 (멀티) — 타 클라 소유 좀비 렌더링 ──────────────────────
        if _net.remote_zombies:
            for _rz in _net.remote_zombies.values():
                if _rz.alive and _vis(_rz.pos, margin=_rz.radius + 10):
                    _rz.draw(_world_surf, _vox, _voy)

        # ── 원격 플레이어 (멀티) — 청크 스트리밍과 동일한 뷰포트 컬링 적용 ──
        if remote_players:
            _name_font = fonts.get(12)
            for _rp in remote_players.values():
                if _vis(_rp.render_pos, margin=_rp.radius + 10):
                    _rp.draw(_world_surf, _vox, _voy, font=_name_font)

        player.draw(_world_surf, _vox, _voy, debug=debug)

        # ── Grenade aim overlay ────────────────────────────────────────────
        _active_w = player.slot_weapon(player.active_slot)
        if (current_vehicle is None and _active_w is not None
                and getattr(_active_w, 'kind', None) == "grenade"
                and _active_w.ammo > 0):
            _psx = int(player.pos.x) - _vox
            _psy = int(player.pos.y) - _voy
            _gr  = GRENADE_MAX_RANGE
            # Range circle (dashed via polygon segments)
            _g_ov = pygame.Surface((_gr * 2 + 4, _gr * 2 + 4), pygame.SRCALPHA)
            _n_seg = 40
            for _si in range(_n_seg):
                _a0 = 2 * math.pi * _si / _n_seg
                _a1 = 2 * math.pi * (_si + 0.5) / _n_seg
                _x0 = int(_gr + 2 + _gr * math.cos(_a0))
                _y0 = int(_gr + 2 + _gr * math.sin(_a0))
                _x1 = int(_gr + 2 + _gr * math.cos(_a1))
                _y1 = int(_gr + 2 + _gr * math.sin(_a1))
                pygame.draw.line(_g_ov, (255, 200, 60, 120), (_x0, _y0), (_x1, _y1), 1)
            _world_surf.blit(_g_ov, (_psx - _gr - 2, _psy - _gr - 2))
            # Clamped target marker
            _gvec2 = world_mouse - player.pos
            _gdist2 = _gvec2.length()
            if _gdist2 > 0:
                if _gdist2 > _gr:
                    _gtgt2 = player.pos + _gvec2.normalize() * _gr
                else:
                    _gtgt2 = pygame.Vector2(world_mouse)
                _tsx = int(_gtgt2.x) - _vox
                _tsy = int(_gtgt2.y) - _voy
                pygame.draw.circle(_world_surf, (255, 90, 30, 200), (_tsx, _tsy), 6, 2)
                pygame.draw.line(_world_surf, (255, 90, 30, 160),
                                 (_tsx - 9, _tsy), (_tsx + 9, _tsy), 1)
                pygame.draw.line(_world_surf, (255, 90, 30, 160),
                                 (_tsx, _tsy - 9), (_tsx, _tsy + 9), 1)
                # Trajectory dots
                if _gdist2 > 1:
                    _gdir2 = _gvec2.normalize()
                    _gspd2 = min(_active_w.bullet_speed * 2.2,
                                 min(_gdist2, _gr) / (_active_w.fuse_time * 0.52))
                    _sim_pos = pygame.Vector2(player.pos)
                    _sim_vel = _gdir2 * _gspd2
                    for _ti in range(6):
                        _sim_dt = _active_w.fuse_time / 6
                        _sim_vel *= max(0.0, 1.0 - _sim_dt * 2)
                        _sim_pos += _sim_vel * _sim_dt
                        _dot_a = int(180 - _ti * 22)
                        _dx = int(_sim_pos.x) - _vox
                        _dy = int(_sim_pos.y) - _voy
                        pygame.draw.circle(_world_surf, (255, 180, 40, _dot_a),
                                           (_dx, _dy), max(1, 3 - _ti // 2))

        # ── Melee swing arc overlay ────────────────────────────────────────
        active_mw = player.slot_weapon(player.active_slot)
        if isinstance(active_mw, MeleeWeapon) and active_mw.is_swinging:
            psx = int(player.pos.x) - _vox
            psy = int(player.pos.y) - _voy
            active_mw.draw_swing_arc(_world_surf, psx, psy, player.aim_dir)

        # ── Interaction hints ─────────────────────────────────────────────
        for zone in zones:
            if not hasattr(zone, 'near_door'):
                continue
            if zone.near_door(player.pos):
                zone.draw_door_hint(_world_surf, _vox, _voy, hint_font)
        from entities import SHOPKEEPER_INTERACT_R as _SK_R
        for _npc in npcs:
            if (isinstance(_npc, ShopkeeperNPC)
                    and _npc.pos.distance_to(player.pos) < _SK_R):
                _npc.draw_interact_hint(_world_surf, _vox, _voy, hint_font)

        proj_manager.draw(_world_surf, _vox, _voy)
        ptcl_manager.draw(_world_surf, _vox, _voy)

        # ── Zone approach labels (debug only) ─────────────────────────────
        if debug:
            draw_zone_labels(_world_surf, zones, player.pos, _vox, _voy, fonts.get(14))

        # ── Fog (fades out as altitude rises) ─────────────────────────────
        _air_alt    = (getattr(current_vehicle, 'altitude', 0.0)
                       if current_vehicle is not None else 0.0)
        _fog_draw   = fog_alpha * (1.0 - _air_alt * 0.85)
        _ppos_on_ws = pygame.Vector2(player.pos.x - _vox, player.pos.y - _voy)
        draw_fog(_world_surf, _ppos_on_ws, fog_surf, v_mask, v_radius,
                 _fog_draw, debug)

        # ── Water immersion overlay ────────────────────────────────────────
        if player.in_water:
            import math as _math
            t_now = pygame.time.get_ticks() / 1000.0
            pulse = int(28 + 12 * _math.sin(t_now * 3.0))
            water_ov = pygame.Surface((_vw, _vh), pygame.SRCALPHA)
            water_ov.fill((20, 80, 160, pulse))
            _world_surf.blit(water_ov, (0, 0))
            for wx2 in range(0, _vw, 3):
                wy2 = int(8 + 5 * _math.sin(t_now * 2.5 + wx2 * 0.04))
                pygame.draw.line(_world_surf, (60, 140, 220, 120),
                                 (wx2, 0), (wx2, wy2), 1)

        # ── Forest canopy overlay (Surface 재사용으로 GC 압력 제거) ───────
        if player.in_forest:
            t_now = pygame.time.get_ticks() / 1000.0
            if _canopy_surf is None or _canopy_surf.get_size() != (_vw, _vh):
                _canopy_surf = pygame.Surface((_vw, _vh), pygame.SRCALPHA)
            _canopy_surf.fill((22, 58, 14, 48))
            for _li in range(30):
                _lx = int((_li * 103 + int(t_now * 18)) % _vw)
                _ly = int((_li * 79  + int(t_now * 12)) % _vh)
                _lr = int(7 + 4 * math.sin(t_now * 0.7 + _li * 0.9))
                _la = int(38 + 22 * math.sin(t_now * 0.5 + _li * 1.1))
                pygame.draw.circle(_canopy_surf, (28, 82, 18, _la), (_lx, _ly), _lr)
                pygame.draw.circle(_canopy_surf, (42, 108, 28, max(0, _la - 15)),
                                   (_lx - _lr // 3, _ly - _lr // 3), max(2, _lr // 2))
            _world_surf.blit(_canopy_surf, (0, 0))

        # ── Scale world surface → screen ───────────────────────────────────
        if _zoom > 1.001:
            pygame.transform.scale(_world_surf, (WIDTH, HEIGHT), screen)
        else:
            screen.blit(_world_surf, (0, 0))

        # ── HUD (drawn directly on screen, unaffected by zoom) ────────────
        draw_hud(screen, player, zombies, npcs, debug, kills, civilian_kills,
                 game_time=game_time, day_t=day_t,
                 chunk_active=chunk_manager.active_count,
                 chunk_loaded=chunk_manager.loaded_count,
                 survival_day=survival_day, day_speed=day_speed,
                 speed_mult=_DBG_SPEED_MULT)

        # ── 멀티플레이 접속 인원 표시 (우상단) ───────────────────────────────
        if _net.transport.connected:
            _online = len(remote_players) + 1   # 원격 + 나
            _mp_f   = fonts.get(14)
            _mp_s   = _mp_f.render(lang.t("mp_online", _online), True, (110, 255, 150))
            _mp_bg  = pygame.Surface((_mp_s.get_width() + 16, _mp_s.get_height() + 8),
                                     pygame.SRCALPHA)
            _mp_bg.fill((0, 0, 0, 130))
            _mp_x = WIDTH - _mp_bg.get_width() - 10
            _mp_y = 10
            screen.blit(_mp_bg, (_mp_x, _mp_y))
            # 접속 표시등 (초록 점)
            pygame.draw.circle(screen, (60, 220, 90), (_mp_x + 10, _mp_y + 13), 4)
            screen.blit(_mp_s, (_mp_x + 18, _mp_y + 4))

        # ── Grenade aim hint (bottom-centre of screen) ────────────────────
        if (current_vehicle is None and _active_w is not None
                and getattr(_active_w, 'kind', None) == "grenade"
                and _active_w.ammo > 0):
            _gh_font = fonts.get(14)
            _gh_txt  = lang.t("grenade_aim", GRENADE_MAX_RANGE)
            _gh_s    = _gh_font.render(_gh_txt, True, (255, 210, 80))
            _gh_bg   = pygame.Surface((_gh_s.get_width() + 16, _gh_s.get_height() + 8),
                                      pygame.SRCALPHA)
            _gh_bg.fill((0, 0, 0, 140))
            _ghx = (WIDTH - _gh_bg.get_width()) // 2
            _ghy = HEIGHT - _gh_bg.get_height() - 6
            screen.blit(_gh_bg, (_ghx, _ghy))
            screen.blit(_gh_s, (_ghx + 8, _ghy + 4))

        # ── Vehicle HUD (HP + fuel bars when driving) ──────────────────────
        if current_vehicle is not None:
            _draw_vehicle_hud(screen, current_vehicle, fonts.get(15))

        # ── Corner minimap (always visible, tiny) ─────────────────────────
        minimap.draw_hud(screen, player, zones, current_vehicle, debug)

        # ── Shop UI (full overlay when open) ──────────────────────────────
        if shop_mode and current_shop is not None:
            font_md = fonts.get(18)
            font_sm = fonts.get(15)
            n = draw_shop_ui(screen, player, current_shop.shop_type,
                             font_md, font_sm, shop_selected, shop_feedback)
            shop_feedback = ""
            if n > 0:
                shop_selected = max(0, min(shop_selected, n - 1))

        # ── Full-screen minimap (M key) ────────────────────────────────────
        if show_minimap:
            minimap.draw(screen, player, zones, zombies, npcs, vehicles,
                         current_vehicle, debug,
                         screen_w=WIDTH, screen_h=HEIGHT)

        # ── Day banner + event notifications ──────────────────────────────
        draw_day_banner(screen, day_banner)
        draw_notifications(screen, notifications)

        # ── Touch controls overlay ─────────────────────────────────────────
        if game_state == STATE_PLAY:
            touch.draw(screen, fonts.get(13))
        touch.consume_frame_flags()

        # ── 수동 GC (2초마다 — 프레임 중 GC 일시정지 방지) ────────────────
        _gc_timer += dt
        if _gc_timer >= 2.0:
            _gc_timer = 0.0
            gc.collect()

        # ── Hot-reload poll (desktop only) ─────────────────────────────────
        _hr_frame += 1
        if _hr_frame >= _HR_POLL_FRAMES:
            _hr_frame = 0
            if _hr_check(_hr_watch, game_state, player,
                         kills, civilian_kills, survival_day, game_time):
                break   # os.execv already fired; exit cleanly

        pygame.display.flip()
        await asyncio.sleep(0)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    asyncio.run(main())
