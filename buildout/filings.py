"""The filings engine (v0.28): what companies and their insiders file with the SEC, across every stock that has been in
the S&P 500, tested for whether it predicts returns the market has not priced.

The nowcast (v0.27) found large public signals on fifteen of the largest companies already priced, and its tests
could only see big effects. Breadth is the remedy: about five hundred stocks a month from 2009, so that a small edge on
each becomes measurable (Grinold's fundamental law), with the caveat that stocks share industries and factors, so the
bets are fewer than the stocks. The data are the SEC's own, free and time-stamped, and every value is used only if it
was filed before the last trading day of the month in which it is used.

  universe      every stock in the S&P 500 at each month end, from its historical membership: companies that later
                left the index stay in the months they were members, which removes the index's own survivorship; free
                price sources still lack many delisted companies, so the share of members with a return is reported
  insiders      the SEC's Insider Transactions Data Sets (Forms 4 and 5, quarterly since 2006): open-market purchases
                ("P") and sales ("S") by officers and directors. Signals: the net purchase ratio over six months
                (Lakonishok and Lee 2001); cluster buying, three or more insiders buying within a month; opportunistic
                buying, by insiders with three years of history and no routine calendar pattern (Cohen, Malloy and
                Pomorski 2012); and purchases by the chief executive or chief financial officer
  fundamentals  XBRL company facts from each filing (data.sec.gov), each value dated by the filing that first reported
                it: accruals (Sloan 1996), gross profitability (Novy-Marx 2013), asset growth (Cooper, Gulen and Schill
                2008), net share issuance net of splits (Pontiff and Woodgate 2008), earnings surprise against the same
                quarter a year earlier as restated in the same filing (SUE, Bernard and Thomas 1989) and revenue
                acceleration
  text          optionally, how much each 10-K's words differ from the year before (Cohen, Malloy and Nguyen 2020,
                "Lazy Prices"): heavy to download, so off unless asked for
  tests         each month, every member's latest usable value ranked against the others and set against its return
                over the next one and three months: the rank information coefficient (IC). The p-value comes from the
                monthly IC series itself, by the equal-weighted cosine test (Lazarus, Lewis, Stock and Watson 2018),
                because the IC of a signal tied to industries or factors swings with them from month to month. Also: the
                IC after controlling for size, momentum and value; both halves of the record; a top-minus-bottom
                portfolio in the published direction after costs; Benjamini-Hochberg across every signal and horizon
                tested; and random signals (persistent noise, and tilts toward random factors) through the same
                p-value for the false-pass rate. A reassignment permutation is kept as a diagnostic only
  events        insider purchases as events: the return over 20 and 60 trading days from the first close at which the
                filing could be traded, less the average of every company with prices, against the same stocks on
                dates with no purchase
  today         the latest readings for the book's companies and their ranks in the latest universe. Research only.

Run where the SEC and a price source are reachable (a laptop, or the weekly GitHub job with SEC_USER_AGENT):
    python -m buildout filings --ua "Your Name you@example.com" --out out
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

CONSTITUENTS_URL = "https://raw.githubusercontent.com/hanshof/sp500_constituents/main/sp_500_historical_components.csv"
INSIDER_URLS = ("https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{q}_form345.zip",
                "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/{q}_form345.zip")
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_PAUSE = 0.12                  # the SEC allows ten requests a second; stay under it
BOOK = ("MSFT", "AMZN", "GOOGL", "META", "NVDA", "AVGO", "TSLA", "ORCL")

START = "2009-01-31"              # first month tested (XBRL company facts are sparse before 2009)
SPLIT = "2018-01-01"              # the two halves of the record
FDR_Q = 0.05
N_PERM = 1000
N_FAKE = 100                      # half persistent noise, half tilts toward random factors
BLOCK = 12                        # months per block in the bootstrap of the monthly IC series
MIN_STOCKS = 100                  # months with fewer ranked stocks are skipped
MIN_MONTHS = 60                   # a test needs five years of monthly ICs
MIN_GROUP = 5                    # a signal with ties (a flag, a count) needs this many stocks with a value other than the commonest
STALE_MONTHS = 15                 # a fundamental older than this is not used
COST_BP = 20                      # round trip per unit of turnover for large US stocks, conservatively
SEED = 28

# the direction each signal predicts in the published work (positive: a higher value, a higher next return)
SIGNALS = {
    "insider_net": ("Insider net purchase ratio, six months", +1, "Lakonishok and Lee 2001", 2001, "insiders"),
    "insider_cluster": ("Cluster buying: three or more insiders within a month", +1, "Alldredge and Blank 2019", 2019, "insiders"),
    "insider_opportunistic": ("Opportunistic insider buyers, last month", +1, "Cohen, Malloy and Pomorski 2012", 2012, "insiders"),
    "insider_ceo_cfo": ("Chief executive or financial officer bought, last month", +1, "Seyhun 1986; Jeng, Metrick and Zeckhauser 2003", 2003, "insiders"),
    "accruals": ("Accruals: (net income minus operating cash flow) over assets", -1, "Sloan 1996", 1996, "fundamentals"),
    "gross_profitability": ("Gross profit over assets", +1, "Novy-Marx 2013", 2013, "fundamentals"),
    "asset_growth": ("Asset growth, year over year", -1, "Cooper, Gulen and Schill 2008", 2008, "fundamentals"),
    "share_issuance": ("Net share issuance, year over year", -1, "Pontiff and Woodgate 2008", 2008, "fundamentals"),
    "sue": ("Earnings surprise against the same quarter a year earlier (SUE)", +1, "Bernard and Thomas 1989", 1989, "fundamentals"),
    "revenue_accel": ("Revenue growth acceleration", +1, "Jegadeesh and Livnat 2006", 2006, "fundamentals"),
    "text_similarity": ("10-K similarity to last year's (Lazy Prices)", +1, "Cohen, Malloy and Nguyen 2020", 2020, "text"),
}
HORIZONS = (1, 3)                 # months ahead
NW_LAGS = {1: 3, 3: 6}            # overlapping three-month returns need at least twice the overlap
CONTROLS = ("size", "momentum", "value")

CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "gross_profit": ["GrossProfit"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "assets": ["Assets"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
}
SHARES = [("dei", "EntityCommonStockSharesOutstanding"), ("us-gaap", "CommonStockSharesOutstanding")]
FORMS = {"10-K", "10-Q", "10-K405", "10-KT"}                 # originals only: an amendment is not what the market first saw


# ---------------------------------------------------------------- fetching (polite, cached)
def _cache_path(cache: Path, url: str) -> Path:
    return cache / "sec" / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".bin")


def sec_get(url: str, ua: str, cache: Path | None = None, max_age_days: float | None = None) -> bytes:
    """GET from the SEC with the required contact header, a pause between requests and a disk cache."""
    from .data import http
    if "@" not in ua:
        raise ValueError("the SEC requires a User-Agent with a real name and email, e.g. 'Jane Doe jane@example.com'")
    if cache is not None:
        p = _cache_path(cache, url)
        if p.exists() and (max_age_days is None or (time.time() - p.stat().st_mtime) < max_age_days * 86400):
            return p.read_bytes()
    time.sleep(SEC_PAUSE)
    b = http.get(url, user_agent=ua, timeout=120)
    if cache is not None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    return b


def quarters(start: str = "2006q1", end: str | None = None) -> list[str]:
    y, q = int(start[:4]), int(start[-1])
    end = end or f"{pd.Timestamp.now().year}q{(pd.Timestamp.now().month - 1) // 3 + 1}"
    ey, eq = int(end[:4]), int(end[-1])
    out = []
    while (y, q) <= (ey, eq):
        out.append(f"{y}q{q}")
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


# ---------------------------------------------------------------- the universe
def parse_constituents(text: str) -> pd.DataFrame:
    """Month-end membership, long: (month, ticker). The file lists the members on each change date."""
    d = pd.read_csv(io.StringIO(text))
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date")
    months = pd.date_range(d["date"].min() + pd.offsets.MonthEnd(0), pd.Timestamp.now() + pd.offsets.MonthEnd(0), freq="ME")
    rows = []
    j = 0
    cur: list[str] = []
    dates, ticks = d["date"].to_list(), d["tickers"].to_list()
    for m in months:
        while j < len(dates) and dates[j] <= m:
            cur = [t.strip().upper() for t in str(ticks[j]).split(",") if t.strip()]
            j += 1
        rows += [(m, t) for t in cur]
    out = pd.DataFrame(rows, columns=["month", "ticker"])
    out["carried"] = out["month"] > d["date"].max() + pd.offsets.MonthEnd(0)     # after the file's last change: carried forward, not tested
    return out


# ---------------------------------------------------------------- insiders
def _read_tsv(z: zipfile.ZipFile, stem: str) -> pd.DataFrame:
    name = next((n for n in z.namelist() if n.upper().split("/")[-1].startswith(stem + ".")), None)
    if name is None:
        return pd.DataFrame()
    with z.open(name) as f:
        return pd.read_csv(f, sep="\t", dtype=str, quoting=csv.QUOTE_NONE, on_bad_lines="skip", encoding="utf-8", encoding_errors="replace")


def _d(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")


def parse_insider_zip(data: bytes) -> pd.DataFrame:
    """Open-market purchases and sales of common stock from one quarter's Insider Transactions Data Set: one row per
    transaction with the filing date, the issuer, the reporting owner and their role."""
    z = zipfile.ZipFile(io.BytesIO(data))
    sub, own, tr = _read_tsv(z, "SUBMISSION"), _read_tsv(z, "REPORTINGOWNER"), _read_tsv(z, "NONDERIV_TRANS")
    if sub.empty or tr.empty:
        return pd.DataFrame()
    tr = tr[tr["TRANS_CODE"].isin(["P", "S"])].copy()
    sub = sub[sub["DOCUMENT_TYPE"].isin(["4", "5", "4/A", "5/A"])]
    keep = ["ACCESSION_NUMBER", "FILING_DATE", "ISSUERCIK", "ISSUERTRADINGSYMBOL", "DOCUMENT_TYPE"] + (["AFF10B5ONE"] if "AFF10B5ONE" in sub else [])
    rel0 = own["RPTOWNER_RELATIONSHIP"].fillna("").str.lower()
    own = own.assign(_insider=rel0.str.contains("director|officer")).sort_values(["ACCESSION_NUMBER", "_insider"], ascending=[True, False], kind="mergesort")
    own = own.drop_duplicates("ACCESSION_NUMBER", keep="first")         # a joint filing is one decision: an officer or director stands for it
    df = tr.merge(sub[keep], on="ACCESSION_NUMBER").merge(own[["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"]],
                                                         on="ACCESSION_NUMBER", how="left")
    rel = df["RPTOWNER_RELATIONSHIP"].fillna("").str.lower()
    title = df["RPTOWNER_TITLE"].fillna("").str.lower()
    out = pd.DataFrame({
        "accession": df["ACCESSION_NUMBER"], "filed": _d(df["FILING_DATE"]), "issuer_cik": pd.to_numeric(df["ISSUERCIK"], errors="coerce"),
        "symbol": df["ISSUERTRADINGSYMBOL"].fillna("").str.upper().str.strip(), "owner_cik": pd.to_numeric(df["RPTOWNERCIK"], errors="coerce"),
        "owner": df["RPTOWNERNAME"], "director": rel.str.contains("director"), "officer": rel.str.contains("officer"),
        "ten_pct": rel.str.contains("10%|tenpercent|ten percent"),
        "ceo_cfo": title.str.contains(r"chief executive|chief financial|principal executive|principal financial|\bco-?ceo\b|\bceo\b|\bcfo\b", regex=True),
        "trans_date": _d(df["TRANS_DATE"]), "code": df["TRANS_CODE"],
        "shares": pd.to_numeric(df["TRANS_SHARES"], errors="coerce"), "price": pd.to_numeric(df["TRANS_PRICEPERSHARE"], errors="coerce"),
        "plan_10b5_1": df["AFF10B5ONE"].fillna("").str.strip().str.lower().isin(["1", "true", "y", "yes"]) if "AFF10B5ONE" in df else False,
        "amendment": df["DOCUMENT_TYPE"].str.endswith("/A"),
    })
    out["value"] = out["shares"] * out["price"]
    out = out[out["filed"].notna() & out["issuer_cik"].notna() & ~out["amendment"]]
    return out.drop(columns=["owner"]).reset_index(drop=True)          # names are not needed, and the full history is large


def insider_download(ua: str, start: str = "2006q1", end: str | None = None, cache: Path | None = None, ciks: set | None = None,
                     symbols: set | None = None) -> tuple[pd.DataFrame, dict]:
    """Every quarter's data set, kept to the issuers asked for (by CIK or by the symbol reported at the time), so the
    full history of US insider trading never sits in memory at once."""
    frames, failed = [], {}
    for q in quarters(start, end):
        data = None
        for u in INSIDER_URLS:
            try:
                data = sec_get(u.format(q=q), ua, cache)
                break
            except Exception as exc:                       # try the other location, then record the quarter as missing
                failed[q] = f"{type(exc).__name__}: {exc}"[:160]
        if data is None:
            continue
        failed.pop(q, None)
        t = parse_insider_zip(data)
        if (ciks is not None or symbols is not None) and not t.empty:
            t = t[t["issuer_cik"].isin(ciks or set()) | t["symbol"].isin(symbols or set())]
        t = t[t["director"] | t["officer"]] if not t.empty else t
        frames.append(t)
    cols = ["accession", "filed", "issuer_cik", "symbol", "owner_cik", "director", "officer", "ten_pct", "ceo_cfo", "trans_date", "code",
            "shares", "price", "plan_10b5_1", "amendment", "value"]
    frames = [f for f in frames if not f.empty]
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame({c: pd.Series(dtype=object) for c in cols})), failed


def month_cutoffs(months: pd.DatetimeIndex, days: pd.DatetimeIndex | None = None) -> pd.DatetimeIndex:
    """The last trading day of each month (the month end itself when no daily calendar is given). A filing is usable
    in a month only if it was filed before that day, so it could be traded at that day's close: known (the day after
    filing) on or before the cutoff."""
    if days is None or len(days) == 0:
        return pd.DatetimeIndex(months)
    days = pd.DatetimeIndex(days)
    d = pd.Series(days[days.dayofweek < 5].sort_values().unique())
    last = d.groupby(d.dt.to_period("M")).max()
    return pd.DatetimeIndex([last.get(m.to_period("M"), m) for m in months])


def trading_calendar(px: dict, share: float = 0.5) -> pd.DatetimeIndex:
    """Weekdays on which at least `share` of the tickers trading that year have a bar: one stray bar in one ticker does
    not move the month's last trading day for everyone."""
    cnt = None
    for df in px.values():
        if df is None or df.empty:
            continue
        c = pd.Series(1, index=pd.DatetimeIndex(df.index[~df.index.duplicated()]))
        cnt = c if cnt is None else cnt.add(c, fill_value=0)
    if cnt is None:
        return pd.DatetimeIndex([])
    cnt = cnt.sort_index()
    cnt = cnt[cnt.index.dayofweek < 5]
    ref = cnt.groupby(cnt.index.year).transform("max")
    return pd.DatetimeIndex(cnt.index[cnt >= share * ref])


