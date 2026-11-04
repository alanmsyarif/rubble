"""Unit shape meshes as non-indexed CCW triangle lists. Pure numpy."""
import numpy as np

# (toFlat rows, centreline radius) per ring kind; mirrors gpu-bodies3d.ts RINGS + visuals.ts RING
_RING_WIRE = 0.1
_RINGS = {
    2: ([1, 0, 0, 0, 1, 0, 0, 0, 1], 0.84),
    3: ([1, 0, 0, 0, 0, 1, 0, -1, 0], 0.66),
    4: ([0, 1, 0, 0, 0, 1, 1, 0, 0], 0.66),
}


def _grid(P, N):
    """(a, b, 3) vertex/normal grids -> triangle list, wound to agree with N."""
    a, b = P.shape[:2]
    i, j = np.meshgrid(np.arange(a - 1), np.arange(b - 1), indexing="ij")
    i, j = i.ravel(), j.ravel()
    idx = np.array([(i, j), (i + 1, j), (i + 1, j + 1), (i, j), (i + 1, j + 1), (i, j + 1)]).transpose(2, 0, 1)
    pos = P[idx[:, :, 0], idx[:, :, 1]].reshape(-1, 3, 3)
    nor = N[idx[:, :, 0], idx[:, :, 1]].reshape(-1, 3, 3)
    fn = np.cross(pos[:, 1] - pos[:, 0], pos[:, 2] - pos[:, 0])
    flip = np.einsum("ij,ij->i", fn, nor.mean(1)) < 0
    pos[flip] = pos[flip][:, ::-1]
    nor[flip] = nor[flip][:, ::-1]
    keep = np.linalg.norm(np.cross(pos[:, 1] - pos[:, 0], pos[:, 2] - pos[:, 0]), axis=1) > 1e-12
    return pos[keep].reshape(-1, 3).astype(np.float32), nor[keep].reshape(-1, 3).astype(np.float32)


def box():
    ps, ns = [], []
    for ax in range(3):
        u, v = (ax + 1) % 3, (ax + 2) % 3
        for s in (-1, 1):
            c = np.array([[-.5, -.5], [-.5, .5], [.5, -.5], [.5, .5]])
            q = np.zeros((4, 3))
            q[:, ax], q[:, u], q[:, v] = s * .5, c[:, 0], c[:, 1]
            n = np.zeros((4, 3))
            n[:, ax] = s
            p, nn = _grid(q.reshape(2, 2, 3), n.reshape(2, 2, 3))
            ps.append(p), ns.append(nn)
    return np.concatenate(ps), np.concatenate(ns)


def sphere(segments=16, rings=8):
    th = np.linspace(0, np.pi, rings + 1)[:, None]
    ph = np.linspace(0, 2 * np.pi, segments + 1)[None, :]
    N = np.stack(np.broadcast_arrays(np.sin(th) * np.cos(ph), np.cos(th), np.sin(th) * np.sin(ph)), -1)
    return _grid(N * 0.5, N)


def ring(kind):
    m, radius = _RINGS[kind]
    M = np.array(m, float).reshape(3, 3)
    R, t = 0.5, 0.5 * (_RING_WIRE / radius)  # three.js TorusGeometry(0.5, tube, 8, 32)
    v = np.linspace(0, 2 * np.pi, 9)[:, None]
    u = np.linspace(0, 2 * np.pi, 33)[None, :]
    P = np.stack(np.broadcast_arrays((R + t * np.cos(v)) * np.cos(u), (R + t * np.cos(v)) * np.sin(u), t * np.sin(v)), -1)
    C = np.stack(np.broadcast_arrays(R * np.cos(u), R * np.sin(u), 0 * v), -1)
    N = P - C
    N /= np.linalg.norm(N, axis=-1, keepdims=True)
    # template -> body frame is M^T (row-vector form: x @ M); scale radius*2 bakes in the demo's size.x factor
    return _grid(P @ M * radius * 2, N @ M)
