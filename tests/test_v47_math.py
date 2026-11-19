"""v0.47: the math audit's fixes, each with the input that showed the defect.

    a Sharpe of rounding error   an all-cash record has no excess return: Sharpe 0, no probabilistic or deflated Sharpe
    the first day's fall         a drawdown is measured from the starting value, everywhere it is computed
    the AI scenario's sign       the AI leg is carried by the book's own return beyond the Nasdaq-100, not by a factor
                                 the book is short; the size does not read the scenario table
    the hedge is paid for        the hedge-policy table charges the overlay's financing, as the backtest does
    the drift is not hindsight   the pipeline's drawdown cap and Kelly check use cash plus a premium per unit of beta
    a missing input is an error  the cap solver raises on NaN; the call takes the last printed cash rate
    one as-of date               yields after the prices' last session are not this call's data; stale yields warn, then stop
    a gap keeps its move         an interior missing close no longer deletes the return across it
    small ones                   the plateau's Sharpe is over cash; the VIX roll costs a round trip a month; the share of
                                 days hedging is over days that have a state; hedges.json is priced at the run's levels
    one set of limits            book.py's constants are config.toml's
"""
from __future__ import annotations

import json
import math
import os
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import book as bk
from buildout import hedgebook, sensitivity, sizing_rules, vixhedge
from buildout.analytics import backtest, hedge, metrics, regime, robust_bt, sizing
from buildout.analytics.returns import book_returns, simple_returns

ROOT = Path(__file__).resolve().parents[1]


def _cut(prices: dict, day) -> dict:
    return {k: v[pd.to_datetime(v["date"]) <= pd.Timestamp(day)] for k, v in prices.items()}


@pytest.fixture(scope="module")
def world():
    prices, ust, _ = bk.synthetic(days=700)
    return prices, ust, bk.build(prices, ust)


@pytest.fixture(scope="module")
def report():
    from buildout import pipeline as pl
    from buildout.config import default_config
    cfg = default_config()
    cfg.data.source = "synthetic"
    inp = pl.load_inputs(cfg)
    return cfg, inp, pl.analyze(cfg, inp)


# ---------------------------------------------------------------- 1. a Sharpe of rounding error
def test_an_all_cash_record_has_no_sharpe_to_report():
    idx = pd.bdate_range("2018-07-31", periods=2086)
    rng = np.random.default_rng(0)
    rf = pd.Series(np.clip(0.03 + np.cumsum(rng.normal(0, 0.0005, len(idx))), 0, None), index=idx).round(4)
    rets = pd.DataFrame({"A": rng.normal(0.001, 0.02, len(idx)), "TLT": rng.normal(0, 0.01, len(idx))}, index=idx)
    res = backtest.run(rets, pd.DataFrame({"A": 0.0, "TLT": 0.0}, index=idx), cost_bps=2, cash_rate=rf, borrow_spread_bps=100,
                       rebalance_every=5, exec_lag=1)
    p = metrics.perf(res.returns, rf=rf)
    # the excess return is about 1e-17 a day: before, 0.10 annualized Sharpe and a 0.61 probabilistic Sharpe came out
    assert p["sharpe"] == 0.0 and p["sr_per_period"] == 0.0 and p["psr"] is None and p["excess_is_zero"] is True
    assert math.isnan(p["sortino"]) and p["cagr"] == pytest.approx(p["cash_cagr"], abs=1e-12)
    risky = metrics.perf(rets["A"], rf=rf)
    assert risky["excess_is_zero"] is False and 0 < risky["psr"] < 1 and risky["sharpe"] != 0.0


def test_the_pipelines_cash_row_carries_no_deflated_sharpe(report):
    _, _, rep = report
    st = rep["backtest"]["stats"]
    st = st if isinstance(st, dict) else {r["index"]: r for r in st}
    cash = st["Cash only"]
    assert cash["sharpe"] == 0.0 and cash["psr"] is None and cash["dsr"] is None and cash["sortino"] is None
    for k, v in st.items():
        if k != "Cash only":
            assert v["psr"] is not None and v["dsr"] is not None and v["dsr"] <= v["psr"] + 1e-12, k


