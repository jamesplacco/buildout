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


def _best(fn, n: int = 3) -> float:
    """The fastest of n runs, in milliseconds: the least disturbed by whatever else the machine is doing."""
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    return round(min(xs), 2)


def _loop_fb(B, pi, A):
    """The step-by-step forward-backward pass the engine used before v0.21, kept as the reference the scan is timed and
    checked against."""
    import numpy as np
    T, K = B.shape
    alpha = np.zeros((T, K))
    c = np.zeros(T)
    a = pi * B[0]
    c[0] = a.sum()
    alpha[0] = a / c[0]
    for t in range(1, T):
        a = (alpha[t - 1] @ A) * B[t]
        c[t] = a.sum()
        alpha[t] = a / c[t]
    beta = np.ones((T, K))
    for t in range(T - 2, -1, -1):
        beta[t] = (A @ (B[t + 1] * beta[t + 1])) / c[t + 1]
    g = alpha * beta
    return alpha, g / g.sum(1, keepdims=True), float(np.log(c).sum())


def matrix_bench(dl: dict | None = None) -> dict:
    """What the matrix shortcuts buy, measured the same way each release: the mind's spread one question at a time
    against all at once, think against think_many, the board, the spectral shortcut's speed and accuracy, and the HMM
    forward-backward as a loop against the doubling scan (with the largest difference between them)."""
    import numpy as np
    from buildout import infer, mind, voices
    out: dict = {}
    G = json.loads((ROOT / "buildout" / "assets" / "mind.json").read_text())
    M = mind.Mind(G, voices.Library(voices.load()))
    qs = [a["bull"] for a in G["axes"].values()]                # every claim the mind weighs, as the board asks them
    seeds = [s for s in (M.recall(q) for q in qs) if s]
    qs = [q for q in qs if M.recall(q)]
    M.spread(seeds[0])
    M.spread_many(seeds)
    one = _best(lambda: [M.spread(s) for s in seeds])
    many = _best(lambda: M.spread_many(seeds))
    R = M.spread_many(seeds)
    diff = max(float(np.abs(R[:, q] - np.array(M.spread(s))).max()) for q, s in enumerate(seeds))
    P = M.walk_matrix()
    out["mind"] = {"nodes": M.N, "nonzeros": int(P.nnz), "density": float(P.nnz / M.N ** 2), "questions": len(qs), "spread_one_by_one_ms": one, "spread_batched_ms": many,
                   "speedup": round(one / many, 1), "max_difference": diff}
    t1 = _best(lambda: [M.think(q) for q in qs])
    t2 = _best(lambda: M.think_many(qs))
    out["think"] = {"one_by_one_ms": t1, "batched_ms": t2, "speedup": round(t1 / t2, 1), "questions": len(qs)}
    t0 = time.perf_counter()
    board = M.board()
    out["board"] = {"axes": len(board), "ms": round((time.perf_counter() - t0) * 1000, 1)}
    t0 = time.perf_counter()
    M.spectral(64)
    build = round((time.perf_counter() - t0) * 1000, 1)
    ov, cr = [], []
    for s in seeds:
        f, e = np.array(M.spread_fast(s)), np.array(M.spread(s))
        ov.append(len(set(np.argsort(-f)[:20]) & set(np.argsort(-e)[:20])) / 20)
        cr.append(float(np.corrcoef(f, e)[0, 1]))
    out["spectral"] = {"k": 64, "build_ms": build, "fast_ms": _best(lambda: [M.spread_fast(s) for s in seeds]) / len(seeds), "exact_ms": one / len(seeds),
                       "top20_overlap": float(np.mean(ov)), "correlation": float(np.mean(cr))}
    rng = np.random.default_rng(1)
    if dl is not None:
        from buildout import labs
        r, _, _ = labs.total_return_index(labs.shiller(dl))
        x = r.to_numpy()
    else:
        x = rng.normal(0.005, 0.045, 1868)
    hm = []
    for K in (2, 3, 4):
        m = infer.hmm_fit(x, K, starts=1, iters=3)
        B = infer._norm_pdf(x, m["mu"], m["sd"]) + 1e-300
        B = B / B.max(1, keepdims=True)
        a1, g1, l1 = _loop_fb(B, m["pi"], m["A"])
        F = infer.forward_backward(B, m["pi"], m["A"])
        hm.append({"K": K, "months": len(x), "loop_ms": _best(lambda: _loop_fb(B, m["pi"], m["A"]), 7), "scan_ms": _best(lambda: infer.forward_backward(B, m["pi"], m["A"]), 7),
                   "max_difference": float(max(np.abs(a1 - F["alpha"]).max(), np.abs(g1 - F["gamma"]).max(), abs(l1 - float(F["loglik"]))))})
    out["hmm"] = hm
    return out


def run(skip_engine: bool = False) -> dict:
    out = {"mind": mind_bench(), "bonds": bonds_bench(), "page": page_bench(), "matrix": matrix_bench()}
    if not skip_engine:
        out["engine"] = engine_bench()
    return out
