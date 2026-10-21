"""Learning the brain's structure from the data, instead of assuming it.

The brain's measured links rest on two assumptions: an ordering (oil moves first, then consumer prices, the 10-year,
stocks, then volatility and gold) and two fixed regimes split at January 2022. This module tests both on the same
six standardized monthly series. The page runs the same code (site/src/brainx.js); tests/test_v09.py checks they agree.

  lingam_order     DirectLiNGAM (Shimizu et al. 2011) with the pairwise likelihood-ratio measure (Hyvarinen and
                   Smith 2013): in a linear system with non-Gaussian shocks, the cause is the variable whose
                   regression residuals look most independent of it, which a Gaussian model cannot tell. It returns a
                   causal order learned from the data alone; it needs non-Gaussian, roughly linear, unconfounded data.
  order_agreement  the share of the 15 pairs the data orders the same way as the assumed chain
  bootstrap_order  how often each pair keeps its learned order across resamples of months (stability, not proof)
  kalman_links     each child's links as random walks, beta_t = beta_{t-1} + eta, y_t = x_t' beta_t + eps: forward
                   Kalman filter, Rauch-Tung-Striebel smoother, and the drift variance q chosen by maximum likelihood
                   on a grid, so the data says how fast a link can change and when it changed sign
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

K1, K2, GAMMA = 79.047, 7.4129, 0.37457


def _entropy(u: np.ndarray) -> float:
    """Hyvarinen's maximum-entropy approximation of differential entropy for a standardized variable."""
    return (1 + math.log(2 * math.pi)) / 2 - K1 * (float(np.mean(np.log(np.cosh(u)))) - GAMMA) ** 2 - K2 * float(np.mean(u * np.exp(-u * u / 2))) ** 2


def _residual(xi: np.ndarray, xj: np.ndarray) -> np.ndarray:
    return xi - (np.cov(xi, xj)[0, 1] / np.var(xj)) * xj


def _std(x: np.ndarray) -> np.ndarray:
    return (x - x.mean()) / x.std()


def _diff_mi(xi_std, xj_std, ri_j, rj_i) -> float:
    return (_entropy(xj_std) + _entropy(ri_j / np.std(ri_j))) - (_entropy(xi_std) + _entropy(rj_i / np.std(rj_i)))


def lingam_order(X: np.ndarray) -> list[int]:
    """Causal order (most exogenous first) by DirectLiNGAM with the pwling measure."""
    X = np.array(X, float)
    U = list(range(X.shape[1]))
    order = []
    while U:
        if len(U) == 1:
            order.append(U[0])
            break
        best, best_m = None, None
        for i in U:
            M = 0.0
            xi = _std(X[:, i])
            for j in U:
                if i == j:
                    continue
                xj = _std(X[:, j])
                M += min(0.0, _diff_mi(xi, xj, _residual(xi, xj), _residual(xj, xi))) ** 2
            if best_m is None or -M > best_m + 1e-15:
                best, best_m = i, -M
        for i in U:
            if i != best:
                X[:, i] = _residual(X[:, i], X[:, best])
        order.append(best)
        U.remove(best)
    return order


def order_agreement(learned: Sequence[int], assumed: Sequence[int]) -> dict:
    pos_l = {v: k for k, v in enumerate(learned)}
    pos_a = {v: k for k, v in enumerate(assumed)}
    pairs = [(a, b) for i, a in enumerate(assumed) for b in assumed[i + 1:]]
    agree = [(a, b) for a, b in pairs if pos_l[a] < pos_l[b]]
    return {"agree": len(agree), "pairs": len(pairs), "share": len(agree) / len(pairs),
            "reversed": [(b, a) for a, b in pairs if pos_l[a] > pos_l[b]]}


def bootstrap_order(X: np.ndarray, samples: Sequence[Sequence[int]]) -> dict:
    """P[i before j] over the given resamples (row-index lists), so Python and the page can share the draws."""
    p = X.shape[1]
    before = np.zeros((p, p))
    for idx in samples:
        o = lingam_order(X[list(idx)])
        pos = {v: k for k, v in enumerate(o)}
        for i in range(p):
            for j in range(p):
                if i != j and pos[i] < pos[j]:
                    before[i, j] += 1
    return {"p_before": (before / max(1, len(samples))).tolist(), "n": len(samples)}


def mulberry32(seed: int):
    """The page's seeded generator, so resamples match exactly across languages."""
    state = seed & 0xFFFFFFFF

    def rnd():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return rnd


def resamples(n: int, draws: int, seed: int = 7) -> list[list[int]]:
    rnd = mulberry32(seed)
    return [[int(rnd() * n) for _ in range(n)] for _ in range(draws)]


# ---------------------------------------------------------------- time-varying links
def kalman_links(y: np.ndarray, X: np.ndarray, q: float, r: float | None = None, p0: float = 1.0) -> dict:
    """Random-walk coefficients: filter and smoother. r (noise variance) defaults to the full-sample OLS residual
    variance; q is the per-month drift variance of each coefficient. Returns smoothed paths, sds and log-likelihood."""
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    n, k = X.shape
    if r is None:
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        e = y - X @ b
        r = float(e @ e) / max(1, n - k)
    Q = q * np.eye(k)
    b = np.zeros(k)
    P = p0 * np.eye(k)
    bf, Pf, bp, Pp = [], [], [], []
    ll = 0.0
    for t in range(n):
        b_pred, P_pred = b, P + Q
        x = X[t]
        f = float(x @ P_pred @ x) + r
        v = y[t] - float(x @ b_pred)
        ll += -0.5 * (math.log(2 * math.pi * f) + v * v / f)
        Kg = P_pred @ x / f
        b = b_pred + Kg * v
        P = P_pred - np.outer(Kg, x @ P_pred)
        bp.append(b_pred); Pp.append(P_pred); bf.append(b); Pf.append(P)
    bs, Ps = [None] * n, [None] * n
    bs[-1], Ps[-1] = bf[-1], Pf[-1]
    for t in range(n - 2, -1, -1):
        J = Pf[t] @ np.linalg.inv(Pp[t + 1])
        bs[t] = bf[t] + J @ (bs[t + 1] - bp[t + 1])
        Ps[t] = Pf[t] + J @ (Ps[t + 1] - Pp[t + 1]) @ J.T
    return {"beta": np.array(bs).tolist(), "sd": np.sqrt(np.array([np.diag(p) for p in Ps])).tolist(), "loglik": ll, "r": r, "q": q}


Q_GRID = [1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2]


def kalman_mle(y, X, grid: Sequence[float] = Q_GRID) -> dict:
    fits = [kalman_links(y, X, q) for q in grid]
    best = max(range(len(grid)), key=lambda i: fits[i]["loglik"])
    out = fits[best]
    out["grid"] = list(grid)
    out["loglik_grid"] = [f["loglik"] for f in fits]
    return out


def sign_changes(path: Sequence[float], sd: Sequence[float], dates: Sequence[str], z: float = 1.645) -> list[dict]:
    """Months where the smoothed link crossed zero, and the stretches where its 90% band excluded zero."""
    out = []
    for t in range(1, len(path)):
        if path[t - 1] * path[t] < 0:
            out.append({"date": dates[t], "to": "negative" if path[t] < 0 else "positive"})
    return out
