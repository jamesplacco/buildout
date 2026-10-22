"""How far to trust the brain: honest error bars, a stacked ensemble of world models, and what it would take for an
unseen cause to erase a measured link. Python is canonical; the page renders the result (brain.json or snap12.js).

  models       five rival models of each measured equation (child on its parents, same month), each predicting every
               month from 2000 using only earlier months:
                 history   expanding-window least squares (all past months)
                 recent    least squares on the last 36 months only
                 robust    expanding-window Huber regression (outliers count less)
                 drift     coefficients that drift as a random walk (Kalman filter; drift variance chosen by likelihood
                           on the first ten years only, so nothing is learned from the future)
                 none      no link at all: the child's own past mean and spread
  stacking     the mixture weights that maximize the out-of-sample log score of the combined forecast (Yao, Vehtari,
               Simpson and Gelman, 2018), fitted by EM. Weights at month t use months before t only.
  conformal    adaptive conformal inference (Gibbs and Candes, 2021): the 90% interval's width is the 90% quantile of
               past standardized errors, and the target level adapts after each miss or hit (gamma = 0.005), which
               keeps long-run coverage at 90% even when the world shifts. Compared with the textbook Gaussian interval.
  confounding  the robustness value (Cinelli and Hazlett, 2020): the share of the residual variance of both the parent
               and the child that an unseen confounder would have to explain to erase the link (q = 1), or to make it
               statistically indistinguishable from zero at 5% (RV_q,alpha). Benchmarked against the strongest
               observed parent's partial R squared.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.stats import t as tdist


MODELS = ["history", "recent", "robust", "drift", "none"]
NAMES = {"history": "full-history", "recent": "last-36-months", "robust": "outlier-resistant", "drift": "drifting-links", "none": "no-link"}
START = 120            # first out-of-sample month: ten years of training (1990-02 to 2000-01)
WINDOW = 36
ALPHA = 0.10
GAMMA = 0.005
Z90 = 1.6448536269514722
LOG2PI = math.log(2 * math.pi)


def _ols_pred(Xp: np.ndarray, yp: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    A = np.column_stack([np.ones(len(yp)), Xp])
    b, *_ = np.linalg.lstsq(A, yp, rcond=None)
    e = yp - A @ b
    dof = max(1, len(yp) - A.shape[1])
    s2 = float(e @ e) / dof
    a = np.concatenate([[1.0], x])
    v = s2 * (1.0 + float(a @ np.linalg.pinv(A.T @ A) @ a))
    return float(a @ b), v


def _huber(y: np.ndarray, A: np.ndarray, c: float = 1.345, iters: int = 50, tol: float = 1e-9) -> tuple[np.ndarray, float]:
    """Huber M-estimate with intercept (A carries the ones column) by IRLS; returns coefficients and the MAD scale."""
    b = np.linalg.lstsq(A, y, rcond=None)[0]
    s = 1.0
    for _ in range(iters):
        e = y - A @ b
        s = float(np.median(np.abs(e - np.median(e)))) / 0.6745
        if s <= 0:
            break
        u = np.abs(e) / s
        w = np.where(u <= c, 1.0, c / np.maximum(u, 1e-300))
        Aw = A * w[:, None]
        nb = np.linalg.solve(A.T @ Aw, Aw.T @ y)
        done = float(np.max(np.abs(nb - b))) < tol
        b = nb
        if done:
            break
    e = y - A @ b
    return b, 1.4826 * float(np.median(np.abs(e - np.median(e))))


def _kalman_q(y: np.ndarray, X: np.ndarray) -> float:
    from .discovery import kalman_mle
    A = np.column_stack([np.ones(len(y)), X])
    return float(kalman_mle(y, A)["q"])


def predictions(y: np.ndarray, X: np.ndarray, start: int = START) -> dict:
    """One-step-ahead predictive means and variances of each model for months start..n-1 (each uses months < t)."""
    n = len(y)
    mu = {m: np.zeros(n - start) for m in MODELS}
    var = {m: np.zeros(n - start) for m in MODELS}
    # drift: the Kalman filter run forward once; its predictive at t uses only months < t
    q = _kalman_q(y[:start], X[:start])
    A = np.column_stack([np.ones(n), X])
    k = A.shape[1]
    b, P = np.zeros(k), np.eye(k)
    e0 = y[:start] - A[:start] @ np.linalg.lstsq(A[:start], y[:start], rcond=None)[0]
    r = float(e0 @ e0) / max(1, start - k)
    for t in range(n):
        P_pred = P + q * np.eye(k)
        a = A[t]
        f = float(a @ P_pred @ a) + r
        if t >= start:
            mu["drift"][t - start], var["drift"][t - start] = float(a @ b), f
        v = y[t] - float(a @ b)
        Kg = P_pred @ a / f
        b = b + Kg * v
        P = P_pred - np.outer(Kg, a @ P_pred)
    for t in range(start, n):
        i = t - start
        mu["history"][i], var["history"][i] = _ols_pred(X[:t], y[:t], X[t])
        mu["recent"][i], var["recent"][i] = _ols_pred(X[t - WINDOW:t], y[t - WINDOW:t], X[t])
        coef, mad = _huber(y[:t], A[:t])
        mu["robust"][i], var["robust"][i] = float(A[t] @ coef), max(mad, 1e-6) ** 2 * (1 + 1.0 / t)
        mu["none"][i], var["none"][i] = float(np.mean(y[:t])), float(np.var(y[:t], ddof=1)) * (1 + 1.0 / t)
    return {"mu": mu, "var": var, "q": q}


def log_density(y: np.ndarray, mu: np.ndarray, var: np.ndarray) -> np.ndarray:
    return -0.5 * (LOG2PI + np.log(var) + (y - mu) ** 2 / var)


def stack(logp: np.ndarray, iters: int = 500, tol: float = 1e-10) -> np.ndarray:
    """logp: models x months. Weights on the simplex maximizing sum_t log sum_m w_m p_mt (EM; concave, so global)."""
    M = logp.shape[0]
    w = np.full(M, 1.0 / M)
    if logp.shape[1] == 0:
        return w
    mx = logp.max(axis=0)
    p = np.exp(logp - mx)
    prev = -np.inf
    for _ in range(iters):
        mix = w @ p
        ll = float(np.sum(np.log(mix) + mx))
        w = w * (p / mix).mean(axis=1)
        w = w / w.sum()
        if ll - prev < tol:
            break
        prev = ll
    return w


def _mixture(w: np.ndarray, mu: np.ndarray, var: np.ndarray) -> tuple[float, float]:
    m = float(w @ mu)
    v = float(w @ (var + mu ** 2)) - m * m
    return m, max(v, 1e-12)


def conformal(y: np.ndarray, pred: dict, dates: list[str], start: int = START, min_hist: int = 24) -> dict:
    """Stacked forecasts with weights from past months only, then adaptive conformal 90% intervals."""
    n = len(y) - start
    MU = np.array([pred["mu"][m] for m in MODELS])
    VAR = np.array([pred["var"][m] for m in MODELS])
    LP = np.array([log_density(y[start:], pred["mu"][m], pred["var"][m]) for m in MODELS])
    W = np.zeros((n, len(MODELS)))
    mu_s, sd_s = np.zeros(n), np.zeros(n)
    w = np.full(len(MODELS), 1.0 / len(MODELS))
    for i in range(n):
        if i >= min_hist:
            w = stack(LP[:, :i], iters=200)
        W[i] = w
        mu_s[i], v = _mixture(w, MU[:, i], VAR[:, i])
        sd_s[i] = math.sqrt(v)
    yy = y[start:]
    score = np.abs(yy - mu_s) / sd_s
    alpha_t, cover_aci, cover_gauss, qs = ALPHA, [], [], []
    for i in range(n):
        if i < min_hist:
            q = Z90
        else:
            level = 1 - alpha_t
            q = math.inf if level >= 1 else (0.0 if level <= 0 else float(np.quantile(score[:i], level)))
        qs.append(q)
        miss = score[i] > q
        cover_aci.append(not miss)
        cover_gauss.append(score[i] <= Z90)
        alpha_t = alpha_t + GAMMA * (ALPHA - (1.0 if miss else 0.0))
    level = 1 - alpha_t
    q_next = math.inf if level >= 1 else float(np.quantile(score, min(max(level, 0.0), 1.0)))
    ca, cg = np.array(cover_aci), np.array(cover_gauss)
    d = dates[start:]
    rec = np.array([x >= "2022-01" for x in d])
    qfin = np.array([q if math.isfinite(q) else np.nan for q in qs])
    return {
        "weights_path": W, "mu": mu_s, "sd": sd_s, "score": score, "q": qs, "q_next": q_next, "alpha_next": alpha_t,
        "coverage": {"aci": float(ca.mean()), "gauss": float(cg.mean()),
                     "aci_recent": float(ca[rec].mean()) if rec.any() else None, "gauss_recent": float(cg[rec].mean()) if rec.any() else None},
        "kappa": (q_next / Z90) if math.isfinite(q_next) else None,
        "mean_width": {"aci": float(np.nanmean(2 * qfin * sd_s)), "gauss": float(np.mean(2 * Z90 * sd_s))},
        "logp": LP,
    }


def robustness_value(t: float, dof: int, q: float = 1.0, alpha: float | None = None) -> float:
    """Cinelli and Hazlett (2020), eq. 18 and 19. f is the partial Cohen's f of the link."""
    if dof <= 1:
        return 0.0
    f = abs(t) / math.sqrt(dof)
    fq = q * f
    if alpha is not None:
        fq = fq - float(tdist.ppf(1 - alpha / 2, dof - 1)) / math.sqrt(dof - 1)
        if fq <= 0:
            return 0.0
    return 0.5 * (math.sqrt(fq ** 4 + 4 * fq ** 2) - fq ** 2)


