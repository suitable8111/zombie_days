import pygame
import random
import math

# 파티클 draw용 공유 Surface — 매 프레임 신규 할당 방지
_PSURF: pygame.Surface | None = None
_PSURF_SIZE = 82   # 반지름 최대 40px 기준


def _psurf() -> pygame.Surface:
    global _PSURF
    if _PSURF is None:
        _PSURF = pygame.Surface((_PSURF_SIZE, _PSURF_SIZE), pygame.SRCALPHA)
    return _PSURF


class Particle:
    __slots__ = ("pos", "vel", "color", "life", "max_life", "radius", "gravity")

    def __init__(self, pos, vel, color, life, radius=2, gravity=0.0):
        self.pos      = pygame.Vector2(pos)
        self.vel      = pygame.Vector2(vel)
        self.color    = color
        self.life     = life
        self.max_life = life
        self.radius   = radius
        self.gravity  = gravity

    @property
    def alive(self):
        return self.life > 0

    def update(self, dt):
        self.life    -= dt
        self.vel.y   += self.gravity * dt
        self.pos     += self.vel * dt

    def draw(self, surface, ox=0, oy=0):
        ratio = max(0.0, self.life / self.max_life)
        alpha = int(255 * ratio)
        r     = max(1, min(39, int(self.radius * ratio)))
        w     = r * 2 + 2
        s     = _psurf()
        s.fill((0, 0, 0, 0), (0, 0, w, w))
        pygame.draw.circle(s, (*self.color, alpha), (r + 1, r + 1), r)
        surface.blit(s, (int(self.pos.x) - ox - r - 1,
                         int(self.pos.y) - oy - r - 1), (0, 0, w, w))


