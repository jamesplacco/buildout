"""Prebuilt hedges for the book, each one switchable, sized, costed and run through the same seven 3-month scenarios
as the solver (reasoner.SCENARIOS). The page runs the same arithmetic (site/src/hedgebook.js); tests/test_v11.py
checks they agree.

Every hedge returns its own P&L per scenario as a fraction of NAV, so the book's return is the sum of the book and
whatever is switched on. Pricing uses Black-Scholes at the scenario set's VIX plus skew for index options and a
lognormal VIX with 100% volatility of volatility for VIX calls (stated assumptions, not quotes).

  tlt         long-bond hedge at a ratio of equity (duration and convexity, financed at cash)
  put_spread  QQQ 95/85 put spread, a premium budget as a share of NAV
  collar      buy the 90 put, sell the 110 call on part of the equity: cheap protection that caps the upside
  gold        a gold sleeve financed from cash
  vix_calls   VIX 25/40 call spread: pays in the crash, costs a little every quiet quarter
  beta_short  short index futures against part of the market beta (keeps the AI-specific exposure)
  ai_pair     short a semiconductor basket against the AI factor (keeps the market exposure)
  trend       cut equity by half after the index falls 8% within the quarter; fills lag, so only 60% of the rest of the
              fall is avoided, and false signals cost 1% a quarter otherwise (path-dependent: an approximation)
  degross     run less equity, hold the rest in cash
  advisor     every on/off combination at the chosen sizes: the cheapest set that meets the loss limit, the best
              growth, and the best worst case
"""
from __future__ import annotations

import math
from itertools import product
from typing import Sequence

from .analytics.options import bs
from .reasoner import DEFAULTS, SCENARIOS, bond_return

HEDGES = [
    {"id": "tlt", "name": "Long Treasuries (TLT)", "param": "ratio", "default": 0.3, "range": [0.0, 1.0], "unit": "x equity",
     "protects": ["soft", "digest"], "nodes": ["y10", "tlt"], "door": "two-way", "note": "Fails when stocks and bonds fall together (2022, term-premium shocks)."},
    {"id": "put_spread", "name": "Index put spread 95/85", "param": "premium", "default": 0.01, "range": [0.0, 0.03], "unit": "of NAV",
     "protects": ["termprem", "digest", "stagfl", "crash"], "nodes": ["eq", "vix"], "door": "two-way", "note": "Pays between 5% and 15% falls; nothing beyond."},
    {"id": "collar", "name": "Collar 90/110", "param": "share", "default": 0.5, "range": [0.0, 1.0], "unit": "of equity",
     "protects": ["digest", "stagfl", "crash"], "nodes": ["eq"], "door": "two-way", "note": "Close to free; gives up gains above 10% in a melt-up."},
    {"id": "gold", "name": "Gold sleeve", "param": "weight", "default": 0.05, "range": [0.0, 0.2], "unit": "of NAV",
     "protects": ["termprem", "stagfl"], "nodes": ["gold", "dollar"], "door": "two-way", "note": "Hedges inflation and policy shocks; can fall in a liquidity crash."},
    {"id": "vix_calls", "name": "VIX call spread 25/40", "param": "premium", "default": 0.005, "range": [0.0, 0.02], "unit": "of NAV",
     "protects": ["crash", "digest"], "nodes": ["vix"], "door": "two-way", "note": "Convex in a crash; decays in calm quarters."},
    {"id": "beta_short", "name": "Short index futures", "param": "share", "default": 0.25, "range": [0.0, 1.0], "unit": "of market beta",
     "protects": ["termprem", "digest", "stagfl", "crash"], "nodes": ["eq"], "door": "two-way", "note": "Linear: costs upside one for one; keeps the AI bet."},
    {"id": "ai_pair", "name": "Short semiconductor basket", "param": "weight", "default": 0.15, "range": [0.0, 0.5], "unit": "of NAV",
     "protects": ["digest", "termprem"], "nodes": ["aidemand", "capex", "NVDA", "AVGO"], "door": "two-way", "note": "Hedges an AI-capex digestion; basis risk if the book's names diverge from the basket."},
    {"id": "trend", "name": "Trend cut", "param": "cut", "default": 0.5, "range": [0.0, 1.0], "unit": "of equity",
     "protects": ["digest", "stagfl", "crash"], "nodes": ["eq"], "door": "two-way", "note": "Cuts after an 8% fall and avoids about 60% of the rest; false signals cost about 1% a quarter (Assumed)."},
    {"id": "degross", "name": "Run less equity", "param": "cut", "default": 0.2, "range": [0.0, 0.8], "unit": "of equity",
     "protects": ["termprem", "digest", "stagfl", "crash"], "nodes": ["eq"], "door": "two-way", "note": "The simplest hedge: less of everything, cash earns the rate."},
]
HEDGE_IDS = [h["id"] for h in HEDGES]
RUNNING_BP = 5.0    # Assumed: execution, rolling and monitoring cost per hedge per quarter, so simpler sets win ties
ASSUMED = {"smh_beta_market": 1.3, "smh_beta_ai": 1.5, "vix0": 18.0, "vix_vol": 1.0, "vix_term": 1.5, "vix_per_market": 90.0,
           "trend_trigger": -0.08, "trend_whipsaw": 0.01, "trend_capture": 0.6, "call_skew": -2.0, "put_skew": 3.0}


