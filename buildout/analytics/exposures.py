"""Factor exposures: exponentially weighted least squares, updated recursively (no lookahead)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ewls_betas(y: pd.Series, X: pd.DataFrame, halflife: int = 126, min_obs: int = 60,
               ridge: float = 1e-10) -> pd.DataFrame:
    """Betas at t use observations through t only. Rows before `min_obs` valid days are NaN.

    Returns columns alpha, one per factor, n_obs (days used), n_eff (effective weight) and resid_vol (daily).
    """
    lam = 0.5 ** (1 / halflife)
    data = pd.concat([y.rename("_y"), X], axis=1)
    k = X.shape[1] + 1
    sxx, sxy, syy = np.zeros((k, k)), np.zeros(k), 0.0
    n_eff, count = 0.0, 0
    out = np.full((len(data), k + 3), np.nan)
    last = None
    for t, row in enumerate(data.to_numpy()):
        yt, xt = row[0], row[1:]
        if np.isnan(yt) or np.isnan(xt).any():
            if last is not None:
                out[t] = last
            continue
        x = np.concatenate(([1.0], xt))
        sxx = lam * sxx + np.outer(x, x)
        sxy = lam * sxy + x * yt
        syy = lam * syy + yt * yt
        n_eff = lam * n_eff + 1
        count += 1
        if count >= min_obs:
            beta = np.linalg.solve(sxx + ridge * np.eye(k), sxy)
            sse = max(syy - 2 * beta @ sxy + beta @ sxx @ beta, 0.0)
            last = np.concatenate((beta, [count, n_eff, np.sqrt(sse / max(n_eff - k, 1))]))
            out[t] = last
    return pd.DataFrame(out, index=data.index, columns=["alpha", *X.columns, "n_obs", "n_eff", "resid_vol"])


def shrink(beta: float, n_obs: float, prior: float, n0: float = 126.0) -> float:
    """Short history (a recent IPO) leans on its prior; weight on own estimate = n / (n + n0)."""
    if np.isnan(beta) or np.isnan(n_obs):
        return prior
    return (n_obs * beta + n0 * prior) / (n_obs + n0)


def latest_betas(returns: pd.DataFrame, factors: pd.DataFrame, names: list[str], halflife: int,
                 min_obs: int = 60, priors: dict[str, str] | None = None, n0: float = 126.0,
                 full_history: int = 504) -> pd.DataFrame:
    """Current factor betas per name. Names with less than `full_history` days are shrunk toward a
    proxy's betas (config priors) or the cross-sectional average of established names."""
    priors = priors or {}
    full = {}
    for name in names:
        b = ewls_betas(returns[name], factors, halflife=halflife, min_obs=min(min_obs, 20)).dropna()
        full[name] = b.iloc[-1] if len(b) else pd.Series(np.nan, index=b.columns)
    raw = pd.DataFrame(full).T
    established = raw[raw["n_obs"] >= full_history]
    xsec = established[factors.columns].mean()
    rows = {}
    for name in names:
        r = raw.loc[name]
        rows[name] = {}
        for f in factors.columns:
            proxy = priors.get(name)
            prior = raw.loc[proxy, f] if proxy in raw.index else xsec[f]
            rows[name][f] = r[f] if r["n_obs"] >= full_history else shrink(r[f], r["n_obs"], prior, n0)
        rows[name]["n_obs"] = r["n_obs"]
        rows[name]["resid_vol_ann"] = r["resid_vol"] * np.sqrt(252)
    return pd.DataFrame(rows).T
