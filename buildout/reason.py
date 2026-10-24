"""Reasoning: deduction, induction, abduction and invented concepts, every claim walked forward and corrected for testing
many.

    panel       monthly features knowable at the start of each month (strictly lagged, as ml.panel) and six outcomes
    deduction   a forward-chaining Horn-clause engine over (subject, predicate, object) facts from the mind's typed edges:
                transitivity of is_a and part_of, inheritance down is_a, causal composition with sign algebra (paths of
                at most three causal edges), semi-naive evaluation to a fixpoint, a proof tree for every derived fact,
                contradictions (both signs on one ordered pair, is_a cycles). The engine's decision policy is encoded
                as rules too, so today's call comes with a proof and the threshold at which each premise flips it.
    induction   candidate conditions at quintile edges known at the discovery cutoff (single features and pairs),
                scored on the discovery period with Newey-West t statistics, Benjamini-Hochberg across everything
                tried, then tested on the untouched later period; rediscovered every ten years and tested on the next
                ten; externally supplied rules tested on the full sample and on each half; a skeptical Bayesian
                posterior that each surviving effect has its claimed sign.
    abduction   which conditions (and invented concepts) best explain an observed outcome, by likelihood ratio with
                Laplace smoothing; which rules fire today and what they jointly imply (naive Bayes, labelled).
    invention   regimes found by a Gaussian mixture on data to a cutoff (k by BIC), named by their most distinctive
                features, assigned later months by the fitted model only and scored out of sample; derived predicates
                (products and differences of standardized features) screened and tested the same way.

Little is expected to survive. A rule that wins in 1886 to 1960 and fails from 1961 is reported as having failed.

This is a research module. It never places orders.
"""
from __future__ import annotations

import json
import math
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from . import decide, labs, policy

FEATURES = ["cape_pct", "log_cape", "ecy", "y10", "dy12", "infl12", "infl36", "mom12_1", "trend_gap", "vol12", "drawdown",
            "corr36", "earn_g12", "earn_accel"]
OUTCOMES = ["ret12", "ret1", "crash12", "vol_next12", "maxdd12", "bond_hedge12"]
HORIZON = {"ret12": 12, "ret1": 1, "crash12": 12, "vol_next12": 12, "maxdd12": 12, "bond_hedge12": 36}
NW_LAGS = {"ret12": 12, "ret1": 0, "crash12": 12, "vol_next12": 12, "maxdd12": 12, "bond_hedge12": 36}
BINARY = {"crash12", "bond_hedge12"}
CRASH = -0.15
FDR = 0.10
MIN_N = 60
MIN_OOS = 24          # months inside and outside a condition for an out-of-sample test to count
TOP_K = 5
QUINTILES = (20, 40, 60, 80)
START_TEST = "1961-01"
CUTOFF = "1960-12"
SPLIT_YEAR = 1950
CONF_FLOOR = 0.4
SEED = 23

FEATURE_NAMES = {
    "cape_pct": "the CAPE's percentile in its own history", "log_cape": "log CAPE", "ecy": "the excess CAPE yield",
    "y10": "the 10-year yield", "dy12": "the 12-month change in the 10-year yield", "infl12": "12-month inflation",
    "infl36": "36-month inflation (annual rate)", "mom12_1": "12-1 month momentum", "trend_gap": "the distance from the 10-month average",
    "vol12": "12-month volatility (annualized)", "drawdown": "the distance below the peak", "corr36": "the 36-month stock-bond correlation",
    "earn_g12": "12-month real earnings growth", "earn_accel": "the 6-month change in earnings growth",
}
OUTCOME_NAMES = {
    "ret12": "the next 12 months' real total return (log)", "ret1": "the next month's real total return (log)",
    "crash12": "a fall of 15% or more within 12 months", "vol_next12": "the next 12 months' volatility (annualized)",
    "maxdd12": "the worst drawdown within 12 months", "bond_hedge12": "bonds hedging stocks over the next 36 months",
}
# plain words for a cluster that sits high / low on a feature; features in one family name a cluster once
WORDS = {
    "cape_pct": ("expensive", "cheap"), "log_cape": ("expensive", "cheap"), "ecy": ("stocks cheap against bonds", "stocks dear against bonds"),
    "y10": ("high rates", "low rates"), "dy12": ("rising rates", "falling rates"), "infl12": ("high inflation", "low inflation"),
    "infl36": ("high inflation", "low inflation"), "mom12_1": ("strong momentum", "weak momentum"), "trend_gap": ("above trend", "below trend"),
    "vol12": ("volatile", "calm"), "drawdown": ("near the peak", "deep below the peak"),
    "corr36": ("stocks and bonds moving together", "bonds hedging stocks"), "earn_g12": ("earnings growing", "earnings falling"),
    "earn_accel": ("earnings accelerating", "earnings decelerating"),
}
FAMILY = {"cape_pct": "valuation", "log_cape": "valuation", "infl12": "inflation", "infl36": "inflation", "earn_g12": "earnings",
          "earn_accel": "earnings_change"}

# Paraphrased, testable versions of well-known principles; the thresholds are the house's, not the authors'.
EXAMPLE_RULES = [
    {"id": "x:cape", "person": "Robert Shiller", "principle": "Expensive markets (high CAPE) are followed by lower real returns.",
     "if": [["cape_pct", ">", 0.8]], "then": {"outcome": "ret12", "direction": "down"}},
    {"id": "x:trend", "person": "Meb Faber", "principle": "Below its 10-month average the market is more prone to large falls.",
     "if": [["trend_gap", "<", 0.0]], "then": {"outcome": "crash12", "direction": "up"}},
    {"id": "x:fed", "person": "Martin Zweig", "principle": "Do not fight the Fed: sharply rising rates are followed by weaker stocks.",
     "if": [["dy12", ">", 0.01]], "then": {"outcome": "ret12", "direction": "down"}},
    {"id": "x:fear", "person": "Warren Buffett", "principle": "Be greedy when others are fearful: deep drawdowns are followed by higher returns.",
     "if": [["drawdown", "<", -0.25]], "then": {"outcome": "ret12", "direction": "up"}},
    {"id": "x:inflhedge", "person": "Ray Dalio", "principle": "When inflation runs high, bonds stop hedging stocks.",
     "if": [["infl36", ">", 0.04]], "then": {"outcome": "bond_hedge12", "direction": "down"}},
    {"id": "x:volcluster", "person": "Robert Engle", "principle": "Volatility clusters: a volatile year is followed by another.",
     "if": [["vol12", ">", 0.2]], "then": {"outcome": "vol_next12", "direction": "up"}},
]

DEFAULT_FACTS = {"corr36": 0.149, "infl36": 0.0306, "hedge_line": 0.0425, "gate": 0.0, "engine_exposure": 1.5, "es_1x": 0.0642,
                 "es_limit": 0.12, "trend_on": True, "overlay_factor": 1.0, "selector_choice": "stocks", "prev_state": "neutral"}


