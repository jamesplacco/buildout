"""Databento: split/dividend-adjusted daily closes for US equities and ETFs, and roll-adjusted
CME Treasury futures returns.

Setup: `pip install databento`, then `export DATABENTO_API_KEY=db-...` (never commit the key).
Historical data is pay-as-you-go per GB; run `estimate_cost` before large pulls.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .store import Cache

MIC_PRIORITY = ["XNGS", "XNYS", "ARCX", "XNCM", "XNMS", "BATS", "XASE"]


def _range_bound(rng: dict, key: str, schema: str | None = None) -> pd.Timestamp:
    """Read 'start' or 'end' from metadata.get_dataset_range, which may also carry per-schema ranges
    and, in older API versions, 'start_date'/'end_date' keys."""
    per_schema = rng.get("schema", {}) if isinstance(rng.get("schema"), dict) else {}
    src = per_schema.get(schema, rng) if schema else rng
    raw = src.get(key) or src.get(f"{key}_date") or rng.get(key) or rng.get(f"{key}_date")
    ts = pd.Timestamp(raw)
    return ts.tz_convert(None) if ts.tzinfo else ts


def _naive_date(ts: pd.Series) -> pd.Series:
    ts = pd.to_datetime(ts)
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert(None)
    return ts.dt.normalize()


def select_factors(f: pd.DataFrame) -> pd.DataFrame:
    """Keep applied, default-option factors for each symbol's primary listing.

    Databento returns one row per listing per event; applying several listings would double count.
    """
    f = f.reset_index() if "ex_date" not in f.columns else f.copy()
    f = f[(f["status"] == "A") & (f["option"] == 1)].copy()
    if f.empty:
        return f[["symbol", "ex_date", "factor"]]
    if {"exchange", "primary_exchange"} <= set(f.columns):
        primary = f[f["exchange"] == f["primary_exchange"]]
        f = primary if not primary.empty else f
    if "operating_mic" in f.columns:
        rank = {m: i for i, m in enumerate(MIC_PRIORITY)}
        f["_rank"] = f["operating_mic"].map(rank).fillna(len(rank))
        f = f.sort_values("_rank").drop(columns="_rank")
    keys = ["symbol", "ex_date"] + (["event_id"] if "event_id" in f.columns else [])
    f = f.drop_duplicates(subset=keys, keep="first")
    f["ex_date"] = pd.to_datetime(f["ex_date"]).dt.normalize()
    return f[["symbol", "ex_date", "factor"]].sort_values(["symbol", "ex_date"])


def apply_factors(closes: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Back-adjust: every bar strictly before an ex-date is multiplied by that event's factor.

    With dividend and split factors applied, close-to-close returns are total returns.
    """
    adj = closes.astype(float).copy()
    for sym, g in factors.groupby("symbol"):
        if sym not in adj.columns:
            continue
        mult = pd.Series(1.0, index=adj.index)
        for ex_date, fac in zip(g["ex_date"], g["factor"].astype(float)):
            mult[adj.index < ex_date] *= fac
        adj[sym] = adj[sym] * mult
    return adj


def roll_adjusted_returns(bars: pd.DataFrame, root: str) -> pd.Series:
    """Daily returns of the most-active contract without roll jumps.

    `bars` holds ROOT.v.0 and ROOT.v.1 rows (date, symbol, instrument_id, close). On a roll day the new
    front contract was yesterday's second contract, so its previous close is available.
    """
    b = bars[bars["symbol"].astype(str).str.startswith(f"{root}.v.")]
    closes = b.pivot_table(index="date", columns="instrument_id", values="close", aggfunc="last").sort_index()
    front = b[b["symbol"] == f"{root}.v.0"].set_index("date")["instrument_id"].sort_index()
    front = front[~front.index.duplicated(keep="last")]
    dates = closes.index
    out = pd.Series(np.nan, index=dates, name=root)
    for i in range(1, len(dates)):
        d, prev = dates[i], dates[i - 1]
        iid = front.get(d)
        if iid is None or iid not in closes.columns:
            continue
        p0, p1 = closes.at[prev, iid], closes.at[d, iid]
        if pd.notna(p0) and pd.notna(p1) and p0 > 0:
            out.iloc[i] = p1 / p0 - 1.0
    return out


