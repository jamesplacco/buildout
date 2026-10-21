"""Volatility forecasting. Risk is far more predictable than return, so sizing leans on these."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.signal import lfilter


def ewma_vol(r: pd.Series | pd.DataFrame, lam: float = 0.94, periods: int = 252, min_periods: int = 20):
    """RiskMetrics zero-mean EWMA. Value at t (through t's close) is the forecast for t+1, annualized."""
    return np.sqrt((r ** 2).ewm(alpha=1 - lam, min_periods=min_periods).mean() * periods)


def _garch_path(x: np.ndarray, omega: float, alpha: float, beta: float, h0: float) -> np.ndarray:
    u = omega + alpha * np.concatenate(([0.0], x[:-1] ** 2))
    u[0] = h0                                    # h[0] = h0; h[t] = omega + alpha*x[t-1]^2 + beta*h[t-1]
    return lfilter([1.0], [1.0, -beta], u)


def garch11(r: pd.Series, periods: int = 252) -> dict:
    """Gaussian GARCH(1,1) by maximum likelihood. Returns params, conditional vol and next-day forecast."""
    s = r.dropna()
    x = (s - s.mean()).to_numpy()
    h0 = x.var()

    def nll(p):
        omega, alpha, beta = p
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999:
            return 1e12
        h = _garch_path(x, omega, alpha, beta, h0)
        return 0.5 * np.sum(np.log(h) + x ** 2 / h)

    res = minimize(nll, [h0 * 0.05, 0.08, 0.90], method="Nelder-Mead",
                   options={"maxiter": 4000, "xatol": 1e-10, "fatol": 1e-10})
    omega, alpha, beta = res.x
    h = _garch_path(x, omega, alpha, beta, h0)
    nxt = omega + alpha * x[-1] ** 2 + beta * h[-1]
    return {"omega": omega, "alpha": alpha, "beta": beta, "persistence": alpha + beta,
            "long_run_vol": float(np.sqrt(omega / (1 - alpha - beta) * periods)),
            "next_day_vol": float(np.sqrt(nxt * periods)),
            "cond_vol": pd.Series(np.sqrt(h * periods), index=s.index), "converged": bool(res.success)}


def realized_variance(intraday_close: pd.Series, every: str = "5min") -> pd.Series:
    """Daily realized variance from intraday bars (e.g. Databento ohlcv-1m), overnight gap excluded."""
    px = intraday_close.resample(every).last().dropna()
    lr = np.log(px).diff()
    day = lr.index.normalize()
    first_of_day = pd.Series(day, index=lr.index).ne(pd.Series(day, index=lr.index).shift())
    lr[first_of_day.to_numpy()] = np.nan
    return (lr ** 2).groupby(day).sum(min_count=1)


def har_forecast(rv: pd.Series, min_train: int = 252, refit_every: int = 21) -> pd.Series:
    """HAR-RV (Corsi 2009): next-day RV on daily, weekly and monthly RV averages. Walk-forward OLS."""
    X = pd.DataFrame({"d": rv, "w": rv.rolling(5).mean(), "m": rv.rolling(22).mean()})
    y = rv.shift(-1)
    out = pd.Series(np.nan, index=rv.index, name="har")
    coef = None
    for t in range(min_train, len(rv)):
        if coef is None or (t - min_train) % refit_every == 0:
            train = pd.concat([X.iloc[:t], y.iloc[:t]], axis=1).dropna()   # y at row t-1 = rv[t], known at t
            A = np.column_stack([np.ones(len(train)), train[["d", "w", "m"]].to_numpy()])
            coef = np.linalg.lstsq(A, train.iloc[:, -1].to_numpy(), rcond=None)[0]
        xt = X.iloc[t].to_numpy()
        if not np.isnan(xt).any():
            out.iloc[t] = max(coef[0] + coef[1:] @ xt, 1e-12)
    return out


def qlike(forecast_var: pd.Series, realized_var: pd.Series) -> float:
    """QLIKE loss: the standard robust loss for comparing variance forecasts (lower is better)."""
    d = pd.concat([forecast_var, realized_var], axis=1).dropna()
    d = d[(d.iloc[:, 0] > 0) & (d.iloc[:, 1] > 0)]
    ratio = d.iloc[:, 1] / d.iloc[:, 0]
    return float((ratio - np.log(ratio) - 1).mean())
