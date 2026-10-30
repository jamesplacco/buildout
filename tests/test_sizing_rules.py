"""v0.32: the volatility-managed rule is set at each month's last close from volatility known then, its test finds a
planted gain and rejects a null, the frontier's rows all meet the limits, and the first row is the unhedged size."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import book as B
from buildout import sizing_rules as SR

ROOT = Path(__file__).resolve().parents[1]


def _series(n=2000, seed=0, vol_regimes=True):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", periods=n)
    sig = np.where((np.arange(n) // 126) % 2 == 0, 0.01, 0.03) if vol_regimes else np.full(n, 0.015)
    return pd.Series(rng.normal(0.0003, 1, n) * sig, index=idx)


def test_exposure_is_set_at_month_end_from_volatility_known_then():
    r = _series()
    x = SR.exposure_path(r, SR.HEADLINE)
    r2 = r.copy()
    r2.loc["2015-03-02":] *= 3                                           # change the future only
    x2 = SR.exposure_path(r2, SR.HEADLINE)
    assert np.allclose(x.loc[:"2015-02-27"].dropna(), x2.loc[:"2015-02-27"].dropna())
    assert np.allclose(x.loc["2015-03-02":"2015-03-31"].dropna(), x2.loc["2015-03-02":"2015-03-31"].dropna())   # March's exposure was fixed at February's close
    m = x.dropna().groupby(x.dropna().index.to_period("M")).nunique()
    assert (m == 1).all()                                                 # one exposure a month
    assert x.max() <= SR.HEADLINE["cap"] + 1e-12 and x.min() >= 0


def test_the_rule_pays_when_volatility_predicts_itself_and_returns_do_not_follow():
    r = _series(vol_regimes=True)                                         # drift constant, variance alternating: the textbook case
    cash = pd.Series(0.0, index=r.index)
    t = SR.test_rule(r, cash, SR.HEADLINE)
    assert t["utility_gain_month"] > 0 and t["sharpe_rule"] > t["sharpe_hold"]


def test_the_rule_is_not_rewarded_on_a_series_with_no_volatility_structure():
    """Zero drift at the target volatility: the rule's exposure hovers near 1x and its gain is noise around zero."""
    gains = []
    for seed in range(8):
        rng = np.random.default_rng(seed)
        idx = pd.bdate_range("2010-01-01", periods=2000)
        r = pd.Series(rng.normal(0.0, 0.20 / math.sqrt(252), 2000), index=idx)
        gains.append(SR.test_rule(r, pd.Series(0.0, index=idx), SR.HEADLINE)["t"])
    assert abs(np.mean(gains)) < 1.0 and max(abs(g) for g in gains) < 3.0


def test_expected_max_t_grows_with_the_count():
    assert SR.expected_max_t(1) < SR.expected_max_t(12) < SR.expected_max_t(100) and 1.5 < SR.expected_max_t(12) < 1.9


def test_the_frontier_meets_the_limits_and_opens_at_the_unhedged_size():
    s = (ROOT / "site" / "src" / "snap30.js").read_text()
    Bk = json.loads(s[s.index("const SNAP30 = ") + 15:s.index(";\n", s.index("const SNAP30 = "))].replace("<\\/", "</"))["book"]
    F = [r for r in Bk["frontier"] if r["meets"]]
    assert len(F) >= 3
    L = Bk["limits"]
    for r in F:
        assert r["es95"] <= L["es_budget"] * 1.006 and r["vol"] <= L["vol_target"] * 1.006 and r["drawdown95"] <= L["max_drawdown"] * 1.006
    assert F[0]["gross"] == pytest.approx(Bk["size"], abs=1e-6) and F[0]["short"] == 0.0
    assert F[-1]["gross"] == 1.0 and F[-1]["short"] >= 0.5
    assert all(F[i + 1]["short"] >= F[i]["short"] for i in range(len(F) - 1))        # more names held, more hedge needed
    V = Bk["vol_rule"]
    assert V["rule"] == SR.HEADLINE and V["n_rules"] == SR.N_RULES
    for k in ("book", "nasdaq_2017"):
        assert V[k]["verdict"] in ("supported", "one_era", "chance", "reversed") and len(V[k]["rules"]) == SR.N_RULES


def test_house_style():
    src = open(SR.__file__).read().lower()
    for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
        assert b not in src
