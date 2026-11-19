"""Hedge sizing and evaluation. All hedge ratios are $ of hedge per $1 of book, applied the next day."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .regime import classify, ewm_corr


def min_var_ratio(book: pd.Series, hedge: pd.Series, halflife: int = 63) -> pd.Series:
    """h* = -cov(book, hedge) / var(hedge). Positive = buy the hedge; negative = the hedge adds risk."""
    cov = book.ewm(halflife=halflife, min_periods=halflife).cov(hedge)
    var = hedge.ewm(halflife=halflife, min_periods=halflife).var()
    return (-cov / var).rename("h")


def financing(h: pd.Series | float, index: pd.Index, rf: pd.Series | float | None, borrow_spread_bps: float = 0.0,
              periods: int = 252) -> pd.Series:
    """What holding h of the hedge on top of a fully invested book costs each day (v0.47): the overlay is bought with
    borrowed money, so it pays the cash rate, plus the borrow spread on a long overlay. rf is the annualized cash
    rate (a number or a dated series); None means the overlay is not financed (a futures leg already in excess)."""
    if rf is None:
        return pd.Series(0.0, index=index)
    cash = (rf.reindex(index).ffill().fillna(0.0) if isinstance(rf, pd.Series) else pd.Series(float(rf), index=index)) / periods
    hh = h.reindex(index) if isinstance(h, pd.Series) else pd.Series(float(h), index=index)
    return hh * cash + hh.clip(lower=0.0) * (borrow_spread_bps / 1e4 / periods)


def apply_hedge(book: pd.Series, hedge: pd.Series, ratio: pd.Series | float, rf: pd.Series | float | None = None,
                borrow_spread_bps: float = 0.0, periods: int = 252) -> pd.Series:
    """Hedged daily return with yesterday's ratio (no lookahead). With rf, the overlay is financed: a hedge held on
    top of a full book is paid for at the cash rate plus the borrow spread, as backtest.run charges it."""
    h = ratio.shift(1) if isinstance(ratio, pd.Series) else ratio
    return book + h * hedge - financing(h, book.index, rf, borrow_spread_bps, periods)


def variance_reduction(book: pd.Series, hedged: pd.Series) -> float:
    d = pd.concat([book, hedged], axis=1).dropna()
    return float(1 - d.iloc[:, 1].var() / d.iloc[:, 0].var())


def policies(book: pd.Series, hedge: pd.Series, halflife: int = 63, static: float = 0.30,
             max_ratio: float = 1.0) -> pd.DataFrame:
    """Daily hedge ratio under four policies, each knowable at the close of t."""
    h = min_var_ratio(book, hedge, halflife)
    regime = classify(ewm_corr(book, hedge, halflife))
    out = pd.DataFrame({
        "none": 0.0,
        "static": static,
        "min_var_long_only": h.clip(0, max_ratio),
        "regime_gated": np.where(regime == "hedging", h.clip(0, max_ratio), 0.0),
    }, index=book.index)
    out.loc[h.isna()] = np.nan
    return out


def evaluate_policies(book: pd.Series, hedge: pd.Series, ratios: pd.DataFrame, q: float = 0.05,
                      periods: int = 252, rf: pd.Series | float | None = None, borrow_spread_bps: float = 0.0) -> pd.DataFrame:
    """Out-of-sample comparison: variance reduction, tail behaviour, and what the hedge cost in return.

    v0.47: with rf (the annualized cash rate) the overlay is financed at cash plus borrow_spread_bps, so
    ann_return_drag is what the hedge added or cost after paying for it; ann_financing is that payment on its own.
    Without rf nothing is charged (the old reading, which credited a hedge that earned exactly cash with a gain)."""
    rows = {}
    base = book[ratios.dropna().index]
    cut = base.quantile(q)
    for name in ratios:
        hedged = apply_hedge(book, hedge, ratios[name], rf, borrow_spread_bps, periods).reindex(base.index)
        d = pd.concat([base, hedged], axis=1).dropna()
        tail = d[d.iloc[:, 0] <= cut]
        fin = financing(ratios[name].shift(1), book.index, rf, borrow_spread_bps, periods).reindex(d.index)
        rows[name] = {"ann_vol": d.iloc[:, 1].std() * np.sqrt(periods),
                      "variance_reduction": 1 - d.iloc[:, 1].var() / d.iloc[:, 0].var(),
                      "worst_days_avg": tail.iloc[:, 1].mean(),
                      "worst_days_saved": tail.iloc[:, 1].mean() - tail.iloc[:, 0].mean(),
                      "ann_return_drag": (d.iloc[:, 1].mean() - d.iloc[:, 0].mean()) * periods,
                      "ann_financing": float(fin.mean() * periods),
                      "avg_ratio": ratios[name].mean()}
    return pd.DataFrame(rows).T


def by_regime(book: pd.Series, hedge: pd.Series, regime: pd.Series, q: float = 0.05) -> pd.DataFrame:
    """In each regime: correlation, best static ratio in hindsight, and what bonds did on the worst days."""
    d = pd.concat({"book": book, "hedge": hedge, "regime": regime}, axis=1).dropna()
    cut = d["book"].quantile(q)
    rows = {}
    for g, x in d.groupby("regime"):
        h = -x["book"].cov(x["hedge"]) / x["hedge"].var()
        tail = x[x["book"] <= cut]
        rows[g] = {"days": len(x), "corr": x["book"].corr(x["hedge"]), "hindsight_ratio": h,
                   "variance_reduction_at_ratio": 1 - (x["book"] + max(h, 0) * x["hedge"]).var() / x["book"].var(),
                   "tail_days": len(tail), "tail_hedge_avg": tail["hedge"].mean() if len(tail) else np.nan,
                   "tail_hedge_up_share": (tail["hedge"] > 0).mean() if len(tail) else np.nan}
    return pd.DataFrame(rows).T


def futures_contracts(hedge_notional: float, hedge_duration: float, dv01_per_contract: float) -> float:
    """Contracts that match the DV01 of a cash-bond hedge (e.g. TLT notional -> UB futures)."""
    return hedge_notional * hedge_duration * 1e-4 / dv01_per_contract


def empirical_dv01(futures_close: pd.Series, yield_pct: pd.Series, multiplier: float = 1000.0,
                   window: int = 126) -> float:
    """$ per contract per 1bp, estimated by regressing contract P&L on yield changes (recent window)."""
    d = pd.concat({"pnl": futures_close.diff() * multiplier, "dy": yield_pct.diff() * 100}, axis=1).dropna().tail(window)
    slope = np.cov(d["pnl"], d["dy"])[0, 1] / d["dy"].var()
    return float(-slope)
