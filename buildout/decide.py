"""The decision engine: one pipeline from data to a sized, explained, falsifiable decision, judged out of sample.

    data        156 years of monthly US stocks (Shiller): real total return, the 10-year yield, a 10-year bond's real
                return built from it, valuation, inflation
    features    the machine-learning lab's eight features, each knowable when the decision is made
    models      12-month forecasts from the historical mean, ridge, a restricted combination of one-variable
                forecasts, and a deep ensemble of small neural networks; stacked with non-negative weights fit only on
                forecasts whose outcome was already known
    inference   a hidden Markov model of regimes (refit every five years, filtered, never smoothed); Bayesian online
                changepoint detection; a Kalman filter on the stock-bond relationship; each model's predictive
                density scored month by month and averaged by its recent predictive likelihood
    decision    the stock exposure (0 to 1.5x) that maximizes expected constant-relative-risk-aversion utility of next
                month's wealth under the averaged predictive mixture, inside an expected-shortfall budget; the hedge
                from a Bayesian selector by regime; checks from two reinforcement-learning agents

Everything a month's decision uses was knowable two months earlier (Shiller's prices are monthly averages, so the
engine acts a month late, as the trend and RL labs do). Risk aversion is not tuned: it is set once, from 1871 to 1939
data only, so that the unconditional answer is to hold 1x; every deviation from holding is then the evidence talking.
The whole engine is walked forward from 1940 with trading and borrowing costs and compared with holding, the trend
rule and the RL agents, with a deflated Sharpe for every configuration tried, and with each part removed in turn.

Today's decision comes with its distribution (draws over regimes, models and forecasts), the inputs that drive it
(leave one out), what would flip it, and the value of knowing the regime for certain.

This is a model-book research engine. It never places orders.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import infer, labs, ml, nn, rl
from .core import cache

START = 1940
LAG = 2                       # months between the last data used and the month acted on
REFIT_HMM = 60
REFIT_ML = 24
GRID = np.round(np.arange(0.0, 1.51, 0.05), 2)
ES_LIMIT = 0.12               # expected loss in the worst month in twenty, at most 12% of capital
COST, BORROW = rl.COST, rl.BORROW
N0 = 120                      # regime means are shrunk toward the long-run mean with 120 pseudo-months of prior
FORGET = 0.98                 # model averaging: a month's predictive score loses 2% of its weight each month
SEED = 19
HEDGES = {"stocks": (1.0, 0.0, 0.0), "bonds": (0.7, 0.3, 0.0), "cash": (0.7, 0.0, 0.3)}
HEDGE_NAMES = {"stocks": "All stocks", "bonds": "70% stocks, 30% 10-year Treasuries", "cash": "70% stocks, 30% cash"}
CONFIGS = {"engine": {}, "no_forecasts": {"tilt": False}, "no_risk_budget": {"es": None}, "regimes_only": {"models": ("hmm",)}}
MODELS = ("hmm", "bocpd", "uncond", "geo")
MODEL_NAMES = {"hmm": "Hidden Markov regimes", "bocpd": "Changepoint-aware (BOCPD)", "uncond": "Long-run average", "geo": "Geometric analogs"}
GEO_W, GEO_K, GEO_N0 = 36, 8, 36   # analog windows of 36 months, the 8 nearest, each one's mean shrunk with 36 pseudo-months
FORECASTS = ("mean", "ridge", "combo", "nn")
FORECAST_NAMES = {"mean": "Historical mean", "ridge": "Ridge regression", "combo": "Restricted combination", "nn": "Neural-network ensemble"}


# ---------------------------------------------------------------- data
def bond_returns(S: pd.DataFrame) -> pd.Series:
    """Real monthly return of a 10-year par Treasury held one month: the coupon plus the price change from the yield
    move, deflated by CPI. Built from Shiller's long rate; ends where that series ends."""
    y = S["y10"] / 100
    y0, y1 = y.shift(1), y
    n = 10 * 2
    c = y0 / 2
    t = np.arange(1, n + 1) / 2 - 1 / 12
    disc = (1 + y1.to_numpy()[:, None] / 2) ** (-2 * t[None, :])
    price = (c.to_numpy()[:, None] * disc).sum(1) + disc[:, -1]
    nominal = pd.Series(price, index=S.index) - 1                                  # the dirty price carries the month's accrued coupon
    real = (1 + nominal) / (S["cpi"] / S["cpi"].shift(1)) - 1
    return real.where(y1.notna() & y0.notna())


def data(S: pd.DataFrame, gh: dict | None = None) -> pd.DataFrame:
    """Stock and bond returns. Shiller's long rate stops a few years before the present; with the GitHub mirror of the
    10-year yield (gh) it is carried on to the latest month, as on the portfolio desk."""
    r, px, _ = labs.total_return_index(S)
    if gh and "y10" in gh:
        from . import portfolio
        g10 = portfolio._gh_month(gh["y10"], "Rate").reindex(S.index)
        S = S.assign(y10=S["y10"].where(S["y10"].notna(), g10))
    D = pd.DataFrame({"r": r, "b": bond_returns(S).reindex(r.index), "dy": (S["y10"].diff() / 100).reindex(r.index)})
    ma = pd.Series(labs.sma(px.reindex(r.index).to_numpy(), 10), index=r.index)
    D["trend"] = (px.reindex(r.index) > ma).astype(float)
    return D


# ---------------------------------------------------------------- utility
def calibrate_gamma(r: np.ndarray) -> float:
    """The risk aversion at which holding 1x is optimal for a normal with this sample's mean and sd."""
    mu, sd = float(np.mean(r)), float(np.std(r))
    lo, hi = 0.5, 30.0
    for _ in range(60):
        g = (lo + hi) / 2
        x = GRID[int(np.argmax(utility(np.array([1.0]), np.array([mu]), np.array([sd]), g)))]
        if x > 1.0:
            lo = g
        else:
            hi = g
    return round((lo + hi) / 2, 3)


_Z, _W = np.polynomial.hermite_e.hermegauss(32)
_W = _W / _W.sum()


def utility(w: np.ndarray, mu: np.ndarray, sd: np.ndarray, gamma: float, grid: np.ndarray = GRID, z: np.ndarray | None = None, wq: np.ndarray | None = None,
            borrow: float = BORROW) -> np.ndarray:
    """Expected CRRA utility of 1 + x R - borrowing for each exposure x on the grid, R a mixture of normals."""
    z = _Z if z is None else z
    wq = _W if wq is None else wq
    R = mu[:, None] + sd[:, None] * z[None, :]                                   # [k, q]
    v = 1 + grid[:, None, None] * R[None] - np.maximum(grid - 1, 0)[:, None, None] * borrow
    v = np.maximum(v, 0.02)
    u = np.log(v) if abs(gamma - 1) < 1e-9 else (v ** (1 - gamma) - 1) / (1 - gamma)
    return (u * wq[None, None, :]).sum(2) @ w                                    # [x]


def certainty_equivalent(u: float, gamma: float) -> float:
    return math.exp(u) - 1 if abs(gamma - 1) < 1e-9 else (1 + (1 - gamma) * u) ** (1 / (1 - gamma)) - 1


def choose(w, mu, sd, gamma, es_limit=ES_LIMIT, z=None, wq=None, borrow=BORROW) -> tuple[float, dict]:
    u = utility(w, mu, sd, gamma, GRID, z, wq, borrow)
    info = {}
    allowed = np.ones(len(GRID), bool)
    if es_limit is not None:
        _, es = infer.mixture_cvar(w, mu, sd, 0.05, n=1201)
        info["es_1x"] = es
        allowed = GRID * max(es, 1e-9) <= es_limit + 1e-12
        allowed[0] = True
    u2 = np.where(allowed, u, -np.inf)
    i = int(np.argmax(u2))
    info["capped"] = bool(i != int(np.argmax(u)))
    info["u"] = u
    return float(GRID[i]), info


# ---------------------------------------------------------------- regimes, walked forward
def shrink(m: dict, r_train: np.ndarray, n0: float = N0) -> tuple[np.ndarray, np.ndarray]:
    """Posterior-predictive state parameters: each state's mean shrunk toward the long-run mean with n0 pseudo-months
    (a state seen for few months is mostly prior), and its variance widened by the remaining uncertainty in the mean.
    Without this a regime model sizes as if its in-sample state means were known, and swings between 0x and 1.5x."""
    K = m["K"]
    if K == 1:
        return m["mu"], m["sd"]
    w, v = np.linalg.eig(m["A"].T)
    pi = np.real(v[:, np.argmin(np.abs(w - 1))])
    pi = np.abs(pi) / np.abs(pi).sum()
    n = pi * len(r_train)
    lam = n / (n + n0)
    mu = r_train.mean() + lam * (m["mu"] - r_train.mean())
    sd = np.sqrt(m["sd"] ** 2 * (1 + 1 / (n + n0)))
    return mu, sd


