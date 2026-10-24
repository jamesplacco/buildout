"""Cross-field methods: the best-tested tools of actuarial science and weather forecasting, ported for the decision engine.

Actuarial science
    gpd_fit, pot          the generalized Pareto distribution fit to excesses over a high threshold (peaks over
                          threshold; Pickands 1975, Balkema and de Haan 1974, Davison and Smith 1990) by maximum
                          likelihood with observed-information standard errors, probability-weighted moments (Hosking
                          and Wallis 1987) as the fallback
    gpd_var_es            the POT value at risk and expected shortfall (McNeil, Frey and Embrechts 2005, section 7.2)
    return_level/period   the loss exceeded once every m months, and how often a loss is exceeded
    mean_excess,
    threshold_stability   the two standard threshold diagnostics: a linear mean-excess plot and stable shape estimates
    tail_backtest         VaR and ES walked forward with Kupiec (1995), Christoffersen (1998) and Acerbi-Szekely (2014) Z2
    ruin_probability      a finite-horizon drawdown ruin probability by stationary bootstrap (Politis and Romano 1994)
    cramer_lundberg       the adjustment coefficient and Lundberg bound for a Brownian surplus
    buhlmann,
    buhlmann_straub       credibility theory (Buhlmann 1967, Buhlmann and Straub 1970): how much a group's own record
                          should count against the collective's
    credibility_n0        the pseudo-count decide.shrink() uses, estimated from the data instead of set by hand

Weather forecasting (verification and post-processing)
    crps_normal,
    crps_mixture          the continuous ranked probability score in closed form (Gneiting and Raftery 2007; Grimit,
                          Gneiting, Berrocal and Johnson 2006 for mixtures of normals)
    log_score_mixture,
    pit_mixture,
    pit_histogram         the probability integral transform and its uniformity tests (Dawid 1984; Diebold, Gunther and
                          Tay 1998; Berkowitz 2001)
    interval_coverage     central-interval coverage with the Kupiec and Christoffersen tests
    brier                 the Brier score with the Murphy (1973) decomposition, extended for binned forecasts
                          (Stephenson, Coelho and Jolliffe 2008)
    skill, spread_skill   skill against climatology and persistence; the spread-skill relationship
    emos_fit, emos_walk   ensemble model output statistics, or nonhomogeneous Gaussian regression (Gneiting, Raftery,
                          Westveld and Goldman 2005): N(a + b mu, c + d sd^2) fit by minimum CRPS, walked forward
    mixture_recalibrate   the same location and spread correction applied to a mixture without losing its shape
    bma_weights, bma_walk Bayesian model averaging weights by EM (Raftery, Gneiting, Balabdaoui and Polakowski 2005)

evaluate_engine(D) scores the engine's own predictive mixture since 1940 with all of the above and says which methods
pass the adoption rule; summary(o) reads the result in plain English. Every function is deterministic; every function
that returns a report returns plain JSON types (numbers, strings, lists, None for not available).
"""
from __future__ import annotations

import math
import time

import numpy as np
from scipy import optimize, stats
from scipy.special import logsumexp, ndtr, xlogy

from .jsonout import clean as _clean0

LAG = 2                        # as decide.LAG: a month's forecast uses outcomes known two months earlier
SQPI = 1.0 / math.sqrt(math.pi)
SQ2PI = math.sqrt(2 * math.pi)
BGK = 0.5826                   # Broadie, Glasserman and Kou (1997): the discrete-monitoring barrier shift, zeta(1/2)/sqrt(2 pi)
ES_LIMIT = 0.12                # as decide.ES_LIMIT: the engine's monthly expected-shortfall budget at 5%
ADOPT_T = 2.0


def jsonable(o):
    """Plain JSON types, full precision: arrays to lists, NaN and infinity to None, numpy scalars to Python numbers."""
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return float(o) if math.isfinite(o) else None
    if o is None or isinstance(o, str):
        return o
    return _clean0(o)


def _phi(z):
    return np.exp(-0.5 * z * z) / SQ2PI


# ================================================================ mixtures of normals
def pad(ws, mus, sds) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Ragged per-month mixtures (lists of arrays, None for a month without one) as padded (T, K) arrays: padding has
    weight 0, mean 0, sd 1, and a month without a mixture has NaN everywhere."""
    T = len(ws)
    K = max([len(np.atleast_1d(w)) for w in ws if w is not None] or [1])
    W, MU, SD = np.zeros((T, K)), np.zeros((T, K)), np.ones((T, K))
    for t in range(T):
        if ws[t] is None:
            W[t], MU[t], SD[t] = np.nan, np.nan, np.nan
            continue
        w, m, s = np.atleast_1d(ws[t]).astype(float), np.atleast_1d(mus[t]).astype(float), np.atleast_1d(sds[t]).astype(float)
        k = len(w)
        W[t, :k], MU[t, :k], SD[t, :k] = w / w.sum(), m, s
    return W, MU, SD


def _mix(w, mu, sd):
    w, mu, sd = np.asarray(w, float), np.asarray(mu, float), np.asarray(sd, float)
    w, mu, sd = np.broadcast_arrays(w, mu, sd)
    with np.errstate(invalid="ignore", divide="ignore"):
        w = w / w.sum(-1, keepdims=True)
    return w, mu, sd


def mixture_moments(w, mu, sd) -> tuple[np.ndarray, np.ndarray]:
    """Mean and sd of each mixture (last axis is the component)."""
    w, mu, sd = _mix(w, mu, sd)
    m = (w * mu).sum(-1)
    v = (w * (sd ** 2 + mu ** 2)).sum(-1) - m ** 2
    return m, np.sqrt(np.maximum(v, 0.0))


def _A(m, s):
    """E|X| for X ~ N(m, s^2)."""
    z = m / s
    return m * (2 * ndtr(z) - 1) + 2 * s * _phi(z)


def crps_normal(mu, sd, y) -> np.ndarray:
    """CRPS of N(mu, sd^2) at y, closed form: sd [z (2 Phi(z) - 1) + 2 phi(z) - 1/sqrt(pi)], z = (y - mu)/sd."""
    mu, sd, y = np.asarray(mu, float), np.asarray(sd, float), np.asarray(y, float)
    z = (y - mu) / sd
    return sd * (z * (2 * ndtr(z) - 1) + 2 * _phi(z) - SQPI)


def _crps_mix_pair(w, mu, sd) -> np.ndarray:
    """The spread term E|X - X'| of each mixture."""
    S = np.sqrt(sd[..., :, None] ** 2 + sd[..., None, :] ** 2)
    return (w[..., :, None] * w[..., None, :] * _A(mu[..., :, None] - mu[..., None, :], S)).sum((-1, -2))


def crps_mixture(w, mu, sd, y) -> np.ndarray:
    """CRPS of a mixture of normals at y (Grimit, Gneiting, Berrocal and Johnson 2006): E|X - y| - E|X - X'|/2 with
    E|X - y| = sum_i w_i A(y - mu_i, sd_i) and E|X - X'| = sum_ij w_i w_j A(mu_i - mu_j, sqrt(sd_i^2 + sd_j^2)), where
    A(m, s) = m (2 Phi(m/s) - 1) + 2 s phi(m/s) is the mean of |N(m, s^2)|. The last axis is the component."""
    w, mu, sd = _mix(w, mu, sd)
    y = np.asarray(y, float)
    return (w * _A(y[..., None] - mu, sd)).sum(-1) - 0.5 * _crps_mix_pair(w, mu, sd)


def log_score_mixture(w, mu, sd, y) -> np.ndarray:
    """log p(y) under the mixture (positively oriented, as decide's log scores)."""
    w, mu, sd = _mix(w, mu, sd)
    y = np.asarray(y, float)
    z = (y[..., None] - mu) / sd
    with np.errstate(divide="ignore"):
        lw = np.log(w)
    return logsumexp(lw - 0.5 * z * z - np.log(sd * SQ2PI), axis=-1)


def pit_mixture(w, mu, sd, y) -> np.ndarray:
    """F(y) under the mixture: uniform on [0, 1] when the forecasts are calibrated."""
    w, mu, sd = _mix(w, mu, sd)
    y = np.asarray(y, float)
    return (w * ndtr((y[..., None] - mu) / sd)).sum(-1)


def mixture_quantile(w, mu, sd, p, iters: int = 80) -> np.ndarray:
    """The p-quantile of each mixture by vectorized bisection (p broadcasts against the leading axes)."""
    w, mu, sd = _mix(w, mu, sd)
    p = np.asarray(p, float)
    lo = np.broadcast_to((mu - 12 * sd).min(-1), np.broadcast_shapes(mu.shape[:-1], p.shape)).copy()
    hi = np.broadcast_to((mu + 12 * sd).max(-1), lo.shape).copy()
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        below = (w * ndtr((mid[..., None] - mu) / sd)).sum(-1) < p
        lo = np.where(below, mid, lo)
        hi = np.where(below, hi, mid)
    return 0.5 * (lo + hi)


def mixture_var_es(w, mu, sd, p) -> tuple[np.ndarray, np.ndarray]:
    """VaR and ES of a mixture as positive losses, in closed form given the quantile q:
    ES = -(1/p) sum_i w_i [mu_i Phi(z_i) - sd_i phi(z_i)], z_i = (q - mu_i)/sd_i."""
    w, mu, sd = _mix(w, mu, sd)
    q = mixture_quantile(w, mu, sd, p)
    z = (q[..., None] - mu) / sd
    tail = (w * (mu * ndtr(z) - sd * _phi(z))).sum(-1)
    return -q, -tail / np.asarray(p, float)


