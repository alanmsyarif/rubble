import sys
import time
from pathlib import Path
from types import SimpleNamespace

import bpy

import rubble
from rubble.sidecar import SidecarProcess

ROOT = str(Path(__file__).resolve().parents[2])
FAKE = [sys.executable, str(Path(__file__).with_name("fake_sidecar.py"))]
V1 = ["Brick Ring (28k)", "Brick Ring (110k)", "Brick Walls (27k)", "Wall Smash (2k)", "Breakable Wall (600)",
      "Chain Mail (1.6k)", "Heavy Pendulum", "Box Pile (4k)", "Box Pile (32k)", "Box Columns (100k)"]


def until(fn, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.01)
    return False


def _handler():
    (h,) = [h for h in bpy.app.handlers.load_pre if h.__name__ == "_stop_everything"]
    return h


def test_register_unregister_twice():
    for _ in range(2):
        rubble.register()
        assert hasattr(bpy.types.WindowManager, "rubble")
        assert hasattr(bpy.types, "RUBBLE_PT_panel") and hasattr(bpy.ops.rubble, "live")
        _handler()
        rubble.unregister()
        assert not hasattr(bpy.types.WindowManager, "rubble")
        assert not hasattr(bpy.types, "RUBBLE_PT_panel")
        assert not [h for h in bpy.app.handlers.load_pre if h.__name__ == "_stop_everything"]


def test_scene_enum_has_ten_v1_scenes():
    from rubble import panel
    assert panel.SCENES == V1
    rubble.register()
    try:
        p = bpy.context.window_manager.rubble
        assert [i.identifier for i in p.bl_rna.properties["scene"].enum_items] == V1
        # only the demo's three scene options, with the demo's keys and defaults (bench-scenes.ts)
        got = {}
        for name in V1:
            p.scene = name
            got[name] = p.options()
        assert got == {**{n: {} for n in V1}, "Breakable Wall (600)": {"strength": 50},
                       "Chain Mail (1.6k)": {"ballDensity": 10}, "Heavy Pendulum": {"ratio": 50000}}, got
        p.scene = "Heavy Pendulum"
        p.mass_ratio = "100"
        assert p.options() == {"ratio": 100}
    finally:
        rubble.unregister()


def test_load_pre_stops_running_sidecar():
    from rubble import ops
    rubble.register()
    try:
        sc = SidecarProcess(None, ROOT, argv=FAKE)
        sc.start()
        s = ops.Session("Wall Smash (2k)", {}, argv=FAKE)
        _handler()(None)
        assert until(lambda: sc.proc.poll() is not None and s.sidecar.proc.poll() is not None)
        assert ops.live() is None and s.handle is None
    finally:
        rubble.unregister()


def test_live_session_on_fake_sidecar():
    from rubble import ops
    rubble.register()
    try:
        p = bpy.context.window_manager.rubble
        p.playing = False
        s = ops.Session("Wall Smash (2k)", {}, argv=FAKE)
        assert ops.live() is s
        # R10: one step after load even while paused, so the boxes show at once
        assert until(lambda: s.tick() and s.renderer.poses is not None)
        assert s.renderer.instance_counts()[0] == 3 and p.bodies == 3 and abs(p.step_ms - 1.5) < 1e-6
        time.sleep(0.1)
        s.tick()
        assert p.fps == 0  # paused: no second frame
        p.playing = True
        assert until(lambda: s.tick() and p.fps > 0)
        end = time.monotonic() + 1.5  # the fake answers at once; steps stay at the demo's real time
        while time.monotonic() < end:
            s.tick()
            time.sleep(1 / 120)
        assert 40 < p.fps < 66, p.fps
        s.sidecar.send({"cmd": "fail"})  # the fake answers with EVENT error
        assert until(lambda: s.tick() and p.error == "fake failure")
        p.error = ""
        s.stop()
        assert s.sidecar.proc.poll() is not None and s.handle is None and s.renderer.shader is None
        assert ops.live() is None
        assert p.error == ""  # a deliberate stop is not an error (R9)
    finally:
        rubble.unregister()


def test_sidecar_death_reports_error():
    from rubble import ops
    rubble.register()
    try:
        p = bpy.context.window_manager.rubble
        s = ops.Session("Wall Smash (2k)", {}, argv=FAKE)
        s.sidecar.proc.kill()
        assert until(lambda: not s.tick())
        assert s.stopped and ops.live() is None and "sidecar exited" in p.error
    finally:
        rubble.unregister()


def test_view_under_mouse_skips_overlapping_regions():
    from rubble import ops
    screen = bpy.context.window_manager.windows[0].screen
    area = next(a for a in screen.areas if a.type == "VIEW_3D")
    win = next(r for r in area.regions if r.type == "WINDOW")
    tools = next(r for r in area.regions if r.type == "TOOLS")
    ev = lambda x, y: SimpleNamespace(mouse_x=x, mouse_y=y)
    cx, cy = win.x + win.width // 2, win.y + win.height // 2
    region, rv3d, coord = ops.view_under_mouse(screen, ev(cx, cy))
    assert region == win and rv3d is not None and coord == (cx - win.x, cy - win.y)
    # over the toolbar (overlapping the window region): same view, no mouse coordinate
    region, _, coord = ops.view_under_mouse(screen, ev(tools.x + 5, tools.y + 5))
    assert region == win and coord is None
    assert ops.view_under_mouse(screen, ev(-100, -100)) is None
    o, d = ops._ray(*ops.view_under_mouse(screen, ev(tools.x + 5, tools.y + 5)))  # view centre ray
    assert abs(d.length - 1) < 1e-6 and len(o) == 3


def test_keys_pass_through_until_first_scene():
    from rubble import ops
    rubble.register()
    try:
        s = ops.Session("Wall Smash (2k)", {}, argv=FAKE)
        sent = []
        s.sidecar.send = sent.append
        s.renderer.poses = None
        for t in ("LEFTMOUSE", "SPACE", "R", "PERIOD"):
            ev = SimpleNamespace(type=t, value="PRESS", ctrl=False, alt=False, shift=False, oskey=False,
                                 mouse_x=0, mouse_y=0)
            ctx = SimpleNamespace(window=SimpleNamespace(screen=bpy.context.window_manager.windows[0].screen))
            assert ops.RUBBLE_OT_live._event(SimpleNamespace(session=s, drag_t=None, last_ball=0.0), ctx, ev) \
                == {"PASS_THROUGH"}, t
        assert sent == []
        s.stop()
    finally:
        rubble.unregister()