def regime_walk(r: np.ndarray, start: int, refit: int = REFIT_HMM, Ks=(2, 3)) -> dict:
    """For each month t >= start: next-month state weights from data through t - LAG, with an HMM refit every
    `refit` months on data through the refit date minus LAG, the number of states chosen by BIC each time."""
    T = len(r)
    out = {"w": [None] * T, "model": [None] * T, "fits": []}
    for t0 in range(start, T, refit):
        upto = t0 - LAG + 1                                                       # rows 0..t0-LAG
        sel = infer.hmm_select(r[:upto], Ks=Ks, starts=3, iters=150)
        m = dict(sel["best"])
        m["mu_s"], m["sd_s"] = shrink(m, r[:upto])
        out["fits"].append({"at": t0, "K": m["K"], "mu": m["mu"].tolist(), "sd": m["sd"].tolist(), "mu_s": m["mu_s"].tolist()})
        hi = min(T, t0 + refit)
        alpha = infer.hmm_filter(r[:hi - LAG + 1], m)
        A2 = np.linalg.matrix_power(m["A"], LAG)
        for t in range(t0, hi):
            out["w"][t] = alpha[t - LAG] @ A2
            out["model"][t] = m
    return out


def geo_walk(D: pd.DataFrame, start: int) -> dict:
    """The geometric-analog model: the covariance matrix of the last 36 months of stock and bond returns (known by
    t - LAG) is a point on the curved space of positive-definite matrices; the 8 past windows nearest it by the
    affine-invariant distance, ending at least 36 months earlier and 36 months apart, each contribute an equal-weight
    normal built from the 12 months that followed them (mean shrunk toward the long-run mean, variance half its own,
    half the long run's). Months before the bond series starts, or where it is missing, fall back to the long run."""
    from . import geometry
    r = D["r"].to_numpy()
    X = D[["r", "b"]].to_numpy()
    T = len(r)
    ok_row = np.isfinite(X).all(1)
    C = geometry.rolling_cov(np.nan_to_num(X), GEO_W)
    good = np.zeros(T, bool)
    run = np.convolve(ok_row.astype(float), np.ones(GEO_W), "full")[:T]
    good[GEO_W - 1:] = run[GEO_W - 1:] >= GEO_W - 1e-9
    C[good] += np.eye(2)[None] * 1e-10
    def at(e: int):
        past = r[:e + 1]
        m0, v0 = float(past.mean()), float(past.var())
        if not good[e]:                                                     # the bond series can end a month or two early
            g = np.flatnonzero(good[max(e - 3, 0):e + 1])
            e = e - 3 + int(g[-1]) if len(g) and e >= 3 else e
        cand = np.flatnonzero(good[:max(e - GEO_W + 1, 0)])                # windows ending before today's begins
        cand = cand[cand + 12 <= e]
        if not good[e] or len(cand) < GEO_K * 3:
            return np.ones(1), np.array([m0]), np.array([math.sqrt(v0)]), None
        d = np.full(T, np.inf)
        d[cand] = geometry.affine_invariant(C[e], C[cand])
        an = geometry.analogs(d, e, int(cand[-1]), k=GEO_K, gap=GEO_W)
        nxt = np.array([r[j + 1:j + 13] for j in an])
        lam = 12 / (12 + GEO_N0)
        return np.full(len(an), 1 / len(an)), m0 + lam * (nxt.mean(1) - m0), np.sqrt(0.5 * nxt.var(1) + 0.5 * v0), an

    out = {"w": [None] * T, "mu": [None] * T, "sd": [None] * T, "analogs": [None] * T}
    for t in range(start, T):
        out["w"][t], out["mu"][t], out["sd"][t], out["analogs"][t] = at(t - LAG)          # today's window ends at t - LAG
    out["now"] = at(T - 1)
    return out


def predictive(D: pd.DataFrame, start_i: int) -> dict:
    """Each model's predictive for every month from start_i, and its log score once the month is known."""
    r = D["r"].to_numpy()
    T = len(r)
    reg = regime_walk(r, start_i)
    bo = infer.bocpd(r, hazard=1 / 120)
    geo = geo_walk(D, start_i)
    out = {k: {"mu": [None] * T, "sd": [None] * T, "w": [None] * T, "ll": np.full(T, np.nan)} for k in MODELS}
    for t in range(start_i, T):
        m = reg["model"][t]
        out["hmm"]["w"][t], out["hmm"]["mu"][t], out["hmm"]["sd"][t] = reg["w"][t], m["mu_s"], m["sd_s"]
        out["bocpd"]["w"][t], out["bocpd"]["mu"][t], out["bocpd"]["sd"][t] = np.ones(1), np.array([bo["pred_mean"][t - LAG]]), np.array([bo["pred_sd"][t - LAG]])
        past = r[:t - LAG + 1]
        out["uncond"]["w"][t], out["uncond"]["mu"][t], out["uncond"]["sd"][t] = np.ones(1), np.array([past.mean()]), np.array([past.std()])
        out["geo"]["w"][t], out["geo"]["mu"][t], out["geo"]["sd"][t] = geo["w"][t], geo["mu"][t], geo["sd"][t]
        for k in MODELS:
            o = out[k]
            dens = float((o["w"][t] * np.exp(-0.5 * ((r[t] - o["mu"][t]) / o["sd"][t]) ** 2) / (o["sd"][t] * math.sqrt(2 * math.pi))).sum())
            o["ll"][t] = math.log(max(dens, 1e-300))
    return {"models": out, "regime_fits": reg["fits"], "bocpd": bo, "geo_now": geo["now"],
            "geo_analogs": [D.index[j].strftime("%Y-%m") for j in (geo["now"][3] or [])]}


def averaging_weights(ll: dict, t: int, models=MODELS, forget: float = FORGET) -> np.ndarray:
    """Dynamic model averaging: weights proportional to exp(discounted sum of past log scores), using only months
    whose outcome was known by t - LAG."""
    s = []
    for k in models:
        x = np.asarray(ll[k], float)[:t - LAG + 1] if k in ll else np.full(0, np.nan)    # a model not scored has no record
        ok = np.isfinite(x)
        if not ok.any():
            s.append(-np.inf)                                  # a model with no record gets no weight
            continue
        age = (t - LAG - np.flatnonzero(ok)).astype(float)
        s.append(float((x[ok] * forget ** age).sum()))
    s = np.array(s)
    if not np.isfinite(s).any():
        return np.full(len(models), 1 / len(models))
    w = np.exp(s - s.max())
    return w / w.sum()


# ---------------------------------------------------------------- the forecasting models, walked forward
class Ridge:
    def __init__(self, alpha: float = 30.0):
        self.alpha = alpha

    def fit(self, X, y):
        X, y = np.asarray(X, float), np.asarray(y, float)
        self.m, self.s = X.mean(0), X.std(0) + 1e-12
        Z = (X - self.m) / self.s
        self.c = float(y.mean())
        self.b = np.linalg.solve(Z.T @ Z + self.alpha * np.eye(Z.shape[1]), Z.T @ (y - self.c))
        return self

    def predict(self, X):
        return self.c + ((np.asarray(X, float) - self.m) / self.s) @ self.b


class Mean:
    def fit(self, X, y):
        self.c = float(np.mean(y))
        return self

    def predict(self, X):
        return np.full(len(X), self.c)


def make_nn(seed: int = SEED):
    return nn.DeepEnsemble(len(ml.FEATURES), M=5, seed=seed, hidden=(16, 8), dropout=0.1, l2=3e-3, lr=2e-3, epochs=200, patience=25, val_frac=0.2,
                           val_gap=ml.H, batch=64)


def makers() -> dict:
    return {"mean": Mean, "ridge": lambda: Ridge(30.0), "combo": lambda: ml.Combination(ml.FEATURES), "nn": make_nn}


def forecast_walk(P: pd.DataFrame, start_year: int = START, refit: int = REFIT_ML) -> dict:
    """12-month forecasts by every model, purged walk-forward from start_year; the NN's predictive sd; and the stacked
    forecast with weights fit on earlier forecasts whose outcomes were known."""
    Dp = P.dropna(subset=ml.FEATURES)
    X = Dp[ml.FEATURES].to_numpy()
    y = Dp["y_ret"].to_numpy()
    idx = Dp.index
    start = int(np.searchsorted(idx.year, start_year))
    purge = ml.H + ml.EMBARGO
    preds = {k: np.full(len(Dp), np.nan) for k in FORECASTS}
    nn_sd = np.full(len(Dp), np.nan)
    for t in range(start, len(Dp), refit):
        end = t - purge
        ok = np.isfinite(y[:end])
        for k, mk in makers().items():
            m = mk()
            m.fit(X[:end][ok], y[:end][ok])
            if k == "nn":
                # total predictive sd: the ensemble's disagreement and dropout spread (what the model does not know)
                # plus the residual noise it saw in training (what nobody could know)
                mu, sd = m.predict_dist(X[t:t + refit], samples=20)
                noise = float(np.mean((y[:end][ok] - m.predict(X[:end][ok])) ** 2))
                preds[k][t:t + refit], nn_sd[t:t + refit] = mu, np.sqrt(sd ** 2 + noise)
            else:
                preds[k][t:t + refit] = m.predict(X[t:t + refit])
    # stacking: at t, weights from rows whose 12-month outcome had ended by t (row index <= t - purge)
    stacked = np.full(len(Dp), np.nan)
    weights = np.full((len(Dp), len(FORECASTS)), np.nan)
    Pm = np.column_stack([preds[k] for k in FORECASTS])
    for t in range(start, len(Dp)):
        w = infer.stack(Pm[:t - purge + 1], y[:t - purge + 1])
        weights[t] = w
        stacked[t] = Pm[t] @ w
    return {"index": idx, "y": y, "preds": preds, "nn_sd": nn_sd, "stacked": stacked, "weights": weights, "start": start}


