"""Reinforcement learning for position sizing, judged out of sample.

The agent chooses the stock exposure each month (0, 0.5, 1 or 1.5 times capital) from a state it could have known:
the trend (price against its 10-month average, acting a month late to undo Shiller's monthly averaging), volatility
and valuation terciles (thresholds from data up to that month only), the drawdown bucket, and its own last action.
Reward is the month's log growth of wealth after trading costs and the cost of borrowing above 1x, so maximizing it
is Kelly's objective, optionally minus a penalty on squared losses.

Because one investor's trades do not move the market, the state transition does not depend on the action except
through the last-action component: the problem is a contextual bandit with switching costs, and fitted Q iteration
on the empirical transitions (an offline, model-based RL method) solves it exactly on the training data. Values in
thin states are shrunk toward the all-month average with a pseudo-count prior, the standard guard against a
tabular agent memorizing a handful of months.

Walk-forward: retrain every 12 months on all earlier months, act on the next 12, from 1940. The agent is compared
with holding and with the 10-month trend rule on the same months, with a stationary-bootstrap test of the Sharpe
difference and a deflated Sharpe for the configurations tried.

v0.25: a configuration can pool the state (trend and drawdown only, six cells, so each cell holds roughly nine times
the months), learn on a CRRA utility whose risk aversion is fit so that holding 1x is optimal on the training months,
or hold 1x unless a bootstrap of the Q values says another action's advantage is significant. Every variant tried is
walked forward the same way and reported under "v25_trials"; only the pooled state passed (Sharpe gain over the
v0.24 agent with a 90% bootstrap range above zero) and joins the configurations.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import labs
from .core import cache

ACTIONS = (0.0, 0.5, 1.0, 1.5)
COST = 0.001            # 10bp per unit of exposure traded
BORROW = 0.02 / 12      # real cost of borrowing above 1x, per month
SEED = 13
CONFIGS = {"kelly": {"gamma": 0.9, "penalty": 0.0, "prior": 24}, "kelly_cautious_prior": {"gamma": 0.9, "penalty": 0.0, "prior": 120},
           "risk_averse": {"gamma": 0.9, "penalty": 4.0, "prior": 24}, "risk_averse_cautious_prior": {"gamma": 0.9, "penalty": 4.0, "prior": 120},
           # v0.25, adopted: the v0.24 headline agent on the pooled trend-and-drawdown state
           "risk_averse_cautious_prior_pooled": {"gamma": 0.9, "penalty": 4.0, "prior": 120, "states": "trend_dd"}}
V24_BEST = "risk_averse_cautious_prior"
SCHEMES = {"full": 54, "trend_vol": 6, "trend_dd": 6, "trend": 2}
# v0.25 variants walked forward and not adopted (see build()["v25_trials"]); each stays selectable as a configuration
V25_VARIANTS = {
    "hold_unless_significant": {"gamma": 0.9, "penalty": 4.0, "prior": 120, "significance": 1.645, "B": 20},
    "pooled_trend_vol": {"gamma": 0.9, "penalty": 4.0, "prior": 120, "states": "trend_vol"},
    "crra_utility": {"gamma": 0.9, "penalty": 4.0, "prior": 120, "utility": "crra"},
    "crra_hold_unless_significant": {"gamma": 0.9, "penalty": 4.0, "prior": 120, "utility": "crra", "significance": 1.645, "B": 20},
    "pooled_trend_vol_hold_unless_significant": {"gamma": 0.9, "penalty": 4.0, "prior": 120, "states": "trend_vol", "significance": 1.645, "B": 20},
    "pooled_trend_dd_kelly": {"gamma": 0.9, "penalty": 0.0, "prior": 24, "states": "trend_dd"},
    "pooled_trend_dd_kelly_cautious_prior": {"gamma": 0.9, "penalty": 0.0, "prior": 120, "states": "trend_dd"},
    "pooled_trend_dd_risk_averse": {"gamma": 0.9, "penalty": 4.0, "prior": 24, "states": "trend_dd"},
    "pooled_trend_dd_crra": {"gamma": 0.9, "penalty": 4.0, "prior": 120, "states": "trend_dd", "utility": "crra"},
    "pooled_trend_only": {"gamma": 0.9, "penalty": 4.0, "prior": 120, "states": "trend"},
}


def states(S: pd.DataFrame) -> pd.DataFrame:
    """Monthly base state, each part knowable at the start of the month it applies to."""
    r, px, _ = labs.total_return_index(S)
    px = px.reindex(r.index)
    ma = pd.Series(labs.sma(px.to_numpy(), 10), index=px.index)
    trend = (px > ma).shift(2).astype(float)                                  # acted on a month late
    vol = r.rolling(12).std().shift(1)
    cape = (S["px"] / S["cpi"]) / ((S["eps"] / S["cpi"]).shift(4).rolling(120, min_periods=120).mean())
    cape = cape.reindex(r.index).shift(1).ffill()               # Shiller's earnings stop before prices do: carry the last CAPE (Assumed)
    wealth = (1 + r).cumprod()
    dd = (wealth / wealth.cummax() - 1).shift(1)
    D = pd.DataFrame({"r": r, "trend": trend, "vol": vol, "cape": cape, "dd": dd}).dropna()
    return D


def _terciles(x: pd.Series, upto: int) -> tuple[float, float]:
    v = x.iloc[:upto]
    return float(v.quantile(1 / 3)), float(v.quantile(2 / 3))


def encode(D: pd.DataFrame, upto: int, scheme: str = "full") -> np.ndarray:
    """Base state with tercile thresholds from rows before `upto` only: 0..53 for the full state, or a pooled scheme
    (see SCHEMES and pool())."""
    v1, v2 = _terciles(D["vol"], upto)
    c1, c2 = _terciles(D["cape"], upto)
    vb = np.digitize(D["vol"].to_numpy(), [v1, v2])
    cb = np.digitize(D["cape"].to_numpy(), [c1, c2])
    db = np.digitize(-D["dd"].to_numpy(), [0.10, 0.25])
    full = (D["trend"].to_numpy().astype(int) * 27 + vb * 9 + cb * 3 + db).astype(int)
    return full if scheme == "full" else pool(full, scheme)


def pool(s, scheme: str):
    """Map full states (0..53) to a pooled scheme: trend_dd (trend x drawdown), trend_vol (trend x volatility), trend."""
    s = np.asarray(s, int)
    tr, vb, db = s // 27, (s // 9) % 3, s % 3
    if scheme == "full":
        return s
    if scheme == "trend_dd":
        return tr * 3 + db
    if scheme == "trend_vol":
        return tr * 3 + vb
    if scheme == "trend":
        return tr
    raise ValueError(f"unknown state scheme {scheme}")


def reward(a: float, prev: float, r: float, penalty: float = 0.0) -> float:
    g = a * r - COST * abs(a - prev) - max(0.0, a - 1.0) * BORROW
    g = max(g, -0.95)
    return math.log1p(g) - penalty * min(0.0, g) ** 2


def rewards(r: np.ndarray, penalty: float = 0.0) -> np.ndarray:
    """reward() for every month, last action and action at once: shape [t, p, a]."""
    A = np.array(ACTIONS)
    g = A[None, None, :] * r[:, None, None] - COST * np.abs(A[None, :] - A[:, None])[None] - np.maximum(0.0, A - 1.0)[None, None, :] * BORROW
    g = np.maximum(g, -0.95)
    return np.log1p(g) - penalty * np.minimum(0.0, g) ** 2


def crra_gamma(r: np.ndarray, hi: float = 60.0) -> float:
    """The relative risk aversion at which holding 1x is the unconditional optimum on these months' empirical returns:
    the root of E[r (1 + r)^-gamma] = 0 (the first-order condition of expected CRRA utility at exposure 1)."""
    r = np.asarray(r, float)
    f = lambda g: float(np.mean(r * (1 + r) ** (-g)))
    lo = 0.0
    if f(lo) <= 0:
        return lo
    if f(hi) > 0:
        return hi
    for _ in range(80):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if f(m) > 0 else (lo, m)
    return (lo + hi) / 2


def crra(g: np.ndarray, gamma_rra: float) -> np.ndarray:
    v = np.maximum(1 + np.asarray(g, float), 0.02)
    return np.log(v) if abs(gamma_rra - 1) < 1e-9 else (v ** (1 - gamma_rra) - 1) / (1 - gamma_rra)


def rewards_crra(r: np.ndarray, gamma_rra: float) -> np.ndarray:
    """CRRA utility of the month's wealth growth for every month, last action and action: shape [t, p, a]."""
    A = np.array(ACTIONS)
    g = A[None, None, :] * r[:, None, None] - COST * np.abs(A[None, :] - A[:, None])[None] - np.maximum(0.0, A - 1.0)[None, None, :] * BORROW
    return crra(np.maximum(g, -0.95), gamma_rra)


