"""The book engine (buildout.book, v0.30): total returns carry dividends, the bond's holidays are carried, a name
before its listing hands its weight to the others pro rata, the semis factor is net of a beta known the day before,
planted betas are recovered, the tail measures are the textbook ones, hedges use yesterday's ratio, and the hedge
that keeps every name meets every limit."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from buildout import book as B


def _px(closes, divs=None, start="2024-01-01"):
    d = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"date": d.strftime("%Y-%m-%d"), "close": closes, "volume": 1e6, "div": divs if divs is not None else np.nan})


def test_total_return_adds_the_dividend_on_its_ex_date():
    r = B.total_returns(_px([100.0, 99.0, 100.0], [np.nan, 1.0, np.nan]))
    assert r.iloc[0] == pytest.approx(0.0) and r.iloc[1] == pytest.approx(100 / 99 - 1)


def test_the_bond_market_holiday_is_carried_to_the_next_open_day():
    ust = pd.DataFrame({"DGS2": [4.0] * 4, "DGS10": [4.5] * 4, "DGS20": [5.0, 5.1, 5.2, 5.3]},
                       index=pd.to_datetime(["2024-10-10", "2024-10-11", "2024-10-15", "2024-10-16"]))
    eq = pd.to_datetime(["2024-10-11", "2024-10-14", "2024-10-15", "2024-10-16"])        # Oct 14: stocks open, bonds shut
    r = B.bond_returns(ust, eq)
    full = B.constant_maturity_returns(ust["DGS20"]).dropna()
    assert r.loc["2024-10-14"] == 0.0
    assert (1 + r.loc["2024-10-14":"2024-10-15"]).prod() - 1 == pytest.approx(full.loc["2024-10-15"])


def test_a_name_before_its_listing_hands_its_weight_over_pro_rata():
    R = pd.DataFrame({"A": [0.01, 0.01], "B": [0.03, 0.03], "C": [np.nan, -0.02]})
    w = pd.Series({"A": 0.5, "B": 0.3, "C": 0.2})
    rb = B.book_returns(R, w)
    assert rb.iloc[0] == pytest.approx((0.5 * 0.01 + 0.3 * 0.03) / 0.8)
    assert rb.iloc[1] == pytest.approx(0.5 * 0.01 + 0.3 * 0.03 + 0.2 * -0.02)


def test_the_semis_factor_uses_a_beta_known_the_day_before():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2020-01-01", periods=400)
    q = pd.Series(rng.normal(0, 0.01, 400), index=idx)
    s = 2 * q + pd.Series(rng.normal(0, 0.005, 400), index=idx)
    a = B.semis_factor(s, q)
    s2 = s.copy()
    s2.iloc[300:] *= 3                                                     # change the future only
    b = B.semis_factor(s2, q)
    assert np.allclose(a.iloc[:300].dropna(), b.iloc[:300].dropna())
    beta = lambda f, x: (x.iloc[300] - f.iloc[300]) / q.iloc[300]          # the beta applied on the day the future starts
    assert beta(a, s) == pytest.approx(beta(b, s2))
    assert abs(np.corrcoef(a.dropna(), q.reindex(a.dropna().index))[0, 1]) < 0.15


def test_tail_measures_are_the_textbook_ones():
    x = np.arange(1, 101) / -100.0                                         # losses of 1% to 100%
    assert B.es(x, 0.05) == pytest.approx(np.mean(np.arange(96, 101) / 100))
    rng = np.random.default_rng(1)
    z = rng.standard_t(5, 2_000_000) * math.sqrt(3 / 5)                    # unit variance
    assert B.t_es(1.0, 0.025) == pytest.approx(B.es(z, 0.025), rel=0.02)


@pytest.fixture(scope="module")
def world():
    prices, ust, truth = B.synthetic()
    return B.build(prices, ust), truth


def test_planted_betas_are_recovered(world):
    o, truth = world
    for b in o["betas"]:
        if b["days"] >= 504:
            assert b["market"] == pytest.approx(truth[b["name"]][0], abs=0.12)
            assert b["semis"] == pytest.approx(truth[b["name"]][1], abs=0.2)
    assert o["exposure"]["market"] == pytest.approx(sum(B.BOOK[k] * truth[k][0] for k in B.BOOK), abs=0.05)


def test_sizes_follow_the_limits(world):
    o, _ = world
    s = o["sizes"]
    assert s["es_budget"] == pytest.approx(B.ES_BUDGET / o["tail"]["es95"]["governing"], abs=1e-5)
    assert s["vol_target"] == pytest.approx(B.VOL_TARGET / o["risk"]["vol"], abs=1e-5)
    assert o["size"] == pytest.approx(min(s.values())) and o["binding"] in s
    k = o["keep_names_hedge"]
    if k["meets_all"]:
        assert k["es95"] <= B.ES_BUDGET + 1e-6 and k["vol"] <= B.VOL_TARGET + 1e-6 and k["drawdown95"] <= B.MAX_DD + 1e-6


def test_hedges_use_yesterdays_ratio():
    prices, ust, _ = B.synthetic(days=900)
    P = B.panel(prices, ust)
    rb = B.book_returns(P["R"], pd.Series(B.BOOK))
    a = B.hedge_tests(rb, P["F"], P["E"], P["cash"])
    rb2 = rb.copy()
    rb2.iloc[-1] = -0.5                                                    # a crash on the last day only
    b = B.hedge_tests(rb2, P["F"], P["E"], P["cash"])
    assert a["now"]["nasdaq_beta"] != b["now"]["nasdaq_beta"]
    for k in ("nasdaq_beta", "bond_static_30"):                            # every policy still loses the crash day in full
        assert b["policies"][k]["mean_ann"] < a["policies"][k]["mean_ann"]


def test_var_backtest_counts_breaches():
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0, 0.01, 3000), index=pd.bdate_range("2010-01-01", periods=3000))
    k = B.kupiec(r)
    assert 10 < k["breaches"] < 50 and k["p"] > 0.01


def test_liquidity_is_position_over_a_fifth_of_volume():
    vol = {"A": pd.DataFrame({"close": [10.0] * 25, "volume": [1e6] * 25}, index=pd.bdate_range("2024-01-01", periods=25))}
    row = B.liquidity(vol, pd.Series({"A": 0.10}), vol["A"].index[-1])[0]
    assert row["days_100m"] == pytest.approx(0.10 * B.NAV_USD / (0.2 * 1e7))


def test_build_never_touches_the_network(monkeypatch):
    import buildout.data as data
    monkeypatch.setattr(data, "http", None, raising=False)
    prices, ust, _ = B.synthetic(days=700)
    assert B.build(prices, ust)["size"] > 0


def test_house_style():
    src = open(B.__file__).read().lower()
    for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
        assert b not in src