def partial_r2(t: float, dof: int) -> float:
    return t * t / (t * t + dof) if dof > 0 else 0.0


def _regime_ols(y: np.ndarray, X: np.ndarray) -> dict:
    A = np.column_stack([np.ones(len(y)), X])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    e = y - A @ b
    dof = len(y) - A.shape[1]
    s2 = float(e @ e) / max(1, dof)
    se = np.sqrt(np.diag(s2 * np.linalg.pinv(A.T @ A)))
    return {"b": b[1:], "se": se[1:], "dof": dof}


def confounding(block: dict, parents: dict, regimes: dict) -> dict:
    cols, dates = block["cols"], block["dates"]
    Z = np.array(block["z"]).T
    out = {}
    for name, (a, b) in regimes.items():
        a_, b_ = a[:7], (b or "9999-12")[:7]
        rows = [i for i, d in enumerate(dates) if a_ <= d <= b_]
        reg = {}
        for child, ps in parents.items():
            fit = _regime_ols(Z[rows, cols.index(child)], Z[np.ix_(rows, [cols.index(p) for p in ps])])
            ts = [float(fit["b"][j] / fit["se"][j]) for j in range(len(ps))]
            for j, p in enumerate(ps):
                others = [(ps[k], partial_r2(ts[k], fit["dof"])) for k in range(len(ps)) if k != j]
                bench = max(others, key=lambda r: r[1]) if others else (None, 0.0)
                rv = robustness_value(ts[j], fit["dof"])
                reg[f"{p}>{child}"] = {"w": float(fit["b"][j]), "t": ts[j], "dof": fit["dof"], "partial_r2": partial_r2(ts[j], fit["dof"]),
                                       "rv": rv, "rv_alpha": robustness_value(ts[j], fit["dof"], alpha=0.05),
                                       "benchmark": bench[0], "benchmark_r2": bench[1], "survives_benchmark": rv > bench[1]}
        out[name] = {"months": len(rows), "links": reg}
    return out


