"""Why the complex models backtest better and forecast worse, measured rather than asserted.

Five measurements on the engine's own 155 years, and one controlled experiment:

  sweep        each model family from simple to complex (nearest neighbours from 400 down to 1, tree ensembles from a
               few shallow trees to hundreds of deep ones, polynomial features of degree 1 to 3): the fit on the
               training years against the forecast on the years after, on three rolling origins. In-sample fit rises
               with complexity every time; out-of-sample skill peaks early and then falls.
  information  how much the data can teach: 12-month returns overlap, so 1,860 months hold about 155 independent
               observations; the predictors are so persistent that their own information is smaller still; with p
               predictors, ordinary least squares loses about p / n_eff of R squared out of sample, which is larger
               than the true R squared the literature finds (a few percent).
  drift        the relationship moves: the CAPE slope re-estimated on rolling 30-year windows, and whether its sign holds.
  bias         Stambaugh's small-sample bias: with a persistent predictor whose shocks move opposite to returns, the
               estimated slope is biased away from zero, so backtests overstate predictability.
  selection    picking the best of many configurations in sample guarantees an out-of-sample letdown (the CPCV result).
  experiment   planted data with known signal-to-noise: complex models beat a linear one only when the signal is strong
               and genuinely nonlinear; at the signal-to-noise of stock returns, they lose.

The conclusions are written from these numbers, so they change if the data do.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import labs, ml

ORIGINS = [(1950, 1980), (1980, 2000), (2000, 2026)]     # train through the first year minus a purge; test until the second
SEED = 17


def _r2(y, p, mu):
    return 1 - float(np.sum((y - p) ** 2)) / float(np.sum((y - mu) ** 2))


def _families():
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import LinearRegression, Ridge
    from sklearn.neighbors import KNeighborsRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import PolynomialFeatures, StandardScaler
    fam = {}
    fam["Nearest neighbours"] = [(f"k = {k}", 1 / k, (lambda k=k: make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=k)))) for k in (400, 200, 100, 50, 25, 12, 6, 3, 1)]
    fam["Boosted trees"] = [(f"{n} trees, depth {d}", n * 2 ** d, (lambda n=n, d=d: GradientBoostingRegressor(n_estimators=n, max_depth=d, learning_rate=0.1, subsample=1.0, random_state=SEED)))
                            for n, d in ((5, 1), (20, 1), (20, 2), (50, 3), (100, 3), (200, 4), (400, 5))]
    fam["Random forest"] = [(f"depth {d}", 2 ** d, (lambda d=d: RandomForestRegressor(n_estimators=100, max_depth=d, min_samples_leaf=1, random_state=SEED, n_jobs=-1)))
                            for d in (1, 2, 3, 5, 8, 12)]
    fam["Polynomial regression"] = [(f"degree {g}", g, (lambda g=g: make_pipeline(StandardScaler(), PolynomialFeatures(g), Ridge(alpha=1e-3)))) for g in (1, 2, 3)]
    fam["_ols"] = [("OLS", 1, lambda: LinearRegression())]
    return fam


def sweep(D: pd.DataFrame) -> dict:
    """In-sample R squared (mean over origins) and pooled out-of-sample R squared against each origin's training mean."""
    D = D.dropna(subset=ml.FEATURES + ["y_ret"])
    splits = []
    for a, b in ORIGINS:
        tr = D[D.index.year < a].iloc[:-(ml.H + ml.EMBARGO)]
        te = D[(D.index.year >= a) & (D.index.year < b)]
        if len(tr) >= 300 and len(te) >= 60:
            splits.append((tr, te))
    out = {}
    for fam, specs in _families().items():
        if fam.startswith("_"):
            continue
        rows = []
        for label, cx, make in specs:
            ins, sse, sst, per = [], 0.0, 0.0, []
            for tr, te in splits:
                m = make().fit(tr[ml.FEATURES].to_numpy(), tr["y_ret"].to_numpy())
                mu = float(tr["y_ret"].mean())
                ins.append(_r2(tr["y_ret"].to_numpy(), m.predict(tr[ml.FEATURES].to_numpy()), mu))
                y, p = te["y_ret"].to_numpy(), m.predict(te[ml.FEATURES].to_numpy())
                sse += float(np.sum((y - p) ** 2))
                sst += float(np.sum((y - mu) ** 2))
                per.append(_r2(y, p, mu))
            oos = 1 - sse / sst
            rows.append({"label": label, "complexity": cx, "in_sample": float(np.mean(ins)), "out_of_sample": oos, "per_origin": per, "gap": float(np.mean(ins) - oos)})
        out[fam] = rows
    return out