class ParticleManager:
    def __init__(self):
        self._particles: list[Particle] = []

    # ── Emitters ──────────────────────────────────────────────────────────────

    def muzzle_flash(self, pos: pygame.Vector2, direction: pygame.Vector2):
        for _ in range(6):
            spread = direction.rotate(random.uniform(-22, 22))
            spd    = random.uniform(80, 200)
            self._particles.append(Particle(
                pos, spread * spd,
                color=(255, random.randint(180, 255), 60),
                life=random.uniform(0.04, 0.10),
                radius=random.randint(2, 4),
            ))

    def blood_hit(self, pos: pygame.Vector2, bullet_vel: pygame.Vector2):
        n = random.randint(5, 10)
        for _ in range(n):
            angle  = random.uniform(0, math.tau)
            spd    = random.uniform(40, 140)
            d      = pygame.Vector2(math.cos(angle), math.sin(angle))
            if bullet_vel.length_squared() > 0:
                d = (d + bullet_vel.normalize() * 0.6).normalize()
            self._particles.append(Particle(
                pos, d * spd,
                color=(random.randint(160, 210), 20, 20),
                life=random.uniform(0.25, 0.55),
                radius=random.randint(2, 4),
                gravity=120.0,
            ))

    def death_explosion(self, pos: pygame.Vector2, color=(60, 180, 60)):
        for _ in range(18):
            angle = random.uniform(0, math.tau)
            spd   = random.uniform(50, 180)
            self._particles.append(Particle(
                pos,
                pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=color,
                life=random.uniform(0.3, 0.7),
                radius=random.randint(2, 5),
                gravity=60.0,
            ))
        # blood burst on death
        for _ in range(10):
            angle = random.uniform(0, math.tau)
            spd   = random.uniform(30, 100)
            self._particles.append(Particle(
                pos,
                pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=(random.randint(150, 200), 15, 15),
                life=random.uniform(0.4, 0.8),
                radius=random.randint(2, 3),
                gravity=80.0,
            ))

    def explosion(self, pos: pygame.Vector2, blast_radius: float = 100):
        """Grenade explosion: fire + debris + shockwave."""
        for _ in range(28):
            angle = random.uniform(0, math.tau)
            spd   = random.uniform(60, 260)
            col   = random.choice([(255, 160, 30), (255, 80, 20), (240, 230, 160)])
            self._particles.append(Particle(
                pos, pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=col, life=random.uniform(0.3, 0.75),
                radius=random.randint(3, 7), gravity=60.0,
            ))
        # shockwave ring
        for i in range(20):
            angle = i * math.tau / 20
            spd   = random.uniform(blast_radius * 1.8, blast_radius * 2.2)
            self._particles.append(Particle(
                pos, pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=(255, 220, 120), life=random.uniform(0.08, 0.18),
                radius=2,
            ))
        # smoke
        for _ in range(12):
            angle = random.uniform(0, math.tau)
            spd   = random.uniform(20, 80)
            self._particles.append(Particle(
                pos, pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=(130, 120, 110), life=random.uniform(0.5, 1.0),
                radius=random.randint(4, 9), gravity=-15.0,
            ))

    def vehicle_explosion(self, pos: pygame.Vector2, radius: float = 120):
        """Dramatic vehicle destruction: fireball + debris + black smoke + sparks."""
        # Core fireball
        for _ in range(55):
            angle = random.uniform(0, math.tau)
            spd   = random.uniform(80, radius * 2.8)
            col   = random.choice([
                (255, 70,  10), (255, 140, 20), (255, 200, 45),
                (240, 50,  10), (255, 255, 110), (220, 90, 15),
            ])
            self._particles.append(Particle(
                pos, pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=col, life=random.uniform(0.45, 1.1),
                radius=random.randint(5, 16), gravity=30.0,
            ))
        # Metal debris (dark, heavy gravity)
        for _ in range(35):
            angle = random.uniform(0, math.tau)
            spd   = random.uniform(120, radius * 3.2)
            col   = random.choice([(58, 52, 44), (78, 68, 52), (95, 85, 65)])
            self._particles.append(Particle(
                pos, pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=col, life=random.uniform(0.7, 1.6),
                radius=random.randint(2, 6), gravity=200.0,
            ))
        # Black smoke (rises upward)
        for _ in range(30):
            angle = random.uniform(0, math.tau)
            spd   = random.uniform(12, 55)
            shade = random.randint(16, 50)
            self._particles.append(Particle(
                pos, pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=(shade, shade, shade), life=random.uniform(1.2, 2.8),
                radius=random.randint(10, 22), gravity=-28.0,
            ))
        # Shockwave rings (three sizes)
        for scale in (0.55, 1.0, 1.5):
            ring_r = radius * scale
            n      = max(16, int(24 * scale))
            for i in range(n):
                a   = i * math.tau / n
                spd = random.uniform(ring_r * 1.5, ring_r * 2.1)
                self._particles.append(Particle(
                    pos, pygame.Vector2(math.cos(a), math.sin(a)) * spd,
                    color=(255, 210, 80), life=random.uniform(0.05, 0.16),
                    radius=random.randint(2, 4),
                ))
        # Sparks (bright, fast, short)
        for _ in range(45):
            angle = random.uniform(0, math.tau)
            spd   = random.uniform(160, radius * 4.5)
            self._particles.append(Particle(
                pos, pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=(255, 255, 190), life=random.uniform(0.08, 0.32),
                radius=1, gravity=220.0,
            ))

    def vehicle_smoke(self, pos: pygame.Vector2):
        """Low-HP vehicle damage smoke."""
        for _ in range(3):
            angle = random.uniform(0, math.tau)
            spd   = random.uniform(8, 28)
            shade = random.randint(28, 65)
            offset = pygame.Vector2(random.uniform(-10, 10), random.uniform(-10, 10))
            self._particles.append(Particle(
                pos + offset,
                pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=(shade, shade, shade), life=random.uniform(0.5, 1.1),
                radius=random.randint(4, 9), gravity=-22.0,
            ))

    def heal_effect(self, pos: pygame.Vector2):
        for _ in range(14):
            angle = random.uniform(0, math.tau)
            spd   = random.uniform(20, 70)
            self._particles.append(Particle(
                pos, pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=(80, 255, 130), life=random.uniform(0.4, 0.9),
                radius=random.randint(2, 4), gravity=-40.0,
            ))

    def screw_pop(self, pos: pygame.Vector2):
        for _ in range(5):
            angle = random.uniform(0, math.tau)
            spd   = random.uniform(30, 90)
            self._particles.append(Particle(
                pos,
                pygame.Vector2(math.cos(angle), math.sin(angle)) * spd,
                color=(200, 200, 200),
                life=random.uniform(0.3, 0.6),
                radius=2,
                gravity=40.0,
            ))

    # ── Update / draw ─────────────────────────────────────────────────────────

    def update(self, dt):
        for p in self._particles:
            p.update(dt)
        self._particles = [p for p in self._particles if p.alive]

    def draw(self, surface, ox=0, oy=0):
        for p in self._particles:
            p.draw(surface, ox, oy)
