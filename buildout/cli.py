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
  python -m buildout mcp --data site/data       MCP server on stdio: research, risk and reasoning tools, never orders
  python -m buildout engine --out site/data     run the offline engines (valuation, causal, hedges, decision loop) and the manifest
  python -m buildout ooda --out site/data       the decision loop alone: observe, orient, decide, act
  python -m buildout labs --out site/data       the labs: trend rules, oscillators, valuation, regimes, GARCH, spreads, calendar
  python -m buildout mind --out site/data       the mind: one graph of the brain and the engine
  python -m buildout think "Is AI a bubble?"    ask the mind; prints the claim, the verdict, the evidence and the decision
  python -m buildout think "If oil spikes, what happens to the book?"   a what-if over the belief network
  python -m buildout ml --out site/data         machine learning, judged honestly: purged walk-forward, CPCV, conformal, analogs
  python -m buildout reality --out site/data    test every model's assumptions: tails, breakpoints, kappa, fragility, worlds
  python -m buildout triage 1.2 8 40 --published --cost-bps 5 --turns 24   a quant's backtest Sharpe after costs, decay and luck
  python -m buildout erp --cash-yield 0.035 --growth 0.06 --rf 0.0513     Damodaran's implied equity risk premium
  python -m buildout dcf --revenue 100 --growth 0.25 --margin 0.30 --target 0.35   Damodaran's narrative-to-numbers DCF
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import default_config, load_config
from .pipeline import analyze, load_inputs, write_report


