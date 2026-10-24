"""v0.25 engines: the ML ensemble's restrictions and credibility shrinkage, walked-forward calibration, and the RL
agent's pooled state, CRRA objective and significance gate. Planted answers, no lookahead, monotone calibration,
determinism."""
import numpy as np
import pandas as pd
import pytest

from buildout import ml, rl


# ---------------------------------------------------------------- ML: credibility shrinkage
def _planted(n=600, slope=0.5, seed=0):
    rng = np.random.default_rng(seed)
    b = np.full(n, 0.05)
    d = rng.normal(0, 0.1, n)                     # the forecast's departure from the benchmark
    y = b + slope * d + rng.normal(0, 0.05, n)
    return b + d, b, y


def test_credibility_recovers_a_planted_weight_and_zero_for_noise():
    p, b, y = _planted(slope=0.5)
    out, w = ml.credibility(p, b, y, np.ones(len(y), bool), delta=None)
    assert abs(w[-1] - 0.5) < 0.08
    p0, b0, y0 = _planted(slope=0.0, seed=1)
    _, w0 = ml.credibility(p0, b0, y0, np.ones(len(y0), bool), delta=None)
    assert w0[-1] < 0.1
    assert ml.credibility_weight(np.ones(5), -np.ones(5)) == 0.0 and ml.credibility_weight(np.ones(5), 3 * np.ones(5)) == 1.0   # clipped to [0, 1]


def test_credibility_is_the_benchmark_until_enough_outcomes_are_known():
    p, b, y = _planted()
    out, w = ml.credibility(p, b, y, np.ones(len(y), bool))
    first = ml.SHRINK_MIN + ml.H                      # row i knows rows up to i - H - 1: SHRINK_MIN of them from here
    assert (w[:first] == 0).all() and np.allclose(out[:first], b[:first]) and w[first:].max() > 0


@pytest.mark.parametrize("fn", ["credibility", "platt", "isotonic"])
def test_shrinkage_and_calibration_use_only_outcomes_already_known(fn):
    rng = np.random.default_rng(3)
    n = 200
    p = rng.uniform(0.05, 0.6, n)
    y = (rng.uniform(size=n) < p).astype(float)
    b = np.full(n, 0.2)
    ok = np.ones(n, bool)
    y2 = y.copy()
    y2[120:] = 1 - y2[120:]
    run = {"credibility": lambda yy: ml.credibility(p, b, yy, ok)[0], "platt": lambda yy: ml.platt(p, yy, ok, b),
           "isotonic": lambda yy: ml.isotonic(p, yy, ok, b)}[fn]
    a, c = run(y), run(y2)
    assert np.allclose(a[:120 + ml.H + 1], c[:120 + ml.H + 1])
    assert not np.allclose(a, c)


def test_calibration_maps_are_monotone():
    rng = np.random.default_rng(4)
    x = rng.uniform(size=300)
    y = (rng.uniform(size=300) < x ** 2).astype(float)
    e, v = ml.pav(x, y)
    assert (np.diff(v) >= -1e-12).all() and (np.diff(e) >= 0).all()
    a0, a1 = ml.platt_fit(ml._logit(x), y)
    assert a1 > 0
    # the shrink map at a fixed weight is nondecreasing in the forecast, and stays between forecast and benchmark
    p = np.linspace(-0.2, 0.3, 50)
    w = 0.4
    s = 0.06 + w * (p - 0.06)
    assert (np.diff(s) > 0).all() and (np.minimum(p, 0.06) <= s + 1e-12).all() and (s <= np.maximum(p, 0.06) + 1e-12).all()


def test_isotonic_calibration_repairs_a_planted_miscalibration():
    rng = np.random.default_rng(5)
    n = 1500
    truth = rng.uniform(0.02, 0.5, n)
    y = (rng.uniform(size=n) < truth).astype(float)
    p = np.sqrt(truth)                                # overconfident, but in the right order
    ok = np.ones(n, bool)
    cal = ml.isotonic(p, y, ok, np.full(n, y.mean()))
    late = slice(400, None)
    assert ml.ece(cal[late], y[late]) < 0.5 * ml.ece(p[late], y[late])


def test_combine_truncates_return_members_and_keeps_v24_as_the_mean():
    n = 300
    rng = np.random.default_rng(6)
    P = [rng.normal(-0.02, 0.05, n), rng.normal(0.03, 0.05, n)]
    b, y, ok = np.full(n, 0.05), rng.normal(0.05, 0.15, n), np.ones(n, bool)
    v24, w = ml.combine_forecasts(P, b, y, ok, "return", "v24")
    assert w is None and np.allclose(v24, (P[0] + P[1]) / 2)
    fl, _ = ml.combine_forecasts(P, b, y, ok, "return", "floor")
    assert np.allclose(fl, (np.maximum(P[0], 0) + np.maximum(P[1], 0)) / 2)
    crash, _ = ml.combine_forecasts([np.full(n, -0.5)], b, y, ok, "crash", "floor")     # no truncation for probabilities
    assert np.allclose(crash, -0.5)
    v25, w25 = ml.combine_forecasts(P, b, y, ok, "return", "v25")
    fs, wfs = ml.combine_forecasts(P, b, y, ok, "return", "floor_shrink")
    assert np.allclose(v25, fs) and np.allclose(w25, wfs) and ((w25 >= 0) & (w25 <= 1)).all()
    with pytest.raises(ValueError):
        ml.combine_forecasts(P, b, y, ok, "return", "nonsense")


