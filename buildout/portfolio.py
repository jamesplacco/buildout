"""The portfolio decision engine: stocks, 10-year Treasuries, gold and cash decided together, from regimes that know how
the assets move with each other; a learner that chooses between whole decision processes; and a simulator of the
decades ahead.

    data        real monthly returns since 1871: the S&P 500 with dividends (Shiller), a 10-year Treasury bought at par
                and held a month (Shiller's long rate, then the GS10 series to 2026), gold (London price), and cash at
                zero real (Shiller has no bill rate; a stated assumption)
    regimes     a hidden Markov model of the three risky returns together, full covariance, the number of states by
                BIC, refit every five years with a warm start and read forward only; so each regime carries its own
                stock-bond correlation, which is the question behind the TLT hedge
    allocation  the mix on a grid (stocks 0 to 1.5, bonds 0 to 1, gold 0 to 0.3, the rest cash, borrowing above 1x at
                2% real) that maximizes expected CRRA utility of next month's real wealth under the regime mixture,
                integrated exactly on a 343-point Gauss-Hermite grid per state, inside a 12% monthly expected-shortfall
                budget; risk aversion is the decision engine's, set on 1871 to 1939 data
    gate        the move from the model book (all stocks) toward that mix is scaled by the engine's own walked-forward
                utility gain over holding, deflated for the policies tried
    meta        exponential weights (Hedge) over six whole policies (hold, 60/40, risk parity, the trend rule, the
                regime allocation and its stock-only twin), each judged on its log growth month by month; the learner's
                regret against the best policy in hindsight is bounded in advance
    simulate    5,000 paths of ten years from a regime-switching bootstrap: states follow the fitted chain from today's
                odds, and each month's three returns are a real historical month drawn from the same state, so fat
                tails and cross-asset correlation come from history, not from a formula
    stress      today's mixes replayed through eight named drawdowns since 1929

Every walked-forward decision uses data known two months earlier and pays 10 basis points per unit traded. This is a
model-book research engine. It never places orders.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import decide, infer, labs
from .core import cache

ASSETS = ("stocks", "bonds", "gold")
NAMES = {"stocks": "US stocks", "bonds": "10-year Treasuries", "gold": "Gold", "cash": "Cash"}
START = 1940
LAG = decide.LAG
REFIT = 60
COST, BORROW = decide.COST, decide.BORROW
ES_LIMIT = decide.ES_LIMIT
N0 = decide.N0
SEED = 23
GRID_S = np.round(np.arange(0.0, 1.51, 0.1), 2)
GRID_B = np.round(np.arange(0.0, 1.01, 0.1), 2)
GRID_G = np.round(np.arange(0.0, 0.31, 0.1), 2)
MAX_GROSS = 1.5
GOLD_FROM = "1976-08"   # gold traded at a fixed price until August 1971; it enters a decision once five free years are known
EPISODES = [("The Depression", "1929-09", "1932-06"), ("1937 to 1938", "1937-03", "1938-03"), ("Inflation of 1946 to 1948", "1946-05", "1948-02"),
            ("The 1973 to 1974 bear market", "1973-01", "1974-09"), ("Volcker's tightening", "1980-11", "1982-07"), ("The dot-com bust", "2000-08", "2002-09"),
            ("The financial crisis", "2007-10", "2009-02"), ("The 2022 rate shock", "2022-01", "2022-09")]


# ---------------------------------------------------------------- data
def _gh_month(df: pd.DataFrame, col: str) -> pd.Series:
    d = pd.to_datetime(df.iloc[:, 0].astype(str).str.slice(0, 7) + "-01")
    s = pd.Series(pd.to_numeric(df[col], errors="coerce").to_numpy(), index=d)
    return s[~s.index.duplicated(keep="last")].sort_index()


def panel(S: pd.DataFrame, gh: dict) -> tuple[pd.DataFrame, dict]:
    """Monthly real returns of stocks, bonds and gold (and the yield behind the bonds), with where each series ends."""
    r, px, _ = labs.total_return_index(S)
    y = S["y10"].copy()
    notes = {"shiller_y10_to": y.last_valid_index().strftime("%Y-%m")}
    if gh and "y10" in gh:
        g10 = _gh_month(gh["y10"], "Rate").reindex(S.index)
        y = y.where(y.notna(), g10)                       # Shiller's long rate is the GS10; the mirror carries it on
        notes["y10_to"] = y.last_valid_index().strftime("%Y-%m")
    SS = pd.DataFrame({"y10": y, "cpi": S["cpi"]})
    b = decide.bond_returns(SS)
    infl = S["cpi"] / S["cpi"].shift(1)
    gold = None
    if gh and "gold" in gh:
        gp = _gh_month(gh["gold"], "Price").reindex(S.index)
        gold = (gp / gp.shift(1)) / infl - 1
        notes["gold_to"] = gp.last_valid_index().strftime("%Y-%m")
    D = pd.DataFrame({"stocks": r, "bonds": b.reindex(r.index), "gold": gold.reindex(r.index) if gold is not None else np.nan,
                      "y10": y.reindex(r.index)}).dropna(subset=["stocks", "bonds", "gold"])
    ma = pd.Series(labs.sma(px.reindex(D.index).to_numpy(), 10), index=D.index)
    D["trend"] = (px.reindex(D.index) > ma).astype(float)
    notes["start"], notes["end"] = D.index[0].strftime("%Y-%m"), D.index[-1].strftime("%Y-%m")
    return D, notes


# ---------------------------------------------------------------- allocation
def grid() -> np.ndarray:
    G = np.array([(s, b, g) for s in GRID_S for b in GRID_B for g in GRID_G if s + b + g <= MAX_GROSS + 1e-9])
    return G


GH1, GW1 = np.polynomial.hermite_e.hermegauss(7)
GW1 = GW1 / GW1.sum()
ZQ = np.array(np.meshgrid(GH1, GH1, GH1, indexing="ij")).reshape(3, -1).T          # 343 nodes
WQ = np.einsum("i,j,k->ijk", GW1, GW1, GW1).ravel()


def crra(v: np.ndarray, gamma: float) -> np.ndarray:
    v = np.maximum(v, 0.02)
    return np.log(v) if abs(gamma - 1) < 1e-9 else (v ** (1 - gamma) - 1) / (1 - gamma)


def port_returns(G: np.ndarray, R: np.ndarray) -> np.ndarray:
    """Portfolio returns for every allocation (rows of G) and scenario (rows of R), cash at zero real and borrowing
    above 1x at the borrowing rate: [M, N]."""
    lev = np.maximum(G.sum(1) - 1, 0.0)
    return G @ R.T - (lev * BORROW)[:, None]


def state_nodes(mu: np.ndarray, S: np.ndarray) -> np.ndarray:
    """The quadrature points of each state's normal: [K, 343, 3]."""
    return np.stack([mu[k] + ZQ @ np.linalg.cholesky(S[k]).T for k in range(len(mu))])


