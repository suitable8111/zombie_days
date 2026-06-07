"""
Procedurally generated map for ZombeeDoor.
Call create_zones() each new game for a fresh random layout.
"""
import pygame
import random
import math
import lang

# ── World size ────────────────────────────────────────────────────────────────
WORLD_W = 4096
WORLD_H = 3072
# Matches chunks.py — used to detect edge chunks for ocean placement
_WORLD_W    = 50_000
_WORLD_H    = 50_000
_EDGE_SLABS = 2     # chunks within this many chunk-widths of S/E/W get ocean

# ── Zone visual properties ────────────────────────────────────────────────────
ZONE_PROPS = {
    "bush": dict(
        hidden=True,  blocks=False, speed_mult=0.62, loot=False,
        fill=(35, 75, 25),   edge=(60, 110, 42),  br=8,
    ),
    "beach": dict(
        hidden=False, blocks=False, speed_mult=0.88, loot=False,
        fill=(205, 178, 118), edge=(180, 150, 88), br=0,
    ),
    "hideout": dict(
        hidden=True,  blocks=False, speed_mult=1.0, loot=True,
        fill=(60, 50, 40),   edge=(95, 78, 58),   br=3,
    ),
    "lake": dict(
        hidden=False, blocks=False, speed_mult=0.32, loot=False,
        fill=(25, 55, 100),  edge=(45, 90, 160),  br=6,
    ),
    "road": dict(
        hidden=False, blocks=False, speed_mult=1.0, loot=False,
        fill=(42, 42, 38),   edge=(60, 60, 55),   br=0,
    ),
    "cliff": dict(
        hidden=False, blocks=True, speed_mult=1.0, loot=False,
        fill=(72, 62, 50),   edge=(50, 44, 36),   br=4,
    ),
}

# Shop building fill/edge colours (keyed by shop_type)
_SHOP_FILL = {
    "weapon":   (68, 38, 38),
    "hospital": (36, 62, 36),
    "hardware": (38, 42, 68),
    "mart":     (58, 52, 22),
    "gym":      (38, 48, 38),
}
_SHOP_EDGE = {
    "weapon":   (115, 55, 55),
    "hospital": ( 55, 105, 55),
    "hardware": ( 65,  65, 115),
    "mart":     (115, 108, 42),
    "gym":      ( 60, 140,  60),
}
_SHOP_LABEL = {
    "weapon":   "shop_sign_weapon",
    "hospital": "shop_sign_hospital",
    "hardware": "shop_sign_hardware",
    "mart":     "shop_sign_mart",
    "gym":      "shop_sign_gym",
}

_DEBUG_LOOT_EDGE = (200, 165, 60)
DOOR_W           = 40    # door gap width (world px)
DOOR_INTERACT_R  = 55    # player-to-door interaction radius
_MARGIN          = 160   # minimum distance any zone from the world edge

# ── Global road grid ──────────────────────────────────────────────────────────
# Roads span the entire world at fixed absolute coordinates.
# Every chunk includes whichever global roads pass through it so they connect
# seamlessly across chunk boundaries.
GLOBAL_ROAD_SPACING = 1100   # world-px between parallel roads (H and V)
GLOBAL_ROAD_WIDTH   = 92     # road width in world-px
GLOBAL_RIVER_SPACING = 3800  # world-px between horizontal rivers
GLOBAL_RIVER_WIDTH   = 78    # river width in world-px


# ══════════════════════════════════════════════════════════════════════════════
# Low-level geometry helpers
# ══════════════════════════════════════════════════════════════════════════════

def _road_gate_pos(lo: int, hi: int) -> int:
    """
    Return the world coordinate of the global road centre that falls inside
    [lo, hi] and is closest to the midpoint.  Falls back to the midpoint if
    no road is found (shouldn't happen for normal chunk-sized fences).
    """
    sp   = GLOBAL_ROAD_SPACING   # 1100
    half = sp // 2               # 550
    mid  = (lo + hi) // 2
    base = half + round((mid - half) / sp) * sp
    for delta in (0, sp, -sp, sp * 2, -sp * 2):
        rc = base + delta
        if lo + 40 <= rc <= hi - 40:
            return rc
    return mid   # fallback: midpoint


def _split_segs(lo, hi, covers):
    """Subtract covered intervals from [lo, hi]. Returns uncovered segment list."""
    segs = [(lo, hi)]
    for a, b in covers:
        nxt = []
        for s, e in segs:
            if b <= s or a >= e:
                nxt.append((s, e))
            else:
                if a > s: nxt.append((s, a))
                if b < e: nxt.append((b, e))
        segs = nxt
    return segs


def _rect_crossings(rect, p0, p1):
    """Return (t, coord, edge_tag) for every boundary crossing of rect on p0→p1."""
    EPS = 1e-6
    dx = p1.x - p0.x
    dy = p1.y - p0.y
    hits = []
    if abs(dx) > EPS:
        for rx, tag in ((rect.left, 'left'), (rect.right, 'right')):
            t = (rx - p0.x) / dx
            if EPS < t <= 1.0:
                y = p0.y + t * dy
                if rect.top <= y <= rect.bottom:
                    hits.append((t, rx, tag))
    if abs(dy) > EPS:
        for ry, tag in ((rect.top, 'top'), (rect.bottom, 'bottom')):
            t = (ry - p0.y) / dy
            if EPS < t <= 1.0:
                x = p0.x + t * dx
                if rect.left <= x <= rect.right:
                    hits.append((t, x, tag))
    return hits


def _compound_blocks(rects, p0, p1, door_cx, door_hw, door_open):
    """
    True if p0→p1 is blocked by the compound's outer walls.
    Interior walls shared between adjacent rooms are transparent.
    The bottom-centre gap of rects[0] is the door.
    """
    old_in = any(r.collidepoint(p0.x, p0.y) for r in rects)
    new_in = any(r.collidepoint(p1.x, p1.y) for r in rects)
    if old_in == new_in:
        return False

    dx = p1.x - p0.x
    dy = p1.y - p0.y
    hits = []
    for ri, rect in enumerate(rects):
        for t, coord, tag in _rect_crossings(rect, p0, p1):
            hits.append((t, coord, tag, ri))
    hits.sort()

    for t, coord, tag, ri in hits:
        px = p0.x + t * dx
        py = p0.y + t * dy
        # Interior wall: crossing point lies inside another room of the compound
        if any(j != ri and rects[j].collidepoint(px, py)
               for j in range(len(rects))):
            continue
        # Outer wall — check door gap (bottom of main rect only)
        if tag == 'bottom' and door_open:
            if door_cx - door_hw <= coord <= door_cx + door_hw:
                return False
        return True

    return True   # safety fallback


# ══════════════════════════════════════════════════════════════════════════════
# Simple rectangular zone  (bush / lake / valley)
# ══════════════════════════════════════════════════════════════════════════════

