"""Databento: split/dividend-adjusted daily closes for US equities and ETFs, and roll-adjusted
CME Treasury futures returns.

Setup: `pip install databento`, then put the key in the DATABENTO_API_KEY environment variable (never commit the key).
Historical data is pay-as-you-go per GB; run `estimate_cost` before large pulls.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .store import Cache

MIC_PRIORITY = ["XNGS", "XNYS", "ARCX", "XNCM", "XNMS", "BATS", "XASE"]
PRICE_BASIS = ("Databento ohlcv-1d: one bar per UTC day from trades on the dataset's venue. The close is the last trade "
               "before midnight UTC (7 or 8 pm New York, after hours), not the exchange's official 4 pm close")


def session_filter(bars: pd.DataFrame, min_rel_volume: float = 0.10) -> tuple[pd.DataFrame, list[str]]:
    """Drop bars that are not a trading session (v0.42.2). Databento's daily bars are cut at midnight UTC and a bar exists
    only for symbols that traded, so the last hour of Friday's after-hours session (7 to 8 pm New York in winter) becomes
    a Saturday bar for the names that happened to trade in it, and the evening before a holiday becomes a holiday bar.
    Those dates then look like gaps in every name that did not trade. A date is kept when it is a weekday and its
    volume is not a sliver: the median across symbols of volume over the symbol's own trailing median is at least
    `min_rel_volume` (a half day runs near 0.5; an after-hours sliver far below 0.01)."""
    if bars.empty:
        return bars, []
    d = pd.to_datetime(bars["date"])
    dates = pd.Index(sorted(d.unique()))
    drop = set(dates[dates.dayofweek >= 5])
    if "volume" in bars.columns and bars["volume"].notna().any() and float(bars["volume"].max()) > 0:
        vol = bars.assign(date=d).pivot_table(index="date", columns="symbol", values="volume", aggfunc="sum").sort_index()
        wk = vol.loc[vol.index.dayofweek < 5]
        med = wk.rolling(41, center=True, min_periods=5).median()
        rel = (wk / med).median(axis=1, skipna=True)
        drop |= set(rel.index[rel < min_rel_volume])
    if not drop:
        return bars, []
    keep = ~d.isin(list(drop))
    return bars.loc[keep].copy(), [t.strftime("%Y-%m-%d") for t in sorted(drop)]


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
        self.dataset_used = ds
        if self.cache is not None and (hit := self.cache.get(key)) is not None:
            return hit
        self.dataset_used = ds
        store = self.hist.timeseries.get_range(dataset=ds, schema="ohlcv-1d", symbols=list(symbols),
                                               start=start, end=end, stype_in="raw_symbol")
        df = store.to_df().reset_index()
        df["date"] = _naive_date(df["ts_event"])
        out = df[["date", "symbol", "open", "high", "low", "close", "volume"]].copy()
        if self.cache is not None:
            self.cache.put(key, out)
        return out

    def daily_bars(self, symbols: list[str], start: str, end: str | None = None) -> pd.DataFrame:
        """The raw bars made fit to use (v0.42.2); what was done is in self.cleaning.
          1. Ticker identity: rows dated before the ticker became this company are another security's and are dropped
             (corporate_actions.TICKER_SINCE); the company's earlier ticker is pulled and joined on (FORMER_TICKER).
          2. Sessions: weekend and sliver-volume dates, which the UTC day boundary creates, are dropped (session_filter)."""
        from .corporate_actions import FORMER_TICKER, TICKER_SINCE
        bars = self.raw_daily_bars(symbols, start, end).copy()
        bars["date"] = pd.to_datetime(bars["date"])
        info: dict = {"dataset": getattr(self, "dataset_used", None), "price_basis": PRICE_BASIS, "ticker_since": {}, "former_ticker": {}}
        for sym, since in TICKER_SINCE.items():
            if sym not in symbols:
                continue
            other = (bars["symbol"] == sym) & (bars["date"] < pd.Timestamp(since))
            info["ticker_since"][sym] = {"since": since, "rows_dropped": int(other.sum()),
                                         "dropped_from": bars.loc[other, "date"].min().strftime("%Y-%m-%d") if other.any() else None}
            bars = bars.loc[~other]
        for sym, (old, until) in FORMER_TICKER.items():
            if sym not in symbols or pd.Timestamp(start) >= pd.Timestamp(until):
                continue
            try:
                cost = self.estimate_cost([old], start, until) if hasattr(self, "hist") else 0.0
                if cost > 1.0:
                    raise RuntimeError(f"estimate ${cost:.2f} is above the $1 allowed for a former ticker")
                prev = self.raw_daily_bars([old], start, until)
                prev = prev.loc[(prev["symbol"] == old) & (pd.to_datetime(prev["date"]) < pd.Timestamp(until))].copy()
                if prev.empty:
                    raise RuntimeError(f"no {old} bars before {until}")
                prev["date"] = pd.to_datetime(prev["date"])
                prev["symbol"] = sym
                bars = pd.concat([prev, bars], ignore_index=True)
                info["former_ticker"][sym] = {"from": old, "until": until, "rows": int(len(prev)), "first": prev["date"].min().strftime("%Y-%m-%d")}
            except Exception as exc:          # the name then starts at its own ticker's first day, and the report says so
                info["former_ticker"][sym] = {"from": old, "until": until, "rows": 0, "error": f"{type(exc).__name__}: {exc}"[:200]}
        bars, dropped = session_filter(bars)
        info["non_session_dates_dropped"] = {"count": len(dropped), "weekend": int(sum(pd.Timestamp(x).dayofweek >= 5 for x in dropped)),
                                             "first": dropped[:3], "last": dropped[-3:]}
        self.cleaning = info
        return bars.sort_values(["date", "symbol"]).reset_index(drop=True)

    def diagnostics(self, symbols: list[str], start: str) -> dict:
        """Free metadata reads that say what a better price basis would take: how far back the consolidated daily summary
        goes, and what hourly bars (to rebuild a regular-session close) would cost. Never raises."""
        out: dict = {}
        try:
            rng = self.hist.metadata.get_dataset_range(dataset="EQUS.SUMMARY")
            out["equs_summary"] = {"start": str(_range_bound(rng, "start", "ohlcv-1d").date()), "end": str(_range_bound(rng, "end", "ohlcv-1d").date())}
        except Exception as exc:
            out["equs_summary"] = {"error": f"{type(exc).__name__}: {exc}"[:160]}
        try:
            ds = getattr(self, "dataset_used", None) or self.equities_dataset_for(start)
            out["ohlcv_1h_cost_usd"] = round(self.estimate_cost(symbols, start, None, schema="ohlcv-1h", dataset=ds), 4)
            out["ohlcv_1d_cost_usd"] = round(self.estimate_cost(symbols, start, None, schema="ohlcv-1d", dataset=ds), 4)
        except Exception as exc:
            out["cost_error"] = f"{type(exc).__name__}: {exc}"[:160]
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
                        allow_unadjusted: bool = False, adjustments: str = "auto") -> pd.DataFrame:
        """adjustments: "databento" (paid reference factors, strict), "public" (the free split table in
        corporate_actions.py), or "auto" (Databento's factors when the account has them, else the public table).
        self.adjustments_used records which one applied; bond-fund income is added later, where FRED is loaded."""
        from .corporate_actions import PENDING, split_factors
        if adjustments not in ("auto", "databento", "public"):
            raise ValueError(f"data.adjustments must be auto, databento or public, not {adjustments!r}")
        bars = self.daily_bars(symbols, start, end)
        closes = bars.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
        self.adjustments_used = "none"
        self.adjustments_error = None
        done = False
        if adjustments in ("auto", "databento"):
            try:
                closes = apply_factors(closes, self.adjustment_factors(symbols, start, end))
                self.adjustments_used, done = "databento", True
            except Exception as exc:
                self.adjustments_error = f"{type(exc).__name__}: {exc}"[:300]
                if adjustments == "databento" and not allow_unadjusted:
                    raise RuntimeError("Adjustment factors failed; unadjusted splits would corrupt returns. "
                                       "Set data.adjustments = \"public\" (or \"auto\") to use the free split table.") from exc
        if not done and adjustments in ("auto", "public"):
            closes = apply_factors(closes, split_factors(symbols))
            self.adjustments_used = "public"
        jumps = closes.pct_change(fill_method=None).abs() > 0.45
        if jumps.any().any():
            bad = {c: list(closes.index[jumps[c]].strftime("%Y-%m-%d")) for c in closes if jumps[c].any()}
            hint = "; ".join(f"{k}: {v}" for k, v in PENDING.items() if k in bad)
            raise ValueError(f"Daily moves above 45% look like unadjusted corporate actions: {bad}. "
                             f"Add the split to SPLITS in buildout/data/corporate_actions.py.{(' Pending: ' + hint) if hint else ''}")
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