def _P(P: dict | None) -> dict:
    return {**DEFAULTS, **(P or {})}


def vix_end(s: dict, vix0: float) -> float:
    return max(9.0, vix0 - ASSUMED["vix_per_market"] * s["market"])


def option_costs(P: dict) -> dict:
    v = P["vix"] / 100
    T = P["horizon"]
    put95 = bs(1.0, 0.95, T, 0.0, 0.0, v + ASSUMED["put_skew"] / 100, "put")["price"]
    put85 = bs(1.0, 0.85, T, 0.0, 0.0, v + ASSUMED["put_skew"] / 100, "put")["price"]
    put90 = bs(1.0, 0.90, T, 0.0, 0.0, v + ASSUMED["put_skew"] / 100, "put")["price"]
    call110 = bs(1.0, 1.10, T, 0.0, 0.0, max(0.05, v + ASSUMED["call_skew"] / 100), "call")["price"]
    F = P["vix"] + ASSUMED["vix_term"]
    vc = bs(F, 25.0, T, 0.0, 0.0, ASSUMED["vix_vol"], "call")["price"] - bs(F, 40.0, T, 0.0, 0.0, ASSUMED["vix_vol"], "call")["price"]
    return {"put_spread": put95 - put85, "collar_net": put90 - call110, "vix_spread": vc}


def hedge_pnl(hid: str, x: float, e: float, s: dict, P: dict, costs: dict) -> float:
    """P&L of one hedge at size x in scenario s, as a fraction of NAV, for equity exposure e (x NAV)."""
    m = 1 + s["market"]
    cash = P["rf"] * P["horizon"]
    stock = P["beta_market"] * s["market"] + P["beta_ai"] * s["ai"]
    if hid == "tlt":
        return e * x * (bond_return(s["dy"], P) - cash)
    if hid == "put_spread":
        c = costs["put_spread"]
        pay = max(0.0, 0.95 - m) - max(0.0, 0.85 - m)
        return (x / c) * pay - x if c > 0 else 0.0
    if hid == "collar":
        n = x * e
        return n * (max(0.0, 0.90 - m) - max(0.0, m - 1.10) - costs["collar_net"])
    if hid == "gold":
        return x * (s["gold"] - cash)
    if hid == "vix_calls":
        c = costs["vix_spread"]
        v = vix_end(s, P["vix"])
        pay = min(max(v - 25.0, 0.0), 15.0)
        return (x / c) * pay - x if c > 0 else 0.0
    if hid == "beta_short":
        return -x * e * P["beta_market"] * s["market"]
    if hid == "ai_pair":
        return -x * (ASSUMED["smh_beta_market"] * s["market"] + ASSUMED["smh_beta_ai"] * s["ai"])
    if hid == "trend":
        trig = ASSUMED["trend_trigger"]
        if s["market"] >= trig:
            return -x * e * ASSUMED["trend_whipsaw"]
        frac_after = (s["market"] - trig) / s["market"]            # share of the fall after the trigger
        cap = ASSUMED["trend_capture"]                              # fills lag and gaps: only part of it is avoided
        return -x * e * (stock * frac_after * cap - cash * 0.5) - x * e * ASSUMED["trend_whipsaw"]
    if hid == "degross":
        return -x * e * (stock - cash)
    raise ValueError(hid)