class Chooser:
    """Precomputes, for one fitted regime model, each allocation's expected utility and return scenarios per state, so
    a month's choice is a weighted sum and a short check of the risk budget."""

    def __init__(self, mu: np.ndarray, S: np.ndarray, gamma: float, G: np.ndarray | None = None):
        self.G = grid() if G is None else G
        self.gamma = gamma
        self.nodes = state_nodes(mu, S)
        self.P = np.stack([port_returns(self.G, self.nodes[k]) for k in range(len(mu))])      # [K, M, 343]
        self.U = (crra(1 + self.P, gamma) * WQ[None, None, :]).sum(2)                          # [K, M]

    def es(self, w: np.ndarray, rows: np.ndarray, alpha: float = 0.05) -> np.ndarray:
        """Expected shortfall (a positive loss) of the mixture for the given allocation rows."""
        vals = self.P[:, rows, :].transpose(1, 0, 2).reshape(len(rows), -1)                    # [m, K*343]
        wt = (w[:, None] * WQ[None, :]).ravel()
        o = np.argsort(vals, axis=1)
        v = np.take_along_axis(vals, o, 1)
        cw = np.cumsum(wt[o], axis=1)
        out = np.empty(len(rows))
        for i in range(len(rows)):                                # the node that crosses alpha counts in part
            j = int(np.searchsorted(cw[i], alpha))
            ww = wt[o[i, :j + 1]].copy()
            ww[-1] -= max(0.0, ww.sum() - alpha)
            out[i] = -float((v[i, :j + 1] * ww).sum() / max(ww.sum(), 1e-12))
        return out

    def choose(self, w: np.ndarray, es_limit: float | None = ES_LIMIT, top: int = 60, allowed: np.ndarray | None = None) -> tuple[int, dict]:
        eu = w @ self.U
        if allowed is not None:
            eu = np.where(allowed, eu, -np.inf)
        order = np.argsort(-eu)
        info = {"eu": eu}
        if es_limit is None:
            return int(order[0]), info
        for k0 in range(0, len(order), top):
            rows = order[k0:k0 + top]
            rows = rows[np.isfinite(eu[rows])]
            if not len(rows):
                break
            es = self.es(w, rows)
            ok = np.flatnonzero(es <= es_limit + 1e-12)
            if len(ok):
                i = int(rows[ok[0]])
                info["capped"] = bool(i != int(order[0]))
                info["es"] = float(es[ok[0]])
                return i, info
        i = int(np.flatnonzero((self.G == 0).all(1))[0])
        info["capped"] = True
        return i, info


