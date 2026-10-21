"""Returns and factor construction."""
from __future__ import annotations

import pandas as pd


def simple_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change(fill_method=None)


def equal_weight(returns: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Daily-rebalanced equal-weight basket over names that trade that day (handles late IPOs)."""
    cols = [c for c in cols if c in returns.columns]
    return returns[cols].mean(axis=1, skipna=True)


def factor_returns(returns: pd.DataFrame, market: str, ai_names: list[str], rates: str) -> pd.DataFrame:
    """market = market proxy; ai = AI basket in excess of the market; rates = long-bond return."""
    ai = equal_weight(returns, ai_names) - returns[market]
    return pd.DataFrame({"market": returns[market], "ai": ai, "rates": returns[rates]})


def book_returns(returns: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Constant-weight book. Names without data yet get their weight redistributed pro rata."""
    w = pd.Series(weights, dtype=float)
    r = returns[w.index]
    avail = r.notna()
    wt = avail.mul(w, axis=1)
    scale = w.sum() / wt.sum(axis=1)
    return (r.fillna(0) * wt).sum(axis=1) * scale


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1
