"""v0.14: the mind (one graph of the brain and the engine, and its reasoning loop), the labs, the card-room math,
the checked knowledge base and the page's mirror of all of it."""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from buildout import games2 as G
from buildout import labs, mind, ontology, voices

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
MIND_JSON = ROOT / "buildout" / "assets" / "mind.json"
KNOW = ROOT / "buildout" / "assets" / "knowledge.json"
QUESTIONS = ["Is the stock market overvalued?", "Does the 200-day moving average work?", "Is AI a bubble?", "Will oil keep rising?", "Is RSI useful?",
             "Should I use leverage?", "Are private credit marks too generous?", "Do active managers beat the index?", "Is gold a good hedge now?",
             "Sell in May and go away?", "Should I buy long bonds?", "Should I make the first offer when haggling?", "Is Kelly betting too aggressive?",
             "Will inflation come back?", "zzqx nonsense"]


@pytest.fixture(scope="module")
def snap():
    return json.loads(MIND_JSON.read_text())


@pytest.fixture(scope="module")
def M(snap):
    return mind.Mind(snap, voices.Library(voices.load()))


def _node(req: dict) -> dict:
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness14.js")], input=json.dumps(req), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


# ---------------------------------------------------------------- the ontology and the knowledge base
def test_ontology_is_large_unique_and_resolves():
    cs = ontology.concepts()
    ids = [c["id"] for c in cs]
    assert len(cs) >= 500 and len(ids) == len(set(ids))
    assert set(c["cluster"] for c in cs) <= set(ontology.CLUSTERS)
    known = set(ids)
    dangling = [(c["id"], t) for c in cs for k, t in c["rel"] if ":" not in t and "c:" + t not in known]
    assert not dangling, dangling[:10]


def test_knowledge_items_are_checked_sourced_and_clean():
    items = json.loads(KNOW.read_text())["items"]
    assert len(items) >= 250
    banned = (chr(0x2014), "inter" "section")
    for it in items:
        assert it["source_url"].startswith("https://"), it["id"]
        assert it["checked"].startswith(("confirmed", "corrected")), it["id"]
        assert len(it["text"].split()) <= 70, it["id"]
        assert not any(b in json.dumps(it, ensure_ascii=False).lower() for b in banned), it["id"]
        if it["kind"] == "paper":
            assert it.get("authors"), it["id"]


def test_world_file_carries_no_mislabelled_inflation():
    w = json.loads((ROOT / "buildout" / "assets" / "world.json").read_text())
    assert all("inflation" not in v for v in w["countries"].values())
    assert w["countries"]["USA"]["gdp"] > 2e13


# ---------------------------------------------------------------- the graph
def test_graph_is_an_order_of_magnitude_larger_and_well_formed(snap):
    n = len(snap["nodes"])
    assert n >= 1000                                            # the atlas had 100 nodes
    ids = [x["id"] for x in snap["nodes"]]
    assert len(set(ids)) == n
    for i, j, w, t in snap["edges"]:
        assert 0 <= i < n and 0 <= j < n and i != j and 0 < w <= 1 and 0 <= t < len(snap["types"])
    kinds = {x["k"] for x in snap["nodes"]}
    assert {"concept", "series", "holding", "quote", "investor", "fact", "paper", "engine", "tool", "country", "signal", "cluster"} <= kinds
    assert all(-1.01 <= x["x"] <= 1.01 and -1.01 <= x["y"] <= 1.01 for x in snap["nodes"])
    # the engine's own modules, with the import graph as links
    eng = {x["id"] for x in snap["nodes"] if x["k"] == "engine"}
    assert {"e:mind", "e:atlas", "e:labs", "e:mcp_server", "e:voices"} <= eng