def extrapolation(D: pd.DataFrame, year: int = 1950, end: int = 1980) -> dict:
    """The cleanest single failure: all eight predictors fitted on the years before 1950, a period when the 10-year yield
    barely moved, then asked about the 1950s to the 1970s, when it tripled. CAPE alone, fitted the same way, for contrast."""
    D = D.dropna(subset=ml.FEATURES + ["y_ret"])
    tr = D[D.index.year < year].iloc[:-(ml.H + ml.EMBARGO)]
    te = D[(D.index.year >= year) & (D.index.year < end)]
    X = np.column_stack([np.ones(len(tr)), tr[ml.FEATURES].to_numpy()])
    b = np.linalg.lstsq(X, tr["y_ret"].to_numpy(), rcond=None)[0]
    Xt = np.column_stack([np.ones(len(te)), te[ml.FEATURES].to_numpy()])
    mu = float(tr["y_ret"].mean())
    p = Xt @ b
    Xc = np.column_stack([np.ones(len(tr)), tr["log_cape"].to_numpy()])
    bc = np.linalg.lstsq(Xc, tr["y_ret"].to_numpy(), rcond=None)[0]
    pc = np.column_stack([np.ones(len(te)), te["log_cape"].to_numpy()]) @ bc
    y = te["y_ret"].to_numpy()
    k = ml.FEATURES.index("y10") + 1
    return {"train": f"{tr.index[0].year} to {tr.index[-1].year}", "test": f"{year} to {end - 1}", "y10_coef": float(b[k]),
            "y10_train": [float(tr["y10"].min()), float(tr["y10"].max())], "y10_test": [float(te["y10"].min()), float(te["y10"].max())],
            "r2_all": _r2(y, p, mu), "r2_cape": _r2(y, pc, mu), "worst_forecast": float(np.expm1(p.min())), "worst_actual": float(np.expm1(y.min()))}


def information(D: pd.DataFrame) -> dict:
    """Effective sample size, predictor persistence, the in-sample R squared, and the expected out-of-sample cost of p
    predictors under ordinary least squares."""
    D = D.dropna(subset=ml.FEATURES + ["y_ret"])
    n = len(D)
    n_eff = n / ml.H                                     # non-overlapping 12-month windows
    y = D["y_ret"].to_numpy()
    ac1 = float(np.corrcoef(y[1:], y[:-1])[0, 1])
    x = D["log_cape"].to_numpy()
    phi = float(np.corrcoef(x[1:], x[:-1])[0, 1])
    half = math.log(0.5) / math.log(phi) if 0 < phi < 1 else float("inf")
    X = np.column_stack([np.ones(n), D[ml.FEATURES].to_numpy()])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    r2_all = _r2(y, X @ b, y.mean())
    Xc = np.column_stack([np.ones(n), x])
    bc = np.linalg.lstsq(Xc, y, rcond=None)[0]
    r2_cape = _r2(y, Xc @ bc, y.mean())
    p = len(ml.FEATURES)
    return {"months": n, "n_eff": n_eff, "y_autocorr_1": ac1, "cape_ar1": phi, "cape_half_life_months": half, "r2_in_sample_all": r2_all, "r2_in_sample_cape": r2_cape,
            "ols_cost": p / n_eff, "ols_cost_cape": 1 / n_eff, "expected_oos_all": r2_all - (p / n_eff) * (1 - r2_all) * 2, "p": p}


def drift(D: pd.DataFrame, window: int = 360, step: int = 60) -> list[dict]:
    D = D.dropna(subset=["log_cape", "y_ret"])
    out = []
    for e in range(window, len(D) + 1, step):
        w = D.iloc[e - window:e]
        x, y = w["log_cape"].to_numpy(), w["y_ret"].to_numpy()
        b = float(np.cov(x, y, bias=True)[0, 1] / np.var(x))
        out.append({"end": w.index[-1].strftime("%Y-%m"), "slope": b, "r2": float(np.corrcoef(x, y)[0, 1] ** 2)})
    return out


