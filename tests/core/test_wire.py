import json
import struct

import pytest

from rubble.wire import MSG_FRAME, MSG_EVENT, MessageReader, ProtocolError, encode_message


def frame_bytes():
    return encode_message(MSG_FRAME, {"step": 1, "bodyCount": 3}, bytes(96))


def test_roundtrip_split_chunks():
    data = frame_bytes()
    r = MessageReader()
    out = []
    for i in range(len(data)):
        out += r.feed(data[i:i + 1])
    assert len(out) == 1
    assert out[0].type == MSG_FRAME
    assert out[0].obj == {"step": 1, "bodyCount": 3}
    assert len(out[0].binary) == 96


def test_two_messages_one_chunk():
    data = frame_bytes() + encode_message(MSG_EVENT, {"kind": "ready"})
    out = MessageReader().feed(data)
    assert [m.type for m in out] == [MSG_FRAME, MSG_EVENT]
    assert out[1].obj == {"kind": "ready"} and len(out[1].binary) == 0


def test_reader_rejects_bad_magic():
    r = MessageReader()
    with pytest.raises(ProtocolError):
        r.feed(b"hello" + frame_bytes())


def test_header_layout():
    d = encode_message(4, {"a": 1}, b"xyz")
    j = json.dumps({"a": 1}, separators=(",", ":")).encode()
    assert d[:16] == b"RBL1" + struct.pack("<III", 4, len(j), 3)
