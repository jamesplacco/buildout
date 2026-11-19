"""v0.47, data and operations: what the audit of Nov 18, 2026 found, each as a test that fails on the old behaviour.

  fundamentals   a balance-sheet figure is this quarter's or None, never a tag last filed years ago
  macro          the yield curve carries the date its yields were published
  retries        a vendor's gateway timeout is retried; the futures definitions are pulled in windows
  split guard    a 2-for-1 on an up day and a 3-for-2 no longer pass; the technicals path is guarded too
  fallback       a name that came from another source than the configured one is said, and fails a check
  status         session-aware freshness, the call's own files, warnings apart from failures, no rounding false alarm
  quality        an extreme move on the newest day is reported as unconfirmed; a dropped final bar is said
  the mirror     stale against the clock, a name behind the others, a jump, a second source that disagrees
  cli            a failed engine exits non-zero; the decision engine reads the run's own 10-year yield
  files          no temporary file or last-good copy is published; the manifest dates files by their data
  workflows      the commit step cannot leave conflict markers; a failed check turns the run red; the alert closes
No test here touches the network: every source is a fake.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from buildout import book as bk
from buildout import datahub, fundamentals as fu, macro, status
from buildout.data import corporate_actions as ca
from buildout.data import http, quality
from buildout.data import databento_source as dbs

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"


# ---------------------------------------------------------------- 1. fundamentals: dated balance sheets
def _flows(concept: str, ends: list[str], vals: list[float]) -> dict:
    rows = []
    for e, v in zip(ends, vals):
        e = pd.Timestamp(e)
        rows.append({"start": (e - pd.DateOffset(months=3) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), "end": e.strftime("%Y-%m-%d"),
                     "val": v * 1e9, "form": "10-Q", "filed": (e + pd.Timedelta(days=30)).strftime("%Y-%m-%d")})
    return {concept: rows}


def _inst(concept: str, pairs: list[tuple[str, float]]) -> dict:
    return {concept: [{"end": e, "val": v * 1e9, "form": "10-Q", "filed": (pd.Timestamp(e) + pd.Timedelta(days=30)).strftime("%Y-%m-%d")} for e, v in pairs]}


QE = ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]


def _company(**instants) -> dict:
    u = {**_flows("PaymentsToAcquirePropertyPlantAndEquipment", QE, [35.1, 39.5, 44.2, 54.2, 77.3]),
         **_flows("NetCashProvidedByUsedInOperatingActivities", QE, [35.5, 54.5, 26.0, 45.4, 42.4])}
    for k, v in instants.items():
        u.update(_inst(k, v))
    return u


def test_a_tag_last_filed_years_ago_is_not_this_quarters_cash():
    # the shapes of site/data/capex.json on Nov 18, 2026: Amazon's combined cash line ends in 2017 (21.531), its
    # cash-and-equivalents line is current (55.783), and its backlog tag ends in 2020 (41.0)
    amzn = _company(CashCashEquivalentsAndShortTermInvestments=[("2016-12-31", 25.98), ("2017-03-31", 21.531)],
                    CashAndCashEquivalentsAtCarryingValue=[("2026-06-30", 78.213), ("2026-09-30", 55.783)],
                    MarketableSecuritiesCurrent=[("2026-06-30", 44.775), ("2026-09-30", 30.0)],
                    LongTermDebt=[("2025-09-30", 50.7), ("2026-06-30", 128.9), ("2026-09-30", 180.887)],
                    RevenueRemainingPerformanceObligation=[("2020-06-30", 41.0)])
    m = fu.analyze_company(amzn)
    assert m["quarter_end"] == "2026-09-30"
    assert m["cash"] == pytest.approx(55.783 + 30.0) and m["cash_date"] == "2026-09-30"
    assert m["cash_basis"] == "cash and equivalents plus marketable securities"
    assert m["net_cash"] == pytest.approx(85.783 - 180.887)                 # was 21.531 - 180.887 = -159.4
    assert m["rpo"] is None and m["rpo_date"] is None and m["rpo_years"] is None
    assert m["stale"] == {"rpo": {"value": 41.0, "date": "2020-06-30"}}      # kept, dated, and used for nothing
    assert m["debt_yoy"] == pytest.approx(180.887 / 50.7 - 1)               # a year before this quarter, not before the last filing


def test_debt_not_filed_for_the_quarter_is_none_not_an_old_zero():
    # Oracle: long-term debt 0.0 dated 2022-05-31 gave net cash +37 against a true -89. CoreWeave: debt one quarter old.
    orcl = _company(CashAndCashEquivalentsAtCarryingValue=[("2026-09-30", 36.369)], LongTermDebt=[("2022-05-31", 0.0)])
    m = fu.analyze_company(orcl)
    assert m["debt"] is None and m["debt_date"] is None and m["net_cash"] is None
    assert m["cash"] == pytest.approx(36.369) and m["cash_basis"] == "cash and equivalents only"
    assert m["stale"]["debt"] == {"value": 0.0, "date": "2022-05-31"}
    crwv = _company(LongTermDebtNoncurrent=[("2026-03-31", 24.859)])
    m = fu.analyze_company(crwv)
    assert m["debt"] is None and m["stale"]["debt"]["date"] == "2026-03-31" and m["cash"] is None
    # a supplement fills what the filings do not carry, as before
    assert fu.analyze_company(crwv, {"debt": 35.068, "debt_date": "2026-06-30"})["debt"] == 35.068
    # fiscal calendars drift by a few days: a balance sheet dated within ten days of the quarter end is the quarter's
    v, d = fu.instant_at(pd.Series({pd.Timestamp("2026-09-27"): 5e9}), pd.Timestamp("2026-09-30"))
    assert (v, d) == (5.0, "2026-09-27")
    assert fu.instant_at(pd.Series({pd.Timestamp("2026-06-30"): 5e9}), pd.Timestamp("2026-09-30")) == (None, None)


def test_capex_json_is_dated_by_its_data(tmp_path, monkeypatch, capsys):
    from buildout import cli
    from buildout.data import edgar_source
    fix = fu.parse_fixture(ROOT / "tests" / "fixtures" / "sec_facts_2026q3.txt")
    facts = {"facts": {"us-gaap": {k: {"units": {"USD": rows}} for k, rows in fix["MSFT"].items()}}}
    monkeypatch.setattr(edgar_source.EdgarSource, "facts", lambda self, t: facts)
    cli.main(["capex", "MSFT", "--ua", "Test Person test@example.com", "--json", str(tmp_path / "capex.json")])
    capsys.readouterr()
    o = json.loads((tmp_path / "capex.json").read_text())
    assert o["as_of"] == "2026-06-30" and o["generated_utc"].endswith("Z") and o["generated_utc"][:4] >= "2026"
    assert o["ttm"]["MSFT"]["cash_date"] == "2026-06-30" and o["ttm"]["MSFT"]["stale"] == {}


# ---------------------------------------------------------------- 2. the curve's date
def test_the_curve_is_dated_by_its_yields_not_by_a_series_posted_ahead():
    d = pd.bdate_range("2024-11-01", "2026-11-16")
    fred = pd.DataFrame({c: np.linspace(4.0, 5.0, len(d)) + i * 0.05 for i, (_, c, _) in enumerate(macro.CURVE)}, index=d)
    ahead = pd.DatetimeIndex(["2026-11-17", "2026-11-18"])                 # IORB is posted for days the curve has not printed
    fred = pd.concat([fred, pd.DataFrame({"IORB": [4.4, 4.4]}, index=ahead)]).sort_index()
    fred.loc[pd.Timestamp("2025-11-15"), "IORB"] = 4.4                     # a Saturday row of another series a year back
    r = macro.rates_block(fred.sort_index())
    assert r["curves"]["latest"]["date"] == "2026-11-16"                   # was 2026-11-18
    assert r["curves"]["latest"]["points"][8]["yield"] == pytest.approx(float(fred["DGS10"].dropna().iloc[-1]))
    assert r["curves"]["year_ago"]["date"] == "2025-11-14"                 # a day the 10-year printed, not the Saturday
    assert pd.Timestamp(r["curves"]["start_of_year"]["date"]) in d


# ---------------------------------------------------------------- 3. retries
class Gateway(Exception):
    def __init__(self, status):
        super().__init__(f"{status} The remote gateway timed out.")
        self.http_status = status


def test_transient_failures_are_retried_and_refusals_are_not():
    naps, calls = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise Gateway(504)
        return "bars"
    assert http.with_retries(flaky, tries=3, backoff=2.0, sleep=naps.append) == "bars" and len(calls) == 3 and naps == [2.0, 4.0]
    calls.clear()

    def refused():
        calls.append(1)
        raise Gateway(403)
    with pytest.raises(Gateway):
        http.with_retries(refused, tries=3, sleep=naps.append)
    assert len(calls) == 1                                                  # a missing licence is not retried
    calls.clear()
    with pytest.raises(Gateway):
        http.with_retries(lambda: (calls.append(1), (_ for _ in ()).throw(Gateway(504)))[1], tries=3, backoff=0.0, sleep=lambda s: None)
    assert len(calls) == 3                                                  # the last failure is raised, unchanged
    assert http.is_transient(TimeoutError()) and http.is_transient(ConnectionResetError()) and not http.is_transient(ValueError("bad symbol"))
    assert http.is_transient(Gateway(429)) and not http.is_transient(Gateway(422))


class _Store:
    def __init__(self, df):
        self.df = df

    def to_df(self):
        return self.df


def _bars(dates, symbols=("AAA", "BBB", "CCC"), last_volume=1.0):
    rows = []
    for i, d in enumerate(dates):
        for j, s in enumerate(symbols):
            rows.append({"ts_event": pd.Timestamp(d, tz="UTC"), "symbol": s, "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0 + 0.01 * i + j,
                         "volume": 1e6 * (last_volume if i == len(dates) - 1 else 1.0)})
    return pd.DataFrame(rows).set_index("ts_event")


def _source(frames_or_errors):
    """A DatabentoSource with a fake client: each get_range call takes the next item (a frame to return, an error to raise)."""
    src = dbs.DatabentoSource.__new__(dbs.DatabentoSource)
    queue, seen = list(frames_or_errors), []

    class TS:
        def get_range(self, **kw):
            seen.append(kw)
            x = queue.pop(0)
            if isinstance(x, Exception):
                raise x
            return _Store(x)

    class Hist:
        timeseries = TS()
    src.hist, src.cache, src.equities_dataset, src.futures_dataset = Hist(), None, "XNAS.ITCH", "GLBX.MDP3"
    src._sleep = lambda s: None
    src.resolve_end = lambda ds, end, schema="ohlcv-1d": "2026-11-18T00:00:00"
    return src, seen


def test_a_gateway_timeout_on_the_bars_is_retried_and_recorded():
    dates = pd.bdate_range("2026-09-01", "2026-11-17")
    src, seen = _source([Gateway(504), _bars(dates)])
    bars = src.daily_bars(["AAA", "BBB", "CCC"], "2026-09-01")
    assert len(seen) == 2 and bars["date"].max() == dates[-1]
    assert src.cleaning["retries"] and "504" in src.cleaning["retries"][0] and src.cleaning["final_bar_dropped"] is None
    src, seen = _source([Gateway(403)])
    with pytest.raises(Gateway):
        src.raw_daily_bars(["AAA"], "2026-09-01")
    assert len(seen) == 1


def test_futures_definitions_are_pulled_in_windows_each_retried():
    from buildout import futures as fut
    seen, fail_once = [], {"2012-06-06"}

    class TS:
        def get_range(self, **kw):
            seen.append((kw["schema"], kw["start"], kw["end"]))
            if kw["start"] in fail_once:
                fail_once.discard(kw["start"])
                raise Gateway(504)
            return _Store(pd.DataFrame({"ts_event": [pd.Timestamp(kw["start"], tz="UTC")], "x": [kw["start"]]}).set_index("ts_event"))

    class Client:
        timeseries = TS()
    retried: list[str] = []
    df = fut.range_in_windows(Client(), "definition", ["ZN.v.0"], "2010-06-06", "2015-01-01", years=2, sleep=lambda s: None, retried=retried)
    spans = [(a, b) for _, a, b in seen]
    assert spans == [("2010-06-06", "2012-06-06"), ("2012-06-06", "2014-06-06"), ("2012-06-06", "2014-06-06"), ("2014-06-06", "2015-01-01")]
    assert list(df["x"]) == ["2010-06-06", "2012-06-06", "2014-06-06"]      # contiguous, half-open, nothing twice
    assert len(retried) == 1 and "definition from 2012-06-06" in retried[0] and "504" in retried[0]


# ---------------------------------------------------------------- 4. the split guard
def _path(n=40, seed=0):
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, n)), index=pd.bdate_range("2026-09-01", periods=n))


def test_split_sized_moves_are_caught_and_genuine_ones_pass():
    s = _path()
    k = s.index[20]

    def moved(ratio):
        x = s.copy()
        x.loc[k:] *= ratio
        return pd.DataFrame({"META": x})
    assert ca.unexplained_jumps(moved(0.5 * 1.12))["META"][0]["looks_like"] == "2:1"      # -44%: passed the old 45% line
    assert ca.unexplained_jumps(moved(1 / 1.5))["META"][0]["looks_like"] == "3:2"         # -33%: passed it by a mile
    assert ca.unexplained_jumps(moved(2.0))["META"][0]["change"] == pytest.approx(1.0, abs=0.1)      # a 1-for-2 reverse split
    assert not ca.unexplained_jumps(moved(1 - 0.264))                                     # Meta, Feb 3, 2022: a real day
    assert not ca.unexplained_jumps(moved(1.359))                                         # Oracle, Sep 10, 2025: a real day
    bad = ca.unexplained_jumps(moved(0.5))
    assert bad["META"][0]["date"] == k.strftime("%Y-%m-%d")
    msg = ca.jump_message(bad)
    assert "META" in msg and "2:1" in msg and "CONFIRMED_MOVES" in msg and "Pending" in msg      # Meta's announced split is named
    assert not ca.unexplained_jumps(moved(0.5), confirmed={"META": (k.strftime("%Y-%m-%d"),)})      # a move checked by hand passes


def test_the_technicals_path_has_the_guard_too(monkeypatch):
    dates = pd.bdate_range("2026-06-01", "2026-11-17")
    raw = _bars(dates, symbols=("META", "QQQ")).reset_index()
    raw["date"] = pd.to_datetime(raw["ts_event"]).dt.tz_convert(None).dt.normalize()
    raw.loc[(raw["symbol"] == "META") & (raw["date"] >= dates[60]), ["open", "high", "low", "close"]] /= 2.0       # an unadjusted 2-for-1

    class Fake:
        def __init__(self, **kw):
            class Meta:
                def get_dataset_range(self, dataset):
                    return {"start": "2018-05-01", "end": "2026-11-18"}

            class Hist:
                metadata = Meta()
            self.hist = Hist()

        def equities_dataset_for(self, start):
            return "XNAS.ITCH"

        def estimate_cost(self, *a, **k):
            return 0.01

        def daily_bars(self, tickers, start):
            return raw[["date", "symbol", "open", "high", "low", "close", "volume"]]
    monkeypatch.setattr(dbs, "DatabentoSource", Fake)
    with pytest.raises(ValueError, match=r"META: .* -5\d% \(a 2:1 split\?\)"):
        datahub.databento(["META", "QQQ"], "2026-06-01")
    raw.loc[(raw["symbol"] == "META") & (raw["date"] >= dates[60]), ["open", "high", "low", "close"]] *= 2.0
    assert set(datahub.databento(["META", "QQQ"], "2026-06-01")) == {"META", "QQQ"}


# ---------------------------------------------------------------- 5. a fallback is said, and fails a check
def _ohlc(n, end="2026-11-17"):
    d = pd.bdate_range(end=end, periods=n)
    c = np.linspace(100, 120, n)
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1e6}, index=d)


def test_names_from_another_source_are_flagged_and_fail_the_status_check(tmp_path, monkeypatch):
    from buildout import technicals
    monkeypatch.setenv("DATABENTO_API_KEY", "db-test")
    monkeypatch.setattr(datahub, "databento", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("504 The remote gateway timed out.")))
    monkeypatch.setattr(datahub, "yahoo", lambda t, years=10: _ohlc(110 if t == "SPCX" else 300))
    monkeypatch.setattr(datahub, "stooq", lambda t: pd.DataFrame())
    monkeypatch.setattr(technicals, "analyze", lambda df, t, b=None: {"date": df.index[-1].strftime("%Y-%m-%d"), "readings": {"close": float(df["close"].iloc[-1])}})
    monkeypatch.setattr(technicals, "text", lambda a: [])
    r = datahub.market(tmp_path, ["MSFT", "SPCX"], bench="QQQ", fundamentals=False)
    t = json.loads((tmp_path / "technicals.json").read_text())
    assert t["configured_source"] == "databento" and t["fallback"] is True and t["fallback_names"] == ["MSFT", "QQQ (benchmark)"]
    assert t["sources"]["MSFT"]["source"] == "yahoo" and t["sources"]["MSFT"]["fallback"] is True and "504" in t["batch_error"]
    assert t["short_history"] == ["SPCX"] and t["missing"] == [] and t["sources"]["SPCX"]["fallback"] is False      # a new listing is not a failure
    assert t["as_of"] == "2026-11-17" and t["generated_utc"].endswith("Z")                  # the data's date, and the run's time apart
    assert r["fallback"] is True
    st = status.build_status(tmp_path, now=datetime(2026, 11, 18, 19, 35, tzinfo=timezone.utc))
    c = {x["name"]: x for x in st["checks"]}["Technical analysis used the configured price source"]
    assert c["ok"] is False and c["level"] == "fail" and "MSFT" in c["detail"] and "504" in c["detail"] and st["ok"] is False
    # the configured source answering leaves nothing to say
    monkeypatch.setattr(datahub, "databento", lambda tickers, start, **k: {x: _ohlc(300) for x in tickers})
    datahub.market(tmp_path, ["MSFT"], bench="QQQ", fundamentals=False)
    t = json.loads((tmp_path / "technicals.json").read_text())
    assert t["fallback"] is False and t["fallback_names"] == [] and t["sources"]["MSFT"]["source"] == "databento"
    assert datahub.source_flags("none", {"databento": "RuntimeError: x", "yahoo": "HTTPError", "stooq": "only 0 bars"}, "databento")["missing"] is True


def test_stooq_answering_with_a_browser_page_is_not_reachable(monkeypatch):
    monkeypatch.setattr(http, "get", lambda url, **k: b"<!DOCTYPE html><html><body>challenge</body></html>" if "stooq" in url else b"Date,Open\n2026-11-17,1\n")
    rows = {r["source"]: r for r in datahub.check()}
    assert rows["stooq"]["reachable"] is False and rows["stooq"]["ok"] is False and "not with data" in rows["stooq"]["note"]
    assert rows["yahoo"]["reachable"] is True
    df = _ohlc(5, end="2026-11-18")                                         # a CSV bar dated today, before the close, is not a close
    mid = datetime(2026, 11, 18, 19, 30, tzinfo=timezone.utc)
    assert len(datahub.drop_open_session(df, now=mid)) == 4 and len(datahub.drop_open_session(df, now=datetime(2026, 11, 18, 21, 30, tzinfo=timezone.utc))) == 5


def test_recent_closes_are_quoted_not_dividend_adjusted_and_never_raise(monkeypatch):
    t0 = int(datetime(2026, 11, 16, 14, 30, tzinfo=timezone.utc).timestamp())
    js = {"chart": {"result": [{"timestamp": [t0, t0 + 86_400], "meta": {},
                                "indicators": {"quote": [{"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [100.0, 101.0], "volume": [10, 20]}],
                                               "adjclose": [{"adjclose": [99.0, 101.0]}]}}]}}
    monkeypatch.setattr(http, "get", lambda url, **k: json.dumps(js).encode() if "yahoo" in url else b"<html>")
    s, src, errs = datahub.recent_closes("MSFT", 5, order=("stooq", "yahoo"))
    assert src == "yahoo" and list(s) == [100.0, 101.0] and errs == {"stooq": "no bars"}      # 100, not the adjusted 99
    monkeypatch.setattr(http, "get", lambda url, **k: (_ for _ in ()).throw(RuntimeError("down")))
    s, src, errs = datahub.recent_closes("MSFT", 5)
    assert s.empty and src == "none" and set(errs) == {"yahoo", "stooq"}


# ---------------------------------------------------------------- 6. status
def _write(d: Path, name: str, obj: dict) -> None:
    (d / name).write_text(json.dumps(obj))


def test_sessions_behind_knows_holidays_and_the_clock():
    at = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)   # noqa: E731
    assert status.sessions_behind("2026-11-17", at("2026-11-18T19:35")) == 0          # yesterday's close, mid-session
    assert status.sessions_behind("2026-11-16", at("2026-11-18T19:35")) == 1
    assert status.sessions_behind("2026-11-25", at("2026-11-27T19:00")) == 0          # the Friday after Thanksgiving: Wednesday is the last close
    assert status.sessions_behind("2026-11-20", at("2026-11-21T17:00")) == 0          # a Saturday run on Friday's close
    assert status.sessions_behind("2026-11-13", at("2026-11-17T01:00")) == 0          # 1 am UTC Tuesday is still Monday in New York
    assert status.sessions_behind("2026-09", at("2026-11-18T19:35")) is None and status.sessions_behind(None, at("2026-11-18T19:35")) is None


def test_the_posterior_check_tolerates_the_writers_rounding(tmp_path):
    _write(tmp_path, "reason.json", {"posterior": {"posterior": [0.328857, 0.049182, 0.131682, 0.22783, 0.074881, 0.147639, 0.039928]},      # sums to 0.999999
                                     "alternatives": {"optimal": {"feasible": True, "port": [0, 0, 0, 0.1]}}})
    st = status.build_status(tmp_path, now=datetime(2026, 11, 18, 19, 35, tzinfo=timezone.utc))
    by = {c["name"]: c for c in st["checks"]}
    assert by["Reasoner posterior is a probability distribution"]["ok"] and st["ok"] is True and st["failed"] == 0
    _write(tmp_path, "reason.json", {"posterior": {"posterior": [0.5, 0.4]}, "alternatives": {"optimal": {"feasible": True}}})
    assert not {c["name"]: c for c in status.build_status(tmp_path)["checks"]}["Reasoner posterior is a probability distribution"]["ok"]


def _call_files(d: Path, asof="2026-11-17", ledger_asof=None, size=0.5331) -> Path:
    _write(d, "book.json", {"asof": asof, "size": size, "binding": "drawdown_cap",
                            "validation": {"ok": True, "failed": [], "notes": [], "cross_check": {"status": "ok", "detail": "10 of 10 names within 1.0% of yahoo"}}})
    led = d / "calls.jsonl"
    led.write_text(json.dumps({"seq": 1, "data_asof": "2026-11-16", "hash": "aa", "call": {"size": 0.53, "binding": "drawdown_cap"}}) + "\n"
                   + json.dumps({"seq": 2, "data_asof": ledger_asof or asof, "hash": "bb", "call": {"size": 0.5331, "binding": "drawdown_cap"}}) + "\n")
    _write(d, "live.json", {"last_mark": asof, "ledger": {"ok": True, "entries": 2, "head": "bb"}})
    _write(d, "paper.json", {"marks_asof": asof, "equity": 98262.56})
    _write(d, "decision.json", {"end": "2026-09", "now": {"exposure": 1.0, "inputs": {"notes": {"y10": {"value": 5.12, "assumed": False, "source": "FRED DGS10 (macro.json)"}}}}})
    return led


def test_the_calls_own_files_are_checked(tmp_path):
    now = datetime(2026, 11, 18, 19, 35, tzinfo=timezone.utc)
    led = _call_files(tmp_path)
    st = status.build_status(tmp_path, now=now, ledger_path=led)
    by = {c["name"]: c for c in st["checks"]}
    for name in ("The call's prices are from the last completed session", "The call's prices passed validation", "A second source agrees with the call's newest closes",
                 "The ledger's newest call is for the book's data date", "The logged call matches the book as computed now",
                 "The calls marked to market are at most 1 session behind the last completed one", "The marked record was built from the current ledger",
                 "The paper account's marks are at most 1 session behind the last completed one", "The decision package carries a decision",
                 "The decision engine read today's 10-year yield"):
        assert by[name]["ok"], name
    assert st["ok"] is True and st["failed"] == 0 and st["warnings"] == 0
    assert {"book.json", "live.json", "paper.json", "decision.json"} <= set(st["files"]) and st["files"]["book.json"]["sessions_behind"] == 0
    # a week later nothing has moved: before v0.47 no check looked at these files at all
    late = status.build_status(tmp_path, now=datetime(2026, 11, 25, 19, 35, tzinfo=timezone.utc), ledger_path=led)
    bad = {c["name"] for c in late["checks"] if not c["ok"] and c["level"] == "fail"}
    assert {"The call's prices are from the last completed session", "The calls marked to market are at most 1 session behind the last completed one",
            "The paper account's marks are at most 1 session behind the last completed one"} <= bad and late["ok"] is False
    # the book moved on and the ledger did not
    led = _call_files(tmp_path, ledger_asof="2026-11-16")
    by = {c["name"]: c for c in status.build_status(tmp_path, now=now, ledger_path=led)["checks"]}
    assert not by["The ledger's newest call is for the book's data date"]["ok"] and by["The ledger's newest call is for the book's data date"]["level"] == "fail"


def test_warnings_are_reported_apart_and_do_not_fail_the_run(tmp_path):
    now = datetime(2026, 11, 18, 19, 35, tzinfo=timezone.utc)
    led = _call_files(tmp_path)
    b = json.loads((tmp_path / "book.json").read_text())
    b["validation"]["cross_check"] = {"status": "unavailable", "detail": "no second quote"}
    b["validation"]["notes"] = ["cross-check unavailable: no second quote"]
    _write(tmp_path, "book.json", b)
    _write(tmp_path, "feeds.json", {"generated_utc": "2026-11-18T19:26:16Z", "sources": {"ok": ["a"], "failed": ["b", "c"]}, "items": []})
    st = status.build_status(tmp_path, now=now, ledger_path=led)
    warn = {c["name"] for c in st["checks"] if not c["ok"]}
    assert warn == {"A second source agrees with the call's newest closes", "Price validation raised no warnings", "Feed scraper read at least half its sources"}
    assert all(c["level"] == "warn" for c in st["checks"] if not c["ok"]) and st["ok"] is True and st["warnings"] == 3 and st["failed"] == 0
    b["validation"]["cross_check"] = {"status": "disagrees", "detail": "meta 2026-11-17: 618.87 here, 309.40 at yahoo"}
    _write(tmp_path, "book.json", b)
    st = status.build_status(tmp_path, now=now, ledger_path=led)
    c = {x["name"]: x for x in st["checks"]}["A second source agrees with the call's newest closes"]
    assert c["level"] == "fail" and st["ok"] is False


# ---------------------------------------------------------------- 7. the newest day
def test_an_extreme_move_on_the_newest_day_is_unconfirmed_not_rejected():
    rng = np.random.default_rng(1)
    d = pd.bdate_range("2025-01-02", periods=400)
    P = pd.DataFrame({s: 100 * np.cumprod(1 + rng.normal(0, 0.012, len(d))) for s in "ABCDE"}, index=d)
    assert quality.screen(P)["unconfirmed"] == []
    Q = P.copy()
    Q.iloc[-1, 0] *= 1.30                                                   # +30% on the last day: a bad print or news, unknowable today
    r = quality.screen(Q)
    assert r["unconfirmed"] == ["A"] and r["symbols"]["A"]["ok"] is True and r["symbols"]["A"]["spikes"] == []
    u = r["symbols"]["A"]["unconfirmed"]
    assert u["date"] == d[-1].strftime("%Y-%m-%d") and u["change"] > 0.25 and u["robust_sds"] > 8
    Q = P.copy()
    Q.iloc[-10, 0] *= 1.30                                                  # the same print ten days ago reversed: a spike, as before
    r = quality.screen(Q)
    assert r["symbols"]["A"]["spikes"] == [d[-10].strftime("%Y-%m-%d")] and r["unconfirmed"] == []
    Q = P * 1.0
    Q.iloc[-1] *= 0.80                                                      # the whole market down 20%: nobody's own move
    assert quality.screen(Q)["unconfirmed"] == []


def test_a_dropped_final_bar_is_said_when_the_exchange_was_open():
    dates = pd.bdate_range("2026-09-01", "2026-11-17")
    src, _ = _source([_bars(dates, last_volume=0.05)])                      # the newest day at 5% of normal volume: a partial pull
    bars = src.daily_bars(["AAA", "BBB", "CCC"], "2026-09-01")
    w = src.cleaning["final_bar_dropped"]
    assert bars["date"].max() == dates[-2] and w["date"] == "2026-11-17" and "partial" in w["note"]
    assert dbs.final_bar_warning(pd.Timestamp("2026-11-26"), ["2026-11-26"]) is None       # Thanksgiving's after-hours sliver: dropped rightly
    assert dbs.final_bar_warning(pd.Timestamp("2026-11-14"), ["2026-11-14"]) is None       # a Saturday
    assert dbs.final_bar_warning(pd.Timestamp("2026-11-17"), ["2026-11-14"]) is None       # the newest bar was kept


# ---------------------------------------------------------------- 8. the mirror
FILES = sorted({bk.FILE.get(k, k.lower()) for k in bk.BOOK} | set(bk.FACTOR_ETF.values()))
D60 = pd.bdate_range("2026-08-26", "2026-11-17")
NOW = "2026-11-18T19:35:00Z"


def _pull(tmp: Path, **changes) -> None:
    good = pd.DataFrame({"date": D60.strftime("%Y-%m-%d"), "open": 10.0, "high": 12.5, "low": 9.5, "close": np.linspace(10, 12, len(D60)), "volume": 1e6})
    for f in FILES:
        changes.get(f, good).to_csv(tmp / f"{f}.csv", index=False)


def _second(shift: dict | None = None, absent=(), source="yahoo"):
    """A second source that agrees with the fake mirror, except where told otherwise."""
    def fetch(ticker, days, order):
        f = ticker.lower()
        if f in absent:
            return pd.Series(dtype=float), "none", {"yahoo": "no bars"}
        s = pd.Series(np.linspace(10, 12, len(D60)), index=D60).tail(days) * (shift or {}).get(f, 1.0)
        return s, source, {}
    return fetch


def test_the_mirror_is_stale_against_the_clock_not_against_itself(tmp_path):
    _pull(tmp_path)
    p = bk.download(tmp_path, now=NOW)
    assert p.validation["ok"] and p.validation["asof"] == p.validation["expected_asof"] == "2026-11-17"
    assert p.validation["cross_check"]["status"] == "not_run" and "MIRROR" not in p.validation["source"] and "Yahoo" in p.validation["source"]
    # every file frozen together: the old rule (stale against the newest date in the pull) passed this for ever
    with pytest.raises(ValueError, match=r"amzn: stale: ends 2026-11-17, 4 sessions before the last completed session \(2026-11-23\)"):
        bk.download(tmp_path, now="2026-11-24T19:35:00Z")
    assert bk.LAST_VALIDATION["ok"] is False and len(bk.LAST_VALIDATION["failed"]) == len(FILES)
    # holidays are not staleness: on the Friday after Thanksgiving, Wednesday's close is current
    good = pd.read_csv(tmp_path / "msft.csv")
    wed = pd.concat([good, pd.DataFrame({"date": ["2026-11-18", "2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25"], "open": 12.0, "high": 12.5,
                                         "low": 11.5, "close": 12.0, "volume": 1e6})])
    _pull(tmp_path, **{f: wed for f in FILES})
    assert bk.download(tmp_path, now="2026-11-27T19:00:00Z").validation["ok"]
    assert bk.expected_asof("2026-11-21T17:00:00Z") == pd.Timestamp("2026-11-20")           # a Saturday run


def test_a_name_behind_the_others_and_a_jump_stop_the_call(tmp_path):
    good = pd.DataFrame({"date": D60.strftime("%Y-%m-%d"), "open": 10.0, "high": 12.5, "low": 9.5, "close": np.linspace(10, 12, len(D60)), "volume": 1e6})
    _pull(tmp_path, meta=good.iloc[:-1])                                    # one name a single session behind: three were allowed before
    with pytest.raises(ValueError, match=r"^price validation failed: meta: stale: ends 2026-11-16, 1 session before"):
        bk.download(tmp_path, now=NOW)
    ahead = pd.concat([good, pd.DataFrame({"date": ["2026-11-18"], "open": 12.0, "high": 12.5, "low": 11.5, "close": 12.0, "volume": 1e6})])
    _pull(tmp_path, **{f: ahead for f in FILES if f != "meta"})             # an evening pull: the others already have today
    with pytest.raises(ValueError, match=r"^price validation failed: meta: stale: ends 2026-11-17, behind the other names \(2026-11-18\)$"):
        bk.download(tmp_path, now=NOW)
    split = good.copy()
    split.loc[40:, ["open", "high", "low", "close"]] /= 2.0                 # a 2-for-1 the mirror did not adjust: was a warning nobody read
    _pull(tmp_path, meta=split)
    with pytest.raises(ValueError, match=r"meta: jump: 2026-\d\d-\d\d -5\d% \(a 2:1 split\?\) with no split recorded"):
        bk.download(tmp_path, now=NOW)
    day = pd.to_datetime(split["date"]).iloc[40].strftime("%Y-%m-%d")
    try:
        ca.CONFIRMED_MOVES["META"] = (day,)                                 # checked by hand: genuine
        assert bk.download(tmp_path, now=NOW).validation["ok"]
    finally:
        ca.CONFIRMED_MOVES.pop("META", None)


def test_a_second_source_that_disagrees_stops_the_call_and_one_that_is_silent_warns(tmp_path):
    _pull(tmp_path)
    p = bk.download(tmp_path, now=NOW, second_source=_second())
    cc = p.validation["cross_check"]
    assert cc["status"] == "ok" and sorted(cc["names"]) == sorted(set(FILES) - {"soxx", "vti"}) and cc["independent"] is False and "origin" in cc["note"]
    assert p.validation["warnings"] == 0 and cc["names"]["goog"]["gap"] == pytest.approx(0.0)
    assert bk.download(tmp_path, now=NOW).validation["cross_check"]["status"] == "ok"       # stored beside the cache, reused by the next call
    with pytest.raises(ValueError, match=r"meta: cross-check: the 2026-11-17 close is 12\.00 here and 12\.36 at yahoo \(-2\.91%, limit 1\.0%\)"):
        bk.download(tmp_path, now=NOW, second_source=_second({"meta": 1.03}))
    assert bk.LAST_VALIDATION["cross_check"]["status"] == "disagrees"
    with pytest.raises(ValueError, match="cross-check"):                    # and the stored verdict stops the next call on the same pull
        bk.download(tmp_path, now=NOW)
    p = bk.download(tmp_path, now=NOW, second_source=_second({"meta": 1.004}))                # a dividend-sized gap is inside the tolerance
    assert p.validation["cross_check"]["status"] == "ok"
    p = bk.download(tmp_path, now=NOW, second_source=_second(absent=FILES))
    assert p.validation["ok"] and p.validation["cross_check"]["status"] == "unavailable" and any("cross-check unavailable" in n for n in p.validation["notes"])
    p = bk.download(tmp_path, now=NOW, second_source=_second(absent=("spcx",), source="stooq"))
    assert p.validation["ok"] and p.validation["cross_check"]["status"] == "partial" and p.validation["cross_check"]["independent"] is True
    p = bk.download(tmp_path, now=NOW, second_source=lambda *a: (_ for _ in ()).throw(OSError("network down")))
    assert p.validation["ok"] and p.validation["cross_check"]["status"] == "unavailable"    # the check is never what stops the call


def test_the_second_source_is_not_asked_again_once_it_has_nothing(tmp_path):
    _pull(tmp_path)
    asked = []

    def fetch(ticker, days, order):
        asked.append(order)
        return pd.Series(np.linspace(10, 12, len(D60)), index=D60).tail(days), "yahoo", {"stooq": "no bars"} if "stooq" in order else {}
    bk.download(tmp_path, now=NOW, second_source=fetch)
    assert asked[0] == ("stooq", "yahoo") and set(asked[1:]) == {("yahoo",)}


def test_the_validation_is_published_with_the_call():
    prices, ust, _ = bk.synthetic(days=700)
    assert "validation" not in bk.build(prices, ust, meta={"synthetic": True})              # a build on anything but a validated pull says nothing
    p = bk.Prices(prices)
    p.validation = {"ok": True, "failed": [], "notes": [], "cross_check": {"status": "ok"}, "asof": "2019-09-05"}
    o = bk.build(p, ust, meta={"source": "mirror download"})
    assert o["validation"]["cross_check"]["status"] == "ok" and o["validation"]["ok"] is True


# ---------------------------------------------------------------- 9. the command line
def test_a_failed_engine_fails_the_command(tmp_path, monkeypatch, capsys):
    from buildout import cli, engine
    rn = {"wall_seconds": 1, "serial_seconds": 1, "jobs": 1, "speedup": 1.0}
    bad = {"engines": [{"name": "causal", "status": "failed", "error": "JSONDecodeError", "kept_last_good": True}, {"name": "ooda", "status": "ok"}], "ok": 1, "failed": 1, "runner": rn}
    monkeypatch.setattr(engine, "run", lambda *a, **k: bad)
    with pytest.raises(SystemExit) as e:
        cli.main(["engine", "--out", str(tmp_path), "--only", "causal,ooda"])
    assert e.value.code not in (0, None) and "causal" in str(e.value.code)
    monkeypatch.setattr(engine, "run", lambda *a, **k: {**bad, "engines": bad["engines"][1:], "failed": 0})
    cli.main(["engine", "--out", str(tmp_path)])                           # all ok: returns
    assert "1 ok, 0 failed" in capsys.readouterr().out


def test_the_decision_engine_reads_the_runs_own_ten_year_yield(tmp_path):
    from buildout import cli
    v, note = cli.decide_y10(tmp_path)                                     # no macro.json: the constant, and it says so
    assert v == cli.Y10_ASSUMED and note["assumed"] is True and "assumed constant" in note["source"] and note["date"] is None
    _write(tmp_path, "macro.json", {"latest": {"DGS10": 5.12, "DGS10_date": "2026-11-16"}})
    v, note = cli.decide_y10(tmp_path)
    assert v == 5.12 and note == {"value": 5.12, "source": "FRED DGS10 (macro.json)", "date": "2026-11-16", "assumed": False}
    _write(tmp_path, "macro.json", {"latest": {"DGS10": 512.0}})          # a units mix-up is not a yield
    assert cli.decide_y10(tmp_path)[1]["assumed"] is True


# ---------------------------------------------------------------- 10. files
def test_no_temporary_file_survives_or_is_published(tmp_path, monkeypatch):
    from buildout import jsonout
    names = []
    real = os.replace
    monkeypatch.setattr(jsonout.os, "replace", lambda a, b: (names.append(Path(a).name), real(a, b))[1])
    jsonout.write({"a": 1}, tmp_path, "macro.json")
    assert names and names[0].startswith(".macro.json.") and names[0].endswith(".tmp")      # a dot-file: git-ignored (.*.tmp), skipped by the build
    assert [p.name for p in tmp_path.iterdir()] == ["macro.json"]
    monkeypatch.setattr(jsonout.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        jsonout.write({"a": 2}, tmp_path, "macro.json")
    assert [p.name for p in tmp_path.iterdir()] == ["macro.json"] and json.loads((tmp_path / "macro.json").read_text())["a"] == 1
    ign = (ROOT / ".gitignore").read_text().splitlines()
    assert "*.json.tmp" in ign and ".lastgood/" in ign and ".*.tmp" in ign


def test_the_site_build_skips_debris_and_dates_files_by_their_data(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_site
    src = tmp_path / "work" / "site"
    (src / "data" / ".lastgood" / "ooda").mkdir(parents=True)
    (src / "page.html").write_text("<style>p{}</style><p>page</p>")
    _write(src / "data", "macro.json", {"latest": {"as_of": "2026-11-16"}})
    _write(src / "data", "technicals.json", {"as_of": "2026-11-17", "generated_utc": "2026-11-18T19:32:00Z"})
    _write(src / "data", "connections.json", {"checked": "2026-11-18T19:31:29Z"})
    _write(src / "data", "causal.json", {"findings": []})
    for junk in ("macro.json.tmp", ".macro.json.123.tmp", ".lastgood/ooda/ooda.json"):
        (src / "data" / junk).write_text("{")
    build_site.build(str(src), str(tmp_path / "out"))
    out = tmp_path / "out" / "data"
    assert sorted(p.name for p in out.iterdir()) == ["causal.json", "connections.json", "macro.json", "manifest.json", "technicals.json"]
    m = json.loads((out / "manifest.json").read_text())["data"]
    assert m["macro.json"]["asof"] == "2026-11-16" and m["macro.json"]["asof_kind"] == "data"            # was null: the date sits under "latest"
    assert m["technicals.json"]["asof"] == "2026-11-17" and m["technicals.json"]["written"] == "2026-11-18T19:32:00Z"
    assert m["connections.json"]["asof_kind"] == "written" and m["connections.json"]["asof"] == "2026-11-18T19:31:29Z"
    assert m["causal.json"]["asof"] is None and m["causal.json"]["asof_kind"] is None


def test_the_runner_leaves_no_last_good_folder(tmp_path):
    from buildout.core import runner

    def ok(out):
        (out / "a.json").write_text('{"schema": 2}')
    runner.run([runner.Task("a", ok, writes=["a.json"])], tmp_path, isolate=False)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json"]


# ---------------------------------------------------------------- 11. the gradient check
def test_gradcheck_ignores_rounding_on_a_zero_gradient_and_still_finds_a_wrong_one(monkeypatch):
    from buildout import nn
    rng = np.random.default_rng(4)
    X, y = rng.normal(size=(12, 3)), rng.normal(size=12)
    m = nn.MLP(3, hidden=(), dropout=0.0)
    assert nn.gradcheck(m, X, y) < 1e-6                                     # the bias gradient is exactly zero here; 5.6e-4 before on some machines
    real = nn.MLP._loss_grad

    def wrong(self, Z, T, params, masks, gbuf=None, penalty=True):
        loss, grads = real(self, Z, T, params, masks, gbuf, penalty)
        grads[-1][...] += 1e-3                                              # a bias gradient that is off by a thousandth
        return loss, grads
    monkeypatch.setattr(nn.MLP, "_loss_grad", wrong)
    assert nn.gradcheck(m, X, y) > 0.5
    monkeypatch.setattr(nn.MLP, "_loss_grad", lambda self, Z, T, params, masks, gbuf=None, penalty=True: (lambda r: (r[0], [g * 1.01 for g in r[1]]))(real(self, Z, T, params, masks, gbuf, penalty)))
    assert nn.gradcheck(nn.MLP(3, hidden=(5,), out=2), X, rng.normal(size=(12, 2))) > 1e-3      # every gradient 1% too large


# ---------------------------------------------------------------- 12. the workflows (text and logic; they cannot run here)
def _step(wf: str, name: str) -> dict:
    d = yaml.safe_load((WF / wf).read_text())
    return next(s for s in next(iter(d["jobs"].values()))["steps"] if s.get("name", "").startswith(name))


def test_no_workflow_merges_generated_files_any_more():
    for wf in ("daily.yml", "filings.yml", "futures.yml"):
        run = "\n".join(ln for ln in _step(wf, "Commit results")["run"].splitlines() if not ln.strip().startswith("#"))      # the commands, not the comments
        assert "pull --rebase" not in run and "git fetch -q origin main" in run and "git checkout -q --detach origin/main" in run and "git push -q origin HEAD:main" in run, wf
    daily = _step("daily.yml", "Commit results")["run"]
    assert "git add site/data ledger/calls.jsonl paper" in daily and "-- ledger/calls.jsonl paper" in daily
    assert yaml.safe_load((WF / "daily.yml").read_text())[True]["schedule"] == [{"cron": "17 11 * * 2-6"}]      # the schedule is as it was


@pytest.mark.skipif(shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash")
@pytest.mark.parametrize("upstream, expect", [
    ("none", {"status": '{"run": "this"}', "ledger": 2, "who": "this run", "code": "v1", "filings": "f1"}),
    ("code and another workflow's file", {"status": '{"run": "this"}', "ledger": 2, "who": "this run", "code": "v2", "filings": "f2"}),
    ("the same generated file", {"status": '{"run": "this"}', "ledger": 2, "who": "this run", "code": "v2", "filings": "f1"}),
    ("another run published", {"status": '{"run": "other"}', "ledger": 2, "who": "other run", "code": "v1", "filings": "f1"}),
])
def test_the_commit_step_against_a_main_that_moved(tmp_path, upstream, expect):
    """The daily commit step, run for real against a local origin. Whatever landed on main meanwhile, the result is one
    consistent commit: this run's files whole, other people's work kept, never a conflict marker, never a rewritten
    ledger line."""
    script = _step("daily.yml", "Commit results")["run"].replace("sleep $((i * 10))", "sleep 0")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

    def git(*a, cwd):
        return subprocess.run(["git", *a], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout
    origin, seed, runner_, dev = (tmp_path / n for n in ("origin.git", "seed", "runner", "dev"))
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("init", "-q", "-b", "main", str(seed), cwd=tmp_path)
    for rel, text in {"site/data/status.json": '{"run": "seed"}', "site/data/filings.json": "f1", "ledger/calls.jsonl": '{"seq":1}\n',
                      "paper/paper_account.json": '{"cash": 1}', "paper/README.md": "readme", "buildout/x.py": "v1"}.items():
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(text)
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "seed", cwd=seed)
    git("push", "-q", str(origin), "main", cwd=seed)
    git("clone", "-q", "--depth", "1", origin.as_uri(), str(runner_), cwd=tmp_path)        # the workflow's shallow checkout
    git("clone", "-q", str(origin), str(dev), cwd=tmp_path)
    if upstream == "code and another workflow's file":
        (dev / "buildout/x.py").write_text("v2")
        (dev / "site/data/filings.json").write_text("f2")
        (dev / "paper/README.md").write_text("a new readme")
    elif upstream == "the same generated file":
        (dev / "buildout/x.py").write_text("v2")
        (dev / "site/data/status.json").write_text('{"run": "someone",\n "edited": "by hand"}')
    elif upstream == "another run published":
        (dev / "ledger/calls.jsonl").write_text('{"seq":1}\n{"seq":2,"by":"other run"}\n')
        (dev / "site/data/status.json").write_text('{"run": "other"}')
    if upstream != "none":
        git("add", "-A", cwd=dev)
        git("commit", "-q", "-m", "upstream", cwd=dev)
        git("push", "-q", "origin", "main", cwd=dev)
    (runner_ / "site/data/status.json").write_text('{"run": "this"}')
    (runner_ / "site/data/book.json").write_text('{"asof": "2026-11-17"}')
    (runner_ / "ledger/calls.jsonl").write_text('{"seq":1}\n{"seq":2,"by":"this run"}\n')
    r = subprocess.run(["bash", "-e", "-c", script], cwd=runner_, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    check = tmp_path / "check"
    git("clone", "-q", str(origin), str(check), cwd=tmp_path)
    led = (check / "ledger/calls.jsonl").read_text()
    got = {"status": (check / "site/data/status.json").read_text(), "ledger": len(led.splitlines()), "who": "this run" if "this run" in led else "other run",
           "code": (check / "buildout/x.py").read_text(), "filings": (check / "site/data/filings.json").read_text()}
    assert got == expect
    assert not any(m in p.read_text() for p in check.rglob("*.json*") for m in ("<<<<<<<", ">>>>>>>"))
    if upstream == "another run published":
        assert "Not committed" in r.stdout and not (check / "site/data/book.json").exists()        # nothing of this run, so the set stays one run's
    else:
        assert (check / "site/data/book.json").exists() and len(git("log", "--oneline", cwd=check).splitlines()) == (2 if upstream == "none" else 3)


def _status_check(tmp_path: Path, st: dict, outcomes="smoke|Smoke test the engine|success\nbook|Book run (Databento)|success") -> subprocess.CompletedProcess:
    code = _step("daily.yml", "Status check")["run"].split("python - <<'PY'\n")[1].rsplit("\nPY", 1)[0]
    (tmp_path / "site" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "site" / "data" / "status.json").write_text(json.dumps(st))
    env = {**os.environ, "STEP_OUTCOMES": outcomes, "HAS_DATABENTO": "true", "HAS_SEC_UA": "true", "RUN_URL": "https://example.com/run",
           "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"), "RUNNER_TEMP": str(tmp_path)}
    return subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True)


def test_a_failed_check_turns_the_run_red_and_a_warning_does_not(tmp_path):
    files = {"macro.json": {"present": True, "valid": True}}
    ok = _status_check(tmp_path, {"files": files, "checks": [{"name": "a", "ok": True, "detail": "", "level": "fail"}]})
    assert ok.returncode == 0 and "all data steps succeeded" in ok.stdout
    warn = _status_check(tmp_path, {"files": files, "checks": [{"name": "Feed scraper read at least half its sources", "ok": False, "detail": "3 read, 9 failed", "level": "warn"}]})
    assert warn.returncode == 0 and "::warning title=Check warning::Feed scraper" in warn.stdout and "### Warnings" in warn.stdout
    red = _status_check(tmp_path, {"files": files, "checks": [{"name": "Book data is from the last completed session", "ok": False, "detail": "as of 2026-11-10, 5 sessions behind", "level": "fail"}]})
    assert red.returncode == 1 and "::error title=Check failed::Book data is from the last completed session" in red.stdout
    alert = (tmp_path / "status_check.md").read_text()                     # what the Status alert step posts to the issue
    assert "## Daily run: FAILED" in alert and "### Checks that failed" in alert and "5 sessions behind" in alert
    assert _status_check(tmp_path, {"files": files, "checks": [{"name": "written by an older status.py", "ok": False, "detail": ""}]}).returncode == 1


def test_the_alert_issue_is_closed_by_the_next_green_run():
    d = yaml.safe_load((WF / "daily.yml").read_text())
    steps = d["jobs"]["run"]["steps"]
    names = [s.get("name", "") for s in steps]
    i, j, k = names.index("Status check"), next(n for n, x in enumerate(names) if x.startswith("Status recovered")), names.index("Status alert")
    assert i < j < k and steps[j]["if"] == "success()" and steps[k]["if"] == "failure()"
    run = steps[j]["run"]
    assert 'title="Daily run failed"' in run and "gh issue close" in run and "--comment" in run and "$RUN_URL" in run
    assert steps[j]["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}" and d["permissions"]["issues"] == "write"
    assert 'title="Daily run failed"' in steps[k]["run"]                    # the same title the alert opens


def test_databento_and_everything_it_needs_is_pinned():
    pins = None
    for wf in ("daily.yml", "futures.yml"):
        run = _step(wf, "Install")["run"]
        mine = sorted(x.strip('"') for x in run.replace("\\\n", " ").split() if "==" in x)
        assert len(mine) == 17 and all(p.count("==") == 1 for p in mine) and "databento==0.88.0" in mine and "aiohttp==3.14.5" in mine, wf
        pins = pins or mine
        assert mine == pins                                                 # the two workflows install the same set
    assert "(ci.yml)" in _step("daily.yml", "Smoke test")["run"] or "(ci.yml)" in (WF / "daily.yml").read_text()
