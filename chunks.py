"""
Dynamic chunk streaming for ZombeeDoor.
The world is divided into CHUNK_SIZE × CHUNK_SIZE tiles.
Only the 5×5 grid of chunks around the player is kept active;
entities beyond DESPAWN_RADIUS are serialised back to their chunk.
"""
import random
import pygame
import difficulty

TOWN_NAMES = [
    "새벽", "청솔", "한강", "광명", "금산",
    "별빛", "동산", "하늘", "무지개", "서광",
    "미래", "태평", "백합", "은하", "낙원",
    "자유", "평화", "해솔", "이슬", "달빛",
]

# ── World & chunk constants ───────────────────────────────────────────────────
CHUNK_SIZE     = 2048          # px per chunk side
WORLD_W        = 50_000        # total world width  (px)
WORLD_H        = 50_000        # total world height (px)
PLAYER_START_X = WORLD_W // 2
PLAYER_START_Y = WORLD_H // 2

ACTIVE_RANGE   = 2             # chunks each side → 5×5 = 25 active chunks
ACTIVE_RADIUS  = 1500.0        # entity logic runs only within this distance
DESPAWN_RADIUS = 1900.0        # entities farther than this are serialised

NPC_PER_CHUNK    = (5, 12)
ZOMBIE_PER_CHUNK = (2,  6)
ZOMBIE_KINDS     = ["regular", "regular", "speed", "giant", "runner", "runner"]

TOWN_CHUNK_CHANCE     = 0.18   # probability a chunk is a town vs wilderness
MILITARY_CHUNK_CHANCE = 0.07   # probability a non-town chunk is a military base
VEHICLES_PER_TOWN     = (1, 3) # how many cars to spawn in a town chunk

_TOWN_VEH_POOL = ["car", "car", "car", "motorcycle", "motorcycle"]
_MIL_VEH_KINDS = ["tank", "helicopter", "airplane"]   # one of each per base


# ── Ghost records (serialised entity state, no pygame objects) ────────────────

_VEH_KIND_POOL = ["car", "car", "car", "motorcycle", "motorcycle",
                  "tank", "helicopter", "airplane"]

class GhostVehicle:
    __slots__ = ('x', 'y', 'hp', 'fuel', 'kind')

    def __init__(self, x, y, hp=None, fuel=None, kind="car"):
        from vehicle import VEH_MAX_HP, VEH_MAX_FUEL
        self.x    = x
        self.y    = y
        self.kind = kind
        self.hp   = hp   if hp   is not None else VEH_MAX_HP
        self.fuel = fuel if fuel is not None else VEH_MAX_FUEL * 0.60


class GhostNPC:
    __slots__ = ('x', 'y', 'hp', 'state', 'infection_timer',
                 'zombie_on_death', 'armed', 'is_sheriff',
                 'is_shopkeeper', 'shopkeeper_type')

    def __init__(self, x, y, hp, state='alive', infection_timer=0.0,
                 zombie_on_death=False, armed=False, is_sheriff=False,
                 is_shopkeeper=False, shopkeeper_type=None):
        self.x = x;  self.y = y;  self.hp = hp
        self.state            = state
        self.infection_timer  = infection_timer
        self.zombie_on_death  = zombie_on_death
        self.armed            = armed
        self.is_sheriff       = is_sheriff
        self.is_shopkeeper    = is_shopkeeper
        self.shopkeeper_type  = shopkeeper_type


class GhostZombie:
    __slots__ = ('x', 'y', 'kind', 'hp')

    def __init__(self, x, y, kind='regular', hp=None):
        from entities import ZOMBIE_TYPES
        self.x    = x;  self.y = y;  self.kind = kind
        self.hp   = hp if hp is not None else ZOMBIE_TYPES[kind]['hp']


# ── Chunk ─────────────────────────────────────────────────────────────────────

