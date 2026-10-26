"""Calibration of the filings engine's test (v0.28), written to buildout/assets/filings_calibration.json:

  worlds   independent synthetic universes with NO planted edge (factor structure, random insider trades, a dual
           class, a split, turnover): the share of signal tests and of random signals below p = 0.05, for the
           engine's p (from the monthly IC series) and for a reassignment permutation
  sparse   random flags at several frequencies (the shape of insider signals) through ic_p, with the engine's
           MIN_GROUP rule

Derived numbers only, no market data. About ten minutes:
    python scripts/calibrate_filings.py [--worlds 8] [--reuse log-of-an-earlier-run]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from buildout import filings as F  # noqa: E402


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
        d = F.synthetic_inputs(edge=0.0, seed=100 + w)
        o = F.build(d["members"], d["cik_of"], d["ticker_of"], d["tx"], d["facts"], d["px"], n_perm=100, n_fake=20, splits=d["splits"], seed=500 + w)
        T = o["tests"]
        out.append({"world": w, "tests": len(T), "tests_p_below_05": float(np.mean([t["p"] <= 0.05 for t in T])),
                    "tests_reassign_p_below_05": float(np.mean([(t["p_reassign"] or 1) <= 0.05 for t in T])),
                    "tests_passing_cut": int(sum(t["pass_bh"] for t in T)), "fakes": o["fakes"]})
        print(json.dumps(out[-1]), flush=True)
    return out


def sparse(sims: int = 300) -> list[dict]:
    rng = np.random.default_rng(7)
    T, N = 130, 160
    out = []
    for rate in (0.03, 0.08, 0.3):
        ps = []
        for k in range(sims):
            g, f = rng.normal(size=N), rng.normal(0, 0.035, size=T)
            ret = f[:, None] * g[None, :] + 0.045 * rng.normal(size=(T, 1)) + 0.06 * rng.normal(size=(T, N))
            flag = (rng.random((T, N)) < rate).astype(float)
            ic = F._ic_rows(F._rank_rows(flag), F._rank_rows(ret))
            ic[np.minimum(flag.sum(1), N - flag.sum(1)) < F.MIN_GROUP] = np.nan        # the engine's rule: enough stocks off the commonest value
            ps.append(F.ic_p(ic[np.isfinite(ic)], seed=k)["p"])
        ok = np.array([x for x in ps if x is not None])            # a run with too few testable months is not tested, as in the engine
        out.append({"flag_rate": rate, "sims": sims, "tested": int(len(ok)), "share_p_below_05": float(np.mean(ok <= 0.05)) if len(ok) else None,
                    "share_p_below_01": float(np.mean(ok <= 0.01)) if len(ok) else None})
        print(json.dumps(out[-1]), flush=True)
    return out


def _avg(rows: list[dict], key: str) -> float | None:
    rows = [r for r in rows if r.get(key) is not None]
    return float(np.average([r[key] for r in rows], weights=[r["n"] for r in rows])) if rows else None


def main(argv: list[str]) -> None:
    n = int(argv[argv.index("--worlds") + 1]) if "--worlds" in argv else 8
    reuse = Path(argv[argv.index("--reuse") + 1]) if "--reuse" in argv else None
    W, S = worlds(n, reuse), sparse()
    kinds = lambda k: [w["fakes"]["by_kind"][k] for w in W if k in (w["fakes"].get("by_kind") or {})]
    tilt, noise = kinds("factor tilt"), kinds("persistent noise")
    nt = [w["tests"] for w in W]
    out = {"schema": 1, "worlds": W, "sparse": S,
           "pooled": {"worlds": n, "tests": int(sum(nt)),
                      "tests_p_below_05": float(np.average([w["tests_p_below_05"] for w in W], weights=nt)),
                      "tests_reassign_p_below_05": float(np.average([w["tests_reassign_p_below_05"] for w in W], weights=nt)),
                      "tests_passing_cut": int(sum(w["tests_passing_cut"] for w in W)),
                      "factor_tilt_p_below_05": _avg(tilt, "share_p_below_05"), "factor_tilt_reassign_p_below_05": _avg(tilt, "share_reassign_p_below_05"),
                      "factor_tilt_effective_n_per_world": _avg(tilt, "effective_n"),
                      "persistent_noise_p_below_05": _avg(noise, "share_p_below_05"), "random_signals": int(sum(t["n"] for t in tilt + noise))}}
    p = ROOT / "buildout" / "assets" / "filings_calibration.json"
    p.write_text(json.dumps(out, indent=1) + "\n")
    print("wrote", p, json.dumps(out["pooled"]))


if __name__ == "__main__":
    main(sys.argv[1:])