def fqi_batch(s: np.ndarray, sn: np.ndarray, R: np.ndarray, gamma: float, prior: float, n_states: int = 54, iters: int = 80) -> np.ndarray:
    """fqi() for B resamples at once: s, sn [B, T], R [B, T, p, a]; returns Q [B, n_states, p, a]."""
    nA = len(ACTIONS)
    B, T = s.shape
    flat = (np.arange(B)[:, None] * n_states + s).ravel()
    cnt = np.bincount(flat, minlength=B * n_states).astype(float).reshape(B, n_states)
    Q = np.zeros((B, n_states, nA, nA))
    rows = np.arange(B)[:, None]
    for _ in range(iters):
        V = Q.max(axis=3)                                       # [B, s, p]
        target = R + gamma * V[rows, sn][:, :, None, :].transpose(0, 1, 3, 2)
        tg = target.reshape(B * T, nA * nA)
        sums = np.stack([np.bincount(flat, weights=tg[:, j], minlength=B * n_states) for j in range(nA * nA)], axis=1).reshape(B, n_states, nA, nA)
        glob = target.mean(axis=1)                              # [B, p, a]
        Qn = (sums + prior * glob[:, None]) / (cnt[:, :, None, None] + prior)
        if np.max(np.abs(Qn - Q)) < 1e-10:
            return Qn
        Q = Qn
    return Q


