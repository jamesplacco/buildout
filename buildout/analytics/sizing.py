"""Position sizing: volatility targeting, shrunk fractional Kelly, equal risk contribution,
drawdown-constrained leverage, and rule-based trims."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def vol_scale(forecast_vol, target_vol: float, cap: float):
    """Exposure multiplier that brings forecast volatility to target, capped by the leverage limit."""
    return np.clip(target_vol / forecast_vol, 0.0, cap)


def shrink_mean(mu_hat: pd.Series, years: float, prior_years: float = 10.0, prior: float | pd.Series = 0.0) -> pd.Series:
    """Sample means are noisy; weight on the sample = years / (years + prior_years)."""
    w = years / (years + prior_years)
    return prior + w * (mu_hat - prior)


def kelly(mu_excess: pd.Series, cov: pd.DataFrame, fraction: float = 0.25, max_gross: float | None = None) -> pd.Series:
    """Fractional Kelly weights f = fraction * inv(cov) @ mu, scaled down to respect max_gross."""
    f = fraction * pd.Series(np.linalg.solve(cov.to_numpy(), mu_excess.reindex(cov.index).to_numpy()), index=cov.index)
    if max_gross is not None and f.abs().sum() > max_gross:
        f *= max_gross / f.abs().sum()
    return f


def erc(cov: pd.DataFrame, budget: pd.Series | None = None) -> pd.Series:
    """Long-only equal (or budgeted) risk contribution weights, summing to 1."""
    n = len(cov)
    b = np.full(n, 1 / n) if budget is None else budget.reindex(cov.index).to_numpy() / budget.sum()
    S = cov.to_numpy()

    def obj(x):
        return 0.5 * x @ S @ x - b @ np.log(x)

    def grad(x):
        return S @ x - b / x

    x0 = 1 / np.sqrt(np.diag(S))
    res = minimize(obj, x0, jac=grad, method="L-BFGS-B", bounds=[(1e-10, None)] * n)
    return pd.Series(res.x / res.x.sum(), index=cov.index)


def drawdown_quantile(mu: float, sigma: float, leverage: float, years: float = 1.0, q: float = 0.95,
                      cash_rate: float = 0.04, borrow_spread: float = 0.01, n_paths: int = 4000,
                      seed: int = 0) -> float:
    """q-quantile of max drawdown over `years` for a constantly rebalanced levered position (GBM).

    Borrowed money (leverage above 1) pays cash_rate + borrow_spread.
    """
    steps = int(252 * years)
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_paths, steps))
    ann_mu = leverage * mu + (1 - leverage) * cash_rate - max(leverage - 1, 0) * borrow_spread
    ann_sig = leverage * sigma
    dt = 1 / 252
    logp = np.cumsum((ann_mu - 0.5 * ann_sig ** 2) * dt + ann_sig * np.sqrt(dt) * z, axis=1)
    logp = np.concatenate([np.zeros((n_paths, 1)), logp], axis=1)
    dd = 1 - np.exp(logp - np.maximum.accumulate(logp, axis=1))
    return float(np.quantile(dd.max(axis=1), q))


def max_leverage(mu: float, sigma: float, max_dd: float, years: float = 1.0, q: float = 0.95,
                 cash_rate: float = 0.04, borrow_spread: float = 0.01, hi: float = 5.0) -> float:
    """Largest leverage whose q-quantile one-year drawdown stays inside max_dd (bisection, common seed)."""
    lo = 0.0
    if drawdown_quantile(mu, sigma, hi, years, q, cash_rate, borrow_spread) <= max_dd:
        return hi
    for _ in range(40):
        mid = (lo + hi) / 2
        if drawdown_quantile(mu, sigma, mid, years, q, cash_rate, borrow_spread) <= max_dd:
            lo = mid
        else:
            hi = mid
    return lo


def trim_orders(current: pd.Series, target: pd.Series, band: float = 0.20) -> pd.DataFrame:
    """Rule-based trims and adds: act only when a weight drifts outside target * (1 +/- band).

    Takes the 'sell all or nothing' decision off the table: a winner gets trimmed back to target.
    """
    df = pd.DataFrame({"current": current, "target": target}).fillna(0.0)
    over = df["current"] > df["target"] * (1 + band)
    under = df["current"] < df["target"] * (1 - band)
    df["action"] = np.where(over, "trim", np.where(under, "add", "hold"))
    df["trade"] = np.where(over | under, df["target"] - df["current"], 0.0)
    return df
