import numpy as np
import pandas as pd

from buildout.analytics.bonds import (bond_price, calibrate_coupon, constant_maturity_returns,
                                      duration_convexity, shock_return)


def test_par_bond_prices_at_par():
    assert abs(bond_price(0.05, 20, 0.05) - 100) < 1e-9


def test_par_duration_matches_closed_form():
    y, n = 0.05, 20
    closed = (1 / y) * (1 - (1 + y / 2) ** (-2 * n))
    d, c = duration_convexity(y, n, y)
    assert abs(d - closed) < 1e-3 and c > 0


def test_shock_return_matches_taylor_expansion():
    d, c = duration_convexity(0.055, 25.8, 0.03)
    for dy, tol in [(0.001, 1e-5), (0.01, 2e-3)]:      # 2nd-order Taylor is exact only for small moves
        taylor = -d * dy + 0.5 * c * dy ** 2
        assert abs(shock_return(0.055, dy, 25.8, 0.03) - taylor) < tol


def test_calibrated_coupon_hits_target_duration():
    cpn = calibrate_coupon(0.0558, 25.8, 15.5)
    assert abs(duration_convexity(0.0558, 25.8, cpn)[0] - 15.5) < 1e-3


def test_flat_yields_earn_carry():
    idx = pd.bdate_range("2024-01-01", periods=253)
    r = constant_maturity_returns(pd.Series(5.0, index=idx), maturity=20)
    annual = (1 + r.dropna()).prod() - 1
    assert abs(annual - 0.05) < 0.003