def shrink_states(m: dict, X: np.ndarray, n0: float = N0) -> tuple[np.ndarray, np.ndarray]:
    """Each state's mean pulled toward the long-run mean with n0 pseudo-months; its covariance widened by the remaining
    uncertainty in the mean."""
    if m["K"] == 1:
        return m["mu"], m["S"]
    n = infer.stationary(m["A"]) * len(X)
    lam = n / (n + n0)
    mu = X.mean(0) + lam[:, None] * (m["mu"] - X.mean(0))
    S = m["S"] * (1 + 1 / (n + n0))[:, None, None]
    return mu, S


# ---------------------------------------------------------------- the walk
def regime_walk(X: np.ndarray, start: int, refit: int = REFIT, Ks=(2, 3, 4)) -> dict:
    T = len(X)
    out = {"w": [None] * T, "fit": [None] * T, "fits": []}
    prev: dict | None = None
    for t0 in range(start, T, refit):
        upto = t0 - LAG + 1
        sel = infer.mvhmm_select(X[:upto], Ks=Ks, init=prev, starts=2, iters=120)
        m = dict(sel["best"])
        prev = m
        m["mu_s"], m["S_s"] = shrink_states(m, X[:upto])
        out["fits"].append({"at": t0, "K": m["K"]})
        hi = min(T, t0 + refit)
        alpha = infer.mvhmm_filter(X[:hi - LAG + 1], m)
        A2 = np.linalg.matrix_power(m["A"], LAG)
        for t in range(t0, hi):
            out["w"][t] = alpha[t - LAG] @ A2
            out["fit"][t] = m
    return out


def run_policy(X: np.ndarray, alloc: np.ndarray, start: int) -> dict:
    """Returns of an allocation path [T, 3] with costs on turnover and borrowing above 1x."""
    T = len(X)
    ret = np.full(T, np.nan)
    prev = alloc[start] if np.isfinite(alloc[start]).all() else np.array([1.0, 0, 0])
    for t in range(start, T):
        a = alloc[t]
        lev = max(a.sum() - 1, 0.0)
        ret[t] = float(a @ X[t]) - COST * float(np.abs(a - prev).sum()) - lev * BORROW
        prev = a
    return {"ret": ret, "alloc": alloc}


