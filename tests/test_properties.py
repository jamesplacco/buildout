"""Property tests: laws the math must obey for every input, not just the examples someone thought of.

Hypothesis generates the inputs and shrinks any failure to the smallest case that breaks a law. The first
run of these tests found two real bugs (an unreachable duration target returned a wrong bond; a kinked par
curve produced negative discount factors); both now fail loudly instead.
"""
import math

import numpy as np
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from buildout.analytics import bonds, curve, options

yields = st.floats(min_value=0.0005, max_value=0.15)
mats = st.floats(min_value=0.5, max_value=30.0)
cpns = st.floats(min_value=0.0, max_value=0.12)
SET = settings(max_examples=150, deadline=None)


@SET
@given(yields, mats, cpns)
def test_price_falls_as_yield_rises(y, m, c):
    assert bonds.bond_price(y + 0.0025, m, c) < bonds.bond_price(y, m, c)


@SET
@given(yields, mats, cpns)
def test_duration_predicts_small_moves(y, m, c):
    d, cx = bonds.duration_convexity(y, m, c)
    p0, p1 = bonds.bond_price(y, m, c), bonds.bond_price(y + 0.0025, m, c)
    taylor = -d * 0.0025 + 0.5 * cx * 0.0025 ** 2
    n = 2 * m
    third = (n + 2) ** 3 / 6 * (0.0025 / 2) ** 3          # bound on the third-order term
    assert abs((p1 / p0 - 1) - taylor) <= third + 1e-12


@SET
@given(yields, mats, cpns)
def test_par_bond_prices_at_par(y, m, c):
    assert bonds.bond_price(y, round(m * 2) / 2, y) == np.float64(100.0) or abs(bonds.bond_price(y, round(m * 2) / 2, y) - 100) < 1e-9


@SET
@given(yields, st.floats(min_value=10.0, max_value=30.0), st.floats(min_value=1.0, max_value=40.0))
def test_calibrated_coupon_hits_the_target_or_refuses(y, m, target):
    c = bonds.calibrate_coupon(y, m, target)
    if math.isnan(c):
        lo = bonds.duration_convexity(y, m, 1.0)[0]
        hi = bonds.duration_convexity(y, m, 0.0)[0]
        assert not (lo <= target <= hi)
    else:
        assert abs(bonds.duration_convexity(y, m, c)[0] - target) < 1e-6


par_curves = st.lists(st.floats(min_value=0.001, max_value=0.09), min_size=11, max_size=11)
YEARS = [1 / 12, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30]


@SET
@given(par_curves)
def test_bootstrap_reprices_par_bonds_or_flags_the_curve(ys):
    z = curve.bootstrap(YEARS, ys)
    if not z.ok:
        assert z.valid_to < 30 and math.isnan(curve.df_at(z, 30.0))
        return
    for m in (2, 5, 10, 30):
        c = curve.par_at(YEARS, ys, m)
        pv = sum(c / 2 * curve.df_at(z, k / 2) for k in range(1, 2 * m + 1)) + curve.df_at(z, m)
        assert abs(pv - 1) < 1e-9


@SET
@given(st.floats(50, 150), st.floats(50, 150), st.floats(0.02, 3.0), st.floats(0.0, 0.08), st.floats(0.0, 0.04), st.floats(0.05, 1.2))
def test_put_call_parity(S, K, T, r, q, v):
    c = options.bs(S, K, T, r, q, v, "call")["price"]
    p = options.bs(S, K, T, r, q, v, "put")["price"]
    assert abs((c - p) - (S * math.exp(-q * T) - K * math.exp(-r * T))) < 1e-8 * max(1, S)


@SET
@given(st.floats(70, 130), st.floats(0.05, 2.0), st.floats(0.08, 0.9), st.sampled_from(["put", "call"]))
def test_implied_vol_round_trips(K, T, v, kind):
    price = options.bs(100, K, T, 0.04, 0.0, v, kind)["price"]
    intrinsic = max(0.0, (K * math.exp(-0.04 * T) - 100) if kind == "put" else (100 - K * math.exp(-0.04 * T)))
    assume(price - intrinsic > 1e-6)                      # deep in the money options carry no vol information
    iv = options.implied_vol(price, 100, K, T, 0.04, 0.0, kind)
    assert abs(iv - v) < 1e-5
