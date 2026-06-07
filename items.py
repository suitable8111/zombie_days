import pygame
import math
import random
import lang

WEAPON_CONFIGS = {
    # Slot 0 — Pistol
    "pistol": {
        "color": (210, 200, 80),  "size": (14, 6),
        "bullet_color": (255, 235, 70),
        "fire_rate": 2.0, "damage": 25, "bullet_speed": 420,
        "mag_size": 12, "reserves": 48, "reload_time": 1.4,
        "spread_count": 1, "spread_angle": 0,
        "slot": 0,
    },
    # Slot 1 — Rifle (semi-auto, high damage)
    "rifle": {
        "color": (150, 130, 90),  "size": (22, 5),
        "bullet_color": (255, 255, 140),
        "fire_rate": 0.6, "damage": 70, "bullet_speed": 700,
        "mag_size": 5, "reserves": 20, "reload_time": 2.0,
        "spread_count": 1, "spread_angle": 0,
        "slot": 1,
    },
    # Slot 2 — Shotgun
    "shotgun": {
        "color": (190, 110, 50),  "size": (18, 8),
        "bullet_color": (255, 155, 60),
        "fire_rate": 0.8, "damage": 18, "bullet_speed": 360,
        "mag_size": 6, "reserves": 24, "reload_time": 2.2,
        "spread_count": 5, "spread_angle": 24,
        "slot": 2,
    },
    # Slot 2 — Machinegun (replaces shotgun in same slot)
    "machinegun": {
        "color": (80, 170, 220),  "size": (20, 6),
        "bullet_color": (100, 215, 255),
        "fire_rate": 9.0, "damage": 12, "bullet_speed": 520,
        "mag_size": 30, "reserves": 120, "reload_time": 2.5,
        "spread_count": 1, "spread_angle": 4,
        "slot": 2,
    },
    # Slot 3 — Grenade (throwable, area damage)
    "grenade": {
        "color": (80, 160, 60),   "size": (14, 14),
        "bullet_color": (100, 220, 80),
        "fire_rate": 0.7, "damage": 80, "bullet_speed": 240,
        "mag_size": 3, "reserves": 6, "reload_time": 1.0,
        "spread_count": 1, "spread_angle": 0,
        "slot": 3,
        "blast_radius": 100, "fuse_time": 1.8,
    },
    # Slot 4 — Heal Pack (consumable)
    "heal_pack": {
        "color": (200, 70, 70),   "size": (12, 14),
        "bullet_color": (100, 255, 120),
        "fire_rate": 0.5, "damage": 0, "bullet_speed": 0,
        "mag_size": 2, "reserves": 4, "reload_time": 0.3,
        "spread_count": 1, "spread_angle": 0,
        "slot": 4,
        "heal_amount": 40,
    },
    # Slot 2 — Flamethrower (continuous fire, short range)
    "flamethrower": {
        "color": (255, 110, 25), "size": (22, 9),
        "bullet_color": (255, 160, 40),
        "fire_rate": 16.0, "damage": 9, "bullet_speed": 340,
        "mag_size": 100, "reserves": 0, "reload_time": 3.0,
        "spread_count": 4, "spread_angle": 20,
        "slot": 2,
        "flame_life": 0.48,
    },
    # Slot 4 — Lantern (passive light source, cycles with heal_pack)
    "lantern": {
        "color": (220, 165, 50),  "size": (12, 16),
        "bullet_color": (255, 240, 120),
        "fire_rate": 1.0, "damage": 0, "bullet_speed": 0,
        "mag_size": 1, "reserves": 0, "reload_time": 0.0,
        "spread_count": 1, "spread_angle": 0,
        "slot": 4,
        "fuel": 225.0,   # real seconds ≈ 3 in-game hours (1 h = 75 s)
    },
}

# Maps weapon kind → inventory slot index (0–4)
WEAPON_SLOT_MAP = {kind: cfg["slot"] for kind, cfg in WEAPON_CONFIGS.items()}