def fqi(s: np.ndarray, sn: np.ndarray, R: np.ndarray, gamma: float, prior: float, n_states: int = 54, iters: int = 80) -> np.ndarray:
    """Fitted Q iteration on transitions (s -> sn) with rewards R[t, p, a]; thin states shrunk toward the all-month
    average with a pseudo-count prior. Q[s, p, a]."""
    return fqi_batch(np.asarray(s, int)[None], np.asarray(sn, int)[None], np.asarray(R)[None], gamma, prior, n_states, iters)[0]


def fit(b: np.ndarray, r: np.ndarray, gamma: float, penalty: float, prior: float, iters: int = 80, n_states: int = 54, utility: str = "penalty") -> np.ndarray:
    """Fitted Q iteration on the empirical model. Q[s, p, a]: base state s, last action p, action a. utility "crra"
    replaces the log-growth-minus-penalty reward with CRRA utility at crra_gamma() of these months."""
    T = len(r) - 1
    R = rewards_crra(r[:T], crra_gamma(r)) if utility == "crra" else rewards(r[:T], penalty)
    return fqi(np.asarray(b[:T], int), np.asarray(b[1:T + 1], int), R, gamma, prior, n_states, iters)


def significant(b: np.ndarray, r: np.ndarray, cfg: dict, n_states: int, rng: np.random.Generator) -> np.ndarray:
    """Which actions' advantage over holding 1x is significant: Q refit on B stationary-bootstrap resamples of the
    transitions; an action qualifies where its mean advantage exceeds z bootstrap standard deviations."""
    T = len(r) - 1
    R = rewards_crra(r[:T], crra_gamma(r)) if cfg.get("utility") == "crra" else rewards(r[:T], cfg["penalty"])
    ii = labs.stationary_bootstrap_idx(T, int(cfg.get("B", 20)), 12, rng)
    b = np.asarray(b, int)
    Qs = fqi_batch(b[ii], b[ii + 1], R[ii], cfg["gamma"], cfg["prior"], n_states)
    adv = Qs - Qs[:, :, :, 2:3]
    return adv.mean(0) > cfg["significance"] * np.maximum(adv.std(0, ddof=1), 1e-12)