def forecast_scores(F: dict) -> dict:
    y = F["y"]
    s = F["start"]
    ok = np.isfinite(y) & (np.arange(len(y)) >= s)
    bench = F["preds"]["mean"]
    out = {}
    for k in list(FORECASTS) + ["stacked"]:
        p = F["stacked"] if k == "stacked" else F["preds"][k]
        m = ok & np.isfinite(p)
        e, eb = y[m] - p[m], y[m] - bench[m]
        out[k] = {"skill": float(1 - (e ** 2).mean() / (eb ** 2).mean()), "dm": ml.diebold_mariano(e, eb), "n": int(m.sum()),
                  "corr": float(np.corrcoef(p[m], y[m])[0, 1]) if np.std(p[m]) > 0 else None}
    m = ok & np.isfinite(F["nn_sd"])
    z = (y[m] - F["preds"]["nn"][m]) / F["nn_sd"][m]
    out["nn"]["coverage80"] = float(np.mean(np.abs(z) <= 1.2816))
    # recalibrated causally: scale the bands by the 80th percentile of |z| over forecasts whose outcome was known
    purge = ml.H + ml.EMBARGO
    zz = np.full(len(y), np.nan)
    zz[m] = np.abs(z)
    hits = []
    for t in np.flatnonzero(m):
        past = zz[:max(0, t - purge + 1)]
        past = past[np.isfinite(past)]
        if len(past) >= 60:
            hits.append(zz[t] <= np.quantile(past, 0.8))
    out["nn"]["coverage80_recalibrated"] = float(np.mean(hits)) if hits else None
    out["nn"]["sd_median"] = float(np.median(F["nn_sd"][m]))
    rm = ok & np.isfinite(F["stacked"])
    out["stacked"]["rmse"] = float(np.sqrt(np.mean((y[rm] - F["stacked"][rm]) ** 2)))
    return out


# ---------------------------------------------------------------- hedge selector
def hedge_selector(D: pd.DataFrame, stress: np.ndarray, start_i: int, forget: float = 0.995, draws: int = 400, seed: int = SEED) -> dict:
    """A Bayesian selector over the three hedges, by context (stressed or calm regime, trend on or off). Every hedge's
    return is observed each month (full feedback), so this is an experts problem rather than a bandit: each
    (context, hedge) keeps a discounted normal posterior of its log growth, the month's choice is the highest posterior
    mean, and Thompson draws give the probability each hedge is best. Uses data through t - LAG."""
    r, b = D["r"].to_numpy(), D["b"].to_numpy()
    trend = D["trend"].to_numpy()
    T = len(r)
    names = list(HEDGES)
    G = np.full((T, len(names)), np.nan)
    for j, k in enumerate(names):
        ws, wb, wc = HEDGES[k]
        G[:, j] = np.log1p(ws * r + wb * b + wc * 0.0)
    trend_l = np.concatenate([np.full(LAG, np.nan), trend[:-LAG]])            # the trend as known when acting
    ctx = lambda t: int(stress[t] > 0.5) * 2 + int(trend_l[t] > 0)
    n = np.zeros((4, len(names)))
    s1 = np.zeros((4, len(names)))
    s2 = np.zeros((4, len(names)))
    pick = np.full(T, -1)
    for t in range(T):
        tl = t - LAG
        if tl >= 0 and np.isfinite(G[tl]).all() and np.isfinite(stress[tl]) and np.isfinite(trend_l[tl]):
            c = ctx(tl)
            n[c] *= forget
            s1[c] *= forget
            s2[c] *= forget
            n[c] += 1
            s1[c] += G[tl]
            s2[c] += G[tl] ** 2
        if t >= start_i and np.isfinite(stress[t]) and np.isfinite(G[t]).all():
            c = ctx(t)
            mean = (s1[c] + 0.0) / (n[c] + 12)                                 # shrunk to zero with 12 pseudo-months
            pick[t] = int(np.argmax(mean))
    ok = pick >= 0
    realized = np.where(ok, G[np.arange(T), np.maximum(pick, 0)], np.nan)

    def posterior(c):
        mean = s1[c] / (n[c] + 12)
        var = np.maximum(s2[c] / np.maximum(n[c], 1) - (s1[c] / np.maximum(n[c], 1)) ** 2, 1e-6)
        se = np.sqrt(var / (n[c] + 12))
        rng = np.random.default_rng(seed)
        d = rng.normal(mean[None, :], se[None, :], (draws, len(names)))
        pb = np.bincount(d.argmax(1), minlength=len(names)) / draws
        return {"mean_annual": (mean * 12).tolist(), "p_best": pb.tolist(), "months": n[c].tolist()}

    return {"names": names, "pick": pick, "ok": ok, "realized": realized, "G": G, "posterior": posterior, "ctx": ctx}


# ---------------------------------------------------------------- reinforcement learning, conservative
def fqi_transitions(s, sn, r, gamma, penalty, prior, iters: int = 60) -> np.ndarray:
    nA, nS = len(rl.ACTIONS), 54
    R = rl.rewards(r, penalty)
    Q = np.zeros((nS, nA, nA))
    cnt = np.bincount(s, minlength=nS).astype(float)
    for _ in range(iters):
        V = Q.max(axis=2)
        target = R + gamma * V[sn][:, None, :].transpose(0, 2, 1)
        sums = np.zeros((nS, nA, nA))
        np.add.at(sums, s, target)
        glob = target.mean(axis=0)
        Qn = (sums + prior * glob[None]) / (cnt[:, None, None] + prior)
        if np.max(np.abs(Qn - Q)) < 1e-10:
            return Qn
        Q = Qn
    return Q


def rl_conservative(Ds: pd.DataFrame, start: int = START, refit: int = 24, B: int = 12, kappa: float = 1.0, cfg: dict | None = None, seed: int = SEED) -> dict:
    """Bootstrapped-ensemble fitted Q iteration that acts on the lower confidence bound: B agents, each trained on a
    stationary-bootstrap resample of the months, and the action is argmax over (mean Q minus kappa sd Q). Where the
    agents disagree, the action falls back toward holding: pessimism in the face of thin data."""
    cfg = cfg or rl.CONFIGS["risk_averse_cautious_prior"]
    idx = Ds.index
    test = [i for i, d in enumerate(idx) if d.year >= start]
    r = Ds["r"].to_numpy()
    acts = np.full(len(Ds), np.nan)
    rets = np.full(len(Ds), np.nan)
    rng = np.random.default_rng(seed)
    p = 2
    Qs = None
    for k in range(0, len(test), refit):
        blk = test[k:k + refit]
        t0 = blk[0]
        b = rl.encode(Ds, t0)
        n = t0 - 1
        ii = labs.stationary_bootstrap_idx(n, B, 12, rng)
        Qs = np.stack([fqi_transitions(b[j], b[j + 1], r[j], cfg["gamma"], cfg["penalty"], cfg["prior"]) for j in ii])
        mu, sd = Qs.mean(0), Qs.std(0)
        L = mu - kappa * sd
        for i in blk:
            q = L[b[i], p]
            a = int(np.argmax(q))
            acts[i] = rl.ACTIONS[a]
            rets[i] = rl.ACTIONS[a] * r[i] - COST * abs(rl.ACTIONS[a] - rl.ACTIONS[p]) - max(0.0, rl.ACTIONS[a] - 1) * BORROW
            p = a
    b = rl.encode(Ds, len(Ds))
    ii = labs.stationary_bootstrap_idx(len(Ds) - 1, B, 12, rng)
    Qs = np.stack([fqi_transitions(b[j], b[j + 1], r[j], cfg["gamma"], cfg["penalty"], cfg["prior"]) for j in ii])
    L = Qs.mean(0) - kappa * Qs.std(0)
    pn = int(np.nanargmin(np.abs(np.array(rl.ACTIONS) - (acts[~np.isnan(acts)][-1] if (~np.isnan(acts)).any() else 1.0))))
    q_now = L[b[-1], pn]
    agree = float(np.mean([int(np.argmax(Q[b[-1], pn])) == int(np.argmax(q_now)) for Q in Qs]))
    m = ~np.isnan(rets)
    return {"dates": [d.strftime("%Y-%m") for d in idx[m]], "ret": rets[m], "act": acts[m], "hold": r[m],
            "now": {"action": rl.ACTIONS[int(np.argmax(q_now))], "lcb": q_now.tolist(), "agreement": agree, "B": B, "kappa": kappa}}


