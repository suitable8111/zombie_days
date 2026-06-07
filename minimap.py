"""
Minimap system for ZombeeDoor.

M key → full-screen overlay minimap.
Fog-of-war: only visited areas are revealed.
F1 debug mode → fog disabled, everything shown.
"""
import pygame

# ── Constants ─────────────────────────────────────────────────────────────────
CELL_SIZE      = 256     # world-px per fog cell (finer = smoother fog edges)
EXPLORE_RADIUS = 420     # world-px revealed around the player each frame
MAP_DISPLAY    = 680     # on-screen minimap square (px); auto-clamped to screen

# Minimap colours
_COL_BG_EXPLORE  = (30, 32, 27)    # explored but empty ground
_COL_BG_DARK     = (6,  6,  6)     # unexplored (fog)
_COL_BORDER      = (90, 80, 55)
_COL_PLAYER      = (120, 190, 255)
_COL_ZOMBIE      = (210, 50,  40)
_COL_NPC         = (70,  200, 80)
_COL_VEHICLE     = (240, 220, 70)
_COL_CURRENT_VEH = (255, 255, 120)

# Zone minimap colours  (zone_type → colour)
_ZONE_COL = {
    "bush":    (40,  90,  30),
    "lake":    (30,  70, 130),
    "valley":  (65,  54,  38),
    "road":    (58,  58,  52),
    "hideout": (75,  62,  48),
    "cliff":   (70,  60,  46),
}
# Shop type overrides for hideout zones
_SHOP_COL = {
    "weapon":   (110, 40, 40),
    "hospital": (40, 100, 40),
    "hardware": (40,  50, 110),
}


def _zone_col(zone):
    st = getattr(zone, 'shop_type', None)
    if st:
        return _SHOP_COL.get(st, (80, 70, 60))
    return _ZONE_COL.get(zone.zone_type, (50, 50, 50))


