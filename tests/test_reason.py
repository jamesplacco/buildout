"""The reasoning module: deduction, induction, abduction and invented concepts, on synthetic data (fast, no network)."""
from __future__ import annotations

import json
import math
import os
import pickle

import numpy as np
import pandas as pd
import pytest

from buildout import reason as R

SCRATCH = "/tmp/claude-0/-home-claude/1e15d221-91bb-543f-92a6-54e21d8a6b8b/scratchpad"
BANNED = ("\u2014", "inter" + "section", "load" + "-bearing")


def synth_S(n: int = 1800, seed: int = 0, start: str = "1871-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="MS")
    cpi = 10 * np.exp(np.cumsum(0.002 + 0.004 * rng.standard_normal(n)))
    y10 = np.clip(4 + np.cumsum(0.08 * rng.standard_normal(n)), 0.5, 15)
    px = 5 * np.exp(np.cumsum(0.005 + 0.04 * rng.standard_normal(n)))
    div = px * 0.04 * (1 + 0.05 * rng.standard_normal(n))
    eps = px / 15 * np.exp(0.1 * rng.standard_normal(n))
    return pd.DataFrame({"px": px, "div": div, "eps": eps, "cpi": cpi, "y10": y10}, index=idx)


def ar_features(n, k, seed, rho=0.9):
    rng = np.random.default_rng(seed)
    X = np.zeros((n, k))
    e = rng.standard_normal((n, k))
    for t in range(1, n):
        X[t] = rho * X[t - 1] + e[t]
    return X


def synth_panel(seed: int, planted: float = 0.0, n: int = 1200, k: int = 6) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 100)
    idx = pd.date_range("1901-01-01", periods=n, freq="MS")
    X = ar_features(n, k, seed)
    P = pd.DataFrame(X, index=idx, columns=[f"f{i}" for i in range(k)])
    pre = idx < "1961-01-01"
    edge = np.quantile(P.loc[pre, "f0"], 0.8)
    P["ret1"] = 0.04 * rng.standard_normal(n) + planted * 0.04 * (P["f0"] > edge)
    return P


def _has_banned(o) -> list:
    s = json.dumps(o).lower()
    return [b for b in BANNED if b in s]


# ---------------------------------------------------------------- panel
def test_panel_no_lookahead():
    S = synth_S(700, seed=3)
    P1 = R.panel(S)
    k = 450
    S2 = S.copy()
    rng = np.random.default_rng(9)
    m = len(S) - k
    for c in ("px", "div", "eps", "cpi"):
        S2.iloc[k:, S2.columns.get_loc(c)] *= np.exp(0.2 * rng.standard_normal(m))
    S2.iloc[k:, S2.columns.get_loc("y10")] += rng.standard_normal(m)
    P2 = R.panel(S2)
    a, b = P1[R.FEATURES].iloc[:k + 1], P2[R.FEATURES].iloc[:k + 1]
    assert a.notna().any().all(), "every feature should be defined somewhere before the cut"
    pd.testing.assert_frame_equal(a, b)
    # the outcomes do see the future, so they must change
    assert not np.allclose(P1["ret12"].iloc[k - 6], P2["ret12"].iloc[k - 6])
    assert set(R.OUTCOMES) <= set(P1.columns)
    assert set(P1["crash12"].dropna().unique()) <= {0.0, 1.0}
    assert (P1["maxdd12"].dropna() <= 0).all()


# ---------------------------------------------------------------- induction
def test_planted_rule_discovered_and_survives():
    P = synth_panel(1, planted=0.6)
    d = R.discover(P, outcomes=["ret1"], feats=[f"f{i}" for i in range(6)], boot=False)
    top = d["rules"][0]
    assert any(c[0] == "f0" and c[1] == ">" for c in top["if"])
    assert top["survives"] and top["oos"]["kept_sign"] and top["oos"]["t"] > 3
    assert d["survivors"]
    assert not _has_banned(R._js(d))


def test_null_data_few_survivors():
    feats = [f"f{i}" for i in range(6)]
    any_disc, surv = 0, 0
    for s in range(5):
        d = R.discover(synth_panel(10 + s, planted=0.0), outcomes=["ret1"], feats=feats, boot=False)
        any_disc += d["bh_significant"] > 0
        surv += len(d["survivors"])
    assert any_disc <= 2          # BH at 10% under the global null: about one seed in ten has any rejection
    assert surv <= 1