# ---------------------------------------------------------------- the engine, walked forward
def run_engine(D: pd.DataFrame, pred: dict, tilt: np.ndarray, gamma: float, start_i: int, models=MODELS, use_tilt=True, es=ES_LIMIT) -> dict:
    r = D["r"].to_numpy()
    T = len(r)
    M = pred["models"]
    x = np.full(T, np.nan)
    ret = np.full(T, np.nan)
    capped = np.zeros(T, bool)
    prev = 1.0
    for t in range(start_i, T):
        wm = averaging_weights({k: M[k]["ll"] for k in models}, t, models)
        W, MU, SD = [], [], []
        for j, k in enumerate(models):
            W.append(wm[j] * M[k]["w"][t])
            MU.append(M[k]["mu"][t] + (tilt[t] if use_tilt and np.isfinite(tilt[t]) else 0.0))
            SD.append(M[k]["sd"][t])
        a, info = choose(np.concatenate(W), np.concatenate(MU), np.concatenate(SD), gamma, es)
        x[t] = a
        capped[t] = info["capped"]
        ret[t] = a * r[t] - COST * abs(a - prev) - max(0.0, a - 1) * BORROW
        prev = a
    m = np.isfinite(ret)
    return {"x": x, "ret": ret, "m": m, "capped": capped}


def timing_alpha(dev: np.ndarray, r: np.ndarray) -> tuple[float, float, int]:
    """The intercept of the deviation's return (engine minus holding) on the market's return, and its t statistic:
    what the engine's departures from 1x earned beyond simply carrying more or less market."""
    ok = np.isfinite(dev) & np.isfinite(r)
    n = int(ok.sum())
    if n < 60:
        return 0.0, 0.0, n
    X = np.column_stack([np.ones(n), r[ok]])
    b, *_ = np.linalg.lstsq(X, dev[ok], rcond=None)
    e = dev[ok] - X @ b
    cov = np.linalg.inv(X.T @ X) * (e @ e) / (n - 2)
    return float(b[0]), float(b[0] / math.sqrt(max(cov[0, 0], 1e-18))), n


N_TRIED = len(CONFIGS) + 4 + 4 + 5 + 11   # configurations of this engine tried, the two RL agents, the trend rule, the geometric-analog model (v0.22), the overlay's four scalings
                                          # of the trend rule (v0.24), the five borrowed upgrades tried on the core (EMOS, textbook EMOS, BMA, credibility n0, an EVT floor) and
                                          # the eleven RL variants of v0.25 (the pooled-state agent and its ten rejected siblings): every sizing strategy tried, counted once (v0.24)


def utility_gain(ret: np.ndarray, hold: np.ndarray, gamma: float) -> tuple[float, float, int]:
    """Mean monthly CRRA utility of the engine minus that of holding, with a Newey-West t statistic (12 lags): did the
    engine's departures from 1x make a risk-averse investor better off, not just richer?"""
    ok = np.isfinite(ret) & np.isfinite(hold)
    n = int(ok.sum())
    if n < 60:
        return 0.0, 0.0, n
    u = lambda v: np.log(np.maximum(v, 0.02)) if abs(gamma - 1) < 1e-9 else (np.maximum(v, 0.02) ** (1 - gamma) - 1) / (1 - gamma)
    d = u(1 + ret[ok]) - u(1 + hold[ok])
    se = math.sqrt(ml.nw_var(d - d.mean(), 12))
    return float(d.mean()), float(d.mean() / se) if se > 0 else 0.0, n


def gate_from_t(t: float, n_tried: int = N_TRIED) -> float:
    """How far to move from holding toward the engine's choice. The evidence is the t statistic of the utility gain
    over holding, less the t one would expect from the best of n_tried useless strategies; the gate is
    2 Phi(t - t0) - 1, floored at 0: nothing on a coin flip, rising to 1 as the evidence becomes conclusive."""
    from scipy import stats
    t0 = float(stats.norm.ppf(1 - 1 / n_tried))
    return float(max(0.0, 2 * stats.norm.cdf(t - t0) - 1))


def gated(D: pd.DataFrame, R: dict, start_i: int, gamma: float) -> dict:
    """The engine walked forward with its own evidence gate: each month the move away from 1x is scaled by the gate
    computed from the engine's utility gain over holding on earlier months (known by t - LAG)."""
    r = D["r"].to_numpy()
    T = len(r)
    x = np.full(T, np.nan)
    ret = np.full(T, np.nan)
    g = np.full(T, np.nan)
    prev = 1.0
    for t in range(start_i, T):
        lo = t - LAG + 1
        _, tt, _ = utility_gain(R["ret"][start_i:lo], r[start_i:lo], gamma)
        g[t] = gate_from_t(tt)
        a = round((1 + g[t] * (R["x"][t] - 1)) / 0.05) * 0.05
        x[t] = a
        ret[t] = a * r[t] - COST * abs(a - prev) - max(0.0, a - 1) * BORROW
        prev = a
    return {"x": x, "ret": ret, "m": np.isfinite(ret), "capped": R["capped"], "gate": g}


def tilt_series(D: pd.DataFrame, F: dict) -> np.ndarray:
    """Monthly mean adjustment from the stacked 12-month forecast against the historical mean, both known LAG - 1
    months before the month acted on (the panel's features are already lagged a month)."""
    st = pd.Series(F["stacked"] - F["preds"]["mean"], index=F["index"]).reindex(D.index)
    return (st.shift(LAG - 1) / ml.H).to_numpy()


def perf(x: np.ndarray) -> dict:
    p = labs.perf(pd.Series(x))
    return {k: (float(v) if isinstance(v, (float, np.floating)) else v) for k, v in p.items()}


OVERLAY_FACTORS = (0.0, 0.25, 0.5, 0.75, 1.0)


def overlay_study(r: np.ndarray, trend_sig: np.ndarray, gated_x: np.ndarray, m: np.ndarray, gamma: float, bidx: np.ndarray) -> dict:
    """The trend rule as a risk overlay, decided by the engine's own objective. Below the 10-month average, exposure is
    scaled by a factor f (0 is the classic rule, 1 is no overlay). For each f, on holding and on the gated engine,
    walked forward with costs: Sharpe, worst drawdown, real growth, the CRRA utility gain over holding with its
    Newey-West t, and bootstrap ranges of the Sharpe and drawdown differences. The rule, fixed before the result: the
    adopted factor is the deepest drawdown cut among the factors whose walk-forward CRRA utility is at least holding's
    (a drawdown limit is a mandate's constraint, so the overlay must be free in expected utility); f = 1 is no overlay."""
    hold = r[m]
    sig = trend_sig[m] > 0
    rows = {}
    for f in OVERLAY_FACTORS:
        for base, bx in (("hold", np.ones(int(m.sum()))), ("engine", gated_x[m])):
            x = np.where(sig, bx, bx * f)
            ret = x * hold - COST * np.abs(np.diff(np.concatenate([[1.0], x]))) - np.maximum(0.0, x - 1) * BORROW
            ug, t, _ = utility_gain(ret, hold, gamma)
            d_sh = np.array([labs.sharpe(ret[i]) - labs.sharpe(hold[i]) for i in bidx])
            d_dd = np.array([labs.perf(pd.Series(ret[i]))["maxdd"] - labs.perf(pd.Series(hold[i]))["maxdd"] for i in bidx])
            rows[f"{base}:{f}"] = {"base": base, "factor": f, "perf": perf(ret), "utility_gain_month": ug, "utility_t": t,
                                   "switches": int(np.sum(np.abs(np.diff(x)) > 1e-9)), "avg_exposure": float(x.mean()),
                                   "sharpe_vs_hold": {"est": float(labs.sharpe(ret) - labs.sharpe(hold)), "lo": float(np.quantile(d_sh, 0.05)), "hi": float(np.quantile(d_sh, 0.95))},
                                   "maxdd_vs_hold": {"est": float(perf(ret)["maxdd"] - perf(hold)["maxdd"]), "lo": float(np.quantile(d_dd, 0.05)), "hi": float(np.quantile(d_dd, 0.95))}}
    # the rule: the deepest cut in the worst drawdown among the factors that cost a risk-averse investor nothing in
    # expected utility (a mandate's drawdown limit is a constraint, not a preference, so the overlay must be free)
    def pick(ug: dict, dd: dict) -> float:
        free = [f for f in OVERLAY_FACTORS if ug[f] >= 0.0]
        return max(free, key=lambda f: dd[f]) if free else 1.0                                 # maxdd is negative: the largest is the shallowest
    best = pick({f: rows[f"hold:{f}"]["utility_gain_month"] for f in OVERLAY_FACTORS}, {f: rows[f"hold:{f}"]["perf"]["maxdd"] for f in OVERLAY_FACTORS})
    # v0.24: the same rule walked forward. Every twelve months the factor is chosen on the record to that point (after a
    # ten-year burn-in, no overlay before it) and applied for the next twelve, so the overlay's own record is judged out
    # of sample like the engine's; the adopted factor above is the rule's current output on the full record.
    u = lambda v: np.log(np.maximum(v, 0.02)) if abs(gamma - 1) < 1e-9 else (np.maximum(v, 0.02) ** (1 - gamma) - 1) / (1 - gamma)
    T = len(hold)
    rets = {}
    for f in OVERLAY_FACTORS:
        x = np.where(sig, 1.0, f)
        rets[f] = x * hold - COST * np.abs(np.diff(np.concatenate([[1.0], x]))) - np.maximum(0.0, x - 1) * BORROW
    uh = u(1 + hold)
    wf = np.array(hold, dtype=float)
    choice = np.ones(T)
    chosen = []
    for t in range(120, T, 12):
        ug = {f: float(np.mean(u(1 + rets[f][:t]) - uh[:t])) for f in OVERLAY_FACTORS}
        dd = {f: float(labs.drawdown(np.cumprod(1 + rets[f][:t])).min()) for f in OVERLAY_FACTORS}
        fc = pick(ug, dd)
        choice[t:t + 12] = fc
        chosen.append(fc)
        wf[t:t + 12] = rets[fc][t:t + 12]
    wug, wt, _ = utility_gain(wf, hold, gamma)
    d_sh = np.array([labs.sharpe(wf[i]) - labs.sharpe(hold[i]) for i in bidx])
    d_dd = np.array([labs.perf(pd.Series(wf[i]))["maxdd"] - labs.perf(pd.Series(hold[i]))["maxdd"] for i in bidx])
    walk = {"perf": perf(wf), "utility_gain_month": wug, "utility_t": wt, "avg_factor": float(np.mean(choice[120:])) if T > 120 else 1.0,
            "factor_changes": int(np.sum(np.abs(np.diff(np.array(chosen))) > 1e-9)) if chosen else 0, "burn_in_months": 120, "refit_months": 12,
            "sharpe_vs_hold": {"est": float(labs.sharpe(wf) - labs.sharpe(hold)), "lo": float(np.quantile(d_sh, 0.05)), "hi": float(np.quantile(d_sh, 0.95))},
            "maxdd_vs_hold": {"est": float(perf(wf)["maxdd"] - perf(hold)["maxdd"]), "lo": float(np.quantile(d_dd, 0.05)), "hi": float(np.quantile(d_dd, 0.95))},
            "chosen": [float(c) for c in chosen]}
    full_best = float(best)
    if best < 1.0 and wug < 0.0:
        # the rule's own walked-forward record fails the test the rule applies to its candidates: not adopted
        reason = (f"no overlay: the factor the rule picks on the full record ({full_best:.2f}) does not survive its own walk-forward; re-chosen every twelve "
                  f"months on the record to date, the overlay costs expected utility against holding (t {wt:+.2f})")
        best = 1.0
    elif best >= 1.0:
        reason = "no overlay: every factor tried costs expected utility against holding"
    else:
        reason = f"below the 10-month average, exposure is scaled by {best:.2f}: the deepest drawdown cut among the factors that keep holding's expected utility, and the choice holds walked forward"
    return {"factors": list(OVERLAY_FACTORS), "rows": rows, "adopted": float(best), "full_record_choice": full_best, "adopted_reason": reason,
            "rule": "largest drawdown reduction among factors whose CRRA utility is at least holding's, adopted only if the same choice walked forward keeps holding's utility",
            "trend_on_now": bool(sig[-1]), "walk_forward": walk}


