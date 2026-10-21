"""Market making and execution: the closed forms the Trading desks use, and estimators for the daily bars.

Quoting (Avellaneda and Stoikov, 2008)
  reservation price  r = s - q * gamma * sigma^2 * tau
  total spread       delta = gamma * sigma^2 * tau + (2 / gamma) * ln(1 + gamma / k)
  fills arrive at    A * exp(-k * distance from mid), a Poisson rate per unit of time

Adverse selection (Glosten and Milgrom, 1985, two-value case)
  spread = mu * (V_high - V_low): the share of informed traders times the size of what they know

Execution
  square-root impact  I = Y * sigma_daily * sqrt(Q / ADV), Y of order 1 (Toth et al., 2011)
  Almgren-Chriss       x_j = X * sinh(kappa * (T - t_j)) / sinh(kappa * T), cosh(kappa * tau) = 1 + lam * sigma^2 * tau^2 / (2 * eta)

Estimators from daily bars (used by the book run once Databento data arrives)
  Roll spread   2 * sqrt(-cov(dp_t, dp_t-1)) when the first-order autocovariance is negative
  Amihud        mean(|return| / dollar volume), per $1 million traded
  Kyle lambda   slope of the return on signed dollar volume (sign from the tick rule)
"""
from __future__ import annotations

import math

import numpy as np


def as_quotes(mid: float, inventory: float, gamma: float, sigma: float, tau: float, k: float) -> dict:
    r = mid - inventory * gamma * sigma ** 2 * tau
    spread = gamma * sigma ** 2 * tau + (2 / gamma) * math.log(1 + gamma / k)
    return {"reservation": r, "spread": spread, "bid": r - spread / 2, "ask": r + spread / 2}


def simulate_as(n_paths: int = 1000, steps: int = 200, T: float = 1.0, s0: float = 100.0, sigma: float = 2.0, gamma: float = 0.1,
                k: float = 1.5, A: float = 140.0, symmetric: bool = False, seed: int = 7) -> dict:
    """Monte Carlo of the Avellaneda-Stoikov market maker; symmetric=True quotes the same spread around the mid."""
    rng = np.random.default_rng(seed)
    dt = T / steps
    s = np.full(n_paths, s0)
    q = np.zeros(n_paths)
    cash = np.zeros(n_paths)
    fills = np.zeros(n_paths)
    for i in range(steps):
        tau = T - i * dt
        spread = gamma * sigma ** 2 * tau + (2 / gamma) * math.log(1 + gamma / k)
        r = s if symmetric else s - q * gamma * sigma ** 2 * tau
        bid, ask = r - spread / 2, r + spread / 2
        db, da = s - bid, ask - s
        hit_b = rng.random(n_paths) < A * np.exp(-k * db) * dt
        hit_a = rng.random(n_paths) < A * np.exp(-k * da) * dt
        q += hit_b.astype(float) - hit_a.astype(float)
        cash += -bid * hit_b + ask * hit_a
        fills += hit_b + hit_a
        s = s + sigma * math.sqrt(dt) * rng.choice([-1.0, 1.0], n_paths)
    pnl = cash + q * s
    return {"mean": float(pnl.mean()), "sd": float(pnl.std()), "inv_sd": float(q.std()), "fills": float(fills.mean())}


def gm_spread(mu: float, v_high: float, v_low: float) -> float:
    return mu * (v_high - v_low)


def sqrt_impact(qty: float, adv: float, sigma_daily: float, Y: float = 0.7) -> float:
    """Expected impact as a fraction of price."""
    if adv <= 0 or qty <= 0:
        return 0.0
    return Y * sigma_daily * math.sqrt(qty / adv)


def ac_trajectory(X: float, T: float, N: int, sigma: float, eta: float, lam: float) -> list[float]:
    """Holdings after each of N equal intervals; lam = 0 is a straight line (TWAP)."""
    tau = T / N
    if lam <= 0:
        return [X * (1 - j / N) for j in range(N + 1)]
    kappa = math.acosh(1 + lam * sigma ** 2 * tau ** 2 / (2 * eta)) / tau
    return [X * math.sinh(kappa * (T - j * tau)) / math.sinh(kappa * T) for j in range(N + 1)]


def ac_cost(traj: list[float], T: float, sigma: float, eta: float) -> dict:
    """Expected temporary-impact cost and its standard deviation for a holdings path (linear impact eta)."""
    N = len(traj) - 1
    tau = T / N
    trades = [traj[j - 1] - traj[j] for j in range(1, N + 1)]
    expected = sum(eta / tau * n * n for n in trades)
    var = sigma ** 2 * tau * sum(x * x for x in traj[1:])
    return {"expected": expected, "sd": math.sqrt(var)}


def roll_spread(prices) -> float:
    dp = np.diff(np.asarray(prices, dtype=float))
    if len(dp) < 3:
        return float("nan")
    c = np.cov(dp[1:], dp[:-1])[0, 1]
    return float(2 * math.sqrt(-c)) if c < 0 else float("nan")


def amihud(returns, dollar_volume) -> float:
    r, v = np.asarray(returns, dtype=float), np.asarray(dollar_volume, dtype=float)
    ok = v > 0
    return float(np.mean(np.abs(r[ok]) / v[ok]) * 1e6) if ok.any() else float("nan")


def kyle_lambda(returns, dollar_volume) -> float:
    r, v = np.asarray(returns, dtype=float), np.asarray(dollar_volume, dtype=float)
    signed = np.sign(r) * v
    if np.var(signed) == 0:
        return float("nan")
    return float(np.cov(r, signed)[0, 1] / np.var(signed, ddof=1))


def bar_liquidity(close, volume) -> dict:
    """The three estimators on one ticker's daily bars."""
    close, volume = np.asarray(close, dtype=float), np.asarray(volume, dtype=float)
    ret = np.diff(close) / close[:-1]
    dv = (close * volume)[1:]
    return {"roll_spread_bps": roll_spread(close) / float(np.mean(close)) * 1e4, "amihud": amihud(ret, dv), "kyle_lambda": kyle_lambda(ret, dv)}


# ---------------------------------------------------------------- v0.7: fill quality (review sections 20-21)
def book_state(bid: float, ask: float, qb: float, qa: float) -> dict:
    """Midpoint, queue imbalance I = (Qb - Qa) / (Qb + Qa) and the size-weighted midpoint (a Qb + b Qa) / (Qb + Qa)."""
    tot = qb + qa
    return {"mid": (bid + ask) / 2, "spread": ask - bid, "imbalance": (qb - qa) / tot if tot > 0 else 0.0,
            "weighted_mid": (ask * qb + bid * qa) / tot if tot > 0 else (bid + ask) / 2}


def markout(side: int, price: float, mid_now: float, mid_later: float) -> dict:
    """Signed markout M_h = s (m_{t+h} - p_t), split into the edge at the fill s (m_t - p_t) and the move after it
    s (m_{t+h} - m_t). side = +1 for a purchase, -1 for a sale."""
    edge, move = side * (mid_now - price), side * (mid_later - mid_now)
    return {"markout": edge + move, "edge": edge, "move": move}


def post_value(p_fill: float, markout_if_filled: float, cost_if_filled: float, cost_of_miss: float) -> float:
    """V_post = P(F) (E[M_h | F] - c_F) - (1 - P(F)) C_miss, per unit."""
    return p_fill * (markout_if_filled - cost_if_filled) - (1 - p_fill) * cost_of_miss


def cross_value(markout_cross: float, cost_cross: float) -> float:
    """Crossing fills for sure: its value is the (usually negative) markout after paying the spread, less fees."""
    return markout_cross - cost_cross
