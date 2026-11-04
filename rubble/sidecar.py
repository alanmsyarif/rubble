"""Node sidecar process manager. Pure module: no bpy."""
import json
import re
import shutil
import subprocess
import threading
import time

from .wire import MSG_EVENT, MSG_FRAME, MSG_SCENE, MSG_STATICS, MessageReader, ProtocolError

_RUNNING: set = set()


class SidecarError(Exception):
    pass


def find_node(path: str) -> str:
    exe = shutil.which(path)
    if not exe:
        raise SidecarError(f"Node not found: {path}")
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        raise SidecarError(f"Node not found: {path} ({e})") from e
    m = re.match(r"v(\d+)", out)
    if not m or int(m.group(1)) < 24:
        raise SidecarError(f"Node 24+ required, found {out or 'unknown'}")
    return exe


class SidecarProcess:
    def __init__(self, node, repo_root, argv=None):
        self.argv = argv or [node, "--experimental-transform-types", "--no-warnings", "sidecar/main.ts"]
        self.repo_root = repo_root
        self.proc = None
        self.step_in_flight = False
        self.alive = False
        self.error = None
        self._cv = threading.Condition()
        self._frame = None
        self._scene = None
        self._statics = []
        self._events = []

    def start(self):
        self.proc = subprocess.Popen(
            self.argv, cwd=self.repo_root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0, creationflags=subprocess.CREATE_NO_WINDOW)
        self.alive = True
        _RUNNING.add(self)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        if self.wait_event("ready", 15) is None:
            err = self.error or "no ready event within 15 s"
            self.stop()
            raise SidecarError(f"Sidecar failed to start: {err}")

    def _die(self, reason):
        with self._cv:
            self.alive = False
            if self.error is None:
                self.error = reason
            self._cv.notify_all()

    def _read_stdout(self):
        reader = MessageReader()
        try:
            while True:
                data = self.proc.stdout.read(1 << 20)
                if not data:
                    self._die("sidecar exited (stdout closed)")
                    return
                for m in reader.feed(data):
                    with self._cv:
                        if m.type == MSG_FRAME:
                            self._frame = m
                            self.step_in_flight = False
                        elif m.type == MSG_SCENE:
                            self._scene = m
                        elif m.type == MSG_STATICS:
                            self._statics.append(m)
                        elif m.type == MSG_EVENT:
                            if m.obj.get("kind") == "error":
                                self.error = m.obj.get("message", "error")
                            self._events.append(m.obj)
                        self._cv.notify_all()
        except ProtocolError as e:
            self._die(f"protocol error: {e}")
        except Exception as e:  # ponytail: reader must never raise into the void
            self._die(f"reader failed: {e}")

    def _read_stderr(self):
        try:
            for line in iter(self.proc.stderr.readline, b""):
                print("[rubble sidecar]", line.decode(errors="replace").rstrip())
        except Exception:
            pass

    def send(self, cmd):
        if not self.alive:
            return
        try:
            self.proc.stdin.write(json.dumps(cmd).encode() + b"\n")
        except (OSError, ValueError) as e:
            self._die(f"send failed: {e}")

    def latest_frame(self):
        with self._cv:
            f, self._frame = self._frame, None
            return f

    def take_scene(self):
        with self._cv:
            s, self._scene = self._scene, None
            return s

    def take_statics(self):
        with self._cv:
            s, self._statics = self._statics, []
            return s

    def wait_event(self, kind, timeout):
        end = time.monotonic() + timeout
        with self._cv:
            while True:
                for i, e in enumerate(self._events):
                    if e.get("kind") == kind:
                        return self._events.pop(i)
                left = end - time.monotonic()
                if left <= 0 or not self.alive:
                    return None
                self._cv.wait(left)

    def stop(self, timeout=2.0):
        p = self.proc
        _RUNNING.discard(self)
        if p is None:
            return
        self.send({"cmd": "quit"})
        self.alive = False
        try:
            p.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            p.wait(timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()


def stop_all():
    for p in list(_RUNNING):
        p.stop()
