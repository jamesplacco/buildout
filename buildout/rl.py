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
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import labs

ACTIONS = (0.0, 0.5, 1.0, 1.5)
COST = 0.001            # 10bp per unit of exposure traded
BORROW = 0.02 / 12      # real cost of borrowing above 1x, per month
SEED = 13
CONFIGS = {"kelly": {"gamma": 0.9, "penalty": 0.0, "prior": 24}, "kelly_cautious_prior": {"gamma": 0.9, "penalty": 0.0, "prior": 120},
           "risk_averse": {"gamma": 0.9, "penalty": 4.0, "prior": 24}, "risk_averse_cautious_prior": {"gamma": 0.9, "penalty": 4.0, "prior": 120}}


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


def encode(D: pd.DataFrame, upto: int) -> np.ndarray:
    """Base state 0..53 with tercile thresholds from rows before `upto` only."""
    v1, v2 = _terciles(D["vol"], upto)
    c1, c2 = _terciles(D["cape"], upto)
    vb = np.digitize(D["vol"].to_numpy(), [v1, v2])
    cb = np.digitize(D["cape"].to_numpy(), [c1, c2])
    db = np.digitize(-D["dd"].to_numpy(), [0.10, 0.25])
    return (D["trend"].to_numpy().astype(int) * 27 + vb * 9 + cb * 3 + db).astype(int)


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


def fit(b: np.ndarray, r: np.ndarray, gamma: float, penalty: float, prior: float, iters: int = 80) -> np.ndarray:
    """Fitted Q iteration on the empirical model. Q[s, p, a]: base state s, last action p, action a."""
    nA, nS = len(ACTIONS), 54
    T = len(r) - 1
    R = rewards(r[:T], penalty)                                 # reward for month t given (last action, action)
    Q = np.zeros((nS, nA, nA))
    cnt = np.bincount(b[:T], minlength=nS).astype(float)
    for _ in range(iters):
        V = Q.max(axis=2)                                       # V[s, p]
        target = R + gamma * V[b[1:T + 1]][:, None, :].transpose(0, 2, 1)   # [t, p, a]: next state's value with last action a
        sums = np.zeros((nS, nA, nA))
        np.add.at(sums, b[:T], target)
        glob = target.mean(axis=0)                              # the all-month average, the prior's center
        Qn = (sums + prior * glob[None]) / (cnt[:, None, None] + prior)
        if np.max(np.abs(Qn - Q)) < 1e-10:
            Q = Qn
            break
        Q = Qn
    return Q


def act(Q: np.ndarray, s: int, p: int) -> int:
    q = Q[s, p]
    best = np.flatnonzero(np.isclose(q, q.max(), rtol=0, atol=1e-12))
    return int(2 if 2 in best else best[0])                     # ties go to holding 1x


def walk_forward(D: pd.DataFrame, cfg: dict, start: int = 1940, refit: int = 12) -> dict:
    idx = D.index
    test = [i for i, d in enumerate(idx) if d.year >= start]
    r = D["r"].to_numpy()
    acts = np.full(len(D), np.nan)
    rets = np.full(len(D), np.nan)
    p = 2
    for k in range(0, len(test), refit):
        blk = test[k:k + refit]
        t0 = blk[0]
        b = encode(D, t0)
        Q = fit(b[:t0], r[:t0], cfg["gamma"], cfg["penalty"], cfg["prior"])
        for i in blk:
            a = act(Q, b[i], p)
            acts[i] = ACTIONS[a]
            rets[i] = ACTIONS[a] * r[i] - COST * abs(ACTIONS[a] - ACTIONS[p]) - max(0.0, ACTIONS[a] - 1) * BORROW
            p = a
    m = ~np.isnan(rets)
    return {"dates": [d.strftime("%Y-%m") for d in idx[m]], "ret": rets[m], "act": acts[m], "hold": r[m]}


def _perf(x: np.ndarray) -> dict:
    s = pd.Series(x)
    return labs.perf(s)