# Weapons that support stat upgrades
UPGRADEABLE = {"pistol", "rifle", "shotgun", "machinegun", "flamethrower"}

UPGRADE_COST = {"fire_rate": 3, "damage": 3, "bullet_speed": 2, "fuel": 5}
UPGRADE_INC  = {"fire_rate": 0.5, "damage": 8, "bullet_speed": 45, "fuel": 30}
MAX_LEVEL    = 5


class Weapon:
    def __init__(self, kind):
        cfg = WEAPON_CONFIGS[kind]
        self.kind          = kind
        self.fire_rate     = cfg["fire_rate"]
        self.damage        = cfg["damage"]
        self.bullet_speed  = cfg["bullet_speed"]
        self.mag_size      = cfg["mag_size"]
        self.mag           = cfg["mag_size"]
        self.reserves      = cfg["reserves"]
        self.reload_time   = cfg["reload_time"]
        self._reload_timer = 0.0
        self.is_reloading  = False
        self.spread_count  = cfg["spread_count"]
        self.spread_angle  = cfg["spread_angle"]
        self.bullet_color  = cfg["bullet_color"]
        self.cooldown      = 0.0
        self.levels        = {"fire_rate": 0, "damage": 0, "bullet_speed": 0, "fuel": 0}
        self.slot          = cfg["slot"]
        # Special-weapon props (0 / 0.0 for normal weapons)
        self.blast_radius  = cfg.get("blast_radius", 0)
        self.fuse_time     = cfg.get("fuse_time", 0.0)
        self.flame_life    = cfg.get("flame_life", 0.0)
        self.heal_amount   = cfg.get("heal_amount", 0)
        self.fuel          = cfg.get("fuel", 0.0)
        self.max_fuel      = cfg.get("fuel", 0.0)

    @property
    def name(self):
        return lang.t(f"wp_{self.kind}")

    @property
    def ammo(self):
        return self.mag

    @property
    def upgradeable(self):
        return self.kind in UPGRADEABLE

    def __str__(self):
        return self.name

    def tick(self, dt):
        self.cooldown = max(0.0, self.cooldown - dt)
        if self.is_reloading:
            self._reload_timer -= dt
            if self._reload_timer <= 0:
                self.is_reloading = False
                fill          = min(self.mag_size - self.mag, self.reserves)
                self.mag      += fill
                self.reserves -= fill

    def can_fire(self):
        return self.cooldown <= 0 and self.mag > 0 and not self.is_reloading

    def consume_shot(self):
        self.cooldown = 1.0 / self.fire_rate
        self.mag     -= 1
        if self.mag == 0 and self.reserves > 0:
            self.start_reload()

    def start_reload(self):
        if self.is_reloading or self.reserves == 0:
            return
        self.is_reloading  = True
        self._reload_timer = self.reload_time

    @property
    def reload_progress(self) -> float:
        if not self.is_reloading:
            return 1.0
        return 1.0 - self._reload_timer / self.reload_time

    def upgrade(self, stat: str, player_screws: int) -> int:
        if not self.upgradeable:
            return 0
        cost = UPGRADE_COST[stat]
        if player_screws < cost or self.levels[stat] >= MAX_LEVEL:
            return 0
        self.levels[stat] += 1
        if stat == "fire_rate":
            self.fire_rate    += UPGRADE_INC["fire_rate"]
        elif stat == "damage":
            self.damage       += UPGRADE_INC["damage"]
        elif stat == "bullet_speed":
            self.bullet_speed += UPGRADE_INC["bullet_speed"]
        elif stat == "fuel":
            inc = UPGRADE_INC["fuel"]
            self.mag_size  += inc
            self.mag        = min(self.mag + inc, self.mag_size)
            self.reserves  += inc
        return cost


# ── Ground drops ──────────────────────────────────────────────────────────────

def _lighten(color, factor=1.35, add=40):
    return tuple(min(255, int(c * factor + add)) for c in color)


