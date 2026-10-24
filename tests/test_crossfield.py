"""crossfield: actuarial and weather-forecasting methods checked against known answers on synthetic data."""
from __future__ import annotations

import json
import math
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from buildout import crossfield as cf

BANNED = (chr(0x2014), "inter" "section", "load" "-bearing")
SCRATCH = Path("/tmp/claude-0/-home-claude/1e15d221-91bb-543f-92a6-54e21d8a6b8b/scratchpad")


def _json_ok(o):
    s = json.dumps(o, allow_nan=False)
    for b in BANNED:
        assert b not in s.lower()
    return s


# ---------------------------------------------------------------- CRPS, log score, PIT
def test_crps_normal_matches_monte_carlo():
    rng = np.random.default_rng(1)
    mu, sd, y = 0.3, 1.7, -0.4
    X = rng.normal(mu, sd, 400_000)
    X2 = rng.normal(mu, sd, 400_000)
    mc = np.mean(np.abs(X - y)) - 0.5 * np.mean(np.abs(X - X2))
    assert abs(float(cf.crps_normal(mu, sd, y)) - mc) < 5e-3


def test_crps_mixture_matches_monte_carlo_and_reduces_to_normal():
    rng = np.random.default_rng(2)
    w, mu, sd = np.array([0.2, 0.5, 0.3]), np.array([-0.08, 0.01, 0.03]), np.array([0.09, 0.03, 0.05])
    N = 600_000
    k = rng.choice(3, N, p=w)
    X = rng.normal(mu[k], sd[k])
    k2 = rng.choice(3, N, p=w)
    X2 = rng.normal(mu[k2], sd[k2])
    for y in (-0.15, 0.0, 0.04):
        mc = np.mean(np.abs(X - y)) - 0.5 * np.mean(np.abs(X - X2))
        assert abs(float(cf.crps_mixture(w, mu, sd, y)) - mc) < 4e-4
    # vectorized over months, and one component is the normal closed form
    ys = np.array([-0.1, 0.02, 0.2])
    one = cf.crps_mixture(np.ones((3, 1)), np.full((3, 1), 0.01), np.full((3, 1), 0.04), ys)
    assert np.allclose(one, cf.crps_normal(0.01, 0.04, ys))
    W, MU, SD = cf.pad([w, np.ones(1)], [mu, np.array([0.0])], [sd, np.array([0.05])])
    v = cf.crps_mixture(W, MU, SD, np.array([0.0, 0.0]))
    assert np.isclose(v[0], cf.crps_mixture(w, mu, sd, 0.0)) and np.isclose(v[1], cf.crps_normal(0.0, 0.05, 0.0))


def test_log_score_pit_and_var_es_of_mixture():
    w, mu, sd = np.array([0.3, 0.7]), np.array([-0.05, 0.01]), np.array([0.08, 0.035])
    y = 0.02
    dens = float((w * stats.norm.pdf(y, mu, sd)).sum())
    assert np.isclose(cf.log_score_mixture(w, mu, sd, y), math.log(dens))
    assert np.isclose(cf.pit_mixture(w, mu, sd, y), float((w * stats.norm.cdf(y, mu, sd)).sum()))
    q = float(cf.mixture_quantile(w, mu, sd, 0.05))
    assert abs(float((w * stats.norm.cdf(q, mu, sd)).sum()) - 0.05) < 1e-9
    v, e = cf.mixture_var_es(w, mu, sd, 0.05)
    from buildout import infer
    v2, e2 = infer.mixture_cvar(w, mu, sd, 0.05, n=40001)
    assert abs(float(v) - v2) < 1e-3 and abs(float(e) - e2) < 1e-3
    vn, en = cf.mixture_var_es(np.ones(1), np.zeros(1), np.ones(1), 0.05)
    assert np.isclose(float(vn), 1.6448536, atol=1e-6) and np.isclose(float(en), stats.norm.pdf(1.6448536) / 0.05, atol=1e-6)