def test_every_typed_reference_resolves_to_a_node(snap):
    ids = {x["id"] for x in snap["nodes"]}

    def resolve(ref):
        kind, _, rest = ref.partition(":")
        if kind in ("s", "j"):
            return "a:" + rest
        if kind == "e":
            return ("m:" + rest if rest != "labs" else "e:labs") if rest.startswith("labs") else "e:" + mind.ENGINE_ALIAS.get(rest, rest)
        return ref
    missing = sorted({t for c in ontology.concepts() for _, t in c["rel"] if ":" in t and resolve(t) not in ids})
    assert not missing, missing
    for iso, _, cur, ex, _ in mind.COUNTRIES:
        for e in ex + ([cur] if cur else []):
            assert (e if ":" in e else "c:" + e) in ids, (iso, e)


def test_every_signal_cites_real_nodes_and_has_a_flip(snap):
    ids = {x["id"] for x in snap["nodes"]}
    for s in snap["signals"]:
        assert s["axis"] in snap["axes"] and s["sign"] in (-1, 1) and 0 < s["s"] <= 1.5 and 0 < s["rel"] <= 1
        assert s["flip"] and s["text"]
        for r in s["refs"]:
            assert r in ids or r.startswith(("e:", "m:")), (s["id"], r)


def test_signals_quote_the_checked_numbers():
    K = {k["id"]: k for k in json.loads(KNOW.read_text())["items"]}
    S = {s["id"]: s for s in json.loads(MIND_JSON.read_text())["signals"]}
    assert f"{K['val-cape-2026-10-20']['value']:.1f}" in S["s:cape"]["text"]
    assert f"{K['ts-sp500-top10-weight-2026-06']['value']:.1f}" in S["s:top10"]["text"]
    assert f"{K['oil-iea-omr-hormuz-flows-sep2026']['value']:.1f}" in S["s:oil_hormuz"]["text"]


# ---------------------------------------------------------------- the reasoning loop
def test_spread_is_a_probability_distribution(M):
    seeds = M.recall("Does the 200-day moving average work?")
    r = M.spread(seeds)
    assert sum(r) == pytest.approx(1.0, abs=1e-9)
    assert min(r) >= 0
    top = sorted(range(M.N), key=lambda i: -r[i])[:5]
    assert M.idx["c:ma200"] in top


def test_spread_matches_closed_form_ppr_on_a_small_graph():
    """Personalized PageRank solves r = (1 - a) s + a P^T r; 40 steps get within (a^40) of it."""
    G0 = {"nodes": [{"id": f"c:{k}", "k": "concept", "n": f"node {k}", "a": [], "t": "", "g": "x"} for k in range(5)],
          "edges": [[0, 1, 1.0, 0], [1, 2, 0.5, 0], [2, 3, 0.8, 0], [3, 0, 0.3, 0], [1, 3, 0.9, 0]], "signals": [], "params": mind.params(), "causal": [], "axes": {}}
    m = mind.Mind(G0)
    r = np.array(m.spread([(0, 1.0)]))
    W = np.zeros((5, 5))
    for i, j, w, _ in G0["edges"]:
        W[i, j] = W[j, i] = w
    deg = W.sum(axis=1)
    P = np.divide(W, deg[:, None], out=np.zeros_like(W), where=deg[:, None] > 0)
    s = np.array([1.0, 0, 0, 0, 0])
    a = mind.ALPHA
    D = (deg == 0).astype(float)
    A = a * P.T + a * np.outer(s, D)
    exact = np.linalg.solve(np.eye(5) - A, (1 - a) * s)
    assert np.allclose(r, exact, atol=a ** 40 * 2)


def test_think_frames_the_right_claim(M):
    exp = {"Is the stock market overvalued?": ("market_valuation", "bear"), "Does the 200-day moving average work?": ("edge:trend", None),
           "Is AI a bubble?": ("ai_boom", "bear"), "Will oil keep rising?": ("oil_energy", "bull"), "Is RSI useful?": ("edge:oscillators", None),
           "Do active managers beat the index?": ("edge:active", None), "Should I buy long bonds?": ("bonds_rates", None),
           "Should I make the first offer when haggling?": ("edge:first_offer", None)}
    for q, (axis, side) in exp.items():
        r = M.think(q)
        assert r["found"] and r["axis"] == axis, (q, r["axis"])
        if side:
            assert r["side"] == side, q
        assert r["range"][0] <= r["p"] + 1e-12 <= r["range"][1] + 2e-12
        assert r["decision"]["executed"] is False


