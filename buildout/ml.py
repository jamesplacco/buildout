"""Machine learning that a skeptical portfolio manager can audit: what it forecasts, how it was validated, how often it
would have been fooled, and whether today looks like anything it has seen.

Data: Shiller's monthly S&P 500 since 1871 (real total return, CAPE, the long rate, CPI), the same series the labs
use. Two questions, both with a 12-month horizon:
  return   the next 12 months' real total return (log), against the prevailing historical mean
  crash    whether the real index falls 15% or more below today's level at any month in the next 12, against the
           prevailing base rate

Features are dated so they were knowable: price-based features use last month's average, earnings and dividends a
four-month publication lag, inflation a one-month release lag.

Validation (what usually goes wrong, and the fix):
  overlap leakage      targets overlap for 12 months; a training row is used only if its target window ended before
                       the forecast date, plus a one-month embargo (purged walk-forward, Lopez de Prado 2018)
  lucky model choice   combinatorial purged cross-validation over 8 blocks, 28 splits, every model configuration; the
                       probability of backtest overfitting is how often the in-sample winner lands below the median
                       out of sample (Bailey et al. 2017)
  false skill          Diebold-Mariano tests with Newey-West errors against the benchmark; out-of-sample R squared and
                       the Brier skill score, never in-sample fit
  hidden fragility     results by era and by regime; permutation importance on out-of-sample blocks only
  false precision      conformal intervals from the model's own past errors, with their realised coverage
  extrapolation        adversarial validation (can a classifier tell recent months from history?) and each feature's
                       distance from its historical range; nearest historical analogs, with what followed

v0.25, the ensemble (combine="v25"; combine="v24" restores the equal-weight mean):
  return   each member's forecast truncated at zero (Campbell and Thompson 2008), averaged, then shrunk toward the
           historical mean by a credibility weight: the discounted least-squares slope of realised excess outcomes on
           the ensemble's excess forecasts, using only forecasts whose outcome was known (H months back), clipped to
           [0, 1], and zero until 60 such outcomes exist
  crash    the equal-weight probability shrunk toward the base rate by the same weight
Every variant tried is scored walk-forward and listed in the build output under "v25_trials".
"""
from __future__ import annotations

import math
from itertools import combinations

import numpy as np
import pandas as pd

from . import labs
from .core import cache

H = 12
EMBARGO = 1
START_OOS = 1940
REFIT = 12
SEED = 11
FEATURES = ["log_cape", "ecy", "y10", "infl12", "mom12_1", "trend_gap", "vol12", "drawdown"]
NAMES = {"log_cape": "Valuation (log CAPE)", "ecy": "Excess CAPE yield", "y10": "Long-term interest rate", "infl12": "Inflation, 12 months",
         "mom12_1": "Momentum, 12 minus 1 months", "trend_gap": "Distance from the 10-month average", "vol12": "Volatility, 12 months",
         "drawdown": "Distance below the peak"}
CRASH = -0.15
COMBINE = "v25"                 # how the ensemble is formed (see combine())
SHRINK_DELTA = 0.9 ** (1 / 12)  # the credibility weight's discount, the same as the accuracy-weighted ensemble's
SHRINK_MIN = 60                 # known outcomes needed before the ensemble departs from the benchmark


# ---------------------------------------------------------------- data
def panel(S: pd.DataFrame) -> pd.DataFrame:
    """Features knowable at the start of each month, and the two 12-month targets."""
    r, px, _ = labs.total_return_index(S)
    cpi = S["cpi"]
    real_px = (px / cpi).reindex(r.index)
    tri = (1 + r).cumprod()
    real_eps = (S["eps"] / cpi).shift(4)
    cape = (S["px"] / cpi) / real_eps.rolling(120, min_periods=120).mean()
    infl12 = np.log(cpi.shift(1) / cpi.shift(13))
    infl10 = np.log(cpi.shift(1) / cpi.shift(121)) / 10
    y10 = S["y10"].shift(1) / 100
    p1 = px.shift(1)
    ma10 = p1.rolling(10).mean()
    rr = r.reindex(px.index)
    X = pd.DataFrame({
        "log_cape": np.log(cape.shift(1)),
        "ecy": 1 / cape.shift(1) - (y10 - infl10),
        "y10": y10,
        "infl12": infl12,
        "mom12_1": np.log(px.shift(2) / px.shift(13)),
        "trend_gap": p1 / ma10 - 1,
        "vol12": rr.shift(1).rolling(12).std() * math.sqrt(12),
        "drawdown": (real_px.reindex(px.index).shift(1) / real_px.reindex(px.index).shift(1).cummax() - 1),
    }, index=px.index)
    lt = np.log(tri.reindex(px.index))
    X["y_ret"] = lt.shift(-H) - lt
    rp = real_px.reindex(px.index)
    fut_min = pd.concat([rp.shift(-k) for k in range(1, H + 1)], axis=1).min(axis=1)
    X["y_crash"] = (fut_min / rp - 1 <= CRASH).astype(float)
    X.loc[rp.shift(-H).isna(), ["y_ret", "y_crash"]] = np.nan
    return X


def today_row(X: pd.DataFrame, S: pd.DataFrame, cape_now: float | None, y10_now: float | None) -> tuple[pd.Series, dict]:
    """The latest month's features. Where Shiller's series stop (earnings in 2023, the long rate in 2023) the current
    CAPE and 10-year yield come from the checked research (labelled), the rest from the price and CPI data."""
    last = X.index[-1]
    row = X.loc[last, FEATURES].copy()
    notes = {"date": last.strftime("%Y-%m")}
    cpi = S["cpi"]
    infl10 = float(np.log(cpi.iloc[-2] / cpi.iloc[-122]) / 10)
    if cape_now:
        row["log_cape"] = math.log(cape_now)
        notes["cape"] = {"value": cape_now, "source": "research (multpl, secondary)"}
    if y10_now:
        row["y10"] = y10_now / 100
        notes["y10"] = {"value": y10_now, "source": "research (Treasury)"}
    if cape_now and y10_now:
        row["ecy"] = 1 / cape_now - (y10_now / 100 - infl10)
    for f in FEATURES:
        if not np.isfinite(row[f]):
            row[f] = X[f].dropna().iloc[-1]
            notes.setdefault("carried", []).append(f)
    return row, notes


