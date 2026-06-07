import pygame
import math
import random
import lang

# --- Tuning ---
PLAYER_SPEED       = 200
PLAYER_SPRINT_MULT = 1.7
QUIET_SPEED_MULT   = 0.55
PLAYER_STAMINA     = 4.0      # seconds of full sprint
STAMINA_REGEN      = 0.6      # per second when not sprinting
PLAYER_HP          = 100
PLAYER_DMGFLASH    = 0.25     # seconds of red flash

NOISE_RADIUS_QUIET = 35

NPC_SPEED         = 60
NPC_PANIC_SPEED   = 110
INFECTION_DELAY   = 8.0
NPC_WANDER_CHANGE = 1.5

NOISE_RADIUS_WALK   = 160
NOISE_RADIUS_SPRINT = 230
ZOMBIE_SIGHT        = 200
ZOMBIE_ATTACK_REACH    = 18    # arm reach beyond body contact (px)
ZOMBIE_BITE_ANIM_DUR   = 0.42  # bite animation duration (s)
NIGHT_SIGHT_BONUS   = 110   # extra sight range at night
NIGHT_DMG_MULT      = 1.6   # contact damage multiplier at night
night_mode          = False  # set by main.py at startup

LAKE_DROWN_RATE     = 40.0  # HP/s zombies lose while in water
LAKE_PLAYER_DMG     = 6.0   # HP/s player loses in water (exhaustion)

ZOMBIE_TYPES = {
    "regular": dict(
        hp=80, speed=dict(wander=55, investigate=82, chase=108),
        radius=11, color=(60, 180, 60), contact_dmg=8, contact_rate=1.0,
        screw_drop=(1, 3),
    ),
    "speed": dict(
        hp=40, speed=dict(wander=90, investigate=130, chase=170),
        radius=9,  color=(80, 220, 180), contact_dmg=5, contact_rate=0.6,
        screw_drop=(1, 2),
    ),
    "giant": dict(
        hp=240, speed=dict(wander=35, investigate=55, chase=72),
        radius=18, color=(120, 60, 180), contact_dmg=20, contact_rate=1.5,
        screw_drop=(3, 6),
    ),
    # Fast-runner: sprint speed exceeds the player's max sprint (340 px/s).
    # Fragile (25 HP) and hits softly (4 dmg), but nearly impossible to outrun.
    "runner": dict(
        hp=25, speed=dict(wander=120, investigate=210, chase=355),
        radius=8,  color=(255, 90, 0), contact_dmg=4, contact_rate=0.7,
        screw_drop=(1, 2),
    ),
    # Quad: 4-legged stalker — normal speed but pounces at 400 px/s.
    "quad": dict(
        hp=55, speed=dict(wander=58, investigate=95, chase=140),
        radius=12, color=(140, 90, 40), contact_dmg=14, contact_rate=0.9,
        screw_drop=(2, 4),
    ),
}
KNOCKBACK_DIST = 22

PLAYER_COLOR   = (80,  160, 255)
NPC_COLOR      = (200, 200, 180)
INFECTED_COLOR = (180, 100, 50)


# ── Shared figure drawing helpers ─────────────────────────────────────────────

# 번 오버레이용 공유 Surface (Surface 신규 할당 방지)
_BURN_SURF: pygame.Surface | None = None
_BURN_SURF_SZ = 64


def _burn_surf() -> pygame.Surface:
    global _BURN_SURF
    if _BURN_SURF is None:
        _BURN_SURF = pygame.Surface((_BURN_SURF_SZ, _BURN_SURF_SZ), pygame.SRCALPHA)
    return _BURN_SURF


