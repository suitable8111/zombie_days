"""
DungGeunMo.ttf 서브셋 생성 — 게임에서 실제 사용하는 글자만 추출.
실행: python3 subset_font.py

fonttools 필요:
  pip install fonttools brotli
"""
import os, sys, subprocess

BASE   = os.path.dirname(os.path.abspath(__file__))
SRC    = os.path.join(BASE, "assets", "fonts", "DungGeunMo.ttf")
DST    = os.path.join(BASE, "assets", "fonts", "DungGeunMo.ttf")  # 덮어쓰기
BACKUP = SRC + ".bak"

# ── 1. lang.py + menu.py 에서 사용되는 모든 문자 수집 ──────────────────────
scan_files = [
    "lang.py", "menu.py", "main.py", "shop.py", "network.py",
]
chars = set()
for fname in scan_files:
    path = os.path.join(BASE, fname)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            chars.update(f.read())

# 기본 ASCII + 한글 자음/모음 단독 포함
extras = (
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
    "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"
    "ㅏㅑㅓㅕㅗㅛㅜㅠㅡㅣ"
)
chars.update(extras)
text = "".join(sorted(chars))

print(f"사용 글자 수: {len(text)}")

# ── 2. 원본 백업 ────────────────────────────────────────────────────────────
if not os.path.isfile(BACKUP):
    import shutil
    shutil.copy2(SRC, BACKUP)
    print(f"백업: {BACKUP}")

# ── 3. fonttools subset 실행 ────────────────────────────────────────────────
try:
    from fontTools import subset as ft_subset  # noqa
except ImportError:
    print("fonttools 없음 → 설치 중...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "fonttools", "brotli"])

tmp = DST + ".tmp.ttf"
from fontTools import subset as ft_subset

opts = ft_subset.Options()
opts.flavor = None
font = ft_subset.load_font(SRC if os.path.isfile(BACKUP) else BACKUP, opts)

subsetter = ft_subset.Subsetter(options=opts)
subsetter.populate(text=text)
subsetter.subset(font)
ft_subset.save_font(font, tmp, opts)
font.close()

os.replace(tmp, DST)

before = os.path.getsize(BACKUP)
after  = os.path.getsize(DST)
print(f"\n✓ 완료!")
print(f"  원본: {before/1024/1024:.1f} MB")
print(f"  서브셋: {after/1024:.0f} KB  ({after/before*100:.1f}%)")
