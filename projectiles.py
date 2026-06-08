import pygame
import math
import random


class Flame:
    """Flamethrower particle — short-lived, cone-spread, continuous damage."""
    MAX_LIFE = 0.48

    def __init__(self, origin, direction, speed, damage, owner="player"):
        self.pos    = pygame.Vector2(origin)
        self.vel    = pygame.Vector2(direction) * speed
        self.damage = damage
        self.life   = self.MAX_LIFE * random.uniform(0.7, 1.0)
        self._max   = self.life
        self.alive  = True
        self.owner  = owner
        self._hit   = set()   # entity ids already damaged this flame

    def update(self, dt):
        self.life -= dt
        if self.life <= 0:
            self.alive = False
            return
        self.vel   *= max(0.0, 1.0 - dt * 2.8)
        self.pos   += self.vel * dt

    @property
    def radius(self):
        ratio = self.life / self._max
        return max(2, int(5 + 10 * (1 - ratio)))   # grows as it ages

    def draw(self, surface, ox=0, oy=0):
        ratio = self.life / self._max
        r = self.radius
        sx, sy = int(self.pos.x) - ox, int(self.pos.y) - oy
        if ratio > 0.65:
            col = (255, 230, 60)
        elif ratio > 0.35:
            col = (255, 110, 20)
        else:
            col = (190, 40, 10)
        alpha = int(210 * ratio)
        s = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(s, (*col, alpha), (r + 1, r + 1), r)
        surface.blit(s, (sx - r - 1, sy - r - 1))


class Bullet:
    def __init__(self, origin, vel, damage, color, owner="player"):
        self.pos    = pygame.Vector2(origin)
        self.vel    = pygame.Vector2(vel)
        self.damage = damage
        self.color  = color
        self.radius = 3
        self.alive  = True
        self.owner  = owner   # "player" or "npc"

    def update(self, dt, bounds):
        self.pos += self.vel * dt
        if (self.pos.x < 0 or self.pos.x > bounds[0] or
                self.pos.y < 0 or self.pos.y > bounds[1]):
            self.alive = False

    def draw(self, surface, ox=0, oy=0):
        sx, sy = int(self.pos.x) - ox, int(self.pos.y) - oy
        if self.vel.length_squared() > 0:
            tail = self.pos - self.vel.normalize() * 7
            pygame.draw.line(surface, self.color,
                             (int(tail.x) - ox, int(tail.y) - oy), (sx, sy), 3)
        pygame.draw.circle(surface, self.color, (sx, sy), self.radius)


class Grenade:
    RADIUS = 6

    def __init__(self, origin, vel, damage, blast_radius, fuse_time):
        self.pos          = pygame.Vector2(origin)
        self.vel          = pygame.Vector2(vel)
        self.damage       = damage
        self.blast_radius = blast_radius
        self.fuse_time    = fuse_time
        self._timer       = fuse_time
        self.alive        = True
        self.exploded     = False

    def update(self, dt):
        if not self.alive:
            return
        self.pos     += self.vel * dt
        self.vel     *= max(0.0, 1.0 - dt * 2)   # air drag
        self._timer  -= dt
        if self._timer <= 0:
            self.alive    = False
            self.exploded = True

    @property
    def fuse_ratio(self):
        return max(0.0, self._timer / self.fuse_time)

    def draw(self, surface, ox=0, oy=0):
        sx, sy = int(self.pos.x) - ox, int(self.pos.y) - oy
        # Blink faster as fuse runs out
        blink = int(self._timer * (4 + 8 * (1 - self.fuse_ratio))) % 2
        body  = (80, 200, 60) if blink else (220, 80, 40)
        pygame.draw.circle(surface, body, (sx, sy), self.RADIUS)
        pygame.draw.circle(surface, (220, 230, 200), (sx, sy), self.RADIUS, 1)


class HitEvent:
    __slots__ = ("pos", "vel", "killed", "target")

    def __init__(self, pos, vel, killed, target="zombie"):
        self.pos    = pygame.Vector2(pos)
        self.vel    = pygame.Vector2(vel)
        self.killed = killed
        self.target = target   # "zombie" or "npc"