def _synthetic(n=900, beta=0.0, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1900-01-01", periods=n, freq="MS")
    X = pd.DataFrame({f: np.cumsum(rng.standard_normal(n)) * 0.02 + rng.standard_normal(n) * 0.1 for f in ml.FEATURES}, index=idx)
    X["y_ret"] = beta * X["log_cape"] + rng.standard_normal(n) * 0.05
    X["y_crash"] = (X["y_ret"] < np.quantile(X["y_ret"], 0.2)).astype(float)
    return X


def _cheap_models(task):
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
    if task == "return":
        return {"cape_ols": ("CAPE", lambda: LinearRegression(), ["log_cape"]), "ridge": ("All", lambda: LinearRegression(), ml.FEATURES),
                "analogs": ("kNN 1", lambda: KNeighborsRegressor(n_neighbors=1), ml.FEATURES)}
    return {"logit": ("Logit", lambda: LogisticRegression(max_iter=500), ml.FEATURES), "analogs": ("kNN 3", lambda: KNeighborsClassifier(n_neighbors=3), ml.FEATURES)}


def test_walk_forward_shrinkage_keeps_a_real_signal_and_tames_noise(monkeypatch):
    monkeypatch.setattr(ml, "models", _cheap_models)
    W = ml.walk_forward(_synthetic(beta=1.0), "return", start=1940, permute=False)
    S = ml.score(W)
    assert {"ensemble", "ensemble_v24"} <= set(S) and W["combine"] == "v25"
    assert S["ensemble"]["skill"] > 0.2 and np.mean(W["shrink_weight"][-120:]) > 0.5
    W0 = ml.walk_forward(_synthetic(beta=0.0), "return", start=1940, permute=False)
    S0 = ml.score(W0)
    assert S0["ensemble_v24"]["skill"] < -0.2                     # a memorizing member drags the plain average down
    assert S0["ensemble"]["skill"] > S0["ensemble_v24"]["skill"] + 0.15 and S0["ensemble"]["skill"] > -0.1
    Wv = ml.walk_forward(_synthetic(beta=0.0), "return", start=1940, permute=False, combine="v24")
    assert np.allclose(Wv["preds"]["ensemble"], Wv["preds"]["ensemble_v24"]) and Wv["shrink_weight"] is None


def test_walk_forward_v25_is_deterministic_and_trials_are_complete(monkeypatch):
    monkeypatch.setattr(ml, "models", _cheap_models)
    D = _synthetic(beta=0.5)
    for task in ("return", "crash"):
        a = ml.walk_forward(D, task, start=1940, permute=False)
        b = ml.walk_forward(D, task, start=1940, permute=False)
        assert a["preds"]["ensemble"] == b["preds"]["ensemble"] and a["shrink_weight"] == b["shrink_weight"]
        T = ml.v25_trials(a, task)
        assert sum(t["adopted"] for t in T) == 1
        for t in T:
            assert {"variant", "metric", "before", "after", "t", "adopted"} <= set(t) and np.isfinite(t["t"])
        adopted = next(t for t in T if t["adopted"])
        assert adopted["after"] == pytest.approx(ml.score(a)["ensemble"]["skill"])
        now, w = ml.combine_now([0.01, 0.02], 0.05, a, task)
        assert 0 <= w <= 1 and min(0.05, 0.015) - 1e-12 <= now <= max(0.05, 0.02) + 1e-12


def test_quantile_regression_interval_covers_a_planted_spread():
    rng = np.random.default_rng(8)
    n = 700
    y = rng.normal(0, 1, n)
    lo, hi = ml.qra_interval(np.zeros(n), y, np.zeros((n, 0)))
    m = np.isfinite(lo)
    assert abs(np.mean((y[m] >= lo[m]) & (y[m] <= hi[m])) - 0.8) < 0.05


# ---------------------------------------------------------------- RL: pooled state, CRRA objective, significance gate
def _rl_frame(n=420, seed=0, signal=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1900-01-01", periods=n, freq="MS")
    trend = (rng.uniform(size=n) < 0.6).astype(float)
    r = rng.normal(0.006, 0.04, n) + signal * np.where(trend > 0, 1.0, -1.0)
    return pd.DataFrame({"r": r, "trend": trend, "vol": rng.uniform(0.02, 0.06, n), "cape": rng.uniform(8, 35, n), "dd": -rng.uniform(0, 0.4, n)}, index=idx)


def test_v24_configurations_are_unchanged_and_the_pooled_one_is_added():
    assert rl.CONFIGS["risk_averse_cautious_prior"] == {"gamma": 0.9, "penalty": 4.0, "prior": 120}
    assert rl.CONFIGS["kelly"] == {"gamma": 0.9, "penalty": 0.0, "prior": 24}
    assert rl.CONFIGS["risk_averse_cautious_prior_pooled"]["states"] == "trend_dd"
    assert not set(rl.V25_VARIANTS) & set(rl.CONFIGS)


def test_pooled_states_match_the_full_state_and_use_only_earlier_data():
    D = _rl_frame()
    full = rl.encode(D, 200)
    for scheme, n in rl.SCHEMES.items():
        s = rl.encode(D, 200, scheme)
        assert s.min() >= 0 and s.max() < n and (s == rl.pool(full, scheme)).all()
    assert (rl.encode(D, 200, "trend_dd") == D["trend"].to_numpy().astype(int) * 3 + np.digitize(-D["dd"].to_numpy(), [0.10, 0.25])).all()
    D2 = D.copy()
    D2.iloc[200:, D2.columns.get_loc("vol")] = 99.0
    assert (rl.encode(D, 200, "trend_vol")[:200] == rl.encode(D2, 200, "trend_vol")[:200]).all()


def test_pooled_agent_learns_a_planted_policy():
    rng = np.random.default_rng(2)
    b = rng.integers(0, 6, 3000)
    ret = np.where(b >= 3, 0.02, -0.02) + rng.normal(0, 0.01, 3000)
    Q = rl.fit(b, ret, 0.9, 0.0, 5, n_states=6)
    assert Q.shape == (6, len(rl.ACTIONS), len(rl.ACTIONS))
    assert all(rl.ACTIONS[rl.act(Q, s, 2)] >= 1.0 for s in range(3, 6)) and all(rl.ACTIONS[rl.act(Q, s, 2)] == 0.0 for s in range(3))


def test_batched_fqi_matches_one_at_a_time():
    rng = np.random.default_rng(3)
    T = 300
    s = rng.integers(0, 6, (4, T))
    sn = rng.integers(0, 6, (4, T))
    R = rl.rewards(rng.normal(0.005, 0.04, T), 4.0)[None].repeat(4, 0)
    Qb = rl.fqi_batch(s, sn, R, 0.9, 120, 6)
    assert np.allclose(Qb, np.stack([rl.fqi(s[j], sn[j], R[j], 0.9, 120, 6) for j in range(4)]), atol=1e-12)


def test_crra_gamma_makes_holding_optimal():
    rng = np.random.default_rng(4)
    r = rng.normal(0.006, 0.045, 3000)
    g = rl.crra_gamma(r)
    assert abs(np.mean(r * (1 + r) ** (-g))) < 1e-10
    u = [np.mean(rl.crra(x * r, g)) for x in (0.5, 1.0, 1.5)]
    assert u[1] >= max(u[0], u[2])
    assert rl.crra_gamma(r + 0.002) > g                          # a higher premium needs more risk aversion to hold 1x
    assert rl.rewards_crra(r[:10], 1.0) == pytest.approx(np.log1p(np.maximum(np.array(rl.ACTIONS)[None, None, :] * r[:10, None, None]
                                                                             - rl.COST * np.abs(np.array(rl.ACTIONS)[None, :] - np.array(rl.ACTIONS)[:, None])[None]
                                                                             - np.maximum(0.0, np.array(rl.ACTIONS) - 1.0)[None, None, :] * rl.BORROW, -0.95)))


def test_significance_gate_holds_on_noise_and_acts_on_a_strong_signal():
    cfg = {"gamma": 0.9, "penalty": 4.0, "prior": 120, "states": "trend", "significance": 1.645, "B": 10}
    noise = rl.walk_forward(_rl_frame(seed=5), cfg, start=1925, refit=60)
    assert np.mean(noise["act"] == 1.0) > 0.8
    strong = rl.walk_forward(_rl_frame(seed=5, signal=0.03), cfg, start=1925, refit=60)
    assert np.mean(strong["act"] != 1.0) > 0.2
    again = rl.walk_forward(_rl_frame(seed=5, signal=0.03), cfg, start=1925, refit=60)
    assert (strong["act"] == again["act"]).all() and np.allclose(strong["ret"], again["ret"])


def test_trial_rows_report_both_metrics_with_ranges():
    rng = np.random.default_rng(6)
    hold = rng.normal(0.006, 0.04, 400)
    better = np.where(hold < -0.03, 0.0, hold)
    idx = np.random.default_rng(7).integers(0, 400, (200, 400))
    rows = rl.trial_rows("cut losses", better, hold, hold, idx, 2.0, False)
    assert [r["metric"] for r in rows] == ["Sharpe", "CRRA certainty equivalent, annual"]
    assert all(r["after"] > r["before"] and r["lo"] <= r["after"] - r["before"] <= r["hi"] for r in rows)
    assert "vs_hold" in rows[1] and not rows[0]["adopted"]
