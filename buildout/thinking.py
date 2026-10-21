"""The brain's reasoning: from what moved to why, what follows, what is wrong with the map, and what to look at next.

The page (site/src/brain.js) runs the same arithmetic on the same graph; tests/test_v08.py checks both languages.
Everything is linear-Gaussian, so every step is exact and inspectable:

  total_effect      T = sum_{k=0..K} (W')^k: how a unit shock at each node reaches every node within K links
  abduce            the root shocks s that best explain the observed nodes y: ridge MAP
                    s = (A'A + lam I)^-1 A'y, A = T[observed, roots], lam = obs_sd^2 / prior_sd^2,
                    with posterior covariance obs_sd^2 (A'A + lam I)^-1 and the share of y explained
  predict           every node's implied value T s and its standard deviation from the posterior covariance
  criticize         standardized residuals (what the map cannot explain) and the link whose change would cut the
                    misfit fastest (gradient of the squared residual with respect to each weight)
  explanations      single-cause hypotheses (and "noise only") ranked by exact Bayesian evidence:
                    y ~ N(0, obs_sd^2 I + prior_sd^2 a a'); posterior over hypotheses with equal priors
  next_observation  the unobserved node whose value would best separate the hypotheses: mutual information
                    between the hypothesis and that node's predictive Gaussian mixture, by quadrature
  intervene         do(node = v): cut the node's incoming links, then propagate (doing), against conditioning on
                    the same value through abduction (seeing); the gap is what the observation would signal
  shared_exposure   cosine similarity of holdings' sensitivities to the root causes: different names, same bet
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np


def weight_matrix(n: int, edges: Sequence[tuple[int, int, float]]) -> np.ndarray:
    W = np.zeros((n, n))
    for f, t, w in edges:
        W[f, t] += w
    return W


def total_effect(n: int, edges, K: int) -> np.ndarray:
    """T[i, j] = effect on node i of a unit shock at node j within K links (the shock itself counts once)."""
    Wt = weight_matrix(n, edges).T
    T = np.eye(n)
    P = np.eye(n)
    for _ in range(K):
        P = Wt @ P
        T = T + P
    return T


def abduce(T: np.ndarray, observed: dict[int, float], roots: Sequence[int], obs_sd: float = 0.5, prior_sd: float = 1.0) -> dict:
    obs = sorted(observed)
    y = np.array([observed[i] for i in obs], float)
    A = T[np.ix_(obs, list(roots))]
    lam = (obs_sd / prior_sd) ** 2
    M = A.T @ A + lam * np.eye(len(roots))
    Minv = np.linalg.inv(M)
    s = Minv @ A.T @ y
    cov = obs_sd ** 2 * Minv
    fit = A @ s
    ss_y = float(y @ y)
    explained = 1 - float((y - fit) @ (y - fit)) / ss_y if ss_y > 0 else 0.0
    return {"obs": obs, "y": y.tolist(), "roots": list(roots), "s": s.tolist(), "sd": np.sqrt(np.diag(cov)).tolist(),
            "cov": cov.tolist(), "fit": fit.tolist(), "explained": explained}


def predict(T: np.ndarray, ab: dict) -> dict:
    Tr = T[:, ab["roots"]]
    mean = Tr @ np.array(ab["s"])
    var = np.einsum("ij,jk,ik->i", Tr, np.array(ab["cov"]), Tr)
    return {"mean": mean.tolist(), "sd": np.sqrt(np.maximum(var, 0)).tolist()}


def criticize(n: int, edges, K: int, ab: dict, obs_sd: float = 0.5, h: float = 1e-4) -> dict:
    """Residuals, and for each edge the derivative of the squared misfit (shocks held at their estimate)."""
    obs, roots, s = ab["obs"], ab["roots"], np.array(ab["s"])
    y = np.array(ab["y"])

    def misfit(E):
        T = total_effect(n, E, K)
        r = y - T[np.ix_(obs, roots)] @ s
        return float(r @ r)
    base = misfit(edges)
    grads = []
    for i, (f, t, w) in enumerate(edges):
        if w == 0:
            grads.append(0.0)
            continue
        E2 = list(edges)
        E2[i] = (f, t, w + h)
        grads.append((misfit(E2) - base) / h)
    resid = (y - np.array(ab["fit"])) / obs_sd
    return {"resid": resid.tolist(), "misfit": base, "grad": grads}


def _log_evidence(y: np.ndarray, a: np.ndarray | None, obs_sd: float, prior_sd: float) -> float:
    """log N(y; 0, obs_sd^2 I + prior_sd^2 a a') by the matrix determinant lemma and Sherman-Morrison."""
    nobs = len(y)
    s2 = obs_sd ** 2
    if a is None:
        return float(-0.5 * (nobs * math.log(2 * math.pi * s2) + (y @ y) / s2))
    aa = float(a @ a)
    c = s2 + prior_sd ** 2 * aa
    q = (float(y @ y) - prior_sd ** 2 * float(a @ y) ** 2 / c) / s2
    logdet = (nobs - 1) * math.log(s2) + math.log(c)
    return float(-0.5 * (nobs * math.log(2 * math.pi) + logdet + q))


def explanations(T: np.ndarray, observed: dict[int, float], roots: Sequence[int], obs_sd: float = 0.5, prior_sd: float = 1.0) -> list[dict]:
    obs = sorted(observed)
    y = np.array([observed[i] for i in obs], float)
    rows = [{"root": None, "logev": _log_evidence(y, None, obs_sd, prior_sd), "s": 0.0, "s_sd": 0.0}]
    for r in roots:
        a = T[obs, r]
        aa = float(a @ a)
        post_var = 1.0 / (aa / obs_sd ** 2 + 1.0 / prior_sd ** 2)
        mean = post_var * float(a @ y) / obs_sd ** 2
        rows.append({"root": int(r), "logev": _log_evidence(y, a, obs_sd, prior_sd), "s": mean, "s_sd": math.sqrt(post_var)})
    m = max(r["logev"] for r in rows)
    z = sum(math.exp(r["logev"] - m) for r in rows)
    for r in rows:
        r["p"] = math.exp(r["logev"] - m) / z
    return sorted(rows, key=lambda r: -r["p"])


def _mixture_entropy(ws, mus, sds, grid: int = 801) -> float:
    lo = min(m - 7 * s for m, s in zip(mus, sds))
    hi = max(m + 7 * s for m, s in zip(mus, sds))
    xs = np.linspace(lo, hi, grid)
    dens = sum(w * np.exp(-0.5 * ((xs - m) / s) ** 2) / (s * math.sqrt(2 * math.pi)) for w, m, s in zip(ws, mus, sds))
    dx = xs[1] - xs[0]
    with np.errstate(divide="ignore", invalid="ignore"):
        f = np.where(dens > 0, -dens * np.log(dens), 0.0)
    return float(f.sum() * dx)


def next_observation(T: np.ndarray, hyps: list[dict], candidates: Sequence[int], obs_sd: float = 0.5, top: int = 6) -> list[dict]:
    """Mutual information I(H; X_u) = h(X_u) - sum_h p_h h(X_u | h), in nats, for each candidate node u."""
    hs = [r for r in hyps if r["p"] > 1e-6][:top]
    tot = sum(r["p"] for r in hs)
    ws = [r["p"] / tot for r in hs]
    out = []
    for u in candidates:
        mus, sds = [], []
        for r in hs:
            if r["root"] is None:
                mus.append(0.0)
                sds.append(obs_sd)
            else:
                g = T[u, r["root"]]
                mus.append(g * r["s"])
                sds.append(math.sqrt(g * g * r["s_sd"] ** 2 + obs_sd ** 2))
        cond = sum(w * 0.5 * math.log(2 * math.pi * math.e * s * s) for w, s in zip(ws, sds))
        out.append({"node": int(u), "info": max(0.0, _mixture_entropy(ws, mus, sds) - cond), "means": mus})
    return sorted(out, key=lambda r: -r["info"])


def intervene(n: int, edges, K: int, node: int, value: float) -> np.ndarray:
    """do(node = value): the node's incoming links are cut, so only its downstream effects remain."""
    cut = [(f, t, w) for f, t, w in edges if t != node]
    return total_effect(n, cut, K)[:, node] * value


def shared_exposure(T: np.ndarray, holdings: Sequence[int], roots: Sequence[int]) -> dict:
    V = T[np.ix_(list(holdings), list(roots))]
    norms = np.linalg.norm(V, axis=1)
    S = (V @ V.T) / np.outer(np.where(norms > 0, norms, 1), np.where(norms > 0, norms, 1))
    return {"sens": V.tolist(), "cos": S.tolist()}


def think(n: int, edges, K: int, observed: dict[int, float], roots: Sequence[int], holdings: Sequence[int],
          obs_sd: float = 0.5, prior_sd: float = 1.0) -> dict:
    T = total_effect(n, edges, K)
    ab = abduce(T, observed, roots, obs_sd, prior_sd)
    pr = predict(T, ab)
    cr = criticize(n, edges, K, ab, obs_sd)
    ex = explanations(T, observed, roots, obs_sd, prior_sd)
    cand = [i for i in range(n) if i not in observed]
    nx = next_observation(T, ex, cand, obs_sd)
    sh = shared_exposure(T, holdings, roots)
    return {"T": T.tolist(), "abduce": ab, "predict": pr, "criticize": cr, "explanations": ex, "next": nx, "shared": sh}
