"""Unusual data: publication lags, annual holds, astronomy and calendar signals, failure handling, JSON safety.
Synthetic inputs only; nothing here touches the network."""
import json

import numpy as np
import pandas as pd
import pytest

from buildout import unusual as u


def _entry(i):
    return next(e for e in u.REGISTRY if e["id"] == i)


def _dl(**series):
    return {"raw": {k: pd.DataFrame({"value": v.astype(float)}, index=pd.DatetimeIndex(v.index, name="date")) for k, v in series.items()},
            "failed": {}}


def _monthly_series(start, n):
    return pd.Series(np.arange(1.0, n + 1), index=pd.date_range(start, periods=n, freq="MS"))


# ---------------------------------------------------------------- lags and holds
@pytest.mark.parametrize("sid", ["sunspots", "oni", "co2_global", "hp_us"])
def test_value_appears_only_lag_months_later(sid):
    lag = _entry(sid)["lag_months"]
    assert lag >= 1
    s = _monthly_series("2000-01-01", 24)
    U = u.monthly(_dl(**{sid: s}), start="1999-01-01", end="2003-12-01")
    col = U[sid]
    for t, v in s.items():
        assert col.loc[t + pd.DateOffset(months=lag)] == v
    # nothing is visible before the first value's release month, and no row shows a value early
    assert col.loc[: pd.Timestamp("2000-01-01") + pd.DateOffset(months=lag - 1)].isna().all()
    for t, v in col.dropna().items():
        ref = s.index[int(v) - 1]
        assert ref + pd.DateOffset(months=lag) <= t


def test_daily_series_is_averaged_within_the_month_then_lagged_and_partial_month_dropped():
    e = _entry("ao")
    days = pd.date_range("2000-01-01", "2000-03-20", freq="D")       # March is incomplete
    s = pd.Series(np.where(days.month == 1, 1.0, 2.0), index=days)
    U = u.monthly(_dl(ao=s), start="1999-12-01", end="2000-06-01")["ao"]
    lag = e["lag_months"]
    assert U.loc[pd.Timestamp("2000-01-01") + pd.DateOffset(months=lag)] == pytest.approx(1.0)
    assert U.loc[pd.Timestamp("2000-02-01") + pd.DateOffset(months=lag)] == pytest.approx(2.0)
    assert np.isnan(U.loc[pd.Timestamp("2000-03-01") + pd.DateOffset(months=lag)])      # March was still being observed
    assert U.loc[:"2000-01-01"].isna().all()


def test_annual_forward_fill_does_not_leak():
    sid = "pop_world"
    e = _entry(sid)
    assert e["frequency"] == "annual"
    anchor, lag = int(e["anchor"]), e["lag_months"]
    years = range(2000, 2006)
    s = pd.Series([float(y) for y in years], index=pd.to_datetime([f"{y}-01-01" for y in years]))
    U = u.monthly(_dl(**{sid: s}), start="1999-01-01", end="2010-12-01")[sid]
    for y in years:
        release = pd.Timestamp(y, anchor, 1) + pd.DateOffset(months=lag)
        assert U.loc[release] == y
        assert U.loc[release - pd.DateOffset(months=1)] != y            # never before its release
        assert U.loc[release + pd.DateOffset(months=11)] == y           # held for the rest of its year
    # every visible value was released on or before its row
    for t, y in U.dropna().items():
        assert pd.Timestamp(int(y), anchor, 1) + pd.DateOffset(months=lag) <= t
    # the last value is held twelve rows in all, then the column goes empty instead of running on
    last_release = pd.Timestamp(2005, anchor, 1) + pd.DateOffset(months=lag)
    assert U.loc[last_release + pd.DateOffset(months=11)] == 2005
    assert np.isnan(U.loc[last_release + pd.DateOffset(months=12)])


def test_seasonal_and_quarterly_holds():
    m = _entry("monsoon_india")
    s = pd.Series([100.0, 90.0], index=pd.to_datetime(["2001-01-01", "2002-01-01"]))
    U = u.monthly(_dl(monsoon_india=s), start="2001-01-01", end="2004-12-01")["monsoon_india"]
    first = pd.Timestamp(2001, int(m["anchor"]), 1) + pd.DateOffset(months=m["lag_months"])
    assert U.loc[first] == 100 and np.isnan(U.loc[first - pd.DateOffset(months=1)])
    q = _entry("gdp_us_real")
    s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2001-03-01", "2001-06-01"]))   # quarter-end reference months
    U = u.monthly(_dl(gdp_us_real=s), start="2001-01-01", end="2002-12-01")["gdp_us_real"]
    r = pd.Timestamp("2001-03-01") + pd.DateOffset(months=q["lag_months"])
    assert list(U.loc[r: r + pd.DateOffset(months=2)]) == [1.0, 1.0, 1.0]
    assert U.loc[r + pd.DateOffset(months=3)] == 2.0
    assert np.isnan(U.loc[r + pd.DateOffset(months=6)])


