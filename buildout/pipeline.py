"""End-to-end run: data -> exposures -> regime -> hedge -> sizing -> risk -> stress -> backtest -> report."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .analytics import backtest, hedge, metrics, regime, risk, signals, sizing, stress, vol
from .analytics.exposures import latest_betas
from .analytics.returns import book_returns, factor_returns, simple_returns
from .config import Config
from .jsonout import clean as _clean, series as _series, write as _write


@dataclass
class Inputs:
    prices: pd.DataFrame            # adjusted closes (total return)
    yields: pd.DataFrame | None     # percent, e.g. DGS10, DGS30
    rf: pd.Series                   # annualized cash rate, decimal
    label: str                      # "synthetic" or the data vendor
    infl36: pd.Series | None = None # 36-month annualized CPI inflation, indexed by the day it was PUBLISHED
    adjustments: dict | None = None # how corporate actions were handled (vendor factors, or the public fallback)


def load_inputs(cfg: Config) -> Inputs:
    d, u = cfg.data, cfg.universe
    if d.source == "synthetic":
        from .data.synthetic import simulate
        w = simulate(list(u.book), tuple(u.hedges), u.market)
        return Inputs(w.prices, w.yields, w.rf, "synthetic")
    from .data.store import Cache
    cache = Cache(d.cache_dir)
    if d.source == "databento":
        from .data.databento_source import DatabentoSource
        src = DatabentoSource(equities_dataset=d.equities_dataset, futures_dataset=d.futures_dataset, cache=cache)
        guard_cost(src, u.equities, d)
        prices = src.adjusted_closes(u.equities, d.start, d.end, adjustments=d.adjustments)
        adj = {"source": src.adjustments_used, "vendor_error": src.adjustments_error}
    elif d.source == "csv":
        from .data.csv_source import load_prices
        prices = load_prices(d.csv_path).loc[d.start:d.end]
        adj = {"source": "as supplied (csv)", "vendor_error": None}
    else:
        raise ValueError(f"unknown data.source {d.source!r}")
    yields, rf = None, pd.Series(0.04, index=prices.index)
    if d.use_fred:
        from .data.fred_source import FredSource
        fred = FredSource(cache).series(["DGS10", "DGS30", "DGS7", "DGS20", d.risk_free_series], d.start, d.end)
        yields = fred[["DGS10", "DGS30"]]
        if adj["source"] == "public":
            from .data.corporate_actions import PRICE_ONLY_NOTE, add_bond_income
            prices, income = add_bond_income(prices, fred)
            adj.update({"note": PRICE_ONLY_NOTE, "bond_income": income, "evidence": "Estimated"})
        rf = (fred[d.risk_free_series] / 100).reindex(prices.index).ffill()
        infl36 = None
        try:
            cpi = FredSource(cache).series(["CPIAUCSL"], "2010-01-01", d.end)["CPIAUCSL"].dropna()
            infl36 = published_infl36(cpi)
        except Exception:                  # the inflation gate is then reported unavailable, never assumed
            infl36 = None
        return Inputs(prices, yields, rf, d.source, infl36, adj)
    if adj["source"] == "public":
        adj.update({"note": "public split table; no FRED, so bond-fund income is missing and the hedge leg is price only", "evidence": "Estimated"})
    return Inputs(prices, yields, rf, d.source, adjustments=adj)


def guard_cost(src, symbols, d) -> None:
    """Spend guard: price the pull before making it, and refuse above the configured ceiling."""
    try:
        usd = float(src.estimate_cost(symbols, d.start, d.end))
    except Exception as exc:              # an estimate that cannot be made is a refusal, not a free pass
        raise RuntimeError(f"Databento cost estimate failed ({exc}); refusing an unpriced pull") from exc
    if usd > d.max_cost_usd:
        raise RuntimeError(f"Databento estimate ${usd:,.2f} exceeds max_cost_usd ${d.max_cost_usd:,.2f}; raise it in config.toml to proceed")


def published_infl36(cpi: pd.Series, lag_days: int = 45) -> pd.Series:
    """36-month annualized inflation, re-dated to when the policy could have known it.

    BLS publishes month M's CPI about two weeks into month M+1; a reading dated M-01 is usable from M-01 + 45 days.
    """
    m = cpi.resample("MS").last()
    avg = (m / m.shift(36)) ** (1 / 3) - 1
    avg.index = avg.index + pd.Timedelta(days=lag_days)
    return avg.dropna().rename("infl36")


def book_targets(prices: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    """Model-book weights per day; a name that has not listed yet hands its weight to the others pro rata."""
    w = pd.Series(weights, dtype=float)
    live = prices[w.index].notna()
    wt = live.mul(w, axis=1)
    return wt.mul(w.sum() / wt.sum(axis=1), axis=0)


def factor_cov(factors: pd.DataFrame, betas: pd.DataFrame, halflife: int) -> pd.DataFrame:
    """Factor-model covariance (daily): B F B' + D. Works for short-history names, unlike a sample matrix."""
    F = risk.ewma_cov(factors.dropna(), halflife)
    B = betas[list(factors.columns)].astype(float)
    D = np.diag((betas["resid_vol_ann"].astype(float).fillna(0.3) ** 2 / 252).to_numpy())
    return pd.DataFrame(B.to_numpy() @ F.to_numpy() @ B.to_numpy().T + D, index=betas.index, columns=betas.index)