# ---------------------------------------------------------------- today
def today(D, pred, F, P, row, gamma, hedge, draws: int = 2000, seed: int = SEED) -> dict:
    """Today's decision, its distribution, drivers, flip points and the value of knowing the regime."""
    r = D["r"].to_numpy()
    T = len(r)
    # regimes on everything, filtered to the last month
    sel = infer.hmm_select(r, Ks=(2, 3), starts=3, iters=150)
    m = dict(sel["best"])
    mu_s, sd_s = shrink(m, r)
    alpha = infer.hmm_filter(r, m)
    w_hmm = alpha[-1] @ m["A"]
    smooth = infer.hmm_smooth(r, m)
    bo = pred["bocpd"]
    t = T                                                       # the month being decided is the one after the data
    M = pred["models"]
    ll = {k: np.concatenate([M[k]["ll"], [np.nan]]) for k in MODELS}
    wm = averaging_weights(ll, t + LAG - 1)                    # every known score counts
    comps = {"hmm": (w_hmm, mu_s, sd_s), "bocpd": (np.ones(1), np.array([bo["pred_mean"][-1]]), np.array([bo["pred_sd"][-1]])),
             "uncond": (np.ones(1), np.array([r.mean()]), np.array([r.std()])), "geo": pred["geo_now"][:3]}
    # forecasts on today's row, every model trained on all rows with a known outcome
    Dp = P.dropna(subset=ml.FEATURES + ["y_ret"])
    X, y = Dp[ml.FEATURES].to_numpy(), Dp["y_ret"].to_numpy()
    xr = np.array([[float(row[f]) for f in ml.FEATURES]])
    now_f, nn_sd, nn_members, nn_epistemic = {}, None, [], None
    for k, mk in makers().items():
        mdl = mk().fit(X, y)
        if k == "nn":
            mu_, sd_ = mdl.predict_dist(xr, samples=50)
            noise = float(np.mean((y - mdl.predict(X)) ** 2))
            now_f[k], nn_sd = float(np.ravel(mu_)[0]), float(math.sqrt(float(np.ravel(sd_)[0]) ** 2 + noise))
            nn_epistemic = float(np.ravel(sd_)[0])
            nn_members = [float(np.ravel(mm.predict(xr))[0]) for mm in mdl.members]
        else:
            now_f[k] = float(np.ravel(mdl.predict(xr))[0])
    wf = F["weights"][-1] if np.isfinite(F["weights"][-1]).all() else np.full(len(FORECASTS), 1 / len(FORECASTS))
    stacked = float(sum(wf[i] * now_f[k] for i, k in enumerate(FORECASTS)))
    tilt = (stacked - now_f["mean"]) / ml.H

    def mix(models=MODELS, use_tilt=True, tilt_v=tilt, hmm_w=None, es=ES_LIMIT, wmod=None):
        wmod = wm if wmod is None else wmod
        W, MU, SD = [], [], []
        keep = [i for i, k in enumerate(MODELS) if k in models]
        ws = np.array([wmod[i] for i in keep])
        ws = ws / ws.sum()
        for j, i in enumerate(keep):
            k = MODELS[i]
            cw, cm, cs = comps[k]
            if k == "hmm" and hmm_w is not None:
                cw = hmm_w
            W.append(ws[j] * cw)
            MU.append(cm + (tilt_v if use_tilt else 0.0))
            SD.append(cs)
        return np.concatenate(W), np.concatenate(MU), np.concatenate(SD)

    def decide(**kw):
        es = kw.pop("es", ES_LIMIT)
        w, mu, sd = mix(**kw)
        return choose(w, mu, sd, gamma, es)

    x, info = decide()
    w0, mu0, sd0 = mix()
    var5, es5 = infer.mixture_cvar(w0, mu0, sd0, 0.05)
    u_star = float(info["u"][list(GRID).index(x)])
    u_hold = float(info["u"][list(GRID).index(1.0)])
    # leave one out
    drivers = []
    for k in MODELS:
        if wm[MODELS.index(k)] < 1e-6:
            continue
        rest = tuple(z for z in MODELS if z != k)
        drivers.append({"part": MODEL_NAMES[k], "without": decide(models=rest)[0]})
    drivers.append({"part": "The forecasts (stacked 12-month view)", "without": decide(use_tilt=False)[0]})
    drivers.append({"part": "The risk budget", "without": decide(es=None)[0]})
    for d in drivers:
        d["delta"] = round(x - d["without"], 2)
    # flip points: the 12-month expected real return (stacked) at which the exposure changes from today's
    grid12 = np.linspace(-0.3, 0.3, 121)
    xs = np.array([decide(tilt_v=(g - now_f["mean"]) / ml.H)[0] for g in grid12])
    up = [float(g) for g, xx in zip(grid12, xs) if xx > x and g > stacked]
    dn = [float(g) for g, xx in zip(grid12, xs) if xx < x and g < stacked]
    flip = {"stacked_now": stacked, "raise_if_above": min(up) if up else None, "cut_if_below": max(dn) if dn else None,
            "curve": {"r12": [round(float(g), 3) for g in grid12[::4]], "x": [float(v) for v in xs[::4]]}}
    worst = int(np.argmin(m["mu"]))
    if m["K"] > 1:
        ps = np.linspace(0, 1, 41)
        xs2 = []
        for p_ in ps:
            ww = np.full(m["K"], (1 - p_) / (m["K"] - 1))
            ww[worst] = p_
            xs2.append(decide(hmm_w=ww)[0])
        cut = [float(p_) for p_, xx in zip(ps, xs2) if xx < x and p_ > w_hmm[worst]]
        flip["cut_if_stress_prob_above"] = min(cut) if cut else None
        flip["stress_curve"] = {"p": [round(float(v), 3) for v in ps[::2]], "x": [float(v) for v in xs2[::2]]}
    # value of knowing the regime: E_k max_x U_k - max_x E_k U_k, in certainty-equivalent monthly return
    evpi = None
    if m["K"] > 1:
        per = []
        for k in range(m["K"]):
            e = np.zeros(m["K"])
            e[k] = 1
            per.append((w_hmm[k], decide(hmm_w=e)))
        u_known = sum(p_ * float(i_["u"][list(GRID).index(a_)]) for p_, (a_, i_) in per)
        evpi = {"ce_month": certainty_equivalent(u_known, gamma) - certainty_equivalent(u_star, gamma),
                "by_state": [{"state": k, "p": float(p_), "x": a_} for k, (p_, (a_, _)) in enumerate(per)]}
    # the decision's distribution: draw a regime, a model, a forecast member
    rng = np.random.default_rng(seed)
    fc_members = [now_f["mean"], now_f["ridge"], now_f["combo"]] + nn_members
    fc_w = np.array([wf[0], wf[1], wf[2]] + [wf[3] / max(1, len(nn_members))] * len(nn_members))
    fc_w = fc_w / fc_w.sum()
    dx = []
    for _ in range(draws):
        mk = rng.choice(len(MODELS), p=wm)
        k = MODELS[mk]
        fc = fc_members[rng.choice(len(fc_members), p=fc_w)]
        tv = (fc - now_f["mean"]) / ml.H
        cw, cm, cs = comps[k]
        if k == "hmm":
            s = rng.choice(m["K"], p=w_hmm / w_hmm.sum())
            cw, cm, cs = np.ones(1), cm[s:s + 1], cs[s:s + 1]
        dx.append(choose(cw, cm + tv, cs, gamma, ES_LIMIT)[0])
    dx = np.array(dx)
    hp = hedge["posterior"](hedge["ctx_now"])
    hi = int(np.argmax(hp["mean_annual"]))
    return {
        "date": D.index[-1].strftime("%Y-%m"), "exposure": x, "capped": info["capped"], "es_1x": info.get("es_1x"), "var5": var5, "es5": es5,
        "ce_gain_vs_hold_annual": 12 * (certainty_equivalent(u_star, gamma) - certainty_equivalent(u_hold, gamma)),
        "distribution": {"p_below_1": float(np.mean(dx < 1 - 1e-9)), "p_above_1": float(np.mean(dx > 1 + 1e-9)), "p_at_1": float(np.mean(np.abs(dx - 1) < 1e-9)),
                         "q10": float(np.quantile(dx, 0.1)), "median": float(np.median(dx)), "q90": float(np.quantile(dx, 0.9)),
                         "hist": [int(v) for v in np.histogram(dx, bins=np.round(np.arange(-0.05, 1.6, 0.1), 2))[0]], "draws": draws},
        "regime": {"K": m["K"], "bic": {str(k): float(v) for k, v in sel["bic"].items()}, "mu": m["mu"].tolist(), "sd": m["sd"].tolist(), "mu_shrunk": mu_s.tolist(), "sd_shrunk": sd_s.tolist(), "A": m["A"].tolist(),
                   "now": alpha[-1].tolist(), "next": w_hmm.tolist(), "worst": worst,
                   "persistence_months": [float(1 / max(1 - m["A"][k, k], 1e-9)) for k in range(m["K"])],
                   "history": {"dates": [d.strftime("%Y-%m") for d in D.index[::3]], "p_worst": [round(float(v), 3) for v in smooth[::3, worst]],
                               "filtered": [round(float(v), 3) for v in alpha[::3, worst]]}},
        "changepoint": {"recent": float(bo["recent"][-1]), "expected_run": float(bo["expected_run"][-1]), "map_run": int(bo["map_run"][-1]),
                        "history": {"dates": [d.strftime("%Y-%m") for d in D.index[::3]], "recent": [round(float(v), 3) for v in bo["recent"][::3]]},
                        "alarms": [D.index[i].strftime("%Y-%m") for i in range(1, T) if bo["recent"][i] > 0.5 >= bo["recent"][i - 1]]},
        "models": {"weights": {k: float(wm[i]) for i, k in enumerate(MODELS)}, "names": MODEL_NAMES, "geo_analogs": pred.get("geo_analogs", [])},
        "forecasts": {"now": now_f, "weights": {k: float(wf[i]) for i, k in enumerate(FORECASTS)}, "stacked": stacked, "nn_sd": nn_sd, "nn_epistemic_sd": nn_epistemic, "nn_members": nn_members, "names": FORECAST_NAMES},
        "drivers": drivers, "flip": flip, "evpi": evpi, "gamma": gamma, "es_limit": ES_LIMIT,
        "mixture": {k: {"w": [float(v) for v in comps[k][0]], "mu": [float(v) for v in comps[k][1]], "sd": [float(v) for v in comps[k][2]]} for k in MODELS},
        "tilt": tilt, "gh": {"z": _Z.tolist(), "w": _W.tolist()}, "grid": GRID.tolist(), "borrow": BORROW,
        "hedge": {"choice": hedge["names"][hi], "name": HEDGE_NAMES[hedge["names"][hi]], "context": hedge["ctx_label"], "as_of": hedge["as_of"], **hp,
                  "names": [HEDGE_NAMES[k] for k in hedge["names"]]},
    }


