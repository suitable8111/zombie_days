"""
Zombie Days — itch.io 커버 이미지 생성기
실행: python3 make_cover.py  →  cover.png (630×500)
"""
import pygame
import math
import random
import os

W, H = 630, 500
OUT  = os.path.join(os.path.dirname(__file__), "cover.png")

KO_FONT = os.path.join(os.path.dirname(__file__), "assets", "fonts", "DungGeunMo.ttf")
EN_FONT = os.path.join(os.path.dirname(__file__), "assets", "fonts", "PressStart2P-Regular.ttf")

pygame.init()
surf = pygame.Surface((W, H))

rng = random.Random(42)

# ── 배경 ──────────────────────────────────────────────────────────────────────
surf.fill((8, 10, 7))

# 격자
for gx in range(0, W, 48):
    pygame.draw.line(surf, (18, 22, 15), (gx, 0), (gx, H), 1)
for gy in range(0, H, 48):
    pygame.draw.line(surf, (18, 22, 15), (0, gy), (W, gy), 1)

# 핏빛 달
moon_s = pygame.Surface((160, 160), pygame.SRCALPHA)
pygame.draw.circle(moon_s, (140, 20, 10, 60), (80, 80), 80)
pygame.draw.circle(moon_s, (180, 30, 15, 40), (80, 80), 65)
surf.blit(moon_s, (W - 180, -30))

# 도시 실루엣
buildings = [
    (0,   H-160, 80,  160),
    (70,  H-220, 60,  220),
    (120, H-140, 90,  140),
    (200, H-200, 50,  200),
    (240, H-170, 70,  170),
    (300, H-240, 55,  240),
    (345, H-180, 80,  180),
    (410, H-210, 60,  210),
    (460, H-150, 85,  150),
    (530, H-190, 60,  190),
    (575, H-160, 55,  160),
]
for bx, by, bw, bh in buildings:
    col = (20, 24, 18)
    pygame.draw.rect(surf, col, (bx, by, bw, bh))
    # 창문
    for wy in range(by + 15, by + bh - 10, 22):
        for wx in range(bx + 8, bx + bw - 8, 18):
            lit = rng.random() < 0.25
            wc  = (180, 160, 60, 200) if lit else (30, 32, 28)
            pygame.draw.rect(surf, wc, (wx, wy, 8, 10))

# 도로
pygame.draw.rect(surf, (28, 30, 24), (0, H-80, W, 80))
pygame.draw.rect(surf, (35, 38, 30), (0, H-82, W, 2))
for lx in range(0, W, 60):
    pygame.draw.rect(surf, (55, 58, 45), (lx, H-42, 36, 4))

# 좀비 실루엣들
def draw_zombie(sx, sy, scale=1.0, col=(35, 48, 28)):
    r = int(10 * scale)
    pygame.draw.circle(surf, col, (sx, sy - int(26*scale)), r)
    pygame.draw.rect(surf, col, (sx-int(7*scale), sy-int(16*scale),
                                  int(14*scale), int(18*scale)))
    # 팔 (뻗은)
    pygame.draw.line(surf, col,
                     (sx - int(7*scale), sy - int(12*scale)),
                     (sx - int(22*scale), sy - int(6*scale)), max(1, int(3*scale)))
    pygame.draw.line(surf, col,
                     (sx + int(7*scale), sy - int(12*scale)),
                     (sx + int(22*scale), sy - int(4*scale)), max(1, int(3*scale)))
    # 다리
    pygame.draw.line(surf, col,
                     (sx - int(4*scale), sy + int(2*scale)),
                     (sx - int(6*scale), sy + int(18*scale)), max(1, int(3*scale)))
    pygame.draw.line(surf, col,
                     (sx + int(4*scale), sy + int(2*scale)),
                     (sx + int(8*scale), sy + int(18*scale)), max(1, int(3*scale)))

zombie_positions = [
    (60,  H-82, 1.4, (45, 62, 35)),
    (130, H-80, 1.2, (38, 55, 28)),
    (200, H-84, 1.5, (50, 70, 38)),
    (310, H-81, 1.3, (42, 60, 32)),
    (430, H-83, 1.1, (35, 52, 26)),
    (520, H-82, 1.4, (48, 65, 36)),
    (590, H-80, 1.2, (40, 58, 30)),
]
for zx, zy, zs, zc in zombie_positions:
    draw_zombie(zx, zy, zs, zc)

