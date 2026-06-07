"""
Shop system — item catalogs, purchase logic, and UI rendering.
Weapon shop also serves as the upgrade station.
"""
import pygame
import lang

# ── Catalog ───────────────────────────────────────────────────────────────────
# Each entry: (item_id, lang_key, cost_screws, category, value)
# category: "weapon" | "fuel" | "heal" | "ammo" | "upgrade_ranged" | "upgrade_melee"
# value: stat name for upgrades, heal amount for heal, fuel amount for fuel, else None

SHOP_CATALOG = {
    "weapon": [
        ("pistol",        "wp_pistol",        15,  "weapon", None),
        ("shotgun",       "wp_shotgun",        25,  "weapon", None),
        ("rifle",         "wp_rifle",          30,  "weapon", None),
        ("machinegun",    "wp_machinegun",     50,  "weapon", None),
        ("grenade",       "wp_grenade",        18,  "weapon", None),
        ("flamethrower",  "wp_flamethrower",  300,  "weapon", None),
    ],
    "hospital": [
        ("heal_pack",   "wp_heal_pack",   10, "heal",    50),
        ("ammo_refill", "shop_ammo_ref",   8, "ammo",   None),
    ],
    "hardware": [
        ("fuel_can",    "shop_fuel_can",  12, "fuel",   40.0),
        ("ammo_refill", "shop_ammo_ref",   8, "ammo",   None),
        ("heal_pack",   "wp_heal_pack",   10, "heal",    50),
    ],
    "mart": [
        ("heal_pack",   "wp_heal_pack",   8,  "heal",  50),
        ("ammo_refill", "shop_ammo_ref",  6,  "ammo",  None),
        ("fuel_can",    "shop_fuel_can",  10, "fuel",  40.0),
    ],
}

_TITLE_KEYS = {
    "weapon":   "shop_title_weapon",
    "hospital": "shop_title_hospital",
    "hardware": "shop_title_hardware",
    "mart":     "shop_title_mart",
    "gym":      "shop_title_gym",
}

# ── Gym upgrade definitions ───────────────────────────────────────────────────
GYM_MAX_LEVEL = 5
GYM_UPGRADES = [
    # (stat_key,         effect_per_level, cost_per_level list,       effect_lang_key)
    ("stamina_regen", 0.15, [8, 15, 25, 38, 55], "gym_effect_stamina"),
    ("speed",         15,   [8, 15, 25, 38, 55], "gym_effect_speed"),
    ("max_hp",        20,   [10, 18, 30, 45, 65], "gym_effect_hp"),
    ("fist_dmg",      3,    [8, 15, 25, 38, 55], "gym_effect_fist"),
]


# ── Upgrade helpers ───────────────────────────────────────────────────────────

def _get_upgrade_items(player):
    """Return dynamic upgrade catalog entries for the weapon shop."""
    from melee import MeleeWeapon, MELEE_MAX_LEVEL, MELEE_UPGRADE_COST
    from items import UPGRADE_COST, MAX_LEVEL
    w = player.weapon
    if w is None or not w.upgradeable:
        return []
    if isinstance(w, MeleeWeapon):
        return [("upgrade_melee", f"upg_{w._upg_stat}",
                 MELEE_UPGRADE_COST, "upgrade_melee", None)]
    elif w.kind == "flamethrower":
        return [
            ("upgrade_fuel",   "upg_fuel",   UPGRADE_COST["fuel"],
             "upgrade_ranged", "fuel"),
            ("upgrade_damage", "upg_damage", UPGRADE_COST["damage"],
             "upgrade_ranged", "damage"),
        ]
    else:
        return [
            ("upgrade_fire_rate",    "upg_fire_rate", UPGRADE_COST["fire_rate"],
             "upgrade_ranged", "fire_rate"),
            ("upgrade_damage",       "upg_damage",    UPGRADE_COST["damage"],
             "upgrade_ranged", "damage"),
            ("upgrade_bullet_speed", "upg_proj_spd",  UPGRADE_COST["bullet_speed"],
             "upgrade_ranged", "bullet_speed"),
        ]


