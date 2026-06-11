#!/bin/bash
# Zombie Days — 멀티플레이 서버 실행 스크립트 (리눅스/macOS)
# 가상환경 자동 생성 + 의존성 설치 + uvicorn 실행.
# systemd 가 Restart=always 로 크래시/재부팅 시 자동 재시작한다.
#
# 사용:
#   ./run_server.sh              # 기본 0.0.0.0:8000
#   PORT=8080 ./run_server.sh    # 포트 변경
set -e

cd "$(dirname "$0")"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# 1) 가상환경 준비
if [ ! -d ".venv" ]; then
  echo "→ 가상환경 생성..."
  python3 -m venv .venv
fi

# 2) 의존성 보장 (없을 때만 설치)
if ! ./.venv/bin/python -c "import socketio, fastapi, uvicorn" 2>/dev/null; then
  echo "→ 서버 의존성 설치..."
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements-server.txt
fi

# 3) 실행 (exec → systemd 가 프로세스를 직접 관리)
echo "→ 서버 시작: http://${HOST}:${PORT}"
exec ./.venv/bin/uvicorn server:app --host "$HOST" --port "$PORT"