class Zone:
    def __init__(self, zone_type, x, y, w, h):
        self.zone_type       = zone_type
        self.rect            = pygame.Rect(x, y, w, h)
        props                = ZONE_PROPS[zone_type]
        self.hidden          = props["hidden"]
        self.blocks_movement = props["blocks"]
        self.speed_mult      = props["speed_mult"]
        self.is_loot_zone    = props["loot"]
        self._fill           = props["fill"]
        self._edge           = props["edge"]
        self._br             = props["br"]
        self.door_open       = True
        self._door_world     = None

    def contains(self, pos):
        return self.rect.collidepoint(pos.x, pos.y)

    def near_door(self, pos):
        return False

    @property
    def door_approach(self):
        return None

    def toggle_door(self):
        pass

    def blocks_passage(self, old_pos, new_pos):
        return False

    def draw(self, surface, ox=0, oy=0, player_inside=False, debug=False, font=None):
        sr = pygame.Rect(self.rect.x - ox, self.rect.y - oy,
                         self.rect.w, self.rect.h)
        if self.zone_type == "lake":
            self._draw_lake(surface, sr, debug, font)
            return
        pygame.draw.rect(surface, self._fill, sr, border_radius=self._br)
        edge = _DEBUG_LOOT_EDGE if (debug and self.is_loot_zone) else self._edge
        pygame.draw.rect(surface, edge, sr, 2, border_radius=self._br)
        self._draw_detail(surface, sr)
        if player_inside and self.zone_type != "road":
            hl = pygame.Surface((sr.w, sr.h), pygame.SRCALPHA)
            hl.fill((255, 255, 255, 18))
            surface.blit(hl, sr.topleft)
        if debug and font:
            col = {"bush": (80, 160, 70), "lake": (70, 140, 220),
                   "road": (160, 160, 140), "beach": (200, 175, 100),
                   "cliff": (180, 160, 130)}.get(
                       self.zone_type, (200, 200, 200))
            txt = font.render(lang.t(f"zone_{self.zone_type}"), True, col)
            surface.blit(txt, (sr.centerx - txt.get_width()  // 2,
                               sr.centery - txt.get_height() // 2))

    def _draw_lake(self, surface, sr, debug=False, font=None):
        t  = pygame.time.get_ticks() / 1000.0
        w, h = sr.w, sr.h
        cx, cy = w // 2, h // 2
        a,  b  = w // 2, h // 2

        lake = pygame.Surface((w, h), pygame.SRCALPHA)

        # Shore fringe (slightly lighter outer ring)
        pygame.draw.ellipse(lake, (50, 100, 170, 220), (0, 0, w, h))

        # Main water body
        inner1 = pygame.Rect(w // 12, h // 12, w * 10 // 12, h * 10 // 12)
        pygame.draw.ellipse(lake, (28, 62, 118, 255), inner1)

        # Deep center
        inner2 = pygame.Rect(w // 4, h // 4, w // 2, h // 2)
        pygame.draw.ellipse(lake, (16, 38, 85, 220), inner2)

        # Animated wave ripples — clipped to ellipse horizontally
        for i in range(5):
            y_frac = 0.22 + i * 0.15
            wy = int(h * y_frac)
            dy_c = wy - cy
            if abs(dy_c) >= b - 4:
                continue
            half_w = int(a * math.sqrt(max(0.0, 1 - (dy_c / b) ** 2))) - 8
            if half_w < 6:
                continue
            phase = t * (0.7 + i * 0.2) + i * 1.4
            pts = []
            for x in range(cx - half_w, cx + half_w, 3):
                wdy = int(2 * math.sin(phase + x * 0.06))
                pts.append((x, wy + wdy))
            if len(pts) >= 2:
                alpha = 55 + i * 10
                pygame.draw.lines(lake, (80, 155, 220, alpha), False, pts, 1)

        # Highlight sparkles (bright dots near top)
        for si in range(4):
            sx_ = cx - 30 + si * 22
            sy_ = int(cy * 0.55) + int(3 * math.sin(t * 1.3 + si * 0.9))
            pygame.draw.circle(lake, (160, 220, 255, 90), (sx_, sy_), 2)

        surface.blit(lake, sr.topleft)

        # Outer shore edge
        pygame.draw.ellipse(surface, (55, 105, 165), sr, 2)

        if debug and font:
            txt = font.render(lang.t("zone_lake"), True, (70, 140, 220))
            surface.blit(txt, (sr.centerx - txt.get_width() // 2,
                               sr.centery - txt.get_height() // 2))

    def _draw_detail(self, surface, sr):
        if self.zone_type == "road":
            line_col = (72, 72, 64)
            swalk    = (52, 52, 48)  # sidewalk strip colour
            if sr.w > sr.h:
                # Horizontal road: sidewalk strips top & bottom
                pygame.draw.line(surface, swalk, (sr.left, sr.top + 5), (sr.right, sr.top + 5), 3)
                pygame.draw.line(surface, swalk, (sr.left, sr.bottom - 5), (sr.right, sr.bottom - 5), 3)
                # Centre dashes
                cy = sr.centery
                for x in range(sr.left + 8, sr.right - 8, 28):
                    pygame.draw.line(surface, line_col, (x, cy), (x + 14, cy), 1)
            else:
                # Vertical road: sidewalk strips left & right
                pygame.draw.line(surface, swalk, (sr.left + 5, sr.top), (sr.left + 5, sr.bottom), 3)
                pygame.draw.line(surface, swalk, (sr.right - 5, sr.top), (sr.right - 5, sr.bottom), 3)
                # Centre dashes
                cx = sr.centerx
                for y in range(sr.top + 8, sr.bottom - 8, 28):
                    pygame.draw.line(surface, line_col, (cx, y), (cx, y + 14), 1)

    def draw_door_hint(self, surface, ox=0, oy=0, font=None):
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Organic lake zone (polygon-shaped water body)
# ══════════════════════════════════════════════════════════════════════════════

def _gen_lake_poly(rng, w, h, kind):
    """Generate polygon points relative to rect top-left for an organic lake."""
    n = {"small": 14, "elongated": 16, "blob": 20, "huge": 26, "ocean": 32}.get(kind, 16)
    cx, cy   = w * 0.5, h * 0.5
    if kind == "elongated":
        rx, ry = w * 0.43, h * 0.32
    else:
        rx, ry = w * 0.43, h * 0.41

    f1 = rng.uniform(0, math.pi * 2)
    f2 = rng.uniform(0, math.pi * 2)
    a1 = 0.12 + (0.08 if kind == "blob" else 0)
    a2 = 0.06 + (0.04 if kind == "blob" else 0)

    pts = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        noise = (1.0
                 + rng.uniform(-0.10, 0.10)
                 + a1 * math.sin(angle * 3 + f1)
                 + a2 * math.sin(angle * 7 + f2))
        px = max(4, min(w - 4, cx + rx * noise * math.cos(angle)))
        py = max(4, min(h - 4, cy + ry * noise * math.sin(angle)))
        pts.append((int(px), int(py)))
    return pts


class LakeZone(Zone):
    """
    Lake zone with an organic polygon silhouette.
    Gameplay containment still uses the rect; the polygon is purely visual.
    kind: 'small' | 'elongated' | 'blob' | 'huge'
    """
    def __init__(self, x, y, w, h, rng, kind="small"):
        super().__init__("lake", x, y, w, h)
        self.lake_kind  = kind
        self._poly      = _gen_lake_poly(rng, w, h, kind)
        self._is_huge   = (kind == "huge")
        self._is_ocean  = (kind == "ocean")
        if self._is_ocean:
            self.speed_mult = 0.12   # nearly impassable

    def _draw_lake(self, surface, sr, debug=False, font=None):
        t      = pygame.time.get_ticks() / 1000.0
        w, h   = sr.w, sr.h
        bx, by = sr.x, sr.y
        poly   = self._poly

        if self._is_ocean:
            col_beach = (195, 168, 105, 185)
            col_shore = (22,  60, 135, 210)
            col_water = (8,   32,  92, 255)
            col_deep  = (3,   12,  52, 255)
            col_wave  = (28,  85, 168)
            col_foam  = (200, 225, 255)
            col_edge  = (18,  52, 120)
        elif self._is_huge:
            col_beach = None
            col_shore = (38,  78, 148, 205)
            col_water = (16,  48, 104, 255)
            col_deep  = (7,   26,  68, 245)
            col_wave  = (50, 115, 190)
            col_foam  = None
            col_edge  = (42,  88, 152)
        else:
            col_beach = None
            col_shore = (50, 100, 170, 220)
            col_water = (28,  62, 118, 255)
            col_deep  = (16,  38,  85, 220)
            col_wave  = (80, 155, 220)
            col_foam  = None
            col_edge  = (55, 105, 165)

        lake = pygame.Surface((w, h), pygame.SRCALPHA)

        cx, cy = w * 0.5, h * 0.5

        def _shrink(f):
            return [(int(cx + (p[0] - cx) * f), int(cy + (p[1] - cy) * f))
                    for p in poly]

        # Ocean: sandy beach fringe under the water
        if col_beach:
            pygame.draw.polygon(lake, col_beach, poly)
            pygame.draw.polygon(lake, col_shore, _shrink(0.90))
            pygame.draw.polygon(lake, col_water, _shrink(0.77))
            pygame.draw.polygon(lake, col_deep,  _shrink(0.45))
        else:
            pygame.draw.polygon(lake, col_shore, poly)
            pygame.draw.polygon(lake, col_water, _shrink(0.87))
            pygame.draw.polygon(lake, col_deep,  _shrink(0.50))

        n_waves = (10 if self._is_ocean else 6 if self._is_huge else 4)
        for i in range(n_waves):
            wy    = int(h * (0.14 + i * (0.68 / n_waves)))
            phase = t * (0.55 + i * 0.18) + i * 1.3
            amp   = 3 if self._is_ocean else 2
            pts   = [(x, wy + int(amp * math.sin(phase + x * 0.07)))
                     for x in range(int(cx * 0.18), int(cx * 1.82), 4)]
            if len(pts) >= 2:
                alpha = 55 + i * 10
                pygame.draw.lines(lake, (*col_wave, alpha), False, pts, 1)
                # White foam crests for ocean
                if col_foam and i % 2 == 0:
                    pygame.draw.lines(lake, (*col_foam, 28), False, pts, 1)

        n_spark = (8 if self._is_ocean else 6 if self._is_huge else 3)
        for si in range(n_spark):
            sx_ = int(w * 0.08) + si * int(w * 0.12)
            sy_ = int(h * 0.30) + int(3 * math.sin(t * 1.2 + si * 0.9))
            pygame.draw.circle(lake, (165, 225, 255, 75), (sx_, sy_), 2)

        surface.blit(lake, (bx, by))
        pygame.draw.polygon(surface, col_edge,
                            [(p[0] + bx, p[1] + by) for p in poly], 2)

        if debug and font:
            key = ("zone_ocean" if self._is_ocean else
                   "zone_sea"   if self._is_huge  else "zone_lake")
            txt = font.render(lang.t(key), True, (70, 140, 220))
            surface.blit(txt, (sr.centerx - txt.get_width() // 2,
                               sr.centery - txt.get_height() // 2))


# ══════════════════════════════════════════════════════════════════════════════
# Forest zone — combined undergrowth + trees
# ══════════════════════════════════════════════════════════════════════════════

_BUSH_BLOB_COLS = [
    ((32, 78, 22),  (55, 108, 38)),
    ((44, 92, 30),  (68, 122, 46)),
    ((55, 108, 38), (80, 140, 58)),
]
_TREE_CANOPY_COLS = [
    (28, 75, 22),
    (42, 98, 30),
    (36, 88, 26),
    (58, 112, 38),
]


class ForestZone(Zone):
    """
    Dense forest patch: bush undergrowth + tree canopies combined.
    Slows movement to 62 % and provides zombie concealment.
    """
    def __init__(self, x: int, y: int, w: int, h: int, rng: random.Random):
        super().__init__("bush", x, y, w, h)

        # Bush blobs (undergrowth layer)
        n_b = max(4, (w * h) // 1500)
        self._blobs: list = []
        for _ in range(n_b * 6):
            if len(self._blobs) >= n_b: break
            self._blobs.append((
                rng.randint(10, max(11, w - 10)),
                rng.randint(10, max(11, h - 10)),
                rng.randint(10, 22), rng.randint(0, 2),
            ))

        # Tree canopies (upper layer — sparser)
        n_t = max(2, (w * h) // 3200)
        self._trees: list = []
        for _ in range(n_t * 8):
            if len(self._trees) >= n_t: break
            self._trees.append((
                rng.randint(18, max(19, w - 18)),
                rng.randint(18, max(19, h - 18)),
                rng.randint(16, 30), rng.randint(0, 3),
            ))

    def draw(self, surface, ox=0, oy=0, player_inside=False, debug=False, font=None):
        sr = pygame.Rect(self.rect.x - ox, self.rect.y - oy, self.rect.w, self.rect.h)
        w, h = sr.w, sr.h
        fs = pygame.Surface((w, h), pygame.SRCALPHA)   # fully transparent — circles only

        # Undergrowth blobs
        for bx, by, br, var in self._blobs:
            base_col, hi_col = _BUSH_BLOB_COLS[var % 3]
            pygame.draw.circle(fs, (*base_col, 235), (bx, by), br)
            pygame.draw.circle(fs, (*hi_col,   200),
                               (bx - max(2, br // 3), by - max(2, br // 3)),
                               max(3, br // 2))
            pygame.draw.circle(fs, (18, 42, 12, 180), (bx, by), br, 1)

        # Tree canopies
        for tx, ty, cr, var in self._trees:
            col = _TREE_CANOPY_COLS[var % 4]
            hi  = tuple(min(255, c + 32) for c in col)
            dk  = tuple(max(0,   c - 18) for c in col)
            tr  = max(3, cr // 3)
            pygame.draw.ellipse(fs, (0, 0, 0, 30),
                                (tx - cr + 3, ty - cr // 2 + 4, cr * 2, cr))
            pygame.draw.circle(fs, (78, 52, 22, 230), (tx, ty + cr // 3), tr)
            pygame.draw.circle(fs, (*dk,  245), (tx, ty), cr)
            pygame.draw.circle(fs, (*col, 235), (tx, ty), cr - 2)
            pygame.draw.circle(fs, (*hi,  180),
                               (tx - cr // 4, ty - cr // 4), max(4, cr // 2))

        surface.blit(fs, sr.topleft)

    def draw_door_hint(self, surface, ox=0, oy=0, font=None):
        pass


# ══════════════════════════════════════════════════════════════════════════════
# River zone — horizontal cross-chunk water obstacle
# ══════════════════════════════════════════════════════════════════════════════

class RiverZone:
    """Flowing river spanning the full chunk width — nearly impassable on foot."""
    zone_type       = "lake"   # treated as water (vehicles avoid, in_water = True)
    hidden          = False
    blocks_movement = False
    speed_mult      = 0.16     # much slower than walking — crossing is possible but hard
    is_loot_zone    = False
    is_safe_zone    = False
    door_open       = True

    def __init__(self, x: int, y: int, w: int, h: int, rng: random.Random):
        self.rect = pygame.Rect(x, y, w, h)
        n = max(2, (w * h) // 8000)
        self._features = []
        for _ in range(n * 8):
            if len(self._features) >= n:
                break
            self._features.append((
                rng.randint(6, max(7, w - 6)),
                rng.randint(6, max(7, h - 6)),
                rng.randint(3, 8),
                rng.randint(0, 1),   # 0=rock  1=reed
            ))

    def contains(self, pos):
        return self.rect.collidepoint(pos.x, pos.y)

    def near_door(self, pos):
        return False

    @property
    def door_approach(self):
        return None

    def toggle_door(self):
        pass

    def blocks_passage(self, old_pos, new_pos):
        return False   # rivers slow, they do not block

    def draw_door_hint(self, surface, ox=0, oy=0, font=None):
        pass

    def draw(self, surface, ox=0, oy=0, player_inside=False, debug=False, font=None):
        sr = pygame.Rect(self.rect.x - ox, self.rect.y - oy, self.rect.w, self.rect.h)
        if not surface.get_clip().colliderect(sr):
            return
        w, h = sr.w, sr.h
        bx, by = sr.x, sr.y
        t = pygame.time.get_ticks() / 1000.0

        rs = pygame.Surface((w, h), pygame.SRCALPHA)
        # Shore band → main water → deep centre
        pygame.draw.rect(rs, (45, 100, 175, 215), (0, 0, w, h))
        pygame.draw.rect(rs, (28, 68, 130, 245), (3, 3, max(1, w - 6), max(1, h - 6)))
        if h > 14:
            pygame.draw.rect(rs, (18, 44, 98, 240),
                             (6, 6, max(1, w - 12), max(1, h - 12)))

        # Animated flow waves
        n_w = max(2, h // 12)
        for i in range(n_w):
            wy_ = int(h * (0.08 + i * 0.84 / max(1, n_w - 1)))
            phase = t * 2.4 + i * 0.65
            pts = [(x, wy_ + int(1.5 * math.sin(phase + x * 0.055)))
                   for x in range(0, w, 5)]
            if len(pts) >= 2:
                alpha = min(120, 38 + i * 14)
                pygame.draw.lines(rs, (82, 158, 225, alpha), False, pts, 1)

        # Shore sparkles
        for si in range(min(5, w // 60)):
            sx_ = int(w * (0.12 + si * 0.18))
            sy_ = int(h * 0.35) + int(2 * math.sin(t * 1.4 + si * 0.8))
            pygame.draw.circle(rs, (155, 215, 255, 65), (sx_, sy_), 2)

        # Rocks / reeds
        for fx, fy, fr, ft in self._features:
            if ft == 0:  # rock
                pygame.draw.ellipse(rs, (62, 55, 43, 205),
                                    (fx - fr, fy - fr * 2 // 3, fr * 2, fr))
            else:        # reed
                pygame.draw.line(rs, (55, 92, 40, 185),
                                 (fx, fy + fr), (fx, fy - fr * 3), 1)
                pygame.draw.circle(rs, (75, 118, 52, 165), (fx, fy - fr * 3), 2)

        surface.blit(rs, (bx, by))
        pygame.draw.rect(surface, (30, 72, 138), sr, 2)

        if debug and font:
            txt = font.render(lang.t("zone_river"), True, (70, 155, 220))
            surface.blit(txt, (sr.centerx - txt.get_width() // 2,
                               sr.centery - txt.get_height() // 2))


# ══════════════════════════════════════════════════════════════════════════════
# Cliff zone — impassable rocky outcrop
# ══════════════════════════════════════════════════════════════════════════════

_CLIFF_COLS = [
    (60, 52, 40),
    (78, 68, 54),
    (96, 84, 66),
]


class CliffZone:
    """Rocky cliff barrier — blocks movement for all except flying vehicles."""
    zone_type       = "cliff"
    hidden          = False
    blocks_movement = True
    speed_mult      = 1.0   # irrelevant (entry is blocked before speed check)
    is_loot_zone    = False
    is_safe_zone    = False
    door_open       = True

    def __init__(self, x: int, y: int, w: int, h: int, rng: random.Random):
        self.rect = pygame.Rect(x, y, w, h)

        # Jagged outline polygon (relative to rect top-left)
        n = 22
        cx, cy = w * 0.5, h * 0.5
        rx, ry = w * 0.44, h * 0.40
        pts = []
        for i in range(n):
            angle = 2 * math.pi * i / n
            noise = 1.0 + rng.uniform(-0.24, 0.24)
            px = max(2, min(w - 2, int(cx + rx * noise * math.cos(angle))))
            py = max(2, min(h - 2, int(cy + ry * noise * math.sin(angle))))
            pts.append((px, py))
        self._poly = pts

        # Rock texture blobs
        n_r = max(4, (w * h) // 1600)
        self._rocks = []
        for _ in range(n_r * 8):
            if len(self._rocks) >= n_r:
                break
            rx_ = rng.randint(6, max(7, w - 6))
            ry_ = rng.randint(6, max(7, h - 6))
            rr  = rng.randint(5, 14)
            rv  = rng.randint(0, 2)
            self._rocks.append((rx_, ry_, rr, rv))

        # Crack lines
        n_c = max(2, (w * h) // 4000)
        self._cracks = []
        for _ in range(n_c):
            ax = rng.randint(8, max(9, w - 8))
            ay = rng.randint(8, max(9, h - 8))
            length = rng.randint(12, 30)
            angle  = rng.uniform(0, math.pi * 2)
            bx_ = int(ax + length * math.cos(angle))
            by_ = int(ay + length * math.sin(angle))
            self._cracks.append((ax, ay, bx_, by_))

    def contains(self, pos):
        return self.rect.collidepoint(pos.x, pos.y)

    def near_door(self, pos):
        return False

    @property
    def door_approach(self):
        return None

    def toggle_door(self):
        pass

    def blocks_passage(self, old_pos, new_pos):
        was_in = self.rect.collidepoint(old_pos.x, old_pos.y)
        now_in = self.rect.collidepoint(new_pos.x, new_pos.y)
        return (not was_in) and now_in

    def draw_door_hint(self, surface, ox=0, oy=0, font=None):
        pass

    def draw(self, surface, ox=0, oy=0, player_inside=False, debug=False, font=None):
        sr = pygame.Rect(self.rect.x - ox, self.rect.y - oy, self.rect.w, self.rect.h)
        if not surface.get_clip().colliderect(sr):
            return
        w, h = sr.w, sr.h
        bx, by = sr.x, sr.y

        cs = pygame.Surface((w, h), pygame.SRCALPHA)

        # Base rock polygon (mid tone)
        pygame.draw.polygon(cs, (*_CLIFF_COLS[1], 255), self._poly)

        # Inner lighter highlight (shrunken poly toward centre)
        cx, cy = w // 2, h // 2
        inner = [(int(cx + (p[0] - cx) * 0.68), int(cy + (p[1] - cy) * 0.68))
                 for p in self._poly]
        pygame.draw.polygon(cs, (*_CLIFF_COLS[2], 200), inner)

        # Rock texture
        for rx_, ry_, rr, rv in self._rocks:
            col = _CLIFF_COLS[rv % 3]
            pygame.draw.ellipse(cs, (*col, 215),
                                (rx_ - rr, ry_ - rr * 2 // 3, rr * 2, rr * 4 // 3))
            # Top-left highlight
            pygame.draw.ellipse(cs, (*_CLIFF_COLS[2], 130),
                                (rx_ - rr // 2, ry_ - rr // 2, rr, rr // 2))

        # Crack lines
        for ax, ay, bx_, by_ in self._cracks:
            pygame.draw.line(cs, (*_CLIFF_COLS[0], 170), (ax, ay), (bx_, by_), 1)

        surface.blit(cs, (bx, by))
        pygame.draw.polygon(surface, _CLIFF_COLS[0],
                            [(p[0] + bx, p[1] + by) for p in self._poly], 2)

        if debug and font:
            txt = font.render(lang.t("zone_cliff"), True, (180, 160, 130))
            surface.blit(txt, (sr.centerx - txt.get_width() // 2,
                               sr.centery - txt.get_height() // 2))


# ══════════════════════════════════════════════════════════════════════════════
# Core safe zone — perimeter fence around a fortified town
# ══════════════════════════════════════════════════════════════════════════════

class CoreSafeZone:
    """
    Perimeter fence enclosing a core-town chunk.
    is_safe_zone = True triggers zombie repulsion during daytime (entities.py).
    At night, random fence segments pulse orange (breach warning).
    """
    zone_type       = "safe_fence"
    hidden          = False
    blocks_movement = False
    speed_mult      = 1.0
    is_loot_zone    = False
    is_safe_zone    = True
    door_open       = True

    _POST_STEP = 36
    _POST_H    = 15
    _WIRE_OFF  = (4, 10)

    _GATE_W = GLOBAL_ROAD_WIDTH + 32   # gate = road width + margin on each side

    def __init__(self, x: int, y: int, w: int, h: int):
        self.rect    = pygame.Rect(x, y, w, h)
        # Align gates with the global road grid so players can walk in along roads
        self._gate_x = _road_gate_pos(x, x + w)   # N/S gate centre x
        self._gate_y = _road_gate_pos(y, y + h)   # E/W gate centre y
        self._gate_w = self._GATE_W

    def contains(self, pos) -> bool:
        return self.rect.collidepoint(pos.x, pos.y)

    def near_door(self, pos) -> bool:
        return False

    @property
    def door_approach(self):
        return None

    def toggle_door(self):
        pass

    def blocks_passage(self, old_pos, new_pos) -> bool:
        old_in = self.rect.collidepoint(old_pos.x, old_pos.y)
        new_in = self.rect.collidepoint(new_pos.x, new_pos.y)
        if old_in == new_in:
            return False           # not crossing the perimeter
        if old_in:
            return False           # exiting: always free
        # Entering: check all 4 gate openings
        ghw = self._gate_w // 2
        for _t, coord, tag in sorted(_rect_crossings(self.rect, old_pos, new_pos)):
            if tag in ('top', 'bottom'):
                # coord = x at crossing — compare with N/S gate centre
                if self._gate_x - ghw <= coord <= self._gate_x + ghw:
                    return False   # through N or S gate
            else:  # 'left' or 'right'
                # recover y at crossing using t parameter
                y_cross = old_pos.y + _t * (new_pos.y - old_pos.y)
                if self._gate_y - ghw <= y_cross <= self._gate_y + ghw:
                    return False   # through W or E gate
            return True            # first crossing is not any gate → blocked
        return True                # safety fallback

    def draw(self, surface, ox=0, oy=0, player_inside=False, debug=False, font=None):
        import entities as _ent
        is_night = _ent.night_mode
        t  = pygame.time.get_ticks() / 1000.0
        r  = self.rect

        day_pc = (140, 132, 115)
        day_wc = (100,  95,  82)
        ngt_pc = (80,   74,  62)
        ngt_wc = (60,   56,  47)
        pc = ngt_pc if is_night else day_pc
        wc = ngt_wc if is_night else day_wc

        STEP = self._POST_STEP
        PH   = self._POST_H

        def _breach(wx_w: int, wy_w: int) -> bool:
            seg = ((wx_w // STEP) * 73856093) ^ ((wy_w // STEP) * 19349663)
            return is_night and (seg & 0x7FFFFFFF) % 11 < 2

        def _post(scr_x, scr_y, dx, dy, breached):
            col = (220, 140, 50) if breached else pc
            pygame.draw.line(surface, col,
                             (scr_x, scr_y), (scr_x + dx, scr_y + dy), 2)
            if breached:
                gw = max(abs(dx) + 4, 8)
                gh = max(abs(dy) + 4, 8)
                gx = scr_x + (min(0, dx) - 2)
                gy = scr_y + (min(0, dy) - 2)
                alph = int(70 + 90 * math.sin(t * 3.1 + (scr_x + scr_y) * 0.04))
                gs = pygame.Surface((gw, gh), pygame.SRCALPHA)
                gs.fill((255, 150, 40, max(0, min(255, alph))))
                surface.blit(gs, (gx, gy))

        def _fence_h(wy_w, wx0_w, wx1_w, post_dy):
            if wx1_w <= wx0_w:
                return
            sy_s = wy_w - oy
            n    = max(2, (wx1_w - wx0_w) // STEP)
            for wo in self._WIRE_OFF:
                wdy = -wo if post_dy < 0 else wo
                pygame.draw.line(surface, wc,
                                 (wx0_w - ox, sy_s + wdy),
                                 (wx1_w - ox, sy_s + wdy), 1)
            for i in range(n + 1):
                wx_w = wx0_w + (wx1_w - wx0_w) * i // n
                _post(wx_w - ox, sy_s, 0, post_dy, _breach(wx_w, wy_w))

        def _fence_v(wx_w, wy0_w, wy1_w, post_dx):
            if wy1_w <= wy0_w:
                return
            sx_s = wx_w - ox
            n    = max(2, (wy1_w - wy0_w) // STEP)
            for wo in self._WIRE_OFF:
                wdx = -wo if post_dx < 0 else wo
                pygame.draw.line(surface, wc,
                                 (sx_s + wdx, wy0_w - oy),
                                 (sx_s + wdx, wy1_w - oy), 1)
            for i in range(n + 1):
                wy_w = wy0_w + (wy1_w - wy0_w) * i // n
                _post(sx_s, wy_w - oy, post_dx, 0, _breach(wx_w, wy_w))

        gate_l = self._gate_x - self._gate_w // 2
        gate_r = self._gate_x + self._gate_w // 2
        gate_t = self._gate_y - self._gate_w // 2
        gate_b = self._gate_y + self._gate_w // 2

        def _gate_gap_h(wy_w, post_dy):
            """Draw gate opening mark + taller posts on a horizontal edge."""
            _post(gate_l - ox, wy_w - oy, 0, post_dy * 2, False)
            _post(gate_r - ox, wy_w - oy, 0, post_dy * 2, False)
            pygame.draw.line(surface, (88, 80, 62),
                             (gate_l - ox, wy_w - oy), (gate_r - ox, wy_w - oy), 3)

        def _gate_gap_v(wx_w, post_dx):
            """Draw gate opening mark + taller posts on a vertical edge."""
            _post(wx_w - ox, gate_t - oy, post_dx * 2, 0, False)
            _post(wx_w - ox, gate_b - oy, post_dx * 2, 0, False)
            pygame.draw.line(surface, (88, 80, 62),
                             (wx_w - ox, gate_t - oy), (wx_w - ox, gate_b - oy), 3)

        # Top edge: gate gap at centre (N gate)
        _fence_h(r.top, r.left, gate_l, -PH)
        _fence_h(r.top, gate_r, r.right, -PH)
        _gate_gap_h(r.top, -PH)
        # Left edge: gate gap at centre (W gate)
        _fence_v(r.left, r.top, gate_t, -PH)
        _fence_v(r.left, gate_b, r.bottom, -PH)
        _gate_gap_v(r.left, -PH)
        # Right edge: gate gap at centre (E gate)
        _fence_v(r.right, r.top, gate_t, +PH)
        _fence_v(r.right, gate_b, r.bottom, +PH)
        _gate_gap_v(r.right, +PH)
        # Bottom edge: gate gap at centre (S gate)
        _fence_h(r.bottom, r.left, gate_l, +PH)
        _fence_h(r.bottom, gate_r, r.right, +PH)
        _gate_gap_h(r.bottom, +PH)

        if player_inside and not is_night:
            clip_w = min(r.w, surface.get_width())
            clip_h = min(r.h, surface.get_height())
            if clip_w > 0 and clip_h > 0:
                hl = pygame.Surface((clip_w, clip_h), pygame.SRCALPHA)
                hl.fill((55, 190, 75, 7))
                surface.blit(hl, (max(0, r.x - ox), max(0, r.y - oy)))

    def draw_door_hint(self, surface, ox=0, oy=0, font=None):
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Approach labels
# ══════════════════════════════════════════════════════════════════════════════

_APPROACH_PAD = 130   # extra px beyond zone rect before label appears

_LABEL_ZONE_KEY = {
    "lake":     "zone_lake",
    "bush":     "zone_bush",
    "hideout":  "zone_hideout",
    "beach":    "zone_beach",
    "military": "zone_military",
    "cliff":    "zone_cliff",
}
_LABEL_COL = {
    "lake":     (60,  150, 235),
    "bush":     (75,  180,  65),
    "valley":   (175, 135,  55),
    "hideout":  (195, 160,  55),
    "beach":    (210, 185, 100),
    "weapon":   (215,  90,  90),
    "hospital": ( 75, 195,  95),
    "hardware": ( 95, 135, 215),
    "mart":     (215, 180,  65),
    "gym":      ( 80, 200,  80),
    "military": (100, 160,  80),
    "cliff":    (185, 165, 130),
}


def _draw_label_tag(surface, text, sx, sy, font, color):
    """Render a pill-shaped approach label centred at (sx, sy) on surface."""
    txt_surf = font.render(text, True, (248, 248, 248))
    pad_x, pad_y = 10, 5
    tw, th = txt_surf.get_width(), txt_surf.get_height()
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    bx, by = sx - bw // 2, sy - bh

    # Drop shadow
    shd = pygame.Surface((bw + 4, bh + 4), pygame.SRCALPHA)
    pygame.draw.rect(shd, (0, 0, 0, 85), (0, 0, bw + 4, bh + 4), border_radius=10)
    surface.blit(shd, (bx - 2, by + 3))

    # Background pill
    r, g, b = color[0], color[1], color[2]
    bg = pygame.Surface((bw, bh), pygame.SRCALPHA)
    pygame.draw.rect(bg, (r, g, b, 220), (0, 0, bw, bh), border_radius=10)
    # Lighter top-half shimmer
    pygame.draw.rect(bg,
                     (min(r + 55, 255), min(g + 55, 255), min(b + 55, 255), 80),
                     (0, 0, bw, bh // 2), border_radius=10)
    # White border
    pygame.draw.rect(bg, (255, 255, 255, 80), (0, 0, bw, bh), 1, border_radius=10)
    surface.blit(bg, (bx, by))
    surface.blit(txt_surf, (bx + pad_x, by + pad_y))


def draw_zone_labels(surface, zones, player_pos, ox, oy, font):
    """
    Draw approach/proximity labels for terrain zones near the player.
    Call once per frame, after the main zone draw loop.
    """
    WIDTH  = surface.get_width()
    HEIGHT = surface.get_height()
    shown  = 0

    for zone in zones:
        if shown >= 3:
            break
        if zone.zone_type in ("road", "safe_fence"):
            continue

        # Proximity check: inflated rect
        approach = zone.rect.inflate(_APPROACH_PAD * 2, _APPROACH_PAD * 2)
        if not approach.collidepoint(player_pos.x, player_pos.y):
            continue

        # Resolve text + colour
        if isinstance(zone, HideoutCompound):
            if zone.shop_type:
                key   = _SHOP_LABEL[zone.shop_type]
                color = _LABEL_COL.get(zone.shop_type, _LABEL_COL["hideout"])
            else:
                key   = "zone_hideout"
                color = _LABEL_COL["hideout"]
        elif isinstance(zone, RiverZone):
            key   = "zone_river"
            color = (50, 130, 210)
        elif isinstance(zone, LakeZone) and zone._is_ocean:
            key   = "zone_ocean"
            color = (28, 100, 210)
        elif isinstance(zone, LakeZone) and zone._is_huge:
            key   = "zone_sea"
            color = _LABEL_COL["lake"]
        elif zone.zone_type in _LABEL_ZONE_KEY:
            key   = _LABEL_ZONE_KEY[zone.zone_type]
            color = _LABEL_COL.get(zone.zone_type, (160, 160, 140))
        else:
            continue

        # Screen position: top-centre of zone, clamped to screen
        bounds = getattr(zone, "_bounds", zone.rect)
        sx     = int(bounds.centerx) - ox
        sy_raw = int(bounds.top)     - oy - 8
        # If player is inside zone, anchor above player instead
        if zone.contains(player_pos):
            sy_raw = int(player_pos.y) - oy - 58
        sy = max(32, min(HEIGHT - 28, sy_raw))
        # Skip if horizontally off-screen
        if sx < -100 or sx > WIDTH + 100:
            continue

        _draw_label_tag(surface, lang.t(key), sx, sy, font, color)
        shown += 1


# ══════════════════════════════════════════════════════════════════════════════
# Multi-room hideout compound
# ══════════════════════════════════════════════════════════════════════════════

_HO_FILL = ZONE_PROPS["hideout"]["fill"]
_HO_EDGE = ZONE_PROPS["hideout"]["edge"]
_HO_BR   = ZONE_PROPS["hideout"]["br"]


class HideoutCompound:
    """
    One or more connected rectangular rooms forming a single hideout.
    rects[0] is the "main" room; the door is at the centre of its bottom wall.
    Annexes may extend from the left, right, or top of the main room.
    """

    zone_type       = "hideout"
    hidden          = True
    blocks_movement = False
    speed_mult      = 1.0
    is_loot_zone    = True
    # class-level defaults so attribute always exists even before __init__
    hp              = 600
    destroyed       = False

    def __init__(self, rects, shop_type=None):
        self.rects     = rects
        self.main      = rects[0]
        self.rect      = self.main
        self.shop_type = shop_type   # None | "weapon" | "hospital" | "hardware"
        # is_loot_zone: plain hideouts have loot; shops have their own catalog
        self.is_loot_zone = (shop_type is None)
        self._bounds = rects[0].copy()
        for r in rects[1:]:
            self._bounds = self._bounds.union(r)
        self.door_open   = True
        self._door_world = pygame.Vector2(self.main.centerx, self.main.bottom)
        # Shopkeeper spawn point: inside building, a bit above center
        self.shopkeeper_pos = (pygame.Vector2(self.main.centerx,
                                              self.main.centery - self.main.h * 0.12)
                               if shop_type else None)
        self.hp        = 600
        self.destroyed = False

    def take_damage(self, amount: int) -> None:
        if self.destroyed:
            return
        self.hp -= amount
        if self.hp <= 0:
            self.hp        = 0
            self.destroyed = True

    # ── Zone API ──────────────────────────────────────────────────────────────

    def contains(self, pos):
        return any(r.collidepoint(pos.x, pos.y) for r in self.rects)

    def near_door(self, pos):
        return pos.distance_to(self._door_world) < DOOR_INTERACT_R

    @property
    def door_approach(self):
        return pygame.Vector2(self._door_world.x, self._door_world.y + DOOR_W)

    def toggle_door(self):
        self.door_open = not self.door_open

    def blocks_passage(self, old_pos, new_pos):
        if self.destroyed:
            return False
        return _compound_blocks(
            self.rects, old_pos, new_pos,
            self.main.centerx, DOOR_W // 2, self.door_open,
        )

    # ── Draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface, ox=0, oy=0, player_inside=False, debug=False, font=None):
        # ── Destroyed: scorched rubble ──────────────────────────────────────
        if self.destroyed:
            t = pygame.time.get_ticks() / 1000.0
            b = self._bounds
            sr = pygame.Rect(b.x - ox, b.y - oy, b.w, b.h)
            if not surface.get_clip().colliderect(sr):
                return
            pygame.draw.rect(surface, (28, 22, 18), sr)
            rng = (b.x * 73856093) ^ (b.y * 19349663)
            for _ in range(32):
                rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF
                dw  = 6  + (rng >> 16) % 22
                rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF
                dh  = 4  + (rng >> 16) % 14
                rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF
                dx  = sr.x + (rng >> 8) % max(1, sr.w - dw)
                rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF
                dy  = sr.y + (rng >> 8) % max(1, sr.h - dh)
                rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF
                cv  = 48 + (rng >> 16) % 58
                pygame.draw.rect(surface, (cv, cv - 8, cv - 18), (dx, dy, dw, dh))
            for i in range(6):
                sx = sr.x + (b.x * 31 + i * 97) % max(1, sr.w)
                sy = sr.y + (b.y * 17 + i * 53) % max(1, sr.h)
                sa = int(28 + 18 * math.sin(t * 1.2 + i * 1.4))
                ss = pygame.Surface((20, 20), pygame.SRCALPHA)
                pygame.draw.circle(ss, (55, 50, 45, max(0, sa)), (10, 10), 10)
                surface.blit(ss, (sx - 10, sy - 10))
            return

        # Resolve fill/edge colours based on shop_type
        if self.shop_type:
            fill_col = _SHOP_FILL.get(self.shop_type, _HO_FILL)
            edge_col = _SHOP_EDGE.get(self.shop_type, _HO_EDGE)
        else:
            fill_col = _HO_FILL
            edge_col = _DEBUG_LOOT_EDGE if debug else _HO_EDGE

        # 1. Fill all rooms
        for r in self.rects:
            pygame.draw.rect(surface, fill_col,
                             (r.x - ox, r.y - oy, r.w, r.h))
        # 2. Door visual
        self._draw_door(surface, ox, oy, fill_col)
        # 3. Outer border
        self._draw_border(surface, ox, oy, edge_col)
        # 4. Player-inside highlight
        if player_inside:
            for r in self.rects:
                hl = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
                hl.fill((255, 255, 255, 18))
                surface.blit(hl, (r.x - ox, r.y - oy))
        # 5. Shop sign (always) or debug label
        if self.shop_type:
            b      = self._bounds
            edge   = _SHOP_EDGE.get(self.shop_type, (200, 200, 200))
            font_s = font  # may be None outside debug; handled below
            # Use a fallback approach: only draw if font is available
            if font:
                sign_txt = lang.t(_SHOP_LABEL[self.shop_type])
                ts = font.render(sign_txt, True, edge)
                # Pill background behind sign
                tx = b.centerx - ox - ts.get_width()  // 2
                ty = b.centery - oy - ts.get_height() // 2
                bg = pygame.Surface((ts.get_width() + 14, ts.get_height() + 6),
                                    pygame.SRCALPHA)
                bg.fill((0, 0, 0, 140))
                surface.blit(bg, (tx - 7, ty - 3))
                surface.blit(ts, (tx, ty))
        elif debug and font:
            b   = self._bounds
            txt = font.render(lang.t("zone_hideout"), True, (200, 165, 60))
            surface.blit(txt, (b.centerx - ox - txt.get_width()  // 2,
                               b.centery - oy - txt.get_height() // 2))

        # ── Damage stages (only when hurt) ───────────────────────────────────
        if 0 < self.hp < 600:
            t   = pygame.time.get_ticks() / 1000.0
            b   = self._bounds
            ratio = self.hp / 600          # 1.0 = full, 0.0 = destroyed
            stage = 3 if ratio < 0.34 else (2 if ratio < 0.67 else 1)

            # Stage 1+: crack lines (deterministic per-building)
            rng = (b.x * 73856093) ^ (b.y * 19349663)
            crack_count = stage * 4
            for ci in range(crack_count):
                rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF
                cr  = self.rects[(rng >> 24) % len(self.rects)]
                rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF
                cx0 = cr.x + (rng >> 16) % max(1, cr.w)
                rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF
                cy0 = cr.y + (rng >> 16) % max(1, cr.h)
                rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF
                cx1 = cx0 + ((rng >> 16) % 28) - 14
                rng = (rng * 1664525 + 1013904223) & 0xFFFFFFFF
                cy1 = cy0 + ((rng >> 16) % 28) - 14
                alpha = 160 if stage == 1 else (200 if stage == 2 else 240)
                cs = pygame.Surface((abs(cx1-cx0)+2, abs(cy1-cy0)+2), pygame.SRCALPHA)
                pygame.draw.line(cs, (20, 16, 12, alpha),
                                 (0 if cx1 >= cx0 else abs(cx1-cx0), 0 if cy1 >= cy0 else abs(cy1-cy0)),
                                 (abs(cx1-cx0) if cx1 >= cx0 else 0, abs(cy1-cy0) if cy1 >= cy0 else 0), 1)
                surface.blit(cs, (min(cx0, cx1) - ox, min(cy0, cy1) - oy))

            # Stage 2+: dark smoke overlay + dust
            if stage >= 2:
                ov = pygame.Surface((b.w, b.h), pygame.SRCALPHA)
                ov.fill((18, 14, 10, 60 if stage == 2 else 110))
                surface.blit(ov, (b.x - ox, b.y - oy))
                for i in range(stage * 2):
                    sx = b.x + (b.x * 31 + i * 97) % max(1, b.w)
                    sy = b.y + (b.y * 17 + i * 53) % max(1, b.h)
                    sa = int(40 + 25 * math.sin(t * 1.4 + i * 1.7))
                    ss = pygame.Surface((16, 16), pygame.SRCALPHA)
                    pygame.draw.circle(ss, (50, 45, 40, max(0, sa)), (8, 8), 8)
                    surface.blit(ss, (sx - ox - 8, sy - oy - 8))

            # Stage 3: fire glow + ember flickers
            if stage == 3:
                for i in range(5):
                    fx = b.x + (b.x * 43 + i * 113) % max(1, b.w)
                    fy = b.y + (b.y * 29 + i * 71)  % max(1, b.h)
                    fa = int(80 + 60 * math.sin(t * 3.5 + i * 2.1))
                    fs = pygame.Surface((24, 24), pygame.SRCALPHA)
                    pygame.draw.circle(fs, (220, 80, 10, max(0, fa)), (12, 12), 12)
                    pygame.draw.circle(fs, (255, 180, 40, max(0, fa // 2)), (12, 12), 6)
                    surface.blit(fs, (fx - ox - 12, fy - oy - 12))

    def _draw_border(self, surface, ox, oy, edge_col):
        for i, r in enumerate(self.rects):
            others = [self.rects[j] for j in range(len(self.rects)) if j != i]

            # Top edge
            cov = [(o.left, o.right) for o in others if o.top <= r.top <= o.bottom]
            for x1, x2 in _split_segs(r.left, r.right, cov):
                pygame.draw.line(surface, edge_col,
                                 (x1 - ox, r.top - oy), (x2 - ox, r.top - oy), 2)

            # Bottom edge — main room gets door gap removed
            cov = [(o.left, o.right) for o in others if o.top <= r.bottom <= o.bottom]
            if i == 0:
                dcx = self.main.centerx
                cov.append((dcx - DOOR_W // 2, dcx + DOOR_W // 2))
            for x1, x2 in _split_segs(r.left, r.right, cov):
                pygame.draw.line(surface, edge_col,
                                 (x1 - ox, r.bottom - oy), (x2 - ox, r.bottom - oy), 2)

            # Left edge
            cov = [(o.top, o.bottom) for o in others if o.left <= r.left <= o.right]
            for y1, y2 in _split_segs(r.top, r.bottom, cov):
                pygame.draw.line(surface, edge_col,
                                 (r.left - ox, y1 - oy), (r.left - ox, y2 - oy), 2)

            # Right edge
            cov = [(o.top, o.bottom) for o in others if o.left <= r.right <= o.right]
            for y1, y2 in _split_segs(r.top, r.bottom, cov):
                pygame.draw.line(surface, edge_col,
                                 (r.right - ox, y1 - oy), (r.right - ox, y2 - oy), 2)

    def _draw_door(self, surface, ox, oy, fill_col=None):
        if fill_col is None:
            fill_col = _HO_FILL
        dcx = self.main.centerx
        ddx = dcx - DOOR_W // 2 - ox
        ddy = self.main.bottom - 26 - oy
        bot = self.main.bottom - oy

        if self.door_open:
            pygame.draw.rect(surface, fill_col,    (ddx, bot - 3, DOOR_W, 3))
            pygame.draw.rect(surface, (22, 17, 13), (ddx, ddy, DOOR_W, 26))
            pygame.draw.rect(surface, (45, 35, 22), (ddx, ddy, DOOR_W, 26), 1)
        else:
            pygame.draw.rect(surface, (75, 50, 28), (ddx, ddy, DOOR_W, 26))
            for k in range(4):
                by = ddy + 3 + k * 5
                pygame.draw.line(surface, (100, 68, 38),
                                 (ddx + 1, by), (ddx + DOOR_W - 2, by), 1)
            pygame.draw.rect(surface, (110, 75, 40), (ddx, ddy, DOOR_W, 26), 1)

    def draw_door_hint(self, surface, ox=0, oy=0, font=None):
        if font is None:
            return
        if self.shop_type:
            key   = "shop_enter_hint_mart" if self.shop_type == "mart" else "shop_enter_hint"
            text  = lang.t(key)
            color = _SHOP_EDGE.get(self.shop_type, (200, 200, 200))
        else:
            text  = lang.t("door_close") if self.door_open else lang.t("door_open")
            color = (200, 230, 160) if self.door_open else (230, 180, 120)
        surf = font.render(text, True, color)
        sx   = int(self._door_world.x) - ox - surf.get_width() // 2
        sy   = int(self._door_world.y) - oy - 32
        surface.blit(surf, (sx, sy))


# ══════════════════════════════════════════════════════════════════════════════
# Room shape templates
# rects[0] = main room (door at bottom-centre).
# Annexes always extend left, right, or above — never below the main room.
# ══════════════════════════════════════════════════════════════════════════════

def _tmpl_single(x, y, w, h):
    return [pygame.Rect(x, y, w, h)]

def _tmpl_L_right(x, y, w, h):
    aw, ah = int(w * 0.60), int(h * 0.65)
    return [pygame.Rect(x, y, w, h),
            pygame.Rect(x + w, y + h - ah, aw, ah)]

def _tmpl_L_left(x, y, w, h):
    aw, ah = int(w * 0.60), int(h * 0.65)
    return [pygame.Rect(x, y, w, h),
            pygame.Rect(x - aw, y + h - ah, aw, ah)]

def _tmpl_back_room(x, y, w, h):
    bw = int(w * 0.55)
    bh = int(h * 0.55)
    return [pygame.Rect(x, y, w, h),
            pygame.Rect(x + (w - bw) // 2, y - bh, bw, bh)]

def _tmpl_T_wings(x, y, w, h):
    aw, ah = int(w * 0.45), int(h * 0.60)
    return [pygame.Rect(x, y, w, h),
            pygame.Rect(x - aw,  y + h - ah, aw, ah),
            pygame.Rect(x + w,   y + h - ah, aw, ah)]

def _tmpl_cross(x, y, w, h):
    bw, bh = int(w * 0.50), int(h * 0.45)
    aw, ah = int(w * 0.40), int(h * 0.55)
    return [pygame.Rect(x, y, w, h),
            pygame.Rect(x + (w - bw) // 2, y - bh, bw, bh),
            pygame.Rect(x - aw,  y + h - ah, aw, ah),
            pygame.Rect(x + w,   y + h - ah, aw, ah)]

def _tmpl_courtyard(x, y, w, h):
    """U-shaped building — two side wings open courtyard to the south."""
    wing_w = int(w * 0.26)
    body_h = int(h * 0.52)
    return [pygame.Rect(x, y, w, body_h),
            pygame.Rect(x, y + body_h, wing_w, h - body_h),
            pygame.Rect(x + w - wing_w, y + body_h, wing_w, h - body_h)]

def _tmpl_long_front(x, y, w, h):
    """Wide single room — apartment strip / office block."""
    return [pygame.Rect(x, y, w, h)]

def _tmpl_big_L(x, y, w, h):
    """Large L-shape with tall right annex."""
    aw, ah = int(w * 0.65), int(h * 0.75)
    return [pygame.Rect(x, y, w, h),
            pygame.Rect(x + w, y, aw, ah)]

# Higher weight on single-room so not every building is complex
_TEMPLATES = [
    _tmpl_single, _tmpl_single, _tmpl_single,
    _tmpl_L_right, _tmpl_L_left,
    _tmpl_back_room,
    _tmpl_T_wings,
    _tmpl_cross,
    _tmpl_courtyard,
    _tmpl_long_front,
    _tmpl_big_L,
]

# Templates suitable for large-footprint city blocks
_CITY_TEMPLATES = [
    _tmpl_single, _tmpl_single,
    _tmpl_L_right, _tmpl_L_left,
    _tmpl_back_room, _tmpl_T_wings,
    _tmpl_courtyard, _tmpl_big_L,
]


# ══════════════════════════════════════════════════════════════════════════════
# Procedural placement helpers
# ══════════════════════════════════════════════════════════════════════════════

def _overlaps(rect, placed, gap):
    padded = rect.inflate(gap * 2, gap * 2)
    return any(padded.colliderect(p) for p in placed)


def _gen_hideouts(placed, n=22):
    result, attempts = [], 0
    while len(result) < n and attempts < n * 18:
        attempts += 1
        w    = random.randint(140, 215)
        h    = random.randint(100, 158)
        tmpl = random.choice(_TEMPLATES)

        proto = tmpl(0, 0, w, h)
        union = proto[0].copy()
        for r in proto[1:]:
            union = union.union(r)

        lo_x = _MARGIN - union.left
        lo_y = _MARGIN - union.top
        hi_x = WORLD_W - _MARGIN - union.right
        hi_y = WORLD_H - _MARGIN - union.bottom
        if lo_x > hi_x or lo_y > hi_y:
            continue

        ox = random.randint(lo_x, hi_x)
        oy = random.randint(lo_y, hi_y)
        rects  = tmpl(ox, oy, w, h)
        bounds = rects[0].copy()
        for r in rects[1:]:
            bounds = bounds.union(r)

        if not _overlaps(bounds, placed, gap=90):
            result.append(HideoutCompound(rects))
            placed.append(bounds)
    return result


def _gen_lakes(placed, n=24):
    result, attempts = [], 0
    while len(result) < n and attempts < n * 10:
        attempts += 1
        w = random.randint(130, 280)
        h = random.randint(90, 190)
        x = random.randint(_MARGIN, WORLD_W - _MARGIN - w)
        y = random.randint(_MARGIN, WORLD_H - _MARGIN - h)
        r = pygame.Rect(x, y, w, h)
        if not _overlaps(r, placed, gap=80):
            result.append(Zone("lake", x, y, w, h))
            placed.append(r)
    return result


def _gen_valleys(placed, n=20):
    result, attempts = [], 0
    while len(result) < n and attempts < n * 8:
        attempts += 1
        horiz = random.random() < 0.5
        w = random.randint(200, 360) if horiz else random.randint(50, 90)
        h = random.randint(50,  90)  if horiz else random.randint(200, 360)
        x = random.randint(_MARGIN, WORLD_W - _MARGIN - w)
        y = random.randint(_MARGIN, WORLD_H - _MARGIN - h)
        r = pygame.Rect(x, y, w, h)
        if not _overlaps(r, placed, gap=30):
            result.append(Zone("valley", x, y, w, h))
            placed.append(r)
    return result


def _gen_bushes(placed, n=45):
    result, attempts = [], 0
    while len(result) < n and attempts < n * 8:
        attempts += 1
        w = random.randint(80, 180)
        h = random.randint(55, 120)
        x = random.randint(_MARGIN, WORLD_W - _MARGIN - w)
        y = random.randint(_MARGIN, WORLD_H - _MARGIN - h)
        r = pygame.Rect(x, y, w, h)
        if not _overlaps(r, placed, gap=40):
            result.append(Zone("bush", x, y, w, h))
            placed.append(r)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Global road grid helpers
# ══════════════════════════════════════════════════════════════════════════════

def _global_road_zones(wx: int, wy: int, chunk_w: int, chunk_h: int) -> list:
    """
    Return Zone("road", ...) segments for every global road lane that
    passes through the rectangle [wx, wx+chunk_w) × [wy, wy+chunk_h).
    Roads extend the full width/height of the chunk so adjacent chunks
    share perfectly aligned road surfaces.
    """
    sp   = GLOBAL_ROAD_SPACING
    half = sp // 2          # offset so first road is centred in first grid cell
    rw   = GLOBAL_ROAD_WIDTH
    roads = []

    # Horizontal road lanes (constant world-Y)
    y = half
    while y < wy + chunk_h + rw:
        road_top = y - rw // 2
        road_bot = road_top + rw
        # Does this lane overlap the chunk's Y range?
        if road_bot > wy and road_top < wy + chunk_h:
            # Clip to chunk bounds so we don't bleed into adjacent chunks
            clip_top = max(road_top, wy)
            clip_bot = min(road_bot, wy + chunk_h)
            roads.append(Zone("road", wx, clip_top, chunk_w, clip_bot - clip_top))
        y += sp

    # Vertical road lanes (constant world-X)
    x = half
    while x < wx + chunk_w + rw:
        road_left  = x - rw // 2
        road_right = road_left + rw
        if road_right > wx and road_left < wx + chunk_w:
            clip_left  = max(road_left,  wx)
            clip_right = min(road_right, wx + chunk_w)
            roads.append(Zone("road", clip_left, wy, clip_right - clip_left, chunk_h))
        x += sp

    return roads


def _global_river_zones(wx: int, wy: int, chunk_w: int, chunk_h: int) -> list:
    """
    Return RiverZone strips for every global river that passes through the chunk.
    Rivers are horizontal (constant world-Y) so they cross the map east-west.
    Offset from roads so they don't overlap.
    """
    zones = []
    sp   = GLOBAL_RIVER_SPACING
    half = int(sp * 0.62)   # offset so rivers don't align with road grid
    rw   = GLOBAL_RIVER_WIDTH

    y = half
    while y < _WORLD_H:
        river_top = y - rw // 2
        river_bot = river_top + rw
        if river_bot > wy and river_top < wy + chunk_h:
            clip_top = max(river_top, wy)
            clip_bot = min(river_bot, wy + chunk_h)
            rng_r = random.Random(y ^ 0xC0FFEE42)
            zones.append(RiverZone(wx, clip_top, chunk_w, clip_bot - clip_top, rng_r))
        y += sp

    return zones


# ══════════════════════════════════════════════════════════════════════════════
# Per-chunk procedural generation (used by ChunkManager)
# ══════════════════════════════════════════════════════════════════════════════

def gen_chunk_zones(wx: int, wy: int, chunk_w: int, chunk_h: int,
                    rng: random.Random) -> list:
    """Generate zones for a single chunk at world offset (wx, wy).
    Uses a caller-provided Random instance so results are deterministic from seed."""
    mg = 60
    placed = []

    def _ol(rect, gap=80):
        return any(rect.inflate(gap * 2, gap * 2).colliderect(p) for p in placed)

    def _ri(lo, hi):
        return rng.randint(lo, hi) if lo < hi else lo

    # ── Global roads always come first ────────────────────────────────────
    zones = _global_road_zones(wx, wy, chunk_w, chunk_h)
    # Register road rects so hideouts/lakes don't overlap them
    for z in zones:
        placed.append(z.rect)

    # ── Global rivers (cross-chunk water bands) ───────────────────────────
    rivers = _global_river_zones(wx, wy, chunk_w, chunk_h)
    zones.extend(rivers)
    for z in rivers:
        placed.append(z.rect)

    # ── Hideouts (0-3 per chunk) ───────────────────────────────────────────
    n_ho = rng.randint(0, 3)
    for _ in range(n_ho * 16):
        if sum(1 for z in zones if z.zone_type == 'hideout') >= n_ho:
            break
        w    = rng.randint(140, 215)
        h    = rng.randint(100, 158)
        tmpl = rng.choice(_TEMPLATES)
        proto = tmpl(0, 0, w, h)
        union = proto[0].copy()
        for r in proto[1:]:
            union = union.union(r)
        lo_x = mg - union.left;   hi_x = chunk_w - mg - union.right
        lo_y = mg - union.top;    hi_y = chunk_h - mg - union.bottom
        if lo_x >= hi_x or lo_y >= hi_y:
            continue
        ox_ = _ri(lo_x, hi_x) + wx
        oy_ = _ri(lo_y, hi_y) + wy
        rects  = tmpl(ox_, oy_, w, h)
        bounds = rects[0].copy()
        for r in rects[1:]:
            bounds = bounds.union(r)
        if not _ol(bounds, 90):
            zones.append(HideoutCompound(rects))
            placed.append(bounds)

    # ── Edge ocean (south / east / west world borders) ────────────────────
    near_south = (wy + chunk_h >= _WORLD_H - chunk_h * _EDGE_SLABS)
    near_east  = (wx + chunk_w >= _WORLD_W - chunk_w * _EDGE_SLABS)
    near_west  = (wx <= chunk_w * _EDGE_SLABS)

    for (edge, is_h) in ((near_south, True), (near_east, False), (near_west, False)):
        if not edge:
            continue
        beach_w = _ri(70, 150)
        if is_h:   # south: ocean at bottom
            ow, oh = chunk_w, min(chunk_h, _ri(700, 1400))
            ox_ = wx;  oy_ = wy + chunk_h - oh
            bx_ = wx;  by_ = oy_ - beach_w
        elif near_east:   # east: ocean at right
            ow, oh = min(chunk_w, _ri(700, 1400)), chunk_h
            ox_ = wx + chunk_w - ow;  oy_ = wy
            bx_ = ox_ - beach_w;     by_ = wy;  beach_h = chunk_h
        else:   # west: ocean at left
            ow, oh = min(chunk_w, _ri(700, 1400)), chunk_h
            ox_ = wx;  oy_ = wy
            bx_ = wx + ow;  by_ = wy;  beach_h = chunk_h

        r_ocean = pygame.Rect(ox_, oy_, ow, oh)
        if not _ol(r_ocean, 50):
            zones.append(LakeZone(r_ocean.x, r_ocean.y, ow, oh, rng, kind="ocean"))
            placed.append(r_ocean)
            # Beach strip
            if is_h:
                bh = beach_w
                r_beach = pygame.Rect(bx_, by_, chunk_w, bh)
            else:
                r_beach = pygame.Rect(bx_, by_, beach_w, chunk_h)
            if not _ol(r_beach, 20):
                zones.append(Zone("beach", r_beach.x, r_beach.y, r_beach.w, r_beach.h))
                placed.append(r_beach)

    # ── Huge lake / sea inland (rare) ─────────────────────────────────────
    if rng.random() < 0.12:
        hw = rng.randint(480, 950)
        hh = rng.randint(340, 680)
        r  = pygame.Rect(_ri(mg, max(mg + 1, chunk_w - mg - hw)) + wx,
                         _ri(mg, max(mg + 1, chunk_h - mg - hh)) + wy, hw, hh)
        if not _ol(r, 100):
            zones.append(LakeZone(r.x, r.y, hw, hh, rng, kind="huge"))
            placed.append(r)

    # ── Lakes (0-2 per chunk) ──────────────────────────────────────────────
    _LAKE_KINDS = ["small", "small", "elongated", "blob"]
    n_la = rng.randint(0, 2)
    for _ in range(n_la * 12):
        if sum(1 for z in zones if z.zone_type == "lake") >= n_la:
            break
        w    = rng.randint(130, 300)
        h    = rng.randint(88, 200)
        kind = rng.choice(_LAKE_KINDS)
        if kind == "elongated":
            w = rng.randint(200, 380)
            h = rng.randint(70, 130)
        r = pygame.Rect(_ri(mg, max(mg + 1, chunk_w - mg - w)) + wx,
                        _ri(mg, max(mg + 1, chunk_h - mg - h)) + wy, w, h)
        if not _ol(r, 80):
            zones.append(LakeZone(r.x, r.y, w, h, rng, kind=kind))
            placed.append(r)

    # ── Forest zones — combined bush + tree (3-8 per chunk) ──────────────
    n_fo = rng.randint(3, 8)
    for _ in range(n_fo * 12):
        if sum(1 for z in zones if z.zone_type == 'bush') >= n_fo:
            break
        w = rng.randint(110, 270);  h = rng.randint(85, 200)
        r = pygame.Rect(_ri(mg, max(mg + 1, chunk_w - mg - w)) + wx,
                        _ri(mg, max(mg + 1, chunk_h - mg - h)) + wy, w, h)
        if not _ol(r, 35):
            zones.append(ForestZone(r.x, r.y, w, h, rng))
            placed.append(r)

    # ── Cliff zones (1-3 per chunk) ───────────────────────────────────────
    n_cl = rng.randint(1, 3)
    for _ in range(n_cl * 14):
        if sum(1 for z in zones if z.zone_type == 'cliff') >= n_cl:
            break
        # Elongated shape — either wide-short or narrow-tall
        if rng.random() < 0.55:
            cw = rng.randint(160, 400)
            ch = rng.randint(45, 95)
        else:
            cw = rng.randint(45, 95)
            ch = rng.randint(160, 400)
        r = pygame.Rect(_ri(mg, max(mg + 1, chunk_w - mg - cw)) + wx,
                        _ri(mg, max(mg + 1, chunk_h - mg - ch)) + wy, cw, ch)
        if not _ol(r, 55):
            zones.append(CliffZone(r.x, r.y, cw, ch, rng))
            placed.append(r)

    # Draw order: beach → lakes/rivers → roads → hideouts → cliffs → forest
    return ([z for z in zones if z.zone_type == 'beach'] +
            [z for z in zones if z.zone_type == 'lake'] +
            [z for z in zones if z.zone_type == 'road'] +
            [z for z in zones if z.zone_type == 'hideout'] +
            [z for z in zones if z.zone_type == 'cliff'] +
            [z for z in zones if z.zone_type == 'bush'])


# ══════════════════════════════════════════════════════════════════════════════
# Town chunk generation (roads + shop buildings)
# ══════════════════════════════════════════════════════════════════════════════

_SHOP_TYPES  = ["weapon", "hospital", "hardware", "mart", "gym"]
_ROAD_WIDTH  = 90     # px


def gen_town_zones(wx: int, wy: int, chunk_w: int, chunk_h: int,
                   rng: random.Random, is_core_town: bool = False) -> list:
    """
    Generate a town chunk: global road grid + extra local streets + shops.
    Buildings are placed in the gaps *between* roads, never on top of them.
    Returns zones in draw order (roads → buildings → bushes).
    """
    zones = []

    # Perimeter fence for core fortified towns
    if is_core_town:
        fence_m = 60
        zones.append(CoreSafeZone(wx + fence_m, wy + fence_m,
                                  chunk_w - fence_m * 2, chunk_h - fence_m * 2))

    def _ri(lo, hi):
        return rng.randint(lo, hi) if lo < hi else lo

    mg = 20   # minimum margin from chunk edge
    rw = _ROAD_WIDTH

    # ── Global roads (always present, spans full chunk) ───────────────────
    global_roads = _global_road_zones(wx, wy, chunk_w, chunk_h)
    zones.extend(global_roads)

    # Collect H/V road extents for gap computation
    h_bands = []   # (top_y, bot_y) world coords
    v_bands = []   # (left_x, right_x) world coords
    for z in global_roads:
        r = z.rect
        if r.w > r.h:
            h_bands.append((r.top, r.bottom))
        else:
            v_bands.append((r.left, r.right))

    # ── Secondary streets — varied widths, random positions ──────────────
    rw_sec   = _ri(52, 72)   # secondary main street
    rw_small = _ri(30, 46)   # residential / narrow
    rw_alley = _ri(20, 32)   # alley
    MIN_SEP  = 100

    def _band_too_close(pos, size, existing):
        return any(abs(pos - b[0]) < MIN_SEP or abs(pos + size - b[1]) < MIN_SEP
                   for b in existing)

    # Horizontal secondary streets
    n_h0      = len(h_bands)
    n_extra_h = _ri(3, 5)
    _t = 0
    while len(h_bands) - n_h0 < n_extra_h and _t < 80:
        _t += 1
        srw = rng.choice([rw_sec, rw_sec, rw_small])
        ry  = wy + _ri(55, chunk_h - 55) - srw // 2
        ry  = max(wy + srw, min(wy + chunk_h - srw * 2, ry))
        if not _band_too_close(ry, srw, h_bands):
            zones.append(Zone("road", wx, ry, chunk_w, srw))
            h_bands.append((ry, ry + srw))

    # Vertical secondary streets
    n_v0      = len(v_bands)
    n_extra_v = _ri(3, 5)
    _t = 0
    while len(v_bands) - n_v0 < n_extra_v and _t < 80:
        _t += 1
        srw = rng.choice([rw_sec, rw_sec, rw_small])
        rx  = wx + _ri(55, chunk_w - 55) - srw // 2
        rx  = max(wx + srw, min(wx + chunk_w - srw * 2, rx))
        if not _band_too_close(rx, srw, v_bands):
            zones.append(Zone("road", rx, wy, srw, chunk_h))
            v_bands.append((rx, rx + srw))

    # ── Alleys — short connectors between adjacent parallel road bands ────
    sorted_h = sorted(h_bands)
    for i in range(len(sorted_h) - 1):
        gap_top = sorted_h[i][1]       # bottom of upper road
        gap_bot = sorted_h[i + 1][0]  # top of lower road
        gap_h   = gap_bot - gap_top
        if gap_h < 85:
            continue
        for _ in range(_ri(0, 2)):
            ax = wx + _ri(65, max(66, chunk_w - 65 - rw_alley))
            zones.append(Zone("road", ax, gap_top, rw_alley, gap_h))

    sorted_v = sorted(v_bands)
    for i in range(len(sorted_v) - 1):
        gap_left  = sorted_v[i][1]
        gap_right = sorted_v[i + 1][0]
        gap_w     = gap_right - gap_left
        if gap_w < 85:
            continue
        for _ in range(_ri(0, 2)):
            ay = wy + _ri(65, max(66, chunk_h - 65 - rw_alley))
            zones.append(Zone("road", gap_left, ay, gap_w, rw_alley))

    # ── Compute gaps between parallel roads ───────────────────────────────
    MIN_GAP = 80   # a gap narrower than this is too tight for a building

    def _gaps(bands, lo, hi):
        """Return list of (gap_start, gap_end) in the space [lo, hi]."""
        sorted_bands = sorted(bands)
        result = []
        prev = lo
        for a, b in sorted_bands:
            if a > prev + MIN_GAP:
                result.append((prev, a))
            prev = max(prev, b)
        if hi > prev + MIN_GAP:
            result.append((prev, hi))
        return result or [(lo, hi)]   # fallback: entire range

    y_gaps = _gaps(h_bands, wy, wy + chunk_h)
    x_gaps = _gaps(v_bands, wx, wx + chunk_w)

    # ── bldg_placed starts with all road rects to block overlaps ──────────
    bldg_placed = [z.rect for z in zones if z.zone_type == "road"]

    def _ol_bldg(rect, gap=20):
        return any(rect.inflate(gap * 2, gap * 2).colliderect(p) for p in bldg_placed)

    # ── Buildings (shops + abandoned) inside road gaps ─────────────────────
    n_bldg   = _ri(16, 26)   # denser city block
    attempts = 0
    GAP_MARGIN = 8
    # Each shop type appears at most once per chunk; shuffle for random order
    shop_types_remaining = list(_SHOP_TYPES)
    rng.shuffle(shop_types_remaining)

    while sum(1 for z in zones if isinstance(z, HideoutCompound)) < n_bldg:
        attempts += 1
        if attempts > n_bldg * 50:
            break

        # Mix of building sizes: 35% small, 45% medium, 20% large
        roll = rng.random()
        if roll < 0.35:
            bw, bh = _ri(80, 130),  _ri(60, 105)
            tmpl   = _tmpl_single
        elif roll < 0.80:
            bw, bh = _ri(120, 185), _ri(88, 145)
            tmpl   = rng.choice(_CITY_TEMPLATES)
        else:
            bw, bh = _ri(170, 280), _ri(90, 145)
            tmpl   = rng.choice([_tmpl_single, _tmpl_long_front,
                                  _tmpl_back_room, _tmpl_courtyard])

        # Max 1 of each shop type per chunk; rest become plain hideouts
        if shop_types_remaining and rng.random() >= 0.22:
            stype = shop_types_remaining.pop(0)
        else:
            stype = None

        xgap = rng.choice(x_gaps)
        ygap = rng.choice(y_gaps)

        proto  = tmpl(0, 0, bw, bh)
        union_ = proto[0].copy()
        for rr in proto[1:]:
            union_ = union_.union(rr)

        lo_x = max(xgap[0] + GAP_MARGIN, wx + mg) - union_.left
        hi_x = min(xgap[1] - GAP_MARGIN, wx + chunk_w - mg) - union_.right
        lo_y = max(ygap[0] + GAP_MARGIN, wy + mg) - union_.top
        hi_y = min(ygap[1] - GAP_MARGIN, wy + chunk_h - mg) - union_.bottom

        if lo_x >= hi_x or lo_y >= hi_y:
            continue

        bx_ = _ri(lo_x, hi_x)
        by_ = _ri(lo_y, hi_y)

        rects  = tmpl(bx_, by_, bw, bh)
        bounds = rects[0].copy()
        for rr in rects[1:]:
            bounds = bounds.union(rr)

        if _ol_bldg(bounds, 8):
            continue

        zones.append(HideoutCompound(rects, shop_type=stype))
        bldg_placed.append(bounds)

    # ── Forest patches (parks, verges, gaps between blocks) ───────────────
    for _ in range(_ri(4, 8) * 10):
        if sum(1 for z in zones if z.zone_type == "bush") >= 8:
            break
        fw = _ri(65, 160);  fh = _ri(50, 120)
        r  = pygame.Rect(_ri(mg, max(mg + 1, chunk_w - fw - mg)) + wx,
                         _ri(mg, max(mg + 1, chunk_h - fh - mg)) + wy, fw, fh)
        if not _ol_bldg(r, 10):
            zones.append(ForestZone(r.x, r.y, fw, fh, rng))
            bldg_placed.append(r)

    # Draw order: fence → roads → buildings → forest
    return ([z for z in zones if z.zone_type == "safe_fence"] +
            [z for z in zones if z.zone_type == "road"] +
            [z for z in zones if isinstance(z, HideoutCompound)] +
            [z for z in zones if z.zone_type == "bush"])



# ══════════════════════════════════════════════════════════════════════════════
# Military base zone
# ══════════════════════════════════════════════════════════════════════════════

class MilitaryBaseZone:
    """
    Procedurally drawn military compound: concrete perimeter wall,
    watchtowers at corners, helipad, runway strip, and barracks building.
    Zombies are permanently repelled (day and night) via entities.py.
    """
    zone_type       = "military"
    hidden          = False
    blocks_movement = False
    speed_mult      = 1.0
    is_loot_zone    = False
    is_safe_zone    = False   # handled by explicit military check in entities.py
    door_open       = True

    _WALL_W   = 10
    _POST_STP = 44

    def __init__(self, x: int, y: int, w: int, h: int, rng: random.Random):
        self.rect = pygame.Rect(x, y, w, h)

        # Helipad — right quadrant
        hpw = min(110, w // 3)
        self._helipad = pygame.Rect(
            x + w * 3 // 4 - hpw // 2, y + h // 2 - hpw // 2, hpw, hpw)

        # Runway strip — left half, horizontal
        rnw = int(w * 0.46)
        rnh = 56
        self._runway = pygame.Rect(x + 38, y + h // 2 - rnh // 2, rnw, rnh)

        # Barracks — upper-centre
        bw = min(170, w // 3)
        bh = min(90,  h // 5)
        self._barracks = pygame.Rect(x + (w - bw) // 2, y + 44, bw, bh)

        # Watchtower rects (straddle corners, drawn on top of walls)
        tw = 24
        self._towers = [
            pygame.Rect(x - tw // 2,     y - tw // 2,         tw, tw),
            pygame.Rect(x + w - tw // 2, y - tw // 2,         tw, tw),
            pygame.Rect(x - tw // 2,     y + h - tw // 2,     tw, tw),
            pygame.Rect(x + w - tw // 2, y + h - tw // 2,     tw, tw),
        ]

        # Gate openings aligned with the global road grid (all 4 sides)
        self._gate_x = _road_gate_pos(x, x + w)
        self._gate_y = _road_gate_pos(y, y + h)
        self._gate_w = GLOBAL_ROAD_WIDTH + 32

    # ── Zone API ──────────────────────────────────────────────────────────────

    def contains(self, pos) -> bool:
        return self.rect.collidepoint(pos.x, pos.y)

    def near_door(self, pos) -> bool:
        return False

    @property
    def door_approach(self):
        return None

    def toggle_door(self):
        pass

    def blocks_passage(self, old_pos, new_pos) -> bool:
        old_in = self.rect.collidepoint(old_pos.x, old_pos.y)
        new_in = self.rect.collidepoint(new_pos.x, new_pos.y)
        if old_in == new_in:
            return False           # not crossing
        if old_in:
            return False           # exiting: always free
        # Entering: check all 4 gate openings
        ghw = self._gate_w // 2
        for _t, coord, tag in sorted(_rect_crossings(self.rect, old_pos, new_pos)):
            if tag in ('top', 'bottom'):
                if self._gate_x - ghw <= coord <= self._gate_x + ghw:
                    return False   # through N or S gate
            else:  # 'left' or 'right'
                y_cross = old_pos.y + _t * (new_pos.y - old_pos.y)
                if self._gate_y - ghw <= y_cross <= self._gate_y + ghw:
                    return False   # through W or E gate
            return True            # first crossing is not any gate → blocked
        return True

    # ── Draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface, ox=0, oy=0, player_inside=False, debug=False, font=None):
        r   = self.rect
        sr  = pygame.Rect(r.x - ox, r.y - oy, r.w, r.h)

        # Interior ground — olive drab concrete
        pygame.draw.rect(surface, (58, 62, 46), sr)

        # Runway strip
        rn  = self._runway
        srn = pygame.Rect(rn.x - ox, rn.y - oy, rn.w, rn.h)
        pygame.draw.rect(surface, (44, 44, 40), srn)
        # Runway centre-line dashes
        dash_n = max(1, rn.w // 28)
        for i in range(dash_n):
            dx = rn.x - ox + 14 + i * 28
            dy = rn.y - oy + rn.h // 2 - 2
            if dx + 12 < srn.right:
                pygame.draw.rect(surface, (165, 155, 110), (dx, dy, 12, 4))

        # Helipad — circle with H marker
        hp     = self._helipad
        hcx    = hp.x - ox + hp.w // 2
        hcy    = hp.y - oy + hp.h // 2
        hp_r   = hp.w // 2
        pygame.draw.circle(surface, (48, 52, 44), (hcx, hcy), hp_r)
        pygame.draw.circle(surface, (128, 148, 110), (hcx, hcy), hp_r, 3)
        hw4 = max(4, hp_r // 2)
        pygame.draw.rect(surface, (128, 148, 110), (hcx - hw4, hcy - hw4, 4, hw4 * 2))
        pygame.draw.rect(surface, (128, 148, 110), (hcx + hw4 - 4, hcy - hw4, 4, hw4 * 2))
        pygame.draw.rect(surface, (128, 148, 110), (hcx - hw4, hcy - 2, hw4 * 2, 4))

        # Barracks building
        bk  = self._barracks
        sbk = pygame.Rect(bk.x - ox, bk.y - oy, bk.w, bk.h)
        pygame.draw.rect(surface, (70, 66, 52), sbk)
        pygame.draw.rect(surface, (92, 88, 70), sbk, 2)
        # Roof ridge line
        pygame.draw.line(surface, (82, 78, 62),
                         (sbk.x + 10, sbk.centery), (sbk.right - 10, sbk.centery), 2)
        # Windows
        for i in range(3):
            wx_ = sbk.x + 14 + i * ((sbk.w - 28) // 3)
            pygame.draw.rect(surface, (88, 118, 98), (wx_, sbk.y + 12, 14, 10))

        # Perimeter wall segments
        wc   = (92, 88, 74)
        wall = self._WALL_W
        ghw  = self._gate_w // 2
        gx_l = self._gate_x - ox - ghw   # S/N gate left x (screen)
        gx_r = self._gate_x - ox + ghw   # S/N gate right x (screen)
        gy_t = self._gate_y - oy - ghw   # E/W gate top y (screen)
        gy_b = self._gate_y - oy + ghw   # E/W gate bottom y (screen)
        # Top wall with N gate gap
        if gx_l > sr.x:
            pygame.draw.rect(surface, wc, (sr.x, sr.y, gx_l - sr.x, wall))
        if gx_r < sr.right:
            pygame.draw.rect(surface, wc, (gx_r, sr.y, sr.right - gx_r, wall))
        # Left wall with W gate gap
        if gy_t > sr.y:
            pygame.draw.rect(surface, wc, (sr.x, sr.y, wall, gy_t - sr.y))
        if gy_b < sr.bottom:
            pygame.draw.rect(surface, wc, (sr.x, gy_b, wall, sr.bottom - gy_b))
        # Right wall with E gate gap
        if gy_t > sr.y:
            pygame.draw.rect(surface, wc, (sr.right - wall, sr.y, wall, gy_t - sr.y))
        if gy_b < sr.bottom:
            pygame.draw.rect(surface, wc, (sr.right - wall, gy_b, wall, sr.bottom - gy_b))
        # Bottom wall with S gate gap
        if gx_l > sr.x:
            pygame.draw.rect(surface, wc, (sr.x, sr.bottom - wall, gx_l - sr.x, wall))
        if gx_r < sr.right:
            pygame.draw.rect(surface, wc, (gx_r, sr.bottom - wall, sr.right - gx_r, wall))

        # Fence posts with barbed wire lines
        fc  = (80, 78, 64)
        wrc = (62, 60, 50)
        stp = self._POST_STP
        # Top edge (N gate gap)
        for fx in range(r.x, r.right + stp, stp):
            sx_ = fx - ox
            if sr.x <= sx_ <= sr.right and not (gx_l - 5 < sx_ < gx_r + 5):
                pygame.draw.rect(surface, fc, (sx_ - 2, sr.y - 9, 4, 9))
        pygame.draw.line(surface, wrc, (sr.x, sr.y - 4), (gx_l, sr.y - 4), 1)
        pygame.draw.line(surface, wrc, (gx_r, sr.y - 4), (sr.right, sr.y - 4), 1)
        pygame.draw.line(surface, wrc, (sr.x, sr.y - 7), (gx_l, sr.y - 7), 1)
        pygame.draw.line(surface, wrc, (gx_r, sr.y - 7), (sr.right, sr.y - 7), 1)
        # Bottom edge (S gate gap)
        for fx in range(r.x, r.right + stp, stp):
            sx_ = fx - ox
            if sr.x <= sx_ <= sr.right and not (gx_l - 5 < sx_ < gx_r + 5):
                pygame.draw.rect(surface, fc, (sx_ - 2, sr.bottom, 4, 9))
        pygame.draw.line(surface, wrc, (sr.x, sr.bottom + 3), (gx_l, sr.bottom + 3), 1)
        pygame.draw.line(surface, wrc, (gx_r, sr.bottom + 3), (sr.right, sr.bottom + 3), 1)
        # Left edge (W gate gap)
        for fy in range(r.y, r.bottom + stp, stp):
            sy_ = fy - oy
            if sr.y <= sy_ <= sr.bottom and not (gy_t - 5 < sy_ < gy_b + 5):
                pygame.draw.rect(surface, fc, (sr.x - 9, sy_ - 2, 9, 4))
        pygame.draw.line(surface, wrc, (sr.x - 4, sr.y), (sr.x - 4, gy_t), 1)
        pygame.draw.line(surface, wrc, (sr.x - 4, gy_b), (sr.x - 4, sr.bottom), 1)
        pygame.draw.line(surface, wrc, (sr.x - 7, sr.y), (sr.x - 7, gy_t), 1)
        pygame.draw.line(surface, wrc, (sr.x - 7, gy_b), (sr.x - 7, sr.bottom), 1)
        # Right edge (E gate gap)
        for fy in range(r.y, r.bottom + stp, stp):
            sy_ = fy - oy
            if sr.y <= sy_ <= sr.bottom and not (gy_t - 5 < sy_ < gy_b + 5):
                pygame.draw.rect(surface, fc, (sr.right, sy_ - 2, 9, 4))
        pygame.draw.line(surface, wrc, (sr.right + 4, sr.y), (sr.right + 4, gy_t), 1)
        pygame.draw.line(surface, wrc, (sr.right + 4, gy_b), (sr.right + 4, sr.bottom), 1)
        pygame.draw.line(surface, wrc, (sr.right + 7, sr.y), (sr.right + 7, gy_t), 1)
        pygame.draw.line(surface, wrc, (sr.right + 7, gy_b), (sr.right + 7, sr.bottom), 1)

        # Watchtowers at corners
        for tw_r in self._towers:
            stw = pygame.Rect(tw_r.x - ox, tw_r.y - oy, tw_r.w, tw_r.h)
            pygame.draw.rect(surface, (78, 74, 60), stw)
            pygame.draw.rect(surface, (108, 104, 84), stw, 2)
            # Slot windows on tower
            for di in range(2):
                ww, wh = 6, 3
                wx_ = stw.x + (stw.w - ww) // 2 + di * 2 - 1
                wy_ = stw.y + (stw.h - wh) // 2
                pygame.draw.rect(surface, (38, 38, 32), (wx_, wy_, ww, wh))

        # Player-inside tint
        if player_inside:
            hl = pygame.Surface((sr.w, sr.h), pygame.SRCALPHA)
            hl.fill((80, 100, 60, 8))
            surface.blit(hl, sr.topleft)

        if debug and font:
            txt = font.render(lang.t("zone_military"), True, (140, 200, 100))
            surface.blit(txt, (sr.centerx - txt.get_width() // 2,
                               sr.centery - txt.get_height() // 2))

    def draw_door_hint(self, surface, ox=0, oy=0, font=None):
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def create_zones():
    """Generate a random map layout. Returns a flat list of Zone / HideoutCompound."""
    placed   = []
    hideouts = _gen_hideouts(placed, n=22)
    lakes    = _gen_lakes   (placed, n=24)
    valleys  = _gen_valleys (placed, n=20)
    bushes   = _gen_bushes  (placed, n=45)
    # Draw order: valleys (ground) → lakes → hideouts → bushes (topmost)
    return valleys + lakes + hideouts + bushes


def get_loot_zones(zones):
    return [z for z in zones if z.is_loot_zone]