# ---------------------------------------------------------------- models
THEORY_SIGN = {"log_cape": -1, "ecy": 1, "infl12": -1, "mom12_1": 1, "trend_gap": 1, "drawdown": -1}   # expected sign of each slope


class Combination:
    """Rapach, Strauss and Zhou (2010): the mean of one-variable OLS forecasts, one per feature, with Campbell and
    Thompson's (2008) restrictions: a slope with the wrong theoretical sign is set to zero (that forecast becomes the
    historical mean), and the combined forecast is floored at zero (a stock forecast below zero is not believed)."""

    def __init__(self, feats: list[str], floor: float | None = 0.0):
        self.feats, self.floor = feats, floor

    def fit(self, X, y):
        X, y = np.asarray(X, float), np.asarray(y, float)
        self.mu = float(y.mean())
        self.coef = []
        for j, f in enumerate(self.feats):
            x = X[:, j]
            v = float(np.var(x))
            b = float(np.cov(x, y, bias=True)[0, 1] / v) if v > 0 else 0.0
            if THEORY_SIGN.get(f, 0) * b < 0:
                b = 0.0
            self.coef.append((b, float(x.mean())))
        return self

    def predict(self, X):
        X = np.asarray(X, float)
        p = np.mean([self.mu + b * (X[:, j] - m) for j, (b, m) in enumerate(self.coef)], axis=0)
        return np.maximum(p, self.floor) if self.floor is not None else p


def models(task: str) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
    from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge
    from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if task == "return":
        return {
            "cape_ols": ("Classic: CAPE alone", lambda: LinearRegression(), ["log_cape"]),
            "ridge": ("Ridge regression", lambda: make_pipeline(StandardScaler(), Ridge(alpha=30.0)), FEATURES),
            "forest": ("Random forest", lambda: RandomForestRegressor(n_estimators=150, max_depth=4, min_samples_leaf=36, max_features=0.5, random_state=SEED, n_jobs=-1), FEATURES),
            "boost": ("Gradient boosting", lambda: HistGradientBoostingRegressor(max_depth=3, learning_rate=0.04, max_iter=120, min_samples_leaf=36, l2_regularization=1.0, random_state=SEED), FEATURES),
            "analogs": ("Nearest historical analogs", lambda: make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=36)), FEATURES),
            "combo": ("Combination of one-variable forecasts, restricted", lambda: Combination(FEATURES), FEATURES),
        }
    return {
        "logit": ("Logistic regression", lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=500)), FEATURES),
        "forest": ("Random forest", lambda: RandomForestClassifier(n_estimators=150, max_depth=4, min_samples_leaf=36, max_features=0.5, random_state=SEED, n_jobs=-1), FEATURES),
        "boost": ("Gradient boosting", lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.04, max_iter=120, min_samples_leaf=36, l2_regularization=1.0, random_state=SEED), FEATURES),
        "analogs": ("Nearest historical analogs", lambda: make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=36)), FEATURES),
    }


def _fit_predict(make, feats, Xtr, ytr, Xte, task):
    m = make()
    m.fit(Xtr[feats].to_numpy(), ytr)
    if task == "return":
        return m.predict(Xte[feats].to_numpy()), m
    if len(np.unique(ytr)) < 2:
        return np.full(len(Xte), float(ytr.mean())), m
    return m.predict_proba(Xte[feats].to_numpy())[:, 1], m


# ---------------------------------------------------------------- purged walk-forward
def walk_forward(D: pd.DataFrame, task: str, start: int = START_OOS, refit: int = REFIT, permute: bool = True, combine: str = COMBINE,
                 shrink_delta: float | None = SHRINK_DELTA) -> dict:
    """Expanding-window forecasts made only with rows whose 12-month target had ended (plus an embargo) by the forecast
    date; refit every `refit` months. Benchmark: the expanding mean (or base rate) of those same rows. The ensemble
    is formed by combine_forecasts(method=combine); "ensemble_v24" is always the equal-weight mean."""
    ycol = "y_ret" if task == "return" else "y_crash"
    D = D.dropna(subset=FEATURES + [ycol])
    idx = D.index
    test_pos = [i for i, d in enumerate(idx) if d.year >= start]
    if not test_pos:
        raise ValueError("no test months")
    M = models(task)
    preds = {k: np.full(len(idx), np.nan) for k in M}
    bench = np.full(len(idx), np.nan)
    imp = {k: {f: [] for f in FEATURES} for k in M}
    rng = np.random.default_rng(SEED)
    blocks = [test_pos[i:i + refit] for i in range(0, len(test_pos), refit)]
    for blk in blocks:
        t0 = blk[0]
        cut = t0 - H - EMBARGO                     # the last row whose target window ended before the forecast date
        if cut < 120:
            continue
        tr = D.iloc[:cut + 1]
        te = D.iloc[blk]
        ytr = tr[ycol].to_numpy()
        bench[blk] = ytr.mean()
        for k, (_, make, feats) in M.items():
            p, m = _fit_predict(make, feats, tr, ytr, te, task)
            preds[k][blk] = p
            if permute and len(blk) >= 6:
                base = _loss(te[ycol].to_numpy(), p, task)
                for f in feats:
                    Xp = te[feats].to_numpy().copy()
                    j = feats.index(f)
                    Xp[:, j] = rng.permutation(Xp[:, j])
                    pp = m.predict(Xp) if task == "return" else (m.predict_proba(Xp)[:, 1] if hasattr(m, "predict_proba") and len(np.unique(ytr)) > 1 else p)
                    imp[k][f].append(_loss(te[ycol].to_numpy(), pp, task) - base)
    ok = ~np.isnan(bench)
    y = D[ycol].to_numpy()
    with np.errstate(all="ignore"):
        stack = np.vstack([preds[k] for k in M if k != "cape_ols"])
        ens = np.where(np.isnan(stack).all(axis=0), np.nan, np.nanmean(np.where(np.isnan(stack), 0, stack), axis=0) * stack.shape[0] / np.maximum(1, (~np.isnan(stack)).sum(axis=0)))
    members = [k for k in M if k != "cape_ols"]
    preds["dmspe"] = dmspe([preds[k] for k in members], y, ok)
    preds["ensemble_v24"] = ens
    preds["ensemble"], wts = combine_forecasts([preds[k] for k in members], bench, y, ok, task, combine, shrink_delta)
    out = {"task": task, "dates": [d.strftime("%Y-%m") for d in idx[ok]], "y": y[ok].tolist(), "bench": bench[ok].tolist(),
           "preds": {k: v[ok].tolist() for k, v in preds.items()}, "n": int(ok.sum()), "refits": len(blocks), "combine": combine, "members": members,
           "shrink_weight": None if wts is None else wts[ok].tolist(),
           "importance": {k: {f: (float(np.mean(v)) if v else None) for f, v in d.items()} for k, d in imp.items()}}
    return out


