"""Framed binary protocol, sidecar stdout -> addon. Pure module: no bpy."""
import json
import struct
from typing import NamedTuple

MAGIC = b"RBL1"
HEADER = struct.Struct("<4sIII")
MSG_EVENT, MSG_SCENE, MSG_STATICS, MSG_FRAME = 1, 2, 3, 4
STATIC_FLOATS = 8
POSE_FLOATS = 8
SHAPE_BOX, SHAPE_SPHERE, SHAPE_RING_FLAT, SHAPE_RING_X, SHAPE_RING_Y, SHAPE_HIDDEN = range(6)


class ProtocolError(Exception):
    pass


class Message(NamedTuple):
    type: int
    obj: dict
    binary: memoryview


def encode_message(type: int, obj: dict, binary: bytes = b"") -> bytes:
    j = json.dumps(obj, separators=(",", ":")).encode()
    return HEADER.pack(MAGIC, type, len(j), len(binary)) + j + bytes(binary)


class MessageReader:
    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list:
        self._buf += data
        out = []
        pos = 0
        buf = self._buf
        while True:
            n = min(4, len(buf) - pos)
            if bytes(buf[pos:pos + n]) != MAGIC[:n]:
                raise ProtocolError("bad magic")
            if len(buf) - pos < HEADER.size:
                break
            _, type_, jl, bl = HEADER.unpack_from(buf, pos)
            end = pos + HEADER.size + jl + bl
            if len(buf) < end:
                break
            js = pos + HEADER.size
            try:
                obj = json.loads(bytes(buf[js:js + jl]))
            except ValueError as e:
                raise ProtocolError(f"bad json: {e}") from e
            out.append(Message(type_, obj, memoryview(bytes(buf[js + jl:end]))))
            pos = end
        del buf[:pos]
        return out