class Minimap:
    def __init__(self, world_w: int, world_h: int):
        self.world_w  = world_w
        self.world_h  = world_h
        self._cols    = world_w // CELL_SIZE + 1
        self._rows    = world_h // CELL_SIZE + 1
        # Set of explored (gx, gy) cell indices
        self._explored: set[tuple[int, int]] = set()

    # ── Exploration update (call every frame) ─────────────────────────────────

    def explore(self, pos: pygame.Vector2, extra_radius: int = 0):
        """Mark cells within EXPLORE_RADIUS+extra_radius of pos as explored."""
        radius = EXPLORE_RADIUS + extra_radius
        cx = int(pos.x) // CELL_SIZE
        cy = int(pos.y) // CELL_SIZE
        cr = radius // CELL_SIZE + 1
        for dy in range(-cr, cr + 1):
            for dx in range(-cr, cr + 1):
                gx, gy = cx + dx, cy + dy
                if 0 <= gx < self._cols and 0 <= gy < self._rows:
                    self._explored.add((gx, gy))

    def is_explored(self, wx: float, wy: float) -> bool:
        gx = int(wx) // CELL_SIZE
        gy = int(wy) // CELL_SIZE
        return (gx, gy) in self._explored

    # ── Full-screen render ────────────────────────────────────────────────────

    def draw(self, surface, player, zones, zombies, npcs, vehicles,
             current_vehicle, debug: bool,
             screen_w: int = 1024, screen_h: int = 768):
        SW = surface.get_width()
        SH = surface.get_height()

        MAP_SZ = min(MAP_DISPLAY, SW - 60, SH - 60)
        mx     = (SW - MAP_SZ) // 2
        my     = (SH - MAP_SZ) // 2

        # Scale: world-px → map-px
        scale_x = MAP_SZ / self.world_w
        scale_y = MAP_SZ / self.world_h
        sc      = min(scale_x, scale_y)   # keep square

        def w2m(wx, wy):
            """World → map-surface pixel."""
            return int(wx * sc), int(wy * sc)

        # ── Dim the game behind the map ────────────────────────────────────
        overlay = pygame.Surface((SW, SH), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 185))
        surface.blit(overlay, (0, 0))

        # ── Map surface ────────────────────────────────────────────────────
        ms = pygame.Surface((MAP_SZ, MAP_SZ))
        ms.fill(_COL_BG_DARK)

        # ── Explored ground tiles ──────────────────────────────────────────
        cell_px = max(1, int(CELL_SIZE * sc) + 1)   # +1 to fill gaps
        if debug:
            # Reveal all ground
            ms.fill(_COL_BG_EXPLORE)
        else:
            for gx, gy in self._explored:
                sx = int(gx * CELL_SIZE * sc)
                sy = int(gy * CELL_SIZE * sc)
                ms.fill(_COL_BG_EXPLORE, (sx, sy, cell_px, cell_px))

        # ── Zones ─────────────────────────────────────────────────────────
        for zone in zones:
            r   = zone.rect
            col = _zone_col(zone)
            # Fog check: use zone centre
            if not debug and not self.is_explored(r.centerx, r.centery):
                continue
            sx, sy   = w2m(r.x, r.y)
            sw, sh   = max(1, int(r.w * sc)), max(1, int(r.h * sc))
            ms.fill(col, (sx, sy, sw, sh))

        # ── Entity dots ────────────────────────────────────────────────────
        # Zombies
        for z in zombies:
            if not debug and not self.is_explored(z.pos.x, z.pos.y):
                continue
            sx, sy = w2m(z.pos.x, z.pos.y)
            if 0 <= sx < MAP_SZ and 0 <= sy < MAP_SZ:
                pygame.draw.circle(ms, _COL_ZOMBIE, (sx, sy), 2)

        # NPCs
        for n in npcs:
            if not debug and not self.is_explored(n.pos.x, n.pos.y):
                continue
            sx, sy = w2m(n.pos.x, n.pos.y)
            if 0 <= sx < MAP_SZ and 0 <= sy < MAP_SZ:
                pygame.draw.circle(ms, _COL_NPC, (sx, sy), 2)

        # Vehicles
        for v in vehicles:
            if not debug and not self.is_explored(v.pos.x, v.pos.y):
                continue
            sx, sy = w2m(v.pos.x, v.pos.y)
            if 0 <= sx < MAP_SZ and 0 <= sy < MAP_SZ:
                col = _COL_CURRENT_VEH if v is current_vehicle else _COL_VEHICLE
                pygame.draw.rect(ms, col, (sx - 2, sy - 2, 5, 5))

        # ── Player (always visible on minimap) ────────────────────────────
        px, py = w2m(player.pos.x, player.pos.y)
        if 0 <= px < MAP_SZ and 0 <= py < MAP_SZ:
            pygame.draw.circle(ms, _COL_PLAYER, (px, py), 5)
            # Facing arrow
            ad   = player.aim_dir
            ex   = px + int(ad.x * 10)
            ey   = py + int(ad.y * 10)
            pygame.draw.line(ms, (200, 240, 255), (px, py), (ex, ey), 2)

        # ── Current-view rectangle (what the camera sees) ────────────────
        vx, vy = w2m(player.pos.x - screen_w / 2,
                     player.pos.y - screen_h / 2)
        vw     = max(2, int(screen_w * sc))
        vh     = max(2, int(screen_h * sc))
        pygame.draw.rect(ms, (140, 140, 120), (vx, vy, vw, vh), 1)

        # ── Blit map surface ───────────────────────────────────────────────
        surface.blit(ms, (mx, my))

        # ── Border ────────────────────────────────────────────────────────
        pygame.draw.rect(surface, _COL_BORDER,
                         (mx - 1, my - 1, MAP_SZ + 2, MAP_SZ + 2), 2,
                         border_radius=3)

        # ── Legend ────────────────────────────────────────────────────────
        self._draw_legend(surface, mx, my, MAP_SZ, debug)

    def _draw_legend(self, surface, mx, my, map_sz, debug):
        import fonts
        import lang
        font = fonts.get(13)

        title_font = fonts.get(18)
        title = title_font.render(lang.t("minimap_title"), True, (220, 210, 160))
        surface.blit(title, (mx + map_sz // 2 - title.get_width() // 2,
                              my - title.get_height() - 8))

        hint = font.render(lang.t("minimap_close"), True, (110, 110, 95))
        surface.blit(hint, (mx + map_sz // 2 - hint.get_width() // 2,
                             my + map_sz + 6))

        if debug:
            dbg = font.render(lang.t("minimap_debug"), True, (100, 200, 100))
            surface.blit(dbg, (mx + 6, my + map_sz + 6))

        # Colour key (bottom-right of map)
        items = [
            (_COL_PLAYER,      lang.t("minimap_leg_player")),
            (_COL_ZOMBIE,      lang.t("minimap_leg_zombie")),
            (_COL_NPC,         lang.t("minimap_leg_npc")),
            (_COL_VEHICLE,     lang.t("minimap_leg_vehicle")),
            (_SHOP_COL["weapon"],   lang.t("minimap_leg_shop_w")),
            (_SHOP_COL["hospital"], lang.t("minimap_leg_shop_h")),
            (_SHOP_COL["hardware"], lang.t("minimap_leg_shop_hw")),
        ]
        lx = mx + map_sz + 10
        ly = my
        for col, text in items:
            pygame.draw.circle(surface, col, (lx + 5, ly + 7), 4)
            ts = font.render(text, True, (180, 175, 160))
            surface.blit(ts, (lx + 14, ly + 1))
            ly += 18

    # ── Small HUD corner minimap (always visible, tiny) ───────────────────────

    def draw_hud(self, surface, player, zones, current_vehicle, debug: bool):
        """Tiny corner minimap (always rendered, no fog)."""
        HUD_SZ  = 120
        padding = 6
        sx_off  = surface.get_width()  - HUD_SZ - padding
        sy_off  = surface.get_height() - HUD_SZ - padding - 88  # above slot bar

        sc = HUD_SZ / max(self.world_w, self.world_h)

        hud = pygame.Surface((HUD_SZ, HUD_SZ), pygame.SRCALPHA)
        hud.fill((0, 0, 0, 160))

        # Explored cells (or all in debug)
        cell_px = max(1, int(CELL_SIZE * sc) + 1)
        if debug:
            hud.fill(_COL_BG_EXPLORE + (160,))
        else:
            for gx, gy in self._explored:
                hx = int(gx * CELL_SIZE * sc)
                hy = int(gy * CELL_SIZE * sc)
                pygame.draw.rect(hud, _COL_BG_EXPLORE + (180,),
                                 (hx, hy, cell_px, cell_px))

        # Zones (explored only, or all in debug)
        for zone in zones:
            r = zone.rect
            if not debug and not self.is_explored(r.centerx, r.centery):
                continue
            col = _zone_col(zone)
            hx = int(r.x * sc)
            hy = int(r.y * sc)
            hw = max(1, int(r.w * sc))
            hh = max(1, int(r.h * sc))
            pygame.draw.rect(hud, col + (200,), (hx, hy, hw, hh))

        # Player dot
        ppx = int(player.pos.x * sc)
        ppy = int(player.pos.y * sc)
        ppx = max(2, min(HUD_SZ - 3, ppx))
        ppy = max(2, min(HUD_SZ - 3, ppy))
        pygame.draw.circle(hud, _COL_PLAYER, (ppx, ppy), 3)

        # Current vehicle
        if current_vehicle is not None:
            vx = int(current_vehicle.pos.x * sc)
            vy = int(current_vehicle.pos.y * sc)
            vx = max(2, min(HUD_SZ - 3, vx))
            vy = max(2, min(HUD_SZ - 3, vy))
            pygame.draw.rect(hud, _COL_CURRENT_VEH, (vx - 2, vy - 2, 5, 5))

        surface.blit(hud, (sx_off, sy_off))
        pygame.draw.rect(surface, (70, 65, 50),
                         (sx_off - 1, sy_off - 1, HUD_SZ + 2, HUD_SZ + 2), 1)