def insider_signals(tx: pd.DataFrame, months: pd.DatetimeIndex, cutoffs: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Monthly insider signals per issuer, each from filings usable by the month's cutoff (see month_cutoffs).
    Officers and directors only; ten-percent holders who are neither are left out; trades under a 10b5-1 plan,
    where flagged (from 2023), are left out of the buying signals. The one-month window runs from the previous month's
    cutoff to this one's, so consecutive windows do not overlap."""
    if tx.empty:
        return pd.DataFrame(columns=["month", "cik", "signal", "value"])
    cut = pd.DatetimeIndex(months if cutoffs is None else cutoffs)
    T = tx[(tx["director"] | tx["officer"])].copy()
    T["known"] = T["filed"] + pd.Timedelta(days=1)
    buys = T[(T["code"] == "P") & ~T["plan_10b5_1"]]
    sells = T[T["code"] == "S"]
    # Cohen, Malloy and Pomorski (2012): an insider with trades in each of the three prior years is classified;
    # routine if they traded in the same calendar month in each of those years, opportunistic otherwise
    yy = T.assign(y=T["trans_date"].dt.year, m=T["trans_date"].dt.month)
    hs = set(map(tuple, yy[["owner_cik", "y", "m"]].drop_duplicates().to_numpy()))
    hy = set(map(tuple, yy[["owner_cik", "y"]].drop_duplicates().to_numpy()))
    def kind(row):
        if pd.isna(row["trans_date"]):
            return "unclassified"
        y, m = row["trans_date"].year, row["trans_date"].month
        if not all((row["owner_cik"], y - k) in hy for k in (1, 2, 3)):
            return "unclassified"
        return "routine" if all((row["owner_cik"], y - k, m) in hs for k in (1, 2, 3)) else "opportunistic"
    buys = buys.assign(kind=buys.apply(kind, axis=1) if len(buys) else "unclassified")
    rows = []
    for i, m in enumerate(months):
        c = cut[i]
        lo1 = cut[i - 1] if i >= 1 else c - pd.DateOffset(months=1)
        lo6 = cut[i - 6] if i >= 6 else c - pd.DateOffset(months=6)
        b6 = buys[(buys["known"] > lo6) & (buys["known"] <= c)]
        s6 = sells[(sells["known"] > lo6) & (sells["known"] <= c)]
        b1 = buys[(buys["known"] > lo1) & (buys["known"] <= c)]
        nb = b6.groupby("issuer_cik")["owner_cik"].nunique()
        ns = s6.groupby("issuer_cik")["owner_cik"].nunique()
        ids = nb.index.union(ns.index)
        nbv, nsv = nb.reindex(ids).fillna(0), ns.reindex(ids).fillna(0)
        net = (nbv - nsv) / (nbv + nsv)
        rows += [(m, int(k), "insider_net", float(v)) for k, v in net.items()]
        cl = b1.groupby("issuer_cik")["owner_cik"].nunique()
        rows += [(m, int(k), "insider_cluster", float(v >= 3)) for k, v in cl.items()]
        op = b1[b1["kind"] == "opportunistic"].groupby("issuer_cik")["owner_cik"].nunique()
        rows += [(m, int(k), "insider_opportunistic", float(v)) for k, v in op.items()]
        cc = b1[b1["ceo_cfo"]].groupby("issuer_cik").size()
        rows += [(m, int(k), "insider_ceo_cfo", 1.0) for k in cc.index]
    return pd.DataFrame(rows, columns=["month", "cik", "signal", "value"])


# ---------------------------------------------------------------- point-in-time fundamentals
def _all_rows(facts: dict, taxonomy: str, names: list[str], unit: str) -> pd.DataFrame:
    """Every reported value of the named concepts from original filings, with its concept priority."""
    tx = facts.get("facts", {}).get(taxonomy, {})
    frames = []
    for pri, n in enumerate(names):
        u = tx.get(n, {}).get("units", {}).get(unit)
        if not u:
            continue
        d = pd.DataFrame(u)
        d["pri"] = pri
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True)
    d = d[d["form"].isin(FORMS)].copy()
    for c in ("end", "start", "filed"):
        if c in d:
            d[c] = pd.to_datetime(d[c], errors="coerce")
    if "start" not in d:
        d["start"] = pd.NaT
    if "accn" not in d:
        d["accn"] = d["filed"].astype(str)
    return d.dropna(subset=["end", "filed"])


def _facts_rows(facts: dict, taxonomy: str, names: list[str], unit: str) -> pd.DataFrame:
    """Point in time: each period's value as FIRST filed; among concepts, the preferred one on that filing date.
    Stable sorts, so the same input always gives the same pick."""
    d = _all_rows(facts, taxonomy, names, unit)
    if d.empty:
        return d
    return d.sort_values(["filed", "pri"], kind="mergesort").drop_duplicates(["start", "end"], keep="first")


def _flow(d: pd.DataFrame, days: tuple[int, int]) -> pd.DataFrame:
    if d.empty:
        return d
    span = (d["end"] - d["start"]).dt.days
    return d[(span >= days[0]) & (span <= days[1])][["end", "val", "filed", "accn"]].sort_values("end", kind="mergesort")


def split_factor(splits: list | None, after: pd.Timestamp, upto: pd.Timestamp | None = None) -> float:
    """The product of split ratios (new shares per old) with effective dates after `after` (and on or before `upto`)."""
    f = 1.0
    for d, r in splits or []:
        d = pd.Timestamp(d)
        if d > after and (upto is None or d <= upto) and r and r > 0:
            f *= float(r)
    return f


def share_counts(facts: dict) -> pd.DataFrame:
    """Shares outstanding per filing: the cover page count (dei), else the balance sheet's. Companies with several
    classes report one count per class with the same date, which are added up (distinct values only). One row per
    filing: (filed, end, val). Classes with different values per share (Berkshire's A and B) are added one for one,
    and two classes with exactly the same count and date are counted once."""
    for t, n in SHARES:
        d = _all_rows(facts, t, [n], "shares")
        if not d.empty:
            d = d[d["val"] > 0]
            if d.empty:
                continue
            rows = []
            for acc, g in d.groupby("accn", sort=False):
                e = g["end"].max()
                g = g[g["end"] >= e - pd.Timedelta(days=31)]
                rows.append((g["filed"].min(), e, float(g.drop_duplicates(["end", "val"])["val"].sum())))
            g = pd.DataFrame(rows, columns=["filed", "end", "val"]).sort_values(["filed", "end"], kind="mergesort").drop_duplicates("filed", keep="last")
            return g.reset_index(drop=True)
    return pd.DataFrame(columns=["filed", "end", "val"])