def _is_upgrade_maxed(player, category, value):
    """Return True if the upgrade for the current weapon is already maxed."""
    from melee import MeleeWeapon, MELEE_MAX_LEVEL
    from items import MAX_LEVEL
    w = player.weapon
    if w is None:
        return True
    if category == "upgrade_melee":
        return not isinstance(w, MeleeWeapon) or w.level >= MELEE_MAX_LEVEL
    return not hasattr(w, 'levels') or w.levels.get(value, 0) >= MAX_LEVEL


# ── Purchase logic ────────────────────────────────────────────────────────────

def _give_weapon(player, kind: str):
    from items import Weapon, WEAPON_SLOT_MAP
    w        = Weapon(kind)
    slot_idx = WEAPON_SLOT_MAP.get(kind, 0)
    slot     = player.weapon_slots[slot_idx]
    for i, existing in enumerate(slot):
        if existing.kind == kind:
            existing.reserves = min(existing.reserves + existing.mag_size * 2,
                                    existing.mag_size * 6)
            return
    slot.append(w)


def try_gym_purchase(player, stat_index: int) -> str:
    """Purchase one level of a gym upgrade."""
    if stat_index < 0 or stat_index >= len(GYM_UPGRADES):
        return ""
    stat_key, effect, costs, _ = GYM_UPGRADES[stat_index]
    lv = player.gym_levels.get(stat_key, 0)
    if lv >= GYM_MAX_LEVEL:
        return lang.t("gym_maxed")
    cost = costs[lv]
    if player.screws < cost:
        return lang.t("shop_no_screws")
    player.screws -= cost
    player.gym_levels[stat_key] = lv + 1
    # Apply effect immediately
    if stat_key == "stamina_regen":
        player._gym_stamina_bonus += effect
    elif stat_key == "speed":
        player.speed += effect
    elif stat_key == "max_hp":
        player.max_hp += int(effect)
        player.hp = min(player.hp + int(effect), player.max_hp)
    elif stat_key == "fist_dmg":
        fist = player.weapon_slots[5][0] if player.weapon_slots[5] else None
        if fist is not None:
            fist.damage += effect
    return ""


def try_purchase(player, shop_type: str, item_index: int,
                 current_vehicle=None) -> str:
    if shop_type == "gym":
        return try_gym_purchase(player, item_index)

    catalog = list(SHOP_CATALOG.get(shop_type, []))
    if shop_type == "weapon":
        catalog = catalog + _get_upgrade_items(player)

    if item_index < 0 or item_index >= len(catalog):
        return ""
    item_id, lang_key, cost, category, value = catalog[item_index]

    # Pre-validate upgrade availability before deducting screws
    if category in ("upgrade_ranged", "upgrade_melee"):
        if _is_upgrade_maxed(player, category, value):
            return lang.t("upg_maxed")

    if player.screws < cost:
        return lang.t("shop_no_screws")

    player.screws -= cost

    if category == "weapon":
        _give_weapon(player, item_id)

    elif category == "heal":
        from items import Weapon, WEAPON_SLOT_MAP
        hp_slot = player.weapon_slots[4]
        for w in hp_slot:
            if w.kind == "heal_pack":
                w.reserves += 2
                return ""
        _give_weapon(player, "heal_pack")

    elif category == "ammo":
        w = player.weapon
        if w and w.kind not in ("heal_pack", "lantern"):
            w.reserves = min(w.reserves + w.mag_size * 3, w.mag_size * 8)
        else:
            for slot in player.weapon_slots[:4]:
                for gun in slot:
                    gun.reserves = min(gun.reserves + gun.mag_size * 3,
                                       gun.mag_size * 8)

    elif category == "fuel":
        amount = float(value) if value is not None else 40.0
        if current_vehicle is not None:
            current_vehicle.add_fuel(amount)
        else:
            return lang.t("shop_no_vehicle")

    elif category == "upgrade_ranged":
        from items import UPGRADE_INC, MAX_LEVEL
        w = player.weapon
        if w and hasattr(w, 'levels'):
            stat = value
            w.levels[stat] = w.levels.get(stat, 0) + 1
            if stat == "fire_rate":
                w.fire_rate    += UPGRADE_INC["fire_rate"]
            elif stat == "damage":
                w.damage       += UPGRADE_INC["damage"]
            elif stat == "bullet_speed":
                w.bullet_speed += UPGRADE_INC["bullet_speed"]

    elif category == "upgrade_melee":
        from melee import MeleeWeapon, MELEE_UPGRADE_INC
        w = player.weapon
        if isinstance(w, MeleeWeapon):
            w.level += 1
            inc = MELEE_UPGRADE_INC[w._upg_stat]
            if w._upg_stat == "damage":
                w.damage      += inc
            elif w._upg_stat == "attack_rate":
                w.attack_rate += inc
                w._swing_dur   = max(0.07, w._swing_dur * 0.86)
            elif w._upg_stat == "knockback":
                w.knockback   += inc

    return ""