# ---------------------------------------------------------------- build
@cache.memo("decide.build", deps=("buildout.infer", "buildout.nn", "buildout.ml", "buildout.rl", "buildout.labs", "buildout.geometry", "buildout.portfolio"), require=("dl",))
def build(dl: dict | None = None, cape_now: float | None = None, y10_now: float | None = None, quick: bool = False, gh: dict | None = None) -> dict:
    dl = dl or labs.download()
    S = labs.shiller(dl)
    D = data(S, gh)
    start_i = int(np.searchsorted(D.index.year, START))
    gamma = calibrate_gamma(D["r"].to_numpy()[:start_i])
    pred = predictive(D, start_i)
    P = ml.panel(S)
    F = forecast_walk(P, START, refit=48 if quick else REFIT_ML)
    fsc = forecast_scores(F)
    tilt = tilt_series(D, F)
    runs = {}
    for name, cfg in CONFIGS.items():
        runs[name] = run_engine(D, pred, tilt, gamma, start_i, models=cfg.get("models", MODELS), use_tilt=cfg.get("tilt", True), es=cfg.get("es", ES_LIMIT))
    runs["gated"] = gated(D, runs["engine"], start_i, gamma)
    m = runs["engine"]["m"]
    dates = D.index[m]
    r = D["r"].to_numpy()
    hold = r[m]
    trend_sig = D["trend"].shift(LAG).to_numpy()
    tx = np.where(trend_sig[m] > 0, 1.0, 0.0)
    trend = tx * hold - COST * np.abs(np.diff(np.concatenate([[1.0], tx])))          # the classic rule with the same costs as the overlay study (v0.24)
    Ds = rl.states(S)
    rl1 = {k: rl.walk_forward(Ds, rl.CONFIGS[k]) for k in ("risk_averse_cautious_prior",)}["risk_averse_cautious_prior"]
    rl2 = rl_conservative(Ds, B=6 if quick else 12, refit=48 if quick else 24)
    # hedge selector on the stress probability from the walked-forward regimes
    stress = np.full(len(D), np.nan)
    for t in range(start_i, len(D)):
        mm = pred["models"]["hmm"]
        w = mm["w"][t]
        stress[t] = float(w[int(np.argmin(mm["mu"][t]))])
    hedge = hedge_selector(D, stress, start_i)
    okh = hedge["ok"]
    hedge_perf = {"selector": perf(np.expm1(hedge["realized"][okh]))}
    for j, k in enumerate(hedge["names"]):
        hedge_perf[k] = perf(np.expm1(hedge["G"][okh, j]))
    last_h = int(np.flatnonzero(okh)[-1])
    # today's hedge context: the regime's stress probability now and the trend now
    from scipy import stats
    rng = np.random.default_rng(SEED)
    bidx = labs.stationary_bootstrap_idx(int(m.sum()), 600, 12, rng)
    configs = {}
    for name, R in runs.items():
        x = R["ret"][m]
        d = np.array([labs.sharpe(x[i]) - labs.sharpe(hold[i]) for i in bidx])
        configs[name] = {"perf": perf(x), "avg_exposure": float(np.nanmean(R["x"][m])), "time_below_1": float(np.mean(R["x"][m] < 1)), "time_above_1": float(np.mean(R["x"][m] > 1)),
                         "time_capped": float(np.mean(R["capped"][m])), "sharpe_vs_hold": {"est": float(labs.sharpe(x) - labs.sharpe(hold)), "lo": float(np.quantile(d, 0.05)),
                                                                                           "hi": float(np.quantile(d, 0.95)), "p_le0": float(np.mean(d <= 0))}}
    # timing alpha (beyond carrying more or less market) of each configuration, and the deflated Sharpe of the best
    alphas = {}
    for k in runs:
        dev = runs[k]["ret"][m] - hold
        a, tt, n_ = timing_alpha(dev, hold)
        X = np.column_stack([np.ones(len(hold)), hold])
        b, *_ = np.linalg.lstsq(X, dev, rcond=None)
        resid = dev - X[:, 1] * b[1]
        alphas[k] = {"alpha_annual": a * 12, "t": tt, "beta_extra": float(b[1]), "sr": float(resid.mean() / resid.std(ddof=1)), "series": resid}
        configs[k]["timing_alpha"] = {kk: v for kk, v in alphas[k].items() if kk != "series"}
    best_k = max(alphas, key=lambda k: alphas[k]["sr"])
    xb = alphas[best_k]["series"]
    ex = np.array([alphas[k]["sr"] for k in alphas])
    dsr = labs.deflated_sharpe(alphas[best_k]["sr"], N_TRIED, float(np.var(ex, ddof=1)), len(xb), float(stats.skew(xb)), float(stats.kurtosis(xb, fisher=False)))
    dsr["best"] = best_k
    # the model-averaging weights through history and their scores
    wm_hist = np.array([averaging_weights({k: pred["models"][k]["ll"] for k in MODELS}, t) for t in range(start_i, len(D))])
    ll_mean = {k: float(np.nanmean(pred["models"][k]["ll"][start_i:])) for k in MODELS}
    # Kalman: stock real return per point of 10-year yield, filtered
    kk = D.dropna(subset=["dy"])
    kal = infer.kalman_regression(kk["r"].to_numpy(), kk["dy"].to_numpy() * 100, q=2e-6, r=float(kk["r"].var()))
    row, notes = ml.today_row(P, S, cape_now, y10_now)
    hedge["ctx_now"] = int((pred["models"]["hmm"]["w"][-1][int(np.argmin(pred["models"]["hmm"]["mu"][-1]))] > 0.5)) * 2 + int(D["trend"].iloc[-LAG + 1] > 0)
    hedge["ctx_label"] = ("stressed" if hedge["ctx_now"] >= 2 else "calm") + " regime, trend " + ("on" if hedge["ctx_now"] % 2 else "off")
    hedge["as_of"] = D.index[last_h].strftime("%Y-%m")
    now = today(D, pred, F, P, row, gamma, hedge)
    overlay = overlay_study(r, trend_sig, runs["gated"]["x"], m, gamma, bidx)
    dev = runs["engine"]["ret"] - D["r"].to_numpy()
    a_all, ta_all, n_all = timing_alpha(dev[start_i:], D["r"].to_numpy()[start_i:])
    ug, t_all, _ = utility_gain(runs["engine"]["ret"][start_i:], D["r"].to_numpy()[start_i:], gamma)
    g_now = gate_from_t(t_all)
    from scipy import stats as _st
    now["engine_exposure"] = now["exposure"]
    now["gate"] = {"value": g_now, "t": t_all, "t0": float(_st.norm.ppf(1 - 1 / N_TRIED)), "n_tried": N_TRIED, "utility_gain_month": ug,
                   "alpha_annual": a_all * 12, "alpha_t": ta_all, "months": n_all}
    now["exposure"] = float(round((1 + g_now * (now["engine_exposure"] - 1)) / 0.05) * 0.05)
    # the trend overlay, if the study adopted one: the gated size times the factor when the trend is off
    now["overlay"] = {"factor": overlay["adopted"], "trend_on": overlay["trend_on_now"], "reason": overlay["adopted_reason"],
                      "exposure_if_off": float(round(now["exposure"] * overlay["adopted"] / 0.05) * 0.05)}
    if not overlay["trend_on_now"]:
        now["exposure"] = now["overlay"]["exposure_if_off"]
    now["rl"] = {"v16": float(rl.ACTIONS[rl.act(rl.fit(rl.encode(Ds, len(Ds)), Ds["r"].to_numpy(), **{k: rl.CONFIGS["risk_averse_cautious_prior"][k] for k in ("gamma", "penalty", "prior")}),
                                                 int(rl.encode(Ds, len(Ds))[-1]), 2)]),
                 "conservative": rl2["now"]}
    now["inputs"] = {"features": {f: float(row[f]) for f in ml.FEATURES}, "notes": notes, "names": ml.NAMES}
    tc = lambda x: [round(float(v), 4) for v in x]
    step = 6
    curve_dates = [d.strftime("%Y-%m") for d in dates[::step]]
    lg = lambda x: tc(np.log(np.cumprod(1 + x))[::step])
    al = {d: i for i, d in enumerate(rl1["dates"])}
    al2 = {d: i for i, d in enumerate(rl2["dates"])}
    ds = [d.strftime("%Y-%m") for d in dates]
    common = [d for d in ds if d in al and d in al2]
    ci = [ds.index(d) for d in common]
    rl1r = np.array([rl1["ret"][al[d]] for d in common])
    rl2r = np.array([rl2["ret"][al2[d]] for d in common])
    out = {
        "schema": 1, "start": ds[0], "end": ds[-1], "months": int(m.sum()), "lag": LAG, "gamma": gamma, "es_limit": ES_LIMIT, "cost": COST, "borrow_annual": BORROW * 12,
        "pipeline": [
            {"stage": "Data", "what": f"{len(D):,} months of US stocks, {D.index[0].year} to {D.index[-1].strftime('%Y-%m')}; the 10-year yield and a 10-year bond's return to {D['b'].last_valid_index().strftime('%Y-%m')}"},
            {"stage": "Features", "what": f"{len(ml.FEATURES)} features knowable at the decision: valuation, the excess CAPE yield, rates, inflation, momentum, trend, volatility, drawdown"},
            {"stage": "Models", "what": f"{len(FORECASTS)} forecasters walked forward from {START} and stacked; a five-network ensemble with honest uncertainty"},
            {"stage": "Inference", "what": "Hidden Markov regimes, Bayesian changepoints, a Kalman stock-bond beta, models averaged by their recent predictive likelihood"},
            {"stage": "Decision", "what": f"Exposure that maximizes expected utility (risk aversion {gamma:.2f}, set so holding is optimal on average) inside a {ES_LIMIT:.0%} monthly expected-shortfall budget; hedge by regime; two RL checks"},
        ],
        "now": now,
        "forecast_scores": fsc,
        "forecast_weights_hist": {"dates": [F["index"][i].strftime("%Y-%m") for i in range(F["start"], len(F["index"]), 12)],
                                  **{k: tc(F["weights"][F["start"]::12, j]) for j, k in enumerate(FORECASTS)}},
        "model_weights_hist": {"dates": [D.index[t].strftime("%Y-%m") for t in range(start_i, len(D), 12)], **{k: tc(wm_hist[::12, j]) for j, k in enumerate(MODELS)}},
        "model_scores": {"mean_log_score": ll_mean, "names": MODEL_NAMES},
        "regime_fits": [{"at": D.index[f["at"]].strftime("%Y-%m"), "K": f["K"], "mu": tc(f["mu"]), "sd": tc(f["sd"])} for f in pred["regime_fits"]],
        "configs": configs, "deflated_excess": {k: (v if isinstance(v, str) else float(v)) for k, v in dsr.items()},
        "gate_hist": {"dates": curve_dates, "g": [round(float(v), 3) for v in runs["gated"]["gate"][m][::step]]},
        "hold": perf(hold), "trend": overlay["rows"]["hold:0.0"]["perf"], "overlay": overlay,    # one implementation of the trend rule (v0.24)
        "rl": {"v16": perf(rl1r), "conservative": perf(rl2r), "hold_same": perf(hold[ci]), "months": len(common), "conservative_avg_exposure": float(np.mean(rl2["act"]))},
        "curve": {"dates": curve_dates, "engine": lg(runs["engine"]["ret"][m]), "gated": lg(runs["gated"]["ret"][m]), "hold": lg(hold), "trend": lg(trend)},
        "exposure_hist": {"dates": curve_dates, "x": [float(v) for v in runs["engine"]["x"][m][::step]], "gated": [float(v) for v in runs["gated"]["x"][m][::step]]},
        "hedges": {"perf": hedge_perf, "names": HEDGE_NAMES, "start": D.index[np.flatnonzero(okh)[0]].strftime("%Y-%m"), "end": hedge["as_of"],
                   "share": {k: float(np.mean(hedge["pick"][okh] == j)) for j, k in enumerate(hedge["names"])}},
        "kalman": {"dates": [d.strftime("%Y-%m") for d in kk.index[::6]], "beta": tc(kal["b"][::6]), "se": tc(kal["se_b"][::6]),
                   "now": float(kal["b"][-1]), "now_se": float(kal["se_b"][-1]), "as_of": kk.index[-1].strftime("%Y-%m")},
    }
    out["findings"] = summary(out)
    return out


