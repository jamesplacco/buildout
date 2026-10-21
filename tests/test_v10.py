"""v0.10: robustness. Robust link statistics, the distributionally robust solver, backtest robustness and the data
screen, checked against brute force, planted answers, properties and the page's JavaScript."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from buildout import reasoner as RZ
from buildout import robust as RB
from buildout.analytics import robust_bt as BT
from buildout.data.quality import screen

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


def _js(req):
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness10.js")], input=json.dumps(req), capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


# ---------- robust link statistics ----------
def test_influence_is_the_exact_leave_one_out_change():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(60, 2))
    y = 0.4 * X[:, 0] - 0.2 * X[:, 1] + rng.standard_t(3, size=60) * 0.5
    fit = RB.ols(y, X)
    D = RB.influence(fit)
    for i in (0, 17, 59):
        keep = np.arange(60) != i
        assert np.allclose(np.array(RB.ols(y[keep], X[keep])["beta"]) - fit["beta"], D[i], atol=1e-12)


def test_huber_resists_planted_outliers_and_hac_widens_under_autocorrelation():
    rng = np.random.default_rng(2)
    n = 300
    x = rng.normal(size=(n, 1))
    y = 0.5 * x[:, 0] + rng.normal(scale=0.3, size=n)
    y_bad = y.copy()
    worst = np.argsort(-x[:, 0])[:6]
    y_bad[worst] -= 8.0                                       # six bad prints on the highest-x months
    assert abs(RB.huber(y_bad, x)["beta"][0] - 0.5) < 0.1 < abs(RB.ols(y_bad, x)["beta"][0] - 0.5)
    assert RB.huber(y, x, c=1e9)["beta"][0] == pytest.approx(RB.ols(y, x)["beta"][0], abs=1e-10)   # c -> infinity is OLS
    e = np.zeros(n)
    for t in range(1, n):
        e[t] = 0.8 * e[t - 1] + rng.normal()
    xa = np.zeros(n)
    for t in range(1, n):
        xa[t] = 0.8 * xa[t - 1] + rng.normal()
    fit = RB.ols(0.1 * xa + e, xa[:, None])
    assert RB.hac_se(fit)[0] > 1.3 * fit["se"][0]


def test_months_to_flip_is_verified_by_refit():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(200, 1))
    y = 0.05 * X[:, 0] + rng.normal(size=200)
    f = RB.months_to_flip(y, X, 0)
    assert f["k"] is not None
    keep = np.ones(200, bool)
    keep[f["dropped"]] = False
    b0 = RB.ols(y, X)["beta"][0]
    assert np.sign(RB.ols(y[keep], X[keep])["beta"][0]) != np.sign(b0)
    if f["k"] > 1:                                            # one fewer is not enough
        keep2 = np.ones(200, bool)
        keep2[f["dropped"][:-1]] = False
        assert np.sign(RB.ols(y[keep2], X[keep2])["beta"][0]) == np.sign(b0)
    strong = 1.0 * X[:, 0] + 0.1 * rng.normal(size=200)
    assert RB.months_to_flip(strong, X, 0)["k"] is None


@needs_node
def test_link_robustness_matches_the_page():
    from buildout.brain import PARENTS, REGIMES
    js = _js({"links": True, "small": [{"y": [0.3, -0.1, 0.8, 0.2, -0.4, 0.9, -1.2, 0.05, 0.6, -0.3, 0.1, 0.4],
                                         "X": [[0.2, 1], [-0.5, 0.3], [1.1, -0.2], [0.4, 0.1], [-0.9, 0.5], [1.3, -1], [-1.5, 0.2], [0.1, 0.9], [0.7, -0.4], [-0.2, 0.6], [0.3, 0.2], [0.5, -0.8]], "j": 0}]})
    s = open(ROOT / "site" / "src" / "snap9.js").read()
    block = json.loads(s[s.index("{"): s.rindex("}") + 1])
    py = RB.link_robustness(block, PARENTS, REGIMES)
    for k, regs in py.items():
        for name, v in regs.items():
            j = js["links"][k][name]
            for f in ("ols", "se", "t", "hac_t", "huber"):
                assert j[f] == pytest.approx(v[f], abs=1e-8), (k, name, f)
            assert j["months_to_flip"] == v["months_to_flip"] and j["flip_months"] == v["flip_months"], (k, name)
            assert [m["month"] for m in j["most_influential"]] == [m["month"] for m in v["most_influential"]]
    sm = js["small"][0]
    y, X = np.array([0.3, -0.1, 0.8, 0.2, -0.4, 0.9, -1.2, 0.05, 0.6, -0.3, 0.1, 0.4]), np.array([[0.2, 1], [-0.5, 0.3], [1.1, -0.2], [0.4, 0.1], [-0.9, 0.5], [1.3, -1], [-1.5, 0.2], [0.1, 0.9], [0.7, -0.4], [-0.2, 0.6], [0.3, 0.2], [0.5, -0.8]])
    f = RB.ols(y, X)
    assert sm["ols"] == pytest.approx(f["beta"], abs=1e-12) and sm["hac"] == pytest.approx(RB.hac_se(f), abs=1e-12)
    assert sm["huber"] == pytest.approx(RB.huber(y, X)["beta"], abs=1e-9) and np.allclose(sm["infl"], RB.influence(f), atol=1e-12)


# ---------- the distributionally robust solver ----------
def _kl(q, p):
    q, p = np.asarray(q), np.asarray(p)
    m = q > 0
    return float(np.sum(q[m] * np.log(q[m] / p[m])))


def test_kl_worst_matches_a_brute_force_search():
    from scipy.optimize import minimize
    u = np.array([0.05, 0.02, -0.04, 0.10, -0.12])
    p = np.array([0.4, 0.25, 0.15, 0.15, 0.05])
    for rho in (0.01, 0.1, 0.5):
        w = RZ.kl_worst(u, p, rho)
        assert _kl(w["q"], p) == pytest.approx(rho, rel=1e-3)               # the constraint binds
        assert float(np.dot(w["q"], u)) == pytest.approx(w["value"], abs=1e-7)
        cons = [{"type": "eq", "fun": lambda q: q.sum() - 1}, {"type": "ineq", "fun": lambda q: rho - _kl(np.maximum(q, 1e-12), p)}]
        r = minimize(lambda q: q @ u, p, constraints=cons, bounds=[(1e-12, 1)] * 5, method="SLSQP", options={"ftol": 1e-12, "maxiter": 500})
        assert w["value"] == pytest.approx(r.fun, abs=1e-5)
    assert RZ.kl_worst(u, p, 0)["value"] == pytest.approx(u @ p)
    assert RZ.kl_worst(u, p, 50)["value"] == pytest.approx(u.min(), abs=1e-4)


@settings(max_examples=60, deadline=None)
@given(st.lists(st.floats(-0.5, 0.5), min_size=2, max_size=7), st.floats(0.0, 2.0))
def test_kl_worst_is_bounded_and_monotone(us, rho):
    u = np.array(us)
    p = np.full(len(u), 1 / len(u))
    v = RZ.kl_worst(u, p, rho)["value"]
    assert u.min() - 1e-9 <= v <= u @ p + 1e-9
    assert RZ.kl_worst(u, p, rho + 0.1)["value"] <= v + 1e-9


def test_robust_solver_reduces_to_the_nominal_one_and_pays_a_price():
    post = RZ.posterior([s["prior"] for s in RZ.SCENARIOS], RZ.SIGNALS, {"infl": True, "corr": True})["posterior"]
    sw = RZ.robustness_sweep(post, RZ.SCENARIOS, RZ.DEFAULTS)
    assert sw["rows"][0]["port"] == RZ.solve(post, RZ.SCENARIOS, RZ.DEFAULTS)["port"]
    ce = [r["worst_case_ce"] for r in sw["rows"]]
    assert all(b <= a + 1e-12 for a, b in zip(ce, ce[1:]))                    # more doubt, lower guaranteed growth
    assert all(r["price_bp"] >= -1e-9 for r in sw["rows"])                     # robustness never raises nominal growth
    assert RZ.max_scenario_odds(0.04, 0.1) > 0.04 and RZ.max_scenario_odds(0.04, 0) == 0.04


@needs_node
def test_robust_solver_matches_the_page():
    obs = {"infl": True, "corr": True, "capex": True}
    js = _js({"sweep": {"observed": obs}, "kl": [[[0.05, -0.02, 0.01], [0.5, 0.3, 0.2], 0.2], [[0.1, 0.0], [0.9, 0.1], 0.05]], "odds": [[0.04, 0.1], [0.3, 0.5]]})
    post = js["sweep"]["post"]
    py = RZ.robustness_sweep(post, RZ.SCENARIOS, RZ.DEFAULTS)
    for a, b in zip(py["rows"], js["sweep"]["res"]["rows"]):
        assert a["port"] == b["port"] and a["worst_case_ce"] == pytest.approx(b["worst_case_ce"], abs=1e-9)
    assert py["first_change_rho"] == js["sweep"]["res"]["first_change_rho"]
    for (u, p, rho), j in zip([[[0.05, -0.02, 0.01], [0.5, 0.3, 0.2], 0.2], [[0.1, 0.0], [0.9, 0.1], 0.05]], js["kl"]):
        assert j["value"] == pytest.approx(RZ.kl_worst(u, p, rho)["value"], abs=1e-10)
    assert js["odds"] == pytest.approx([RZ.max_scenario_odds(0.04, 0.1), RZ.max_scenario_odds(0.3, 0.5)], abs=1e-12)


# ---------- backtest robustness ----------
def test_bootstrap_keeps_blocks_and_brackets_the_truth():
    idx = BT.stationary_bootstrap(1000, 50, mean_block=20, seed=1)
    runs = np.mean(np.diff(idx, axis=1) == 1)
    assert 0.9 < runs < 0.99                                                    # mostly consecutive days
    rng = np.random.default_rng(4)
    d = pd.bdate_range("2015-01-01", periods=2520)
    r = pd.Series(rng.normal(0.0004, 0.01, len(d)), index=d)
    b = BT.bootstrap_stats({"a": r, "b": r * 0.5}, 0.0, draws=400, base="a")
    lo, mid, hi = b["variants"]["a"]["sharpe"]
    assert lo < r.mean() / r.std() * np.sqrt(252) < hi
    assert b["variants"]["b"]["sharpe"] == pytest.approx(b["variants"]["a"]["sharpe"], rel=1e-9)   # scale does not change Sharpe


def test_pbo_separates_luck_from_skill():
    rng = np.random.default_rng(5)
    noise = rng.normal(0, 0.01, size=(2400, 30))
    assert 0.3 < BT.cscv_pbo(noise)["pbo"] < 0.7                              # selection among equals is a coin flip
    skill = noise.copy()
    skill[:, 7] += 0.0015                                                      # one rule is genuinely better
    assert BT.cscv_pbo(skill)["pbo"] < 0.1


def test_robustness_block_lands_in_the_report():
    from buildout.config import default_config
    from buildout.pipeline import analyze, load_inputs
    cfg = default_config()
    cfg.data.source = "synthetic"
    rep = analyze(cfg, load_inputs(cfg))
    r = rep["robustness"]
    assert r["family_rules"] == 30 and r["pbo"]["splits"] == 924 and 0 <= r["pbo"]["pbo"] <= 1
    assert r["plateau"]["chosen"] == "enter -0.10 exit +0.00 x1" and 1 <= r["plateau"]["rank"] <= 30
    assert set(r["bootstrap"]["variants"]) >= {"Book, unhedged", "Book + regime-gated TLT"}
    assert rep["data_quality"]["flagged"] == 0


# ---------- the data screen ----------
def test_screen_flags_bad_prints_frozen_feeds_and_gaps_but_not_real_moves():
    rng = np.random.default_rng(6)
    d = pd.bdate_range("2024-01-01", periods=300)
    px = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, size=(300, 4)), axis=0)), index=d, columns=list("ABCD"))
    px.iloc[100, 0] *= 1.5                                                     # a bad print that reverses
    px.iloc[150:160, 1] = px.iloc[150, 1]                                      # a frozen feed
    px.iloc[200, 2] = np.nan                                                   # a gap
    px.iloc[250:, 3] *= 0.7                                                    # a real, lasting crash
    s = screen(px)
    assert s["symbols"]["A"]["spikes"] == [d[100].strftime("%Y-%m-%d")]
    assert s["symbols"]["B"]["stale_runs"] and s["symbols"]["C"]["gaps"] == 1
    assert s["symbols"]["D"]["ok"] and s["flagged"] == 3


# ---------- property-based invariants across the engine ----------
from buildout import thinking as TH  # noqa: E402
from buildout.analytics import risk as RK  # noqa: E402


@st.composite
def graphs(draw):
    n = draw(st.integers(4, 8))
    edges = []
    for f in range(n):
        for t in range(n):
            if f != t and draw(st.booleans()) and draw(st.booleans()):
                edges.append((f, t, draw(st.floats(-0.6, 0.6))))
    return n, edges


@settings(max_examples=40, deadline=None)
@given(graphs(), st.integers(1, 5), st.integers(0, 10_000))
def test_channels_always_sum_to_the_total_effect(g, K, seed):
    n, E = g
    rng = np.random.default_rng(seed)
    roots = [0, 1]
    obs = {i: float(rng.normal()) for i in range(2, n)}
    T = TH.total_effect(n, E, K)
    ab = TH.abduce(T, obs, roots)
    tgt = n - 1
    pa = TH.path_attribution(n, E, K, ab, tgt)
    assert pa["total"] == pytest.approx(sum(T[tgt, r] * s for r, s in zip(roots, ab["s"])), abs=1e-9)
    mg = TH.marginal(T, obs, roots)
    o = sorted(obs)
    A = T[np.ix_(o, roots)]
    from scipy.stats import multivariate_normal
    S = 0.25 * np.eye(len(o)) + A @ A.T
    assert mg["logpdf"] == pytest.approx(multivariate_normal(np.zeros(len(o)), S).logpdf([obs[i] for i in o]), abs=1e-8)


@settings(max_examples=40, deadline=None)
@given(st.integers(2, 8), st.integers(0, 10_000))
def test_risk_shares_sum_to_one_and_effective_counts_are_bounded(k, seed):
    rng = np.random.default_rng(seed)
    A = rng.normal(size=(k, k))
    cov = pd.DataFrame(A @ A.T / k + 0.01 * np.eye(k))
    w = pd.Series(rng.uniform(0.05, 1, size=k))
    rc = RK.risk_contributions(w, cov)
    assert rc["share"].sum() == pytest.approx(1.0)
    erc = RK.effective_risk_contributors(rc["share"])
    assert 1 - 1e-9 <= RK.effective_independent_bets(w, cov) <= k + 1e-9
    assert erc <= k + 1e-9


@settings(max_examples=30, deadline=None)
@given(st.integers(30, 400), st.integers(1, 20), st.floats(2.0, 60.0))
def test_bootstrap_indices_stay_in_range(n, draws, block):
    idx = BT.stationary_bootstrap(n, draws, block)
    assert idx.shape == (draws, n) and idx.min() >= 0 and idx.max() < n