class Chunk:
    def __init__(self, cx: int, cy: int):
        self.cx   = cx
        self.cy   = cy
        self.seed = (cx * 73856093 ^ cy * 19349663) & 0x7FFFFFFF
        self._generated    = False
        self.town_name: str | None = None
        self._items_placed = False
        self.is_town       = False
        self.is_core_town  = False
        self.is_military   = False
        self.zones:           list = []
        self.ghost_npcs:      list[GhostNPC]     = []
        self.ghost_zombies:   list[GhostZombie]  = []
        self.ghost_vehicles:  list[GhostVehicle] = []
        self._item_spawns:    list[tuple]         = []

    @property
    def world_x(self) -> int:
        return self.cx * CHUNK_SIZE

    @property
    def world_y(self) -> int:
        return self.cy * CHUNK_SIZE

    # ── Generation ────────────────────────────────────────────────────────

    def generate(self):
        from map import gen_chunk_zones, gen_town_zones, MilitaryBaseZone
        from entities import NPC_HP, ZOMBIE_TYPES
        from items import WEAPON_CONFIGS

        rng = random.Random(self.seed)
        wx, wy = self.world_x, self.world_y

        self.is_town      = (rng.random() < TOWN_CHUNK_CHANCE)
        self.town_name    = rng.choice(TOWN_NAMES) if self.is_town else None
        self.is_core_town = self.is_town and (self.seed % 5 == 0)

        # Military base — only on non-town chunks
        if not self.is_town:
            self.is_military = (rng.random() < MILITARY_CHUNK_CHANCE)

        if self.is_town:
            self.zones = gen_town_zones(wx, wy, CHUNK_SIZE, CHUNK_SIZE, rng,
                                        is_core_town=self.is_core_town)
        else:
            raw = gen_chunk_zones(wx, wy, CHUNK_SIZE, CHUNK_SIZE, rng)
            if self.is_military:
                base_w = rng.randint(480, 660)
                base_h = rng.randint(400, 540)
                bx = wx + rng.randint(120, max(121, CHUNK_SIZE - base_w - 120))
                by = wy + rng.randint(120, max(121, CHUNK_SIZE - base_h - 120))
                mil_zone = MilitaryBaseZone(bx, by, base_w, base_h, rng)
                # Insert military base after ground/road zones, before bushes
                ground = [z for z in raw if z.zone_type in ('beach', 'lake', 'road')]
                upper  = [z for z in raw if z.zone_type not in ('beach', 'lake', 'road')]
                self.zones = ground + [mil_zone] + upper
                self._mil_rect = mil_zone.rect  # cached for vehicle placement
            else:
                self.zones = raw
                self._mil_rect = None

        # NPC ghosts
        if self.is_military:
            # Armed soldiers patrolling inside the base
            mr = self._mil_rect
            for _ in range(rng.randint(6, 10)):
                x = mr.x + rng.uniform(40, mr.w - 40)
                y = mr.y + rng.uniform(40, mr.h - 40)
                self.ghost_npcs.append(GhostNPC(x, y, NPC_HP, armed=True))
            # A few civilians outside
            for _ in range(rng.randint(1, 3)):
                x = wx + rng.uniform(80, CHUNK_SIZE - 80)
                y = wy + rng.uniform(80, CHUNK_SIZE - 80)
                if not mr.collidepoint(x, y):
                    self.ghost_npcs.append(GhostNPC(x, y, NPC_HP, armed=False))
        elif self.is_town:
            npc_count = rng.randint(8, 16)
            for _ in range(npc_count):
                x = wx + rng.uniform(80, CHUNK_SIZE - 80)
                y = wy + rng.uniform(80, CHUNK_SIZE - 80)
                self.ghost_npcs.append(
                    GhostNPC(x, y, NPC_HP, armed=rng.random() < 0.05))
            # 2-3 Sheriffs per town
            from entities import SHERIFF_HP
            for _ in range(rng.randint(2, 3)):
                x = wx + rng.uniform(100, CHUNK_SIZE - 100)
                y = wy + rng.uniform(100, CHUNK_SIZE - 100)
                self.ghost_npcs.append(
                    GhostNPC(x, y, SHERIFF_HP, armed=True, is_sheriff=True))
            # Shopkeepers inside each shop building
            for zone in self.zones:
                stype = getattr(zone, 'shop_type', None)
                sp    = getattr(zone, 'shopkeeper_pos', None)
                if stype and sp is not None:
                    self.ghost_npcs.append(
                        GhostNPC(sp.x, sp.y, 9999,
                                 is_shopkeeper=True, shopkeeper_type=stype))
        else:
            npc_count = rng.randint(*NPC_PER_CHUNK)
            for _ in range(npc_count):
                x = wx + rng.uniform(80, CHUNK_SIZE - 80)
                y = wy + rng.uniform(80, CHUNK_SIZE - 80)
                self.ghost_npcs.append(
                    GhostNPC(x, y, NPC_HP, armed=rng.random() < 0.05))

        # Zombie ghosts
        if self.is_military:
            # Zombies only outside the perimeter
            mr = self._mil_rect
            for _ in range(rng.randint(2, 5)):
                for _a in range(12):
                    x = wx + rng.uniform(80, CHUNK_SIZE - 80)
                    y = wy + rng.uniform(80, CHUNK_SIZE - 80)
                    if not mr.collidepoint(x, y):
                        break
                kind = rng.choice(difficulty.get_zombie_pool(difficulty.current_day))
                self.ghost_zombies.append(GhostZombie(x, y, kind))
        else:
            zmb_count = rng.randint(1, 3) if self.is_town else rng.randint(*ZOMBIE_PER_CHUNK)
            for _ in range(zmb_count):
                x    = wx + rng.uniform(80, CHUNK_SIZE - 80)
                y    = wy + rng.uniform(80, CHUNK_SIZE - 80)
                kind = rng.choice(difficulty.get_zombie_pool(difficulty.current_day))
                self.ghost_zombies.append(GhostZombie(x, y, kind))

        # Vehicle ghosts
        if self.is_military:
            # Tank + helicopter + airplane inside the base
            mr = self._mil_rect
            for kind in _MIL_VEH_KINDS:
                vx = mr.x + rng.uniform(60, mr.w - 60)
                vy = mr.y + rng.uniform(60, mr.h - 60)
                self.ghost_vehicles.append(GhostVehicle(vx, vy, kind=kind))
        elif self.is_town:
            # Cars and motorcycles parked on roadsides
            road_zones = [z for z in self.zones if z.zone_type == 'road']
            n_veh = rng.randint(*VEHICLES_PER_TOWN)
            for _ in range(n_veh):
                kind = rng.choice(_TOWN_VEH_POOL)
                if road_zones:
                    road = rng.choice(road_zones)
                    r    = road.rect
                    if r.w > r.h:   # horizontal road — park above or below
                        vx = float(r.x + rng.uniform(20, max(21.0, r.w - 20.0)))
                        vy = float(r.top - 30) if rng.random() < 0.5 else float(r.bottom + 30)
                    else:           # vertical road — park left or right
                        vy = float(r.y + rng.uniform(20, max(21.0, r.h - 20.0)))
                        vx = float(r.left - 30) if rng.random() < 0.5 else float(r.right + 30)
                else:
                    vx = wx + rng.uniform(100, CHUNK_SIZE - 100)
                    vy = wy + rng.uniform(100, CHUNK_SIZE - 100)
                vx = max(float(wx + 40), min(float(wx + CHUNK_SIZE - 40), vx))
                vy = max(float(wy + 40), min(float(wy + CHUNK_SIZE - 40), vy))
                self.ghost_vehicles.append(GhostVehicle(vx, vy, kind=kind))

        # Item spawns for loot zones (plain hideouts only, not shops)
        mg = 22
        _normal_pool = [k for k in WEAPON_CONFIGS.keys() if k != "flamethrower"]
        for zone in (z for z in self.zones if z.is_loot_zone):
            r  = zone.rect
            lo_x, hi_x = r.x + mg, max(r.x + mg + 1, r.x + r.w - mg)
            lo_y, hi_y = r.y + mg, max(r.y + mg + 1, r.y + r.h - mg)
            # Flamethrower: 0.01% chance, Day 30+
            if (difficulty.current_day >= 30
                    and rng.random() < 0.0001):
                kind = "flamethrower"
            else:
                kind = rng.choice(_normal_pool)
            self._item_spawns.append(
                ('weapon', kind, rng.randint(lo_x, hi_x), rng.randint(lo_y, hi_y)))
            for _ in range(rng.randint(1, 2)):
                self._item_spawns.append(
                    ('screw', rng.randint(1, 3),
                     rng.randint(lo_x, hi_x), rng.randint(lo_y, hi_y)))

        self._generated = True

    def create_items(self) -> list:
        """Materialise item objects from the deterministic spawn list (once only)."""
        from items import WeaponDrop, ScrewDrop
        items = []
        for s in self._item_spawns:
            if s[0] == 'weapon':
                items.append(WeaponDrop(s[1], s[2], s[3]))
            else:
                items.append(ScrewDrop(s[2], s[3], count=s[1]))
        self._items_placed = True
        return items


