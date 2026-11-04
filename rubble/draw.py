"""Instanced viewport renderer: one batch per shape, poses/statics/indices in textures."""
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from . import geometry
from .wire import POSE_FLOATS, SHAPE_BOX, SHAPE_HIDDEN, SHAPE_SPHERE, STATIC_FLOATS

TEX_W = 2048
SHAPES = range(SHAPE_HIDDEN)  # 0..4; hidden bodies are in no batch

VERT = """
ivec2 tc(int i) { return ivec2(i % texW, i / texW); }
vec3 rot(vec4 q, vec3 v) { return v + 2.0 * cross(q.xyz, cross(q.xyz, v) + q.w * v); }
vec3 to_linear(vec3 c) {
  return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c));
}
void main() {
  int b = int(texelFetch(index, tc(gl_InstanceID), 0).r);
  vec4 s0 = texelFetch(statics, tc(2 * b), 0);
  vec4 s1 = texelFetch(statics, tc(2 * b + 1), 0);
  vec4 p = texelFetch(poses, tc(2 * b), 0);
  vec4 q = texelFetch(poses, tc(2 * b + 1), 0);
  vec3 v = pos * (ringScale == 1 ? vec3(s0.x) : s0.xyz);
  vnor = rot(q, nor);
  vcol = to_linear(s1.rgb);
  gl_Position = viewProj * vec4(p.xyz + rot(q, v), 1.0);
}
"""
FRAG = """
void main() {
  float l = 0.25 + 0.75 * max(dot(normalize(vnor), normalize(vec3(0.3, 0.5, 0.8))), 0.0);
  FragColor = vec4(vcol * l, 1.0);
}
"""


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _texture(flat, channels, fmt):
    """Pad a flat float32 array to a TEX_W-wide texture."""
    h = max(1, -(-len(flat) // (TEX_W * channels)))
    buf = np.zeros(TEX_W * h * channels, np.float32)
    buf[:len(flat)] = flat
    return gpu.types.GPUTexture((TEX_W, h), format=fmt, data=gpu.types.Buffer("FLOAT", buf.size, buf))


class BodyRenderer:
    def __init__(self):
        iface = gpu.types.GPUStageInterfaceInfo("rubble_body_iface")
        iface.smooth("VEC3", "vnor")
        iface.smooth("VEC3", "vcol")
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, "VEC3", "pos")
        info.vertex_in(1, "VEC3", "nor")
        info.push_constant("MAT4", "viewProj")
        info.push_constant("INT", "texW")
        info.push_constant("INT", "ringScale")
        info.sampler(0, "FLOAT_2D", "poses")
        info.sampler(1, "FLOAT_2D", "statics")
        info.sampler(2, "FLOAT_2D", "index")
        info.vertex_out(iface)
        info.fragment_out(0, "VEC4", "FragColor")
        info.vertex_source(VERT)
        info.fragment_source(FRAG)
        self.shader = gpu.shader.create_from_info(info)
        self.line_shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        meshes = {SHAPE_BOX: geometry.box(), SHAPE_SPHERE: geometry.sphere()}
        meshes.update({k: geometry.ring(k) for k in SHAPES if k not in meshes})
        self.batches = {s: batch_for_shader(self.shader, "TRIS", {"pos": p, "nor": n}) for s, (p, n) in meshes.items()}
        self.statics = np.zeros((0, STATIC_FLOATS), np.float32)
        self.statics_tex = None
        self.indices = {s: np.zeros(0, np.int64) for s in SHAPES}
        self.index_tex = {}
        self.poses = None  # (n, 8) CPU copy of the last frame, for ropes
        self.poses_tex = None
        self.ropes = []
        self._host = None

    def set_scene(self, scene):
        self.ropes = scene.obj.get("ropes", [])
        self.statics = np.frombuffer(scene.binary, np.float32).reshape(-1, STATIC_FLOATS).copy()
        self.poses = self.poses_tex = None
        self._rebuild()

    def add_statics(self, msg):
        start, count = msg.obj["from"], msg.obj["count"]
        if start + count > len(self.statics):
            grown = np.zeros((start + count, STATIC_FLOATS), np.float32)
            grown[:len(self.statics)] = self.statics
            self.statics = grown
        self.statics[start:start + count] = np.frombuffer(msg.binary, np.float32).reshape(-1, STATIC_FLOATS)
        self._rebuild()

    def _rebuild(self):
        self.statics_tex = _texture(self.statics.ravel(), 4, "RGBA32F") if len(self.statics) else None
        shape = self.statics[:, 3].astype(np.int64)
        self.indices = {s: np.flatnonzero(shape == s) for s in SHAPES}
        self.index_tex = {s: _texture(i.astype(np.float32), 1, "R32F") for s, i in self.indices.items() if len(i)}

    def set_frame(self, frame):
        n = frame.obj["bodyCount"]
        h = max(1, -(-n * 2 // TEX_W))
        if self._host is None or self._host.size != TEX_W * h * 4:
            self._host = np.zeros(TEX_W * h * 4, np.float32)
        self._host[:n * POSE_FLOATS] = np.frombuffer(frame.binary, np.float32, n * POSE_FLOATS)
        self.poses = self._host[:n * POSE_FLOATS].reshape(n, POSE_FLOATS)
        self.poses_tex = gpu.types.GPUTexture(
            (TEX_W, h), format="RGBA32F", data=gpu.types.Buffer("FLOAT", self._host.size, self._host))

    def draw(self, view_proj):
        if self.shader is None or self.poses_tex is None or self.statics_tex is None:
            return
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(True)
        sh = self.shader
        sh.bind()
        sh.uniform_float("viewProj", view_proj)
        sh.uniform_int("texW", TEX_W)
        sh.uniform_sampler("poses", self.poses_tex)
        sh.uniform_sampler("statics", self.statics_tex)
        for s, tex in self.index_tex.items():
            sh.uniform_int("ringScale", int(s not in (SHAPE_BOX, SHAPE_SPHERE)))
            sh.uniform_sampler("index", tex)
            self.batches[s].draw_instanced(sh, instance_start=0, instance_count=len(self.indices[s]))
        self._draw_ropes(view_proj)
        gpu.state.depth_test_set("NONE")

    def _draw_ropes(self, view_proj):
        n = len(self.poses)
        ropes = [r for r in self.ropes if len(r["links"]) > 1 and max(r["links"]) < n]
        if not ropes:
            return
        ls = self.line_shader
        ls.bind()
        ls.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
        ls.uniform_float("lineWidth", 3.0)
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(view_proj)
            for r in ropes:
                c = r["color"]
                ls.uniform_float("color", [_srgb_to_linear(((c >> k) & 255) / 255) for k in (16, 8, 0)] + [1.0])
                batch_for_shader(ls, "LINE_STRIP", {"pos": self.poses[r["links"], :3]}).draw(ls)

    def free(self):
        self.shader = self.line_shader = self.batches = None
        self.statics_tex = self.poses_tex = None
        self.index_tex = {}