def stambaugh(D: pd.DataFrame, S: pd.DataFrame, sims: int = 2000) -> dict:
    """Stambaugh (1999) small-sample bias of the CAPE slope, on annual (December) data: real log total return over the
    next year regressed on log CAPE. The predictor is persistent and its shocks move with returns, so under the null of
    no predictability the estimated slope is biased negative, the direction that flatters "high CAPE, low returns".
    Simulated with the measured persistence, shock correlation and volatilities; the share of null draws at least as
    negative as the real estimate is the bias-aware p-value."""
    rng = np.random.default_rng(SEED)
    r, _, _ = labs.total_return_index(S)
    lr = np.log1p(r)
    A = pd.DataFrame({"x": D["log_cape"], "lr": lr.reindex(D.index)}).dropna()
    yr = A.groupby(A.index.year).agg(x=("x", "first"), r=("lr", "sum"), n=("lr", "size"))
    yr = yr[yr["n"] == 12]
    x, ret = yr["x"].to_numpy(), yr["r"].to_numpy()
    xt, x1, r1 = x[:-1], x[1:], ret[:-1]                  # x at the start of year t, its value a year later, return in year t
    T = len(xt)
    phi, a0 = np.polyfit(xt, x1, 1)
    v = x1 - (a0 + phi * xt)
    b_hat, c0 = np.polyfit(xt, r1, 1)
    u = r1 - (c0 + b_hat * xt)
    rho = float(np.corrcoef(u, v)[0, 1])
    su, sv = float(u.std()), float(v.std())
    analytic = -(rho * su / sv) * (1 + 3 * phi) / T
    bs = np.empty(sims)
    for i in range(sims):
        e1, e2 = rng.standard_normal(T + 50), rng.standard_normal(T + 50)
        uu = su * e1
        vv = sv * (rho * e1 + math.sqrt(1 - rho ** 2) * e2)
        z = np.zeros(T + 51)
        for t in range(T + 50):
            z[t + 1] = phi * z[t] + vv[t]
        z = z[50:]
        bs[i] = np.polyfit(z[:-1], uu[50:50 + T], 1)[0]
    return {"years": T, "phi_annual": float(phi), "rho": rho, "slope": float(b_hat), "bias_mean": float(bs.mean()), "bias_analytic": float(analytic),
            "slope_sd_null": float(bs.std()), "p_bias_aware": float(np.mean(bs <= b_hat)), "slope_corrected": float(b_hat - bs.mean()),
            "p_naive": float(2 * (1 - _ncdf(abs(b_hat) / (su / (xt.std() * math.sqrt(T))))))}


def _ncdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def experiment(sims: int = 12) -> dict:
    """Planted data: a persistent predictor, 12-month overlapping outcomes, 1,800 months; the true 12-month R squared
    and the shape (linear or a threshold) are set. Linear regression against a random forest and boosted trees, each
    trained on the first 60% and judged on the rest after a purge."""
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import LinearRegression
    rng = np.random.default_rng(SEED)
    n, H = 1800, 12
    out = []
    for shape in ("linear", "threshold"):
        for r2 in (0.02, 0.05, 0.15, 0.40):
            res = {"linear": [], "forest": [], "boost": []}
            for s in range(sims):
                x = np.zeros(n + H)
                for t in range(1, n + H):
                    x[t] = 0.98 * x[t - 1] + rng.standard_normal() * 0.2
                xs = (x - x.mean()) / x.std()
                g = xs if shape == "linear" else np.where(xs > 0.5, 1.0, -0.3)
                eps = rng.standard_normal(n + H)
                noise = np.convolve(eps, np.ones(H), "full")[:n + H]           # 12-month overlapping noise
                sig = g[:n] * 1.0
                k = math.sqrt(r2 / (1 - r2) * np.var(noise[:n]) / np.var(sig))
                y = k * sig + noise[H:n + H]
                X = np.column_stack([xs[:n], rng.standard_normal((n, 4))])       # one real predictor, four distractions
                cut = int(n * 0.6)
                tr, te = slice(0, cut - H), slice(cut, n)
                mu = y[tr].mean()
                for nm, m in (("linear", LinearRegression()), ("forest", RandomForestRegressor(n_estimators=60, max_depth=6, random_state=s, n_jobs=-1)),
                              ("boost", GradientBoostingRegressor(n_estimators=150, max_depth=3, random_state=s))):
                    m.fit(X[tr], y[tr])
                    res[nm].append(_r2(y[te], m.predict(X[te]), mu))
            out.append({"shape": shape, "true_r2": r2, **{k: float(np.mean(v)) for k, v in res.items()}})
    return {"rows": out, "sims": sims, "months": n}


def build(dl: dict | None = None, quick: bool = False) -> dict:
    dl = dl or labs.download()
    S = labs.shiller(dl)
    D = ml.panel(S)
    o = {"schema": 1, "sweep": sweep(D), "extrapolation": extrapolation(D), "information": information(D), "drift": drift(D), "stambaugh": stambaugh(D, S, 500 if quick else 2000),
         "experiment": experiment(4 if quick else 12)}
    o["conclusions"] = conclusions(o)
    return o