def policies(D: pd.DataFrame, walk: dict, gamma: float, start: int) -> tuple[dict, dict]:
    """Every policy's allocation path, decided with data known LAG months earlier."""
    X = D[list(ASSETS)].to_numpy()
    T = len(X)
    P: dict[str, np.ndarray] = {}
    P["hold"] = np.tile([1.0, 0.0, 0.0], (T, 1))
    P["sixty_forty"] = np.tile([0.6, 0.4, 0.0], (T, 1))
    rp = np.full((T, 3), np.nan)
    gold_ok = (D.index >= pd.Timestamp(GOLD_FROM + "-01"))
    for t in range(start, T):
        v = X[max(0, t - LAG - 35):t - LAG + 1].std(0)
        iv = 1 / np.maximum(v, 1e-4)
        if not gold_ok[t]:
            iv[2] = 0.0
        rp[t] = iv / iv.sum()
    P["risk_parity"] = rp
    tr = D["trend"].shift(LAG).to_numpy()
    P["trend"] = np.column_stack([np.where(tr > 0, 1.0, 0.0), np.zeros(T), np.zeros(T)])
    G = grid()
    stock_only = (G[:, 1] == 0) & (G[:, 2] == 0)
    no_gold = G[:, 2] == 0
    eng = np.full((T, 3), np.nan)
    eng_s = np.full((T, 3), np.nan)
    capped = np.zeros(T, bool)
    cache_c: dict[int, Chooser] = {}
    for t in range(start, T):
        m = walk["fit"][t]
        key = id(m)
        if key not in cache_c:
            cache_c.clear()
            cache_c[key] = Chooser(m["mu_s"], m["S_s"], gamma, G)
        C = cache_c[key]
        i, info = C.choose(walk["w"][t], allowed=None if gold_ok[t] else no_gold)
        eng[t] = G[i]
        capped[t] = info.get("capped", False)
        j, _ = C.choose(walk["w"][t], allowed=stock_only)
        eng_s[t] = G[j]
    P["regime"] = eng
    P["regime_stocks"] = eng_s
    return P, {"capped": capped}


def gate_series(ret: np.ndarray, hold: np.ndarray, gamma: float, start: int) -> np.ndarray:
    g = np.full(len(ret), np.nan)
    for t in range(start, len(ret)):
        lo = t - LAG + 1
        _, tt, _ = decide.utility_gain(ret[start:lo], hold[start:lo], gamma)
        g[t] = decide.gate_from_t(tt, N_TRIED)
    return g


N_TRIED = 9          # six policies, the gated engine, the learner, and the stock-only decision engine of v0.19


def meta_learner(R: dict, start: int, names: list[str]) -> dict:
    """Hedge over whole policies: the loss of a policy in a month is minus its log growth; the learning rate is the
    one that bounds regret for losses within [-0.35, 0.35] over the horizon, fixed in advance, not tuned."""
    T = len(next(iter(R.values()))["ret"])
    L = np.column_stack([-np.log1p(np.maximum(R[k]["ret"], -0.9)) for k in names])
    L[:start] = np.nan
    n = T - start
    eta = math.sqrt(8 * math.log(len(names)) / n) / 0.7
    W = np.full((T, len(names)), np.nan)
    # weights at t use losses known by t - LAG
    Lk = np.vstack([np.full((LAG - 1, len(names)), np.nan), L[:-(LAG - 1)]]) if LAG > 1 else L
    W[start:] = infer.hedge_weights(np.nan_to_num(Lk[start:], nan=0.0), eta)
    return {"W": W, "eta": eta, "bound_logwealth": math.log(len(names)) / eta + eta * n * 0.7 ** 2 / 8}


# ---------------------------------------------------------------- simulate
def simulate(X: np.ndarray, m: dict, labels: np.ndarray, p0: np.ndarray, allocs: dict, months: int = 120, paths: int = 5000, seed: int = SEED,
             rebalance_cost: bool = True) -> dict:
    """Regime-switching bootstrap: a state path from the fitted chain starting at today's odds; each month's returns
    are a historical month drawn from the months the model put in that state."""
    rng = np.random.default_rng(seed)
    K = m["K"]
    pools = [np.flatnonzero(labels == k) for k in range(K)]
    pools = [p if len(p) else np.arange(len(X)) for p in pools]
    A = m["A"]
    cA = np.cumsum(A, 1)
    s = rng.choice(K, size=paths, p=p0 / p0.sum())
    idx = np.empty((paths, months), int)
    for t in range(months):
        if t:
            u = rng.random(paths)
            s = (u[:, None] > cA[s]).sum(1)
            s = np.minimum(s, K - 1)
        for k in range(K):
            sel = np.flatnonzero(s == k)
            if len(sel):
                idx[sel, t] = pools[k][rng.integers(0, len(pools[k]), len(sel))]
    R = X[idx]                                                                              # [paths, months, 3]
    out = {}
    for name, a in allocs.items():
        a = np.asarray(a, float)
        r = R @ a - max(a.sum() - 1, 0.0) * BORROW
        W = np.cumprod(1 + np.maximum(r, -0.99), axis=1)
        dd = (W / np.maximum.accumulate(W, axis=1) - 1).min(1)
        hz = {}
        for h in (12, 36, 60, 120):
            if h <= months:
                wh = W[:, h - 1]
                ann = wh ** (12 / h) - 1
                hz[str(h)] = {"q05": float(np.quantile(wh, 0.05)), "q25": float(np.quantile(wh, 0.25)), "q50": float(np.median(wh)), "q75": float(np.quantile(wh, 0.75)),
                              "q95": float(np.quantile(wh, 0.95)), "p_loss": float(np.mean(wh < 1)), "ann_median": float(np.median(ann))}
        fan = {q: [float(v) for v in np.quantile(W[:, 2::3], q, axis=0)] for q in (0.05, 0.25, 0.5, 0.75, 0.95)}
        out[name] = {"horizons": hz, "p_dd30": float(np.mean(dd < -0.30)), "p_dd50": float(np.mean(dd < -0.50)), "dd_median": float(np.median(dd)),
                     "es_month": float(-np.mean(np.sort(r.ravel())[: max(1, int(0.05 * r.size))])), "fan": {f"q{int(q * 100):02d}": v for q, v in fan.items()}}
    out["_meta"] = {"paths": paths, "months": months, "fan_months": list(range(3, months + 1, 3))}
    return out


