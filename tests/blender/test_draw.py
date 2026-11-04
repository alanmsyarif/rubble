import statistics
import time

import gpu
import numpy as np
from mathutils import Matrix

from rubble import wire
from rubble.draw import BodyRenderer


def _msg(type_, obj, binary=b""):
    (m,) = wire.MessageReader().feed(wire.encode_message(type_, obj, binary))
    return m


def _statics(shapes, size=(1, 1, 1), rgb=(0.8, 0.5, 0.2)):
    s = np.zeros((len(shapes), 8), np.float32)
    s[:, :3], s[:, 3], s[:, 4:7], s[:, 7] = size, shapes, rgb, 1
    return s


def _scene(shapes, ropes=()):
    return _msg(wire.MSG_SCENE, {"name": "t", "bodyCount": len(shapes), "ropes": list(ropes)},
                _statics(shapes).tobytes())


def _frame(n, pos=(0, 0, 0)):
    p = np.zeros((n, 8), np.float32)
    p[:, :3], p[:, 7] = pos, 1
    return _msg(wire.MSG_FRAME, {"step": 1, "bodyCount": n, "stepMs": 1.0, "stats": {}}, p.tobytes())


def test_renderer_builds_in_background():
    r = BodyRenderer()
    r.draw(Matrix.Identity(4))  # no scene, no frame: no-op
    r.free()
    assert r.shader is None and r.batches is None


def test_index_lists_skip_hidden():
    r = BodyRenderer()
    r.set_scene(_scene([0, 0, 1, 2, 5]))
    lens = {s: len(i) for s, i in r.indices.items()}
    assert lens == {0: 2, 1: 1, 2: 1, 3: 0, 4: 0}, lens
    assert all(4 not in i for i in r.indices.values())
    assert list(r.indices[0]) == [0, 1] and list(r.indices[2]) == [3]
    r.free()


def test_renderer_grows_on_statics():
    r = BodyRenderer()
    r.set_scene(_scene([0] * 10))
    r.add_statics(_msg(wire.MSG_STATICS, {"from": 10, "count": 1}, _statics([1]).tobytes()))
    assert list(r.indices[1]) == [10] and len(r.indices[0]) == 10
    assert r.statics.shape == (11, 8)
    assert r.statics_tex.width * r.statics_tex.height >= 22
    # crossing a texture row (1024 bodies per 2048-wide row) grows the height
    r.add_statics(_msg(wire.MSG_STATICS, {"from": 11, "count": 1100}, _statics([0] * 1100).tobytes()))
    assert r.statics.shape == (1111, 8) and r.statics_tex.height == 2
    r.free()


def test_set_frame_110k_under_10ms():
    n = 110_442
    r = BodyRenderer()
    r.set_scene(_scene([0] * n))
    f = _frame(n)
    times = []
    for _ in range(20):
        t = time.perf_counter()
        r.set_frame(f)
        times.append((time.perf_counter() - t) * 1000)
    med = statistics.median(times)
    print(f"  set_frame 110442 bodies: median {med:.3f} ms, max {max(times):.3f} ms")
    assert med < 10, med
    r.free()


def test_draw_offscreen_renders_body():
    # a long thin box (x-length 1.6) rotated 90 deg about z (quat x,y,z,w) stands vertical, plus a red rope
    r = BodyRenderer()
    st = _statics([0, 5, 5])
    st[0, :3] = (1.6, 0.2, 0.2)
    r.set_scene(_msg(wire.MSG_SCENE, {"name": "t", "bodyCount": 3, "ropes": [{"links": [1, 2], "color": 0xFF0000}]},
                     st.tobytes()))
    p = np.zeros((3, 8), np.float32)
    p[:, 7] = 1
    p[0, 4:] = (0, 0, np.sin(np.pi / 4), np.cos(np.pi / 4))
    p[1, :3], p[2, :3] = (-0.9, 0.9, 0), (0.9, 0.9, 0)
    r.set_frame(_msg(wire.MSG_FRAME, {"step": 1, "bodyCount": 3, "stepMs": 1.0, "stats": {}}, p.tobytes()))
    off = gpu.types.GPUOffScreen(64, 64)
    with off.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(0, 0, 0, 1), depth=1.0)
        r.draw(Matrix.Diagonal((0.5, 0.5, 0.5, 1)))
        px = np.array(fb.read_color(0, 0, 64, 64, 4, 0, "FLOAT").to_list()).reshape(64, 64, 4)
    off.free()
    r.free()
    # box spans NDC y in [-0.4, 0.4], x in [-0.05, 0.05]
    assert px[32 + 10, 32, :3].max() > 0.05, px[42, 32]   # lit above centre
    assert px[32, 32 + 10, :3].max() == 0, px[32, 42]     # nothing right of centre
    row = px[int(64 * (0.5 + 0.45 / 2))]                  # rope at NDC y = 0.45
    assert ((row[:, 0] > 0.5) & (row[:, 1] < 0.1)).any(), row[:, :3].max(0)
