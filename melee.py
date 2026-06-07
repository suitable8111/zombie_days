"""
Melee weapon system for ZombeeDoor.
Three weapons in slot 5 (key 0):
  bat      – wide arc, upgrades damage (nail bat)
  machete  – long reach, upgrades attack speed
  knuckle  – short reach, upgrades knockback
"""
import pygame
import math
import lang

# ── Stats ─────────────────────────────────────────────────────────────────────
MELEE_CONFIGS = {
    "fist": {
        "damage": 10, "attack_rate": 4.5,
        "reach": 44,  "arc_deg": 55,
        "knockback": 55, "swing_dur": 0.09,
        "color": (195, 155, 115),   # skin tone
        "upgrade_stat": "damage",
    },
    "bat": {
        "damage": 45, "attack_rate": 1.1,
        "reach": 72,  "arc_deg": 90,
        "knockback": 18, "swing_dur": 0.22,
        "color": (160, 110, 55),
        "upgrade_stat": "damage",
    },
    "machete": {
        "damage": 60, "attack_rate": 0.9,
        "reach": 88,  "arc_deg": 52,
        "knockback": 22, "swing_dur": 0.18,
        "color": (170, 175, 185),
        "upgrade_stat": "attack_rate",
    },
    "knuckle": {
        "damage": 28, "attack_rate": 3.2,
        "reach": 46,  "arc_deg": 30,
        "knockback": 15, "swing_dur": 0.11,
        "color": (200, 170, 80),
        "upgrade_stat": "knockback",
    },
}

MELEE_UPGRADE_COST = 3
MELEE_MAX_LEVEL    = 5
MELEE_UPGRADE_INC  = {
    "damage":      22,    # bat: nails add damage
    "attack_rate": 0.55,  # machete: faster swings
    "knockback":   20,    # knuckle: push further
}

MELEE_SLOT = 5   # occupies slot index 5 (key 0)