def test_evidence_moves_the_verdict_the_right_way(M):
    assert M.think("Do active managers beat the index?")["p"] < 0.35      # 25% success, fees, Sharpe's arithmetic
    assert M.think("Is the stock market overvalued?")["p"] > 0.5          # CAPE above 99% of history
    r = M.think("Should I use leverage?")
    assert r["claim"].startswith("Take risk") and r["p"] < 0.5


def test_dependence_discount_and_hinge(M):
    seeds = M.recall("Is the stock market overvalued?")
    r = M.spread(seeds)
    V = M.weigh("market_valuation", r, "Is the stock market overvalued?")
    by = {}
    for x in V["rows"]:
        by.setdefault(x["sig"]["group"], []).append(x)
    for g in by.values():
        deps = sorted(x["dep"] for x in g)[::-1]
        assert deps == pytest.approx([1 / math.sqrt(k + 1) for k in range(len(g))])
    L = sum(x["c"] for x in V["rows"])
    assert V["p_bull"] == pytest.approx(1 / (1 + math.exp(-L)))
    h = V["hinge"]
    assert max(abs(x["c"]) for x in V["rows"]) == pytest.approx(abs(next(x["c"] for x in V["rows"] if x["sig"]["id"] == h["id"])))


def test_chains_reach_the_book_over_atlas_links(M, snap):
    r = M.think("Will oil keep rising?")
    assert r["chains"]
    causal = {(a, b) for a, b, _ in snap["causal"]}
    for c in r["chains"]:
        assert c["path"][-1] == "a:book"
        for u, v in zip(c["path"], c["path"][1:]):
            assert (M.idx[u], M.idx[v]) in causal


def test_unknown_question_is_handled(M):
    r = M.think("zzqx nonsense")
    assert r["found"] is False


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_page_mind_matches_python(snap, M):
    req = {"voices": {"cfg": voices.config(), "lib": {"quotes": voices.load()}}, "mind": snap, "questions": QUESTIONS, "spread": "Is gold a good hedge now?",
           "bad": [{}, {"nodes": []}, dict(snap, edges=[[0, 0, -1, 0]])]}
    out = _node(req)
    assert out["ok"] is True and out["bad"] == [False, False, False]
    seeds = M.recall("Is gold a good hedge now?")
    r = M.spread(seeds)
    assert np.allclose(out["spread"], r, atol=1e-12)
    for q, js in zip(QUESTIONS, out["think"]):
        py = M.think(q)
        assert js["found"] == py["found"], q
        if not py["found"]:
            continue
        assert js["axis"] == py["axis"] and js["side"] == py["side"] and js["mode"] == py["mode"], q
        assert js["seeds"] == [s["id"] for s in py["seeds"]], q
        assert js["p"] == pytest.approx(py["p"], abs=1e-6) and js["logodds"] == pytest.approx(py["logodds"], abs=1e-6), q
        assert js["range"] == pytest.approx(py["range"], abs=1e-6), q
        assert [x[0] for x in js["pros"]] == [x["id"] for x in py["pros"]] and [x[0] for x in js["cons"]] == [x["id"] for x in py["cons"]], q
        assert js["hinge"]["id"] == py["hinge"]["id"], q
        assert [c["path"] for c in js["chains"]] == [c["path"] for c in py["chains"]], q
        assert js["decision"] == py["decision"]["action"] and js["hedge"] == py["decision"].get("hedge"), q
        assert js["concepts"] == [c["id"] for c in py["concepts"]], q
        assert [o[0] for o in js["others"]] == [o["axis"] for o in py["others"]], q