def analyze(cfg: Config, inp: Inputs, line: float | None = None, line_status: str = "unavailable") -> dict:
    """line / line_status come from the research step (research.json); without them the inflation gate is
    reported as unavailable and the hedge policy runs on the correlation state alone, saying so."""
    u, rp = cfg.universe, cfg.risk
    prices = inp.prices.dropna(how="all")
    rets = simple_returns(prices)
    tlt = u.hedges[0]
    names = list(u.book)
    fac = factor_returns(rets, u.market, u.ai_factor or names, tlt)
    book = book_returns(rets, u.book).iloc[1:]
    hedge_r = rets[tlt].reindex(book.index)

    # 1. Regime: is the long bond hedging this book right now?
    corr = regime.ewm_corr(book, hedge_r, rp.corr_halflife)
    reg = regime.classify(corr)
    shocks = regime.shock_table(book, hedge_r, rp.tail_quantile, by=reg)

    # 2. Hedge policies, judged out of sample
    pol = hedge.policies(book, hedge_r, rp.corr_halflife, static=0.30, max_ratio=rp.max_hedge_ratio)
    from . import policy as P
    mv = hedge.min_var_ratio(book, hedge_r, rp.corr_halflife)
    gate_ok = line_status == "ok" and line is not None
    pol["regime_gated"] = P.tlt_ratio_series(corr, mv, inp.infl36 if gate_ok else None, line if gate_ok else None,
                                             rp.max_hedge_ratio)     # the one hedge policy: recommendation = backtest
    pol_eval = hedge.evaluate_policies(book, hedge_r, pol, rp.tail_quantile)
    reg_stats = hedge.by_regime(book, hedge_r, reg, rp.tail_quantile)
    candidates = {}
    for h in u.hedges:
        ratio = hedge.min_var_ratio(book, rets[h].reindex(book.index), rp.corr_halflife).clip(0, rp.max_hedge_ratio)
        candidates[h] = hedge.evaluate_policies(book, rets[h].reindex(book.index), ratio.to_frame("min_var"),
                                                rp.tail_quantile).iloc[0].to_dict()

    # 3. Exposures (short-history names shrink toward their prior)
    ai_names = u.ai_factor or names
    betas = latest_betas(rets, fac, names, rp.beta_halflife, rp.min_obs, u.priors,
                         factor_fn=lambda n: factor_returns(rets, u.market, ai_names, tlt, exclude=n))

    # 4. Volatility and sizing
    book_vol = float(vol.ewma_vol(book).iloc[-1])
    g = vol.garch11(book)
    scale_now = float(sizing.vol_scale(book_vol, rp.target_vol, rp.max_gross))
    cov = factor_cov(fac, betas, rp.corr_halflife)
    w_book = pd.Series(u.book, dtype=float)
    rc = risk.risk_contributions(w_book, cov)
    erc_w = sizing.erc(cov) * w_book.sum()
    years = len(book) / 252
    mu_hat = float(book.mean() * 252)
    rf_now = float(inp.rf.iloc[-1])
    mu_shrunk = float(sizing.shrink_mean(pd.Series([mu_hat]), years, rp.mean_prior_years, prior=rf_now + 0.04).iloc[0])
    long_run_vol = float(book.std() * np.sqrt(252))
    kelly_lev = rp.kelly_fraction * (mu_shrunk - rf_now) / long_run_vol ** 2
    dd_lev = sizing.max_leverage(mu_shrunk, long_run_vol, rp.max_drawdown, q=rp.drawdown_confidence,
                                 cash_rate=rf_now, borrow_spread=rp.financing_spread_bps / 1e4)
    # Risk limits set the size; Kelly is the edge check: what excess return would justify this size?
    size_dec = P.sizing_decision(scale_now, dd_lev, rp.max_gross, kelly_lev, long_run_vol, rp.kelly_fraction)
    lev_now = float(size_dec["scale"])
    edge_needed = lev_now * long_run_vol ** 2 / rp.kelly_fraction

    # 5. Risk: VaR / CVaR
    var_h, cvar_h = risk.historical_var(book, 0.99)
    var_f, cvar_f = risk.fhs_var(rets[names].reindex(book.index), w_book, q=0.99)

    # 6. Stress
    eq_curve = (1 + book).cumprod()
    episode_px = pd.concat([prices[[u.market] + u.hedges], eq_curve.rename("BOOK")], axis=1)
    episodes = stress.episode_returns(episode_px)
    h_now = float(pol["regime_gated"].dropna().iloc[-1]) if pol["regime_gated"].notna().any() else 0.0
    state_now = P.hedge_state(corr.to_numpy())[-1]
    infl_now = float(inp.infl36.dropna().iloc[-1]) if inp.infl36 is not None and inp.infl36.notna().any() else None
    hedge_dec = P.tlt_decision(state_now, infl_now, line, line_status, float(mv.dropna().iloc[-1]) if mv.notna().any() else None,
                               rp.max_hedge_ratio)
    limits = P.portfolio_limits(lev_now, h_now, 0.0, getattr(rp, "max_total_gross", 2.0))
    y0 = float(inp.yields["DGS30"].dropna().iloc[-1] / 100) if inp.yields is not None else 0.0558
    scen = [stress.scenario_pnl(w_book, betas, h, s, y0=y0) | {"hedge_ratio": h}
            for s in stress.SCENARIOS for h in (0.0, 0.3, h_now)]

    # 7. Backtest four policies on the same book
    base = book_targets(prices, u.book).reindex(rets.index)
    vol_scale_ts = sizing.vol_scale(vol.ewma_vol(book), rp.target_vol, rp.max_gross).reindex(rets.index)
    variants = {
        "Book, unhedged": (base, None),
        "Book + 30% TLT always": (base, pd.Series(0.30, index=rets.index)),
        "Book + regime-gated TLT": (base, pol["regime_gated"].reindex(rets.index)),
        "Vol-targeted + regime-gated TLT": (base.mul(vol_scale_ts, axis=0), pol["regime_gated"].reindex(rets.index)),
    }
    variants["Cash only"] = (base * 0.0, None)        # the cash-reduction baseline every variant must beat
    built = {}
    for label, (w, hr) in variants.items():
        tg = w.copy()
        tg[tlt] = 0.0 if hr is None else hr * w.sum(axis=1)
        built[label] = tg.loc[book.index[0]:].dropna(how="any")
    # one evaluation window for every variant: from the first day ALL of them have a valid target (warm-up excluded)
    start = max(tg.index[0] for tg in built.values())
    bt, curves, final_navs = {}, {}, {}
    for label, tg in built.items():
        tg = tg.loc[start:]
        res = backtest.run(rets.loc[start:], tg, cost_bps=rp.cost_bps, cash_rate=inp.rf,
                           borrow_spread_bps=rp.financing_spread_bps, rebalance_every=5, exec_lag=1)
        bt[label] = metrics.perf(res.returns, rf=inp.rf) | {
            "avg_turnover_ann": float(res.turnover.sum() / max(len(res.turnover) / 252, 1e-9)),
            "cost_drag_ann": float(res.costs.sum() / max(len(res.costs) / 252, 1e-9)),
            "financing_ann": float(res.financing.sum() / max(len(res.financing) / 252, 1e-9)),
            "nav_final": float(res.equity.iloc[-1]), "start": start.strftime("%Y-%m-%d")}
        curves[label] = _series(res.equity)
        final_navs[label] = res
    # count the whole search, not just the variants on display: hedge policies, candidate hedges, variants
    n_trials = len(bt) + len(pol.columns) + len(u.hedges)
    srs = [v["sr_per_period"] for k, v in bt.items() if k != "Cash only"]
    for v in bt.values():
        v["dsr"] = metrics.deflated_sharpe(v["sr_per_period"], v["n"], v["skew"], v["kurtosis"],
                                           n_trials=n_trials, sr_var=float(np.var(srs, ddof=1)) if len(srs) > 1 else 0.0)
    drift = final_navs["Book, unhedged"].weights.iloc[-1].drop(tlt, errors="ignore")

    # 7a. Robustness: would the backtest survive another history, and is the chosen hedge rule a peak or a plateau?
    from .analytics import robust_bt
    from .data.quality import screen as quality_screen
    ratio_fn = lambda en, ex: P.tlt_ratio_series(corr, mv, inp.infl36 if gate_ok else None, line if gate_ok else None,  # noqa: E731
                                                  rp.max_hedge_ratio, enter=en, exit=ex)
    family = robust_bt.rule_family(book, hedge_r, corr, mv, ratio_fn, rp.cost_bps, inp.rf)
    robustness = robust_bt.robustness_block({k: v.returns for k, v in final_navs.items() if k != "Cash only"}, inp.rf, family,
                                            "enter -0.10 exit +0.00 x1", base="Book, unhedged", draws=500)
    robustness["family_rules"] = int(family.shape[1])
    data_quality = quality_screen(prices)

    # 7b. The field manual's checks on the book itself: fat-tail shortfall, the hedge selector by regime, liquidity
    from . import buyside, microstructure
    tail = buyside.tail_risk(book)
    hedge_pick = buyside.hedge_selector(book, {h: rets[h].reindex(book.index) for h in u.hedges}, reg.reindex(book.index),
                                        weight=0.3, periods_per_year=252)
    liquidity = {t: microstructure.roll_spread(prices[t].dropna().tail(252)) / float(prices[t].dropna().tail(252).mean()) * 1e4
                 for t in names if t in prices and prices[t].dropna().size > 60}

    # 8. Can we forecast the book's next month? Walk-forward, purged, judged on calibration.
    feats = signals.features(eq_curve, hedge_r, corr)
    label = signals.forward_up(eq_curve, 21)
    p = signals.walk_forward(feats, label, horizon=21)
    sig_eval = signals.evaluate(p, label)

    summary = {
        "as_of": book.index[-1].strftime("%Y-%m-%d"), "data": inp.label, "adjustments": inp.adjustments,
        "regime_now": reg.dropna().iloc[-1] if reg.notna().any() else None,
        "stock_bond_corr_now": float(corr.dropna().iloc[-1]),
        "hedge_ratio_now": h_now, "book_vol_ewma": book_vol, "book_vol_garch_next": g["next_day_vol"],
        "vol_target_scale": scale_now, "kelly_leverage": kelly_lev, "drawdown_leverage_cap": dd_lev,
        "recommended_gross": lev_now, "excess_return_needed_for_gross": edge_needed,
        "var99_hist": var_h, "cvar99_hist": cvar_h, "var99_fhs": var_f,
        "cvar99_fhs": cvar_f, "effective_risk_contributors": risk.effective_risk_contributors(rc["share"]),
        "effective_independent_bets": risk.effective_independent_bets(w_book, cov),
        "diversification_ratio": risk.diversification_ratio(w_book, cov),
        "exposure": limits, "hedge_state": state_now, "trials_counted": n_trials,
        "conventions": {"execution": "signal at the close of t, traded at the close of t+1", "costs": f"{rp.cost_bps:g}bp one way on turnover",
                        "financing": f"cash rate + {rp.financing_spread_bps:g}bp on borrowed money", "inception": "first trade's cost is in the first return",
                        "sharpe": "excess over the accrued cash rate", "window": "every variant on the same dates after warm-up"},
        "mu_shrunk": mu_shrunk, "rf": rf_now,
        "limits": {"max_gross": rp.max_gross, "target_vol": rp.target_vol, "kelly_fraction": rp.kelly_fraction,
                   "max_drawdown": rp.max_drawdown, "drawdown_confidence": rp.drawdown_confidence,
                   "trim_band": rp.trim_band, "max_hedge_ratio": rp.max_hedge_ratio},
    }
    return _clean({
        "summary": summary,
        "regime": {"corr": _series(corr), "label_episodes": regime.episodes(reg).tail(12), "shock_table": shocks},
        "hedge": {"policies": pol_eval, "by_regime": reg_stats, "candidates": candidates,
                  "ratio_history": _series(pol["regime_gated"])},
        "exposures": betas, "risk_contributions": rc, "erc_weights": erc_w,
        "stress": {"episodes": episodes, "scenarios": scen},
        "backtest": {"stats": bt, "curves": curves},
        "signal": {k: v for k, v in sig_eval.items()},
        "trims": {"basis": "example: model-book drift since the last rebalance, not your holdings",
                  "rows": sizing.trim_orders(drift, w_book * float(base.iloc[-1].sum()) / float(w_book.sum()), rp.trim_band)},
        "decision": P.snapshot(as_of=book.index[-1].strftime("%Y-%m-%d"), hedge=hedge_dec, size=size_dec, limits=limits,
                               inputs={"corr63": {"value": float(corr.dropna().iloc[-1]), "date": corr.dropna().index[-1].strftime("%Y-%m-%d")},
                                       "infl36": {"value": infl_now, "date": inp.infl36.dropna().index[-1].strftime("%Y-%m-%d") if infl_now is not None else None},
                                       "line": {"value": line, "status": line_status}, "data": inp.label}),
        "tail": tail, "hedge_selector": hedge_pick, "roll_spread_bps": liquidity,
        "robustness": robustness, "data_quality": data_quality,
    })


def write_report(report: dict, out_dir: str | Path) -> Path:
    return _write(report, out_dir, "report.json")