def _draw_weapon_icon(surface, kind, cx, cy, col):
    """Draw a recognisable weapon silhouette centred at (cx, cy).
    All weapons face right; coordinates are pixel offsets from centre."""
    hi = _lighten(col)        # highlight / barrel colour
    dk = tuple(max(0, c - 30) for c in col)   # shadow

    if kind == "pistol":
        # Barrel (top, extending right)
        pygame.draw.rect(surface, hi,  (cx - 2, cy - 5, 12, 3), border_radius=1)
        # Slide / body
        pygame.draw.rect(surface, col, (cx - 6, cy - 3, 12, 4), border_radius=1)
        # Grip (drops down at left)
        pygame.draw.rect(surface, col, (cx - 6, cy + 1,  5, 7), border_radius=1)
        # Trigger guard arc approximation
        pygame.draw.line(surface, hi,  (cx - 1, cy + 1), (cx + 1, cy + 4), 1)

    elif kind == "rifle":
        # Stock (left end)
        pygame.draw.rect(surface, col, (cx - 13, cy - 2, 6, 7), border_radius=1)
        # Receiver / body
        pygame.draw.rect(surface, col, (cx - 7,  cy - 4, 12, 6), border_radius=1)
        # Long barrel (right)
        pygame.draw.rect(surface, hi,  (cx + 4,  cy - 2, 10, 2))
        # Muzzle brake
        pygame.draw.rect(surface, hi,  (cx + 13, cy - 3,  2, 4))
        # Scope rail + scope
        pygame.draw.rect(surface, dk,  (cx - 4,  cy - 7,  8, 2), border_radius=1)
        pygame.draw.rect(surface, hi,  (cx - 3,  cy - 9,  6, 3), border_radius=1)
        # Pistol grip below receiver
        pygame.draw.rect(surface, col, (cx,      cy + 2,  4, 5), border_radius=1)

    elif kind == "shotgun":
        # Double barrel (two parallel lines, extending right)
        pygame.draw.rect(surface, hi,  (cx - 4,  cy - 5, 16, 2))
        pygame.draw.rect(surface, hi,  (cx - 4,  cy - 2, 16, 2))
        # Wide body
        pygame.draw.rect(surface, col, (cx - 10, cy - 5, 10, 8), border_radius=1)
        # Stock
        pygame.draw.rect(surface, col, (cx - 13, cy - 4,  5, 7), border_radius=1)
        # Pump handle (under front barrels)
        pygame.draw.rect(surface, hi,  (cx,      cy + 0,  7, 3), border_radius=1)

    elif kind == "machinegun":
        # Bipod legs at front
        pygame.draw.line(surface, col, (cx + 9, cy + 1), (cx + 12, cy + 7), 2)
        pygame.draw.line(surface, col, (cx + 6, cy + 1), (cx + 9,  cy + 7), 2)
        # Long barrel
        pygame.draw.rect(surface, hi,  (cx - 3,  cy - 2, 16, 2))
        # Heat shield over barrel
        pygame.draw.rect(surface, dk,  (cx - 1,  cy - 4, 10, 2), border_radius=1)
        # Body / receiver
        pygame.draw.rect(surface, col, (cx - 10, cy - 4, 12, 6), border_radius=1)
        # Box magazine (hangs below body)
        pygame.draw.rect(surface, col, (cx - 7,  cy + 2,  8, 7), border_radius=1)
        pygame.draw.rect(surface, hi,  (cx - 6,  cy + 3,  6, 2))
        # Stock
        pygame.draw.rect(surface, col, (cx - 13, cy - 3,  5, 6), border_radius=1)

    elif kind == "grenade":
        # Body
        pygame.draw.circle(surface, col, (cx, cy + 2), 7)
        pygame.draw.circle(surface, hi,  (cx, cy + 2), 7, 1)
        # Horizontal segmentation line
        pygame.draw.line(surface, hi,    (cx - 5, cy + 2), (cx + 5, cy + 2), 1)
        # Safety lever (spoon) on top
        pygame.draw.rect(surface, hi,    (cx - 5, cy - 6, 10, 2), border_radius=1)
        # Pin ring
        pygame.draw.circle(surface, hi,  (cx + 4, cy - 5), 3, 1)
        # Neck between lever and body
        pygame.draw.rect(surface, dk,    (cx - 2, cy - 5,  4, 4))

    elif kind == "flamethrower":
        # Tank body (fuel cylinder)
        pygame.draw.ellipse(surface, col,    (cx - 5, cy + 1, 10, 14))
        pygame.draw.ellipse(surface, hi,     (cx - 5, cy + 1, 10, 14), 1)
        # Shoulder strap connector
        pygame.draw.line(surface, dk, (cx, cy + 1), (cx, cy - 6), 2)
        # Gun barrel (horizontal)
        pygame.draw.rect(surface, col, (cx - 12, cy - 9, 18, 5), border_radius=1)
        pygame.draw.rect(surface, hi,  (cx - 12, cy - 9, 18, 5), 1, border_radius=1)
        # Nozzle
        pygame.draw.rect(surface, dk,  (cx + 5, cy - 8, 5, 3), border_radius=1)
        # Flame burst at nozzle tip
        pygame.draw.circle(surface, (255, 200, 40), (cx + 12, cy - 7), 3)
        pygame.draw.circle(surface, (255, 80,  10), (cx + 14, cy - 7), 2)

    elif kind == "heal_pack":
        # Box body
        pygame.draw.rect(surface, col,   (cx - 7, cy - 8, 14, 16), border_radius=3)
        pygame.draw.rect(surface, hi,    (cx - 7, cy - 8, 14, 16), 1, border_radius=3)
        # White medical cross
        white = (240, 245, 240)
        pygame.draw.rect(surface, white, (cx - 1, cy - 6,  3, 12))
        pygame.draw.rect(surface, white, (cx - 5, cy - 2, 10,  3))

    elif kind == "lantern":
        # Wire handle arch over the top
        handle_pts = [
            (cx - 3, cy - 9), (cx - 5, cy - 14),
            (cx,     cy - 16),
            (cx + 5, cy - 14), (cx + 3, cy - 9),
        ]
        pygame.draw.lines(surface, hi, False, handle_pts, 2)
        # Top cap
        pygame.draw.rect(surface, hi,  (cx - 4, cy - 10, 8, 3), border_radius=1)
        # Main body
        pygame.draw.rect(surface, col, (cx - 6, cy - 8, 12, 15), border_radius=2)
        pygame.draw.rect(surface, hi,  (cx - 6, cy - 8, 12, 15), 1, border_radius=2)
        # Vertical frame bars
        pygame.draw.line(surface, dk,  (cx - 3, cy - 7), (cx - 3, cy + 6), 1)
        pygame.draw.line(surface, dk,  (cx + 3, cy - 7), (cx + 3, cy + 6), 1)
        # Glass / flame window (warm glow)
        glow_c = (min(255, col[0] + 55), min(255, col[1] + 35), max(0, col[2] - 10))
        pygame.draw.rect(surface, glow_c, (cx - 2, cy - 5, 5, 9), border_radius=1)
        # Flame centre
        pygame.draw.circle(surface, (255, 238, 90), (cx, cy - 1), 2)
        # Base foot
        pygame.draw.rect(surface, hi,  (cx - 5, cy + 7, 10, 2), border_radius=1)