class MeleeWeapon:
    def __init__(self, kind: str):
        cfg = MELEE_CONFIGS[kind]
        self.kind         = kind
        self.damage       = float(cfg["damage"])
        self.attack_rate  = float(cfg["attack_rate"])
        self.reach        = cfg["reach"]
        self.arc_deg      = cfg["arc_deg"]
        self.knockback    = float(cfg["knockback"])
        self._swing_dur   = cfg["swing_dur"]
        self.color        = cfg["color"]
        self.slot         = MELEE_SLOT
        self._upg_stat    = cfg["upgrade_stat"]

        self.cooldown     = 0.0
        self.swing_timer  = 0.0
        self._hit_ids: set = set()   # zombie ids already struck this swing
        self.level        = 0

        # Fist combo state
        if kind == "fist":
            self.combo_index   = 0    # next hit in sequence: 0=R jab, 1=L jab, 2=R strong
            self._active_combo = 0    # which hit is currently being swung
            self._combo_reset  = 0.0  # idle countdown before resetting combo_index

    # ── API expected by the weapon-slot system ────────────────────────────────

    @property
    def name(self):
        return lang.t(f"wp_{self.kind}")

    @property
    def upgradeable(self):
        return self.kind != "fist"

    @property
    def is_default(self):
        return self.kind == "fist"

    @property
    def is_reloading(self):
        return False

    @property
    def mag(self):
        return self.level          # reused as "level" in slot-bar display

    @property
    def mag_size(self):
        return MELEE_MAX_LEVEL

    def tick(self, dt: float):
        self.cooldown    = max(0.0, self.cooldown    - dt)
        self.swing_timer = max(0.0, self.swing_timer - dt)
        if self.swing_timer <= 0:
            self._hit_ids = set()
        if self.kind == "fist" and self.combo_index > 0:
            self._combo_reset = max(0.0, self._combo_reset - dt)
            if self._combo_reset <= 0:
                self.combo_index = 0

    # ── Attack ────────────────────────────────────────────────────────────────

    @property
    def is_swinging(self) -> bool:
        return self.swing_timer > 0

    @property
    def swing_progress(self) -> float:
        """1.0 at swing start → 0.0 at end."""
        return self.swing_timer / self._swing_dur if self._swing_dur > 0 else 0.0

    def can_attack(self) -> bool:
        return self.cooldown <= 0

    def start_swing(self):
        if self.kind == "fist":
            self._active_combo = self.combo_index
            self.combo_index   = (self.combo_index + 1) % 3
            self._combo_reset  = 1.2   # reset to 0 if idle for 1.2 s
            if self._active_combo == 2:   # strong punch — slower, bigger cooldown
                dur = self._swing_dur * 1.55
                self.cooldown    = 1.0 / self.attack_rate + 0.30
                self.swing_timer = dur
            else:
                self.cooldown    = 1.0 / self.attack_rate
                self.swing_timer = self._swing_dur
        else:
            self.cooldown    = 1.0 / self.attack_rate
            self.swing_timer = self._swing_dur
        self._hit_ids = set()

    @property
    def hit_damage(self) -> float:
        if self.kind != "fist":
            return self.damage
        mult = (2.6 if self._active_combo == 2 else
                0.85 if self._active_combo == 1 else 1.0)
        return self.damage * mult

    @property
    def hit_knockback(self) -> float:
        if self.kind != "fist":
            return self.knockback
        mult = (2.4 if self._active_combo == 2 else
                0.80 if self._active_combo == 1 else 1.0)
        return self.knockback * mult

    def get_hits(self, player_pos: pygame.Vector2,
                 aim_dir: pygame.Vector2, zombies: list) -> list:
        """Return zombies inside the swing arc not already hit this swing."""
        if not self.is_swinging or aim_dir.length_squared() < 0.01:
            return []
        ad     = aim_dir.normalize()
        half_a = math.radians(self.arc_deg / 2)
        hits   = []
        for z in zombies:
            if not z.alive or id(z) in self._hit_ids:
                continue
            d = player_pos.distance_to(z.pos)
            if d > self.reach + z.radius:
                continue
            to_z = z.pos - player_pos
            cos_a = ad.dot(to_z.normalize()) if to_z.length_squared() > 0.01 else 1.0
            if math.acos(max(-1.0, min(1.0, cos_a))) <= half_a:
                hits.append(z)
                self._hit_ids.add(id(z))
        return hits

    # ── Upgrade ───────────────────────────────────────────────────────────────

    def upgrade(self, player_screws: int) -> int:
        """Apply one upgrade. Returns screws spent (0 if can't upgrade)."""
        if self.level >= MELEE_MAX_LEVEL or player_screws < MELEE_UPGRADE_COST:
            return 0
        self.level += 1
        inc = MELEE_UPGRADE_INC[self._upg_stat]
        if self._upg_stat == "damage":
            self.damage      += inc
        elif self._upg_stat == "attack_rate":
            self.attack_rate += inc
            self._swing_dur   = max(0.07, self._swing_dur * 0.86)
        elif self._upg_stat == "knockback":
            self.knockback   += inc
        return MELEE_UPGRADE_COST

    @property
    def upgrade_stat_label(self) -> str:
        return lang.t(f"upg_{self._upg_stat}")

    @property
    def upgrade_stat_value(self) -> str:
        if self._upg_stat == "damage":
            return f"{int(self.damage)}"
        if self._upg_stat == "attack_rate":
            return f"{self.attack_rate:.1f}/s"
        return f"{int(self.knockback)}px"

    # ── Draw ─────────────────────────────────────────────────────────────────

    def draw_swing_arc(self, surface, sx: int, sy: int,
                       aim_dir: pygame.Vector2):
        """Draw a translucent wedge (or punch flash for fist) during the swing."""
        if not self.is_swinging or aim_dir.length_squared() < 0.01:
            return
        prog = self.swing_progress

        if self.kind == "fist":
            return  # arm animation handled inside Player.draw() via _draw_human_anim

        prog  = self.swing_progress              # 1.0 → 0.0
        alpha = int(prog * 120)
        arc_r = int(self.reach * (0.55 + prog * 0.45))

        ad     = aim_dir.normalize()
        half_a = math.radians(self.arc_deg / 2)
        base_a = math.atan2(ad.y, ad.x)

        n = 14
        pts = [(sx, sy)]
        for i in range(n + 1):
            a = (base_a - half_a) + (2 * half_a) * i / n
            pts.append((int(sx + math.cos(a) * arc_r),
                         int(sy + math.sin(a) * arc_r)))

        arc_s = pygame.Surface((surface.get_width(), surface.get_height()),
                                pygame.SRCALPHA)
        pygame.draw.polygon(arc_s, (*self.color, alpha), pts)
        # Edge highlight
        edge_pts = pts[1:-1]
        if len(edge_pts) >= 2:
            pygame.draw.lines(arc_s, (*self.color, min(255, alpha + 60)),
                              False, edge_pts, 2)
        surface.blit(arc_s, (0, 0))

    def draw_icon(self, surface, cx: int, cy: int):
        col = self.color
        hi  = tuple(min(255, c + 55) for c in col)
        dk  = tuple(max(0,   c - 45) for c in col)

        if self.kind == "fist":
            # Closed fist — rounded rectangle body + 4 knuckle bumps
            pygame.draw.ellipse(surface, col, (cx - 8, cy - 5, 16, 12))
            pygame.draw.ellipse(surface, dk,  (cx - 8, cy - 5, 16, 12), 1)
            for i in range(4):
                kx = cx - 5 + i * 3
                pygame.draw.circle(surface, hi,  (kx, cy - 5), 2)
                pygame.draw.circle(surface, dk,  (kx, cy - 5), 2, 1)
            # Thumb
            pygame.draw.ellipse(surface, col, (cx + 6, cy - 4, 5, 8))
            pygame.draw.ellipse(surface, dk,  (cx + 6, cy - 4, 5, 8), 1)

        elif self.kind == "bat":
            # Handle: bottom-left to upper-right
            pygame.draw.line(surface, col, (cx - 9, cy + 9),
                             (cx + 2,  cy - 2), 4)
            # Barrel: thicker knob at the upper end
            pygame.draw.line(surface, hi,  (cx - 1, cy - 2),
                             (cx + 9, cy - 12), 6)
            pygame.draw.line(surface, dk,  (cx,     cy - 3),
                             (cx + 9, cy - 12), 2)
            # Nails (small crosses on barrel) — shows upgrade visually
            if self.level >= 1:
                for nx, ny in ((cx + 4, cy - 7), (cx + 7, cy - 10)):
                    pygame.draw.line(surface, (200, 200, 200),
                                     (nx - 2, ny), (nx + 2, ny), 1)
                    pygame.draw.line(surface, (200, 200, 200),
                                     (nx, ny - 2), (nx, ny + 2), 1)

        elif self.kind == "machete":
            # Blade (long diagonal)
            pygame.draw.line(surface, hi,  (cx - 10, cy + 7),
                             (cx + 10, cy - 9), 4)
            pygame.draw.line(surface, col, (cx - 9,  cy + 9),
                             (cx + 10, cy - 7), 2)
            # Edge sharpness line
            pygame.draw.line(surface, (230, 235, 245),
                             (cx - 6, cy + 3), (cx + 8, cy - 7), 1)
            # Guard
            pygame.draw.line(surface, dk,   (cx - 2, cy),
                             (cx + 4, cy - 6), 4)
            # Handle
            pygame.draw.line(surface, col,  (cx - 10, cy + 7),
                             (cx - 14, cy + 11), 3)

        elif self.kind == "knuckle":
            # Four finger rings
            for i in range(4):
                fx = cx - 6 + i * 4
                pygame.draw.circle(surface, hi,  (fx, cy - 3), 3)
                pygame.draw.circle(surface, dk,  (fx, cy - 3), 3, 1)
            # Palm plate
            pygame.draw.rect(surface, col,
                             (cx - 8, cy + 1, 16, 7), border_radius=2)
            pygame.draw.rect(surface, hi,
                             (cx - 8, cy + 1, 16, 7), 1, border_radius=2)
            # Spike if upgraded
            if self.level >= 2:
                for sx2 in (cx - 5, cx - 1, cx + 3):
                    pygame.draw.line(surface, (220, 200, 100),
                                     (sx2, cy + 1), (sx2, cy - 2), 1)


# ── Ground drop ───────────────────────────────────────────────────────────────

class MeleeDrop:
    PICKUP_RADIUS = 12

    def __init__(self, kind: str, x: float, y: float):
        self.weapon = MeleeWeapon(kind)
        self.pos    = pygame.Vector2(x, y)
        self.radius = self.PICKUP_RADIUS

    def draw(self, surface, ox=0, oy=0, debug=False):
        t      = pygame.time.get_ticks() / 1000.0
        pulse  = int(22 + 16 * math.sin(t * 2.5))
        sx, sy = int(self.pos.x) - ox, int(self.pos.y) - oy
        col    = self.weapon.color

        gr   = self.radius * 5
        glow = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*col, pulse), (gr, gr), gr)
        surface.blit(glow, (sx - gr, sy - gr))

        shadow = pygame.Surface((32, 18), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 50), (0, 0, 32, 18))
        surface.blit(shadow, (sx - 16, sy + 8))

        self.weapon.draw_icon(surface, sx, sy)

        if debug:
            pygame.draw.circle(surface, (*col, 90), (sx, sy), self.radius, 1)