# ── ChunkManager ──────────────────────────────────────────────────────────────

class ChunkManager:
    def __init__(self):
        self._cache:        dict[tuple[int, int], Chunk] = {}
        self._active_keys:  set[tuple[int, int]]         = set()
        # Keys whose ghosts have already been released into the live world
        self._spawned_keys: set[tuple[int, int]]         = set()

    # ── Internal helpers ──────────────────────────────────────────────────

    def _coord(self, pos) -> tuple[int, int]:
        return (int(pos.x) // CHUNK_SIZE, int(pos.y) // CHUNK_SIZE)

    def _active_coords(self, pos) -> list[tuple[int, int]]:
        pcx, pcy = self._coord(pos)
        r = ACTIVE_RANGE
        return [(pcx + dx, pcy + dy)
                for dx in range(-r, r + 1)
                for dy in range(-r, r + 1)]

    def _get_or_create(self, cx: int, cy: int) -> Chunk:
        key = (cx, cy)
        if key not in self._cache:
            self._cache[key] = Chunk(cx, cy)
        return self._cache[key]

    # ── Public API ────────────────────────────────────────────────────────

    def find_safe_start(self) -> tuple[float, float]:
        """Generate the start chunk and return an open spawn position."""
        cx = PLAYER_START_X // CHUNK_SIZE
        cy = PLAYER_START_Y // CHUNK_SIZE
        chunk = self._get_or_create(cx, cy)
        if not chunk._generated:
            chunk.generate()
        rng = random.Random(chunk.seed ^ 0xDEAD)
        for _ in range(30):
            x = chunk.world_x + rng.randint(200, CHUNK_SIZE - 200)
            y = chunk.world_y + rng.randint(200, CHUNK_SIZE - 200)
            pos = pygame.Vector2(x, y)
            if not any(z.zone_type in ('lake', 'hideout') and z.contains(pos)
                       for z in chunk.zones):
                return float(x), float(y)
        return float(PLAYER_START_X), float(PLAYER_START_Y)

    def update(self, player_pos):
        """
        Call once per frame.
        Returns (active_zones, new_gnpcs, new_gzombies, new_items, new_gvehicles).
        """
        new_keys = set(self._active_coords(player_pos))
        self._active_keys = new_keys

        zones         = []
        new_gnpcs     = []
        new_gzombies  = []
        new_items     = []
        new_gvehicles = []

        for key in new_keys:
            cx, cy = key
            chunk  = self._get_or_create(cx, cy)
            if not chunk._generated:
                chunk.generate()
            zones.extend(chunk.zones)

            if key not in self._spawned_keys:
                self._spawned_keys.add(key)
                new_gnpcs.extend(chunk.ghost_npcs)
                chunk.ghost_npcs.clear()
                new_gzombies.extend(chunk.ghost_zombies)
                chunk.ghost_zombies.clear()
                new_gvehicles.extend(chunk.ghost_vehicles)
                chunk.ghost_vehicles.clear()
                if not chunk._items_placed:
                    new_items.extend(chunk.create_items())

        return zones, new_gnpcs, new_gzombies, new_items, new_gvehicles

    def serialize_npc(self, npc) -> None:
        from entities import Sheriff, ShopkeeperNPC
        key = (int(npc.pos.x) // CHUNK_SIZE, int(npc.pos.y) // CHUNK_SIZE)
        chunk = self._get_or_create(*key)
        chunk.ghost_npcs.append(GhostNPC(
            npc.pos.x, npc.pos.y, npc.hp, npc.state,
            npc.infection_timer, npc._zombie_on_death, npc.armed,
            is_sheriff=isinstance(npc, Sheriff),
            is_shopkeeper=isinstance(npc, ShopkeeperNPC),
            shopkeeper_type=getattr(npc, 'shop_type', None),
        ))
        self._spawned_keys.discard(key)

    def serialize_zombie(self, zombie) -> None:
        key = (int(zombie.pos.x) // CHUNK_SIZE, int(zombie.pos.y) // CHUNK_SIZE)
        chunk = self._get_or_create(*key)
        chunk.ghost_zombies.append(
            GhostZombie(zombie.pos.x, zombie.pos.y, zombie.kind, zombie.hp))
        self._spawned_keys.discard(key)

    def serialize_vehicle(self, vehicle) -> None:
        key = (int(vehicle.pos.x) // CHUNK_SIZE, int(vehicle.pos.y) // CHUNK_SIZE)
        chunk = self._get_or_create(*key)
        chunk.ghost_vehicles.append(
            GhostVehicle(vehicle.pos.x, vehicle.pos.y,
                         vehicle.hp, vehicle.fuel,
                         kind=getattr(vehicle, '_kind', 'car')))
        self._spawned_keys.discard(key)

    def get_town_name(self, pos) -> str | None:
        """Return the town name for the chunk at pos, or None."""
        key   = self._coord(pos)
        chunk = self._cache.get(key)
        if chunk and chunk._generated and chunk.is_town:
            return chunk.town_name
        return None

    @property
    def active_count(self) -> int:
        return len(self._active_keys)

    @property
    def loaded_count(self) -> int:
        return len(self._cache)