def test_end_cuts_values_not_yet_knowable():
    s = _monthly_series("2000-01-01", 12)
    U = u.monthly(_dl(sunspots=s), start="2000-01-01", end="2000-06-01")
    assert U.index.max() == pd.Timestamp("2000-06-01")
    assert U["sunspots"].max() == 6 - _entry("sunspots")["lag_months"]


# ---------------------------------------------------------------- astronomy
def test_lunar_phase_is_periodic_and_matches_a_known_full_moon():
    t = pd.date_range("1900-01-01", "2030-01-01", periods=500)
    a = u.lunar_age(t)
    b = u.lunar_age(t + pd.Timedelta(days=u.SYNODIC))
    d = np.abs(a - b)
    assert np.all(np.minimum(d, u.SYNODIC - d) < 1e-6)
    assert u.SYNODIC == pytest.approx(29.53, abs=0.01)
    full = pd.Timestamp("2024-01-25 17:54")                               # full moon, 25 January 2024
    assert abs(u.lunar_age(full)[0] - u.SYNODIC / 2) < 1.0
    assert u.illumination(full)[0] > 0.98
    assert u.illumination(pd.Timestamp("2024-01-11 11:57"))[0] < 0.02   # the new moon before it
    C = u.computed(pd.date_range("1871-01-01", "2026-12-01", freq="MS"))
    assert C["moon_full_share"].mean() == pytest.approx(0.25, abs=0.005)
    assert C["moon_new_share"].mean() == pytest.approx(0.25, abs=0.005)
    assert C["moon_full_share"].between(0, 1).all() and C["moon_illum"].between(0, 1).all()


def test_daylight_equator_and_new_york_seasons():
    doy = np.arange(1, 366)
    assert np.allclose(u.daylight_hours(0.0, doy), 12.0, atol=1e-9)
    C = u.computed(pd.date_range("2020-01-01", "2020-12-01", freq="MS"))
    ny = C["daylight_ny"]
    assert ny.loc["2020-06-01"] > ny.loc["2020-12-01"]
    assert 14.5 < ny.loc["2020-06-01"] < 15.3 and 9.0 < ny.loc["2020-12-01"] < 9.6
    assert C["daylight_london"].loc["2020-06-01"] > ny.loc["2020-06-01"]
    assert C["daylight_chg_ny"].loc["2020-03-01"] > 0 and C["daylight_chg_ny"].loc["2020-10-01"] < 0
    assert (C.loc["2020-04-01":"2020-09-01", "sad_ny"] == 0).all() and C.loc["2020-12-01", "sad_ny"] > 2


def test_calendar_signals():
    C = u.computed(pd.date_range("2024-01-01", "2028-12-01", freq="MS"))
    assert C.loc["2024", "trading_days"].sum() == 252                     # NYSE 2024 calendar
    assert C.loc["2024-06-01", "trading_days"] == 19                       # Juneteenth
    assert C.loc["2024-09-01", "fri13"] == 1 and C.loc["2024-12-01", "fri13"] == 1 and C.loc["2024-10-01", "fri13"] == 0
    assert C.loc["2025-01-01", "pres_cycle"] == 1 and C.loc["2026-06-01", "pres_cycle"] == 2 and C.loc["2028-11-01", "pres_cycle"] == 4
    assert C.loc["2024-11-01", "halloween"] == 1 and C.loc["2025-04-01", "halloween"] == 1 and C.loc["2025-05-01", "halloween"] == 0
    assert C["january"].sum() == 5
    # any date within a month maps to that month
    D = u.computed(pd.to_datetime(["2024-01-17", "2024-02-29"]))
    assert list(D.index) == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01")]


