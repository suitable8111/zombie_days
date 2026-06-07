import pygame
import random


class Camera:
    LERP = 9.0   # follow speed (higher = snappier)

    def __init__(self, world_w: int, world_h: int, screen_w: int, screen_h: int):
        self.x        = 0.0
        self.y        = 0.0
        self.world_w  = world_w
        self.world_h  = world_h
        self.screen_w = screen_w
        self.screen_h = screen_h
        self._shake   = 0.0
        # frame-locked offset (computed once per frame in begin_frame)
        self._ox = 0
        self._oy = 0

    def update(self, target: pygame.Vector2, dt: float):
        tx = target.x - self.screen_w / 2
        ty = target.y - self.screen_h / 2
        t  = min(1.0, self.LERP * dt)
        self.x += (tx - self.x) * t
        self.y += (ty - self.y) * t
        if self.world_w > self.screen_w:
            self.x = max(0.0, min(self.world_w - self.screen_w, self.x))
        if self.world_h > self.screen_h:
            self.y = max(0.0, min(self.world_h - self.screen_h, self.y))
        self._shake = max(0.0, self._shake - dt * 20)

    def add_shake(self, amount: float):
        self._shake = min(20.0, self._shake + amount)

    def begin_frame(self):
        """Lock the shake offset for this frame — call once before any draw."""
        if self._shake > 0.5:
            self._ox = int(self.x + random.uniform(-self._shake, self._shake))
            self._oy = int(self.y + random.uniform(-self._shake, self._shake))
        else:
            self._ox = int(self.x)
            self._oy = int(self.y)

    def offset(self) -> tuple[int, int]:
        return (self._ox, self._oy)

    def to_screen(self, wx: float, wy: float) -> tuple[int, int]:
        return (int(wx) - self._ox, int(wy) - self._oy)

    def to_world(self, sx: float, sy: float) -> pygame.Vector2:
        return pygame.Vector2(sx + self.x, sy + self.y)

    def visible(self, pos: pygame.Vector2, margin: int = 60) -> bool:
        sx = pos.x - self._ox
        sy = pos.y - self._oy
        return (-margin < sx < self.screen_w + margin and
                -margin < sy < self.screen_h + margin)