class WeaponDrop:
    PICKUP_RADIUS = 10

    def __init__(self, kind, x, y):
        self.weapon = Weapon(kind)
        self.pos    = pygame.Vector2(x, y)
        self.radius = self.PICKUP_RADIUS
        cfg         = WEAPON_CONFIGS[kind]
        self._color = cfg["color"]
        self._kind  = kind

    def draw(self, surface, ox=0, oy=0, debug=False):
        t      = pygame.time.get_ticks() / 1000.0
        pulse  = int(25 + 18 * math.sin(t * 2.5))
        sx, sy = int(self.pos.x) - ox, int(self.pos.y) - oy

        # Glow halo (larger than old code for better visibility)
        gr = self.radius * 6
        glow = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*self._color, pulse),
                           (gr, gr), gr)
        surface.blit(glow, (sx - gr, sy - gr))

        # Drop shadow
        shadow = pygame.Surface((36, 20), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 55), (0, 0, 36, 20))
        surface.blit(shadow, (sx - 18, sy + 6))

        # Weapon silhouette icon
        _draw_weapon_icon(surface, self._kind, sx, sy, self._color)

        if debug:
            pygame.draw.circle(surface, (*self._color, 100),
                               (sx, sy), self.radius, 1)


class ScrewDrop:
    PICKUP_RADIUS = 8
    COLOR         = (190, 190, 190)

    def __init__(self, x, y, count=1):
        self.pos    = pygame.Vector2(x, y)
        self.radius = self.PICKUP_RADIUS
        self.count  = count

    def draw(self, surface, ox=0, oy=0, debug=False):
        t     = pygame.time.get_ticks() / 1000.0
        pulse = int(25 + 12 * math.sin(t * 2.0))
        ix, iy = int(self.pos.x) - ox, int(self.pos.y) - oy
        r      = self.PICKUP_RADIUS - 2

        glow = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*self.COLOR, pulse), (r * 2, r * 2), r * 2)
        surface.blit(glow, (ix - r * 2, iy - r * 2))

        pygame.draw.circle(surface, self.COLOR, (ix, iy), r)
        pygame.draw.circle(surface, (230, 230, 230), (ix, iy), r, 1)
        pygame.draw.line(surface, (100, 100, 100), (ix - 3, iy - 3), (ix + 3, iy + 3), 1)
        pygame.draw.line(surface, (100, 100, 100), (ix + 3, iy - 3), (ix - 3, iy + 3), 1)

        if debug:
            pygame.draw.circle(surface, (*self.COLOR, 100), (ix, iy), self.PICKUP_RADIUS, 1)


