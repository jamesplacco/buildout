"""Buildout as an MCP server: the engine's research, risk and reasoning as tools an assistant can call.

    python -m buildout.mcp_server [--data site/data] [--config config.toml]

Model Context Protocol over stdio (JSON-RPC 2.0, one message per line). Standard library only, no SDK.

Every tool is research or a proposal. Nothing here places, routes or cancels an order, reads a brokerage account or
touches config.private.toml: create_order_proposal returns a proposal for a person to review and execute elsewhere.

  get_research_snapshot   what the engine's latest files say (hedge line, regime, data checks), with dates
  get_portfolio_risk      the model book: weights, the engine's risk summary, and which names are the same bet
  analyze_positions       your real holdings, passed in for one call (e.g. from Robinhood's MCP), through the same lens
  run_hedge_scenario      the TLT hedge policy (hedge.tlt.v2) on any correlation path and inflation reading
  evaluate_trade          a candidate portfolio against the reasoner's scenarios: growth, worst case, loss limit, regret
  create_order_proposal   a structured, hashed proposal checked against the limits; never executed
  review_decision         process score for one decision, or the full scorecard for a journal
  compare_explanations    competing explanations of one observation, and the evidence that best separates them
  trace_exposure          the brain: what explains the readings, what follows for each holding, what to look at next,
                          the gap between seeing a value and setting it, which world fits, how surprising the readings
                          are, each cause's but-for share, the channels, how a bad quarter happens, and counterfactuals
  learned_structure       the causal order learned from the data, and how each measured link has moved over time
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import decisions, field, policy, reasoner, thinking
from .config import default_config, load_config

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
GRAPH_PATH = Path(__file__).resolve().parent / "assets" / "brain_graph.json"
LIMIT_NOTE = "Research and proposals only: this server never places, routes or cancels orders."


# ---------------------------------------------------------------- shared state
class Context:
    def __init__(self, data_dir: str | None = None, config_path: str | None = None):
        root = Path(__file__).resolve().parents[1]
        self.data_dir = Path(data_dir or os.environ.get("BUILDOUT_DATA") or root / "site" / "data")
        cfg = Path(config_path or os.environ.get("BUILDOUT_CONFIG") or root / "config.toml")
        if cfg.name == "config.private.toml":
            raise SystemExit("config.private.toml holds real positions and is never served; pass the model config")
        self.config = load_config(cfg) if cfg.exists() else default_config()
        self.config_source = str(cfg.name) if cfg.exists() else "built-in default"
        self.graph = json.loads(GRAPH_PATH.read_text())

    def load(self, name: str) -> dict | None:
        try:
            return json.loads((self.data_dir / f"{name}.json").read_text())
        except (OSError, ValueError):
            return None


def _num(x, nd: int = 4):
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return round(x, nd) if math.isfinite(x) else None
    return x


def _clean(o, nd: int = 4):
    if isinstance(o, dict):
        return {str(k): _clean(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v, nd) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist(), nd)
    return _num(o, nd)


class ToolError(ValueError):
    """A bad argument: reported to the caller as a tool error, not a protocol error."""


def _req_num(args: dict, k: str, lo: float, hi: float, default=None) -> float | None:
    v = args.get(k, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ToolError(f"{k} must be a finite number")
    if not lo <= v <= hi:
        raise ToolError(f"{k} must be between {lo} and {hi}")
    return float(v)


# ---------------------------------------------------------------- tools
def get_research_snapshot(ctx: Context, args: dict) -> dict:
    research, macro, status, reason = (ctx.load(n) for n in ("research", "macro", "status", "reason"))
    out: dict[str, Any] = {"data_dir": str(ctx.data_dir), "files": {n: d is not None for n, d in
                           (("research", research), ("macro", macro), ("status", status), ("reason", reason))}}
    if research:
        H = research.get("hedge") or {}
        out["hedge_line"] = {"status": H.get("status"), "line": H.get("line"), "trained_through": H.get("trained_through"),
                             "bootstrap": H.get("bootstrap"), "holdout": H.get("holdout"), "evidence": "Estimated"}
        out["panel"] = research.get("panel")
    if macro:
        out["regime"] = {"latest": macro.get("latest"), "inflation": (macro.get("macro_state") or {}).get("inflation"), "evidence": "Observed"}
    if status:
        checks = status.get("checks") or []
        out["data_checks"] = {"pass": sum(1 for c in checks if c.get("ok")), "total": len(checks),
                              "failing": [c.get("name") for c in checks if not c.get("ok")]}
    if reason:
        alts = reason.get("alternatives") or {}
        out["reasoner"] = {"posterior": dict(zip([s["id"] for s in reason.get("scenarios", [])], (reason.get("posterior") or {}).get("posterior", []))),
                           "minimax_regret": alts.get("minimax_regret"), "optimal": (alts.get("optimal") or {}).get("port")}
    g = ctx.graph["graph"]
    out["brain_readings"] = {"month": g.get("observed_month"), "z3m": g["observed"], "evidence": "Observed (3-month change in standard deviations)",
                             "source": "snapshot shipped with the page" if not (ctx.load("brain") or {}).get("state") else "brain.json"}
    if not any(out["files"].values()):
        out["note"] = f"No engine outputs found in {ctx.data_dir}; run the daily action or pass --data. Brain readings come from the page snapshot."
    return out


def _book(ctx: Context) -> dict[str, float]:
    return dict(ctx.config.universe.book)


def _think(ctx: Context, extra: dict | None = None, K: int | None = None, book_weights: dict | None = None) -> tuple[dict, dict]:
    """book_weights (node id -> weight) replaces the links into the book node: the same graph, your holdings."""
    g = ctx.graph["graph"]
    ids = [n["id"] for n in g["nodes"]]
    idx = {k: i for i, k in enumerate(ids)}
    obs = dict(g["observed"])
    for k, v in (extra or {}).items():
        if k not in idx:
            raise ToolError(f"unknown node {k!r}; known: {', '.join(ids)}")
        if v is None:
            obs.pop(k, None)
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 6:
                raise ToolError(f"reading for {k} must be a number of standard deviations between -6 and 6, or null to remove it")
            obs[k] = float(v)
    if not obs:
        raise ToolError("at least one reading is needed")
    edges = [(idx[e["from"]], idx[e["to"]], e["w"]) for e in g["edges"]]
    if book_weights is not None:
        b = idx["book"]
        edges = [e for e in edges if e[1] != b] + [(idx[k], b, float(w)) for k, w in book_weights.items() if w]
    th = thinking.think(len(ids), edges, int(K or g["K"]), {idx[k]: v for k, v in obs.items()}, [idx[r] for r in g["roots"]],
                        [idx[h] for h in g["holdings"]], g["obs_sd"], g["prior_sd"])
    base = [(idx[e["from"]], idx[e["to"]]) for e in g["edges"]]
    return th, {"ids": ids, "idx": idx, "edges": edges, "base_edges": base, "obs": obs, "K": int(K or g["K"])}


def get_portfolio_risk(ctx: Context, args: dict) -> dict:
    book = _book(ctx)
    report = ctx.load("report")
    th, m = _think(ctx)
    g = ctx.graph["graph"]
    hold = g["holdings"]
    cos = np.array(th["shared"]["cos"])
    pairs = sorted(((cos[i, j], hold[i], hold[j]) for i in range(len(hold)) for j in range(i + 1, len(hold))), reverse=True)
    T = np.array(th["T"])
    book_i = m["idx"]["book"]
    sens = {r: float(T[book_i, m["idx"][r]]) for r in g["roots"]}
    out = {"book": "MODEL book from " + ctx.config_source + ", not personal positions", "weights": book,
           "gross_long": round(sum(book.values()), 4),
           "limits": {"max_gross": ctx.config.risk.max_gross, "target_vol": ctx.config.risk.target_vol, "max_drawdown": ctx.config.risk.max_drawdown,
                      "max_hedge_ratio": ctx.config.risk.max_hedge_ratio},
           "same_bet_pairs": [{"a": a, "b": b, "cosine": round(float(c), 3)} for c, a, b in pairs[:5]],
           "book_sensitivity_to_root_causes": {k: round(v, 4) for k, v in sorted(sens.items(), key=lambda kv: -abs(kv[1]))},
           "evidence": {"weights": "Assumed (model book)", "sensitivities": "Hypothesis (judged links) plus Estimated (measured links)"}}
    S = (report or {}).get("summary")
    if S:
        out["engine_summary"] = {k: S.get(k) for k in ("as_of", "recommended_gross", "hedge_ratio_now", "effective_risk_contributors",
                                                         "effective_independent_bets", "vol_ann", "max_drawdown", "data") if k in S}
    else:
        out["engine_summary"] = None
        out["note"] = "No report.json in the data folder: the engine's measured risk summary needs a book run."
    return out


# symbols outside the AI book that still have a node: broad equity funds, bond funds (scaled to TLT's duration), gold
ALIASES = {"GOOG": "GOOGL", "FB": "META"}
PROXY_NODES = {"QQQ": ("eq", 1.0), "SPY": ("eq", 1.0), "VOO": ("eq", 1.0), "IVV": ("eq", 1.0), "VTI": ("eq", 1.0), "QQQM": ("eq", 1.0),
               "TLT": ("tlt", 1.0), "VGLT": ("tlt", 0.9), "EDV": ("tlt", 1.4), "IEF": ("tlt", 0.45), "GOVT": ("tlt", 0.35),
               "GLD": ("gold", 1.0), "IAU": ("gold", 1.0), "GLDM": ("gold", 1.0)}
BOND_FUNDS = {"TLT": 1.0, "VGLT": 0.9, "EDV": 1.4, "IEF": 0.45, "GOVT": 0.35}
GOLD_FUNDS = ("GLD", "IAU", "GLDM")


def analyze_positions(ctx: Context, args: dict) -> dict:
    """Your real holdings, passed in for one call (for example from Robinhood's MCP), run through the same risk
    lens as the model book. Nothing is stored, logged or written; the server still cannot trade."""
    pos = args.get("positions")
    if not isinstance(pos, list) or not 1 <= len(pos) <= 200:
        raise ToolError("positions must be a list of 1 to 200 holdings: {symbol, and weight, or market_value, or quantity and price}")
    nav = _req_num(args, "nav", 1e-6, 1e12)
    cash = _req_num(args, "cash", -1e12, 1e12, 0.0)
    rows, by_weight = {}, None
    for p in pos:
        if not isinstance(p, dict):
            raise ToolError("each position must be an object")
        sym = str(p.get("symbol", "")).strip().upper()
        if not sym or len(sym) > 12 or not sym.replace(".", "").replace("-", "").isalnum():
            raise ToolError(f"bad symbol {p.get('symbol')!r}")
        sym = ALIASES.get(sym, sym)
        if "weight" in p:
            w = _req_num(p, "weight", -2.0, 2.0)
            kind = True
        else:
            mv = _req_num(p, "market_value", -1e12, 1e12)
            if mv is None:
                q, px = _req_num(p, "quantity", -1e12, 1e12), _req_num(p, "price", 0, 1e9)
                if q is None or px is None:
                    raise ToolError(f"{sym}: give weight, market_value, or quantity and price")
                mv = q * px
            w = mv
            kind = False
        if by_weight is None:
            by_weight = kind
        elif by_weight != kind:
            raise ToolError("use weights for every position or values for every position, not a mix")
        rows[sym] = rows.get(sym, 0.0) + w
    if not by_weight:
        total = sum(rows.values()) + (cash or 0.0)
        base = nav or total
        if base <= 0:
            raise ToolError("the account value must be positive: pass nav, or cash plus positive positions")
        weights = {k: v / base for k, v in rows.items()}
        cash_w = (cash or 0.0) / base
    else:
        weights = dict(rows)
        cash_w = 1.0 - sum(weights.values())
    hold_ids = set(ctx.graph["graph"]["holdings"])
    nodes, mapped, unmapped = {}, {}, []
    for sym, w in weights.items():
        if sym in hold_ids:
            nodes[sym] = nodes.get(sym, 0.0) + w
            mapped[sym] = sym
        elif sym in PROXY_NODES:
            node, scale = PROXY_NODES[sym]
            nodes[node] = nodes.get(node, 0.0) + w * scale
            mapped[sym] = f"{node} (x{scale:g})"
        else:
            unmapped.append(sym)
    gross = sum(abs(w) for w in weights.values())
    covered = sum(abs(weights[s]) for s in mapped) / gross if gross else 0.0
    eq_w = sum(w for s, w in weights.items() if s not in BOND_FUNDS and s not in GOLD_FUNDS)
    tlt_eq = sum(w * BOND_FUNDS[s] for s, w in weights.items() if s in BOND_FUNDS)
    gold_w = sum(w for s, w in weights.items() if s in GOLD_FUNDS)
    th, m = _think(ctx, book_weights=nodes)
    T = np.array(th["T"])
    bi = m["idx"]["book"]
    g = ctx.graph["graph"]
    sens = {r: float(T[bi, m["idx"][r]]) for r in g["roots"]}
    held = [h for h in g["holdings"] if nodes.get(h)]
    cos = np.array(th["shared"]["cos"])
    hix = {h: i for i, h in enumerate(g["holdings"])}
    pairs = sorted(((cos[hix[a], hix[b]], a, b) for i, a in enumerate(held) for b in held[i + 1:]), reverse=True)
    model = _book(ctx)
    diffs = sorted(((weights.get(k, 0.0) - model.get(k, 0.0), k) for k in set(weights) | set(model)), key=lambda t: -abs(t[0]))
    w_arr = np.array([abs(w) for w in weights.values()])
    lim = ctx.config.risk
    checks = [{"check": "gross within max_gross", "value": round(gross, 4), "limit": lim.max_gross, "pass": gross <= lim.max_gross + 1e-9},
              {"check": "largest single name at most 25% of the account", "value": round(max(weights.values(), key=abs), 4),
               "name": max(weights, key=lambda k: abs(weights[k])), "pass": max(abs(w) for w in weights.values()) <= 0.25 + 1e-9},
              {"check": "no short positions", "pass": all(w >= 0 for w in weights.values())}]
    return {"privacy": "Analysed for this call only: nothing is stored, logged or committed. This server cannot place orders.",
            "weights": {k: round(v, 4) for k, v in sorted(weights.items(), key=lambda kv: -abs(kv[1]))}, "cash_weight": round(cash_w, 4),
            "gross": gross, "effective_names": float(1 / np.sum((w_arr / w_arr.sum()) ** 2)) if w_arr.sum() else None,
            "checks": checks,
            "brain": {"mapped": mapped, "unmapped": unmapped, "share_of_gross_mapped": covered,
                      "book_now_sd": {"implied": th["predict"]["mean"][bi], "sd": th["predict"]["sd"][bi]},
                      "sensitivity_to_root_causes": {k: round(v, 4) for k, v in sorted(sens.items(), key=lambda kv: -abs(kv[1]))},
                      "same_bet_pairs": [{"a": a, "b": b, "cosine": round(float(c), 3)} for c, a, b in pairs[:5]]},
            "vs_model_book": [{"symbol": k, "yours_minus_model": round(d, 4)} for d, k in diffs[:8] if abs(d) > 1e-9],
            "as_portfolio_vector": {"equity": round(eq_w, 4), "hedge_ratio": round(tlt_eq / eq_w, 4) if eq_w > 0 else 0.0, "put_premium": 0.0,
                                    "gold": round(gold_w, 4), "use": "pass to evaluate_trade to score these holdings on the seven scenarios"},
            "evidence": {"weights": "Observed (as supplied)", "brain": "Hypothesis (judged links) plus Estimated (measured links)",
                         "proxies": "Assumed: broad funds map to stocks, bond funds to TLT scaled by duration, gold funds to gold"}}


def run_hedge_scenario(ctx: Context, args: dict) -> dict:
    path = args.get("correlations")
    if path is None:
        c = _req_num(args, "correlation", -1, 1)
        if c is None:
            raise ToolError("give correlation (one reading) or correlations (a path, oldest first)")
        path = [c]
    if not isinstance(path, list) or not path or len(path) > 5000:
        raise ToolError("correlations must be a non-empty list (at most 5000 readings)")
    for v in path:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not -1 <= v <= 1:
            raise ToolError("every correlation must be a number between -1 and 1")
    prev = args.get("previous_state", "neutral")
    if prev not in ("hedging", "neutral", "amplifying"):
        raise ToolError("previous_state must be hedging, neutral or amplifying")
    infl = _req_num(args, "inflation_36m", -0.2, 0.5)
    research = ctx.load("research") or {}
    H = research.get("hedge") or {}
    line = _req_num(args, "line", 0, 0.2, H.get("line") if H.get("status") == "ok" else 0.0425)
    status = args.get("line_status", H.get("status") or "ok")
    mv = _req_num(args, "mv_ratio", 0, 5)
    states = policy.hedge_state(path, prev)
    d = policy.tlt_decision(states[-1], infl, line, status, mv, ctx.config.risk.max_hedge_ratio)
    flips = [i for i in range(1, len(states)) if states[i] != states[i - 1]]
    return {"policy": d["policy"], "decision": d, "state_path_tail": states[-10:], "state_changes": len(flips),
            "rule": "enter hedging at correlation <= -0.10, leave at >= 0 (hysteresis); TLT on only while hedging and 36-month inflation is below the line",
            "line_used": line, "line_source": "argument" if "line" in args else ("research.json" if H.get("status") == "ok" else "v0.7 out-of-sample estimate (4.25%)")}


PORT_KEYS = ("equity", "hedge_ratio", "put_premium", "gold")


def _port(args: dict, key: str = "portfolio") -> tuple[float, float, float, float]:
    p = args.get(key)
    if not isinstance(p, dict):
        raise ToolError(f"{key} must be an object with {', '.join(PORT_KEYS)}")
    lim = {"equity": 1.5, "hedge_ratio": 1.0, "put_premium": 0.05, "gold": 0.5}
    return tuple(_req_num(p, k, 0, lim[k], 0.0) for k in PORT_KEYS)


def _signals(args: dict) -> dict:
    obs = args.get("signals") or {}
    ids = [s["id"] for s in reasoner.SIGNALS]
    if not isinstance(obs, dict):
        raise ToolError("signals must be an object of signal id to true, false or null")
    for k, v in obs.items():
        if k not in ids:
            raise ToolError(f"unknown signal {k!r}; known: {', '.join(ids)}")
        if v not in (True, False, None):
            raise ToolError(f"signal {k} must be true, false or null")
    return {k: obs.get(k) for k in ids}


def evaluate_trade(ctx: Context, args: dict) -> dict:
    port = _port(args)
    obs = _signals(args)
    P = {**reasoner.DEFAULTS}
    vix = _req_num(args, "vix", 5, 150)
    if vix is not None:
        P["vix"] = vix
    post = reasoner.posterior([s["prior"] for s in reasoner.SCENARIOS], reasoner.SIGNALS, obs)["posterior"]
    alts = reasoner.alternatives(post, reasoner.SCENARIOS, P, port)
    mine = alts["keep"]
    best = alts.get("optimal")
    return {"portfolio": dict(zip(PORT_KEYS, port)), "signals": obs,
            "scenario_probabilities": {s["id"]: round(p, 4) for s, p in zip(reasoner.SCENARIOS, post)},
            "result": {"growth_ce_3m": mine["ce"], "mean_3m": mine["mean"], "worst_3m": mine["worst"], "meets_loss_limit": mine["feasible"],
                       "max_regret": mine.get("max_regret"), "by_scenario": {s["id"]: r for s, r in zip(reasoner.SCENARIOS, mine["rets"])}},
            "best_on_grid": {"portfolio": dict(zip(PORT_KEYS, best["port"])), "growth_ce_3m": best["ce"], "worst_3m": best["worst"]} if best else None,
            "minimax_regret_choice": alts["minimax_regret"],
            "limits": {"max_loss_3m": P["max_loss"], "max_equity": P["max_equity"], "max_gross": P["max_gross"], "max_premium": P["max_premium"]},
            "evidence": {"scenarios": "Assumed", "likelihoods": "Hypothesis", "signals": "as given"}}


def create_order_proposal(ctx: Context, args: dict) -> dict:
    sym = str(args.get("symbol", "")).strip().upper()
    if not sym or len(sym) > 12 or not sym.replace(".", "").replace("-", "").isalnum():
        raise ToolError("symbol must be a ticker such as NVDA")
    side = args.get("side")
    if side not in ("buy", "sell"):
        raise ToolError("side must be buy or sell")
    w = _req_num(args, "weight_change", -1.0, 1.0)
    if w is None or w == 0:
        raise ToolError("weight_change (fraction of NAV, signed to match side) is required and cannot be 0")
    if (side == "buy") != (w > 0):
        raise ToolError("weight_change sign must match side (buy positive, sell negative)")
    rationale = str(args.get("rationale", "")).strip()
    kill = str(args.get("kill_criteria", "")).strip()
    if len(rationale) < 10 or len(kill) < 5:
        raise ToolError("a proposal needs a rationale and a kill criterion: what would prove it wrong")
    p = _req_num(args, "probability", 0.01, 0.99)
    book = _book(ctx)
    after = dict(book)
    after[sym] = round(after.get(sym, 0.0) + w, 6)
    if after[sym] < -1e-9:
        raise ToolError(f"the model book holds {book.get(sym, 0.0):.2%} of {sym}; this would go short, which the model book does not allow")
    checks = []
    gross = sum(abs(v) for v in after.values())
    checks.append({"check": "gross within max_gross", "value": round(gross, 4), "limit": ctx.config.risk.max_gross, "pass": gross <= ctx.config.risk.max_gross + 1e-9})
    checks.append({"check": "single name at most 25% of NAV", "value": after[sym], "limit": 0.25, "pass": after[sym] <= 0.25 + 1e-9})
    checks.append({"check": "in the AI universe", "value": sym, "pass": sym in ctx.config.universe.ai_factor or sym in ctx.config.universe.hedges,
                   "note": "outside the universe the engine has no betas for it"})
    checks.append({"check": "probability stated", "value": p, "pass": p is not None, "note": "a stated probability is what the journal scores later"})
    body = {"symbol": sym, "side": side, "weight_change": w, "weight_after": after[sym], "rationale": rationale, "kill_criteria": kill,
            "probability": p, "horizon": str(args.get("horizon", "3 months"))[:40], "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {"proposal": body, "id": "prop-" + digest[:12], "sha256": digest, "checks": checks, "all_checks_pass": all(c["pass"] for c in checks),
            "status": "proposal_only", "executed": False, "requires_human_review": True, "note": LIMIT_NOTE}


def review_decision(ctx: Context, args: dict) -> dict:
    recs = args.get("records")
    rec = args.get("record")
    if recs is None and rec is None:
        raise ToolError("give record (one decision) or records (a journal export)")
    if rec is not None:
        if not isinstance(rec, dict):
            raise ToolError("record must be an object")
        ps = decisions.process_score(rec)
        missing = [k for k in decisions.PROCESS_ITEMS if k not in (rec.get("process") or {})]
        out = {"process_score": ps, "process_items": list(decisions.PROCESS_ITEMS), "missing_items": missing,
               "verdict": None if ps is None else ("good process" if ps >= 0.75 else "process gaps" if ps >= 0.5 else "poor process")}
        if rec.get("status") == "closed" and rec.get("right") in (0, 1, 0.5):
            good = ps is not None and ps >= 0.75
            win = rec["right"] >= 0.5
            out["quadrant"] = ("earned" if win else "bad luck") if good else ("dumb luck" if win else "deserved") if ps is not None else "unknown process"
        return out
    if not isinstance(recs, list) or len(recs) > 5000:
        raise ToolError("records must be a list of at most 5000 decisions")
    return decisions.scorecard([r for r in recs if isinstance(r, dict)])


def compare_explanations(ctx: Context, args: dict) -> dict:
    cases = {c["id"]: c for c in ctx.graph["field"]["cases"]}
    cid = args.get("case")
    if cid is not None:
        if cid not in cases:
            raise ToolError(f"unknown case {cid!r}; known: {', '.join(cases)}")
        c = cases[cid]
        hyps, lik = c["hyps"], c["ev"]
    else:
        hyps, lik = args.get("hypotheses"), args.get("evidence")
        if not isinstance(hyps, list) or not 2 <= len(hyps) <= 12 or not isinstance(lik, dict) or not lik:
            raise ToolError("give case, or hypotheses (2 to 12 names) and evidence ({item: [P(seen | each hypothesis)]})")
        for e, ls in lik.items():
            if not isinstance(ls, list) or len(ls) != len(hyps) or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 1 for x in ls):
                raise ToolError(f"evidence {e!r} needs one probability between 0 and 1 per hypothesis")
    prior = args.get("prior") or [1 / len(hyps)] * len(hyps)
    if len(prior) != len(hyps) or any((not isinstance(x, (int, float))) or x < 0 for x in prior) or sum(prior) <= 0:
        raise ToolError("prior needs one non-negative weight per hypothesis")
    seen = args.get("seen") or {}
    if not isinstance(seen, dict) or any(k not in lik or v not in (True, False, None) for k, v in seen.items()):
        raise ToolError("seen maps listed evidence items to true, false or null")
    post = field.posterior(prior, lik, seen)
    nx = field.next_evidence(prior, lik, seen)
    lead = int(np.argmax(post))
    return {"case": cid, "posterior": dict(zip(hyps, post)), "leading": hyps[lead], "doubt_bits": field.entropy(post),
            "check_next": nx[:5], "evidence": "Hypothesis: likelihoods are judged, not fitted",
            "available_cases": {k: v["n"] for k, v in cases.items()}}


def trace_exposure(ctx: Context, args: dict) -> dict:
    extra = args.get("readings") or {}
    if not isinstance(extra, dict):
        raise ToolError("readings must be an object of node id to standard deviations")
    K = args.get("orders")
    if K is not None and (isinstance(K, bool) or not isinstance(K, int) or not 1 <= K <= 8):
        raise ToolError("orders must be an integer from 1 to 8")
    th, m = _think(ctx, extra, K)
    ids, idx, g = m["ids"], m["idx"], ctx.graph["graph"]
    name = {n["id"]: n["name"] for n in g["nodes"]}
    ab, pr, cr = th["abduce"], th["predict"], th["criticize"]
    ex = [{"cause": "noise only" if r["root"] is None else ids[r["root"]], "p": r["p"], "shock_sd": r["s"], "shock_sd_err": r["s_sd"]} for r in th["explanations"][:5]]
    tied = len(ex) > 1 and ex[0]["p"] - ex[1]["p"] < 0.05
    joint = sorted(({"cause": ids[r], "shock_sd": s, "sd": sd} for r, s, sd in zip(ab["roots"], ab["s"], ab["sd"])), key=lambda d: -abs(d["shock_sd"]))
    resid = sorted(({"node": ids[o], "standardized_residual": r} for o, r in zip(ab["obs"], cr["resid"])), key=lambda d: -abs(d["standardized_residual"]))
    gi = int(np.argmax(np.abs(cr["grad"]))) if any(cr["grad"]) else None
    holds = {h: {"name": name[h], "implied_sd": pr["mean"][idx[h]], "sd": pr["sd"][idx[h]]} for h in g["holdings"] + ["book"]}
    out = {"readings": m["obs"], "orders": m["K"],
           "explain": {"single_causes": ex, "cannot_tell_top_two_apart": tied, "joint_inference": joint[:5], "share_explained": ab["explained"]},
           "deduce": holds,
           "doubt": {"least_explained": resid[:3],
                     "link_most_to_blame": None if gi is None else {"from": ids[m["edges"][gi][0]], "to": ids[m["edges"][gi][1]], "w": m["edges"][gi][2], "misfit_gradient": cr["grad"][gi]}},
           "look_next": [{"node": ids[r["node"]], "name": name[ids[r["node"]]], "information_nats": r["info"]} for r in th["next"][:3]],
           "evidence": "Readings Observed; measured links Estimated; judged links Hypothesis"}
    do = args.get("do")
    if do is not None:
        if not isinstance(do, dict) or do.get("node") not in idx:
            raise ToolError("do needs {node, value}")
        v = _req_num(do, "value", -6, 6)
        doing = thinking.intervene(len(ids), m["edges"], m["K"], idx[do["node"]], v)
        seen_th, _ = _think(ctx, {**extra, do["node"]: v}, K)
        seeing = seen_th["predict"]["mean"]
        out["do_vs_see"] = {"node": do["node"], "value": v, "book_if_set": float(doing[idx["book"]]), "book_if_seen": float(seeing[idx["book"]]),
                            "meaning": "setting a value moves only what lies downstream; seeing it also says something about its causes"}
    # frontier: which world, how surprised, but-for, channels, a bad quarter, and an optional counterfactual
    T = np.array(th["T"])
    roots, book = ab["roots"], idx["book"]
    obs_i = {idx[k]: v for k, v in m["obs"].items()}
    by = g.get("edges_by_blend") or {}
    if by:
        Tby = {float(b): thinking.total_effect(len(ids), [(e[0], e[1], w) for e, w in zip(m["base_edges"], ws)], m["K"]) for b, ws in by.items()}
        rp = thinking.regime_posterior(Tby, obs_i, roots, g["obs_sd"], g["prior_sd"])
        world = {"posterior": {f"{b:g}": p for b, p in zip(rp["blends"], rp["p"])}, "mean_blend": rp["mean_blend"],
                 "bayes_factor_2022_vs_1990": rp["bayes_factor_new_vs_old"], "blend_meaning": "0 = 1990-2021 measured links, 1 = 2022-on links"}
    else:
        world = None
    su = thinking.surprise(T, obs_i, roots, g["obs_sd"], g["prior_sd"])
    pa = thinking.path_attribution(len(ids), m["edges"], m["K"], ab, book)
    tail = _req_num(args, "tail_probability", 0.001, 0.5, 0.05)
    base = thinking.loss_story(T, roots, book, 0.0, prior_sd=g["prior_sd"])
    story = None
    if base["possible"]:
        from scipy.stats import norm
        L = base["mean"] + base["sd"] * float(norm.ppf(tail))
        st = thinking.loss_story(T, roots, book, L, prior_sd=g["prior_sd"])
        alt = thinking.loss_story(T, roots, book, L, prior_sd=g["prior_sd"], exclude=[st["drivers"][0]["root"]])
        dr = lambda x: [{"cause": ids[d["root"]], "shock_sd": d["shift"]} for d in x["drivers"] if abs(d["shift"]) > 0.02][:5]  # noqa: E731
        story = {"tail_probability": tail, "book_level_sd": L, "book_sd": st["sd"], "story": dr(st),
                 "runner_up": {"story": dr(alt), "probability": alt["p_at_or_below"]} if alt["possible"] else None}
    out["frontier"] = {
        "which_world": world,
        "surprise": {"p_value": su["p"], "mahalanobis2": su["maha2"], "readings": su["dof"],
                     "leave_one_out": [{"node": ids[d["node"]], "z": d["z"]} for d in su["loo"][:4]]},
        "but_for": [{"cause": ids[d["root"]], "contribution_sd": d["contribution"]} for d in thinking.but_for(T, ab, book)[:6]],
        "channels": {"total_sd": pa["total"], "n": pa["n_paths"], "top": [{"path": [ids[k] for k in p["nodes"]], "sd": p["contribution"]} for p in pa["paths"][:6]]},
        "bad_quarter": story,
        "evidence": "which world Estimated; channels and stories Hypothesis (judged links)"}
    cf = args.get("counterfactual")
    if cf is not None:
        if not isinstance(cf, dict) or cf.get("node") not in idx or cf.get("node") == "book":
            raise ToolError("counterfactual needs {node, value} with a node other than book")
        v = _req_num(cf, "value", -6, 6)
        c = thinking.counterfactual(len(ids), m["edges"], m["K"], T, ab, idx[cf["node"]], v)
        out["frontier"]["counterfactual"] = {"node": cf["node"], "factual_sd": c["factual"][idx[cf["node"]]], "set_to_sd": v,
                                             "book": {"factual": c["factual"][book], "counterfactual": c["counterfactual"][book]},
                                             "holdings_change": {h: c["change"][idx[h]] for h in g["holdings"]}}
    return out


def learned_structure(ctx: Context, args: dict) -> dict:
    """What the data says about the map's own assumptions: DirectLiNGAM order and Kalman time-varying links."""
    from .brain import learn
    live = (ctx.load("brain") or {}).get("learned")
    if live and isinstance(live, dict) and live.get("links"):
        L, src = live, "brain.json (latest daily run)"
    else:
        if getattr(ctx, "_learned", None) is None:
            ctx._learned = learn(ctx.graph["series"])
        L, src = ctx._learned, "snapshot series shipped with the page"
    link = args.get("link")
    if link is not None and link not in L["links"]:
        raise ToolError(f"unknown link {link!r}; measured links: {', '.join(L['links'])}")
    keys = [link] if link else list(L["links"])
    links = {}
    for k in keys:
        x = L["links"][k]
        n = len(x["beta"])
        links[k] = {"latest": x["beta"][-1], "band90": 1.645 * x["sd"][-1], "drift_q": x["q"], "sign_changes": x["sign_changes"][-4:],
                    "five_years_ago": x["beta"][max(0, n - 61)]}
    lo = L["order"]["low_inflation"]
    return {"source": src, "months": len(L["dates"]), "through": L["dates"][-1],
            "order": {"assumed": ["oil", "cpi", "y10", "eq", "vix", "gold"], "learned_1990_2021": lo["learned"],
                      "agreement_share": lo["agreement"]["share"], "learned_2022_on": L["order"]["inflation"]["learned"],
                      "months_2022_on": L["order"]["inflation"]["months"]},
            "links": links, "method": "DirectLiNGAM (pairwise likelihood ratio) and a random-walk Kalman smoother with drift by maximum likelihood",
            "evidence": "Estimated; the order assumes linear links and no hidden common cause"}


# ---------------------------------------------------------------- registry
def _obj(props: dict, required: list[str] | None = None) -> dict:
    s = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        s["required"] = required
    return s


NUM = {"type": "number"}
PORT = _obj({"equity": {"type": "number", "description": "equity exposure, multiple of NAV (0 to 1.5)"},
             "hedge_ratio": {"type": "number", "description": "TLT hedge ratio (0 to 1)"},
             "put_premium": {"type": "number", "description": "put-spread premium, fraction of NAV (0 to 0.05)"},
             "gold": {"type": "number", "description": "gold, fraction of NAV (0 to 0.5)"}})
SIGNALS = {"type": "object", "description": "signal id to true, false or null (unknown): " + ", ".join(s["id"] for s in reasoner.SIGNALS),
           "additionalProperties": {"type": ["boolean", "null"]}}

TOOLS: dict[str, tuple[Callable[[Context, dict], dict], str, dict, dict]] = {
    "get_research_snapshot": (get_research_snapshot, "The engine's latest research: the out-of-sample TLT hedge line and its band, the stock-bond regime, "
                              "data checks, the reasoner's scenario probabilities and the brain's readings, each with its date and evidence label.",
                              _obj({}), {"readOnlyHint": True, "openWorldHint": False}),
    "get_portfolio_risk": (get_portfolio_risk, "The MODEL book (not personal positions): weights, limits, the engine's risk summary when a book run exists, "
                           "which holdings are the same bet, and the book's sensitivity to each root cause in the brain.",
                           _obj({}), {"readOnlyHint": True, "openWorldHint": False}),
    "analyze_positions": (analyze_positions, "Run YOUR holdings (for example from Robinhood's MCP) through the same lens as the model book: weights, "
                          "limit checks, concentration, which names are the same bet, sensitivity to each root cause, the gap to the model book, "
                          "and the portfolio vector to score with evaluate_trade. For this call only: nothing is stored; cannot trade.",
                          _obj({"positions": {"type": "array", "maxItems": 200, "items": _obj({"symbol": {"type": "string"}, "weight": NUM, "market_value": NUM,
                                                                                                "quantity": NUM, "price": NUM}, ["symbol"])},
                                "nav": {**NUM, "description": "total account value including cash; default positions plus cash"},
                                "cash": {**NUM, "description": "cash balance, same units as market_value"}}, ["positions"]),
                          {"readOnlyHint": True, "openWorldHint": False}),
    "run_hedge_scenario": (run_hedge_scenario, "Run the TLT hedge policy hedge.tlt.v2 on a stock-bond correlation path and a 36-month inflation reading.",
                           _obj({"correlation": {**NUM, "description": "one 63-day stock-bond correlation"},
                                 "correlations": {"type": "array", "items": NUM, "description": "a path of correlations, oldest first"},
                                 "previous_state": {"type": "string", "enum": ["hedging", "neutral", "amplifying"]},
                                 "inflation_36m": {**NUM, "description": "36-month average inflation, as a fraction (0.031 = 3.1%)"},
                                 "line": {**NUM, "description": "inflation line as a fraction; default the research estimate"},
                                 "line_status": {"type": "string", "enum": ["ok", "no_reliable_threshold", "insufficient_evidence"]},
                                 "mv_ratio": {**NUM, "description": "minimum-variance hedge ratio, if known"}}),
                           {"readOnlyHint": True, "openWorldHint": False}),
    "evaluate_trade": (evaluate_trade, "Score a candidate portfolio (equity, TLT hedge, put spread, gold) on the reasoner's seven 3-month scenarios: "
                       "certainty-equivalent growth, worst case, the loss limit, regret against the alternatives, and the best portfolio on the grid.",
                       _obj({"portfolio": PORT, "signals": SIGNALS, "vix": {**NUM, "description": "VIX level for put pricing"}}, ["portfolio"]),
                       {"readOnlyHint": True, "openWorldHint": False}),
    "create_order_proposal": (create_order_proposal, "Write a structured, hashed order PROPOSAL against the model book and check it against the limits. "
                              "Never executes: a person reviews it and acts elsewhere.",
                              _obj({"symbol": {"type": "string"}, "side": {"type": "string", "enum": ["buy", "sell"]},
                                    "weight_change": {**NUM, "description": "signed change in fraction of NAV (buy positive)"},
                                    "rationale": {"type": "string"}, "kill_criteria": {"type": "string", "description": "what would prove it wrong"},
                                    "probability": {**NUM, "description": "probability the thesis is right over the horizon"},
                                    "horizon": {"type": "string"}}, ["symbol", "side", "weight_change", "rationale", "kill_criteria"]),
                              {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}),
    "review_decision": (review_decision, "Score one decision's process (logged before, sized by rule, kill respected, two sources) and its luck quadrant, "
                        "or a whole journal export: calibration, hit rate, alpha after beta and the process-outcome grid.",
                        _obj({"record": {"type": "object"}, "records": {"type": "array", "items": {"type": "object"}}}),
                        {"readOnlyHint": True, "openWorldHint": False}),
    "compare_explanations": (compare_explanations, "Compare competing explanations of one observation by Bayes' rule and rank the unchecked evidence by "
                             "how much doubt it would remove (bits). Use a field case (leadtime, pipeline, credit) or supply your own.",
                             _obj({"case": {"type": "string"}, "hypotheses": {"type": "array", "items": {"type": "string"}},
                                   "evidence": {"type": "object", "additionalProperties": {"type": "array", "items": NUM}},
                                   "prior": {"type": "array", "items": NUM}, "seen": {"type": "object", "additionalProperties": {"type": ["boolean", "null"]}}}),
                             {"readOnlyHint": True, "openWorldHint": False}),
    "learned_structure": (learned_structure, "What the data says about the brain's own assumptions: the causal order learned by DirectLiNGAM against the assumed "
                          "order, and each measured link's path over time (Kalman smoother): latest value, 90% band, drift and sign changes.",
                          _obj({"link": {"type": "string", "description": "optional, e.g. y10>eq"}}), {"readOnlyHint": True, "openWorldHint": False}),
    "trace_exposure": (trace_exposure, "Reason over the brain (34 nodes, about 110 links): which root causes explain the readings, what that implies for each "
                       "holding and the book, which link is most to blame for the misfit, what to observe next, and doing versus seeing a value.",
                       _obj({"readings": {"type": "object", "description": "node id to a reading in standard deviations (null removes a measured reading)",
                                          "additionalProperties": {"type": ["number", "null"]}},
                             "orders": {"type": "integer", "description": "orders of effect, 1 to 8 (default 6)"},
                             "do": _obj({"node": {"type": "string"}, "value": NUM}, ["node", "value"]),
                             "counterfactual": _obj({"node": {"type": "string"}, "value": NUM}, ["node", "value"]),
                             "tail_probability": {**NUM, "description": "how bad a quarter the loss story describes, e.g. 0.05 = 1 in 20"}}),
                       {"readOnlyHint": True, "openWorldHint": False}),
}


# ---------------------------------------------------------------- protocol
def tool_list() -> list[dict]:
    return [{"name": n, "description": d, "inputSchema": s, "annotations": {"title": n.replace("_", " ").capitalize(), **a}} for n, (_, d, s, a) in TOOLS.items()]


def handle(ctx: Context, msg: dict) -> dict | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None, "error": {"code": -32600, "message": "invalid request"}}
    mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if "id" not in msg:
        return None                                        # notifications (initialized, cancelled) need no reply

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if method == "initialize":
        want = params.get("protocolVersion")
        return ok({"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0], "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "buildout", "version": _version()},
                   "instructions": "Buildout's research, risk and reasoning engine for a MODEL AI-buildout book. " + LIMIT_NOTE +
                                   " Numbers carry evidence labels: Observed, Estimated, Assumed, Hypothesis."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tool_list()})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            return err(-32602, f"unknown tool {name!r}")
        if not isinstance(args, dict):
            return err(-32602, "arguments must be an object")
        schema = TOOLS[name][2]
        extra = set(args) - set(schema["properties"])
        if extra:
            return ok({"content": [{"type": "text", "text": f"unknown argument(s): {', '.join(sorted(extra))}"}], "isError": True})
        try:
            res = _clean(TOOLS[name][0](ctx, args))
        except ToolError as e:
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:                              # a tool failure is reported, never fatal to the server
            print(f"buildout mcp: {name} failed: {e!r}", file=sys.stderr)
            return ok({"content": [{"type": "text", "text": f"{name} failed: {type(e).__name__}"}], "isError": True})
        return ok({"content": [{"type": "text", "text": json.dumps(res, indent=1)}], "structuredContent": res, "isError": False})
    return err(-32601, f"method not found: {method}")


def _version() -> str:
    from . import __version__
    return __version__


def serve(ctx: Context, stdin=None, stdout=None) -> None:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            if isinstance(msg, list):                       # batches: answer each request
                resp = [r for r in (handle(ctx, m) for m in msg) if r is not None] or None
            else:
                resp = handle(ctx, msg)
        if resp is not None:
            stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
            stdout.flush()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Buildout MCP server (stdio)")
    ap.add_argument("--data", help="folder with the engine's JSON outputs (default site/data or $BUILDOUT_DATA)")
    ap.add_argument("--config", help="model config (default config.toml or $BUILDOUT_CONFIG); config.private.toml is refused")
    a = ap.parse_args(argv)
    serve(Context(a.data, a.config))


if __name__ == "__main__":
    main()