def analyze(block: dict, parents: dict, regimes: dict, children: list[str] | None = None) -> dict:
    cols, dates = block["cols"], block["dates"]
    Z = np.array(block["z"]).T
    children = children or list(parents)
    eqs = {}
    for child in children:
        y = Z[:, cols.index(child)]
        X = Z[:, [cols.index(p) for p in parents[child]]]
        pred = predictions(y, X)
        c = conformal(y, pred, dates)
        d = dates[START:]
        rec = np.array([x >= "2022-01" for x in d])
        LP = c["logp"]
        w_all = stack(LP)
        w_rec = stack(LP[:, rec]) if rec.sum() >= 12 else None
        e = {"months": len(d), "from": d[0], "to": d[-1], "q_drift": pred["q"],
             "log_score": {m: float(LP[i].mean()) for i, m in enumerate(MODELS)},
             "log_score_recent": {m: float(LP[i, rec].mean()) for i, m in enumerate(MODELS)} if rec.any() else None,
             "weights": dict(zip(MODELS, map(float, w_all))), "weights_recent": dict(zip(MODELS, map(float, w_rec))) if w_rec is not None else None,
             "weights_now": dict(zip(MODELS, map(float, c["weights_path"][-1]))),
             "coverage": c["coverage"], "kappa": c["kappa"], "mean_width": c["mean_width"], "alpha_next": c["alpha_next"]}
        if child == "eq":
            step = 3
            e["path"] = {"dates": d[::step], "weights": {m: [round(float(v), 4) for v in c["weights_path"][::step, i]] for i, m in enumerate(MODELS)}}
            tail = 60
            e["band"] = {"dates": d[-tail:], "y": [round(float(v), 4) for v in y[START:][-tail:]], "mu": [round(float(v), 4) for v in c["mu"][-tail:]],
                         "sd": [round(float(v), 4) for v in c["sd"][-tail:]], "q": [round(float(v), 4) if math.isfinite(v) else None for v in c["q"][-tail:]]}
        eqs[child] = e
    return {"schema": 1, "models": MODELS, "start": dates[START], "alpha": ALPHA, "gamma": GAMMA, "window": WINDOW,
            "equations": eqs, "confounding": confounding(block, parents, regimes)}


