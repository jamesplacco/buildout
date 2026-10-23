"""v0.21: the matrix shortcuts. The forward-backward pass as a scan of matrix products (and every EM start in one batch),
the mind's spread for many questions as one sparse matrix product, the board, the spectral map, the page's batched
spread, and the Pearl facts; each shortcut checked against the step-by-step version it replaces."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from buildout import infer, mind, voices
from buildout.core import bench

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
MIND_JSON = ROOT / "buildout" / "assets" / "mind.json"


def random_hmm(T=700, K=3, seed=0):
    rng = np.random.default_rng(seed)
    A = rng.dirichlet(np.ones(K) * 0.5, K) * 0.3 + np.eye(K) * 0.7
    A /= A.sum(1, keepdims=True)
    pi = rng.dirichlet(np.ones(K))
    B = rng.uniform(0.01, 1.0, (T, K)) ** 3
    return B, pi, A


# ---------------------------------------------------------------- the scan
def test_scan_gives_every_prefix_and_suffix_product():
    rng = np.random.default_rng(1)
    C = rng.uniform(0.0, 1.0, (37, 3, 3))
    Q, L = infer._scan(C)
    run = np.eye(3)
    for t in range(37):
        run = run @ C[t]
        assert np.allclose(Q[t] * math.exp(L[t]), run, rtol=1e-10, atol=0)
    Qr, Lr = infer._scan(C, reverse=True)
    run = np.eye(3)
    for t in range(36, -1, -1):
        run = C[t] @ run
        assert np.allclose(Qr[t] * math.exp(Lr[t]), run, rtol=1e-10, atol=0)


def test_forward_backward_matches_the_loop():
    for K in (1, 2, 3, 5):
        B, pi, A = random_hmm(K=K, seed=K)
        a1, g1, l1 = bench._loop_fb(B, pi, A)
        F = infer.forward_backward(B, pi, A)
        assert np.abs(a1 - F["alpha"]).max() < 1e-12 and np.abs(g1 - F["gamma"]).max() < 1e-12
        assert float(F["loglik"]) == pytest.approx(l1, rel=1e-12, abs=1e-9)
        assert F["xi"].sum() == pytest.approx(len(B) - 1)


def test_batch_axis_is_the_same_as_one_at_a_time():
    sets = [random_hmm(T=300, K=3, seed=s) for s in range(4)]
    F = infer.forward_backward(np.stack([s[0] for s in sets]), np.stack([s[1] for s in sets]), np.stack([s[2] for s in sets]))
    for i, (B, pi, A) in enumerate(sets):
        G = infer.forward_backward(B, pi, A)
        assert np.allclose(F["gamma"][i], G["gamma"], atol=1e-14) and np.allclose(F["xi"][i], G["xi"], atol=1e-12)


def _em_reference(x, K, mu, sd, iters=200, tol=1e-6, min_sd=1e-3):
    """Baum-Welch one start at a time with the step-by-step pass, as the engine ran before v0.21."""
    A = np.full((K, K), 0.05 / max(1, K - 1))
    np.fill_diagonal(A, 0.95)
    pi = np.full(K, 1.0 / K)
    ll_old = -np.inf
    for _ in range(iters):
        B = infer._norm_pdf(x, mu, sd) + 1e-300
        mx = B.max(1, keepdims=True)
        al, g, ll = bench._loop_fb(B / mx, pi, A)
        ll += float(np.log(mx).sum())
        T = len(x)
        Bs = B / mx
        beta = np.ones((T, K))
        c = np.zeros(T)
        a = pi * Bs[0]
        c[0] = a.sum()
        for t in range(1, T):
            c[t] = ((al[t - 1] @ A) * Bs[t]).sum()
        for t in range(T - 2, -1, -1):
            beta[t] = (A @ (Bs[t + 1] * beta[t + 1])) / c[t + 1]
        xi = A * (al[:-1].T @ (Bs[1:] * beta[1:] / c[1:, None]))
        pi = g[0]
        A = xi / xi.sum(1, keepdims=True)
        w = g.sum(0)
        mu = (g * x[:, None]).sum(0) / w
        sd = np.sqrt(np.maximum((g * (x[:, None] - mu) ** 2).sum(0) / w, min_sd ** 2))
        if ll - ll_old < tol * abs(ll):
            break
        ll_old = ll
    return mu, sd, A, ll


def test_batched_em_equals_one_start_at_a_time():
    rng = np.random.default_rng(4)
    st = np.cumsum(rng.random(800) < 0.03) % 2
    x = np.where(st == 1, rng.normal(0.01, 0.03, 800), rng.normal(-0.01, 0.07, 800))
    m = infer.hmm_fit(x, 2, starts=1, iters=200)
    mu0 = np.quantile(x, (np.arange(2) + 0.5) / 2)
    mu, sd, A, ll = _em_reference(x, 2, mu0, np.full(2, x.std()))
    o = np.argsort(mu)
    assert m["loglik"] == pytest.approx(ll, rel=1e-12)
    assert np.allclose(m["mu"], mu[o], atol=1e-12) and np.allclose(m["sd"], sd[o], atol=1e-12) and np.allclose(m["A"], A[np.ix_(o, o)], atol=1e-10)
    many = infer.hmm_fit(x, 2, starts=5)
    assert many["loglik"] >= m["loglik"] - 1e-9


# ---------------------------------------------------------------- the mind as matrices
@pytest.fixture(scope="module")
def M():
    return mind.Mind(json.loads(MIND_JSON.read_text()), voices.Library(voices.load()))


QS = ["Is the stock market overvalued?", "Should I buy long bonds?", "Is AI a bubble?", "Does machine learning predict returns?", "Is gold a good hedge now?"]


def test_spread_many_is_the_same_walk_for_every_column(M):
    seeds = [M.recall(q) for q in QS]
    R = M.spread_many(seeds)
    for q, s in enumerate(seeds):
        assert np.abs(R[:, q] - np.array(M.spread(s))).max() < 1e-15
    P = M.walk_matrix()
    assert P.shape == (M.N, M.N) and P.nnz <= 2 * len(M.edges)


def test_think_many_is_think(M):
    a = [M.think(q) for q in QS]
    b = M.think_many(QS)
    for x, y in zip(a, b):
        assert x.get("axis") == y.get("axis") and x.get("p") == y.get("p") and x.get("seeds") == y.get("seeds")
    assert getattr(M, "_spread_cache", None) is None


def test_board_weighs_every_axis(M):
    B = M.board()
    axes = M.G["axes"]
    assert len(B) >= 20 and {r["axis"] for r in B} <= set(axes)
    assert all(0 < r["p_bull"] < 1 and r["lo"] <= r["p_bull"] + 1e-9 <= r["hi"] + 2e-9 and r["n"] >= 1 for r in B)
    d = [abs(r["p_bull"] - 0.5) for r in B]
    assert d == sorted(d, reverse=True)


def test_spectral_shortcut_is_close_but_not_exact(M):
    s = M.recall(QS[1])
    f, e = np.array(M.spread_fast(s)), np.array(M.spread(s))
    assert np.corrcoef(f, e)[0, 1] > 0.85
    lam = M.spectral(64)[1]
    assert len(lam) == 64 and lam.max() <= 1 + 1e-9
    rel = M.related("c:kalman", 8)
    assert len(rel) == 8 and all(r["id"] != "c:kalman" for r in rel)
    assert rel == sorted(rel, key=lambda r: -r["similarity"])


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_page_batched_spread_and_board_match(M):
    G = json.loads(MIND_JSON.read_text())
    qs = [a["bull"] for a in G["axes"].values()]
    req = {"voices": {"cfg": voices.config(), "lib": {"quotes": voices.load()}}, "mind": G, "questions": qs}
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness21.js")], input=json.dumps(req), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    js = json.loads(r.stdout)
    assert js["exact"] and js["maxd"] == 0                   # each column of the page's batch is the single walk, bit for bit
    py = M.board()
    assert [x["axis"] for x in js["board"]] == [x["axis"] for x in py]
    for a, b in zip(js["board"], py):
        assert a["p_bull"] == pytest.approx(b["p_bull"], abs=2e-6) and a["n"] == b["n"]


# ---------------------------------------------------------------- the knowledge, the tool, the page
def test_pearl_facts_and_concepts_are_in_the_mind(M):
    for k in ("k:pearl-mechanism-alea", "k:pearl-duplex-bankless", "k:pearl-issuance-bankless", "k:pearl-together-alea"):
        n = M.nodes[M.idx[k]]
        assert n.get("source_url", "").startswith("https://") and n.get("checked")
    for c in ("c:matrix-multiplication", "c:parallel-prefix-scan", "c:personalized-pagerank", "c:proof-of-useful-work"):
        assert c in M.idx
    assert "d:matrix" in M.idx


def test_mcp_mind_board(tmp_path):
    from buildout import mcp_server
    ctx = mcp_server.Context(str(tmp_path), None)
    assert len(mcp_server.mind_board(ctx, {})["board"]) >= 20
    assert len(mcp_server.mind_board(ctx, {"related": "c:gpu", "limit": 5})["related"]) == 5
    with pytest.raises(mcp_server.ToolError):
        mcp_server.mind_board(ctx, {"related": "c:no-such-node"})


def test_page_ships_the_shortcut_desk():
    page = (ROOT / "site" / "page.html").read_text()
    for idt in ("view-matrix", "mx-tiles", "mx-board", "mx-go", "mx-bench", "mx-brain", "mx-pearl", "const SNAP21 =", "function mindSpreadMany", "mx-scan"):
        assert idt in page, idt
    low = page.lower()
    assert chr(0x2014) not in page and ("inter" "section") not in low and ("load" "-bearing") not in low
