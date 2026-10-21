"""Game theory for the book: who else is choosing, and what their best response does to ours.

The page (site/src/engine7.js) runs the same functions; tests/test_v07.py checks the two agree.

  nash             every Nash equilibrium of a two-player matrix game: pure cells by best-response check, mixed
                   ones by support enumeration (exact for nondegenerate games), plus dominance, Pareto cells and
                   the price of anarchy
  cournot          capex as a quantity race among N builders with different costs of capital (asymmetric Cournot,
                   closed form, firms with no profitable quantity drop out); calibrated so the equilibrium reproduces
                   the builders' observed capex
  capex_dilemma    the same model as a 2x2 game, you against the rest: restrain (your share of the joint-profit
                   quantity) or race (the Cournot quantity)
  crowded_exit     de-grossing a crowded trade as a global game (Morris and Shin): a unique exit threshold when
                   private information is precise enough, and the share of the crowd expected to run
  kyle             the informed trader and the market maker (Kyle 1985): price impact, trading intensity, profit
  ladder           a prediction-market ladder P(X > k): coherence, executable arbitrage after fees, implied distribution
"""
from __future__ import annotations

import itertools
import math
from typing import Sequence

import numpy as np

SQRT2PI = math.sqrt(2 * math.pi)


def _ncdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT2PI