def summary(r: dict) -> list[str]:
    """Plain-language lines for the page and the MCP server."""
    out = []
    eq = r["equations"].get("eq")
    if eq:
        best = max(eq["weights_recent"] or eq["weights"], key=lambda m: (eq["weights_recent"] or eq["weights"])[m])
        out.append(f"Stocks' equation: textbook 90% intervals covered {eq['coverage']['gauss']:.0%} of months since {eq['from'][:4]}"
                   f" ({eq['coverage']['gauss_recent']:.0%} since 2022); adaptive conformal intervals covered {eq['coverage']['aci']:.0%}"
                   f" ({eq['coverage']['aci_recent']:.0%} since 2022). Honest intervals today are {eq['kappa']:.2f} times the textbook width.")
        out.append(f"Since 2022 the stacked ensemble puts {100 * (eq['weights_recent'] or eq['weights'])[best]:.0f}% on the {NAMES[best]} model"
                   + (": same-month moves in oil, prices and the 10-year have not improved out-of-sample forecasts of stocks." if best == "none" else "."))
    lk = r["confounding"].get("inflation", {}).get("links", {}).get("y10>eq")
    if lk:
        sig = (f"{lk['rv_alpha']:.0%} to make it insignificant at 5%" if lk["rv_alpha"] > 0 else "it is already not significant at 5%")
        out.append(f"An unseen cause would need to explain {lk['rv']:.0%} of the residual variance of both the 10-year yield and stocks to erase"
                   f" the 2022-on link ({sig}); the strongest observed parent, {lk['benchmark']}, explains {lk['benchmark_r2']:.0%}.")
    return out