def act(Q: np.ndarray, s: int, p: int) -> int:
    q = Q[s, p]
    best = np.flatnonzero(np.isclose(q, q.max(), rtol=0, atol=1e-12))
    return int(2 if 2 in best else best[0])                     # ties go to holding 1x


def act_significant(Q: np.ndarray, ok: np.ndarray, s: int, p: int) -> int:
    """The best action among those whose advantage over holding is significant; holding 1x otherwise."""
    cand = np.flatnonzero(ok[s, p])
    return int(cand[np.argmax(Q[s, p][cand])]) if len(cand) else 2


def walk_forward(D: pd.DataFrame, cfg: dict, start: int = 1940, refit: int = 12, seed: int = SEED) -> dict:
    """Retrain every `refit` months on earlier months only and act on the next block. cfg keys beyond gamma, penalty
    and prior (all optional): states (a SCHEMES key), utility ("penalty" or "crra"), significance (z) with B."""
    idx = D.index
    test = [i for i, d in enumerate(idx) if d.year >= start]
    r = D["r"].to_numpy()
    acts = np.full(len(D), np.nan)
    rets = np.full(len(D), np.nan)
    scheme = cfg.get("states", "full")
    nS = SCHEMES[scheme]
    rng = np.random.default_rng(seed)
    p = 2
    for k in range(0, len(test), refit):
        blk = test[k:k + refit]
        t0 = blk[0]
        b = encode(D, t0, scheme)
        Q = fit(b[:t0], r[:t0], cfg["gamma"], cfg["penalty"], cfg["prior"], n_states=nS, utility=cfg.get("utility", "penalty"))
        ok = significant(b[:t0], r[:t0], cfg, nS, rng) if cfg.get("significance") else None
        for i in blk:
            a = act(Q, b[i], p) if ok is None else act_significant(Q, ok, b[i], p)
            acts[i] = ACTIONS[a]
            rets[i] = ACTIONS[a] * r[i] - COST * abs(ACTIONS[a] - ACTIONS[p]) - max(0.0, ACTIONS[a] - 1) * BORROW
            p = a
    m = ~np.isnan(rets)
    return {"dates": [d.strftime("%Y-%m") for d in idx[m]], "ret": rets[m], "act": acts[m], "hold": r[m]}


def _perf(x: np.ndarray) -> dict:
    s = pd.Series(x)
    return labs.perf(s)


def trial_rows(name: str, x: np.ndarray, x0: np.ndarray, hold: np.ndarray, idx: np.ndarray, gamma_rra: float, adopted: bool) -> list[dict]:
    """A variant's Sharpe and CRRA certainty equivalent against the v0.24 agent on the same months, with stationary-
    bootstrap 90% ranges; "passes" means the range excludes zero. The CRRA gain is also shown against holding."""
    def ce(v):
        u = float(np.mean(crra(v, gamma_rra)))
        return 12 * ((math.exp(u) - 1) if abs(gamma_rra - 1) < 1e-9 else (1 + (1 - gamma_rra) * u) ** (1 / (1 - gamma_rra)) - 1)
    ds = np.array([labs.sharpe(x[i]) - labs.sharpe(x0[i]) for i in idx])
    du = np.array([ce(x[i]) - ce(x0[i]) for i in idx])
    rows = []
    for metric, before, after, d in (("Sharpe", labs.sharpe(x0), labs.sharpe(x), ds), ("CRRA certainty equivalent, annual", ce(x0), ce(x), du)):
        lo, hi = float(np.quantile(d, 0.05)), float(np.quantile(d, 0.95))
        sd = float(np.std(d, ddof=1))
        rows.append({"variant": name, "metric": metric, "before": float(before), "after": float(after), "t": float((after - before) / sd) if sd > 0 else 0.0,
                     "lo": lo, "hi": hi, "passes": bool(lo > 0), "adopted": adopted})
    rows[-1]["vs_hold"] = float(ce(x) - ce(hold))
    return rows