# ---------------------------------------------------------------- v0.25: restrictions, credibility shrinkage, calibration
def _known(pos: np.ndarray, a: int, i: int) -> np.ndarray:
    """Earlier forecast rows whose 12-month outcome had been seen by forecast row i (the dmspe rule)."""
    kj = pos[:a]
    return kj[kj <= i - H - 1]


def credibility_weight(d: np.ndarray, u: np.ndarray, disc: np.ndarray | None = None) -> float:
    """The weight on a forecast's departure d from the benchmark that minimizes the (discounted) squared error of the
    realised departure u: sum(w d u) / sum(w d^2), clipped to [0, 1]. Zero means the benchmark; one means the forecast."""
    w = np.ones(len(d)) if disc is None else disc
    den = float((w * d * d).sum())
    return 0.0 if den <= 0 else min(1.0, max(0.0, float((w * d * u).sum()) / den))


def credibility(p: np.ndarray, bench: np.ndarray, y: np.ndarray, ok: np.ndarray, delta: float | None = SHRINK_DELTA, min_known: int = SHRINK_MIN) -> tuple[np.ndarray, np.ndarray]:
    """Shrink forecasts toward the benchmark, row by row, with a credibility weight estimated only from earlier
    forecasts whose outcome was known; the benchmark until `min_known` such outcomes exist. delta None: no discount."""
    p, bench, y = (np.asarray(v, float) for v in (p, bench, y))
    out = np.full(len(p), np.nan)
    wts = np.full(len(p), np.nan)
    pos = np.where(ok)[0]
    d, u = p - bench, y - bench
    for a, i in enumerate(pos):
        kj = _known(pos, a, i)
        w = 0.0
        if len(kj) >= min_known:
            w = credibility_weight(d[kj], u[kj], None if delta is None else delta ** (i - 1 - kj))
        wts[i] = w
        out[i] = bench[i] + w * d[i]
    return out, wts


def _logit(p):
    q = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(q / (1 - q))


