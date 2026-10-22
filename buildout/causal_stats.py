"""Correlation is not causation, so test the links several ways on the same six monthly series (oil, CPI, 10-year,
stocks, VIX, gold), by regime. Python is canonical; the page renders the result (site/src/snap11.js or brain.json).

  granger            does x's past improve the forecast of y beyond y's own past? F-test of two lags of x in a
                     regression of y on two lags of y (bivariate Granger causality). Predictive, not structural.
  partial            partial correlations from the inverse correlation matrix: the link between two series after
                     the other four are held fixed (a Gaussian graphical model: zero means conditionally independent)
  crisis             correlation with stocks in stocks' worst 10% of months against the other 90%: what a hedge does
                     when it is needed, not on average
  tail               lower-tail dependence at the 10% quantile: P(both in their worst decile) / 0.10, so 1 means
                     crashes always arrive together and 0.10 means they are independent
  lead_lag           correlation of x(t - k) with y(t) for k = -3..3 months: who moves first
"""
from __future__ import annotations

import numpy as np
from scipy.stats import f as fdist

ORDER = ["oil", "cpi", "y10", "eq", "vix", "gold"]


def _lags(v: np.ndarray, p: int) -> np.ndarray:
    return np.column_stack([v[p - k - 1: len(v) - k - 1] for k in range(p)])


def granger(x: np.ndarray, y: np.ndarray, p: int = 2) -> dict:
    n = len(y)
    Y = y[p:]
    R = np.column_stack([np.ones(n - p), _lags(y, p)])
    U = np.column_stack([R, _lags(x, p)])
    rss = lambda A: float(np.sum((Y - A @ np.linalg.lstsq(A, Y, rcond=None)[0]) ** 2))  # noqa: E731
    r0, r1 = rss(R), rss(U)
    df2 = len(Y) - U.shape[1]
    F = ((r0 - r1) / p) / (r1 / df2)
    return {"F": F, "p": float(fdist.sf(F, p, df2)), "lags": p, "n": len(Y)}


def partial_corr(Z: np.ndarray) -> np.ndarray:
    C = np.corrcoef(Z, rowvar=False)
    Pm = np.linalg.inv(C)
    d = np.sqrt(np.diag(Pm))
    out = -Pm / np.outer(d, d)
    np.fill_diagonal(out, 1.0)
    return out


def crisis_corr(Z: np.ndarray, eq: int, q: float = 0.10) -> dict:
    cut = np.quantile(Z[:, eq], q)
    bad = Z[:, eq] <= cut
    out = {}
    for j in range(Z.shape[1]):
        if j == eq:
            continue
        cb = float(np.mean(Z[bad, j]))
        out[j] = {"crisis_mean": cb, "normal_corr": float(np.corrcoef(Z[~bad, eq], Z[~bad, j])[0, 1]),
                  "all_corr": float(np.corrcoef(Z[:, eq], Z[:, j])[0, 1]), "crisis_corr": float(np.corrcoef(Z[bad, eq], Z[bad, j])[0, 1]) if bad.sum() > 3 else None}
    return out


def tail_dependence(x: np.ndarray, y: np.ndarray, q: float = 0.10) -> float:
    a, b = x <= np.quantile(x, q), y <= np.quantile(y, q)
    return float(np.mean(a & b) / q)


def lead_lag(x: np.ndarray, y: np.ndarray, kmax: int = 3) -> dict:
    out = {}
    for k in range(-kmax, kmax + 1):
        if k > 0:
            a, b = x[:-k], y[k:]
        elif k < 0:
            a, b = x[-k:], y[:k]
        else:
            a, b = x, y
        out[k] = float(np.corrcoef(a, b)[0, 1])
    return out


def analyze(block: dict, regimes: dict) -> dict:
    cols, dates = block["cols"], block["dates"]
    Z = np.array(block["z"]).T
    eq = cols.index("eq")
    out = {"cols": cols, "regimes": {}}
    for name, (a, b) in regimes.items():
        a_, b_ = a[:7], (b or "9999-12")[:7]
        rows = [i for i, d in enumerate(dates) if a_ <= d <= b_]
        X = Z[rows]
        g = {f"{cols[i]}>{cols[j]}": granger(X[:, i], X[:, j]) for i in range(len(cols)) for j in range(len(cols)) if i != j}
        pc = partial_corr(X)
        cr = crisis_corr(X, eq)
        td = {f"{cols[i]}~{cols[j]}": tail_dependence(X[:, i], X[:, j]) for i in range(len(cols)) for j in range(i + 1, len(cols))}
        ll = {f"{cols[i]}>{cols[j]}": lead_lag(X[:, i], X[:, j]) for i in range(len(cols)) for j in range(len(cols)) if i != j}
        out["regimes"][name] = {"months": len(rows), "granger": g, "partial": pc.round(4).tolist(),
                                "crisis": {cols[j]: v for j, v in cr.items()}, "tail": td, "lead_lag": ll}
    return out


def summary(an: dict, alpha: float = 0.05) -> list[str]:
    """Plain-language findings: significant Granger links, and hedges that fail in crises."""
    lines = []
    for name, r in an["regimes"].items():
        sig = sorted(((k, v["p"]) for k, v in r["granger"].items() if v["p"] < alpha), key=lambda t: t[1])
        if sig:
            lines.append(f"{name}: {len(sig)} of 30 directed pairs Granger-predict at 5%: " + ", ".join(f"{k} (p={p:.3f})" for k, p in sig[:6]))
        for s, v in r["crisis"].items():
            if v["crisis_corr"] is not None and v["normal_corr"] is not None and abs(v["crisis_corr"] - v["normal_corr"]) > 0.3:
                lines.append(f"{name}: {s} correlates {v['normal_corr']:+.2f} with stocks normally but {v['crisis_corr']:+.2f} in stocks' worst months")
    return lines