def test_pit_tests_accept_calibrated_and_reject_underdispersed():
    rng = np.random.default_rng(3)
    y = rng.normal(0, 1, 2000)
    good = cf.pit_histogram(stats.norm.cdf(y))
    bad = cf.pit_histogram(stats.norm.cdf(y / 0.6))
    assert good["ks_p"] > 0.05 and good["berkowitz_p"] > 0.01
    assert bad["ks_p"] < 1e-6 and bad["berkowitz_p"] < 1e-6 and bad["pit_sd"] > good["pit_sd"]
    cv = cf.interval_coverage(stats.norm.cdf(y), 0.9)
    assert abs(cv["coverage"] - 0.9) < 0.02 and cv["kupiec_p"] > 0.05
    assert cf.interval_coverage(stats.norm.cdf(y / 0.6), 0.9)["kupiec_p"] < 1e-6
    _json_ok(good)


# ---------------------------------------------------------------- Brier and the Murphy decomposition
def test_brier_decomposition_identity():
    rng = np.random.default_rng(4)
    p = rng.choice(np.linspace(0.05, 0.95, 10), 3000)
    o = (rng.random(3000) < p).astype(float)
    b = cf.brier(p, o)
    assert abs(b["bs"] - (b["reliability"] - b["resolution"] + b["uncertainty"])) < 1e-12
    assert abs(b["wbv"]) < 1e-15 and abs(b["wbc"]) < 1e-15
    pc = rng.random(3000)
    oc = (rng.random(3000) < pc ** 1.5).astype(float)
    b2 = cf.brier(pc, oc, bins=10)
    assert abs(b2["identity_gap"]) < 1e-12
    assert abs(b2["bs"] - np.mean((pc - oc) ** 2)) < 1e-12
    _json_ok(b2)


# ---------------------------------------------------------------- extreme values
def test_gpd_mle_recovers_xi_on_gpd_and_pareto():
    rng = np.random.default_rng(5)
    for xi, beta in ((0.3, 1.0), (0.1, 0.02), (-0.2, 2.0)):
        y = stats.genpareto.rvs(xi, scale=beta, size=5000, random_state=rng)
        f = cf.gpd_fit(y)
        assert f["method"] == "mle"
        assert abs(f["xi"] - xi) < 3 * f["se_xi"] + 0.01
        assert abs(f["beta"] / beta - 1) < 0.08
        assert abs(f["se_xi"] / f["se_xi_expected"] - 1) < 0.25          # observed against expected information
        p = cf.gpd_fit(y, method="pwm")
        assert p["method"] == "pwm" and abs(p["xi"] - xi) < 0.08
    alpha = 2.5
    x = (1 - rng.random(20000)) ** (-1 / alpha)                          # Pareto with x_m = 1: excesses over u are GPD(1/alpha, u/alpha)
    u = 2.0
    f = cf.gpd_fit(x[x > u] - u)
    assert abs(f["xi"] - 1 / alpha) < 3 * f["se_xi"]
    assert abs(f["beta"] / (u / alpha) - 1) < 0.15


def test_pot_var_es_match_pareto_quantiles():
    rng = np.random.default_rng(6)
    alpha = 3.0
    x = (1 - rng.random(200_000)) ** (-1 / alpha)
    fit = cf.pot(x, 0.9, ps=(0.01, 0.001))
    for p in (0.01, 0.001):
        var_true = p ** (-1 / alpha)
        es_true = var_true * alpha / (alpha - 1)
        assert abs(fit[f"var_{p}"] / var_true - 1) < 0.06
        assert abs(fit[f"es_{p}"] / es_true - 1) < 0.10
    rl = float(cf.return_level(1000, fit))
    assert abs(rl / 1000 ** (1 / alpha) - 1) < 0.08
    assert abs(cf.return_period(rl, fit) - 1000) < 1e-6 * 1000
    me = cf.mean_excess(x, [2.0, 3.0])
    assert abs(me[0]["e"] / (2.0 / (alpha - 1)) - 1) < 0.1             # e(u) = u/(alpha - 1) for a Pareto
    ts = cf.threshold_stability(x, quantiles=[0.8, 0.85, 0.9, 0.95])
    assert ts["stable_from_quantile"] is not None
    _json_ok(fit)
    _json_ok(ts)


def test_gpd_var_es_vectorized_and_exponential_limit():
    v, e = cf.gpd_var_es(np.array([0.05, 0.01]), 1.0, 0.0, 2.0, 1000, 100)
    assert np.allclose(v, 1.0 - 2.0 * np.log(np.array([0.5, 0.1])))
    assert np.allclose(e, v + 2.0)                                       # memoryless tail: ES = VaR + beta


