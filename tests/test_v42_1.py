"""v0.42.1: a FRED refusal no longer stops the Databento run or the macro step. FRED's graph CSV throttles GitHub's
machines; two refusals trip the breaker and every later FRED read in the process is skipped. Each series with a
stand-in (the Treasury's par curve for the DGS yields, the indexes' own closes, Shiller's CPI) is taken from it and
recorded; with every route down the run goes on with its rates marked unavailable."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from buildout.config import load_config
from buildout.data import fred_source as fs
from buildout.data import http


def _treasury_csv(y: int) -> str:
    days = pd.bdate_range(f"{y}-01-02", f"{y}-12-31" if y < pd.Timestamp.now().year else pd.Timestamp.now().normalize())
    rows = ["Date,1 Mo,3 Mo,6 Mo,1 Yr,2 Yr,3 Yr,5 Yr,7 Yr,10 Yr,20 Yr,30 Yr"]
    for i, d in enumerate(reversed(days)):                     # the Treasury lists newest first
        b = 4.0 + 0.001 * (i % 50)
        rows.append(d.strftime("%m/%d/%Y") + "," + ",".join(f"{b + k * 0.05:.2f}" for k in range(11)))
    return "\n".join(rows) + "\n"


@pytest.fixture
def blocked_fred(monkeypatch):
    """FRED refuses everything; the Treasury answers; Yahoo and Shiller are stubbed."""
    http.reset()
    fs._TREASURY.clear()
    calls = {"fred": 0, "treasury": 0}
    orig = http.get

    def get(url, *a, **k):
        if "stlouisfed" in url:
            calls["fred"] += 1
            if http.host_down(url):
                raise RuntimeError("skipped: breaker")
            http._fails["fred.stlouisfed.org"] = http._fails.get("fred.stlouisfed.org", 0) + 1
            raise RuntimeError(f"GET failed (HTTP 429) after 3 tries: {url}")
        if "home.treasury.gov" in url:
            calls["treasury"] += 1
            y = int(url.split("daily-treasury-rates.csv/")[1].split("/")[0])
            return _treasury_csv(y).encode()
        return orig(url, *a, **k)

    monkeypatch.setattr(http, "get", get)
    idx = pd.bdate_range("1990-01-02", pd.Timestamp.now().normalize())
    monkeypatch.setattr(fs, "from_index", lambda sid: pd.Series(np.linspace(100, 20000, len(idx)), index=idx, name=sid))
    monkeypatch.setattr(fs, "from_shiller_cpi", lambda: pd.Series(np.linspace(200, 330, 200), index=pd.date_range("2010-01-01", periods=200, freq="MS"), name="CPIAUCSL"))
    yield calls
    http.reset()
    fs._TREASURY.clear()


def test_dgs_series_come_from_the_treasury_when_fred_refuses(blocked_fred):
    src = fs.FredSource()
    out = src.series(["DGS10", "DGS30", "DGS3MO", "NASDAQ100", "BAMLH0A0HYM2"], "2018-05-01")
    assert {"DGS10", "DGS30", "DGS3MO", "NASDAQ100"} <= set(out.columns)
    assert src.fallbacks["DGS10"].startswith("US Treasury par yield curve (10 Yr)") and "Yahoo ^NDX" in src.fallbacks["NASDAQ100"]
    assert "BAMLH0A0HYM2" in src.failed and "BAMLH0A0HYM2" not in src.fallbacks       # no stand-in: recorded, not invented
    first_year = pd.Timestamp.now().year - 2018 + 1
    assert blocked_fred["treasury"] == first_year                                      # one download per year, shared by every DGS series
    assert blocked_fred["fred"] <= 5                                                   # the breaker stops FRED retries early
    assert out["DGS10"].dropna().index[0] >= pd.Timestamp("2018-05-01") and out["DGS10"].notna().sum() > 1500


def test_the_databento_run_survives_a_fred_refusal(blocked_fred, tmp_path):
    from buildout import pipeline
    from buildout.data.synthetic import simulate
    cfg = load_config("config.toml")
    w = simulate(list(cfg.universe.book), tuple(cfg.universe.hedges), cfg.universe.market)
    w.prices.to_csv(tmp_path / "px.csv")
    cfg.data.source, cfg.data.csv_path, cfg.data.cache_dir = "csv", str(tmp_path / "px.csv"), str(tmp_path / "cache")
    cfg.data.start = str(w.prices.index[0].date())
    inp = pipeline.load_inputs(cfg)
    a = inp.adjustments
    assert inp.yields is not None and list(inp.yields.columns) == ["DGS10", "DGS30"]
    assert a["rates_fallbacks"]["DGS10"].startswith("US Treasury") and "CPIAUCSL" in a["rates_fallbacks"]
    assert "rates_error" not in a and inp.rf.notna().all()


def test_with_every_route_down_the_run_goes_on_and_says_so(blocked_fred, tmp_path, monkeypatch):
    from buildout import pipeline
    from buildout.data.synthetic import simulate
    monkeypatch.setattr(fs, "treasury_year", lambda y: (_ for _ in ()).throw(RuntimeError("treasury down")))
    cfg = load_config("config.toml")
    w = simulate(list(cfg.universe.book), tuple(cfg.universe.hedges), cfg.universe.market)
    w.prices.to_csv(tmp_path / "px.csv")
    cfg.data.source, cfg.data.csv_path, cfg.data.cache_dir = "csv", str(tmp_path / "px.csv"), str(tmp_path / "cache")
    cfg.data.start = str(w.prices.index[0].date())
    inp = pipeline.load_inputs(cfg)                            # before v0.42.1 this raised "no FRED series could be read"
    assert inp.yields is None and "rates_error" in inp.adjustments and "rates unavailable" in inp.adjustments["note"]
    assert inp.adjustments["evidence"] == "Estimated"


def test_the_macro_step_has_its_required_series_without_fred(blocked_fred):
    from buildout.macro import REQUIRED, FRED_IDS, analyze_macro
    src = fs.FredSource()
    fred = src.series(FRED_IDS)
    assert set(REQUIRED) <= set(fred.columns)
    rep = analyze_macro(fred, failed=src.failed)
    assert rep and src.fallbacks.get("DGS20", "").startswith("US Treasury")


def test_stand_ins_are_never_cached_under_freds_name(blocked_fred, tmp_path):
    from buildout.data.store import Cache
    c = Cache(str(tmp_path))
    fs.FredSource(c).series(["DGS10"], "2024-01-01")
    assert c.get("fred|DGS10") is None
