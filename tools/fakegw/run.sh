#!/bin/bash
# Fake FXO gateway for development: auto-answers our INVITEs, plays play.wav,
# records what it hears to rec/.  Control port 127.0.0.1:4444 (baresip ctrl_tcp).
#   ./run.sh            start      ./run.sh stop     stop (container is removed)
#   ./run.sh dial URI   make the fake gateway call the hub, e.g. sip:100@192.168.1.5:5090
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd)
NAME=landline-hub-fakegw
case "${1:-start}" in
  start)
    docker image inspect $NAME >/dev/null 2>&1 || docker build -q -t $NAME "$D" >/dev/null
    [ -f "$D/play.wav" ] || python3 "$D/make_wav.py" tone >/dev/null
    mkdir -p "$D/rec"
    docker run --rm -d --name $NAME --network host -u "$(id -u):$(id -g)" -e HOME=/data/home \
      -v "$D":/data $NAME baresip -f /data/home/.baresip >/dev/null
    echo "fake gateway up (SIP :5062)";;
  stop) docker stop $NAME >/dev/null && echo stopped;;
  dial) python3 - "$2" <<'PY'
import json, socket, sys
cmd = json.dumps({"command": "dial", "params": sys.argv[1], "token": "1"}).encode()
s = socket.create_connection(("127.0.0.1", 4444), timeout=3)
s.sendall(str(len(cmd)).encode() + b":" + cmd + b",")
print(s.recv(4096).decode(errors="replace"))
PY
  ;;
  hangup) python3 - <<'PY'
import json, socket
cmd = json.dumps({"command": "hangup", "token": "2"}).encode()
s = socket.create_connection(("127.0.0.1", 4444), timeout=3)
s.sendall(str(len(cmd)).encode() + b":" + cmd + b",")
print(s.recv(4096).decode(errors="replace"))
PY
  ;;
esac
