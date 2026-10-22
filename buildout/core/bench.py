"""`python -m buildout bench`: how fast the engine's hot paths are, measured the same way every release.

    mind      load and index the graph; answer five questions (median); a history and a yield question
    bonds     calibrate every fund on today's curve; one scenario; the 9 by 9 grid
    engine    the offline engines through the runner, with a warm cache
    page      the mind in the page's own JavaScript (node), when node is installed

Medians of repeated runs, in milliseconds. `--out DIR` writes bench.json.
"""
from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ["Is the stock market overvalued?", "Should I buy long bonds?", "Is AI a bubble?", "What if oil spikes, what happens to bonds?", "Does machine learning predict returns?"]


def _t(fn, n: int = 5) -> float:
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    return round(statistics.median(xs), 2)


def mind_bench() -> dict:
    from buildout import mind, voices
    t = time.perf_counter()
    G = json.loads((ROOT / "buildout" / "assets" / "mind.json").read_text())
    M = mind.Mind(G, voices.Library(voices.load()))
    init = (time.perf_counter() - t) * 1000
    M.think(QUESTIONS[0])                                   # first call builds the postings
    return {"nodes": len(G["nodes"]), "links": len(G["edges"]), "init_ms": round(init, 1),
            "think_ms": round(_t(lambda: [M.think(q) for q in QUESTIONS], 3) / len(QUESTIONS), 2),
            "history_ms": _t(lambda: M.think("What happened in 1974?")), "bonds_question_ms": _t(lambda: M.think("If the 10-year and 30-year both go to 4%, what is TLT?"))}


def bonds_bench() -> dict:
    from buildout import bondlab, mind
    curve, facts, _ = bondlab.from_knowledge(mind.load_knowledge())
    F = bondlab.setup(curve, facts)
    return {"setup_ms": _t(lambda: bondlab.setup(curve, facts), 3), "scenario_ms": _t(lambda: bondlab.scenario(curve, F, 0.04, 0.04)),
            "grid_ms": _t(lambda: bondlab.grid(curve, F["TLT"]), 3)}


def engine_bench() -> dict:
    from buildout import engine
    d = Path(tempfile.mkdtemp(prefix="buildout-bench-"))
    try:
        engine.run(d)                                       # warm the cache
        t = time.perf_counter()
        m = engine.run(d)
        return {"wall_s": round(time.perf_counter() - t, 2), "ok": m["ok"], "failed": m["failed"], **{k: m["runner"][k] for k in ("jobs", "serial_seconds", "speedup")}}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def page_bench() -> dict:
    node = shutil.which("node")
    h = ROOT / "site" / "tests" / "harness_bench.js"
    if not node or not h.exists():
        return {"skipped": "node or the harness is missing"}
    from buildout import voices
    req = {"voices": {"cfg": voices.config(), "lib": {"quotes": voices.load()}}, "mind": json.loads((ROOT / "buildout" / "assets" / "mind.json").read_text()), "questions": QUESTIONS}
    r = subprocess.run([node, str(h)], input=json.dumps(req), capture_output=True, text=True, timeout=300)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-300:]}


def run(skip_engine: bool = False) -> dict:
    out = {"mind": mind_bench(), "bonds": bonds_bench(), "page": page_bench()}
    if not skip_engine:
        out["engine"] = engine_bench()
    return out
