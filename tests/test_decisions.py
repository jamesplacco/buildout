"""Decision math: Kelly, scoring rules, luck tests and the journal scorecard."""
import math
import random

import numpy as np

import pytest

from buildout import decisions as dc


def test_kelly_and_the_hill():
    assert dc.kelly(0.6, 1.0) == pytest.approx(0.2)              # even money at 60%: bet 20%
    assert dc.kelly(0.4, 1.0) == 0.0                              # no edge, no bet
    f = dc.kelly(0.55, 2.0)
    # the Kelly fraction maximizes expected log growth; twice Kelly grows about as slowly as zero... or worse
    g = lambda x: dc.log_growth(x, 0.55, 2.0)                    # noqa: E731
    assert g(f) > g(f * 0.5) > 0 and g(f) > g(f * 1.5)
    assert g(2 * f) < g(f) * 0.05 + 1e-12
    assert math.isnan(dc.kelly(1.2, 1.0))


def test_scoring_rules():
    assert dc.brier([1, 0], [1, 0]) == 0.0
    assert dc.brier([0.5] * 4, [1, 0, 1, 0]) == pytest.approx(0.25)
    cal = dc.calibration([0.9, 0.9, 0.1, 0.1], [1, 0, 0, 0])
    assert cal[0]["realized"] == 0.0 and cal[-1]["realized"] == 0.5


def test_luck_tests():
    assert dc.binom_tail(10, 0, 0.5) == 1.0 and dc.binom_tail(10, 11, 0.5) == 0.0
    assert dc.binom_tail(10, 7, 0.5) == pytest.approx(176 / 1024)    # 7, 8, 9 or 10 heads in 10 flips
    assert dc.years_to_significance(0.5) == pytest.approx(16.0)       # a Sharpe of 0.5 needs 16 years at t = 2
    assert dc.years_to_significance(0.0) == math.inf


def test_growth_math_matches_simulation():
    # the +50% / -40% coin: the average player grows 5% a round, the typical player shrinks 5.1%
    assert math.sqrt(1.5 * 0.6) - 1 == pytest.approx(-0.0513, abs=1e-4)
    mu, sig, r = 0.10, 0.25, 0.04
    best = (mu - r) / sig ** 2                                          # growth-optimal leverage
    assert dc.lev_growth(mu, sig, r, best) > dc.lev_growth(mu, sig, r, best * 0.5)
    assert dc.lev_growth(mu, sig, r, 2 * best) == pytest.approx(r, abs=1e-12)   # twice optimal leverage earns the cash rate
    rng = random.Random(3)
    lev, years, n = 1.5, 30, 3000
    logs = []
    for _ in range(n):                                  # monthly rebalancing approximates the continuous formula
        x = 0.0
        for _ in range(12 * years):
            ret = rng.gauss(mu / 12, sig / math.sqrt(12))
            x += math.log1p(r / 12 + lev * (ret - r / 12))
        logs.append(x / years)
    assert sum(logs) / n == pytest.approx(dc.lev_growth(mu, sig, r, lev), abs=0.006)


def test_conjunction_bayes_diversification():
    assert dc.conjunction([0.8] * 5) == pytest.approx(0.32768)
    assert dc.bayes(0.15, 0.9, 0.9) == pytest.approx(0.135 / (0.135 + 0.085))
    assert dc.div_ratio(15, 0.0) == pytest.approx(1 / math.sqrt(15))
    assert dc.div_ratio(15, 0.6) == pytest.approx(math.sqrt((1 + 14 * 0.6) / 15))


def test_tail_hedge_can_raise_compound_growth():
    scen = [(0.9, 0.12), (0.1, -0.40)]
    bare = dc.hedge_cagr(scen, 0.0)
    hedged = dc.hedge_cagr(scen, 0.02, {1: 0.15})                       # costs 2% a year, pays 15% in the crash
    # the hedge loses money on average (expected payoff 1.5% against a 2% cost), yet compound growth rises
    assert 0.9 * 0.12 + 0.1 * -0.40 > 0.9 * (0.12 - 0.02) + 0.1 * (-0.40 - 0.02 + 0.15)
    assert hedged > bare
    assert dc.hedge_cagr([(1.0, -1.2)], 0.0) == -1.0                    # ruin is ruin


