"""Live mode: a Session (sidecar + renderer + draw handler + timer) and the operators driving it."""
import time
import weakref
from pathlib import Path

import bpy
from bpy_extras import view3d_utils

from .draw import BodyRenderer
from .sidecar import SidecarError, SidecarProcess, find_node

REPO_ROOT = str(Path(__file__).resolve().parents[1])  # v1 runs from the repo checkout
BALL_OFFSET = 2 + 0.7  # R6: the demo fires 2 m plus the ball radius in front of the eye
BALL_REPEAT = 0.12  # s between balls while Space is held (demo: ~8 a second)
STEP_DT = 1 / 60  # gpuParams3D dt: like the demo, never step faster than real time
_live = None  # weakref to the running Session: no GPU object is ever held at module level


def live():
    s = _live() if _live else None
    return s if s and not s.stopped else None


def _props():
    return bpy.context.window_manager.rubble


def _redraw():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == "VIEW_3D":
                a.tag_redraw()


class Session:
    def __init__(self, scene, options, node_path="node", argv=None):
        global _live
        self.stopped = False
        self.timer = None
        self.handle = None
        self.fps = 0.0
        self._interval = 0.0  # smoothed seconds between applied frames
        self._last_frame = None
        self._due = 0.0  # when the next playing step may be sent
        if not argv and not Path(REPO_ROOT, "sidecar", "main.ts").is_file():
            raise SidecarError(f"Rubble solver not found at {REPO_ROOT}\\sidecar - link the addon folder from the repo, don't copy it")
        self.sidecar = SidecarProcess(None if argv else find_node(node_path), REPO_ROOT, argv)
        self.sidecar.start()
        try:
            self.renderer = BodyRenderer()
            self.handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), "WINDOW", "POST_VIEW")
        except Exception:
            self.sidecar.stop()
            raise
        p = _props()
        p.error, p.fps, p.step_ms, p.bodies = "", 0, 0, 0
        _live = weakref.ref(self)
        self.load(scene, options)

    def load(self, scene, options):
        self.sidecar.send({"cmd": "load", "scene": scene, "options": options})
        self.step()  # R10: a first frame even while paused

    def reset(self):
        self.sidecar.send({"cmd": "reset"})
        self.step()

    def step(self):
        self.sidecar.step_in_flight = True  # R9: before send, or the reader may clear it first
        self.sidecar.send({"cmd": "step"})

    def tick(self):
        """One timer tick. R11 order: scene, statics, frame, redraw. False once the sidecar has died."""
        sc, r, p = self.sidecar, self.renderer, _props()
        changed = False
        scene = sc.take_scene()
        if scene:
            r.set_scene(scene)
            changed = True
        for m in sc.take_statics():
            r.add_statics(m)
            changed = True
        f = sc.latest_frame()
        if f:
            r.set_frame(f)
            now = time.perf_counter()
            if self._last_frame is not None:
                dt = now - self._last_frame
                self._interval = dt if not self._interval else 0.9 * self._interval + 0.1 * dt
                self.fps = 1 / max(self._interval, 1e-6)
            self._last_frame = now
            p.fps, p.step_ms, p.bodies = self.fps, f.obj.get("stepMs", 0.0), f.obj["bodyCount"]
            changed = True
        while e := sc.wait_event("error", 0):
            p.error = e.get("message", "error")
        if changed:
            _redraw()
        if not sc.alive:
            p.error = sc.error or "sidecar exited"
            self.stop()
            return False
        now = time.perf_counter()
        if p.playing and not sc.step_in_flight and now >= self._due:
            self._due = max(self._due + STEP_DT, now)  # behind: slow motion, no catch-up (demo)
            self.step()
        return True

    def _draw(self):
        rv3d = bpy.context.region_data
        if rv3d is not None:
            self.renderer.draw(rv3d.perspective_matrix)

    def stop(self):
        if self.stopped:
            return
        self.stopped = True  # R9: from here on the sidecar's "exited" error is ours, not a failure
        try:
            try:
                if self.timer:
                    bpy.context.window_manager.event_timer_remove(self.timer)
                self.timer = None
            finally:
                try:
                    if self.handle:
                        bpy.types.SpaceView3D.draw_handler_remove(self.handle, "WINDOW")
                    self.handle = None
                finally:
                    self.renderer.free()
        finally:
            try:
                self.sidecar.stop()
            finally:
                _redraw()


def view_under_mouse(screen, event):
    """(window region, rv3d, mouse coord in it) for the 3D view the mouse is in, else None.
    coord is None when the mouse is on a region overlapping the view (toolbar, sidebar, header)."""
    x, y = event.mouse_x, event.mouse_y
    inside = lambda r: r.width > 1 and r.height > 1 and r.x <= x < r.x + r.width and r.y <= y < r.y + r.height
    for a in screen.areas:
        if a.type != "VIEW_3D" or not (a.x <= x < a.x + a.width and a.y <= y < a.y + a.height):
            continue
        wins = [r for r in a.regions if r.type == "WINDOW"]
        if not wins:
            return None
        over = next((r for r in a.regions if r.type != "WINDOW" and inside(r)), None)
        win = next((r for r in wins if inside(r)), wins[0])
        coord = None if over or not inside(win) else (x - win.x, y - win.y)
        return win, win.data or a.spaces.active.region_3d, coord  # region.data: quad view
    return None


