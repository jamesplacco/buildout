"""The engine registry: every engine, what it reads, what it writes, and a manifest of the last run.

    python -m buildout engine --out site/data                    # run the offline engines and write engines.json
    python -m buildout engine --out site/data --list             # print the registry
    python -m buildout engine --out site/data --only valuation,ooda

The data engine is the product; the page is a harness that renders what the engines write. Each engine is a pure
function of files in the data folder (plus the shipped assets), isolated so one failure never stops the rest, and
recorded with its inputs' content hashes, its outputs, timing and status, so any number on the page can be traced to
the run and the inputs that produced it.

Engines that need the network or a secret (macro, book, research, brain, capex, feeds) run as their own steps in the
daily Action and are registered here so the manifest describes the whole system; `run` executes the offline ones.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__


@dataclass
class Engine:
    name: str
    title: str
    reads: list[str]
    writes: list[str]
    module: str
    offline: bool
    does: str
    run: Callable | None = field(default=None, repr=False)


def _write(out: Path, name: str, obj) -> None:
    from .jsonout import write
    write(obj, out, name)


def _valuation(out: Path) -> None:
    from . import ooda, valuation
    snap = ooda.positions_snapshot()
    capex = ooda._load(out, "capex")
    funds = ooda.merged_fundamentals(snap, capex)
    macro = ooda._load(out, "macro")
    rf = ooda._ten_year(macro, snap.get("rf_10y", 4.2)) / 100
    res = valuation.analyze_book(funds, {t: v["market_cap"] for t, v in snap["market_caps"].items()}, rf, snap.get("betas", {}))
    res.update({"as_of": snap["as_of"], "prices_as_of": snap["market_caps_as_of"]})
    _write(out, "valuation.json", res)


def _causal(out: Path) -> None:
    from . import causal_stats
    from .brain import REGIMES
    from .ooda import ASSETS
    brain = json.loads((out / "brain.json").read_text()) if (out / "brain.json").exists() else {}
    series = brain.get("series") or json.loads((ASSETS / "brain_graph.json").read_text())["series"]
    an = causal_stats.analyze(series, REGIMES)
    an["findings"] = causal_stats.summary(an)
    _write(out, "causal.json", an)


def _hedges(out: Path) -> None:
    from . import hedgebook, reasoner
    from .ooda import positions_snapshot
    snap = positions_snapshot()
    post = [s["prior"] for s in reasoner.SCENARIOS]
    sizes = {h["id"]: h["default"] for h in hedgebook.HEDGES}
    sizes.update(snap.get("hedges_default", {}).get("sizes", {}))
    _write(out, "hedges.json", {"catalog": hedgebook.catalog(), "advisor_prior_odds": hedgebook.advisor(sizes, 1.0, post),
                                "assumed": hedgebook.ASSUMED})


def _ooda(out: Path) -> None:
    from . import ooda
    cfg = Path(__file__).resolve().parents[1] / "config.toml"
    _write(out, "ooda.json", ooda.build(out, str(cfg)))


def _reason(out: Path) -> None:
    from . import reasoner
    _write(out, "reason.json", reasoner.build(out))


def _mind(out: Path) -> None:
    from . import mind
    _write(out, "mind.json", mind.build_from_dir(out))


def _voices(out: Path) -> None:
    from . import voices
    q = voices.load()
    lib = voices.Library(q)
    bad = [x["id"] for x in q if not str(x.get("source_url", "")).startswith("https://") or x.get("stance") not in voices.STANCES]
    if bad:
        raise ValueError(f"{len(bad)} quotes fail integrity: {bad[:5]}")
    _write(out, "voices.json", {"quotes": lib.quotes, "topics": {k: {"title": v["title"], "bull": v["bull"], "bear": v["bear"]} for k, v in voices.TOPICS.items()}})


def _status(out: Path) -> None:
    from .status import build_status
    _write(out, "status.json", build_status(out))


REGISTRY: list[Engine] = [
    Engine("macro", "Market regime", [], ["macro.json"], "macro.py", False, "FRED: curve, spreads, levels, stock-bond correlation and regime"),
    Engine("research", "Long-history research", [], ["research.json"], "research.py", False, "156 years: the hedge line out of sample, fat tails, base rates"),
    Engine("brain", "Brain links", [], ["brain.json"], "brain.py", False, "Measured links by regime, the series, structure learning, robust links, self-checks (conformal, stacking, robustness values)"),
    Engine("book", "Book run", ["research.json"], ["report.json"], "pipeline.py", False, "Databento: exposures, regime, hedge, sizing, VaR, stress, backtest, robustness"),
    Engine("capex", "Fundamentals", [], ["capex.json"], "fundamentals.py", False, "SEC XBRL: TTM cash flows, capex, debt, depreciation paths"),
    Engine("atlas", "The atlas", [], ["atlas.json"], "atlas.py", False,
           "Every monthly series: graphical lasso with stability selection, LiNGAM orientation, structural VAR, connectedness"),
    Engine("labs", "The labs", [], ["labs.json"], "labs.py", False,
           "Trading claims on 156 years: trend rules with a bootstrap, max test and deflated Sharpe; oscillators; valuation out of sample; Markov regimes; GARCH; cointegration; multiple testing"),
    Engine("ml", "Machine-learning lab", [], ["ml.json"], "ml.py", False,
           "Six models forecast 12-month returns and 15% falls since 1940: purged walk-forward, Diebold-Mariano, CPCV and overfitting odds, conformal intervals, analogs, novelty"),
    Engine("reality", "Reality check", ["labs.json"], ["reality.json"], "assumptions.py", False,
           "Every model's assumptions tested: tails, dependence, stability, correlation regimes, breakpoints, kappa, fragility, 400 stressed worlds"),
    Engine("connect", "Data connections", [], ["connections.json"], "datahub.py", False, "Credential and reachability check for every data source"),
    Engine("market", "Technicals and fundamentals", [], ["technicals.json", "statements.json"], "technicals.py", False,
           "Daily OHLCV from the best available source: every indicator, signals, levels and an event study per ticker; SEC statements, ratios and scores"),
    Engine("rl", "Reinforcement-learning sizing", [], ["rl.json"], "rl.py", False, "Fitted Q iteration over trend, volatility, valuation and drawdown states, walk-forward from 1940"),
    Engine("portfolio", "Portfolio engine", [], ["portfolio.json"], "portfolio.py", False,
           "Stocks, Treasuries, gold and cash from a three-asset regime model, utility-optimal mixes in a risk budget, eight policies walked forward, "
           "a learner over policies, a regime-switching bootstrap of ten years and eight replayed drawdowns"),
    Engine("decide", "Decision engine", [], ["decision.json"], "decide.py", False,
           "Data to decision: stacked forecasts with a neural-network ensemble, hidden Markov regimes, changepoints, a Kalman stock-bond beta, "
           "dynamic model averaging, utility-optimal exposure inside a risk budget, an evidence gate, a hedge selector and a conservative RL check, walked forward from 1940"),
    Engine("bonds", "Bonds, simply", [], ["bonds.json"], "bondlab.py", False,
           "Every Treasury ETF repriced bond by bond on today's curve at any 10-year and 30-year yield; convexity, income, roll, break-evens; stocks per point of yield by inflation band"),
    Engine("feeds", "Noteworthy", [], ["feeds.json"], "feeds.py", False, "Feeds, heat, niche skew, lead time"),
    Engine("reason", "Solver and games", ["macro.json", "research.json", "brain.json", "capex.json", "report.json"], ["reason.json"], "reasoner.py", True,
           "Tempered Bayes, the constrained choice, the game against Nature, value of information, games", _reason),
    Engine("valuation", "Valuation and accounting", ["capex.json", "macro.json"], ["valuation.json"], "valuation.py", True,
           "Accounting quality, reverse DCF, base rates, irrationality and why, per position", _valuation),
    Engine("causal", "Causal statistics", ["brain.json"], ["causal.json"], "causal_stats.py", True,
           "Granger, partial correlations, crisis behaviour, tail dependence, lead-lag", _causal),
    Engine("hedges", "Hedge book", [], ["hedges.json"], "hedgebook.py", True, "Prebuilt hedges, priced and run through the scenarios; the advisor", _hedges),
    Engine("ooda", "Decision loop", ["macro.json", "research.json", "brain.json", "capex.json", "report.json"], ["ooda.json"], "ooda.py", True,
           "Observe, orient, decide, act: one decision record per position and hedge", _ooda),
    Engine("mind", "The mind", ["atlas.json", "labs.json", "research.json", "ml.json", "reality.json"], ["mind.json"], "mind.py", True,
           "One graph of the brain and the engine: concepts, markets, checked evidence, voices, engine modules, economies and signals", _mind),
    Engine("voices", "Investor voices", [], ["voices.json"], "voices.py", True, "Verified quotes, extreme bear to extreme bull; integrity checked on every run", _voices),
    Engine("status", "Run status", ["*"], ["status.json"], "status.py", True, "Freshness and sanity checks on every output", _status),
]


def _hash(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


TIMEOUTS = {"mind": 600.0, "reason": 600.0}


def tasks(only: list[str] | None = None) -> list:
    """The registry as runner tasks: offline engines with a function run; the rest are recorded as external."""
    from .core.runner import Task
    out = []
    for e in REGISTRY:
        runnable = e.offline and e.run is not None and (not only or e.name in only)
        out.append(Task(e.name, e.run if runnable else None, [r for r in e.reads if r != "*"], list(e.writes), timeout=TIMEOUTS.get(e.name, 300.0),
                        meta={"title": e.title, "module": e.module, "offline": e.offline, "does": e.does, "skipped": e.offline and not runnable}))
    return out


def run(out_dir, only: list[str] | None = None, jobs: int | None = None, isolate: bool = True) -> dict:
    """Run the offline engines through the core runner (parallel, isolated, contract-checked, last-good fallback)
    and write engines.json, the manifest the page and `status` read."""
    from .core import runner
    out = Path(out_dir)
    ts = tasks(only)
    res = runner.run(ts, out, jobs=jobs, isolate=isolate)
    rows = []
    for t in ts:
        r = res["tasks"].get(t.name, {})
        st = "skipped" if t.meta["skipped"] else ("external" if t.fn is None else r.get("status", "skipped"))
        row = {"name": t.name, "title": t.meta["title"], "module": t.meta["module"], "offline": t.meta["offline"], "does": t.meta["does"],
               "reads": t.reads, "writes": t.writes, "status": st, "outputs": r.get("outputs") or {w: _hash(out / w) for w in t.writes}}
        for k in ("seconds", "inputs", "error", "trace", "attempts", "contract", "kept_last_good", "stale_inputs"):
            if r.get(k) not in (None, [], {}):
                row[k] = r[k]
        rows.append(row)
    manifest = {"schema": 2, "version": __version__, "run_at": res["run_at"], "engines": rows,
                "ok": sum(r["status"] == "ok" for r in rows), "failed": sum(r["status"] in ("failed", "timeout", "rejected") for r in rows),
                "runner": {k: res[k] for k in ("jobs", "isolated", "wall_seconds", "serial_seconds", "speedup", "levels")}}
    _write(out, "engines.json", manifest)
    return manifest
