"""Robust statistics for the brain's measured links: would the conclusion survive bad months, fat tails and
autocorrelation?

Monthly changes in oil, CPI, yields, stocks, VIX and gold have kurtosis of 5 to 8: a few months (October 2008,
March 2020) can carry a regression. Each measured link is therefore re-estimated four ways, and the page runs the
same arithmetic (site/src/brainx.js; tests/test_v10.py checks they agree):

  ols            least squares with an intercept (the brain's own estimate)
  hac            Newey-West standard errors (Bartlett kernel, lags = floor(4 (n/100)^(2/9))): t-statistics that do
                 not assume independent months
  huber          Huber M-estimate by iteratively reweighted least squares (c = 1.345, scale = MAD / 0.6745):
                 large residuals count linearly instead of quadratically
  influence      the exact change in every coefficient from dropping each month, without refitting:
                 beta_(-i) - beta = -(X'X)^-1 x_i e_i / (1 - h_ii)
  months_to_flip how many of the most influential months must be dropped to reverse the link's sign. Months are
                 ranked by how hard their removal pushes the slope toward zero (the approximate maximum influence
                 perturbation of Broderick, Giordano and Meager) and each count is checked by an actual refit;
                 None means dropping 10% of the sample this way does not reverse it.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np


def _design(X: np.ndarray) -> np.ndarray:
    X = np.asarray(X, float)
    return np.column_stack([np.ones(len(X)), X])


def ols(y, X) -> dict:
    """Slopes (intercept fitted, not returned), classical standard errors, residuals, leverage and (X'X)^-1."""
    y = np.asarray(y, float)
    Z = _design(X)
    n, k = Z.shape
    G = np.linalg.inv(Z.T @ Z)
    b = G @ (Z.T @ y)
    e = y - Z @ b
    s2 = float(e @ e) / max(1, n - k)
    h = np.einsum("ij,jk,ik->i", Z, G, Z)
    return {"beta": b[1:].tolist(), "se": np.sqrt(np.diag(G) * s2)[1:].tolist(), "b_full": b, "e": e, "h": h, "G": G, "Z": Z, "n": n}


def hac_se(fit: dict, lags: int | None = None) -> list[float]:
    Z, e, G, n = fit["Z"], fit["e"], fit["G"], fit["n"]
    L = int(math.floor(4 * (n / 100) ** (2 / 9))) if lags is None else lags
    U = Z * e[:, None]
    S = U.T @ U
    for l in range(1, L + 1):
        w = 1 - l / (L + 1)
        C = U[l:].T @ U[:-l]
        S += w * (C + C.T)
    V = G @ S @ G
    return np.sqrt(np.diag(V))[1:].tolist()


def huber(y, X, c: float = 1.345, iters: int = 100, tol: float = 1e-10) -> dict:
    y = np.asarray(y, float)
    Z = _design(X)
    b = np.linalg.solve(Z.T @ Z, Z.T @ y)
    w = np.ones(len(y))
    for _ in range(iters):
        e = y - Z @ b
        s = float(np.median(np.abs(e - np.median(e)))) / 0.6745
        if s <= 0:
            break
        u = np.abs(e) / s
        w = np.where(u <= c, 1.0, c / np.maximum(u, 1e-300))
        Zw = Z * w[:, None]
        b_new = np.linalg.solve(Z.T @ Zw, Zw.T @ y)
        if float(np.max(np.abs(b_new - b))) < tol:
            b = b_new
            break
        b = b_new
    return {"beta": b[1:].tolist(), "downweighted": int(np.sum(w < 1)), "weights": w.tolist()}


def influence(fit: dict) -> np.ndarray:
    """n x k: the change in each slope from dropping each observation (exact, by the leave-one-out identity)."""
    Z, e, h, G = fit["Z"], fit["e"], fit["h"], fit["G"]
    D = -(Z @ G) * (e / np.maximum(1 - h, 1e-12))[:, None]
    return D[:, 1:]


def months_to_flip(y, X, j: int, max_share: float = 0.10) -> dict:
    """Fewest observations whose removal flips the sign of slope j, verified by refitting."""
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    fit = ols(y, X)
    b = fit["beta"][j]
    D = influence(fit)[:, j]
    toward = -np.sign(b) * D                      # how far dropping each month pushes the slope toward zero
    order = np.argsort(-toward, kind="stable")
    n = len(y)
    kmax = max(1, int(max_share * n))
    for k in range(1, kmax + 1):
        keep = np.ones(n, bool)
        keep[order[:k]] = False
        bk = ols(y[keep], X[keep])["beta"][j]
        if np.sign(bk) != np.sign(b):
            return {"k": k, "share": k / n, "dropped": order[:k].tolist(), "beta_after": bk}
    return {"k": None, "share": None, "dropped": order[: min(5, n)].tolist(), "beta_after": None}


def link_robustness(block: dict, parents: dict, regimes: dict) -> dict:
    """Every measured link, every regime: OLS, HAC t, Huber, the most influential months, and months to flip."""
    cols = block["cols"]
    dates = block["dates"]
    Zs = np.array(block["z"]).T
    out = {}
    for name, (a, b) in regimes.items():
        a_, b_ = a[:7], (b or "9999-12")[:7]
        rows = [i for i, d in enumerate(dates) if a_ <= d <= b_]
        for child, ps in parents.items():
            y = Zs[rows, cols.index(child)]
            X = Zs[np.ix_(rows, [cols.index(p) for p in ps])]
            fit = ols(y, X)
            hac = hac_se(fit)
            hb = huber(y, X)
            D = influence(fit)
            for j, p in enumerate(ps):
                fl = months_to_flip(y, X, j)
                top = np.argsort(-np.abs(D[:, j]), kind="stable")[:3]
                out.setdefault(f"{p}>{child}", {})[name] = {
                    "n": len(rows), "ols": fit["beta"][j], "se": fit["se"][j], "t": fit["beta"][j] / fit["se"][j],
                    "hac_t": fit["beta"][j] / hac[j], "huber": hb["beta"][j], "downweighted": hb["downweighted"],
                    "months_to_flip": fl["k"], "flip_share": fl["share"],
                    "flip_months": [dates[rows[i]] for i in fl["dropped"]][:8] if fl["k"] else [],
                    "most_influential": [{"month": dates[rows[i]], "delta": float(D[i, j])} for i in top]}
    return out