# ---------------------------------------------------------------- 2. the first day's fall
def test_a_fall_on_the_first_day_is_a_drawdown_everywhere():
    idx = pd.bdate_range("2024-01-02", periods=3)
    r = pd.Series([-0.2, 0.05, 0.01], index=idx)
    assert metrics.perf(r)["max_drawdown"] == pytest.approx(-0.2)                       # was 0.0
    assert metrics.max_drawdown((1 + r).cumprod()) == pytest.approx(0.0)                # a bare equity series has no start
    assert metrics.max_drawdown((1 + r).cumprod(), start=1.0) == pytest.approx(-0.2)
    d = bk.drawdowns(r, r)
    assert d["max"] == pytest.approx(0.2) and d["nasdaq_max"] == pytest.approx(0.2) and d["peak"] == str(idx[0].date()) and d["trough"] == str(idx[0].date())
    assert vixhedge._dd(r) == pytest.approx(0.2)
    assert robust_bt._max_dd(np.array([[-0.2, 0.05, 0.01], [0.05, -0.1, 0.0]])) == pytest.approx([-0.2, -0.1])
    up = pd.Series([0.1, -0.5, 0.2, -0.1], index=pd.bdate_range("2024-01-02", periods=4))
    assert bk.drawdowns(up, up)["max"] == pytest.approx(0.5) and metrics.perf(up)["max_drawdown"] == pytest.approx(-0.5)   # a later peak is unchanged
    flat = pd.Series([0.01, 0.02, 0.0], index=idx)
    assert bk.drawdowns(flat, flat)["max"] == 0.0 and bk.drawdowns(flat, flat)["now"] == 0.0


def test_the_sizing_rules_record_counts_its_first_day():
    idx = pd.bdate_range("2020-01-01", "2020-06-30")
    rng = np.random.default_rng(4)
    r = pd.Series(rng.normal(0.001, 0.004, len(idx)), index=idx)
    rule = sizing_rules.HEADLINE
    first = sizing_rules.exposure_path(r, rule).first_valid_index()
    r.loc[first] = -0.30                                                                # the record's first day is a crash
    t = sizing_rules.test_rule(r, pd.Series(0.0, index=idx), rule)
    assert t["from"] == str(first.date()) and t["maxdd_hold"] >= 0.30 - 1e-12           # was the small falls after it


# ---------------------------------------------------------------- 3. the AI scenario's sign
def test_the_ai_leg_has_the_sign_of_the_ai_move(world):
    _, _, o = world
    L = o["scenario_loadings"]["book"]
    assert set(L) == {"market", "ai", "rates"} and 0.9 < L["ai"] < 1.1 and 0.9 < L["market"] < 1.1 and abs(L["rates"]) < 0.1
    assert isinstance(o["scenarios_method"], str) and "book's own daily return less QQQ" in o["scenarios_method"]
    rows = {r["scenario"]: r for r in o["scenarios"]}
    for r in rows.values():
        assert r["legs"]["nasdaq"] + r["legs"]["ai"] + r["legs"]["rates"] == pytest.approx(r["book"], abs=5e-6)
        assert r["ai_vs_nasdaq"] == r["semis_vs_nasdaq"]                                # the old key is the same input
        assert r["legs"]["ai"] * r["ai_vs_nasdaq"] > 0, "the AI leg moves the book the way the AI names move"
        assert r["legs"]["nasdaq"] * r["nasdaq"] > 0
    dig, melt = rows["AI capex digestion (growth scare)"], rows["AI melt-up, yields up"]
    assert dig["book"] < dig["legs"]["nasdaq"] < 0, "an AI sell-off is worse for an AI book than the Nasdaq leg alone"
    assert melt["book"] > melt["legs"]["nasdaq"] > 0, "and an AI rally is better"
    assert dig["book"] == pytest.approx(-0.30, abs=0.03) and melt["book"] == pytest.approx(0.25, abs=0.03)