def solve_linear(M: list[list[float]], v: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None when singular. Mirrors engine7.js solveLinear."""
    n = len(v)
    A = [list(map(float, M[i])) + [float(v[i])] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(A[r][c]))
        if abs(A[p][c]) < 1e-12:
            return None
        A[c], A[p] = A[p], A[c]
        for r in range(n):
            if r != c:
                f = A[r][c] / A[c][c]
                A[r] = [a - f * b for a, b in zip(A[r], A[c])]
    return [A[i][n] / A[i][i] for i in range(n)]


# ---------------------------------------------------------------- Nash equilibria of a bimatrix game
def nash(A: Sequence[Sequence[float]], B: Sequence[Sequence[float]], tol: float = 1e-9) -> dict:
    A = np.asarray(A, float)
    B = np.asarray(B, float)
    m, n = A.shape
    eqs: list[dict] = []

    def add(x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        for e in eqs:
            if np.allclose(e["x"], x, atol=1e-7) and np.allclose(e["y"], y, atol=1e-7):
                return
        eqs.append({"x": x.tolist(), "y": y.tolist(), "u_row": float(x @ A @ y), "u_col": float(x @ B @ y),
                    "pure": bool(max(x) > 1 - 1e-9 and max(y) > 1 - 1e-9)})

    for i in range(m):                      # pure: mutual best responses (exact even when the game is degenerate)
        for j in range(n):
            if A[i, j] >= A[:, j].max() - tol and B[i, j] >= B[i, :].max() - tol:
                add(np.eye(m)[i], np.eye(n)[j])
    for k in range(2, min(m, n) + 1):       # mixed: equal-size supports
        for I in itertools.combinations(range(m), k):
            for J in itertools.combinations(range(n), k):
                # y on J makes the row player indifferent across I: A[I,J] y = v, sum y = 1
                My = [list(A[i, list(J)]) + [-1.0] for i in I] + [[1.0] * k + [0.0]]
                sy = solve_linear(My, [0.0] * k + [1.0])
                Mx = [[B[i, j] for i in I] + [-1.0] for j in J] + [[1.0] * k + [0.0]]
                sx = solve_linear(Mx, [0.0] * k + [1.0])
                if sy is None or sx is None:
                    continue
                y = np.zeros(n)
                y[list(J)] = sy[:k]
                x = np.zeros(m)
                x[list(I)] = sx[:k]
                if (y < -tol).any() or (x < -tol).any():
                    continue
                if (A @ y).max() > sy[k] + 1e-7 or (x @ B).max() > sx[k] + 1e-7:
                    continue
                add(np.clip(x, 0, 1), np.clip(y, 0, 1))
    dom_row = [i for i in range(m) if any((A[k] > A[i] + tol).all() for k in range(m) if k != i)]
    dom_col = [j for j in range(n) if any((B[:, k] > B[:, j] + tol).all() for k in range(n) if k != j)]
    W = A + B
    pareto = [(i, j) for i in range(m) for j in range(n)
              if not any((A[a, b] >= A[i, j] and B[a, b] >= B[i, j] and (A[a, b] > A[i, j] or B[a, b] > B[i, j]))
                         for a in range(m) for b in range(n))]
    best = float(W.max())
    worst_eq = min((e["u_row"] + e["u_col"] for e in eqs), default=float("nan"))
    return {"equilibria": eqs, "dominated_rows": dom_row, "dominated_cols": dom_col, "pareto": pareto,
            "welfare_best": best, "welfare_worst_eq": worst_eq,
            "price_of_anarchy": best / worst_eq if worst_eq and worst_eq > 0 else None}


# ---------------------------------------------------------------- Cournot capex race
def cournot(a: float, b: float, costs: Sequence[float]) -> dict:
    """Inverse demand P = a - b Q (return per $ of capacity), firm i's unit cost c_i. Closed form, with exit.

    Active set S: q_i = (a - (|S|+1) c_i + sum_{j in S} c_j) / (b (|S|+1)); drop any firm with q_i <= 0 and repeat.
    """
    c = list(map(float, costs))
    active = list(range(len(c)))
    while True:
        n = len(active)
        cs = sum(c[i] for i in active)
        q = {i: (a - (n + 1) * c[i] + cs) / (b * (n + 1)) for i in active}
        out = [i for i in active if q[i] <= 0]
        if not out or n == 0:
            break
        active = [i for i in active if i not in out]
    Q = sum(q.get(i, 0.0) for i in active)
    P = a - b * Q
    qs = [max(q.get(i, 0.0), 0.0) for i in range(len(c))]
    profit = [(P - c[i]) * qs[i] for i in range(len(c))]
    return {"q": qs, "Q": Q, "P": P, "profit": profit, "active": active}


def cournot_calibrate(q_obs: Sequence[float], costs: Sequence[float], p_obs: float) -> dict:
    """Choose a and b so the Nash equilibrium reproduces total observed capex Q at price p_obs (both observed or
    assumed); firm shares then follow from the cost differences."""
    n = len(q_obs)
    Q = float(sum(q_obs))
    cbar = float(np.mean(costs))
    a_minus = (n + 1) * (p_obs - cbar)             # P - cbar = (a - cbar) / (n + 1) in the symmetric-mean form
    a = cbar + a_minus
    b = (a - p_obs) / Q
    return {"a": a, "b": b, "Q_obs": Q, "p_obs": p_obs}


def capex_game(q_obs: Sequence[float], costs: Sequence[float], p_obs: float) -> dict:
    cal = cournot_calibrate(q_obs, costs, p_obs)
    a, b = cal["a"], cal["b"]
    eq = cournot(a, b, costs)
    n = len(costs)
    cmin = min(costs)
    Qm = (a - cmin) / (2 * b)                      # one coordinated builder at the lowest cost
    Pm = a - b * Qm
    joint = (Pm - cmin) * Qm
    entrant = cournot(a, b, list(costs) + [float(np.mean(costs))])
    return {"calibration": cal, "nash": eq, "collusive_Q": Qm, "collusive_P": Pm, "joint_profit_max": joint,
            "overbuild": eq["Q"] / Qm, "profit_share_kept": sum(eq["profit"]) / joint if joint > 0 else None,
            "with_entrant": entrant, "entrant_cut": (sum(entrant["profit"][:n]) / sum(eq["profit"]) - 1) if sum(eq["profit"]) > 0 else None,
            "symmetric_overbuild": 2 * n / (n + 1), "symmetric_profit_share": 4 * n / (n + 1) ** 2}


def capex_dilemma(a: float, b: float, c: float, n: int = 5) -> dict:
    """The N-builder race seen from one seat. Restrain = your 1/N share of the joint-profit quantity; race = the
    symmetric Cournot quantity. A[me][others] is your annual profit when you play `me` and every rival plays `others`.
    Racing is dominant when it pays more against both columns; then everyone races, and each earns A[race][race]
    instead of A[restrain][restrain]. The 2-builder version is the textbook prisoner's dilemma (also returned)."""
    q = {"restrain": (a - c) / (2 * b) / n, "race": (a - c) / (b * (n + 1))}
    names = ["restrain", "race"]

    def pay(mine, theirs, k):
        Q = q[mine] + (k - 1) * q[theirs]
        return (a - b * Q - c) * q[mine]

    A = [[pay(me, them, n) for them in names] for me in names]
    dominant = A[1][0] > A[0][0] and A[1][1] > A[0][1]
    q2 = {"restrain": (a - c) / (4 * b), "race": (a - c) / (3 * b)}
    A2 = [[(a - b * (q2[me] + q2[them]) - c) * q2[me] for them in names] for me in names]
    B2 = [[A2[j][i] for j in range(2)] for i in range(2)]
    return {"names": names, "n": n, "q": q, "A": A, "race_dominant": bool(dominant),
            "everyone_restrains": A[0][0], "everyone_races": A[1][1], "cost_of_racing": 1 - A[1][1] / A[0][0],
            "temptation": A[1][0] / A[0][0] - 1,
            "duopoly": {"A": A2, "B": B2, "analysis": nash(A2, B2)}}


# ---------------------------------------------------------------- crowded exit as a global game
def crowded_exit(lam: float, cost: float, y: float, sd_public: float, sd_private: float, theta: float | None = None) -> dict:
    """Morris-Shin. Fundamental theta ~ N(y, sd_public^2) is the payoff of staying in the crowded trade; each pod sees
    x = theta + noise (sd_private). Staying pays theta - lam * (share exiting); exiting pays -cost.

    The marginal pod at x* is indifferent: E[theta | x*] - lam * Phi(sqrt(beta)(x* - mu*) / sqrt(1 + beta / (alpha + beta))) = -cost,
    with alpha = 1/sd_public^2, beta = 1/sd_private^2, mu* = (alpha y + beta x*) / (alpha + beta). Solved by bisection.
    unique: the indifference curve is monotone in x*, true whenever lam * alpha / sqrt(beta) * c < sqrt(2 pi) (checked).
    """
    alpha, beta = 1 / sd_public ** 2, 1 / sd_private ** 2
    s = math.sqrt(1 + beta / (alpha + beta))

    def F(x):
        mu = (alpha * y + beta * x) / (alpha + beta)
        return mu - lam * _ncdf(math.sqrt(beta) * (x - mu) / s) + cost

    def dF(x):
        mu = (alpha * y + beta * x) / (alpha + beta)
        z = math.sqrt(beta) * (x - mu) / s
        return beta / (alpha + beta) - lam * _npdf(z) * math.sqrt(beta) * (alpha / (alpha + beta)) / s

    lo, hi = y - 20 * (sd_public + sd_private) - lam, y + 20 * (sd_public + sd_private) + lam
    for _ in range(200):
        mid = (lo + hi) / 2
        if F(mid) > 0:
            hi = mid
        else:
            lo = mid
    xs = (lo + hi) / 2
    grid = np.linspace(y - 6 * sd_public - lam, y + 6 * sd_public + lam, 801)
    unique = bool(min(dF(g) for g in grid) > 0)
    th = y if theta is None else theta
    share = _ncdf(math.sqrt(beta) * (xs - th))
    return {"x_star": xs, "theta_star": xs, "unique": unique, "share_exiting": share, "theta": th,
            "stay_payoff": th - lam * share, "laplace_limit": lam / 2 - cost,
            "p_fundamental_below": _ncdf((xs - y) / sd_public)}


# ---------------------------------------------------------------- Kyle (1985)
def kyle(sigma_v: float, sigma_u: float) -> dict:
    """One auction. Value v ~ N(p0, sigma_v^2), noise flow u ~ N(0, sigma_u^2). Linear equilibrium:
    insider trades beta (v - p0), price moves lambda per unit of order flow."""
    lam = sigma_v / (2 * sigma_u)
    beta = sigma_u / sigma_v
    return {"lambda": lam, "beta": beta, "insider_profit": sigma_u * sigma_v / 2, "post_var_share": 0.5,
            "cost_of_noise_flow": sigma_u * sigma_v / 2}


# ---------------------------------------------------------------- prediction-market ladder
def kalshi_fee(p: float, contracts: int = 1, rate: float = 0.07) -> float:
    """Per-order trading fee, rounded up to the cent: ceil(rate x C x P x (1 - P)) (published general schedule;
    check the series' own schedule before relying on it)."""
    return math.ceil(rate * contracts * p * (1 - p) * 100 - 1e-9) / 100


def ladder(rows: Sequence[dict], contracts: int = 100) -> dict:
    """rows: [{k, bid, ask}] for 'X above k', prices in dollars (0..1), k ascending.

    Coherence: P(X > k) must not rise with k. Executable check for k_i < k_j: buy 'above k_i' at its ask and sell
    'above k_j' at its bid: never loses, so bid_j > ask_i + fees is free money. Implied pmf from mid differences.
    """
    r = sorted(rows, key=lambda x: x["k"])
    mids = [(x["bid"] + x["ask"]) / 2 for x in r]
    viol, arbs = [], []
    for i in range(len(r)):
        for j in range(i + 1, len(r)):
            if mids[j] > mids[i] + 1e-12:
                viol.append({"lo": r[i]["k"], "hi": r[j]["k"], "gap": mids[j] - mids[i]})
            edge = r[j]["bid"] - r[i]["ask"]
            fees = (kalshi_fee(r[i]["ask"], contracts) + kalshi_fee(r[j]["bid"], contracts)) / contracts
            if edge - fees > 0:
                arbs.append({"buy": r[i]["k"], "sell": r[j]["k"], "edge": edge, "fees": fees, "net": edge - fees,
                             "per_100": (edge - fees) * 100})
    mono = []                                       # isotonic (pool-adjacent-violators) fit of the mids, non-increasing
    for v in mids:
        mono.append([v, 1])
        while len(mono) > 1 and mono[-2][0] < mono[-1][0]:
            v2, w2 = mono.pop()
            v1, w1 = mono.pop()
            mono.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2])
    fit = [v for v, w in mono for _ in range(w)]
    bins = [{"lo": None, "hi": r[0]["k"], "p": 1 - fit[0]}]
    bins += [{"lo": r[i]["k"], "hi": r[i + 1]["k"], "p": fit[i] - fit[i + 1]} for i in range(len(r) - 1)]
    bins += [{"lo": r[-1]["k"], "hi": None, "p": fit[-1]}]
    return {"mids": mids, "coherent_fit": fit, "violations": viol, "arbitrage": arbs, "pmf": bins}