def book_pnl(e: float, s: dict, P: dict) -> float:
    """The unhedged book at equity e: stocks on e x NAV, cash (or borrowing) on the rest."""
    stock = P["beta_market"] * s["market"] + P["beta_ai"] * s["ai"]
    cash = 1 - e
    return e * stock + cash * (P["rf"] + (P["borrow_spread"] if cash < 0 else 0.0)) * P["horizon"]


def evaluate(on: dict[str, float], e: float, post: Sequence[float], P: dict | None = None, scen=SCENARIOS) -> dict:
    """on: hedge id -> size (only switched-on hedges). Returns scenario returns, growth, worst case and cost."""
    P = _P(P)
    costs = option_costs(P)
    base = [book_pnl(e, s, P) for s in scen]
    parts = {h: [hedge_pnl(h, x, e, s, P, costs) for s in scen] for h, x in on.items() if x}
    rets = [b + sum(p[i] for p in parts.values()) for i, b in enumerate(base)]
    elog = sum(w * math.log1p(max(r, -0.999999)) for w, r in zip(post, rets))
    mean = sum(w * r for w, r in zip(post, rets))
    base_mean = sum(w * r for w, r in zip(post, base))
    return {"rets": rets, "base": base, "parts": parts, "ce": math.expm1(elog), "elog": elog, "mean": mean, "worst": min(rets),
            "cost_bp": (base_mean - mean) * 1e4, "worst_gain": min(rets) - min(base),
            "contrib": {h: {"mean_bp": sum(w * r for w, r in zip(post, p)) * 1e4, "worst_scenario": p[base.index(min(base))]} for h, p in parts.items()}}


def advisor(sizes: dict[str, float], e: float, post: Sequence[float], P: dict | None = None, max_loss: float | None = None,
            allowed: Sequence[str] | None = None, top: int = 5) -> dict:
    """Every on/off combination of the allowed hedges at the given sizes."""
    P = _P(P)
    L = P["max_loss"] if max_loss is None else max_loss
    ids = [h for h in (allowed or HEDGE_IDS) if sizes.get(h)]
    rows = []
    for mask in product((0, 1), repeat=len(ids)):
        on = {h: sizes[h] for h, b in zip(ids, mask) if b}
        r = evaluate(on, e, post, P)
        rows.append({"on": sorted(on), "ce": r["ce"], "worst": r["worst"], "cost_bp": r["cost_bp"], "meets": r["worst"] >= -L - 1e-12,
                     "all_in_bp": r["cost_bp"] + RUNNING_BP * len(on)})
    meets = [r for r in rows if r["meets"]]
    cheapest = sorted(meets, key=lambda r: (r["all_in_bp"], -r["ce"], len(r["on"]), r["on"]))[:top]
    growth = sorted(rows, key=lambda r: (-r["ce"], len(r["on"]), r["on"]))[:top]
    safest = sorted(rows, key=lambda r: (-r["worst"], -r["ce"], len(r["on"]), r["on"]))[:top]
    return {"combinations": len(rows), "meets_limit": len(meets), "loss_limit": L, "cheapest_meeting_limit": cheapest,
            "best_growth": growth, "best_worst_case": safest}


def catalog(P: dict | None = None) -> list[dict]:
    P = _P(P)
    c = option_costs(P)
    out = []
    for h in HEDGES:
        d = dict(h)
        if h["id"] == "put_spread":
            d["price"] = c["put_spread"]
        elif h["id"] == "collar":
            d["price"] = c["collar_net"]
        elif h["id"] == "vix_calls":
            d["price"] = c["vix_spread"]
        out.append(d)
    return out
