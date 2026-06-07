#!/bin/bash
# Zombie Days — itch.io 웹 빌드 스크립트 (uv 사용)
set -e

echo "=== Zombie Days Web Build ==="
GAME_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$HOME/.venv-zombeedoor-web"

# 빌드 전 정리
echo "→ 이전 빌드 정리..."
rm -rf "$GAME_DIR/build"  # 전체 빌드 디렉토리 제거
rm -f "$GAME_DIR/assets/font.ttf"
rm -f "$GAME_DIR/assets/fonts/DungGeunMo.ttf.bak"
rm -f "$GAME_DIR/zombiedays-itch.zip"

# Python 3.11 가상환경 생성 (게임 폴더 밖에 생성)
if [ ! -d "$VENV_DIR" ]; then
  echo "→ Python 3.11 가상환경 생성 중..."
  uv venv "$VENV_DIR" --python 3.11
fi

# 패키지 설치
echo "→ pygbag / pygame-ce 설치 중..."
uv pip install --python "$VENV_DIR/bin/python" pygbag pygame-ce

# 빌드
echo "→ 빌드 시작..."
cd "$GAME_DIR"
"$VENV_DIR/bin/python" -m pygbag --build main.py

# zip 생성
echo "→ zip 패키징..."
rm -f zombiedays-itch.zip
cd build/web
zip -r "$GAME_DIR/zombiedays-itch.zip" . -x "*.DS_Store"
cd "$GAME_DIR"

echo ""
echo "✓ 완료: $GAME_DIR/zombiedays-itch.zip"
echo ""
echo "itch.io 업로드 체크리스트:"
echo "  1. New Project → Kind: HTML"
echo "  2. zombiedays-itch.zip 업로드"
echo "  3. Embed options → 'SharedArrayBuffer' 체크 (필수!)"
echo "  4. Viewport: 1024 × 768"