def replay(D: pd.DataFrame, allocs: dict) -> list[dict]:
    rows = []
    for name, a, b in EPISODES:
        seg = D.loc[a:b, list(ASSETS)]
        if len(seg) < 2:
            continue
        r = {k: float(np.prod(1 + seg.to_numpy() @ np.asarray(v) - max(np.sum(v) - 1, 0) * BORROW) - 1) for k, v in allocs.items()}
        rows.append({"name": name, "start": a, "end": b, "months": len(seg), "returns": r,
                     "assets": {k: float(np.prod(1 + seg[k].to_numpy()) - 1) for k in ASSETS}})
    return rows


# ---------------------------------------------------------------- build
def describe_states(m: dict, mu_s: np.ndarray) -> list[dict]:
    out = []
    for k in range(m["K"]):
        S = m["S"][k]
        sd = np.sqrt(np.diag(S))
        corr = S / np.outer(sd, sd)
        out.append({"mu": (m["mu"][k] * 12).tolist(), "mu_shrunk": (mu_s[k] * 12).tolist(), "vol": (sd * math.sqrt(12)).tolist(),
                    "corr_sb": float(corr[0, 1]), "corr_sg": float(corr[0, 2]), "corr_bg": float(corr[1, 2]),
                    "persistence_months": float(1 / max(1 - m["A"][k, k], 1e-9))})
    # names from what each state does: the worst stock mean is stressed, the best a calm bull; of the rest, one where
    # Treasuries earned over 4% a year real is a bond rally, otherwise one with stock volatility above 16% is turbulent, else quiet
    order = list(np.argsort([s["mu"][0] for s in out]))
    used: set[str] = set()
    for i, k in enumerate(order):
        if i == 0:
            nm = "Stressed"
        elif i == len(order) - 1:
            nm = "Calm bull"
        else:
            nm = "Bond rally" if out[k]["mu"][1] > 0.04 else ("Turbulent" if out[k]["vol"][0] > 0.16 else "Quiet")
        base, n_ = nm, 2
        while nm in used:
            nm = f"{base} {n_}"
            n_ += 1
        used.add(nm)
        out[k]["name"] = nm
    return out


