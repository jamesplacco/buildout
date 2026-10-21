"""Portfolio risk: covariance, risk contributions, effective bets, VaR/CVaR (historical and FHS)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ewma_cov(returns: pd.DataFrame, halflife: int = 63) -> pd.DataFrame:
    """Latest exponentially weighted covariance matrix (daily units)."""
    cov = returns.ewm(halflife=halflife, min_periods=halflife).cov()
    last = cov.index.get_level_values(0)[-1]
    return cov.loc[last]


def risk_contributions(w: pd.Series, cov: pd.DataFrame, periods: int = 252) -> pd.DataFrame:
    w = w.reindex(cov.index).fillna(0.0)
    S = cov.to_numpy() * periods
    sigma = float(np.sqrt(w.to_numpy() @ S @ w.to_numpy()))
    mrc = S @ w.to_numpy() / sigma
    rc = w.to_numpy() * mrc
    return pd.DataFrame({"weight": w, "marginal": mrc, "contribution": rc, "share": rc / sigma}, index=cov.index)


def effective_bets(shares: pd.Series) -> float:
    """1 / sum(share^2): 1 means one position drives all the risk."""
    s = shares[shares.abs() > 0]
    return float(1 / np.sum(s ** 2))


def historical_var(port_ret: pd.Series, q: float = 0.99) -> tuple[float, float]:
    r = port_ret.dropna()
    var = -np.quantile(r, 1 - q)
    return float(var), float(-r[r <= -var].mean())


def fhs_var(returns: pd.DataFrame, w: pd.Series, lam: float = 0.94, q: float = 0.99) -> tuple[float, float]:
    """Filtered historical simulation (Barone-Adesi): history's shock shapes, today's volatility."""
    r = returns[w.index]
    vol = np.sqrt((r ** 2).ewm(alpha=1 - lam, min_periods=20).mean())
    z = r / vol.shift(1)
    scen = (z * vol.iloc[-1]).dropna(how="all").fillna(0.0)
    return historical_var(scen @ w, q)
