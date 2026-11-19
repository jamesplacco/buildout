"""Performance statistics, including the probabilistic and deflated Sharpe ratios
(Bailey and Lopez de Prado), which discount a backtest for luck and for how many variants were tried."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

EULER_GAMMA = 0.5772156649015329


SD_FLOOR = 1e-12      # a daily excess-return deviation below this is rounding, not risk (v0.47)


def max_drawdown(equity: pd.Series, start: float | None = None) -> float:
    """Worst fall from a running peak, as a negative number. `start` (v0.47) is the value the series began from,
    before its first row: with it, a fall on the first day counts as a fall from where the record started."""
    peak = equity.cummax()
    if start is not None:
        peak = peak.clip(lower=start)
    return float((equity / peak - 1).min())


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


def perf(returns: pd.Series, periods: int = 252, rf: float | pd.Series = 0.0) -> dict:
    """Statistics from one net return series. rf is the annualized cash rate, a number or a series aligned by date
    (the excess return for Sharpe and Sortino is over cash actually accrued that day, not over zero)."""
    r = returns.dropna()
    r = r.iloc[r.ne(0).argmax():] if r.ne(0).any() else r
    eq = (1 + r).cumprod()
    years = len(r) / periods
    cash = (rf.reindex(r.index).ffill().fillna(0.0) if isinstance(rf, pd.Series) else pd.Series(float(rf), index=r.index)) / periods
    ex = r - cash
    # v0.47: a series that earns exactly cash has an excess return of rounding error (about 1e-17 a day), and the
    # ratio of two rounding errors is not a Sharpe ratio. Below SD_FLOOR the excess is zero: Sharpe 0, and the
    # statistics that divide by it (Sortino, the probabilistic and deflated Sharpe) are not defined.
    sd = float(ex.std()) if len(ex) > 1 else 0.0
    flat = not (sd > SD_FLOOR)
    sr = 0.0 if flat else float(ex.mean() / sd)
    downside = np.sqrt((np.minimum(ex, 0) ** 2).mean())
    mdd = max_drawdown(eq, start=1.0)             # v0.47: a fall on the first day is a fall from the starting value
    cagr = eq.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    sk, ku = float(skew(r)), float(kurtosis(r, fisher=False))
    return {"cagr": cagr, "vol": r.std() * np.sqrt(periods), "sharpe": sr * np.sqrt(periods),
            "sortino": ex.mean() / downside * np.sqrt(periods) if (downside > SD_FLOOR and not flat) else np.nan,
            "max_drawdown": mdd, "calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
            "skew": sk, "kurtosis": ku, "hit_rate": float((r > 0).mean()),
            "worst_day": float(r.min()), "best_day": float(r.max()),
            "psr": None if flat else probabilistic_sharpe(sr, len(r), sk, ku), "excess_is_zero": bool(flat),
            "sr_per_period": sr, "n": len(r), "years": years,
            "final_equity": float(eq.iloc[-1]) if len(eq) else 1.0, "cash_cagr": float((1 + cash).prod() ** (1 / years) - 1) if years > 0 else np.nan}
