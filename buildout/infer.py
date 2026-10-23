"""Inference: what state is the market in, did something just change, and how are relationships drifting.

    hmm        a Gaussian hidden Markov model of monthly returns (Baum-Welch with scaling, several starts, the number of
               states chosen by BIC); the forward filter gives each month's regime probabilities using only data up to
               that month, the backward pass the smoothed history, Viterbi the single most likely path
    bocpd      Bayesian online changepoint detection (Adams and MacKay 2007) with a Normal-Gamma prior: after each
               month, the posterior over how long the current regime has lasted, and the chance it began recently
    kalman     a time-varying regression y = a_t + b_t x by the Kalman filter, coefficients as random walks: how the
               stock market's response to the 10-year yield has drifted (filtered, so never using the future)
    stack      forecast combination by non-negative least squares on earlier out-of-sample forecasts (stacking), the
               weights summing to one; the honest version of model averaging

Every function is deterministic and causal where it says filtered; the tests plant regimes, changepoints and a
drifting slope and recover them.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.special import gammaln

LOG2PI = math.log(2 * math.pi)


# ---------------------------------------------------------------- hidden Markov model
def _norm_pdf(x: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    z = (x[:, None] - mu[None, :]) / sd[None, :]
    return np.exp(-0.5 * z * z) / (sd[None, :] * math.sqrt(2 * math.pi))


def _forward(B: np.ndarray, pi: np.ndarray, A: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    T, K = B.shape
    alpha = np.zeros((T, K))
    c = np.zeros(T)
    a = pi * B[0]
    c[0] = a.sum() or 1e-300
    alpha[0] = a / c[0]
    for t in range(1, T):
        a = (alpha[t - 1] @ A) * B[t]
        c[t] = a.sum() or 1e-300
        alpha[t] = a / c[t]
    return alpha, c


def _backward(B: np.ndarray, A: np.ndarray, c: np.ndarray) -> np.ndarray:
    T, K = B.shape
    beta = np.ones((T, K))
    for t in range(T - 2, -1, -1):
        beta[t] = (A @ (B[t + 1] * beta[t + 1])) / c[t + 1]
    return beta


# ---------------------------------------------------------------- the forward-backward pass as matrix products
# The forward recursion a_t = a_(t-1) A diag(b_t) is a product of matrices, and matrix multiplication is associative, so
# every prefix product can be formed by doubling: in round r each partial product is multiplied by the one 2^r steps
# back, and after log2(T) rounds of batched matrix multiplication every month's filter is known. The same trick runs
# the backward pass over suffixes, and a leading batch axis runs every random start of the EM at once. This is the
# shortcut AI hardware is built around: many small matrix products at the same time instead of one step after another.
def _scan(C: np.ndarray, reverse: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Inclusive prefix products C[0] C[1] ... C[t] along axis -3 (suffix products C[t] ... C[-1] with reverse=True)
    by Hillis-Steele doubling. Each partial product is rescaled to a total of 1 and its log scale carried."""
    Q = C.copy()
    L = np.zeros(C.shape[:-2])
    n = C.shape[-3]
    d = 1
    while d < n:
        P = Q[..., :-d, :, :] @ Q[..., d:, :, :]
        Ln = L[..., :-d] + L[..., d:]
        if reverse:
            Q[..., :-d, :, :], L[..., :-d] = P, Ln
        else:
            Q[..., d:, :, :], L[..., d:] = P, Ln
        sc = np.einsum("...ij->...", Q)                       # the total of each nonnegative product: one fast contraction
        sc = np.where(sc > 0, sc, 1.0)
        Q /= sc[..., None, None]
        L += np.log(sc)
        d *= 2
    return Q, L