# ---------------------------------------------------------------- parsers
def test_hurdat_parser_counts_storms_and_zero_fills():
    txt = "\n".join([
        "AL012001,            ALPHA,      3,",
        "20010801, 0000,  , TS, 20.0N,  60.0W,  40, 1005,",
        "20010801, 0600,  , HU, 20.5N,  61.0W,  70,  990,",
        "20010801, 0900,  , HU, 20.6N,  61.2W,  75,  988,",
        "AL022001,             BETA,      2,",
        "20010802, 0000,  , TD, 15.0N,  40.0W,  30, 1009,",
        "20010915, 1200,  , TS, 16.0N,  41.0W,  50, 1000,",
    ]).encode()
    r = u._p_hurdat(txt)
    assert r["storms"].loc["2001-08-01"] == 1 and r["storms"].loc["2001-09-01"] == 1
    assert r["hurricanes"].loc["2001-08-01"] == 1 and r["hurricanes"].loc["2001-09-01"] == 0
    assert r["ace"].loc["2001-08-01"] == pytest.approx((40 ** 2 + 70 ** 2) * 1e-4)   # the 0900 fix is not synoptic
    assert r["ace"].loc["2001-12-01"] == 0 and r["ace"].index.min() == pd.Timestamp("2001-01-01")


# ---------------------------------------------------------------- download failures
def test_download_with_failing_http_returns_failures_without_raising(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(u.http, "get", boom)
    dl = u.download(use_cache=False)
    assert dl["raw"] == {}
    assert set(dl["failed"]) == {e["id"] for e in u.REGISTRY}
    assert all(isinstance(v, str) and v for v in dl["failed"].values())
    monkeypatch.setenv("BUILDOUT_CACHE", str(tmp_path))
    dl2 = u.download(max_age=0)                                            # cached path, nothing cached yet
    assert dl2["raw"] == {} and set(dl2["failed"]) == {e["id"] for e in u.REGISTRY}
    assert u.monthly(dl2).empty


def test_download_keeps_the_sources_that_answer(monkeypatch):
    silso = b"2000;01;2000.042; 100.0; 5.0; 900;0\n2000;02;2000.122; 110.0; 5.0; 900;0\n"

    def fake(url, **k):
        if url.endswith("SN_m_tot_V2.0.csv"):
            return silso
        raise RuntimeError("404")
    monkeypatch.setattr(u.http, "get", fake)
    dl = u.download(use_cache=False)
    assert list(dl["raw"]) == ["sunspots"]
    assert dl["raw"]["sunspots"]["value"].tolist() == [100.0, 110.0]
    assert "sunspots" not in dl["failed"] and len(dl["failed"]) == len(u.REGISTRY) - 1


# ---------------------------------------------------------------- metadata
def test_meta_is_json_safe_and_covers_every_column():
    M = u.meta()
    json.dumps(M, allow_nan=False)
    for k, v in M.items():
        for f in ("name", "family", "frequency", "lag_months", "url", "note"):
            assert f in v
        assert isinstance(v["lag_months"], int) and v["lag_months"] >= 0
        assert all(x is None or isinstance(x, (str, int, float, bool)) for x in v.values())
    ids = [e["id"] for e in u.REGISTRY]
    assert len(ids) == len(set(ids)) and not set(ids) & set(u.COMPUTED)
    s = _monthly_series("2000-01-01", 30)
    U = u.monthly(_dl(sunspots=s, oni=s, pop_world=s.iloc[::12]), start="2000-01-01", end="2004-01-01")
    C = u.computed(U.index)
    assert set(U.columns) <= set(M) and set(C.columns) <= set(M)
    assert all(M[c]["lag_months"] == 0 for c in C.columns)
    assert all(M[e["id"]]["lag_months"] >= 1 for e in u.REGISTRY)
    dl = _dl(sunspots=s)
    json.dumps(u.meta(dl), allow_nan=False)
    assert u.meta(dl)["sunspots"]["rows"] == 30


def test_registry_entries_are_complete():
    fams = set()
    for e in u.REGISTRY:
        for f in ("id", "name", "family", "frequency", "start", "end", "url", "licence", "lag_months"):
            assert e.get(f) not in (None, ""), (e["id"], f)
        assert e["url"].startswith("https://raw.githubusercontent.com/")
        assert e["frequency"] in u.HOLD
        if e["frequency"] in ("annual", "seasonal"):
            assert 1 <= int(e["anchor"]) <= 12
        fams.add(e["family"])
        assert e["file"] in u.PARSERS and e["file"] in u.FILES
    assert {"climate", "astronomy", "geophysics", "hazards", "shipping", "demographics", "macro", "sentiment", "energy"} <= fams


def test_house_style_in_strings():
    import inspect
    for mod_src in (inspect.getsource(u), open(__file__, encoding="utf-8").read()):
        assert chr(0x2014) not in mod_src
        for w in ("inter" + "section", "load" + "-bearing"):
            assert w not in mod_src.lower()
