"""Portfolio risk: covariance, risk contributions, concentration and diversification, VaR/CVaR (historical and FHS).

Two different questions, kept apart:
  effective_risk_contributors   how evenly the risk is spread across POSITIONS (1 / sum of squared risk shares)
  effective_independent_bets    how many independent DRIVERS the risk loads on (Meucci: entropy of the risk
                                spread across the covariance's principal components). Two equal positions that
                                are perfectly correlated score 2 on the first and 1 on the second.
"""
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


def effective_risk_contributors(shares: pd.Series) -> float:
    """1 / sum(share^2) of position risk shares: concentration by position, NOT independence."""
    s = shares[shares.abs() > 0]
    return float(1 / np.sum(s ** 2))


effective_bets = effective_risk_contributors      # v0.6 name, kept so old callers do not break


def effective_independent_bets(w: pd.Series | np.ndarray, cov: pd.DataFrame | np.ndarray) -> float:
    """exp(entropy) of the portfolio variance split across principal components (Meucci 2009).

    Each component k gets p_k = (w . e_k)^2 lambda_k / (w' S w); the result runs from 1 (one driver) to n.
    """
    S = np.asarray(cov, dtype=float)
    x = np.asarray(w.reindex(cov.index).fillna(0.0) if isinstance(w, pd.Series) and isinstance(cov, pd.DataFrame) else w, dtype=float)
    lam, E = np.linalg.eigh(S)
    lam = np.clip(lam, 0.0, None)
    v = (E.T @ x) ** 2 * lam
    tot = v.sum()
    if tot <= 0:
        return float("nan")
    p = v[v > tot * 1e-12] / tot
    return float(np.exp(-(p * np.log(p)).sum()))


def diversification_ratio(w: pd.Series | np.ndarray, cov: pd.DataFrame | np.ndarray) -> float:
    """Weighted average volatility over portfolio volatility (Choueifaty): 1 means no diversification at all."""
    S = np.asarray(cov, dtype=float)
    x = np.asarray(w.reindex(cov.index).fillna(0.0) if isinstance(w, pd.Series) and isinstance(cov, pd.DataFrame) else w, dtype=float)
    port = float(np.sqrt(x @ S @ x))
    return float(np.abs(x) @ np.sqrt(np.diag(S)) / port) if port > 0 else float("nan")


def historical_var(port_ret: pd.Series, q: float = 0.99) -> tuple[float, float]:
    r = port_ret.dropna()
    var = -np.quantile(r, 1 - q)
    return float(var), float(-r[r <= -var].mean())


def fhs_var(returns: pd.DataFrame, w: pd.Series, lam: float = 0.94, q: float = 0.99) -> tuple[float, float]:
    """Filtered historical simulation (Barone-Adesi): history's shock shapes, today's volatility."""
    r = returns[w.index]
    vol = np.sqrt((r ** 2).ewm(alpha=1 - lam, min_periods=20).mean())
    z = r / vol.shift(1)
    scen = (z * vol.iloc[-1]).dropna(how="all")
    # v0.30: a name without a scenario that day (before its listing) hands its weight to the others pro rata, as
    # book_returns does, so the historical and the filtered VaR describe the same book (zero-filling understated it)
    wt = scen.notna().mul(w, axis=1)
    wt = wt.mul(w.sum() / wt.sum(axis=1).replace(0, np.nan), axis=0)
    return historical_var((scen.fillna(0.0) * wt).sum(axis=1).dropna(), q)