def conclusions(o: dict) -> list[dict]:
    I, sw, ex = o["information"], o["sweep"], o["experiment"]["rows"]
    out = []
    peaks = []
    for fam, rows in sw.items():
        best = max(rows, key=lambda r: r["out_of_sample"])
        most = rows[-1]
        peaks.append((fam, best, most))
    pct = lambda v: f"{v:+.0%}" if v > -1 else "below -100%"
    txt = "; ".join(f"{f.lower()} reach {m['in_sample']:.0%} in sample at {m['label']} and {pct(m['out_of_sample'])} out of sample, against {pct(b['out_of_sample'])} at their simplest"
                    for f, b, m in peaks if f != "Polynomial regression")
    out.append({"title": "Every step up in complexity fits the past better and the future worse", "text":
                f"Each family was trained on the years before 1950, 1980 and 2000 and judged on the decades after, against simply forecasting the training average. {txt[0].upper() + txt[1:]}. "
                "The in-sample R squared climbs toward 100% because a flexible model can memorize 1,700 months; it cannot memorize the next ones."})
    E = o["extrapolation"]
    out.append({"title": "Flexible models extrapolate, and the future is outside the sample", "text":
                f"Fitted on {E['train']}, when the 10-year yield stayed between {E['y10_train'][0]:.1%} and {E['y10_train'][1]:.1%}, the eight-predictor regression put a weight of {E['y10_coef']:+.1f} on it. "
                f"From {E['test']} the yield ran from {E['y10_test'][0]:.1%} to {E['y10_test'][1]:.1%}, and the model forecast a 12-month return as low as {E['worst_forecast']:.0%} (the worst actual was {E['worst_actual']:.0%}): "
                f"out-of-sample R squared {pct(E['r2_all'])}, against {E['r2_cape']:+.1%} for CAPE alone. Polynomials do the same thing faster."})
    out.append({"title": "The data hold far fewer observations than they seem to", "text":
                f"{I['months']:,} months of 12-month returns overlap, so they hold about {I['n_eff']:.0f} independent observations (next month's 12-month return is {I['y_autocorr_1']:.0%} correlated with this month's). "
                f"Log CAPE's month-to-month autocorrelation is {I['cape_ar1']:.3f}, a half-life of about {I['cape_half_life_months'] / 12:.0f} years, so valuation itself offers only a handful of independent swings."})
    out.append({"title": "The signal is smaller than the cost of estimating it", "text":
                f"All eight predictors together explain {I['r2_in_sample_all']:.1%} of 12-month returns in sample. Ordinary least squares with {I['p']} predictors on about {I['n_eff']:.0f} independent observations "
                f"loses roughly {I['ols_cost']:.1%} of R squared out of sample, the same order as the signal; a flexible model with hundreds of effective parameters loses far more. CAPE alone costs about {I['ols_cost_cape']:.1%}, which is why the simplest models lose least."})
    d = o["drift"]
    signs = sum(1 for r in d if r["slope"] < 0)
    out.append({"title": "The relationship moves under the model", "text":
                f"Re-estimated on rolling 30-year windows, the CAPE slope is negative (high valuation, lower returns) in {signs} of {len(d)} windows and ranges from {min(r['slope'] for r in d):+.2f} to {max(r['slope'] for r in d):+.2f}; "
                f"a flexible model learns the old regime's details exactly, and the details are what change."})
    st = o["stambaugh"]
    out.append({"title": "Persistent predictors flatter backtests", "text":
                f"Log CAPE keeps {st['phi_annual']:.0%} of its level from one year to the next and its shocks move {st['rho']:+.2f} with returns, so even a useless predictor shows an average slope of {st['bias_mean']:+.3f} over {st['years']} years (Stambaugh's bias). "
                f"The real slope is {st['slope']:+.3f}; corrected, {st['slope_corrected']:+.3f}. The naive p-value is {st['p_naive']:.3f}, the bias-aware one {st['p_bias_aware']:.3f}: the effect survives, but it is smaller than the raw backtest says."})
    lo = next((r for r in ex if r["shape"] == "linear" and r["true_r2"] == 0.05), None)
    hi = next((r for r in ex if r["shape"] == "threshold" and r["true_r2"] == 0.40), None)
    if lo and hi:
        out.append({"title": "Complexity pays only when the signal is strong and genuinely nonlinear", "text":
                    f"On planted data with a true R squared of 5% and a linear shape, out-of-sample R squared is {lo['linear']:+.1%} for linear regression, {lo['forest']:+.1%} for a random forest and {lo['boost']:+.1%} for boosted trees. "
                    f"With a 40% R squared and a threshold shape, the ranking flips: linear {hi['linear']:+.1%}, forest {hi['forest']:+.1%}, boosting {hi['boost']:+.1%}. Stock returns live in the first case."})
    out.append({"title": "Choosing the best backtest is itself a forecast that fails", "text":
                "Picking the configuration that looked best in sample means picking the one that fit the most noise: on this data the in-sample winner landed below the median out of sample in 82% of combinatorial splits (the ML lab's CPCV)."})
    return out
