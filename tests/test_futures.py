"""The futures engine (buildout.futures): pysystemtrade's layout is read right, a roll is never a jump, carry has the
right sign, every signal is known at the month's last close and trades from it, positions are used only after their
release, the portfolios trade what they say, and a planted carry edge is found on synthetic data."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from buildout import futures as Fu

HEAD = "DATETIME,CARRY,CARRY_CONTRACT,PRICE,PRICE_CONTRACT,FORWARD,FORWARD_CONTRACT\n"


def test_pysystemtrade_layout_is_one_row_a_day_with_contract_months():
    text = HEAD + "\n".join([
        "2024-03-01 15:00:00,101.0,20240600,100.0,20240300,101.0,20240600",
        "2024-03-01 23:00:00,,20240600,100.5,20240300,,20240600",            # a later row of the same day without carry
        "2024-03-04 23:00:00,102.0,20240600,101.0,20240300,102.0,20240600"])
    f = Fu.parse_carver(text)
    assert list(f.index) == [pd.Timestamp("2024-03-01"), pd.Timestamp("2024-03-04")]
    assert f.loc["2024-03-01", "price"] == 100.5 and f.loc["2024-03-01", "carry"] == 101.0 and f.loc["2024-03-01", "m_price"] == 202403


def _frame(prices, held, nxt_prices, nxt):
    idx = pd.bdate_range("2024-01-01", periods=len(prices))
    return pd.DataFrame({"price": prices, "m_price": held, "carry": nxt_prices, "m_carry": nxt, "forward": nxt_prices, "m_forward": nxt}, index=idx, dtype=float)


def test_a_roll_is_not_a_jump():
    # day 3 rolls from March to June; June closed at 90 the day before, so the roll-day return is 91 / 90 - 1
    f = _frame([100, 101, 91, 92], [202403, 202403, 202406, 202406], [89, 90, 80, 81], [202406, 202406, 202409, 202409])
    r = Fu.front_returns(f)
    assert abs(r.iloc[2] - (91 / 90 - 1)) < 1e-12 and abs(r.iloc[1] - 0.01) < 1e-12


def test_carry_is_positive_in_backwardation_whichever_contract_is_nearer():
    f = _frame([100.0], [202403], [97.0], [202406])                     # the further contract is cheaper: backwardation
    assert abs(Fu.carry_series(f).iloc[0] - np.log(100 / 97) * 4) < 1e-12
    g = _frame([100.0], [202406], [103.0], [202403])                     # the carry contract is the nearer one (as for STIR)
    assert abs(Fu.carry_series(g).iloc[0] - np.log(103 / 100) * 4) < 1e-12


def test_signals_are_known_at_the_month_end_and_returns_come_after():
    frames, _ = Fu.synthetic_frames(edge=0.0, seed=1, start="2015-01-01", end="2018-12-31", markets=["ES", "ZN", "GC"])
    P1 = Fu.month_panel(frames)
    g = frames["ES"].copy()
    g.loc["2017-07-01":, "price"] *= 1.5                                  # change everything after June 2017
    g.loc["2017-07-01":, ["carry", "forward"]] *= 1.5
    P2 = Fu.month_panel({"ES": g, "ZN": frames["ZN"], "GC": frames["GC"]})
    a = P1[(P1.market == "ES") & (P1.month == pd.Timestamp("2017-06-30"))].iloc[0]
    b = P2[(P2.market == "ES") & (P2.month == pd.Timestamp("2017-06-30"))].iloc[0]
    for s in ("carry", "trend_1", "trend_3", "trend_12", "basis_mom", "vol"):
        assert a[s] == pytest.approx(b[s], nan_ok=True)
    nxt = P1[(P1.market == "ES") & (P1.month == pd.Timestamp("2017-07-31"))].iloc[0]
    assert a["next_ret"] == pytest.approx(nxt["ret"])


def test_a_month_in_progress_has_no_return():
    frames, _ = Fu.synthetic_frames(edge=0.0, seed=1, start="2015-01-01", end="2018-06-12", markets=["ES"])
    P = Fu.month_panel(frames).set_index("month")
    assert np.isnan(P.loc[pd.Timestamp("2018-06-30"), "ret"]) and np.isnan(P.loc[pd.Timestamp("2018-05-31"), "next_ret"])
    frames, _ = Fu.synthetic_frames(edge=0.0, seed=1, start="2015-01-01", end="2024-03-28", markets=["ES"])     # Good Friday 2024: March is complete
    assert np.isfinite(Fu.month_panel(frames).set_index("month").loc[pd.Timestamp("2024-03-31"), "ret"])


def test_positions_are_used_only_after_their_release():
    cot = pd.DataFrame({"market": ["ES", "ES"], "report_date": pd.to_datetime(["2024-05-21", "2024-05-28"]), "comm_long": [100.0, 100.0], "comm_short": [300.0, 100.0]})
    keys = pd.DataFrame({"market": ["ES"], "month": [pd.Timestamp("2024-05-31")], "cutoff": [pd.Timestamp("2024-05-31")]})
    v = Fu.cot_asof(cot, keys)["hedging_pressure"].iloc[0]
    assert v == pytest.approx(0.5)                                         # the May 28 report is out on Friday May 31, usable from June 3


def test_portfolios_trade_what_they_say():
    G = pd.DataFrame({"s": np.arange(12.0), "vol": [0.1] * 6 + [0.2] * 6}, index=[f"M{i}" for i in range(12)])
    w = Fu.weights(G, "s", "xs")
    assert w[w > 0].index.tolist() == [f"M{i}" for i in range(6, 12)] and abs(w.sum()) < 0.5 * w.abs().sum()
    t = Fu.weights(G.assign(s=G["s"] - 5.5), "s", "ts")
    assert (np.sign(t) == np.sign(G["s"] - 5.5)).all()
    months = pd.date_range("2000-01-31", periods=3, freq="ME")
    P = pd.DataFrame([{"month": m, "market": k, "s": float(i), "vol": 0.1, "next_ret": 0.0, "next_rolls": 1.0} for m in months for i, k in enumerate(["ES", "ZN", "GC", "CL", "ZC"])])
    pf = Fu.portfolio(P, "s", "ts")
    assert (pf["net"] < 0).all() and (pf["gross"] == 0).all()             # flat prices: costs, rolls included, are all that is left


@pytest.fixture(scope="module")
def synthetic():
    frames, cot = Fu.synthetic_frames()
    return Fu.build(frames, cot, n_fake=6)


def test_a_planted_carry_edge_is_found(synthetic):
    T = {(t["signal"], t["design"]): t for t in synthetic["tests"]}
    c = T[("carry", "xs")]
    assert c["pass_bh"] and c["sharpe_net"] > 0.5 and c["within_class"]["sharpe_net"] > 0
    others = [t for k, t in T.items() if k[0] != "carry"]
    assert sum(t["pass_bh"] for t in others) <= 1
    assert synthetic["n_hypotheses"] == len(synthetic["tests"]) == 12 and synthetic["findings"]
    assert {b["market"] for b in synthetic["book"]["today"]} >= {"ZN", "ZB", "ES"} and synthetic["book"]["selloffs"]


def test_house_style():
    src = open(Fu.__file__).read().lower()
    for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
        assert b not in src


def test_a_missing_month_is_a_gap_not_a_shift():
    frames, _ = Fu.synthetic_frames(edge=0.0, seed=2, start="2015-01-01", end="2017-12-31", markets=["ES"])
    f = frames["ES"]
    f = f[(f.index < "2016-05-01") | (f.index >= "2016-06-01")]          # no data at all in May 2016
    P = Fu.month_panel({"ES": f}).set_index("month")
    assert np.isnan(P.loc[pd.Timestamp("2016-04-30"), "next_ret"])         # April's next month is May, which is missing
    assert P.loc[pd.Timestamp("2016-06-30"), "next_ret"] == pytest.approx(P.loc[pd.Timestamp("2016-07-31"), "ret"])


def test_a_stale_deferred_price_gives_no_carry():
    prices = [100, 101, 102, 103, 104, 105, 106]
    f = _frame(prices, [202403] * 7, [99, 98, 98, 98, 98, 98, 97], [202406] * 7)    # the June quote frozen for five rows
    c = Fu.carry_series(f)
    assert np.isfinite(c.iloc[1]) and np.isnan(c.iloc[5]) and np.isfinite(c.iloc[6])


def test_basis_momentum_uses_the_second_nearby_only():
    f = _frame([100, 101, 102], [202403] * 3, [99, 100, 101], [202406] * 3)
    assert Fu.second_returns(f).notna().sum() == 2
    g = _frame([100, 101, 102], [202312] * 3, [99, 100, 101], [202412] * 3)      # a year out, as for crude in pysystemtrade
    assert Fu.second_returns(g).notna().sum() == 0


def test_no_positioning_in_shutdown_months():
    cot = pd.DataFrame({"market": ["ES"] * 6, "report_date": pd.date_range("2025-09-02", periods=6, freq="7D"), "comm_long": [100.0] * 6, "comm_short": [300.0] * 6})
    keys = pd.DataFrame({"market": ["ES", "ES"], "month": pd.to_datetime(["2025-09-30", "2025-10-31"]), "cutoff": pd.to_datetime(["2025-09-30", "2025-10-31"])})
    v = Fu.cot_asof(cot, keys).set_index("month")["hedging_pressure"]
    assert v.loc[pd.Timestamp("2025-09-30")] == pytest.approx(0.5) and np.isnan(v.loc[pd.Timestamp("2025-10-31")])


def test_a_run_from_2010_can_still_be_judged_on_both_halves():
    frames, _ = Fu.synthetic_frames(edge=1.0, seed=5, start="2010-06-07", end="2026-09-30")
    o = Fu.build(frames, None, n_fake=0)
    c = {t["design"]: t for t in o["tests"] if t["signal"] == "carry"}["xs"]
    assert c["halves"]["first"].get("sharpe") is not None and c["halves"]["split"] > "2015" and c["pass_bh"]
    assert c["verdict"] in ("supported", "faded")                          # never capped at one era by a fixed 2007 split
