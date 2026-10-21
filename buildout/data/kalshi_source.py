"""Kalshi public market data: prediction-market probabilities as macro features (Fed path, CPI, recession).

Databento does not carry prediction markets. Kalshi's market-data endpoints are public; series tickers
(e.g. the Fed rate series) are configurable because the exchange renames and adds series.
"""
from __future__ import annotations

import urllib.parse

import pandas as pd

from . import http

BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _price(m: dict, field: str) -> float | None:
    if m.get(f"{field}_dollars") not in (None, ""):
        return float(m[f"{field}_dollars"])
    if m.get(field) is not None:
        return float(m[field]) / 100.0
    return None


def implied_probabilities(markets: pd.DataFrame) -> pd.DataFrame:
    """Mid-price probability per outcome, normalized within each event so brackets sum to 1."""
    df = markets.copy()
    df["mid"] = (df["yes_bid"] + df["yes_ask"]) / 2
    df["mid"] = df["mid"].fillna(df["last_price"])
    df["prob"] = df["mid"] / df.groupby("event_ticker")["mid"].transform("sum")
    return df.sort_values(["event_ticker", "prob"], ascending=[True, False])


class KalshiSource:
    def markets(self, series_ticker: str, status: str = "open") -> pd.DataFrame:
        rows, cursor = [], ""
        while True:
            q = {"series_ticker": series_ticker, "status": status, "limit": 1000}
            if cursor:
                q["cursor"] = cursor
            page = http.get_json(f"{BASE}/markets?{urllib.parse.urlencode(q)}")
            for m in page.get("markets", []):
                rows.append({"ticker": m.get("ticker"), "event_ticker": m.get("event_ticker"),
                             "title": m.get("title"), "subtitle": m.get("yes_sub_title") or m.get("subtitle"),
                             "yes_bid": _price(m, "yes_bid"), "yes_ask": _price(m, "yes_ask"),
                             "last_price": _price(m, "last_price"), "volume": m.get("volume"),
                             "close_time": m.get("close_time")})
            cursor = page.get("cursor") or ""
            if not cursor:
                break
        return pd.DataFrame(rows)