def test_scorecard_separates_luck_from_skill():
    base = {"status": "closed", "beta": 1.0, "process": {k: True for k in dc.PROCESS_ITEMS}}
    recs = [
        dict(base, p=0.7, right=1, ret=0.10, bench_ret=0.02),           # good process, beat the market: earned
        dict(base, p=0.6, right=0, ret=-0.05, bench_ret=0.01),          # good process, lost: bad luck
        dict(base, p=0.8, right=1, ret=0.20, bench_ret=0.25, process={"logged_before": False}),   # rode the market: not alpha
        dict(base, p=0.5, right=0, ret=-0.10, bench_ret=0.0, process={}),
        {"status": "open", "p": 0.5},
        {"status": "closed", "p": 0.5, "right": None, "ret": 0.0},      # not scored until judged
    ]
    sc = dc.scorecard(recs)
    assert sc["n_closed"] == 4 and sc["n_open"] == 1
    assert sc["grid"] == {"earned": 1, "bad_luck": 1, "dumb_luck": 0, "deserved": 1, "unknown_process": 1}   # {} is unknown, not bad
    assert sc["brier"] == pytest.approx(((0.7 - 1) ** 2 + 0.6 ** 2 + (0.8 - 1) ** 2 + 0.5 ** 2) / 4)
    assert sc["alpha"]["mean"] == pytest.approx((0.08 - 0.06 - 0.05 - 0.10) / 4)
    assert sc["hit_rate"] == 0.5 and sc["overconfidence"] == pytest.approx(0.65 - 0.5)


def test_position_kelly_is_the_growth_maximizer():
    """The closed form f* = p/l - (1-p)/w maximizes expected log growth, checked numerically; no edge, no bet."""
    from scipy.optimize import minimize_scalar
    from buildout.decisions import position_kelly
    for p, w, l in [(0.55, 0.06, 0.08), (0.62, 0.04, 0.02), (0.5, 0.3, 0.1), (0.7, 0.03, 0.03), (0.4, 0.5, 0.2)]:
        f = position_kelly(p, w, l)
        g = lambda x: -(p * np.log1p(x * w) + (1 - p) * np.log1p(-x * l))  # noqa: E731
        best = minimize_scalar(g, bounds=(0, 0.999 / l), method="bounded", options={"xatol": 1e-10}).x
        assert f == pytest.approx(max(0.0, best), abs=1e-5)
        assert f == pytest.approx(max(0.0, dc.kelly(p, w / l) / l), abs=1e-12)
    assert position_kelly(0.55, 0.06, 0.08) == 0.0          # negative expectancy: 0.55 x 6% < 0.45 x 8%
    assert np.isnan(position_kelly(0.5, 0.1, 0))


def test_partly_right_scores_half_and_luck_uses_base_rates():
    base = {"status": "closed", "beta": 1.0, "ret": 0.01, "bench_ret": 0.0}
    sc = dc.scorecard([dict(base, p=0.7, right=0.5), dict(base, p=0.9, right=1, base=0.8), dict(base, p=0.9, right=1, base=0.8)])
    assert sc["brier"] == pytest.approx(((0.7 - 0.5) ** 2 + 0.1 ** 2 + 0.1 ** 2) / 3)
    assert sc["hit_rate"] == pytest.approx(2.5 / 3)
    # two full hits from calls whose base rates were 50%, 80% and 80%
    p = dc.poisson_binom_tail([0.5, 0.8, 0.8], 2)
    assert sc["luck_p_value"] == pytest.approx(p) and p > dc.binom_tail(3, 2, 0.5)
    assert dc.poisson_binom_tail([0.5] * 10, 7) == pytest.approx(dc.binom_tail(10, 7, 0.5))