def research_line(out_dir) -> tuple:
    """The hedge line and its verdict from the research step's research.json, if that file is in the output folder."""
    from pathlib import Path
    p = Path(out_dir) / "research.json"
    try:
        h = json.loads(p.read_text())["hedge"]
        status = h.get("status", "ok" if h.get("line") is not None else "no_reliable_threshold")
        return (h.get("line"), status)
    except (OSError, KeyError, ValueError, TypeError):
        return (None, "unavailable")


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
    rz = sub.add_parser("reason")
    rz.add_argument("--out", default="out", help="folder with the other daily files; reason.json is written there")
    jn = sub.add_parser("journal")
    jn.add_argument("path", help="decision journal exported from the page (JSON)")
    en = sub.add_parser("engine")
    en.add_argument("--out", default="out")
    en.add_argument("--only", default=None, help="comma-separated engine names")
    en.add_argument("--list", action="store_true")
    oo = sub.add_parser("ooda")
    oo.add_argument("--out", default="out")
    oo.add_argument("--config", default="config.toml")
    at = sub.add_parser("atlas")
    at.add_argument("--out", default="out")
    at.add_argument("--no-fred", action="store_true", help="GitHub mirrors only")
    lb = sub.add_parser("labs")
    lb.add_argument("--out", default="out")
    md = sub.add_parser("mind")
    md.add_argument("--out", default="out")
    th = sub.add_parser("think")
    th.add_argument("question")
    th.add_argument("--data", default=None, help="folder with mind.json (default: the shipped snapshot)")
    th.add_argument("--json", action="store_true", help="print the whole result as JSON (for editors and scripts)")
    for name in ("ml", "reality"):
        q = sub.add_parser(name)
        q.add_argument("--out", default="out")
    tr = sub.add_parser("triage")
    tr.add_argument("sharpe", type=float)
    tr.add_argument("years", type=float)
    tr.add_argument("trials", type=int, nargs="?", default=1)
    tr.add_argument("--published", action="store_true")
    tr.add_argument("--cost-bps", type=float, default=0.0)
    tr.add_argument("--turns", type=float, default=0.0)
    tr.add_argument("--vol", type=float, default=0.15)
    tr.add_argument("--skew", type=float, default=0.0)
    tr.add_argument("--kurt", type=float, default=3.0)
    tr.add_argument("--periods", type=int, default=12)
    er = sub.add_parser("erp")
    er.add_argument("--level", type=float, default=100.0)
    er.add_argument("--cash-yield", type=float, required=True)
    er.add_argument("--growth", type=float, required=True)
    er.add_argument("--rf", type=float, default=0.0513)
    dc = sub.add_parser("dcf")
    dc.add_argument("--revenue", type=float, required=True)
    dc.add_argument("--growth", type=float, required=True)
    dc.add_argument("--margin", type=float, required=True)
    dc.add_argument("--target", type=float, required=True)
    dc.add_argument("--years-to-target", type=int, default=5)
    dc.add_argument("--sales-to-capital", type=float, default=1.5)
    dc.add_argument("--wacc", type=float, default=0.10)
    dc.add_argument("--wacc-mature", type=float, default=0.085)
    dc.add_argument("--rf", type=float, default=0.0513)
    dc.add_argument("--p-fail", type=float, default=0.0)
    dc.add_argument("--shares", type=float, default=1.0)
    dc.add_argument("--debt", type=float, default=0.0)
    dc.add_argument("--cash", type=float, default=0.0)
    mc = sub.add_parser("mcp")
    mc.add_argument("--data", default=None, help="folder with the engine's JSON outputs")
    mc.add_argument("--config", default=None, help="model config; config.private.toml is refused")
    a = ap.parse_args(argv)

    if a.cmd == "engine":
        from .engine import REGISTRY, run as run_engines
        if a.list:
            for e in REGISTRY:
                print(f"{e.name:10s} {'offline' if e.offline else 'network'}  reads {', '.join(e.reads) or '-'}  writes {', '.join(e.writes)}  ({e.does})")
            return
        m = run_engines(a.out, a.only.split(",") if a.only else None)
        for r in m["engines"]:
            print(f"{r['name']:10s} {r['status']:9s} {r.get('seconds', '')}  {r.get('error', '')}")
        return
    if a.cmd == "ooda":
        from .jsonout import write
        from .ooda import build as build_ooda
        print("wrote", write(build_ooda(a.out, a.config), a.out, "ooda.json"))
        return
    if a.cmd == "labs":
        from . import labs, mind
        from .jsonout import write
        K = {k["id"]: k for k in mind.load_knowledge()}
        L = labs.build(labs.download(), cape_now=(K.get("val-cape-2026-10-20") or {}).get("value"))
        L["findings"] = labs.summary(L)
        print("wrote", write(labs.public(L), a.out, "labs.json"))
        for f in L["findings"]:
            print(" ", f)
        return
    if a.cmd == "mind":
        from . import mind
        from .jsonout import write
        G = mind.build_from_dir(a.out)
        print("wrote", write(G, a.out, "mind.json"), f"({len(G['nodes'])} nodes, {len(G['edges'])} links, {len(G['signals'])} signals)")
        return
    if a.cmd == "think":
        from pathlib import Path
        from . import mind, voices
        p = Path(a.data) / "mind.json" if a.data else mind.ASSETS / "mind.json"
        r = mind.Mind(json.loads(p.read_text()), voices.Library(voices.load())).think(a.question)
        if a.json:
            print(json.dumps(r, indent=1, default=str))
            return
        if not r["found"]:
            print(r["note"])
            return
        if r.get("define"):
            d = r["define"]
            print(f"{d['name']}: {d['text']}" + (f"  [{d['formula']}]" if d.get("formula") else ""))
        w = r.get("whatif")
        if w and w.get("found"):
            print(f"what-if: \"{w['claim']}\" set to {w['p_fixed']:.0%}")
            t = w.get("target")
            if t and t["axis"] == "book":
                print(f"  the model book's average lean: {t['lean0']:+.2f} -> {t['lean1']:+.2f}")
                for x in t["rows"]:
                    print(f"    {x['title']}: {x['d'] * 100:+.1f} points for the book")
            elif t:
                print(f"  {t['title']}: bull case {t['p0']:.0%} -> {t['p1']:.0%}")
            for x in w["effects"][:5]:
                print(f"  {x['title']}: {x['p0']:.0%} -> {x['p1']:.0%}")
        print(f"{r['axis_title']}: \"{r['claim']}\" {r['p']:.0%} (range {r['range'][0]:.0%} to {r['range'][1]:.0%}, {r['n_signals']} signals)")
        for x in r["pros"]:
            print(f"  + {x['c']:+.3f}  {x['text']}")
        for x in r["cons"]:
            print(f"  - {x['c']:+.3f}  {x['text']}")
        if r["hinge"]:
            print(f"  hinge: {r['hinge']['text']}")
        for c in r["chains"]:
            print("  chain:", " -> ".join(c["names"]))
        print("  decision:", r["decision"]["text"])
        return
    if a.cmd in ("ml", "reality"):
        from pathlib import Path
        from . import assumptions, labs, ml, mind
        from .jsonout import write
        K = {k["id"]: k for k in mind.load_knowledge()}
        cape = (K.get("val-cape-2026-10-20") or {}).get("value")
        dl = labs.download()
        mlo = ml.build(dl, cape_now=cape, y10_now=5.13)
        mlo["findings"] = ml.summary(mlo)
        if a.cmd == "ml":
            print("wrote", write(mlo, a.out, "ml.json"))
            for f in mlo["findings"]:
                print(" ", f)
            return
        lp = Path(a.out) / "labs.json"
        L = json.loads(lp.read_text()) if lp.exists() else None
        o = assumptions.build(dl, L, mlo, None, None)
        o["findings"] = assumptions.summary(o)
        print("wrote", write(o, a.out, "reality.json"))
        for f in o["findings"]:
            print(" ", f)
        return
    if a.cmd == "triage":
        from .assumptions import triage
        t = triage(a.sharpe, a.years, a.trials, a.periods, a.skew, a.kurt, a.published, a.cost_bps, a.turns, a.vol)
        print(f"claimed Sharpe {t['sharpe']:.2f}; after costs {t['net']:.2f}; after {t['decay']:.0%} expected decay {t['live']:.2f}")
        print(f"chance the true Sharpe beats zero {t['psr']:.0%}; beats the best of {a.trials} lucky tries ({t['emax_annual']:.2f}) {t['dsr']:.0%}")
        print(f"minimum backtest for {a.trials} tries: {t['minbtl_years']:.1f} years ({'enough' if t['enough_data'] else 'not enough'} at {a.years:g}); verdict: {t['verdict']}")
        return
    if a.cmd == "erp":
        from .damodaran import implied_erp
        e = implied_erp(a.level, a.cash_yield, a.growth, a.rf)
        print("no solution for these inputs" if e["r"] is None else f"expected return {e['r']:.2%}; implied equity risk premium {e['erp']:.2%} over {a.rf:.2%}")
        return
    if a.cmd == "dcf":
        from .damodaran import narrative_dcf
        d = narrative_dcf(a.revenue, a.growth, a.margin, a.target, a.years_to_target, a.sales_to_capital, wacc_start=a.wacc, wacc_mature=a.wacc_mature, rf=a.rf,
                          p_fail=a.p_fail, debt=a.debt, cash=a.cash, shares=a.shares)
        for r in d["rows"]:
            print(f"  year {r['year']:2d}  growth {r['growth']:6.1%}  revenue {r['revenue']:10.1f}  margin {r['margin']:5.1%}  FCFF {r['fcff']:9.1f}  WACC {r['wacc']:5.2%}")
        print(f"value of operations {d['ev']:.1f} ({d['terminal_share']:.0%} from the terminal value, terminal growth {d['g_terminal']:.2%}); equity per share {d['per_share']:.2f}")
        return
    if a.cmd == "atlas":
        from . import atlas
        from .jsonout import write
        r = atlas.build(atlas.download(fred=not a.no_fred))
        r["findings"] = atlas.summary(r)
        print("wrote", write(r, a.out, "atlas.json"))
        for f in r["findings"]:
            print(" ", f)
        return
    if a.cmd == "mcp":
        from .mcp_server import Context, serve
        serve(Context(a.data, a.config))
        return
    if a.cmd == "demo":
        cfg = default_config()
        cfg.data.source = "synthetic"
        rep = analyze(cfg, load_inputs(cfg), *research_line(a.out))
        print(json.dumps(rep["summary"], indent=1, default=str))
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
        rep = analyze(cfg, load_inputs(cfg), *research_line(a.out))
        print(json.dumps(rep["summary"], indent=1, default=str))
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
    elif a.cmd == "reason":
        from .jsonout import write
        from .reasoner import build
        res = build(a.out)
        best = res["alternatives"]["optimal"]
        print("posterior", [round(x, 3) for x in res["posterior"]["posterior"]])
        print("optimal (equity, hedge ratio, put premium, gold):", best["port"] if best else None)
        print("wrote", write(res, a.out, "reason.json"))
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
        if hl["status"] == "ok":
            print(f"hedge line {hl['line']:.2%} (band {hl['zone'][0]:.2%} to {hl['zone'][1]:.2%}, chosen on data through {hl['trained_through']}); ", end="")
        else:
            print(f"hedge line: {hl['status'].replace('_', ' ')}; ", end="")
        print(f"latest 36-month inflation {hl['latest']['infl_avg']:.2%}, correlation {hl['latest']['corr']:+.2f}")
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