# ---------------------------------------------------------------- backtests
def test_kupiec_accepts_correct_and_rejects_wrong_model():
    rng = np.random.default_rng(7)
    x = rng.normal(0, 1, 3000)
    good = cf.kupiec(x < -1.6448536, 0.05)
    bad = cf.kupiec(x < -1.6448536 * 0.7, 0.05)
    assert good["p"] > 0.05 and bad["p"] < 1e-4 and bad["direction"] == "too many"
    c = cf.christoffersen(x < -1.6448536, 0.05)
    assert c["p_ind"] > 0.01
    clustered = np.zeros(3000, bool)
    clustered[np.arange(0, 3000, 100)[:, None] + np.arange(5)[None, :]] = True
    assert cf.christoffersen(clustered, 0.05)["p_ind"] < 1e-6


def test_acerbi_szekely_z2():
    rng = np.random.default_rng(8)
    T, p = 2000, 0.05
    x = rng.standard_t(4, T) * 0.04
    gq = (np.arange(200) + 0.5) / 200
    s = 0.04
    Vt, Et = -stats.t.ppf(p, 4) * s, s * (4 + stats.t.ppf(p, 4) ** 2) / 3 * stats.t.pdf(stats.t.ppf(p, 4), 4) / p
    Qt = np.tile(-stats.t.ppf(p * gq, 4) * s, (T, 1))
    z_t = cf.acerbi_szekely_z2(x, np.full(T, Vt), np.full(T, Et), p, Qt, sims=1000)
    assert z_t["p"] > 0.01 and abs(z_t["null_mean"]) < 0.02
    half = cf.acerbi_szekely_z2(x, np.full(T, Vt / 2), np.full(T, Et / 2), p, Qt / 2, sims=1000)
    assert half["z2"] < -0.5 and half["p"] < 0.01                         # a model with half the true scale is rejected
    # the FZ0 joint VaR-ES score prefers the true tail to a halved one, month by month
    d = cf.fz0_loss(x, np.full(T, Vt / 2), np.full(T, Et / 2), p) - cf.fz0_loss(x, np.full(T, Vt), np.full(T, Et), p)
    assert cf.dm_test(d)["t"] > 2


def test_tail_backtest_runs_on_synthetic_returns_and_flags_the_normal():
    rng = np.random.default_rng(9)
    r = 0.006 + 0.04 * rng.standard_t(3, 1500) / math.sqrt(3)
    o = cf.tail_backtest(r, 600, refit=12, sims=300, methods=("normal", "historical", "pot"))
    _json_ok(o)
    m = o["methods"]
    assert m["pot"]["0.01"]["kupiec"]["p"] > 0.01
    assert m["pot"]["0.01"]["z2"]["p"] > 0.01
    assert m["normal"]["0.01"]["z2"]["z2"] < m["pot"]["0.01"]["z2"]["z2"]      # the normal understates the size of tail losses
    assert m["normal"]["0.01"]["es_mean"] < m["pot"]["0.01"]["es_mean"]


# ---------------------------------------------------------------- credibility
def test_buhlmann_recovers_planted_k():
    rng = np.random.default_rng(10)
    a, s2, n, r = 1.0, 4.0, 20, 400
    th = rng.normal(5, math.sqrt(a), r)
    G = [rng.normal(t, math.sqrt(s2), n) for t in th]
    b = cf.buhlmann(G)
    assert abs(b["k"] / (s2 / a) - 1) < 0.3
    assert abs(b["Z"][0] - n / (n + s2 / a)) < 0.05
    bs = cf.buhlmann_straub(G)
    assert abs(bs["k"] - b["k"]) < 1e-6 * b["k"]
    _json_ok(b)
    # exposures: X_ij with variance s2/m_ij
    m = [rng.integers(1, 10, n).astype(float) for _ in range(r)]
    X = [rng.normal(t, np.sqrt(s2 / mm)) for t, mm in zip(th, m)]
    bs2 = cf.buhlmann_straub(X, m)
    assert abs(bs2["k"] / (s2 / a) - 1) < 0.3
    flat = cf.buhlmann([rng.normal(0, 1, 10) * 0 + rng.normal(0, 1, 10) for _ in range(5)])
    assert flat["k"] is None or flat["k"] > 0