# ---------------------------------------------------------------- JSON safety
def _js(o, nd: int = 6):
    """Lists, rounded floats, None for NaN; dates as YYYY-MM."""
    if isinstance(o, dict):
        return {str(k): _js(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_js(v, nd) for v in o]
    if isinstance(o, np.ndarray):
        return [_js(v, nd) for v in o.tolist()]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return round(float(o), nd) if math.isfinite(float(o)) else None
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m")
    if o is None or isinstance(o, str):
        return o
    return str(o)


def _ym(d) -> str:
    return pd.Timestamp(d).strftime("%Y-%m")


# ---------------------------------------------------------------- 1. the panel
def panel(S: pd.DataFrame, gh: dict | None = None) -> pd.DataFrame:
    """Monthly features knowable at the start of each month and six outcomes.

    Features at month t use data through t - 1 (prices are monthly averages), earnings a further four-month publication
    lag, exactly as ml.panel; corr36 is the 36-month correlation of decide.data's stock and bond real returns through
    t - 1. Outcomes follow ml.panel's convention: the 12-month return runs from t to t + 12 on the total return index.
    With gh the 10-year yield is carried past where Shiller's long rate stops (as decide.data does)."""
    S = S.copy()
    if gh and "y10" in gh:
        from . import portfolio
        g10 = portfolio._gh_month(gh["y10"], "Rate").reindex(S.index)
        S["y10"] = S["y10"].where(S["y10"].notna(), g10)
    r, px, _ = labs.total_return_index(S)
    D = decide.data(S)
    idx = px.index
    cpi = S["cpi"]
    rp = (px / cpi).reindex(idx)
    tri = (1 + r).cumprod().reindex(idx)
    rr = r.reindex(idx)
    real_eps = (S["eps"] / cpi).shift(4)
    cape = (S["px"] / cpi) / real_eps.rolling(120, min_periods=120).mean()
    cape_l = cape.shift(1)
    infl10 = np.log(cpi.shift(1) / cpi.shift(121)) / 10
    y10 = S["y10"].shift(1) / 100
    p1 = px.shift(1)
    earn_g12 = np.log(real_eps.shift(1) / real_eps.shift(13))
    rb = D["r"].rolling(36).corr(D["b"]).reindex(idx)
    X = pd.DataFrame({
        "cape_pct": cape_l.expanding(min_periods=60).rank(pct=True),
        "log_cape": np.log(cape_l),
        "ecy": 1 / cape_l - (y10 - infl10),
        "y10": y10,
        "dy12": y10 - y10.shift(12),
        "infl12": np.log(cpi.shift(1) / cpi.shift(13)),
        "infl36": np.log(cpi.shift(1) / cpi.shift(37)) / 3,
        "mom12_1": np.log(px.shift(2) / px.shift(13)),
        "trend_gap": p1 / p1.rolling(10).mean() - 1,
        "vol12": rr.shift(1).rolling(12).std() * math.sqrt(12),
        "drawdown": rp.shift(1) / rp.shift(1).cummax() - 1,
        "corr36": rb.shift(1),
        "earn_g12": earn_g12,
        "earn_accel": earn_g12 - earn_g12.shift(6),
    }, index=idx)
    X = X.replace([np.inf, -np.inf], np.nan)
    lt = np.log(tri)
    X["ret12"] = lt.shift(-12) - lt
    X["ret1"] = lt.shift(-1) - lt
    fut = np.column_stack([rp.shift(-k).to_numpy() for k in range(1, 13)])
    with np.errstate(invalid="ignore"):
        X["crash12"] = (np.nanmin(np.where(np.isfinite(fut), fut, np.inf), 1) / rp.to_numpy() - 1 <= CRASH).astype(float)
    X["vol_next12"] = rr.rolling(12).std().shift(-12) * math.sqrt(12)
    path = np.column_stack([tri.shift(-k).to_numpy() for k in range(0, 13)])
    X["maxdd12"] = np.min(path / np.maximum.accumulate(path, axis=1) - 1, axis=1)
    fc = rb.shift(-36)
    X["bond_hedge12"] = (fc < 0).astype(float).where(fc.notna())
    gone = rp.shift(-12).isna() | tri.shift(-12).isna()
    X.loc[gone, ["ret12", "crash12", "vol_next12", "maxdd12"]] = np.nan
    X.loc[tri.shift(-1).isna(), "ret1"] = np.nan
    return X


def today_row(P: pd.DataFrame) -> tuple[pd.Series, dict]:
    """The latest month's features; where a series has stopped (Shiller's earnings, the long rate) the last known value
    is carried and named."""
    row = P[FEATURES].iloc[-1].copy()
    notes = {"date": _ym(P.index[-1]), "carried": {}}
    for f in FEATURES:
        if not np.isfinite(row[f]):
            s = P[f].dropna()
            if len(s):
                row[f] = s.iloc[-1]
                notes["carried"][f] = _ym(s.index[-1])
    return row, notes


# ---------------------------------------------------------------- 2. deduction
TYPED = ("is_a", "part_of", "measures", "uses", "opposes", "causes+", "causes-", "hedges", "example_of")
CAUSAL = ("causes+", "causes-")
INHERIT = ("causes+", "causes-", "hedges", "measures")


def _sign(p: str) -> int:
    return 1 if p == "causes+" else -1


def rules(max_len: int = 3) -> list[dict]:
    """The deductive rules, each sound for the relation it names.

    Valid: is_a, part_of transitive; X example_of Y and Y is_a Z give X example_of Z; opposes is symmetric; a kind
    inherits its class's causal effects, hedges and measures (X is_a Y and Y p Z give X p Z, a default that holds for a
    subtype); causal composition with sign algebra (A causes+ B and B causes- C give A causes- C), confidence
    multiplied, at most max_len causal edges in a chain, no self-causation.

    Not encoded, because it is not valid: "A causes- X and B causes+ X, so A hedges B". A hedge is a statement about
    the joint distribution of two returns (they move against each other in the states that matter); two causes acting
    on a common effect say nothing about how the causes move together. Even a common cause (Z causes+ A and Z causes- B)
    is only one channel, and other channels can outweigh it: stocks and bonds share the inflation channel, yet their
    correlation was positive for decades and negative for others. Hedging is learned from data (bond_hedge12), never
    deduced from signs. Likewise X p Y and Y is_a Z does not give X p Z for causes (raising one inflation measure does
    not raise every macro variable), so inheritance runs down the hierarchy only."""
    R = [
        {"name": "is_a.transitive", "body": [("?x", "is_a", "?y"), ("?y", "is_a", "?z")], "head": ("?x", "is_a", "?z")},
        {"name": "part_of.transitive", "body": [("?x", "part_of", "?y"), ("?y", "part_of", "?z")], "head": ("?x", "part_of", "?z")},
        {"name": "example_of.up", "body": [("?x", "example_of", "?y"), ("?y", "is_a", "?z")], "head": ("?x", "example_of", "?z")},
        {"name": "opposes.symmetric", "body": [("?x", "opposes", "?y")], "head": ("?y", "opposes", "?x")},
    ]
    for p in INHERIT:
        R.append({"name": f"inherit.{p}", "body": [("?x", "is_a", "?y"), ("?y", p, "?z")], "head": ("?x", p, "?z")})
    for p1 in CAUSAL:
        for p2 in CAUSAL:
            out = "causes+" if _sign(p1) * _sign(p2) > 0 else "causes-"
            R.append({"name": f"causal.{p1[-1]}{p2[-1]}", "body": [("?a", p1, "?b"), ("?b", p2, "?c")], "head": ("?a", out, "?c"),
                      "max_len": max_len, "distinct": ("?a", "?c")})
    return R


class _KB:
    """Facts with indexes by (predicate, subject) and (predicate, object); every fact keeps its rule and premises."""

    def __init__(self):
        self.s, self.p, self.o, self.c, self.L, self.rule, self.prem, self.prov = [], [], [], [], [], [], [], []
        self.key: dict[tuple, int] = {}
        self.ps: dict[tuple, list] = {}
        self.po: dict[tuple, list] = {}
        self.byp: dict[str, list] = {}

    def add(self, s, p, o, c, L, rule, prem, prov=""):
        k = (s, p, o)
        if k in self.key:
            return None
        i = len(self.s)
        self.key[k] = i
        for lst, v in ((self.s, s), (self.p, p), (self.o, o), (self.c, c), (self.L, L), (self.rule, rule), (self.prem, prem), (self.prov, prov)):
            lst.append(v)
        self.ps.setdefault((p, s), []).append(i)
        self.po.setdefault((p, o), []).append(i)
        self.byp.setdefault(p, []).append(i)
        return i

    def lookup(self, pat, b):
        s, p, o = (b.get(x, x) if isinstance(x, str) and x.startswith("?") else x for x in pat)
        sv, ov = s.startswith("?"), o.startswith("?")
        if not sv and not ov:
            i = self.key.get((s, p, o))
            return [] if i is None else [i]
        if not sv:
            return self.ps.get((p, s), [])
        if not ov:
            return self.po.get((p, o), [])
        return self.byp.get(p, [])


def _unify(pat, s, p, o, b):
    if pat[1] != p:
        return None
    b = dict(b)
    for x, v in ((pat[0], s), (pat[2], o)):
        if x.startswith("?"):
            if x in b and b[x] != v:
                return None
            b[x] = v
        elif x != v:
            return None
    return b


def graph_facts(G: dict, learned: bool = False) -> list[tuple]:
    """(subject, predicate, object, confidence, provenance) from the mind's typed edges, 'related' and the other
    untyped kinds ignored. Edges are [i, j, weight, type index] (the stored form) or [a, b, type, weight]."""
    nodes = G["nodes"]
    types = G.get("types", [])
    out = []
    for e in G.get("edges", []):
        if isinstance(e[2], str):
            a, b, typ, w = e[0], e[1], e[2], float(e[3])
        else:
            a, b, w, typ = e[0], e[1], float(e[2]), types[int(e[3])]
        if typ not in TYPED:
            continue
        a = nodes[a]["id"] if isinstance(a, int) else a
        b = nodes[b]["id"] if isinstance(b, int) else b
        out.append((a, typ, b, float(w), "mind.json"))
    if learned:
        for i, j, w in G.get("causal", []):
            out.append((nodes[i]["id"], "causes+" if w > 0 else "causes-", nodes[j]["id"], min(1.0, abs(float(w))), "atlas (learned)"))
    return out


def deduce(G: dict | list, max_len: int = 3, max_steps: int = 30, max_facts: int = 400_000, floor: float = CONF_FLOOR,
           learned: bool = False) -> dict:
    """Semi-naive forward chaining to a fixpoint. G is a mind graph or a list of (s, p, o[, conf[, provenance]]).

    Returns the full fact table (given and derived; each row [s, p, o, conf, causal_len, rule, premise rows,
    provenance]), counts by rule, contradictions, the number of rounds and whether the fixpoint was reached. The first
    derivation of a fact is kept, which under semi-naive order is a shortest one."""
    if isinstance(G, dict):
        base = graph_facts(G, learned)
        names = {n["id"]: n.get("n", n["id"]) for n in G["nodes"]}
    else:
        base = [(f[0], f[1], f[2], float(f[3]) if len(f) > 3 else 1.0, f[4] if len(f) > 4 else "given") for f in G]
        names = {}
    kb = _KB()
    delta = []
    for s, p, o, c, prov in base:
        i = kb.add(s, p, o, c, 1 if p in CAUSAL else 0, "given", (), prov)
        if i is not None:
            delta.append(i)
    R = rules(max_len)
    counts = {r["name"]: 0 for r in R}
    steps, fix = 0, False
    while delta and steps < max_steps and len(kb.s) < max_facts:
        steps += 1
        dset = set(delta)
        pend: dict[tuple, tuple] = {}
        for r in R:
            body = r["body"]
            for pos, pat in enumerate(body):
                for i in delta:
                    if kb.p[i] != pat[1]:
                        continue
                    b0 = _unify(pat, kb.s[i], kb.p[i], kb.o[i], {})
                    if b0 is None:
                        continue
                    frames = [(b0, {pos: i})]
                    for qpos, q in enumerate(body):
                        if qpos == pos:
                            continue
                        nxt = []
                        for b, used in frames:
                            for j in kb.lookup(q, b):
                                if qpos < pos and j in dset:            # each combination once: earlier atoms from older facts
                                    continue
                                bb = _unify(q, kb.s[j], kb.p[j], kb.o[j], b)
                                if bb is not None:
                                    nxt.append((bb, {**used, qpos: j}))
                        frames = nxt
                    for b, used in frames:
                        prem = tuple(used[k] for k in range(len(body)))
                        hs, hp, ho = (b.get(x, x) for x in r["head"])
                        if "distinct" in r and b[r["distinct"][0]] == b[r["distinct"][1]]:
                            continue
                        L = sum(kb.L[j] for j in prem) if hp in CAUSAL else 0
                        if r.get("max_len") and L > r["max_len"]:
                            continue
                        k = (hs, hp, ho)
                        if k in kb.key or k in pend:
                            continue
                        pend[k] = (float(np.prod([kb.c[j] for j in prem])), L, r["name"], prem)
        delta = []
        for (hs, hp, ho), (c, L, rn, prem) in pend.items():
            i = kb.add(hs, hp, ho, c, L, rn, prem, "derived")
            if i is not None:
                delta.append(i)
                counts[rn] += 1
            if len(kb.s) >= max_facts:
                break
    fix = not delta
    table = [[kb.s[i], kb.p[i], kb.o[i], kb.c[i], kb.L[i], kb.rule[i], list(kb.prem[i]), kb.prov[i]] for i in range(len(kb.s))]
    D = {"facts": table, "n_given": sum(1 for t in table if t[5] == "given"), "counts": counts, "steps": steps, "fixpoint": fix,
         "max_len": max_len, "floor": floor, "names": names}
    D["n_derived"] = len(table) - D["n_given"]
    D["contradictions"] = contradictions(D, floor)
    return D


def _index(D: dict) -> dict:
    ix = D.get("_ix")
    if ix is None or len(ix) != len(D["facts"]):
        ix = {(t[0], t[1], t[2]): i for i, t in enumerate(D["facts"])}
        D["_ix"] = ix
    return ix


def contradictions(D: dict, floor: float = CONF_FLOOR) -> list[dict]:
    """The same ordered pair derived with both causal signs, each at or above the confidence floor; is_a and part_of
    cycles (a kind of itself); a pair that is both is_a and opposes."""
    ix = _index(D)
    F = D["facts"]
    out = []
    for i, t in enumerate(F):
        s, p, o, c = t[0], t[1], t[2], t[3]
        if p == "causes+" and c >= floor:
            j = ix.get((s, "causes-", o))
            if j is not None and F[j][3] >= floor:
                out.append({"kind": "sign", "pair": [s, o], "plus": prove((s, "causes+", o), D), "minus": prove((s, "causes-", o), D),
                            "conf": [c, F[j][3]]})
        if p in ("is_a", "part_of") and s == o:
            out.append({"kind": f"{p}_cycle", "node": s, "proof": prove((s, p, o), D)})
        if p == "is_a" and ix.get((s, "opposes", o)) is not None:
            out.append({"kind": "is_a_and_opposes", "pair": [s, o], "proof": prove((s, p, o), D)})
    return out


def prove(fact, D: dict) -> dict | None:
    """The proof tree of a fact: its rule and the proofs of its premises, down to given facts."""
    ix = _index(D)
    i = ix.get(tuple(fact[:3]))
    if i is None:
        return None

    def tree(k: int) -> dict:
        t = D["facts"][k]
        node = {"fact": [t[0], t[1], t[2]], "conf": t[3], "rule": t[5]}
        if t[5] == "given":
            node["provenance"] = t[7]
        else:
            node["premises"] = [tree(j) for j in t[6]]
        return node
    return tree(i)


def _leaves(tr: dict) -> list:
    if tr.get("rule") == "given":
        return [tr["fact"]]
    return [x for p in tr.get("premises", []) for x in _leaves(p)]


def _resolve(x: str, D: dict) -> str:
    names = D.get("names") or {}
    if x in names or not names:
        return x
    lx = x.lower()
    for k, v in names.items():
        if str(v).lower() == lx:
            return k
    return x


def explain_path(a: str, c: str, D: dict) -> dict:
    """How a relates to c: every derived or given fact (a, p, c) with its proof and the chain of given facts behind
    it; if nothing was derived, the shortest chain of given typed facts between them (either direction)."""
    a, c = _resolve(a, D), _resolve(c, D)
    ix = _index(D)
    names = D.get("names") or {}
    found = []
    for p in TYPED:
        i = ix.get((a, p, c))
        if i is not None:
            tr = prove((a, p, c), D)
            ch = _leaves(tr)
            found.append({"relation": p, "conf": D["facts"][i][3], "rule": D["facts"][i][5], "proof": tr, "chain": ch,
                          "text": " ; ".join(f"{names.get(s, s)} {pp} {names.get(o, o)}" for s, pp, o in ch)})
    if found:
        return {"from": a, "to": c, "derived": True, "paths": found}
    adj: dict[str, list] = {}
    for t in D["facts"]:
        if t[5] == "given":
            adj.setdefault(t[0], []).append((t[2], [t[0], t[1], t[2]]))
            adj.setdefault(t[2], []).append((t[0], [t[0], t[1], t[2]]))
    prev = {a: None}
    q = [a]
    while q and c not in prev:
        nq = []
        for u in q:
            for v, f in adj.get(u, []):
                if v not in prev:
                    prev[v] = (u, f)
                    nq.append(v)
        q = nq
        if len(prev) > 200_000:
            break
    if c not in prev:
        return {"from": a, "to": c, "derived": False, "paths": [], "text": "No typed connection."}
    ch = []
    v = c
    while prev[v] is not None:
        u, f = prev[v]
        ch.append(f)
        v = u
    ch = ch[::-1]
    return {"from": a, "to": c, "derived": False, "paths": [{"relation": "connection", "chain": ch,
            "text": " ; ".join(f"{names.get(s, s)} {pp} {names.get(o, o)}" for s, pp, o in ch)}],
            "text": "Nothing follows deductively; this is the shortest chain of given facts, which proves no relation."}


# ---------------------------------------------------------------- 2b. the decision policy as rules
def _grid_round(x: float) -> float:
    return float(round(x / 0.05) * 0.05)


def _policy(f: dict) -> dict:
    """Conclusions of the policy rules on the facts (no proof): state, bond hedge, exposure, overlay, hedge choice."""
    enter, exit_ = policy.HEDGE_PARAMS["enter"], policy.HEDGE_PARAMS["exit"]
    c = float(f["corr36"])
    prev = f.get("prev_state", "neutral")
    if prev == "hedging" and c <= exit_:
        state, srule = "hedging", "state.hold"
    elif prev == "amplifying" and c >= -exit_:
        state, srule = "amplifying", "state.hold_amp"
    elif c <= enter:
        state, srule = "hedging", "state.enter"
    elif c >= -enter:
        state, srule = "amplifying", "state.amplify"            # the page's stockBondState (engine7.js): symmetric bands
    else:
        state, srule = "neutral", "state.neutral"
    below = float(f["infl36"]) < float(f["hedge_line"])
    on = state == "hedging" and below
    gated = _grid_round(1 + float(f["gate"]) * (float(f["engine_exposure"]) - 1))
    es1 = max(float(f["es_1x"]), 1e-12)
    ok = decide.GRID * es1 <= float(f["es_limit"]) + 1e-12
    ok[0] = True
    cap = float(decide.GRID[np.flatnonzero(ok)[-1]])
    pre = min(gated, cap)
    trend_on = bool(f["trend_on"])
    fac = float(f["overlay_factor"])
    if trend_on or fac >= 1.0:
        overlay, x = "none", pre
    else:
        overlay, x = "applied", _grid_round(pre * fac)
    choice = f.get("selector_choice", "stocks")
    return {"state": state, "state_rule": srule, "inflation_below_line": below, "bond_hedge": "on" if on else "off", "gated": gated, "es_cap": cap,
            "capped": bool(cap < gated), "pre_overlay": pre, "overlay": overlay, "exposure": round(x, 6), "hedge_choice": choice,
            "hedge_name": decide.HEDGE_NAMES.get(choice, choice)}


POLICY_RULES = [
    {"name": "state.enter", "text": "If the 36-month stock-bond correlation is at or below -0.10, the state is hedging."},
    {"name": "state.hold", "text": "If the state was hedging and the correlation is at or below 0, it stays hedging (hysteresis)."},
    {"name": "state.amplify", "text": "If the correlation is at or above +0.10, the state is amplifying: stocks and bonds fall together."},
    {"name": "state.hold_amp", "text": "If the state was amplifying and the correlation is at or above 0, it stays amplifying (hysteresis)."},
    {"name": "state.neutral", "text": "Otherwise the state is neutral."},
    {"name": "line.below", "text": "Inflation is below the line if 36-month inflation is under the hedge line."},
    {"name": "hedge.tlt.v2", "text": "The bond hedge is on if and only if the state is hedging and inflation is below the line."},
    {"name": "gate.scale", "text": "The gated exposure is 1 + gate x (engine exposure - 1), on the 0.05 grid."},
    {"name": "risk.budget", "text": "The cap is the largest exposure on the grid whose expected shortfall (exposure x ES at 1x) is within the limit."},
    {"name": "risk.cap", "text": "The exposure before the overlay is the smaller of the gated exposure and the cap."},
    {"name": "overlay.none", "text": "No overlay if the trend is on or the adopted factor is at least 1."},
    {"name": "overlay.apply", "text": "Otherwise the exposure is scaled by the factor, on the 0.05 grid."},
    {"name": "selector.choose", "text": "The hedge mix is the Bayesian selector's choice."},
]

_CF_RANGE = {"corr36": (-1.0, 1.0), "infl36": (-0.05, 0.20), "hedge_line": (-0.05, 0.20), "gate": (0.0, 1.0), "engine_exposure": (0.0, 1.5),
             "es_1x": (0.001, 0.5), "es_limit": (0.001, 0.5), "overlay_factor": (0.0, 1.0)}


def _key(c: dict) -> tuple:
    return (c["bond_hedge"], c["exposure"], c["overlay"])


def _flip(f: dict, k: str, lo: float, hi: float) -> dict:
    base = _key(_policy(f))
    x0 = float(f[k])
    out = {}
    for side, end in (("up", hi), ("down", lo)):
        if (side == "up" and x0 >= hi) or (side == "down" and x0 <= lo):
            out[side] = None
            continue
        g = np.linspace(x0, end, 801)[1:]
        hit = None
        prev = x0
        for v in g:
            if _key(_policy({**f, k: float(v)})) != base:
                hit = (prev, float(v))
                break
            prev = float(v)
        if hit is None:
            out[side] = None
            continue
        a, b = hit
        for _ in range(60):
            m = (a + b) / 2
            if _key(_policy({**f, k: m})) != base:
                b = m
            else:
                a = m
        new = _policy({**f, k: b})
        out[side] = {"at": round(b, 6), "bond_hedge": new["bond_hedge"], "exposure": new["exposure"], "overlay": new["overlay"]}
    return out


def decision_proof(facts: dict | None = None) -> dict:
    """Today's call derived by the policy rules, with a proof tree whose leaves are the input facts and whose nodes
    name the rule used, and for each premise the value at which a conclusion (bond hedge, exposure, overlay) flips."""
    f = {**DEFAULT_FACTS, **(facts or {})}
    c = _policy(f)
    leaf = lambda k: {"fact": f"{k} = {f[k]}", "given": True}
    state = {"conclusion": f"state = {c['state']}", "rule": c["state_rule"],
             "premises": [leaf("corr36")] + ([leaf("prev_state")] if c["state_rule"] in ("state.hold", "state.hold_amp", "state.neutral") else [])}
    line = {"conclusion": f"inflation below line = {c['inflation_below_line']}", "rule": "line.below", "premises": [leaf("infl36"), leaf("hedge_line")]}
    hedge = {"conclusion": f"bond hedge = {c['bond_hedge']}", "rule": "hedge.tlt.v2", "premises": [state, line]}
    gated = {"conclusion": f"gated exposure = {c['gated']:.2f}x", "rule": "gate.scale", "premises": [leaf("gate"), leaf("engine_exposure")]}
    cap = {"conclusion": f"risk cap = {c['es_cap']:.2f}x", "rule": "risk.budget", "premises": [leaf("es_1x"), leaf("es_limit")]}
    pre = {"conclusion": f"exposure before overlay = {c['pre_overlay']:.2f}x", "rule": "risk.cap", "premises": [gated, cap]}
    ov = {"conclusion": f"overlay = {c['overlay']}", "rule": "overlay.none" if c["overlay"] == "none" else "overlay.apply",
          "premises": [leaf("trend_on"), leaf("overlay_factor"), pre]}
    expo = {"conclusion": f"exposure = {c['exposure']:.2f}x", "rule": ov["rule"], "premises": [ov]}
    sel = {"conclusion": f"hedge mix = {c['hedge_name']}", "rule": "selector.choose", "premises": [leaf("selector_choice")]}
    tree = {"conclusion": f"decision: {c['exposure']:.2f}x stocks, bond hedge {c['bond_hedge']}, mix {c['hedge_name'].lower()}",
            "rule": "decision", "premises": [expo, hedge, sel]}
    cf = []
    for k, (lo, hi) in _CF_RANGE.items():
        fl = _flip(f, k, lo, hi)
        row = {"premise": k, "now": f[k], "flips_up": fl["up"], "flips_down": fl["down"]}
        if fl["up"] is None and fl["down"] is None:
            row["why_not"] = _why_not(k, c)
        cf.append(row)
    for k, alt in (("trend_on", not f["trend_on"]), ("prev_state", "neutral" if f.get("prev_state") == "hedging" else "hedging")):
        new = _policy({**f, k: alt})
        cf.append({"premise": k, "now": f.get(k), "if": alt, "changes": _key(new) != _key(c),
                   "bond_hedge": new["bond_hedge"], "exposure": new["exposure"], "overlay": new["overlay"]})
    for alt in decide.HEDGES:
        if alt != f.get("selector_choice"):
            cf.append({"premise": "selector_choice", "now": f.get("selector_choice"), "if": alt, "changes": True,
                       "hedge_name": decide.HEDGE_NAMES[alt]})
    return {"facts": f, "conclusions": c, "proof": tree, "rules": POLICY_RULES, "counterfactuals": cf}


def _why_not(k: str, c: dict) -> str:
    if k in ("infl36", "hedge_line"):
        return "The state is not hedging, so inflation alone cannot turn the bond hedge on." if c["state"] != "hedging" else "No value in range flips it."
    if k == "engine_exposure":
        return "The evidence gate is 0, so the engine's own optimum cannot move the book."
    if k == "overlay_factor":
        return "The trend is on, so the overlay factor is not used."
    return "No value in range flips a conclusion."


# ---------------------------------------------------------------- 3. induction
def _diff_t(Y: np.ndarray, M: np.ndarray, lags: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For each mask column: mean of Y inside minus outside, its Newey-West t (the slope of Y on the indicator), and the
    count inside. Vectorized over columns."""
    n = len(Y)
    Mf = M.astype(float)
    n1 = Mf.sum(0)
    p = n1 / n
    with np.errstate(invalid="ignore", divide="ignore"):
        m1 = (Y @ Mf) / n1
        m0 = (Y.sum() - Y @ Mf) / (n - n1)
        eff = m1 - m0
        U = (Mf - p) * (Y[:, None] - m0 - eff * Mf)
        s = (U * U).sum(0) / n
        for l in range(1, lags + 1):
            s += 2 * (1 - l / (lags + 1)) * (U[l:] * U[:-l]).sum(0) / n
        se = np.sqrt(np.maximum(s, 1e-18) / n) / (p * (1 - p))
        t = eff / se
    return eff, np.where(np.isfinite(t), t, 0.0), n1


def _cond_mask(X: dict, conds) -> np.ndarray:
    m = None
    for f, op, v in conds:
        x = X[f]
        with np.errstate(invalid="ignore"):
            c = {"<": x < v, "<=": x <= v, ">": x > v, ">=": x >= v, "==": x == v}[op]
        m = c if m is None else m & c
    return m


def _text(conds, edges_q: dict | None = None, cutoff: str | None = None) -> str:
    parts = []
    for c in conds:
        f, op, v = c[0], c[1], c[2]
        q = c[3] if len(c) > 3 else None
        word = {"<": "below", "<=": "at or below", ">": "above", ">=": "at or above", "==": "equal to"}[op]
        s = f"{FEATURE_NAMES.get(f, f)} {word} {v:.3g}"
        if q is not None:
            s += f" (its {q}th percentile{' to ' + cutoff[:4] if cutoff else ''})"
        parts.append(s)
    return " and ".join(parts)


class _Cands:
    """Single conditions at quintile edges, and pairs of different features."""

    def __init__(self, Xd: np.ndarray, feats: list[str], pairs: bool = True):
        self.feats = feats
        self.edges = {f: np.quantile(Xd[:, j], [q / 100 for q in QUINTILES]) for j, f in enumerate(feats)}
        self.singles = []
        for f in feats:
            for q, e in zip(QUINTILES, self.edges[f]):
                self.singles.append((f, "<=", float(e), q))
                self.singles.append((f, ">", float(e), q))
        ns = len(self.singles)
        ca, cb = list(range(ns)), [-1] * ns
        if pairs:
            for a, b in combinations(range(ns), 2):
                if self.singles[a][0] != self.singles[b][0]:
                    ca.append(a)
                    cb.append(b)
        self.ca, self.cb = np.array(ca), np.array(cb)

    def single_masks(self, X: np.ndarray) -> np.ndarray:
        j = {f: i for i, f in enumerate(self.feats)}
        cols = []
        for f, op, v, _ in self.singles:
            x = X[:, j[f]]
            cols.append(x <= v if op == "<=" else x > v)
        return np.column_stack(cols + [np.ones(len(X), bool)])

    def conds(self, k: int) -> list:
        out = [self.singles[self.ca[k]]]
        if self.cb[k] >= 0:
            out.append(self.singles[self.cb[k]])
        return [list(c) for c in out]

    def score(self, Y: np.ndarray, Sm: np.ndarray, lags: int, min_n: int = MIN_N, chunk: int = 1500):
        K = len(self.ca)
        eff, t, n1 = np.zeros(K), np.zeros(K), np.zeros(K)
        cb = np.where(self.cb >= 0, self.cb, Sm.shape[1] - 1)
        for s0 in range(0, K, chunk):
            sl = slice(s0, min(K, s0 + chunk))
            M = Sm[:, self.ca[sl]] & Sm[:, cb[sl]]
            eff[sl], t[sl], n1[sl] = _diff_t(Y, M, lags)
        ok = (n1 >= min_n) & (len(Y) - n1 >= min_n)
        p = np.where(ok, 2 * stats.norm.sf(np.abs(t)), np.nan)
        return eff, t, n1, ok, p


def _frame(P: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    return P[P[feats].notna().all(axis=1)]


def _purged(index: pd.DatetimeIndex, end: pd.Timestamp, h: int) -> np.ndarray:
    """Rows whose outcome window (h months) ended before `end`."""
    return (index + pd.DateOffset(months=h)) < end


def _pick(order, masks_fn, k: int, jac: float = 0.7) -> list[int]:
    """Greedy top-k by |t|, skipping a candidate whose rows overlap a kept one's by more than `jac` (Jaccard)."""
    kept, km = [], []
    for i in order:
        m = masks_fn(i)
        if any((m & q).sum() / max(1, (m | q).sum()) > jac for q in km):
            continue
        kept.append(int(i))
        km.append(m)
        if len(kept) >= k:
            break
    return kept


def _boot_p(Y: np.ndarray, m: np.ndarray, B: int = 300, block: float = 24, seed: int = SEED) -> float:
    """Stationary-bootstrap p value of the difference in means (blocks of 24 months on average, centred)."""
    rng = np.random.default_rng(seed)
    idx = labs.stationary_bootstrap_idx(len(Y), B, block, rng)
    Yb, Mb = Y[idx], m[idx]
    n1 = Mb.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        d = (Yb * Mb).sum(1) / n1 - (Yb * ~Mb).sum(1) / (len(Y) - n1)
    d = d[np.isfinite(d)]
    e = Y[m].mean() - Y[~m].mean()
    return float((np.sum(np.abs(d - e) >= abs(e)) + 1) / (len(d) + 1))


def _oos(Y: np.ndarray, m: np.ndarray, lags: int, sign: int, min_n: int = MIN_OOS) -> dict:
    """The out-of-sample test of one condition. With fewer than min_n months inside or outside it the rule is
    untestable there (its effect is shown, but it neither keeps nor loses its sign)."""
    n_in, n = int(m.sum()), int(len(m))
    rec = {"effect": None, "t": None, "p_one": 1.0, "n_in": n_in, "n": n, "kept_sign": None, "testable": False}
    if 0 < n_in < n:
        e2, t2, _ = _diff_t(Y, m[:, None], lags)
        rec["effect"] = float(e2[0])
        if n_in >= min_n and n - n_in >= min_n:
            rec.update({"t": float(t2[0]), "p_one": float(stats.norm.sf(sign * t2[0])), "kept_sign": bool(np.sign(e2[0]) == sign), "testable": True})
    return rec


def _discover_one(Q: pd.DataFrame, feats: list[str], outcome: str, test_start: pd.Timestamp, test_end: pd.Timestamp | None,
                  top_k: int, min_n: int, pairs: bool, boot: bool):
    """Candidates scored on rows whose outcome was known before test_start; the top tested on [test_start, test_end)."""
    h, lags = HORIZON[outcome], NW_LAGS[outcome]
    idx = Q.index
    fin = Q[outcome].notna().to_numpy()
    dsel = fin & _purged(idx, test_start, h)
    tsel = fin & (idx >= test_start) & ((idx < test_end) if test_end is not None else True)
    Xall = Q[feats].to_numpy()
    C = _Cands(Xall[idx < test_start], feats, pairs)
    Xd, Yd = Xall[dsel], Q[outcome].to_numpy()[dsel]
    Sd = C.single_masks(Xd)
    eff, t, n1, ok, p = C.score(Yd, Sd, lags, min_n)
    cb = np.where(C.cb >= 0, C.cb, Sd.shape[1] - 1)
    order = np.argsort(-np.where(ok, np.abs(t), -1))
    order = order[ok[order]]
    kept = _pick(order, lambda i: Sd[:, C.ca[i]] & Sd[:, cb[i]], top_k)
    Xt, Yt = Xall[tsel], Q[outcome].to_numpy()[tsel]
    St = C.single_masks(Xt) if len(Xt) else None
    rows = []
    for i in kept:
        rec = {"outcome": outcome, "if": [c[:3] for c in C.conds(i)], "quintiles": [c[3] for c in C.conds(i)],
               "direction": int(np.sign(eff[i])),
               "disc": {"effect": eff[i], "t": t[i], "p": p[i], "n_in": int(n1[i]), "n": int(len(Yd)),
                        "mean_in": float(Yd[Sd[:, C.ca[i]] & Sd[:, cb[i]]].mean())}}
        if boot:
            rec["disc"]["boot_p"] = _boot_p(Yd, Sd[:, C.ca[i]] & Sd[:, cb[i]])
        if St is not None and len(Yt) > 2:
            rec["oos"] = _oos(Yt, St[:, C.ca[i]] & St[:, cb[i]], lags, rec["direction"])
        rows.append((i, rec))
    meta = {"tried": int(ok.sum()), "disc_from": _ym(idx[dsel][0]) if dsel.any() else None, "disc_to": _ym(idx[dsel][-1]) if dsel.any() else None,
            "disc_months": int(dsel.sum()), "test_months": int(tsel.sum()), "edges": {f: C.edges[f].tolist() for f in feats}}
    return p[ok], rows, meta, (C, eff, t, ok)


def discover(P: pd.DataFrame, outcomes=OUTCOMES, start_test: str = START_TEST, top_k: int = TOP_K, fdr: float = FDR, min_n: int = MIN_N,
             pairs: bool = True, feats: list[str] | None = None, boot: bool = True) -> dict:
    """Every condition at a quintile edge (edges from data before start_test), alone and in pairs of different
    features, scored on the discovery period (outcome known before start_test) by the difference in mean outcome
    against the complement, with Newey-West t (12 lags for the 12-month outcomes, 36 for the 36-month one, 0 for the
    next month). Benjamini-Hochberg runs across every candidate tried for every outcome. The top candidates per outcome
    (de-duplicated by overlap) are tested on the untouched later period with the same thresholds; a survivor has a
    discovery q at or below the FDR and an out-of-sample one-sided p, BH-adjusted across the candidates tested, at or
    below it too, with the sign kept."""
    feats = [f for f in (feats or FEATURES) if f in P]
    outcomes = [o for o in outcomes if o in P]
    Q = _frame(P, feats)
    ts = pd.Timestamp(start_test)
    allp, per, recs = [], {}, []
    for o in outcomes:
        pv, rows, meta, _ = _discover_one(Q, feats, o, ts, None, top_k, min_n, pairs, boot)
        allp.append(pv)
        per[o] = meta
        recs.append(rows)
    flat = np.concatenate(allp) if allp else np.array([])
    q = np.array(labs.bh(flat.tolist())) if len(flat) else np.array([])
    # the q value of each kept candidate: its p's position in the pooled ranking
    off = 0
    qmap = []
    for o, pv in zip(outcomes, allp):
        qmap.append(q[off:off + len(pv)])
        off += len(pv)
    tested = []
    for o, rows, pv, qq in zip(outcomes, recs, allp, qmap):
        per[o]["bh_significant"] = int((qq <= fdr).sum())
        sp = np.sort(pv)
        for i, rec in rows:
            k = int(np.searchsorted(sp, rec["disc"]["p"], side="left"))
            rec["disc"]["q"] = float(np.sort(qq)[min(k, len(qq) - 1)]) if len(qq) else 1.0
            tested.append(rec)
    po = [r["oos"]["p_one"] if "oos" in r else 1.0 for r in tested]
    qo = labs.bh(po) if po else []
    out_rules = []
    for n, (r, qv) in enumerate(zip(tested, qo)):
        r["id"] = f"d:{r['outcome']}:{n}"
        if "oos" in r:
            r["oos"]["q"] = float(qv)
        r["survives"] = bool(r["disc"]["q"] <= fdr and "oos" in r and r["oos"]["testable"] and r["oos"]["kept_sign"] and r["oos"]["q"] <= fdr)
        r["text"] = f"If {_text([c + [qq] for c, qq in zip(r['if'], r['quintiles'])], cutoff=_ym(ts - pd.DateOffset(months=1)))}, " \
                    f"{OUTCOME_NAMES[r['outcome']]} is {'higher' if r['direction'] > 0 else 'lower'}"
        out_rules.append(r)
    return {"start_test": start_test, "fdr": fdr, "min_n": min_n, "features": feats, "outcomes": outcomes,
            "n_candidates": int(len(flat)), "bh_significant": int((q <= fdr).sum()) if len(q) else 0, "per_outcome": per,
            "rules": out_rules, "survivors": [r["id"] for r in out_rules if r["survives"]],
            "kept_sign": int(sum(1 for r in out_rules if r.get("oos", {}).get("kept_sign"))), "tested": len(out_rules),
            "testable": int(sum(1 for r in out_rules if r.get("oos", {}).get("testable"))), "min_oos": MIN_OOS}


def rolling(P: pd.DataFrame, outcomes=OUTCOMES, first: int = 1931, step: int = 10, top_k: int = 3, min_n: int = MIN_N,
            pairs: bool = True, feats: list[str] | None = None) -> dict:
    """Rediscover every ten years on the data to date and test on the next ten. A rule 'held' in a decade if its
    effect kept its sign there; 'significant' if also one-sided p below 5%."""
    feats = [f for f in (feats or FEATURES) if f in P]
    Q = _frame(P, feats)
    last = Q.index[-1].year
    out = {}
    for o in [o for o in outcomes if o in P]:
        dec = []
        for y in range(first, last, step):
            ts, te = pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y + step}-01-01")
            fin = Q[o].notna() & (Q.index >= ts) & (Q.index < te)
            if fin.sum() < 36:
                continue
            _, rows, meta, _ = _discover_one(Q, feats, o, ts, te, top_k, min_n, pairs, False)
            if meta["disc_months"] < 240 or not rows:
                continue
            res = []
            for _, r in rows:
                oo = r.get("oos", {})
                res.append({"rule": _text(r["if"]), "disc_t": r["disc"]["t"], "oos_effect": oo.get("effect"), "oos_t": oo.get("t"), "months_in": oo.get("n_in"),
                            "held": oo.get("kept_sign"), "significant": bool(oo.get("kept_sign") and (oo.get("p_one") or 1) < 0.05) if oo.get("testable") else None})
            dec.append({"from": y, "to": y + step - 1, "disc_months": meta["disc_months"], "test_months": meta["test_months"], "top": res[0], "others": res[1:]})
        tops = [d["top"] for d in dec if d["top"]["held"] is not None]
        alls = [x for d in dec for x in [d["top"]] + d["others"] if x["held"] is not None]
        nt = len(tops)
        out[o] = {"decades": dec, "n": len(dec), "testable": nt,
                  "share_held": sum(x["held"] for x in tops) / nt if nt else None,
                  "share_significant": sum(x["significant"] for x in tops) / nt if nt else None,
                  "share_reversed_significant": sum(1 for x in tops if not x["held"] and x["oos_t"] is not None and abs(x["oos_t"]) > 1.96) / nt if nt else None,
                  "share_held_top3": float(np.mean([x["held"] for x in alls])) if alls else None, "testable_top3": len(alls)}
    return out


def _direction(d) -> int:
    if isinstance(d, (int, float)):
        return int(np.sign(d))
    d = str(d).lower()
    return 1 if d in ("up", "higher", "more", "+", "positive", "increase", "rises") else -1


def bayes_sign(effect: float, se: float, tau: float, sign: int) -> float:
    """Posterior probability that the true effect has `sign`, under a skeptical N(0, tau^2) prior and a normal
    likelihood with the Newey-West standard error."""
    if not (np.isfinite(effect) and np.isfinite(se) and se > 0 and tau > 0):
        return float("nan")
    w = tau ** 2 / (tau ** 2 + se ** 2)
    m, s = w * effect, math.sqrt(w) * se
    return float(stats.norm.cdf(sign * m / s))


def _tau(P: pd.DataFrame, outcome: str) -> float:
    return 0.5 * float(P[outcome].std())


def test_rules(P: pd.DataFrame, rules_in: list[dict], fdr: float = FDR, split: int = SPLIT_YEAR) -> list[dict]:
    """Externally supplied rules {"id","person","principle","if":[[var, op, number], ...],"then":{"outcome","direction"}}:
    the full-sample difference in mean outcome (inside the condition minus outside) with its Newey-West t, the halves
    before and after `split`, BH across the supplied rules, a verdict and a skeptical Bayesian posterior."""
    out, ps = [], []
    for r in rules_in:
        th = r.get("then") or {}
        o = th.get("outcome")
        conds = [list(c) for c in r.get("if", [])]
        rec = {"id": r.get("id"), "person": r.get("person"), "principle": r.get("principle"), "if": conds, "outcome": o,
               "direction": _direction(th.get("direction", "up")), "source": r.get("source", "supplied")}
        bad = [c[0] for c in conds if c[0] not in P] + ([o] if o not in P else [])
        if bad or not conds:
            rec.update({"verdict": "untestable", "why": f"unknown variable {bad[0]}" if bad else "no condition"})
            out.append(rec)
            ps.append(None)
            continue
        cols = [c[0] for c in conds] + [o]
        Q = P[P[cols].notna().all(axis=1)]
        X = {c: Q[c].to_numpy() for c in cols}
        m = _cond_mask(X, [(c[0], c[1], float(c[2])) for c in conds])
        Y = Q[o].to_numpy()
        lags = NW_LAGS[o]

        def est(sel):
            mm = m[sel]
            if mm.sum() < 12 or (~mm).sum() < 12:
                return {"effect": None, "t": None, "n_in": int(mm.sum()), "n": int(sel.sum())}
            e, t, n1 = _diff_t(Y[sel], mm[:, None], lags)
            se = abs(e[0] / t[0]) if t[0] else float("nan")
            return {"effect": float(e[0]), "t": float(t[0]), "se": se, "n_in": int(n1[0]), "n": int(sel.sum()),
                    "mean_in": float(Y[sel][mm].mean()), "mean_out": float(Y[sel][~mm].mean())}
        full = est(np.ones(len(Y), bool))
        rec["full"] = full
        rec["pre"] = est(Q.index.year < split)
        rec["post"] = est(Q.index.year >= split)
        rec["months_in"] = full["n_in"]
        rec["from"], rec["to"] = _ym(Q.index[0]), _ym(Q.index[-1])
        if full["t"] is None:
            ps.append(None)
            rec["verdict"] = "no evidence"
            rec["why"] = "too few months inside or outside the condition"
        else:
            ps.append(float(2 * stats.norm.sf(abs(full["t"]))))
            rec["p"] = ps[-1]
            rec["p_bayes_sign"] = bayes_sign(full["effect"], full["se"], _tau(P, o), rec["direction"])
        out.append(rec)
    valid = [i for i, p in enumerate(ps) if p is not None]
    qs = labs.bh([ps[i] for i in valid]) if valid else []
    for i, qv in zip(valid, qs):
        r = out[i]
        r["q"] = float(qv)
        same = np.sign(r["full"]["effect"]) == r["direction"]
        r["verdict"] = ("supported" if same else "reversed") if qv <= fdr else "no evidence"
        halves = [h for h in (r["pre"], r["post"]) if h.get("effect") is not None]
        r["halves_agree"] = bool(len(halves) == 2 and all(np.sign(h["effect"]) == np.sign(r["full"]["effect"]) for h in halves))
        if r["verdict"] == "supported" and not r["halves_agree"]:
            r["verdict"] = "one era only"          # significant on the full record but the two halves disagree in sign: not a durable rule
    return out


def load_rules(paths) -> list[dict]:
    out = []
    for p in paths or ():
        try:
            d = json.loads(Path(p).read_text())
        except (OSError, ValueError):
            continue
        d = d.get("rules", []) if isinstance(d, dict) else d
        for r in d:
            if isinstance(r, dict):
                out.append({**r, "source": str(p)})
    return out


# ---------------------------------------------------------------- 4. abduction
def _obs_mask(P: pd.DataFrame, observed: dict) -> tuple[np.ndarray, np.ndarray]:
    known = np.ones(len(P), bool)
    hit = np.ones(len(P), bool)
    for k, v in observed.items():
        y = P[k].to_numpy()
        known &= np.isfinite(y)
        with np.errstate(invalid="ignore"):
            if isinstance(v, (list, tuple)):
                op, val = v[0], float(v[1])
                hit &= {"<": y < val, "<=": y <= val, ">": y > val, ">=": y >= val}[op]
            else:
                hit &= y == float(v)
    return known, hit & known


def abduce(P: pd.DataFrame, observed: dict, concepts: tuple | None = None, top: int = 10, min_n: int = 24, feats: list[str] | None = None) -> dict:
    """Which conditions best explain an observed outcome (e.g. {"crash12": 1}, {"bond_hedge12": 0}, {"ret12": ["<", -0.1]}).

    Hypotheses are single conditions at full-sample quintile edges (this is retrospective explanation, not
    forecasting) and, if given, membership of each invented concept (concepts = (labels Series, {label: name})). For
    each: P(obs|h) and P(obs|not h) with Laplace smoothing, their likelihood ratio, the prior frequency of h and its
    posterior given the observation. Ranked by how much probability the observation moves onto h (posterior minus
    prior, equal to the prior times the lift less one); ranking by likelihood ratio times prior frequency favours
    conditions that are true most of the time, so that product is reported but does not set the order."""
    feats = [f for f in (feats or FEATURES) if f in P]
    known, O = _obs_mask(P, observed)
    Pk = P[known]
    Ok = O[known]
    hyps, cols = [], []
    for f in feats:
        x = Pk[f].to_numpy()
        v = np.isfinite(x)
        if v.sum() < 2 * min_n:
            continue
        ed = np.quantile(x[v], [q / 100 for q in QUINTILES])
        for q, e in zip(QUINTILES, ed):
            for op in ("<=", ">"):
                with np.errstate(invalid="ignore"):
                    h = (x <= e) if op == "<=" else (x > e)
                hyps.append({"kind": "condition", "if": [[f, op, float(e)]], "text": _text([[f, op, float(e), q]], cutoff=None)})
                cols.append((h & v, v))
    if concepts is not None:
        lab, nm = concepts
        L = lab.reindex(Pk.index)
        v = L.notna().to_numpy()
        for k, name in nm.items():
            hyps.append({"kind": "concept", "concept": int(k), "text": f"the market is in the regime '{name}'"})
            cols.append(((L == k).to_numpy() & v, v))
    if not cols:
        return {"observed": observed, "months": int(known.sum()), "explanations": []}
    H = np.column_stack([c[0] for c in cols])
    V = np.column_stack([c[1] for c in cols])
    n = V.sum(0)
    nh = H.sum(0)
    nO = (V & Ok[:, None]).sum(0)
    nOh = (H & Ok[:, None]).sum(0)
    poh = (nOh + 1) / (nh + 2)
    ponh = (nO - nOh + 1) / (n - nh + 2)
    lr = poh / ponh
    prior = nh / np.maximum(n, 1)
    post = poh * prior / (poh * prior + ponh * (1 - prior))
    gain = post - prior
    ok = (nh >= min_n) & (n - nh >= min_n) & (lr > 1)
    order = [i for i in np.argsort(-np.where(ok, gain, -np.inf)) if ok[i]][:top]
    ex = []
    for i in order:
        ex.append({**hyps[i], "lr": float(lr[i]), "p_obs_given_h": float(poh[i]), "p_obs_given_not": float(ponh[i]), "prior": float(prior[i]),
                   "posterior": float(post[i]), "support": float(gain[i]), "lr_x_prior": float(lr[i] * prior[i]), "months": int(nh[i]),
                   "months_obs": int(nOh[i])})
    return {"observed": observed, "months": int(known.sum()), "months_observed": int(Ok.sum()), "base_rate": float(Ok.mean()) if len(Ok) else None,
            "hypotheses": len(hyps), "explanations": ex,
            "method": "Laplace-smoothed likelihood ratios over single conditions at full-sample quintile edges and invented regimes; ranked by posterior minus prior."}


def _fires(row: pd.Series, conds) -> bool | None:
    vals = []
    for f, op, v in conds:
        x = row.get(f, np.nan)
        if not np.isfinite(x):
            return None
        vals.append({"<": x < v, "<=": x <= v, ">": x > v, ">=": x >= v, "==": x == v}[op])
    return bool(all(vals))


def abduce_now(P: pd.DataFrame, row: pd.Series, rules_in: list[dict]) -> dict:
    """Which rules fire for today's feature row and what they jointly imply. The joint is a naive-Bayes style
    combination: for a yes/no outcome, the base rate's log odds plus each firing rule's log-odds shift; for a
    continuous one, the base mean plus each firing rule's shift. It assumes the rules are independent given the outcome,
    which overlapping market conditions are not, so it overstates agreement; it is a summary, not a forecast."""
    fires, silent, unknown = [], 0, []
    for r in rules_in:
        conds = [(c[0], c[1], float(c[2])) for c in r["if"]]
        o = r["outcome"]
        if any(c[0] not in P for c in conds) or o not in P:
            continue
        f = _fires(row, conds)
        if f is None:
            unknown.append(r.get("id"))
            continue
        if not f:
            silent += 1
            continue
        Q = P[P[[c[0] for c in conds] + [o]].notna().all(axis=1)]
        m = _cond_mask({c: Q[c].to_numpy() for c in set([c[0] for c in conds])}, conds)
        y = Q[o].to_numpy()
        fires.append({"id": r.get("id"), "text": r.get("text") or r.get("principle") or _text(conds), "outcome": o,
                      "survives": r.get("survives", r.get("verdict") == "supported"), "base": float(y.mean()), "in": float(y[m].mean()),
                      "months": int(m.sum())})
    def combine(fs_all):
        joint = {}
        for o in sorted(set(f["outcome"] for f in fs_all)):
            fs = [f for f in fs_all if f["outcome"] == o]
            base = fs[0]["base"]
            if o in BINARY:
                lg = lambda p: math.log(min(max(p, 1e-4), 1 - 1e-4) / (1 - min(max(p, 1e-4), 1 - 1e-4)))
                z = lg(base) + sum(lg(f["in"]) - lg(base) for f in fs)
                comb = 1 / (1 + math.exp(-z))
            else:
                comb = base + sum(f["in"] - base for f in fs)
            joint[o] = {"base": base, "combined": comb, "rules": [f["id"] for f in fs],
                        "method": "naive Bayes (assumes the rules independent given the outcome; overstates agreement)"}
        return joint
    return {"date": _ym(row.name) if row.name is not None else None, "fires": fires, "silent": silent, "unknown": unknown,
            "joint": combine([f for f in fires if f["survives"]]), "joint_all": combine(fires),
            "note": "joint uses only rules that survived out of sample or were supported; joint_all uses every firing rule"}


# ---------------------------------------------------------------- 5. concept invention
def _name(zmean: np.ndarray, feats: list[str], k: int = 3, min_z: float = 0.5) -> tuple[str, list]:
    order = np.argsort(-np.abs(zmean))
    used, words, why = set(), [], []
    for j in order:
        f = feats[j]
        fam = FAMILY.get(f, f)
        if fam in used:
            continue
        if len(words) >= 2 and abs(zmean[j]) < min_z:
            break
        used.add(fam)
        w = WORDS.get(f, (f"high {f}", f"low {f}"))[0 if zmean[j] > 0 else 1]
        words.append(w)
        why.append([f, float(zmean[j])])
        if len(words) >= k:
            break
    return ", ".join(words), why


def _dm_ls(d: np.ndarray, lags: int) -> dict:
    from . import ml
    se = math.sqrt(ml.nw_var(d, lags))
    t = float(d.mean() / se) if se > 0 else 0.0
    return {"mean_gain": float(d.mean()), "t": t, "p_one_sided": float(stats.norm.sf(t))}


def invent(P: pd.DataFrame, cutoff: str = CUTOFF, ks=range(2, 9), feats: list[str] | None = None, seed: int = SEED, return_labels: bool = False,
           predicates: bool = True):
    """Regimes invented from data to the cutoff: features standardized on that period, a Gaussian mixture (full
    covariance) with k chosen by BIC, each cluster named by its two or three most distinctive features. Later months are
    assigned by the fitted model only. Out of sample, does membership forecast ret12 (MSE skill against the cutoff's
    unconditional mean, Diebold-Mariano t) and crash12 (log score against the base rate, Newey-West t)? Also derived
    predicates (products and differences of standardized feature pairs) screened before the cutoff and tested after."""
    from sklearn.mixture import GaussianMixture
    from sklearn.metrics import adjusted_rand_score  # noqa: F401  (kept importable for callers checking recovery)
    from . import ml
    feats = [f for f in (feats or FEATURES) if f in P]
    Q = _frame(P, feats)
    cut = pd.Timestamp(cutoff) + pd.offsets.MonthEnd(0)
    pre = Q.index <= cut
    mu, sd = Q.loc[pre, feats].mean(), Q.loc[pre, feats].std(ddof=0).replace(0, 1.0)
    Z = ((Q[feats] - mu) / sd).to_numpy()
    Zp = Z[pre]
    bic, fits = {}, {}
    for k in ks:
        if k >= len(Zp) // 10:
            break
        g = GaussianMixture(k, covariance_type="full", reg_covar=1e-3, n_init=2, random_state=seed, max_iter=300).fit(Zp)
        bic[k], fits[k] = float(g.bic(Zp)), g
    kbest = min(bic, key=bic.get)
    g = fits[kbest]
    raw = g.predict(Z)
    sizes = np.bincount(raw[pre], minlength=kbest)
    remap = {int(c): i for i, c in enumerate(np.argsort(-sizes, kind="stable"))}
    lab = np.array([remap[int(c)] for c in raw])
    labels = pd.Series(lab, index=Q.index)
    clusters, names = [], {}
    for c in range(kbest):
        zm = Zp[lab[pre] == c].mean(0) if (lab[pre] == c).any() else np.zeros(len(feats))
        nm, why = _name(zm, feats)
        base_nm, j = nm, 2
        while nm in names.values():
            nm = f"{base_nm} ({j})"
            j += 1
        names[c] = nm
        clusters.append({"id": c, "name": nm, "distinctive": why, "months_pre": int((lab[pre] == c).sum()), "months_post": int((lab[~pre] == c).sum())})
    res = {"cutoff": _ym(cut), "k": kbest, "bic": bic, "features": feats, "clusters": clusters, "names": names}
    # out of sample
    oos = {}
    idx = Q.index
    for o in ("ret12", "crash12"):
        if o not in Q:
            continue
        y = Q[o].to_numpy()
        tr = np.isfinite(y) & _purged(idx, cut + pd.Timedelta(days=1), HORIZON[o])
        te = np.isfinite(y) & ~pre
        if tr.sum() < 60 or te.sum() < 60:
            continue
        if o in BINARY:
            base = (y[tr].sum() + 1) / (tr.sum() + 2)
            pc = np.array([(y[tr & (lab == c)].sum() + 1) / ((tr & (lab == c)).sum() + 2) for c in range(kbest)])
            p = pc[lab[te]]
            yt = y[te]
            ls_c = yt * np.log(p) + (1 - yt) * np.log(1 - p)
            ls_b = yt * math.log(base) + (1 - yt) * math.log(1 - base)
            bs_c, bs_b = np.mean((p - yt) ** 2), np.mean((base - yt) ** 2)
            oos[o] = {"log_score_gain": _dm_ls(ls_c - ls_b, NW_LAGS[o]), "brier_skill": float(1 - bs_c / bs_b), "base_rate_pre": float(base),
                      "rate_by_cluster_pre": pc.tolist(), "months": int(te.sum())}
        else:
            m0 = y[tr].mean()
            mc = np.array([y[tr & (lab == c)].mean() if (tr & (lab == c)).any() else m0 for c in range(kbest)])
            f = mc[lab[te]]
            e, eb = y[te] - f, y[te] - m0
            oos[o] = {"mse_skill": float(1 - np.mean(e ** 2) / np.mean(eb ** 2)), "dm": ml.diebold_mariano(e, eb, NW_LAGS[o]),
                      "mean_by_cluster_pre": mc.tolist(), "mean_pre": float(m0), "months": int(te.sum())}
        oos[o]["beats_unconditional"] = bool((oos[o].get("dm") or oos[o].get("log_score_gain"))["t"] > 1.645)
    res["oos"] = oos
    for c in clusters:
        m = labels.reindex(P.index) == c["id"]
        c["ret12_all"] = float(P.loc[m, "ret12"].mean()) if "ret12" in P and m.any() else None
        c["crash12_all"] = float(P.loc[m, "crash12"].mean()) if "crash12" in P and m.any() else None
    res["latest"] = {"date": _ym(Q.index[-1]), "cluster": int(lab[-1]), "name": names[int(lab[-1])]}
    res["k_at_bound"] = bool(kbest == max(bic))

    def assign(row) -> int:
        z = ((pd.Series({f: float(row[f]) for f in feats}) - mu) / sd).to_numpy()[None, :]
        return remap[int(g.predict(z)[0])]
    if predicates:
        res["predicates"] = invent_predicates(P, cutoff, feats=feats)
    return (res, labels, assign) if return_labels else res


def invent_predicates(P: pd.DataFrame, cutoff: str = CUTOFF, outcomes=("ret12", "crash12"), feats: list[str] | None = None, fdr: float = FDR,
                      min_n: int = MIN_N, top: int = 10) -> dict:
    """Derived predicates: for each pair of standardized features (standardized on data to the cutoff) their product
    and difference; conditions at the derived feature's top and bottom quintile before the cutoff. Screened on the
    discovery period with Newey-West t and BH across all of them; the top `top` per outcome tested after the cutoff with
    BH on one-sided p. A survivor passes both. The test does not ask whether a derived predicate beats its parents."""
    feats = [f for f in (feats or FEATURES) if f in P]
    Q = _frame(P, feats)
    cut = pd.Timestamp(cutoff) + pd.offsets.MonthEnd(0)
    pre = Q.index <= cut
    mu, sd = Q.loc[pre, feats].mean(), Q.loc[pre, feats].std(ddof=0).replace(0, 1.0)
    Z = ((Q[feats] - mu) / sd).to_numpy()
    names, cols = [], []
    for i, j in combinations(range(len(feats)), 2):
        cols.append(Z[:, i] * Z[:, j])
        names.append((feats[i], "x", feats[j]))
        cols.append(Z[:, i] - Z[:, j])
        names.append((feats[i], "-", feats[j]))
    W = np.column_stack(cols)
    lo, hi = np.quantile(W[pre], 0.2, axis=0), np.quantile(W[pre], 0.8, axis=0)
    cands = [(k, "<=", lo[k]) for k in range(W.shape[1])] + [(k, ">", hi[k]) for k in range(W.shape[1])]
    M = np.column_stack([W[:, k] <= v if op == "<=" else W[:, k] > v for k, op, v in cands])
    allp, keep = [], []
    for o in outcomes:
        y = Q[o].to_numpy()
        d = np.isfinite(y) & _purged(Q.index, cut + pd.Timedelta(days=1), HORIZON[o])
        eff, t, n1 = _diff_t(y[d], M[d], NW_LAGS[o])
        ok = (n1 >= min_n) & (d.sum() - n1 >= min_n)
        p = np.where(ok, 2 * stats.norm.sf(np.abs(t)), np.nan)
        allp.append(p[ok])
        order = [i for i in np.argsort(-np.where(ok, np.abs(t), -1)) if ok[i]][:top]
        keep.append((o, d, y, eff, t, p, order))
    flat = np.concatenate(allp) if allp else np.array([])
    qs = np.array(labs.bh(flat.tolist())) if len(flat) else np.array([])
    sp, sq = np.sort(flat), np.sort(qs)
    tested = []
    for o, d, y, eff, t, p, order in keep:
        te = np.isfinite(y) & ~pre
        for i in order:
            k, op, v = cands[i]
            a, how, b = names[k]
            mt = M[te, i]
            rec = {"outcome": o, "predicate": f"z({a}) {'times' if how == 'x' else 'minus'} z({b})", "op": op, "edge": float(v), "direction": int(np.sign(eff[i])),
                   "disc": {"effect": float(eff[i]), "t": float(t[i]), "p": float(p[i]), "q": float(sq[min(int(np.searchsorted(sp, p[i])), len(sq) - 1)])}}
            rec["oos"] = _oos(y[te], mt, NW_LAGS[o], rec["direction"])
            tested.append(rec)
    qo = labs.bh([r["oos"]["p_one"] for r in tested]) if tested else []
    for r, q in zip(tested, qo):
        r["oos"]["q"] = float(q)
        r["survives"] = bool(r["disc"]["q"] <= fdr and r["oos"]["testable"] and r["oos"]["kept_sign"] and q <= fdr)
    return {"candidates": int(len(flat)), "screened": int((qs <= fdr).sum()) if len(qs) else 0, "tested": tested,
            "survivors": [r["predicate"] + f" {r['op']} {r['edge']:.3g} -> {r['outcome']}" for r in tested if r["survives"]]}


# ---------------------------------------------------------------- 6. build and summary
def _compact_deduction(D: dict, sample: int = 25) -> dict:
    names = D.get("names") or {}
    F = D["facts"]
    der = [i for i, t in enumerate(F) if t[5] != "given"]
    causal = sorted([i for i in der if F[i][1] in CAUSAL and F[i][4] >= 2], key=lambda i: (-F[i][3], F[i][0]))
    nm = lambda x: names.get(x, x)
    ex = []
    for i in causal[:sample]:
        t = F[i]
        ch = _leaves(prove(t[:3], D))
        ex.append({"fact": [nm(t[0]), t[1], nm(t[2])], "conf": t[3], "rule": t[5], "chain": [[nm(a), p, nm(b)] for a, p, b in ch]})
    con = []
    for c in D["contradictions"][:20]:
        if c["kind"] == "sign":
            con.append({"kind": "sign", "pair": [nm(x) for x in c["pair"]], "conf": c["conf"],
                        "plus": [[nm(a), p, nm(b)] for a, p, b in _leaves(c["plus"])], "minus": [[nm(a), p, nm(b)] for a, p, b in _leaves(c["minus"])]})
        else:
            con.append({"kind": c["kind"], "node": nm(c.get("node") or c.get("pair", [""])[0])})
    return {"given": D["n_given"], "derived": D["n_derived"], "counts": D["counts"], "steps": D["steps"], "fixpoint": D["fixpoint"],
            "max_len": D["max_len"], "floor": D["floor"], "contradictions_n": len(D["contradictions"]),
            "sign_contradictions": sum(1 for c in D["contradictions"] if c["kind"] == "sign"), "contradictions": con,
            "causal_derived": sum(1 for i in der if F[i][1] in CAUSAL), "examples": ex}


def build(S: pd.DataFrame, gh: dict | None = None, G: dict | None = None, rules_paths=(), facts: dict | None = None, do_rolling: bool = True,
          quick: bool = False) -> dict:
    """Everything above, compact and JSON-safe, with today's row and what fires. quick (tests) skips the bootstrap
    check and tries fewer mixture sizes."""
    t0 = time.time()
    timing = {}
    P = panel(S, gh)
    timing["panel"] = time.time() - t0
    disc = discover(P, boot=not quick)
    timing["discover"] = time.time() - t0
    roll = rolling(P) if do_rolling else {}
    timing["rolling"] = time.time() - t0
    supplied = [{**r, "source": "built-in example"} for r in EXAMPLE_RULES] + load_rules(rules_paths)
    tr = test_rules(P, supplied)
    timing["rules"] = time.time() - t0
    inv, labels, assign = invent(P, return_labels=True, ks=range(2, 5) if quick else range(2, 9))
    timing["invent"] = time.time() - t0
    concepts = (labels, inv["names"])
    abd = {"crash12=1": abduce(P, {"crash12": 1}, concepts), "bond_hedge12=0": abduce(P, {"bond_hedge12": 0}, concepts),
           "ret12<-0.10": abduce(P, {"ret12": ["<", -0.10]}, concepts)}
    for v in abd.values():
        v["explanations"] = v["explanations"][:5]
    timing["abduce"] = time.time() - t0
    if G is None:
        p = Path(__file__).resolve().parent / "assets" / "mind.json"
        G = json.loads(p.read_text()) if p.exists() else None
    ded = _compact_deduction(deduce(G)) if G else None
    timing["deduce"] = time.time() - t0
    dp = decision_proof(facts)
    row, notes = today_row(P)
    for r in disc["rules"]:
        r["p_bayes_sign"] = bayes_sign(r["oos"]["effect"], abs(r["oos"]["effect"] / r["oos"]["t"]) if r.get("oos", {}).get("t") else float("nan"),
                                       _tau(P, r["outcome"]), r["direction"]) if r.get("oos", {}).get("effect") is not None else None
    now = abduce_now(P, row, disc["rules"] + [r for r in tr if r.get("verdict") != "untestable"])
    lab_now = assign(row)
    out = {
        "schema": 1, "panel": {"from": _ym(P.index[0]), "to": _ym(P.index[-1]), "months": len(P), "features": FEATURES, "outcomes": OUTCOMES,
                               "complete_from": _ym(_frame(P, FEATURES).index[0]), "complete_to": _ym(_frame(P, FEATURES).index[-1])},
        "discover": disc, "rolling": roll, "rules": tr, "invent": inv, "abduce": abd, "deduce": ded, "decision": dp,
        "today": {"row": {f: float(row[f]) for f in FEATURES}, "notes": notes, "regime": inv["names"].get(int(lab_now)), "regime_id": int(lab_now),
                  **now},
    }
    out["runtime_s"] = time.time() - t0
    out["timing"] = timing
    out = _js(out)
    out["findings"] = summary(out)
    return out


def _pct(x, nd: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:+.{nd}f}"


def _unit(outcome: str) -> str:
    return "percentage points of probability" if outcome in BINARY else "percentage points"


def summary(o: dict) -> list[str]:
    """Plain-English findings, third person, saying what failed."""
    out = []
    d = o.get("discover") or {}
    if d:
        surv = [r for r in d["rules"] if r["survives"]]
        kept = [r for r in d["rules"] if r.get("oos", {}).get("testable")]
        out.append(f"Induction: the reasoner tried {d['n_candidates']:,} conditions (single features and pairs at quintile edges) on the discovery "
                   f"period before {d['start_test'][:4]}; {d['bh_significant']:,} passed Benjamini-Hochberg at a {d['fdr']:.0%} false discovery rate, "
                   f"a count inflated by persistent conditions whose Newey-West errors are too small. Of the {d['tested']} strongest it carried into the "
                   f"untouched period from {d['start_test'][:4]}, {d['tested'] - len(kept)} could not be tested there (fewer than {d['min_oos']} months "
                   f"inside or outside the condition), {d['kept_sign']} of the {len(kept)} testable kept their sign and {len(surv)} survived.")
        seen = set()
        for r in surv:
            key = tuple(map(tuple, r["if"]))
            if key in seen:
                continue
            seen.add(key)
            oo = r["oos"]
            also = [x["outcome"] for x in surv if tuple(map(tuple, x["if"])) == key and x is not r]
            out.append(f"Survivor: {r['text']}. Out of sample the gap is {_pct(oo['effect'])} {_unit(r['outcome'])} (t {oo['t']:.1f}, {oo['n_in']} of "
                       f"{oo['n']} months inside), against {_pct(r['disc']['effect'])} before; the skeptical posterior that the sign is right is "
                       f"{(r.get('p_bayes_sign') or 0):.0%}" + (f". The same condition also survived for {', '.join(also)}" if also else "")
                       + (f". It rests on only {oo['n_in']} months, so it is fragile" if oo["n_in"] < 2 * MIN_N else "") + ".")
            if len(seen) >= 3:
                break
        failed = [r for r in d["rules"] if not r["survives"] and r["disc"]["q"] <= d["fdr"] and r.get("oos", {}).get("testable")]
        if failed:
            r = failed[0]
            oo = r["oos"]
            out.append(f"What failed: the strongest testable discovery that did not survive was '{r['text']}' (discovery t {r['disc']['t']:.1f}); "
                       f"after {d['start_test'][:4]} its gap was {_pct(oo['effect'])} {_unit(r['outcome'])} (t {oo['t']:.1f}).")
    ro = o.get("rolling") or {}
    if ro:
        parts = [f"{k} {v['share_held']:.0%} of {v['testable']} testable decades" for k, v in ro.items() if v.get("share_held") is not None]
        rev = [k for k, v in ro.items() if (v.get("share_reversed_significant") or 0) > 0]
        out.append("Rediscovered every ten years on the data to date and tested on the next ten, the top rule kept its sign for " + "; ".join(parts)
                   + (f". It reversed significantly at least once for {', '.join(rev)}" if rev else "")
                   + ". Decades in which the top rule's condition barely occurred are left out rather than counted as failures"
                   + (f"; for {', '.join(k for k, v in ro.items() if not v.get('testable'))} the top rule was never testable, because each decade's best "
                      f"rule was a rare pair of conditions that hardly recurred in the next ten years" if any(not v.get("testable") for v in ro.values()) else "")
                   + ".")
    tr = o.get("rules") or []
    if tr:
        sup = [r for r in tr if r.get("verdict") == "supported"]
        rev = [r for r in tr if r.get("verdict") == "reversed"]
        ne = [r for r in tr if r.get("verdict") == "no evidence"]
        split = [r for r in tr if r.get("verdict") == "one era only"]
        out.append(f"Supplied rules: {len(sup)} of {len(tr)} supported in both halves of the record, {len(split)} significant in one era only, {len(rev)} reversed, "
                   f"{len(ne)} with no evidence after Benjamini-Hochberg across them"
                   + (f" (supported: {'; '.join((r.get('principle') or r['person'] or r['id']).rstrip('.') for r in sup)})" if sup else "")
                   + (f"; reversed: {'; '.join((r.get('principle') or r['person'] or r['id']).rstrip('.') for r in rev)}" if rev else "")
                   + (f". One era only, so not a durable rule: {', '.join(r['person'] or r['id'] for r in split)}" if split else "") + ".")
    inv = o.get("invent") or {}
    if inv:
        oo = inv.get("oos", {})
        r12, c12 = oo.get("ret12"), oo.get("crash12")
        bits = []
        if r12:
            bits.append(f"for the 12-month return an MSE skill of {_pct(r12['mse_skill'])}% against the {inv['cutoff'][:4]} mean (Diebold-Mariano t {r12['dm']['t']:.1f})")
        if c12:
            bits.append(f"for crashes a log-score gain of {c12['log_score_gain']['mean_gain']:+.3f} nats a month (t {c12['log_score_gain']['t']:.1f})")
        beat = [k for k, v in oo.items() if v.get("beats_unconditional")]
        out.append(f"Invented regimes: a Gaussian mixture on data to {inv['cutoff']} chose {inv['k']} regimes by BIC"
                   + (" (the largest number tried, so BIC wanted more, as it does with persistent monthly data)" if inv.get("k_at_bound") else "")
                   + ": " + "; ".join(f"'{c['name']}'" for c in inv["clusters"]) + ". Out of sample, membership gave " + " and ".join(bits)
                   + (", so the invented regimes do not forecast better than the unconditional mean" if not beat else f"; it beat the mean for {', '.join(beat)}") + ".")
        pr = inv.get("predicates")
        if pr:
            out.append(f"Invented predicates: {pr['candidates']:,} conditions on products and differences of feature pairs were screened; {pr['screened']} passed "
                       f"the discovery screen and {len(pr['survivors'])} survived out of sample" + (f" ({pr['survivors'][0]})" if pr["survivors"] else "") + ".")
    ab = (o.get("abduce") or {}).get("crash12=1")
    if ab and ab.get("explanations"):
        e = ab["explanations"][0]
        out.append(f"Abduction: the best single explanation of a 15% fall within 12 months (base rate {ab['base_rate']:.0%} of {ab['months']:,} months) is "
                   f"{e['text']}: falls followed it {e['p_obs_given_h']:.0%} of the time against {e['p_obs_given_not']:.0%} otherwise "
                   f"(likelihood ratio {e['lr']:.1f}, {e['months']} months). This is retrospective, not a forecast.")
    dd = o.get("deduce")
    if dd:
        out.append(f"Deduction: from {dd['given']:,} typed facts in the mind the rules derived {dd['derived']:,} more in {dd['steps']} rounds "
                   f"({'fixpoint reached' if dd['fixpoint'] else 'step cap reached'}), {dd['causal_derived']:,} of them causal chains of up to {dd['max_len']} links; "
                   f"{dd['sign_contradictions']} ordered pairs were derived with both signs above a confidence of {dd['floor']:.1f}"
                   + (f", e.g. {dd['contradictions'][0]['pair'][0]} on {dd['contradictions'][0]['pair'][1]}" if dd["contradictions"] and dd["contradictions"][0]["kind"] == "sign" else "")
                   + f", and {dd['contradictions_n'] - dd['sign_contradictions']} other contradictions (cycles, a kind opposing its class).")
    dp = o.get("decision")
    if dp:
        c = dp["conclusions"]
        cf = {r["premise"]: r for r in dp["counterfactuals"] if "flips_up" in r}
        flips = []
        if cf.get("corr36", {}).get("flips_down"):
            flips.append(f"the bond hedge turns on if the 36-month correlation falls to {cf['corr36']['flips_down']['at']:.2f}")
        if cf.get("gate", {}).get("flips_up"):
            flips.append(f"the exposure rises to {cf['gate']['flips_up']['exposure']:.2f}x if the evidence gate reaches {cf['gate']['flips_up']['at']:.0%}")
        if cf.get("es_1x", {}).get("flips_up"):
            flips.append(f"the risk budget cuts it to {cf['es_1x']['flips_up']['exposure']:.2f}x if expected shortfall at 1x passes {cf['es_1x']['flips_up']['at']:.1%}")
        out.append(f"The decision, derived by rule: {c['exposure']:.2f}x stocks, bond hedge {c['bond_hedge']} (state {c['state']}), {c['hedge_name'].lower()}."
                   + (" The nearest flips: " + "; ".join(flips) + "." if flips else ""))
    t = o.get("today") or {}
    if t:
        rule_s = lambda n: f"{n} rule" + ("" if n == 1 else "s")
        bits = [f"{OUTCOME_NAMES.get(k, k)} {v['combined'] * 100:.1f}% against a base of {v['base'] * 100:.1f}% ({rule_s(len(v['rules']))})"
                for k, v in (t.get("joint") or {}).items()]
        nsurv = sum(1 for f in t.get("fires", []) if f.get("survives"))
        out.append(f"Today ({t.get('date')}, in the regime '{t.get('regime')}'), {rule_s(len(t.get('fires', [])))} fire, {nsurv} of them survivors or supported"
                   + ("; the survivors' naive-Bayes combination, which treats overlapping rules as independent and so overstates agreement, gives " + "; ".join(bits)
                      if bits else "; no surviving rule fires, so the reasoner adds nothing to the decision today")
                   + (f". Features carried from where their series stop: {', '.join(sorted((t.get('notes') or {}).get('carried', {})))}" if (t.get("notes") or {}).get("carried") else "")
                   + ".")
    return [x.replace("\u2014", ", ") for x in out]