@cache.memo("portfolio.build", deps=("buildout.infer", "buildout.decide", "buildout.labs"), require=("dl", "gh"))
def build(dl: dict | None = None, gh: dict | None = None, quick: bool = False) -> dict:
    from scipy import stats
    dl = dl or labs.download()
    S = labs.shiller(dl)
    D, notes = panel(S, gh or {})
    X = D[list(ASSETS)].to_numpy()
    T = len(X)
    start = int(np.searchsorted(D.index.year, START))
    gamma = decide.calibrate_gamma(D["stocks"].to_numpy()[:start])
    walk = regime_walk(X, start, refit=120 if quick else REFIT)
    P, extra = policies(D, walk, gamma, start)
    R = {k: run_policy(X, a, start) for k, a in P.items()}
    hold = R["hold"]["ret"]
    g = gate_series(R["regime"]["ret"], hold, gamma, start)
    ga = np.full((T, 3), np.nan)
    for t in range(start, T):
        ga[t] = np.array([1.0, 0, 0]) + g[t] * (P["regime"][t] - np.array([1.0, 0, 0]))
    P["gated"] = ga
    R["gated"] = run_policy(X, ga, start)
    names = ["hold", "sixty_forty", "risk_parity", "trend", "regime", "regime_stocks"]
    ML = meta_learner(R, start, names)
    ma = np.full((T, 3), np.nan)
    for t in range(start, T):
        ma[t] = ML["W"][t] @ np.vstack([P[k][t] for k in names])
    P["meta"] = ma
    R["meta"] = run_policy(X, ma, start)
    sl = slice(start, T)
    rng = np.random.default_rng(SEED)
    bidx = labs.stationary_bootstrap_idx(T - start, 400 if quick else 800, 12, rng)
    perf = {}
    for k, v in R.items():
        x = v["ret"][sl]
        d = np.array([labs.sharpe(x[i]) - labs.sharpe(hold[sl][i]) for i in bidx])
        ug, ut, _ = decide.utility_gain(x, hold[sl], gamma)
        p = labs.perf(pd.Series(x))
        perf[k] = {**{kk: float(vv) for kk, vv in p.items()}, "avg": {a: float(np.nanmean(P[k][sl][:, i])) for i, a in enumerate(ASSETS)},
                   "sharpe_vs_hold": {"est": float(labs.sharpe(x) - labs.sharpe(hold[sl])), "lo": float(np.quantile(d, 0.05)), "hi": float(np.quantile(d, 0.95))},
                   "utility_t": ut, "ce_gain_annual": 12 * float(ug)}
    # the deflated test is on each policy's return in excess of holding stocks, not on its own Sharpe
    srs = {k: float(np.mean(R[k]["ret"][sl] - hold[sl]) / np.std(R[k]["ret"][sl] - hold[sl], ddof=1)) for k in R if k not in ("hold", "gated")}
    best_k = max(srs, key=srs.get)
    xb = R[best_k]["ret"][sl] - hold[sl]
    dsr = labs.deflated_sharpe(srs[best_k], N_TRIED, float(np.var(list(srs.values()), ddof=1)), len(xb), float(stats.skew(xb)), float(stats.kurtosis(xb, fisher=False)))
    dsr = {"best": best_k, **{k: float(v) for k, v in dsr.items()}}
    # today: the model on everything, read to the last month
    selN = infer.mvhmm_select(X, Ks=(2, 3, 4), starts=3, iters=200)
    m = dict(selN["best"])
    mu_s, S_s = shrink_states(m, X)
    alpha = infer.mvhmm_filter(X, m)
    w_next = alpha[-1] @ m["A"]
    smooth = infer.mvhmm_smooth(X, m)
    labels = infer.mvviterbi(X, m)
    C = Chooser(mu_s, S_s, gamma)
    i_opt, info = C.choose(w_next)
    opt = C.G[i_opt]
    stock_only = (C.G[:, 1] == 0) & (C.G[:, 2] == 0)
    i_s, _ = C.choose(w_next, allowed=stock_only)
    # the gate looks at every policy, not only the engine's own: the one with the strongest utility evidence over holding
    # is the candidate, and it moves the book only as far as that evidence, deflated for the policies tried, allows
    cand = {"regime": opt, "meta": P["meta"][-1], "sixty_forty": P["sixty_forty"][-1], "risk_parity": P["risk_parity"][-1],
            "trend": np.array([1.0 if D["trend"].iloc[-1] > 0 else 0.0, 0, 0]), "regime_stocks": C.G[i_s]}
    best_pol = max(cand, key=lambda k: perf[k]["utility_t"])
    gate_now = decide.gate_from_t(perf[best_pol]["utility_t"], N_TRIED)
    final = np.array([1.0, 0, 0]) + gate_now * (np.asarray(cand[best_pol]) - np.array([1.0, 0, 0]))
    final = np.round(final / 0.05) * 0.05
    drivers = []
    for j, a in enumerate(ASSETS[1:], start=1):
        allowed = C.G[:, j] == 0
        ii, _ = C.choose(w_next, allowed=allowed)
        drivers.append({"part": f"Without {NAMES[a].lower()}", "mix": C.G[ii].tolist()})
    ii, _ = C.choose(w_next, es_limit=None)
    drivers.append({"part": "Without the risk budget", "mix": C.G[ii].tolist()})
    for k in range(m["K"]):
        e = np.zeros(m["K"])
        e[k] = 1
        ii, _ = C.choose(e)
        drivers.append({"part": f"If certain of state {k}", "state": k, "mix": C.G[ii].tolist()})
    ws = [0.0, 0.25, 0.5, 0.75, 1.0]
    worst = int(np.argmin(m["mu"][:, 0]))
    stress_path = []
    for p_ in np.linspace(0, 1, 21):
        ww = w_next * (1 - p_) / max(1e-12, 1 - w_next[worst]) if w_next[worst] < 1 else np.full(m["K"], 0.0)
        ww = np.where(np.arange(m["K"]) == worst, p_, ww * (1 - (np.arange(m["K"]) == worst)))
        ww = ww / ww.sum()
        ii, _ = C.choose(ww)
        stress_path.append({"p": float(p_), "mix": C.G[ii].tolist()})
    del ws
    allocs = {"decision": final.tolist(), "optimum": opt.tolist(), "hold": [1.0, 0, 0], "sixty_forty": [0.6, 0.4, 0.0],
              "risk_parity": P["risk_parity"][-1].tolist(), "meta": P["meta"][-1].tolist()}
    sim = simulate(X, m, labels, alpha[-1], {k: allocs[k] for k in ("decision", "optimum", "hold", "sixty_forty", "risk_parity", "meta")}, paths=2000 if quick else 5000)
    rep = replay(D, {k: allocs[k] for k in ("decision", "optimum", "hold", "sixty_forty", "risk_parity", "meta")})
    states = describe_states(m, mu_s)
    step = 6
    dates = [d.strftime("%Y-%m") for d in D.index]
    tc = lambda a: [round(float(v), 4) for v in a]
    lg = lambda x: tc(np.log(np.cumprod(1 + x[sl]))[::step])
    out = {
        "schema": 1, "notes": notes, "start": dates[start], "end": dates[-1], "months": T - start, "gamma": gamma, "es_limit": ES_LIMIT, "n_tried": N_TRIED,
        "assets": list(ASSETS), "names": NAMES,
        "now": {"date": dates[-1], "K": m["K"], "bic": {str(k): float(v) for k, v in selN["bic"].items()}, "states": states, "now": alpha[-1].tolist(), "next": w_next.tolist(),
                "worst": worst, "optimum": opt.tolist(), "stocks_only": C.G[i_s].tolist(), "gate": gate_now, "gate_policy": best_pol,
                "gate_t": perf[best_pol]["utility_t"], "gate_t0": float(stats.norm.ppf(1 - 1 / N_TRIED)), "decision": final.tolist(), "capped": bool(info.get("capped", False)),
                "es_optimum": info.get("es"), "drivers": drivers, "stress_path": stress_path, "meta_weights": {k: float(ML["W"][-1][i]) for i, k in enumerate(names)},
                "meta_mix": P["meta"][-1].tolist(), "risk_parity_mix": P["risk_parity"][-1].tolist(),
                "history": {"dates": dates[::3], "p_worst": tc(smooth[::3, worst]), "filtered": tc(alpha[::3, worst])}},
        "perf": perf, "deflated": dsr, "meta": {"eta": ML["eta"], "bound": ML["bound_logwealth"], "names": names,
                                               "hist": {"dates": dates[start::12], **{k: tc(ML["W"][start::12, i]) for i, k in enumerate(names)}}},
        "curve": {"dates": dates[start::step], **{k: lg(R[k]["ret"]) for k in ("hold", "sixty_forty", "risk_parity", "trend", "regime", "gated", "meta")}},
        "alloc_hist": {"dates": dates[start::step], **{a: tc(P["regime"][start::step, i]) for i, a in enumerate(ASSETS)}},
        "gate_hist": {"dates": dates[start::step], "g": tc(g[start::step])},
        "time_capped": float(np.mean(extra["capped"][sl])),
        "simulation": sim, "stress": rep, "allocs": allocs,
        "regime_fits": walk["fits"],
    }
    out["findings"] = summary(out)
    return out


