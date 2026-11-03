"""Price-pull validation: planted duplicates, reversed dates, bad closes, gaps, a 4:1 split with and without the split
field, stale data and an out-of-range yield are each found under their own kind; a clean frame passes; the command
line exits 1 when a frame fails."""
from __future__ import annotations

import json
import pickle

import numpy as np
import pandas as pd
import pytest

from buildout.data import validate as V


def _bars(n=300, start="2024-01-02", seed=0, split_at=None, factor=4.0, record=True) -> pd.DataFrame:
    """Daily bars on NYSE sessions with a 1% daily volatility; with split_at, an unadjusted factor:1 split that day."""
    rng = np.random.default_rng(seed)
    cbd = pd.offsets.CustomBusinessDay(holidays=pd.to_datetime(V._holidays()))
    idx = pd.date_range(start, periods=n, freq=cbd)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    split = np.full(n, np.nan)
    if split_at is not None:
        close[split_at:] /= factor
        if record:
            split[split_at] = factor
    spread = close * 0.005
    return pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), "open": close, "high": close + spread, "low": close - spread,
                         "close": close, "volume": rng.integers(1_000, 10_000, n), "div": np.nan, "split": split})


def _kinds(r):
    return [i["kind"] for i in r["issues"]]


def _issue(r, kind):
    return next(i for i in r["issues"] if i["kind"] == kind)


def test_a_clean_frame_passes_with_no_issues():
    df = _bars()
    r = V.validate_prices(df, "clean", asof=df["date"].iloc[-1])
    assert r["ok"] and r["issues"] == [] and r["rows"] == 300
    assert r["first"] == df["date"].iloc[0] and r["last"] == df["date"].iloc[-1]
    assert json.loads(json.dumps(r)) == r                                    # plain JSON, nothing to convert


def test_the_date_may_be_the_index():
    df = _bars().set_index("date")
    r = V.validate_prices(df, "indexed")
    assert r["ok"] and r["issues"] == [] and r["rows"] == 300


def test_planted_duplicates_fail():
    df = _bars()
    dup = pd.concat([df.iloc[:100], df.iloc[[99, 99]], df.iloc[100:]], ignore_index=True)
    r = V.validate_prices(dup, "dups")
    assert not r["ok"] and "duplicate_dates" in _kinds(r)
    i = _issue(r, "duplicate_dates")
    assert i["dates"] == [df["date"].iloc[99]] and "2 rows" in i["detail"]


def test_dates_out_of_order_fail():
    df = _bars()
    swapped = pd.concat([df.iloc[:50], df.iloc[[51, 50]], df.iloc[52:]], ignore_index=True)
    r = V.validate_prices(swapped, "order")
    assert not r["ok"] and _kinds(r) == ["non_monotonic"]
    assert _issue(r, "non_monotonic")["dates"] == [df["date"].iloc[50]]


def test_non_positive_and_missing_closes_fail():
    df = _bars()
    df.loc[10, "close"] = 0.0
    df.loc[20, "close"] = -1.0
    df.loc[30, "close"] = np.nan
    r = V.validate_prices(df, "bad")
    assert not r["ok"]
    i = _issue(r, "nonpositive_close")
    assert i["count"] == 3 and i["dates"] == [df["date"].iloc[k] for k in (10, 20, 30)]


def test_a_gap_is_a_warning_with_its_length():
    df = _bars()
    holed = df.drop(index=range(100, 110)).reset_index(drop=True)            # ten sessions missing: an 11-day step
    r = V.validate_prices(holed, "gap")
    assert r["ok"] and _kinds(r) == ["warn_gap"]
    i = _issue(r, "warn_gap")
    assert i["gaps"] == [{"from": df["date"].iloc[99], "to": df["date"].iloc[110], "bdays": 11}]
    assert V.validate_prices(df.drop(index=range(100, 104)), "short gap")["issues"] == []   # five-session step: within the limit


def test_an_unrecorded_4_for_1_split_is_named_as_a_warning():
    df = _bars(split_at=150, record=False)
    r = V.validate_prices(df, "split")
    assert r["ok"] and _kinds(r) == ["warn_jump"]
    i = _issue(r, "warn_jump")
    assert i["dates"] == [df["date"].iloc[150]] and "4:1" in i["detail"]
    assert i["events"][0]["looks_like"] == "4:1" and i["events"][0]["ratio"] == pytest.approx(0.25, rel=0.06)


def test_a_recorded_split_is_named_not_flagged():
    df = _bars(split_at=150, record=True)
    r = V.validate_prices(df, "split")
    assert r["ok"] and _kinds(r) == ["info_split"]
    e = _issue(r, "info_split")["events"][0]
    assert e["split"] == "4:1" and e["date"] == df["date"].iloc[150] and e["adjusted"] is False
    adj = _bars()                                                            # an adjusted series with the split recorded
    adj.loc[150, "split"] = 4.0
    e2 = _issue(V.validate_prices(adj, "adj"), "info_split")["events"][0]
    assert e2["adjusted"] is True


