"""Calibration of the futures engine's test (v0.29), written to buildout/assets/futures_calibration.json: independent
synthetic worlds with NO planted edge (market and sector factors, persistent carry, random hedgers' positions), each
run through the whole engine. The share of the twelve signal tests (and of the random signals) below p = 0.05 is the
false-alarm rate; an honest test gives about 5%. Random signals also run on 30 more worlds, ten a world. Derived
numbers only, no market data. About fifteen minutes:

    python scripts/calibrate_futures.py [--worlds 20] [--reuse log-of-an-earlier-run]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from buildout import futures as Fu  # noqa: E402


def worlds(n: int, reuse: Path | None = None) -> list[dict]:
    """Each world is deterministic in its seed, so results printed by an earlier run of this same code can be reused."""
    done = {}
    if reuse and reuse.exists():
        for line in reuse.read_text().splitlines():
            if line.startswith('{"world"'):
                r = json.loads(line)
                done[r["world"]] = r
    out = []
    for w in range(n):
        if w in done:
            out.append(done[w])
            continue
        frames, cot = Fu.synthetic_frames(edge=0.0, seed=200 + w)
        o = Fu.build(frames, cot, n_fake=10, seed=600 + w)
        T = o["tests"]
        out.append({"world": w, "tests": len(T), "tests_p_below_05": float(np.mean([t["p"] <= 0.05 for t in T])),
                    "tests_passing_cut": int(sum(t["pass_bh"] for t in T)), "supported": int(sum(t["supported"] for t in T)),
                    "by_design": {d: float(np.mean([t["p"] <= 0.05 for t in T if t["design"] == d])) for d in Fu.DESIGNS},
                    "fakes": o["fakes"]})
        print(json.dumps(out[-1]), flush=True)
    return out


def fake_worlds(n: int = 30, per: int = 10) -> list[dict]:
    """Random persistent signals on further worlds with no edge, ten a world: the false-alarm rate of the test itself
    needs many worlds, because signals that share one world's returns are not independent draws."""
    out = []
    for w in range(n):
        frames, cot = Fu.synthetic_frames(edge=0.0, seed=3000 + w)
        P = Fu.month_panel(frames, cot)
        P = P[P["month"] >= Fu.pd.Timestamp(Fu.START) - Fu.pd.DateOffset(years=2)]
        f = Fu.fake_runs(P, per, 4000 + w)
        out.append({"world": w, "runs": f["runs"], "xs": f["xs"]["share_p_below_05"], "ts": f["ts"]["share_p_below_05"], "all": f["share_p_below_05"]})
        print(json.dumps(out[-1]), flush=True)
    return out


def main(argv: list[str]) -> None:
    n = int(argv[argv.index("--worlds") + 1]) if "--worlds" in argv else 8
    reuse = Path(argv[argv.index("--reuse") + 1]) if "--reuse" in argv else None
    W = worlds(n, reuse)
    FW = fake_worlds()
    nt = [w["tests"] for w in W]
    fr = [w["fakes"] for w in W if w["fakes"].get("runs")] + [{"runs": f["runs"], "share_p_below_05": f["all"]} for f in FW]
    out = {"schema": 1, "worlds": W, "fake_worlds": FW,
           "pooled": {"worlds": n, "tests": int(sum(nt)), "tests_p_below_05": float(np.average([w["tests_p_below_05"] for w in W], weights=nt)),
                      "tests_passing_cut": int(sum(w["tests_passing_cut"] for w in W)), "supported": int(sum(w["supported"] for w in W)),
                      "fake_runs": int(sum(f["runs"] for f in fr)), "fake_worlds": n + len(FW),
                      "fakes_p_below_05": float(np.average([f["share_p_below_05"] for f in fr], weights=[f["runs"] for f in fr])) if fr else None}}
    p = ROOT / "buildout" / "assets" / "futures_calibration.json"
    p.write_text(json.dumps(out, indent=1) + "\n")
    print("wrote", p, json.dumps(out["pooled"]))


if __name__ == "__main__":
    main(sys.argv[1:])
