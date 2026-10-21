"""Treasury curve analytics from par yields: zero curve, forwards, carry and roll-down, futures DV01.

Mirrors site/src/math.js (parAt, bootstrap, forwardRate, carryRoll, futuresDV01) so the page and the
engine give the same numbers; tests/test_page.py checks them against each other.
All rates are decimals with semiannual compounding.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .bonds import bond_price, duration_convexity


def _sign(v: float) -> int:
    return (v > 0) - (v < 0)


def pchip_slopes(x: list[float], y: list[float]) -> list[float]:
    """Fritsch-Carlson monotone cubic slopes, with SciPy's shape-preserving end conditions.

    Written out rather than taken from scipy so the page (math.js) can mirror it line for line.
    """
    n = len(x)
    hs = [x[k + 1] - x[k] for k in range(n - 1)]
    d = [(y[k + 1] - y[k]) / hs[k] for k in range(n - 1)]
    if n == 2:
        return [d[0], d[0]]
    m = [0.0] * n
    for k in range(1, n - 1):
        if d[k - 1] == 0 or d[k] == 0 or _sign(d[k - 1]) != _sign(d[k]):
            m[k] = 0.0
        else:
            w1, w2 = 2 * hs[k] + hs[k - 1], hs[k] + 2 * hs[k - 1]
            m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])

    def edge(h0: float, h1: float, d0: float, d1: float) -> float:
        e = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if _sign(e) != _sign(d0):
            return 0.0
        if _sign(d0) != _sign(d1) and abs(e) > abs(3 * d0):
            return 3 * d0
        return e

    m[0] = edge(hs[0], hs[1], d[0], d[1])
    m[-1] = edge(hs[-1], hs[-2], d[-1], d[-2])
    return m


def par_at(years: list[float], yields: list[float], t: float) -> float:
    """Par yield at maturity t: monotone cubic between tenors (no overshoot), flat beyond the ends.

    Linear interpolation would put kinks at every tenor and turn the forward curve into a saw.
    """
    n = len(years)
    if t <= years[0]:
        return yields[0]
    if t >= years[-1]:
        return yields[-1]
    m = pchip_slopes(years, yields)
    k = 0
    while k < n - 2 and t > years[k + 1]:
        k += 1
    hk = years[k + 1] - years[k]
    u = (t - years[k]) / hk
    return ((2 * u ** 3 - 3 * u ** 2 + 1) * yields[k] + (u ** 3 - 2 * u ** 2 + u) * hk * m[k]
            + (-2 * u ** 3 + 3 * u ** 2) * yields[k + 1] + (u ** 3 - u ** 2) * hk * m[k + 1])


@dataclass
class ZeroCurve:
    grid: np.ndarray      # 0.5, 1.0, ... years
    df: np.ndarray        # discount factors
    zero: np.ndarray      # zero rates, semiannual compounding


def bootstrap(years: list[float], yields: list[float], max_t: float = 30.0) -> ZeroCurve:
    """Semiannual bootstrap. Bills (one year and in) are treated as zero-coupon; coupon tenors are par bonds."""
    grid, df, total = [], [], 0.0
    for k in range(1, int(np.floor(max_t * 2 + 0.5)) + 1):
        t = k / 2
        c = par_at(years, yields, t)
        d = (1 + c / 2) ** (-2 * t) if t <= 1 else (1 - (c / 2) * total) / (1 + c / 2)
        grid.append(t)
        df.append(d)
        total += d
    grid_a, df_a = np.array(grid), np.array(df)
    return ZeroCurve(grid_a, df_a, 2 * (df_a ** (-1 / (2 * grid_a)) - 1))


def df_at(curve: ZeroCurve, t: float) -> float:
    if t <= 0:
        return 1.0
    i = int(np.floor(t * 2 + 0.5)) - 1
    if 0 <= i < len(curve.grid) and abs(curve.grid[i] - t) < 1e-9:
        return float(curve.df[i])
    j = min(len(curve.grid) - 1, max(0, int(np.floor(t * 2)) - 1))
    if t < curve.grid[0]:
        z = curve.zero[0]
    elif j + 1 < len(curve.grid):
        z = curve.zero[j] + (curve.zero[j + 1] - curve.zero[j]) * ((t - curve.grid[j]) / 0.5)
    else:
        z = curve.zero[j]
    return float((1 + z / 2) ** (-2 * t))


def forward_rate(curve: ZeroCurve, t1: float, t2: float) -> float:
    return 2 * ((df_at(curve, t1) / df_at(curve, t2)) ** (1 / (2 * (t2 - t1))) - 1)


def carry_roll(years: list[float], yields: list[float], maturity: float, repo: float) -> dict:
    """One-year carry and roll-down of a par bond financed at `repo`, if the curve does not move.

    breakeven_bp is the yield rise over the year that leaves the financed position flat.
    """
    c = par_at(years, yields, maturity)
    m_h = maturity - 1
    y_h = par_at(years, yields, m_h)
    roll = (bond_price(y_h, m_h, c) - 100) / 100
    carry = c - repo
    dur_h = duration_convexity(y_h, m_h, c)[0] if m_h > 0 else 0.0

    def pnl(dy: float) -> float:
        return (bond_price(y_h + dy, m_h, c) - 100) / 100 + carry

    lo, hi = -0.05, 0.05
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if pnl(mid) > 0 else (lo, mid)
    return {"maturity": maturity, "coupon": c, "yield_at_horizon": y_h, "carry": carry, "roll": roll,
            "total": roll + carry, "duration_at_horizon": dur_h, "breakeven_bp": (lo + hi) / 2 * 1e4}


FUTURES = {  # cheapest-to-deliver assumed to be the shortest deliverable: right while yields sit below 6%
    "ZN": {"name": "10-year note", "ctd": 6.5, "face": 100_000},
    "TN": {"name": "Ultra 10-year", "ctd": 9 + 5 / 12, "face": 100_000},
    "ZB": {"name": "Bond", "ctd": 15.0, "face": 100_000},
    "UB": {"name": "Ultra bond", "ctd": 25.0, "face": 100_000},
}


def futures_dv01(years: list[float], yields: list[float], key: str) -> dict:
    """Approximate futures DV01 = CTD DV01 / conversion factor (CME: 6% yield, maturity in whole quarters)."""
    f = FUTURES[key]
    mat, cpn = f["ctd"], par_at(years, yields, f["ctd"])
    price = bond_price(cpn, mat, cpn)
    dur = duration_convexity(cpn, mat, cpn)[0]
    ctd_dv01 = dur * price / 100 * f["face"] * 1e-4
    cf = bond_price(0.06, np.floor(mat * 4) / 4, cpn) / 100
    return {"key": key, "ctd_years": mat, "coupon": cpn, "cf": cf, "ctd_dv01": ctd_dv01, "dv01": ctd_dv01 / cf}
