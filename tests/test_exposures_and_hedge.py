"""Known-answer tests: the engine must recover betas and regimes that were planted in the synthetic market."""
import numpy as np
import pandas as pd

from buildout.analytics import hedge, regime
from buildout.analytics.exposures import ewls_betas, latest_betas, shrink
from buildout.analytics.returns import book_returns, simple_returns


def test_recovers_planted_betas(world):
    rets = simple_returns(world.prices)
    for name in ["MSFT", "NVDA", "TSLA"]:
        b = ewls_betas(rets[name], world.factors, halflife=100_000).iloc[-1]
        truth = world.true_betas.loc[name]
        assert abs(b["market"] - truth["market"]) < 0.10
        assert abs(b["ai"] - truth["ai"]) < 0.15
        assert abs(b["rates"] - truth["rates"]) < 0.15


def test_short_history_name_is_shrunk_toward_prior(world):
    rets = simple_returns(world.prices)
    betas = latest_betas(rets, world.factors, ["MSFT", "TSLA", "SPCX"], halflife=126, priors={"SPCX": "TSLA"})
    assert betas.loc["SPCX", "n_obs"] < 100
    raw = ewls_betas(rets["SPCX"], world.factors, halflife=126, min_obs=20).dropna().iloc[-1]["market"]
    lo, hi = sorted([raw, betas.loc["TSLA", "market"]])
    assert lo - 1e-9 <= betas.loc["SPCX", "market"] <= hi + 1e-9
    assert shrink(2.0, 0, 1.0) == 1.0


def test_regime_correlation_signs_match_truth(world):
    rets = simple_returns(world.prices)
    d = pd.concat({"m": rets["QQQ"], "b": rets["TLT"], "s": world.regime}, axis=1).dropna()
    by = d.groupby("s").apply(lambda x: x["m"].corr(x["b"]))
    assert by["hedging"] < -0.35 and by["amplifying"] > 0.35


def test_regime_detector_tracks_truth(world):
    rets = simple_returns(world.prices)
    lab = regime.classify(regime.ewm_corr(rets["QQQ"], rets["TLT"], 63))
    d = pd.concat({"est": lab, "true": world.regime}, axis=1).dropna()
    d = d[d["est"] != "neutral"]
    assert (d["est"] == d["true"]).mean() > 0.75


def test_regime_gated_hedge_beats_static_and_tail_signs(world):
    rets = simple_returns(world.prices)
    book = book_returns(rets, {n: 1 / 9 for n in world.true_betas.index}).iloc[1:]
    tlt = rets["TLT"].reindex(book.index)
    pol = hedge.policies(book, tlt, 63, static=0.30)
    ev = hedge.evaluate_policies(book, tlt, pol)
    assert ev.loc["regime_gated", "variance_reduction"] > ev.loc["static", "variance_reduction"]
    by = hedge.by_regime(book, tlt, world.regime.reindex(book.index))
    assert by.loc["hedging", "tail_hedge_avg"] > 0 > by.loc["amplifying", "tail_hedge_avg"]


def test_futures_contract_math():
    # $1m of TLT-like duration 15.5 hedged with a contract of $150/bp DV01 -> 1e6*15.5*1e-4/150 contracts
    assert abs(hedge.futures_contracts(1e6, 15.5, 150.0) - 1e6 * 15.5e-4 / 150) < 1e-12
    idx = pd.bdate_range("2025-01-01", periods=200)
    dy = pd.Series(np.random.default_rng(0).normal(0, 0.05, 200), index=idx).cumsum() + 5
    fut = 110 - (dy - 5) * 0.15 / 0.01 * 1  # 0.15 points per bp -> $150/bp at $1000/point
    assert abs(hedge.empirical_dv01(fut, dy) - 150.0) < 1e-6
