"""Rates of change: how fast a market is moving toward a decision threshold, and whether it is speeding up.

Level tells you where a series is. The desk decides on three more numbers:

  velocity      v = OLS slope of the last `weeks` of observations, in units per week
  acceleration  a = v(last window) - v(the window before it), per window
  time to trigger  T = (threshold - level) / v, in weeks, when v points at the threshold

A least-squares slope uses every point in the window, so one noisy print moves it far less than a
two-point difference. The page computes the same numbers with the same formulas (site/src/math.js),
and tests/test_page.py checks the two agree.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def ols_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Least-squares slope of y on x; NaN with fewer than three points or no spread in x."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 3:
        return float("nan")
    dx = x - x.mean()
    sxx = float((dx * dx).sum())
    if sxx <= 0:
        return float("nan")
    return float((dx * (y - y.mean())).sum() / sxx)


def velocity(s: pd.Series, weeks: float = 13, end: pd.Timestamp | None = None) -> float:
    """Slope per week over the `weeks` before `end` (default: the last observation)."""
    s = s.dropna()
    if s.empty:
        return float("nan")
    end = s.index[-1] if end is None else end
    w = s.loc[end - pd.Timedelta(weeks=weeks):end]
    t = (w.index - end).days.to_numpy() / 7.0
    return ols_slope(t, w.to_numpy())


def acceleration(s: pd.Series, weeks: float = 13) -> float:
    """Velocity over the last window minus velocity over the window before it."""
    s = s.dropna()
    if s.empty:
        return float("nan")
    end = s.index[-1]
    prior_end = end - pd.Timedelta(weeks=weeks)
    if s.index[0] > prior_end - pd.Timedelta(weeks=weeks / 2):
        return float("nan")
    return velocity(s, weeks, end) - velocity(s, weeks, prior_end)


def time_to_trigger(level: float, v: float, threshold: float) -> float:
    """Weeks until `level` reaches `threshold` at velocity `v`.

    0 if it is already there or beyond in the direction of travel, inf when moving away or not moving.
    """
    if not all(map(math.isfinite, (level, threshold))):
        return float("nan")
    gap = threshold - level
    if gap == 0:
        return 0.0
    if not math.isfinite(v) or v == 0 or (gap > 0) != (v > 0):
        return float("inf")
    return gap / v


def velocity_z(s: pd.Series, weeks: float = 13, years: int = 5) -> float:
    """Today's velocity against every weekly-sampled velocity over the past `years` (how unusual the speed is)."""
    s = s.dropna()
    if len(s) < 60:
        return float("nan")
    end = s.index[-1]
    fridays = pd.date_range(end - pd.DateOffset(years=years), end, freq="W-FRI")
    vs = [velocity(s, weeks, d) for d in fridays if d - pd.Timedelta(weeks=weeks) >= s.index[0]]
    vs = np.array([v for v in vs if math.isfinite(v)])
    if len(vs) < 30 or vs.std() <= 0:
        return float("nan")
    return float((velocity(s, weeks) - vs.mean()) / vs.std())


def roc_row(s: pd.Series, scale: float = 1.0) -> dict:
    """Velocity (13 and 4 weeks), acceleration and how unusual the speed is, in the series' units times `scale`."""
    v13, v4 = velocity(s, 13), velocity(s, 4)
    a13 = acceleration(s, 13)
    out = {"v13": v13 * scale, "v4": v4 * scale, "a13": a13 * scale, "z_v13": velocity_z(s, 13)}
    return {k: (float(v) if math.isfinite(v) else None) for k, v in out.items()}