def forward_backward(B: np.ndarray, pi: np.ndarray, A: np.ndarray, smooth: bool = True) -> dict:
    """Filtered and smoothed state probabilities, the summed transition posteriors and the log-likelihood (of the
    emission densities as given), for one sequence or a batch: B [..., T, K], pi [..., K], A [..., K, K]."""
    T, K = B.shape[-2:]
    a1 = pi * B[..., 0, :]
    out: dict = {}
    if T == 1:
        alpha = a1[..., None, :]
        ll = np.log(a1.sum(-1))
    else:
        C = A[..., None, :, :] * B[..., 1:, None, :]                       # C_t = A diag(b_t)
        Qf, Lf = _scan(C)
        rest = (a1[..., None, None, :] @ Qf)[..., 0, :]
        alpha = np.concatenate([a1[..., None, :], rest], axis=-2)
        ll = np.log(alpha[..., -1, :].sum(-1)) + Lf[..., -1]
    alpha = alpha / alpha.sum(-1, keepdims=True)
    out["alpha"], out["loglik"] = alpha, ll
    if not smooth:
        return out
    if T == 1:
        out["gamma"], out["xi"] = alpha, np.zeros(A.shape)
        return out
    Qb, _ = _scan(C, reverse=True)
    beta = np.concatenate([Qb.sum(-1), np.ones(B.shape[:-2] + (1, K))], axis=-2)
    beta = beta / beta.sum(-1, keepdims=True)
    g = alpha * beta
    out["gamma"] = g / g.sum(-1, keepdims=True)
    xi = alpha[..., :-1, :, None] * A[..., None, :, :] * (B[..., 1:, :] * beta[..., 1:, :])[..., None, :]
    xi = xi / xi.sum(axis=(-1, -2), keepdims=True)
    out["xi"] = xi.sum(-3)
    return out


def hmm_fit(x: np.ndarray, K: int = 2, iters: int = 200, starts: int = 4, seed: int = 7, tol: float = 1e-6, min_sd: float = 1e-3) -> dict:
    """Baum-Welch for a K-state Gaussian HMM; the best of several random starts, all run at once as one batch (each
    start stops updating when it converges, exactly as if run alone). States are ordered by mean (state 0 the worst).
    Returns pi, A, mu, sd, the log-likelihood and BIC."""
    x = np.asarray(x, float)
    T = len(x)
    rng = np.random.default_rng(seed)
    MU, SD = [], []
    for s in range(starts):
        q = np.sort(rng.choice(x, K, replace=False)) if s else np.quantile(x, (np.arange(K) + 0.5) / K)
        MU.append(q.astype(float))
        SD.append(np.full(K, x.std()) * (0.6 + 0.8 * rng.random(K) if s else 1.0))
    mu, sd = np.array(MU), np.array(SD)
    A0 = np.full((K, K), 0.05 / max(1, K - 1))
    np.fill_diagonal(A0, 0.95)
    if K == 1:
        A0 = np.ones((1, 1))
    A = np.repeat(A0[None], starts, 0)
    pi = np.full((starts, K), 1.0 / K)
    active = np.ones(starts, bool)
    ll_old = np.full(starts, -np.inf)
    ll_last = np.full(starts, -np.inf)
    for _ in range(iters):
        if not active.any():
            break
        ix = np.flatnonzero(active)                               # only the starts still moving are computed
        z = (x[None, :, None] - mu[ix, None, :]) / sd[ix, None, :]
        B = np.exp(-0.5 * z * z) / (sd[ix, None, :] * math.sqrt(2 * math.pi)) + 1e-300
        mx = B.max(-1, keepdims=True)
        F = forward_backward(B / mx, pi[ix], A[ix])
        ll = F["loglik"] + np.log(mx[..., 0]).sum(-1)
        g, xi = F["gamma"], F["xi"]
        w = g.sum(1)
        mu[ix] = (g * x[None, :, None]).sum(1) / w
        sd[ix] = np.sqrt(np.maximum((g * (x[None, :, None] - mu[ix][:, None, :]) ** 2).sum(1) / w, min_sd ** 2))
        pi[ix] = g[:, 0]
        A[ix] = xi / np.maximum(xi.sum(-1, keepdims=True), 1e-300)
        ll_last[ix] = ll
        done = ll - ll_old[ix] < tol * np.abs(ll)
        ll_old[ix[~done]] = ll[~done]
        active[ix[done]] = False
    best = None
    for s in range(starts):
        if best is None or ll_last[s] > best["loglik"]:
            o = np.argsort(mu[s])
            best = {"K": K, "pi": pi[s][o], "A": A[s][np.ix_(o, o)], "mu": mu[s][o], "sd": sd[s][o], "loglik": float(ll_last[s])}
    p = best["K"] * (best["K"] - 1) + 2 * best["K"] + (best["K"] - 1)       # transitions, means and sds, initial
    best["bic"] = -2 * best["loglik"] + p * math.log(T)
    return best