def test_credibility_n0_recovers_planted_k_from_state_probabilities():
    rng = np.random.default_rng(11)
    K, n, a, s2 = 200, 60, 0.0001, 0.0016                                  # k = 16 months
    th = rng.normal(0.006, math.sqrt(a), K)
    st = np.repeat(np.arange(K), n)
    r = rng.normal(th[st], math.sqrt(s2))
    P = np.eye(K)[st]
    c = cf.credibility_n0(r, P)
    assert abs(c["n0"] / (s2 / a) - 1) < 0.4
    # soft probabilities that are nearly hard give nearly the same answer
    P2 = 0.98 * P + 0.02 / K
    c2 = cf.credibility_n0(r, P2)
    assert c2["n0"] is not None and abs(c2["n0"] / c["n0"] - 1) < 0.5


# ---------------------------------------------------------------- EMOS and BMA
def test_emos_removes_planted_bias_and_underdispersion():
    rng = np.random.default_rng(12)
    T = 3000
    mu = rng.normal(0, 1, T)
    sd_true = np.exp(rng.normal(0, 0.3, T))
    y = rng.normal(mu, sd_true)
    f_mu, f_sd = mu + 0.5, 0.5 * sd_true                                   # biased by +0.5, half the spread
    fit = cf.emos_fit(f_mu, f_sd, y)
    assert abs(fit["a"] + 0.5) < 0.1 and abs(fit["b"] - 1) < 0.05
    assert abs(fit["d"] - 4.0) < 0.6 and fit["c"] < 0.15
    loc, s = cf.emos_apply(fit, f_mu, f_sd)
    assert abs(np.mean(y - loc)) < 0.05
    assert abs(np.std(stats.norm.cdf((y - loc) / s)) - 1 / math.sqrt(12)) < 0.01
    assert fit["crps"] < fit["crps_identity"]
    # walked forward: identity during the burn-in, the fix after it
    wk = cf.emos_walk(f_mu, f_sd, y, start=0, refit=250, min_train=300)
    assert np.allclose(wk["mu"][:250], f_mu[:250])
    assert abs(np.mean(y[600:] - wk["mu"][600:])) < 0.08
    # the mixture form: shape kept, mean and spread corrected
    W = np.tile([0.5, 0.5], (T, 1))
    MU = np.column_stack([f_mu - 0.3 * f_sd, f_mu + 0.3 * f_sd])
    SD = np.column_stack([f_sd, f_sd]) * 0.9
    fm = cf.emos_fit(MU, SD, y, w=W)
    w2, mu2, sd2 = cf.emos_apply(fm, MU, SD, W)
    pit = cf.pit_mixture(w2, mu2, sd2, y)
    assert abs(np.mean(y - (w2 * mu2).sum(1))) < 0.05 and abs(np.std(pit) - 1 / math.sqrt(12)) < 0.015
    assert np.allclose((mu2[:, 1] - mu2[:, 0]) / sd2[:, 0], (MU[:, 1] - MU[:, 0]) / SD[:, 0])


def test_mixture_recalibrate_moments():
    w, mu, sd = np.array([0.4, 0.6]), np.array([-0.02, 0.03]), np.array([0.05, 0.02])
    m, s = cf.mixture_moments(w, mu, sd)
    w2, mu2, sd2 = cf.mixture_recalibrate(w, mu, sd, 0.001, 0.5, 1.3)
    m2, s2 = cf.mixture_moments(w2, mu2, sd2)
    assert np.isclose(m2, 0.001 + 0.5 * m) and np.isclose(s2, 1.3 * s)


def test_bma_recovers_planted_weights():
    rng = np.random.default_rng(13)
    T, wt = 6000, np.array([0.6, 0.3, 0.1])
    mus = np.column_stack([rng.normal(0, 1, T), rng.normal(0, 1, T), rng.normal(0, 1, T)])
    sds = np.array([0.5, 1.0, 2.0])
    k = rng.choice(3, T, p=wt)
    y = rng.normal(mus[np.arange(T), k], sds[k])
    L = stats.norm.logpdf(y[:, None], mus, sds[None, :])
    b = cf.bma_weights(L)
    assert np.allclose(b["w"], wt, atol=0.03)
    W = cf.bma_walk(L, start=3000, refit=500)
    assert np.allclose(W[-1], wt, atol=0.04)
    _json_ok(b)


