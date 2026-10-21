"""Black-Scholes with a continuous dividend yield, Greeks and implied volatility.

Mirrors site/src/math.js (bs, impliedVol). Vega is per volatility point, theta per calendar day.
"""
from __future__ import annotations

import math

from scipy.stats import norm


def bs(S: float, K: float, T: float, r: float, q: float, v: float, kind: str) -> dict:
    if not (S > 0 and K > 0):
        nan = float("nan")
        return {"price": nan, "delta": nan, "gamma": nan, "vega": nan, "theta": nan, "pitm": nan}
    if T <= 0 or v <= 0:
        t = max(T, 0.0)
        fwd, disc = S * math.exp((r - q) * t), math.exp(-r * t)
        itm = fwd > K if kind == "call" else fwd < K
        intr = (max(fwd - K, 0.0) if kind == "call" else max(K - fwd, 0.0)) * disc
        delta = ((1.0 if kind == "call" else -1.0) * math.exp(-q * t)) if itm else 0.0
        return {"price": intr, "delta": delta, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "pitm": 1.0 if itm else 0.0}
    sq = v * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * v * v) * T) / sq
    d2 = d1 - sq
    df, dq = math.exp(-r * T), math.exp(-q * T)
    pdf = norm.pdf(d1)
    gamma = dq * pdf / (S * sq)
    vega = S * dq * pdf * math.sqrt(T) / 100
    if kind == "call":
        return {"price": S * dq * norm.cdf(d1) - K * df * norm.cdf(d2), "delta": dq * norm.cdf(d1), "gamma": gamma,
                "vega": vega, "theta": (-S * dq * pdf * v / (2 * math.sqrt(T)) - r * K * df * norm.cdf(d2)
                                        + q * S * dq * norm.cdf(d1)) / 365, "pitm": norm.cdf(d2)}
    return {"price": K * df * norm.cdf(-d2) - S * dq * norm.cdf(-d1), "delta": dq * (norm.cdf(d1) - 1), "gamma": gamma,
            "vega": vega, "theta": (-S * dq * pdf * v / (2 * math.sqrt(T)) + r * K * df * norm.cdf(-d2)
                                    - q * S * dq * norm.cdf(-d1)) / 365, "pitm": norm.cdf(-d2)}


def implied_vol(price: float, S: float, K: float, T: float, r: float, q: float, kind: str) -> float:
    """Bisection on [0.0001, 5]; NaN when the price is outside the no-arbitrage bounds."""
    if not (price > 0 and S > 0 and K > 0 and T > 0):
        return float("nan")
    if kind == "call":
        lower, upper = max(S * math.exp(-q * T) - K * math.exp(-r * T), 0.0), S * math.exp(-q * T)
    else:
        lower, upper = max(K * math.exp(-r * T) - S * math.exp(-q * T), 0.0), K * math.exp(-r * T)
    if price <= lower + 1e-12 or price >= upper - 1e-12:
        return float("nan")
    lo, hi = 1e-4, 5.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if bs(S, K, T, r, q, mid, kind)["price"] > price else (mid, hi)
    return (lo + hi) / 2