def test_the_size_does_not_read_the_scenario_table(world, monkeypatch):
    prices, ust, o = world
    real = bk.scenario_betas
    monkeypatch.setattr(bk, "scenario_betas", lambda R, F, rb, halflife=bk.BETA_HL: real(R, F, rb, halflife).assign(ai=-3.0, market=7.0))
    o2 = bk.build(prices, ust)
    assert o2["scenarios"] != o["scenarios"]
    for k in ("size", "binding", "sizes", "keep_names_hedge", "frontier", "tail", "risk", "exposure", "betas", "hedges"):
        assert o2[k] == o[k], k


# ---------------------------------------------------------------- 4. the hedge is paid for
def test_a_hedge_that_earns_cash_adds_nothing_once_it_is_financed():
    idx = pd.bdate_range("2020-01-01", periods=1000)
    book = pd.Series(np.random.default_rng(0).normal(0, 0.01, 1000), index=idx)
    cashlike = pd.Series(0.04 / 252, index=idx)                                         # the "hedge" earns exactly cash
    ratios = pd.DataFrame({"none": 0.0, "static": 0.30}, index=idx)
    free = hedge.evaluate_policies(book, cashlike, ratios)
    assert free.loc["static", "ann_return_drag"] == pytest.approx(0.30 * 0.04, rel=1e-3)        # the old reading: a free 1.2% a year
    assert free.loc["static", "ann_financing"] == 0.0
    paid = hedge.evaluate_policies(book, cashlike, ratios, rf=0.04)
    assert paid.loc["static", "ann_return_drag"] == pytest.approx(0.0, abs=1e-9)
    spread = hedge.evaluate_policies(book, cashlike, ratios, rf=pd.Series(0.04, index=idx), borrow_spread_bps=100)
    assert spread.loc["static", "ann_return_drag"] == pytest.approx(-0.30 * 0.01, rel=1e-3)
    assert spread.loc["static", "ann_financing"] == pytest.approx(0.30 * 0.05, rel=1e-3)
    assert spread.loc["none", "ann_return_drag"] == 0.0 and spread.loc["none", "ann_financing"] == 0.0
    # and that is what the backtester charges for the same overlay
    rets = pd.DataFrame({"B": book, "TLT": cashlike})
    on = backtest.run(rets, pd.DataFrame({"B": 1.0, "TLT": 0.3}, index=idx), cost_bps=0, cash_rate=0.04, borrow_spread_bps=100)
    off = backtest.run(rets, pd.DataFrame({"B": 1.0, "TLT": 0.0}, index=idx), cost_bps=0, cash_rate=0.04, borrow_spread_bps=100)
    assert (on.returns.mean() - off.returns.mean()) * 252 == pytest.approx(spread.loc["static", "ann_return_drag"], abs=2e-4)


def test_the_pipelines_policy_table_is_after_financing(report):
    cfg, inp, rep = report
    rows = {r["index"]: r for r in rep["hedge"]["policies"]}
    assert rows["static"]["ann_financing"] == pytest.approx(0.30 * (float(inp.rf.mean()) + cfg.risk.financing_spread_bps / 1e4), rel=0.05)
    assert rows["none"]["ann_financing"] == 0.0 and "financed" in rep["hedge"]["financing"]
    for h, c in rep["hedge"]["candidates"].items():
        assert c["ann_financing"] > 0, h


