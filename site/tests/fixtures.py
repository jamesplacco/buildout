"""Engine-shaped data files for page tests, built from the synthetic market by the real engine code.

The numbers are synthetic by design; only the shapes matter. Nothing here is ever served to the site.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from buildout.config import default_config  # noqa: E402
from buildout.data.synthetic import simulate  # noqa: E402
from buildout.jsonout import write  # noqa: E402
from buildout.macro import analyze_macro  # noqa: E402
from buildout.pipeline import analyze, load_inputs, write_report  # noqa: E402
from buildout.status import build_status  # noqa: E402

BOOK = ["MSFT", "AMZN", "GOOGL", "META", "NVDA", "AVGO", "TSLA", "SPCX", "ORCL"]


def fake_fred(seed: int = 3) -> pd.DataFrame:
    w = simulate(BOOK, n_days=2520, seed=7)
    idx, rng = w.prices.index, np.random.default_rng(seed)
    d10, d30 = w.yields["DGS10"] + 2.5, w.yields["DGS30"] + 2.5
    df = pd.DataFrame(index=idx)
    df["NASDAQ100"] = w.prices["QQQ"] * 100
    for k, o in {"DGS1MO": -1.0, "DGS3MO": -0.9, "DGS6MO": -0.8, "DGS1": -0.65, "DGS2": -0.4, "DGS3": -0.3, "DGS5": -0.2, "DGS7": -0.1}.items():
        df[k] = d10 + o
    df["DGS10"], df["DGS20"], df["DGS30"] = d10, d30 + 0.05, d30
    walk = lambda base, s: base + rng.normal(0, s, len(idx)).cumsum()  # noqa: E731
    df["DFII10"], df["T10YIE"], df["THREEFYTP10"] = walk(1.5, 0.02), walk(2.3, 0.01), walk(0.3, 0.01)
    df["BAMLC0A0CM"], df["BAMLH0A0HYM2"] = np.abs(walk(1.1, 0.01)), np.abs(walk(3.5, 0.03)) + 1
    df["VIXCLS"], df["DTWEXBGS"] = np.abs(walk(18, 0.3)) + 10, walk(120, 0.2)
    df["DCOILBRENTEU"], df["DCOILWTICO"] = np.abs(walk(80, 1)) + 20, np.abs(walk(75, 1)) + 20
    return df


def make_fixtures(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    write(analyze_macro(fake_fred(), failed={"THREEFYTP10": "fixture: simulated failure"}), out, "macro.json")
    cfg = default_config()
    cfg.data.source = "synthetic"
    rep = analyze(cfg, load_inputs(cfg))
    rep["summary"]["data"] = "fixture"          # pretend market data so the page renders the book panel
    write_report(rep, out)
    q = pd.date_range("2023-09-30", periods=12, freq="QE")
    companies = {}
    for t, (o0, c0) in {"GOOGL": (30, 12), "MSFT": (35, 14), "AMZN": (30, 18), "META": (22, 10), "ORCL": (5, 4), "TSLA": (4, 2.5), "SPCX": (2, 3)}.items():
        d = pd.DataFrame({"ocf": o0 * (1 + 0.03 * np.arange(12)), "capex": c0 * (1 + 0.12 * np.arange(12)), "long_term_debt": 50.0, "cash": 20.0}, index=q)
        d = d.iloc[-3:] if t == "SPCX" else d
        d["fcf"], d["capex_to_ocf"] = d["ocf"] - d["capex"], d["capex"] / d["ocf"]
        companies[t] = d.reset_index(names="quarter_end")
    write({"units": "USD billions", "companies": companies, "skipped": []}, out, "capex.json")
    write(build_status(out, now=datetime(2026, 10, 20, 12, tzinfo=timezone.utc)), out, "status.json")
    return out


if __name__ == "__main__":
    print("wrote", make_fixtures(Path(sys.argv[1] if len(sys.argv) > 1 else "out/fixtures")))