# ---------------------------------------------------------------- the card room
def test_hand_evaluator_ranks_categories():
    c = lambda s: [G.card(x) for x in s.split()]  # noqa: E731
    hands = ["As Ks Qs Js Ts 2d 3c", "9h 9d 9s 9c 2d 3c 4h", "Kh Kd Ks 2c 2d 7h 8s", "Ah 9h 5h 3h 2h Kd Qc", "5d 4c 3h 2s Ad Kc Qh",
             "7h 7d 7s Kc 2d 9h 4s", "Jh Jd 4s 4c 9d 2h 3s", "Qh Qd 8s 6c 4d 3h 2s", "Ah Jd 9s 7c 5d 3h 2s"]
    cats = [G.category(G.eval7(c(h))) for h in hands]
    assert cats == ["Straight flush", "Four of a kind", "Full house", "Flush", "Straight", "Three of a kind", "Two pair", "Pair", "High card"]
    vals = [G.eval7(c(h)) for h in hands]
    assert vals == sorted(vals, reverse=True)
    assert G.eval7(c("5d 4c 3h 2s Ad Kc Qh")) < G.eval7(c("6d 5c 4h 3s 2d Kc Qh"))   # the wheel is the lowest straight


def test_equity_matches_known_matchups():
    aa = G.equity([G.card("As"), G.card("Ah")], [], 1, trials=6000, seed=3)["equity"]
    assert aa == pytest.approx(0.852, abs=0.015)                 # pocket aces against a random hand
    sure = G.equity([G.card("As"), G.card("Ah")], [G.card(x) for x in ("Ad", "Ac", "Kd", "2s", "3h")], 1, trials=500)["equity"]
    assert sure == pytest.approx(1.0, abs=0.002)