def hmm_filter(x: np.ndarray, m: dict) -> np.ndarray:
    """P(state at t | data up to t): causal regime probabilities."""
    B = _norm_pdf(np.asarray(x, float), m["mu"], m["sd"]) + 1e-300
    return forward_backward(B / B.max(-1, keepdims=True), m["pi"], m["A"], smooth=False)["alpha"]


def hmm_smooth(x: np.ndarray, m: dict) -> np.ndarray:
    B = _norm_pdf(np.asarray(x, float), m["mu"], m["sd"]) + 1e-300
    return forward_backward(B / B.max(-1, keepdims=True), m["pi"], m["A"])["gamma"]


def viterbi(x: np.ndarray, m: dict) -> np.ndarray:
    lB = np.log(_norm_pdf(np.asarray(x, float), m["mu"], m["sd"]) + 1e-300)
    lA = np.log(m["A"] + 1e-300)
    T, K = lB.shape
    d = np.log(m["pi"] + 1e-300) + lB[0]
    bp = np.zeros((T, K), int)
    for t in range(1, T):
        s = d[:, None] + lA
        bp[t] = s.argmax(0)
        d = s.max(0) + lB[t]
    path = np.zeros(T, int)
    path[-1] = int(d.argmax())
    for t in range(T - 1, 0, -1):
        path[t - 1] = bp[t, path[t]]
    return path


def hmm_select(x: np.ndarray, Ks=(1, 2, 3, 4), **kw) -> dict:
    fits = {K: hmm_fit(x, K, **kw) for K in Ks}
    best = min(fits.values(), key=lambda m: m["bic"])
    return {"best": best, "bic": {K: m["bic"] for K, m in fits.items()}}


def hmm_next(prob: np.ndarray, m: dict) -> dict:
    """Next month's return distribution given today's regime probabilities: a mixture of the states' normals."""
    w = prob @ m["A"]
    mean = float(w @ m["mu"])
    var = float(w @ (m["sd"] ** 2 + m["mu"] ** 2) - mean ** 2)
    return {"weights": w, "mean": mean, "sd": math.sqrt(max(var, 0.0))}