def _draw_burn_overlay(surface, sx, sy, r, burn_timer, max_dur=3.5):
    """Draw animated fire effect on a burning entity."""
    t     = pygame.time.get_ticks() / 1000.0
    ratio = min(1.0, burn_timer / max_dur)
    bs    = _burn_surf()

    # Glow halo
    gr = min(int(r * 1.8), _BURN_SURF_SZ // 2 - 1)
    w  = gr * 2
    bs.fill((0, 0, 0, 0), (0, 0, w, w))
    pygame.draw.circle(bs, (255, 80, 10, int(55 * ratio)), (gr, gr), gr)
    surface.blit(bs, (sx - gr, sy - gr), (0, 0, w, w))

    # Flame tongues orbiting the entity
    n = 7
    for i in range(n):
        ang    = t * 5.2 + i * (math.tau / n) + math.sin(t * 9 + i * 1.5) * 0.25
        dist   = r * (0.55 + 0.35 * math.sin(t * 4 + i * 0.8))
        fx     = sx + int(dist * math.cos(ang))
        fy     = sy + int(dist * math.sin(ang))
        fr     = max(2, min(int((3 + 4 * math.sin(t * 7 + i * 1.2)) * ratio),
                            _BURN_SURF_SZ // 2 - 1))
        phase  = math.sin(t * 8 + i)
        col    = (255, 230, 50) if phase > 0.4 else (255, 120, 20) if phase > -0.2 else (210, 45, 10)
        fa     = int(220 * ratio)
        fw     = fr * 2 + 2
        bs.fill((0, 0, 0, 0), (0, 0, fw, fw))
        pygame.draw.circle(bs, (*col, fa), (fr + 1, fr + 1), fr)
        surface.blit(bs, (fx - fr - 1, fy - fr - 1), (0, 0, fw, fw))


def _draw_human_anim(surface, cx, cy, r, aim_dir, walk_phase,
                     shirt_col, skin_col, pants_col,
                     gun_dir=None, gun_col=(50, 50, 50),
                     helmet_col=None, sprinting=False,
                     punch_ext=0.0, punch_arm=-1, punch_strong=False):
    """
    Animated top-down humanoid with walk/run/shoot poses.
    aim_dir    – direction the character faces (head orientation)
    walk_phase – accumulated radians; drives leg swing animation
    gun_dir    – if given, hands grip a gun barrel in this direction
    helmet_col – if given, a helmet is drawn over the head
    """
    fd   = aim_dir.normalize() if aim_dir.length_squared() > 0.01 else pygame.Vector2(0, -1)
    perp = pygame.Vector2(-fd.y, fd.x)

    def pt(f, s=0.0):
        return (int(cx + fd.x*f + perp.x*s), int(cy + fd.y*f + perp.y*s))

    body_r = max(5, int(r * 0.76))
    leg_r  = max(3, int(r * 0.38))
    arm_r  = max(2, int(r * 0.29))
    head_r = max(5, int(r * 0.62))
    foot_r = max(2, leg_r - 1)
    amp    = r * (0.46 if sprinting else 0.30)   # leg forward/back swing

    l_swing = math.sin(walk_phase) * amp            # left leg
    r_swing = math.sin(walk_phase + math.pi) * amp  # right leg (opposite phase)
    foot_col = tuple(max(0, c - 20) for c in pants_col)

    # ── Back leg (drawn behind body) ──────────────────────────────────
    ll = pt(-r * 0.18 + l_swing, +r * 0.40)
    pygame.draw.circle(surface, pants_col, ll, leg_r)
    lf = pt(-r * 0.12 + l_swing * 1.30, +r * 0.36)
    pygame.draw.circle(surface, foot_col, lf, foot_r)

    # ── Body ──────────────────────────────────────────────────────────
    pygame.draw.circle(surface, shirt_col, (cx, cy), body_r)
    pygame.draw.circle(surface, tuple(max(0, c - 25) for c in shirt_col),
                       (cx, cy), body_r, 1)

    # ── Front leg (drawn over body) ────────────────────────────────────
    rl = pt(-r * 0.18 + r_swing, -r * 0.40)
    pygame.draw.circle(surface, pants_col, rl, leg_r)
    rf = pt(-r * 0.12 + r_swing * 1.30, -r * 0.36)
    pygame.draw.circle(surface, foot_col, rf, foot_r)

    # ── Arms / gun ────────────────────────────────────────────────────
    if gun_dir is not None and gun_dir.length_squared() > 0.01:
        gd = gun_dir.normalize()
        gp = pygame.Vector2(-gd.y, gd.x)
        # Two hands gripping the weapon (one each side of barrel)
        for sign in (+1, -1):
            ax = int(cx + gd.x * body_r * 0.42 + gp.x * sign * body_r * 0.54)
            ay = int(cy + gd.y * body_r * 0.42 + gp.y * sign * body_r * 0.54)
            pygame.draw.circle(surface, skin_col, (ax, ay), arm_r)
        # Barrel from near-centre outward
        gs = (int(cx + gd.x * body_r * 0.22), int(cy + gd.y * body_r * 0.22))
        ge = (int(cx + gd.x * (r + 12)),       int(cy + gd.y * (r + 12)))
        pygame.draw.line(surface, gun_col, gs, ge, 3)
        pygame.draw.circle(surface, (85, 85, 85), ge, 2)
    elif punch_ext > 0.0:
        # ── Fist combo punch ─────────────────────────────────────────
        dk = tuple(max(0, c - 45) for c in skin_col)
        hi = tuple(min(255, c + 35) for c in skin_col)

        # punch_arm: -1 = right arm punches (combo 0 & 2), +1 = left arm punches (combo 1)
        punch_side  = punch_arm          # side that punches (-1=right, +1=left)
        guard_side  = -punch_arm         # other arm stays as guard

        # Guard arm — held slightly forward in boxing guard
        gax, gay = pt(body_r * 0.22, guard_side * body_r * 0.72)
        guard_w = arm_r + (2 if punch_strong else 0)
        pygame.draw.circle(surface, skin_col, (gax, gay), guard_w)
        pygame.draw.circle(surface, dk, (gax, gay), guard_w, 1)

        # Punching arm — shoulder origin, fist extends forward
        shx, shy = pt(body_r * 0.08, punch_side * body_r * 0.68)
        reach_mult = 1.65 if punch_strong else 1.45
        ext_f = body_r * 0.42 + r * reach_mult * punch_ext
        ext_s = punch_side * body_r * 0.42 * (1.0 - punch_ext)   # closes to center
        px_, py_ = pt(ext_f, ext_s)

        arm_w = arm_r + (1 if punch_strong else 0)
        pygame.draw.line(surface, dk,       (shx, shy), (px_, py_), arm_w * 2 + 1)
        pygame.draw.line(surface, skin_col, (shx, shy), (px_, py_), arm_w * 2 - 1)

        # Fist head — bigger for strong punch
        fr = arm_r + (2 if punch_strong and punch_ext > 0.55 else
                      1 if punch_ext > 0.60 else 0)
        pygame.draw.circle(surface, skin_col, (px_, py_), fr)
        pygame.draw.circle(surface, dk,       (px_, py_), fr, 1)

        # Knuckle bumps at impact
        knuckle_thresh = 0.60 if punch_strong else 0.68
        if punch_ext > knuckle_thresh:
            face_a = math.atan2(fd.y, fd.x) + math.pi / 2
            n_knuckles = 4 if punch_strong else 3
            for k in range(n_knuckles):
                ka = face_a + (k - (n_knuckles - 1) / 2) * 0.45
                kx = int(px_ + math.cos(ka) * (fr - 1))
                ky = int(py_ + math.sin(ka) * (fr - 1))
                pygame.draw.circle(surface, hi, (kx, ky), 1)
    else:
        # Relaxed arms sway gently, opposite phase to legs
        for sign, ph in ((+1, 0.0), (-1, math.pi)):
            sway = math.sin(walk_phase + ph) * r * 0.14
            ax, ay = pt(sway, sign * body_r * 0.88)
            pygame.draw.circle(surface, skin_col, (ax, ay), arm_r)

    # ── Head ──────────────────────────────────────────────────────────
    hx, hy = pt(r * 0.35)
    if helmet_col:
        pygame.draw.circle(surface, helmet_col, (hx, hy), head_r + 2)
        pygame.draw.circle(surface, tuple(max(0, c - 32) for c in helmet_col),
                           (hx, hy), head_r + 2, 1)
    pygame.draw.circle(surface, skin_col, (hx, hy), head_r)
    # Eyes
    eye_r = max(1, int(head_r * 0.26))
    for sign in (+1, -1):
        ex = int(hx + fd.x * head_r * 0.28 + perp.x * sign * head_r * 0.40)
        ey = int(hy + fd.y * head_r * 0.28 + perp.y * sign * head_r * 0.40)
        pygame.draw.circle(surface, (30, 20, 15), (ex, ey), eye_r)


def _draw_zombie_figure(surface, cx, cy, r, facing, body_col, bite_t=0.0):
    """Zombie: hunched polygon torso + reaching claw arms + glowing red eyes."""
    fd = facing if facing.length_squared() > 0.01 else pygame.Vector2(0, -1)
    perp = pygame.Vector2(-fd.y, fd.x)

    def pt(fwd, sid=0.0):
        return (int(cx + fd.x * fwd + perp.x * sid),
                int(cy + fd.y * fwd + perp.y * sid))

    dark = tuple(max(0, c - 38) for c in body_col)
    lite = tuple(min(255, c + 28) for c in body_col)

    # Arms: retract slightly during bite lunge
    arm_ret = bite_t * r * 0.20
    arm_w = max(2, r // 5)
    for sign in (+1, -1):
        a0 = pt(-r * 0.12, sign * r * 0.58)
        a1 = pt( r * 0.48 - arm_ret, sign * r * 0.74)
        a2 = pt( r * 0.96 - arm_ret, sign * r * 0.50)
        pygame.draw.line(surface, dark, a0, a1, arm_w)
        pygame.draw.line(surface, dark, a1, a2, max(2, arm_w - 1))
        # Three claw tips
        for dx, dy in ((-2, 0), (1, -3), (1, 3)):
            pygame.draw.circle(surface, dark, (a2[0] + dx, a2[1] + dy), 2)

    # Hunched torso (slightly irregular polygon, leans forward)
    torso = [
        pt(-r * 0.68,  r * 0.46),
        pt(-r * 0.68, -r * 0.46),
        pt( r * 0.10, -r * 0.54),
        pt( r * 0.36,  r * 0.00),
        pt( r * 0.10,  r * 0.54),
    ]
    pygame.draw.polygon(surface, body_col, torso)
    pygame.draw.polygon(surface, dark, torso, 1)

    # Head: lunges forward during bite
    head_r   = max(4, int(r * 0.56))
    bite_fwd = r * 0.38 * bite_t
    hx = int(cx + fd.x * (r * 0.28 + bite_fwd) + perp.x * (-r * 0.08))
    hy = int(cy + fd.y * (r * 0.28 + bite_fwd) + perp.y * (-r * 0.08))

    # Open jaw (drawn before head circle so head overlaps the hinge)
    if bite_t > 0.05:
        gap      = head_r * 0.72 * bite_t   # jaw spread along perp
        jaw_len  = head_r * 0.95            # jaw reach forward
        # Hinge point (back of mouth, inside head)
        mo_x = int(hx - fd.x * head_r * 0.18)
        mo_y = int(hy - fd.y * head_r * 0.18)
        # Jaw tip center
        ft_x = int(hx + fd.x * jaw_len)
        ft_y = int(hy + fd.y * jaw_len)
        # Upper/lower jaw tips
        u_x = int(ft_x + perp.x * gap)
        u_y = int(ft_y + perp.y * gap)
        l_x = int(ft_x - perp.x * gap)
        l_y = int(ft_y - perp.y * gap)
        # Dark red inner mouth (4-point wedge)
        pygame.draw.polygon(surface, (108, 12, 12),
                            [(mo_x, mo_y), (u_x, u_y), (ft_x, ft_y), (l_x, l_y)])
        # Jaw edges
        pygame.draw.line(surface, dark, (mo_x, mo_y), (u_x, u_y), 2)
        pygame.draw.line(surface, dark, (mo_x, mo_y), (l_x, l_y), 2)
        # Teeth visible when mouth is open enough
        if bite_t > 0.40:
            tcol = (228, 220, 198)
            for tf in (0.28, 0.56, 0.80):
                for tip_x, tip_y in ((u_x, u_y), (l_x, l_y)):
                    tx = mo_x + int((tip_x - mo_x) * tf)
                    ty = mo_y + int((tip_y - mo_y) * tf)
                    pygame.draw.circle(surface, tcol, (tx, ty), max(1, head_r // 5))

    pygame.draw.circle(surface, lite, (hx, hy), head_r)
    pygame.draw.circle(surface, dark, (hx, hy), head_r, 1)

    # Glowing red eyes (on lunging head, brighter when biting)
    eye_r   = max(1, int(head_r * 0.32))
    eye_col = (255, 55, 55) if bite_t > 0.3 else (225, 35, 35)
    for sign in (+1, -1):
        ex = int(hx + fd.x * head_r * 0.25 + perp.x * sign * head_r * 0.42)
        ey = int(hy + fd.y * head_r * 0.25 + perp.y * sign * head_r * 0.42)
        pygame.draw.circle(surface, (40, 0, 0), (ex, ey), eye_r + 1)
        pygame.draw.circle(surface, eye_col, (ex, ey), eye_r)


def _draw_quad_figure(surface, cx, cy, r, facing, body_col, pouncing=False):
    """4-legged stalker zombie: low body, 4 legs, yellow predator eyes."""
    fd   = facing if facing.length_squared() > 0.01 else pygame.Vector2(0, -1)
    perp = pygame.Vector2(-fd.y, fd.x)

    def pt(fwd, sid=0.0):
        return (int(cx + fd.x * fwd + perp.x * sid),
                int(cy + fd.y * fwd + perp.y * sid))

    dark = tuple(max(0, c - 40) for c in body_col)
    lite = tuple(min(255, c + 35) for c in body_col)

    # 4 legs: two front, two back
    for fwd_b, sid_b in [(0.38, 0.42), (0.38, -0.42),
                         (-0.32, 0.38), (-0.32, -0.38)]:
        hip   = pt(fwd_b * r * 0.55, sid_b * r)
        knee  = pt(fwd_b * r * 0.85, sid_b * r * 1.1)
        foot  = pt(fwd_b * r * 1.10, sid_b * r * 0.75)
        pygame.draw.line(surface, dark, hip, knee, 2)
        pygame.draw.line(surface, dark, knee, foot, 2)
        pygame.draw.circle(surface, dark, foot, 2)

    # Low, wide body
    body = [
        pt(-r * 0.40,  r * 0.38),
        pt(-r * 0.40, -r * 0.38),
        pt( r * 0.18, -r * 0.44),
        pt( r * 0.32,  0),
        pt( r * 0.18,  r * 0.44),
    ]
    pygame.draw.polygon(surface, body_col, body)
    pygame.draw.polygon(surface, dark, body, 1)

    # Pounce flash: lighter outline
    if pouncing:
        pygame.draw.polygon(surface, lite, body, 2)

    # Head — low, wide, snout-like
    head_r = max(3, int(r * 0.46))
    hx, hy = pt(r * 0.42, 0)
    pygame.draw.circle(surface, lite, (hx, hy), head_r)
    pygame.draw.circle(surface, dark, (hx, hy), head_r, 1)

    # Predator eyes: yellow-green
    eye_r = max(1, int(head_r * 0.30))
    for sign in (+1, -1):
        ex = int(hx + fd.x * head_r * 0.2 + perp.x * sign * head_r * 0.44)
        ey = int(hy + fd.y * head_r * 0.2 + perp.y * sign * head_r * 0.44)
        pygame.draw.circle(surface, (20, 15, 0),   (ex, ey), eye_r + 1)
        pygame.draw.circle(surface, (205, 190, 20), (ex, ey), eye_r)


# ── Debug helper ──────────────────────────────────────────────────────────────

def _debug_circle(surface, color, center, radius, alpha=35, ox=0, oy=0):
    if radius <= 0:
        return
    s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    pygame.draw.circle(s, (*color, alpha), (radius, radius), radius)
    surface.blit(s, (int(center.x) - radius - ox, int(center.y) - radius - oy))


# ── Player ────────────────────────────────────────────────────────────────────

class Player:
    def __init__(self, x, y):
        self.pos          = pygame.Vector2(x, y)
        self.radius       = 12
        self.speed        = PLAYER_SPEED
        self.is_hidden    = False
        self.noise_radius = 0.0
        self._moving      = False
        self._sprinting   = False
        self._quiet       = False
        # stamina
        self.stamina      = PLAYER_STAMINA
        self.max_stamina  = PLAYER_STAMINA
        # HP
        self.hp           = PLAYER_HP
        self.max_hp       = PLAYER_HP
        self._dmg_flash   = 0.0
        # ── Weapon inventory: 6 slots (pistol/rifle/autofire/grenade/heal/melee)
        # Each slot holds a list so multiple weapon kinds can be cycled within one slot
        self.weapon_slots = [[] for _ in range(6)]
        self.active_slot  = 5   # start on melee slot so fist is immediately usable
        self._slot_idx    = [0] * 6   # which weapon is active within each slot
        self.screws       = 0
        # Gym upgrade levels (0–5 each)
        self.gym_levels   = {"stamina_regen": 0, "speed": 0, "max_hp": 0, "fist_dmg": 0}
        self._gym_stamina_bonus = 0.0   # extra stamina regen/s from gym
        # Default bare-fist weapon always in melee slot
        from melee import MeleeWeapon as _MW
        self.weapon_slots[5].append(_MW("fist"))
        # combat
        self.aim_dir   = pygame.Vector2(1, 0)
        # animation
        self._walk_phase  = 0.0
        self._throw_anim    = 0.0   # countdown for grenade throw arm animation
        self._flamethrowing = False  # True the frame flamethrower fires (reset each frame)
        self.in_water       = False  # True when standing in a lake zone
        self.in_forest      = False  # True when inside a ForestZone

    # ── Weapon inventory helpers ───────────────────────────────────────────

    def slot_weapon(self, slot_idx: int):
        """Active weapon in a given slot, or None if empty."""
        s = self.weapon_slots[slot_idx]
        if not s:
            return None
        return s[min(self._slot_idx[slot_idx], len(s) - 1)]

    @property
    def weapon(self):
        return self.slot_weapon(self.active_slot)

    def switch_slot(self, idx: int):
        idx = max(0, min(5, idx))
        if idx == self.active_slot:
            # Same slot pressed again → cycle through weapons in this slot
            s = self.weapon_slots[idx]
            if len(s) > 1:
                self._slot_idx[idx] = (self._slot_idx[idx] + 1) % len(s)
        else:
            self.active_slot = idx

    @property
    def alive(self):
        return self.hp > 0

    def take_damage(self, amount: int):
        self.hp         = max(0, self.hp - amount)
        self._dmg_flash = PLAYER_DMGFLASH

    def pickup(self, item):
        from items import WeaponDrop, ScrewDrop, WEAPON_SLOT_MAP
        from melee import MeleeDrop
        if isinstance(item, MeleeDrop):
            slot_list = self.weapon_slots[5]
            for i, existing in enumerate(slot_list):
                if existing.kind == item.weapon.kind:
                    return   # already have this melee weapon
            slot_list.append(item.weapon)
            return
        if isinstance(item, WeaponDrop):
            slot_idx   = WEAPON_SLOT_MAP.get(item.weapon.kind, 0)
            slot_list  = self.weapon_slots[slot_idx]
            # Same kind → replace (keep upgrade levels intact would require merging;
            # for simplicity just overwrite that entry so we don't duplicate)
            for i, existing in enumerate(slot_list):
                if existing.kind == item.weapon.kind:
                    if existing.kind == "lantern":
                        existing.fuel = existing.max_fuel   # refill instead of replace
                    else:
                        slot_list[i] = item.weapon
                    return
            # Different kind in same slot → add to cycle list
            slot_list.append(item.weapon)
        elif isinstance(item, ScrewDrop):
            self.screws += item.count

    def handle_input(self, keys, dt, bounds, zones=None):
        dx = keys[pygame.K_d] - keys[pygame.K_a]
        dy = keys[pygame.K_s] - keys[pygame.K_w]
        move = pygame.Vector2(dx, dy)
        self._moving = move.length_squared() > 0

        # Sprint (Shift) — requires stamina; quiet (Ctrl) — mutually exclusive
        want_sprint      = (keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]) and self._moving
        want_quiet       = (keys[pygame.K_LCTRL]  or keys[pygame.K_RCTRL])  and self._moving
        self._sprinting  = want_sprint and self.stamina > 0
        self._quiet      = want_quiet and not self._sprinting

        if self._sprinting:
            self.stamina = max(0.0, self.stamina - dt)
        else:
            self.stamina = min(self.max_stamina,
                               self.stamina + (STAMINA_REGEN + self._gym_stamina_bonus) * dt)

        if self._moving:
            if self._sprinting:
                speed_mult = PLAYER_SPRINT_MULT
            elif self._quiet:
                speed_mult = QUIET_SPEED_MULT
            else:
                speed_mult = 1.0
            if self._flamethrowing:
                speed_mult *= 0.55   # heavy weapon slows movement
            if zones:
                _on_road = any(z.zone_type == "road"
                               and z.rect.collidepoint(self.pos.x, self.pos.y)
                               for z in zones)
                if not _on_road:
                    for zone in zones:
                        if not zone.blocks_movement and zone.contains(self.pos):
                            speed_mult = min(speed_mult, zone.speed_mult)
            move = move.normalize() * self.speed * speed_mult * dt

        old_pos = pygame.Vector2(self.pos)
        self.pos += move

        if zones:
            for zone in zones:
                if zone.blocks_passage(old_pos, self.pos):
                    self.pos     = old_pos
                    self._moving = False
                    break

        self.pos.x = max(self.radius, min(bounds[0] - self.radius, self.pos.x))
        self.pos.y = max(self.radius, min(bounds[1] - self.radius, self.pos.y))

        if self.is_hidden or not self._moving:
            self.noise_radius = 0.0
        elif self._sprinting:
            self.noise_radius = NOISE_RADIUS_SPRINT
        elif self._quiet:
            self.noise_radius = NOISE_RADIUS_QUIET
        else:
            self.noise_radius = NOISE_RADIUS_WALK

        self._dmg_flash     = max(0.0, self._dmg_flash  - dt)
        self._throw_anim    = max(0.0, self._throw_anim - dt)
        self._flamethrowing = False   # reset each frame; main.py sets True when firing

        # ── Road priority: compute once, suppress terrain effects when on road ──
        _road_here = bool(zones and any(
            z.zone_type == "road" and z.rect.collidepoint(self.pos.x, self.pos.y)
            for z in zones
        ))

        # ── Lake / water check ────────────────────────────────────────────
        self.in_water = (not _road_here) and bool(zones and any(
            z.zone_type == "lake" and z.rect.collidepoint(self.pos.x, self.pos.y)
            for z in zones
        ))
        if self.in_water:
            self.take_damage(int(LAKE_PLAYER_DMG * dt + 0.5))

        # ── Forest check ──────────────────────────────────────────────────
        self.in_forest = (not _road_here) and bool(zones and any(
            z.zone_type == "bush" and z.rect.collidepoint(self.pos.x, self.pos.y)
            for z in zones
        ))

        # Advance walk animation
        if self._moving:
            rate = 14.0 if self._sprinting else 8.0
            self._walk_phase = (self._walk_phase + dt * rate) % math.tau

    def draw(self, surface, ox=0, oy=0, debug=False):
        r      = self.radius
        sx, sy = int(self.pos.x) - ox, int(self.pos.y) - oy
        alpha  = 110 if self.is_hidden else 255

        if self._dmg_flash > 0:
            shirt_col = (240, 70,  70)
            skin_col  = (255, 120, 120)
            pants_col = (190, 45,  45)
            helm_col  = (200, 55,  55)
        else:
            shirt_col = (38,  88, 162)   # tactical vest
            skin_col  = (195, 160, 125)  # skin
            pants_col = (26,  52, 108)   # dark trousers
            helm_col  = (22,  42,  88)   # helmet

        pad = r + 22
        s = pygame.Surface((pad * 2, pad * 2))
        s.fill((2, 2, 2))
        s.set_colorkey((2, 2, 2))

        from melee import MeleeWeapon as _MW
        is_melee = isinstance(self.weapon, _MW)
        gun_dir  = (self.aim_dir if (self.weapon and not is_melee) else None)

        # Fist punch / throw extension factor (0 = rest, 1 = full reach)
        punch_ext    = 0.0
        punch_arm    = -1    # -1 = right arm, +1 = left arm
        punch_strong = False
        _THROW_DUR   = 0.38
        if self._throw_anim > 0.0:
            # Grenade throw: right arm swings overhead and forward
            _tp = self._throw_anim / _THROW_DUR   # 1.0 → 0.0
            punch_ext = (1.0 - _tp) / 0.35 if _tp > 0.65 else _tp / 0.65
            punch_ext = max(0.0, min(1.0, punch_ext))
            punch_arm = -1   # right arm
        elif (is_melee and getattr(self.weapon, 'is_default', False)
                and getattr(self.weapon, 'is_swinging', False)):
            _active = getattr(self.weapon, '_active_combo', 0)
            punch_strong = (_active == 2)
            punch_arm    = +1 if _active == 1 else -1
            _p = self.weapon.swing_progress   # 1.0 → 0.0; strong punch may start >1.0
            if punch_strong:
                # wider wind-up window before the fist extends
                punch_ext = (1.0 - _p) / 0.45 if _p > 0.55 else _p / 0.55
            else:
                punch_ext = (1.0 - _p) / 0.35 if _p > 0.65 else _p / 0.65
            punch_ext = max(0.0, min(1.0, punch_ext))

        _draw_human_anim(s, pad, pad, r, self.aim_dir, self._walk_phase,
                         shirt_col, skin_col, pants_col,
                         gun_dir=gun_dir, gun_col=(45, 45, 45),
                         helmet_col=helm_col, sprinting=self._sprinting,
                         punch_ext=punch_ext, punch_arm=punch_arm,
                         punch_strong=punch_strong)

        if alpha < 255:
            s.set_alpha(alpha)
        surface.blit(s, (sx - pad, sy - pad))

        # HP bar
        if self.hp < self.max_hp:
            bw    = r * 2 + 8
            ratio = self.hp / self.max_hp
            bx    = sx - r - 4
            by    = sy - r - 14
            pygame.draw.rect(surface, (60, 18, 18), (bx, by, bw, 4))
            hp_col = ((60, 200, 60) if ratio > 0.5
                      else (210, 200, 50) if ratio > 0.25
                      else (220, 55, 55))
            pygame.draw.rect(surface, hp_col, (bx, by, int(bw * ratio), 4))

        if debug and self.noise_radius > 0:
            nr = int(self.noise_radius)
            _debug_circle(surface, (255, 220, 0), self.pos, nr, 40, ox, oy)
            pygame.draw.circle(surface, (200, 175, 0), (sx, sy), nr, 1)


NPC_HP = 30

NPC_GUN_CHANCE  = 0.05    # 5% of civilians spawn armed
NPC_GUN_RANGE   = 280     # px — armed NPC shooting range
NPC_GUN_DAMAGE  = 12
NPC_GUN_SPEED   = 380     # bullet px/s
NPC_GUN_RATE    = 1.2     # shots per second

NPC_PUNCH_DMG      = 8       # unarmed NPC fight-back damage
NPC_PUNCH_CD       = 1.1     # seconds between punches
NPC_PUNCH_R        = 50      # punch reach center-to-center (px)
NPC_PUNCH_ANIM_DUR = 0.32    # punch extension animation duration (s)

SHERIFF_HP        = 80
SHERIFF_GUN_RANGE = 340
SHERIFF_GUN_DMG   = 15
SHERIFF_GUN_RATE  = 0.9   # shots per second
SHERIFF_PATROL_R  = 380   # patrol radius around spawn origin
SHERIFF_ALERT_R   = 700   # radius in which fellow sheriffs hear the alarm

NPC_HOSTILE_COLOR = (255, 120, 30)   # orange when hostile
NPC_ARMED_BADGE   = (255, 230, 50)   # yellow star badge


# ── NPC ───────────────────────────────────────────────────────────────────────

class NPC:
    STATE_ALIVE    = "alive"
    STATE_INFECTED = "infected"
    STATE_PANIC    = "panic"
    STATE_HOSTILE  = "hostile"
    STATE_DEAD     = "dead"

    def __init__(self, x, y):
        self.pos    = pygame.Vector2(x, y)
        self.radius = 10
        self.state  = self.STATE_ALIVE
        self.hp           = NPC_HP
        self.max_hp       = NPC_HP
        self._hit_flash   = 0.0
        self.infection_timer = 0.0
        self._wander_timer   = random.uniform(0, NPC_WANDER_CHANGE)
        self._direction      = pygame.Vector2(random.choice([-1, 1]),
                                              random.choice([-1, 1])).normalize()
        self._panic_timer    = 0.0
        self._zombie_on_death = False
        # Armed civilian fields
        self.armed        = random.random() < NPC_GUN_CHANCE
        self._gun_cd      = 0.0
        self._shoot_dir   = pygame.Vector2(1, 0)
        # Unarmed fight-back
        self._fighting_back = False   # True → unarmed melee retaliation
        self._punch_cd      = 0.0
        self._punch_anim    = 0.0    # countdown for punch extension animation
        self._punch_arm     = -1     # alternates -1/+1 each punch (right/left)
        # Alert indicator
        self._alert_timer   = 0.0    # '!!' pop timer
        self._prev_saw_zombie = False
        # animation
        self._walk_phase  = random.uniform(0, math.tau)
        # Burn state
        self._burn_timer  = 0.0
        self._burn_dps    = 0.0
        self._burn_kill   = False   # True when burn was the killing blow

    def ignite(self, dps: float, duration: float = 3.5):
        self._burn_timer = max(self._burn_timer, duration)
        self._burn_dps   = max(self._burn_dps,   dps)

    def bite(self):
        if self.state in (self.STATE_ALIVE, self.STATE_PANIC, self.STATE_HOSTILE):
            self.state = self.STATE_INFECTED
            self.infection_timer = INFECTION_DELAY
            self._zombie_on_death = True

    def take_hit(self, damage: int, from_player: bool = False,
                 from_bullet: bool = False):
        if self.state == self.STATE_DEAD:
            return
        self.hp         = max(0, self.hp - damage)
        self._hit_flash = 0.25
        if self.hp <= 0:
            self.state = self.STATE_DEAD
            return
        if from_player and self.state != self.STATE_INFECTED:
            if from_bullet:
                # Shot by bullet → flee (overrides even hostile state)
                self.state          = self.STATE_PANIC
                self._panic_timer   = 3.5
                self._fighting_back = False
            elif self.state != self.STATE_HOSTILE:
                # Hit by melee/fist → fight back (only if not already hostile)
                self.state = self.STATE_HOSTILE
                if not self.armed:
                    self._fighting_back = True

    def panic(self, away_from: pygame.Vector2):
        # STATE_INFECTED must not be overwritten — infection timer only ticks there
        if self.state in (self.STATE_DEAD, self.STATE_HOSTILE, self.STATE_INFECTED):
            return
        self.state        = self.STATE_PANIC
        self._panic_timer = 2.0
        d = self.pos - away_from
        if d.length_squared() > 0:
            self._direction = d.normalize()

    def hear_gunshot(self, shot_pos: pygame.Vector2):
        """Called when a gunshot is heard nearby — civilian flees from the sound."""
        if self.state in (self.STATE_DEAD, self.STATE_INFECTED):
            return
        if self.state != self.STATE_PANIC:
            self._alert_timer = 0.9   # '!!' pop
        self.state          = self.STATE_PANIC
        self._fighting_back = False
        self._panic_timer   = 4.0
        d = self.pos - shot_pos
        if d.length_squared() > 0:
            self._direction = d.normalize()

    def update(self, dt, bounds, zones=None, zombies=None, player=None):
        """Returns list[Bullet] fired this frame (may be empty)."""
        from projectiles import Bullet   # local import avoids circular at module level
        fired: list[Bullet] = []

        if self.state == self.STATE_DEAD:
            return fired
        if self.state == self.STATE_INFECTED:
            self.infection_timer -= dt
            if self.infection_timer <= 0:
                self.state = self.STATE_DEAD
            return fired

        # Burn DoT
        if self._burn_timer > 0:
            self._burn_timer -= dt
            self.hp          -= self._burn_dps * dt
            self._hit_flash   = 0.1
            if self.hp <= 0:
                self.state      = self.STATE_DEAD
                self._burn_kill = True
                return fired

        self._gun_cd      = max(0.0, self._gun_cd - dt)
        self._punch_cd    = max(0.0, self._punch_cd - dt)
        self._punch_anim  = max(0.0, self._punch_anim - dt)
        self._alert_timer = max(0.0, self._alert_timer - dt)

        # ── HOSTILE: armed → shoot / unarmed → punch back ────────────────────
        if self.state == self.STATE_HOSTILE:
            if player is not None:
                d    = player.pos - self.pos
                dist = d.length()
                if dist > 0:
                    self._direction = d / dist
                    self._shoot_dir = d / dist

                if self.armed and not self._fighting_back:
                    # Armed civilian: shoot
                    if dist <= NPC_GUN_RANGE and self._gun_cd <= 0:
                        vel = self._shoot_dir * NPC_GUN_SPEED
                        fired.append(Bullet(self.pos, vel, NPC_GUN_DAMAGE,
                                            (255, 140, 0), owner="npc"))
                        self._gun_cd = 1.0 / NPC_GUN_RATE
                else:
                    # Unarmed: chase and punch when in range
                    if dist <= NPC_PUNCH_R and self._punch_cd <= 0:
                        player.take_damage(NPC_PUNCH_DMG)
                        self._punch_cd  = NPC_PUNCH_CD
                        self._punch_anim = NPC_PUNCH_ANIM_DUR
                        self._punch_arm  = -self._punch_arm  # alternate arms
            speed = NPC_PANIC_SPEED
        else:
            # ── Zombie detection: flee, and shoot if armed ────────────────────
            saw_zombie = False
            nearest_z  = None
            nearest_zd = NPC_GUN_RANGE if self.armed else ZOMBIE_SIGHT
            for z in (zombies or []):
                if z.alive:
                    d = self.pos.distance_to(z.pos)
                    if d < (nearest_zd if self.armed else ZOMBIE_SIGHT):
                        nearest_zd = d
                        nearest_z  = z

            if nearest_z is not None:
                saw_zombie = True
                if not self._prev_saw_zombie:
                    self._alert_timer = 0.9   # '!!' pop on first detection
                away = self.pos - nearest_z.pos
                if away.length_squared() > 0:
                    flee_dir        = away.normalize()
                    self._shoot_dir = -flee_dir
                    if not self.armed:
                        self._direction = flee_dir
                    else:
                        self._direction = flee_dir * 0.3

                if not self.armed:
                    self.state        = self.STATE_PANIC
                    self._panic_timer = 2.0
                else:
                    if self._gun_cd <= 0:
                        vel = self._shoot_dir * NPC_GUN_SPEED
                        fired.append(Bullet(self.pos, vel, NPC_GUN_DAMAGE,
                                            (255, 220, 80), owner="npc"))
                        self._gun_cd = 1.0 / NPC_GUN_RATE
                    self.state        = self.STATE_PANIC
                    self._panic_timer = 2.0

            self._prev_saw_zombie = saw_zombie

            if not saw_zombie and self.state == self.STATE_PANIC:
                self._panic_timer -= dt
                if self._panic_timer <= 0:
                    self.state = self.STATE_ALIVE

            speed = NPC_PANIC_SPEED if self.state == self.STATE_PANIC else NPC_SPEED

            # ── Random wander direction (only when calm) ──────────────────────
            if self.state == self.STATE_ALIVE:
                self._wander_timer -= dt
                if self._wander_timer <= 0:
                    angle = random.uniform(0, math.tau)
                    self._direction    = pygame.Vector2(math.cos(angle), math.sin(angle))
                    self._wander_timer = random.uniform(0.8, NPC_WANDER_CHANGE)

        # ── Zone speed multiplier ─────────────────────────────────────────────
        eff_speed = speed
        if zones:
            _on_road = any(z.zone_type == "road"
                           and z.rect.collidepoint(self.pos.x, self.pos.y)
                           for z in zones)
            if not _on_road:
                for zone in zones:
                    if zone.contains(self.pos) and 0 < zone.speed_mult < 1.0:
                        eff_speed = min(eff_speed, speed * zone.speed_mult)
                        break

        # Don't push into the player when in punch range
        if (self._fighting_back and self.state == self.STATE_HOSTILE
                and player is not None
                and self.pos.distance_to(player.pos) <= NPC_PUNCH_R):
            eff_speed = 0.0

        old_pos   = pygame.Vector2(self.pos)
        self.pos += self._direction * eff_speed * dt
        self._hit_flash = max(0.0, self._hit_flash - dt)

        # Advance walk animation proportional to actual movement
        move_dist = (self.pos - old_pos).length()
        if move_dist > 0.5:
            walk_rate = 14.0 if self.state == self.STATE_PANIC else 7.5
            self._walk_phase = (self._walk_phase + dt * walk_rate) % math.tau

        # ── Zone collision (lakes + hideout walls) ────────────────────────────
        if zones:
            for zone in zones:
                if zone.blocks_passage(old_pos, self.pos):
                    self.pos = old_pos
                    angle = random.uniform(0, math.tau)
                    self._direction    = pygame.Vector2(math.cos(angle), math.sin(angle))
                    self._wander_timer = random.uniform(0.3, 1.0)
                    break

        # ── World bounds ──────────────────────────────────────────────────────
        if self.pos.x < self.radius or self.pos.x > bounds[0] - self.radius:
            self._direction.x *= -1
            self.pos.x = max(self.radius, min(bounds[0] - self.radius, self.pos.x))
        if self.pos.y < self.radius or self.pos.y > bounds[1] - self.radius:
            self._direction.y *= -1
            self.pos.y = max(self.radius, min(bounds[1] - self.radius, self.pos.y))

        return fired

    def draw(self, surface, ox=0, oy=0):
        if self.state == self.STATE_DEAD:
            return
        r      = self.radius
        sx, sy = int(self.pos.x) - ox, int(self.pos.y) - oy

        if self._hit_flash > 0:
            shirt_col = (255, 80,  80)
            skin_col  = (255, 130, 130)
            pants_col = (200, 55,  55)
        elif self.state == self.STATE_HOSTILE:
            if self._fighting_back:
                shirt_col = (200, 55,  55)   # angry red
                skin_col  = (220, 110, 90)
                pants_col = (145, 40,  40)
            else:
                shirt_col = (210, 88,  20)   # armed hostile: burnt orange
                skin_col  = (185, 100, 55)
                pants_col = (155, 60,  15)
        elif self.state == self.STATE_INFECTED:
            shirt_col = (155, 85,  40)
            skin_col  = (130, 70,  30)
            pants_col = (110, 60,  25)
        else:
            shirt_col = (178, 172, 155)  # civilian jacket
            skin_col  = (195, 160, 125)  # skin
            pants_col = (135, 130, 118)  # trousers

        # Face where walking; armed + active → face shoot target
        face_dir   = self._direction
        gun_dir    = None
        punch_ext  = 0.0
        punch_arm  = self._punch_arm
        if self._fighting_back and self.state == self.STATE_HOSTILE:
            face_dir  = self._shoot_dir   # _shoot_dir = toward player
            # rise-fall curve matching player fist: 0.0→1.0→0.0
            if self._punch_anim > 0.0:
                _p = self._punch_anim / NPC_PUNCH_ANIM_DUR   # 1.0 → 0.0
                punch_ext = (1.0 - _p) / 0.35 if _p > 0.65 else _p / 0.65
                punch_ext = max(0.0, min(1.0, punch_ext))
        elif self.armed and self.state in (self.STATE_HOSTILE, self.STATE_PANIC):
            face_dir = self._shoot_dir
            gun_dir  = self._shoot_dir

        is_panicking = self.state == self.STATE_PANIC
        _draw_human_anim(surface, sx, sy, r, face_dir, self._walk_phase,
                         shirt_col, skin_col, pants_col,
                         gun_dir=gun_dir, gun_col=(48, 42, 30),
                         sprinting=is_panicking,
                         punch_ext=punch_ext, punch_arm=punch_arm)

        if self._burn_timer > 0:
            _draw_burn_overlay(surface, sx, sy, r, self._burn_timer)

        # Armed badge: small yellow dot above head
        if self.armed:
            pygame.draw.circle(surface, NPC_ARMED_BADGE,
                               (sx, sy - r - 6), 3)

        # HP bar (once damaged)
        if self.hp < self.max_hp:
            bw    = r * 2 + 4
            ratio = self.hp / self.max_hp
            bx    = sx - r - 2
            by    = sy - r - 14
            pygame.draw.rect(surface, (50, 15, 15), (bx, by, bw, 4))
            pygame.draw.rect(surface, (220, 160, 50), (bx, by, int(bw * ratio), 4))

        # '!!' alert pop
        if self._alert_timer > 0:
            FULL_TIME = 0.9
            elapsed   = FULL_TIME - self._alert_timer
            scale     = min(1.0, elapsed / 0.10)
            alpha     = int(255 * min(1.0, self._alert_timer / 0.22))
            oy_off    = int((1.0 - scale) * 5)
            ax        = sx
            ay        = sy - r - 22

            ico = pygame.Surface((26, 22), pygame.SRCALPHA)
            bar_h = max(1, int(9  * scale))
            bar_w = max(1, int(3  * scale))
            dot_r = max(1, int(2  * scale))
            # background bubble
            pygame.draw.rect(ico, (8, 6, 2, int(alpha * 0.70)),
                             (0, 0, 26, 22), border_radius=3)
            # draw two '!' bars side by side
            for ix in (6, 14):
                icx, icy = ix, 11
                out_a = (8, 5, 0, alpha)
                col   = (255, 80, 30, alpha)   # orange-red for danger
                pygame.draw.rect(ico, out_a,
                                 (icx - bar_w//2 - 1,
                                  icy - bar_h - dot_r*2 - 1 + oy_off,
                                  bar_w + 2, bar_h + 2))
                pygame.draw.circle(ico, out_a,
                                   (icx, icy + dot_r + 1 + oy_off), dot_r + 1)
                pygame.draw.rect(ico, col,
                                 (icx - bar_w//2,
                                  icy - bar_h - dot_r*2 + oy_off,
                                  bar_w, bar_h))
                pygame.draw.circle(ico, col, (icx, icy + dot_r + oy_off), dot_r)

            surface.blit(ico, (ax - 13, ay - 11))

        # Infection countdown bar
        if self.state == self.STATE_INFECTED:
            bw    = r * 2
            ratio = self.infection_timer / INFECTION_DELAY
            bx    = sx - r
            by    = sy - r - (20 if self.hp < self.max_hp else 8)
            pygame.draw.rect(surface, (80, 80, 80),  (bx, by, bw, 4))
            pygame.draw.rect(surface, (220, 80, 30), (bx, by, int(bw * ratio), 4))


# ── Sheriff ───────────────────────────────────────────────────────────────────

class Sheriff(NPC):
    """Town law enforcer: patrols, shoots zombies, turns hostile if player harms civilians."""

    def __init__(self, x, y, zone_rect=None):
        super().__init__(x, y)
        self.armed      = True
        self.hp         = SHERIFF_HP
        self.max_hp     = SHERIFF_HP
        self.radius     = 11
        self._origin    = pygame.Vector2(x, y)
        self._zone_rect = zone_rect   # town boundary rect (pygame.Rect or None)

    # Called by main.py when player harms any civilian/sheriff in range.
    @staticmethod
    def alert_nearby(npcs, hit_pos: pygame.Vector2):
        for n in npcs:
            if isinstance(n, Sheriff) and n.state != NPC.STATE_DEAD:
                if n.pos.distance_to(hit_pos) <= SHERIFF_ALERT_R:
                    n.state = NPC.STATE_HOSTILE

    def update(self, dt, bounds, zones=None, zombies=None, player=None):
        from projectiles import Bullet
        fired: list[Bullet] = []

        if self.state == self.STATE_DEAD:
            return fired
        if self.state == self.STATE_INFECTED:
            self.infection_timer -= dt
            if self.infection_timer <= 0:
                self.state = self.STATE_DEAD
            return fired

        self._gun_cd = max(0.0, self._gun_cd - dt)

        # ── HOSTILE: chase + shoot player ────────────────────────────────────
        if self.state == self.STATE_HOSTILE:
            if player is not None:
                d    = player.pos - self.pos
                dist = d.length()
                if dist > 0:
                    self._direction = d / dist
                    self._shoot_dir = d / dist
                if dist <= SHERIFF_GUN_RANGE and self._gun_cd <= 0:
                    vel = self._shoot_dir * NPC_GUN_SPEED
                    fired.append(Bullet(self.pos, vel, SHERIFF_GUN_DMG,
                                        (255, 140, 0), owner="npc"))
                    self._gun_cd = 1.0 / SHERIFF_GUN_RATE
            speed = NPC_PANIC_SPEED
        else:
            # ── Zombie detection: stand ground, shoot ─────────────────────────
            nearest_z  = None
            nearest_zd = SHERIFF_GUN_RANGE
            for z in (zombies or []):
                if z.alive:
                    d = self.pos.distance_to(z.pos)
                    if d < nearest_zd:
                        nearest_zd = d
                        nearest_z  = z

            if nearest_z is not None:
                toward = nearest_z.pos - self.pos
                if toward.length_squared() > 0:
                    self._shoot_dir = toward.normalize()
                self._direction = self._shoot_dir * 0.2   # barely move
                if self._gun_cd <= 0:
                    vel = self._shoot_dir * NPC_GUN_SPEED
                    fired.append(Bullet(self.pos, vel, SHERIFF_GUN_DMG,
                                        (255, 220, 80), owner="npc"))
                    self._gun_cd = 1.0 / SHERIFF_GUN_RATE
                speed = NPC_SPEED
            else:
                # ── Patrol: wander inside zone, drift back to origin if too far
                self._wander_timer -= dt
                if self._wander_timer <= 0:
                    angle = random.uniform(0, math.tau)
                    self._direction    = pygame.Vector2(math.cos(angle), math.sin(angle))
                    self._wander_timer = random.uniform(1.0, 2.5)

                dist_from_origin = self.pos.distance_to(self._origin)
                if dist_from_origin > SHERIFF_PATROL_R:
                    back = (self._origin - self.pos).normalize()
                    self._direction = back
                speed = NPC_SPEED * 0.8

        # ── Zone speed multiplier ─────────────────────────────────────────────
        eff_speed = speed
        if zones:
            _on_road = any(z.zone_type == "road"
                           and z.rect.collidepoint(self.pos.x, self.pos.y)
                           for z in zones)
            if not _on_road:
                for zone in zones:
                    if zone.contains(self.pos) and 0 < zone.speed_mult < 1.0:
                        eff_speed = min(eff_speed, speed * zone.speed_mult)
                        break

        old_pos   = pygame.Vector2(self.pos)
        self.pos += self._direction * eff_speed * dt
        self._hit_flash = max(0.0, self._hit_flash - dt)

        move_dist = (self.pos - old_pos).length()
        if move_dist > 0.5:
            walk_rate = 14.0 if self.state == self.STATE_HOSTILE else 7.5
            self._walk_phase = (self._walk_phase + dt * walk_rate) % math.tau

        if zones:
            for zone in zones:
                if zone.blocks_passage(old_pos, self.pos):
                    self.pos = old_pos
                    angle = random.uniform(0, math.tau)
                    self._direction    = pygame.Vector2(math.cos(angle), math.sin(angle))
                    self._wander_timer = random.uniform(0.3, 1.0)
                    break

        if self.pos.x < self.radius or self.pos.x > bounds[0] - self.radius:
            self._direction.x *= -1
            self.pos.x = max(self.radius, min(bounds[0] - self.radius, self.pos.x))
        if self.pos.y < self.radius or self.pos.y > bounds[1] - self.radius:
            self._direction.y *= -1
            self.pos.y = max(self.radius, min(bounds[1] - self.radius, self.pos.y))

        return fired

    def take_hit(self, damage: int, from_player: bool = False,
                 from_bullet: bool = False):
        super().take_hit(damage, from_player=False)   # don't re-trigger NPC logic
        self._hit_flash = 0.25
        if from_player and self.state != self.STATE_DEAD:
            self.state = self.STATE_HOSTILE   # always fight back regardless of bullet

    def draw(self, surface, ox=0, oy=0):
        if self.state == self.STATE_DEAD:
            return
        r      = self.radius
        sx, sy = int(self.pos.x) - ox, int(self.pos.y) - oy

        if self._hit_flash > 0:
            shirt_col = (255, 80,  80)
            skin_col  = (255, 130, 130)
            pants_col = (200, 55,  55)
        elif self.state == self.STATE_HOSTILE:
            shirt_col = (180, 60,  20)
            skin_col  = (190, 145, 100)
            pants_col = (130, 50,  15)
        else:
            shirt_col = (195, 165, 90)   # tan/khaki uniform
            skin_col  = (210, 170, 120)
            pants_col = (140, 110, 60)

        face_dir = self._direction
        gun_dir  = None
        if self.state in (self.STATE_HOSTILE,) or (
                self._shoot_dir.length_squared() > 0.01 and
                self.state not in (self.STATE_ALIVE,)):
            face_dir = self._shoot_dir
            gun_dir  = self._shoot_dir

        _draw_human_anim(surface, sx, sy, r, face_dir, self._walk_phase,
                         shirt_col, skin_col, pants_col,
                         gun_dir=gun_dir, gun_col=(55, 38, 22),
                         sprinting=(self.state == self.STATE_HOSTILE))

        # Sheriff star badge (gold, bigger than armed-NPC dot)
        star_cx, star_cy = sx, sy - r - 7
        pygame.draw.circle(surface, (240, 200, 30), (star_cx, star_cy), 5)
        pygame.draw.circle(surface, (180, 140, 10), (star_cx, star_cy), 5, 1)

        # HP bar (once damaged)
        if self.hp < self.max_hp:
            bw    = r * 2 + 4
            ratio = self.hp / self.max_hp
            bx    = sx - r - 2
            by    = sy - r - 16
            pygame.draw.rect(surface, (50, 15, 15), (bx, by, bw, 4))
            pygame.draw.rect(surface, (220, 180, 30), (bx, by, int(bw * ratio), 4))


# ── ShopkeeperNPC ─────────────────────────────────────────────────────────────

SHOPKEEPER_INTERACT_R = 55   # interaction radius (px)

# Per-shop-type visual colours: (shirt, skin, pants)
_SK_COLORS = {
    "hospital": ((215, 230, 215), (210, 178, 140), (175, 195, 175)),
    "weapon":   (( 52,  68,  44), (185, 152, 122), ( 42,  50,  38)),
    "hardware": (( 55,  70, 110), (195, 162, 130), ( 40,  48,  75)),
    "mart":     ((210, 195,  48), (210, 175, 135), ( 55,  60,  85)),
    "gym":      (( 48, 155,  48), (195, 160, 125), ( 28,  75,  28)),
}

# Small icon drawn above head per shop type (text glyph)
_SK_ICON = {
    "hospital": "+",
    "weapon":   "★",
    "hardware": "⚙",
    "mart":     "$",
    "gym":      "💪",
}


class ShopkeeperNPC(NPC):
    """Static shopkeeper NPC. Invincible, faces player when nearby."""

    def __init__(self, x, y, shop_type: str):
        super().__init__(x, y)
        self.shop_type  = shop_type
        self.hp         = 150
        self.max_hp     = 150
        self.armed      = False
        self._origin    = pygame.Vector2(x, y)

    # ── Overrides ─────────────────────────────────────────────────────────────

    def take_hit(self, damage: int, from_player: bool = False,
                 from_bullet: bool = False):
        if self.state == self.STATE_DEAD:
            return
        self.hp = max(0, self.hp - damage)
        self._hit_flash = 0.25
        if self.hp <= 0:
            self.state = self.STATE_DEAD

    def hear_gunshot(self, shot_pos: pygame.Vector2):
        pass   # doesn't react

    def update(self, dt, bounds, zones=None, zombies=None, player=None):
        # Slowly face toward player when nearby; idle walk-phase bob
        if player is not None:
            d = player.pos - self.pos
            if 0 < d.length() < 120:
                self._direction = d.normalize()
        self._walk_phase = (self._walk_phase + dt * 1.8) % math.tau
        return []   # no bullets

    def draw(self, surface, ox=0, oy=0):
        if self.state == self.STATE_DEAD:
            return
        r      = self.radius
        sx, sy = int(self.pos.x) - ox, int(self.pos.y) - oy

        shirt_col, skin_col, pants_col = _SK_COLORS.get(
            self.shop_type, _SK_COLORS["mart"])

        _draw_human_anim(surface, sx, sy, r, self._direction, self._walk_phase,
                         shirt_col, skin_col, pants_col)

        # Small icon badge above head
        icon = _SK_ICON.get(self.shop_type, "?")
        try:
            import fonts as _fonts
            _fnt = _fonts.get(14)
            _ico = _fnt.render(icon, True, (240, 230, 180))
            surface.blit(_ico, (sx - _ico.get_width() // 2, sy - r - 14))
        except Exception:
            pass

    def draw_interact_hint(self, surface, ox, oy, font):
        """Draw 'T — 거래' prompt above head when player is near."""
        if font is None:
            return
        sx, sy = int(self.pos.x) - ox, int(self.pos.y) - oy
        _, _, _, edge = (None, None, None,
                         (60, 140, 60) if self.shop_type == "gym" else
                         (115, 55, 55) if self.shop_type == "weapon" else
                         (55, 105, 55) if self.shop_type == "hospital" else
                         (65, 65, 115) if self.shop_type == "hardware" else
                         (115, 108, 42))
        text  = "T — 거래"
        ts    = font.render(text, True, edge)
        tx    = sx - ts.get_width()  // 2
        ty    = sy - self.radius - 26
        bg    = pygame.Surface((ts.get_width() + 10, ts.get_height() + 4),
                                pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        surface.blit(bg, (tx - 5, ty - 2))
        surface.blit(ts, (tx, ty))


# ── Zombie ────────────────────────────────────────────────────────────────────

_STATE_COLORS = {
    "wander":      (150, 150, 150),
    "investigate": (255, 180, 0),
    "chase":       (255, 60,  60),
}


class Zombie:
    STATE_WANDER      = "wander"
    STATE_INVESTIGATE = "investigate"
    STATE_CHASE       = "chase"

    def __init__(self, x, y, kind="regular", day: int = 1):
        from difficulty import hp_mult, speed_mult
        cfg = ZOMBIE_TYPES[kind]
        hm  = hp_mult(day)
        sm  = speed_mult(day)
        self.pos            = pygame.Vector2(x, y)
        self.kind           = kind
        self.radius         = cfg["radius"]
        self._color         = cfg["color"]
        self._speeds        = {k: v * sm for k, v in cfg["speed"].items()}
        self.contact_dmg    = cfg["contact_dmg"]
        self.contact_rate   = cfg["contact_rate"]
        self.screw_drop     = cfg["screw_drop"]
        self.state          = self.STATE_WANDER
        self.last_known_pos = None
        self.bite_cooldown  = 0.0
        self._contact_cd    = 0.0
        self._hear_noise_pos = None
        self._alert_timer    = 0.0
        self._target_npc     = None
        self._wander_dir    = pygame.Vector2(random.uniform(-1, 1),
                                             random.uniform(-1, 1)).normalize()
        self._wander_timer  = random.uniform(0, 2.0)
        self._facing        = pygame.Vector2(self._wander_dir)
        self.hp             = int(cfg["hp"] * hm)
        self.max_hp         = self.hp
        self.alive          = True
        # Quad-specific pounce state
        self._pounce_cd    = random.uniform(2.0, 4.0) if kind == "quad" else 0.0
        self._pounce_timer = 0.0
        self._pounce_dir   = pygame.Vector2(1, 0)
        # Bite animation
        self._bite_anim    = 0.0
        # Burn state (flamethrower DoT)
        self._burn_timer   = 0.0
        self._burn_dps     = 0.0

    # ── State machine ──────────────────────────────────────────────────────

    def alert(self, noise_pos: pygame.Vector2):
        """Called externally when a loud sound (gunshot, explosion) is heard."""
        if self.alive:
            self._hear_noise_pos = pygame.Vector2(noise_pos)

    def _next_state(self, player, npcs):
        alert_pos = self._hear_noise_pos
        self._hear_noise_pos = None

        # ── Visibility checks ─────────────────────────────────────────────
        eff_sight  = ZOMBIE_SIGHT + (NIGHT_SIGHT_BONUS if night_mode else 0)
        pdist      = self.pos.distance_to(player.pos)
        close_p    = pdist < self.radius + player.radius + 60
        can_see_p  = (close_p or not player.is_hidden) and pdist <= eff_sight
        can_hear_p = player.noise_radius > 0 and pdist <= player.noise_radius

        # ── Find nearest visible target (player or NPC, distance wins) ────
        best_dist   = pdist if can_see_p else float('inf')
        best_is_npc = False
        best_npc    = None

        for npc in npcs:
            if npc.state != NPC.STATE_DEAD:
                d = self.pos.distance_to(npc.pos)
                if d <= eff_sight and d < best_dist:
                    best_dist   = d
                    best_is_npc = True
                    best_npc    = npc

        # ── Chase nearest visible target ───────────────────────────────────
        if best_dist < float('inf'):
            if best_is_npc:
                self._target_npc    = best_npc
                self.last_known_pos = pygame.Vector2(best_npc.pos)
            else:
                self._target_npc    = None
                self.last_known_pos = pygame.Vector2(player.pos)
            return self.STATE_CHASE

        # ── No visible target: respond to sounds ───────────────────────────
        self._target_npc = None
        if can_hear_p:
            self.last_known_pos = pygame.Vector2(player.pos)
            return self.STATE_INVESTIGATE
        if alert_pos is not None:
            self.last_known_pos = alert_pos
            return self.STATE_INVESTIGATE
        if self.state == self.STATE_CHASE:
            return self.STATE_INVESTIGATE
        if self.state == self.STATE_INVESTIGATE:
            if self.last_known_pos and self.pos.distance_to(self.last_known_pos) < 20:
                return self.STATE_WANDER
            return self.STATE_INVESTIGATE
        return self.STATE_WANDER

    # ── Movement ───────────────────────────────────────────────────────────

    def _get_waypoint(self, target_pos: pygame.Vector2, zones) -> pygame.Vector2:
        """Route toward target_pos, using the door approach point when target is
        inside a hideout and we are still outside."""
        if not zones:
            return target_pos
        for zone in zones:
            if zone.zone_type != "hideout":
                continue
            if not zone.contains(target_pos):
                continue
            # Target is inside this hideout
            if zone.contains(self.pos):
                return target_pos          # both inside — go straight to target
            if zone.door_open:
                approach = zone.door_approach
                if approach is not None:
                    return approach        # outside — head for door entrance
            # Door is closed; we can't get in, so don't push against the wall
            return target_pos
        return target_pos

    def _wander(self, dt, speed, bounds):
        self._wander_timer -= dt
        if self._wander_timer <= 0:
            angle = random.uniform(0, math.tau)
            self._wander_dir   = pygame.Vector2(math.cos(angle), math.sin(angle))
            self._wander_timer = random.uniform(1.0, 2.5)

        self.pos += self._wander_dir * speed * dt

        if self.pos.x < self.radius or self.pos.x > bounds[0] - self.radius:
            self._wander_dir.x *= -1
            self.pos.x = max(self.radius, min(bounds[0] - self.radius, self.pos.x))
        if self.pos.y < self.radius or self.pos.y > bounds[1] - self.radius:
            self._wander_dir.y *= -1
            self.pos.y = max(self.radius, min(bounds[1] - self.radius, self.pos.y))

    def _move_toward(self, dt, target, speed):
        d = target - self.pos
        if d.length_squared() > 1:
            self.pos += d.normalize() * speed * dt

    def _try_bite(self, npcs):
        if self.bite_cooldown > 0:
            return
        for npc in npcs:
            if npc.state != NPC.STATE_DEAD:
                if self.pos.distance_to(npc.pos) < self.radius + npc.radius + ZOMBIE_ATTACK_REACH:
                    npc.bite()
                    npc.panic(self.pos)
                    self.bite_cooldown = 1.0
                    self._bite_anim    = ZOMBIE_BITE_ANIM_DUR
                    break

    def _try_contact_damage(self, player):
        if self._contact_cd > 0:
            return
        if self.pos.distance_to(player.pos) < self.radius + player.radius + ZOMBIE_ATTACK_REACH:
            dmg    = int(self.contact_dmg * (NIGHT_DMG_MULT if night_mode else 1.0))
            riding = getattr(player, '_riding', None)
            if riding is not None and riding.alive:
                # Once any lift: helicopter/airplane rotors make them untouchable
                if getattr(riding, 'altitude', 0.0) < 0.05:
                    reduction  = getattr(riding, 'damage_reduction', 0.0)
                    veh_dmg    = int(dmg * (1.0 - reduction))
                    riding.hp  = max(0, riding.hp - veh_dmg)
                    if riding.hp <= 0:
                        riding.alive = False
                    exposure = getattr(riding, 'rider_exposure', 0.0)
                    if exposure > 0:
                        player.take_damage(int(dmg * exposure))
            else:
                player.take_damage(dmg)
            self._contact_cd = self.contact_rate
            self._bite_anim  = ZOMBIE_BITE_ANIM_DUR

    def take_hit(self, damage: int, bullet_vel: pygame.Vector2):
        self.hp -= damage
        if self.hp <= 0:
            self.alive = False
        elif bullet_vel.length_squared() > 0:
            self.pos += bullet_vel.normalize() * KNOCKBACK_DIST

    def ignite(self, dps: float, duration: float = 3.5):
        """Start or refresh a burn-over-time effect."""
        self._burn_timer = max(self._burn_timer, duration)
        self._burn_dps   = max(self._burn_dps,   dps)

    def take_melee_hit(self, damage: int, knock_dir: pygame.Vector2,
                       knock_dist: float):
        self.hp -= damage
        if self.hp <= 0:
            self.alive = False
        elif knock_dir.length_squared() > 0 and knock_dist > 0:
            self.pos += knock_dir.normalize() * knock_dist

    def screw_count(self) -> int:
        lo, hi = self.screw_drop
        return random.randint(lo, hi)

    # ── Update ─────────────────────────────────────────────────────────────

    def update(self, dt, player, npcs, bounds, zones=None):
        if not self.alive:
            return
        self.bite_cooldown = max(0.0, self.bite_cooldown - dt)
        self._contact_cd   = max(0.0, self._contact_cd - dt)
        self._bite_anim    = max(0.0, self._bite_anim - dt)

        # Burn DoT
        if self._burn_timer > 0:
            self._burn_timer -= dt
            self.hp          -= self._burn_dps * dt
            if self.hp <= 0:
                self.alive = False
                return

        prev_state = self.state
        self.state = self._next_state(player, npcs)
        if self.state == self.STATE_CHASE and prev_state != self.STATE_CHASE:
            self._alert_timer = 0.85   # '!' pop on first detection
        self._alert_timer = max(0.0, self._alert_timer - dt)
        speed = self._speeds[self.state]

        old_pos = pygame.Vector2(self.pos)

        # ── Quad: pounce check then early-out movement ────────────────────
        _pouncing = False
        if self.kind == "quad":
            self._pounce_cd = max(0.0, self._pounce_cd - dt)
            if self._pounce_timer > 0:
                self._pounce_timer -= dt
                self.pos    += self._pounce_dir * 400.0 * dt
                self._facing = pygame.Vector2(self._pounce_dir)
                _pouncing    = True
            elif self.state == self.STATE_CHASE and self._pounce_cd <= 0:
                tgt = (self._target_npc.pos
                       if self._target_npc and self._target_npc.state != NPC.STATE_DEAD
                       else player.pos)
                d = self.pos.distance_to(tgt)
                if 55 < d < 290:
                    self._pounce_dir   = (tgt - self.pos).normalize()
                    self._pounce_timer = 0.30
                    self._pounce_cd    = random.uniform(3.5, 6.0)
                    self._alert_timer  = 0.4

        # ── Normal movement (skipped while pouncing) ──────────────────────
        if not _pouncing:
            if self.state == self.STATE_WANDER:
                self._wander(dt, speed, bounds)
            elif self.state == self.STATE_INVESTIGATE and self.last_known_pos:
                wp = self._get_waypoint(self.last_known_pos, zones)
                self._move_toward(dt, wp, speed)
            elif self.state == self.STATE_CHASE:
                if self._target_npc is not None and self._target_npc.state != NPC.STATE_DEAD:
                    tgt_pos = self._target_npc.pos
                    tgt_r   = self._target_npc.radius
                    wp      = self._get_waypoint(tgt_pos, zones)
                else:
                    self._target_npc = None
                    tgt_pos = player.pos
                    tgt_r   = player.radius
                    wp      = self._get_waypoint(tgt_pos, zones)
                if self.pos.distance_to(tgt_pos) > self.radius + tgt_r + ZOMBIE_ATTACK_REACH:
                    self._move_toward(dt, wp, speed)

        # Hideouts (walls) and lakes block zombie movement
        if zones:
            for zone in zones:
                if zone.blocks_passage(old_pos, self.pos):
                    self.pos = old_pos
                    # Deflect along the zone boundary instead of stopping dead
                    away = old_pos - pygame.Vector2(zone.rect.center)
                    if away.length_squared() > 0:
                        perp = pygame.Vector2(-away.y, away.x).normalize()
                        self._wander_dir   = perp if random.random() > 0.5 else -perp
                        self._wander_timer = random.uniform(0.4, 1.2)
                    break

        # Update visual facing from actual movement delta
        delta = self.pos - old_pos
        if delta.length_squared() > 0.5:
            self._facing = delta.normalize()

        # ── Drowning: take rapid damage while inside a lake (not on road) ──
        if zones:
            _zomb_on_road = any(z.zone_type == "road"
                                and z.rect.collidepoint(self.pos.x, self.pos.y)
                                for z in zones)
            if not _zomb_on_road:
                for zone in zones:
                    if (zone.zone_type == "lake"
                            and zone.rect.collidepoint(self.pos.x, self.pos.y)):
                        self.hp -= LAKE_DROWN_RATE * dt
                        if self.hp <= 0:
                            self.alive = False
                        break

        # ── Safe-zone repulsion (daytime: zombies avoid core-town fences) ───
        if zones and not night_mode and self.state != self.STATE_CHASE:
            for zone in zones:
                if getattr(zone, 'is_safe_zone', False) and zone.contains(self.pos):
                    self.pos = old_pos
                    away = old_pos - pygame.Vector2(zone.rect.centerx, zone.rect.centery)
                    if away.length_squared() > 0:
                        self._wander_dir = away.normalize()
                    self._wander_timer = random.uniform(1.5, 3.0)
                    break

        # ── Military base always blocks zombies (day and night) ──────────────
        if zones:
            for zone in zones:
                if zone.zone_type == "military" and zone.contains(self.pos):
                    self.pos = old_pos
                    away = old_pos - pygame.Vector2(zone.rect.centerx, zone.rect.centery)
                    if away.length_squared() > 0:
                        self._wander_dir = away.normalize()
                    self._wander_timer = random.uniform(1.5, 3.0)
                    break

        self._try_bite(npcs)
        if self.state == self.STATE_CHASE:
            self._try_contact_damage(player)

    # ── Draw ───────────────────────────────────────────────────────────────

    def draw(self, surface, ox=0, oy=0, debug=False, font=None):
        if not self.alive:
            return
        r      = self.radius
        sx, sy = int(self.pos.x) - ox, int(self.pos.y) - oy

        # Compute bite_t: rise-fall curve over ZOMBIE_BITE_ANIM_DUR
        bite_t = 0.0
        if self._bite_anim > 0.0:
            _p    = self._bite_anim / ZOMBIE_BITE_ANIM_DUR   # 1.0 → 0.0
            bite_t = (1.0 - _p) / 0.35 if _p > 0.65 else _p / 0.65
            bite_t = max(0.0, min(1.0, bite_t))

        if self.kind == "quad":
            _draw_quad_figure(surface, sx, sy, r, self._facing, self._color,
                              pouncing=self._pounce_timer > 0)
        else:
            _draw_zombie_figure(surface, sx, sy, r, self._facing, self._color,
                                bite_t=bite_t)

        # Burn overlay
        if self._burn_timer > 0:
            _draw_burn_overlay(surface, sx, sy, r, self._burn_timer)

        # HP bar
        if self.hp < self.max_hp:
            bw    = r * 2 + 4
            ratio = self.hp / self.max_hp
            bx    = sx - r - 2
            by    = sy - r - 14
            pygame.draw.rect(surface, (70, 18, 18), (bx, by, bw, 4))
            hp_color = ((60, 200, 60)   if ratio > 0.5
                        else (210, 200, 50) if ratio > 0.25
                        else (220, 55, 55))
            pygame.draw.rect(surface, hp_color, (bx, by, int(bw * ratio), 4))

        # '!' detection alert
        if self._alert_timer > 0:
            FULL_TIME = 0.85
            elapsed   = FULL_TIME - self._alert_timer
            # Pop scale: 0→1 in first 0.12 s
            scale = min(1.0, elapsed / 0.12)
            # Fade out in last 0.25 s
            alpha = int(255 * min(1.0, self._alert_timer / 0.25))

            ax = sx
            ay = sy - self.radius - 20

            # Surface for the whole icon (alpha-composited)
            ico = pygame.Surface((18, 22), pygame.SRCALPHA)
            icx, icy = 9, 11    # centre inside icon surface

            bar_h = max(1, int(10 * scale))
            bar_w = max(1, int(4  * scale))
            dot_r = max(1, int(3  * scale))
            # slide up during pop
            oy_off = int((1.0 - scale) * 6)

            # Bubble background
            pygame.draw.rect(ico, (22, 18, 8, int(alpha * 0.72)),
                             (0, 0, 18, 22), border_radius=3)
            # Dark outline
            out_a = (10, 8, 2, alpha)
            pygame.draw.rect(ico, out_a,
                             (icx - bar_w//2 - 1, icy - bar_h - dot_r*2 - 1 + oy_off,
                              bar_w + 2, bar_h + 2))
            pygame.draw.circle(ico, out_a,
                               (icx, icy + dot_r + 1 + oy_off), dot_r + 1)
            # Yellow fill
            yel = (255, 218, 28, alpha)
            pygame.draw.rect(ico, yel,
                             (icx - bar_w//2, icy - bar_h - dot_r*2 + oy_off,
                              bar_w, bar_h))
            pygame.draw.circle(ico, yel, (icx, icy + dot_r + oy_off), dot_r)

            surface.blit(ico, (ax - 9, ay - 11))

        if not debug:
            return

        _debug_circle(surface, (255, 50, 50), self.pos, ZOMBIE_SIGHT, 12, ox, oy)
        pygame.draw.circle(surface, (180, 40, 40), (sx, sy), ZOMBIE_SIGHT, 1)

        if font:
            label_text  = lang.t(f"zs_{self.state}")
            label_color = _STATE_COLORS[self.state]
            txt = font.render(label_text, True, label_color)
            surface.blit(txt, (sx - txt.get_width() // 2, sy - self.radius - 18))

        if self.state == self.STATE_INVESTIGATE and self.last_known_pos:
            lx = int(self.last_known_pos.x) - ox
            ly = int(self.last_known_pos.y) - oy
            pygame.draw.line(surface, (255, 180, 0), (sx, sy), (lx, ly), 1)
            pygame.draw.circle(surface, (255, 180, 0), (lx, ly), 6, 1)
            pygame.draw.line(surface, (255, 180, 0), (lx - 4, ly - 4), (lx + 4, ly + 4), 1)
            pygame.draw.line(surface, (255, 180, 0), (lx + 4, ly - 4), (lx - 4, ly + 4), 1)
