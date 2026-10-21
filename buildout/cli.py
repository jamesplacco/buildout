"""Command line.

  python -m buildout demo                       synthetic market with known answers (no data needed)
  python -m buildout macro --out site/data      free FRED regime monitor: Nasdaq-100 vs the long Treasury
  python -m buildout cost  --config config.toml Databento cost estimate before any paid pull
  python -m buildout run   --config config.toml full book run on Databento data, writes report.json
  python -m buildout capex GOOGL MSFT --ua "Name email" [--json site/data/capex.json]
  python -m buildout kalshi KXFED               prediction-market probabilities for a series
  python -m buildout status --out site/data     freshness and sanity checks on every output, for the page
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import default_config, load_config
from .pipeline import analyze, load_inputs, write_report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="buildout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--out", default="out")
    m = sub.add_parser("macro")
    m.add_argument("--out", default="out")
    m.add_argument("--csv", help="offline FRED-style CSV (date + series columns) instead of downloading")
    r = sub.add_parser("run")
    r.add_argument("--config", default="config.toml")
    r.add_argument("--out", default="out")
    c = sub.add_parser("cost")
    c.add_argument("--config", default="config.toml")
    x = sub.add_parser("capex")
    x.add_argument("tickers", nargs="+")
    x.add_argument("--ua", required=True, help='"Your Name your@email.com" (SEC requirement)')
    x.add_argument("--json", help="write the last 12 quarters per ticker to this JSON path")
    k = sub.add_parser("kalshi")
    k.add_argument("series")
    st = sub.add_parser("status")
    st.add_argument("--out", default="out")
    a = ap.parse_args(argv)

    if a.cmd == "demo":
        cfg = default_config()
        cfg.data.source = "synthetic"
        rep = analyze(cfg, load_inputs(cfg))
        print(json.dumps(rep["summary"], indent=1))
        print("wrote", write_report(rep, a.out))
    elif a.cmd == "macro":
        import pandas as pd
        from .jsonout import write
        from .macro import FRED_IDS, analyze_macro
        failed = {}
        if a.csv:
            fred = pd.read_csv(a.csv, index_col=0, parse_dates=True)
        else:
            from .data.fred_source import FredSource
            src = FredSource()
            fred = src.series(FRED_IDS)
            failed = src.failed
        rep = analyze_macro(fred, failed=failed)
        if failed:
            print("FRED series that failed:", failed, file=sys.stderr)
        print(json.dumps(rep["latest"], indent=1))
        print("wrote", write(rep, a.out, "macro.json"))
    elif a.cmd == "run":
        cfg = load_config(a.config)
        rep = analyze(cfg, load_inputs(cfg))
        print(json.dumps(rep["summary"], indent=1))
        print("wrote", write_report(rep, a.out))
    elif a.cmd == "cost":
        from .data.databento_source import DatabentoSource
        cfg = load_config(a.config)
        src = DatabentoSource(equities_dataset=cfg.data.equities_dataset)
        usd = src.estimate_cost(cfg.universe.equities, cfg.data.start, cfg.data.end)
        print(f"{src.equities_dataset_for(cfg.data.start)} ohlcv-1d, {len(cfg.universe.equities)} symbols "
              f"from {cfg.data.start}: ${usd:,.2f}")
    elif a.cmd == "capex":
        from .data.edgar_source import EdgarSource
        src = EdgarSource(a.ua)
        out, failed = {}, []
        for t in a.tickers:
            try:
                df = src.fundamentals(t).tail(12)
            except Exception as exc:          # a new listing may not have XBRL facts yet
                failed.append(f"{t}: {exc}")
                continue
            usd = ["ocf", "capex", "fcf", "long_term_debt", "cash"]
            df[usd] = df[usd] / 1e9
            print(f"\n{t} ($bn)\n", df.round(2).to_string())
            out[t] = df.reset_index(names="quarter_end")
        if failed:
            print("\nskipped:", *failed, sep="\n  ", file=sys.stderr)
        if a.json:
            from pathlib import Path
            from .jsonout import write
            print("wrote", write({"units": "USD billions", "companies": out, "skipped": failed},
                                 Path(a.json).parent, Path(a.json).name))
    elif a.cmd == "status":
        from .status import build_status
        from .jsonout import write
        stat = build_status(a.out)
        print(json.dumps({k: stat[k] for k in ("ok", "generated_utc")}, indent=1))
        for c in stat["checks"]:
            print(("PASS " if c["ok"] else "FAIL ") + c["name"] + (f": {c['detail']}" if c["detail"] else ""))
        print("wrote", write(stat, a.out, "status.json"))
    elif a.cmd == "kalshi":
        from .data.kalshi_source import KalshiSource, implied_probabilities
        print(implied_probabilities(KalshiSource().markets(a.series)).head(30).to_string())
