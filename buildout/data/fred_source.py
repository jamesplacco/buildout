"""FRED (St. Louis Fed): Treasury yields, breakevens, credit spreads, VIX, cash rates. Free, no key.

Useful series: DGS2, DGS10, DGS20, DGS30, DGS3MO, T10YIE (breakeven), DFII10 (real yield),
BAMLC0A0CM (IG spread), BAMLH0A0HYM2 (HY spread), VIXCLS, NASDAQ100, SP500, DFF, SOFR.
"""
from __future__ import annotations

import io

import pandas as pd

from . import http
from .store import Cache

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


def parse_fred_csv(text: str, sid: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    date_col, val_col = df.columns[0], df.columns[-1]
    s = pd.Series(pd.to_numeric(df[val_col], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df[date_col]), name=sid)
    return s.dropna()


class FredSource:
    """Downloads each series on its own: one renamed or failing series is recorded in `failed`, not fatal."""

    def __init__(self, cache: Cache | None = None):
        self.cache = cache
        self.failed: dict[str, str] = {}

    def series(self, ids: list[str], start: str | None = None, end: str | None = None) -> pd.DataFrame:
        cols = []
        for sid in ids:
            key = f"fred|{sid}"
            hit = self.cache.get(key) if self.cache is not None else None
            if hit is not None:
                cols.append(hit[sid])
                continue
            try:
                s = parse_fred_csv(http.get(FRED_CSV.format(sid=sid)).decode(), sid)
            except Exception as exc:          # network, renamed series, or an HTML error page instead of CSV
                self.failed[sid] = str(exc)[:200]
                continue
            if s.empty:
                self.failed[sid] = "no observations"
                continue
            if self.cache is not None:
                self.cache.put(key, s.to_frame())
            cols.append(s)
        if not cols:
            raise RuntimeError(f"no FRED series could be read: {self.failed}")
        out = pd.concat(cols, axis=1).sort_index()
        return out.loc[start:end] if (start or end) else out