# ── UI rendering ──────────────────────────────────────────────────────────────

def draw_gym_ui(surface, player, font_md, font_sm,
                selected: int = 0, feedback: str = "") -> int:
    """Dedicated gym upgrade screen."""
    W = surface.get_width()
    H = surface.get_height()
    overlay = pygame.Surface((W, H), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 155))
    surface.blit(overlay, (0, 0))

    PANEL_W = 460
    ROW_H   = 66
    HEAD_H  = 80
    FOOT_H  = 40
    n       = len(GYM_UPGRADES)
    PANEL_H = HEAD_H + n * ROW_H + FOOT_H
    px = (W - PANEL_W) // 2
    py = (H - PANEL_H) // 2

    panel = pygame.Surface((PANEL_W, PANEL_H), pygame.SRCALPHA)
    panel.fill((14, 22, 14, 235))
    surface.blit(panel, (px, py))
    pygame.draw.rect(surface, (60, 140, 60), (px, py, PANEL_W, PANEL_H), 2, border_radius=4)

    # Title + screws
    ts = font_md.render(lang.t("shop_title_gym"), True, (100, 220, 100))
    surface.blit(ts, (px + PANEL_W // 2 - ts.get_width() // 2, py + 10))
    ss = font_sm.render(lang.t("hud_screws", player.screws), True, (180, 180, 160))
    surface.blit(ss, (px + PANEL_W // 2 - ss.get_width() // 2, py + 40))

    cur_y = py + HEAD_H
    for i, (stat_key, effect, costs, eff_lang) in enumerate(GYM_UPGRADES):
        lv      = player.gym_levels.get(stat_key, 0)
        maxed   = lv >= GYM_MAX_LEVEL
        cost    = costs[lv] if not maxed else 0
        can_buy = (not maxed) and (player.screws >= cost)
        active  = (i == selected)

        if active:
            hl = pygame.Surface((PANEL_W - 8, ROW_H - 4), pygame.SRCALPHA)
            hl.fill((20, 45, 20, 210))
            surface.blit(hl, (px + 4, cur_y + 2))
            pygame.draw.rect(surface, (60, 140, 60),
                             (px + 4, cur_y + 2, PANEL_W - 8, ROW_H - 4), 1, border_radius=2)

        name_col = (210, 240, 210) if can_buy else (100, 200, 100) if maxed else (90, 110, 90)
        cost_col = (160, 220, 100) if can_buy else (80, 160, 80) if maxed else (120, 60, 60)

        # Left: [N] + name
        surface.blit(font_sm.render(f"[{i+1}]", True, (80, 160, 80)),
                     (px + 12, cur_y + 10))
        surface.blit(font_md.render(lang.t(f"gym_{stat_key}"), True, name_col),
                     (px + 44, cur_y + 8))

        # Level bar
        bar_x, bar_y, bar_w, bar_h = px + 44, cur_y + 32, 180, 7
        pygame.draw.rect(surface, (30, 50, 30), (bar_x, bar_y, bar_w, bar_h), border_radius=3)
        if lv > 0:
            filled_w = int(bar_w * lv / GYM_MAX_LEVEL)
            pygame.draw.rect(surface, (60, 200, 80),
                             (bar_x, bar_y, filled_w, bar_h), border_radius=3)
        lv_txt = lang.t("gym_lv", lv, GYM_MAX_LEVEL)
        surface.blit(font_sm.render(lv_txt, True, (120, 180, 120)),
                     (bar_x + bar_w + 8, bar_y - 2))

        # Right: effect description + cost
        total_effect = round(effect * lv, 2) if not isinstance(effect, int) else effect * lv
        eff_txt  = lang.t(eff_lang, f"+{round(effect, 2)}" if not isinstance(effect, int) else f"+{effect}")
        cost_str = lang.t("gym_maxed") if maxed else lang.t("upg_cost", cost)
        surface.blit(font_sm.render(eff_txt, True, (120, 200, 130)),
                     (px + PANEL_W - font_sm.size(eff_txt)[0] - 80, cur_y + 8))
        surface.blit(font_sm.render(cost_str, True, cost_col),
                     (px + PANEL_W - font_sm.size(cost_str)[0] - 14, cur_y + 8))

        cur_y += ROW_H

    # Feedback / hint
    if feedback:
        fb = font_sm.render(feedback, True, (220, 80, 60))
        surface.blit(fb, (px + PANEL_W // 2 - fb.get_width() // 2, cur_y + 8))
    else:
        hint_s = font_sm.render(lang.t("shop_hint"), True, (80, 120, 80))
        surface.blit(hint_s, (px + PANEL_W // 2 - hint_s.get_width() // 2, cur_y + 8))

    return n


def draw_shop_ui(surface, player, shop_type: str,
                 font_md, font_sm, selected: int = 0,
                 feedback: str = "") -> int:
    if shop_type == "gym":
        return draw_gym_ui(surface, player, font_md, font_sm, selected, feedback)

    base_catalog = list(SHOP_CATALOG.get(shop_type, []))
    upg_items    = _get_upgrade_items(player) if shop_type == "weapon" else []
    full_catalog = base_catalog + upg_items
    if not full_catalog:
        return 0

    W = surface.get_width()
    H = surface.get_height()

    overlay = pygame.Surface((W, H), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 155))
    surface.blit(overlay, (0, 0))

    PANEL_W  = 400
    ROW_H    = 50
    HEAD_H   = 80
    FOOT_H   = 40
    DIV_H    = 26   # divider row height
    n_rows   = len(base_catalog) + (DIV_H // ROW_H + 1 if upg_items else 0) + len(upg_items)
    PANEL_H  = HEAD_H + len(base_catalog) * ROW_H + (DIV_H if upg_items else 0) + len(upg_items) * ROW_H + FOOT_H
    px = (W - PANEL_W) // 2
    py = (H - PANEL_H) // 2

    panel = pygame.Surface((PANEL_W, PANEL_H), pygame.SRCALPHA)
    panel.fill((18, 16, 12, 230))
    surface.blit(panel, (px, py))
    pygame.draw.rect(surface, (110, 90, 40),
                     (px, py, PANEL_W, PANEL_H), 2, border_radius=4)

    # Title + screws
    title_str = lang.t(_TITLE_KEYS.get(shop_type, "shop_title_weapon"))
    ts = font_md.render(title_str, True, (255, 215, 80))
    surface.blit(ts, (px + PANEL_W // 2 - ts.get_width() // 2, py + 10))

    sc_str = lang.t("hud_screws", player.screws)
    ss = font_sm.render(sc_str, True, (180, 180, 160))
    surface.blit(ss, (px + PANEL_W // 2 - ss.get_width() // 2, py + 40))

    # Buy item rows
    cur_y = py + HEAD_H
    for i, (item_id, name_key, cost, cat, val) in enumerate(base_catalog):
        iy     = cur_y
        active = (i == selected)
        can_buy = (player.screws >= cost)

        if active:
            hl = pygame.Surface((PANEL_W - 8, ROW_H - 4), pygame.SRCALPHA)
            hl.fill((40, 35, 18, 200))
            surface.blit(hl, (px + 4, iy + 2))
            pygame.draw.rect(surface, (130, 110, 48),
                             (px + 4, iy + 2, PANEL_W - 8, ROW_H - 4), 1, border_radius=2)

        num_col  = (155, 145, 105) if can_buy else (70, 70, 60)
        name_col = (230, 220, 180) if can_buy else (100, 100, 88)
        cost_col = (200, 200, 90)  if can_buy else (160, 60, 60)

        surface.blit(font_sm.render(f"[{i+1}]",         True, num_col),
                     (px + 12, iy + ROW_H // 2 - font_sm.get_height() // 2))
        surface.blit(font_md.render(lang.t(name_key),   True, name_col),
                     (px + 42, iy + ROW_H // 2 - font_md.get_height() // 2))
        surface.blit(font_sm.render(lang.t("upg_cost", cost), True, cost_col),
                     (px + PANEL_W - font_sm.size(lang.t("upg_cost", cost))[0] - 14,
                      iy + ROW_H // 2 - font_sm.get_height() // 2))
        cur_y += ROW_H

    # Upgrade section divider + rows (weapon shop only)
    if upg_items:
        # Divider
        pygame.draw.line(surface, (80, 70, 40),
                         (px + 10, cur_y + DIV_H // 2),
                         (px + PANEL_W - 10, cur_y + DIV_H // 2), 1)
        div_lbl = font_sm.render(lang.t("shop_upg_section"), True, (140, 120, 60))
        surface.blit(div_lbl, (px + PANEL_W // 2 - div_lbl.get_width() // 2,
                               cur_y + DIV_H // 2 - div_lbl.get_height() // 2))
        cur_y += DIV_H

        # Show current weapon name above upgrade items
        w = player.weapon
        if w:
            wn = font_sm.render(f"[ {w.name} ]", True, (200, 170, 80))
            surface.blit(wn, (px + 12, cur_y - DIV_H // 2 + 2))

        for j, (item_id, name_key, cost, cat, val) in enumerate(upg_items):
            gi     = len(base_catalog) + j   # global index
            iy     = cur_y
            active = (gi == selected)
            maxed  = _is_upgrade_maxed(player, cat, val)
            can_buy = (player.screws >= cost) and not maxed

            if active:
                hl = pygame.Surface((PANEL_W - 8, ROW_H - 4), pygame.SRCALPHA)
                hl.fill((30, 25, 45, 200))
                surface.blit(hl, (px + 4, iy + 2))
                pygame.draw.rect(surface, (90, 80, 140),
                                 (px + 4, iy + 2, PANEL_W - 8, ROW_H - 4), 1, border_radius=2)

            num_col  = (130, 120, 180) if can_buy else (70, 70, 60)
            name_col = (200, 185, 240) if (can_buy and not maxed) else \
                       (100, 200, 100) if maxed else (100, 90, 120)
            cost_col = (160, 150, 220) if can_buy else \
                       (80, 160, 80)   if maxed   else (100, 60, 60)

            key_lbl = lang.t("upg_maxed") if maxed else f"[{gi+1}]"
            cost_str = lang.t("upg_maxed") if maxed else lang.t("upg_cost", cost)

            surface.blit(font_sm.render(key_lbl,           True, num_col),
                         (px + 12, iy + ROW_H // 2 - font_sm.get_height() // 2))
            surface.blit(font_md.render(lang.t(name_key),  True, name_col),
                         (px + 52, iy + ROW_H // 2 - font_md.get_height() // 2))
            surface.blit(font_sm.render(cost_str,          True, cost_col),
                         (px + PANEL_W - font_sm.size(cost_str)[0] - 14,
                          iy + ROW_H // 2 - font_sm.get_height() // 2))
            cur_y += ROW_H

    # Feedback / hint
    if feedback:
        fb = font_sm.render(feedback, True, (220, 80, 60))
        surface.blit(fb, (px + PANEL_W // 2 - fb.get_width() // 2, cur_y + 8))
    else:
        hint_s = font_sm.render(lang.t("shop_hint"), True, (100, 100, 88))
        surface.blit(hint_s, (px + PANEL_W // 2 - hint_s.get_width() // 2,
                               cur_y + 8))

    return len(full_catalog)