def fundamental_signals(facts: dict, splits: list | None = None) -> pd.DataFrame:
    """The six fundamental signals for one company, each dated by the filing that made it knowable (the later of
    the filings it needs). `splits` [(date, ratio)] puts share counts on one basis. Returns (known, signal, value)."""
    D = {k: _facts_rows(facts, "us-gaap", v, "USD/shares" if k == "eps" else "USD") for k, v in CONCEPTS.items()}
    out = []
    A = D["assets"]
    A = A[A["start"].isna()][["end", "val", "filed"]].sort_values("end", kind="mergesort") if not A.empty else A
    ann = {k: _flow(D[k], (350, 380)) for k in ("revenue", "net_income", "cfo", "gross_profit", "cost_of_revenue")}
    qtr = {k: _flow(D[k], (80, 100)) for k in ("revenue", "eps")}

    def at(df, end, tol=10):
        if df is None or df.empty:
            return None
        x = df[(df["end"] - end).abs() <= pd.Timedelta(days=tol)]
        return x.iloc[-1] if len(x) else None
    if A is not None and not A.empty:
        ends = sorted(set(pd.concat([ann[k]["end"] for k in ("net_income", "gross_profit", "revenue") if not ann[k].empty] or [pd.Series(dtype="datetime64[ns]")])))
        seen: list = []
        for e in ends:
            if any(abs((e - x).days) <= 10 for x in seen):
                continue
            seen.append(e)
            a1, a0 = at(A, e), at(A, e - pd.DateOffset(years=1), 20)
            if a1 is None or a0 is None or a1["val"] <= 0 or a0["val"] <= 0:
                continue
            avg = (a1["val"] + a0["val"]) / 2
            known = max(a1["filed"], a0["filed"])
            out.append((known, "asset_growth", a1["val"] / a0["val"] - 1))
            r, c = at(ann["net_income"], e), at(ann["cfo"], e)
            if r is not None and c is not None:
                out.append((max(known, r["filed"], c["filed"]), "accruals", (r["val"] - c["val"]) / avg))
            gp = at(ann["gross_profit"], e)
            if gp is None:
                rv, cr = at(ann["revenue"], e), at(ann["cost_of_revenue"], e)
                if rv is not None and cr is not None:
                    out.append((max(known, rv["filed"], cr["filed"]), "gross_profitability", (rv["val"] - cr["val"]) / a1["val"]))
            else:
                out.append((max(known, gp["filed"]), "gross_profitability", gp["val"] / a1["val"]))
    # shares outstanding, year over year, net of splits between the two counts
    sh = share_counts(facts)
    for _, r in sh.iterrows():
        p = sh[(sh["filed"] <= r["filed"] - pd.DateOffset(months=11)) & (sh["filed"] >= r["filed"] - pd.DateOffset(months=13))]
        if len(p):
            q = p.iloc[-1]
            out.append((r["filed"], "share_issuance", math.log(r["val"] / (q["val"] * split_factor(splits, q["end"], r["end"])))))
    # quarterly: SUE on diluted EPS against the same quarter a year earlier, preferring the comparative restated in the
    # same filing (on the same share basis after a split), then revenue acceleration
    E = qtr["eps"]
    if not E.empty:
        allE = _all_rows(facts, "us-gaap", CONCEPTS["eps"], "USD/shares")
        allE = allE[((allE["end"] - allE["start"]).dt.days.between(80, 100))] if not allE.empty else allE
        diffs: list[tuple[float, pd.Timestamp, pd.Timestamp]] = []
        for _, r in E.reset_index(drop=True).iterrows():
            pe = r["end"] - pd.DateOffset(years=1)
            same = allE[(allE["accn"] == r["accn"]) & ((allE["end"] - pe).abs() <= pd.Timedelta(days=20))] if not allE.empty else allE
            if len(same):
                same = same.sort_values("pri", kind="mergesort")
                pval, pknown = float(same.iloc[0]["val"]), r["filed"]
            else:
                p = at(E, pe, 20)
                if p is None:
                    continue
                pval, pknown = float(p["val"]) / split_factor(splits, p["filed"], r["filed"]), p["filed"]
            dlt = r["val"] - pval
            known = max(r["filed"], pknown)
            if len(diffs) >= 4:
                hist = diffs[-8:]
                sd = float(np.std([x / split_factor(splits, f, r["filed"]) for x, _, f in hist], ddof=1))
                if sd > 0:
                    out.append((max([known] + [k for _, k, _ in hist]), "sue", dlt / sd))
            diffs.append((dlt, known, r["filed"]))
    R = qtr["revenue"]
    if not R.empty:
        g = []
        for _, r in R.iterrows():
            p = at(R, r["end"] - pd.DateOffset(years=1), 20)
            if p is not None and p["val"] > 0 and r["val"] > 0:
                g.append((r["end"], max(r["filed"], p["filed"]), math.log(r["val"] / p["val"])))
        for i in range(1, len(g)):
            if 70 <= (g[i][0] - g[i - 1][0]).days <= 110:
                out.append((max(g[i][1], g[i - 1][1]), "revenue_accel", g[i][2] - g[i - 1][2]))
    df = pd.DataFrame(out, columns=["known", "signal", "value"])
    if df.empty:
        return df
    df["known"] = pd.to_datetime(df["known"]) + pd.Timedelta(days=1)        # usable from the day after the filing
    return df.dropna()


def book_equity(facts: dict) -> pd.DataFrame:
    E = _facts_rows(facts, "us-gaap", CONCEPTS["equity"], "USD")
    if E.empty:
        return E
    E = E[E["start"].isna()][["end", "val", "filed"]]
    E["known"] = E["filed"] + pd.Timedelta(days=1)
    return E


# ---------------------------------------------------------------- the monthly panel
def _month_end_prices(px: dict, col: str, cal: pd.DatetimeIndex | None) -> pd.DataFrame:
    cols, lastday = {}, None
    if cal is not None and len(cal):
        cs = pd.Series(cal, index=cal)
        lastday = cs.groupby(cal.to_period("M")).max()
    for t, df in px.items():
        if df is None or df.empty:
            continue
        c = df[col] if col in df else (df["adj_close"] if "adj_close" in df else df["close"])
        c = c[~c.index.duplicated()].sort_index().dropna()
        m = c.resample("ME").last()
        if lastday is not None:                          # stale: the ticker's last bar is before the month's last trading day
            got = pd.Series(c.index, index=c.index).resample("ME").last()
            need = pd.Series([lastday.get(x.to_period("M"), pd.NaT) for x in got.index], index=got.index)
            m = m.where(~(need.notna() & (got < need)))
        cols[t] = m
    return pd.DataFrame(cols)


