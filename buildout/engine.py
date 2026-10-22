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
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    Engine("research", "Long-history research", [], ["research.json"], "research.py", False, "155 years: the hedge line out of sample, fat tails, base rates"),
    Engine("brain", "Brain links", [], ["brain.json"], "brain.py", False, "Measured links by regime, the series, structure learning, robust links, self-checks (conformal, stacking, robustness values)"),
    Engine("book", "Book run", ["research.json"], ["report.json"], "pipeline.py", False, "Databento: exposures, regime, hedge, sizing, VaR, stress, backtest, robustness"),
    Engine("capex", "Fundamentals", [], ["capex.json"], "fundamentals.py", False, "SEC XBRL: TTM cash flows, capex, debt, depreciation paths"),
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
    Engine("voices", "Investor voices", [], ["voices.json"], "voices.py", True, "Verified quotes, extreme bear to extreme bull; integrity checked on every run", _voices),
    Engine("status", "Run status", ["*"], ["status.json"], "status.py", True, "Freshness and sanity checks on every output", _status),
]


def _hash(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def run(out_dir, only: list[str] | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for e in REGISTRY:
        row = {"name": e.name, "title": e.title, "module": e.module, "offline": e.offline, "does": e.does, "reads": e.reads, "writes": e.writes}
        if not e.offline or e.run is None or (only and e.name not in only):
            row.update({"status": "external" if not e.offline else "skipped", "outputs": {w: _hash(out / w) for w in e.writes}})
            rows.append(row)
            continue
        ins = {r: _hash(out / r) for r in e.reads if r != "*"}
        t0 = time.perf_counter()
        try:
            e.run(out)
            row["status"] = "ok"
        except Exception as exc:                       # isolated: one engine failing never stops the others
            row.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300], "trace": traceback.format_exc()[-800:]})
        row.update({"seconds": round(time.perf_counter() - t0, 3), "inputs": ins, "outputs": {w: _hash(out / w) for w in e.writes}})
        rows.append(row)
    manifest = {"schema": 1, "version": __version__, "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engines": rows,
                "ok": sum(r["status"] == "ok" for r in rows), "failed": sum(r["status"] == "failed" for r in rows)}
    _write(out, "engines.json", manifest)
    return manifest
