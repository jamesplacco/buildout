import numpy as np
import pandas as pd

from buildout.analytics import risk, signals, sizing


def test_erc_equalizes_risk():
    cov = pd.DataFrame([[0.04, 0.01, 0.0], [0.01, 0.09, 0.02], [0.0, 0.02, 0.16]], index=list("ABC"), columns=list("ABC"))
    w = sizing.erc(cov)
    shares = risk.risk_contributions(w, cov, periods=1)["share"]
    assert shares.max() - shares.min() < 1e-4 and abs(w.sum() - 1) < 1e-12


def test_drawdown_cap_is_monotone():
    a = sizing.max_leverage(0.10, 0.30, 0.20)
    b = sizing.max_leverage(0.10, 0.30, 0.35)
    assert 0 < a < b


def test_trim_rule():
    t = sizing.trim_orders(pd.Series({"NVDA": 0.20, "MSFT": 0.14, "TSLA": 0.05}),
                           pd.Series({"NVDA": 0.14, "MSFT": 0.14, "TSLA": 0.10}), band=0.20)
    assert t.loc["NVDA", "action"] == "trim" and abs(t.loc["NVDA", "trade"] + 0.06) < 1e-12
    assert t.loc["MSFT", "action"] == "hold" and t.loc["TSLA", "action"] == "add"


def test_model_finds_no_edge_where_none_exists(world):
    px = world.prices["QQQ"]
    bond = world.prices["TLT"].pct_change()
    corr = bond.rolling(63).corr(px.pct_change())
    X = signals.features(px, bond, corr)
    y = signals.forward_up(px, 21)
    ev = signals.evaluate(signals.walk_forward(X, y), y)
    assert ev["brier_skill"] < 0.03 and abs(ev["auc"] - 0.5) < 0.08


def test_model_finds_planted_edge():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2012-01-01", periods=2520)
    f = pd.Series(rng.standard_normal(2520), index=idx)
    y = (0.8 * f + rng.standard_normal(2520) > 0).astype(float)
    p = signals.walk_forward(f.to_frame("f"), y, horizon=1, min_train=252)
    assert signals.evaluate(p, y)["auc"] > 0.65
