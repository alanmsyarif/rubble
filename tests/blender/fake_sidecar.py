"""Test stand-in for sidecar/main.ts: the wire protocol over a fixed scene of 3 boxes."""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rubble.wire import MSG_EVENT, MSG_FRAME, MSG_SCENE, encode_message  # noqa: E402

N = 3
STATICS = struct.pack(f"<{N * 8}f", *[1, 1, 1, 0, 0.8, 0.5, 0.2, 1] * N)
out = sys.stdout.buffer


def send(type_, obj, binary=b""):
    out.write(encode_message(type_, obj, binary))
    out.flush()


send(MSG_EVENT, {"kind": "ready"})
step = 0
for line in sys.stdin.buffer:
    if not line.strip():
        continue
    cmd = json.loads(line)
    c = cmd["cmd"]
    if c in ("load", "reset"):
        step = 0
        send(MSG_SCENE, {"name": cmd.get("scene", "fake"), "bodyCount": N, "ropes": []}, STATICS)
    elif c == "step":
        step += 1
        poses = struct.pack(f"<{N * 8}f", *[v for i in range(N) for v in (i, 0, 0.5, 0, 0, 0, 0, 1)])
        send(MSG_FRAME, {"step": step, "bodyCount": N, "stepMs": 1.5, "stats": {}}, poses)
    elif c == "pick":
        send(MSG_EVENT, {"kind": "pick", "hit": {"body": 0, "local": [0, 0, 0], "t": 5.0}})
    elif c == "fail":
        send(MSG_EVENT, {"kind": "error", "message": "fake failure"})
    elif c == "quit":
        break