def test_test_rules_and_bayes():
    P = synth_panel(2, planted=0.6)
    rules = [{"id": "a", "person": "X", "principle": "f0 high, returns up", "if": [["f0", ">", float(np.quantile(P["f0"], 0.8))]],
              "then": {"outcome": "ret1", "direction": "up"}},
             {"id": "b", "person": "Y", "principle": "f0 high, returns down", "if": [["f0", ">", float(np.quantile(P["f0"], 0.8))]],
              "then": {"outcome": "ret1", "direction": "down"}},
             {"id": "c", "person": "Z", "principle": "noise", "if": [["f3", ">", 0.0]], "then": {"outcome": "ret1", "direction": "up"}},
             {"id": "d", "person": "W", "principle": "unknown", "if": [["nope", ">", 0.0]], "then": {"outcome": "ret1", "direction": "up"}}]
    out = {r["id"]: r for r in R.test_rules(P, rules)}
    assert out["a"]["verdict"] == "supported" and out["a"]["p_bayes_sign"] > 0.99
    assert out["b"]["verdict"] == "reversed" and out["b"]["p_bayes_sign"] < 0.01
    assert out["d"]["verdict"] == "untestable"
    assert out["a"]["pre"]["n"] + out["a"]["post"]["n"] == out["a"]["full"]["n"]
    assert out["a"]["halves_agree"]
    assert abs(R.bayes_sign(0.0, 1.0, 1.0, 1) - 0.5) < 1e-9


# ---------------------------------------------------------------- deduction
def _small_kb():
    F = [("a", "is_a", "b", 0.9), ("b", "is_a", "c", 0.9), ("c", "is_a", "d", 0.9),
         ("x", "causes+", "y", 0.8), ("y", "causes-", "z", 0.8), ("x", "causes-", "y2", 0.8), ("y2", "causes-", "z2", 0.8),
         ("c1", "causes+", "c2", 0.9), ("c2", "causes+", "c3", 0.9), ("c3", "causes+", "c4", 0.9), ("c4", "causes+", "c5", 0.9),
         ("p", "causes+", "q", 0.9), ("q", "causes+", "r", 0.9), ("p", "causes-", "r", 0.9),
         ("u", "is_a", "v", 0.9), ("v", "is_a", "u", 0.9),
         ("k", "is_a", "cls", 0.9), ("cls", "causes+", "e", 0.8), ("m", "opposes", "n", 0.6)]
    return R.deduce(F, max_len=3)


def test_deduction_transitivity_and_signs():
    D = _small_kb()
    ix = {tuple(t[:3]): t for t in D["facts"]}
    assert ("a", "is_a", "d") in ix and math.isclose(ix[("a", "is_a", "d")][3], 0.9 ** 3)
    assert ("x", "causes-", "z") in ix and ("x", "causes+", "z") not in ix
    assert ("x", "causes+", "z2") in ix
    assert ("c1", "causes+", "c4") in ix and ("c1", "causes+", "c5") not in ix     # three causal links at most
    assert ("k", "causes+", "e") in ix                                              # inherited down is_a
    assert ("n", "opposes", "m") in ix
    assert ("x", "hedges", "y2") not in ix                                          # no hedging from signs
    assert D["fixpoint"] and D["steps"] < 30
    assert D["counts"]["is_a.transitive"] >= 3


def test_proofs_reproduce_derivation():
    D = _small_kb()
    tr = R.prove(("c1", "causes+", "c4"), D)
    assert tr["rule"].startswith("causal.")
    leaves = R._leaves(tr)
    assert leaves == [["c1", "causes+", "c2"], ["c2", "causes+", "c3"], ["c3", "causes+", "c4"]]
    conf = 1.0
    for l in leaves:
        conf *= {tuple(t[:3]): t[3] for t in D["facts"]}[tuple(l)]
    assert math.isclose(tr["conf"], conf)
    ep = R.explain_path("x", "z", D)
    assert ep["derived"] and ep["paths"][0]["relation"] == "causes-"
    assert R.prove(("zz", "is_a", "yy"), D) is None


def test_contradictions_found():
    D = _small_kb()
    kinds = [(c["kind"], tuple(c.get("pair", [c.get("node")]))) for c in D["contradictions"]]
    assert ("sign", ("p", "r")) in kinds
    assert any(k == "is_a_cycle" for k, _ in kinds)