@cache.memo("rl.build", deps=("buildout.labs",), require=("dl",))
def build(dl: dict | None = None, B: int = 600, trials: bool = True) -> dict:
    from scipy import stats
    dl = dl or labs.download()
    S = labs.shiller(dl)
    D = states(S)
    res = {}
    for name, cfg in CONFIGS.items():
        res[name] = walk_forward(D, cfg)
    base = res["kelly"]
    dates = base["dates"]
    hold = base["hold"]
    trend = np.where(D.loc[pd.to_datetime(dates), "trend"].to_numpy() > 0, hold, 0.0)
    rng = np.random.default_rng(SEED)
    idx = labs.stationary_bootstrap_idx(len(hold), B, 12, rng)
    out = {"schema": 1, "actions": list(ACTIONS), "cost": COST, "borrow_annual": BORROW * 12, "start": dates[0], "months": len(dates), "configs": {}}
    for name, w in res.items():
        x = w["ret"]
        d = np.array([labs.sharpe(x[i]) - labs.sharpe(hold[i]) for i in idx])
        p = _perf(x)
        out["configs"][name] = {**CONFIGS[name], "perf": p, "avg_exposure": float(np.mean(w["act"])), "time_out": float(np.mean(w["act"] == 0)),
                                "time_levered": float(np.mean(w["act"] > 1)), "switches_per_year": float(np.mean(np.abs(np.diff(w["act"])) > 0) * 12),
                                "sharpe_vs_hold": {"est": float(labs.sharpe(x) - labs.sharpe(hold)), "lo": float(np.quantile(d, 0.05)), "hi": float(np.quantile(d, 0.95)),
                                                   "p_le0": float(np.mean(d <= 0))}}
    # v0.25 trials: every variant against the v0.24 headline agent, walked forward the same way
    gamma_rra = crra_gamma(D["r"].to_numpy()[:int(np.searchsorted(D.index.year, int(dates[0][:4])))])
    x0 = res[V24_BEST]["ret"]
    tried = {k: res[k]["ret"] for k in CONFIGS if k not in ("kelly", "kelly_cautious_prior", "risk_averse", V24_BEST)}
    if trials:
        for k, cfg in V25_VARIANTS.items():
            tried[k] = walk_forward(D, cfg)["ret"]
    out["v25_trials"] = [row for k, x in tried.items() for row in trial_rows(k, x, x0, hold, idx, gamma_rra, k in CONFIGS)]
    out["v25_gamma_rra"] = gamma_rra
    best = max(out["configs"], key=lambda k: out["configs"][k]["perf"]["sharpe"])
    xb = res[best]["ret"] - hold
    allx = [res[k]["ret"] for k in res] + [x for k, x in tried.items() if k not in res]     # every configuration and variant tried
    ex = np.array([(x - hold).mean() / (x - hold).std(ddof=1) if (x - hold).std(ddof=1) > 0 else 0.0 for x in allx])   # a variant identical to holding has no edge
    out["best"] = best
    out["n_tried"] = len(allx)
    out["deflated_excess"] = labs.deflated_sharpe(float(xb.mean() / xb.std(ddof=1)), len(allx), float(np.var(ex, ddof=1)), len(xb),
                                                  float(stats.skew(xb)), float(stats.kurtosis(xb, fisher=False)))
    out["hold"] = _perf(hold)
    out["trend"] = _perf(trend)
    # today's policy, trained on everything
    cfg = CONFIGS[best]
    scheme = cfg.get("states", "full")
    full = encode(D, len(D))
    b = pool(full, scheme)
    r_all = D["r"].to_numpy()
    Q = fit(b, r_all, cfg["gamma"], cfg["penalty"], cfg["prior"], n_states=SCHEMES[scheme], utility=cfg.get("utility", "penalty"))
    ok = significant(b, r_all, cfg, SCHEMES[scheme], np.random.default_rng(SEED)) if cfg.get("significance") else None
    choose = (lambda s, p: act(Q, s, p)) if ok is None else (lambda s, p: act_significant(Q, ok, s, p))
    last = D.iloc[-1]
    f_now = int(full[-1])
    s_now = int(b[-1])
    p_now = ACTIONS.index(res[best]["act"][-1]) if len(res[best]["act"]) else 2
    out["now"] = {"date": D.index[-1].strftime("%Y-%m"), "state": {"trend_on": bool(last["trend"] > 0), "vol_tercile": int((f_now // 9) % 3), "cape_tercile": int((f_now // 3) % 3),
                  "drawdown_bucket": int(f_now % 3)}, "states": scheme, "q": [float(v) for v in Q[s_now, p_now]], "action": ACTIONS[choose(s_now, p_now)]}
    out["policy"] = [{"trend_on": bool(s // 27), "vol": int((s // 9) % 3), "cape": int((s // 3) % 3), "dd": int(s % 3), "action": ACTIONS[choose(int(pool(s, scheme)), 2)],
                      "months": int((full == s).sum())} for s in range(54) if (full == s).sum() >= 6]
    out["curve"] = {"dates": dates[::6], "agent": [round(float(v), 4) for v in np.log(np.cumprod(1 + res[best]["ret"]))[::6]],
                    "hold": [round(float(v), 4) for v in np.log(np.cumprod(1 + hold))[::6]], "trend": [round(float(v), 4) for v in np.log(np.cumprod(1 + trend))[::6]]}
    out["findings"] = summary(out)
    return out


def summary(o: dict) -> list[str]:
    b = o["configs"][o["best"]]
    h, t = o["hold"], o["trend"]
    sv = b["sharpe_vs_hold"]
    n = o.get("n_tried", len(o["configs"]))
    f = [f"A reinforcement-learning sizing agent ({o['best'].replace('_', ' ')}, the best of {len(o['configs'])} configurations), retrained every year and judged "
         f"out of sample since {o['start'][:4]}: Sharpe {b['perf']['sharpe']:.2f} against {h['sharpe']:.2f} for holding and {t['sharpe']:.2f} for the trend rule; "
         f"worst drawdown {b['perf']['maxdd']:.0%} against {h['maxdd']:.0%}; real growth {b['perf']['cagr']:.1%} a year against {h['cagr']:.1%}.",
         f"Its Sharpe gain over holding is {sv['est']:+.2f} with a 90% bootstrap range of {sv['lo']:+.2f} to {sv['hi']:+.2f}; after deflating for the "
         f"{n} configurations and variants tried, the chance its edge over holding is real is {o['deflated_excess']['dsr']:.0%}.",
         f"It averaged {b['avg_exposure']:.2f}x exposure, sat out {b['time_out']:.0%} of months and levered {b['time_levered']:.0%}. "
         f"Today's state calls for {o['now']['action']:.1f}x."]
    tr = [r for r in o.get("v25_trials", []) if r["metric"] == "Sharpe"]
    cu = [r for r in o.get("v25_trials", []) if r["metric"] != "Sharpe"]
    if tr:
        ok = [r["variant"].replace("_", " ") for r in tr if r["passes"]]
        f.append(f"Version 0.25 walked forward {len(tr)} variants against the v0.24 agent (Sharpe {tr[0]['before']:.2f}): "
                 + (f"{', '.join(ok)} raised Sharpe with a 90% bootstrap range above zero" if ok else "none raised Sharpe with a 90% bootstrap range above zero")
                 + f". On CRRA utility (risk aversion {o['v25_gamma_rra']:.1f}, the level at which holding is optimal before {o['start'][:4]}) {sum(r['passes'] for r in cu)} beat the v0.24 agent "
                 f"with a range above zero, mostly by holding more stock, and {sum(r['vs_hold'] > 0 for r in cu)} beat holding itself.")
    return f