def test_bargaining_and_sizing_closed_forms():
    assert G.rubinstein(0.9, 0.9)["first"] == pytest.approx(1 / 1.9)
    assert G.rubinstein(0.99, 0.5)["first"] > 0.5
    n = G.nash_split(100, 20, 30, 0.5)
    assert n["x1"] == pytest.approx(45) and n["x2"] == pytest.approx(55)
    b = G.best_offer(40, 50, 120)
    assert b["price"] == pytest.approx(80) and b["accept"] == pytest.approx(40 / 70)
    assert G.kelly(0.55, 1) == pytest.approx(0.10)
    assert G.risk_of_ruin(0.1, 1, G.bankroll_for(0.1, 1, 0.01)) == pytest.approx(0.01)
    assert G.irr([-100, 0, 121]) == pytest.approx(0.10)
    m = G.multiples([50, 50], [30, 60], 40)
    assert (m["tvpi"], m["dpi"], m["rvpi"]) == pytest.approx((1.3, 0.9, 0.4))
    assert G.ks_pme([100, 0], [0, 150], 0, [100, 150]) == pytest.approx(1.0)   # matched the index exactly
    y = G.yale_model()
    assert y["trough"] < 0 and y["trough_year"] <= 5 and y["tvpi"] > 1
    assert G.implied_convenience(100, G.carry_price(100, 0.05, 0.02, 0.07, 0.5), 0.05, 0.02, 0.5) == pytest.approx(0.07)
    assert G.roll_yield(110, 100, 12) > 0 > G.roll_yield(100, 110, 12)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_page_card_room_matches_python():
    hands = [["As", "Ks", "Qs", "Js", "Ts", "2d", "3c"], ["5d", "4c", "3h", "2s", "Ad", "Kc", "Qh"], ["Jh", "Jd", "4s", "4c", "9d", "2h", "3s"], ["Ah", "Jd", "9s", "7c", "5d", "3h", "2s"]]
    req = {"voices": {"cfg": voices.config(), "lib": {"quotes": voices.load()}}, "mind": json.loads(MIND_JSON.read_text()),
           "games": {"hands": hands, "equity": [[["As", "Kd"], [], 2, 1500, 7], [["7h", "2c"], ["Ad", "Kd", "3s"], 1, 1500, 9]], "kelly": [[0.55, 1], [0.3, 4]],
                     "ruin": [[0.05, 1.2, 40]], "rub": [[0.95, 0.9]], "nash": [[100, 20, 30, 0.6]], "offer": [[40, 50, 120], [10, 50, 60]],
                     "irr": [[[-100, 20, 30, 80], None], [[-50, -50, 40, 90], [0, 1, 3, 5]]], "mult": [[[50, 50], [30, 60], 40]], "pme": [[[100, 50], [30, 160], 20, [100, 110, 150]]],
                     "yale": [[100, 12, [0.25, 0.333, 0.5, 0.5, 0.5, 0.5], 0.1, 2.5, 0, 12]], "carry": [[100, 0.05, 0.02, 0.1, 1]], "conv": [[134, 107, 0.05, 0.02, 0.5]], "roll": [[134, 107, 6]]}}
    g = _node(req)["games"]
    assert g["eval"] == [G.eval7([G.card(x) for x in h]) for h in hands]
    for (hero, board, n, t, seed), js in zip(req["games"]["equity"], g["equity"]):
        py = G.equity([G.card(x) for x in hero], [G.card(x) for x in board], n, t, seed)
        assert js["equity"] == pytest.approx(py["equity"], abs=1e-12)
    assert g["kelly"] == pytest.approx([G.kelly(0.55, 1), G.kelly(0.3, 4)])
    assert g["ruin"][0] == pytest.approx(G.risk_of_ruin(0.05, 1.2, 40))
    assert g["rub"][0]["first"] == pytest.approx(G.rubinstein(0.95, 0.9)["first"])
    assert g["nash"][0]["x1"] == pytest.approx(G.nash_split(100, 20, 30, 0.6)["x1"])
    assert g["offer"][0]["price"] == pytest.approx(G.best_offer(40, 50, 120)["price"]) and g["offer"][1]["price"] == pytest.approx(G.best_offer(10, 50, 60)["price"])
    assert g["irr"][0] == pytest.approx(G.irr([-100, 20, 30, 80]), abs=1e-9)
    assert g["irr"][1] == pytest.approx(G.irr([-50, -50, 40, 90], [0, 1, 3, 5]), abs=1e-9)
    assert g["mult"][0]["tvpi"] == pytest.approx(1.3)
    assert g["pme"][0] == pytest.approx(G.ks_pme([100, 50], [30, 160], 20, [100, 110, 150]))
    y = G.yale_model()
    assert g["yale"][0]["irr"] == pytest.approx(y["irr"], abs=1e-9) and g["yale"][0]["trough_year"] == y["trough_year"]
    assert g["carry"][0] == pytest.approx(G.carry_price(100, 0.05, 0.02, 0.1, 1))
    assert g["conv"][0] == pytest.approx(G.implied_convenience(134, 107, 0.05, 0.02, 0.5))
    assert g["roll"][0] == pytest.approx(G.roll_yield(134, 107, 6))


# ---------------------------------------------------------------- the labs, on synthetic data with known answers
def test_indicators_match_definitions():
    x = np.linspace(100, 200, 60)
    assert labs.sma(x, 10)[-1] == pytest.approx(x[-10:].mean())
    up = np.cumsum(np.ones(40)) + 100
    assert labs.rsi(up, 14)[-1] == pytest.approx(100.0)
    e = labs.ema(np.full(50, 7.0), 12)
    assert e[-1] == pytest.approx(7.0)
    dd = labs.drawdown(np.array([1.0, 2.0, 1.0, 3.0]))
    assert list(dd) == pytest.approx([0, 0, -0.5, 0])


