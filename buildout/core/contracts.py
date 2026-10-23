"""Output contracts: what each engine file must look like before the page or another engine may read it.

A contract is a small declarative spec checked after an engine writes its file:

    "bonds.json": C(required=["curve", "funds", "cases"], finite=["curve.10y", "funds.TLT.duration"],
                    ranges={"curve.10y": (0, 0.25)}, nonempty=["funds"])

`check(path)` returns a list of problems (empty when the file honours its contract). The runner rejects a file that
breaks its contract and restores the last good copy, so a bad run degrades to yesterday's numbers instead of breaking
the page. Every number in a written file must be finite (the writer refuses NaN and infinity), and every file carries
the schema stamp.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class C:
    required: list[str] = field(default_factory=list)      # dotted paths that must exist
    nonempty: list[str] = field(default_factory=list)      # paths to non-empty lists or dicts
    finite: list[str] = field(default_factory=list)        # paths to finite numbers
    ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    schema: bool = True                                    # the writer's {"schema": n} stamp


CONTRACTS: dict[str, C] = {
    "valuation.json": C(required=["as_of"]),
    "causal.json": C(required=["findings"]),
    "hedges.json": C(required=["catalog"], nonempty=["catalog"]),
    "ooda.json": C(),
    "reason.json": C(),
    "mind.json": C(required=["nodes", "edges", "signals", "axes", "params"], nonempty=["nodes", "edges"], schema=False),
    "voices.json": C(required=["quotes", "topics"], nonempty=["quotes"]),
    "status.json": C(),
    "bonds.json": C(required=["curve", "funds", "cases", "breakeven"], nonempty=["funds"], finite=["curve.10y", "curve.30y", "funds.TLT.duration", "funds.TLT.coupon"],
                    ranges={"curve.10y": (0.0, 0.25), "curve.30y": (0.0, 0.25), "funds.TLT.duration": (5.0, 30.0)}),
    "ml.json": C(required=["return", "crash"]),
    "rl.json": C(required=["configs", "best", "hold"]),
    "portfolio.json": C(required=["now", "perf", "simulation", "stress", "findings"], nonempty=["findings", "stress"],
                        finite=["now.gate", "gamma"], ranges={"now.gate": (0.0, 1.0), "gamma": (0.5, 30.0)}),
    "geometry.json": C(required=["covariance", "transport", "paths", "scaling", "compounding", "engine_model", "tests", "findings"], nonempty=["tests", "findings"],
                       finite=["engine_model.t", "scaling.all"], ranges={"scaling.all": (0.0, 1.5)}),
    "decision.json": C(required=["now", "pipeline", "configs", "hold", "findings"], nonempty=["pipeline", "findings"],
                       finite=["now.exposure", "now.engine_exposure", "now.gate.value", "gamma"],
                       ranges={"now.exposure": (0.0, 1.5), "now.engine_exposure": (0.0, 1.5), "now.gate.value": (0.0, 1.0), "gamma": (0.5, 30.0)}),
    "complexity.json": C(required=["sweep", "information", "conclusions"], nonempty=["conclusions"]),
    "engines.json": C(required=["engines"]),
}


def get_path(obj: Any, path: str) -> tuple[bool, Any]:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def _nonfinite(o: Any, where: str = "", out: list | None = None) -> list[str]:
    out = [] if out is None else out
    if len(out) >= 5:
        return out
    if isinstance(o, float) and not math.isfinite(o):
        out.append(where or "(root)")
    elif isinstance(o, dict):
        for k, v in o.items():
            _nonfinite(v, f"{where}.{k}" if where else str(k), out)
    elif isinstance(o, list):
        for i, v in enumerate(o[:5000]):
            _nonfinite(v, f"{where}[{i}]", out)
    return out


def check_obj(name: str, obj: Any, spec: C | None = None) -> list[str]:
    spec = spec or CONTRACTS.get(name, C(schema=False))
    bad: list[str] = []
    if not isinstance(obj, dict):
        return [f"{name}: the top level is {type(obj).__name__}, not an object"]
    if spec.schema and "schema" not in obj:
        bad.append(f"{name}: no schema stamp")
    for p in spec.required:
        if not get_path(obj, p)[0]:
            bad.append(f"{name}: missing {p}")
    for p in spec.nonempty:
        ok, v = get_path(obj, p)
        if ok and not v:
            bad.append(f"{name}: {p} is empty")
    for p in spec.finite:
        ok, v = get_path(obj, p)
        if ok and not (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)):
            bad.append(f"{name}: {p} is not a finite number ({v!r})")
    for p, (lo, hi) in spec.ranges.items():
        ok, v = get_path(obj, p)
        if ok and isinstance(v, (int, float)) and not (lo <= v <= hi):
            bad.append(f"{name}: {p} = {v} outside [{lo}, {hi}]")
    bad += [f"{name}: non-finite number at {w}" for w in _nonfinite(obj)]
    return bad


def check(path: str | Path, spec: C | None = None) -> list[str]:
    p = Path(path)
    if not p.exists():
        return [f"{p.name}: missing"]
    try:
        obj = json.loads(p.read_text(), parse_constant=lambda c: float(c))
    except (ValueError, OSError) as exc:
        return [f"{p.name}: not valid JSON ({exc})"[:200]]
    return check_obj(p.name, obj, spec)