def _overlay_line(o: dict) -> str:
    """The trend rule, confronted as a baseline: what it earns, what it cuts, and what the engine adopts from it."""
    ov = o["overlay"]
    full, adopted = ov["rows"]["hold:0.0"], ov["rows"][f"hold:{ov['adopted']}"]
    hold = o["hold"]
    head = (f"The 10-month trend rule is the strongest simple baseline: Sharpe {full['perf']['sharpe']:.2f} against {hold['sharpe']:.2f} for holding and a worst drawdown of "
            f"{full['perf']['maxdd']:.0%} against {hold['maxdd']:.0%}, but it gives up real growth ({full['perf']['cagr']:.1%} against {hold['cagr']:.1%} a year), so a risk-averse "
            f"investor is no better off in expected utility (t {full['utility_t']:+.1f}); its Sharpe edge is not significant (90% range {full['sharpe_vs_hold']['lo']:+.2f} to "
            f"{full['sharpe_vs_hold']['hi']:+.2f}) while its drawdown cut is ({full['maxdd_vs_hold']['lo']:+.0%} to {full['maxdd_vs_hold']['hi']:+.0%}). ")
    w = ov.get("walk_forward")
    if ov["adopted"] >= 1.0 and w and ov.get("full_record_choice", 1.0) < 1.0:
        fb = ov["rows"][f"hold:{ov['full_record_choice']}"]
        return head + (f"On the full record the rule would pick a factor of {ov['full_record_choice']:.2f} (it keeps holding's expected utility, t {fb['utility_t']:+.2f}, and cuts the "
                       f"worst drawdown to {fb['perf']['maxdd']:.0%}), but the same rule walked forward, re-chosen every twelve months on the record to that point after a "
                       f"ten-year burn-in, costs expected utility (t {w['utility_t']:+.2f}; Sharpe {w['perf']['sharpe']:.2f}, worst drawdown {w['perf']['maxdd']:.0%}; the choice "
                       f"changed {w['factor_changes']} times). The engine holds itself to the walk-forward standard, so no overlay is adopted; the four scalings tried count among the "
                       f"{o['now']['gate']['n_tried']} strategies the gate deflates for, and the trend rule stays a cross-check.")
    if ov["adopted"] >= 1.0:
        return head + "No factor of the overlay kept holding's expected utility, so the engine adopts none of it."
    wf = (f" Walked forward (the factor re-chosen every twelve months on the record to that point, after a ten-year burn-in), the overlay's Sharpe is "
          f"{w['perf']['sharpe']:.2f} with a worst drawdown of {w['perf']['maxdd']:.0%} (gain over holding {w['sharpe_vs_hold']['lo']:+.2f} to {w['sharpe_vs_hold']['hi']:+.2f}; "
          f"utility t {w['utility_t']:+.2f}; the choice changed {w['factor_changes']} times, averaging {w['avg_factor']:.2f}); the four scalings count among the "
          f"{o['now']['gate']['n_tried']} strategies the gate deflates for.") if w else ""
    return head + (f"The engine therefore adopts the rule as a risk overlay at a factor of {ov['adopted']:.2f}: below the 10-month average the gated size is scaled by "
                   f"{ov['adopted']:.2f}, which keeps holding's expected utility (t {adopted['utility_t']:+.2f}), lifts the Sharpe ratio to {adopted['perf']['sharpe']:.2f} "
                   f"(90% range of the gain {adopted['sharpe_vs_hold']['lo']:+.2f} to {adopted['sharpe_vs_hold']['hi']:+.2f}) and cuts the worst drawdown to "
                   f"{adopted['perf']['maxdd']:.0%}.{wf} The trend is {'on' if ov['trend_on_now'] else 'off'} today, so the overlay "
                   f"{'leaves the size unchanged' if ov['trend_on_now'] else 'applies'}.")