_MELEE_KINDS = ["bat", "machete", "knuckle"]


class ItemManager:
    def __init__(self, loot_zones):
        self.items = []
        for zone in loot_zones:
            self._spawn_in(zone)

    def _rand_pos(self, zone, margin=22):
        r = zone.rect
        return (random.randint(r.x + margin, r.x + r.w - margin),
                random.randint(r.y + margin, r.y + r.h - margin))

    def _spawn_in(self, zone):
        from melee import MeleeDrop
        # Always spawn a ranged weapon
        x, y = self._rand_pos(zone)
        kind = random.choice(list(WEAPON_CONFIGS.keys()))
        self.items.append(WeaponDrop(kind, x, y))
        # ~50% chance for an additional melee weapon alongside
        if random.random() < 0.50:
            x, y = self._rand_pos(zone)
            self.items.append(MeleeDrop(random.choice(_MELEE_KINDS), x, y))
        for _ in range(random.randint(1, 2)):
            x, y = self._rand_pos(zone)
            self.items.append(ScrewDrop(x, y, count=random.randint(1, 3)))

    def collect(self, player):
        picked = [item for item in self.items
                  if player.pos.distance_to(item.pos) < player.radius + item.radius]
        for item in picked:
            player.pickup(item)
            self.items.remove(item)

    def draw(self, surface, ox=0, oy=0, debug=False, player_pos=None, zones=None):
        for item in self.items:
            if not debug and player_pos is not None and zones is not None:
                # Hide items that are inside a hideout the player hasn't entered
                _item_zone = None
                for z in zones:
                    if z.zone_type == "hideout" and z.contains(item.pos):
                        _item_zone = z
                        break
                if _item_zone is not None and not _item_zone.contains(player_pos):
                    continue
            item.draw(surface, ox, oy, debug)
