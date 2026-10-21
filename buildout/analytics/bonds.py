"""Bond math: exact repricing, duration/convexity, and long-bond return proxies from FRED yields."""
from __future__ import annotations

import numpy as np
import pandas as pd


def bond_price(y: float, maturity: float, coupon: float, freq: int = 2, shift: float = 0.0) -> float:
    """Full (dirty) price per 100 face. Cash flows sit on the original coupon grid, `shift` years closer."""
    n = int(np.floor(maturity * freq + 0.5))     # half-up, matching Math.round in the page
    times = np.arange(1, n + 1) / freq - shift
    times = times[times > 0]
    disc = (1 + y / freq) ** (-freq * times)
    cfs = np.full(times.shape, 100 * coupon / freq)
    cfs[-1] += 100
    return float((cfs * disc).sum())


def duration_convexity(y: float, maturity: float, coupon: float, freq: int = 2, h: float = 1e-4) -> tuple[float, float]:
    p0 = bond_price(y, maturity, coupon, freq)
    up, dn = bond_price(y + h, maturity, coupon, freq), bond_price(y - h, maturity, coupon, freq)
    return (dn - up) / (2 * p0 * h), (up + dn - 2 * p0) / (p0 * h * h)


def shock_return(y0: float, dy: float, maturity: float, coupon: float, horizon_years: float = 0.0, freq: int = 2) -> float:
    """Total return of a bond over `horizon_years` when its yield moves from y0 to y0 + dy (decimals)."""
    p0 = bond_price(y0, maturity, coupon, freq)
    p1 = bond_price(y0 + dy, maturity, coupon, freq, shift=horizon_years)
    paid = coupon * 100 * np.floor(horizon_years * freq + 1e-9) / freq
    return (p1 + paid) / p0 - 1


def calibrate_coupon(y: float, maturity: float, target_duration: float, freq: int = 2) -> float:
    """Coupon that gives a representative bond the target modified duration (e.g. TLT's ~15.5y)."""
    lo, hi = 0.0, 0.15
    for _ in range(80):
        mid = (lo + hi) / 2
        d, _ = duration_convexity(y, maturity, mid, freq)
        lo, hi = (mid, hi) if d > target_duration else (lo, mid)
    return (lo + hi) / 2


def constant_maturity_returns(yields_pct: pd.Series, maturity: float = 20.0, freq: int = 2) -> pd.Series:
    """Daily total return of buying a par bond each day at yesterday's yield and repricing it today.

    The standard way to build long-history bond returns from constant-maturity yields (FRED DGSxx).
    """
    y = (yields_pct / 100).dropna()
    out = pd.Series(np.nan, index=y.index, name=f"cm{maturity:g}y")
    for i in range(1, len(y)):
        dt = (y.index[i] - y.index[i - 1]).days / 365.25
        c = y.iloc[i - 1]
        out.iloc[i] = bond_price(y.iloc[i], maturity, c, freq, shift=dt) / 100 - 1
    return out
