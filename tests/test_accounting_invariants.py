"""Portfolio accounting: one order of events, with hand-calculated answers (buildout/nav.py, v0.48).

Each expected value below was worked out by hand from the stated inputs, not read off the code.
"""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from buildout import nav, track


def test_a_loss_on_the_first_day_is_a_drawdown():
    # NAV 100, first return -20%, then nineteen flat days: ends at 80, and the worst fall from a peak is 20%
    r = [-0.20] + [0.0] * 19
    assert nav.levels(r, 100.0)[-1] == pytest.approx(80.0)
    assert nav.max_drawdown(r) == pytest.approx(0.20)
    idx = pd.bdate_range("2024-01-02", periods=20)
    s = track.stats(pd.Series(r, index=idx), pd.Series(0.0, index=idx))
    assert s["maxdd"] == pytest.approx(0.20), "the record's statistics use the same convention"
    # before v0.48 the first close was the first peak, and this path showed no drawdown at all
    lv = (1 + pd.Series(r)).cumprod()
    assert float(1 - (lv / lv.cummax()).min()) == 0.0
    # a path that only rises has none; a fall after a rise is measured from the rise
    assert nav.max_drawdown([0.1, 0.1]) == 0.0
    assert nav.max_drawdown([0.25, -0.20]) == pytest.approx(0.20)
    assert nav.max_drawdown([]) == 0.0


def test_a_rebalance_trades_the_net_amount_per_instrument():
    # A 25, B 25, cash 50. A rises 10% to 27.50: NAV 102.50. Back to 25% / 25% / 50%: each of A and B wants 25.625.
    o = nav.rebalance({"A": 25.0, "B": 25.0}, 50.0, {"A": 0.10}, {"A": 0.25, "B": 0.25})
    assert o["pre_nav"] == pytest.approx(102.50)
    assert o["trades"]["A"] == pytest.approx(-1.875) and o["trades"]["B"] == pytest.approx(0.625)
    assert o["traded"] == pytest.approx(2.50)
    assert o["turnover"] == pytest.approx(0.02439024, abs=1e-8), "two-way, over the pre-trade NAV"
    assert o["cash"] == pytest.approx(51.25) and o["nav"] == pytest.approx(102.50), "no cost: the NAV is unchanged by the trade"
    assert o["positions"] == pytest.approx({"A": 25.625, "B": 25.625})


def test_offsetting_requests_in_one_instrument_trade_nothing():
    t = nav.net_trades({"X": 5.0, "Y": 2.0}, {"X": -5.0})
    assert t == {"Y": 2.0} and nav.traded(nav.net_trades({"X": 5.0}, {"X": -5.0})) == 0.0
    # and so cost nothing: a book already at its targets, asked to rebalance at 5 bp
    o = nav.rebalance({"X": 50.0}, 50.0, None, {"X": 0.5}, cost_bp=5.0)
    assert o["traded"] == pytest.approx(0.0, abs=1e-12) and o["cost"] == pytest.approx(0.0, abs=1e-12)


def test_a_fee_is_charged_once():
    o = nav.rebalance({"A": 50.0}, 50.0, None, {"A": 0.5}, fee=1.25)
    assert o["cash"] == pytest.approx(48.75) and o["nav"] == pytest.approx(98.75) and o["positions"] == pytest.approx({"A": 50.0})
    assert nav.charge_fee(50.0, 100.0, 1.25) == pytest.approx((48.75, 98.75))
    assert nav.charge_fee(50.0, 100.0, -0.40) == pytest.approx((50.40, 100.40)), "a negative fee is a rebate"
    # costs come out of cash after the targets are set on the pre-cost NAV: 10 bp on 10 traded is 0.01
    c = nav.rebalance({}, 100.0, None, {"A": 0.10}, cost_bp=10.0)
    assert c["cost"] == pytest.approx(0.01) and c["positions"]["A"] == pytest.approx(10.0) and c["nav"] == pytest.approx(99.99)
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            nav.rebalance({"A": 50.0}, 50.0, None, {"A": 0.5}, fee=bad)


