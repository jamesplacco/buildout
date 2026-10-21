"""SEC EDGAR XBRL: quarterly operating cash flow, capex, free cash flow and debt straight from filings.

Free. The SEC requires a User-Agent with a real name and email. Cash-flow facts are reported
year-to-date in 10-Qs, so quarters are recovered by differencing within each fiscal year.
"""
from __future__ import annotations

import pandas as pd

from . import http

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

FLOW_CONCEPTS = {
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsForProceedsFromProductiveAssets"],
}
INSTANT_CONCEPTS = {
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
}
FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}


def _facts(units: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(units)
    if df.empty:
        return df
    df = df[df["form"].isin(FORMS)].copy()
    df["end"] = pd.to_datetime(df["end"])
    if "start" in df.columns:
        df["start"] = pd.to_datetime(df["start"])
    df["filed"] = pd.to_datetime(df["filed"])
    return df


def quarterly_flow(units: list[dict]) -> pd.Series:
    """Turn duration facts (3, 6, 9, 12 month) into discrete quarterly values indexed by quarter end."""
    df = _facts(units)
    if df.empty or "start" not in df.columns:
        return pd.Series(dtype=float)
    df = df.dropna(subset=["start"]).sort_values("filed").drop_duplicates(["start", "end"], keep="last")
    df["days"] = (df["end"] - df["start"]).dt.days
    out: dict[pd.Timestamp, float] = {}
    for _, row in df[(df["days"] >= 80) & (df["days"] <= 100)].iterrows():
        out[row["end"]] = float(row["val"])
    for _, g in df.groupby("start"):
        g = g.sort_values("end")
        ends, vals = list(g["end"]), list(g["val"].astype(float))
        for i in range(1, len(g)):
            gap = (ends[i] - ends[i - 1]).days
            if 80 <= gap <= 100 and ends[i] not in out:
                out[ends[i]] = vals[i] - vals[i - 1]
    return pd.Series(out, dtype=float).sort_index()


def instant_values(units: list[dict]) -> pd.Series:
    df = _facts(units)
    if df.empty:
        return pd.Series(dtype=float)
    if "start" in df.columns:
        df = df[df["start"].isna()]
    df = df.sort_values("filed").drop_duplicates("end", keep="last")
    return pd.Series(df["val"].astype(float).to_numpy(), index=df["end"]).sort_index()


def _first_available(facts: dict, names: list[str], fn) -> pd.Series:
    gaap = facts.get("facts", {}).get("us-gaap", {})
    out = pd.Series(dtype=float)
    for name in names:
        units = gaap.get(name, {}).get("units", {}).get("USD")
        if units:
            s = fn(units)
            out = s if out.empty else out.combine_first(s)
    return out


def fundamentals_table(facts: dict) -> pd.DataFrame:
    cols = {k: _first_available(facts, v, quarterly_flow) for k, v in FLOW_CONCEPTS.items()}
    cols |= {k: _first_available(facts, v, instant_values) for k, v in INSTANT_CONCEPTS.items()}
    df = pd.DataFrame(cols).sort_index()
    df["fcf"] = df["ocf"] - df["capex"]
    df["capex_to_ocf"] = df["capex"] / df["ocf"]
    return df


class EdgarSource:
    def __init__(self, user_agent: str):
        if "@" not in user_agent or "your@email" in user_agent:
            raise ValueError("SEC requires a real 'Name email' User-Agent; set data.sec_user_agent.")
        self.ua = user_agent
        self._map: dict[str, int] | None = None

    def cik(self, ticker: str) -> int:
        if self._map is None:
            raw = http.get_json(TICKERS_URL, self.ua)
            self._map = {v["ticker"].upper(): int(v["cik_str"]) for v in raw.values()}
        return self._map[ticker.upper()]

    def facts(self, ticker: str) -> dict:
        return http.get_json(FACTS_URL.format(cik=self.cik(ticker)), self.ua)

    def fundamentals(self, ticker: str, facts: dict | None = None) -> pd.DataFrame:
        return fundamentals_table(facts if facts is not None else self.facts(ticker))