class ProjectileManager:
    def __init__(self):
        self.bullets:  list[Bullet]  = []
        self.grenades: list[Grenade] = []
        self.flames:   list[Flame]   = []

    def add(self, projectiles):
        for p in projectiles:
            if isinstance(p, Grenade):
                self.grenades.append(p)
            elif isinstance(p, Flame):
                self.flames.append(p)
            else:
                self.bullets.append(p)

    def update(self, dt, bounds, zones, zombies, npcs=None, player=None,
               remote_players=None, pvp_out=None):
        """Returns (list[HitEvent], list[Grenade exploded]).
        remote_players: {pid: NetworkPlayer} — 멀티 PvP 대상.
        pvp_out: 리스트면 (target_id, dmg, knock) 튜플이 append 된다.
        """
        hits: list[HitEvent] = []

        for b in self.bullets:
            if not b.alive:
                continue
            b.update(dt, bounds)
            if not b.alive:
                continue
            # Block by lake (impassable zone)
            for zone in zones:
                if zone.blocks_movement and zone.contains(b.pos):
                    b.alive = False
                    break
            if not b.alive:
                continue
            # ── PvP: 내 총알이 원격 플레이어 적중 (멀티) ──────────────────
            if b.owner == "player" and remote_players:
                for pid, rp in remote_players.items():
                    if rp.alive and b.pos.distance_to(rp.render_pos) < b.radius + rp.radius:
                        knock = (b.vel.normalize() if b.vel.length_squared() > 0
                                 else pygame.Vector2(1, 0))
                        if pvp_out is not None:
                            pvp_out.append((pid, b.damage, knock))
                        hits.append(HitEvent(pygame.Vector2(rp.render_pos),
                                             b.vel, False, "player"))
                        b.alive = False
                        break
            if not b.alive:
                continue
            # Zombie collision (all bullets hit zombies)
            for zombie in zombies:
                if zombie.alive and b.pos.distance_to(zombie.pos) < b.radius + zombie.radius:
                    was_alive = zombie.alive
                    zombie.take_hit(b.damage, b.vel)
                    hits.append(HitEvent(zombie.pos, b.vel,
                                         was_alive and not zombie.alive, "zombie"))
                    b.alive = False
                    break
            if not b.alive:
                continue
            # NPC bullets also hit player
            if b.owner == "npc" and player is not None:
                if b.pos.distance_to(player.pos) < b.radius + player.radius:
                    player.take_damage(b.damage)
                    hits.append(HitEvent(player.pos, b.vel, False, "player"))
                    b.alive = False
                    continue
            # Player bullets hit NPCs; NPC bullets do NOT hit other NPCs
            if b.owner == "player" and npcs:
                for npc in npcs:
                    if (npc.state != "dead" and
                            b.pos.distance_to(npc.pos) < b.radius + npc.radius):
                        was_dead = npc.state == "dead"
                        npc.take_hit(b.damage, from_player=True, from_bullet=True)
                        # Set flee direction away from bullet travel
                        if npc.state == "panic" and b.vel.length_squared() > 0:
                            npc._direction = -b.vel.normalize()
                        killed   = not was_dead and npc.state == "dead"
                        hits.append(HitEvent(npc.pos, b.vel, killed, "npc"))
                        b.alive = False
                        break

        self.bullets = [b for b in self.bullets if b.alive]

        # Grenades
        exploded: list[Grenade] = []
        alive_grenades = []
        for g in self.grenades:
            g.update(dt)
            if g.exploded:
                exploded.append(g)
            elif g.alive:
                alive_grenades.append(g)
        self.grenades = alive_grenades

        # Flames — ignite on contact (DoT handled in entity.update)
        for f in self.flames:
            if not f.alive:
                continue
            f.update(dt)
            if not f.alive:
                continue
            for zombie in zombies:
                if zombie.alive and id(zombie) not in f._hit:
                    if f.pos.distance_to(zombie.pos) < f.radius + zombie.radius:
                        zombie.ignite(dps=f.damage * 3.5, duration=3.5)
                        f._hit.add(id(zombie))
            if npcs and f.owner == "player":
                for npc in npcs:
                    if npc.state != "dead" and id(npc) not in f._hit:
                        if f.pos.distance_to(npc.pos) < f.radius + npc.radius:
                            npc.ignite(dps=f.damage * 3.5, duration=3.5)
                            hits.append(HitEvent(npc.pos, f.vel,
                                                 npc.state == "dead", "npc"))
                            f._hit.add(id(npc))
        self.flames = [f for f in self.flames if f.alive]

        return hits, exploded

    def draw(self, surface, ox=0, oy=0):
        for f in self.flames:
            f.draw(surface, ox, oy)
        for b in self.bullets:
            b.draw(surface, ox, oy)
        for g in self.grenades:
            g.draw(surface, ox, oy)
