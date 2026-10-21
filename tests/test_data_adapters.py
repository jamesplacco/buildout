"""Offline tests of the data adapters' transformation logic (no network, no API key)."""
import numpy as np
import pandas as pd

from buildout.data.databento_source import apply_factors, roll_adjusted_returns, select_factors
from buildout.data.edgar_source import fundamentals_table, quarterly_flow
from buildout.data.fred_source import parse_fred_csv
from buildout.data.kalshi_source import implied_probabilities


def test_split_factor_removes_jump():
    idx = pd.bdate_range("2024-06-03", periods=6)
    closes = pd.DataFrame({"NVDA": [1200.0, 1210, 1220, 122.0, 123, 124]}, index=idx)
    factors = pd.DataFrame({"symbol": ["NVDA"], "ex_date": [idx[3]], "factor": [0.1]})
    adj = apply_factors(closes, factors)
    assert adj["NVDA"].pct_change().abs().max() < 0.02


def test_select_factors_keeps_applied_primary_listing():
    f = pd.DataFrame({
        "ex_date": ["2025-02-20"] * 4, "symbol": ["MSFT"] * 4, "event_id": ["E1"] * 4,
        "status": ["A", "A", "R", "A"], "option": [1, 1, 1, 2],
        "exchange": ["USNASD", "USBATS", "USNASD", "USNASD"], "primary_exchange": ["USNASD"] * 4,
        "operating_mic": ["XNGS", "BATS", "XNGS", "XNGS"], "factor": [0.9975, 0.9975, 0.5, 0.1],
    })
    out = select_factors(f)
    assert len(out) == 1 and out["factor"].iloc[0] == 0.9975


def test_futures_roll_without_jump():
    d = pd.bdate_range("2025-03-17", periods=4)
    rows = [
        (d[0], "ZN.v.0", 1, 110.0), (d[0], "ZN.v.1", 2, 109.0),
        (d[1], "ZN.v.0", 1, 110.5), (d[1], "ZN.v.1", 2, 109.5),
        (d[2], "ZN.v.0", 2, 109.0), (d[2], "ZN.v.1", 3, 108.0),     # roll: contract 2 becomes front
        (d[3], "ZN.v.0", 2, 109.5), (d[3], "ZN.v.1", 3, 108.5),
    ]
    bars = pd.DataFrame(rows, columns=["date", "symbol", "instrument_id", "close"])
    r = roll_adjusted_returns(bars, "ZN")
    assert abs(r.iloc[2] - (109.0 / 109.5 - 1)) < 1e-12        # not 109.0 / 110.5
    assert abs(r.iloc[3] - (109.5 / 109.0 - 1)) < 1e-12


def _fact(start, end, val, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


def test_edgar_decumulates_ytd_and_takes_restatements():
    units = [
        _fact("2025-01-01", "2025-03-31", 10, "2025-04-25"),
        _fact("2025-01-01", "2025-06-30", 25, "2025-07-25"),
        _fact("2025-01-01", "2025-06-30", 26, "2025-10-25"),     # restated later
        _fact("2025-01-01", "2025-09-30", 46, "2025-10-25"),
        _fact("2025-01-01", "2025-12-31", 70, "2026-02-01", "10-K"),
    ]
    q = quarterly_flow(units)
    assert list(q.round(6)) == [10, 16, 20, 24]


def test_edgar_table_computes_fcf():
    facts = {"facts": {"us-gaap": {
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [_fact("2026-01-01", "2026-03-31", 40, "2026-04-30")]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [_fact("2026-01-01", "2026-03-31", 45, "2026-04-30")]}},
    }}}
    t = fundamentals_table(facts)
    assert t["fcf"].iloc[-1] == -5


def test_fred_parser_handles_missing_marker():
    s = parse_fred_csv("observation_date,DGS30\n2026-10-07,5.66\n2026-10-08,.\n2026-10-09,5.58\n", "DGS30")
    assert len(s) == 2 and s.iloc[-1] == 5.58


def test_kalshi_probabilities_normalize_within_event():
    m = pd.DataFrame({"event_ticker": ["E", "E", "E"], "yes_bid": [0.6, 0.3, 0.05],
                      "yes_ask": [0.62, 0.32, 0.07], "last_price": [np.nan] * 3})
    p = implied_probabilities(m)
    assert abs(p["prob"].sum() - 1) < 1e-12
