"""Decision policies: one specification, used by the recommendation, its explanation and the backtest.

Every policy has a stable id and a version. The page (site/src/engine7.js) implements the same functions and
tests/test_v07.py checks both languages at the boundaries, through the hysteresis and with missing inputs.

  hedge.tlt.v2        TLT on only while the stock-bond state is "hedging" and, where the research found a
                      reliable inflation line, 36-month inflation is below it
  size.equity.v2      equity scale = min(vol target / forecast vol, drawdown cap, max gross); Kelly is a check
  limits.portfolio.v1 total gross (equity + bond notional) and option premium capped after every hedge is added

A missing input never becomes a silent zero: the decision comes back "unavailable" with the input named.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

HEDGE_ID, SIZE_ID, LIMITS_ID = "hedge.tlt.v2", "size.equity.v2", "limits.portfolio.v1"
HEDGE_PARAMS = {"enter": -0.10, "exit": 0.0, "max_ratio": 1.0}
TEXT = {
    HEDGE_ID: ("Hold TLT at the minimum-variance ratio (capped at 1.0x) only while the stock-bond state is 'hedging' "
               "and, when the research has a reliable inflation line, 36-month inflation is below it. The state enters "
               "'hedging' when the correlation is at or below -0.10 and leaves only when it rises above 0."),
    SIZE_ID: ("Equity scale = the smallest of: volatility target / forecast volatility, the drawdown cap, and max gross. "
              "Quarter Kelly is reported beside it as an edge check: the excess return that would justify this size."),
    LIMITS_ID: ("After the hedge is added, equity plus bond notional may not exceed max total gross; if it does, equity "
                "and hedge are scaled down together. Option premium is capped as a share of NAV."),
}


def _fin(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def hedge_state(corrs: Iterable[float], prev: str = "neutral", enter: float = -0.10, exit: float = 0.0) -> list[str | None]:
    """Three states with hysteresis, one per correlation reading (None where the reading is missing).

    hedging     entered at corr <= enter, left only when corr > exit
    amplifying  entered at corr >= -enter, left only when corr < -exit
    neutral     otherwise
    """
    out, state = [], prev
    for c in corrs:
        if not _fin(c):
            out.append(None)
            continue
        if state == "hedging" and c > exit:
            state = "neutral"
        elif state == "amplifying" and c < -exit:
            state = "neutral"
        if state == "neutral":
            if c <= enter:
                state = "hedging"
            elif c >= -enter:
                state = "amplifying"
        out.append(state)
    return out


def tlt_decision(state: str | None, infl36: float | None, line: float | None, line_status: str = "ok",
                 mv_ratio: float | None = None, max_ratio: float = 1.0) -> dict:
    """The TLT decision with every gate visible. line_status is the research verdict on the inflation line."""
    gates = {"state": {"value": state, "pass": state == "hedging"}}
    blocked = []
    if state is None:
        blocked.append("stock-bond correlation unavailable")
    if line_status != "ok" or not _fin(line):
        gates["inflation"] = {"value": infl36, "line": None, "pass": None, "status": line_status if line_status != "ok" else "unavailable"}
    elif not _fin(infl36):
        gates["inflation"] = {"value": None, "line": line, "pass": None, "status": "input_unavailable"}
        blocked.append("36-month inflation unavailable")
    else:
        gates["inflation"] = {"value": infl36, "line": line, "pass": infl36 < line, "status": "ok"}
    if blocked:
        return {"policy": HEDGE_ID, "status": "unavailable", "on": None, "ratio": None, "gates": gates, "blocked": blocked}
    on = gates["state"]["pass"] and gates["inflation"]["pass"] is not False
    r = min(max(mv_ratio, 0.0), max_ratio) if (on and _fin(mv_ratio)) else (None if on else 0.0)
    return {"policy": HEDGE_ID, "status": "ok", "on": bool(on), "ratio": r, "gates": gates, "blocked": []}


def tlt_ratio_series(corr: pd.Series, mv_ratio: pd.Series, infl36: pd.Series | None = None, line: float | None = None,
                     max_ratio: float = 1.0, enter: float = -0.10, exit: float = 0.0) -> pd.Series:
    """The same policy, one value per day, for the backtest. infl36 must already be lagged to its publication date."""
    states = pd.Series(hedge_state(corr.to_numpy(), enter=enter, exit=exit), index=corr.index)
    on = states.eq("hedging")
    if infl36 is not None and _fin(line):
        gate = infl36.reindex(corr.index).ffill()
        on &= gate.lt(line).fillna(False)       # an unknown inflation reading never switches the hedge on
    r = mv_ratio.reindex(corr.index).clip(0, max_ratio)
    out = r.where(on, 0.0)
    out[corr.isna() | mv_ratio.reindex(corr.index).isna()] = np.nan
    return out.rename(HEDGE_ID)


def sizing_decision(vol_scale: float | None, dd_cap: float | None, max_gross: float, kelly_lev: float | None = None,
                    long_run_vol: float | None = None, kelly_fraction: float = 0.25) -> dict:
    cands = {"vol_target": vol_scale, "drawdown_cap": dd_cap, "max_gross": max_gross}
    missing = [k for k, v in cands.items() if not _fin(v)]
    if missing:
        return {"policy": SIZE_ID, "status": "unavailable", "scale": None, "binding": None, "candidates": cands,
                "blocked": [f"{k} unavailable" for k in missing]}
    binding = min(cands, key=lambda k: cands[k])
    scale = float(cands[binding])
    check = None
    if _fin(long_run_vol) and long_run_vol > 0:
        check = {"kelly_leverage": kelly_lev, "excess_return_needed": scale * long_run_vol ** 2 / kelly_fraction,
                 "kelly_supports_size": bool(_fin(kelly_lev) and kelly_lev >= scale)}
    return {"policy": SIZE_ID, "status": "ok", "scale": scale, "binding": binding, "candidates": cands,
            "kelly_check": check, "blocked": []}


def portfolio_limits(equity: float, hedge_ratio: float, premium: float = 0.0, max_total_gross: float = 2.0,
                     max_premium: float = 0.02) -> dict:
    """Equity notional, bond notional, total gross and net, after the portfolio-wide cap. Units: x NAV."""
    bond = equity * hedge_ratio
    gross = equity + bond
    k = min(1.0, max_total_gross / gross) if gross > 0 else 1.0
    prem = min(premium, max_premium)
    return {"policy": LIMITS_ID, "equity": equity * k, "bond": bond * k, "total_gross": gross * k, "net_long": (equity + bond) * k,
            "premium": prem, "scaled_by": k, "binding": [n for n, b in (("max_total_gross", k < 1), ("max_premium", premium > max_premium)) if b]}


def snapshot(*, as_of: str, hedge: dict, size: dict, limits: dict, inputs: dict, alternatives: Sequence[dict] = ()) -> dict:
    """A replayable decision record: policy ids, inputs with their dates, outputs, binding constraints, blockers."""
    return {"schema": 1, "as_of": as_of, "policies": {HEDGE_ID: TEXT[HEDGE_ID], SIZE_ID: TEXT[SIZE_ID], LIMITS_ID: TEXT[LIMITS_ID]},
            "inputs": inputs, "hedge": hedge, "size": size, "limits": limits, "alternatives": list(alternatives),
            "blocked": hedge.get("blocked", []) + size.get("blocked", [])}
