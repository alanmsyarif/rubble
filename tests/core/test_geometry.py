import numpy as np
import pytest

from rubble import geometry as g


def _ext(p):
    return p.max(0) - p.min(0)


def _check(pos, nor):
    assert pos.dtype == nor.dtype == np.float32 and pos.shape == nor.shape
    assert pos.shape[1] == 3 and len(pos) % 3 == 0
    t = pos.reshape(-1, 3, 3)
    fn = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    ok = np.linalg.norm(fn, axis=1) > 1e-9
    assert (np.einsum("ij,ij->i", fn[ok], nor.reshape(-1, 3, 3).mean(1)[ok]) > 0).all()


def test_box_36_verts_unit_normals():
    p, n = g.box()
    assert len(p) == 36 and np.abs(p).max() <= 0.5 + 1e-6
    assert np.allclose(np.linalg.norm(n, axis=1), 1, atol=1e-5)
    _check(p, n)


def test_sphere_radius_half():
    p, n = g.sphere()
    assert np.allclose(np.linalg.norm(p, axis=1), 0.5, atol=1e-5)
    _check(p, n)


def test_ring_flat_lies_in_xy():
    p, n = g.ring(2)
    e = _ext(p)
    assert e[2] < 0.15 * e[:2].max()
    _check(p, n)


def test_ring_x_stands_in_xz():
    p, n = g.ring(3)
    e = _ext(p)
    assert e[1] < 0.15 * max(e[0], e[2])
    _check(p, n)


def test_ring_y_stands_in_yz():
    p, n = g.ring(4)
    e = _ext(p)
    assert e[0] < 0.15 * max(e[1], e[2])
    _check(p, n)


def test_ring_flat_outer_radius():
    p, _ = g.ring(2)
    assert np.linalg.norm(p[:, :2], axis=1).max() == pytest.approx(0.94, abs=0.02)