def platt_fit(z: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Logistic regression of outcomes on a score, by maximum likelihood (L-BFGS from the identity map)."""
    from scipy.optimize import minimize
    X = np.column_stack([np.ones(len(z)), z])

    def nll(th):
        eta = np.clip(X @ th, -30, 30)
        q = 1 / (1 + np.exp(-eta))
        return float(-np.sum(y * np.log(np.clip(q, 1e-12, 1)) + (1 - y) * np.log(np.clip(1 - q, 1e-12, 1)))), X.T @ (q - y)
    th = minimize(nll, np.array([0.0, 1.0]), jac=True, method="L-BFGS-B").x
    return float(th[0]), float(th[1])


def platt(p: np.ndarray, y: np.ndarray, ok: np.ndarray, fallback: np.ndarray, min_known: int = SHRINK_MIN) -> np.ndarray:
    """Platt scaling walked forward: at each row, a logistic map of logit(p) fit on earlier rows with known outcomes."""
    z = _logit(p)
    out = np.array(fallback, float).copy()
    pos = np.where(ok)[0]
    for a, i in enumerate(pos):
        kj = _known(pos, a, i)
        if len(kj) < min_known or len(np.unique(y[kj])) < 2:
            continue
        a0, a1 = platt_fit(z[kj], np.asarray(y, float)[kj])
        out[i] = 1 / (1 + math.exp(-min(30.0, max(-30.0, a0 + a1 * z[i]))))
    return out


def pav(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pool-adjacent-violators: the nondecreasing step function of x closest to y. Returns (right edges, levels)."""
    o = np.argsort(x, kind="mergesort")
    vals, wts, edge = [], [], []
    for xx, v in zip(np.asarray(x, float)[o], np.asarray(y, float)[o]):
        vals.append(v); wts.append(1.0); edge.append(xx)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            w = wts[-2] + wts[-1]
            vals[-2:] = [(vals[-2] * wts[-2] + vals[-1] * wts[-1]) / w]
            wts[-2:] = [w]
            edge[-2:] = [edge[-1]]
    return np.array(edge), np.array(vals)


def isotonic(p: np.ndarray, y: np.ndarray, ok: np.ndarray, fallback: np.ndarray, min_known: int = SHRINK_MIN) -> np.ndarray:
    """Isotonic calibration walked forward: at each row, PAV fit on earlier rows with known outcomes."""
    out = np.array(fallback, float).copy()
    pos = np.where(ok)[0]
    for a, i in enumerate(pos):
        kj = _known(pos, a, i)
        if len(kj) < min_known:
            continue
        e, v = pav(np.asarray(p)[kj], np.asarray(y)[kj])
        out[i] = v[min(int(np.searchsorted(e, p[i])), len(v) - 1)]
    return out


def _mean_rows(P: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        return np.where(np.isnan(P).all(axis=0), np.nan, np.nanmean(np.where(np.isnan(P), 0, P), axis=0) * P.shape[0] / np.maximum(1, (~np.isnan(P)).sum(axis=0)))


def combine_forecasts(P: list, bench: np.ndarray, y: np.ndarray, ok: np.ndarray, task: str, method: str = COMBINE, delta: float | None = SHRINK_DELTA) -> tuple[np.ndarray, np.ndarray | None]:
    """The ensemble from member forecasts P. Methods: v24 (equal-weight mean), floor (members truncated at zero, return
    only), shrink (mean shrunk toward the benchmark), floor_shrink, shrink_members, platt and isotonic (calibrated
    mean, crash only); v25 is floor_shrink for returns and shrink for crashes. Returns (forecast, weights or None)."""
    P = np.vstack(P).astype(float)
    if method == "v25":
        method = "floor_shrink" if task == "return" else "shrink"
    if method in ("floor", "floor_shrink") and task == "return":
        P = np.maximum(P, 0.0)
    if method == "shrink_members":
        return _mean_rows(np.vstack([credibility(p, bench, y, ok, delta)[0] for p in P])), None
    m = _mean_rows(P)
    if method in ("shrink", "floor_shrink"):
        return credibility(m, bench, y, ok, delta)
    if method == "platt":
        return platt(m, y, ok, bench), None
    if method == "isotonic":
        return isotonic(m, y, ok, bench), None
    if method in ("v24", "floor"):
        return m, None
    raise ValueError(f"unknown combine method {method}")


def combine_now(now_members: list[float], bench_now: float, W: dict, task: str, method: str = COMBINE, delta: float | None = SHRINK_DELTA) -> tuple[float, float | None]:
    """Today's ensemble: the same combination, with a credibility weight from every walked-forward forecast (all of
    whose outcomes are known by today)."""
    if method == "v25":
        method = "floor_shrink" if task == "return" else "shrink"
    v = np.array(now_members, float)
    if method in ("floor", "floor_shrink") and task == "return":
        v = np.maximum(v, 0.0)
    raw = float(v.mean())
    if method not in ("shrink", "floor_shrink"):
        return raw, None
    y, b = np.array(W["y"]), np.array(W["bench"])
    Pm = np.vstack([np.array(W["preds"][k]) for k in W["members"]])
    if method == "floor_shrink" and task == "return":
        Pm = np.maximum(Pm, 0.0)
    d = Pm.mean(axis=0) - b
    if len(d) < SHRINK_MIN:
        return bench_now, 0.0
    age = np.arange(len(d))[::-1]
    w = credibility_weight(d, y - b, None if delta is None else delta ** age)
    return bench_now + w * (raw - bench_now), w


def dmspe(P: list[np.ndarray], y: np.ndarray, ok: np.ndarray, delta: float = 0.9 ** (1 / 12), min_known: int = 24) -> np.ndarray:
    """Stock and Watson's discounted-MSPE combination: each model's weight is inversely proportional to its
    discounted sum of squared errors on outcomes already known at the forecast date (H months back), so the weights
    use no future information. Equal weights until 24 errors are known."""
    P = np.vstack(P)
    n = P.shape[1]
    out = np.full(n, np.nan)
    pos = np.where(ok)[0]
    for a, i in enumerate(pos):
        known = [j for j in pos[:a] if j <= i - H - 1]
        col = P[:, i]
        if len(known) < min_known:
            out[i] = np.nanmean(col)
            continue
        kj = np.array(known)
        w_t = delta ** (i - 1 - kj)
        e2 = ((P[:, kj] - y[kj]) ** 2 * w_t).sum(axis=1)
        w = 1 / np.maximum(e2, 1e-12)
        good = ~np.isnan(col)
        out[i] = float((w[good] * col[good]).sum() / w[good].sum()) if good.any() else np.nan
    return out


def _loss(y, p, task):
    if task == "return":
        return float(np.mean((y - p) ** 2))
    return float(np.mean((y - p) ** 2))


def nw_var(d: np.ndarray, lags: int) -> float:
    d = d - d.mean()
    n = len(d)
    v = float(d @ d) / n
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        v += 2 * w * float(d[L:] @ d[:-L]) / n
    return max(v, 1e-18) / n


def diebold_mariano(e_model: np.ndarray, e_bench: np.ndarray, lags: int = H) -> dict:
    """Is the model's squared error lower than the benchmark's, with Newey-West errors for the 12-month overlap?"""
    from scipy import stats
    d = e_bench ** 2 - e_model ** 2
    se = math.sqrt(nw_var(d, lags))
    t = float(d.mean() / se) if se > 0 else 0.0
    return {"mean_gain": float(d.mean()), "t": t, "p_one_sided": float(1 - stats.norm.cdf(t))}


def score(W: dict) -> dict:
    """Out-of-sample scores against the benchmark, overall, by era and by regime."""
    y = np.array(W["y"])
    b = np.array(W["bench"])
    dates = pd.to_datetime(W["dates"])
    out = {}
    for k, p in W["preds"].items():
        p = np.array(p)
        sse_m, sse_b = float(np.sum((y - p) ** 2)), float(np.sum((y - b) ** 2))
        row = {"skill": 1 - sse_m / sse_b if sse_b > 0 else 0.0, "dm": diebold_mariano(y - p, y - b)}
        if W["task"] == "return":
            row["hit"] = float(np.mean(np.sign(p - b) == np.sign(y - b)))
        else:
            row["auc"] = _auc(y, p)
            row["brier"] = float(np.mean((y - p) ** 2))
            row["brier_bench"] = float(np.mean((y - b) ** 2))
        eras = {}
        for lab, a, z in (("1940 to 1969", 1940, 1969), ("1970 to 1999", 1970, 1999), ("2000 on", 2000, 2100)):
            m = (dates.year >= a) & (dates.year <= z)
            if m.sum() > 24:
                eb, em = float(np.sum((y[m] - b[m]) ** 2)), float(np.sum((y[m] - p[m]) ** 2))
                eras[lab] = 1 - em / eb if eb > 0 else 0.0
        row["eras"] = eras
        out[k] = row
    return out


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order))
    ranks[order] = np.arange(1, len(order) + 1)
    allv = np.concatenate([pos, neg])
    for v in np.unique(allv):                      # average ranks for ties
        m = allv == v
        ranks[m] = ranks[m].mean()
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


