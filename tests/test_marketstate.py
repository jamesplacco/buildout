"""Market reads: changes in the right units, honest z-scores, the volatility premium, and the Fed's plumbing."""
import numpy as np
import pandas as pd
import pytest

from buildout import marketstate as ms


def _bdays(n, end="2026-10-16"):
    return pd.bdate_range(end=end, periods=n)


def test_change_units():
    assert ms.change("pct", 100.0, 103.0) == pytest.approx(0.03)
    assert ms.change("bp", 4.50, 4.62) == pytest.approx(12.0)
    assert ms.change("pts", 18.0, 21.5) == pytest.approx(3.5)
    assert ms.change("pct", 0.0, 1.0) is None and ms.change("bp", None, 1.0) is None
    assert ms.change("bp", float("nan"), 1.0) is None


def test_move_row_windows_and_ranks():
    idx = _bdays(3000)
    s = pd.Series(np.linspace(1.0, 5.0, len(idx)), index=idx)
    row = ms.move_row("y10", "10-year", s, "bp")
    assert row["date"] == "2026-10-16" and row["value"] == pytest.approx(5.0)
    assert row["d1"] > 0 and row["w1"] > row["d1"] and row["y1"] > row["m1"] > row["w1"]
    assert row["rank10y"] == pytest.approx(1.0)           # a straight line ends at its ten-year high
    assert row["spark"]["dates"][-1] <= "2026-10-16"
    price = ms.move_row("ndx", "Nasdaq-100", s * 1000, "pct")
    assert "rank10y" not in price                        # prices are not ranked against their own history


def test_weekly_z_flags_a_shock_and_needs_history():
    rng = np.random.default_rng(1)
    idx = _bdays(900)
    s = pd.Series(4 + np.cumsum(rng.normal(0, 0.05, len(idx))), index=idx)
    s.iloc[-1] += 1.0                                    # a 100bp day: far outside three years of weekly moves
    assert ms.weekly_z(s, "bp") > 4
    assert ms.weekly_z(s.iloc[-60:], "bp") is None       # too little history for an honest z-score
    flat = pd.Series(5.0, index=idx)
    assert ms.weekly_z(flat, "bp") is None               # zero variance: no z-score, not infinity


def test_realized_vol_recovers_a_planted_vol():
    rng = np.random.default_rng(2)
    idx = _bdays(5000)
    px = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.20 / np.sqrt(252), len(idx)))), index=idx)
    rv = ms.realized_vol(px).dropna()
    assert rv.mean() == pytest.approx(20.0, rel=0.03)


def test_vol_block_premium_and_term():
    rng = np.random.default_rng(3)
    idx = _bdays(3000)
    px = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.18 / np.sqrt(252), len(idx)))), index=idx)
    fred = pd.DataFrame({"SP500": px, "VIXCLS": 22.0, "NASDAQ100": px * 2, "VXNCLS": 26.0, "VXVCLS": 21.0}, index=idx)
    v = ms.vol_block(fred)
    spx = v["latest"]["spx"]
    assert spx["vrp"] == pytest.approx(spx["implied"] - spx["realized"])
    assert spx["earned_mean5y"] == pytest.approx(22.0 - 18.0, abs=1.5)   # implied 22 against a true 18
    assert v["latest"]["term"]["ratio"] == pytest.approx(22 / 21)
    assert v["latest"]["term"]["days_inverted_1y"] > 200                 # ratio above 1 every day
    assert set(v["history"]) >= {"spx", "ndx", "term"}


def test_liquidity_block_units_and_alignment():
    days = pd.date_range("2025-01-01", "2026-10-16", freq="D")
    wed = days[days.dayofweek == 2]
    fred = pd.DataFrame(index=days)
    fred.loc[wed, "WALCL"] = 6_755_639.0                  # millions
    fred.loc[wed, "WTREGEN"] = 883_373.0                  # millions
    fred.loc[wed, "WRESBAL"] = 3_022.14                   # billions
    fred["RRPONTSYD"] = 0.33                              # billions
    fred["SOFR"], fred["IORB"] = 3.88, 3.90
    L = ms.liquidity_block(fred)["latest"]
    assert L["net"]["value"] == pytest.approx(6.755639 - 0.883373 - 0.00033)
    assert L["net"]["rrp"] == pytest.approx(0.00033)
    assert L["reserves"]["value"] == pytest.approx(3.02214)
    assert L["funding"]["gap_bp"] == pytest.approx(-2.0)
    assert L["funding"]["days_above_1y"] == 0
    assert set(ms.LIQ_IDS) <= set(ms.ids())


def test_inflation_state_survives_a_missing_month_and_reports_its_pace():
    idx = pd.date_range("2018-01-01", "2026-09-01", freq="MS")
    cpi = pd.Series(250 * 1.0025 ** np.arange(len(idx)), index=idx)       # 3.04% a year, every month
    fred = pd.DataFrame({"CPIAUCSL": cpi.drop(pd.Timestamp("2025-10-01"))})
    inf = ms.macro_state_block(fred)["inflation"]
    assert inf["yoy"] == pytest.approx(1.0025 ** 12 - 1, rel=1e-9)
    assert inf["avg36"] == pytest.approx(1.0025 ** 12 - 1, rel=1e-9)
    assert inf["above_line"] and inf["months_to_line_at_2pct"] == 11          # 36a - k(a - b) < 3 ln(1.0275) first at k = 11
    assert inf["yoy_v3"] == pytest.approx(0, abs=1e-12) and inf["yoy_v1"] == pytest.approx(0, abs=1e-12)
    ramp = pd.Series(250 * np.exp(np.cumsum(np.linspace(0.001, 0.004, len(idx)))), index=idx)  # inflation speeding up
    inf2 = ms.macro_state_block(pd.DataFrame({"CPIAUCSL": ramp}))["inflation"]
    assert inf2["yoy_v3"] > 0 and inf2["avg36_v3"] > 0
