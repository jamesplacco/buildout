"""The daily run must degrade gracefully: missing series, bad files and stale data are reported, not fatal."""
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from buildout import macro
from buildout.config import default_config
from buildout.data import fred_source
from buildout.jsonout import clean, write
from buildout.pipeline import analyze, load_inputs, write_report
from buildout.status import build_status, weekdays_since


def _fred(world, drop=()):
    idx = world.prices.index
    d10, d30 = world.yields["DGS10"], world.yields["DGS30"]
    cols = {"NASDAQ100": world.prices["QQQ"] * 100, "DGS10": d10, "DGS20": d30 - 0.1, "DGS30": d30,
            "DGS1MO": d10 - 1.0, "DGS3MO": d10 - 0.9, "DGS6MO": d10 - 0.8, "DGS1": d10 - 0.6, "DGS2": d10 - 0.4,
            "DGS3": d10 - 0.3, "DGS5": d10 - 0.2, "DGS7": d10 - 0.1, "T10YIE": 2.4, "DFII10": 2.0,
            "THREEFYTP10": 0.4, "BAMLC0A0CM": 1.1, "BAMLH0A0HYM2": 3.5, "VIXCLS": 18.0, "DTWEXBGS": 120.0,
            "DCOILBRENTEU": 80.0, "DCOILWTICO": 75.0}
    return pd.DataFrame({k: v for k, v in cols.items() if k not in drop}, index=idx)


def test_macro_survives_missing_optional_series(world):
    rep = macro.analyze_macro(_fred(world, drop=("DGS1MO", "DGS7", "THREEFYTP10", "BAMLH0A0HYM2", "VIXCLS", "DCOILBRENTEU")))
    assert "term_premium10" not in rep["rates"]["levels"] and "vix" not in rep["rates"]["levels"]
    assert len(rep["rates"]["curves"]["latest"]["points"]) == 9
    assert json.loads(json.dumps(clean(rep), allow_nan=False))      # serializes without NaN tokens


def test_macro_names_missing_required_series(world):
    with pytest.raises(ValueError, match="DGS20"):
        macro.analyze_macro(_fred(world, drop=("DGS20",)))


def test_macro_tolerates_gaps(world):
    f = _fred(world)
    f.iloc[::7, f.columns.get_loc("DGS10")] = np.nan                # FRED's "." holidays and missing prints
    f.iloc[-3:, f.columns.get_loc("VIXCLS")] = np.nan
    rep = macro.analyze_macro(f)
    assert rep["latest"]["VIXCLS_date"] < rep["latest"]["as_of"]   # last good print, with its own date


def test_episode_atlas_finds_peak_and_trough(world):
    f = _fred(world)
    f.loc["2020-02-20":"2020-03-20", "NASDAQ100"] *= np.linspace(1.0, 0.6, len(f.loc["2020-02-20":"2020-03-20"]))
    eps = {e["key"]: e for e in macro.episode_atlas(f)}
    c = eps["covid-2020"]
    assert c["peak"] < c["trough"] and c["equity_return"] < -0.3
    assert c["bond_series"] == "DGS20" and isinstance(c["bond_return"], float)
    assert c["vix_max"] == pytest.approx(18.0)
    for e in eps.values():
        assert e["equity_return"] <= 0 and e["days"] > 0


def test_fred_source_records_failures(monkeypatch):
    def fake_get(url, *a, **k):
        if "BAD" in url:
            raise RuntimeError("404")
        return b"observation_date,X\n2026-10-16,1.5\n2026-10-19,.\n"
    monkeypatch.setattr(fred_source.http, "get", fake_get)
    src = fred_source.FredSource()
    df = src.series(["GOOD", "BAD"])
    assert list(df.columns) == ["GOOD"] and "BAD" in src.failed
    assert df["GOOD"].dropna().iloc[-1] == 1.5                       # "." parses as missing, not as a number


def test_json_writer_is_atomic_and_stamped(tmp_path):
    p = write({"x": float("nan"), "y": np.float64(np.inf), "d": pd.Timestamp("2026-10-19")}, tmp_path, "t.json")
    data = json.loads(p.read_text())
    assert data == {"schema": 2, "x": None, "y": None, "d": "2026-10-19"}
    assert not list(tmp_path.glob("*.tmp"))


def test_weekdays_since_matches_the_page():
    now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)            # a Tuesday
    assert weekdays_since("2026-10-16", now) == 2 and weekdays_since("2026-10-20", now) == 0
    assert weekdays_since("2026-10-09", now) == 7 and weekdays_since(None, now) is None


def test_status_flags_synthetic_stale_and_broken_outputs(world, tmp_path):
    rep = macro.analyze_macro(_fred(world))
    write(rep, tmp_path, "macro.json")
    cfg = default_config()
    cfg.data.source = "synthetic"
    write_report(analyze(cfg, load_inputs(cfg)), tmp_path)
    as_of = datetime.fromisoformat(rep["latest"]["as_of"]).replace(tzinfo=timezone.utc)
    st = build_status(tmp_path, now=as_of)
    by = {c["name"]: c for c in st["checks"]}
    assert by["Correlations are within -1 and 1"]["ok"] and by["Treasury curve has at least 8 tenors"]["ok"]
    assert by["FRED data is at most 3 weekdays old"]["ok"]
    assert not by["Book run used market data, not the synthetic test market"]["ok"] and st["ok"] is False
    stale = build_status(tmp_path, now=as_of + pd.Timedelta(days=14))
    assert not {c["name"]: c for c in stale["checks"]}["FRED data is at most 3 weekdays old"]["ok"]
    (tmp_path / "capex.json").write_text('{"companies": ')           # truncated file
    broken = build_status(tmp_path, now=as_of)
    assert broken["files"]["capex.json"]["valid"] is False
    assert any(c["name"] == "capex.json is valid JSON" and not c["ok"] for c in broken["checks"])


def test_current_drawdown_runs_to_the_last_day(world):
    f = _fred(world)
    eps = {e["key"]: e for e in macro.episode_atlas(f)}
    if "current" in eps:
        c = eps["current"]
        assert c["trough"] == f["NASDAQ100"].dropna().index[-1].strftime("%Y-%m-%d")
        last, peak = f["NASDAQ100"].dropna().iloc[-1], f["NASDAQ100"].loc[c["peak"]]
        assert c["equity_return"] == pytest.approx(last / peak - 1)


def test_status_judges_sec_data_by_the_quarter(tmp_path):
    now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    rows = lambda q: {"companies": {"GOOGL": [{"quarter_end": q, "capex": 1.0, "ocf": 2.0}], "MSFT": []}}
    write(rows("2026-06-30"), tmp_path, "capex.json")
    st = build_status(tmp_path, now=now)
    f, by = st["files"]["capex.json"], {c["name"]: c for c in st["checks"]}
    assert f["cadence"] == "quarterly" and f["as_of"] == "2026-06-30"
    assert by["SEC filings include a quarter ended in the last 140 days"]["ok"]
    write(rows("2026-03-31"), tmp_path, "capex.json")
    old = {c["name"]: c for c in build_status(tmp_path, now=now)["checks"]}
    assert not old["SEC filings include a quarter ended in the last 140 days"]["ok"]
    write({"companies": {"GOOGL": ["junk", {"quarter_end": None}]}}, tmp_path, "capex.json")
    junk = build_status(tmp_path, now=now)                             # hostile rows: no crash, no date
    assert junk["files"]["capex.json"].get("as_of") is None