def build(dl: dict | None = None, B: int = 600) -> dict:
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
    srs = []
    for name, w in res.items():
        x = w["ret"]
        d = np.array([labs.sharpe(x[i]) - labs.sharpe(hold[i]) for i in idx])
        p = _perf(x)
        srs.append(labs.sharpe(x) / math.sqrt(12))
        out["configs"][name] = {**CONFIGS[name], "perf": p, "avg_exposure": float(np.mean(w["act"])), "time_out": float(np.mean(w["act"] == 0)),
                                "time_levered": float(np.mean(w["act"] > 1)), "switches_per_year": float(np.mean(np.abs(np.diff(w["act"])) > 0) * 12),
                                "sharpe_vs_hold": {"est": float(labs.sharpe(x) - labs.sharpe(hold)), "lo": float(np.quantile(d, 0.05)), "hi": float(np.quantile(d, 0.95)),
                                                   "p_le0": float(np.mean(d <= 0))}}
    best = max(out["configs"], key=lambda k: out["configs"][k]["perf"]["sharpe"])
    xb = res[best]["ret"] - hold
    ex = np.array([(res[k]["ret"] - hold).mean() / (res[k]["ret"] - hold).std(ddof=1) for k in res])
    out["best"] = best
    out["deflated_excess"] = labs.deflated_sharpe(float(xb.mean() / xb.std(ddof=1)), len(res), float(np.var(ex, ddof=1)), len(xb),
                                                  float(stats.skew(xb)), float(stats.kurtosis(xb, fisher=False)))
    out["hold"] = _perf(hold)
    out["trend"] = _perf(trend)
    # today's policy, trained on everything
    b = encode(D, len(D))
    Q = fit(b, D["r"].to_numpy(), CONFIGS[best]["gamma"], CONFIGS[best]["penalty"], CONFIGS[best]["prior"])
    last = D.iloc[-1]
    s_now = int(b[-1])
    p_now = ACTIONS.index(res[best]["act"][-1]) if len(res[best]["act"]) else 2
    out["now"] = {"date": D.index[-1].strftime("%Y-%m"), "state": {"trend_on": bool(last["trend"] > 0), "vol_tercile": int((s_now // 9) % 3), "cape_tercile": int((s_now // 3) % 3),
                  "drawdown_bucket": int(s_now % 3)}, "q": [float(v) for v in Q[s_now, p_now]], "action": ACTIONS[act(Q, s_now, p_now)]}
    out["policy"] = [{"trend_on": bool(s // 27), "vol": int((s // 9) % 3), "cape": int((s // 3) % 3), "dd": int(s % 3), "action": ACTIONS[act(Q, s, 2)],
                      "months": int((b == s).sum())} for s in range(54) if (b == s).sum() >= 6]
    out["curve"] = {"dates": dates[::6], "agent": [round(float(v), 4) for v in np.log(np.cumprod(1 + res[best]["ret"]))[::6]],
                    "hold": [round(float(v), 4) for v in np.log(np.cumprod(1 + hold))[::6]], "trend": [round(float(v), 4) for v in np.log(np.cumprod(1 + trend))[::6]]}
    out["findings"] = summary(out)
    return out


def summary(o: dict) -> list[str]:
    b = o["configs"][o["best"]]
    h, t = o["hold"], o["trend"]
    sv = b["sharpe_vs_hold"]
    return [f"A reinforcement-learning sizing agent ({o['best'].replace('_', ' ')}, the best of {len(o['configs'])} configurations), retrained every year and judged "
            f"out of sample since {o['start'][:4]}: Sharpe {b['perf']['sharpe']:.2f} against {h['sharpe']:.2f} for holding and {t['sharpe']:.2f} for the trend rule; "
            f"worst drawdown {b['perf']['maxdd']:.0%} against {h['maxdd']:.0%}; real growth {b['perf']['cagr']:.1%} a year against {h['cagr']:.1%}.",
            f"Its Sharpe gain over holding is {sv['est']:+.2f} with a 90% bootstrap range of {sv['lo']:+.2f} to {sv['hi']:+.2f}; after deflating for the "
            f"{len(o['configs'])} configurations tried, the chance its edge over holding is real is {o['deflated_excess']['dsr']:.0%}.",
            f"It averaged {b['avg_exposure']:.2f}x exposure, sat out {b['time_out']:.0%} of months and levered {b['time_levered']:.0%}. "
            f"Today's state calls for {o['now']['action']:.1f}x."]
