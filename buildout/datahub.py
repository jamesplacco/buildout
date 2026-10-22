"""The data hub: every market-data source the engine can read, behind one interface, with a connection check.

  databento   paid, keyed (DATABENTO_API_KEY): split-adjusted daily OHLCV for US equities and ETFs, CME futures
  yahoo       free, unofficial chart API: daily OHLCV with split and dividend adjustment; the default fallback
  stooq       free CSV: daily OHLCV
  sec         free, needs a contact User-Agent (SEC_USER_AGENT): XBRL company facts for every filer
  treasury    free CSV: the daily par yield curve
  cftc        free Socrata API: traders in financial futures (positioning by dealer, asset manager, leveraged funds)
  fred        free CSV (FRED_API_KEY optional): macro and rates series
  github      free mirrors of public datasets (Shiller, CPI, oil, gas, gold, VIX)

`ohlcv(ticker)` tries the sources in priority order and records which one answered; `check()` tests credentials
and reachability for every source and returns a table the page shows; `market(out)` runs the technical and
fundamental analysis for the universe and writes derived results only (readings, signals, ratios), never raw prices.
Every request is independent: a dead source is recorded and skipped, never fatal.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import time
from pathlib import Path

import pandas as pd

from .data import http

UA = "buildout/0.16 research engine"
SOURCES = {
    "databento": {"needs": "DATABENTO_API_KEY", "probe": "https://hist.databento.com", "cost": "paid", "what": "Split-adjusted daily OHLCV, futures"},
    "yahoo": {"needs": None, "probe": "https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=5d&interval=1d", "cost": "free", "what": "Daily OHLCV, adjusted"},
    "stooq": {"needs": None, "probe": "https://stooq.com/q/d/l/?s=spy.us&i=d", "cost": "free", "what": "Daily OHLCV"},
    "sec": {"needs": "SEC_USER_AGENT", "probe": "https://data.sec.gov/api/xbrl/companyconcept/CIK0000789019/us-gaap/Revenues.json", "cost": "free", "what": "XBRL company facts"},
    "treasury": {"needs": None, "probe": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv",
                 "cost": "free", "what": "Daily par yield curve"},
    "cftc": {"needs": None, "probe": "https://publicreporting.cftc.gov/resource/gpe5-46if.json?$limit=1", "cost": "free", "what": "Traders in financial futures"},
    "fred": {"needs": None, "probe": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", "cost": "free", "what": "Macro and rates"},
    "github": {"needs": None, "probe": "https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv", "cost": "free", "what": "Public dataset mirrors"},
}
PRIORITY = ["databento", "yahoo", "stooq"]


# ---------------------------------------------------------------- connection check
def check(timeout: int = 12) -> list[dict]:
    """Credential present, host reachable, first bytes sane. Never prints a secret."""
    out = []
    y = dt.date.today().year
    for name, s in SOURCES.items():
        row = {"source": name, "what": s["what"], "cost": s["cost"], "credential": None, "reachable": False, "ms": None, "note": ""}
        if s["needs"]:
            row["credential"] = bool(os.environ.get(s["needs"]))
            if not row["credential"]:
                row["note"] = f"set the {s['needs']} secret"
        t = time.time()
        try:
            b = http.get(s["probe"].format(y=y), user_agent=os.environ.get("SEC_USER_AGENT", UA) if name == "sec" else UA, retries=1, timeout=timeout)
            row["reachable"] = len(b) > 0
            row["ms"] = int((time.time() - t) * 1000)
        except Exception as e:  # noqa: BLE001 - every failure is a recorded status, never fatal
            row["note"] = (row["note"] + "; " if row["note"] else "") + type(e).__name__
        row["ok"] = row["reachable"] and row["credential"] is not False
        out.append(row)
    return out


# ---------------------------------------------------------------- daily OHLCV adapters
def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[[c for c in ("open", "high", "low", "close", "volume") if c in df]].astype(float).dropna(subset=["close"])


def parse_yahoo(js: dict) -> pd.DataFrame:
    """Yahoo's chart JSON to OHLCV, scaled by adjclose/close so splits and dividends are adjusted on every column."""
    r = js["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    rows = []
    for i, ts in enumerate(r["timestamp"]):
        c = q["close"][i]
        if c is None:
            continue
        f = (adj[i] / c) if adj and adj[i] else 1.0
        rows.append({"date": dt.datetime.fromtimestamp(ts, dt.timezone.utc).date(), "open": (q["open"][i] or c) * f, "high": (q["high"][i] or c) * f,
                     "low": (q["low"][i] or c) * f, "close": c * f, "volume": q["volume"][i] or 0.0})
    return _frame(rows)


def yahoo(ticker: str, years: int = 10) -> pd.DataFrame:
    p2 = int(time.time())
    p1 = p2 - int(years * 365.25 * 86400)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit&includeAdjustedClose=true"
    return parse_yahoo(json.loads(http.get(url, user_agent="Mozilla/5.0 (buildout research)", retries=2)))


def parse_stooq(text: str) -> pd.DataFrame:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            rows.append({"date": r["Date"], "open": float(r["Open"]), "high": float(r["High"]), "low": float(r["Low"]), "close": float(r["Close"]),
                         "volume": float(r.get("Volume") or 0)})
        except (KeyError, ValueError):
            continue
    return _frame(rows)


def stooq(ticker: str) -> pd.DataFrame:
    sym = ticker.lower().replace(".", "-") + ("" if "." in ticker or ticker.startswith("^") else ".us")
    return parse_stooq(http.get(f"https://stooq.com/q/d/l/?s={sym}&i=d", retries=2).decode("utf-8", "replace"))


def databento(tickers: list[str], start: str, cfg_data=None) -> dict[str, pd.DataFrame]:
    """Split-adjusted OHLCV from Databento with the engine's own factor logic (public split table fallback)."""
    from .data.corporate_actions import split_factors
    from .data.databento_source import DatabentoSource, apply_factors
    src = DatabentoSource(equities_dataset=getattr(cfg_data, "equities_dataset", "auto") if cfg_data else "auto")
    bars = src.raw_daily_bars(tickers, start)
    out = {}
    for t, g in bars.groupby("symbol"):
        g = g.set_index("date").sort_index()
        f = split_factors([t])
        ohlc = g[["open", "high", "low", "close"]]
        adj_close = apply_factors(g[["close"]].rename(columns={"close": t}), f)[t]
        ratio = (adj_close / g["close"]).fillna(1.0)
        df = ohlc.mul(ratio, axis=0)
        df["volume"] = g["volume"] / ratio
        out[t] = df.astype(float)
    return out


def ohlcv(ticker: str, years: int = 10, order: list[str] | None = None, prefetched: dict | None = None) -> tuple[pd.DataFrame, str, dict]:
    """The first source that answers with at least a year of bars. Returns the frame, the source and the errors."""
    errs = {}
    for name in order or PRIORITY:
        try:
            if name == "databento":
                if prefetched and ticker in prefetched:
                    df = prefetched[ticker]
                else:
                    if not os.environ.get("DATABENTO_API_KEY"):
                        errs[name] = "no key"
                        continue
                    df = databento([ticker], (pd.Timestamp.now() - pd.DateOffset(years=years)).strftime("%Y-%m-%d")).get(ticker, pd.DataFrame())
            elif name == "yahoo":
                df = yahoo(ticker, years)
            elif name == "stooq":
                df = stooq(ticker)
            else:
                continue
            if len(df) >= 250:
                return df.tail(int(years * 252) + 5), name, errs
            errs[name] = f"only {len(df)} bars"
        except Exception as e:  # noqa: BLE001
            errs[name] = f"{type(e).__name__}: {str(e)[:120]}"
    return pd.DataFrame(), "none", errs


# ---------------------------------------------------------------- SEC company facts
CIK = {"MSFT": 789019, "GOOGL": 1652044, "AMZN": 1018724, "META": 1326801, "ORCL": 1341439, "NVDA": 1045810, "TSLA": 1318605, "AVGO": 1730168,
       "CRWV": 1769628, "AAPL": 320193}


def companyfacts(ticker: str) -> dict:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError("set SEC_USER_AGENT (a name and email the SEC can contact)")
    cik = CIK.get(ticker)
    if cik is None:
        m = http.get_json("https://www.sec.gov/files/company_tickers.json", ua)
        cik = next((int(v["cik_str"]) for v in m.values() if v["ticker"] == ticker), None)
        if cik is None:
            raise KeyError(ticker)
    return http.get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", ua)


# ---------------------------------------------------------------- positioning and the curve
def cftc_tff(markets: tuple[str, ...] = ("E-MINI S&P 500", "NASDAQ-100", "10-YEAR U.S. TREASURY NOTES", "ULTRA U.S. T-BOND"), weeks: int = 156) -> dict:
    """Leveraged-fund and asset-manager net positions as a share of open interest, with a 3-year percentile."""
    out = {}
    for m in markets:
        q = f"https://publicreporting.cftc.gov/resource/gpe5-46if.json?$where=market_and_exchange_names%20like%20%27%25{m.replace(' ', '%20')}%25%27&$order=report_date_as_yyyy_mm_dd%20DESC&$limit={weeks}"
        rows = json.loads(http.get(q, retries=2))
        if not rows:
            continue
        df = pd.DataFrame(rows)
        oi = df["open_interest_all"].astype(float)
        lev = (df["lev_money_positions_long"].astype(float) - df["lev_money_positions_short"].astype(float)) / oi
        am = (df["asset_mgr_positions_long"].astype(float) - df["asset_mgr_positions_short"].astype(float)) / oi
        out[m] = {"date": df["report_date_as_yyyy_mm_dd"].iloc[0][:10], "leveraged_net_oi": float(lev.iloc[0]), "asset_mgr_net_oi": float(am.iloc[0]),
                  "leveraged_pct_3y": float((lev <= lev.iloc[0]).mean()), "asset_mgr_pct_3y": float((am <= am.iloc[0]).mean())}
    return out


def treasury_curve(year: int | None = None) -> dict:
    y = year or dt.date.today().year
    text = http.get(SOURCES["treasury"]["probe"].format(y=y), retries=2).decode()
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return {}
    last = rows[0]
    return {"date": last.get("Date"), "curve": {k: float(v) / 100 for k, v in last.items() if k != "Date" and v}}


# ---------------------------------------------------------------- broker positions (Robinhood and others), kept private
def import_positions(path: str | Path) -> dict:
    """Read a broker CSV export (Robinhood, Schwab, Fidelity and similar: a symbol column and a quantity, value or
    weight column) into weights. The result is for config.private.toml or analyze_positions; it is never committed."""
    rows = list(csv.DictReader(io.StringIO(Path(path).read_text(encoding="utf-8-sig"))))
    if not rows:
        raise ValueError("empty file")
    keys = {k.lower().strip(): k for k in rows[0]}
    pick = lambda *names: next((keys[n] for n in names if n in keys), None)
    sym = pick("symbol", "ticker", "instrument")
    val = pick("market value", "equity", "value", "current value", "market_value")
    qty = pick("quantity", "shares", "qty")
    px = pick("price", "last price", "average cost", "current price")
    wt = pick("weight", "% of account", "percent of account")
    if sym is None:
        raise ValueError("no symbol column")
    num = lambda s: float(str(s).replace("$", "").replace(",", "").replace("%", "").strip() or 0)
    pos = {}
    for r in rows:
        s = str(r[sym]).strip().upper()
        if not s or s in ("CASH", "TOTAL", "ACCOUNT TOTAL") or not s.replace(".", "").replace("-", "").isalnum():
            continue
        if val:
            v = num(r[val])
        elif qty and px:
            v = num(r[qty]) * num(r[px])
        elif wt:
            v = num(r[wt])
        else:
            raise ValueError("need a value, quantity and price, or weight column")
        pos[s] = pos.get(s, 0.0) + v
    tot = sum(v for v in pos.values() if v > 0)
    return {"weights": {k: v / tot for k, v in sorted(pos.items(), key=lambda kv: -kv[1]) if tot > 0}, "total": tot, "n": len(pos)}


# ---------------------------------------------------------------- the market run
def market(out: str | Path, tickers: list[str], bench: str = "QQQ", years: int = 10, fundamentals: bool = True) -> dict:
    """Technical analysis for every ticker (benchmark-relative), fundamental analysis for the operating companies;
    writes technicals.json and statements.json (derived only) and returns a summary with each source used."""
    from . import statements, technicals
    from .jsonout import write
    pre = {}
    if os.environ.get("DATABENTO_API_KEY"):
        try:
            pre = databento(sorted(set(tickers + [bench])), (pd.Timestamp.now() - pd.DateOffset(years=years)).strftime("%Y-%m-%d"))
        except Exception as e:  # noqa: BLE001
            pre = {"_error": str(e)[:200]}
    b, bsrc, _ = ohlcv(bench, years, prefetched=pre)
    tech, used = {}, {}
    for t in tickers:
        df, src, errs = ohlcv(t, years, prefetched=pre)
        used[t] = {"source": src, "errors": errs}
        if df.empty:
            continue
        a = technicals.analyze(df, t, b["close"] if not b.empty else None)
        a["source"] = src
        a["text"] = technicals.text(a)
        tech[t] = a
    write({"as_of": dt.date.today().isoformat(), "bench": bench, "bench_source": bsrc, "assets": tech, "sources": used}, out, "technicals.json")
    fund = {}
    if fundamentals:
        for t in tickers:
            if t not in CIK:
                continue
            try:
                px = tech[t]["readings"].get("close") if t in tech else None
                fund[t] = statements.analyze(companyfacts(t), t, price=px)
            except Exception as e:  # noqa: BLE001
                fund[t] = {"ticker": t, "ok": False, "note": f"{type(e).__name__}: {str(e)[:150]}"}
        write({"as_of": dt.date.today().isoformat(), "companies": fund}, out, "statements.json")
    return {"technicals": len(tech), "statements": sum(1 for v in fund.values() if v.get("ok")), "sources": used}
