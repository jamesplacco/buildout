"""v0.42.2: the first Databento report that reached the page (Nov 10, 2026) flagged 10 of 12 names. Two causes, both
rebuilt here from a fake vendor feed:
  1. Reused tickers. SPCX was Tuttle's SPAC ETF until April 6, 2026 and META was Roundhill's metaverse ETF until
     January 28, 2022; a pull by ticker returned those funds' prices as SpaceX's and Meta's history.
  2. The UTC day. Databento's daily bars are cut at midnight UTC and exist only for names that traded, so winter
     Friday evenings became Saturday bars for the busiest names and gaps for the rest."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from buildout.data import corporate_actions as CA
from buildout.data.databento_source import DatabentoSource, session_filter
from buildout.data.quality import gap_runs, screen

SYMS = ["QQQ", "MSFT", "META", "SPCX", "IEF", "ORCL"]


def _feed() -> pd.DataFrame:
    """What the vendor returns by ticker, 2021-01-04 to 2026-11-09."""
    rng = np.random.default_rng(7)
    days = pd.bdate_range("2021-01-04", "2026-11-09")
    rows = []

    def add(sym, idx, p0, vol, sd=0.012):
        px = p0 * np.cumprod(1 + rng.normal(0.0003, sd, len(idx)))
        rows.extend({"date": d, "symbol": sym, "open": p, "high": p, "low": p, "close": p, "volume": vol} for d, p in zip(idx, px))

    for sym, p0 in (("QQQ", 310.0), ("MSFT", 220.0), ("IEF", 118.0), ("ORCL", 63.0)):
        add(sym, days, p0, 5_000_000, 0.004 if sym == "IEF" else 0.012)
    add("FB", days[days < "2022-06-09"], 270.0, 20_000_000)                                  # Meta Platforms as FB
    add("META", days[(days >= "2021-06-30") & (days <= "2022-01-28")], 15.0, 300_000, 0.01)  # the Roundhill ETF
    add("META", days[days >= "2022-06-09"], 184.0, 20_000_000)                               # Meta Platforms
    add("SPCX", days[days <= "2026-04-06"], 25.0, 20_000, 0.002)                             # Tuttle's SPAC ETF
    add("SPCX", days[days >= "2026-06-12"], 95.0, 60_000_000, 0.03)                          # SpaceX
    # winter Fridays: the 7 to 8 pm New York hour lands on Saturday UTC, for the names that traded in it
    for fri in days[(days.dayofweek == 4) & (days.month.isin([11, 12, 1, 2]))]:
        for sym, p in (("QQQ", 400.0), ("MSFT", 300.0)):
            rows.append({"date": fri + pd.Timedelta(days=1), "symbol": sym, "open": p, "high": p, "low": p, "close": p, "volume": 900})
    # the evening before Thanksgiving 2024 lands on the holiday (a Thursday)
    rows.append({"date": pd.Timestamp("2024-11-28"), "symbol": "QQQ", "open": 505.0, "high": 505.0, "low": 505.0, "close": 505.0, "volume": 1200})
    f = pd.DataFrame(rows)
    return f[~((f["date"] == "2024-11-28") & (f["volume"] > 5000))]                          # no session on the holiday itself


def _source(feed: pd.DataFrame, fb_ok: bool = True) -> DatabentoSource:
    src = DatabentoSource.__new__(DatabentoSource)

    def raw(symbols, start, end=None):
        if "FB" in symbols and not fb_ok:
            raise PermissionError("422 symbology: FB did not resolve")
        out = feed[feed["symbol"].isin(symbols) & (feed["date"] >= pd.Timestamp(start))]
        return out[out["date"] < pd.Timestamp(end)] if end else out

    src.raw_daily_bars = raw
    src.adjustment_factors = lambda symbols, start, end=None: (_ for _ in ()).throw(PermissionError("403"))
    return src


def test_the_fake_feed_reproduces_what_the_report_showed():
    raw = _feed()
    naive = raw[raw["symbol"].isin(SYMS)].pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    q = screen(naive)["symbols"]
    assert q["QQQ"]["gaps"] == 0 and q["IEF"]["gaps"] > 60 and q["ORCL"]["gaps"] == q["IEF"]["gaps"]      # the Saturday slivers
    assert q["META"]["gaps"] > 90 and q["SPCX"]["gaps"] > 45                                              # the months between two owners of a ticker
    assert q["META"]["gap_runs"][0]["from"] == "2022-01-29" and q["META"]["gap_runs"][0]["to"] == "2022-06-08"      # from the Saturday sliver after the ETF's last day


def test_cleaned_closes_have_one_company_per_ticker_and_no_gaps():
    src = _source(_feed())
    c = src.adjusted_closes(SYMS, "2021-01-04", adjustments="auto")
    assert (c.index.dayofweek < 5).all() and pd.Timestamp("2024-11-28") not in c.index
    assert c["SPCX"].first_valid_index() == pd.Timestamp("2026-06-12")                 # SpaceX's own history only
    assert c["META"].first_valid_index() == pd.Timestamp("2021-01-04")                 # FB joined on
    assert c["META"].loc["2021-07-01":"2022-01-28"].min() > 100                        # the $15 ETF is gone
    q = screen(c)
    assert q["flagged"] == 0, {k: v for k, v in q["symbols"].items() if not v["ok"]}
    cl = src.cleaning
    assert cl["ticker_since"]["SPCX"]["rows_dropped"] > 1000 and cl["ticker_since"]["META"]["dropped_from"] == "2021-06-30"
    assert cl["former_ticker"]["META"]["from"] == "FB" and cl["former_ticker"]["META"]["rows"] > 300
    assert cl["non_session_dates_dropped"]["count"] > 60 and cl["non_session_dates_dropped"]["weekend"] == cl["non_session_dates_dropped"]["count"] - 1
    assert "not the exchange's official" in cl["price_basis"]


def test_without_the_former_ticker_meta_starts_at_its_own_listing_and_says_so():
    src = _source(_feed(), fb_ok=False)
    c = src.adjusted_closes(SYMS, "2021-01-04", adjustments="auto")
    assert c["META"].first_valid_index() == pd.Timestamp("2022-06-09")
    assert "FB did not resolve" in src.cleaning["former_ticker"]["META"]["error"]
    assert screen(c)["flagged"] == 0


def test_session_filter_keeps_half_days_and_drops_slivers():
    d = pd.bdate_range("2025-01-02", "2025-03-31")
    bars = pd.DataFrame([{"date": t, "symbol": s, "close": 10.0, "volume": 1_000_000} for t in d for s in ("A", "B", "C")])
    bars.loc[bars["date"] == d[20], "volume"] = 450_000                               # a half day
    bars.loc[bars["date"] == d[30], "volume"] = 5_000                                 # a sliver on a weekday
    kept, dropped = session_filter(bars)
    assert dropped == [d[30].strftime("%Y-%m-%d")] and d[20] in set(kept["date"])
    no_vol = bars.drop(columns="volume")
    assert session_filter(no_vol)[1] == []


def test_a_market_wide_bounce_is_not_a_bad_print_but_a_lone_one_is():
    rng = np.random.default_rng(3)
    d = pd.bdate_range("2020-01-02", periods=300)
    r = pd.DataFrame(rng.normal(0, 0.01, (300, 5)), index=d, columns=list("ABCDE"))
    r.iloc[50] = -0.095                                   # the whole market falls, then bounces
    r.iloc[51] = 0.093
    r.iloc[200, 0], r.iloc[201, 0] = 0.30, -0.23           # one name's bad print
    s = screen(100 * (1 + r).cumprod())["symbols"]
    assert s["A"]["spikes"] == [d[200].strftime("%Y-%m-%d")] and all(s[c]["ok"] for c in "BCDE")


def test_gap_runs_lists_the_longest_first():
    m = pd.Series([False, True, True, False, True, False, True, True, True], index=pd.bdate_range("2026-01-05", periods=9))
    g = gap_runs(m)
    assert [x["days"] for x in g] == [3, 2, 1] and g[0]["from"] == "2026-01-13" and g[0]["to"] == "2026-01-15"


def test_ticker_tables_are_consistent():
    for sym, (old, until) in CA.FORMER_TICKER.items():
        assert CA.TICKER_SINCE[sym] == until and old not in CA.TICKER_SINCE
    assert CA.TICKER_SINCE["SPCX"] == "2026-06-12"
