"""Signals and a walk-forward probabilistic model, evaluated honestly (calibration, not just hit rate)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def momentum(prices: pd.Series, lookback: int = 252, skip: int = 21) -> pd.Series:
    return np.log(prices.shift(skip) / prices.shift(lookback))


def trend(prices: pd.Series, window: int = 200) -> pd.Series:
    return prices / prices.rolling(window, min_periods=window).mean() - 1


def features(price: pd.Series, bond_ret: pd.Series, corr: pd.Series) -> pd.DataFrame:
    r = price.pct_change(fill_method=None)
    bond_px = (1 + bond_ret.fillna(0)).cumprod()
    return pd.DataFrame({
        "mom_12_1": momentum(price),
        "mom_3m": np.log(price / price.shift(63)),
        "trend_200": trend(price),
        "vol_63": r.rolling(63).std() * np.sqrt(252),
        "dd_from_high": price / price.rolling(252, min_periods=60).max() - 1,
        "bond_mom_3m": np.log(bond_px / bond_px.shift(63)),
        "stock_bond_corr": corr,
    })


def forward_up(price: pd.Series, horizon: int = 21) -> pd.Series:
    """Label at t: 1 if the next `horizon` days return is positive. Uses t+1..t+h, so it is only known later."""
    fwd = price.shift(-horizon) / price - 1
    return (fwd > 0).astype(float).where(fwd.notna())


def logistic_fit(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 50) -> np.ndarray:
    """L2-regularized logistic regression by Newton/IRLS. First column of X must be the intercept."""
    w = np.zeros(X.shape[1])
    reg = l2 * np.eye(X.shape[1])
    reg[0, 0] = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        g = X.T @ (p - y) + reg @ w
        H = (X * (p * (1 - p))[:, None]).T @ X + reg
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def walk_forward(X: pd.DataFrame, y: pd.Series, horizon: int = 21, min_train: int = 504,
                 refit_every: int = 21, l2: float = 100.0) -> pd.Series:
    """Expanding-window predictions. Training at refit date t0 only uses rows whose labels were fully
    realized by t0 (purge of `horizon` days), so overlapping labels cannot leak the future.
    Heavy L2 by default: overlapping monthly labels carry far fewer independent observations than rows,
    and a weakly regularized model turns noise into overconfident probabilities."""
    data = pd.concat([X, y.rename("_y")], axis=1)
    p = pd.Series(np.nan, index=data.index, name="p_up")
    for t0 in range(min_train, len(data), refit_every):
        train = data.iloc[: max(t0 - horizon, 0)].dropna()
        if len(train) < min_train // 2:
            continue
        mu, sd = train[X.columns].mean(), train[X.columns].std().replace(0, 1)
        A = np.column_stack([np.ones(len(train)), ((train[X.columns] - mu) / sd).to_numpy()])
        w = logistic_fit(A, train["_y"].to_numpy(), l2)
        test = data.iloc[t0: t0 + refit_every][X.columns]
        ok = test.notna().all(axis=1)
        B = np.column_stack([np.ones(ok.sum()), ((test[ok] - mu) / sd).to_numpy()])
        p.loc[test.index[ok]] = 1 / (1 + np.exp(-(B @ w)))
    return p


def evaluate(p: pd.Series, y: pd.Series, bins: int = 5) -> dict:
    """Hit rate, Brier skill vs the base rate, log loss, AUC and a calibration table."""
    d = pd.concat({"p": p, "y": y}, axis=1).dropna()
    if d.empty:
        return {}
    base = d["y"].mean()
    brier = float(((d["p"] - d["y"]) ** 2).mean())
    brier_base = float(((base - d["y"]) ** 2).mean())
    eps = 1e-12
    ll = float(-(d["y"] * np.log(d["p"] + eps) + (1 - d["y"]) * np.log(1 - d["p"] + eps)).mean())
    ranks = d["p"].rank()
    pos = d["y"] == 1
    n1, n0 = pos.sum(), (~pos).sum()
    auc = float((ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else np.nan
    d["bin"] = pd.qcut(d["p"], bins, duplicates="drop")
    calib = d.groupby("bin", observed=True).agg(predicted=("p", "mean"), realized=("y", "mean"), n=("y", "size"))
    return {"n": len(d), "hit_rate": float(((d["p"] > 0.5) == pos).mean()), "base_rate": float(base),
            "brier": brier, "brier_skill": 1 - brier / brier_base, "log_loss": ll, "auc": auc,
            "calibration": calib.reset_index(drop=True)}