# 연기 효과
for i in range(12):
    sx_ = rng.randint(0, W)
    sy_ = rng.randint(H//3, H-100)
    sr_ = rng.randint(15, 45)
    sa_ = rng.randint(12, 35)
    ss_ = pygame.Surface((sr_*2, sr_*2), pygame.SRCALPHA)
    pygame.draw.circle(ss_, (30, 28, 25, sa_), (sr_, sr_), sr_)
    surf.blit(ss_, (sx_-sr_, sy_-sr_))

# ── 타이틀 텍스트 ─────────────────────────────────────────────────────────────
# 영어 타이틀 (PressStart2P)
if os.path.isfile(EN_FONT):
    f_title = pygame.font.Font(EN_FONT, 38)
    f_sub   = pygame.font.Font(EN_FONT, 12)
else:
    f_title = pygame.font.SysFont(None, 72)
    f_sub   = pygame.font.SysFont(None, 24)

if os.path.isfile(KO_FONT):
    f_ko = pygame.font.Font(KO_FONT, 22)
else:
    f_ko = pygame.font.SysFont(None, 28)

# 타이틀 그림자
for ox, oy in [(-3,3),(3,3),(0,4),(-3,-1)]:
    ts = f_title.render("ZOMBIE DAYS", True, (80, 10, 5))
    surf.blit(ts, (W//2 - ts.get_width()//2 + ox, 60 + oy))

# 타이틀 메인
t1 = f_title.render("ZOMBIE", True, (220, 45, 20))
t2 = f_title.render("DAYS",   True, (255, 200, 40))
surf.blit(t1, (W//2 - t1.get_width()//2, 55))
surf.blit(t2, (W//2 - t2.get_width()//2, 55 + t1.get_height() + 6))

# 한글 부제
ko1 = f_ko.render("좀비로 가득찬 세상에서 살아남아라", True, (160, 200, 130))
surf.blit(ko1, (W//2 - ko1.get_width()//2, 182))

# 영어 부제
if os.path.isfile(EN_FONT):
    f_en_sub = pygame.font.Font(EN_FONT, 8)
else:
    f_en_sub = pygame.font.SysFont(None, 16)
en1 = f_en_sub.render("SURVIVE IN A WORLD OVERRUN BY ZOMBIES", True, (120, 160, 100))
surf.blit(en1, (W//2 - en1.get_width()//2, 208))

# 구분선
pygame.draw.line(surf, (100, 20, 10), (W//2-200, 226), (W//2+200, 226), 1)

# 특징 태그
tags = ["🔫 WEAPONS", "🚗 VEHICLES", "🏚 BUILDINGS", "🔥 FLAMETHROWER"]
if os.path.isfile(EN_FONT):
    f_tag = pygame.font.Font(EN_FONT, 7)
else:
    f_tag = pygame.font.SysFont(None, 14)

tag_colors = [(180,220,140), (140,200,220), (220,180,120), (220,100,40)]
tag_x = W//2 - 230
for i, (tag, tc) in enumerate(zip(tags, tag_colors)):
    tg = f_tag.render(tag, True, tc)
    surf.blit(tg, (tag_x + i*118, 242))

# 버전
if os.path.isfile(EN_FONT):
    f_ver = pygame.font.Font(EN_FONT, 7)
else:
    f_ver = pygame.font.SysFont(None, 14)
vt = f_ver.render("v1.0  |  BROWSER PLAYABLE", True, (80, 90, 70))
surf.blit(vt, (W//2 - vt.get_width()//2, H - 28))

# 붉은 비네트
vign = pygame.Surface((W, H), pygame.SRCALPHA)
for r_v in range(min(W,H)//2, 0, -3):
    a = max(0, int(120 * (1 - r_v / (min(W,H)//2))))
    pygame.draw.circle(vign, (60, 0, 0, a), (W//2, H//2), r_v, 3)
surf.blit(vign, (0, 0))

pygame.image.save(surf, OUT)
print(f"✓ 커버 이미지 저장: {OUT}  ({W}×{H})")
pygame.quit()