# ---------------------------------------------------------------- v0.25 trials, every variant scored the same way
def ece(p: np.ndarray, y: np.ndarray, bins=(0, 0.1, 0.2, 0.35, 1.01)) -> float:
    """Expected calibration error over the calibration table's bins: the share-weighted gap between forecast and outcome."""
    e = 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p >= lo) & (p < hi)
        if m.any():
            e += float(m.mean()) * abs(float(p[m].mean()) - float(y[m].mean()))
    return e


def qra_interval(p: np.ndarray, y: np.ndarray, F: np.ndarray, level: float = 0.8, window: int = 360, min_known: int = SHRINK_MIN, refit: int = REFIT) -> tuple[np.ndarray, np.ndarray]:
    """Quantile regression averaging (Nowotarski and Weron 2015) for the interval around p: the lower and upper
    quantiles of the forecast error regressed on the member forecasts F (columns; none for an intercept only), fit
    every `refit` rows on the last `window` errors already known."""
    from scipy.optimize import linprog
    a = (1 - level) / 2
    n = len(y)
    lo, hi = np.full(n, np.nan), np.full(n, np.nan)
    cur = None

    def qreg(X, v, tau):
        m, k = X.shape
        c = np.concatenate([np.zeros(k), tau * np.ones(m), (1 - tau) * np.ones(m)])
        res = linprog(c, A_eq=np.hstack([X, np.eye(m), -np.eye(m)]), b_eq=v, bounds=[(None, None)] * k + [(0, None)] * (2 * m), method="highs")
        return res.x[:k]
    for i in range(n):
        k = i - H - 1
        if k + 1 < min_known:
            continue
        if cur is None or i % refit == 0:
            j0 = max(0, k + 1 - window)
            X = np.column_stack([np.ones(k + 1 - j0), F[j0:k + 1]])
            e = y[j0:k + 1] - p[j0:k + 1]
            cur = (qreg(X, e, a), qreg(X, e, 1 - a))
        x = np.concatenate([[1.0], F[i]])
        lo[i], hi[i] = p[i] + x @ cur[0], p[i] + x @ cur[1]
    return lo, hi


def conformal_path(p: np.ndarray, y: np.ndarray, level: float = 0.8, window: int = 360, min_known: int = SHRINK_MIN) -> tuple[np.ndarray, np.ndarray]:
    """The symmetric conformal interval each row would have had, from the last `window` known absolute errors."""
    e = np.abs(y - p)
    lo, hi = np.full(len(y), np.nan), np.full(len(y), np.nan)
    for i in range(len(y)):
        k = i - H - 1
        if k + 1 >= min_known:
            q = float(np.quantile(e[max(0, k + 1 - window):k + 1], level))
            lo[i], hi[i] = p[i] - q, p[i] + q
    return lo, hi


def winkler(lo: np.ndarray, hi: np.ndarray, y: np.ndarray, level: float = 0.8) -> np.ndarray:
    a = 1 - level
    return (hi - lo) + (2 / a) * np.maximum(lo - y, 0) + (2 / a) * np.maximum(y - hi, 0)


