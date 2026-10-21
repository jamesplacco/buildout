"""The free FRED run and the operational pieces the daily workflow depends on."""
import json

import numpy as np
import pandas as pd

from buildout.data.databento_source import _range_bound
from buildout.jsonout import clean
from buildout.macro import analyze_macro


def _fake_fred(world):
    idx = world.prices.index
    return pd.DataFrame({
        "NASDAQ100": world.prices["QQQ"] * 100,
        "DGS20": world.yields["DGS30"] - 0.15,
        "DGS30": world.yields["DGS30"],
        "DGS10": world.yields["DGS10"],
        "DGS3MO": 3.9, "DGS2": 4.5, "T10YIE": 2.4, "VIXCLS": 18.0, "DFII10": 2.6, "BAMLH0A0HYM2": 3.1,
    }, index=idx)


def test_macro_run_reads_planted_regimes(world):
    rep = analyze_macro(_fake_fred(world), since="2016-01-01")
    by = pd.DataFrame(rep["shock_by_regime"]).set_index("group") if isinstance(rep["shock_by_regime"], list) \
        else rep["shock_by_regime"]
    assert by.loc["hedging", "avg_bond"] > 0 > by.loc["amplifying", "avg_bond"]
    assert rep["latest"]["regime"] in {"hedging", "neutral", "amplifying"}
    assert len(rep["yearly"]) >= 9 and all(-1 <= y["corr"] <= 1 for y in rep["yearly"])
    curves = rep["rates"]["curves"]
    assert curves["latest"]["points"][-1]["tenor"] == "30Y" and curves["year_ago"]["date"] < curves["latest"]["date"]
    assert set(rep["rates"]["spreads_bp"]) == {"2s10s", "3m10y", "10s30s"}
    payload = json.dumps(clean(rep))
    assert "NaN" not in payload and len(payload) < 400_000


def test_range_bound_handles_api_shapes():
    assert _range_bound({"start": "2018-05-01T00:00:00Z", "end": "2026-10-20T00:00:00Z"}, "end") == pd.Timestamp("2026-10-20")
    assert _range_bound({"start_date": "2018-05-01", "end_date": "2026-10-19"}, "end") == pd.Timestamp("2026-10-19")
    nested = {"start": "2018-05-01T00:00:00Z", "end": "2026-10-20T12:00:00Z",
              "schema": {"ohlcv-1d": {"start": "2018-05-01T00:00:00Z", "end": "2026-10-20T00:00:00Z"}}}
    assert _range_bound(nested, "end", "ohlcv-1d") == pd.Timestamp("2026-10-20")


def test_clean_makes_json_safe():
    out = clean({"a": np.float64("nan"), "b": np.int64(3), "c": pd.Timestamp("2026-10-20"), "d": np.bool_(True)})
    assert out == {"a": None, "b": 3, "c": "2026-10-20", "d": True}