def mixture_cvar(w: np.ndarray, mu: np.ndarray, sd: np.ndarray, alpha: float = 0.05, n: int = 4001) -> tuple[float, float]:
    """Value at risk and expected shortfall (as positive losses) of a normal mixture, by a fine grid."""
    lo, hi = float((mu - 6 * sd).min()), float((mu + 6 * sd).max())
    g = np.linspace(lo, hi, n)
    pdf = (w[None, :] * np.exp(-0.5 * ((g[:, None] - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))).sum(1)
    cdf = np.cumsum(pdf) * (g[1] - g[0])
    cdf /= cdf[-1]
    i = int(np.searchsorted(cdf, alpha))
    var = -g[i]
    tail = pdf[: i + 1]
    es = -float((g[: i + 1] * tail).sum() / tail.sum()) if tail.sum() > 0 else var
    return float(var), es


# ---------------------------------------------------------------- changepoints
def bocpd(x: np.ndarray, hazard: float = 1 / 120, mu0: float = 0.0, kappa0: float = 1.0, alpha0: float = 2.0, beta0: float | None = None, rmax: int = 600) -> dict:
    """Run-length posterior after each observation (Adams and MacKay 2007), Normal-Gamma conjugate prior with a
    Student-t predictive. Returns for each t: P(run length < 6), the most likely run length, the expected one, and the
    moment-matched predictive mean and sd of observation t+1 given data up to t."""
    x = np.asarray(x, float)
    if beta0 is None:
        beta0 = float(np.var(x[: min(len(x), 120)])) * alpha0 if len(x) > 2 else 1.0
    T = len(x)
    R = np.array([1.0])
    mu, kap, al, be = np.array([mu0]), np.array([kappa0]), np.array([alpha0]), np.array([beta0])
    recent, mapr, er = np.zeros(T), np.zeros(T, int), np.zeros(T)
    pm, ps = np.zeros(T), np.zeros(T)
    for t in range(T):
        df = 2 * al
        scale = np.sqrt(be * (kap + 1) / (al * kap))
        z = (x[t] - mu) / scale
        lp = gammaln((df + 1) / 2) - gammaln(df / 2) - 0.5 * np.log(df * math.pi) - np.log(scale) - (df + 1) / 2 * np.log1p(z * z / df)
        pred = np.exp(lp - lp.max())
        growth = R * pred * (1 - hazard)
        cp = float((R * pred * hazard).sum())
        R = np.concatenate([[cp], growth])
        R /= R.sum()
        mu_n = np.concatenate([[mu0], (kap * mu + x[t]) / (kap + 1)])
        kap_n = np.concatenate([[kappa0], kap + 1])
        al_n = np.concatenate([[alpha0], al + 0.5])
        be_n = np.concatenate([[beta0], be + kap * (x[t] - mu) ** 2 / (2 * (kap + 1))])
        mu, kap, al, be = mu_n, kap_n, al_n, be_n
        if len(R) > rmax:
            R, mu, kap, al, be = R[:rmax], mu[:rmax], kap[:rmax], al[:rmax], be[:rmax]
            R /= R.sum()
        # the predictive for the next observation, moment-matched: a mixture over run lengths of Student-t's
        df_n = 2 * al
        var_n = be * (kap + 1) / (al * kap) * df_n / np.maximum(df_n - 2, 1e-9)
        pm[t] = float(R @ mu)
        ps[t] = math.sqrt(max(float(R @ (var_n + mu ** 2)) - pm[t] ** 2, 1e-12))
        recent[t] = float(R[:6].sum())
        mapr[t] = int(R.argmax())
        er[t] = float((np.arange(len(R)) * R).sum())
    return {"recent": recent, "map_run": mapr, "expected_run": er, "pred_mean": pm, "pred_sd": ps}


# ---------------------------------------------------------------- drifting relationships
def kalman_regression(y: np.ndarray, x: np.ndarray, q: float = 1e-4, r: float | None = None, a0: tuple[float, float] = (0.0, 0.0), p0: float = 1.0) -> dict:
    """y_t = a_t + b_t x_t + e_t with (a, b) a random walk (state noise q times identity, measurement noise r).
    Filtered estimates and their standard errors, each using data up to t only."""
    y, x = np.asarray(y, float), np.asarray(x, float)
    r = float(np.var(y)) if r is None else r
    th = np.array(a0, float)
    P = np.eye(2) * p0
    Q = np.eye(2) * q
    out_b, out_a, se_b = np.zeros(len(y)), np.zeros(len(y)), np.zeros(len(y))
    for t in range(len(y)):
        P = P + Q
        h = np.array([1.0, x[t]])
        s = float(h @ P @ h + r)
        k = P @ h / s
        th = th + k * (y[t] - h @ th)
        P = P - np.outer(k, h) @ P
        out_a[t], out_b[t], se_b[t] = th[0], th[1], math.sqrt(max(P[1, 1], 0.0))
    return {"a": out_a, "b": out_b, "se_b": se_b}


# ---------------------------------------------------------------- combination
def stack(P: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Non-negative weights summing to one that minimize the squared error of the combined forecast P @ w on past
    out-of-sample forecasts (rows with any NaN are ignored). Equal weights when there is too little history."""
    from scipy.optimize import nnls
    P, y = np.asarray(P, float), np.asarray(y, float)
    ok = np.isfinite(P).all(1) & np.isfinite(y)
    k = P.shape[1]
    if ok.sum() < max(24, 3 * k):
        return np.full(k, 1.0 / k)
    w, _ = nnls(P[ok], y[ok])
    if w.sum() <= 0:
        return np.full(k, 1.0 / k)
    return w / w.sum()


def gauss_hermite_log_growth(x: np.ndarray, mean: float, sd: float, n: int = 40) -> np.ndarray:
    """E[log(1 + x R)] for R ~ normal(mean, sd), for each exposure x, by Gauss-Hermite quadrature; returns below
    -99% are clipped (a levered position cannot lose more than everything)."""
    z, w = np.polynomial.hermite_e.hermegauss(n)
    w = w / w.sum()
    R = mean + sd * z
    v = 1 + np.outer(np.asarray(x, float), R)
    return (np.log(np.maximum(v, 0.01)) * w[None, :]).sum(1)


# ---------------------------------------------------------------- multivariate regimes
def _mv_logpdf(X: np.ndarray, mu: np.ndarray, S: np.ndarray) -> np.ndarray:
    """log N(x; mu_k, S_k) for every row and state: [T, K]."""
    T, d = X.shape
    K = len(mu)
    out = np.empty((T, K))
    for k in range(K):
        L = np.linalg.cholesky(S[k])
        z = np.linalg.solve(L, (X - mu[k]).T)
        out[:, k] = -0.5 * (z * z).sum(0) - np.log(np.diag(L)).sum() - 0.5 * d * LOG2PI
    return out


def _scaled(lB: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    m = lB.max(1, keepdims=True)
    return np.exp(lB - m), m[:, 0]


def _regularize(S: np.ndarray, floor: float, shrink: float) -> np.ndarray:
    d = S.shape[-1]
    diag = np.einsum("...ii->...i", S)
    target = np.zeros_like(S)
    idx = np.arange(d)
    target[..., idx, idx] = diag
    S = (1 - shrink) * S + shrink * target
    S[..., idx, idx] += floor
    return S


def mvhmm_fit(X: np.ndarray, K: int = 2, iters: int = 150, starts: int = 3, seed: int = 7, tol: float = 1e-6, init: dict | None = None,
              floor: float = 1e-6, shrink: float = 0.05, order_by: int = 0) -> dict:
    """Baum-Welch for a K-state HMM with full-covariance normal emissions (several assets at once, so the regime also
    describes how they move together), every start run at once as one batch. Covariances are shrunk 5% toward their
    diagonal and floored. `init` warm-starts from an earlier fit (refits then take a few iterations, and the states
    keep their meaning). States are ordered by the mean of column `order_by` (state 0 the worst)."""
    X = np.asarray(X, float)
    T, d = X.shape
    rng = np.random.default_rng(seed)
    tries = ([init] if init is not None and init["K"] == K else []) + [None] * (starts if init is None or init["K"] != K else 1)
    PI, AA, MU, SS = [], [], [], []
    for s, ini in enumerate(tries):
        if ini is not None:
            pi, A, mu, S = ini["pi"].copy(), ini["A"].copy(), ini["mu"].copy(), ini["S"].copy()
        else:
            if s == 0:
                q = np.argsort(X[:, order_by])
                mu = np.array([X[q[int(len(q) * (k + 0.5) / K)]] for k in range(K)])
            else:
                mu = X[rng.choice(T, K, replace=False)]
            S = np.repeat(np.cov(X.T)[None], K, 0) * (0.6 + 0.8 * rng.random(K))[:, None, None] if s else np.repeat(np.cov(X.T)[None], K, 0)
            S = _regularize(S, floor, shrink)
            A = np.full((K, K), 0.05 / max(1, K - 1))
            np.fill_diagonal(A, 0.95)
            if K == 1:
                A = np.ones((1, 1))
            pi = np.full(K, 1.0 / K)
        PI.append(pi); AA.append(A); MU.append(mu); SS.append(S)
    pi, A, mu, S = np.array(PI), np.array(AA), np.array(MU, float), np.array(SS, float)
    n = len(tries)
    active = np.ones(n, bool)
    ll_old = np.full(n, -np.inf)
    ll_last = np.full(n, -np.inf)
    for _ in range(iters):
        if not active.any():
            break
        ix = np.flatnonzero(active)
        lB = np.stack([_mv_logpdf(X, mu[s], S[s]) for s in ix])
        mx = lB.max(-1, keepdims=True)
        F = forward_backward(np.exp(lB - mx), pi[ix], A[ix])
        ll = F["loglik"] + mx[..., 0].sum(-1)
        g, xi = F["gamma"], F["xi"]
        w = g.sum(1) + 1e-12                                                  # [n, K]
        mu[ix] = np.einsum("stk,td->skd", g, X) / w[..., None]
        D = X[None, None, :, :] - mu[ix][:, :, None, :]                       # [n, K, T, d]
        S[ix] = _regularize(np.einsum("stk,sktd,skte->skde", g, D, D) / w[..., None, None], floor, shrink)
        pi[ix] = g[:, 0]
        A[ix] = xi / np.maximum(xi.sum(-1, keepdims=True), 1e-300)
        ll_last[ix] = ll
        done = ll - ll_old[ix] < tol * np.abs(ll)
        ll_old[ix[~done]] = ll[~done]
        active[ix[done]] = False
    best = None
    for s in range(n):
        if best is None or ll_last[s] > best["loglik"]:
            o = np.argsort(mu[s][:, order_by])
            best = {"K": K, "d": d, "pi": pi[s][o], "A": A[s][np.ix_(o, o)], "mu": mu[s][o], "S": S[s][o], "loglik": float(ll_last[s])}
    p = K * (K - 1) + K * d + K * d * (d + 1) // 2 + (K - 1)
    best["bic"] = -2 * best["loglik"] + p * math.log(T)
    return best


def mvhmm_select(X: np.ndarray, Ks=(1, 2, 3), init: dict | None = None, **kw) -> dict:
    fits = {K: mvhmm_fit(X, K, init=init if init is not None and init.get("K") == K else None, **kw) for K in Ks}
    best = min(fits.values(), key=lambda m: m["bic"])
    return {"best": best, "bic": {K: m["bic"] for K, m in fits.items()}, "fits": fits}


def mvhmm_filter(X: np.ndarray, m: dict) -> np.ndarray:
    B, _ = _scaled(_mv_logpdf(np.asarray(X, float), m["mu"], m["S"]))
    return forward_backward(B, m["pi"], m["A"], smooth=False)["alpha"]


def mvhmm_smooth(X: np.ndarray, m: dict) -> np.ndarray:
    B, _ = _scaled(_mv_logpdf(np.asarray(X, float), m["mu"], m["S"]))
    return forward_backward(B, m["pi"], m["A"])["gamma"]


def mvviterbi(X: np.ndarray, m: dict) -> np.ndarray:
    lB = _mv_logpdf(np.asarray(X, float), m["mu"], m["S"])
    lA = np.log(m["A"] + 1e-300)
    T, K = lB.shape
    dd = np.log(m["pi"] + 1e-300) + lB[0]
    bp = np.zeros((T, K), int)
    for t in range(1, T):
        s = dd[:, None] + lA
        bp[t] = s.argmax(0)
        dd = s.max(0) + lB[t]
    path = np.zeros(T, int)
    path[-1] = int(dd.argmax())
    for t in range(T - 1, 0, -1):
        path[t - 1] = bp[t, path[t]]
    return path


def stationary(A: np.ndarray) -> np.ndarray:
    w, v = np.linalg.eig(A.T)
    p = np.real(v[:, np.argmin(np.abs(w - 1))])
    p = np.abs(p)
    return p / p.sum()


# ---------------------------------------------------------------- online learning over policies
def hedge_weights(losses: np.ndarray, eta: float, prior: np.ndarray | None = None) -> np.ndarray:
    """Exponential weights (Freund and Schapire's Hedge) after each round: losses [T, N], the weight row t uses only
    rounds before t. Regret against the best single policy in hindsight is at most ln(N)/eta + eta T L^2 / 8 for
    losses bounded by L."""
    T, N = losses.shape
    w = np.full(N, 1.0 / N) if prior is None else np.asarray(prior, float) / np.sum(prior)
    lw = np.log(w)
    out = np.zeros((T, N))
    for t in range(T):
        z = lw - lw.max()
        out[t] = np.exp(z) / np.exp(z).sum()
        lt = losses[t]
        if np.isfinite(lt).all():
            lw = lw - eta * lt
    return out