def test_graph_facts_ignore_related():
    G = {"nodes": [{"id": "a", "n": "A"}, {"id": "b", "n": "B"}, {"id": "c", "n": "C"}], "types": ["is_a", "related", "causes+"],
         "edges": [[0, 1, 0.9, 0], [1, 2, 0.6, 1], [0, 2, 0.8, 2]]}
    F = R.graph_facts(G)
    assert ("a", "is_a", "b", 0.9, "mind.json") in F and all(f[1] != "related" for f in F)
    D = R.deduce(G)
    assert D["names"]["a"] == "A"


# ---------------------------------------------------------------- the decision as rules
def test_decision_proof_defaults_and_flips():
    dp = R.decision_proof(R.DEFAULT_FACTS)
    c = dp["conclusions"]
    assert c["exposure"] == 1.0 and c["bond_hedge"] == "off" and c["overlay"] == "none" and c["state"] == "amplifying"     # corr +0.15 is above the +0.10 band, as on the page

    def leaves(t):
        return [t] if t.get("given") else [x for p in t["premises"] for x in leaves(p)]
    names = {r["name"] for r in R.POLICY_RULES} | {"decision"}

    def rules_ok(t):
        return t.get("given") or (t["rule"] in names and all(rules_ok(p) for p in t["premises"]))
    lv = leaves(dp["proof"])
    assert lv and all(l["fact"].split(" = ")[0] in R.DEFAULT_FACTS for l in lv)
    assert rules_ok(dp["proof"])
    cf = {r["premise"]: r for r in dp["counterfactuals"] if "flips_up" in r}
    assert abs(cf["corr36"]["flips_down"]["at"] + 0.10) < 1e-4 and cf["corr36"]["flips_down"]["bond_hedge"] == "on"
    assert abs(cf["gate"]["flips_up"]["at"] - 0.05) < 2e-3 and cf["gate"]["flips_up"]["exposure"] == 1.05
    assert abs(cf["es_1x"]["flips_up"]["at"] - 0.12) < 1e-4 and cf["es_1x"]["flips_up"]["exposure"] == 0.95
    assert abs(cf["es_limit"]["flips_down"]["at"] - 0.0642) < 1e-4
    assert cf["engine_exposure"]["flips_up"] is None and "gate" in cf["engine_exposure"]["why_not"]
    assert cf["infl36"]["flips_up"] is None and cf["infl36"]["flips_down"] is None
    # direct checks either side of each threshold
    f = R.DEFAULT_FACTS
    assert R.decision_proof({**f, "corr36": -0.11})["conclusions"]["bond_hedge"] == "on"
    assert R.decision_proof({**f, "corr36": -0.09})["conclusions"]["bond_hedge"] == "off"
    assert R.decision_proof({**f, "corr36": -0.11, "infl36": 0.05})["conclusions"]["bond_hedge"] == "off"
    assert R.decision_proof({**f, "corr36": -0.05, "prev_state": "hedging"})["conclusions"]["bond_hedge"] == "on"
    assert R.decision_proof({**f, "corr36": 0.05, "prev_state": "hedging"})["conclusions"]["bond_hedge"] == "off"
    assert R.decision_proof({**f, "gate": 1.0})["conclusions"]["exposure"] == 1.5
    assert R.decision_proof({**f, "gate": 1.0, "es_1x": 0.1})["conclusions"]["exposure"] == 1.2
    assert R.decision_proof({**f, "trend_on": False, "overlay_factor": 0.5})["conclusions"]["exposure"] == 0.5
    assert not _has_banned(R._js(dp))


# ---------------------------------------------------------------- invention and abduction
def _cluster_panel(seed=4, n=1200):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1901-01-01", periods=n, freq="MS")
    A = np.array([[0.995, 0.0025, 0.0025], [0.0025, 0.995, 0.0025], [0.0025, 0.0025, 0.995]])
    s = np.zeros(n, int)
    for t in range(1, n):
        s[t] = rng.choice(3, p=A[s[t - 1]])
    # make sure every regime appears before and after the cutoff
    s[:120], s[120:240], s[240:360], s[800:900], s[900:1000], s[1000:1100] = 0, 1, 2, 0, 1, 2
    means = np.array([[3, 0, 0, 0], [0, 3, 0, 0], [0, 0, 3, -3]], float)
    cols = ["cape_pct", "y10", "vol12", "corr36"]
    X = means[s] + 0.5 * rng.standard_normal((n, 4))
    P = pd.DataFrame(X, index=idx, columns=cols)
    P["ret12"] = np.array([0.08, 0.02, -0.04])[s] + 0.1 * rng.standard_normal(n)
    P["crash12"] = (rng.random(n) < np.array([0.03, 0.05, 0.4])[s]).astype(float)
    return P, s, cols


