"""
Vehicle system for ZombeeDoor.
Driveable cars with angle-based steering, fuel, HP, and roadkill.
"""
import pygame
import math
import random

# ── Tuning ────────────────────────────────────────────────────────────────────
VEH_ACCEL          = 340.0    # px/s²
VEH_BRAKE          = 500.0    # px/s²
VEH_FRICTION       = 180.0    # px/s² passive decel
VEH_MAX_SPEED      = 600.0    # px/s forward
VEH_MAX_REV        = 200.0    # px/s reverse
VEH_STEER_SPD      = 110.0    # deg/s at full speed

VEH_ENTER_R        = 70       # board-distance (px)

VEH_MAX_HP         = 200
VEH_MAX_FUEL       = 100.0    # seconds of driving at speed
VEH_FUEL_DRAIN     = 0.25     # fuel/s while engine spins

VEH_ROADKILL_SPEED = 100.0    # min |speed| to trigger roadkill
VEH_ROADKILL_DMGZ  = 80       # damage per zombie hit
VEH_ROADKILL_DMGV  = 8        # vehicle HP lost per zombie hit

VEH_EXPLODE_R      = 120      # explosion blast radius (passed to ParticleManager)
VEH_BOUNDING_R     = 34      # collision circle radius (≈ sqrt(hw²+hl²) for 18×30 car)
# Wall collision damage tiers (by |speed|)
VEH_WALL_DMG_TIER1_SPD = 100   # below this: no damage, just bounce
VEH_WALL_DMG_TIER2_SPD = 250   # below this: minor  (5–15)
VEH_WALL_DMG_TIER3_SPD = 450   # below this: moderate (20–40)
                                # at or above: severe (50–80)

# ── Motorcycle ────────────────────────────────────────────────────────────────
MOTO_MAX_SPEED  = 1080.0   # 1.8× car
MOTO_ACCEL      = 580.0
MOTO_STEER_SPD  = 170.0
MOTO_MAX_HP     = 70

# ── Tank ──────────────────────────────────────────────────────────────────────
TANK_MAX_SPEED  = 210.0
TANK_MAX_REV    = 75.0
TANK_ACCEL      = 85.0
TANK_STEER_SPD  = 38.0
TANK_MAX_HP     = 500
TANK_CANNON_R   = 120      # blast radius px
TANK_CANNON_RNG = 460      # barrel length (px ahead of tank centre)
TANK_CANNON_CD  = 2.5      # seconds between shots

# ── Helicopter ────────────────────────────────────────────────────────────────
HELI_MAX_SPEED   = 480.0
HELI_ACCEL       = 220.0
HELI_STEER_SPD   = 115.0
HELI_MAX_HP      = 150
HELI_MAX_FUEL    = 60.0
HELI_FUEL_DRAIN  = 0.50
HELI_LIFT_RATE   = 0.75    # altitude/s when Space held
HELI_FALL_RATE   = 0.40
HELI_MG_SPINUP   = 1.0    # hold Space this long (s) before gun fires
HELI_MG_FIRE_CD  = 0.07   # s between shots when spun up  ≈ 14 rds/s
HELI_MG_SPREAD   = 75     # world-px spread radius at target
HELI_MG_DMG      = 30
HELI_MG_SPEED    = 650    # bullet speed px/s

# ── Airplane ──────────────────────────────────────────────────────────────────
PLANE_MAX_SPEED   = 820.0
PLANE_STALL_SPD   = 380.0  # below this when airborne → begin landing
PLANE_TAKEOFF_SPD = 400.0  # ground speed needed to lift off
PLANE_ACCEL       = 140.0
PLANE_STEER_SPD   = 52.0
PLANE_MAX_HP      = 200
PLANE_MAX_FUEL    = 80.0
PLANE_CARPET_R    = 300    # blast radius of each carpet bomb
PLANE_CARPET_N    = 7      # bombs in one carpet run
PLANE_CARPET_CD   = 8.0    # cooldown (s)
PLANE_BOMB_R      = PLANE_CARPET_R   # kept for any external references
PLANE_BOMB_CD     = PLANE_CARPET_CD

# ── Colours ───────────────────────────────────────────────────────────────────
_COL_BODY  = (100, 90, 75)
_COL_ROOF  = (78,  72, 60)
_COL_GLASS = (72, 120, 155)
_COL_WHEEL = (28,  28, 28)
_COL_HEADL = (255, 248, 190)
_COL_TAILL = (200,  45, 28)
_COL_DMGD  = (130,  50, 25)


def _circle_rect_overlap(cx: float, cy: float, radius: float,
                         rect: "pygame.Rect") -> bool:
    """Standard circle-AABB overlap test."""
    nearest_x = max(rect.left, min(cx, rect.right))
    nearest_y = max(rect.top,  min(cy, rect.bottom))
    dx = cx - nearest_x
    dy = cy - nearest_y
    return dx * dx + dy * dy < radius * radius


def _lerp3(a, b, t):
    t = max(0.0, min(1.0, t))
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