# ---------------------------------------------------------------- 5. the drift is not hindsight
def test_the_pipelines_cap_uses_cash_plus_a_premium_per_unit_of_beta(report):
    cfg, inp, rep = report
    S = rep["summary"]
    rets = simple_returns(inp.prices.dropna(how="all"))
    book = book_returns(rets, cfg.universe.book).iloc[1:]
    d = pd.concat([book, rets[cfg.universe.market]], axis=1).dropna()
    beta = float(d.cov().iloc[0, 1] / d.iloc[:, 1].var())
    assert S["drift_beta"] == pytest.approx(beta, abs=1e-6) and S["drift"] == pytest.approx(S["rf"] + bk.EQUITY_PREMIUM * beta, abs=1e-6)
    vol = float(book.std() * math.sqrt(252))
    cap = sizing.max_leverage(S["drift"], vol, cfg.risk.max_drawdown, q=cfg.risk.drawdown_confidence, cash_rate=S["rf"],
                              borrow_spread=cfg.risk.financing_spread_bps / 1e4)
    assert S["drawdown_leverage_cap"] == pytest.approx(cap, abs=1e-6)
    assert S["kelly_leverage"] == pytest.approx(cfg.risk.kelly_fraction * (S["drift"] - S["rf"]) / vol ** 2, abs=1e-6)
    assert S["recommended_gross"] == pytest.approx(min(S["vol_target_scale"], S["drawdown_leverage_cap"], cfg.risk.max_gross), abs=1e-6)
    c = S["insample_mean_comparison"]                                                    # kept, labelled, and sizing nothing
    assert c["mu_shrunk"] == S["mu_shrunk"] and "comparison only" in c["note"]
    assert c["drawdown_leverage_cap"] == pytest.approx(sizing.max_leverage(S["mu_shrunk"], vol, cfg.risk.max_drawdown, cash_rate=S["rf"]), abs=1e-6)
    L = rep["stress"]["scenario_loadings"]                                               # the same scenario reading as book.json's
    assert 0.8 < L["ai"] < 1.2 and "basket including the name" in rep["stress"]["method"]
    dig = next(s for s in rep["stress"]["scenarios"] if s["scenario"].startswith("AI capex digestion") and s["hedge_ratio"] == 0.0)
    assert dig["book"] < -0.15 * L["market"]


# ---------------------------------------------------------------- 6. a missing input is an error
@pytest.mark.parametrize("kw", [{"mu": float("nan")}, {"sigma": float("nan")}, {"cash_rate": float("nan")}, {"sigma": -0.1}, {"max_dd": float("inf")}])
def test_the_cap_solver_refuses_what_is_not_a_number(kw):
    a = {"mu": 0.11, "sigma": 0.29, "max_dd": 0.25, "cash_rate": 0.04, **kw}
    with pytest.raises(ValueError, match="max_leverage"):                                # each of these used to return 0.0: hold nothing
        sizing.max_leverage(a["mu"], a["sigma"], a["max_dd"], cash_rate=a["cash_rate"])
    assert sizing.max_leverage(0.11, 0.29, 0.25, cash_rate=0.04) > 0.3


def test_a_blank_cash_rate_on_the_last_row_is_the_last_one_printed(world):
    prices, ust, o = world
    u = ust.copy()
    u.iloc[-1, u.columns.get_loc("DGS2")] = np.nan
    o2 = bk.build(prices, u)                                                            # was: size 0.0, binding drawdown_cap, cash_rate None
    assert o2["limits"]["cash_rate"] == pytest.approx(float(ust["DGS2"].iloc[-2]) / 100, abs=1e-6)
    assert o2["limits"]["cash_rate_date"] == str(ust.index[-2].date()) and any("2-year yield is blank" in x for x in o2["warnings"])
    assert o2["size"] == pytest.approx(o["size"], rel=0.02) and o2["size"] > 0.2 and o2["binding"] == o["binding"]
    s2 = sensitivity.build(prices, u)                                                   # the block beside the call reads the same rate
    assert s2["cash_rate"] == pytest.approx(o2["limits"]["cash_rate"], abs=1e-6) and s2["size"] == pytest.approx(o2["size"], abs=1e-6)
    u.iloc[-6:, u.columns.get_loc("DGS2")] = np.nan
    with pytest.raises(ValueError, match="DGS2"):
        bk.build(prices, u)


# ---------------------------------------------------------------- 7. one as-of date
def test_yields_after_the_prices_last_session_are_not_this_calls_data(world):
    prices, ust, o = world
    day = pd.to_datetime(prices["qqq"]["date"]).iloc[-3]
    early = _cut(prices, day)
    a = bk.build(early, ust.loc[:day])                                                  # run that evening
    later = ust.copy()
    later.iloc[-2:] = later.iloc[-2:] + 1.5                                             # two newer rows post, 150bp higher
    b = bk.build(early, later)                                                          # run again once they have
    assert a["asof"] == b["asof"] == str(day.date()) and b["treasury_to"] == str(day.date()) and b["treasury_rows_after_asof"] == 2
    for k in ("size", "sizes", "binding", "limits", "keep_names_hedge", "frontier", "scenarios", "correlation"):
        assert a[k] == b[k], k
    assert a["treasury_rows_after_asof"] == 0 and a["warnings"] == [] and o["treasury_lag_bdays"] == 0


