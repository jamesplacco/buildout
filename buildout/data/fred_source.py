"""FRED (St. Louis Fed): Treasury yields, breakevens, credit spreads, VIX, cash rates. Free, no key.

Useful series: DGS2, DGS10, DGS20, DGS30, DGS3MO, T10YIE (breakeven), DFII10 (real yield),
BAMLC0A0CM (IG spread), BAMLH0A0HYM2 (HY spread), VIXCLS, NASDAQ100, SP500, DFF, SOFR.
"""
from __future__ import annotations

import io

import pandas as pd

from . import http
from .store import Cache

import json
import os

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
# v0.33: FRED's official API, used when FRED_API_KEY is set (a free key from fredaccount.stlouisfed.org). The graph CSV
# endpoint above throttles some cloud machines, GitHub's among them; the API is the route FRED supports for programs.
FRED_API = "https://api.stlouisfed.org/fred/series/observations?series_id={sid}&api_key={key}&file_type=json"


def parse_fred_api(text: str, sid: str) -> pd.Series:
    obs = json.loads(text).get("observations", [])
    s = pd.Series(pd.to_numeric([o.get("value") for o in obs], errors="coerce"),
                  index=pd.to_datetime([o.get("date") for o in obs]), name=sid)
    return s.dropna()


def fetch(sid: str) -> pd.Series:
    """One series: through the API when a key is set (falling back to the CSV), else the CSV."""
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key:
        try:
            return parse_fred_api(http.get(FRED_API.format(sid=sid, key=key), timeout=20).decode(), sid)
        except Exception:                     # a bad key or an API outage: try the CSV before giving up
            pass
    return parse_fred_csv(http.get(FRED_CSV.format(sid=sid), timeout=20).decode(), sid)


def parse_fred_csv(text: str, sid: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    date_col, val_col = df.columns[0], df.columns[-1]
    s = pd.Series(pd.to_numeric(df[val_col], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df[date_col]), name=sid)
    return s.dropna()


# v0.42.1: when FRED refuses a series (its graph CSV throttles GitHub's machines, and two refusals in a row trip the
# breaker for the rest of the process), the same numbers come from a source that answers. FRED's DGS series are the
# Treasury's daily par yield curve, republished; NASDAQ100, SP500 and the volatility indexes are the indexes' own closes;
# CPIAUCSL falls back to CPI-U from Shiller's monthly file (not seasonally adjusted: changes over whole years match).
TREASURY_CSV = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
                "?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
TREASURY_COLS = {"DGS1MO": "1 Mo", "DGS3MO": "3 Mo", "DGS6MO": "6 Mo", "DGS1": "1 Yr", "DGS2": "2 Yr", "DGS3": "3 Yr",
                 "DGS5": "5 Yr", "DGS7": "7 Yr", "DGS10": "10 Yr", "DGS20": "20 Yr", "DGS30": "30 Yr"}
INDEX_TICKERS = {"NASDAQ100": "^NDX", "SP500": "^GSPC", "VIXCLS": "^VIX", "VXNCLS": "^VXN", "VXVCLS": "^VIX3M"}
_TREASURY: dict[int, pd.DataFrame] = {}          # one download per year per process, shared by every DGS series


def treasury_year(y: int) -> pd.DataFrame:
    if y not in _TREASURY:
        d = pd.read_csv(io.StringIO(http.get(TREASURY_CSV.format(y=y), timeout=45, retries=2).decode()))
        d["Date"] = pd.to_datetime(d["Date"])
        _TREASURY[y] = d.set_index("Date").sort_index()
    return _TREASURY[y]


def from_treasury(sid: str, start: str | None = None) -> pd.Series:
    col = TREASURY_COLS[sid]
    first = max(1990, pd.Timestamp(start).year if start else 1990)      # the Treasury's CSV begins in 1990
    frames = []
    for y in range(first, pd.Timestamp.now().year + 1):
        try:
            d = treasury_year(y)
        except Exception:
            if y == pd.Timestamp.now().year:          # the current year is the one that matters; older gaps are tolerated
                raise
            continue
        if col in d.columns:
            frames.append(pd.to_numeric(d[col], errors="coerce"))
    if not frames:
        raise RuntimeError(f"the Treasury curve has no {col!r} column")
    s = pd.concat(frames).sort_index()
    s = s[~s.index.duplicated(keep="last")].dropna()
    s.name = sid
    return s


def from_index(sid: str) -> pd.Series:
    from ..datahub import yahoo
    df = yahoo(INDEX_TICKERS[sid], years=45)
    s = df.set_index(pd.to_datetime(df["date"]))["close"].astype(float).dropna()
    s.name = sid
    return s


def from_shiller_cpi() -> pd.Series:
    from .. import labs
    s = labs.shiller(labs.download())["cpi"].dropna()
    s.name = "CPIAUCSL"
    return s


def fallback(sid: str, start: str | None = None) -> tuple[pd.Series, str] | None:
    """The same series from another source, with its label; None when there is no stand-in."""
    if sid in TREASURY_COLS:
        return from_treasury(sid, start), f"US Treasury par yield curve ({TREASURY_COLS[sid]})"
    if sid in INDEX_TICKERS:
        return from_index(sid), f"Yahoo {INDEX_TICKERS[sid]} close"
    if sid == "CPIAUCSL":
        return from_shiller_cpi(), "CPI-U, not seasonally adjusted (Shiller's monthly file)"
    return None


class FredSource:
    """Downloads each series on its own: one renamed or failing series is recorded in `failed`, not fatal. A series
    FRED refuses is taken from its stand-in when there is one, and recorded in `fallbacks` with the source used."""

    def __init__(self, cache: Cache | None = None, use_fallbacks: bool = True):
        self.cache = cache
        self.failed: dict[str, str] = {}
        self.fallbacks: dict[str, str] = {}
        self.use_fallbacks = use_fallbacks

    def series(self, ids: list[str], start: str | None = None, end: str | None = None) -> pd.DataFrame:
        cols = []
        for sid in ids:
            key = f"fred|{sid}"
            hit = self.cache.get(key) if self.cache is not None else None
            if hit is not None:
                cols.append(hit[sid])
                continue
            try:
                s = fetch(sid)
                if s.empty:
                    raise RuntimeError("no observations")
            except Exception as exc:          # network, throttling, a renamed series, or an HTML page instead of CSV
                fb = None
                if self.use_fallbacks:
                    try:
                        fb = fallback(sid, start)
                    except Exception as exc2:
                        self.failed[sid] = f"{str(exc)[:140]}; stand-in failed too: {str(exc2)[:100]}"
                        continue
                if fb is None or fb[0].empty:
                    self.failed[sid] = str(exc)[:200]
                    continue
                s, label = fb
                self.fallbacks[sid] = label
                cols.append(s)                # a stand-in is never cached under FRED's name
                continue
            if self.cache is not None:
                self.cache.put(key, s.to_frame())
            cols.append(s)
        if not cols:
            raise RuntimeError(f"no FRED series could be read: {self.failed}")
        out = pd.concat(cols, axis=1, sort=True).sort_index()
        return out.loc[start:end] if (start or end) else out
