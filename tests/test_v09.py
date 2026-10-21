"""v0.9: the brain's frontier reasoning and structure learning, checked against brute force, planted answers, and the
page's JavaScript on the page's own graph and series."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import chi2, multivariate_normal, norm

from buildout import discovery as D
from buildout import thinking as TH

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")
REQ = {"graph": {"K": 6, "blends": [0, 0.25, 0.5, 0.75, 1], "cf": ["oil", 0.0], "level": -0.4, "chi2": [[3, 4], [30, 10], [0.5, 1], [80, 34]]},
       "discovery": {"rows": 383, "draws": 6, "learn": True}}


@pytest.fixture(scope="module")
def js():
    if NODE is None:
        pytest.skip("node not installed")
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness9.js")], input=json.dumps(REQ), capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def _py_graph(js):
    g = js["graph"]
    obs = {int(k): v for k, v in g["observed"].items()}
    E = {float(b): [tuple(e) for e in es] for b, es in g["edges_by_blend"].items()}
    T = TH.total_effect(g["n"], E[1.0], REQ["graph"]["K"])
    return g, obs, E, T


def _chain():
    n = 9
    E = [(0, 3, 0.6), (1, 3, -0.4), (2, 4, 0.7), (3, 5, 0.5), (4, 5, 0.3), (5, 6, 0.8), (3, 7, 0.4), (7, 5, -0.3), (6, 8, 0.5), (5, 3, 0.1)]
    return n, E, TH.total_effect(n, E, 6), [0, 1, 2], {3: 1.0, 4: -0.5, 5: 0.7, 7: 0.2}


# ---------- exact against brute force ----------
def test_marginal_and_leave_one_out_are_exact():
    n, E, T, roots, obs = _chain()
    mg = TH.marginal(T, obs, roots)
    o = sorted(obs)
    A = T[np.ix_(o, roots)]
    S = 0.25 * np.eye(len(o)) + A @ A.T
    y = np.array([obs[i] for i in o])
    assert mg["logpdf"] == pytest.approx(multivariate_normal(np.zeros(len(o)), S).logpdf(y), abs=1e-10)
    loo = {d["node"]: d["z"] for d in TH.surprise(T, obs, roots)["loo"]}
    for k, i in enumerate(o):
        rest = [j for j in range(len(o)) if j != k]
        mu = S[k, rest] @ np.linalg.solve(S[np.ix_(rest, rest)], y[rest])
        v = S[k, k] - S[k, rest] @ np.linalg.solve(S[np.ix_(rest, rest)], S[rest, k])
        assert loo[i] == pytest.approx((y[k] - mu) / math.sqrt(v), abs=1e-10)


def test_paths_but_for_and_loss_story_identities():
    n, E, T, roots, obs = _chain()
    ab = TH.abduce(T, obs, roots)
    pa = TH.path_attribution(n, E, 6, ab, 8, top=3)
    exact = sum(T[8, r] * s for r, s in zip(roots, ab["s"]))
    assert pa["total"] == pytest.approx(exact, abs=1e-12)
    assert sum(p["contribution"] for p in pa["paths"]) + pa["other"] == pytest.approx(exact, abs=1e-12)
    assert sum(d["contribution"] for d in TH.but_for(T, ab, 8)) == pytest.approx(TH.predict(T, ab)["mean"][8], abs=1e-12)
    ls = TH.loss_story(T, roots, 8, -0.5)
    assert np.dot(T[8, roots], ls["s_star"]) == pytest.approx(-0.5) and ls["p_at_or_below"] == pytest.approx(norm.cdf(ls["z"]))
    # the forward story is the minimum-norm one: no other combination reaching -0.5 is closer to "nothing happens"
    a = T[8, roots]
    rng = np.random.default_rng(0)
    for _ in range(50):
        v = rng.normal(size=3)
        v = v - a * (a @ v) / (a @ a) + a * (-0.5) / (a @ a)
        assert np.linalg.norm(v) >= np.linalg.norm(ls["s_star"]) - 1e-12
    ex = TH.loss_story(T, roots, 8, -0.5, exclude=[0])
    assert ex["shift"][0] == 0 and abs(ex["z"]) >= abs(ls["z"])


def test_counterfactual_keeps_the_evidence_and_moves_only_descendants():
    n, E, T, roots, obs = _chain()
    ab = TH.abduce(T, obs, roots)
    cf = TH.counterfactual(n, E, 6, T, ab, 3, 0.0)
    xf, xc = np.array(cf["factual"]), np.array(cf["counterfactual"])
    assert xc[3] == pytest.approx(0.0)
    for i in (0, 1, 2, 4):                                   # not downstream of node 3: unchanged
        assert xc[i] == pytest.approx(xf[i])
    for o, v in zip(ab["obs"], ab["y"]):                     # the factual world is the observed one
        assert xf[o] == pytest.approx(v)


def test_regime_comparison_finds_the_planted_world():
    n = 5
    E0 = [(0, 2, 0.8), (1, 2, 0.1), (2, 3, 0.6), (2, 4, -0.5)]
    E1 = [(0, 2, -0.6), (1, 2, 0.9), (2, 3, 0.6), (2, 4, 0.5)]
    T0, T1 = TH.total_effect(n, E0, 4), TH.total_effect(n, E1, 4)
    s = np.array([1.5, -0.4])
    y = T1[:, [0, 1]] @ s
    obs = {2: y[2], 3: y[3], 4: y[4]}
    rp = TH.regime_posterior({0.0: T0, 1.0: T1}, obs, [0, 1])
    assert rp["p"][1] > 0.9 and rp["bayes_factor_new_vs_old"] > 10


# ---------- structure learning: planted answers ----------
def test_lingam_recovers_a_planted_causal_order():
    rng = np.random.default_rng(3)
    n = 3000
    e = rng.laplace(size=(n, 5)) * [1.0, 0.8, 1.2, 0.9, 1.0]
    x0 = e[:, 0]
    x1 = 0.8 * x0 + e[:, 1]
    x2 = -0.6 * x1 + 0.5 * x0 + e[:, 2]
    x3 = 0.7 * x2 + e[:, 3]
    x4 = 0.5 * x1 - 0.4 * x3 + e[:, 4]
    truth = [x0, x1, x2, x3, x4]
    perm = [3, 0, 4, 2, 1]                                     # shuffle the columns so position is no hint
    X = np.column_stack([truth[p] for p in perm])
    learned = [perm[i] for i in D.lingam_order(X)]
    assert learned == [0, 1, 2, 3, 4]


def test_kalman_tracks_a_planted_sign_flip_and_learns_the_drift():
    rng = np.random.default_rng(5)
    n = 400
    x = rng.normal(size=(n, 2))
    beta = np.where(np.arange(n) < 250, 0.3, -0.3)
    y = 0.5 * x[:, 0] + beta * x[:, 1] + rng.normal(scale=0.5, size=n)
    k = D.kalman_mle(y, x)
    b = np.array(k["beta"])[:, 1]
    assert abs(b[100] - 0.3) < 0.15 and abs(b[350] + 0.3) < 0.15
    flips = D.sign_changes(list(b), None, [str(i) for i in range(n)])
    assert any(220 <= int(f["date"]) <= 280 and f["to"] == "negative" for f in flips)
    flat = D.kalman_mle(0.5 * x[:, 0] + 0.3 * x[:, 1] + rng.normal(scale=0.5, size=n), x)
    assert flat["q"] < k["q"]                                  # a link that never moved earns a smaller drift


def test_mulberry_matches_the_page_and_resamples_are_shared(js):
    assert D.resamples(REQ["discovery"]["rows"], 3, 7) == js["discovery"]["samples"]


# ---------- the page agrees ----------
def test_frontier_reasoning_matches_python_on_the_page_graph(js):
    g, obs, E, T = _py_graph(js)
    roots, book, K = g["roots"], g["book"], REQ["graph"]["K"]
    mg = TH.marginal(T, obs, roots)
    assert g["marginal"]["logpdf"] == pytest.approx(mg["logpdf"], abs=1e-9)
    Tby = {b: TH.total_effect(g["n"], es, K) for b, es in E.items()}
    rp = TH.regime_posterior(Tby, obs, roots)
    assert g["regime"]["p"] == pytest.approx(rp["p"], abs=1e-9)
    su = TH.surprise(T, obs, roots)
    assert g["surprise"]["p"] == pytest.approx(su["p"], abs=1e-9)
    assert [d["node"] for d in g["surprise"]["loo"]] == [d["node"] for d in su["loo"]]
    ab = TH.abduce(T, obs, roots)
    cf = TH.counterfactual(g["n"], E[1.0], K, T, ab, g["cf_node"], REQ["graph"]["cf"][1])
    assert g["cf"]["change"] == pytest.approx(cf["change"], abs=1e-9)
    pa = TH.path_attribution(g["n"], E[1.0], K, ab, book)
    assert g["paths"]["total"] == pytest.approx(pa["total"], abs=1e-9) and g["paths"]["n_paths"] == pa["n_paths"]
    assert [round(p["contribution"], 9) for p in g["paths"]["paths"]] == [round(p["contribution"], 9) for p in pa["paths"]]
    assert [d["contribution"] for d in g["butfor"]] == pytest.approx([d["contribution"] for d in TH.but_for(T, ab, book)], abs=1e-9)
    for key, kw in (("loss", {}), ("lossNow", {"s_mean": ab["s"], "cov": ab["cov"]}), ("lossEx", {"exclude": [roots[0], roots[6]]})):
        ls = TH.loss_story(T, roots, book, REQ["graph"]["level"], **kw)
        assert g[key]["p_at_or_below"] == pytest.approx(ls["p_at_or_below"], abs=1e-9)
        assert g[key]["s_star"] == pytest.approx(ls["s_star"], abs=1e-9)
    for (x, k), v in zip(REQ["graph"]["chi2"], g["chi2"]):
        assert v == pytest.approx(chi2.sf(x, k), rel=1e-9, abs=1e-15)


def test_structure_learning_matches_python_on_the_page_series(js):
    from buildout.brain import learn
    d = js["discovery"]
    block = d["series"]
    rows = REQ["discovery"]["rows"]
    X = np.array(block["z"]).T[:rows]
    assert d["order"] == D.lingam_order(X)
    bs = D.bootstrap_order(X, D.resamples(rows, REQ["discovery"]["draws"], 7))
    assert np.allclose(d["boot"]["p_before"], bs["p_before"])
    k = D.kalman_links(X[:, 3], X[:, [0, 2]], 1e-3)
    assert np.allclose(d["kal"]["beta"], k["beta"], atol=1e-9) and d["kal"]["loglik"] == pytest.approx(k["loglik"], abs=1e-8)
    py = learn(block)
    for name in ("low_inflation", "inflation"):
        assert d["learn"]["order"][name]["learned"] == py["order"][name]["learned"]
    for key, v in d["learn"]["links"].items():
        assert v["q"] == py["links"][key]["q"]
        assert np.allclose(v["beta"], py["links"][key]["beta"], atol=1e-4)    # Python rounds the stored path to 4 dp


# ---------- the MCP server carries the frontier ----------
def test_mcp_trace_exposure_carries_the_frontier_and_matches_the_page(js):
    from buildout import mcp_server as MS
    ctx = MS.Context()
    call = lambda name, args: MS.handle(ctx, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})["result"]  # noqa: E731
    r = call("trace_exposure", {"counterfactual": {"node": "oil", "value": 0.0}, "tail_probability": 0.05})
    assert r["isError"] is False
    f = r["structuredContent"]["frontier"]
    assert list(f["which_world"]["posterior"].values()) == pytest.approx(js["graph"]["regime"]["p"], abs=1e-4)
    assert f["surprise"]["p_value"] == pytest.approx(js["graph"]["surprise"]["p"], abs=1e-4)
    assert f["channels"]["total_sd"] == pytest.approx(js["graph"]["paths"]["total"], abs=1e-4)
    assert f["counterfactual"]["book"]["counterfactual"] - f["counterfactual"]["book"]["factual"] == pytest.approx(js["graph"]["cf"]["change"][js["graph"]["book"]], abs=1e-3)
    assert f["bad_quarter"]["story"] and f["bad_quarter"]["runner_up"]["probability"] < 0.05
    for bad in ({"counterfactual": {"node": "book", "value": 1}}, {"counterfactual": {"node": "oil"}}, {"tail_probability": 2}):
        assert call("trace_exposure", bad)["isError"] is True
    L = call("learned_structure", {"link": "y10>eq"})["structuredContent"]
    assert L["order"]["learned_1990_2021"] == js["discovery"]["learn"]["order"]["low_inflation"]["learned"]
    assert set(L["links"]) == {"y10>eq"} and L["months"] == len(js["discovery"]["series"]["dates"])
    assert call("learned_structure", {"link": "nope"})["isError"] is True


@needs_node
def test_the_page_accepts_the_engines_learned_block_and_rejects_broken_ones(js):
    from buildout.brain import learn
    good = learn(js["discovery"]["series"])
    bad = json.loads(json.dumps(good))
    bad["links"]["y10>eq"]["beta"] = bad["links"]["y10>eq"]["beta"][:-1]
    worse = json.loads(json.dumps(good))
    worse["order"]["low_inflation"]["learned"][0] = "<b>"
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness9.js")], input=json.dumps({"validate": [good, bad, worse, None, {"dates": []}]}),
                       capture_output=True, text=True, check=True)
    assert json.loads(r.stdout)["valid"] == [True, False, False, False, False]