def mixture_recalibrate(w, mu, sd, a, b, s) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A location shift and a scale inflation applied to a mixture without changing its shape: X' = a + b m + s (X - m),
    m the mixture's mean. The new mean is a + b m (the EMOS location), the new sd s times the old; each component's
    mean moves to a + b m + s (mu_i - m) and its sd to s sd_i. a, b, s broadcast over the leading axes."""
    w, mu, sd = _mix(w, mu, sd)
    m, _ = mixture_moments(w, mu, sd)
    a, b, s = (np.asarray(v, float)[..., None] for v in (a, b, s))
    return w, a + b * m[..., None] + s * (mu - m[..., None]), s * sd


# ================================================================ forecast verification
def dm_test(d, lags: int = 12) -> dict:
    """Diebold-Mariano style test that the mean score difference d is zero, with a Newey-West (Bartlett) variance."""
    d = np.asarray(d, float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return {"mean": None, "se": None, "t": None, "p": None, "n": n}
    e = d - d.mean()
    v = float(e @ e) / n
    for L in range(1, lags + 1):
        v += 2 * (1 - L / (lags + 1)) * float(e[L:] @ e[:-L]) / n
    se = math.sqrt(max(v, 1e-30) / n)
    t = float(d.mean() / se)
    return {"mean": float(d.mean()), "se": se, "t": t, "p": float(2 * stats.norm.sf(abs(t))), "n": n}


def _acf1(x) -> float:
    x = np.asarray(x, float) - np.mean(x)
    den = float(x @ x)
    return float(x[1:] @ x[:-1] / den) if den > 0 else 0.0


def pit_histogram(pit, bins: int = 10) -> dict:
    """Uniformity of the PIT: the histogram, a chi-square and a Kolmogorov-Smirnov test, and the Berkowitz (2001)
    likelihood-ratio test on z = Phi^-1(PIT) (mean 0, variance 1, no first-order autocorrelation; chi-square, 3 df).

    Serial dependence: the chi-square and KS p-values assume independent PITs. One-step forecasts of a calibrated model
    give independent PITs, but monthly returns cluster in volatility, so a miscalibrated spread produces runs of extreme
    PITs and the nominal tests overstate the evidence. The *_neff p-values shrink the sample to an effective size
    n (1 - rho)/(1 + rho), rho the larger first-order autocorrelation of the PIT and of its squared distance from 1/2;
    Berkowitz handles first-order dependence in the mean explicitly; berkowitz_marginal drops the autocorrelation term
    (2 df), so a rejection there is about the forecast distribution itself rather than about predictable dependence."""
    u = np.asarray(pit, float)
    u = u[np.isfinite(u)]
    n = len(u)
    cnt = np.histogram(u, bins=np.linspace(0, 1, bins + 1))[0]
    exp_ = n / bins
    chi = float(((cnt - exp_) ** 2 / exp_).sum())
    ks = stats.kstest(u, "uniform")
    rho = max(abs(_acf1(u)), abs(_acf1((u - 0.5) ** 2)))
    rho = min(rho, 0.95)
    neff = max(10.0, n * (1 - rho) / (1 + rho))
    z = stats.norm.ppf(np.clip(u, 1e-10, 1 - 1e-10))
    zl, zc = z[:-1], z[1:]
    X = np.column_stack([np.ones(n - 1), zl])
    beta, *_ = np.linalg.lstsq(X, zc, rcond=None)
    res = zc - X @ beta
    s2 = float(res @ res) / (n - 1)
    ll1 = -0.5 * (n - 1) * (math.log(2 * math.pi * s2) + 1)
    ll0 = float(-0.5 * (n - 1) * math.log(2 * math.pi) - 0.5 * (zc @ zc))
    lr_b = max(0.0, 2 * (ll1 - ll0))
    zm, zv = float(z.mean()), float(z.var())
    lr_m = max(0.0, float(n * (zv - 1 - math.log(zv)) + n * zm ** 2))     # N(m, v) against N(0, 1), no dependence: 2 df
    return {"n": n, "bins": bins, "counts": cnt.tolist(), "chi2": chi, "chi2_p": float(stats.chi2.sf(chi, bins - 1)),
            "chi2_p_neff": float(stats.chi2.sf(chi * neff / n, bins - 1)), "ks": float(ks.statistic), "ks_p": float(ks.pvalue),
            "ks_p_neff": float(stats.kstwo.sf(float(ks.statistic), int(round(neff)))), "rho": rho, "n_eff": neff,
            "berkowitz_lr": lr_b, "berkowitz_p": float(stats.chi2.sf(lr_b, 3)), "berkowitz_marginal_lr": lr_m, "berkowitz_marginal_p": float(stats.chi2.sf(lr_m, 2)),
            "z_mean": float(z.mean()), "z_sd": float(z.std()), "z_acf1": float(beta[1]),
            "pit_sd": float(u.std()), "pit_sd_uniform": 1 / math.sqrt(12)}


def kupiec(hits, p: float) -> dict:
    """Kupiec (1995) proportion-of-failures likelihood ratio: are the exceedances as frequent as p? chi-square, 1 df."""
    I = np.asarray(hits, bool)
    n, x = len(I), int(I.sum())
    if n == 0:
        return {"n": 0, "x": 0, "rate": None, "lr": None, "p": None}
    ph = x / n
    lr = -2 * (xlogy(n - x, 1 - p) + xlogy(x, p) - xlogy(n - x, 1 - ph) - xlogy(x, ph))
    lr = max(float(lr), 0.0)
    return {"n": n, "x": x, "expected": n * p, "rate": ph, "lr": lr, "p": float(stats.chi2.sf(lr, 1)),
            "direction": "too many" if ph > p else ("too few" if ph < p else "exact")}


def christoffersen(hits, p: float | None = None) -> dict:
    """Christoffersen (1998) independence test (first-order Markov against independence, chi-square 1 df) and, with p,
    the conditional-coverage test that adds Kupiec's (2 df)."""
    I = np.asarray(hits, int)
    a, b = I[:-1], I[1:]
    n00, n01 = int(((a == 0) & (b == 0)).sum()), int(((a == 0) & (b == 1)).sum())
    n10, n11 = int(((a == 1) & (b == 0)).sum()), int(((a == 1) & (b == 1)).sum())
    p01 = n01 / max(n00 + n01, 1)
    p11 = n11 / max(n10 + n11, 1)
    pi = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)
    l0 = xlogy(n00 + n10, 1 - pi) + xlogy(n01 + n11, pi)
    l1 = xlogy(n00, 1 - p01) + xlogy(n01, p01) + xlogy(n10, 1 - p11) + xlogy(n11, p11)
    lr = max(float(-2 * (l0 - l1)), 0.0)
    out = {"n00": n00, "n01": n01, "n10": n10, "n11": n11, "p_after_hit": p11, "p_after_no_hit": p01, "lr_ind": lr, "p_ind": float(stats.chi2.sf(lr, 1))}
    if p is not None:
        k = kupiec(I.astype(bool), p)
        out["lr_cc"] = lr + (k["lr"] or 0.0)
        out["p_cc"] = float(stats.chi2.sf(out["lr_cc"], 2))
    return out


def interval_coverage(pit, level: float = 0.9) -> dict:
    """Coverage of the central `level` interval read off the PIT, with Kupiec and Christoffersen tests on the misses."""
    u = np.asarray(pit, float)
    u = u[np.isfinite(u)]
    lo = (1 - level) / 2
    miss = (u < lo) | (u > 1 - lo)
    k = kupiec(miss, 1 - level)
    c = christoffersen(miss, 1 - level)
    return {"level": level, "coverage": float(1 - miss.mean()), "n": len(u), "below": float((u < lo).mean()), "above": float((u > 1 - lo).mean()),
            "kupiec_p": k["p"], "independence_p": c["p_ind"], "cc_p": c["p_cc"]}


def brier(p, o, bins: int | None = None) -> dict:
    """Brier score with the Murphy (1973) decomposition BS = REL - RES + UNC. When forecasts are binned and vary within
    a bin, two terms complete the identity (Stephenson, Coelho and Jolliffe 2008): BS = REL - RES + UNC + WBV - 2 WBC,
    WBV the within-bin variance of the forecasts and WBC their within-bin covariance with the outcomes. With 20 or
    fewer distinct forecast values each value is its own bin and the two extra terms are zero."""
    p, o = np.asarray(p, float), np.asarray(o, float)
    ok = np.isfinite(p) & np.isfinite(o)
    p, o = p[ok], o[ok]
    N = len(p)
    bs = float(np.mean((p - o) ** 2))
    vals = np.unique(p)
    if bins is None and len(vals) <= 20:
        lab = np.searchsorted(vals, p)
    else:
        nb = bins or 10
        lab = np.minimum((p * nb).astype(int), nb - 1)
    ob = o.mean()
    rel = res = wbv = wbc = 0.0
    table = []
    for k in np.unique(lab):
        m = lab == k
        nk = int(m.sum())
        pk, ok_ = p[m].mean(), o[m].mean()
        rel += nk * (pk - ok_) ** 2
        res += nk * (ok_ - ob) ** 2
        wbv += float(((p[m] - pk) ** 2).sum())
        wbc += float(((p[m] - pk) * (o[m] - ok_)).sum())
        table.append({"n": nk, "forecast": float(pk), "observed": float(ok_)})
    rel, res, wbv, wbc = rel / N, res / N, wbv / N, wbc / N
    unc = float(ob * (1 - ob))
    return jsonable({"bs": bs, "reliability": float(rel), "resolution": float(res), "uncertainty": unc, "wbv": float(wbv), "wbc": float(wbc),
            "identity_gap": float(bs - (rel - res + unc + wbv - 2 * wbc)), "bss_vs_base_rate": float(1 - bs / unc) if unc > 0 else None,
            "n": N, "table": table})


