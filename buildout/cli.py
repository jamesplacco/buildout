"""Command line.

  python -m buildout demo                       synthetic market with known answers (no data needed)
  python -m buildout macro --out site/data      free FRED regime monitor: Nasdaq-100 vs the long Treasury
  python -m buildout cost  --config config.toml Databento cost estimate before any paid pull
  python -m buildout run   --config config.toml full book run on Databento data, writes report.json
  python -m buildout capex GOOGL MSFT --ua "Name email" [--json site/data/capex.json]
  python -m buildout kalshi KXFED               prediction-market probabilities for a series
  python -m buildout status --out site/data     freshness and sanity checks on every output, for the page
  python -m buildout research --out site/data   155 years of public data: when bonds hedge, fat tails, base rates
  python -m buildout journal decisions.json     score an exported decision journal: calibration, alpha, luck
  python -m buildout brain --out site/data      measured links between oil, CPI, yields, stocks, VIX and gold, by regime
  python -m buildout buyside --out site/data    the field manual's engine: regime and gross, hedge selector, fat tails, replays
  python -m buildout feeds --out site/data      Noteworthy: RSS, Substack, Telegram, X (with a token), Reddit, HN, news
  python -m buildout sources --out site/data    the registry of every source the engine and the page read
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
    rs = sub.add_parser("research")
    rs.add_argument("--out", default="out")
    rs.add_argument("--data", help="folder with shiller.csv, cpi.csv, y10.csv, brent.csv, vix.csv, gold.csv instead of downloading")
    for name in ("brain", "buyside"):
        b = sub.add_parser(name)
        b.add_argument("--out", default="out")
        b.add_argument("--data", help="folder with the research CSVs instead of downloading")
    fd = sub.add_parser("feeds")
    fd.add_argument("--out", default="out")
    fd.add_argument("--config", default="feeds.toml")
    so = sub.add_parser("sources")
    so.add_argument("--out", default="out")
    so.add_argument("--feeds", default="feeds.toml")
    jn = sub.add_parser("journal")
    jn.add_argument("path", help="decision journal exported from the page (JSON)")
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
        from .fundamentals import analyze_company, from_companyfacts
        out, failed, ttm = {}, [], {}
        for t in a.tickers:
            try:
                facts = src.facts(t)
                df = src.fundamentals(t, facts).tail(12)
            except Exception as exc:          # a new listing may not have XBRL facts yet
                failed.append(f"{t}: {exc}")
                continue
            try:
                ttm[t] = analyze_company(from_companyfacts(facts))
            except Exception as exc:
                failed.append(f"{t} (trailing twelve months): {exc}")
            usd = ["ocf", "capex", "fcf", "long_term_debt", "cash"]
            df[usd] = df[usd] / 1e9
            print(f"\n{t} ($bn)\n", df.round(2).to_string())
            out[t] = df.reset_index(names="quarter_end")
        if failed:
            print("\nskipped:", *failed, sep="\n  ", file=sys.stderr)
        if a.json:
            from pathlib import Path
            from .jsonout import write
            print("wrote", write({"units": "USD billions", "companies": out, "ttm": ttm, "skipped": failed},
                                 Path(a.json).parent, Path(a.json).name))
    elif a.cmd == "status":
        from .status import build_status
        from .jsonout import write
        stat = build_status(a.out)
        print(json.dumps({k: stat[k] for k in ("ok", "generated_utc")}, indent=1))
        for c in stat["checks"]:
            print(("PASS " if c["ok"] else "FAIL ") + c["name"] + (f": {c['detail']}" if c["detail"] else ""))
        print("wrote", write(stat, a.out, "status.json"))
    elif a.cmd == "research":
        from .jsonout import write
        from .research import SOURCES, compact, download, run
        if a.data:                            # offline: shiller.csv, cpi.csv, y10.csv, brent.csv, vix.csv, gold.csv
            import pandas as pd
            from pathlib import Path
            raw = {k: pd.read_csv(Path(a.data) / f"{k}.csv") for k in SOURCES}
        else:
            raw = download()
        res = run(raw)
        hl = res["hedge_line"]
        print(f"hedge line {hl['line']:.2%} (band {hl['zone'][0]:.2%} to {hl['zone'][1]:.2%}); "
              f"latest 36-month inflation {hl['latest']['infl_avg']:.2%}, correlation {hl['latest']['corr']:+.2f}")
        print("wrote", write(compact(res), a.out, "research.json"))      # the page reads this shape directly
    elif a.cmd in ("brain", "buyside"):
        from .jsonout import write
        from .research import SOURCES, download
        if a.data:
            import pandas as pd
            from pathlib import Path
            raw = {k: pd.read_csv(Path(a.data) / f"{k}.csv") for k in SOURCES}
        else:
            raw = download()
        if a.cmd == "brain":
            from .brain import run as run_brain
            res = run_brain(raw)
            flip = res["y10_eq_corr"]
            print(f"10-year yield vs stocks, monthly correlation: {flip['low_inflation']:+.2f} (1990-2021), {flip['inflation']:+.2f} (2022 on)")
            print("wrote", write(res, a.out, "brain.json"))
        else:
            from .buyside import run as run_buy
            res = run_buy(raw)
            print(f"tail: 97.5% monthly shortfall normal {res['tail']['normal']:.1%}, Student-t {res['tail']['student_t']:.1%}, "
                  f"history {res['tail']['historical']:.1%}")
            print("wrote", write(res, a.out, "buyside.json"))
    elif a.cmd == "feeds":
        from pathlib import Path
        from .feeds import load_config as load_feeds, run as run_feeds, token_from_env
        from .jsonout import write
        hist_path = Path(a.out) / "feeds_history.json"
        history = json.loads(hist_path.read_text()) if hist_path.exists() else {}
        doc, history = run_feeds(load_feeds(a.config), history, token=token_from_env())
        print(doc["bluf"])
        print(f"read {doc['sources']['read']} items; {len(doc['sources']['failed'])} sources failed or skipped")
        print("wrote", write(doc, a.out, "feeds.json"))
        print("wrote", write(history, a.out, "feeds_history.json"))
    elif a.cmd == "sources":
        from .jsonout import write
        from .sources import run as run_sources
        res = run_sources(a.feeds)
        print(f"{res['count']} sources: {res['by_kind']}")
        print("wrote", write(res, a.out, "sources.json"))
    elif a.cmd == "journal":
        from .decisions import scorecard
        doc = json.loads(open(a.path).read())
        recs = doc.get("decisions", doc) if isinstance(doc, dict) else doc
        print(json.dumps(scorecard([r for r in recs if not r.get("example")]), indent=1, default=str))
    elif a.cmd == "kalshi":
        from .data.kalshi_source import KalshiSource, implied_probabilities
        print(implied_probabilities(KalshiSource().markets(a.series)).head(30).to_string())