def test_invent_recovers_and_names_clusters():
    from sklearn.metrics import adjusted_rand_score
    P, s, cols = _cluster_panel()
    inv, lab, assign = R.invent(P, cutoff="1960-12", feats=cols, return_labels=True, predicates=False, ks=range(2, 6))
    assert inv["k"] == 3
    post = lab.index > "1960-12-31"
    assert adjusted_rand_score(s[np.asarray(post)], lab[post].to_numpy()) > 0.9
    names = [c["name"] for c in inv["clusters"]]
    assert len(set(names)) == 3 and all(n for n in names)
    assert any("expensive" in n for n in names) and any("volatile" in n for n in names)
    assert inv["oos"]["ret12"]["mse_skill"] > 0.1 and inv["oos"]["crash12"]["beats_unconditional"]
    assert assign(P.iloc[-1]) == lab.iloc[-1]
    assert not _has_banned(R._js(inv))


def test_rare_condition_is_untestable_not_failed():
    rng = np.random.default_rng(1)
    y = rng.standard_normal(300)
    m = np.zeros(300, bool)
    m[:5] = True
    o = R._oos(y, m, 0, 1)
    assert o["testable"] is False and o["kept_sign"] is None and o["p_one"] == 1.0


def test_invent_predicates_runs():
    P, s, cols = _cluster_panel(seed=5)
    pr = R.invent_predicates(P, "1960-12", feats=cols)
    assert pr["candidates"] > 0 and isinstance(pr["survivors"], list)


def test_abduce_ranks_planted_cause_first():
    rng = np.random.default_rng(6)
    n = 1500
    idx = pd.date_range("1880-01-01", periods=n, freq="MS")
    X = ar_features(n, 4, 6, rho=0.95)
    P = pd.DataFrame(X, index=idx, columns=["cape_pct", "y10", "vol12", "corr36"])
    hi = P["vol12"] > np.quantile(P["vol12"], 0.8)
    P["crash12"] = (rng.random(n) < np.where(hi, 0.7, 0.04)).astype(float)
    ab = R.abduce(P, {"crash12": 1}, feats=list(P.columns[:4]))
    top = ab["explanations"][0]
    assert top["if"][0][0] == "vol12" and top["if"][0][1] == ">"
    assert abs(top["if"][0][2] - np.quantile(P["vol12"], 0.8)) < 1e-9
    assert top["lr"] > 5
    # and the current-row reasoning labels its combination
    row = P.iloc[-1].copy()
    row["vol12"] = 99.0
    now = R.abduce_now(P, row, [{"id": "r", "if": [["vol12", ">", float(np.quantile(P['vol12'], 0.8))]], "outcome": "crash12", "survives": True}])
    assert now["fires"] and "naive Bayes" in now["joint"]["crash12"]["method"]
    assert now["joint"]["crash12"]["combined"] > now["joint"]["crash12"]["base"]


# ---------------------------------------------------------------- build
def test_build_synthetic_json_safe():
    S = synth_S(1800, seed=8)
    G = {"nodes": [{"id": "a", "n": "A"}, {"id": "b", "n": "B"}, {"id": "c", "n": "C"}], "types": ["is_a", "causes+", "causes-"],
         "edges": [[0, 1, 0.8, 1], [1, 2, 0.8, 2]]}
    o = R.build(S, G=G, do_rolling=False, quick=True)
    s = json.dumps(o, allow_nan=False)
    assert "NaN" not in s
    assert not _has_banned(o)
    assert o["decision"]["conclusions"]["exposure"] == 1.0
    assert o["findings"] and all(isinstance(x, str) for x in o["findings"])
    assert o["deduce"]["derived"] >= 1


@pytest.mark.skipif(not os.path.exists(f"{SCRATCH}/labs_dl.pkl"), reason="cached download absent")
def test_real_panel_shapes():
    from buildout import labs
    dl = pickle.load(open(f"{SCRATCH}/labs_dl.pkl", "rb"))
    P = R.panel(labs.shiller(dl))
    assert len(P) > 1800 and P["corr36"].notna().sum() > 1500
    assert 0.1 < P["crash12"].mean() < 0.4