def v25_trials(W: dict, task: str, adopted: str = COMBINE) -> list[dict]:
    """Every v0.25 variant, scored on the same walked-forward months: skill against the benchmark before (the v0.24
    equal-weight ensemble, or the named model) and after, the Diebold-Mariano t of after against before, and
    calibration (interval coverage for returns, expected calibration error and AUC for crashes)."""
    y, b = np.array(W["y"]), np.array(W["bench"])
    P = {k: np.array(v) for k, v in W["preds"].items()}
    mem = W["members"]
    ok = np.ones(len(y), bool)
    v24 = P["ensemble_v24"]
    D_ = SHRINK_DELTA
    sk = lambda p: 1 - float(np.sum((y - p) ** 2)) / float(np.sum((y - b) ** 2))
    rows = []

    def add(name, p, before=v24, before_name="v24 ensemble", is_adopted=False, extra=None):
        row = {"variant": name, "metric": "skill against the " + ("historical mean" if task == "return" else "base rate") + f" (before: {before_name})",
               "before": sk(before), "after": sk(p), "t": diebold_mariano(y - p, y - before)["t"], "t_vs_benchmark": diebold_mariano(y - p, y - b)["t"],
               "adopted": is_adopted}
        if task == "return":
            row["coverage80"] = {"before": conformal(y - before)["coverage"], "after": conformal(y - p)["coverage"]}
        else:
            row["ece"] = {"before": ece(before, y), "after": ece(p, y)}
            row["auc"] = {"before": _auc(y, before), "after": _auc(y, p)}
        rows.append(row | (extra or {}))
    Pm = np.vstack([P[k] for k in mem])
    if task == "return":
        fl = _mean_rows(np.maximum(Pm, 0.0))
        add("shrink toward the mean, expanding weight", credibility(v24, b, y, ok, None)[0])
        add("shrink toward the mean, discounted weight", credibility(v24, b, y, ok, D_)[0])
        add("truncate the ensemble at zero", np.maximum(v24, 0.0))
        add("shrink (expanding) then truncate", np.maximum(credibility(v24, b, y, ok, None)[0], 0.0))
        add("truncate each member at zero, then average", fl)
        if "combo" in P:
            add("shrink the restricted combination", credibility(P["combo"], b, y, ok, None)[0], P["combo"], "restricted combination")
        add("shrink the accuracy-weighted ensemble", credibility(P["dmspe"], b, y, ok, None)[0])
        add("shrink each member (expanding), then average", _mean_rows(np.vstack([credibility(p, b, y, ok, None)[0] for p in Pm])))
        add("truncate members, average, shrink (expanding)", credibility(fl, b, y, ok, None)[0])
        add("truncate members, average, shrink (discounted)", credibility(fl, b, y, ok, D_)[0], is_adopted=adopted in ("v25", "floor_shrink"))
        add("shrink (discounted) then truncate", np.maximum(credibility(v24, b, y, ok, D_)[0], 0.0))
        # intervals around the adopted forecast: quantile regression averaging against the conformal interval
        p = P["ensemble"]
        l0, h0 = conformal_path(p, y)
        for name, F in (("quantile regression averaging on the members", Pm.T), ("quantile regression, intercept only", np.zeros((len(y), 0)))):
            l1, h1 = qra_interval(p, y, F)
            m = np.isfinite(l0) & np.isfinite(l1)
            w0, w1 = winkler(l0, h0, y)[m], winkler(l1, h1, y)[m]
            d = w0 - w1
            rows.append({"variant": name, "metric": "80% interval score (Winkler, lower is better; before: conformal)", "before": float(w0.mean()), "after": float(w1.mean()),
                         "t": float(d.mean() / math.sqrt(nw_var(d, H))), "adopted": False,
                         "coverage80": {"before": float(np.mean((y[m] >= l0[m]) & (y[m] <= h0[m]))), "after": float(np.mean((y[m] >= l1[m]) & (y[m] <= h1[m])))}})
    else:
        add("Platt scaling of the ensemble", platt(v24, y, ok, b))
        add("isotonic calibration of the ensemble", isotonic(v24, y, ok, b))
        add("shrink toward the base rate, expanding weight", credibility(v24, b, y, ok, None)[0])
        add("shrink toward the base rate, discounted weight", credibility(v24, b, y, ok, D_)[0], is_adopted=adopted in ("v25", "shrink"))
        if "logit" in P:
            add("Platt scaling of the logistic regression", platt(P["logit"], y, ok, b))
            add("shrink the logistic regression (expanding)", credibility(P["logit"], b, y, ok, None)[0])
        add("Platt-scale each member, then average", _mean_rows(np.vstack([platt(p, y, ok, b) for p in Pm])))
    return rows


# ---------------------------------------------------------------- combinatorial purged CV and overfitting
def cpcv(D: pd.DataFrame, task: str, groups: int = 8, k: int = 2) -> dict:
    """Every way of holding out k of `groups` time blocks; training rows within H + embargo months of a test block are
    purged. For each split: each configuration's in-sample and out-of-sample skill against the training mean. PBO is
    the share of splits in which the configuration that looked best in sample ranked below the median out of sample."""
    ycol = "y_ret" if task == "return" else "y_crash"
    D = D.dropna(subset=FEATURES + [ycol])
    D = D[D.index.year >= 1890]
    n = len(D)
    edges = np.linspace(0, n, groups + 1).astype(int)
    blocks = [np.arange(edges[i], edges[i + 1]) for i in range(groups)]
    M = models(task)
    configs = dict(M)
    configs["mean"] = ("Historical mean", None, [])
    names = list(configs)
    rows = []
    y = D[ycol].to_numpy()
    for test in combinations(range(groups), k):
        te = np.concatenate([blocks[g] for g in test])
        ban = set()
        for g in test:
            lo, hi = blocks[g][0] - H - EMBARGO, blocks[g][-1] + H + EMBARGO
            ban.update(range(max(0, lo), min(n, hi + 1)))
        tr = np.array([i for i in range(n) if i not in ban])
        ytr, yte = y[tr], y[te]
        mu = ytr.mean()
        sse_b_te, sse_b_tr = float(np.sum((yte - mu) ** 2)), float(np.sum((ytr - mu) ** 2))
        ins, oos = {}, {}
        for nm in names:
            _, make, feats = configs[nm]
            if make is None:
                ins[nm], oos[nm] = 0.0, 1 - sse_b_te / sse_b_te
                continue
            p_te, m = _fit_predict(make, feats, D.iloc[tr], ytr, D.iloc[te], task)
            p_tr = m.predict(D.iloc[tr][feats].to_numpy()) if task == "return" else m.predict_proba(D.iloc[tr][feats].to_numpy())[:, 1]
            ins[nm] = 1 - float(np.sum((ytr - p_tr) ** 2)) / sse_b_tr
            oos[nm] = 1 - float(np.sum((yte - p_te) ** 2)) / sse_b_te
        rows.append({"test": list(test), "in": ins, "out": oos})
    below = 0
    for r in rows:
        best = max(names, key=lambda c: (r["in"][c], c))
        rank = sorted(names, key=lambda c: r["out"][c]).index(best)       # 0 = worst
        if rank < (len(names) - 1) / 2:
            below += 1
    oos_mean = {c: float(np.mean([r["out"][c] for r in rows])) for c in names}
    ins_mean = {c: float(np.mean([r["in"][c] for r in rows])) for c in names}
    beats = {c: float(np.mean([r["out"][c] > 0 for r in rows])) for c in names}
    return {"splits": len(rows), "groups": groups, "k": k, "pbo": below / len(rows), "oos_mean": oos_mean, "in_mean": ins_mean,
            "share_beating_mean": beats, "names": names}


