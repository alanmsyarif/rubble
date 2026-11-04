# Throwaway spike: instanced cube draw handler fed by a texture, numpy-animated poses, default backend.
import sys, os, time, json
import bpy, gpu, numpy as np
from gpu_extras.batch import batch_for_shader
OUT = sys.argv[sys.argv.index("--") + 1]
CONFIGS = [48, 64, 80]  # side; bodies = side^3 = 110592 / 262144 / 512000
WARM, TICKS, W = 30, 200, 2048
res = {"backend": gpu.platform.backend_type_get(), "runs": []}
G = {}

VERT = """
void main() {
  int i = gl_InstanceID;
  ivec2 c0 = ivec2((i * 2) % texW, (i * 2) / texW);
  vec4 p = texelFetch(xf, c0, 0);
  vec4 q = texelFetch(xf, ivec2(c0.x + 1, c0.y), 0);
  vec3 u = q.yzw; float w = q.x;
  vec3 v = pos * vec3(0.4, 0.2, 0.1);
  vec3 r = v + 2.0 * cross(u, cross(u, v) + w * v);
  vnor = nor + 2.0 * cross(u, cross(u, nor) + w * nor);
  gl_Position = viewProj * vec4(p.xyz + r, 1.0);
}
"""
FRAG = """
void main() {
  float l = 0.25 + 0.75 * max(dot(normalize(vnor), normalize(vec3(0.3, 0.5, 0.8))), 0.0);
  FragColor = vec4(vec3(0.85, 0.6, 0.45) * l, 1.0);
}
"""

def init_gpu():
    iface = gpu.types.GPUStageInterfaceInfo("spk_iface"); iface.smooth("VEC3", "vnor")
    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, "VEC3", "pos"); info.vertex_in(1, "VEC3", "nor")
    info.push_constant("MAT4", "viewProj"); info.push_constant("INT", "texW")
    info.sampler(0, "FLOAT_2D", "xf")
    info.vertex_out(iface); info.fragment_out(0, "VEC4", "FragColor")
    info.vertex_source(VERT); info.fragment_source(FRAG)
    G["shader"] = gpu.shader.create_from_info(info)
    P, N = [], []
    for ax in range(3):
        u, v = [(1, 2), (0, 2), (0, 1)][ax]
        for sgn in (-1, 1):
            n = [0, 0, 0]; n[ax] = sgn
            def pt(a, b):
                p = [0.0, 0.0, 0.0]; p[ax] = 0.5 * sgn; p[u] = a; p[v] = b; return p
            q = [pt(-.5, -.5), pt(.5, -.5), pt(.5, .5), pt(-.5, .5)]
            for k in (0, 1, 2, 0, 2, 3):
                P.append(q[k]); N.append(n)
    G["batch"] = batch_for_shader(G["shader"], "TRIS", {"pos": P, "nor": N})

def build(side):
    n = side ** 3
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    i = np.arange(n)
    base = np.stack([i % side, (i // side) % side, i // (side * side)], 1).astype(np.float32) * 0.5
    st = {"side": side, "n": n, "base": base, "i": i.astype(np.float32), "H": (2 * n + W - 1) // W}
    st["host"] = np.zeros(W * st["H"] * 4, np.float32)
    c = side * 0.25
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                r3d = area.spaces.active.region_3d
                r3d.view_location = (c, c, c); r3d.view_distance = side * 1.3
    return st

def poses(st, t):
    n = st["n"]; a = t + st["i"] * 0.001
    h = st["host"][: n * 8].reshape(n, 8)
    h[:, :3] = st["base"]; h[:, 2] += 0.1 * np.sin(a); h[:, 3] = 0
    h[:, 4] = np.cos(a * 0.5); h[:, 5:7] = 0; h[:, 7] = np.sin(a * 0.5)

S = {"cfg": 0, "tick": 0, "draws": [], "up": [], "start": time.perf_counter(), "st": None, "pix": None}

def draw_cb():
    st = S["st"]
    if st and "tex" in st:
        gpu.state.depth_test_set("LESS_EQUAL"); gpu.state.depth_mask_set(True)
        sh = G["shader"]; sh.bind()
        sh.uniform_float("viewProj", bpy.context.region_data.perspective_matrix)
        sh.uniform_int("texW", W); sh.uniform_sampler("xf", st["tex"])
        G["batch"].draw_instanced(sh, instance_start=0, instance_count=st["n"])
        gpu.state.depth_test_set("NONE")
    if st and S["tick"] >= WARM + TICKS - 5 and S["pix"] is None:
        r = bpy.context.region
        fb = gpu.state.active_framebuffer_get()
        px = fb.read_color(r.width // 2, r.height // 2, 1, 1, 4, 0, "FLOAT")
        S["pix"] = [round(float(x), 3) for x in np.array(px.to_list()).ravel()]
    S["draws"].append(time.perf_counter())

def tag():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D": area.tag_redraw()

def finish():
    st = S["st"]; d = np.diff(np.array(S["draws"])) * 1000
    res["runs"].append({"bodies": st["n"], "fps_median": float(1000 / np.median(d)),
        "draw_interval_ms_p95": float(np.percentile(d, 95)), "draws": len(d) + 1,
        "pose_upload_ms": float(np.median(S["up"]) * 1000), "center_pixel_rgba": S["pix"]})

def tick():
    try:
        if time.perf_counter() - S["start"] > 280: raise TimeoutError("spike exceeded 280 s")
        if not G: init_gpu()
        if S["tick"] == 0:
            S["st"] = build(CONFIGS[S["cfg"]]); S["pix"] = None
        st = S["st"]; t0 = time.perf_counter()
        poses(st, S["tick"] * 0.05); h = st["host"]
        st["tex"] = gpu.types.GPUTexture((W, st["H"]), format="RGBA32F", data=gpu.types.Buffer("FLOAT", h.size, h))
        tag()
        t1 = time.perf_counter()
        S["tick"] += 1
        if S["tick"] == WARM: S["draws"].clear(); S["up"].clear()
        elif S["tick"] > WARM: S["up"].append(t1 - t0)
        if S["tick"] == WARM + TICKS:
            finish(); S["cfg"] += 1; S["tick"] = 0
            if S["cfg"] == len(CONFIGS): raise StopIteration
        return 0.0
    except BaseException as e:
        if not isinstance(e, StopIteration):
            import traceback; res["error"] = traceback.format_exc()
        json.dump(res, open(OUT, "w"), indent=1)
        os._exit(0)  # spike only

bpy.types.SpaceView3D.draw_handler_add(draw_cb, (), "WINDOW", "POST_VIEW")
bpy.app.timers.register(tick, first_interval=2.0)
