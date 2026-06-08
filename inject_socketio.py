"""
웹 빌드 후 build/web/index.html 에 Socket.IO JS 브릿지를 주입한다.
network.py 의 WebBridgeTransport 가 window.zdConnect / zdSend / _zd_inbox 를 호출한다.

build_web.sh 가 pygbag 빌드 직후 자동 호출한다.
"""
import os
import sys

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "build", "web", "index.html")

BRIDGE = """<!-- ZombieDays Socket.IO 멀티플레이 브릿지 -->
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
  window._zd_inbox = [];
  window.zdConnect = function(url){
    try {
      window._zd_sock = io(url, {transports:["websocket"]});
      window._zd_sock.on("connect", function(){ window._zd_sid = window._zd_sock.id; });
      var push = function(d){ window._zd_inbox.push(JSON.stringify(d)); };
      window._zd_sock.on("init_players", function(arr){ (arr||[]).forEach(push); });
      window._zd_sock.on("update_player", push);
      window._zd_sock.on("leave_player", function(d){
        window._zd_inbox.push(JSON.stringify({_leave: d.id})); });
    } catch(e){ console.error("zdConnect 실패", e); }
  };
  window.zdSend = function(s){
    if(window._zd_sock){ window._zd_sock.emit("update_position", JSON.parse(s)); }
  };
</script>
"""

MARKER = "ZombieDays Socket.IO"


def main():
    if not os.path.isfile(INDEX):
        print(f"[inject] index.html 없음: {INDEX}")
        return 1
    with open(INDEX, encoding="utf-8") as f:
        html = f.read()
    if MARKER in html:
        print("[inject] 이미 주입됨 — 건너뜀")
        return 0
    if "</head>" in html:
        html = html.replace("</head>", BRIDGE + "</head>", 1)
    else:
        html = BRIDGE + html   # head 가 없으면 앞에 삽입
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(html)
    print("[inject] Socket.IO 브릿지 주입 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