def summary(o: dict) -> list[str]:
    n, e, h, t = o["now"], o["configs"]["engine"], o["hold"], o["trend"]
    sv = e["sharpe_vs_hold"]
    fs = o["forecast_scores"]
    dr = sorted(n["drivers"], key=lambda d: -abs(d["delta"]))
    top = dr[0] if dr and abs(dr[0]["delta"]) > 0 else None
    out = [
        f"Decision for the model book: {n['exposure']:.2f}x stocks. The engine's own choice is {n['engine_exposure']:.2f}x"
        + (" (held down by the risk budget)" if n["capped"] else "")
        + f". Walked forward since {o['start'][:4]}, its departures from 1x improved a risk-averse investor's utility with t {n['gate']['t']:.1f} "
        f"(the best of {n['gate']['n_tried']} useless strategies would show {n['gate']['t0']:.2f}; timing alpha {n['gate']['alpha_annual']:+.1%} a year, t {n['gate']['alpha_t']:.1f}), "
        f"so its evidence gate moves {n['gate']['value']:.0%} of the way from holding. Hedge: {n['hedge']['name'].lower()} ({n['hedge']['context']}). "
        f"Across {n['distribution']['draws']:,} draws over regimes, models and forecasts, {n['distribution']['p_below_1']:.0%} of the engine's choices are below 1x "
        f"and {n['distribution']['p_above_1']:.0%} above.",
        f"Regimes: {n['regime']['K']} states by BIC; the stressed state's probability for next month is {n['regime']['next'][n['regime']['worst']]:.0%}; "
        f"the chance a new regime began in the last six months is {n['changepoint']['recent']:.0%}.",
        f"Walked forward from {o['start'][:4]} with costs, the engine's Sharpe is {e['perf']['sharpe']:.2f} against {h['sharpe']:.2f} for holding and {t['sharpe']:.2f} for the trend rule "
        f"(gain over holding {sv['est']:+.2f}, 90% range {sv['lo']:+.2f} to {sv['hi']:+.2f}); worst drawdown {e['perf']['maxdd']:.0%} against {h['maxdd']:.0%}. "
        f"Gated by its own evidence, Sharpe {o['configs']['gated']['perf']['sharpe']:.2f}. Deflated for the {o['now']['gate']['n_tried']} strategies tried, the chance the best one's "
        f"timing alpha is real is {o['deflated_excess']['dsr']:.0%}.",
        _overlay_line(o),
        f"Forecasts out of sample: the neural-network ensemble's skill against the historical mean is {fs['nn']['skill']:+.1%} (Diebold-Mariano t {fs['nn']['dm']['t']:.1f}), "
        f"ridge {fs['ridge']['skill']:+.1%}, the restricted combination {fs['combo']['skill']:+.1%}, the stack {fs['stacked']['skill']:+.1%}; "
        f"the ensemble's 80% bands covered {fs['nn']['coverage80']:.0%} of outcomes.",
    ]
    if top:
        fl = n["flip"]
        parts = []
        if fl.get("raise_if_above") is not None:
            parts.append(f"rise if the stacked 12-month real return forecast topped {fl['raise_if_above']:.0%}")
        if fl.get("cut_if_below") is not None:
            parts.append(f"fall if the stacked 12-month real return forecast dropped below {fl['cut_if_below']:.0%}")
        if fl.get("cut_if_stress_prob_above") is not None:
            parts.append(f"fall if the stressed regime's probability passed {fl['cut_if_stress_prob_above']:.0%}")
        out.append(f"What moves the engine's own choice most: {top['part'][0].lower() + top['part'][1:]} (without it, {top['without']:.2f}x)."
                   + (" The optimum would " + "; it would ".join(parts) + "." if parts else ""))
    if n.get("evpi"):
        bp = n["evpi"]["ce_month"] * 1e4 * 12
        out.append(f"On the regime model's own numbers, knowing the regime for certain would be worth {bp:.0f} basis points a year in certainty-equivalent terms"
                   + (": little, so more regime research would not change the decision much." if bp < 50 else
                      (", yet the gate is shut: the model's confidence in its regimes has not shown up in results, which is the gap between a model's value and its record."
                       if n["gate"]["value"] == 0 else ", and the gate lets part of it through.")))
    return out


# ---------------------------------------------------------------- what if (the page's sliders and the mind's answers)
def what_if(n: dict, p_stress: float | None = None, r12: float | None = None, gamma: float | None = None, es: float | None | str = "default",
            t: float | None = None) -> dict:
    """Today's decision recomputed with one or more inputs changed: the stressed regime's odds for next month (the other
    states keep their proportions), the stacked 12-month real return forecast, the risk aversion, the risk budget (None
    turns it off) and the evidence t behind the gate. site/src/dxlive.js is the same function in the page."""
    M = n["mixture"]
    mw = [n["models"]["weights"][k] for k in MODELS]
    tilt = n["tilt"] if r12 is None else (r12 - n["forecasts"]["now"]["mean"]) / ml.H
    W, MU, SD = [], [], []
    for j, k in enumerate(MODELS):
        cw = list(M[k]["w"])
        if k == "hmm" and p_stress is not None:
            wk = n["regime"]["worst"]
            rest = 1 - cw[wk]
            cw = [p_stress if i == wk else (v / rest * (1 - p_stress) if rest > 1e-12 else (1 - p_stress) / (len(cw) - 1)) for i, v in enumerate(cw)]
        for i, v in enumerate(cw):
            W.append(mw[j] * v)
            MU.append(M[k]["mu"][i] + tilt)
            SD.append(M[k]["sd"][i])
    g_ = n["gamma"] if gamma is None else gamma
    es_ = n["es_limit"] if es == "default" else es
    gh = n.get("gh") or {}
    x, info = choose(np.array(W), np.array(MU), np.array(SD), g_, es_, np.array(gh["z"]) if gh else None, np.array(gh["w"]) if gh else None, n.get("borrow", BORROW))
    gate = n["gate"]["value"] if t is None else gate_from_t(t, n["gate"]["n_tried"])
    return {"optimum": x, "capped": info["capped"], "es_1x": info.get("es_1x"), "gate": gate, "decision": round(float(round((1 + gate * (x - 1)) / 0.05) * 0.05), 2),
            "tilt": tilt, "gamma": g_, "ce": [certainty_equivalent(float(u), g_) for u in info["u"]]}
