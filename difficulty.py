"""
Survival Day difficulty scaling.
main.py sets current_day each frame; other modules read it.
"""
import lang

current_day: int = 1   # updated by main.py

# ── Zombie pools unlocked per day ─────────────────────────────────────────────
_POOLS: dict[int, list[str]] = {
    1: ["regular", "regular", "regular"],
    3: ["regular", "regular", "speed", "speed"],
    5: ["regular", "speed", "speed", "quad", "quad"],
    7: ["regular", "speed", "quad", "giant", "runner", "runner"],
}

def get_zombie_pool(day: int) -> list[str]:
    pool = _POOLS[1]
    for d in sorted(_POOLS):
        if day >= d:
            pool = _POOLS[d]
    return pool


# ── Stat multipliers ──────────────────────────────────────────────────────────

def hp_mult(day: int) -> float:
    """HP grows 10 % per day (Day 1 = ×1.0)."""
    return 1.0 + (day - 1) * 0.10

def speed_mult(day: int) -> float:
    """Speed grows 3 % per day, capped at ×1.5."""
    return min(1.5, 1.0 + (day - 1) * 0.03)

def max_wave_count(day: int) -> int:
    """Max zombies spawned per wave ring."""
    return min(6, 1 + (day - 1) // 2)

def screw_bonus(completed_day: int) -> int:
    """Bonus screws awarded when the player survives a day."""
    return 10 + completed_day * 2


# ── Danger level ──────────────────────────────────────────────────────────────
# (min_day, lang_key, RGB color)
_DANGER = [
    (7, "danger_catastrophe", (220,  50,  50)),
    (5, "danger_crisis",      (255, 130,  40)),
    (3, "danger_warning",     (220, 200,  50)),
    (1, "danger_safe",        ( 80, 200,  80)),
]

def get_danger(day: int) -> tuple[str, tuple]:
    for threshold, key, color in _DANGER:
        if day >= threshold:
            return key, color
    return _DANGER[-1][1], _DANGER[-1][2]


# ── Per-day event notifications ───────────────────────────────────────────────
_DAY_EVENTS: dict[int, str] = {
    3: "day_warn_speed",
    5: "day_warn_quad",
    7: "day_warn_giant",
}

def get_day_event(day: int) -> str | None:
    return _DAY_EVENTS.get(day)