class DatabentoSource:
    def __init__(self, api_key: str | None = None, equities_dataset: str = "auto",
                 futures_dataset: str = "GLBX.MDP3", cache: Cache | None = None):
        try:
            import databento as db
        except ImportError as exc:  # pragma: no cover
            raise ImportError("Databento source needs `pip install databento`") from exc
        key = api_key or os.environ.get("DATABENTO_API_KEY")
        if not key:
            raise RuntimeError("Set DATABENTO_API_KEY in your environment (never commit it).")
        self.hist = db.Historical(key)
        self.ref = db.Reference(key)
        self.equities_dataset = equities_dataset
        self.futures_dataset = futures_dataset
        self.cache = cache

    # ---- dataset choice and cost control -------------------------------------------------------
    def equities_dataset_for(self, start: str) -> str:
        if self.equities_dataset != "auto":
            return self.equities_dataset
        try:
            first = _range_bound(self.hist.metadata.get_dataset_range(dataset="EQUS.SUMMARY"), "start", "ohlcv-1d")
            if first <= pd.Timestamp(start):
                return "EQUS.SUMMARY"   # consolidated official daily summary across venues
        except Exception:
            pass
        return "XNAS.ITCH"              # Nasdaq venue, history from 2018-05-01

    def resolve_end(self, dataset: str, end: str | None, schema: str = "ohlcv-1d") -> str:
        """Databento's get_range treats a missing end as start + one bar, so always pass one explicitly:
        the dataset's available end, capped at today's UTC midnight so only completed sessions are used."""
        if end is not None:
            return str(end)
        today = pd.Timestamp.now(tz="UTC").tz_convert(None).normalize()
        try:
            avail = _range_bound(self.hist.metadata.get_dataset_range(dataset=dataset), "end", schema)
            return min(avail, today).strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            return today.strftime("%Y-%m-%d")

    def estimate_cost(self, symbols: list[str], start: str, end: str | None = None,
                      schema: str = "ohlcv-1d", dataset: str | None = None) -> float:
        ds = dataset or self.equities_dataset_for(start)
        return float(self.hist.metadata.get_cost(dataset=ds, symbols=list(symbols), schema=schema,
                                                 start=start, end=self.resolve_end(ds, end, schema)))

    # ---- equities --------------------------------------------------------------------------------
    def raw_daily_bars(self, symbols: list[str], start: str, end: str | None = None) -> pd.DataFrame:
        ds = self.equities_dataset_for(start)
        end = self.resolve_end(ds, end)
        key = f"bars|{ds}|{','.join(sorted(symbols))}|{start}|{end}"
        if self.cache is not None and (hit := self.cache.get(key)) is not None:
            return hit
        store = self.hist.timeseries.get_range(dataset=ds, schema="ohlcv-1d", symbols=list(symbols),
                                               start=start, end=end, stype_in="raw_symbol")
        df = store.to_df().reset_index()
        df["date"] = _naive_date(df["ts_event"])
        out = df[["date", "symbol", "open", "high", "low", "close", "volume"]].copy()
        if self.cache is not None:
            self.cache.put(key, out)
        return out

    def adjustment_factors(self, symbols: list[str], start: str, end: str | None = None) -> pd.DataFrame:
        key = f"factors|{','.join(sorted(symbols))}|{start}|{end}"
        if self.cache is not None and (hit := self.cache.get(key)) is not None:
            return hit
        raw = self.ref.adjustment_factors.get_range(symbols=list(symbols), start=start, end=end, countries=["US"])
        out = select_factors(raw)
        if self.cache is not None:
            self.cache.put(key, out)
        return out

    def adjusted_closes(self, symbols: list[str], start: str, end: str | None = None,
                        allow_unadjusted: bool = False) -> pd.DataFrame:
        bars = self.raw_daily_bars(symbols, start, end)
        closes = bars.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
        try:
            closes = apply_factors(closes, self.adjustment_factors(symbols, start, end))
        except Exception as exc:
            if not allow_unadjusted:
                raise RuntimeError("Adjustment factors failed; unadjusted splits would corrupt returns. "
                                   "Pass allow_unadjusted=True only for a quick look.") from exc
        jumps = closes.pct_change(fill_method=None).abs() > 0.45
        if jumps.any().any():
            bad = {c: list(closes.index[jumps[c]].strftime("%Y-%m-%d")) for c in closes if jumps[c].any()}
            raise ValueError(f"Daily moves above 45% look like unadjusted corporate actions: {bad}")
        return closes

    # ---- Treasury futures ------------------------------------------------------------------------
    def futures_daily(self, roots: list[str], start: str, end: str | None = None) -> pd.DataFrame:
        symbols = [f"{r}.v.{k}" for r in roots for k in (0, 1)]
        store = self.hist.timeseries.get_range(dataset=self.futures_dataset, schema="ohlcv-1d", symbols=symbols,
                                               stype_in="continuous", start=start,
                                               end=self.resolve_end(self.futures_dataset, end))
        df = store.to_df().reset_index()
        df["date"] = _naive_date(df["ts_event"])
        return df[["date", "symbol", "instrument_id", "close", "volume"]]

    def futures_returns(self, roots: list[str], start: str, end: str | None = None) -> pd.DataFrame:
        bars = self.futures_daily(roots, start, end)
        return pd.concat([roll_adjusted_returns(bars, r) for r in roots], axis=1)