def test_stale_yields_warn_then_stop(world):
    prices, ust, o = world
    one = bk.build(prices, ust.iloc[:-1])                                               # a bond-market holiday on which stocks traded
    assert one["treasury_lag_bdays"] == 1 and one["warnings"] == []
    two = bk.build(prices, ust.iloc[:-2])
    assert two["treasury_lag_bdays"] == 2 and len(two["warnings"]) == 1 and "2 sessions before the prices" in two["warnings"][0]
    assert two["size"] == pytest.approx(o["size"], rel=0.05)
    with pytest.raises(ValueError, match="Treasury yields end"):
        bk.build(prices, ust.iloc[:-(bk.TREASURY_LAG_MAX + 1)])


def _treasury_csv(rows):
    return ("Date,2 Yr,10 Yr,20 Yr\n" + "\n".join(f"{d},{a},{b},{c}" for d, a, b, c in rows)).encode()


def test_the_treasury_cache_is_refreshed_after_a_day(tmp_path, monkeypatch):
    import buildout.data.http as http
    year = pd.Timestamp.now().year
    calls = []

    def get(url, timeout=45, **kw):
        calls.append(url)
        y = int(url.split("field_tdr_date_value=")[1].split("&")[0])
        return _treasury_csv([(f"01/05/{y}", 4.0, 4.5, 5.0), (f"01/06/{y}", 4.1, 4.6, 5.1)] + ([(f"01/07/{y}", 4.2, 4.7, 5.2)] if len(calls) > 1 and y == year else []))

    monkeypatch.setattr(http, "get", get)
    p = tmp_path / "ust.json"
    f1 = bk.treasury(p, start_year=year)                                                # no file: downloaded
    assert len(calls) == 1 and len(f1) == 2 and bk.TREASURY_STATUS["source"] == "download"
    f2 = bk.treasury(p, start_year=year)                                                # a fresh file: read, not downloaded
    assert len(calls) == 1 and f2.equals(f1) and bk.TREASURY_STATUS["source"] == "cache"
    old = p.stat().st_mtime - 2 * 86400
    os.utime(p, (old, old))
    f3 = bk.treasury(p, start_year=year)                                                # a day old: the last year is read again and merged
    assert len(calls) == 2 and len(f3) == 3 and float(f3["DGS20"].iloc[-1]) == 5.2 and bk.TREASURY_STATUS["source"] == "download"
    os.utime(p, (old, old))
    monkeypatch.setattr(http, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the Treasury is down")))
    f4 = bk.treasury(p, start_year=year)                                                # the refresh fails: the old file, and it says so
    assert f4.equals(f3) and "refresh failed" in bk.TREASURY_STATUS["error"]
    with pytest.raises(RuntimeError):                                                   # with no file at all there is nothing to fall back on
        bk.treasury(tmp_path / "none.json", start_year=year)


# ---------------------------------------------------------------- 8. a gap keeps its move
def test_an_interior_missing_close_keeps_the_move_across_it():
    idx = pd.bdate_range("2024-01-01", periods=6)
    px = pd.DataFrame({"A": [100, 101, np.nan, 111.1, 112, np.nan], "B": [np.nan, 50, 50, 51, 51, 52.0]}, index=idx)
    r = simple_returns(px)
    assert (1 + r["A"].fillna(0)).prod() - 1 == pytest.approx(0.12)                    # was 1.8%: the 10% across the gap was dropped
    assert r["A"].iloc[2] == 0.0 and r["A"].iloc[3] == pytest.approx(111.1 / 101 - 1)
    assert np.isnan(r["A"].iloc[5]), "after a name's last close there is still nothing"
    assert np.isnan(r["B"].iloc[0]) and np.isnan(r["B"].iloc[1]), "and nothing before its first"
    whole = pd.DataFrame({"A": [100.0, 101, 103, 102]}, index=idx[:4])
    assert simple_returns(whole).equals(whole.pct_change(fill_method=None))             # a record with no gap is untouched
    b = book_returns(r, {"A": 0.5, "B": 0.5})
    assert b.iloc[3] == pytest.approx(0.5 * (111.1 / 101 - 1) + 0.5 * 0.02)


# ---------------------------------------------------------------- 9. small ones
def test_the_plateau_sharpe_is_over_cash():
    idx = pd.bdate_range("2020-01-01", periods=1500)
    rng = np.random.default_rng(2)
    F = pd.DataFrame({"a": rng.normal(0.0006, 0.01, 1500), "b": rng.normal(0.0004, 0.01, 1500)}, index=idx)
    rf = pd.Series(0.05, index=idx)
    raw, net = robust_bt.plateau(F, "a"), robust_bt.plateau(F, "a", rf=rf)
    ex = F["a"] - 0.05 / 252
    assert net["chosen_sharpe"] == pytest.approx(ex.mean() / ex.std() * math.sqrt(252)) and net["sharpe"] == "excess over cash"
    assert raw["chosen_sharpe"] - net["chosen_sharpe"] == pytest.approx(0.05 / (F["a"].std() * math.sqrt(252)), rel=1e-6)
    blk = robust_bt.robustness_block({"a": F["a"], "b": F["b"]}, rf, F, "a", base="b", draws=20)
    assert blk["plateau"]["chosen_sharpe"] == pytest.approx(net["chosen_sharpe"])        # the block passes the rate through
    assert blk["bootstrap"]["variants"]["a"]["sharpe"][1] == pytest.approx(net["chosen_sharpe"], abs=1.0)


def _carver(prices: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"price": prices, "m_price": 202001.0, "carry": np.nan, "m_carry": np.nan, "forward": np.nan, "m_forward": np.nan})


