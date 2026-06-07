"""
로컬에서 빌드된 웹 게임을 테스트할 때 사용.
SharedArrayBuffer 필수 헤더를 포함한 HTTP 서버.

사용법:
  python3 serve_local.py           # build/web/ 서빙
  python3 serve_local.py <폴더>   # 지정 폴더 서빙
"""
import http.server
import sys
import os

PORT    = 8080
FOLDER  = sys.argv[1] if len(sys.argv) > 1 else "build/web"

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy",   "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass   # 로그 출력 끄기

os.chdir(FOLDER)
with http.server.HTTPServer(("", PORT), Handler) as srv:
    print(f"✓ http://localhost:{PORT}  (Ctrl+C 로 종료)")
    srv.serve_forever()