def _mix(a) -> str:
    s, b, g = a
    c = 1 - s - b - g
    parts = [f"{s:.0%} stocks"] + ([f"{b:.0%} Treasuries"] if b > 1e-9 else []) + ([f"{g:.0%} gold"] if g > 1e-9 else [])
    parts.append(f"{c:.0%} cash" if c > 1e-9 else (f"{-c:.0%} borrowed" if c < -1e-9 else ""))
    return ", ".join(p for p in parts if p)


def summary(o: dict) -> list[str]:
    n, P = o["now"], o["perf"]
    st = n["states"]
    w = n["next"]
    cur = int(np.argmax(w))
    sim = o["simulation"]
    gp = n["gate_policy"].replace("_", " ").replace("sixty forty", "60/40")
    out = [
        f"Portfolio decision for the model book: {_mix(n['decision'])}. The regime optimum is {_mix(n['optimum'])}. Of the {len(o['meta']['names'])} policies walked forward since "
        f"{o['start'][:4]}, the one with the strongest evidence of making a risk-averse investor better off than holding stocks is {gp} (utility t {n['gate_t']:.1f}, against "
        f"{n['gate_t0']:.1f} expected from the best of {o['n_tried']} useless ones), so the gate moves {n['gate']:.0%} of the way toward it.",
        f"Regimes: {n['K']} states of stocks, bonds and gold together. Next month is most likely {st[cur]['name'].lower()} ({w[cur]:.0%}), where stocks and Treasuries "
        f"have moved with a correlation of {st[cur]['corr_sb']:+.2f}; in the stressed state ({w[n['worst']]:.0%}) it is {st[n['worst']]['corr_sb']:+.2f}.",
        f"Walked forward with costs since {o['start'][:4]}: Sharpe {P['regime']['sharpe']:.2f} for the regime allocation, {P['gated']['sharpe']:.2f} gated, "
        f"{P['meta']['sharpe']:.2f} for the learner over six policies, against {P['hold']['sharpe']:.2f} for holding stocks, {P['sixty_forty']['sharpe']:.2f} for 60/40 "
        f"and {P['risk_parity']['sharpe']:.2f} for risk parity; worst drawdowns {P['regime']['maxdd']:.0%}, {P['meta']['maxdd']:.0%}, {P['hold']['maxdd']:.0%}, {P['sixty_forty']['maxdd']:.0%}.",
        f"Deflated for the {o['n_tried']} policies tried, the chance the best one ({o['deflated']['best'].replace('_', ' ')}) has a real edge in Sharpe is {o['deflated']['dsr']:.0%}.",
    ]
    h10 = sim["hold"]["horizons"]["120"]
    s10 = sim["sixty_forty"]["horizons"]["120"]
    out.append(f"Simulated ten years from today's regime odds ({sim['_meta']['paths']:,} paths of historical months drawn by state): all stocks end at a median "
               f"{h10['q50']:.2f}x real (5% to 95%: {h10['q05']:.2f}x to {h10['q95']:.2f}x) with a {sim['hold']['p_dd30']:.0%} chance of a drawdown deeper than 30%; "
               f"60/40 at {s10['q50']:.2f}x ({s10['q05']:.2f}x to {s10['q95']:.2f}x) with {sim['sixty_forty']['p_dd30']:.0%}.")
    worst_ep = min(o["stress"], key=lambda r: r["returns"]["hold"]) if o["stress"] else None
    if worst_ep:
        out.append(f"Replayed through {worst_ep['name'][0].lower() + worst_ep['name'][1:]} ({worst_ep['start']} to {worst_ep['end']}), today's mixes return, in real terms: all stocks "
                   f"{worst_ep['returns']['hold']:+.0%}, 60/40 {worst_ep['returns']['sixty_forty']:+.0%}, risk parity {worst_ep['returns']['risk_parity']:+.0%}, "
                   f"the regime optimum {worst_ep['returns']['optimum']:+.0%}.")
    return out
