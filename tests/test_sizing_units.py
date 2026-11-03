"""Direct unit tests of the sizing functions against closed forms: volatility targeting scales inversely with volatility
and respects its cap and floor; Kelly is fraction * inv(cov) mu (mu / sigma^2 for one asset); ERC equalizes risk
contributions; the drawdown simulation matches the deterministic drawdown when volatility is zero, borrowing cost
included; the volatility-managed rule's exposure is rebuilt exactly from volatility known at the previous month's last
close and is unchanged by any data after it; the expected maximum t grows with the count of trials."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from buildout import sizing_rules as SR
from buildout.analytics import sizing as S


def _returns(n=1500, seed=3, scale=0.012):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0002, scale, n), index=pd.bdate_range("2015-01-01", periods=n))


# ---------------------------------------------------------------- analytics.sizing
def test_vol_scale_halves_when_vol_doubles():
    a = S.vol_scale(0.10, 0.10, cap=10.0)
    b = S.vol_scale(0.20, 0.10, cap=10.0)
    assert a == pytest.approx(1.0) and b == pytest.approx(a / 2)
    v = np.array([0.05, 0.10, 0.20, 0.40])
    s = S.vol_scale(v, 0.10, cap=10.0)
    assert np.allclose(s[1:] / s[:-1], 0.5)


def test_vol_scale_respects_cap_and_floor():
    s = S.vol_scale(np.array([0.01, 0.10, -0.10]), 0.20, cap=1.5)
    assert s[0] == 1.5 and s[1] == pytest.approx(1.5) and s[2] == 0.0
    assert S.vol_scale(0.40, 0.20, cap=1.5) == pytest.approx(0.5)


def test_kelly_single_asset_is_mu_over_sigma_squared():
    mu, sigma = 0.06, 0.25
    cov = pd.DataFrame([[sigma ** 2]], index=["A"], columns=["A"])
    f = S.kelly(pd.Series({"A": mu}), cov, fraction=1.0)
    assert f["A"] == pytest.approx(mu / sigma ** 2)                       # 0.96
    assert S.kelly(pd.Series({"A": mu}), cov, fraction=0.25)["A"] == pytest.approx(0.25 * mu / sigma ** 2)


def test_kelly_multi_asset_is_inverse_cov_times_mu_and_aligns_by_name():
    names = ["A", "B", "C"]
    vol = np.array([0.2, 0.3, 0.5])
    corr = np.array([[1, 0.5, 0.2], [0.5, 1, 0.3], [0.2, 0.3, 1]])
    cov = pd.DataFrame(np.outer(vol, vol) * corr, index=names, columns=names)
    mu = pd.Series({"C": 0.08, "A": 0.04, "B": 0.05})                      # given out of order on purpose
    f = S.kelly(mu, cov, fraction=0.5)
    expect = 0.5 * np.linalg.inv(cov.to_numpy()) @ mu.reindex(names).to_numpy()
    assert list(f.index) == names and np.allclose(f.to_numpy(), expect)
    diag = pd.DataFrame(np.diag(vol ** 2), index=names, columns=names)
    assert np.allclose(S.kelly(mu, diag, fraction=1.0).to_numpy(), mu.reindex(names).to_numpy() / vol ** 2)


def test_kelly_gross_cap_scales_proportionally():
    names = ["A", "B"]
    cov = pd.DataFrame(np.diag([0.04, 0.09]), index=names, columns=names)
    mu = pd.Series({"A": 0.08, "B": -0.09})
    raw = S.kelly(mu, cov, fraction=1.0)                                   # 2.0 and -1.0: gross 3
    capped = S.kelly(mu, cov, fraction=1.0, max_gross=1.5)
    assert raw.abs().sum() == pytest.approx(3.0)
    assert capped.abs().sum() == pytest.approx(1.5) and np.allclose(capped / raw, 0.5)
    assert np.allclose(S.kelly(mu, cov, fraction=1.0, max_gross=5.0), raw)   # a cap that does not bind changes nothing


def test_shrink_mean_weights_the_sample_by_years():
    mu = pd.Series({"A": 0.20, "B": -0.10})
    assert np.allclose(S.shrink_mean(mu, years=10, prior_years=10), mu / 2)
    assert np.allclose(S.shrink_mean(mu, years=30, prior_years=10, prior=0.04), 0.04 + 0.75 * (mu - 0.04))
    assert np.allclose(S.shrink_mean(mu, years=0, prior_years=10, prior=0.05), 0.05)


def test_erc_is_inverse_vol_for_uncorrelated_assets():
    vol = np.array([0.1, 0.2, 0.4])
    cov = pd.DataFrame(np.diag(vol ** 2), index=list("ABC"), columns=list("ABC"))
    w = S.erc(cov)
    expect = (1 / vol) / (1 / vol).sum()
    assert np.allclose(w.to_numpy(), expect, atol=1e-6) and w.sum() == pytest.approx(1.0)


def test_erc_equalizes_risk_contributions_and_honours_a_budget():
    names = list("ABCD")
    vol = np.array([0.15, 0.25, 0.35, 0.5])
    corr = np.full((4, 4), 0.4) + 0.6 * np.eye(4)
    cov = pd.DataFrame(np.outer(vol, vol) * corr, index=names, columns=names)
    w = S.erc(cov).to_numpy()
    rc = w * (cov.to_numpy() @ w)
    assert (w > 0).all() and np.allclose(rc / rc.sum(), 0.25, atol=1e-4)
    b = pd.Series({"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0})
    wb = S.erc(cov, budget=b).to_numpy()
    rcb = wb * (cov.to_numpy() @ wb)
    assert np.allclose(rcb / rcb.sum(), (b / b.sum()).to_numpy(), atol=1e-4)


def test_drawdown_quantile_matches_the_deterministic_case():
    # zero volatility, negative drift: the price falls along a straight line in logs, max drawdown 1 - exp(mu * years)
    assert S.drawdown_quantile(-0.10, 0.0, 1.0, cash_rate=0.0) == pytest.approx(1 - math.exp(-0.10), rel=1e-9)
    # levered 2x: drift 2 mu, minus cash on the borrowed unit, minus the spread: 2(-0.10) - 0.04 - 0.01 = -0.25
    assert S.drawdown_quantile(-0.10, 0.0, 2.0, cash_rate=0.04, borrow_spread=0.01) == pytest.approx(1 - math.exp(-0.25), rel=1e-9)
    assert S.drawdown_quantile(0.10, 0.0, 1.5) == 0.0                     # a rising line never draws down
    assert S.drawdown_quantile(0.10, 0.30, 0.0) == 0.0                    # all cash


def test_drawdown_quantile_rises_with_leverage_and_quantile():
    dds = [S.drawdown_quantile(0.08, 0.30, L, n_paths=1500) for L in (0.5, 1.0, 1.5, 2.0)]
    assert all(a < b for a, b in zip(dds, dds[1:]))
    assert S.drawdown_quantile(0.08, 0.30, 1.0, q=0.5, n_paths=1500) < S.drawdown_quantile(0.08, 0.30, 1.0, q=0.95, n_paths=1500)


def test_max_leverage_sits_on_the_limit():
    L = S.max_leverage(0.08, 0.30, 0.30)
    assert 0 < L < 5
    assert S.drawdown_quantile(0.08, 0.30, L) <= 0.30 < S.drawdown_quantile(0.08, 0.30, L + 0.01)
    assert S.max_leverage(0.10, 0.01, 0.50) == 5.0                        # the limit never binds: the upper bound comes back


def test_trim_orders_acts_only_outside_the_band():
    cur = pd.Series({"A": 0.25, "B": 0.10, "C": 0.15, "D": 0.05})
    tgt = pd.Series({"A": 0.20, "B": 0.10, "C": 0.20, "E": 0.10})
    t = S.trim_orders(cur, tgt, band=0.20)
    assert t.loc["A", "action"] == "trim" and t.loc["A", "trade"] == pytest.approx(-0.05)   # 0.25 > 0.24
    assert t.loc["B", "action"] == "hold" and t.loc["B", "trade"] == 0.0
    assert t.loc["C", "action"] == "add" and t.loc["C", "trade"] == pytest.approx(0.05)     # 0.15 < 0.16
    assert t.loc["D", "action"] == "trim" and t.loc["D", "trade"] == pytest.approx(-0.05)   # not in the target: sold
    assert t.loc["E", "action"] == "add" and t.loc["E", "trade"] == pytest.approx(0.10)
    assert S.trim_orders(pd.Series({"A": 0.23}), pd.Series({"A": 0.20}), band=0.20).loc["A", "action"] == "hold"


# ---------------------------------------------------------------- sizing_rules
def test_realized_vol_is_the_annualized_rolling_std_and_scales_linearly():
    r = _returns()
    v = SR.realized_vol(r, 21)
    assert v.iloc[:20].isna().all() and v.iloc[20:].notna().all()
    assert v.iloc[100] == pytest.approx(r.iloc[80:101].std(ddof=1) * math.sqrt(252))
    assert np.allclose(SR.realized_vol(2 * r, 21).dropna(), 2 * v.dropna())


def test_exposure_is_rebuilt_from_the_previous_month_end_volatility():
    r = _returns()
    for rule in ({"window": 21, "target": 0.20, "cap": 1.5, "form": "var"}, {"window": 63, "target": 0.15, "cap": 1.0, "form": "vol"}):
        x = SR.exposure_path(r, rule)
        rv = SR.realized_vol(r, rule["window"])
        month_end = rv.groupby(rv.index.to_period("M")).tail(1)
        raw = rule["target"] ** 2 / month_end ** 2 if rule["form"] == "var" else rule["target"] / month_end
        expect_by_month = pd.Series(raw.clip(0, rule["cap"]).to_numpy(), index=month_end.index.to_period("M")).shift(1)
        expect = pd.Series(expect_by_month.reindex(r.index.to_period("M")).to_numpy(), index=r.index)
        both = expect.notna()
        assert both.sum() > 1000 and np.allclose(x[both], expect[both])
        assert x[~both].isna().all()                                       # nothing is held before a full window is known


def test_vol_form_halves_and_var_form_quarters_when_vol_doubles():
    r = _returns(scale=0.02)                                              # about 32% a year: no rule hits its cap
    rv = {"window": 21, "target": 0.10, "cap": 10.0, "form": "vol"}
    rq = dict(rv, form="var")
    for rule, k in ((rv, 0.5), (rq, 0.25)):
        a, b = SR.exposure_path(r, rule).dropna(), SR.exposure_path(2 * r, rule).dropna()
        assert a.max() < rule["cap"] and np.allclose(b, k * a)


def test_exposure_respects_cap_and_floor():
    calm = _returns(scale=0.002)                                          # 3% a year: the raw exposure is far above any cap
    for rule in SR.RULES:
        x = SR.exposure_path(calm, rule).dropna()
        assert (x == rule["cap"]).all()
    wild = _returns(scale=0.05)
    for rule in SR.RULES:
        x = SR.exposure_path(wild, rule).dropna()
        assert (x >= 0).all() and (x <= rule["cap"]).all() and (x < rule["cap"]).any()


@pytest.mark.parametrize("cut", ["2016-03-31", "2016-04-01", "2016-04-15", "2017-12-29", "2018-06-07"])
def test_exposure_path_uses_no_future_data(cut):
    """The exposure through any day is the same whether or not the data after that day exists, and does not move
    when the rest of the month is rewritten."""
    r = _returns()
    for rule in (SR.HEADLINE, {"window": 63, "target": 0.20, "cap": 1.5, "form": "vol"}):
        full = SR.exposure_path(r, rule)
        trunc = SR.exposure_path(r.loc[:cut], rule)
        pd.testing.assert_series_equal(full.loc[:cut], trunc, check_names=False)
        r2 = r.copy()
        after = r2.index > pd.Timestamp(cut)
        r2[after] = r2[after] * 5 + 0.03
        pd.testing.assert_series_equal(full.loc[:cut], SR.exposure_path(r2, rule).loc[:cut], check_names=False)


def test_rule_returns_are_exposure_times_return_plus_cash_less_cost():
    r = _returns()
    cash = pd.Series(0.0001, index=r.index)
    rule = SR.HEADLINE
    x = SR.exposure_path(r, rule)
    got = SR.rule_returns(r, cash, rule, cost_bp=3.0)
    ok = x.notna()
    turn = x.diff().abs().fillna(0.0)[ok]
    expect = x[ok] * r[ok] + (1 - x[ok]) * cash[ok] - turn * 3.0 / 1e4
    assert np.allclose(got, expect) and got.index.equals(r.index[ok])
    assert (SR.rule_returns(r, cash, rule, cost_bp=0.0) >= got - 1e-15).all()


def test_monthly_compounds_daily_returns():
    idx = pd.bdate_range("2024-01-01", "2024-02-29")
    r = pd.Series(0.01, index=idx)
    m = SR.monthly(r)
    assert m.iloc[0] == pytest.approx(1.01 ** (idx.month == 1).sum() - 1)
    assert m.iloc[1] == pytest.approx(1.01 ** (idx.month == 2).sum() - 1)


def test_utility_is_crra():
    v = np.array([-0.2, 0.0, 0.1])
    assert np.allclose(SR.utility(v, 1.0), np.log(1 + v))
    assert np.allclose(SR.utility(v, 2.0), 1 - 1 / (1 + v))
    assert np.allclose(SR.utility(v, 3.0), ((1 + v) ** -2 - 1) / -2)
    assert SR.utility(np.array([-1.5]), 2.0)[0] == pytest.approx(1 - 1 / 0.02)   # a loss beyond 98% is floored


def test_expected_max_t_is_monotone_and_close_to_simulation():
    ns = [2, 3, 5, 12, 50, 100, 1000]
    e = [SR.expected_max_t(n) for n in ns]
    assert all(a < b for a, b in zip(e, e[1:]))
    rng = np.random.default_rng(0)
    for n in (5, 12, 100):
        sim = rng.standard_normal((20000, n)).max(axis=1).mean()
        assert abs(SR.expected_max_t(n) - sim) < 0.06, n
    assert SR.N_RULES == 12 and SR.expected_max_t(SR.N_RULES) == pytest.approx(1.6648, abs=1e-3)


def test_expected_max_t_of_one_trial_is_zero():      # v0.38: was minus infinity (norm.ppf(0)); fixed
    assert SR.expected_max_t(1) == pytest.approx(0.0, abs=0.1)