def skill(score_model, score_ref, orientation: str = "loss", lags: int = 12) -> dict:
    """Skill against a reference forecast. For a loss (CRPS, Brier): 1 - mean(model)/mean(ref); for a gain (log
    score): the mean difference. The DM t is positive when the model is better."""
    a, b = np.asarray(score_model, float), np.asarray(score_ref, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if orientation == "loss":
        return {"skill": float(1 - a.mean() / b.mean()), "model": float(a.mean()), "ref": float(b.mean()), **{k: v for k, v in dm_test(b - a, lags).items() if k in ("t", "p", "n")}}
    return {"gain": float(a.mean() - b.mean()), "model": float(a.mean()), "ref": float(b.mean()), **{k: v for k, v in dm_test(a - b, lags).items() if k in ("t", "p", "n")}}


def climatology_scores(r, start: int, lag: int = LAG, min_n: int = 60) -> dict:
    """The climatological forecast for month t: the empirical distribution of every outcome known by t - lag. Its CRPS
    is exact for the empirical distribution (mean |X - y| - mean |X - X'|/2); its log score uses a Gaussian kernel with
    Silverman's bandwidth (an empirical distribution has no density)."""
    r = np.asarray(r, float)
    T = len(r)
    crps, ls = np.full(T, np.nan), np.full(T, np.nan)
    for t in range(start, T):
        X = r[:max(t - lag + 1, 0)]
        X = np.sort(X[np.isfinite(X)])
        n = len(X)
        if n < min_n or not np.isfinite(r[t]):
            continue
        i = np.arange(1, n + 1)
        crps[t] = np.mean(np.abs(X - r[t])) - float(((2 * i - n - 1) * X).sum()) / n ** 2
        h = 1.06 * X.std() * n ** -0.2
        ls[t] = math.log(max(float(np.mean(_phi((r[t] - X) / h))) / h, 1e-300))
    return {"crps": crps, "ls": ls}


def persistence_scores(r, start: int, lag: int = LAG, min_n: int = 60) -> dict:
    """Persistence: the last known month (t - lag) as the center, with the spread of every known month."""
    r = np.asarray(r, float)
    T = len(r)
    mu, sd = np.full(T, np.nan), np.full(T, np.nan)
    for t in range(start, T):
        X = r[:max(t - lag + 1, 0)]
        if len(X) >= min_n:
            mu[t], sd[t] = r[t - lag], np.nanstd(X)
    return {"crps": crps_normal(mu, sd, r), "ls": -0.5 * ((r - mu) / sd) ** 2 - np.log(sd * SQ2PI)}


def spread_skill(sd, err, bins: int = 5) -> dict:
    """Does a wider forecast mean a bigger miss? The correlation of the predictive sd with |error| (Pearson and
    Spearman), and the binned table: for a calibrated normal forecast the RMSE in each bin equals its mean sd."""
    sd, err = np.asarray(sd, float), np.asarray(err, float)
    ok = np.isfinite(sd) & np.isfinite(err)
    sd, err = sd[ok], err[ok]
    q = np.quantile(sd, np.linspace(0, 1, bins + 1))
    lab = np.clip(np.searchsorted(q, sd, side="right") - 1, 0, bins - 1)
    rows = [{"sd": float(sd[lab == k].mean()), "rmse": float(np.sqrt(np.mean(err[lab == k] ** 2))), "n": int((lab == k).sum())} for k in range(bins) if (lab == k).any()]
    pr = stats.pearsonr(sd, np.abs(err))
    sp = stats.spearmanr(sd, np.abs(err))
    return {"corr": float(pr[0]), "corr_p": float(pr[1]), "spearman": float(sp[0]), "spearman_p": float(sp[1]), "bins": rows,
            "ratio_rmse_to_sd": float(np.sqrt(np.mean(err ** 2)) / np.sqrt(np.mean(sd ** 2)))}


# ================================================================ EMOS / nonhomogeneous Gaussian regression
IDENTITY = (0.0, 1.0, 0.0, 1.0)


def _emos_unpack(th, m, v):
    a, b, c, d = th
    var = np.maximum(c + d * v, 1e-14)
    return a + b * m, var


def emos_fit(mu, sd, y, w=None) -> dict:
    """Minimum-CRPS fit of N(a + b mu, c + d sd^2) with c, d >= 0 (Gneiting et al. 2005). With w (mixture weights;
    mu and sd then (n, K) components), the forecast is the mixture recalibrated by mixture_recalibrate with location
    a + b m and spread s^2 = (c + d v)/v, m and v the mixture's mean and variance, and the CRPS minimized is the
    mixture's own. Fit in standardized units for conditioning; L-BFGS-B from two starts (the identity and climatology)."""
    y = np.asarray(y, float)
    s0 = float(np.std(y)) or 1.0
    ys = y / s0
    if w is None:
        m, v = np.asarray(mu, float) / s0, (np.asarray(sd, float) / s0) ** 2

        def f(th):
            loc, var = _emos_unpack(th, m, v)
            return float(np.mean(crps_normal(loc, np.sqrt(var), ys)))
    else:
        W, MU, SD = _mix(w, np.asarray(mu, float) / s0, np.asarray(sd, float) / s0)
        m, sdm = mixture_moments(W, MU, SD)
        v = np.maximum(sdm ** 2, 1e-14)
        pair = _crps_mix_pair(W, MU, SD)                    # the spread term scales exactly with s, so compute it once
        dev = MU - m[:, None]

        def f(th):
            loc, var = _emos_unpack(th, m, v)
            s = np.sqrt(var / v)
            t1 = (W * _A(ys[:, None] - loc[:, None] - s[:, None] * dev, s[:, None] * SD)).sum(-1)
            return float(np.mean(t1 - 0.5 * s * pair))
    starts = [np.array(IDENTITY), np.array([ys.mean(), 0.0, ys.var(), 0.0])]
    best = None
    for x0 in starts:
        r = optimize.minimize(f, x0, method="L-BFGS-B", bounds=[(None, None), (None, None), (0.0, None), (0.0, None)])
        if best is None or r.fun < best.fun:
            best = r
    a, b, c, d = best.x
    return {"a": float(a * s0), "b": float(b), "c": float(c * s0 ** 2), "d": float(d), "crps": float(best.fun * s0),
            "crps_identity": float(f(np.array(IDENTITY)) * s0), "n": int(len(y)), "converged": bool(best.success), "mode": "normal" if w is None else "mixture"}


def emos_apply(fit: dict, mu, sd, w=None):
    """The recalibrated forecast: (loc, sd) of the normal, or (w, mu, sd) of the recalibrated mixture."""
    if w is None:
        loc = fit["a"] + fit["b"] * np.asarray(mu, float)
        return loc, np.sqrt(np.maximum(fit["c"] + fit["d"] * np.asarray(sd, float) ** 2, 1e-14))
    m, sdm = mixture_moments(w, mu, sd)
    v = np.maximum(sdm ** 2, 1e-14)
    s = np.sqrt(np.maximum(fit["c"] + fit["d"] * v, 1e-14) / v)
    return mixture_recalibrate(w, mu, sd, fit["a"], fit["b"], s)


def emos_walk(mu, sd, y, start: int, refit: int = 12, window: int | None = None, w=None, lag: int = LAG, min_train: int = 60) -> dict:
    """EMOS walked forward: every `refit` months from `start` the parameters are fit on months whose outcome was known
    by t - lag (a rolling `window` of them, or all), and applied to the next `refit` months. Before min_train such
    months exist the forecast passes through unchanged. Returns arrays for the engine and a JSON-safe list of fits."""
    y = np.asarray(y, float)
    T = len(y)
    mu, sd = np.asarray(mu, float), np.asarray(sd, float)
    valid = np.isfinite(y) & (np.isfinite(mu).all(-1) if mu.ndim > 1 else np.isfinite(mu)) & (np.isfinite(sd).all(-1) if sd.ndim > 1 else np.isfinite(sd))
    if w is not None:
        w = np.asarray(w, float)
        valid &= np.isfinite(w).all(-1)
    P = np.tile(np.array(IDENTITY), (T, 1))
    fits = []
    for t0 in range(start, T, refit):
        hi = max(t0 - lag + 1, 0)
        lo = 0 if window is None else max(0, hi - window)
        idx = np.flatnonzero(valid[lo:hi]) + lo
        if len(idx) >= min_train:
            ft = emos_fit(mu[idx], sd[idx], y[idx], None if w is None else w[idx])
            P[t0:t0 + refit] = (ft["a"], ft["b"], ft["c"], ft["d"])
            fits.append({"at": t0, **ft})
    fit_t = lambda t: {"a": P[t, 0], "b": P[t, 1], "c": P[t, 2], "d": P[t, 3]}
    if w is None:
        loc = P[:, 0] + P[:, 1] * mu
        s = np.sqrt(np.maximum(P[:, 2] + P[:, 3] * sd ** 2, 1e-14))
        return {"mu": loc, "sd": s, "params": P, "fits": jsonable(fits), "fit_at": fit_t}
    m, sdm = mixture_moments(np.nan_to_num(w), np.nan_to_num(mu), np.nan_to_num(sd, nan=1.0))
    v = np.maximum(sdm ** 2, 1e-14)
    s = np.sqrt(np.maximum(P[:, 2] + P[:, 3] * v, 1e-14) / v)
    W2, MU2, SD2 = mixture_recalibrate(np.nan_to_num(w, nan=1.0), np.nan_to_num(mu), np.nan_to_num(sd, nan=1.0), P[:, 0], P[:, 1], s)
    bad = ~np.isfinite(w).all(-1)
    for A_ in (W2, MU2, SD2):
        A_[bad] = np.nan
    return {"w": W2, "mu": MU2, "sd": SD2, "params": P, "scale": s, "fits": jsonable(fits), "fit_at": fit_t}


# ================================================================ Bayesian model averaging
def bma_weights(logdens, forget: float = 1.0, iters: int = 1000, tol: float = 1e-9, w0=None) -> dict:
    """BMA weights by EM (Raftery et al. 2005): with member predictive log densities l_tk at the outcomes, maximize
    sum_t a_t log sum_k w_k exp(l_tk), a_t = forget^age (1 for a plain training window). E step: responsibilities
    z_tk proportional to w_k exp(l_tk); M step: w_k = weighted mean of z_tk. The members' own spreads are kept, so
    this is the weights-only form of BMA for members that are already full predictive distributions."""
    L = np.asarray(logdens, float)
    n, K = L.shape
    a = forget ** np.arange(n - 1, -1, -1, dtype=float)
    w = np.full(K, 1 / K) if w0 is None else np.asarray(w0, float) / np.sum(w0)
    ll_old = -np.inf
    it = 0
    for it in range(1, iters + 1):
        with np.errstate(divide="ignore"):
            lz = np.log(w)[None, :] + L
        lse = logsumexp(lz, axis=1)
        ll = float((a * lse).sum())
        z = np.exp(lz - lse[:, None])
        w = (a[:, None] * z).sum(0) / a.sum()
        if ll - ll_old < tol * max(1.0, abs(ll)):
            break
        ll_old = ll
    return {"w": w.tolist(), "loglik": ll, "iterations": it, "n": int(n)}


def bma_walk(logdens, start: int, lag: int = LAG, window: int | None = None, forget: float = 1.0, refit: int = 1, min_train: int = 60) -> np.ndarray:
    """BMA weights for each month t >= start from member log scores known by t - lag; equal weights before min_train
    scored months exist. Warm-started EM, so each refit takes a few iterations."""
    L = np.asarray(logdens, float)
    T, K = L.shape
    W = np.full((T, K), np.nan)
    ok = np.isfinite(L).all(1)
    w = np.full(K, 1 / K)
    cur = w.copy()
    for t in range(start, T):
        if (t - start) % refit == 0:
            hi = max(t - lag + 1, 0)
            lo = 0 if window is None else max(0, hi - window)
            idx = np.flatnonzero(ok[lo:hi]) + lo
            if len(idx) >= min_train:
                cur = np.array(bma_weights(L[idx], forget=forget, w0=np.maximum(w, 1e-6))["w"])
                w = cur
            else:
                cur = np.full(K, 1 / K)
        W[t] = cur
    return W


# ================================================================ extreme values: peaks over threshold
def _gpd_nll(xi, beta, y):
    if beta <= 0:
        return np.inf
    z = 1 + xi * y / beta
    if np.any(z <= 0):
        return np.inf
    n = len(y)
    if abs(xi) < 1e-8:
        return n * math.log(beta) + float(y.sum()) / beta
    return n * math.log(beta) + (1 + 1 / xi) * float(np.log(z).sum())


def gpd_pwm(excesses) -> dict:
    """Probability-weighted moments (Hosking and Wallis 1987): with a0 the mean and a1 = mean((1 - p_i) y_(i)),
    p_i = (i - 0.35)/n, xi = 2 - a0/(a0 - 2 a1) and beta = 2 a0 a1/(a0 - 2 a1). Valid for xi < 1/2."""
    y = np.sort(np.asarray(excesses, float))
    n = len(y)
    p = (np.arange(1, n + 1) - 0.35) / n
    a0, a1 = y.mean(), float(np.mean((1 - p) * y))
    den = a0 - 2 * a1
    return {"xi": float(2 - a0 / den), "beta": float(2 * a0 * a1 / den)}


def _hessian(f, x, h):
    k = len(x)
    H = np.zeros((k, k))
    for i in range(k):
        for j in range(i, k):
            ei, ej = np.eye(k)[i] * h[i], np.eye(k)[j] * h[j]
            H[i, j] = H[j, i] = (f(x + ei + ej) - f(x + ei - ej) - f(x - ei + ej) + f(x - ei - ej)) / (4 * h[i] * h[j])
    return H


def gpd_fit(excesses, method: str = "mle") -> dict:
    """Fit the generalized Pareto distribution to excesses y > 0: G(y) = 1 - (1 + xi y/beta)^(-1/xi).
    Maximum likelihood from the PWM estimate (Nelder-Mead on xi and log beta), with standard errors from the observed
    information (the inverse numerical Hessian of the negative log-likelihood at the optimum). PWM is used when asked,
    when the optimizer fails, or when the MLE gives xi <= -1/2 (where the MLE is no longer regular). For PWM the
    standard errors are those of the expected information evaluated at the PWM estimate, an approximation."""
    y = np.asarray(excesses, float)
    y = y[np.isfinite(y) & (y > 0)]
    n = len(y)
    if n < 5:
        return {"xi": None, "beta": None, "se_xi": None, "se_beta": None, "n": n, "method": "none", "loglik": None}
    pw = gpd_pwm(y)
    xi0 = float(np.clip(pw["xi"], -0.4, 0.9))
    b0 = max(pw["beta"], 1e-6 * float(y.mean())) if np.isfinite(pw["beta"]) and pw["beta"] > 0 else float(y.mean())
    if method == "mle":
        f = lambda th: _gpd_nll(th[0], math.exp(th[1]), y)
        best = None
        for x0 in ([xi0, math.log(b0)], [0.1, math.log(float(y.mean()))]):
            r = optimize.minimize(f, np.array(x0), method="Nelder-Mead", options={"xatol": 1e-9, "fatol": 1e-11, "maxiter": 4000})
            if np.isfinite(r.fun) and (best is None or r.fun < best.fun):
                best = r
        if best is not None and best.x[0] > -0.5:
            xi, beta = float(best.x[0]), float(math.exp(best.x[1]))
            g = lambda th: _gpd_nll(th[0], th[1], y)
            H = _hessian(g, np.array([xi, beta]), np.array([1e-4, 1e-4 * beta]))
            try:
                C = np.linalg.inv(H)
                se = np.sqrt(np.diag(C)) if np.all(np.diag(C) > 0) else np.array([np.nan, np.nan])
            except np.linalg.LinAlgError:
                se = np.array([np.nan, np.nan])
            return jsonable({"xi": xi, "beta": beta, "se_xi": float(se[0]), "se_beta": float(se[1]), "n": n, "method": "mle", "loglik": -float(best.fun),
                             "se_xi_expected": float((1 + xi) / math.sqrt(n)), "pwm": pw})
    xi, beta = pw["xi"], pw["beta"]
    se_xi = (1 + xi) / math.sqrt(n) if xi > -1 else float("nan")
    se_b = beta * math.sqrt(2 * (1 + xi) / n) if xi > -1 else float("nan")
    ll = -_gpd_nll(xi, beta, y)
    return jsonable({"xi": xi, "beta": beta, "se_xi": se_xi, "se_beta": se_b, "n": n, "method": "pwm", "loglik": ll if np.isfinite(ll) else None, "pwm": pw})


def gpd_var_es(p, u, xi, beta, n, n_u):
    """POT value at risk and expected shortfall at tail probability p (McNeil, Frey and Embrechts 2005, 7.2.3):
    VaR_p = u + beta/xi [((n/n_u) p)^(-xi) - 1] (u - beta log((n/n_u) p) when xi = 0) and
    ES_p = VaR_p/(1 - xi) + (beta - xi u)/(1 - xi), finite for xi < 1. Valid for p below the exceedance rate n_u/n.
    Vectorized: returns arrays for array inputs, floats for scalars."""
    p, u, xi, beta = (np.asarray(v, float) for v in (p, u, xi, beta))
    ratio = np.asarray(n, float) / np.asarray(n_u, float) * p
    small = np.abs(xi) < 1e-8
    xs = np.where(small, 1.0, xi)
    var = np.where(small, u - beta * np.log(ratio), u + beta / xs * (ratio ** (-xs) - 1))
    es = np.where(xi < 1, var / (1 - xi) + (beta - xi * u) / (1 - xi), np.inf)
    if var.ndim == 0:
        return float(var), float(es)
    return var, es


def pot(x_losses, u_quantile: float = 0.9, method: str = "mle", ps=(0.05, 0.01)) -> dict:
    """Peaks over threshold on losses (positive = loss): the threshold at the u_quantile of the sample, the GPD fit to
    the excesses, and VaR and ES at each tail probability in ps."""
    x = np.asarray(x_losses, float)
    x = x[np.isfinite(x)]
    n = len(x)
    u = float(np.quantile(x, u_quantile))
    exc = x[x > u] - u
    f = gpd_fit(exc, method)
    out = {"u": u, "u_quantile": u_quantile, "n": n, "n_u": int(len(exc)), **{k: f[k] for k in ("xi", "beta", "se_xi", "se_beta", "method")}}
    if f["xi"] is not None:
        for p in ps:
            v, e = gpd_var_es(p, u, f["xi"], f["beta"], n, len(exc))
            out[f"var_{p}"], out[f"es_{p}"] = v, e
    return jsonable(out)


def return_level(m_months, fit: dict):
    """The loss exceeded on average once every m months: x_m = u + beta/xi [(m n_u/n)^xi - 1] (fit from pot())."""
    m = np.asarray(m_months, float)
    v, _ = gpd_var_es(1.0 / m, fit["u"], fit["xi"], fit["beta"], fit["n"], fit["n_u"])
    return v


def return_period(loss, fit: dict):
    """The mean number of months between losses at least this large: 1/[(n_u/n)(1 + xi (x - u)/beta)^(-1/xi)]."""
    x = np.asarray(loss, float)
    z = np.maximum(1 + fit["xi"] * (x - fit["u"]) / fit["beta"], 1e-300)
    sf = fit["n_u"] / fit["n"] * (np.exp(-(x - fit["u"]) / fit["beta"]) if abs(fit["xi"]) < 1e-8 else z ** (-1 / fit["xi"]))
    out = np.where(x >= fit["u"], 1 / sf, np.nan)
    return float(out) if out.ndim == 0 else out


def mean_excess(x, thresholds) -> list[dict]:
    """The mean-excess function e(u) = E[X - u | X > u] with its standard error. Above a threshold where the GPD fits,
    e(u) is linear in u with slope xi/(1 - xi)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    out = []
    for u in np.atleast_1d(thresholds):
        e = x[x > u] - u
        out.append({"u": float(u), "n": int(len(e)), "e": float(e.mean()) if len(e) else None, "se": float(e.std(ddof=1) / math.sqrt(len(e))) if len(e) > 1 else None})
    return jsonable(out)


def threshold_stability(x, quantiles=None, min_exc: int = 20) -> dict:
    """The standard threshold diagnostic: refit the GPD over a range of thresholds. Above a good threshold the shape xi
    and the modified scale beta* = beta - xi u are constant. The suggested threshold is the lowest at which every higher
    threshold's xi lies inside this one's 95% interval; the mean-excess slope is reported alongside."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    qs = np.round(np.arange(0.80, 0.985, 0.01), 3) if quantiles is None else np.asarray(quantiles, float)
    rows = []
    for q in qs:
        u = float(np.quantile(x, q))
        exc = x[x > u] - u
        if len(exc) < min_exc:
            continue
        f = gpd_fit(exc)
        if f["xi"] is None:
            continue
        rows.append({"q": float(q), "u": u, "n_u": int(len(exc)), "xi": f["xi"], "se_xi": f["se_xi"], "beta": f["beta"], "beta_star": f["beta"] - f["xi"] * u})
    stable = None
    for i, rw in enumerate(rows):
        se = rw["se_xi"] if rw["se_xi"] is not None and np.isfinite(rw["se_xi"]) else None
        if se is None:
            continue
        if all(abs(r2["xi"] - rw["xi"]) <= 1.96 * se for r2 in rows[i:]):
            stable = rw["q"]
            break
    me = mean_excess(x, [r["u"] for r in rows])
    slope = None
    if len(rows) >= 3:
        uu = np.array([m["u"] for m in me])
        ee = np.array([m["e"] for m in me])
        slope = float(np.polyfit(uu, ee, 1)[0])
    return jsonable({"rows": rows, "stable_from_quantile": stable, "mean_excess": me, "mean_excess_slope": slope,
                     "implied_xi_from_slope": slope / (1 + slope) if slope is not None and slope > -1 else None})


# ================================================================ tail backtest
def _hist_var_es(Ls: np.ndarray, p):
    """Historical VaR (the 1 - p sample quantile of losses) and ES (the mean of losses at or beyond it); Ls sorted."""
    n = len(Ls)
    p = np.atleast_1d(np.asarray(p, float))
    v = np.quantile(Ls, 1 - p)
    cs = np.concatenate([[0.0], np.cumsum(Ls[::-1])])
    k = np.maximum(n - np.searchsorted(Ls, v, side="left"), 1)
    return v, cs[k] / k


def acerbi_szekely_z2(x, var, es, p: float, tail_q: np.ndarray, sims: int = 2000, seed: int = 19) -> dict:
    """Acerbi and Szekely (2014) test 2: Z2 = sum_t x_t I_t / (T p ES_t) + 1, x the return (negative a loss), I_t the
    VaR exceedance and ES_t positive. E[Z2] = 0 under a correct model; a negative Z2 means the model understates the
    tail. The p-value (one-sided, Z2 too negative) is by simulation under the model's own forecasts: an exceedance with
    probability p and, given one, a loss drawn from the forecast's tail, read off tail_q (T, G), the loss quantiles at
    tail probabilities p (j - 1/2)/G."""
    x, var, es = (np.asarray(a, float) for a in (x, var, es))
    T = len(x)
    I = x < -var
    z2 = float((x * I / (T * p * es)).sum() + 1)
    rng = np.random.default_rng(seed)
    G = tail_q.shape[1]
    hit = rng.random((sims, T)) < p
    j = rng.integers(0, G, size=(sims, T))
    loss = tail_q[np.arange(T)[None, :], j]
    z_null = -(loss * hit / (T * p * es[None, :])).sum(1) + 1
    return {"z2": z2, "p": float((np.sum(z_null <= z2) + 1) / (sims + 1)), "null_mean": float(z_null.mean()), "null_q05": float(np.quantile(z_null, 0.05)),
            "realized_tail_loss_mean": float(-x[I].mean()) if I.any() else None, "forecast_es_mean_in_hits": float(es[I].mean()) if I.any() else None}


def fz0_loss(x, var, es, p: float) -> np.ndarray:
    """The FZ0 loss of Patton, Ziegel and Chen (2019), a strictly consistent scoring function for VaR and ES jointly
    (Fissler and Ziegel 2016), so two tail forecasts can be compared month by month with a Diebold-Mariano test. In
    return terms v = -VaR and e = -ES (e <= v < 0): L = -1{x <= v}(v - x)/(p e) + v/e + log(-e) - 1. Lower is better."""
    x, v, e = np.asarray(x, float), -np.asarray(var, float), -np.asarray(es, float)
    e = np.minimum(e, -1e-12)
    return -(x <= v).astype(float) * (v - x) / (p * e) + v / e + np.log(-e) - 1


def _ewma_sd(r: np.ndarray, lam: float, m: np.ndarray, burn: int = 12) -> np.ndarray:
    """sd_t from returns through t - 1: sd_t^2 = lam sd_(t-1)^2 + (1 - lam)(r_(t-1) - m_(t-1))^2, seeded with the first
    `burn` months' variance."""
    T = len(r)
    v = np.full(T, np.nan)
    v[burn] = float(np.var(r[:burn]))
    for t in range(burn + 1, T):
        v[t] = lam * v[t - 1] + (1 - lam) * (r[t - 1] - m[t - 1]) ** 2
    return np.sqrt(v)


def tail_backtest(r, start: int, ps=(0.05, 0.01), u_quantile: float = 0.9, lag: int = LAG, refit: int = 1, mixtures: dict | None = None,
                  ewma: float = 0.97, sims: int = 2000, G: int = 100, seed: int = 19, methods=("normal", "historical", "pot", "filtered_pot")) -> dict:
    """Walk-forward VaR and ES of monthly losses (-r) from `start`, each month from data known by t - lag in an expanding
    window from the first month, by:
        normal        the window's mean and sd
        historical    the window's empirical quantile and tail mean
        pot           GPD over the window's u_quantile of losses (refit every `refit` months)
        filtered_pot  McNeil and Frey (2000) in EWMA form: POT on losses standardized by an EWMA volatility (lam 0.97,
                      the RiskMetrics monthly decay), rescaled by the volatility known at t - lag
        (mixtures)    any predictive mixtures given as {name: (W, MU, SD)} padded (T, K) arrays, e.g. the engine's
    Each is judged by the Kupiec test (exceedance frequency), the Christoffersen test (independence of exceedances) and
    Acerbi-Szekely Z2 (the size of losses beyond VaR against ES). 'calibrated' means Kupiec and Z2 both pass at 5%;
    'independent' that Christoffersen does too. The ES at 5% is what the engine's 12% budget is measured against."""
    r = np.asarray(r, float)
    T = len(r)
    L = -r
    ps = tuple(ps)
    gq = (np.arange(G) + 0.5) / G
    out = {"start": start, "months": T - start, "lag": lag, "u_quantile": u_quantile, "ewma_lambda": ewma, "methods": {}}
    fc = {}
    tq = {}
    m_exp = np.cumsum(np.nan_to_num(r)) / np.cumsum(np.isfinite(r)).clip(1)
    for meth in methods:
        V = {p: np.full(T, np.nan) for p in ps}
        E = {p: np.full(T, np.nan) for p in ps}
        Q = {p: np.full((T, G), np.nan) for p in ps}
        params = []
        if meth == "filtered_pot":
            sdf = _ewma_sd(r, ewma, m_exp)
            z = (L + m_exp_shift(m_exp)) / sdf
        cache = None
        for t in range(start, T):
            hi = max(t - lag + 1, 0)
            Lw = L[:hi]
            if meth == "normal":
                mu_, sd_ = float(np.mean(-Lw)), float(np.std(-Lw))
                for p in ps:
                    zz = stats.norm.ppf(p)
                    V[p][t] = -(mu_ + sd_ * zz)
                    E[p][t] = -mu_ + sd_ * _phi(zz) / p
                    Q[p][t] = -(mu_ + sd_ * stats.norm.ppf(p * gq))
            elif meth == "historical":
                Ls = np.sort(Lw)
                for p in ps:
                    v, e = _hist_var_es(Ls, p)
                    V[p][t], E[p][t] = v[0], e[0]
                    Q[p][t] = np.quantile(Ls, 1 - p * gq)
            elif meth in ("pot", "filtered_pot"):
                if meth == "pot":
                    xs, scale, shift = Lw, 1.0, 0.0
                else:
                    zw = z[:hi]
                    xs = zw[np.isfinite(zw)]
                    scale, shift = float(sdf[hi]), float(-m_exp[t - lag])
                if cache is None or (t - start) % refit == 0:
                    n = len(xs)
                    u = float(np.quantile(xs, u_quantile))
                    exc = xs[xs > u] - u
                    f = gpd_fit(exc)
                    cache = (u, f["xi"], f["beta"], n, len(exc))
                    if (t - start) % 120 == 0:
                        params.append({"at": t, "u": u, "xi": f["xi"], "se_xi": f["se_xi"], "beta": f["beta"], "n_u": len(exc), "method": f["method"]})
                u, xi, beta, n, nu = cache
                for p in ps:
                    v, e = gpd_var_es(p, u, xi, beta, n, nu)
                    V[p][t], E[p][t] = shift + scale * v, shift + scale * e
                    qv, _ = gpd_var_es(p * gq, u, xi, beta, n, nu)
                    Q[p][t] = shift + scale * qv
        fc[meth] = (V, E, params)
        tq[meth] = Q
    for name, (W, MU, SD) in (mixtures or {}).items():
        V, E, Q = {}, {}, {}
        ok = np.isfinite(W).all(1) & np.isfinite(MU).all(1) & np.isfinite(SD).all(1) & (np.arange(T) >= start)
        for p in ps:
            V[p], E[p], Q[p] = np.full(T, np.nan), np.full(T, np.nan), np.full((T, G), np.nan)
            v, e = mixture_var_es(W[ok], MU[ok], SD[ok], p)
            V[p][ok], E[p][ok] = v, e
            Q[p][ok] = -mixture_quantile(W[ok][:, None, :], MU[ok][:, None, :], SD[ok][:, None, :], p * gq[None, :], iters=50)
        fc[name] = (V, E, [])
        tq[name] = Q
    fzs = {}
    for name, (V, E, params) in fc.items():
        res = {}
        fzs[name] = {}
        for p in ps:
            ok = np.isfinite(V[p]) & np.isfinite(r) & (np.arange(T) >= start)
            fzs[name][p] = np.full(T, np.nan)
            fzs[name][p][ok] = fz0_loss(r[ok], V[p][ok], E[p][ok], p)
            hits = r[ok] < -V[p][ok]
            k = kupiec(hits, p)
            c = christoffersen(hits, p)
            z2 = acerbi_szekely_z2(r[ok], V[p][ok], E[p][ok], p, tq[name][p][ok], sims=sims, seed=seed)
            res[str(p)] = {"kupiec": k, "christoffersen": c, "z2": z2, "var_mean": float(V[p][ok].mean()), "es_mean": float(E[p][ok].mean()),
                           "fz0": float(np.mean(fz0_loss(r[ok], V[p][ok], E[p][ok], p))),
                           "es_last": float(E[p][ok][-1]), "var_last": float(V[p][ok][-1]),
                           "calibrated": bool(k["p"] > 0.05 and z2["p"] > 0.05), "independent": bool(c["p_ind"] > 0.05)}
            if p == 0.05:
                res[str(p)]["share_es_above_budget"] = float(np.mean(E[p][ok] > ES_LIMIT))
                res[str(p)]["max_exposure_now"] = float(ES_LIMIT / max(E[p][ok][-1], 1e-9))
        res["params"] = params
        out["methods"][name] = res
    ref = next(iter(mixtures)) if mixtures else (methods[0] if methods else None)
    if ref is not None:
        out["fz0_ref"] = ref
        out["fz0_vs_ref"] = {n: {str(p): {k_: v_ for k_, v_ in dm_test(fzs[ref][p] - fzs[n][p]).items() if k_ in ("mean", "t", "n")} for p in ps}
                             for n in fzs if n != ref}             # t > 0: this estimator's joint VaR-ES score beats the reference's
    out["calibrated"] = {p: [n for n in out["methods"] if out["methods"][n][str(p)]["calibrated"]] for p in map(str, ps)}
    out["calibrated_and_independent"] = {p: [n for n in out["methods"] if out["methods"][n][str(p)]["calibrated"] and out["methods"][n][str(p)]["independent"]] for p in map(str, ps)}
    return jsonable(out)


def m_exp_shift(m_exp: np.ndarray) -> np.ndarray:
    """Losses standardized around the mean known one month earlier (the EWMA's own information set)."""
    return np.concatenate([[m_exp[0]], m_exp[:-1]])


# ================================================================ ruin
def _sb_paths(n: int, h: int, B: int, block: float, rng: np.random.Generator) -> np.ndarray:
    """Stationary-bootstrap index paths of length h from a sample of n (Politis and Romano 1994), wrapping around."""
    p = 1.0 / block
    idx = np.empty((B, h), dtype=int)
    idx[:, 0] = rng.integers(0, n, size=B)
    newb = rng.random((B, h)) < p
    jumps = rng.integers(0, n, size=(B, h))
    for t in range(1, h):
        idx[:, t] = np.where(newb[:, t], jumps[:, t], (idx[:, t - 1] + 1) % n)
    return idx


def ruin_probability(returns, exposure: float = 1.0, limit_dd: float = 0.5, horizon_months: int = 120, B: int = 4000, block: float = 12,
                     seed: int = 19, borrow: float = 0.0, from_peak: bool = True) -> dict:
    """The probability that wealth invested at `exposure` (borrowing above 1x at `borrow` a month) falls `limit_dd`
    below its running peak (or below its start, from_peak=False) within horizon_months, by stationary bootstrap of the
    monthly returns with mean block `block` (block=1 is the iid bootstrap). With a Wilson 95% interval."""
    r = np.asarray(returns, float)
    r = r[np.isfinite(r)]
    rng = np.random.default_rng(seed)
    idx = _sb_paths(len(r), horizon_months, B, block, rng)
    g = np.log(np.maximum(1 + exposure * r[idx] - max(exposure - 1, 0) * borrow, 1e-12))
    Lc = np.cumsum(g, axis=1)
    ref = np.maximum.accumulate(np.maximum(Lc, 0.0), axis=1) if from_peak else np.zeros_like(Lc)
    hit = (Lc - ref) <= math.log(1 - limit_dd)
    ruined = hit.any(1)
    first = np.where(ruined, hit.argmax(1) + 1, -1)
    pr = float(ruined.mean())
    z = 1.96
    den = 1 + z * z / B
    ctr = (pr + z * z / (2 * B)) / den
    half = z * math.sqrt(pr * (1 - pr) / B + z * z / (4 * B * B)) / den
    return jsonable({"p": pr, "lo": ctr - half, "hi": ctr + half, "B": B, "exposure": exposure, "limit_dd": limit_dd, "horizon_months": horizon_months,
                     "block": block, "from_peak": from_peak, "median_months_to_ruin": float(np.median(first[ruined])) if ruined.any() else None})


def brownian_ruin(mu: float, sigma: float, b: float, T: float | None = None, dt: float | None = None) -> float:
    """P(min_{s <= T} X_s <= -b) for X_s = mu s + sigma W_s: Phi((-b - mu T)/(sigma sqrt T)) + exp(-2 mu b/sigma^2)
    Phi((-b + mu T)/(sigma sqrt T)); exp(-2 mu b/sigma^2) for T = None and mu > 0. With dt, discrete monitoring every dt
    is approximated by moving the barrier out by 0.5826 sigma sqrt(dt) (Broadie, Glasserman and Kou 1997)."""
    if dt:
        b = b + BGK * sigma * math.sqrt(dt)
    if T is None:
        return 1.0 if mu <= 0 else math.exp(-2 * mu * b / sigma ** 2)
    s = sigma * math.sqrt(T)
    return float(ndtr((-b - mu * T) / s) + math.exp(-2 * mu * b / sigma ** 2) * ndtr((-b + mu * T) / s))


def cramer_lundberg(mu: float, sigma: float, u: float | None = None) -> dict:
    """The Cramer-Lundberg model for an investor. An insurer's surplus is U_t = u + c t - S_t: initial capital u, premium
    income c, claims S_t; the adjustment coefficient R solves E[exp(-R (c - claim per unit time))] = 1 and the Lundberg
    bound is psi(u) <= exp(-R u). The mapping: the surplus is log wealth, u is the distance in log terms to the ruin
    level (-log(1 - drawdown limit)), the premium income is the expected log excess return per month mu (the drift
    the investor is paid for bearing risk), and the claims are the losses, here the Brownian noise sigma W_t. For
    a Brownian surplus the Lundberg equation -R mu + R^2 sigma^2/2 = 0 gives R = 2 mu/sigma^2, and because a Brownian
    path cannot jump past the barrier the bound holds with equality: psi(u) = exp(-2 mu u/sigma^2), infinite horizon,
    measured from the start (not from a running peak). With mu <= 0 ruin is certain."""
    R = 2 * mu / sigma ** 2 if mu > 0 else 0.0
    out = {"mu": mu, "sigma": sigma, "R": R, "safety_loading": mu / sigma if sigma > 0 else None}
    if u is not None:
        out["u"] = u
        out["lundberg_bound"] = math.exp(-R * u) if R > 0 else 1.0
        out["psi_brownian"] = out["lundberg_bound"]
    return jsonable(out)


def adjustment_coefficient(x) -> float | None:
    """The empirical adjustment coefficient: R > 0 with mean(exp(-R x)) = 1 for per-period surplus increments x (log
    growth). Exists when the mean is positive and some increments are negative; None otherwise."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if x.mean() <= 0 or not (x < 0).any():
        return None
    f = lambda R: float(np.mean(np.exp(-R * x))) - 1
    hi = 1.0
    while f(hi) < 0 and hi < 1e6:
        hi *= 2
    return float(optimize.brentq(f, 1e-10, hi)) if f(hi) > 0 else None


# ================================================================ credibility
def buhlmann_straub(values, weights=None, dof: float | None = None) -> dict:
    """Buhlmann-Straub credibility. Group i has observations X_ij with exposures m_ij; X_i = weighted mean, m_i = sum of
    exposures, X = the exposure-weighted grand mean, r groups. The nonparametric estimators:
        EPV  s^2 = sum_ij m_ij (X_ij - X_i)^2 / sum_i (n_i - 1)        (expected process variance)
        VHM  a   = [sum_i m_i (X_i - X)^2 - s^2 (r - 1)] / (m - sum_i m_i^2/m)   (variance of hypothetical means)
        k = s^2/a, Z_i = m_i/(m_i + k), estimate_i = Z_i X_i + (1 - Z_i) mu, mu = sum Z_i X_i / sum Z_i.
    When a <= 0 the groups are indistinguishable from noise: k is infinite (None), Z = 0, every estimate is mu = X."""
    X = [np.asarray(v, float) for v in values]
    Wt = [np.ones_like(v) for v in X] if weights is None else [np.asarray(w, float) for w in weights]
    r = len(X)
    mi = np.array([w.sum() for w in Wt])
    Xi = np.array([float((w * v).sum() / w.sum()) for v, w in zip(X, Wt)])
    m = mi.sum()
    Xb = float((mi * Xi).sum() / m)
    df = float(sum(int((w > 0).sum()) - 1 for w in Wt)) if dof is None else float(dof)
    epv = float(sum((w * (v - xi) ** 2).sum() for v, w, xi in zip(X, Wt, Xi))) / df
    vhm = float(((mi * (Xi - Xb) ** 2).sum() - epv * (r - 1)) / (m - (mi ** 2).sum() / m))
    if vhm > 0:
        k = epv / vhm
        Z = mi / (mi + k)
        mu = float((Z * Xi).sum() / Z.sum())
    else:
        k, Z, mu = float("inf"), np.zeros(r), Xb
    est = Z * Xi + (1 - Z) * mu
    return jsonable({"groups": r, "epv": epv, "vhm": vhm, "k": k, "Z": Z, "exposure": mi, "group_means": Xi, "grand_mean": Xb,
                     "collective": mu, "estimates": est, "dof": df})


def buhlmann(groups) -> dict:
    """Buhlmann credibility for r groups of n observations each: EPV the mean within-group variance, VHM the variance
    of the group means less EPV/n, k = EPV/VHM, Z = n/(n + k). Unequal group sizes are passed to Buhlmann-Straub with
    unit exposures (the two coincide for equal sizes)."""
    G = [np.asarray(g, float) for g in groups]
    ns = {len(g) for g in G}
    if len(ns) > 1:
        return buhlmann_straub(G)
    n = ns.pop()
    r = len(G)
    means = np.array([g.mean() for g in G])
    epv = float(np.mean([g.var(ddof=1) for g in G]))
    vhm = float(means.var(ddof=1) - epv / n)
    grand = float(means.mean())
    if vhm > 0:
        k = epv / vhm
        z = n / (n + k)
    else:
        k, z = float("inf"), 0.0
    return jsonable({"groups": r, "n": n, "epv": epv, "vhm": vhm, "k": k, "Z": [z] * r, "group_means": means, "grand_mean": grand,
                     "collective": grand, "estimates": z * means + (1 - z) * grand})


def credibility_n0(r, state_probs) -> dict:
    """The pseudo-count decide.shrink() uses, estimated from the data. shrink() sets a state's mean to
    rbar + n/(n + n0) (mu_state - rbar) with n the state's months: that is Buhlmann credibility with Z = n/(n + k),
    so n0 should be k = EPV/VHM, the within-state variance of a month's return over the variance of the true state
    means. States are the groups and each month counts in each state with its probability (Buhlmann-Straub with the
    state probabilities as exposures; degrees of freedom the effective months less one per state).

    Two cautions. With two or three states VHM rests on one or two degrees of freedom, so k is noisy. And the states
    come from a model fit to the same returns, which separates the state means more than the truth would, so VHM is
    biased up and k down: a data-estimated n0 errs toward too little shrinkage."""
    r = np.asarray(r, float)
    P = np.asarray(state_probs, float)
    ok = np.isfinite(r) & np.isfinite(P).all(1)
    r, P = r[ok], P[ok]
    K = P.shape[1]
    out = buhlmann_straub([r] * K, [P[:, i] for i in range(K)], dof=float(P.sum() - K))
    out["n0"] = out["k"]
    out["months"] = int(len(r))
    return out


# ================================================================ the engine, evaluated
def _dma(models: dict, names, ll: dict, start: int, T: int, tilt=None):
    """decide's dynamic model-averaging mixture for every month from start, as padded arrays."""
    from . import decide
    ws, mus, sds = [None] * T, [None] * T, [None] * T
    WM = np.full((T, len(names)), np.nan)
    for t in range(start, T):
        wm = decide.averaging_weights(ll, t, names)
        WM[t] = wm
        W, MU, SD = [], [], []
        for j, k in enumerate(names):
            W.append(wm[j] * models[k]["w"][t])
            MU.append(models[k]["mu"][t] + (tilt[t] if tilt is not None and np.isfinite(tilt[t]) else 0.0))
            SD.append(models[k]["sd"][t])
        ws[t], mus[t], sds[t] = np.concatenate(W), np.concatenate(MU), np.concatenate(SD)
    return pad(ws, mus, sds), WM


def _member_mixture(models: dict, names, WM: np.ndarray, start: int, T: int, tilt=None):
    ws, mus, sds = [None] * T, [None] * T, [None] * T
    for t in range(start, T):
        ws[t] = np.concatenate([WM[t, j] * models[k]["w"][t] for j, k in enumerate(names)])
        mus[t] = np.concatenate([models[k]["mu"][t] + (tilt[t] if tilt is not None and np.isfinite(tilt[t]) else 0.0) for k in names])
        sds[t] = np.concatenate([models[k]["sd"][t] for k in names])
    return pad(ws, mus, sds)


def score_mixture(W, MU, SD, y, idx) -> dict:
    """Per-month log score, CRPS and PIT of padded mixtures on the rows idx."""
    w, mu, sd, yy = W[idx], MU[idx], SD[idx], y[idx]
    return {"ls": log_score_mixture(w, mu, sd, yy), "crps": crps_mixture(w, mu, sd, yy), "pit": pit_mixture(w, mu, sd, yy)}


CAL_TESTS = ("pit_ks", "pit_chi2", "pit_berkowitz_marginal", "coverage90", "tail_0.05_kupiec", "tail_0.05_z2", "tail_0.01_kupiec", "tail_0.01_z2")


def _summ_scores(s: dict) -> dict:
    """Mean scores and the calibration tests: PIT uniformity (KS and chi-square at the effective sample size), the
    marginal Berkowitz test, and 90% coverage. Tail tests are added by evaluate_engine."""
    ph = pit_histogram(s["pit"])
    cv = interval_coverage(s["pit"], 0.9)
    fail = [k for k, v in (("pit_ks", ph["ks_p_neff"]), ("pit_chi2", ph["chi2_p_neff"]), ("pit_berkowitz_marginal", ph["berkowitz_marginal_p"]),
                           ("coverage90", cv["kupiec_p"])) if v < 0.05]
    return {"log_score": float(np.mean(s["ls"])), "crps": float(np.mean(s["crps"])), "pit": ph, "coverage90": cv, "calibration_failures": fail}


def _compare(base: dict, var: dict, lags: int = 12) -> dict:
    ls = dm_test(var["ls"] - base["ls"], lags)
    cr = dm_test(base["crps"] - var["crps"], lags)
    return {"log_score_gain": ls["mean"], "log_score_t": ls["t"], "crps_gain": cr["mean"], "crps_t": cr["t"], "crps_gain_pct": float(cr["mean"] / np.mean(base["crps"]))}


def adoption(cmp: dict, base_fail: list, var_fail: list) -> dict:
    """The lead's rule: adopt only if the out-of-sample log score or CRPS improves with t > 2, or a calibration failure
    is fixed, without the other score worsening (t below -2)."""
    lt, ct = cmp["log_score_t"], cmp["crps_t"]
    fixed = [f for f in base_fail if f not in var_fail]
    worse = lt < -ADOPT_T or ct < -ADOPT_T
    better = lt > ADOPT_T or ct > ADOPT_T
    ok = (better or bool(fixed)) and not worse
    fzt = [cmp.get(f"fz0_t_{p}") for p in (0.05, 0.01) if cmp.get(f"fz0_t_{p}") is not None]
    if ok and not better:
        strength = "fix confirmed by the FZ0 tail score" if any(t_ > ADOPT_T for t_ in fzt) else "marginal: a tail p-value crossed 5% but the paired FZ0 tail score did not improve with t > 2"
    else:
        strength = "score improvement" if ok else "not adopted"
    why = ("log score t {:+.2f}, CRPS t {:+.2f}".format(lt, ct) + (f"; fixes {', '.join(fixed)}" if fixed else "")
           + (f"; new calibration failures {', '.join(f for f in var_fail if f not in base_fail)}" if any(f not in base_fail for f in var_fail) else ""))
    return {"adopt": bool(ok), "fixed": fixed, "worse": bool(worse), "strength": strength, "reason": why}


def _credibility_hmm(r: np.ndarray, start: int, models_hmm: dict, T: int):
    """The regime model with shrink()'s n0 estimated by credibility_n0 at each refit (on the smoothed state
    probabilities of the training data, all of it known at the refit), instead of the hand-set N0. decide.regime_walk is
    rerun (it is deterministic, so its fits are the engine's own) and decide.shrink is called with the estimated n0."""
    from . import decide, infer
    reg = decide.regime_walk(r, start)
    mu_t, sd_t, n0s = [None] * T, [None] * T, []
    done = {}
    for t in range(start, T):
        m = reg["model"][t]
        key = id(m)
        if key not in done:
            t0 = start + ((t - start) // decide.REFIT_HMM) * decide.REFIT_HMM
            upto = t0 - decide.LAG + 1
            if m["K"] > 1:
                P = infer.hmm_smooth(r[:upto], m)
                c = credibility_n0(r[:upto], P)
                n0 = c["n0"] if c["n0"] is not None else 1e12
            else:
                c, n0 = {"vhm": None, "epv": None}, decide.N0
            mu_s, sd_s = decide.shrink(m, r[:upto], n0=n0)
            done[key] = (mu_s, sd_s)
            n0s.append({"at": t0, "K": m["K"], "n0": None if n0 >= 1e12 else float(n0), "epv": c.get("epv"), "vhm": c.get("vhm")})
        mu_t[t], sd_t[t] = done[key]
    same_w = all(np.allclose(reg["w"][t], models_hmm["w"][t]) for t in range(start, T, 37))
    return {"w": reg["w"], "mu": mu_t, "sd": sd_t}, n0s, same_w


def _ll_component(m: dict, y: np.ndarray, start: int, T: int) -> np.ndarray:
    ll = np.full(T, np.nan)
    for t in range(start, T):
        ll[t] = float(log_score_mixture(m["w"][t], m["mu"][t], m["sd"][t], y[t]))
    return ll


def evaluate_engine(D, start_year: int = 1940, pred: dict | None = None, tilt=None, burn: int = 120, emos_refit: int = 12, sims: int = 2000,
                    seed: int = 19, tail: bool = True, ruin: bool = True) -> dict:
    """The engine's monthly predictive distribution scored out of sample, and four candidate improvements tested on it.

    The forecast for month t is decide's dynamic model-averaging mixture of its four models (averaging_weights on log
    scores known by t - LAG), from decide.predictive (pass `pred` to reuse one). The forecast tilt from the stacked
    12-month forecasts is not part of decide.predictive; pass `tilt` (decide.tilt_series) to include it.
        as_is        the mixture as the engine builds it
        emos         EMOS walked forward: location a + b m and spread scaled to sqrt(c + d v), fit every emos_refit months
                     by minimum CRPS on months known by t - LAG, the mixture's shape kept (mixture_recalibrate)
        emos_normal  the textbook NGR: the normal N(a + b m, c + d v) itself, for reference (the engine needs a mixture)
        bma          BMA weights by EM on the four models' past log scores (expanding window, known by t - LAG) in place
                     of the dynamic model-averaging weights
        credibility  shrink() with n0 estimated by credibility_n0 at each regime refit instead of the hand-set 120
    Each is scored by mean log score and CRPS with Diebold-Mariano t statistics (Newey-West, 12 lags) against as_is on
    the months after a burn-in of `burn` months (so EMOS and BMA have a record to fit on), by PIT uniformity and 90%
    coverage, and by the adoption rule. Then skill against climatology and persistence, the Brier score of the chance
    of a down month, the spread-skill relation, the tail backtest (with the engine's mixtures among the estimators) and
    ruin probabilities. Returns plain JSON types."""
    from . import decide
    t_all = time.time()
    timings = {}
    y = D["r"].to_numpy().astype(float)
    T = len(y)
    si = int(np.searchsorted(D.index.year, start_year))
    t0 = time.time()
    if pred is None:
        pred = decide.predictive(D, si)
    timings["predictive"] = time.time() - t0
    names = list(decide.MODELS)
    M = pred["models"]
    ll = {k: np.asarray(M[k]["ll"], float) for k in names}
    (W0, MU0, SD0), WM = _dma(M, names, ll, si, T, tilt)
    ev = np.arange(si + burn, T)
    full = np.arange(si, T)
    dates = [d.strftime("%Y-%m") for d in D.index]
    variants = {}
    raw = {}
    raw["as_is"] = score_mixture(W0, MU0, SD0, y, ev)
    raw_full = score_mixture(W0, MU0, SD0, y, full)
    # EMOS, mixture-preserving and normal
    t0 = time.time()
    em = emos_walk(MU0, SD0, y, si, refit=emos_refit, w=W0)
    raw["emos"] = score_mixture(em["w"], em["mu"], em["sd"], y, ev)
    m0, s0 = mixture_moments(np.nan_to_num(W0, nan=1.0), np.nan_to_num(MU0), np.nan_to_num(SD0, nan=1.0))
    m0[~np.isfinite(W0).all(1)] = np.nan
    s0[~np.isfinite(W0).all(1)] = np.nan
    en = emos_walk(m0, s0, y, si, refit=emos_refit)
    raw["emos_normal"] = {"ls": -0.5 * ((y[ev] - en["mu"][ev]) / en["sd"][ev]) ** 2 - np.log(en["sd"][ev] * SQ2PI),
                          "crps": crps_normal(en["mu"][ev], en["sd"][ev], y[ev]), "pit": ndtr((y[ev] - en["mu"][ev]) / en["sd"][ev])}
    timings["emos"] = time.time() - t0
    # BMA
    t0 = time.time()
    Lm = np.column_stack([ll[k] for k in names])
    WB = bma_walk(Lm, si, refit=12)
    W1, MU1, SD1 = _member_mixture(M, names, WB, si, T, tilt)
    raw["bma"] = score_mixture(W1, MU1, SD1, y, ev)
    timings["bma"] = time.time() - t0
    # credibility n0
    t0 = time.time()
    hmm_c, n0s, same_w = _credibility_hmm(y, si, M["hmm"], T)
    M2 = dict(M)
    M2["hmm"] = {**hmm_c}
    ll2 = dict(ll)
    ll2["hmm"] = _ll_component(M2["hmm"], y, si, T)
    (W2, MU2, SD2), WM2 = _dma(M2, names, ll2, si, T, tilt)
    raw["credibility"] = score_mixture(W2, MU2, SD2, y, ev)
    timings["credibility"] = time.time() - t0
    mixes = {"as_is": (W0, MU0, SD0), "emos": (em["w"], em["mu"], em["sd"]), "emos_normal": (np.ones((T, 1)), en["mu"][:, None], en["sd"][:, None]),
             "bma": (W1, MU1, SD1), "credibility": (W2, MU2, SD2)}
    vt = None
    if tail:
        t0 = time.time()
        vt = tail_backtest(y, si + burn, mixtures={k: mixes[k] for k in raw}, sims=sims, seed=seed, methods=())
        timings["tail_variants"] = time.time() - t0
    for k, s in raw.items():
        v = _summ_scores(s)
        if vt is not None:
            tm = vt["methods"][k]
            v["tail"] = {p: {"hit_rate": tm[p]["kupiec"]["rate"], "kupiec_p": tm[p]["kupiec"]["p"], "z2": tm[p]["z2"]["z2"], "z2_p": tm[p]["z2"]["p"],
                             "independence_p": tm[p]["christoffersen"]["p_ind"], "es_mean": tm[p]["es_mean"]} for p in ("0.05", "0.01")}
            v["calibration_failures"] += [f"tail_{p}_{t_}" for p in ("0.05", "0.01") for t_, key in (("kupiec", "kupiec_p"), ("z2", "z2_p")) if v["tail"][p][key] < 0.05]
        variants[k] = v
    fz = {}
    for k in raw:
        Wk, Mk, Sk = (a_[ev] for a_ in mixes[k])
        fz[k] = {}
        for p in (0.05, 0.01):
            vv, ee = mixture_var_es(Wk, Mk, Sk, p)
            fz[k][p] = fz0_loss(y[ev], vv, ee, p)
    for k in raw:
        if k != "as_is":
            v = variants[k]
            v["vs_as_is"] = _compare(raw["as_is"], raw[k])
            for p in (0.05, 0.01):
                d_ = dm_test(fz["as_is"][p] - fz[k][p])
                v["vs_as_is"][f"fz0_gain_{p}"], v["vs_as_is"][f"fz0_t_{p}"] = d_["mean"], d_["t"]
            v["adoption"] = adoption(v["vs_as_is"], variants["as_is"]["calibration_failures"], v["calibration_failures"])
    # benchmarks for the engine as is
    clim = climatology_scores(y, si)
    pers = persistence_scores(y, si)
    bench = {"climatology": {"crps": skill(raw["as_is"]["crps"], clim["crps"][ev]), "log_score": skill(raw["as_is"]["ls"], clim["ls"][ev], "gain")},
             "persistence": {"crps": skill(raw["as_is"]["crps"], pers["crps"][ev]), "log_score": skill(raw["as_is"]["ls"], pers["ls"][ev], "gain")},
             "uncond_model": {"crps": skill(raw["as_is"]["crps"], crps_mixture(*pad(M["uncond"]["w"], M["uncond"]["mu"], M["uncond"]["sd"]), y)[ev]),
                              "log_score": skill(raw["as_is"]["ls"], ll["uncond"][ev], "gain")}}
    # the chance of a down month
    pdn = pit_mixture(W0[ev], MU0[ev], SD0[ev], np.zeros(len(ev)))
    o = (y[ev] < 0).astype(float)
    base_rate = np.array([np.mean(y[:t - LAG + 1] < 0) for t in ev])
    br = brier(pdn, o, bins=10)
    br_clim = float(np.mean((base_rate - o) ** 2))
    br["bss_vs_climatology"] = float(1 - br["bs"] / br_clim)
    br["bs_climatology"] = br_clim
    br["dm_vs_climatology"] = dm_test((base_rate - o) ** 2 - (pdn - o) ** 2)
    m_ev, s_ev = mixture_moments(W0[ev], MU0[ev], SD0[ev])
    ssk = spread_skill(s_ev, y[ev] - m_ev)
    out = {"schema": 1, "start": dates[si], "eval_start": dates[si + burn], "end": dates[-1], "months_full": int(len(full)), "months_eval": int(len(ev)),
           "burn_in_months": burn, "lag": LAG, "tilt_included": tilt is not None,
           "as_is_full": _summ_scores(raw_full), "variants": variants, "benchmarks": bench, "brier_down_month": br, "spread_skill": ssk,
           "emos": {"fits_last": em["fits"][-1] if em["fits"] else None, "fits": em["fits"][::5], "normal_fits_last": en["fits"][-1] if en["fits"] else None,
                    "scale_median": float(np.nanmedian(em["scale"][ev]))},
           "bma": {"weights_last": {k: float(WB[-1, j]) for j, k in enumerate(names)}, "weights_mean": {k: float(np.nanmean(WB[ev, j])) for j, k in enumerate(names)},
                   "dma_weights_mean": {k: float(np.nanmean(WM[ev, j])) for j, k in enumerate(names)},
                   "dma_max_weight_mean": float(np.nanmean(WM[ev].max(1))), "bma_max_weight_mean": float(np.nanmean(WB[ev].max(1)))},
           "credibility": {"n0_hand": decide.N0, "fits": n0s, "n0_median": float(np.median([f["n0"] for f in n0s if f["n0"] is not None])) if any(f["n0"] is not None for f in n0s) else None,
                           "infinite_count": int(sum(f["n0"] is None and f["K"] > 1 for f in n0s)), "regime_weights_match_engine": bool(same_w)},
           "rule": "adopt only if the out-of-sample log score or CRPS improves with t > 2, or a calibration failure is fixed, without the other worsening (t below -2)"}
    out["adopt"] = [k for k, v in variants.items() if k != "as_is" and v["adoption"]["adopt"]]
    if tail:
        t0 = time.time()
        out["tail"] = tail_backtest(y, si, mixtures={"engine": (W0, MU0, SD0)}, sims=sims, seed=seed)
        timings["tail"] = time.time() - t0
    if ruin:
        t0 = time.time()
        rr = {}
        for x in (1.0, 1.5):
            rp = ruin_probability(y, x, 0.5, 120, B=4000, block=12, seed=seed, borrow=decide.BORROW)
            g = np.log(np.maximum(1 + x * y - max(x - 1, 0) * decide.BORROW, 1e-12))
            cl = cramer_lundberg(float(g.mean()), float(g.std()), u=-math.log(0.5))
            Re = adjustment_coefficient(g)
            rr[str(x)] = {"bootstrap_dd50_10y": rp, "cramer_lundberg": cl, "empirical_R": Re, "empirical_lundberg_bound": math.exp(-Re * -math.log(0.5)) if Re else None,
                          "brownian_from_start_10y": brownian_ruin(float(g.mean()), float(g.std()), -math.log(0.5), 120, dt=1.0)}
        out["ruin"] = rr
        timings["ruin"] = time.time() - t0
    timings["total"] = time.time() - t_all
    out["timings_s"] = timings
    return jsonable(out)


# ================================================================ plain English
def _f(v, fmt="{:+.2f}"):
    return "n/a" if v is None else fmt.format(v)


NAMES = {"emos": "EMOS recalibration (location and spread, mixture shape kept)", "emos_normal": "textbook EMOS (a single normal)",
         "bma": "BMA weights by EM in place of dynamic model averaging", "credibility": "shrink() with the credibility-estimated n0"}


def summary(o: dict) -> list[str]:
    """Plain-English findings: third person, what helped and what did not."""
    v = o["variants"]
    a = v["as_is"]
    out = []
    ph, cv = a["pit"], a["coverage90"]
    out.append(f"From {o['eval_start']} to {o['end']} ({o['months_eval']} months) the engine's predictive mixture scores a mean log score of {a['log_score']:.3f} and a "
               f"CRPS of {a['crps']:.4f}; its 90% intervals cover {cv['coverage']:.1%} of months (Kupiec p {cv['kupiec_p']:.2f}), and its PIT has sd "
               f"{ph['pit_sd']:.3f} against {ph['pit_sd_uniform']:.3f} for a calibrated forecast, so the body of the distribution is slightly too wide (KS p {ph['ks_p']:.3f}, "
               f"{ph['ks_p_neff']:.3f} allowing for serial dependence; marginal Berkowitz p {ph['berkowitz_marginal_p']:.3f}).")
    out.append(f"The full Berkowitz test rejects (p {ph['berkowitz_p']:.2g}) because consecutive PITs are correlated ({ph['z_acf1']:+.2f}): Shiller's prices are monthly "
               f"averages, which builds positive first-order autocorrelation into monthly returns, and the engine acts two months late, so last month's return is not "
               f"in its information set. This is a known feature of the data rather than a fixable miscalibration.")
    cf_ = a["calibration_failures"]
    out.append("Calibration failures of the engine as is: " + (", ".join(cf_) if cf_ else "none") + ". " +
               ("The failures are in the far tail: at 1% the mixture is breached more often and by more than it predicts." if any(f.startswith("tail_0.01") for f in cf_) else ""))
    b = o["benchmarks"]
    out.append(f"Against climatology (the expanding history of returns) the engine's CRPS skill is {b['climatology']['crps']['skill']:+.2%} (t {_f(b['climatology']['crps']['t'])}) "
               f"and its log score gain {b['climatology']['log_score']['gain']:+.4f} (t {_f(b['climatology']['log_score']['t'])}); against its own long-run-average model, "
               f"CRPS skill {b['uncond_model']['crps']['skill']:+.2%} (t {_f(b['uncond_model']['crps']['t'])}); persistence is far worse (CRPS skill of the engine "
               f"{b['persistence']['crps']['skill']:+.0%}).")
    good, bad = [], []
    for k in ("emos", "emos_normal", "bma", "credibility"):
        if k not in v:
            continue
        c = v[k]["vs_as_is"]
        line = (f"{NAMES[k]}: log score {c['log_score_gain']:+.4f} (t {_f(c['log_score_t'])}), CRPS {c['crps_gain_pct']:+.2%} (t {_f(c['crps_t'])}), "
                f"joint VaR-ES score (FZ0) t {_f(c.get('fz0_t_0.05'))} at 5% and {_f(c.get('fz0_t_0.01'))} at 1%")
        if v[k]["adoption"]["fixed"]:
            line += f", fixes {', '.join(v[k]['adoption']['fixed'])}"
        (good if v[k]["adoption"]["adopt"] else bad).append(line)
    if good:
        out.append("Passes the adoption rule: " + "; ".join(good) + ". A fix here means a tail test's p-value moved from below 5% to above it; "
                   "the FZ0 t statistics are the paired test of whether the tail forecast actually improved, and a fix without an FZ0 t above 2 is marginal.")
    out.append(("Does not pass the adoption rule: " + "; ".join(bad) + ".") if bad else "Every candidate passes the adoption rule.")
    cr = o["credibility"]
    out.append(f"Credibility theory puts the regime shrinkage pseudo-count at a median of {_f(cr['n0_median'], '{:.0f}')} months across the regime refits (the hand-set value is "
               f"{cr['n0_hand']}), with {cr['infinite_count']} refits where the state means were indistinguishable from noise (full shrinkage); with two or three states the "
               f"estimate rests on one or two degrees of freedom, so it is a check on the hand-set value more than a replacement.")
    bm = o["bma"]
    out.append(f"Dynamic model averaging puts {bm['dma_max_weight_mean']:.0%} of the weight on its favorite model in an average month; BMA by EM, {bm['bma_max_weight_mean']:.0%}. "
               f"BMA's latest weights: " + ", ".join(f"{k} {w:.2f}" for k, w in bm["weights_last"].items()) + ".")
    br = o["brier_down_month"]
    out.append(f"The chance of a down month: Brier score {br['bs']:.4f} against {br['bs_climatology']:.4f} for the historical frequency (skill {br['bss_vs_climatology']:+.2%}, "
               f"t {_f(br['dm_vs_climatology']['t'])}); reliability {br['reliability']:.4f}, resolution {br['resolution']:.4f}, uncertainty {br['uncertainty']:.4f}.")
    ss = o["spread_skill"]
    out.append(f"Spread and skill: the correlation of the mixture's sd with the size of the miss is {ss['corr']:.2f} (p {ss['corr_p']:.3g}); the RMSE is "
               f"{ss['ratio_rmse_to_sd']:.2f} times the mean predictive sd.")
    if "tail" in o:
        tl = o["tail"]
        for p in ("0.05", "0.01"):
            rows = []
            for nme, res in tl["methods"].items():
                q = res[p]
                rows.append(f"{nme} {q['kupiec']['rate']:.1%} hits (Kupiec p {q['kupiec']['p']:.2f}, Z2 {q['z2']['z2']:+.2f} p {q['z2']['p']:.2f}, independence p {q['christoffersen']['p_ind']:.2f})")
            cal = tl["calibrated"][p]
            ci = tl["calibrated_and_independent"][p]
            out.append(f"Tail backtest at {float(p):.0%} since {o['start'][:4]}: " + "; ".join(rows) + ". Calibrated in frequency and size: " + (", ".join(cal) if cal else "none")
                       + "; also independent: " + (", ".join(ci) if ci else "none") + ".")
        if tl.get("fz0_vs_ref"):
            fzr = tl["fz0_vs_ref"]
            out.append(f"Paired against the {tl['fz0_ref']} tail by the FZ0 joint VaR-ES score (t > 0 favors the alternative): "
                       + "; ".join(f"{n_} t {_f(d_['0.05']['t'])} at 5% and {_f(d_['0.01']['t'])} at 1%" for n_, d_ in fzr.items())
                       + (". No estimator beats it with t above 2." if not any((d_[p]["t"] or 0) > ADOPT_T for d_ in fzr.values() for p in ("0.05", "0.01")) else "."))
        vt = {k: v_["tail"] for k, v_ in v.items() if "tail" in v_}
        if vt:
            out.append(f"Tails of each candidate on the same months ({o['eval_start'][:4]} on): " + "; ".join(
                f"{k} {t_['0.01']['hit_rate']:.1%} breaches at 1% (Z2 {t_['0.01']['z2']:+.2f}, p {t_['0.01']['z2_p']:.2f}) and {t_['0.05']['hit_rate']:.1%} at 5%" for k, t_ in vt.items()) + ".")
        e5 = tl["methods"].get("engine", {}).get("0.05")
        if e5 and "pot" in tl["methods"] and "filtered_pot" in tl["methods"]:
            pt, fp = tl["methods"]["pot"]["0.05"], tl["methods"]["filtered_pot"]["0.05"]
            out.append(f"For the 12% ES budget: the engine's own 5% ES averaged {e5['es_mean']:.1%} and is {e5['es_last']:.1%} in the latest month, allowing up to "
                       f"{e5['max_exposure_now']:.2f}x" + (" (calibrated at 5%, so the budget is measured on a sound number)" if e5["calibrated"] else " (not calibrated at 5%)")
                       + f"; the POT estimate is {pt['es_last']:.1%} (up to {pt['max_exposure_now']:.2f}x) and the volatility-filtered POT {fp['es_last']:.1%} "
                       f"(up to {fp['max_exposure_now']:.2f}x). "
                       + ("The budget does not bind at 1x under any of them." if min(e5["max_exposure_now"], pt["max_exposure_now"], fp["max_exposure_now"]) >= 1
                          else "The budget binds below 1x under at least one of them."))
    if "ruin" in o:
        r1, r15 = o["ruin"]["1.0"], o["ruin"]["1.5"]
        out.append(f"Ruin, read as a 50% fall from a peak within ten years by block bootstrap of every month since 1871: {r1['bootstrap_dd50_10y']['p']:.1%} at 1x and "
                   f"{r15['bootstrap_dd50_10y']['p']:.1%} at 1.5x. The Brownian Cramer-Lundberg bound for ever losing half from the start is "
                   f"{r1['cramer_lundberg']['lundberg_bound']:.1%} at 1x and {r15['cramer_lundberg']['lundberg_bound']:.1%} at 1.5x (adjustment coefficients "
                   f"{r1['cramer_lundberg']['R']:.2f} and {r15['cramer_lundberg']['R']:.2f}).")
    return out