@pytest.mark.parametrize("factor,name", [(2.0, "2:1"), (3.0, "3:1"), (4.0, "4:1"), (10.0, "10:1"), (0.1, "1:10")])
def test_standard_ratios_are_named(factor, name):
    df = _bars(split_at=120, factor=factor, record=False)
    i = _issue(V.validate_prices(df, "s"), "warn_jump")
    assert i["events"][0]["looks_like"] == name
    assert V.split_name(factor) == name


def test_a_large_real_move_is_a_jump_but_not_a_split():
    df = _bars()
    df.loc[200:, ["open", "high", "low", "close"]] *= 1.55                    # +55%: news, not a reverse split
    i = _issue(V.validate_prices(df, "move"), "warn_jump")
    assert i["events"][0]["looks_like"] is None and "split?" not in i["detail"]


def test_stale_data_fails_against_asof():
    df = _bars()
    last = pd.Timestamp(df["date"].iloc[-1])
    cbd = pd.offsets.CustomBusinessDay(holidays=pd.to_datetime(V._holidays()))
    assert V.validate_prices(df, "fresh", asof=last + 5 * cbd)["ok"]
    r = V.validate_prices(df, "stale", asof=last + 6 * cbd)
    assert not r["ok"] and _kinds(r) == ["stale"] and "6 business days" in _issue(r, "stale")["detail"]
    assert V.validate_prices(df, "no asof")["ok"]                            # no asof, no staleness check


def test_ohlc_inconsistency_is_a_warning():
    df = _bars()
    df.loc[40, "high"] = df.loc[40, "low"] - 1
    df.loc[41, "close"] = df.loc[41, "high"] * 1.01
    r = V.validate_prices(df, "ohlc")
    assert r["ok"] and _kinds(r) == ["warn_ohlc"] and _issue(r, "warn_ohlc")["count"] == 2


def test_empty_and_closeless_frames_fail():
    assert not V.validate_prices(pd.DataFrame(columns=["date", "close"]), "empty")["ok"]
    assert not V.validate_prices(_bars().drop(columns="close"), "noclose")["ok"]


def test_business_days_skip_weekends_and_holidays():
    assert V.bdays_between("2026-10-23", "2026-10-26") == 1                  # Friday to Monday
    assert V.bdays_between("2026-11-25", "2026-11-27") == 1                  # Thanksgiving
    assert V.bdays_between("2026-04-02", "2026-04-06") == 1                  # Good Friday
    assert V.bdays_between("2026-10-23", "2026-11-03") == 7


def test_curve_checks_range_gaps_and_staleness():
    days = pd.bdate_range("2026-09-01", "2026-10-30").strftime("%Y-%m-%d")
    good = {"3M": {d: 4.0 for d in days}, "10Y": {d: 4.3 for d in days}}
    r = V.validate_curve(good, asof="2026-10-30")
    assert r["ok"] and r["issues"] == [] and r["rows"] == 2 * len(days) and r["last"] == "2026-10-30"
    bad = {"3M": dict(good["3M"]), "10Y": dict(good["10Y"])}
    bad["10Y"][days[5]] = 43.0                                                 # a units slip: basis points read as percent
    bad["3M"][days[6]] = float("nan")
    for d in days[20:30]:
        del bad["3M"][d]
    r = V.validate_curve(bad, asof="2026-10-30")
    assert not r["ok"] and sorted(_kinds(r)) == ["warn_gap", "warn_missing", "yield_range"]
    assert _issue(r, "yield_range")["dates"] == [days[5]]
    stale = V.validate_curve(good, asof="2026-11-12")
    assert not stale["ok"] and _kinds(stale) == ["stale", "stale"]


def test_validate_all_summarizes():
    frames = {"a": _bars(), "b": _bars(seed=1).drop(index=range(50, 60)), "c": pd.concat([_bars().iloc[:5], _bars().iloc[[4]]])}
    s = V.validate_all(frames)
    assert s["n"] == 3 and not s["ok"] and s["failed"] == ["c"] and s["warnings"] == 1
    assert [r["name"] for r in s["results"]] == ["a", "b", "c"]


def test_command_line_exits_1_on_a_failure(tmp_path, capsys):
    good = tmp_path / "good.pkl"
    good.write_bytes(pickle.dumps({"prices": {"a": _bars(), "b": _bars(seed=2, split_at=100)}}))
    out = tmp_path / "out" / "v.json"
    assert V.main(["--pickle", str(good), "--json", str(out)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("OK   a") and "splits 4:1" in lines[1] and lines[-1].startswith("2 frames, 0 failed")
    assert json.loads(out.read_text())["ok"] is True
    bad = tmp_path / "bad.pkl"
    df = _bars()
    bad.write_bytes(pickle.dumps({"prices": {"a": df}}))
    later = (pd.Timestamp(df["date"].iloc[-1]) + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    assert V.main(["--pickle", str(bad), "--asof", later]) == 1
    assert capsys.readouterr().out.startswith("FAIL a")
