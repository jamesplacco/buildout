"""The reasoner: from evidence to a sized, constrained, explainable choice, and to what is worth learning next.

    python -m buildout reason --out site/data          # writes reason.json (needs macro/report/research there, or uses defaults)

Six steps, each a pure function the page runs too (site/src/engine7.js; tests/test_v07.py checks they agree):

  1. posterior        prior over seven 3-month scenarios x the likelihood of what is observed now. Signals that share a
                      driver are grouped; inside a group the log-likelihoods are averaged, not added, so two readings
                      of one cause count once (tempered naive Bayes). Every number here is labelled Assumed.
  2. scenario_returns the 3-month return of a portfolio vector (equity, TLT hedge ratio, put-spread premium, gold)
                      in each scenario: factor betas, a duration-and-convexity bond, a Black-Scholes 95/85 put spread
                      bought at VIX + 3, financing on borrowed money.
  3. solve            the feasible portfolio with the highest expected log growth, subject to a worst-scenario loss
                      limit, max equity, max total gross and a premium budget (exhaustive grid: exact on the grid,
                      18,414 portfolios x 7 scenarios).
  4. alternatives     keep / reduce / hedge / optimal on the same scenarios, with regret and minimax regret.
  5. robust           the zero-sum game against Nature: mix the alternatives to maximize the worst expected return;
                      Nature's equilibrium mix is the scenario blend the book is most exposed to (linear program).
  6. value_of_info    for each signal, what learning it would be worth (expected value of sample information, in
                      certainty-equivalent basis points) and whether flipping it changes the choice.
  +  reverse_stress   the most plausible factor move that produces a given loss: s* = -L Sigma b / (b' Sigma b), with its
                      Mahalanobis distance, from measured covariances by regime.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from .analytics.options import bs

FACTORS = ["market", "ai", "dy", "oil", "gold"]
# Assumptions, not forecasts: seven 3-month states of the world. Their prior mixture is set so the AI book (1.15x the
# Nasdaq-100 plus the AI factor) earns about 2.4% a quarter with a 16% quarterly standard deviation and a fat left tail,
# close to the Nasdaq-100's record since 1999 scaled by the book's beta. The names follow the stress desk's scenarios.
SCENARIOS = [
    {"id": "base", "name": "Grind higher (base case)", "market": 0.06, "ai": 0.02, "dy": 0.0010, "oil": 0.00, "gold": 0.01, "prior": 0.52},
    {"id": "soft", "name": "Soft landing, cuts", "market": 0.07, "ai": 0.03, "dy": -0.0050, "oil": -0.05, "gold": 0.02, "prior": 0.12},
    {"id": "melt", "name": "AI melt-up, yields up", "market": 0.12, "ai": 0.10, "dy": 0.0040, "oil": 0.05, "gold": 0.00, "prior": 0.10},
    {"id": "termprem", "name": "AI financing / term-premium shock", "market": -0.08, "ai": -0.06, "dy": 0.0075, "oil": 0.00, "gold": 0.03, "prior": 0.09},
    {"id": "digest", "name": "AI capex digestion (growth scare)", "market": -0.12, "ai": -0.12, "dy": -0.0060, "oil": -0.10, "gold": 0.04, "prior": 0.07},
    {"id": "stagfl", "name": "Inflation + hikes (2022 replay)", "market": -0.15, "ai": -0.06, "dy": 0.0100, "oil": 0.25, "gold": 0.06, "prior": 0.06},
    {"id": "crash", "name": "Liquidity crash, everything sells", "market": -0.22, "ai": -0.08, "dy": 0.0025, "oil": -0.20, "gold": -0.04, "prior": 0.04},
]
# P(signal is on | scenario), in SCENARIOS order. Hypotheses, shown on the page and editable there.
SIGNALS = [
    {"id": "infl", "name": "36-month inflation at or above 2.75%", "cluster": "inflation", "lik": [0.40, 0.30, 0.50, 0.60, 0.30, 0.90, 0.40]},
    {"id": "corr", "name": "Stocks and bonds moving together (correlation above 0)", "cluster": "inflation", "lik": [0.40, 0.35, 0.55, 0.70, 0.25, 0.85, 0.50]},
    {"id": "oil", "name": "Brent at or above 1.3x its 5-year average", "cluster": "oil", "lik": [0.15, 0.15, 0.25, 0.20, 0.15, 0.70, 0.20]},
    {"id": "vix", "name": "VIX at or above 20", "cluster": "stress", "lik": [0.20, 0.20, 0.25, 0.50, 0.60, 0.55, 0.80]},
    {"id": "hy", "name": "High-yield spread at or above 4.5%", "cluster": "credit", "lik": [0.15, 0.15, 0.10, 0.40, 0.50, 0.45, 0.70]},
    {"id": "capex", "name": "Builders' capex above 80% of operating cash flow", "cluster": "ai", "lik": [0.50, 0.40, 0.60, 0.70, 0.70, 0.50, 0.50]},
    {"id": "curve", "name": "2s10s curve inverted", "cluster": "growth", "lik": [0.25, 0.35, 0.20, 0.20, 0.55, 0.45, 0.50]},
]
DEFAULTS = {"beta_market": 1.15, "beta_ai": 1.0, "tlt_duration": 16.5, "tlt_convexity": 360.0, "y30": 0.0485, "rf": 0.042,
            "borrow_spread": 0.01, "vix": 18.0, "skew_pts": 3.0, "horizon": 0.25,
            "max_loss": 0.15, "max_equity": 1.5, "max_gross": 2.0, "max_premium": 0.02}


# ---------------------------------------------------------------- 1. posterior
def posterior(priors: Sequence[float], signals: Sequence[dict], observed: dict) -> dict:
    """observed: {signal_id: True | False | None}. None (unknown) contributes nothing."""
    p = np.asarray(priors, float)
    p = p / p.sum()
    logp = np.log(p)
    groups: dict[str, list[np.ndarray]] = {}
    for s in signals:
        o = observed.get(s["id"])
        if o is None:
            continue
        lik = np.asarray(s["lik"], float)
        groups.setdefault(s["cluster"], []).append(np.log(lik if o else 1 - lik))
    contrib = {}
    for c, rows in groups.items():
        v = np.mean(rows, axis=0)               # one driver, one vote
        contrib[c] = v
        logp = logp + v
    post = np.exp(logp - logp.max())
    post = post / post.sum()
    return {"prior": p.tolist(), "posterior": post.tolist(), "log_contrib": {k: v.tolist() for k, v in contrib.items()}}


# ---------------------------------------------------------------- 2. scenario returns
def put_spread_cost(vix: float, horizon: float = 0.25, upper: float = 0.95, lower: float = 0.85, skew_pts: float = 3.0) -> float:
    v = (vix + skew_pts) / 100
    return float(bs(1.0, upper, horizon, 0.0, 0.0, v, "put")["price"] - bs(1.0, lower, horizon, 0.0, 0.0, v, "put")["price"])


def bond_return(dy: float, P: dict) -> float:
    return P["y30"] * P["horizon"] - P["tlt_duration"] * dy + 0.5 * P["tlt_convexity"] * dy * dy


def scenario_returns(port: Sequence[float], scen: Sequence[dict], P: dict, cost: float) -> list[float]:
    """port = (equity, hedge_ratio, premium, gold) in x NAV. Returns the 3-month portfolio return per scenario."""
    e, h, prem, g = port
    out = []
    for s in scen:
        stock = P["beta_market"] * s["market"] + P["beta_ai"] * s["ai"]
        bond = bond_return(s["dy"], P) - P["rf"] * P["horizon"]          # the hedge is financed
        m = 1 + s["market"]
        payoff = max(0.0, 0.95 - m) - max(0.0, 0.85 - m)
        puts = (prem / cost) * payoff - prem if cost > 0 else 0.0
        cash = 1 - e - g - prem
        carry = cash * (P["rf"] + (P["borrow_spread"] if cash < 0 else 0.0)) * P["horizon"]
        out.append(e * stock + e * h * bond + puts + g * s["gold"] + carry)
    return out


def _grid():
    for i in range(31):
        for j in range(11):
            for k in range(9):
                for l in range(6):
                    yield (i / 20, j / 10, k / 400, l / 50)


def _feasible(port, rets, P) -> bool:
    e, h, prem, g = port
    return bool(min(rets) >= -P["max_loss"] - 1e-12 and e <= P["max_equity"] + 1e-12 and e * (1 + h) + g <= P["max_gross"] + 1e-12
            and prem <= P["max_premium"] + 1e-12)


def _elog(rets, w) -> float:
    return float(sum(wi * math.log1p(max(r, -0.999999)) for wi, r in zip(w, rets)))


# ---------------------------------------------------------------- 3. solve
def solve(post: Sequence[float], scen: Sequence[dict], P: dict, fix_equity: float | None = None, allow: str = "ehpg",
          loss_limit: bool = True) -> dict | None:
    """Exhaustive search of the grid; returns the feasible portfolio with the highest expected log growth."""
    cost = put_spread_cost(P["vix"], P["horizon"], skew_pts=P["skew_pts"])
    best = None
    for port in _grid():
        e, h, prem, g = port
        if fix_equity is not None and abs(e - fix_equity) > 1e-9:
            continue
        if ("h" not in allow and h) or ("p" not in allow and prem) or ("g" not in allow and g):
            continue
        rets = scenario_returns(port, scen, P, cost)
        if not _feasible(port, rets, P if loss_limit else {**P, "max_loss": 10.0}):
            continue
        u = _elog(rets, post)
        if best is None or u > best["elog"] + 1e-12:
            best = {"port": list(port), "elog": u, "rets": rets}
    return best


def evaluate(port: Sequence[float], post: Sequence[float], scen: Sequence[dict], P: dict) -> dict:
    cost = put_spread_cost(P["vix"], P["horizon"], skew_pts=P["skew_pts"])
    rets = scenario_returns(port, scen, P, cost)
    u = _elog(rets, post)
    return {"port": list(port), "rets": rets, "elog": u, "ce": math.expm1(u), "worst": min(rets),
            "mean": float(np.dot(post, rets)), "feasible": _feasible(port, rets, P)}


# ---------------------------------------------------------------- 3b. robust to being wrong about the odds (v0.10)
"""Distributionally robust choice. The posterior over scenarios is itself an estimate. Instead of maximizing expected
log growth under it, maximize the WORST expected log growth over every distribution Q within a Kullback-Leibler
radius rho of it: inf_{KL(Q||P) <= rho} E_Q[u] = sup_{lam > 0} [-lam rho - lam log E_P exp(-u / lam)] (the convex dual).
rho = 0 is the ordinary solver; as rho grows the answer slides toward the worst single scenario (maximin). The
worst-case odds Q* are an exponential tilt of P toward the scenarios that hurt this portfolio most."""
GOLD = (math.sqrt(5) - 1) / 2
DRO_ITERS = 80
DRO_T = (-12.0, 8.0)          # log lambda search bracket


def _dro_g(t, U, p, umin, rho):
    lam = np.exp(t)
    s = np.sum(p * np.exp(-(U - umin[..., None]) / lam[..., None]), axis=-1)
    return umin - lam * rho - lam * np.log(s)


def kl_worst(u, p, rho: float) -> dict:
    """Worst expected u over KL(Q||P) <= rho, for one vector u (or a matrix of rows, vectorized)."""
    U = np.atleast_2d(np.asarray(u, float))
    p = np.asarray(p, float)
    if rho <= 0:
        v = U @ p
        return {"value": v if np.ndim(u) > 1 else float(v[0]), "lam": None, "q": p.tolist()}
    sup = p > 0
    umin = np.where(sup, U, np.inf).min(axis=1)
    a = np.full(len(U), DRO_T[0])
    b = np.full(len(U), DRO_T[1])
    c = b - GOLD * (b - a)
    d = a + GOLD * (b - a)
    fc = _dro_g(c, U, p, umin, rho)
    fd = _dro_g(d, U, p, umin, rho)
    for _ in range(DRO_ITERS):
        m = fc > fd
        b = np.where(m, d, b)
        a = np.where(m, a, c)
        nc = np.where(m, c, d)
        nf = np.where(m, fc, fd)
        newpt = np.where(m, b - GOLD * (b - a), a + GOLD * (b - a))
        fnew = _dro_g(newpt, U, p, umin, rho)
        c, d = np.where(m, newpt, nc), np.where(m, nc, newpt)
        fc, fd = np.where(m, fnew, nf), np.where(m, nf, fnew)
    tm = (a + b) / 2
    val = np.maximum(_dro_g(tm, U, p, umin, rho), umin)
    lam = np.exp(tm)
    if np.ndim(u) > 1:
        return {"value": val, "lam": lam}
    w = p * np.exp(-(U[0] - umin[0]) / lam[0])
    return {"value": float(val[0]), "lam": float(lam[0]), "q": (w / w.sum()).tolist()}


def _feasible_grid(scen, P):
    cost = put_spread_cost(P["vix"], P["horizon"], skew_pts=P["skew_pts"])
    ports, R = [], []
    for port in _grid():
        rets = scenario_returns(port, scen, P, cost)
        if _feasible(port, rets, P):
            ports.append(port)
            R.append(rets)
    return ports, np.array(R)


def solve_robust(post, scen, P: dict, rho: float, _cache=None) -> dict | None:
    ports, R = _cache or _feasible_grid(scen, P)
    if not ports:
        return None
    U = np.log1p(np.maximum(R, -0.999999))
    vals = kl_worst(U, post, rho)["value"] if rho > 0 else U @ np.asarray(post, float)
    i = 0
    for k in range(1, len(ports)):           # first strict improvement wins, as in the nominal solver
        if vals[k] > vals[i] + 1e-12:
            i = k
    w = kl_worst(U[i], post, rho)
    return {"port": list(ports[i]), "value": float(vals[i]), "ce": math.expm1(float(vals[i])), "nominal_elog": float(U[i] @ np.asarray(post, float)),
            "rets": R[i].tolist(), "q_worst": w["q"], "rho": rho}


def max_scenario_odds(p: float, rho: float) -> float:
    """The highest probability one scenario can take within KL radius rho of its posterior probability p."""
    if rho <= 0 or p >= 1:
        return p
    kl = lambda q: q * math.log(q / p) + (1 - q) * math.log((1 - q) / (1 - p))  # noqa: E731
    lo, hi = p, 1 - 1e-12
    if kl(hi) <= rho:
        return hi
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if kl(mid) <= rho else (lo, mid)
    return lo


RHO_SWEEP = [0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]


def robustness_sweep(post, scen, P: dict, rhos=RHO_SWEEP) -> dict:
    cache = _feasible_grid(scen, P)
    rows = []
    nominal = solve_robust(post, scen, P, 0.0, cache)
    for r in rhos:
        sr = solve_robust(post, scen, P, r, cache)
        rows.append({"rho": r, "port": sr["port"], "worst_case_ce": sr["ce"], "nominal_ce": math.expm1(sr["nominal_elog"]),
                     "price_bp": (nominal["nominal_elog"] - sr["nominal_elog"]) * 1e4, "q_worst": sr["q_worst"]})
    changes = [rows[i]["rho"] for i in range(1, len(rows)) if rows[i]["port"] != rows[i - 1]["port"]]
    return {"rows": rows, "first_change_rho": changes[0] if changes else None}


# ---------------------------------------------------------------- 4. alternatives
def _r20(x: float) -> int:
    """Nearest grid step of 0.05, halves rounded up (the same in JavaScript's Math.round)."""
    return int(math.floor(min(max(x, 0.0), 1.5) * 20 + 0.5))


def alternatives(post, scen, P, current: Sequence[float]) -> dict:
    """Keep the exposure, reduce it until the loss limit holds, hedge it at the same equity, or the free optimum."""
    keep = evaluate(current, post, scen, P)
    cost = put_spread_cost(P["vix"], P["horizon"], skew_pts=P["skew_pts"])
    red = None
    for i in range(_r20(current[0]), -1, -1):                     # largest equity, no hedges, that meets the limit
        port = (i / 20, 0.0, 0.0, 0.0)
        if _feasible(port, scenario_returns(port, scen, P, cost), P):
            red = evaluate(port, post, scen, P)
            break
    e0 = _r20(current[0]) / 20
    hed = solve(post, scen, P, fix_equity=e0) or solve(post, scen, P, fix_equity=e0, loss_limit=False)   # best hedge, limit unmet
    opt = solve(post, scen, P)
    out = {"keep": keep, "reduce": red, "hedge": evaluate(hed["port"], post, scen, P) if hed else None,
           "optimal": evaluate(opt["port"], post, scen, P) if opt else None}
    names = [k for k, v in out.items() if v]
    R = np.array([out[k]["rets"] for k in names])
    regret = R.max(axis=0) - R                                     # per scenario, vs the best alternative there
    for k, rg in zip(names, regret):
        out[k]["max_regret"] = float(rg.max())
    out["minimax_regret"] = names[int(np.argmin(regret.max(axis=1)))]
    return out


# ---------------------------------------------------------------- 5. robust: a zero-sum game against Nature
def simplex_max(c: Sequence[float], A: Sequence[Sequence[float]], b: Sequence[float]) -> tuple[list[float], float, list[float]]:
    """max c.x s.t. A x <= b, x >= 0, b >= 0 (dense tableau, Bland's rule). Returns (x, optimum, dual prices).
    Small problems only; mirrors engine7.js."""
    m, n = len(A), len(c)
    T = [list(map(float, A[i])) + [1.0 if j == i else 0.0 for j in range(m)] + [float(b[i])] for i in range(m)]
    z = [-float(x) for x in c] + [0.0] * m + [0.0]
    basis = [n + i for i in range(m)]
    for _ in range(500):
        col = next((j for j in range(n + m) if z[j] < -1e-12), None)
        if col is None:
            break
        ratios = [(T[i][-1] / T[i][col], basis[i], i) for i in range(m) if T[i][col] > 1e-12]
        if not ratios:
            raise ValueError("unbounded")
        _, _, r = min(ratios)
        pv = T[r][col]
        T[r] = [x / pv for x in T[r]]
        for i in range(m):
            if i != r and abs(T[i][col]) > 0:
                f = T[i][col]
                T[i] = [a - f * bb for a, bb in zip(T[i], T[r])]
        f = z[col]
        z = [a - f * bb for a, bb in zip(z, T[r])]
        basis[r] = col
    x = [0.0] * (n + m)
    for i, bi in enumerate(basis):
        x[bi] = T[i][-1]
    return x[:n], z[-1], z[n:n + m]


def zero_sum(M: Sequence[Sequence[float]]) -> dict:
    """Row player maximizes M[i][j]; the column player (Nature) minimizes. Exact, by one linear program.

    Shift M so every entry is positive (B = M + k). Nature's problem: max sum(w) s.t. B w <= 1, w >= 0; then
    y = w / sum(w) and the value is 1 / sum(w) - k. The row player's optimal mix is the LP's dual prices, normalized.
    """
    A = np.asarray(M, float)
    k = 1.0 - A.min()
    B = A + k
    w, opt, dual = simplex_max([1.0] * B.shape[1], B.tolist(), [1.0] * B.shape[0])
    sw = sum(w)
    sd = sum(dual)
    return {"row": [d / sd for d in dual], "col": [wi / sw for wi in w], "value": float(1.0 / sw - k)}


def robust(alts: dict, post: Sequence[float]) -> dict:
    names = [k for k in ("keep", "reduce", "hedge", "optimal") if alts.get(k)]
    M = [alts[k]["rets"] for k in names]
    g = zero_sum(M)
    return {"names": names, "mix": g["row"], "nature": g["col"], "value": g["value"],
            "mixed_port": [float(sum(x * alts[k]["port"][i] for x, k in zip(g["row"], names))) for i in range(4)]}


# ---------------------------------------------------------------- 6. value of information
def value_of_info(priors, signals, observed, scen, P) -> dict:
    """EVPI on the grid, and per signal: EVSI (certainty-equivalent bp) and whether flipping it flips the choice."""
    base = posterior(priors, signals, observed)["posterior"]
    best = solve(base, scen, P)
    per_scen = [solve([1.0 if j == i else 0.0 for j in range(len(scen))], scen, P) for i in range(len(scen))]
    evpi = sum(pi * b["elog"] for pi, b in zip(base, per_scen)) - best["elog"]
    rows = []
    for s in signals:
        rest = {k: v for k, v in observed.items() if k != s["id"]}
        post0 = np.array(posterior(priors, signals, rest)["posterior"])
        p_on = float(np.dot(post0, s["lik"]))
        u0 = solve(post0.tolist(), scen, P)["elog"]
        pre = 0.0
        choice = {}
        for o, po in ((True, p_on), (False, 1 - p_on)):
            post_o = posterior(priors, signals, rest | {s["id"]: o})["posterior"]
            b = solve(post_o, scen, P)
            pre += po * b["elog"]
            choice[o] = b["port"]
        cur = observed.get(s["id"])
        flipped = None if cur is None else choice[not cur] != choice[cur]
        rows.append({"id": s["id"], "name": s["name"], "p_on": p_on, "evsi_bp": (pre - u0) * 1e4, "observed": cur,
                     "flip_changes_choice": flipped, "choice_if_on": choice[True], "choice_if_off": choice[False]})
    rows.sort(key=lambda r: -r["evsi_bp"])
    return {"evpi_bp": evpi * 1e4, "signals": rows}


# ---------------------------------------------------------------- + reverse stress
def exposure_vector(port: Sequence[float], P: dict) -> list[float]:
    """First-order sensitivity of the 3-month return to each factor in FACTORS (market, ai, dy, oil, gold)."""
    e, h, prem, g = port
    return [e * P["beta_market"], e * P["beta_ai"], -e * h * P["tlt_duration"], 0.0, g]


def reverse_stress(b: Sequence[float], cov: Sequence[Sequence[float]], loss: float) -> dict:
    """The single most likely factor move (minimum Mahalanobis distance) that loses `loss`, to first order."""
    S = np.asarray(cov, float)
    bv = np.asarray(b, float)
    q = float(bv @ S @ bv)
    if q <= 0:
        return {"shock": [0.0] * len(bv), "sigmas": float("inf"), "p_normal": 0.0}
    shock = -loss * (S @ bv) / q
    d = loss / math.sqrt(q)
    return {"shock": shock.tolist(), "sigmas": d, "p_normal": 0.5 * math.erfc(d / math.sqrt(2)), "port_sd": math.sqrt(q)}


def factor_cov(raw: dict, horizon_months: int = 3) -> dict:
    """Measured covariance of monthly moves (market = S&P, dy = 10-year yield in decimals, oil, gold) by regime,
    scaled to the horizon; the AI factor has no long free history: 25% a year, uncorrelated with the rest (Assumed)."""
    from .brain import REGIMES, changes
    from .research import tidy
    df = changes(tidy(raw))
    df = df.assign(y10=df["y10"] / 100)
    out = {}
    for name, (a, b) in REGIMES.items():
        d = df.loc[a:b] if b else df.loc[a:]
        C = d[["eq", "y10", "oil", "gold"]].cov().to_numpy() * horizon_months
        full = np.zeros((5, 5))
        idx = [0, 2, 3, 4]
        for i, ii in enumerate(idx):
            for j, jj in enumerate(idx):
                full[ii, jj] = C[i, j]
        full[1, 1] = 0.25 ** 2 * horizon_months / 12
        out[name] = {"months": int(len(d)), "cov": full.round(10).tolist()}
    return {"factors": FACTORS, "horizon_months": horizon_months, "regimes": out}


def observe(macro: dict | None, research: dict | None, fund_capex_ocf: float | None) -> dict:
    """Signal states from the engine's own files; anything missing stays None (unknown), never False."""
    def lv(k):
        try:
            return macro["rates"]["levels"][k]["value"]
        except (TypeError, KeyError):
            return None
    obs = {k: None for k in ("infl", "corr", "oil", "vix", "hy", "capex", "curve")}
    try:
        obs["infl"] = macro["macro_state"]["inflation"]["avg36"] >= 0.0275
    except (TypeError, KeyError):
        pass
    try:
        obs["corr"] = macro["latest"]["corr63"] > 0
    except (TypeError, KeyError):
        pass
    for k, key, at in (("vix", "vix", 20.0), ("hy", "hy_oas", 4.5)):
        v = lv(key)
        obs[k] = None if v is None else v >= at
    c2 = lv("c2s10s")
    obs["curve"] = None if c2 is None else c2 < 0
    obs["capex"] = None if fund_capex_ocf is None else fund_capex_ocf > 0.8
    return obs


def run(observed: dict, P: dict | None = None, current: Sequence[float] = (1.0, 0.0, 0.0, 0.0), cov: dict | None = None,
        priors: Sequence[float] | None = None) -> dict:
    P = {**DEFAULTS, **(P or {})}
    pri = priors or [s["prior"] for s in SCENARIOS]
    post = posterior(pri, SIGNALS, observed)
    alts = alternatives(post["posterior"], SCENARIOS, P, current)
    rob = robust(alts, post["posterior"])
    voi = value_of_info(pri, SIGNALS, observed, SCENARIOS, P)
    rev = None
    if cov:
        b = exposure_vector(alts["keep"]["port"], P)
        rev = {k: reverse_stress(b, v["cov"], P["max_loss"]) for k, v in cov["regimes"].items()}
    return {"schema": 1, "observed": observed, "params": P, "scenarios": SCENARIOS, "signals": SIGNALS, "posterior": post,
            "alternatives": alts, "robust": rob, "value_of_info": voi, "reverse_stress": rev, "factor_cov": cov,
            "labels": {"scenarios": "Assumed", "likelihoods": "Hypothesis", "signals": "Observed", "cov": "Estimated"}}


# ---------------------------------------------------------------- the daily file
BUILDERS = {"MSFT": (6.0, 0.09), "GOOGL": (6.0, 0.09), "AMZN": (5.0, 0.09), "META": (5.5, 0.09), "ORCL": (5.0, 0.11)}
P_OBS = 0.40   # Hypothesis: annual gross profit per $ of AI capacity at today's build rate


def build(folder) -> dict:
    """Read the engine's other outputs from `folder`, observe the signals, reason, and play the games."""
    import json
    from pathlib import Path

    from . import games

    def load(n):
        try:
            return json.loads((Path(folder) / f"{n}.json").read_text())
        except (OSError, ValueError):
            return None
    macro, research, brain, capex, report = (load(n) for n in ("macro", "research", "brain", "capex", "report"))
    ttm = (capex or {}).get("ttm") or {}
    rows = {t: ttm[t] for t in BUILDERS if isinstance(ttm.get(t), dict) and ttm[t].get("capex") and ttm[t].get("ocf")}
    ratio = (sum(r["capex"] for r in rows.values()) / sum(r["ocf"] for r in rows.values())) if len(rows) == len(BUILDERS) else None
    obs = observe(macro, research, ratio)
    S = (report or {}).get("summary") or {}
    current = (float(S.get("recommended_gross", 1.0) or 1.0), float(S.get("hedge_ratio_now", 0.0) or 0.0), 0.0, 0.0)
    P = {}
    try:
        P["vix"] = float(macro["rates"]["levels"]["vix"]["value"])
    except (TypeError, KeyError):
        pass
    out = run(obs, P, current, (brain or {}).get("factor_cov"))
    game = None
    if len(rows) == len(BUILDERS):
        q = [rows[t]["capex"] for t in BUILDERS]
        c = [1 / life + wacc for life, wacc in BUILDERS.values()]
        cg = games.capex_game(q, c, P_OBS)
        game = {"tickers": list(BUILDERS), "capex": q, "costs": c, "p_obs": P_OBS, "model": cg,
                "dilemma": games.capex_dilemma(cg["calibration"]["a"], cg["calibration"]["b"], float(np.mean(c)), len(c))}
    out["games"] = {"capex": game, "basis": "builders' trailing-twelve-month capex from SEC filings (capex.json)" if game else "capex.json unavailable"}
    return out
