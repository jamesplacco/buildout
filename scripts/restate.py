"""The record before and after a release, on the same prices (v0.48).

    python scripts/restate.py --base <commit> --version v0.48 --out site/data/restatement.json

Builds the walk-forward record twice from one pull of prices and one Treasury file: once with the code at --base
(checked out into a temporary worktree) and once with the code in this checkout. Writes what each policy's net
Sharpe ratio, CAGR, worst drawdown and yearly turnover were and are, and the gross worst drawdown, so the page can
say what a correction moved and by how much without anyone copying numbers by hand. Nothing in the ledger or the
published record is changed: the "after" is the record the daily run already publishes.

The daily run calls this once (when the output file does not exist yet), because raw prices and the Treasury file
live only in the run's cache. Needs the base commit in the local history (`git fetch --depth=1 origin <commit>`).
"""
from __future__ import annotations

import argparse
import json
import pickle
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BUILD = """
import json, pickle, sys
sys.path.insert(0, sys.argv[1])
from buildout import book as bk, ledger, track
D = pickle.load(open(sys.argv[2], "rb"))
o = bk._clean(track.build(D["prices"], D["ust"], None, ledger.read(D["ledger"])))
json.dump(o, open(sys.argv[3], "w"))
"""
METRICS = ("sharpe", "cagr", "maxdd")


def compare(old: dict, new: dict) -> dict:
    mv = {}
    for k, v in new["pit"]["policies"].items():
        a = old.get("pit", {}).get("policies", {}).get(k)
        if not a:
            continue
        mv[k] = {m: [a["net"][m], v["net"][m]] for m in METRICS}
        mv[k]["turnover"] = [a["meta"].get("turnover_yr"), v["meta"].get("turnover_yr")]
        mv[k]["gross_maxdd"] = [a["gross"]["maxdd"], v["gross"]["maxdd"]]
    moves = lambda keys, m: max((abs(mv[k][m][1] - mv[k][m][0]) for k in keys), default=0.0)
    unhedged = [k for k in mv if k != "call_short"]
    return {"policies": mv, "max_sharpe_move": moves(mv, "sharpe"), "max_sharpe_move_unhedged": moves(unhedged, "sharpe"),
            "max_maxdd_move": moves(unhedged, "maxdd"), "max_gross_maxdd_move": moves(unhedged, "gross_maxdd")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="the commit whose code made the record being corrected")
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default=".cache/book")
    ap.add_argument("--inputs", help="a pickle of {prices, ust} to use instead of pulling (for tests)")
    a = ap.parse_args()
    from buildout import book as bk, ledger, track
    if a.inputs:
        D = pickle.loads(Path(a.inputs).read_bytes())
        prices, ust = D["prices"], D["ust"]
    else:
        universe = {**bk.BOOK, **{t.upper(): 0.0 for t in track.CANDIDATES}}
        prices = bk.download(Path(a.cache), book=universe)
        ust = bk.treasury()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        inputs = tmp / "inputs.pkl"
        with inputs.open("wb") as fh:
            pickle.dump({"prices": dict(prices), "ust": ust, "ledger": str(ledger.PATH)}, fh)
        wt = tmp / "base"
        subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(wt), a.base], check=True, capture_output=True)
        try:
            outs = {}
            for name, root in (("before", wt), ("after", ROOT)):
                f = tmp / f"{name}.json"
                subprocess.run([sys.executable, "-c", BUILD, str(root), str(inputs), str(f)], check=True, cwd=str(root))
                outs[name] = json.loads(f.read_text())
        finally:
            subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(wt)], capture_output=True)
    new = outs["after"]
    o = {"schema": 1, "version": a.version, "date": datetime.now(timezone.utc).date().isoformat(), "base": a.base,
         "asof": new.get("asof"), "computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "same_inputs": "one pull of every candidate's prices and one Treasury file, both runs", **compare(outs["before"], new),
         "live_rule": {k: new.get("live_rule", {}).get(k) for k in ("months", "fallbacks", "high_end_below_full_size", "high_end_max_total_gross", "total_gross_limit")}}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(o, indent=1))
    print("wrote", a.out, {k: [round(x, 4) for x in v["sharpe"]] for k, v in o["policies"].items()})


if __name__ == "__main__":
    main()