def test_multiple_testing_corrections():
    p = [0.01, 0.04, 0.03, 0.2]
    assert labs.holm(p) == pytest.approx([0.04, 0.09, 0.09, 0.2])
    assert labs.bh(p) == pytest.approx([0.04, 0.16 / 3, 0.16 / 3, 0.2])


def test_working_null_and_variance_ratio():
    assert labs.working_vr(2) == pytest.approx(1.25)
    rng = np.random.default_rng(1)
    r = rng.normal(0, 1, 6000)
    v = labs.variance_ratio(r, 4)
    assert abs(v["vr"] - 1) < 0.08 and v["p"] > 0.01


def test_garch_recovers_a_simulated_process():
    rng = np.random.default_rng(4)
    w, a, b = 1e-5, 0.08, 0.9
    n = 6000
    e = np.zeros(n)
    s2 = w / (1 - a - b)
    for t in range(n):
        e[t] = math.sqrt(s2) * rng.standard_normal()
        s2 = w + a * e[t] ** 2 + b * s2
    g = labs.garch11(e)
    assert g["alpha"] == pytest.approx(a, abs=0.03) and g["beta"] == pytest.approx(b, abs=0.04)


def test_markov_switching_finds_two_planted_regimes():
    rng = np.random.default_rng(8)
    st, x = 0, []
    for _ in range(1500):
        st = st if rng.random() < (0.97 if st == 0 else 0.9) else 1 - st
        x.append(rng.normal(0.01, 0.02) if st == 0 else rng.normal(-0.02, 0.07))
    m = labs.markov_switching(np.array(x))
    sd = sorted(m["sd"])
    assert sd[0] == pytest.approx(0.02, abs=0.006) and sd[1] == pytest.approx(0.07, abs=0.015)


def test_cointegration_detects_a_planted_pair():
    rng = np.random.default_rng(2)
    x = np.cumsum(rng.normal(0, 1, 1500))
    y = 2 + 1.5 * x + rng.normal(0, 1, 1500)
    z = np.cumsum(rng.normal(0, 1, 1500))
    assert labs.engle_granger(y, x, sims=200)["p"] < 0.05
    assert labs.engle_granger(z, x, sims=200)["p"] > 0.05


# ---------------------------------------------------------------- the page
def test_page_ships_the_mind_labs_and_code():
    page = (ROOT / "site" / "page.html").read_text()
    for id_ in ("view-mind", "view-labs", "view-cardroom", "view-code", "view-agents", "hero-mind", "mind-hero-cv", "md-cv"):
        assert f'id="{id_}"' in page, id_
    assert "const SNAP14 =" in page and "def think(self" in page        # the engine's own source is in the code appendix
    assert "DATABENTO_API_KEY=" not in page


def test_mcp_tools_reason_and_compute_without_executing():
    from buildout import mcp_server as MS
    c = MS.Context()
    r = MS.reason(c, {"question": "Should I buy long bonds?"})
    assert r["found"] and r["decision"]["executed"] is False and "never" in r["note"].lower()
    assert MS.labs_lookup(c, {"part": "multiple_testing"})["result"]["n"] >= 30
    assert MS.game_math(c, {"kind": "kelly", "args": {"p": 0.55, "b": 1}})["fraction"] == pytest.approx(0.1)
    for bad in ({"kind": "equity", "args": {"hand": ["As"]}}, {"kind": "nope"}, {"kind": "kelly", "args": {"p": "x"}}):
        with pytest.raises(MS.ToolError):
            MS.game_math(c, bad)
    with pytest.raises(MS.ToolError):
        MS.reason(c, {"question": ""})


def test_page_states_the_mind_counts_it_ships():
    page = (ROOT / "site" / "page.html").read_text()
    snap = json.loads(MIND_JSON.read_text())
    n = len(snap["nodes"])
    concepts = sum(1 for x in snap["nodes"] if x["k"] == "concept")
    assert f"{n:,} nodes" in page and f"{concepts} concepts" in page
    assert abs(len(snap["edges"]) - 5600) < 300 and "5,600 typed links" in page