def test_the_vix_future_pays_a_round_trip_each_month():
    from buildout import futures as fu
    idx = pd.bdate_range("2019-12-02", "2020-06-30")
    rng = np.random.default_rng(1)
    vx = _carver(pd.Series(20 * np.exp(np.cumsum(rng.normal(0, 0.04, len(idx)))), index=idx))
    nq = _carver(pd.Series(9000 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))), index=idx))
    vix = pd.Series(18 + rng.normal(0, 1, len(idx)), index=idx)
    M = vixhedge.monthly({"NQ": nq}, vx, vix)
    gross = (1 + fu.front_returns(vx).dropna()).resample("ME").prod() - 1
    assert np.allclose(M["vix_fut"], gross.reindex(M.index) - vixhedge.COST_BP / 1e4)    # was a twelfth of it
    F0 = vx["price"].resample("ME").last().shift(1).reindex(M.index)
    pay = np.maximum(F0 * (1 + gross.reindex(M.index)) - vixhedge.STRIKE * F0, 0)      # the option pays on the future's price, not on the holder's net return
    prem = vixhedge._black76_call(F0, vixhedge.STRIKE * F0, 1 / 12, vixhedge.VOV) * (1 + vixhedge.OPTION_SPREAD / 2)
    assert np.allclose(M["vix_call"], (pay * (1 - vixhedge.OPTION_SPREAD / 2) - prem) / F0)


def test_the_share_of_days_hedging_is_over_days_that_have_a_state(world):
    prices, ust, o = world
    P = bk.panel(prices, ust)
    rb = bk.book_returns(P["R"], pd.Series(bk.BOOK))
    d = pd.concat([rb, P["F"]["rates"]], axis=1).dropna()
    lab = regime.classify(regime.ewm_corr(d["book"], d["rates"], bk.COV_HL))
    assert lab.isna().sum() >= bk.COV_HL - 1                                            # the warm-up has no state
    want = float((lab.dropna() == regime.HEDGING).mean())
    assert o["correlation"]["share_days_hedging"] == pytest.approx(want, abs=1e-6)
    assert want > float((lab == regime.HEDGING).mean())                                 # the old figure counted the warm-up as not hedging


