"""The decision loop: Observe, Orient, Decide, Act (Boyd), as one record the page renders and the journal can keep.

    python -m buildout ooda --out site/data            # writes ooda.json from the other daily files

  Observe   what the data says now: the brain's readings, how surprising they are for the map, which world they fit,
            what moved most, and how fresh each input is
  Orient    what it means: competing explanations and the joint inference, how fragile the key link is, what hedges
            did in stocks' worst months in this regime, and what each position's price requires against the base
            rates, with the accounting under it
  Decide    the solver's choice with and without doubt about its odds, the hedge book (what is switched on, what the
            advisor would switch on to meet the loss limit at least cost), and an action for every position, each
            run through the same decision frameworks: outside view, inside view, pre-mortem, margin of safety,
            reversibility and kill criteria
  Act       proposals only (never orders): position changes, hedge switches, what to watch, and when to look again

Every rule below is stated in code and labelled; none is a forecast. The engine decides nothing a person has not
reviewed.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from . import causal_stats, hedgebook, reasoner, thinking, valuation
from .config import default_config, load_config

ASSETS = Path(__file__).resolve().parent / "assets"
FRAMEWORKS = {
    "outside_view": "Base rates first: how often have companies this size done what the price requires? (Kahneman, Mauboussin)",
    "inside_view": "Then the company's own record: its growth, margins and the quality of its earnings.",
    "pre_mortem": "Assume the decision failed a year from now and name the most likely reason (Klein).",
    "margin_of_safety": "Price against value at a generous base-rate outcome (the 90th percentile of growth for its size).",
    "reversibility": "Two-way doors can be decided fast and undone; one-way doors deserve the slow process (Bezos).",
    "kill_criteria": "Write down in advance what would prove the decision wrong, and act on it when it happens (Duke).",
    "ooda": "Observe, orient, decide, act, and loop faster than conditions change (Boyd).",
}


def _load(folder, name):
    try:
        return json.loads((Path(folder) / f"{name}.json").read_text())
    except (OSError, ValueError, TypeError):
        return None


def positions_snapshot() -> dict:
    return json.loads((ASSETS / "positions.json").read_text())


def merged_fundamentals(snap: dict, capex: dict | None) -> dict:
    """The researched snapshot, with any field the daily SEC run reports newer replacing it."""
    out = {t: dict(v) for t, v in snap["ttm"].items()}
    ttm = (capex or {}).get("ttm") or {}
    keymap = {"revenue": "revenue", "ocf": "ocf", "capex": "capex", "da": "da", "op_income": "op_income", "net_income": "net_income", "sbc": "sbc",
              "interest": "interest", "debt": "debt", "cash_total": "cash"}
    for t, row in ttm.items():
        if t not in out or not isinstance(row, dict):
            continue
        newer = str(row.get("quarter_end") or "") > str(out[t].get("period_end") or "")
        if not newer:
            continue
        for src, dst in keymap.items():
            v = row.get(src)
            if isinstance(v, (int, float)) and math.isfinite(v):
                out[t][dst] = v
        out[t]["period_end"] = row.get("quarter_end")
        out[t]["refreshed_from_sec"] = True
    return out


def position_action(t: str, w: float, val: dict, max_name: float = 0.25) -> dict:
    """One position through the frameworks. Rules, stated: the outside view (base rates) sets the direction and the inside
    view (the company's own growth and accounting) sets the size. A price outside 99% of base-rate outcomes trims half,
    or a quarter if the company is already growing faster than the price needs and its accounting is not weak. A price
    outside 95% holds and leans on the hedges, unless the accounting is weak and growth is slower than required, which
    trims a quarter. A pessimistic price on decent accounting is an add candidate, up to a quarter more within the 25%
    single-name cap."""
    v = (val.get("verdict") or {}).get("code", "insufficient")
    qg = (val.get("quality") or {}).get("quality_grade", "mixed")
    own, g0 = val.get("own_growth"), val.get("implied_growth")
    support = own is not None and g0 is not None and own >= g0        # the price already assumes a slowdown
    if v == "insufficient":
        act, target, conf = "investigate", w, "low"
    elif v == "extreme":
        mild = support and qg != "low"
        act, target, conf = "trim", w * (0.75 if mild else 0.5), "high" if not support and qg == "low" else "medium"
    elif v == "exuberant":
        if qg == "low" and not support:
            act, target, conf = "trim", w * 0.75, "medium"
        else:
            act, target, conf = "hold and hedge", w, "medium"
    elif v == "pessimistic":
        act, target, conf = ("add", min(w * 1.25, max_name), "low") if qg in ("high", "mixed") else ("hold", w, "low")
    else:
        act, target, conf = "hold", w, "medium"
    why = val.get("why") or []
    g, p, own = val.get("implied_growth"), val.get("p_achieve"), val.get("own_growth")
    flags = (val.get("quality") or {}).get("flags") or []
    frames = {
        "outside_view": None if p is None else f"{valuation._share(p).capitalize()} of companies with {valuation.BASE_RATES[val['base_rate_bucket']]['label']} achieved the {g:.0%} a year the price requires.",
        "inside_view": " ".join(x for x in [f"Revenue grew {own:.0%} last year." if own is not None else "", f"Accounting quality {qg}" + (f": {flags[0]['text']}." if flags else ".")] if x),
        "pre_mortem": f"Most likely way this goes wrong: {why[0]['text']}" if why else "Not enough data for a pre-mortem.",
        "margin_of_safety": None if val.get("price_to_p90_value") is None else f"Price is {val['price_to_p90_value']:.2f}x the value at a 90th-percentile growth outcome for its size{' (no margin of safety)' if val['price_to_p90_value'] > 1 else ''}.",
        "reversibility": "Two-way door: a trim or add can be reversed next quarter at the cost of spreads and taxes.",
        "kill_criteria": {"trim": f"Reverse if revenue growth stays above {g:.0%} for four quarters with clean cash conversion." if g is not None else "",
                          "hold and hedge": f"Remove the hedge if the price falls back inside the base rates (implied growth below {valuation.base_rate_quantile(0.95, val.get('base_rate_bucket', 'over_50b')) / 100 + valuation.ASSUMED['inflation']:.0%}).",
                          "add": f"Exit the add if quality flags turn red or revenue growth falls below {g:.0%}." if g is not None else "",
                          "hold": "Re-check if the price moves outside the base rates either way, or a quality flag turns red.",
                          "investigate": "Get the missing filings before acting."}[act],
    }
    return {"ticker": t, "weight": w, "target": round(target, 4), "action": act, "confidence": conf, "verdict": v, "quality": qg, "frameworks": frames}


def _ten_year(macro: dict | None, fallback: float) -> float:
    try:
        for p in macro["rates"]["curves"]["latest"]["points"]:
            if p.get("tenor") == "10Y" and isinstance(p.get("yield"), (int, float)) and 0 < p["yield"] < 25:
                return float(p["yield"])
    except (TypeError, KeyError):
        pass
    return fallback


def _brain_readings(graph: dict, brain_json: dict | None) -> dict:
    obs = dict(graph["graph"]["observed"])
    st = (brain_json or {}).get("state") or {}
    node_m = {n["measured"]: n["id"] for n in graph["graph"]["nodes"] if n.get("measured")}
    for m, v in st.items():
        if isinstance(v, dict) and isinstance(v.get("z3m"), (int, float)) and m in node_m:
            obs[node_m[m]] = float(v["z3m"])
    return obs


def build(folder, config_path: str | None = None, signals: dict | None = None, as_of: str | None = None) -> dict:
    folder = Path(folder)
    cfg = load_config(config_path) if config_path and Path(config_path).exists() else default_config()
    graph = json.loads((ASSETS / "brain_graph.json").read_text())
    macro, research, brain_json, capex, report = (_load(folder, n) for n in ("macro", "research", "brain", "capex", "report"))
    snap = positions_snapshot()
    g = graph["graph"]
    ids = [n["id"] for n in g["nodes"]]
    idx = {k: i for i, k in enumerate(ids)}
    edges = [(idx[e["from"]], idx[e["to"]], e["w"]) for e in g["edges"]]
    readings = _brain_readings(graph, brain_json)
    obs_i = {idx[k]: v for k, v in readings.items()}
    roots = [idx[r] for r in g["roots"]]
    th = thinking.think(len(ids), edges, g["K"], obs_i, roots, [idx[h] for h in g["holdings"]], g["obs_sd"], g["prior_sd"])
    T = np.array(th["T"])
    ab = th["abduce"]
    su = thinking.surprise(T, obs_i, roots, g["obs_sd"], g["prior_sd"])
    by = g.get("edges_by_blend") or {}
    world = None
    if by:
        Tby = {float(b): thinking.total_effect(len(ids), [(e[0], e[1], w) for e, w in zip(edges, ws)], g["K"]) for b, ws in by.items()}
        world = thinking.regime_posterior(Tby, obs_i, roots, g["obs_sd"], g["prior_sd"])
    # ---- observe
    moved = sorted(readings.items(), key=lambda kv: -abs(kv[1]))[:4]
    observe = {"readings": readings, "moved": [{"node": k, "z": v} for k, v in moved],
               "surprise": {"p": su["p"], "maha2": su["maha2"], "worst_predicted": [{"node": ids[d["node"]], "z": d["z"]} for d in su["loo"][:3]]},
               "world": None if world is None else {"blends": world["blends"], "p": world["p"], "mean_blend": world["mean_blend"]},
               "inputs": {"brain": "brain.json" if brain_json else f"snapshot through {g.get('observed_month')}", "fundamentals": snap["as_of"],
                          "prices": snap["market_caps_as_of"], "report": (report or {}).get("summary", {}).get("as_of")}}
    # ---- orient
    series = (brain_json or {}).get("series") or graph.get("series")
    from .brain import PARENTS, REGIMES
    causal = causal_stats.analyze(series, REGIMES) if series else None
    regime_now = "inflation" if (world is None or world["mean_blend"] >= 0.5) else "low_inflation"
    robust_links = (brain_json or {}).get("robust_links")
    if not isinstance(robust_links, dict) and series:
        from .robust import link_robustness
        robust_links = link_robustness(series, PARENTS, REGIMES)
    key = (robust_links or {}).get("y10>eq", {})
    funds = merged_fundamentals(snap, capex)
    rf = _ten_year(macro, snap.get("rf_10y", 4.2)) / 100
    vals = valuation.analyze_book(funds, {t: v["market_cap"] for t, v in snap["market_caps"].items()}, rf, snap.get("betas", {}),
                                  brain={"pods": readings.get("pods")} if "pods" in readings else {"pods": th["predict"]["mean"][idx["pods"]]})
    crisis = causal["regimes"][regime_now]["crisis"] if causal else {}
    orient = {"explanations": [{"cause": "noise only" if r["root"] is None else ids[r["root"]], "p": r["p"], "size": r["s"]} for r in th["explanations"][:4]],
              "joint": sorted(({"cause": ids[r], "sd": s} for r, s in zip(ab["roots"], ab["s"])), key=lambda d: -abs(d["sd"]))[:4],
              "explained": ab["explained"], "book_implied": th["predict"]["mean"][idx["book"]], "book_sd": th["predict"]["sd"][idx["book"]],
              "key_link": {"name": "10-year yield to stocks", "regimes": key},
              "crisis_behaviour": {"regime": regime_now, "in_stocks_worst_months": {k: v["crisis_mean"] for k, v in crisis.items()}},
              "positions": {t: {"verdict": v["verdict"], "implied_growth": v.get("implied_growth"), "p_achieve": v.get("p_achieve"),
                                "quality": v["quality"]["quality_grade"], "flags": v["quality"]["flags"], "why": (v.get("why") or [])[:3],
                                "pe": v.get("pe"), "ev_sales": v.get("ev_sales"), "owner_fcf_yield": v.get("owner_fcf_yield"),
                                "price_to_p90_value": v.get("price_to_p90_value")} for t, v in vals["positions"].items()},
              "causal_findings": causal_stats.summary(causal) if causal else []}
    # ---- decide
    sig = signals if signals is not None else reasoner.observe(macro, research, None)
    pri = [s["prior"] for s in reasoner.SCENARIOS]
    post = reasoner.posterior(pri, reasoner.SIGNALS, sig)["posterior"]
    P = dict(reasoner.DEFAULTS)
    try:
        P["vix"] = float(macro["rates"]["levels"]["vix"]["value"])
    except (TypeError, KeyError):
        pass
    nominal = reasoner.solve(post, reasoner.SCENARIOS, P)
    robust = reasoner.solve_robust(post, reasoner.SCENARIOS, P, 0.05)
    S = (report or {}).get("summary") or {}
    e = float(S.get("recommended_gross") or sum(cfg.universe.book.values()))
    hcfg = dict(snap.get("hedges_default", {}))
    if config_path and Path(config_path).exists():                 # [hedges] in config.toml: the switches the page exports
        import tomllib
        raw = tomllib.loads(Path(config_path).read_text()).get("hedges") or {}
        if isinstance(raw.get("on"), list):
            hcfg["on"] = [h for h in raw["on"] if h in hedgebook.HEDGE_IDS]
        if isinstance(raw.get("sizes"), dict):
            hcfg["sizes"] = {k: float(v) for k, v in raw["sizes"].items() if k in hedgebook.HEDGE_IDS and isinstance(v, (int, float))}
        if isinstance(raw.get("equity"), (int, float)) and not S.get("recommended_gross"):
            e = float(raw["equity"])
    sizes = {h["id"]: h["default"] for h in hedgebook.HEDGES}
    sizes.update(hcfg.get("sizes", {}))
    on = {h: sizes[h] for h in hcfg.get("on", [])}
    current = hedgebook.evaluate(on, e, post, P)
    adv = hedgebook.advisor(sizes, e, post, P, allowed=hcfg.get("allowed"))
    actions = [position_action(t, w, vals["positions"].get(t, {})) for t, w in cfg.universe.book.items()]
    freed = sum(a["weight"] - a["target"] for a in actions)
    decide = {"posterior": dict(zip([s["id"] for s in reasoner.SCENARIOS], post)), "signals": sig,
              "solver": {"nominal": nominal and {"port": nominal["port"], "ce": math.expm1(nominal["elog"])}, "robust_rho_0.05": robust and {"port": robust["port"], "ce": robust["ce"]}},
              "hedges": {"equity": e, "on": sorted(on), "current": {"ce": current["ce"], "worst": current["worst"], "cost_bp": current["cost_bp"], "rets": current["rets"]},
                         "advisor": {k: adv[k][:3] for k in ("cheapest_meeting_limit", "best_growth", "best_worst_case")}, "meets_limit": adv["meets_limit"], "combinations": adv["combinations"], "loss_limit": adv["loss_limit"]},
              "positions": actions, "freed_weight": freed}
    # ---- act
    proposals = [{"type": "position", "ticker": a["ticker"], "action": a["action"], "from": a["weight"], "to": a["target"], "confidence": a["confidence"],
                  "kill": a["frameworks"]["kill_criteria"], "door": "two-way"} for a in actions if abs(a["target"] - a["weight"]) > 1e-9]
    pick = (adv["cheapest_meeting_limit"] or adv["best_worst_case"])[:1]
    if pick:
        want = set(pick[0]["on"])
        for h in hedgebook.HEDGE_IDS:
            if (h in want) != (h in on):
                proposals.append({"type": "hedge", "hedge": h, "action": "switch on" if h in want else "switch off", "size": sizes[h], "door": "two-way",
                                  "why": "the cheapest set of switched-on hedges that keeps the worst scenario inside the loss limit" if adv["cheapest_meeting_limit"] else "no set meets the limit; this one has the best worst case"})
    today = date.fromisoformat(as_of) if as_of else date.today()
    watch = [{"node": ids[r["node"]], "why": "the unobserved node that best separates the leading explanations", "information_nats": r["info"]} for r in th["next"][:3]]
    act = {"proposals": proposals, "watch": watch, "review_by": (today + timedelta(days=14)).isoformat(),
           "note": "Proposals for a person to review; the engine places no orders."}
    return {"schema": 1, "as_of": today.isoformat(), "observe": observe, "orient": orient, "decide": decide, "act": act,
            "valuation": vals, "causal": causal, "hedge_catalog": hedgebook.catalog(P), "frameworks": FRAMEWORKS,
            "labels": {"observe": "Observed", "orient": "Estimated and Hypothesis, as marked", "decide": "rules stated in code", "act": "proposals only"}}
