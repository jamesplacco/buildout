"""How sure is the size (v0.44): the call's size under other defensible models and settings.

The book's size is the smallest of four numbers: the loss budget over the expected shortfall, the volatility target
over the volatility, the leverage at which a simulated year's 95th-percentile drawdown reaches the cap, and the gross
cap. The drawdown number binds, and it comes from one model: constant volatility, normal shocks, an assumed drift
(sizing.drawdown_quantile). It is solved to four decimals. That precision is about the arithmetic, not about next
year. Two outside audits asked the same question: what does the size become under other specifications, and did the
cap hold where it was used?

This module answers the first half on today's book (the second half, what happened, is track.window_drawdowns):

    models      the one-year 95th-percentile drawdown, and the size that keeps it inside the cap, when the shocks
                have fat tails, when they come in the clusters the book actually had, when volatility itself moves,
                when the assumed equity premium is taken away, and when volatility is today's or the worst year's
    settings    the size when one setting at a time is changed: each limit, the premium, the method for the tail,
                the two half-lives of the factor model
    seeds       how much the engine's own number moves when only the random draws change

Everything is simulated at 1.00x as daily simple returns, then levered: a size g holds g of NAV in the book and the
rest in cash, restored daily (borrowing above 1.00x pays the cash rate plus a spread), the same book the engine's
simulation describes. The engine's own row is the engine's own function, so it equals the published size exactly;
tests check that this module's simulator with normal shocks agrees with it to sampling error. Nothing here changes
the call. It says how far to trust it.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import book as bk
from .analytics import sizing

N_PATHS, STEPS, Q = 4000, 252, 0.95
BLOCK = 21                  # mean block length of the bootstrap, in trading days: a month of the book's own history at a time
NU = bk.T_NU                # degrees of freedom of the fat-tailed shocks, the same as the engine's parametric tail
SEEDS = 20
BORROW = 0.01


# ---------------------------------------------------------------- paths at 1.00x
def _shocks_normal(rng) -> np.ndarray:
    return rng.standard_normal((N_PATHS, STEPS))


def _shocks_t(rng, nu: float = NU) -> np.ndarray:
    return rng.standard_t(nu, (N_PATHS, STEPS)) / math.sqrt(nu / (nu - 2))        # unit variance


def _shocks_blocks(rng, z: np.ndarray, block: int = BLOCK) -> np.ndarray:
    """Stationary bootstrap (Politis and Romano): each path walks the history from a random day and, each day, jumps
    to a new random day with probability 1/block. Clusters of bad days stay together, as they came."""
    n = len(z)
    start = rng.integers(0, n, (N_PATHS, STEPS))
    jump = rng.random((N_PATHS, STEPS)) < 1.0 / block
    jump[:, 0] = True
    idx = np.empty((N_PATHS, STEPS), dtype=np.int64)
    idx[:, 0] = start[:, 0]
    for t in range(1, STEPS):
        idx[:, t] = np.where(jump[:, t], start[:, t], (idx[:, t - 1] + 1) % n)
    return z[idx]


def _paths_clustered(rng, zf: np.ndarray, s0: float, mu: float, lam: float = bk.EWMA_LAMBDA) -> np.ndarray:
    """Volatility that moves: tomorrow's variance is lam times today's plus (1 - lam) times today's squared move (the
    RiskMetrics recursion the engine's filtered tail uses), started at daily volatility s0, with the book's own
    standardized shocks drawn at random. Variance has no pull back to a level, so a bad week raises the whole path."""
    z = zf[rng.integers(0, len(zf), (N_PATHS, STEPS))]
    X = np.empty((N_PATHS, STEPS))
    v = np.full(N_PATHS, s0 * s0)
    for t in range(STEPS):
        e = np.sqrt(v) * z[:, t]
        X[:, t] = mu / 252 + e
        v = lam * v + (1 - lam) * e * e
    return X


def dd_quantile(X: np.ndarray, g: float, rf: float, q: float = Q) -> float:
    """The q-quantile, across paths, of the worst peak-to-trough fall over the year at size g."""
    d = g * X + (1 - g) * rf / 252 - max(g - 1, 0.0) * BORROW / 252
    lv = np.concatenate([np.ones((len(d), 1)), np.cumprod(1 + d, axis=1)], axis=1)
    return float(np.quantile((1 - lv / np.maximum.accumulate(lv, axis=1)).max(axis=1), q))


def size_inside(X: np.ndarray, rf: float, cap: float, hi: float = 3.0, tol: float = 1e-4) -> float:
    """The largest size whose drawdown quantile is at or inside the cap (bisection; the answer is on the safe side)."""
    if dd_quantile(X, hi, rf) <= cap:
        return hi
    lo = 0.0
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if dd_quantile(X, mid, rf) <= cap:
            lo = mid
        else:
            hi = mid
    return lo


# ---------------------------------------------------------------- the three tables
def models(rb: pd.Series, sigma: float, mu: float, rf: float, size: float, cap: float = bk.MAX_DD, vol_now: float | None = None, seed: int = 0) -> dict:
    r = rb.dropna()
    z = ((r - r.mean()) / r.std()).to_numpy()
    s = bk.ewma_vol(r)
    zf = (r / s).dropna()
    zf = ((zf - zf.mean()) / zf.std()).to_numpy()
    worst_vol = float(r.rolling(252).std().max() * math.sqrt(252))
    sd = sigma / math.sqrt(252)
    lin = lambda Z, m=mu, v=sigma: m / 252 + v / math.sqrt(252) * Z
    rng = lambda k: np.random.default_rng(seed + 1000 * k)
    P = {
        "student_t": lin(_shocks_t(rng(1))),
        "blocks": lin(_shocks_blocks(rng(2), z)),
        "clustered": _paths_clustered(rng(3), zf, sd, mu),
    }
    rows = [{"key": "gbm", "label": "The engine's model", "what": "constant volatility, normal shocks, the assumed drift",
             "dd_full": sizing.drawdown_quantile(mu, sigma, 1.0, cash_rate=rf), "dd_at_size": sizing.drawdown_quantile(mu, sigma, size, cash_rate=rf),
             "size": sizing.max_leverage(mu, sigma, cap, cash_rate=rf), "kind": "shape"}]
    text = {"student_t": ("Fat tails", f"the same volatility and drift; shocks from a Student-t with {NU:g} degrees of freedom, each day independent"),
            "blocks": ("The book's own days, in runs", f"the same volatility and drift; the book's own daily moves since {r.index[0].year}, redrawn in runs averaging {BLOCK} days, so bad days stay together"),
            "clustered": ("Volatility that moves", "the same starting volatility and drift; each day's variance follows the last day's move, so a bad week raises what comes after")}
    for k, X in P.items():
        rows.append({"key": k, "label": text[k][0], "what": text[k][1], "dd_full": dd_quantile(X, 1.0, rf), "dd_at_size": dd_quantile(X, size, rf), "size": size_inside(X, rf, cap), "kind": "shape"})
    levels = [("no_premium", "No equity premium", "the engine's model with drift equal to cash: nothing is assumed to be earned for the risk", rf, sigma)]
    if vol_now is not None:
        levels.append(("vol_now", "Today's volatility", f"the engine's model at the volatility of the last few weeks ({vol_now:.0%}) in place of the factor model's ({sigma:.0%})", mu, vol_now))
    levels.append(("vol_worst", "The worst year's volatility", f"the engine's model at the book's highest one-year realized volatility ({worst_vol:.0%})", mu, worst_vol))
    for k, label, what, m, v in levels:
        rows.append({"key": k, "label": label, "what": what, "dd_full": sizing.drawdown_quantile(m, v, 1.0, cash_rate=rf), "dd_at_size": sizing.drawdown_quantile(m, v, size, cash_rate=rf),
                     "size": sizing.max_leverage(m, v, cap, cash_rate=rf), "kind": "level"})
    base = rows[0]["size"]
    for x in rows:
        x["d_size"] = x["size"] - base
        x["inside_at_size"] = bool(x["dd_at_size"] <= cap + 1e-9)
    shape = [x for x in rows if x["kind"] == "shape"]
    # only the draws change: the engine's model, twenty seeds, this module's simulator
    sizes = [size_inside(lin(_shocks_normal(np.random.default_rng(10_000 + i))), rf, cap) for i in range(SEEDS)]
    return {"rows": rows, "cap": cap, "size": size, "paths": N_PATHS, "block": BLOCK, "nu": NU,
            "shape_range": [min(x["size"] for x in shape), max(x["size"] for x in shape)],
            "all_range": [min(x["size"] for x in rows), max(x["size"] for x in rows)],
            "worst_at_size": max(x["dd_at_size"] for x in shape),
            "seeds": {"n": SEEDS, "min": float(min(sizes)), "max": float(max(sizes)), "sd": float(np.std(sizes, ddof=1)), "mean": float(np.mean(sizes))},
            "check_normal": {"size": size_inside(lin(_shocks_normal(rng(9))), rf, cap), "dd_full": dd_quantile(lin(_shocks_normal(rng(9))), 1.0, rf)}}


def _sizes(es_gov: float, sigma: float, mu: float, rf: float, es_budget: float = bk.ES_BUDGET, vol_target: float = bk.VOL_TARGET, cap: float = bk.MAX_DD) -> dict:
    s = {"es_budget": es_budget / es_gov, "vol_target": vol_target / sigma, "drawdown_cap": sizing.max_leverage(mu, sigma, cap, cash_rate=rf), "gross_cap": bk.MAX_GROSS}
    b = min(s, key=s.get)
    return {"size": float(s[b]), "binding": b, "sizes": {k: float(v) for k, v in s.items()}}


def settings(P: dict, w: pd.Series, rb: pd.Series, fm: dict, tail: dict, beta_vti: float, rf: float) -> list[dict]:
    """The size when one setting changes and the rest stay. The first row of each group marked `now` is the engine."""
    sigma, es = fm["vol"], tail["es95"]
    mu = lambda prem: rf + prem * beta_vti
    out = []

    def add(group: str, label: str, now: bool, **kw):
        a = {"es_gov": es["governing"], "sigma": sigma, "mu": mu(bk.EQUITY_PREMIUM), "rf": rf, **kw}
        out.append({"group": group, "label": label, "now": bool(now), **_sizes(**a)})

    for v in (0.10, bk.ES_BUDGET, 0.15):
        add("Loss budget, a month", f"{v:.0%}", v == bk.ES_BUDGET, es_budget=v)
    for v in (0.15, bk.VOL_TARGET, 0.25):
        add("Volatility target", f"{v:.0%}", v == bk.VOL_TARGET, vol_target=v)
    for v in (0.20, bk.MAX_DD, 0.30):
        add("Drawdown cap, a year", f"{v:.0%}", v == bk.MAX_DD, cap=v)
    for v in (0.0, 0.03, bk.EQUITY_PREMIUM, 0.07):
        add("Equity premium in the drift", f"{v:.0%}", v == bk.EQUITY_PREMIUM, mu=mu(v))
    for k, name in (("governing", f"the most cautious of the three ({es['method'].replace('_', ' ')})"), ("historical", "the book's own months"), ("filtered", "its months rescaled to today's volatility"), ("student_t", "a fat-tailed curve at the model's volatility")):
        add("Method for the tail", name, k == "governing", es_gov=es[k])
    R, F = P["R"], P["F"]
    for bh, ch in ((bk.BETA_HL, bk.COV_HL), (63, bk.COV_HL), (252, bk.COV_HL), (bk.BETA_HL, 21), (bk.BETA_HL, 126)):
        now = (bh, ch) == (bk.BETA_HL, bk.COV_HL)
        f2 = fm if now else bk.factor_model(R, F, w, beta_hl=bh, cov_hl=ch)
        t2 = tail if now else bk.tail_block(rb, f2["vol"])
        add("Half-lives of the factor model", f"betas {bh} days, covariance {ch} days", now, sigma=f2["vol"], es_gov=t2["es95"]["governing"])
        out[-1]["vol"] = float(f2["vol"])
    return out


def build(prices: dict[str, pd.DataFrame], ust: pd.DataFrame | None = None, book: dict[str, float] = bk.BOOK, seed: int = 0) -> dict:
    """The sensitivity block for the page (site/data/book.json: sensitivity). About ten seconds; run by the daily
    `book` command, not by the walk-forward, which builds the book a hundred times."""
    ust = bk.treasury() if ust is None else ust
    w = pd.Series(book, dtype=float)
    P = bk.panel(prices, ust, book)
    R, F, E = P["R"], P["F"], P["E"]
    rb = bk.book_returns(R, w)
    fm = bk.factor_model(R, F, w)
    sigma = fm["vol"]
    tail = bk.tail_block(rb, sigma)
    beta_vti = float(pd.concat([rb, E["VTI"]], axis=1).dropna().cov().iloc[0, 1] / E["VTI"].var())
    rf = float(ust["DGS2"].iloc[-1]) / 100
    mu = rf + bk.EQUITY_PREMIUM * beta_vti
    now = _sizes(tail["es95"]["governing"], sigma, mu, rf)
    M = models(rb, sigma, mu, rf, now["size"], vol_now=float(tail["daily_vol_now_ann"]), seed=seed)
    S = settings(P, w, rb, fm, tail, beta_vti, rf)
    lo, hi = min(x["size"] for x in S), max(x["size"] for x in S)
    return {"schema": 1, "asof": str(R.dropna(how="all").index[-1].date()), "size": now["size"], "binding": now["binding"], "sizes": now["sizes"],
            "sigma": float(sigma), "drift": float(mu), "cash_rate": rf, "beta_broad": beta_vti, "models": M, "settings": S,
            "settings_range": [float(lo), float(hi)],
            "note": "Each row changes one thing and holds the rest. The call is unchanged by any of this; it is how far to trust the size."}


def attach(o: dict, prices: dict[str, pd.DataFrame], ust: pd.DataFrame | None = None, book: dict[str, float] = bk.BOOK) -> dict:
    """Add the block to a finished book run. A failure here is recorded, not raised: the call does not depend on it."""
    try:
        o["sensitivity"] = build(prices, ust, book)
        if abs(o["sensitivity"]["size"] - float(o["size"])) > 1e-6:
            o["sensitivity"]["mismatch"] = f"this block sized the book at {o['sensitivity']['size']:.4f}; the call is {float(o['size']):.4f}"
    except Exception as exc:  # noqa: BLE001
        o["sensitivity"] = {"failed": f"{type(exc).__name__}: {exc}"[:300]}
    return o