class Vehicle:
    def __init__(self, x: float, y: float):
        self.pos       = pygame.Vector2(x, y)
        self.angle     = 0.0          # degrees; 0 = facing up/north
        self.speed     = 0.0          # px/s; +forward, −reverse
        self.hp        = VEH_MAX_HP
        self.fuel      = VEH_MAX_FUEL * 0.65  # partially filled when found
        self.alive     = True
        self._occupied = False
        self._hit_tmr  = 0.0          # brief flash on impact

        # Collision box half-extents
        self._hw = 18   # half-width  (px)
        self._hl = 30   # half-length (px)

        # Per-instance tuning (subclasses override in their __init__)
        self._max_speed  = VEH_MAX_SPEED
        self._max_rev    = VEH_MAX_REV
        self._accel      = VEH_ACCEL
        self._brake      = VEH_BRAKE
        self._friction   = VEH_FRICTION
        self._steer_spd  = VEH_STEER_SPD
        self._fuel_drain = VEH_FUEL_DRAIN
        self._max_hp     = VEH_MAX_HP
        self._max_fuel   = VEH_MAX_FUEL

        # Vehicle meta
        self._kind            = "car"
        self.rider_exposure   = 0.0   # fraction of zombie dmg that bleeds to rider
        self.damage_reduction = 0.0   # fraction of zombie dmg absorbed by armour (tank=0.9)
        self._ram_buildings   = False  # True = plow through hideouts instead of bouncing
        self._last_hit_zone   = None   # set each frame; main.py reads and clears it
        self._can_ford        = False  # True = can enter water (tank)
        self._ford_timer      = 0.0   # seconds spent in water this dip
        self._in_water        = False  # set true each frame the vehicle is in water
        self._exploded        = False  # True after wreck explosion has already fired

    # ── Geometry helpers ──────────────────────────────────────────────────────

    def _fwd(self) -> pygame.Vector2:
        r = math.radians(self.angle)
        return pygame.Vector2(math.sin(r), -math.cos(r))

    def _rgt(self) -> pygame.Vector2:
        f = self._fwd()
        return pygame.Vector2(f.y, -f.x)

    # ── API ───────────────────────────────────────────────────────────────────

    def draw_wreck(self, surface, ox=0, oy=0):
        """Draw scorched wreck that remains after the vehicle explodes."""
        cx = int(self.pos.x) - ox
        cy = int(self.pos.y) - oy
        r  = math.radians(self.angle)
        fx, fy = math.sin(r), -math.cos(r)   # forward unit vector
        rx, ry = math.cos(r),  math.sin(r)   # right unit vector

        def pt(f, ri):
            return (cx + int(fx * f + rx * ri),
                    cy + int(fy * f + ry * ri))

        hw, hl = self._hw, self._hl

        # Charred hull — slightly smaller than original
        hull = [pt(-hl + 4, -hw + 3), pt(-hl + 4, hw - 3),
                pt(hl - 4, hw - 3),  pt(hl - 4, -hw + 3)]
        pygame.draw.polygon(surface, (22, 18, 14), hull)
        pygame.draw.polygon(surface, (40, 34, 26), hull, 2)

        # Burnt frame rails
        pygame.draw.line(surface, (35, 28, 20),
                         pt(-hl, -hw + 4), pt(hl, -hw + 4), 2)
        pygame.draw.line(surface, (35, 28, 20),
                         pt(-hl, hw - 4), pt(hl, hw - 4), 2)

        # Deterministic scorch blotches
        seed = (int(self.pos.x) * 73856093) ^ (int(self.pos.y) * 19349663)
        for i in range(6):
            seed = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
            bf   = ((seed >> 16) % (hl * 2)) - hl
            seed = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
            br   = ((seed >> 16) % (hw * 2)) - hw
            seed = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
            bsz  = 3 + (seed >> 24) % 5
            pygame.draw.circle(surface, (14, 11, 8), pt(bf, br), bsz)

        # Scattered debris around wreck
        seed2 = seed
        for i in range(8):
            seed2 = (seed2 * 1664525 + 1013904223) & 0xFFFFFFFF
            df  = ((seed2 >> 16) % (hl * 3)) - hl
            seed2 = (seed2 * 1664525 + 1013904223) & 0xFFFFFFFF
            dr  = ((seed2 >> 16) % (hw * 3)) - hw
            seed2 = (seed2 * 1664525 + 1013904223) & 0xFFFFFFFF
            dsz = 1 + (seed2 >> 26) % 3
            cv  = 30 + (seed2 >> 18) % 25
            pygame.draw.rect(surface, (cv, cv - 6, cv - 14),
                             (cx + int(fx * df + rx * dr) - dsz,
                              cy + int(fy * df + ry * dr) - dsz,
                              dsz * 2, dsz * 2))

        # Lingering smoke wisps (animated)
        t = pygame.time.get_ticks() / 1000.0
        for i in range(3):
            wx = cx + int(fx * ((i - 1) * hl * 0.4) + rx * ((i % 2) * hw * 0.5 - hw * 0.25))
            wy = cy + int(fy * ((i - 1) * hl * 0.4) + ry * ((i % 2) * hw * 0.5 - hw * 0.25))
            sa = int(22 + 14 * math.sin(t * 1.1 + i * 2.0))
            ss = pygame.Surface((14, 14), pygame.SRCALPHA)
            pygame.draw.circle(ss, (38, 34, 30, max(0, sa)), (7, 7), 7)
            surface.blit(ss, (wx - 7, wy - 7))

    def take_damage(self, amount: int) -> None:
        """Apply explosion/collision damage. Marks alive=False when hp reaches 0."""
        if not self.alive:
            return
        self.hp -= amount
        self._hit_tmr = 0.30
        if self.hp <= 0:
            self.hp    = 0
            self.alive = False

    def is_near(self, pos: pygame.Vector2) -> bool:
        return self.alive and self.pos.distance_to(pos) < VEH_ENTER_R

    def enter(self) -> bool:
        if self.alive and not self._occupied:
            self._occupied = True
            return True
        return False

    def leave(self) -> pygame.Vector2:
        """Exit vehicle; returns the world position to place the player."""
        self._occupied = False
        self.speed     = 0.0
        rgt = self._rgt()
        return pygame.Vector2(self.pos.x + rgt.x * (self._hw + 22),
                              self.pos.y + rgt.y * (self._hw + 22))

    def add_fuel(self, amount: float):
        self.fuel = min(self._max_fuel, self.fuel + amount)

    # ── Driving update (call every frame when occupied) ───────────────────────

    def update_drive(self, dt: float, keys, bounds: tuple,
                     zones=None) -> int:
        """
        Drives for one frame.
        Returns collision damage (> 0 if car hit a solid zone this frame).
        Caller should apply the same damage to the player.
        """
        self._hit_tmr = max(0.0, self._hit_tmr - dt)
        world_w, world_h = bounds

        # Throttle / brake
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            self.speed = min(self._max_speed, self.speed + self._accel * dt)
        elif keys[pygame.K_s] or keys[pygame.K_DOWN]:
            self.speed = max(-self._max_rev, self.speed - self._brake * dt)
        else:
            friction_step = self._friction * dt
            if abs(self.speed) < friction_step:
                self.speed = 0.0
            else:
                self.speed -= math.copysign(friction_step, self.speed)

        # Steering (scales with speed so stationary car doesn't spin)
        spd_f = min(1.0, abs(self.speed) / 200.0)
        steer = 0.0
        if abs(self.speed) > 5:
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                steer = -self._steer_spd * spd_f
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                steer = +self._steer_spd * spd_f
            if self.speed < 0:
                steer = -steer
        self.angle = (self.angle + steer * dt) % 360.0

        # Tentative new position
        fwd = self._fwd()
        nx = max(0.0, min(world_w, self.pos.x + fwd.x * self.speed * dt))
        ny = max(0.0, min(world_h, self.pos.y + fwd.y * self.speed * dt))

        # ── Zone collision ─────────────────────────────────────────────────
        collision_dmg = 0
        self._last_hit_zone  = None
        self._in_water       = False
        if zones:
            # Road suppresses terrain collision (lake/river overlapping a road)
            _veh_on_road = any(z.zone_type == "road"
                               and z.rect.collidepoint(nx, ny)
                               for z in zones)
            for zone in zones:
                if zone.zone_type not in ("lake", "hideout", "cliff"):
                    continue
                if _veh_on_road:
                    continue   # road overrides all terrain — no collision on road
                # Destroyed buildings: all vehicles pass through freely
                if getattr(zone, "destroyed", False):
                    continue
                # Fordable vehicle (tank) crosses water — mark in-water, no bounce
                if self._can_ford and zone.zone_type == "lake":
                    check_rect = getattr(zone, "_bounds", zone.rect)
                    if _circle_rect_overlap(nx, ny, VEH_BOUNDING_R, check_rect):
                        self._in_water = True
                    continue
                # Tank rams through hideout buildings — record hit, skip bounce
                if self._ram_buildings and zone.zone_type == "hideout":
                    check_rect = getattr(zone, "_bounds", zone.rect)
                    if _circle_rect_overlap(nx, ny, VEH_BOUNDING_R, check_rect):
                        self._last_hit_zone = zone
                    continue   # no bounce — tank passes through
                check_rect = getattr(zone, "_bounds", zone.rect)
                if _circle_rect_overlap(nx, ny, VEH_BOUNDING_R, check_rect):
                    spd = abs(self.speed)
                    # Tiered damage: light tap = 0, medium = moderate, hard = severe
                    if spd < VEH_WALL_DMG_TIER1_SPD:
                        dmg = 0
                    elif spd < VEH_WALL_DMG_TIER2_SPD:
                        dmg = int(5 + (spd - VEH_WALL_DMG_TIER1_SPD) /
                                  (VEH_WALL_DMG_TIER2_SPD - VEH_WALL_DMG_TIER1_SPD) * 10)
                    elif spd < VEH_WALL_DMG_TIER3_SPD:
                        dmg = int(20 + (spd - VEH_WALL_DMG_TIER2_SPD) /
                                  (VEH_WALL_DMG_TIER3_SPD - VEH_WALL_DMG_TIER2_SPD) * 20)
                    else:
                        dmg = min(80, int(50 + (spd - VEH_WALL_DMG_TIER3_SPD) / 150 * 30))
                    if dmg > 0:
                        self.hp      -= dmg
                        self._hit_tmr = 0.30
                        collision_dmg = dmg
                        if self.hp <= 0 and self.alive:
                            self.alive     = False
                            self._occupied = False
                    # Bounce: damped reflection (always)
                    self.speed = -self.speed * 0.25
                    nx, ny = self.pos.x, self.pos.y   # revert movement
                    break

        self.pos.x = nx
        self.pos.y = ny

        # ── Water traversal penalties (fordable vehicles only) ─────────────
        if self._can_ford:
            if self._in_water:
                self._ford_timer += dt
                # Speed cap in water: 55% of normal max
                water_cap = self._max_speed * 0.55
                if abs(self.speed) > water_cap:
                    self.speed = math.copysign(water_cap, self.speed)
                # Engine damage ramps up after 6 s underwater
                _excess = max(0.0, self._ford_timer - 6.0)
                if _excess > 0:
                    _dmg = _excess * 18 * dt
                    self.hp      -= _dmg
                    self._hit_tmr = 0.30
                    if self.hp <= 0 and self.alive:
                        self.hp        = 0
                        self.alive     = False
                        self._occupied = False
            else:
                # Drain timer slowly when out of water
                self._ford_timer = max(0.0, self._ford_timer - dt * 1.5)

        # Fuel drain while moving
        if abs(self.speed) > 20:
            self.fuel = max(0.0, self.fuel - self._fuel_drain * dt)
        if self.fuel <= 0:
            self.speed = max(0.0, self.speed - self._brake * 0.4 * dt)

        return collision_dmg

    # ── Roadkill (call after update_drive) ───────────────────────────────────

    def check_roadkill(self, zombies: list) -> list:
        """
        Test the car body against each zombie.
        Returns list of (zombie, knockback_vector) for zombies that were hit.
        Also damages self.hp per collision. Sets self.alive=False if HP → 0.
        """
        if not self._occupied or abs(self.speed) < VEH_ROADKILL_SPEED:
            return []
        fwd   = self._fwd()
        hits  = []
        for z in zombies:
            if not z.alive:
                continue
            dist = self.pos.distance_to(z.pos)
            if dist > self._hl + z.radius:
                continue
            offs  = z.pos - self.pos
            knock = (fwd * 0.7 + offs.normalize() * 0.3) if offs.length() > 0.1 else fwd
            knock = knock.normalize()
            z.take_hit(VEH_ROADKILL_DMGZ, knock)
            self.hp      -= VEH_ROADKILL_DMGV
            self._hit_tmr = 0.18
            hits.append((z, knock))
        if self.hp <= 0 and self.alive:
            self.alive     = False
            self._occupied = False
        return hits

    # ── Draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface, ox: int, oy: int, debug: bool = False):
        if not self.alive:
            return
        cx = int(self.pos.x) - ox
        cy = int(self.pos.y) - oy

        fwd = self._fwd()
        rgt = self._rgt()
        hw, hl = self._hw, self._hl

        def pt(fl, fr):
            return (cx + fwd.x * fl + rgt.x * fr,
                    cy + fwd.y * fl + rgt.y * fr)

        # ── Body ──────────────────────────────────────────────────────────
        dmg_t    = max(0.0, 1.0 - self.hp / VEH_MAX_HP)
        body_col = _lerp3(_COL_BODY, _COL_DMGD, dmg_t)
        if self._hit_tmr > 0:
            body_col = (min(255, body_col[0] + 90), body_col[1], body_col[2])
        body = [pt(hl, -hw), pt(hl, hw), pt(-hl, hw), pt(-hl, -hw)]
        pygame.draw.polygon(surface, body_col, body)
        pygame.draw.polygon(surface, (55, 50, 40), body, 1)

        # ── Roof ──────────────────────────────────────────────────────────
        roof = [pt( hl * 0.55, -hw * 0.65), pt( hl * 0.55,  hw * 0.65),
                pt(-hl * 0.35,  hw * 0.65), pt(-hl * 0.35, -hw * 0.65)]
        pygame.draw.polygon(surface, _COL_ROOF, roof)

        # ── Windshield ────────────────────────────────────────────────────
        ws = [pt(hl * 0.92, -hw * 0.65), pt(hl * 0.92,  hw * 0.65),
              pt(hl * 0.55,  hw * 0.60), pt(hl * 0.55, -hw * 0.60)]
        pygame.draw.polygon(surface, _COL_GLASS, ws)

        # ── Wheels (four corners) ─────────────────────────────────────────
        for fl, fr in ((hl * 0.70,  hw), (hl * 0.70, -hw),
                       (-hl * 0.60,  hw), (-hl * 0.60, -hw)):
            wp = pygame.Vector2(pt(fl, fr))
            wpts = [wp + pygame.Vector2( fwd.x * 7 + rgt.x * 4,  fwd.y * 7 + rgt.y * 4),
                    wp + pygame.Vector2( fwd.x * 7 - rgt.x * 4,  fwd.y * 7 - rgt.y * 4),
                    wp + pygame.Vector2(-fwd.x * 7 - rgt.x * 4, -fwd.y * 7 - rgt.y * 4),
                    wp + pygame.Vector2(-fwd.x * 7 + rgt.x * 4, -fwd.y * 7 + rgt.y * 4)]
            pygame.draw.polygon(surface, _COL_WHEEL, wpts)

        # ── Head / tail lights ────────────────────────────────────────────
        for fr in (-hw * 0.55, hw * 0.55):
            p = pt(hl + 2, fr)
            pygame.draw.circle(surface, _COL_HEADL, (int(p[0]), int(p[1])), 4)
            q = pt(-hl - 2, fr)
            pygame.draw.circle(surface, _COL_TAILL, (int(q[0]), int(q[1])), 3)

        # ── Headlight beam (only when driving) ────────────────────────────
        if self._occupied:
            beam = [pt(hl, -hw * 0.5), pt(hl, hw * 0.5),
                    pt(hl + 230,  hw * 1.0), pt(hl + 230, -hw * 1.0)]
            bs = pygame.Surface((surface.get_width(), surface.get_height()),
                                pygame.SRCALPHA)
            pygame.draw.polygon(bs, (255, 255, 200, 16), beam)
            surface.blit(bs, (0, 0))

        if debug:
            pygame.draw.circle(surface, (220, 180, 50), (cx, cy), hl, 1)

    def draw_enter_hint(self, surface, ox: int, oy: int, font):
        import lang
        if getattr(self, 'altitude', 0.0) > 0.1:
            return  # airborne — can't board
        sx = int(self.pos.x) - ox
        sy = int(self.pos.y) - oy - self._hl - 20
        txt = font.render(lang.t("veh_enter_hint"), True, (240, 230, 100))
        surface.blit(txt, (sx - txt.get_width() // 2, sy))


# ── Motorcycle ────────────────────────────────────────────────────────────────

class Motorcycle(Vehicle):
    def __init__(self, x: float, y: float):
        super().__init__(x, y)
        self._max_speed  = MOTO_MAX_SPEED
        self._accel      = MOTO_ACCEL
        self._steer_spd  = MOTO_STEER_SPD
        self._max_hp     = MOTO_MAX_HP
        self.hp          = MOTO_MAX_HP
        self._hw         = 8
        self._hl         = 24
        self._kind       = "motorcycle"
        self.rider_exposure = 0.30   # 30% zombie dmg bleeds to rider
        self._wheel_spin = 0.0

    def update_drive(self, dt, keys, bounds, zones=None):
        self._wheel_spin = (self._wheel_spin + abs(self.speed) * dt * 4.0) % 360
        return super().update_drive(dt, keys, bounds, zones)

    def draw(self, surface, ox: int, oy: int, debug: bool = False):
        if not self.alive:
            return
        cx = int(self.pos.x) - ox
        cy = int(self.pos.y) - oy
        fwd = self._fwd()
        rgt = self._rgt()

        def pt(fl, fr):
            return (cx + fwd.x * fl + rgt.x * fr,
                    cy + fwd.y * fl + rgt.y * fr)

        dmg_t    = max(0.0, 1.0 - self.hp / self._max_hp)
        body_col = _lerp3((55, 50, 38), _COL_DMGD, dmg_t)
        if self._hit_tmr > 0:
            body_col = (min(255, body_col[0] + 90), body_col[1], body_col[2])

        # Rear wheel
        wr = pt(-self._hl * 0.72, 0)
        pygame.draw.circle(surface, _COL_WHEEL, (int(wr[0]), int(wr[1])), 7)
        pygame.draw.circle(surface, (65, 65, 65), (int(wr[0]), int(wr[1])), 4)
        for sa in range(0, 360, 90):
            ra = math.radians(sa + self._wheel_spin)
            pygame.draw.line(surface, (50, 50, 50),
                             (int(wr[0]), int(wr[1])),
                             (int(wr[0] + math.cos(ra) * 4),
                              int(wr[1] + math.sin(ra) * 4)), 1)

        # Front wheel
        wf = pt(self._hl * 0.78, 0)
        pygame.draw.circle(surface, _COL_WHEEL, (int(wf[0]), int(wf[1])), 7)
        pygame.draw.circle(surface, (65, 65, 65), (int(wf[0]), int(wf[1])), 4)
        for sa in range(0, 360, 90):
            ra = math.radians(sa + self._wheel_spin)
            pygame.draw.line(surface, (50, 50, 50),
                             (int(wf[0]), int(wf[1])),
                             (int(wf[0] + math.cos(ra) * 4),
                              int(wf[1] + math.sin(ra) * 4)), 1)

        # Frame
        body = [pt(self._hl * 0.60,  -4), pt(self._hl * 0.60,  4),
                pt(-self._hl * 0.60,  4), pt(-self._hl * 0.60, -4)]
        pygame.draw.polygon(surface, body_col, body)

        # Gas tank bump
        tank = [pt(6, -5), pt(6, 5), pt(-7, 5), pt(-7, -5)]
        pygame.draw.polygon(surface, _lerp3((80, 75, 55), _COL_DMGD, dmg_t), tank)

        # Handlebar
        hbl = pt(self._hl * 0.55, -9)
        hbr = pt(self._hl * 0.55,  9)
        pygame.draw.line(surface, (100, 95, 80),
                         (int(hbl[0]), int(hbl[1])),
                         (int(hbr[0]), int(hbr[1])), 3)

        # Headlight
        hlp = pt(self._hl * 0.72, 0)
        pygame.draw.circle(surface, _COL_HEADL, (int(hlp[0]), int(hlp[1])), 3)

        if debug:
            pygame.draw.circle(surface, (220, 180, 50), (cx, cy), self._hl, 1)


# ── Tank ──────────────────────────────────────────────────────────────────────

class Tank(Vehicle):
    def __init__(self, x: float, y: float):
        super().__init__(x, y)
        self._max_speed  = TANK_MAX_SPEED
        self._max_rev    = TANK_MAX_REV
        self._accel      = TANK_ACCEL
        self._steer_spd  = TANK_STEER_SPD
        self._max_hp     = TANK_MAX_HP
        self.hp          = TANK_MAX_HP
        self._hw         = 28
        self._hl         = 40
        self._kind       = "tank"
        self.damage_reduction = 0.90  # 90% zombie dmg absorbed by armour
        self.turret_angle     = 0.0   # independent of hull angle
        self._cannon_cd       = 0.0
        self._ram_buildings   = True  # tank plows through hideouts
        self._can_ford        = True  # tank crosses rivers (with penalties)

    def update_turret(self, world_mouse: pygame.Vector2):
        diff = world_mouse - self.pos
        if diff.length_squared() > 1:
            self.turret_angle = math.degrees(math.atan2(diff.x, -diff.y)) % 360

    def fire_cannon(self, target_pos=None) -> tuple | None:
        """Returns (blast_pos, TANK_CANNON_R) if ready, else None.
        target_pos: world position to aim at (clamped to max range along turret axis)."""
        if self._cannon_cd > 0:
            return None
        self._cannon_cd = TANK_CANNON_CD
        tr   = math.radians(self.turret_angle)
        tfwd = pygame.Vector2(math.sin(tr), -math.cos(tr))
        if target_pos is not None:
            diff = pygame.Vector2(target_pos) - self.pos
            dist = diff.length()
            blast_pos = self.pos + tfwd * min(dist, TANK_CANNON_RNG)
        else:
            blast_pos = self.pos + tfwd * TANK_CANNON_RNG
        return (blast_pos, TANK_CANNON_R)

    def update_drive(self, dt, keys, bounds, zones=None):
        self._cannon_cd = max(0.0, self._cannon_cd - dt)
        return super().update_drive(dt, keys, bounds, zones)

    def draw(self, surface, ox: int, oy: int, debug: bool = False):
        if not self.alive:
            return
        cx = int(self.pos.x) - ox
        cy = int(self.pos.y) - oy
        fwd = self._fwd()
        rgt = self._rgt()

        def pt(fl, fr):
            return (cx + fwd.x * fl + rgt.x * fr,
                    cy + fwd.y * fl + rgt.y * fr)

        # Treads (both sides)
        for side in (-1, 1):
            trd = [pt( self._hl + 4, side * (self._hw + 5)),
                   pt( self._hl + 4, side * (self._hw + 10)),
                   pt(-self._hl - 4, side * (self._hw + 10)),
                   pt(-self._hl - 4, side * (self._hw + 5))]
            pygame.draw.polygon(surface, (42, 36, 25), trd)
            # Segment marks
            for si in range(-4, 5):
                fl  = si * (self._hl / 4)
                seg = [pt(fl - 3, side * (self._hw + 5)),
                       pt(fl + 3, side * (self._hw + 5)),
                       pt(fl + 3, side * (self._hw + 10)),
                       pt(fl - 3, side * (self._hw + 10))]
                pygame.draw.polygon(surface, (28, 22, 14), seg, 1)

        # Hull
        dmg_t    = max(0.0, 1.0 - self.hp / self._max_hp)
        hull_col = _lerp3((68, 78, 52), _COL_DMGD, dmg_t)
        if self._hit_tmr > 0:
            hull_col = (min(255, hull_col[0] + 70), hull_col[1], hull_col[2])
        hull = [pt(self._hl, -self._hw), pt(self._hl, self._hw),
                pt(-self._hl, self._hw), pt(-self._hl, -self._hw)]
        pygame.draw.polygon(surface, hull_col, hull)
        pygame.draw.polygon(surface, (40, 46, 30), hull, 2)

        # Turret (independent rotation)
        tr   = math.radians(self.turret_angle)
        tfwd = pygame.Vector2(math.sin(tr), -math.cos(tr))
        pygame.draw.circle(surface, (52, 62, 40), (cx, cy), 16)
        pygame.draw.circle(surface, (35, 44, 26), (cx, cy), 16, 2)

        # Barrel
        bstart = (cx + tfwd.x * 14, cy + tfwd.y * 14)
        bend   = (cx + tfwd.x * 52, cy + tfwd.y * 52)
        pygame.draw.line(surface, (35, 43, 25),
                         (int(bstart[0]), int(bstart[1])),
                         (int(bend[0]),   int(bend[1])), 7)
        pygame.draw.line(surface, (55, 65, 42),
                         (int(bstart[0]), int(bstart[1])),
                         (int(bend[0]),   int(bend[1])), 4)

        # Flash indicator when cannon cooling down
        if self._cannon_cd > TANK_CANNON_CD - 0.08:
            pygame.draw.circle(surface,
                               (255, 230, 80),
                               (int(bend[0]), int(bend[1])), 6)

        if debug:
            pygame.draw.circle(surface, (220, 180, 50), (cx, cy), self._hl, 1)


# ── Helicopter ────────────────────────────────────────────────────────────────

class Helicopter(Vehicle):
    def __init__(self, x: float, y: float):
        super().__init__(x, y)
        self._max_speed  = HELI_MAX_SPEED
        self._accel      = HELI_ACCEL
        self._steer_spd  = HELI_STEER_SPD
        self._max_hp     = HELI_MAX_HP
        self._max_fuel   = HELI_MAX_FUEL
        self._fuel_drain = HELI_FUEL_DRAIN
        self.hp          = HELI_MAX_HP
        self.fuel        = HELI_MAX_FUEL * 0.65
        self._hw         = 20
        self._hl         = 32
        self._kind       = "helicopter"
        self.altitude    = 0.0     # 0 = ground, 1 = fully airborne
        self._rotor_ang  = 0.0
        self._mg_hold    = 0.0    # seconds Space held continuously (spinup)
        self._mg_fire_cd = 0.0   # shot cooldown

    @property
    def is_airborne(self) -> bool:
        return self.altitude >= 0.98

    def check_roadkill(self, zombies: list) -> list:
        if self.altitude > 0.5:
            return []
        return super().check_roadkill(zombies)

    def update_drive(self, dt, keys, bounds, zones=None):  # noqa: ARG002
        self._rotor_ang  = (self._rotor_ang + (200 + self.altitude * 420) * dt) % 360
        self._mg_fire_cd = max(0.0, self._mg_fire_cd - dt)

        # Space = lift
        space = keys[pygame.K_SPACE]
        if space and self.fuel > 0:
            self.altitude = min(1.0, self.altitude + HELI_LIFT_RATE * dt)
        else:
            self.altitude = max(0.0, self.altitude - HELI_FALL_RATE * dt)

        self._hit_tmr = max(0.0, self._hit_tmr - dt)
        world_w, world_h = bounds

        if keys[pygame.K_w] or keys[pygame.K_UP]:
            self.speed = min(self._max_speed, self.speed + self._accel * dt)
        elif keys[pygame.K_s] or keys[pygame.K_DOWN]:
            self.speed = max(-self._max_rev, self.speed - self._brake * dt)
        else:
            fs = self._friction * dt
            if abs(self.speed) < fs:
                self.speed = 0.0
            else:
                self.speed -= math.copysign(fs, self.speed)

        spd_f = min(1.0, abs(self.speed) / 200.0)
        steer = 0.0
        if abs(self.speed) > 5:
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                steer = -self._steer_spd * spd_f
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                steer = +self._steer_spd * spd_f
            if self.speed < 0:
                steer = -steer
        self.angle = (self.angle + steer * dt) % 360.0

        fwd = self._fwd()
        nx = max(0.0, min(world_w, self.pos.x + fwd.x * self.speed * dt))
        ny = max(0.0, min(world_h, self.pos.y + fwd.y * self.speed * dt))

        # Helicopters fly over all terrain — no zone collision
        collision_dmg = 0
        self.pos.x = nx
        self.pos.y = ny

        if abs(self.speed) > 20 or self.altitude > 0.05:
            self.fuel = max(0.0, self.fuel - self._fuel_drain * dt)
        if self.fuel <= 0:
            self.altitude = max(0.0, self.altitude - HELI_FALL_RATE * 2 * dt)
            self.speed = max(0.0, self.speed - self._brake * 0.4 * dt)

        return collision_dmg

    @property
    def mg_spinup_ratio(self) -> float:
        """0.0 → 1.0 spinup progress (1.0 = gun fully ready)."""
        return min(1.0, self._mg_hold / HELI_MG_SPINUP)

    def fire_weapon(self, dt: float, space_held: bool,
                    world_mouse: pygame.Vector2) -> list:
        """Charge minigun while Space held; return shot descriptors when firing.
        Each descriptor: (origin, direction, damage, speed).
        """
        if space_held and self.is_airborne and self.fuel > 0:
            self._mg_hold = min(self._mg_hold + dt, HELI_MG_SPINUP + 0.5)
        else:
            self._mg_hold = max(0.0, self._mg_hold - dt * 2.5)

        shots = []
        if (self._mg_hold >= HELI_MG_SPINUP
                and self._mg_fire_cd <= 0
                and self.is_airborne):
            self._mg_fire_cd = HELI_MG_FIRE_CD
            sx = world_mouse.x + random.uniform(-HELI_MG_SPREAD, HELI_MG_SPREAD)
            sy = world_mouse.y + random.uniform(-HELI_MG_SPREAD, HELI_MG_SPREAD)
            target = pygame.Vector2(sx, sy)
            diff   = target - self.pos
            if diff.length_squared() > 0:
                shots.append((pygame.Vector2(self.pos),
                               diff.normalize(),
                               HELI_MG_DMG,
                               HELI_MG_SPEED))
        return shots

    def draw(self, surface, ox: int, oy: int, debug: bool = False):
        if not self.alive:
            return
        cx = int(self.pos.x) - ox
        cy = int(self.pos.y) - oy
        fwd = self._fwd()
        rgt = self._rgt()
        scale = 1.0 + self.altitude * 0.20
        hw = self._hw * scale
        hl = self._hl * scale

        def pt(fl, fr):
            return (cx + fwd.x * fl + rgt.x * fr,
                    cy + fwd.y * fl + rgt.y * fr)

        # Ground shadow (offset by altitude)
        sh_off = int(self.altitude * 36)
        if self.altitude > 0.04:
            sha = pygame.Surface((int(hl * 2.2), int(hw * 2.4)), pygame.SRCALPHA)
            sa  = int(110 * (1.0 - self.altitude * 0.45))
            pygame.draw.ellipse(sha, (0, 0, 0, sa), sha.get_rect())
            surface.blit(sha, (cx - sha.get_width() // 2,
                               cy + sh_off - sha.get_height() // 2))

        dmg_t    = max(0.0, 1.0 - self.hp / self._max_hp)
        body_col = _lerp3((88, 80, 58), _COL_DMGD, dmg_t)
        if self._hit_tmr > 0:
            body_col = (min(255, body_col[0] + 70), body_col[1], body_col[2])

        # Fuselage
        fuse = [pt( hl * 0.88, -hw * 0.50), pt( hl * 0.88,  hw * 0.50),
                pt(-hl * 0.45,  hw * 0.95), pt(-hl * 0.95,  hw * 0.35),
                pt(-hl * 0.95, -hw * 0.35), pt(-hl * 0.45, -hw * 0.95)]
        pygame.draw.polygon(surface, body_col, fuse)
        pygame.draw.polygon(surface, (50, 44, 32), fuse, 1)

        # Cockpit glass
        glass = [pt(hl * 0.92, -hw * 0.38), pt(hl * 0.92, hw * 0.38),
                 pt(hl * 0.50,  hw * 0.50), pt(hl * 0.50, -hw * 0.50)]
        pygame.draw.polygon(surface, _COL_GLASS, glass)

        # Tail boom
        tail = [pt(-hl * 0.90, -3), pt(-hl * 0.90, 3),
                pt(-hl * 1.55, 3),  pt(-hl * 1.55, -3)]
        pygame.draw.polygon(surface, _lerp3((68, 60, 45), _COL_DMGD, dmg_t), tail)

        # Main rotor (SRCALPHA overlay so blades look semi-transparent)
        rotor_len = int(50 * scale)
        rs = pygame.Surface((rotor_len * 2 + 6, rotor_len * 2 + 6), pygame.SRCALPHA)
        rc = rotor_len + 3
        blade_alpha = int(130 + 60 * self.altitude)
        for i in range(4):
            ba = math.radians(self._rotor_ang + i * 90)
            ex = int(math.cos(ba) * rotor_len)
            ey = int(math.sin(ba) * rotor_len)
            pygame.draw.line(rs, (82, 78, 58, blade_alpha),
                             (rc - ex, rc - ey), (rc + ex, rc + ey), 3)
        surface.blit(rs, (cx - rc, cy - rc))

        # Tail rotor
        tp    = pt(-hl * 1.45, 0)
        tr_l  = int(11 * scale)
        for i in range(2):
            ta = math.radians(self._rotor_ang * 2.5 + i * 180)
            pygame.draw.line(surface, (75, 70, 55),
                             (int(tp[0] - math.cos(ta) * tr_l),
                              int(tp[1] - math.sin(ta) * tr_l)),
                             (int(tp[0] + math.cos(ta) * tr_l),
                              int(tp[1] + math.sin(ta) * tr_l)), 2)

        if debug:
            pygame.draw.circle(surface, (220, 180, 50), (cx, cy), int(hl), 1)


# ── Airplane ──────────────────────────────────────────────────────────────────

class Airplane(Vehicle):
    def __init__(self, x: float, y: float):
        super().__init__(x, y)
        self._max_speed  = PLANE_MAX_SPEED
        self._max_rev    = 0.0         # no reverse
        self._accel      = PLANE_ACCEL
        self._steer_spd  = PLANE_STEER_SPD
        self._max_hp     = PLANE_MAX_HP
        self._max_fuel   = PLANE_MAX_FUEL
        self.hp          = PLANE_MAX_HP
        self.fuel        = PLANE_MAX_FUEL * 0.65
        self._hw         = 22
        self._hl         = 36
        self._kind       = "airplane"
        self.altitude    = 0.0
        self._prop_ang   = 0.0
        self._bomb_cd    = 0.0
        self.targeting   = False   # True = bomb zone overlay visible

    @property
    def is_airborne(self) -> bool:
        return self.altitude >= 0.95

    def check_roadkill(self, zombies: list) -> list:
        if self.altitude > 0.5:
            return []
        return super().check_roadkill(zombies)

    def _bomb_positions(self) -> list:
        """Compute bomb positions relative to current pos/angle (no side-effects)."""
        fwd = self._fwd()
        rgt = pygame.Vector2(fwd.y, -fwd.x)
        rng = random.Random(id(self))   # stable per-instance seed while targeting
        positions = []
        for i in range(PLANE_CARPET_N):
            t_fwd = (i - PLANE_CARPET_N // 2) * 130
            t_rgt = rng.uniform(-90, 90)
            bx = self.pos.x + fwd.x * t_fwd + rgt.x * t_rgt
            by = self.pos.y + fwd.y * t_fwd + rgt.y * t_rgt
            positions.append(pygame.Vector2(bx, by))
        return positions

    def bomb_preview(self) -> list:
        """Return (pos, radius) pairs for the targeting overlay, no cooldown consumed."""
        if self._bomb_cd > 0 or not self.is_airborne:
            return []
        return [(p, PLANE_CARPET_R) for p in self._bomb_positions()]

    def carpet_bomb(self) -> list:
        """Fire carpet bomb. Returns list of (pos, radius) for each explosion."""
        if self._bomb_cd > 0 or not self.is_airborne:
            return []
        self._bomb_cd  = PLANE_CARPET_CD
        self.targeting = False
        return [(p, PLANE_CARPET_R) for p in self._bomb_positions()]

    def update_drive(self, dt, keys, bounds, zones=None):  # noqa: ARG002
        self._prop_ang  = (self._prop_ang  + abs(self.speed) * dt * 0.9) % 360
        self._bomb_cd   = max(0.0, self._bomb_cd - dt)
        self._hit_tmr   = max(0.0, self._hit_tmr - dt)
        world_w, world_h = bounds

        # Throttle / air-brake (no reverse — _max_rev = 0 for airplane)
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            self.speed = min(self._max_speed, self.speed + self._accel * dt)
        elif keys[pygame.K_s] or keys[pygame.K_DOWN]:
            # Reduced brake when airborne so the plane slows smoothly
            brake_f = 0.45 if self.is_airborne else 1.0
            self.speed = max(0.0, self.speed - self._brake * brake_f * dt)
        else:
            # Passive drag: much weaker in the air so the plane stays fast
            drag = self._friction * (0.15 if self.is_airborne else 1.0) * dt
            if abs(self.speed) < drag:
                if not self.is_airborne:
                    self.speed = 0.0
            else:
                self.speed -= math.copysign(drag, self.speed)

        # Altitude: auto-takeoff when fast enough
        if not self.is_airborne and self.speed >= PLANE_TAKEOFF_SPD:
            self.altitude = min(1.0, self.altitude + 0.55 * dt)
        elif self.is_airborne:
            if self.speed >= PLANE_STALL_SPD:
                self.altitude = min(1.0, self.altitude + 0.25 * dt)
            else:
                self.altitude = max(0.0, self.altitude - 0.45 * dt)
        elif self.altitude > 0:
            self.altitude = max(0.0, self.altitude - 0.40 * dt)

        # Steering
        spd_f = min(1.0, abs(self.speed) / 450.0)
        steer = 0.0
        if abs(self.speed) > 20:
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                steer = -self._steer_spd * spd_f
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                steer = +self._steer_spd * spd_f
        self.angle = (self.angle + steer * dt) % 360.0

        fwd = self._fwd()
        nx = max(0.0, min(world_w, self.pos.x + fwd.x * self.speed * dt))
        ny = max(0.0, min(world_h, self.pos.y + fwd.y * self.speed * dt))

        # Airplanes fly over all terrain — no zone collision
        collision_dmg = 0

        self.pos.x = nx
        self.pos.y = ny

        if abs(self.speed) > 20:
            self.fuel = max(0.0, self.fuel - self._fuel_drain * dt)
        if self.fuel <= 0:
            self.altitude = max(0.0, self.altitude - 0.40 * dt)
            self.speed = max(0.0, self.speed - self._brake * 0.4 * dt)

        return collision_dmg

    def draw(self, surface, ox: int, oy: int, debug: bool = False):
        if not self.alive:
            return
        cx = int(self.pos.x) - ox
        cy = int(self.pos.y) - oy
        fwd = self._fwd()
        rgt = self._rgt()
        scale = 1.0 + self.altitude * 0.18
        hw = self._hw * scale
        hl = self._hl * scale

        def pt(fl, fr):
            return (cx + fwd.x * fl + rgt.x * fr,
                    cy + fwd.y * fl + rgt.y * fr)

        # Ground shadow
        sh_off = int(self.altitude * 42)
        if self.altitude > 0.04:
            sha = pygame.Surface((int(hl * 2.4), int(hw * 2.0)), pygame.SRCALPHA)
            sa  = int(120 * (1.0 - self.altitude * 0.40))
            pygame.draw.ellipse(sha, (0, 0, 0, sa), sha.get_rect())
            surface.blit(sha, (cx - sha.get_width() // 2,
                               cy + sh_off - sha.get_height() // 2))

        dmg_t    = max(0.0, 1.0 - self.hp / self._max_hp)
        body_col = _lerp3((128, 122, 102), _COL_DMGD, dmg_t)
        if self._hit_tmr > 0:
            body_col = (min(255, body_col[0] + 70), body_col[1], body_col[2])
        wing_col = _lerp3((108, 102, 84), _COL_DMGD, dmg_t)

        # Wings
        wing_l = [pt( hw * 0.15, -hw * 0.28), pt(-hw * 0.15, -hw * 0.28),
                  pt(-hw * 0.55, -hw * 1.40), pt( hw * 0.55, -hw * 1.05)]
        wing_r = [pt( hw * 0.15,  hw * 0.28), pt(-hw * 0.15,  hw * 0.28),
                  pt(-hw * 0.55,  hw * 1.40), pt( hw * 0.55,  hw * 1.05)]
        pygame.draw.polygon(surface, wing_col, wing_l)
        pygame.draw.polygon(surface, wing_col, wing_r)
        pygame.draw.polygon(surface, (68, 63, 50), wing_l, 1)
        pygame.draw.polygon(surface, (68, 63, 50), wing_r, 1)

        # Fuselage
        fuse = [pt( hl,        -hw * 0.22), pt( hl,         hw * 0.22),
                pt(-hl * 0.65,  hw * 0.38), pt(-hl,         hw * 0.18),
                pt(-hl,        -hw * 0.18), pt(-hl * 0.65, -hw * 0.38)]
        pygame.draw.polygon(surface, body_col, fuse)
        pygame.draw.polygon(surface, (78, 73, 58), fuse, 1)

        # Tail fins
        tf_col = wing_col
        tail_l = [pt(-hl * 0.62, -hw * 0.22),
                  pt(-hl * 0.62, -hw * 0.22 - 13 * scale),
                  pt(-hl,        -hw * 0.18)]
        tail_r = [pt(-hl * 0.62,  hw * 0.22),
                  pt(-hl * 0.62,  hw * 0.22 + 13 * scale),
                  pt(-hl,         hw * 0.18)]
        pygame.draw.polygon(surface, tf_col, tail_l)
        pygame.draw.polygon(surface, tf_col, tail_r)

        # Cockpit
        cock = [pt(hl * 0.90, -hw * 0.18), pt(hl * 0.90, hw * 0.18),
                pt(hl * 0.50,  hw * 0.20), pt(hl * 0.50, -hw * 0.20)]
        pygame.draw.polygon(surface, _COL_GLASS, cock)

        # Propeller (spinning lines at nose)
        prop_r = int(18 * scale)
        np_    = pt(hl, 0)
        for i in range(2):
            pa  = math.radians(self._prop_ang + i * 180)
            px1 = int(np_[0] + math.cos(pa) * prop_r)
            py1 = int(np_[1] + math.sin(pa) * prop_r)
            px2 = int(np_[0] - math.cos(pa) * prop_r)
            py2 = int(np_[1] - math.sin(pa) * prop_r)
            pygame.draw.line(surface, (60, 55, 42), (px2, py2), (px1, py1), 3)
        pygame.draw.circle(surface, (80, 75, 60),
                           (int(np_[0]), int(np_[1])), 3)

        if debug:
            pygame.draw.circle(surface, (220, 180, 50), (cx, cy), int(hl), 1)
