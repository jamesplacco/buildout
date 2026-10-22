"""v0.19: inference (regimes, changepoints, drifting betas, stacking) and the decision engine, on planted answers."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from buildout import decide, infer


def planted_regimes(T=900, seed=1):
    rng = np.random.default_rng(seed)
    st = [0]
    for _ in range(T - 1):
        st.append(st[-1] if rng.random() < 0.97 else 1 - st[-1])
    st = np.array(st)
    x = np.where(st == 1, rng.normal(0.01, 0.03, T), rng.normal(-0.01, 0.08, T))
    return x, st


# ---------------------------------------------------------------- hidden Markov model
def test_hmm_recovers_planted_regimes():
    x, st = planted_regimes()
    sel = infer.hmm_select(x, Ks=(1, 2, 3), starts=3, iters=150)
    m = sel["best"]
    assert m["K"] == 2
    assert m["mu"][0] < 0 < m["mu"][1]                       # ordered: state 0 is the worst
    assert abs(m["sd"][0] - 0.08) < 0.015 and abs(m["sd"][1] - 0.03) < 0.006
    assert (infer.viterbi(x, m) == st).mean() > 0.88
    assert ((infer.hmm_filter(x, m)[:, 1] > 0.5) == (st == 1)).mean() > 0.85
    assert np.allclose(m["A"].sum(1), 1)


def test_hmm_filter_is_causal():
    x, _ = planted_regimes(400)
    m = infer.hmm_fit(x, 2, starts=2, iters=80)
    a = infer.hmm_filter(x, m)
    y = x.copy()
    y[250:] = 0.5                                            # the future changes
    b = infer.hmm_filter(y, m)
    assert np.allclose(a[:250], b[:250])
    sm = infer.hmm_smooth(x, m)
    assert not np.allclose(sm[:250], infer.hmm_smooth(y, m)[:250])     # the smoother does look ahead, by design


def test_hmm_next_and_mixture_risk():
    m = {"A": np.array([[0.9, 0.1], [0.2, 0.8]]), "mu": np.array([-0.01, 0.01]), "sd": np.array([0.08, 0.03])}
    nx = infer.hmm_next(np.array([1.0, 0.0]), m)
    assert np.allclose(nx["weights"], [0.9, 0.1])
    assert abs(nx["mean"] - (-0.009 + 0.001)) < 1e-12
    var, es = infer.mixture_cvar(np.array([1.0]), np.array([0.0]), np.array([0.05]))
    assert abs(var - 0.05 * stats.norm.ppf(0.95)) < 1e-3
    assert abs(es - 0.05 * stats.norm.pdf(stats.norm.ppf(0.95)) / 0.05) < 2e-3
    g = infer.gauss_hermite_log_growth(np.array([0.0, 1.0]), 0.01, 0.05)
    assert g[0] == 0 and abs(g[1] - (0.01 - 0.5 * 0.05 ** 2)) < 5e-4


# ---------------------------------------------------------------- changepoints
def test_bocpd_finds_the_planted_change():
    rng = np.random.default_rng(3)
    y = np.concatenate([rng.normal(0, 0.02, 300), rng.normal(0.03, 0.06, 300)])
    b = infer.bocpd(y, hazard=1 / 120)
    hit = int(np.argmax(b["recent"][250:400])) + 250
    assert 299 <= hit <= 306
    assert b["recent"][10:290].max() < 0.5
    assert b["expected_run"][299] > 100 and b["map_run"][-1] > 250
    assert abs(b["pred_mean"][250]) < 0.01 and 0.015 < b["pred_sd"][250] < 0.03
    assert b["pred_sd"][-1] > 0.045                           # the predictive has learned the new volatility
    z = infer.bocpd(y[:350], hazard=1 / 120)                  # causal: the past does not move with more data
    assert np.allclose(z["recent"], b["recent"][:350])


# ---------------------------------------------------------------- Kalman
def test_kalman_tracks_a_drifting_slope():
    rng = np.random.default_rng(4)
    x = rng.normal(0, 1, 1200)
    beta = np.linspace(-1, 1, 1200)
    y = 0.5 + beta * x + rng.normal(0, 0.3, 1200)
    k = infer.kalman_regression(y, x, q=1e-4, r=0.09)
    assert np.mean(np.abs(k["b"][200:] - beta[200:])) < 0.12
    assert np.all(k["se_b"] > 0)
    k2 = infer.kalman_regression(y[:600], x[:600], q=1e-4, r=0.09)
    assert np.allclose(k2["b"], k["b"][:600])


# ---------------------------------------------------------------- stacking
def test_stack_recovers_the_useful_forecaster():
    rng = np.random.default_rng(5)
    y = rng.normal(0, 1, 500)
    good = y + rng.normal(0, 0.5, 500)
    noise = rng.normal(0, 1, 500)
    w = infer.stack(np.column_stack([good, noise, np.zeros(500)]), y)
    assert w[0] > 0.7 and abs(w.sum() - 1) < 1e-12 and (w >= 0).all()
    assert np.allclose(infer.stack(np.ones((5, 3)), np.ones(5)), 1 / 3)     # too little history: equal weights


# ---------------------------------------------------------------- the decision engine's parts
def test_bond_returns_from_yields():
    idx = pd.date_range("2000-01-01", periods=4, freq="MS")
    S = pd.DataFrame({"y10": [5.0, 4.0, 4.0, 6.0], "cpi": [100.0] * 4}, index=idx)
    b = decide.bond_returns(S)
    assert np.isnan(b.iloc[0])
    assert 0.07 < b.iloc[1] < 0.09                            # a point down: about eight points of duration up
    assert abs(b.iloc[2] - 0.04 / 12) < 1e-3                  # unchanged yield: about a month's coupon
    assert b.iloc[3] < -0.12


def test_risk_aversion_makes_holding_optimal_on_average():
    rng = np.random.default_rng(6)
    r = rng.normal(0.006, 0.04, 800)
    g = decide.calibrate_gamma(r)
    x, _ = decide.choose(np.ones(1), np.array([r.mean()]), np.array([r.std()]), g, es_limit=None)
    assert x == pytest.approx(1.0, abs=0.051)
    hi, _ = decide.choose(np.ones(1), np.array([r.mean() * 2]), np.array([r.std()]), g, es_limit=None)
    lo, _ = decide.choose(np.ones(1), np.array([0.0]), np.array([r.std()]), g, es_limit=None)
    assert hi > 1.0 and lo == 0.0


def test_risk_budget_binds():
    w, mu, sd = np.ones(1), np.array([0.02]), np.array([0.08])
    x0, i0 = decide.choose(w, mu, sd, 2.0, es_limit=None)
    x1, i1 = decide.choose(w, mu, sd, 2.0, es_limit=0.10)
    assert x1 < x0 and i1["capped"] and x1 * i1["es_1x"] <= 0.10 + 1e-9


def test_shrinkage_pulls_thin_states_to_the_mean():
    m = {"K": 2, "A": np.array([[0.5, 0.5], [0.01, 0.99]]), "mu": np.array([-0.05, 0.01]), "sd": np.array([0.1, 0.03])}
    r = np.full(300, 0.005)
    mu, sd = decide.shrink(m, r, n0=120)
    assert -0.05 < mu[0] < 0.005 and abs(mu[0] - 0.005) < abs(mu[1] - 0.005) * 10
    assert (mu[0] - 0.005) / (-0.055) < (mu[1] - 0.005) / 0.005            # the rarely visited state is shrunk more
    assert np.all(sd >= m["sd"])


def test_gate_needs_more_than_a_lucky_draw():
    t0 = stats.norm.ppf(1 - 1 / decide.N_TRIED)
    assert decide.gate_from_t(0.0) == 0.0 and decide.gate_from_t(t0) == 0.0
    assert 0 < decide.gate_from_t(t0 + 1) < 1 and decide.gate_from_t(10) > 0.999


def test_utility_gain_sees_risk_not_just_return():
    rng = np.random.default_rng(7)
    h = rng.normal(0.006, 0.04, 2000)
    lev = 1.5 * h                                             # more return, much more risk
    g, t, n = decide.utility_gain(lev, h, gamma=4.0)
    assert g < 0 and n == 2000
    calm = np.where(h < -0.06, 0.0, h)                        # sidestepping the worst months helps a risk-averse investor
    assert decide.utility_gain(calm, h, gamma=4.0)[0] > 0


def test_model_averaging_prefers_the_better_scorer():
    ll = {"hmm": np.full(400, -1.0), "bocpd": np.full(400, -2.0), "uncond": np.full(400, np.nan)}
    w = decide.averaging_weights(ll, 300)
    assert w[0] > 0.99 and abs(w.sum() - 1) < 1e-12
    ll["hmm"][:250] = -5.0                                    # an old bad record is forgotten as months pass
    w1 = decide.averaging_weights(ll, 260)
    w2 = decide.averaging_weights(ll, 399)
    assert w2[0] > w1[0]


def test_regime_walk_is_causal():
    x, _ = planted_regimes(500)
    a = decide.regime_walk(x, 300, refit=100, Ks=(2,))
    y = x.copy()
    y[420:] = 0.3
    b = decide.regime_walk(y, 300, refit=100, Ks=(2,))
    for t in range(300, 400 + decide.LAG + 20):
        assert np.allclose(a["w"][t], b["w"][t]), t           # months decided before the change saw none of it


def test_hedge_selector_learns_by_context_without_lookahead():
    T = 1200
    rng = np.random.default_rng(8)
    stress = (np.arange(T) // 60) % 2 * 1.0                   # stressed and calm spells of five years
    r = np.where(stress > 0.5, rng.normal(-0.01, 0.06, T), rng.normal(0.012, 0.03, T))
    b = np.where(stress > 0.5, rng.normal(0.02, 0.01, T), rng.normal(0.0, 0.01, T))
    D = pd.DataFrame({"r": r, "b": b, "trend": np.ones(T)}, index=pd.date_range("1900-01-01", periods=T, freq="MS"))
    h = decide.hedge_selector(D, stress, 300)
    names = h["names"]
    pk = h["pick"][300:]
    st = stress[300:]
    assert np.mean(np.array(names)[pk[st > 0.5]] == "bonds") > 0.8
    assert np.mean(np.array(names)[pk[st < 0.5]] == "stocks") > 0.8
    D2 = D.copy()
    D2.iloc[900:, 0] = 0.5
    h2 = decide.hedge_selector(D2, stress, 300)
    assert np.array_equal(h["pick"][:900 + decide.LAG], h2["pick"][:900 + decide.LAG])


def test_forecast_walk_purges_and_stacks():
    from buildout import ml
    n = 700
    rng = np.random.default_rng(9)
    X = rng.normal(0, 1, (n, len(ml.FEATURES)))
    y = 0.05 * X[:, 0] + rng.normal(0, 0.05, n)
    P = pd.DataFrame(X, columns=ml.FEATURES, index=pd.date_range("1900-01-01", periods=n, freq="MS"))
    P["y_ret"] = y
    F = decide.forecast_walk(P, 1940, refit=60)
    s = F["start"]
    assert np.isnan(F["preds"]["ridge"][:s]).all() and np.isfinite(F["preds"]["ridge"][s:]).all()
    sc = decide.forecast_scores(F)
    assert sc["ridge"]["skill"] > 0.3 and sc["nn"]["skill"] > 0.1 and sc["stacked"]["skill"] > 0.2
    assert 0.5 < sc["nn"]["coverage80"] <= 1.0
    assert np.allclose(np.nansum(F["weights"][s:], 1), 1)


def test_decision_text_follows_the_rules():
    banned = ["inter" "section", "load" "-bearing", "—"]
    import inspect
    src = inspect.getsource(decide) + inspect.getsource(infer)
    for b in banned:
        assert b not in src.lower()
    assert "never places orders" in decide.__doc__
    assert math.isclose(decide.ES_LIMIT, 0.12)


# ---------------------------------------------------------------- the shipped decision, the tool and the page
def test_mcp_decision_engine_reads_the_snapshot_and_never_orders(tmp_path):
    from buildout import mcp_server
    ctx = mcp_server.Context(str(tmp_path), None)
    o = mcp_server.decision_engine(ctx, {})
    assert 0 <= o["exposure"] <= 1.5 and 0 <= o["gate"]["value"] <= 1 and "never places orders" in o["note"]
    assert set(mcp_server.decision_engine(ctx, {"part": "backtest"})) >= {"configs", "hold", "trend", "rl"}
    assert "evpi" in mcp_server.decision_engine(ctx, {"part": "flip"})
    with pytest.raises(mcp_server.ToolError):
        mcp_server.decision_engine(ctx, {"part": "trade"})
    assert mcp_server.TOOLS["decision_engine"][3]["readOnlyHint"]


def test_shipped_decision_is_consistent():
    import json
    from pathlib import Path
    from buildout.core import contracts
    txt = (Path(__file__).resolve().parents[1] / "site" / "src" / "snap19.js").read_text()
    i = txt.index("const SNAP19 = ") + len("const SNAP19 = ")
    o = json.loads(txt[i:txt.index(";\n", i)].replace("<\\/", "</"))["decision"]
    n = o["now"]
    g = n["gate"]["value"]
    assert n["exposure"] == pytest.approx(round((1 + g * (n["engine_exposure"] - 1)) / 0.05) * 0.05)
    assert g == pytest.approx(decide.gate_from_t(n["gate"]["t"], n["gate"]["n_tried"]))
    assert abs(sum(n["models"]["weights"].values()) - 1) < 1e-4 and abs(sum(n["forecasts"]["weights"].values()) - 1) < 1e-4
    assert abs(sum(n["regime"]["next"]) - 1) < 1e-4 and n["distribution"]["draws"] == sum(n["distribution"]["hist"])
    assert o["months"] > 1000 and o["start"].startswith("1940")
    p = Path(__file__).resolve().parents[0] / "_decision.json"
    try:
        p.write_text(json.dumps({"schema": 1, **o}))
        assert contracts.check(p) == []
    finally:
        p.unlink(missing_ok=True)
    page = (Path(__file__).resolve().parents[1] / "site" / "page.html").read_text()
    for idt in ("view-decision", "dx-card", "dx-pipe", "dx-reg", "dx-curve", "dx-find"):
        assert f'id="{idt}"' in page
