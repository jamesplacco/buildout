"""Performance statistics, including the probabilistic and deflated Sharpe ratios
(Bailey and Lopez de Prado), which discount a backtest for luck and for how many variants were tried."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

EULER_GAMMA = 0.5772156649015329


def max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1).min())


def probabilistic_sharpe(sr: float, n: int, sk: float, ku: float, sr_star: float = 0.0) -> float:
    """P(true Sharpe > sr_star). sr is per period (not annualized); ku is raw (not excess) kurtosis."""
    denom = np.sqrt(max(1 - sk * sr + (ku - 1) / 4 * sr ** 2, 1e-12))
    return float(norm.cdf((sr - sr_star) * np.sqrt(n - 1) / denom))


def expected_max_sharpe(n_trials: int, sr_var: float) -> float:
    """Expected best per-period Sharpe among n_trials skill-less strategies with Sharpe variance sr_var."""
    if n_trials <= 1:
        return 0.0
    return float(np.sqrt(sr_var) * ((1 - EULER_GAMMA) * norm.ppf(1 - 1 / n_trials)
                                    + EULER_GAMMA * norm.ppf(1 - 1 / (n_trials * np.e))))


def deflated_sharpe(sr: float, n: int, sk: float, ku: float, n_trials: int, sr_var: float) -> float:
    return probabilistic_sharpe(sr, n, sk, ku, expected_max_sharpe(n_trials, sr_var))


def perf(returns: pd.Series, periods: int = 252, rf: float = 0.0) -> dict:
    r = returns.dropna()
    r = r.iloc[r.ne(0).argmax():] if r.ne(0).any() else r
    eq = (1 + r).cumprod()
    years = len(r) / periods
    ex = r - rf / periods
    sr = ex.mean() / r.std() if r.std() > 0 else 0.0
    downside = np.sqrt((np.minimum(ex, 0) ** 2).mean())
    mdd = max_drawdown(eq)
    cagr = eq.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    sk, ku = float(skew(r)), float(kurtosis(r, fisher=False))
    return {"cagr": cagr, "vol": r.std() * np.sqrt(periods), "sharpe": sr * np.sqrt(periods),
            "sortino": ex.mean() / downside * np.sqrt(periods) if downside > 0 else np.nan,
            "max_drawdown": mdd, "calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
            "skew": sk, "kurtosis": ku, "hit_rate": float((r > 0).mean()),
            "worst_day": float(r.min()), "best_day": float(r.max()),
            "psr": probabilistic_sharpe(sr, len(r), sk, ku), "sr_per_period": sr, "n": len(r), "years": years}
