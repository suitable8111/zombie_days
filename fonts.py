import os
import pygame

_BASE     = os.path.dirname(os.path.abspath(__file__))
_KO_PATH  = os.path.join(_BASE, "assets", "fonts", "DungGeunMo.ttf")
_EN_PATH  = os.path.join(_BASE, "assets", "fonts", "PressStart2P-Regular.ttf")
_FB_PATH  = os.path.join(_BASE, "assets", "font.ttf")   # legacy fallback

# PressStart2P renders wider than normal fonts at the same size parameter.
# This scale factor compensates so layouts don't overflow.
_EN_SCALE = 0.62

_cache: dict = {}   # (size, lang_code) → Font


def get(size: int) -> pygame.font.Font:
    """Return the correct font for the current language at the requested size."""
    import lang as _lang
    code = _lang.current()   # "ko" or "en"
    key  = (size, code)
    if key not in _cache:
        if code == "ko" and os.path.isfile(_KO_PATH):
            _cache[key] = pygame.font.Font(_KO_PATH, size)
        elif code == "en" and os.path.isfile(_EN_PATH):
            scaled = max(6, int(size * _EN_SCALE))
            _cache[key] = pygame.font.Font(_EN_PATH, scaled)
        else:
            path = _FB_PATH if os.path.isfile(_FB_PATH) else None
            _cache[key] = (pygame.font.Font(path, size) if path
                           else pygame.font.SysFont(None, size))
    return _cache[key]


def clear_cache() -> None:
    """Call after a language switch to drop stale entries."""
    _cache.clear()
