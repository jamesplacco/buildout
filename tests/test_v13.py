"""v0.13: the atlas. Structure learning recovers a planted graph, the dynamics are exact, the page's arithmetic
equals Python's, the layout and communities behave, and the data plumbing (gaps, currency quotes) is right."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import atlas as AT

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
SNAP = json.loads((ROOT / "buildout" / "assets" / "atlas.json").read_text())


def _planted(p=12, n=700, seed=4, missing=True):
    """A random DAG with uniform (non-Gaussian) shocks; some series start late or end early."""
    rng = np.random.default_rng(seed)
    order = list(range(p))
    B = np.zeros((p, p))
    edges = set()
    for j in range(1, p):
        for i in rng.choice(j, size=min(j, 2), replace=False):
            w = rng.choice([-1, 1]) * rng.uniform(0.3, 0.6)
            B[j, i] = w
            edges.add((min(i, j), max(i, j)))
    E = rng.uniform(-1, 1, (n, p)) * np.sqrt(3)
    X = np.linalg.solve(np.eye(p) - B, E.T).T
    X = (X - X.mean(0)) / X.std(0)
    if missing:
        X[:150, 3] = np.nan
        X[-120:, min(7, p - 1)] = np.nan
    return X, B, edges, order


def test_structure_learning_recovers_a_planted_graph():
    X, B, truth, _ = _planted()
    C, N = AT.pairwise_corr(X)
    S = AT.nearest_pd(C)
    ch = AT.choose_alpha(S, float(np.median(N[np.triu_indices(len(S), 1)])))
    st = AT.stability(X, ch["alpha"], n_sub=24)
    found = {(i, j) for i in range(len(S)) for j in range(i + 1, len(S)) if st["freq"][i, j] >= AT.PI_THR}
    # a graphical model recovers the moral graph: the causal links plus a link between two causes of one effect
    moral = set(truth)
    for j in range(len(B)):
        ps = [i for i in range(len(B)) if B[j, i]]
        moral |= {(min(a, b), max(a, b)) for a in ps for b in ps if a != b}
    # the lasso screens generously (it keeps small partial correlations among strongly correlated series); stability
    # selection and then the regression's own t-statistics do the filtering
    assert len(found & truth) / len(truth) >= 0.9, (truth - found)          # screening recall of the causal links
    orn = AT.orient(X, sorted(found))
    fit = AT.fit_svar(X, orn["order"], sorted(found), nbr_lag=False)
    kept = {(min(i, j), max(i, j)) for j in range(len(B)) for i in range(len(B)) if fit["B"][j, i]}
    assert len(kept & truth) / max(1, len(kept)) >= 0.8, (kept - truth)     # pruning removes the marriages
    assert len(kept & truth) / len(truth) >= 0.7
    right = sum(1 for j in range(len(B)) for i in range(len(B)) if fit["B"][j, i] and B[j, i])
    assert right / max(1, len(kept & truth)) >= 0.75                         # and points them the right way


def test_pairwise_corr_matches_pandas():
    X, *_ = _planted(p=6, n=300)
    C, N = AT.pairwise_corr(X, min_n=10)
    ref = pd.DataFrame(X).corr(min_periods=10).to_numpy()
    assert np.allclose(C, ref, atol=1e-10)
    assert N[3, 0] == 150 and N[5, 3] == 300 - 150 - 120


def test_svar_dynamics_are_exact():
    rng = np.random.default_rng(1)
    p = 7
    B = np.tril(rng.normal(0, 0.3, (p, p)), -1)
    A = rng.normal(0, 0.12, (p, p))
    A, r0, f = AT.stable_A(B, A)
    Phi = AT.irf(B, A, 6)
    P0 = np.linalg.inv(np.eye(p) - B)
    assert np.allclose(Phi[0], P0)
    assert np.allclose(Phi[3], np.linalg.matrix_power(P0 @ A, 3) @ P0)
    con = AT.connectedness(Phi, np.ones(p))
    assert np.allclose(con["theta"].sum(axis=1), 1.0) and 0 <= con["total"] <= 100
    assert con["net"].sum() == pytest.approx(0.0, abs=1e-9)          # what is given is taken


def test_gfevd_bounds_and_rolling_has_no_look_ahead():
    X, *_ = _planted(p=10, n=200, missing=False)
    v = AT.gfevd_total(X)
    assert 0 < v < 100
    idx = pd.date_range("2000-01-01", periods=200, freq="MS")
    Z = pd.DataFrame(X, index=idx)
    a = AT.rolling_connectedness(Z, window=60)
    Z2 = Z.copy()
    Z2.iloc[-1] = 9.0                                                 # a wild last month changes only the last value
    b = AT.rolling_connectedness(Z2, window=60)
    assert a["total"][:-1] == b["total"][:-1] and a["total"][-1] != b["total"][-1]


def test_communities_and_layout():
    p = 16
    W = np.zeros((p, p))
    for blk in (range(0, 8), range(8, 16)):
        for i in blk:
            for j in blk:
                if i != j:
                    W[i, j] = 0.5
    W[0, 8] = 0.05
    lab = AT.communities(W)
    assert len(set(lab[:8])) == 1 and len(set(lab[8:])) == 1 and lab[0] != lab[8]
    assert AT.modularity(W, lab) > 0.4
    X1, X2 = AT.galaxy_layout(W, lab), AT.galaxy_layout(W, lab)
    assert np.array_equal(X1, X2) and np.abs(X1).max() <= 1.0 + 1e-9


def test_gaps_are_not_moves_and_currencies_point_up_when_stronger():
    months = pd.date_range("2000-01-01", periods=200, freq="MS")
    fx = pd.DataFrame({"Date": [d.strftime("%Y-%m-%d") for d in months for _ in (0,)], "Country": "Japan",
                       "Exchange rate": np.linspace(100, 150, 200)})       # yen weakening: more yen per dollar
    gold = pd.DataFrame({"Date": [d.strftime("%Y-%m") for d in months], "Price": np.linspace(1000, 2000, 200)})
    gold = gold.drop(index=range(100, 103))                                # a three-month hole in the data
    P, meta = AT.panel({"raw": {"fx": fx, "gold": gold, "fred": {}}, "failed": {}})
    assert (P["jpy"].dropna() < 0).all()                                   # a weakening yen reads as negative
    assert P["gold"].loc["2008-05-01":"2008-08-01"].isna().sum() >= 1      # no fake four-month jump
    assert meta["jpy"]["family"] == "Asian FX"


def test_snapshot_integrity():
    a = SNAP
    ids = [n["id"] for n in a["nodes"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 90 and a["series"] >= 60
    for l in a["links"]:
        assert l["from"] in ids and l["to"] in ids and abs(l["w"]) < 3
        if not l["lag"]:
            assert 0.7 <= l["stability"] <= 1 and (not l["established"] or l["stability"] >= 0.7)
    sk = a["skeleton"]
    assert sk["established"]["kept"] <= sk["edges_stable"] <= sk["edges_full"]
    assert sk["established"]["pfer_bound"] <= 0.1 * sk["established"]["kept"] + 1e-9
    assert AT.radius(AT.matrices(a)["Wc"]) < 1                             # the same-month system has an inverse
    n = {x["id"]: x for x in a["nodes"]}
    assert n["eur"]["community"] == n["chf"]["community"]                   # the European bloc moves together
    assert any(l["from"] in ("wti", "brent") and l["to"] in ("wti", "brent") for l in a["links"])
    for f in a["findings"]:
        assert "—" not in f and "intersection" not in f.lower()


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_page_atlas_equals_python():
    shocks = [{"hormuz": 1.5}, {"copper": 1.0}, {"sp500": -1.0, "vix": 1.0}, {"fed": 1.0}]
    bad = copy.deepcopy(SNAP)
    bad["links"][0]["w"] = "x"
    bad2 = copy.deepcopy(SNAP)
    bad2["nodes"][0]["x"] = 40
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness13.js")], input=json.dumps({"atlas": SNAP, "shocks": shocks, "h": 12, "bad": [bad, bad2, {}],
                        "mc": {"shock": {"hormuz": 1.5}, "target": "book", "draws": 120}}), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    js = json.loads(r.stdout)
    assert js["ok"] and js["bad"] == [False, False, False]
    M = AT.matrices(SNAP)
    assert js["ids"] == M["ids"]
    for s, R in zip(shocks, js["responses"]):
        py = AT.respond(SNAP, s, 12, M)
        assert np.allclose(np.array(R), py, atol=1e-9)
    mc = js["mc"]
    assert mc["kept"] + mc["dropped"] == 120 and all(b[0] <= b[1] <= b[2] for b in mc["band"])


def test_mcp_atlas_trace():
    from buildout.mcp_server import Context, ToolError, atlas_trace
    r = atlas_trace(Context(data_dir="/nonexistent"), {"shock": {"hormuz": 1.5}, "horizon": 6, "targets": ["book", "brent"]})
    assert len(r["responses"]["book"]["by_month"]) == 7 and r["responses"]["brent"]["by_month"][0] > 0
    assert all(m["node"] != "hormuz" for m in r["moved_most"])
    n = atlas_trace(Context(data_dir="/nonexistent"), {"node": "copper"})
    assert n["node"]["family"] == "Metals" and n["links"]
    for bad in ({}, {"shock": {"nope": 1}}, {"shock": {"copper": 9}}, {"shock": {"copper": True}}, {"node": "nope"}, {"shock": {"copper": 1}, "targets": ["zz"]}):
        with pytest.raises(ToolError):
            atlas_trace(Context(data_dir="/nonexistent"), bad)
