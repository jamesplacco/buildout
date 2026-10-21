"""The backtester must be impossible to fool on timing and exact on costs and financing."""
import numpy as np
import pandas as pd

from buildout.analytics import backtest, metrics


def _random_returns(n=2520, seed=1):
    idx = pd.bdate_range("2016-01-01", periods=n)
    return pd.DataFrame({"X": np.random.default_rng(seed).normal(0, 0.01, n)}, index=idx)


def test_lookahead_canary():
    r = _random_returns()
    legit = np.sign(r["X"]).to_frame("X")                 # known at today's close, traded for tomorrow
    cheat = np.sign(r["X"].shift(-1)).fillna(0).to_frame("X")   # peeks at tomorrow
    sr_legit = metrics.perf(backtest.run(r, legit, cost_bps=0).returns.iloc[1:])["sharpe"]
    sr_cheat = metrics.perf(backtest.run(r, cheat, cost_bps=0).returns.iloc[1:])["sharpe"]
    assert abs(sr_legit) < 1.0          # no edge on a random walk
    assert sr_cheat > 10                # the engine would expose a peeking signal immediately


def test_costs_are_exact():
    idx = pd.bdate_range("2024-01-01", periods=101)
    r = pd.DataFrame({"X": 0.0}, index=idx)
    tg = pd.DataFrame({"X": [1.0 if i % 2 == 0 else 0.0 for i in range(101)]}, index=idx)
    res = backtest.run(r, tg, cost_bps=2.0, borrow_spread_bps=0)
    # every day trades the full position in or out: cost = 2bp of traded notional
    expected = 1.0
    pos = 0.0
    for i in range(101):
        target = expected * (1.0 if i % 2 == 0 else 0.0)
        expected -= abs(target - pos) * 2e-4
        pos = target
    assert abs(res.equity.iloc[-1] - expected) < 1e-12


def test_leverage_pays_cash_rate_plus_spread():
    idx = pd.bdate_range("2024-01-01", periods=253)
    r = pd.DataFrame({"X": 0.0}, index=idx)
    tg = pd.DataFrame({"X": 2.0}, index=idx)
    res = backtest.run(r, tg, cost_bps=0, cash_rate=0.04, borrow_spread_bps=100)
    # borrowed ~1x NAV for 252 days at 5%/252 per day
    assert abs(res.equity.iloc[-1] - (1 - 0.05 / 252) ** 252) < 2e-3


def test_compounding_is_exact():
    idx = pd.bdate_range("2024-01-01", periods=11)
    r = pd.DataFrame({"X": 0.01}, index=idx)
    res = backtest.run(r, pd.DataFrame({"X": 1.0}, index=idx), cost_bps=0)
    assert abs(res.equity.iloc[-1] - 1.01 ** 10) < 1e-12


def test_probabilistic_and_deflated_sharpe():
    assert abs(metrics.probabilistic_sharpe(0.0, 1000, 0.0, 3.0) - 0.5) < 1e-12
    psr = metrics.probabilistic_sharpe(0.05, 2520, 0.0, 3.0)
    dsr = metrics.deflated_sharpe(0.05, 2520, 0.0, 3.0, n_trials=50, sr_var=0.02 ** 2)
    assert dsr < psr


def test_max_drawdown():
    eq = pd.Series([1.0, 1.2, 0.9, 1.5, 0.75])
    assert abs(metrics.max_drawdown(eq) - (-0.5)) < 1e-12
