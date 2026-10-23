"""v0.22: the shape of the market. Each geometric tool checked on data whose answer is known (a planted circle has one
loop, pure noise stays inside the Marchenko-Pastur edges, the affine-invariant distance ignores a change of units),
and the engine's geometric-analog model wired through the decision engine, the page and the agents' tools."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.sparse.csgraph import minimum_spanning_tree

from buildout import decide, geometry as g

ROOT = Path(__file__).resolve().parents[1]


def spd(rng, d=3):
    A = rng.normal(size=(d, d))
    return A @ A.T + d * np.eye(d) * 0.1


def test_rolling_cov_is_every_window_cov():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(120, 3))
    C = g.rolling_cov(X, 36)
    assert np.isnan(C[34]).all()
    for e in (35, 60, 119):
        assert np.allclose(C[e], np.cov(X[e - 35:e + 1].T), atol=1e-12)


def test_affine_invariant_distance_is_a_metric_that_ignores_units():
    rng = np.random.default_rng(1)
    A, B, Cm = spd(rng), spd(rng), spd(rng)
    d = lambda P, Q: float(g.affine_invariant(P, Q[None])[0])
    assert d(A, A) < 1e-9
    assert abs(d(A, B) - d(B, A)) < 1e-9
    assert d(A, Cm) <= d(A, B) + d(B, Cm) + 1e-9
    M = rng.normal(size=(3, 3))                       # any change of units or mixing of the assets
    assert abs(d(M @ A @ M.T, M @ B @ M.T) - d(A, B)) < 1e-8
    assert abs(d(np.eye(3), np.e * np.eye(3)) - math.sqrt(3)) < 1e-9


def test_frechet_mean_and_bures():
    rng = np.random.default_rng(2)
    A = spd(rng)
    assert np.allclose(g.frechet_mean(np.stack([A, A, A])), A)
    D2 = np.diag([1.0, 4.0])
    assert np.allclose(g.frechet_mean(np.stack([np.eye(2), D2 ** 2])), D2)          # the geometric, not arithmetic, mean
    assert g.bures(np.zeros(2), np.eye(2), np.zeros(2), np.eye(2)) < 1e-9
    assert abs(g.bures(np.zeros(2), np.eye(2), np.zeros(2), 4 * np.eye(2)) - math.sqrt(2)) < 1e-9


def test_classical_mds_recovers_a_flat_map():
    rng = np.random.default_rng(3)
    P = rng.normal(size=(30, 2))
    D = np.sqrt(((P[:, None] - P[None]) ** 2).sum(-1))
    xy, share = g.classical_mds(D, 2)
    D2 = np.sqrt(((xy[:, None] - xy[None]) ** 2).sum(-1))
    assert np.allclose(D, D2, atol=1e-8)
    assert share.sum() > 0.999


def test_marchenko_pastur_noise_stays_inside_and_a_factor_escapes():
    rng = np.random.default_rng(4)
    N, T = 40, 400
    Z = rng.normal(size=(T, N))
    lam = np.linalg.eigvalsh(np.corrcoef(Z.T))
    lo, hi = g.mp_edges(N / T)
    assert (lam > hi * 1.1).sum() == 0 and lam.min() > lo * 0.6
    f = rng.normal(size=(T, 1))
    lam2 = np.linalg.eigvalsh(np.corrcoef((Z + 1.5 * f).T))
    assert (lam2 > hi).sum() == 1
    x = np.linspace(lo, hi, 4001)
    assert abs(np.trapezoid(g.mp_density(x, N / T), x) - 1) < 0.01


def test_h0_is_the_minimum_spanning_tree():
    rng = np.random.default_rng(5)
    P = rng.normal(size=(25, 3))
    D = np.sqrt(((P[:, None] - P[None]) ** 2).sum(-1))
    assert abs(g.mst_h0(D).sum() - minimum_spanning_tree(D).sum()) < 1e-9
    assert len(g.mst_h0(D)) == 24


def test_h1_finds_the_one_loop_in_a_circle():
    rng = np.random.default_rng(6)
    th = np.sort(rng.uniform(0, 2 * math.pi, 24))
    P = np.column_stack([np.cos(th), np.sin(th)]) + rng.normal(0, 0.02, (24, 2))
    D = np.sqrt(((P[:, None] - P[None]) ** 2).sum(-1))
    pairs = [(b, d) for b, d in g.rips_h1(D) if math.isfinite(d)]
    life = sorted((d - b for b, d in pairs), reverse=True)
    assert life[0] > 0.8 and pairs[0][1] > 1.6 and (len(life) == 1 or life[1] < 0.3 * life[0])
    blob = rng.normal(size=(24, 2)) * 0.3
    Db = np.sqrt(((blob[:, None] - blob[None]) ** 2).sum(-1))
    lb = [d - b for b, d in g.rips_h1(Db) if math.isfinite(d)]
    assert (max(lb) if lb else 0) < 0.5 * life[0]


def test_h1_square_dies_when_the_diagonal_appears():
    D = np.array([[0, 1, 1.5, 1], [1, 0, 1, 1.5], [1.5, 1, 0, 1], [1, 1.5, 1, 0]], float)
    pairs = [(b, d) for b, d in g.rips_h1(D) if math.isfinite(d)]
    assert pairs == [(1.0, 1.5)]


def test_transport_and_paths():
    rng = np.random.default_rng(7)
    A = rng.normal(size=(200, 3))
    dirs = rng.normal(size=(32, 3))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    assert g.sliced_w(A, A, dirs) == 0.0
    assert g.sliced_w(A, A + 1.0, dirs) > 0.3
    th = np.linspace(0, 2 * math.pi, 4001)
    assert abs(g.levy_area(np.cos(th), np.sin(th)) - math.pi) < 1e-3                 # counterclockwise: x leads y
    assert abs(g.levy_area(np.sin(th), np.cos(th)) + math.pi) < 1e-3


def test_dfa_hurst_tells_noise_from_memory():
    rng = np.random.default_rng(8)
    e = rng.normal(size=4000)
    assert abs(g.dfa_hurst(e) - 0.5) < 0.08
    x = np.zeros(4000)
    for t in range(1, 4000):
        x[t] = 0.6 * x[t - 1] + e[t]                                                 # short memory pushes small-scale H up
    assert g.dfa_hurst(x) > 0.6


def test_analogs_are_spaced_and_known():
    d = np.array([0.1, 0.2, 0.15, 5, 0.05, 0.3, 0.01, np.inf])
    an = g.analogs(d, 7, 6, k=3, gap=2)
    assert an[0] == 6 and all(abs(a - b) >= 2 for a in an for b in an if a != b)
    assert 7 not in an


def test_forward_returns():
    x = np.array([0.1, -0.1, 0.2, 0.0, 0.05])
    f = g.forward(x, 2)
    assert abs(f[0] - (0.9 * 1.2 - 1)) < 1e-12 and np.isnan(f[-1]) and np.isnan(f[-2])


def test_engine_has_the_geometric_model():
    assert "geo" in decide.MODELS and "geo" in decide.MODEL_NAMES
    rng = np.random.default_rng(9)
    idx = pd.date_range("1900-01-01", periods=600, freq="MS")
    D = pd.DataFrame({"r": rng.normal(0.005, 0.04, 600), "b": rng.normal(0.002, 0.02, 600)}, index=idx)
    out = decide.geo_walk(D, 300)
    for t in (300, 450, 599):
        w, mu, sd = out["w"][t], out["mu"][t], out["sd"][t]
        assert abs(w.sum() - 1) < 1e-12 and (sd > 0).all() and len(mu) == (decide.GEO_K if t > 500 else len(mu)) and len(mu) >= 4
        assert all(j + 12 <= t - decide.LAG and j <= t - decide.LAG - decide.GEO_W for j in out["analogs"][t])
    assert out["now"][3] is not None


def test_page_ships_the_geometry_desk():
    page = (ROOT / "site" / "page.html").read_text()
    for idt in ("view-geometry", "const SNAP22 =", "geo-map", "geo-spec", "geo-bars", "geo-tests", "geo-levy"):
        assert idt in page, idt
    low = page.lower()
    assert chr(0x2014) not in page and ("inter" "section") not in low and ("load" "-bearing") not in low


def test_mcp_geometry_tool(tmp_path):
    from buildout import mcp_server
    ctx = mcp_server.Context(str(tmp_path), None)
    out = mcp_server.geometry_engine(ctx, {})
    assert out["tests"] and out["findings"]
    with pytest.raises(mcp_server.ToolError):
        mcp_server.geometry_engine(ctx, {"part": "no-such-part"})