def _two_names():
    idx = pd.bdate_range("2024-01-02", periods=3)
    R = pd.DataFrame({"a": [0.0, 0.10, 0.0], "b": [0.0, 0.0, 0.0]}, index=idx)
    W = pd.DataFrame(0.5, index=idx, columns=["a", "b"])
    return idx, R, W


def test_the_sleeve_is_charged_for_one_net_trade_per_name():
    """Day 2: a rises 10%. Day 3 the sleeve is cut from 1.00 to 0.90 of NAV and re-equalised.
    Coming into day 3 the account is worth 1.05, with a at 0.55 / 1.05 = 0.5238 of NAV and b at 0.50 / 1.05 = 0.4762.
    Wanted: 0.45 each. Trades: sell 0.0738 of a, sell 0.0262 of b: 0.1000 of NAV in all.
    Charged separately: the size change |0.90 - 1.00| = 0.1000, plus 0.90 x the re-equalising inside the sleeve
    (0.0238 + 0.0238 = 0.0476) = 0.0429. The sale of b for size and the purchase of b to re-equalise are one trade."""
    idx, R, W = _two_names()
    g = pd.Series([1.0, 1.0, 0.9], index=idx)
    port = (R * W).sum(axis=1) * g                     # no cash return, no costs: the account's own return
    t = nav.sleeve_turnover(g, R, W, port)
    assert t.iloc[0] == pytest.approx(1.0), "the opening build"
    assert t.iloc[1] == pytest.approx(0.0), "nothing to do until a price has moved"
    assert t.iloc[2] == pytest.approx(0.55 / 1.05 - 0.45 + 0.50 / 1.05 - 0.45) == pytest.approx(0.10)
    inside = track.rebalance_turnover(R, W)
    separate = abs(0.9 - 1.0 * 1.05 / 1.05) + 0.9 * inside.iloc[2]
    assert separate == pytest.approx(0.10 + 0.9 * (2 * (0.55 / 1.05 - 0.5))) and separate > t.iloc[2] + 0.04
    # never more than the two charged separately, on any path
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2020-01-01", periods=400)
    R = pd.DataFrame(rng.normal(0.0005, 0.02, (400, 4)), index=idx, columns=list("abcd"))
    W = pd.DataFrame(0.25, index=idx, columns=list("abcd"))
    g = pd.Series(np.repeat(rng.uniform(0.3, 1.2, 20), 20), index=idx)
    port = (R * W).sum(axis=1) * g
    net = nav.sleeve_turnover(g, R, W, port)
    x = (R * W).sum(axis=1)
    dg = (g - g.shift(1) * (1 + x.shift(1)) / (1 + port.shift(1))).abs().fillna(g.iloc[0])
    upper = dg + g * track.rebalance_turnover(R, W)
    assert (net <= upper + 1e-12).all() and net.sum() < upper.sum() - 0.05


def test_the_walk_forward_nets_when_it_is_given_the_names():
    src = inspect.getsource(track.walk_forward)
    assert 'names = getattr(turn_names, "attrs", {}).get("names")' in src and "nav.sleeve_turnover(g, names[0], names[1], gross_ret)" in src
    idx, R, W = _two_names()
    t = track.rebalance_turnover(R, W)
    assert t.attrs["names"][0] is not None and list(t.attrs["names"][1].columns) == ["a", "b"], "the names travel with the number"
    assert '"turnover_method"' in src and "two-way (buys plus sells)" in src, "the record says which count it used and what it means"
    assert "max_drawdown(x)" in inspect.getsource(track.stats) and "nav.max_drawdown(x)" in inspect.getsource(track.max_drawdown)
    assert track.max_drawdown(pd.Series([-0.10, -0.05])) == pytest.approx(0.145), "-10% then -5% is 14.5% from the start"