# ---------------------------------------------------------------- today: forecast, interval, analogs, distance
def conformal(errors: np.ndarray, level: float = 0.8, window: int = 360) -> dict:
    """Split-conformal interval from the last `window` out-of-sample absolute errors, and how often past intervals of
    that width (each built only from errors known at the time) actually covered."""
    e = np.abs(errors)
    q_now = float(np.quantile(e[-window:], level))
    hits = []
    for t in range(120 + H, len(e)):
        past = e[max(0, t - H - window):t - H]             # only errors whose outcome was known
        if len(past) < 60:
            continue
        hits.append(e[t] <= np.quantile(past, level))
    return {"halfwidth": q_now, "level": level, "coverage": float(np.mean(hits)) if hits else None, "n": len(hits)}


def analogs(D: pd.DataFrame, row: pd.Series, k: int = 8, gap: int = 18) -> list[dict]:
    """The k historical months closest to today in standardized feature space (no two within `gap` months), with what
    the next 12 months brought."""
    H_ = D.dropna(subset=FEATURES)
    mu, sd = H_[FEATURES].mean(), H_[FEATURES].std()
    Z = (H_[FEATURES] - mu) / sd
    z0 = (row[FEATURES] - mu) / sd
    d = np.sqrt(((Z - z0) ** 2).sum(axis=1))
    d = d[d.index <= H_.index[-1] - pd.DateOffset(months=24)]
    picked = []
    for dt in d.sort_values().index:
        if all(abs((dt - p).days) > gap * 30.5 for p in picked):
            picked.append(dt)
        if len(picked) == k:
            break
    out = []
    for dt in picked:
        r = H_.loc[dt]
        out.append({"date": dt.strftime("%Y-%m"), "distance": float(d[dt]), "next12": None if not np.isfinite(r["y_ret"]) else float(math.expm1(r["y_ret"])),
                    "crash": None if not np.isfinite(r["y_crash"]) else bool(r["y_crash"]), "cape": float(math.exp(r["log_cape"]))})
    return out


def shift(D: pd.DataFrame, row: pd.Series, k: int = 24, gap: int = 24) -> dict:
    """Is today outside what the models learned from? Novelty: the distance from today to its k-th nearest historical
    month (standardized features, ignoring the last `gap` months), ranked against the same distance for every
    historical month (whose neighbours exclude its own `gap`-month window). Above the 90th percentile means the models
    are extrapolating. Also each feature's position in its own history."""
    H_ = D.dropna(subset=FEATURES)
    X = ((H_[FEATURES] - H_[FEATURES].mean()) / H_[FEATURES].std()).to_numpy()
    z0 = ((row[FEATURES] - H_[FEATURES].mean()) / H_[FEATURES].std()).to_numpy(float)
    n = len(X)
    pos = np.arange(n)
    hist = np.empty(n)
    for i in range(n):
        d = np.sqrt(((X - X[i]) ** 2).sum(axis=1))
        d = d[np.abs(pos - i) > gap]
        hist[i] = np.partition(d, k - 1)[k - 1]
    d0 = np.sqrt(((X[:-gap] - z0) ** 2).sum(axis=1))
    nov = float(np.partition(d0, k - 1)[k - 1])
    feats = {}
    for f in FEATURES:
        x = H_[f].to_numpy()
        v = float(row[f])
        feats[f] = {"value": v, "pct": float(np.mean(x < v)), "z": float((v - x.mean()) / x.std()), "outside": bool(v > x.max() or v < x.min())}
    return {"novelty": nov, "novelty_pct": float(np.mean(hist < nov)), "k": k, "features": feats, "typical": float(np.median(hist))}