# ---------------------------------------------------------------- ruin
def test_ruin_probability_matches_brownian_closed_form():
    rng = np.random.default_rng(14)
    mu, sig = 0.004, 0.045
    r = np.expm1(rng.normal(mu, sig, 200_000))
    limit, H = 0.3, 120
    b = -math.log(1 - limit)
    rp = cf.ruin_probability(r, 1.0, limit, H, B=20000, block=1, from_peak=False, seed=3)
    exact = cf.brownian_ruin(mu, sig, b, H, dt=1.0)
    assert abs(rp["p"] - exact) < 0.015, (rp, exact)
    assert rp["lo"] <= rp["p"] <= rp["hi"]
    assert cf.ruin_probability(r, 1.0, limit, H, B=4000, block=1, from_peak=True, seed=3)["p"] >= rp["p"] - 0.02
    cl = cf.cramer_lundberg(mu, sig, u=b)
    assert np.isclose(cl["R"], 2 * mu / sig ** 2) and np.isclose(cl["lundberg_bound"], math.exp(-2 * mu * b / sig ** 2))
    assert np.isclose(cl["psi_brownian"], cf.brownian_ruin(mu, sig, b))
    assert cf.brownian_ruin(mu, sig, b, 1e7) == pytest.approx(cl["lundberg_bound"], rel=1e-6)
    Re = cf.adjustment_coefficient(np.log1p(r))
    assert abs(Re / cl["R"] - 1) < 0.1
    _json_ok(rp)
    _json_ok(cl)


# ---------------------------------------------------------------- the engine evaluation, end to end on synthetic data
def _synthetic_D(T=900, seed=15):
    rng = np.random.default_rng(seed)
    st = np.zeros(T, int)
    for t in range(1, T):
        st[t] = st[t - 1] if rng.random() < 0.97 else 1 - st[t - 1]
    r = np.where(st == 0, rng.normal(0.008, 0.035, T), rng.normal(-0.01, 0.08, T))
    idx = pd.date_range("1871-01-01", periods=T, freq="MS")
    return pd.DataFrame({"r": r, "b": rng.normal(0.002, 0.02, T), "dy": rng.normal(0, 0.002, T), "trend": (rng.random(T) > 0.3).astype(float)}, index=idx)


def test_evaluate_engine_and_summary_on_synthetic_data():
    D = _synthetic_D()
    o = cf.evaluate_engine(D, start_year=1920, burn=120, sims=200)
    s = _json_ok(o)
    assert "variants" in o and set(o["variants"]) >= {"as_is", "emos", "bma", "credibility"}
    assert o["credibility"]["regime_weights_match_engine"]
    assert all(isinstance(v["adoption"]["adopt"], bool) for k, v in o["variants"].items() if k != "as_is")
    lines = cf.summary(o)
    assert len(lines) >= 8
    _json_ok(lines)
    assert "None" not in " ".join(lines) and s


def test_module_text_is_house_style():
    src = Path(cf.__file__).read_text()
    for b in BANNED:
        assert b not in src.lower()


# ---------------------------------------------------------------- real data, when the scratchpad is present
@pytest.mark.skipif(not (SCRATCH / "labs_dl.pkl").exists() or not (SCRATCH / "atlas_dl.pkl").exists(), reason="no local Shiller download")
def test_tail_backtest_on_real_data():
    from buildout import decide, labs
    S = labs.shiller(pickle.load(open(SCRATCH / "labs_dl.pkl", "rb")))
    gh = pickle.load(open(SCRATCH / "atlas_dl.pkl", "rb"))["raw"]
    D = decide.data(S, gh)
    si = int(np.searchsorted(D.index.year, 1940))
    o = cf.tail_backtest(D["r"].to_numpy(), si, refit=12, sims=200, methods=("normal", "pot"))
    _json_ok(o)
    assert o["methods"]["pot"]["0.05"]["es_mean"] > 0
