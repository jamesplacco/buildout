"""Rates of change: slopes recover planted speeds, acceleration sees a change of speed, triggers point the right way."""
import math

import numpy as np
import pandas as pd
import pytest

from buildout import roc


def _weekly(values, end="2026-10-16"):
    return pd.Series(values, index=pd.date_range(end=end, periods=len(values), freq="W-FRI"))


def test_slope_recovers_a_planted_speed_through_noise():
    rng = np.random.default_rng(4)
    s = _weekly(2.0 + 0.04 * np.arange(60) + rng.normal(0, 0.03, 60))     # +4bp a week (in percent units)
    assert roc.velocity(s, 13) == pytest.approx(0.04, abs=0.01)
    assert roc.velocity(s.iloc[:2], 13) != roc.velocity(s.iloc[:2], 13)     # two points: no slope (NaN)


def test_acceleration_sees_a_change_of_speed():
    flat_then_up = _weekly(np.r_[np.full(39, 3.0), 3.0 + 0.1 * np.arange(1, 14)])   # still for 39 weeks, then +10bp a week
    a = roc.acceleration(flat_then_up, 13)
    assert a > 0.08                                     # the last window moves ~0.1 a week, the one before it ~0
    assert roc.velocity(flat_then_up, 13) == pytest.approx(a, abs=0.02)
    steady = _weekly(1 + 0.05 * np.arange(52))
    assert abs(roc.acceleration(steady, 13)) < 1e-9


def test_time_to_trigger_directions():
    assert roc.time_to_trigger(2.77, 0.041, 3.0) == pytest.approx((3.0 - 2.77) / 0.041)
    assert roc.time_to_trigger(2.77, -0.041, 3.0) == math.inf          # moving away
    assert roc.time_to_trigger(3.1, 0.041, 3.0) == math.inf            # beyond the line and moving further: never returns to it
    assert roc.time_to_trigger(3.0, 0.5, 3.0) == 0.0
    assert roc.time_to_trigger(2.0, 0.0, 3.0) == math.inf
    assert math.isnan(roc.time_to_trigger(float("nan"), 0.1, 3.0))


def test_velocity_z_flags_an_unusually_fast_move():
    rng = np.random.default_rng(9)
    base = 2 + np.cumsum(rng.normal(0, 0.01, 400))
    base[-13:] += 0.08 * np.arange(1, 14)                               # a sudden 8bp-a-week climb
    z = roc.velocity_z(_weekly(base), 13)
    assert z > 3
    row = roc.roc_row(_weekly(base), scale=100)
    assert row["v13"] == pytest.approx(roc.velocity(_weekly(base), 13) * 100)
    assert set(row) == {"v13", "v4", "a13", "z_v13"}
