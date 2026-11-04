import sys
import shutil
import time

import pytest

from rubble.sidecar import SidecarError, SidecarProcess, find_node, stop_all
from rubble.wire import MSG_FRAME, MSG_SCENE

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not found")
ROOT = __file__.rsplit("tests", 1)[0].rstrip("\/")


def wait_for(fn, timeout):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.01)
    return None


@pytest.fixture
def sc():
    p = SidecarProcess(find_node(NODE), ROOT)
    p.start()
    yield p
    p.stop()


def load(p, name, timeout=60):
    p.send({"cmd": "load", "scene": name, "options": {}})
    scene = wait_for(p.take_scene, timeout)
    assert scene is not None and scene.type == MSG_SCENE
    return scene


def step_frame(p):
    p.step_in_flight = True
    p.send({"cmd": "step"})
    f = wait_for(p.latest_frame, 30)
    assert f is not None and f.type == MSG_FRAME
    return f


def test_start_with_bad_node_path_raises_sidecar_error():
    with pytest.raises(SidecarError, match="nope"):
        find_node(r"C:\nope\node.exe")


@needs_node
def test_load_and_step(sc):
    scene = load(sc, "Wall Smash (2k)")
    n = scene.obj["bodyCount"]
    assert abs(n - 2000) < 400
    for _ in range(10):
        f = step_frame(sc)
        assert len(f.binary) == n * 32
        assert not sc.step_in_flight


@needs_node
def test_latest_frame_drops_old(sc):
    load(sc, "Wall Smash (2k)")
    for _ in range(5):
        sc.send({"cmd": "step"})
    time.sleep(2)
    assert sc.latest_frame().obj["step"] == 5
    assert sc.latest_frame() is None


@needs_node
def test_stop_exits_process(sc):
    sc.stop()
    assert wait_for(lambda: sc.proc.poll() is not None, 3) is not None
    sc.stop()


@needs_node
def test_reader_reports_dead_after_process_killed(sc):
    sc.proc.kill()
    assert wait_for(lambda: not sc.alive, 2)
    assert sc.error
    sc.send({"cmd": "step"})


@needs_node
def test_brick_ring_110k_through_pipe(sc):
    n = load(sc, "Brick Ring (110k)", 120).obj["bodyCount"]
    for _ in range(3):
        assert len(step_frame(sc).binary) == n * 32
    assert sc.alive and sc.error is None
    stop_all()


READY = ("import sys,time\nsys.path.insert(0,%r)\nfrom rubble.wire import *\n"
         "o=sys.stdout.buffer\no.write(encode_message(MSG_EVENT,{'kind':'ready'}));o.flush()\n") % ROOT


def test_event_error_clears_step_in_flight():
    code = READY + ("for l in sys.stdin.buffer:\n o.write(encode_message(MSG_EVENT,{'kind':'error','message':'boom'}));o.flush()\n")
    p = SidecarProcess(None, ROOT, argv=[sys.executable, "-c", code])
    p.start()
    try:
        p.step_in_flight = True
        p.send({"cmd": "step"})
        assert wait_for(lambda: p.error == "boom", 3) and not p.step_in_flight
    finally:
        p.stop()


def test_stop_kills_child_ignoring_stdin():
    p = SidecarProcess(None, ROOT, argv=[sys.executable, "-c", READY + "time.sleep(60)\n"])
    p.start()
    t = time.time()
    p.stop(timeout=0.5)
    assert time.time() - t < 3 and p.proc.poll() is not None
    p.stop()


def test_death_error_includes_stderr_tail():
    code = READY + "sys.stderr.write('Cannot find package three'+chr(10));sys.stderr.flush();time.sleep(0.3)\nsys.exit(1)\n"
    p = SidecarProcess(None, ROOT, argv=[sys.executable, "-c", code])
    p.start()
    try:
        assert wait_for(lambda: not p.alive, 3) and "Cannot find package three" in p.error
    finally:
        p.stop()
