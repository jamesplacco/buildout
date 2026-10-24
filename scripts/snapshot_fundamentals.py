"""Build the Fundamentals desk's dated snapshot from the raw SEC facts with the engine's own code.

    python scripts/snapshot_fundamentals.py            # prints the JSON block pasted into site/src/research.js

tests/test_page.py re-runs this and checks that the page carries exactly these numbers, so the page can
never drift from the filings it cites. Supplements are figures the standard XBRL tags do not carry; each
names its source.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from buildout import fundamentals as fu  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "sec_facts_2026q3.txt"
NAMES = {"MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon", "META": "Meta", "ORCL": "Oracle", "NVDA": "Nvidia",
         "TSLA": "Tesla", "CRWV": "CoreWeave"}
CIK = {"MSFT": "789019", "GOOGL": "1652044", "AMZN": "1018724", "META": "1326801", "ORCL": "1341439", "NVDA": "1045810",
       "TSLA": "1318605", "CRWV": "1769628"}
SUPPLEMENTS = {
    "GOOGL": {"debt": 100.164, "debt_date": "2026-06-30", "_override": ("debt", "debt_date"),
              "debt_secondary": "total debt at Jun 30, 2026 from stockanalysis.com (the XBRL debt tag ends Dec 31, 2025: $49.1B); excludes leases"},
    "ORCL": {"debt": 125.34, "debt_date": "2026-08-31", "interest": 5.10, "da": 7.623, "op_income": 20.606,
             "leases_not_commenced": 288.0, "notes": "Debt, interest and leases not yet commenced from the Q1 FY27 10-Q (sec-api.io, Oct 8 2026); depreciation and operating income are fiscal 2026 (to May 31)."},
    "CRWV": {"debt": 35.068, "debt_date": "2026-06-30", "interest_lq": 0.640, "op_income_lq": -0.049, "rpo": 104.0, "rpo_date": "2026-06-30",
             "power_active_gw": 1.5, "power_contracted_gw": 3.7, "_override": ("debt",),
             "notes": "Debt (recourse plus non-recourse), latest-quarter interest and operating loss, backlog and power from the Q2 2026 results release."},
}
GUIDE = {  # next fiscal year's capex guidance, $B (midpoints), and the source
    "MSFT": (255.0, "about $175B in calendar 2026 and about $255B in fiscal 2027 (to June 2027)"),
    "GOOGL": (200.0, "$195B to $205B in 2026; 2027 to increase significantly"),
    "AMZN": (220.0, "about $220B in 2026"),
    "META": (137.5, "$130B to $145B in 2026, including finance-lease principal"),
    "ORCL": (92.5, "$90B to $95B in fiscal 2027 (to May 2027)"),
}
# annual cash capex ($B) from the 10-K facts (PaymentsToAcquirePropertyPlantAndEquipment or ProductiveAssets)
HISTORY = {
    "MSFT": {2017: 8.129, 2018: 11.632, 2019: 13.925, 2020: 15.441, 2021: 20.622, 2022: 23.886, 2023: 28.107, 2024: 44.477, 2025: 64.551, 2026: 115.948},
    "GOOGL": {2017: 13.184, 2018: 25.139, 2019: 23.548, 2020: 22.281, 2021: 24.640, 2022: 31.485, 2023: 32.251, 2024: 52.535, 2025: 91.447},
    "AMZN": {2017: 11.955, 2018: 13.427, 2019: 16.861, 2020: 40.140, 2021: 61.053, 2022: 63.645, 2023: 52.729, 2024: 82.999, 2025: 131.819},
    "META": {2017: 6.733, 2018: 13.915, 2019: 15.102, 2020: 15.163, 2021: 18.690, 2022: 31.186, 2023: 27.045, 2024: 37.256, 2025: 69.691},
    "ORCL": {2017: 2.021, 2018: 1.736, 2019: 1.660, 2020: 1.564, 2021: 2.135, 2022: 4.511, 2023: 8.695, 2024: 6.866, 2025: 21.215, 2026: 55.663},
}
# (fit year, reported depreciation that year in $B, stated server life in years)
DEPR = {"MSFT": (2026, 34.3, 6.0), "GOOGL": (2025, 21.136, 6.0), "AMZN": (2025, 65.756, 5.0), "META": (2025, 18.616, 5.5), "ORCL": (2026, 7.623, 5.0)}
SHORT_LIFE = 4.0
YEAR_AFTER_GROWTH = 0.15   # assumption: the year after guidance grows 15%


def build() -> dict:
    facts = fu.parse_fixture(FIXTURE)
    rows = []
    for t in NAMES:
        m = fu.analyze_company(facts[t], SUPPLEMENTS.get(t))
        keep = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items() if not k.startswith("_")}
        keep.update({"t": t, "name": NAMES[t], "cik": CIK[t]})
        if t in GUIDE:
            keep["guide"], keep["guide_text"] = GUIDE[t]
        if t in DEPR:
            fy, actual, life = DEPR[t]
            hist = dict(HISTORY[t])
            nxt = fy + 1 if fy == max(hist) else max(hist) + 1
            hist[nxt] = GUIDE[t][0]
            hist[nxt + 1] = round(GUIDE[t][0] * (1 + YEAR_AFTER_GROWTH), 3)
            sens = fu.life_sensitivity(hist, fy, actual, life, SHORT_LIFE, [fy, nxt, nxt + 1])
            keep["depr"] = {"fit_year": fy, "reported": actual, "stated_life": life, "short_life": SHORT_LIFE,
                            "hist": {str(y): v for y, v in sorted(HISTORY[t].items())}, "guide_year": nxt,
                            "server_share": round(sens["server_share"], 4),
                            "years": [fy, nxt, nxt + 1],
                            "stated": [round(sens["stated"][y], 3) for y in (fy, nxt, nxt + 1)],
                            "short": [round(sens["short"][y], 3) for y in (fy, nxt, nxt + 1)]}
        rows.append(keep)
    return {"as_of": "SEC filings through Sep 11, 2026", "rows": rows, "year_after_growth": YEAR_AFTER_GROWTH}


if __name__ == "__main__":
    print(json.dumps(build(), separators=(",", ":")))