def monthly_returns(px: dict, cal: pd.DatetimeIndex | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Month-end simple total returns (adjusted closes) by ticker, and month-end adjusted prices. Only complete months:
    a month is kept once the data reach its last business day or the next month. With a trading calendar, a ticker
    whose last bar in a month is before that month's last trading day has no price for that month."""
    P = _month_end_prices(px, "adj_close", cal)
    if len(P):
        last = max(df.index.max() for df in px.values() if df is not None and not df.empty)
        keep = [m for m in P.index if last > m or last >= (m + pd.offsets.BMonthEnd(0) if m.dayofweek < 5 else m - pd.offsets.BMonthEnd(1))]
        P = P.loc[keep]
    return P.pct_change(fill_method=None), P


def split_prices(px: dict, cal: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Month-end prices adjusted for splits only (today's share basis), for market values; the total-return close
    where a source gives no split-only close."""
    return _month_end_prices(px, "split_close", cal)


def as_of(sig: pd.DataFrame, months: pd.DatetimeIndex, stale: int = STALE_MONTHS, cutoffs: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """For each month, each company's latest value of each signal usable by the month's cutoff (known on or before
    it; see month_cutoffs), not older than `stale` months. sig: (known, cik, signal, value)."""
    cut = pd.DatetimeIndex(months if cutoffs is None else cutoffs).to_numpy()
    out = []
    for s, g in sig.groupby("signal"):
        g = g.sort_values("known", kind="mergesort")
        for c, h in g.groupby("cik"):
            k, v = h["known"].to_numpy(), h["value"].to_numpy(float)
            idx = np.searchsorted(k, cut, side="right") - 1
            ok = idx >= 0
            if not ok.any():
                continue
            age = np.full(len(months), np.inf)
            age[ok] = (months.to_numpy()[ok] - k[idx[ok]]) / np.timedelta64(30, "D")
            use = ok & (age <= stale)
            out.append(pd.DataFrame({"month": months[use], "cik": c, "signal": s, "value": v[idx[use]]}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["month", "cik", "signal", "value"])


def build_panel(members: pd.DataFrame, cik_of: dict, signals: pd.DataFrame, R: pd.DataFrame, P: pd.DataFrame,
                shares: pd.DataFrame | None = None, beq: pd.DataFrame | None = None, PS: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per (month, company): its signals usable by the month's end, its log return over the next 1 and 3
    months, and the controls (log market value, momentum over months t-11 to t-1, book to market). Two share classes
    of one company (GOOG and GOOGL) are one company: the row kept is the class with a return, the book's ticker first."""
    M = members[["month", "ticker"]].copy()
    M["cik"] = [cik_of.get((t, m.year)) or cik_of.get(t) for t, m in zip(M["ticker"], M["month"])]
    M = M.dropna(subset=["cik"])
    M["cik"] = M["cik"].astype(int)
    lr = np.log1p(R)
    fwd = {h: lr[::-1].rolling(h, min_periods=h).sum()[::-1].shift(-1) for h in HORIZONS}     # months t+1 .. t+h
    mom = lr.shift(1).rolling(11, min_periods=9).sum()                                         # t-11 .. t-1 (12-1)
    def look(F, name):
        s = F.stack(future_stack=True).rename(name).reset_index()
        s.columns = ["month", "ticker", name]
        return s
    for h, F in fwd.items():
        M = M.merge(look(F, f"ret{h}"), on=["month", "ticker"], how="left")
    M = M.merge(look(mom, "momentum"), on=["month", "ticker"], how="left")
    M = M.merge(look(PS if PS is not None and not PS.empty else P, "price"), on=["month", "ticker"], how="left")
    M["_has"] = M["ret1"].notna()
    M["_book"] = M["ticker"].isin(BOOK)
    M = M.sort_values(["month", "cik", "_has", "_book", "ticker"], ascending=[True, True, False, False, True], kind="mergesort")
    M = M.drop_duplicates(["month", "cik"], keep="first").drop(columns=["_has", "_book"]).reset_index(drop=True)
    W = signals.pivot_table(index=["month", "cik"], columns="signal", values="value", aggfunc="last").reset_index()
    M = M.merge(W, on=["month", "cik"], how="left")
    if shares is not None and not shares.empty:
        M = M.merge(shares, on=["month", "cik"], how="left")
        M["size"] = np.log(M["price"] * M["shares"]).where((M["price"] > 0) & (M["shares"] > 0))
    else:
        M["size"] = np.nan
    if beq is not None and not beq.empty:
        M = M.merge(beq, on=["month", "cik"], how="left")
        M["value"] = (M["book_equity"] / np.exp(M["size"])).where(M["book_equity"] > 0)
    else:
        M["value"] = np.nan
    return M


# ---------------------------------------------------------------- tests
def _rank(x: pd.Series) -> pd.Series:
    return x.rank(pct=True) - 0.5


def ic_by_month(panel: pd.DataFrame, signal: str, h: int = 1, controls: bool = False) -> pd.Series:
    """Spearman rank IC of the signal against the next-h-month return, month by month; with controls, the signal's
    rank is first residualized on the ranks of size, momentum and value (a Fama-MacBeth style partial IC)."""
    out = {}
    for m, g in panel.groupby("month"):
        g = g[[signal, f"ret{h}"] + (list(CONTROLS) if controls else [])].dropna()
        if len(g) < MIN_STOCKS or g[signal].nunique() < 2 or len(g) - g[signal].value_counts().iloc[0] < MIN_GROUP:
            continue                                    # a binary or count signal needs at least MIN_GROUP stocks on its rarer side
        x, y = _rank(g[signal]), _rank(g[f"ret{h}"])
        if controls:
            Z = np.column_stack([np.ones(len(g))] + [_rank(g[c]).to_numpy() for c in CONTROLS])
            bx = np.linalg.lstsq(Z, x.to_numpy(), rcond=None)[0]
            by = np.linalg.lstsq(Z, y.to_numpy(), rcond=None)[0]
            xr, yr = x.to_numpy() - Z @ bx, y.to_numpy() - Z @ by
            if xr.std() == 0:
                continue
            out[m] = float(np.corrcoef(xr, yr)[0, 1])
        else:
            out[m] = float(np.corrcoef(x, y)[0, 1])
    return pd.Series(out, dtype=float, index=pd.DatetimeIndex(list(out.keys()))).sort_index() if out else pd.Series(dtype=float, index=pd.DatetimeIndex([]))


def _nw_t(s: pd.Series, lags: int) -> float | None:
    from . import labs
    x = s.dropna().to_numpy()
    if len(x) < 24:
        return None
    return float(labs.nw_mean(x, lags)["t"])


def ewc_test(x: np.ndarray) -> dict:
    """Equal-weighted cosine test of a zero mean (Lazarus, Lewis, Stock and Watson 2018): the long-run variance from
    the first nu cosine projections of the demeaned series, nu = 0.4 T^(2/3), and the t-statistic referred to Student's
    t with nu degrees of freedom. It keeps its size in short and autocorrelated series, where Newey-West with few lags
    and the block bootstrap reject too often."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    T = len(x)
    nu = max(4, int(0.4 * T ** (2 / 3)))
    e = x - x.mean()
    t_idx = np.arange(1, T + 1) - 0.5
    L = np.array([math.sqrt(2 / T) * np.sum(np.cos(math.pi * j * t_idx / T) * e) for j in range(1, nu + 1)])
    omega = float(np.mean(L ** 2))
    t = float(math.sqrt(T) * x.mean() / math.sqrt(omega)) if omega > 0 else float("nan")
    return {"t": t, "df": nu, "p": float(2 * stats.t.sf(abs(t), nu)) if np.isfinite(t) else None}


def ic_p(ic: pd.Series | np.ndarray, h: int = 1, n: int = 2000, seed: int = SEED, block: int = BLOCK) -> dict:
    """The p-value for a mean IC from the monthly IC series itself, so month-to-month swings that come from industries
    or factors are in the test: the equal-weighted cosine test (ewc_test), which holds its size in short, autocorrelated
    and overlapping (three-month) series. Newey-West and a moving-block bootstrap are reported beside it as diagnostics;
    both reject too often in short or persistent series. Two-sided. Needs MIN_MONTHS months."""
    from . import labs
    x = np.asarray(ic, float)
    x = x[np.isfinite(x)]
    if len(x) < MIN_MONTHS:
        return {"p": None, "p_block": None, "p_nw": None, "t_nw": None, "t_ewc": None, "df": None}
    ew = ewc_test(x)
    nw = labs.nw_mean(x, NW_LAGS.get(h, max(3, 2 * h)))
    rng = np.random.default_rng(seed)
    e = x - x.mean()
    T, b = len(e), min(block, max(2, len(e) // 4))
    k = int(math.ceil(T / b))
    starts = rng.integers(0, T - b + 1, size=(n, k))
    idx = (starts[:, :, None] + np.arange(b)[None, None, :]).reshape(n, -1)[:, :T]
    boot = e[idx].mean(1)
    pb = float((1 + np.sum(np.abs(boot) >= abs(x.mean()))) / (1 + n))
    return {"p": ew["p"], "t_ewc": ew["t"], "df": ew["df"], "p_block": pb, "p_nw": float(nw["p"]), "t_nw": float(nw["t"])}


def _rank_rows(X: np.ndarray) -> np.ndarray:
    """Each row's values as centred ranks among that row's available values (NaN stays NaN; ties share a rank)."""
    R = np.full(X.shape, np.nan)
    for i in range(X.shape[0]):
        ok = np.isfinite(X[i])
        if ok.sum() > 1:
            R[i, ok] = stats.rankdata(X[i, ok]) / ok.sum() - 0.5
    return R


def _ic_rows(S: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Each month's correlation between the ranks of the signal and of the return, over the companies with both
    (NaN for months with fewer than MIN_STOCKS of them)."""
    m = np.isfinite(S) & np.isfinite(Y)
    n = m.sum(1)
    x, y = np.where(m, S, 0.0), np.where(m, Y, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mx, my = x.sum(1) / n, y.sum(1) / n
        cov = (x * y).sum(1) / n - mx * my
        vx, vy = (x * x).sum(1) / n - mx ** 2, (y * y).sum(1) / n - my ** 2
        ic = cov / np.sqrt(vx * vy)
    ok = (n >= MIN_STOCKS) & np.isfinite(ic) & (vx > 1e-12)
    return np.where(ok, ic, np.nan)


def _mean_rank_ic(S: np.ndarray, Y: np.ndarray) -> float:
    ic = _ic_rows(S, Y)
    return float(np.nanmean(ic)) if np.isfinite(ic).any() else np.nan


def _matrices(panel: pd.DataFrame, signal: str, h: int) -> tuple[np.ndarray, np.ndarray]:
    ciks = np.sort(panel["cik"].unique())
    months = np.sort(panel["month"].unique())
    S = _rank_rows(panel.pivot_table(index="month", columns="cik", values=signal).reindex(index=months, columns=ciks).to_numpy(float))
    Y = _rank_rows(panel.pivot_table(index="month", columns="cik", values=f"ret{h}").reindex(index=months, columns=ciks).to_numpy(float))
    return S, Y


def perm_ic(panel: pd.DataFrame, signal: str, h: int, n: int = N_PERM, seed: int = SEED) -> dict:
    """A diagnostic, not the test: the companies' signal series reassigned to other companies at random (the same
    reassignment in every month). It keeps each series' persistence but breaks the link between a signal and each
    company's industry and factor exposures, so for a signal tied to those it understates the month-to-month spread
    of the IC and calls noise significant. Shown beside the real p so the gap is visible. Two-sided."""
    if panel[signal].notna().sum() == 0:
        return {}
    S, Y = _matrices(panel, signal, h)
    obs = _mean_rank_ic(S, Y)
    if not np.isfinite(obs):
        return {}
    rng = np.random.default_rng(seed)
    null = np.array([_mean_rank_ic(S[:, rng.permutation(S.shape[1])], Y) for _ in range(n)])
    null = null[np.isfinite(null)]
    return {"mean_ic": obs, "p_reassign": float((1 + np.sum(np.abs(null) >= abs(obs))) / (1 + len(null))) if len(null) else None,
            "null_sd": float(null.std()) if len(null) else None, "permutations": int(len(null))}


def quintile_ls(panel: pd.DataFrame, signal: str, direction: int, h: int = 1) -> dict:
    """Long the stocks the published work favours, short those it disfavours, equal weight, rebalanced monthly, after
    costs on turnover; always in the published direction, so a reversed signal shows a negative return. A continuous
    signal is split into quintiles (ties shared by rank); a flag or count, whose commonest value covers half the stocks
    or more, is split into the stocks off that value against those on it. Monthly simple returns."""
    rets, prev = {}, None
    turn = []
    kind = None
    for m, g in panel.groupby("month"):
        g = g[["cik", signal, "ret1"]].dropna().groupby("cik").mean()
        if len(g) < MIN_STOCKS or g[signal].nunique() < 2:
            continue
        v = g[signal]
        top = v.value_counts()
        if top.iloc[0] >= 0.5 * len(v):                 # a flag or a count: off the common value against on it
            kind = "event"
            mode = top.index[0]
            hi, lo = v.index[v > mode], v.index[v == mode]
            if (v < mode).sum() > (v > mode).sum():
                hi, lo = v.index[v == mode], v.index[v < mode]
        else:
            kind = "quintile"
            r = v.rank(method="average", pct=True)
            hi, lo = v.index[r > 0.8], v.index[r <= 0.2]
        if len(hi) < MIN_GROUP or len(lo) < MIN_GROUP:
            continue
        long_, short = (hi, lo) if direction > 0 else (lo, hi)
        w = {c: 1 / len(long_) for c in long_} | {c: -1 / len(short) for c in short}
        to = sum(abs(w.get(c, 0) - (prev or {}).get(c, 0)) for c in set(w) | set(prev or {})) / 2 if prev is not None else 1.0
        turn.append(to)
        sr = np.expm1(g["ret1"])
        rets[m] = float(sum(wi * sr[c] for c, wi in w.items())) - to * COST_BP / 1e4
        prev = w
    s = pd.Series(rets, dtype=float).sort_index()
    if len(s) < 24:
        return {"months": int(len(s)), "kind": kind}
    return {"months": int(len(s)), "kind": kind, "from": s.index[0].strftime("%Y-%m"), "to": s.index[-1].strftime("%Y-%m"),
            "return_annual": float(s.mean() * 12), "vol_annual": float(s.std(ddof=1) * math.sqrt(12)),
            "sharpe": float(s.mean() / s.std(ddof=1) * math.sqrt(12)) if s.std(ddof=1) > 0 else None, "t": _nw_t(s, 3),
            "turnover_monthly": float(np.mean(turn)), "curve": {"months": [d.strftime("%Y-%m") for d in s.index], "r": [float(x) for x in s]}}


def _bh(p: np.ndarray, q: float = FDR_Q) -> float:
    p = np.sort(np.asarray(p, float))
    m = len(p)
    ok = np.flatnonzero(p <= q * np.arange(1, m + 1) / m)
    return float(p[ok[-1]]) if len(ok) else 0.0


def fake_signals(panel: pd.DataFrame, n: int, seed: int, rho: float = 0.9) -> list[tuple[str, np.ndarray]]:
    """Random signals with no edge, as (kind, months x companies matrix) in the panel's sorted months and companies.
    Half are persistent noise (AR(1) per company). Half are tilts toward a random factor: each company's correlation
    over the past 36 months with a random long-short portfolio of the universe, plus persistent noise. A tilt is the
    shape that fools tests which ignore factors: it carries no edge, but its IC rises and falls with the factor."""
    rng = np.random.default_rng(seed)
    ciks = np.sort(panel["cik"].unique())
    months = np.sort(panel["month"].unique())
    past = np.expm1(panel.pivot_table(index="month", columns="cik", values="ret1").reindex(index=months, columns=ciks)).shift(1)   # month t's own return
    out = []
    for k in range(n):
        e = rng.normal(size=(len(months), len(ciks)))
        Z = np.zeros_like(e)
        Z[0] = e[0]
        for i in range(1, len(months)):
            Z[i] = rho * Z[i - 1] + math.sqrt(1 - rho ** 2) * e[i]
        if k % 2 == 1:
            w = rng.normal(size=len(ciks))
            w = w - w.mean()                                # long-short, so the tilt is not simply toward the market
            f = (past.fillna(0.0) * w).sum(axis=1) / past.notna().sum(axis=1).clip(lower=1)
            beta = past.rolling(36, min_periods=24).corr(f).to_numpy(float)
            Z = np.where(np.isfinite(beta), beta + 0.5 * np.nanstd(beta) * Z, np.nan)
            out.append(("factor tilt", Z))
        else:
            out.append(("persistent noise", Z))
    return out


# ---------------------------------------------------------------- insider purchases as events
def event_study(tx: pd.DataFrame, px: dict, ticker_of: dict, windows=(20, 60), seed: int = SEED) -> dict:
    """Open-market purchases by officers and directors (first purchase filing per company per month). The window
    starts at the close of the first trading day after the filing date, the first close at which a filing made after
    hours could be traded, so the reaction on that day is not counted; it runs 20 or 60 trading days, measured against
    the equal-weighted average of every company with prices (each company once). Windows with a missing day are dropped.
    Each event is paired with placebo windows of the same company at dates with no purchase within 90 days; the
    statistic is the event minus its own placebos, averaged by calendar month, and its t comes from the equal-weighted
    cosine test on that monthly series, because events cluster in time and windows overlap."""
    if tx is None or tx.empty or "code" not in tx:
        return {}
    uniq, seen = {}, set()
    for t, df in px.items():                              # two share classes sharing one price series count once
        if df is None or df.empty or id(df) in seen:
            continue
        seen.add(id(df))
        uniq[t] = df["adj_close"] if "adj_close" in df else df["close"]
    closes = pd.DataFrame(uniq).sort_index()
    rets = closes.pct_change(fill_method=None)
    mkt = rets.mean(axis=1)
    ab = rets.sub(mkt, axis=0)
    B = tx[(tx["code"] == "P") & (tx["director"] | tx["officer"]) & ~tx["plan_10b5_1"].astype(bool)].copy()
    B["ym"] = B["filed"].dt.to_period("M")
    B = B.sort_values("filed", kind="mergesort").drop_duplicates(["issuer_cik", "ym"])
    idx = ab.index
    A = ab.to_numpy(float)
    col = {t: j for j, t in enumerate(ab.columns)}
    dates_by = {c: np.sort(g["filed"].to_numpy()) for c, g in B.groupby("issuer_cik")}
    rng = np.random.default_rng(seed)
    res = {}
    for w in windows:
        rows = []
        for _, e in B.iterrows():
            t = ticker_of.get(int(e["issuer_cik"]))
            if t not in col:
                continue
            k = idx.searchsorted(e["filed"], side="right")          # first trading day after the filing date
            if k + 1 + w > len(idx) or len(idx) - w - 1 <= 260:
                continue
            win = A[k + 1:k + 1 + w, col[t]]
            if not np.isfinite(win).all():
                continue
            own, pl = dates_by[e["issuer_cik"]], []
            for _ in range(6):                                     # up to six placebo dates, none within 90 days of a purchase
                j = int(rng.integers(260, len(idx) - w - 1))
                d = idx[j].to_datetime64()
                pos = np.searchsorted(own, d)
                gaps = [abs(own[q] - d) for q in (pos - 1, pos) if 0 <= q < len(own)]
                pw = A[j + 1:j + 1 + w, col[t]]
                if (not gaps or min(gaps) > np.timedelta64(90, "D")) and np.isfinite(pw).all():
                    pl.append(float(pw.sum()))
            if pl:
                rows.append((idx[k].to_period("M"), float(win.sum()), float(np.mean(pl))))
        if len(rows) < 30:
            continue
        D = pd.DataFrame(rows, columns=["month", "car", "placebo"])
        monthly = (D["car"] - D["placebo"]).groupby(D["month"]).mean().sort_index()
        ew = ewc_test(monthly.to_numpy(float)) if len(monthly) >= 24 else {"t": None, "df": None, "p": None}
        res[str(w)] = {"events": int(len(D)), "months_with_events": int(len(monthly)), "mean_car": float(D["car"].mean()),
                       "placebo_mean": float(D["placebo"].mean()), "difference": float((D["car"] - D["placebo"]).mean()), "t": ew["t"], "df": ew["df"], "p": ew["p"],
                       "hit": float((D["car"] > 0).mean())}
    return res


# ---------------------------------------------------------------- the whole run
def _controlled(icc: pd.Series) -> dict:
    """The controlled IC's own test: equal-weighted cosine t and p (needs MIN_MONTHS months)."""
    x = icc.dropna().to_numpy(float) if len(icc) else np.array([])
    if len(x) < MIN_MONTHS:
        return {"t_controlled": None, "p_controlled": None}
    e = ewc_test(x)
    return {"t_controlled": e["t"], "p_controlled": e["p"]}


VERDICTS = {"supported": "still works", "reversed": "significant, but reversed", "cut_only": "passes the cut only",
            "chance": "no better than chance", "opposite": "opposite sign, not significant", "untested": "not testable here"}


def build(members: pd.DataFrame, cik_of: dict, ticker_of: dict, tx: pd.DataFrame, facts: dict, px: dict,
          text: pd.DataFrame | None = None, n_perm: int = N_PERM, n_fake: int = N_FAKE, seed: int = SEED, meta: dict | None = None,
          splits: dict | None = None) -> dict:
    """Everything from data already in memory (so the run can be repeated without the network):
    members (month, ticker[, carried]); cik_of {(ticker, year) or ticker: cik}; ticker_of {cik: ticker}; tx from
    insider_download; facts {cik: companyfacts JSON}; px {ticker: daily frame with close or adj_close, and
    split_close where known}; text (known, cik, signal, value) for 10-K similarity, optional; splits {cik: [(date,
    ratio)]}, optional."""
    t0 = time.time()
    meta = dict(meta or {})
    splits = splits or {}
    cal = trading_calendar(px) if px else None
    R, P = monthly_returns(px, cal)
    PS = split_prices(px, cal).reindex(P.index)
    months = R.index[(R.index >= pd.Timestamp(START))]
    days = cal
    cut = month_cutoffs(months, days)
    members = members[members["month"].isin(months)]
    carried = set(members.loc[members["carried"], "month"]) if "carried" in members else set()
    # signals
    fs, sh, be = [], [], []
    for c, f in facts.items():
        spl = splits.get(int(c))
        d = fundamental_signals(f, spl)
        if not d.empty:
            d["cik"] = int(c)
            fs.append(d)
        s_ = share_counts(f)
        if not s_.empty:                                  # on today's share basis, to match split-adjusted prices
            basis = [split_factor(spl, e) for e in s_["end"]]
            sh.append(pd.DataFrame({"known": s_["filed"] + pd.Timedelta(days=1), "cik": int(c), "signal": "shares", "value": s_["val"].astype(float) * np.array(basis)}))
        b = book_equity(f)
        if not b.empty:
            be.append(pd.DataFrame({"known": b["known"], "cik": int(c), "signal": "book_equity", "value": b["val"].astype(float)}))
    F = pd.concat(fs, ignore_index=True) if fs else pd.DataFrame(columns=["known", "cik", "signal", "value"])
    if text is not None and not text.empty:
        F = pd.concat([F, text], ignore_index=True)
    sig = pd.concat([as_of(F, months, cutoffs=cut), insider_signals(tx, months, cut)], ignore_index=True)
    shares = as_of(pd.concat(sh, ignore_index=True), months, 18, cut).pivot_table(index=["month", "cik"], values="value").reset_index().rename(columns={"value": "shares"}) if sh else None
    beq = as_of(pd.concat(be, ignore_index=True), months, 18, cut).pivot_table(index=["month", "cik"], values="value").reset_index().rename(columns={"value": "book_equity"}) if be else None
    panel = build_panel(members, cik_of, sig, R, P, shares, beq, PS)
    # insider counts are zero, not missing, for members with no insider purchase that month, in quarters whose data set arrived
    bad_q = {pd.Period(q.replace("q", "Q")) for q in (meta.get("failed_quarters") or {})}
    have = ~panel["month"].dt.to_period("Q").isin(bad_q)
    for s in ("insider_cluster", "insider_opportunistic", "insider_ceo_cfo"):
        if s in panel:
            panel.loc[have, s] = panel.loc[have, s].fillna(0.0)
    present = [s for s in SIGNALS if s in panel and panel[s].notna().sum() > 0]
    # coverage, counted over every member, before members without a company match are dropped
    mm = members.assign(cik=[cik_of.get((t, m.year)) or cik_of.get(t) for t, m in zip(members["ticker"], members["month"])])
    per = mm.groupby("month").agg(members=("ticker", "size"), with_cik=("cik", lambda x: x.notna().sum()),
                                  companies=("cik", lambda x: x.nunique() + x.isna().sum()))
    got = panel.groupby("month")["ret1"].apply(lambda x: x.notna().sum())
    per = per.join(got.rename("with_return"), how="left").fillna({"with_return": 0})
    per = per[~per.index.isin(carried)]
    coverage = {"months": int(len(per)), "members_mean": float(per["members"].mean()) if len(per) else None,
                "companies_mean": float(per["companies"].mean()) if len(per) else None,
                "with_cik_share": float((per["with_cik"] / per["members"]).mean()) if len(per) else None,
                "with_return_share": float((per["with_return"] / per["companies"]).mean()) if len(per) else None,
                "signal_share": {s: float(panel[s].notna().mean()) for s in present},
                "membership_through": (min(carried) - pd.offsets.MonthEnd(1)).strftime("%Y-%m") if carried else (months[-1].strftime("%Y-%m") if len(months) else None),
                "dual_class_rows_merged": int(mm.dropna(subset=["cik"]).duplicated(["month", "cik"]).sum())}
    PT = panel[~panel["month"].isin(carried)]
    # tests
    tests, untested = [], []
    for s in present:
        name, direction, ref, year, family = SIGNALS[s]
        for h in HORIZONS:
            ic = ic_by_month(PT, s, h)
            if len(ic) < MIN_MONTHS:
                untested.append({"signal": s, "name": name, "horizon": h, "months": int(len(ic)),
                                 "why": f"only {len(ic)} months (a test needs {MIN_MONTHS}) with at least {MIN_STOCKS} stocks and {MIN_GROUP} off the commonest value"})
                continue
            icc = ic_by_month(PT, s, h, controls=True)
            pp = ic_p(ic, h, seed=seed)
            pm = perm_ic(PT, s, h, n_perm, seed) if n_perm else {}
            halves = {k: float(v.mean()) if len(v) else None for k, v in (("first", ic[ic.index < pd.Timestamp(SPLIT)]), ("second", ic[ic.index >= pd.Timestamp(SPLIT)]))}
            tests.append({"signal": s, "name": name, "family": family, "reference": ref, "published": year, "direction": direction, "horizon": h,
                          "months": int(len(ic)), "mean_ic": float(ic.mean()), "t_nw": pp["t_nw"],
                          "mean_ic_controlled": float(icc.mean()) if len(icc) else None, **_controlled(icc), "t_ewc": pp["t_ewc"], "df": pp["df"],
                          "p": pp["p"], "p_block": pp["p_block"], "p_nw": pp["p_nw"], "p_reassign": pm.get("p_reassign"), "halves": halves,
                          "same_sign_both_halves": bool(halves["first"] is not None and halves["second"] is not None and np.sign(halves["first"]) == np.sign(halves["second"]) == np.sign(ic.mean())),
                          "as_published": bool(np.sign(ic.mean()) == direction),
                          "ic_series": {"months": [d.strftime("%Y-%m") for d in ic.index], "ic": [float(x) for x in ic]}})
    p = np.array([t["p"] if t.get("p") is not None else 1.0 for t in tests])
    cut_bh = _bh(p) if len(p) else 0.0
    for t in tests:
        t["pass_bh"] = bool(cut_bh > 0 and (t.get("p") or 1) <= cut_bh)
        t["supported"] = bool(t["pass_bh"] and t["as_published"] and t["same_sign_both_halves"] and t["p_controlled"] is not None
                              and t["p_controlled"] <= 0.05 and np.sign(t["mean_ic_controlled"] or 0) == t["direction"])
        t["verdict"] = ("supported" if t["supported"] else "reversed" if t["pass_bh"] and not t["as_published"] else "cut_only" if t["pass_bh"]
                        else "chance" if t["as_published"] else "opposite")
        if t["horizon"] == 1:
            t["portfolio"] = quintile_ls(PT, t["signal"], t["direction"], 1)      # always the published direction
    # random signals with no edge through the same test
    fake = {"signals": 0}
    if n_fake:
        ciks = np.sort(PT["cik"].unique())
        mo = np.sort(PT["month"].unique())
        Y = _rank_rows(PT.pivot_table(index="month", columns="cik", values="ret1").reindex(index=mo, columns=ciks).to_numpy(float))
        present_mask = np.isfinite(PT.pivot_table(index="month", columns="cik", values="ret1").reindex(index=mo, columns=ciks).to_numpy(float))
        rows = []
        rng = np.random.default_rng(seed + 2)
        for k, (kind, Z) in enumerate(fake_signals(PT, n_fake, seed + 1)):
            S = _rank_rows(np.where(present_mask, Z, np.nan))
            ic = _ic_rows(S, Y)
            pr = ic_p(ic[np.isfinite(ic)], 1, n=1000, seed=seed + 10 + k)
            row = {"kind": kind, "p": pr["p"] if pr["p"] is not None else 1.0, "t_nw": pr["t_nw"], "ic": ic}
            if kind == "factor tilt" and n_perm:
                obs = np.nanmean(ic)
                null = np.array([_mean_rank_ic(S[:, rng.permutation(S.shape[1])], Y) for _ in range(max(100, n_perm // 10))])
                row["p_reassign"] = float((1 + np.sum(np.abs(null) >= abs(obs))) / (1 + len(null)))
            rows.append(row)
        fp = np.array([r["p"] for r in rows])
        by = {}
        for kind in ("persistent noise", "factor tilt"):
            G = [r for r in rows if r["kind"] == kind]
            if G:
                by[kind] = {"n": len(G), "share_p_below_05": float(np.mean([r["p"] <= 0.05 for r in G])), "share_p_below_01": float(np.mean([r["p"] <= 0.01 for r in G]))}
                if any("p_reassign" in r for r in G):
                    by[kind]["share_reassign_p_below_05"] = float(np.mean([r["p_reassign"] <= 0.05 for r in G if "p_reassign" in r]))
                if len(G) > 2:                                # signals that share factors are not independent draws
                    M = pd.DataFrame({i: r["ic"] for i, r in enumerate(G)}).corr().to_numpy()
                    rho = float(np.nanmean(np.abs(M[~np.eye(len(G), dtype=bool)])))
                    by[kind]["mean_abs_corr"] = rho
                    by[kind]["effective_n"] = float(len(G) / (1 + (len(G) - 1) * rho))
        noise_p = np.array([r["p"] for r in rows if r["kind"] == "persistent noise"])
        fake = {"signals": len(rows), "share_p_below_05": float(np.mean(noise_p <= 0.05)) if len(noise_p) else None,
                "share_p_below_01": float(np.mean(noise_p <= 0.01)) if len(noise_p) else None, "headline": "persistent noise",
                "passed_at_cut": int(np.sum(fp <= cut_bh)) if cut_bh > 0 else 0, "by_kind": by}
    # insider purchases as events
    ev = event_study(tx, px, ticker_of)
    # today: the book's latest readings and ranks
    last = panel["month"].max() if len(panel) else None
    today = []
    if last is not None:
        G = panel[panel["month"] == last]
        for t in BOOK:
            c = cik_of.get(t)
            row = G[G["cik"] == c] if c is not None else G.iloc[0:0]
            if row.empty:
                continue
            r = row.iloc[0]
            today.append({"ticker": t, "month": last.strftime("%Y-%m"), "membership_carried": bool(last in carried),
                          "readings": {s: (None if pd.isna(r.get(s)) else float(r[s])) for s in present},
                          "percentile": {s: (None if pd.isna(r.get(s)) else float((G[s] < r[s]).sum() / max(1, G[s].notna().sum()))) for s in present}})
        recent = tx[(tx["filed"] > last - pd.DateOffset(days=90))] if not tx.empty and "filed" in tx else pd.DataFrame(columns=["issuer_cik", "code", "owner_cik", "value"])
        for x in today:
            c = cik_of.get(x["ticker"])
            rr = recent[recent["issuer_cik"] == c] if c is not None and not recent.empty else pd.DataFrame(columns=["issuer_cik", "code", "owner_cik", "value"])
            x["insiders_90d"] = {"buyers": int(rr[rr["code"] == "P"]["owner_cik"].nunique()), "sellers": int(rr[rr["code"] == "S"]["owner_cik"].nunique()),
                                 "sold_value": float(rr[rr["code"] == "S"]["value"].sum()) if len(rr) else 0.0}
    tm = PT["month"]
    out = {"schema": 2, "built": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"), "meta": meta,
           "universe": {"source": CONSTITUENTS_URL, "months": int(tm.nunique()), "from": tm.min().strftime("%Y-%m") if len(tm) else None,
                        "to": tm.max().strftime("%Y-%m") if len(tm) else None, "tickers_ever": int(members["ticker"].nunique()),
                        "companies_with_facts": int(len(facts)), "insider_transactions": int(len(tx))},
           "coverage": coverage, "tests": tests, "untested": untested, "bh_cut": cut_bh, "n_hypotheses": int(len(tests)), "fakes": fake, "events": ev, "today": today,
           "assumptions": {"start": START, "split": SPLIT, "fdr_q": FDR_Q, "block_months": BLOCK, "nw_lags": NW_LAGS, "permutations_diagnostic": n_perm,
                           "stale_months": STALE_MONTHS, "cost_bp_round_trip": COST_BP, "min_stocks": MIN_STOCKS, "min_group": MIN_GROUP, "min_months": MIN_MONTHS,
                           "horizons": list(HORIZONS), "controls": list(CONTROLS)},
           "verdicts": VERDICTS, "limitations": LIMITATIONS, "timing_s": round(time.time() - t0, 1)}
    out = _clean(out)
    out["findings"] = summary(out)
    return out


LIMITATIONS = [
    "The universe is the S&P 500 at each month end: large, liquid companies, where published anomalies are known to be weakest; the same engine can take a broader list.",
    "The membership file (hanshof/sp500_constituents) ends at its last recorded change; months after it carry that list forward, are left out of the tests, and are marked where the book's readings use them.",
    "Returns come from free price sources, downloaded by each company's current ticker, which often lack companies that were delisted or went bankrupt; the share of members with a return is reported, and a missing delisting return biases results toward survivors.",
    "Stocks share industries and factors, so the bets are fewer than the stocks: the p-value comes from the month-to-month spread of the IC, which carries that dependence. The controls are size, momentum and value; industry is not among them, so a signal that only picks an industry can still pass.",
    "Fundamentals come from XBRL company facts, which begin in 2009 for most companies; each value is the one first filed, but a filing date is a day, not a minute, so a value is used only if it was filed before the last trading day of the month. Revenue can be reported under different concepts in different years.",
    "Two share classes of one company (GOOG and GOOGL) are one company in the tests. Share counts are put on one basis with split events from the price source; where the source gives none (Stooq), market value and share issuance can be off around a split. Classes worth different amounts per share (Berkshire's A and B) are added one for one, which misstates that company's size.",
    "Ticker-to-company mapping uses the symbols insiders reported at the time and the SEC's current list; a reused ticker can be mismatched for a while, and unmatched members are counted and left out.",
    "The 10b5-1 plan flag exists in the insider data sets only from 2023, so earlier planned sales and purchases count as discretionary.",
    "Most of these signals were published before the sample begins, so the tests ask whether they still work, not whether they ever did (McLean and Pontiff 2016 find anomaly returns fall by about half after publication).",
]


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d")
    return o


def _f(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def summary(o: dict) -> list[str]:
    u, cv = o["universe"], o["coverage"]
    out = [f"{u['tickers_ever']:,} tickers that were in the S&P 500, tested from {u['from']} to {u['to']} ({u['months']} months, about "
           f"{_f(cv.get('companies_mean'), 0)} companies a month, {_f((cv.get('with_return_share') or 0) * 100, 0)}% with a return), {u['insider_transactions']:,} insider "
           f"transactions and the filings of {u['companies_with_facts']:,} companies."]
    T = o["tests"]
    sup = [t for t in T if t["supported"]]
    passed = [t for t in T if t["pass_bh"]]
    fk = o.get("fakes") or {}
    by = fk.get("by_kind") or {}
    tilt = by.get("factor tilt") or {}
    line = (f"{o['n_hypotheses']} hypotheses tested (signals by horizon; {len(o.get('untested') or [])} not testable), p-values from each signal's monthly IC "
            f"series (the equal-weighted cosine test, which holds its size in short and autocorrelated series), Benjamini-Hochberg at q = {FDR_Q}: "
            f"{len(passed)} passed, {len(sup)} also held in the published direction, in both halves and after controlling for size, momentum and value.")
    if fk.get("signals"):
        noise = by.get("persistent noise") or {}
        line += (f" Of {noise.get('n', 0)} random persistent signals, {_f((fk.get('share_p_below_05') or 0) * 100, 0)}% had p below 0.05 (about 5% "
                 f"is the honest rate).")
        if tilt.get("n"):
            line += (f" Random tilts toward factors are not independent draws (effective number {_f(tilt.get('effective_n'), 1)} of {tilt['n']}) and on real "
                     f"data can carry real factor premia, so their {_f((tilt.get('share_p_below_05') or 0) * 100, 0)}% below 0.05 is a reading, not a calibration")
            if tilt.get("share_reassign_p_below_05") is not None:
                line += f"; a reassignment permutation put {_f(tilt['share_reassign_p_below_05'] * 100, 0)}% of them below 0.05"
            line += "."
    out.append(line)
    for t in sorted(T, key=lambda t: t.get("p") or 1)[:8]:
        if t["horizon"] != 1:
            continue
        pf = t.get("portfolio") or {}
        out.append(f"{t['name']} ({t['reference']}): mean rank IC {_f(t['mean_ic'])} (t {_f(t['t_nw'], 1)}; controlled {_f(t['mean_ic_controlled'])}), "
                   f"p {_f(t['p'], 4)}, {'as published' if t['as_published'] else 'opposite to the published sign'}; the published long-short after costs: "
                   f"Sharpe {_f(pf.get('sharpe'), 2)}.")
    ev = o.get("events") or {}
    if ev.get("20"):
        e = ev["20"]
        out.append(f"Insider purchases as events: {e['events']:,} purchases; over 20 trading days from the first tradable close the stock beat the universe by "
                   f"{_f(e['mean_car'] * 100, 2)}% against {_f(e['placebo_mean'] * 100, 2) if e.get('placebo_mean') is not None else 'n/a'}% on the same stocks' "
                   f"placebo dates (p {_f(e.get('p'), 3)}, by month).")
    return out


# ---------------------------------------------------------------- 10-K text (optional: heavy to download)
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
OLDER_URL = "https://data.sec.gov/submissions/{name}"


def tenk_list(sub: dict, older: list[dict] | None = None) -> pd.DataFrame:
    """The 10-K filings (originals) in a company's submissions JSON: accession, filing date, primary document. The
    JSON's "recent" block holds only the latest filings of a large filer; `older` takes the extra files it lists
    under filings.files, so the history is complete."""
    blocks = [(sub.get("filings") or {}).get("recent") or {}] + list(older or [])
    r = {k: sum((list(b.get(k, [])) for b in blocks), []) for k in ("form", "accessionNumber", "filingDate", "primaryDocument")}
    if not r["form"]:
        return pd.DataFrame(columns=["acc", "filed", "doc"])
    d = pd.DataFrame({"form": r["form"], "acc": r["accessionNumber"], "filed": r["filingDate"], "doc": r["primaryDocument"]})
    d = d[d["form"].isin(["10-K", "10-K405", "10-KT"])].copy()
    d["filed"] = pd.to_datetime(d["filed"], errors="coerce")
    return d.dropna(subset=["filed"]).drop_duplicates("acc").sort_values("filed", kind="mergesort")


def words(html: bytes) -> dict:
    """Word counts of a filing's visible text: styles, scripts and the hidden inline XBRL header removed, then tags
    and entities stripped, lower case, letters only, words of 3+ letters."""
    import re
    t = re.sub(rb"(?is)<(style|script|ix:header)\b.*?</\1\s*>", b" ", html)
    t = re.sub(rb"(?is)<div[^>]*display\s*:\s*none[^>]*>.*?</div>", b" ", t)
    t = re.sub(rb"<[^>]+>", b" ", t)
    t = re.sub(rb"&[#a-zA-Z0-9]+;", b" ", t).decode("utf-8", "replace").lower()
    c: dict = {}
    for w in re.findall(r"[a-z]{3,}", t):
        c[w] = c.get(w, 0) + 1
    return c


def cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return float("nan")
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na > 0 and nb > 0 else float("nan")


def text_signals(cik: int, ua: str, cache: Path, max_docs: int = 20) -> pd.DataFrame:
    """Lazy Prices: each 10-K's cosine similarity (word counts) to the company's previous 10-K, known the day after
    it was filed. Only the word counts are kept on disk, not the documents."""
    sub = json.loads(sec_get(SUBMISSIONS_URL.format(cik=int(cik)), ua, cache, max_age_days=7))
    older = []
    for f in (sub.get("filings") or {}).get("files") or []:
        try:
            older.append(json.loads(sec_get(OLDER_URL.format(name=f["name"]), ua, cache, max_age_days=30)))
        except Exception:
            continue
    L = tenk_list(sub, older).tail(max_docs)
    vecs, out = [], []
    for _, r in L.iterrows():
        key = cache / "text" / f"{int(cik)}_{r['acc']}.json"
        if key.exists():
            v = json.loads(key.read_text())
        else:
            v = words(sec_get(ARCHIVE_URL.format(cik=int(cik), acc=r["acc"].replace("-", ""), doc=r["doc"]), ua, None))
            key.parent.mkdir(parents=True, exist_ok=True)
            key.write_text(json.dumps(v))
        if vecs:
            out.append((r["filed"] + pd.Timedelta(days=1), int(cik), "text_similarity", cosine(v, vecs[-1])))
        vecs.append(v)
    return pd.DataFrame(out, columns=["known", "cik", "signal", "value"]).dropna()


# ---------------------------------------------------------------- validation on synthetic data in the SEC's layouts
def _synthetic_facts(rng: np.random.Generator, gp_level: float, split_on: str | None = None) -> dict:
    """One company's company-facts JSON, 2008 to 2020: annual 10-K values, quarterly 10-Q values with the prior
    year's comparative in the same filing, a cover-page share count and, when `split_on` is set, a 2-for-1 split on
    that date (share counts double, and the comparative EPS in the next filings is restated)."""
    A, NI, CFO, GP, EQ, EPS, REV, SH = [], [], [], [], [], [], [], []
    base = {}
    sd = pd.Timestamp(split_on) if split_on else None
    for y in range(2008, 2021):
        filed = f"{y + 1}-02-20"
        acc = f"k{y}"
        a = 1000 * (1.05 ** (y - 2008)) * (1 + 0.02 * rng.normal())
        A.append({"end": f"{y}-12-31", "val": a, "filed": filed, "form": "10-K", "accn": acc})
        EQ.append({"end": f"{y}-12-31", "val": a * (0.4 + 0.1 * rng.random()), "filed": filed, "form": "10-K", "accn": acc})
        NI.append({"start": f"{y}-01-01", "end": f"{y}-12-31", "val": (0.08 + 0.02 * rng.normal()) * a, "filed": filed, "form": "10-K", "accn": acc})
        CFO.append({"start": f"{y}-01-01", "end": f"{y}-12-31", "val": (0.10 + 0.02 * rng.normal()) * a, "filed": filed, "form": "10-K", "accn": acc})
        GP.append({"start": f"{y}-01-01", "end": f"{y}-12-31", "val": gp_level * a, "filed": filed, "form": "10-K", "accn": acc})
        n = 1e6 * (1 + 0.01 * rng.normal()) * (2.0 if sd is not None and pd.Timestamp(f"{y + 1}-02-01") > sd else 1.0)
        SH.append({"end": f"{y + 1}-02-01", "val": n, "filed": filed, "form": "10-K", "accn": acc})
        for s_, e, f in (("01-01", "03-31", "05-01"), ("04-01", "06-30", "08-01"), ("07-01", "09-30", "11-01")):
            acc_q = f"q{y}{e[:2]}"
            post = sd is not None and pd.Timestamp(f"{y}-{f}") > sd
            eps_true = 1 + 0.05 * rng.normal()
            base[(y, e)] = eps_true
            EPS.append({"start": f"{y}-{s_}", "end": f"{y}-{e}", "val": eps_true / (2.0 if post else 1.0), "filed": f"{y}-{f}", "form": "10-Q", "accn": acc_q})
            if (y - 1, e) in base:                                       # the comparative, restated on the filing's share basis
                EPS.append({"start": f"{y - 1}-{s_}", "end": f"{y - 1}-{e}", "val": base[(y - 1, e)] / (2.0 if post else 1.0), "filed": f"{y}-{f}", "form": "10-Q", "accn": acc_q})
            REV.append({"start": f"{y}-{s_}", "end": f"{y}-{e}", "val": 100 * (1 + 0.05 * rng.normal()), "filed": f"{y}-{f}", "form": "10-Q", "accn": acc_q})
    g = lambda d: {"units": {"USD": d}}
    return {"facts": {"us-gaap": {"Assets": g(A), "StockholdersEquity": g(EQ), "NetIncomeLoss": g(NI), "NetCashProvidedByUsedInOperatingActivities": g(CFO),
                                  "GrossProfit": g(GP), "EarningsPerShareDiluted": {"units": {"USD/shares": EPS}}, "Revenues": g(REV)},
                      "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": SH}}}}}


def _daily(r: np.ndarray, months: pd.DatetimeIndex, days: pd.DatetimeIndex, rng: np.random.Generator) -> np.ndarray:
    """Daily log returns that add up exactly to each month's log return: the month's return spread evenly, plus daily
    noise that sums to zero within the month."""
    out = np.zeros(len(days))
    per = days.to_period("M")
    for k, m in enumerate(months):
        ii = np.flatnonzero(per == m.to_period("M"))
        if len(ii):
            z = 0.01 * rng.normal(size=len(ii))
            out[ii] = np.log1p(r[k]) / len(ii) + z - z.mean()
    return out


def synthetic_inputs(n: int = 160, edge: float = 0.004, seed: int = 3) -> dict:
    """A universe of n companies in the SEC's layouts, monthly prices from 2008 to 2020 and one planted edge: higher
    gross profitability, a higher next-month return by `edge` per standard deviation (measured rank IC about 0.04, at
    the strong end of what published anomalies show in large stocks). Prices are daily, so month ends that fall on a
    weekend and the event study's windows are exercised. Returns also load on a market factor and on a second, industry-like factor with a
    persistent loading per company, so random tilts toward factors can be tested. Insider trades are random. One
    company has two share classes (T000 and T000B), one has a 2-for-1 split in June 2013, twenty companies leave the
    index after 2016 and twenty join in 2013, and the last two months are carried forward past the membership file."""
    rng = np.random.default_rng(seed)
    months = pd.date_range("2008-12-31", "2020-12-31", freq="ME")
    days = pd.bdate_range("2008-12-01", "2020-12-31")
    tick = [f"T{i:03d}" for i in range(n)]
    f1 = rng.normal(0.0, 0.045, size=len(months))         # factors with no premium: a tilt toward them is variance, not edge
    f2 = rng.normal(0.0, 0.035, size=len(months))
    facts, px, splits = {}, {}, {}
    for i, t in enumerate(tick):
        k = 0.15 + 0.3 * rng.random()
        facts[1000 + i] = _synthetic_facts(rng, k, "2013-06-15" if i == 7 else None)
        if i == 7:
            splits[1007] = [(pd.Timestamp("2013-06-15"), 2.0)]
        z = (k - 0.3) / 0.0866
        b, g = rng.normal(1.0, 0.3), rng.normal(0.0, 1.0)
        r = edge * z + b * f1 + g * f2 + 0.06 * rng.normal(size=len(months))
        px[t] = pd.DataFrame({"close": 100 * np.exp(np.cumsum(_daily(r, months, days, rng)))}, index=days)
    px["T000B"] = px["T000"] * (1 + 0.002 * rng.normal(size=len(days)))[:, None]
    rows = []
    for m in months:
        for i, t in enumerate(tick):
            if 100 <= i < 120 and m > pd.Timestamp("2016-12-31"):
                continue
            if 120 <= i < 140 and m < pd.Timestamp("2013-01-31"):
                continue
            rows.append((m, t))
        rows.append((m, "T000B"))
    members = pd.DataFrame(rows, columns=["month", "ticker"])
    members["carried"] = members["month"] > months[-3]
    cik_of = {t: 1000 + i for i, t in enumerate(tick)} | {"T000B": 1000}
    tx = []
    for i in range(n):
        c = 1000 + i
        for y in range(2006, 2021):
            for code, lam in (("P", 1.2), ("S", 4.0)):
                for _ in range(rng.poisson(lam)):
                    o = int(rng.integers(0, 8))
                    filed = pd.Timestamp(f"{y}-01-01") + pd.Timedelta(days=int(rng.integers(0, 360)))
                    tx.append({"accession": f"a{c}{y}{len(tx)}", "filed": filed, "issuer_cik": c, "symbol": tick[i], "owner_cik": c * 100 + o,
                               "director": o >= 4, "officer": o < 4, "ten_pct": False, "ceo_cfo": o == 0, "trans_date": filed - pd.Timedelta(days=2),
                               "code": code, "shares": 1000.0, "price": 50.0, "plan_10b5_1": False, "amendment": False, "value": 50000.0})
        for y in range(2006, 2021):                                  # cluster purchases: three or four insiders in one month, no edge
            for mo in range(1, 13):
                if rng.random() < 0.06:
                    for o in rng.choice(8, size=int(rng.integers(3, 5)), replace=False):
                        filed = pd.Timestamp(f"{y}-{mo:02d}-01") + pd.Timedelta(days=int(rng.integers(0, 25)))
                        tx.append({"accession": f"c{c}{y}{len(tx)}", "filed": filed, "issuer_cik": c, "symbol": tick[i], "owner_cik": c * 100 + int(o),
                                   "director": o >= 4, "officer": o < 4, "ten_pct": False, "ceo_cfo": o == 0, "trans_date": filed - pd.Timedelta(days=2),
                                   "code": "P", "shares": 1000.0, "price": 50.0, "plan_10b5_1": False, "amendment": False, "value": 50000.0})
    tx = pd.DataFrame(tx)
    return {"members": members, "cik_of": cik_of, "ticker_of": {1000 + i: t for i, t in enumerate(tick)}, "tx": tx, "facts": facts, "px": px, "splits": splits}


def validate(n_perm: int = 200, n_fake: int = 40) -> dict:
    """The engine run end to end on synthetic_inputs(): the planted signal should pass and hold on every check, the
    noise signals (insider trades included) should not, random signals, factor tilts included, should land below
    p = 0.05 about 5% of the time, two share classes should be one company and a split should not read as issuance."""
    d = synthetic_inputs()
    o = build(d["members"], d["cik_of"], d["ticker_of"], d["tx"], d["facts"], d["px"], n_perm=n_perm, n_fake=n_fake,
              meta={"synthetic": True, "planted": "gross_profitability"}, splits=d["splits"])
    T = [t for t in o["tests"] if t["horizon"] == 1]
    gp = next((t for t in T if t["signal"] == "gross_profitability"), {})
    noise = [t for t in o["tests"] if t["signal"] != "gross_profitability"]
    si = fundamental_signals(d["facts"][1007], d["splits"][1007])
    si = si[(si["signal"] == "share_issuance") & (si["known"].dt.year == 2014)]["value"]
    si_raw = fundamental_signals(d["facts"][1007])
    si_raw = si_raw[(si_raw["signal"] == "share_issuance") & (si_raw["known"].dt.year == 2014)]["value"]
    tilt = (o["fakes"].get("by_kind") or {}).get("factor tilt") or {}
    out = {"planted": {k: gp.get(k) for k in ("mean_ic", "t_nw", "t_controlled", "p", "p_reassign", "pass_bh", "as_published", "supported", "verdict")}
                      | {"sharpe": (gp.get("portfolio") or {}).get("sharpe")},
           "noise": [{k: t.get(k) for k in ("signal", "horizon", "mean_ic", "p", "p_reassign", "pass_bh", "verdict")} for t in noise],
           "untested": o["untested"], "fakes": o["fakes"], "n_hypotheses": o["n_hypotheses"],
           "checks": {"dual_class_rows_merged": o["coverage"]["dual_class_rows_merged"], "membership_through": o["coverage"]["membership_through"],
                      "split_issuance_with_splits": float(si.iloc[0]) if len(si) else None, "split_issuance_without": float(si_raw.iloc[0]) if len(si_raw) else None,
                      "insider_signals_tested": sorted({t["signal"] for t in o["tests"] if t["family"] == "insiders"})},
           "design": {"companies": 160, "months": "2008-12 to 2020-12, daily prices", "edge_ic": "about 0.04", "factors": "market, plus an industry-like factor with a persistent loading per company"}}
    nf = sum(t["pass_bh"] for t in noise)
    out["findings"] = [f"On a synthetic universe of 160 companies in the SEC's own data layouts, with factor structure, random insider trades and one planted edge "
                       f"(gross profitability, a rank IC about 0.04), the engine found it: mean rank IC {_f(gp.get('mean_ic'))}, p {_f(gp.get('p'), 3)}, "
                       f"{'supported on every check' if gp.get('supported') else 'not supported on every check'}, long-short Sharpe {_f(out['planted']['sharpe'], 2)}; "
                       f"{nf} of {len(noise)} noise tests passed; {_f((o['fakes'].get('share_p_below_05') or 0) * 100, 0)}% of {o['fakes']['signals']} random signals had "
                       f"p below 0.05" + (f", and on the factor tilts the reassignment permutation gave {_f((tilt.get('share_reassign_p_below_05') or 0) * 100, 0)}% "
                       f"against {_f((tilt.get('share_p_below_05') or 0) * 100, 0)}% for the test used" if tilt.get("share_reassign_p_below_05") is not None else "") + "."]
    return _clean(out)


# ---------------------------------------------------------------- network orchestration (laptop or the daily job)
def slim_facts(f: dict) -> dict:
    """A company-facts JSON kept to the concepts and fields the engine reads (a full one is several megabytes)."""
    keep = {"us-gaap": {n for v in CONCEPTS.values() for n in v} | {n for t, n in SHARES if t == "us-gaap"}, "dei": {n for t, n in SHARES if t == "dei"}}
    cols = ("start", "end", "val", "filed", "form", "accn")
    out: dict = {"facts": {}}
    for tax, names in keep.items():
        for n in names:
            u = ((f.get("facts") or {}).get(tax) or {}).get(n)
            if not u:
                continue
            out["facts"].setdefault(tax, {})[n] = {"units": {k: [{c: r[c] for c in cols if c in r} for r in rows if r.get("form") in FORMS]
                                                             for k, rows in (u.get("units") or {}).items()}}
    return out


def yahoo_with_splits(ticker: str, years: int = 20) -> tuple[pd.DataFrame, list]:
    """Daily bars from Yahoo's chart API: `close` adjusted for splits and dividends (for returns), `split_close`
    adjusted for splits only (for market values), and the split events [(date, new shares per old)]."""
    import datetime as dt
    from . import datahub
    from .data import http
    p2 = int(time.time())
    p1 = p2 - int(years * 365.25 * 86400)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit&includeAdjustedClose=true"
    js = json.loads(http.get(url, user_agent="Mozilla/5.0 (buildout research)", retries=2))
    df = datahub.parse_yahoo(js)
    r = js["chart"]["result"][0]
    raw = pd.Series([c for c in r["indicators"]["quote"][0]["close"]],
                    index=[pd.Timestamp(dt.datetime.fromtimestamp(t, dt.timezone.utc).date()) for t in r["timestamp"]], dtype=float)
    raw = raw[~raw.index.duplicated(keep="last")]
    df["split_close"] = raw.reindex(df.index)
    sp = []
    for e in ((r.get("events") or {}).get("splits") or {}).values():
        try:
            sp.append((pd.Timestamp(dt.datetime.fromtimestamp(int(e["date"]), dt.timezone.utc).date()), float(e["numerator"]) / float(e["denominator"])))
        except (KeyError, ValueError, ZeroDivisionError):
            continue
    return df, sorted(sp)


def collect(ua: str, cache: str | Path = ".cache/filings", start_q: str = "2006q1", price_order: list[str] | None = None, years: int = 20,
            limit: int | None = None, text: bool = False) -> dict:
    """Download everything (cached on disk): membership, the SEC's ticker list, insider data sets (kept to the
    index's companies quarter by quarter), company facts for every member from 2007, and daily prices by each
    company's current ticker. Prices come from Yahoo (with split events), then Stooq; Databento is not used here,
    because its split table covers only the book's names. Returns the inputs of build()."""
    from . import datahub
    from .data import http
    cache = Path(cache)
    price_order = price_order or ["yahoo", "stooq"]
    members = parse_constituents(http.get(CONSTITUENTS_URL, timeout=120).decode())
    tickers = sorted(members["ticker"].unique())
    if limit:
        tickers = tickers[:limit]
        members = members[members["ticker"].isin(tickers)]
    norm = lambda t: t.upper().replace(".", "-")
    cur = json.loads(sec_get(TICKERS_URL, ua, cache, max_age_days=7))
    cik_cur = {norm(v["ticker"]): int(v["cik_str"]) for v in cur.values()}
    cur_of: dict = {}
    for v in cur.values():                                  # each company's current ticker (the first listed is its main class)
        cur_of.setdefault(int(v["cik_str"]), norm(v["ticker"]))
    syms = set(tickers) | {norm(t) for t in tickers}
    tx_all, failed_q = insider_download(ua, start_q, None, cache, ciks={cik_cur[norm(t)] for t in tickers if norm(t) in cik_cur}, symbols=syms)
    cik_of: dict = {}
    if not tx_all.empty:                                   # the symbols insiders reported at the time, by year
        yr = tx_all["filed"].dt.year
        for (sym, y), g in tx_all.groupby([tx_all["symbol"], yr]):
            cik_of[(sym, int(y))] = int(g["issuer_cik"].mode().iloc[0])
            if "-" in sym:
                cik_of[(sym.replace("-", "."), int(y))] = int(g["issuer_cik"].mode().iloc[0])
    for t in tickers:
        if norm(t) in cik_cur:
            cik_of.setdefault(t, cik_cur[norm(t)])
    for t, c in cik_cur.items():
        cik_of.setdefault(t, c)
    mm = members[members["month"] >= pd.Timestamp(START) - pd.DateOffset(years=2)]
    mm = mm.assign(cik=[cik_of.get((t, m.year)) or cik_of.get(t) for t, m in zip(mm["ticker"], mm["month"])]).dropna(subset=["cik"])
    ciks = set(mm["cik"].astype(int))
    tx = tx_all[tx_all["issuer_cik"].isin(ciks)] if not tx_all.empty else tx_all
    del tx_all
    facts, failed_f = {}, {}
    for c in sorted(ciks):
        try:
            facts[c] = slim_facts(json.loads(sec_get(FACTS_URL.format(cik=int(c)), ua, cache, max_age_days=7)))
        except Exception as exc:
            failed_f[int(c)] = f"{type(exc).__name__}: {exc}"[:120]
    # prices by company: its current ticker where the SEC lists one, else the ticker it had in the index
    tick_of_cik = mm.groupby("cik")["ticker"].agg(lambda x: x.mode().iloc[0]).astype(str).to_dict()
    px, splits, failed_p, src = {}, {}, {}, {}
    by_cik: dict = {}
    for c in sorted(ciks):
        sym = cur_of.get(int(c)) or norm(tick_of_cik[c])
        df, s_, sp = pd.DataFrame(), "none", []
        for name in price_order:
            try:
                if name == "yahoo":
                    df, sp = yahoo_with_splits(sym, years)
                else:
                    df, _, _ = datahub.ohlcv(sym, years, [name])
                if len(df) >= 250:
                    s_ = name
                    break
            except Exception as exc:  # noqa: BLE001
                failed_p.setdefault(int(c), {})[name] = f"{type(exc).__name__}: {str(exc)[:100]}"
                df = pd.DataFrame()
        if s_ == "none":
            continue
        by_cik[int(c)] = df
        src[int(c)] = s_
        if sp:
            splits[int(c)] = sp
    for t in tickers:                                      # every ticker a company had in the index points to its prices
        cs = {cik_of.get((t, y)) for y in range(1996, pd.Timestamp.now().year + 1)} | {cik_of.get(t)}
        cs = [c for c in cs if c in by_cik]
        if cs:
            px[t] = by_cik[cs[0]]
    ticker_of = {}
    for c, t in tick_of_cik.items():
        if t in px:
            ticker_of[int(c)] = t
    T = []
    if text:                                               # opt in: the 10-Ks themselves, several gigabytes
        for c in sorted(ciks):
            try:
                T.append(text_signals(int(c), ua, cache))
            except Exception:
                continue
    return {"members": members, "cik_of": cik_of, "ticker_of": ticker_of, "tx": tx, "facts": facts, "px": px, "splits": splits,
            "text": pd.concat(T, ignore_index=True) if T else None,
            "meta": {"failed_quarters": failed_q, "failed_facts": len(failed_f), "failed_prices": len(failed_p), "price_order": price_order,
                     "price_sources": pd.Series(src, dtype=object).value_counts().to_dict() if src else {}, "companies_with_splits": len(splits)}}