@cache.memo("ml.build", deps=("buildout.labs",), require=("dl",))
def build(dl: dict | None = None, cape_now: float | None = None, y10_now: float | None = None, quick: bool = False) -> dict:
    dl = dl or labs.download()
    S = labs.shiller(dl)
    D = panel(S)
    out = {"schema": 1, "features": {f: NAMES[f] for f in FEATURES}, "horizon": H, "embargo": EMBARGO, "start_oos": START_OOS, "crash_threshold": CRASH}
    row, notes = today_row(D, S, cape_now, y10_now)
    out["today"] = {"notes": notes, "features": {f: float(row[f]) for f in FEATURES}}
    for task in ("return", "crash"):
        W = walk_forward(D, task, refit=24 if quick else REFIT, permute=not quick)
        sc = score(W)
        M = models(task)
        ycol = "y_ret" if task == "return" else "y_crash"
        Dt = D.dropna(subset=FEATURES + [ycol])
        cut = len(Dt) - 1
        now = {}
        for k2, (_, make, feats) in M.items():
            p, _ = _fit_predict(make, feats, Dt.iloc[:cut + 1], Dt[ycol].to_numpy(), row.to_frame().T.astype(float), task)
            now[k2] = float(p[0])
        ks = [k2 for k2 in M if k2 != "cape_ols"]
        bench_now = float(Dt[ycol].mean())
        now["ensemble_v24"] = float(np.mean([now[k2] for k2 in ks]))
        now["ensemble"], w_now = combine_now([now[k2] for k2 in ks], bench_now, W, task)
        yy = np.array(W["y"])
        age = np.arange(len(yy))[::-1]
        wts = {k2: 1 / max(float((((np.array(W["preds"][k2]) - yy) ** 2) * (0.9 ** (1 / 12)) ** age)[~np.isnan(W["preds"][k2])].sum()), 1e-12) for k2 in ks}
        now["dmspe"] = float(sum(wts[k2] * now[k2] for k2 in ks) / sum(wts.values()))
        now["benchmark"] = bench_now
        ens_label = {"return": "Ensemble, members truncated at zero and shrunk toward the mean", "crash": "Ensemble, shrunk toward the base rate"}[task] if COMBINE == "v25" else "Equal-weight ensemble"
        res = {"labels": {k2: M[k2][0] for k2 in M} | {"ensemble": ens_label, "ensemble_v24": "Equal-weight ensemble (v0.24)", "dmspe": "Accuracy-weighted ensemble"},
               "scores": sc, "now": now, "n_oos": W["n"], "refits": W["refits"], "combine": COMBINE,
               "shrink": {"weight_now": w_now, "delta": SHRINK_DELTA, "min_known": SHRINK_MIN,
                          "weight_mean": None if W["shrink_weight"] is None else float(np.mean(W["shrink_weight"])),
                          "weight_series": None if W["shrink_weight"] is None else [round(v, 3) for v in W["shrink_weight"][::3]]},
               "importance": W["importance"], "series": {"dates": W["dates"][::3], "y": [round(v, 4) for v in W["y"][::3]], "bench": [round(v, 4) for v in W["bench"][::3]],
                                                          "ensemble": [round(v, 4) for v in W["preds"]["ensemble"][::3]]}}
        if task == "return":
            res["interval"] = conformal(np.array(W["y"]) - np.array(W["preds"]["ensemble"]))
        else:
            y = np.array(W["y"])
            p = np.array(W["preds"]["ensemble"])
            bins = []
            for lo, hi in ((0, 0.1), (0.1, 0.2), (0.2, 0.35), (0.35, 1.01)):
                m = (p >= lo) & (p < hi)
                if m.sum() >= 12:
                    bins.append({"lo": lo, "hi": hi, "n": int(m.sum()), "forecast": float(p[m].mean()), "realized": float(y[m].mean())})
            res["calibration"] = bins
        res["cpcv"] = cpcv(D, task, groups=6 if quick else 8)
        res["v25_trials"] = v25_trials(W, task)
        out[task] = res
    out["v25_trials"] = [t | {"task": task} for task in ("return", "crash") for t in out[task]["v25_trials"]]
    out["analogs"] = analogs(D, row)
    out["shift"] = shift(D, row)
    out["findings"] = summary(out)
    return out


def summary(o: dict) -> list[str]:
    r, c = o["return"], o["crash"]
    sk = r["scores"]
    best = max((k for k in sk if k not in ("ensemble", "ensemble_v24", "dmspe")), key=lambda k: sk[k]["skill"])
    f = [f"Twelve-month real return, judged out of sample from {o['start_oos']} with purged walk-forward refits: the ensemble's skill against the historical mean is "
         f"{sk['ensemble']['skill']:+.1%} (Diebold-Mariano t {sk['ensemble']['dm']['t']:.1f}); the best single model is {r['labels'][best].lower()} at {sk[best]['skill']:+.1%}. "
         f"Across {r['cpcv']['splits']} combinatorial purged splits the chance that picking the in-sample winner misleads is {r['cpcv']['pbo']:.0%}."]
    if "ensemble_v24" in sk and r.get("combine") == "v25":
        n_r = sum(1 for t in r.get("v25_trials", []) if t["metric"].startswith("skill"))
        n_c = sum(1 for t in c.get("v25_trials", []) if t["metric"].startswith("skill"))
        f.append(f"Since v0.25 the ensemble truncates each member's forecast at zero and shrinks the average toward the historical mean with a weight learned "
                 f"only from forecasts whose outcome was known (today {r['shrink']['weight_now']:.2f}, average {r['shrink']['weight_mean']:.2f}); the equal-weight v0.24 "
                 f"ensemble scored {sk['ensemble_v24']['skill']:+.1%}. The crash ensemble is shrunk toward the base rate the same way "
                 f"(Brier skill {c['scores']['ensemble']['skill']:+.1%} against {c['scores']['ensemble_v24']['skill']:+.1%}). Each was chosen from the variants tried ({n_r} for returns, "
                 f"{n_c} for crashes), so the margins are smaller than their t statistics suggest.")
    ens = r["now"]["ensemble"]
    f.append(f"Today the ensemble expects {math.expm1(ens):+.1%} real over the next year against a historical {math.expm1(r['now']['benchmark']):+.1%}, "
             f"with an 80% conformal interval of plus or minus {r['interval']['halfwidth']:.0%} in log terms (past intervals covered {r['interval']['coverage']:.0%}).")
    cs = c["scores"]["ensemble"]
    f.append(f"A fall of 15% or more within a year: the ensemble puts it at {c['now']['ensemble']:.0%} against a base rate of {c['now']['benchmark']:.0%}; "
             f"its Brier skill out of sample is {cs['skill']:+.1%} and AUC {cs['auc']:.2f}.")
    sh = o["shift"]
    out_feats = [o["features"][k] for k, v in sh["features"].items() if v["outside"] or abs(v["z"]) > 2.5]
    f.append(f"Is today familiar? Its {sh['k']} nearest historical months are further away than they are for {sh['novelty_pct']:.0%} of months in the record"
             + (f"; {', '.join(x.lower() for x in out_feats)} at an extreme." if out_feats else ".") + (" The models are extrapolating." if sh["novelty_pct"] > 0.9 else ""))
    return f
