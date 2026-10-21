"""Curve and option math: identities that must hold whatever the inputs."""
import math

import numpy as np
import pytest

from buildout.analytics import bonds, curve, options

YEARS = [1 / 12, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30]
OCT19 = [y / 100 for y in [4.11, 4.27, 4.37, 4.50, 4.77, 4.85, 4.94, 5.04, 5.15, 5.53, 5.48]]


def test_bootstrap_reprices_every_par_bond():
    zc = curve.bootstrap(YEARS, OCT19)
    for k, t in enumerate(zc.grid):
        if t <= 1:
            continue
        c = curve.par_at(YEARS, OCT19, t)
        pv = c / 2 * zc.df[:k].sum() + (1 + c / 2) * zc.df[k]
        assert pv == pytest.approx(1.0, abs=1e-12)


def test_flat_curve_has_flat_zeros_and_forwards():
    flat = [0.05] * len(YEARS)
    zc = curve.bootstrap(YEARS, flat)
    assert np.allclose(zc.zero, 0.05, atol=1e-12)
    for a, b in ((0, 1), (1, 2), (5, 10), (10, 30)):
        assert curve.forward_rate(zc, a, b) == pytest.approx(0.05, abs=1e-12)
    c = curve.carry_roll(YEARS, flat, 10, repo=0.05)
    assert c["roll"] == pytest.approx(0, abs=1e-12) and c["total"] == pytest.approx(0, abs=1e-12)
    assert c["breakeven_bp"] == pytest.approx(0, abs=1e-6)


def test_upward_curve_pays_carry_and_roll():
    up = [0.02 + 0.001 * t for t in YEARS]
    c = curve.carry_roll(YEARS, up, 10, repo=up[1])
    assert c["carry"] > 0 and c["roll"] > 0 and c["breakeven_bp"] > 0
    # forwards sit above spot on an upward-sloping curve
    zc = curve.bootstrap(YEARS, up)
    assert curve.forward_rate(zc, 5, 10) > curve.par_at(YEARS, up, 10)


def test_futures_dv01_ordering_and_conversion():
    fut = {k: curve.futures_dv01(YEARS, OCT19, k) for k in ("ZN", "TN", "ZB", "UB")}
    assert fut["ZN"]["dv01"] < fut["TN"]["dv01"] < fut["ZB"]["dv01"] < fut["UB"]["dv01"]
    for f in fut.values():                      # coupons below the 6% factor yield give factors below one
        assert 0.7 < f["cf"] < 1.0 and f["dv01"] > f["ctd_dv01"]
    assert 40 < fut["ZN"]["dv01"] < 80 and 100 < fut["UB"]["dv01"] < 220


def test_put_call_parity_and_greeks():
    S, r, q = 100.0, 0.0427, 0.006
    for K in (80, 100, 125):
        for T in (0.1, 1.0, 2.5):
            for v in (0.15, 0.4):
                c, p = options.bs(S, K, T, r, q, v, "call"), options.bs(S, K, T, r, q, v, "put")
                assert c["price"] - p["price"] == pytest.approx(S * math.exp(-q * T) - K * math.exp(-r * T), abs=1e-10)
                h = 1e-3
                up, dn = options.bs(S + h, K, T, r, q, v, "call"), options.bs(S - h, K, T, r, q, v, "call")
                assert c["delta"] == pytest.approx((up["price"] - dn["price"]) / (2 * h), abs=1e-6)
                assert c["gamma"] == pytest.approx((up["price"] - 2 * c["price"] + dn["price"]) / h ** 2, abs=1e-4)
                vu, vd = options.bs(S, K, T, r, q, v + 1e-4, "call")["price"], options.bs(S, K, T, r, q, v - 1e-4, "call")["price"]
                assert c["vega"] == pytest.approx((vu - vd) / 2e-4 / 100, rel=1e-5, abs=1e-9)
                tm = options.bs(S, K, T - 1 / 365, r, q, v, "call")["price"]
                assert c["theta"] == pytest.approx(tm - c["price"], rel=2e-2, abs=1e-4)


def test_implied_vol_round_trip_and_bounds():
    for kind in ("call", "put"):
        for K, T, v in ((90, 0.25, 0.24), (100, 1, 0.2), (130, 3, 0.55)):
            px = options.bs(100, K, T, 0.04, 0.01, v, kind)["price"]
            assert options.implied_vol(px, 100, K, T, 0.04, 0.01, kind) == pytest.approx(v, abs=1e-8)
    assert math.isnan(options.implied_vol(0.0, 100, 100, 1, 0.04, 0, "call"))
    assert math.isnan(options.implied_vol(150.0, 100, 100, 1, 0.04, 0, "call"))   # above the spot bound
    assert math.isnan(options.implied_vol(1.0, 100, 50, 1, 0.04, 0, "call"))      # below intrinsic


def test_degenerate_option_inputs_do_not_raise():
    assert options.bs(100, 90, 0, 0.04, 0, 0.2, "call")["price"] == pytest.approx(10)
    assert options.bs(100, 110, 1, 0.04, 0, 0, "put")["price"] >= 0
    assert math.isnan(options.bs(0, 100, 1, 0.04, 0, 0.2, "call")["price"])


def test_bond_price_identities():
    for y in (0.01, 0.05, 0.09):
        for m in (1, 5, 30):
            assert bonds.bond_price(y, m, y) == pytest.approx(100, abs=1e-9)          # par at coupon = yield
            p_lo, p_hi = bonds.bond_price(y - 0.01, m, 0.04), bonds.bond_price(y + 0.01, m, 0.04)
            assert p_lo > bonds.bond_price(y, m, 0.04) > p_hi                         # price falls as yield rises
            d, cx = bonds.duration_convexity(y, m, 0.04)
            assert 0 < d < m and cx > 0
        d0, _ = bonds.duration_convexity(y, 10, 0.0)                                  # zero: D = T / (1 + y/2)
        assert d0 == pytest.approx(10 / (1 + y / 2), rel=1e-6)
    assert bonds.bond_price(0.05, 0.25, 0.05) > 0                                     # half-period maturities price