def test_hedges_json_is_priced_at_the_runs_market_levels(tmp_path):
    from buildout import engine
    macro = {"latest": {"VIXCLS": 25.46, "VIXCLS_date": "2026-11-17", "DGS30": 5.46, "DGS30_date": "2026-11-16", "DGS3MO": 4.34, "DGS3MO_date": "2026-11-16"},
             "vol": {"latest": {"ndx": {"implied": 34.44, "date": "2026-11-17"}}}}
    P, rec = hedgebook.market_params(macro)
    assert P == {"vix": 25.46, "index_vol": 34.44, "y30": pytest.approx(0.0546), "rf": pytest.approx(0.0434)}
    assert not any(v["assumed"] for v in rec.values()) and rec["vix"]["date"] == "2026-11-17"
    live, default = hedgebook.option_costs(hedgebook._P(P)), hedgebook.option_costs(hedgebook._P(None))
    assert live["vix_spread"] > 2 * default["vix_spread"]                               # 4.19 against 1.70 points: the spread is at the money at a VIX of 25
    assert live["put_spread"] > default["put_spread"]
    P0, rec0 = hedgebook.market_params(None)
    assert P0 == {} and all(v["assumed"] for v in rec0.values()) and rec0["vix"]["value"] == hedgebook.DEFAULTS["vix"]
    bad, recb = hedgebook.market_params({"latest": {"VIXCLS": float("nan"), "DGS30": 546.0}})
    assert bad == {} and recb["vix"]["assumed"] and recb["y30"]["assumed"]             # a print outside its limits is not used
    (tmp_path / "with").mkdir()
    (tmp_path / "without").mkdir()
    (tmp_path / "with" / "macro.json").write_text(json.dumps(macro))
    engine._hedges(tmp_path / "with")
    engine._hedges(tmp_path / "without")
    a, b = (json.loads((tmp_path / k / "hedges.json").read_text()) for k in ("with", "without"))
    price = lambda o: next(c["price"] for c in o["catalog"] if c["id"] == "vix_calls")  # noqa: E731
    assert a["inputs_assumed"] is False and a["inputs"]["vix"]["value"] == 25.46 and price(a) == pytest.approx(float(live["vix_spread"]), abs=1e-6)
    assert b["inputs_assumed"] is True and price(b) == pytest.approx(float(default["vix_spread"]), abs=1e-6)
    assert isinstance(a["assumed"], dict) and "vix_vol" in a["assumed"]                 # the modelling assumptions keep their key
    assert next(e for e in engine.REGISTRY if e.name == "hedges").reads == ["macro.json"]


# ---------------------------------------------------------------- 10. one set of limits
def test_the_books_constants_are_config_tomls():
    """book.py sizes the call from its own constants and never reads config.toml; the pipeline reads config.toml.
    If the two drift apart the page shows two books under one name."""
    raw = tomllib.loads((ROOT / "config.toml").read_text())
    from buildout.config import load_config
    cfg = load_config(ROOT / "config.toml")
    assert cfg.universe.book == bk.BOOK and sum(bk.BOOK.values()) == pytest.approx(1.0)
    assert cfg.universe.priors == bk.PRIORS
    assert cfg.risk.target_vol == bk.VOL_TARGET and cfg.risk.max_drawdown == bk.MAX_DD and cfg.risk.max_gross == bk.MAX_GROSS
    assert cfg.risk.beta_halflife == bk.BETA_HL and cfg.risk.corr_halflife == bk.COV_HL
    assert cfg.risk.drawdown_confidence == sensitivity.Q == 0.95
    # the expected-shortfall budget has no key in config.toml today: it lives in book.py alone. The day one is added
    # it must be this number; until then the number is pinned here so a change is a decision, not an edit.
    assert raw.get("risk", {}).get("es_budget", bk.ES_BUDGET) == bk.ES_BUDGET == 0.12
    assert bk.TREASURY_LAG_OK < bk.TREASURY_LAG_MAX