def _ray(region, rv3d, coord):
    if coord is None:
        coord = (region.width / 2, region.height / 2)
    o = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    d = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord).normalized()
    return o, d


def _node_path(context):
    a = context.preferences.addons.get(__package__)
    return a.preferences.node_path if a else "node"  # dev_register.py registers without enabling


class RUBBLE_OT_live(bpy.types.Operator):
    bl_idname = "rubble.live"
    bl_label = "Start Live"
    bl_description = "Run the selected three-avbd scene live in the viewport"

    def invoke(self, context, event):
        if live():
            self.report({"WARNING"}, "Rubble is already live")
            return {"CANCELLED"}
        p = context.window_manager.rubble
        try:
            self.session = Session(p.scene, p.options(), _node_path(context))
        except (SidecarError, OSError) as e:
            p.error = str(e)
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.session.timer = context.window_manager.event_timer_add(1 / 120, window=context.window)
        self.drag_t = None  # distance along the mouse ray while dragging a body
        self.last_ball = 0.0
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        s = self.session
        if s.stopped:
            return {"CANCELLED"}
        try:
            return self._event(context, event)
        except Exception as e:
            context.window_manager.rubble.error = f"{type(e).__name__}: {e}"
            s.stop()
            raise

    def _event(self, context, event):
        s, t, v = self.session, event.type, event.value
        if t == "TIMER":
            return {"PASS_THROUGH"} if s.tick() else {"CANCELLED"}
        if t == "ESC" and v == "PRESS":
            s.stop()
            return {"CANCELLED"}
        view = view_under_mouse(context.window.screen, event)
        if self.drag_t is not None:
            if t == "MOUSEMOVE":
                if view and view[2]:
                    o, d = _ray(*view)
                    s.sidecar.send({"cmd": "drag_move", "target": list(o + d * self.drag_t)})
                return {"RUNNING_MODAL"}
            if t == "LEFTMOUSE" and v == "RELEASE":
                s.sidecar.send({"cmd": "drag_end"})
                self.drag_t = None
                return {"RUNNING_MODAL"}
        if not view or v != "PRESS" or event.ctrl or event.alt or event.shift or event.oskey:
            return {"PASS_THROUGH"}
        if s.renderer.poses is None and t in ("LEFTMOUSE", "SPACE", "R", "PERIOD"):
            return {"PASS_THROUGH"}  # first scene still loading: don't fill the stdin pipe
        if t == "LEFTMOUSE":
            return self._grab(*view) if view[2] else {"PASS_THROUGH"}
        if t == "SPACE":
            now = time.monotonic()
            if now - self.last_ball >= BALL_REPEAT:
                self.last_ball = now
                o, d = _ray(*view)  # through the mouse, or the view centre when it's on the sidebar
                s.sidecar.send({"cmd": "cannonball", "origin": list(o + d * BALL_OFFSET), "dir": list(d)})
        elif t == "P":
            p = context.window_manager.rubble
            p.playing = not p.playing
        elif t == "PERIOD":
            if not s.sidecar.step_in_flight:
                s.step()
        elif t == "R":
            s.reset()
        else:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}

    def _grab(self, region, rv3d, coord):
        sc = self.session.sidecar
        while sc.wait_event("pick", 0):  # drop a late answer to an earlier pick
            pass
        o, d = _ray(region, rv3d, coord)
        sc.send({"cmd": "pick", "origin": list(o), "dir": list(d)})
        e = sc.wait_event("pick", 0.2)
        hit = e and e.get("hit")
        if not hit:
            return {"PASS_THROUGH"}
        self.drag_t = max(hit["t"], 0.1)  # demo: Math.max(hit.t, 0.1)
        sc.send({"cmd": "drag_start", "body": hit["body"], "local": hit["local"], "target": list(o + d * self.drag_t)})
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        self.session.stop()


class _OnLive:
    @classmethod
    def poll(cls, context):
        return live() is not None


class RUBBLE_OT_stop(_OnLive, bpy.types.Operator):
    bl_idname = "rubble.stop"
    bl_label = "Stop"

    def execute(self, context):
        live().stop()
        return {"FINISHED"}


class RUBBLE_OT_play_toggle(_OnLive, bpy.types.Operator):
    bl_idname = "rubble.play_toggle"
    bl_label = "Play / Pause"

    def execute(self, context):
        p = context.window_manager.rubble
        p.playing = not p.playing
        return {"FINISHED"}


class RUBBLE_OT_step(_OnLive, bpy.types.Operator):
    bl_idname = "rubble.step"
    bl_label = "Step"

    def execute(self, context):
        s = live()
        if not s.sidecar.step_in_flight:
            s.step()
        return {"FINISHED"}


class RUBBLE_OT_reset(_OnLive, bpy.types.Operator):
    bl_idname = "rubble.reset"
    bl_label = "Reset"

    def execute(self, context):
        live().reset()
        return {"FINISHED"}


CLASSES = (RUBBLE_OT_live, RUBBLE_OT_stop, RUBBLE_OT_play_toggle, RUBBLE_OT_step, RUBBLE_OT_reset)
