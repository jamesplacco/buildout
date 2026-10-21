"""10-K math on the real SEC facts the page snapshot is built from (tests/fixtures/sec_facts_2026q3.txt).

Every check here is a number that can be traced to a filing: if the engine and the page disagree with the
filings, these fail."""
from pathlib import Path

import pandas as pd
import pytest

from buildout import fundamentals as fu
from buildout.data.edgar_source import quarterly_flow

FIX = fu.parse_fixture(Path(__file__).parent / "fixtures" / "sec_facts_2026q3.txt")


@pytest.fixture(scope="module")
def m():
    return {t: fu.analyze_company(u) for t, u in FIX.items()}


def test_trailing_twelve_months_from_year_to_date_filings(m):
    # Microsoft's fiscal year ends in June: the 10-K total is the TTM
    assert m["MSFT"]["capex"] == pytest.approx(115.948)
    assert m["MSFT"]["ocf"] == pytest.approx(182.935)
    # Alphabet: full-year 2025 minus the first half of 2025 plus the first half of 2026
    assert m["GOOGL"]["capex"] == pytest.approx(91.447 - 39.643 + 80.598)
    # Amazon tags its own trailing twelve months: the de-cumulated quarters must sum to it exactly
    assert m["AMZN"]["capex"] == pytest.approx(173.028)
    assert m["AMZN"]["ocf"] == pytest.approx(161.403)
    # Oracle's fiscal year ends in May; its Q1 FY27 10-Q ends in August
    assert m["ORCL"]["quarter_end"] == "2026-08-31"
    assert m["ORCL"]["fcf"] == pytest.approx(-28.72, abs=0.005)        # sec-api.io reports ($28.72bn)


def test_quarters_are_recovered_from_cumulative_facts():
    q = quarterly_flow(FIX["GOOGL"]["PaymentsToAcquirePropertyPlantAndEquipment"]) / 1e9
    assert q[pd.Timestamp("2026-06-30")] == pytest.approx(80.598 - 35.674)    # Q2 = H1 - Q1
    assert q[pd.Timestamp("2025-12-31")] == pytest.approx(91.447 - 63.596)    # Q4 = FY - nine months
    crwv = quarterly_flow(FIX["CRWV"]["PaymentsToAcquirePropertyPlantAndEquipment"]) / 1e9
    assert crwv[pd.Timestamp("2026-06-30")] == pytest.approx(6.422)            # matches the Q2 2026 release


def test_ratios_and_paper_profits(m):
    assert m["MSFT"]["capex_to_ocf"] == pytest.approx(115.948 / 182.935)
    assert m["AMZN"]["capex_to_ocf"] > 1 > m["GOOGL"]["capex_to_ocf"]
    # Alphabet's non-operating income (mostly marks on SpaceX and Anthropic) about equals its operating income
    assert m["GOOGL"]["nonop"] == pytest.approx(151.641)
    assert m["GOOGL"]["nonop_share"] == pytest.approx(151.641 / (147.628 + 151.641))
    assert m["AMZN"]["nonop_share"] > 0.4 and m["MSFT"]["nonop_share"] < 0.1
    assert m["AMZN"]["debt_yoy"] == pytest.approx(128.894 / 50.718 - 1)
    assert m["ORCL"]["rpo_years"] == pytest.approx(664.0 / m["ORCL"]["revenue"])


def test_minsky_stages(m):
    assert m["MSFT"]["stage"] == m["GOOGL"]["stage"] == m["META"]["stage"] == "hedge"
    assert m["AMZN"]["stage"] == m["ORCL"]["stage"] == "speculative"
    # CoreWeave's latest quarter: an operating loss against $640M of interest
    crwv = dict(m["CRWV"], op_income_lq=-0.049, interest_lq=0.640)
    assert fu.minsky_stage(crwv) == "ponzi"
    assert fu.minsky_stage({"ocf": -1.0, "capex": 1.0}) == "ponzi"
    assert fu.minsky_stage({"ocf": None, "capex": 1.0}) is None


def test_supplements_fill_gaps_without_overwriting_filings():
    out = fu.analyze_company(FIX["ORCL"], {"debt": 125.34, "ocf": 1.0})
    assert out["debt"] == 125.34 and out["ocf"] == pytest.approx(46.94)     # filed OCF wins over a supplement
    forced = fu.analyze_company(FIX["ORCL"], {"ocf": 1.0, "_override": ("ocf",)})
    assert forced["ocf"] == 1.0


def test_depreciation_model_shapes():
    capex = {2023: 10.0}
    d = fu.depreciation_path(capex, 1.0, 5.0, 25.0, [2023, 2024, 2027, 2028, 2029])
    assert d[2023] == pytest.approx(10 * 0.5 / 5)          # half a year in the year it is placed in service
    assert d[2024] == pytest.approx(2.0) and d[2027] == pytest.approx(2.0)
    assert d[2028] == pytest.approx(1.0) and d[2029] == pytest.approx(0.0)
    assert sum(fu.depreciation_path(capex, 1.0, 5.0, 25.0, list(range(2023, 2030))).values()) == pytest.approx(10.0)
    # a shorter life front-loads the same cost; the fitted share reproduces the reported number exactly
    hist = {2021: 20.6, 2022: 23.9, 2023: 28.1, 2024: 44.5, 2025: 64.6, 2026: 115.9}
    s = fu.fit_server_share(hist, 2026, 34.3, 6.0)
    assert 0 < s < 1
    assert fu.depreciation_path(hist, s, 6.0, 25.0, [2026])[2026] == pytest.approx(34.3)
    sens = fu.life_sensitivity(hist, 2026, 34.3, 6.0, 4.0, [2026, 2027])
    assert sens["extra"][2026] > 0
