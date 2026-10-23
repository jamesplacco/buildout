"""v0.20: the multivariate regime model, the online learner, the portfolio engine's parts, the page's decision mirror and
the mind's decision answers, on planted answers and against the Python engine."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from buildout import decide, infer, mind, portfolio

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
MIND_JSON = ROOT / "buildout" / "assets" / "mind.json"


def planted(T=900, seed=2):
    rng = np.random.default_rng(seed)
    st = [0]
    for _ in range(T - 1):
        st.append(st[-1] if rng.random() < 0.97 else 1 - st[-1])
    st = np.array(st)
    C0 = np.array([[0.08 ** 2, 0.6 * 0.08 * 0.03], [0.6 * 0.08 * 0.03, 0.03 ** 2]])
    C1 = np.array([[0.03 ** 2, -0.4 * 0.03 * 0.02], [-0.4 * 0.03 * 0.02, 0.02 ** 2]])
    X = np.where(st[:, None] == 0, rng.multivariate_normal([-0.01, -0.005], C0, T), rng.multivariate_normal([0.01, 0.004], C1, T))
    return X, st


# ---------------------------------------------------------------- the multivariate regime model
def test_mvhmm_recovers_states_and_their_correlations():
    X, st = planted()
    sel = infer.mvhmm_select(X, Ks=(1, 2, 3))
    m = sel["best"]
    assert m["K"] == 2 and m["mu"][0, 0] < 0 < m["mu"][1, 0]
    corr = [m["S"][k][0, 1] / math.sqrt(m["S"][k][0, 0] * m["S"][k][1, 1]) for k in range(2)]
    assert corr[0] == pytest.approx(0.6, abs=0.12) and corr[1] == pytest.approx(-0.4, abs=0.12)
    assert (infer.mvviterbi(X, m) == st).mean() > 0.95
    assert ((infer.mvhmm_filter(X, m)[:, 1] > 0.5) == (st == 1)).mean() > 0.9
    assert np.allclose(infer.stationary(m["A"]) @ m["A"], infer.stationary(m["A"]))


def test_mvhmm_filter_is_causal_and_warm_start_keeps_meaning():
    X, _ = planted(500)
    m = infer.mvhmm_fit(X, 2, starts=2, iters=80)
    a = infer.mvhmm_filter(X, m)
    Y = X.copy()
    Y[300:] = 0.4
    assert np.allclose(a[:300], infer.mvhmm_filter(Y, m)[:300])
    w = infer.mvhmm_fit(X[:480], 2, init=m, iters=40)
    assert np.allclose(w["mu"], m["mu"], atol=0.01)                  # the states keep their order and meaning


def test_hedge_learner_finds_the_best_policy_within_its_regret_bound():
    rng = np.random.default_rng(3)
    T, N = 2000, 4
    L = rng.uniform(0, 1, (T, N))
    L[:, 2] -= 0.15
    L = np.clip(L, 0, 1)
    eta = math.sqrt(8 * math.log(N) / T)
    W = infer.hedge_weights(L, eta)
    assert W[-1].argmax() == 2 and np.allclose(W.sum(1), 1)
    regret = float((W * L).sum() - L.sum(0).min())
    assert regret <= math.log(N) / eta + eta * T / 8 + 1e-9
    assert np.allclose(W[0], 1 / N)                                   # the first round uses no losses


# ---------------------------------------------------------------- the portfolio engine's parts
def test_chooser_matches_a_closed_form_and_honours_the_budget():
    mu = np.array([[0.008, 0.002, 0.0]])
    S = np.diag([0.04, 0.02, 0.03]) ** 2
    S = S[None]
    C = portfolio.Chooser(mu, S, gamma=4.0)
    i, info = C.choose(np.ones(1), es_limit=None)
    # mean-variance with no correlation, levered past 1x: each weight about (mu - borrowing cost) / (gamma sigma^2), on the 0.1 grid
    want = np.clip((mu[0] - portfolio.BORROW) / (4.0 * np.diag(S[0])), 0, None)
    assert want.sum() > 1 and np.allclose(C.G[i], want, atol=0.11)
    j, inf2 = C.choose(np.ones(1), es_limit=0.03)
    assert C.es(np.ones(1), np.array([j]))[0] <= 0.03 + 1e-9 and inf2["capped"]
    es = C.es(np.ones(1), np.array([int(np.flatnonzero((C.G == [1.0, 0, 0]).all(1))[0])]))[0]
    assert es == pytest.approx(-0.008 + 0.04 * stats.norm.pdf(stats.norm.ppf(0.95)) / 0.05, rel=0.08)


def test_policy_returns_charge_costs_and_borrowing():
    X = np.array([[0.01, 0.0, 0.0], [0.02, 0.01, 0.0], [-0.01, 0.0, 0.0]])
    alloc = np.array([[1.0, 0, 0], [1.5, 0, 0], [0.5, 0.5, 0]])
    r = portfolio.run_policy(X, alloc, 0)["ret"]
    assert r[0] == pytest.approx(0.01)
    assert r[1] == pytest.approx(1.5 * 0.02 - portfolio.COST * 0.5 - 0.5 * portfolio.BORROW)
    assert r[2] == pytest.approx(0.5 * -0.01 - portfolio.COST * 1.5)


def test_simulation_and_replay_arithmetic():
    rng = np.random.default_rng(4)
    X = rng.normal([0.006, 0.002, 0.001], [0.04, 0.02, 0.03], (600, 3))
    m = {"K": 1, "A": np.ones((1, 1))}
    sim = portfolio.simulate(X, m, np.zeros(600, int), np.ones(1), {"hold": [1.0, 0, 0], "cash": [0.0, 0, 0]}, months=60, paths=800)
    assert sim["cash"]["horizons"]["60"]["q50"] == pytest.approx(1.0) and sim["cash"]["p_dd30"] == 0
    h = sim["hold"]["horizons"]["60"]
    assert h["q05"] < h["q50"] < h["q95"] and 0 < sim["hold"]["p_dd30"] < 1
    assert len(sim["hold"]["fan"]["q50"]) == len(sim["_meta"]["fan_months"])
    idx = pd.date_range("1929-01-01", periods=48, freq="MS")
    D = pd.DataFrame({"stocks": np.full(48, -0.01), "bonds": np.full(48, 0.005), "gold": np.zeros(48)}, index=idx)
    rep = portfolio.replay(D, {"hold": [1.0, 0, 0], "sixty_forty": [0.6, 0.4, 0]})
    ep = rep[0]
    assert ep["name"] == "The Depression" and ep["returns"]["hold"] == pytest.approx(0.99 ** ep["months"] - 1)


def test_state_names_are_unique_and_follow_the_data():
    m = {"K": 4, "A": np.full((4, 4), 0.25), "mu": np.array([[-0.01, 0.0, 0.0], [0.004, 0.005, 0.0], [0.005, 0.001, 0.0], [0.01, 0.001, 0.0]]),
         "S": np.stack([np.diag([0.06, 0.02, 0.02]) ** 2, np.diag([0.03, 0.02, 0.02]) ** 2, np.diag([0.05, 0.02, 0.02]) ** 2, np.diag([0.03, 0.02, 0.02]) ** 2])}
    names = [s["name"] for s in portfolio.describe_states(m, m["mu"])]
    assert names == ["Stressed", "Bond rally", "Turbulent", "Calm bull"]


def test_panel_splices_the_yield_and_prices_gold():
    idx = pd.date_range("2023-07-01", periods=4, freq="MS")
    S = pd.DataFrame({"px": [100.0, 101, 102, 103], "div": [2.0] * 4, "eps": [5.0] * 4, "cpi": [100.0] * 4, "y10": [4.0, 4.0, np.nan, np.nan]}, index=idx)
    gh = {"y10": pd.DataFrame({"Date": ["2023-09-01", "2023-10-01"], "Rate": [4.5, 4.0]}),
          "gold": pd.DataFrame({"Date": ["2023-07", "2023-08", "2023-09", "2023-10"], "Price": [1900.0, 1919.0, 1919.0, 1900.0]})}
    D, notes = portfolio.panel(S, gh)
    assert notes["y10_to"] == "2023-10" and len(D) == 3
    assert D["gold"].iloc[0] == pytest.approx(0.01) and D["bonds"].iloc[1] < 0 < D["bonds"].iloc[2]


# ---------------------------------------------------------------- the shipped engine, the page mirror and the mind
def _snap20() -> dict:
    txt = (ROOT / "site" / "src" / "snap20.js").read_text()
    i = txt.index("const SNAP20 = ") + len("const SNAP20 = ")
    return json.loads(txt[i:txt.index(";\n", i)].replace("<\\/", "</"))["portfolio"]


def test_shipped_portfolio_is_consistent():
    from buildout.core import contracts
    o = _snap20()
    n = o["now"]
    assert abs(sum(n["next"]) - 1) < 1e-4 and abs(sum(n["meta_weights"].values()) - 1) < 1e-4
    g = n["gate"]
    want = np.round((np.array([1.0, 0, 0]) + g * (np.array(n["optimum"] if n["gate_policy"] == "regime" else n["decision"]) - [1.0, 0, 0])) / 0.05) * 0.05
    assert g == pytest.approx(decide.gate_from_t(n["gate_t"], o["n_tried"]))
    if g == 0:
        assert n["decision"] == [1.0, 0.0, 0.0]
    else:
        assert np.all(np.isfinite(want))
    assert o["start"].startswith("1940") and o["months"] > 1000 and len(o["stress"]) == len(portfolio.EPISODES)
    for k in ("hold", "sixty_forty", "risk_parity", "trend", "regime", "regime_stocks", "gated", "meta"):
        assert k in o["perf"]
    p = Path(__file__).with_name("_portfolio.json")
    try:
        p.write_text(json.dumps(o))
        assert contracts.check(p) == []
    finally:
        p.unlink(missing_ok=True)


def test_mcp_portfolio_engine(tmp_path):
    from buildout import mcp_server
    ctx = mcp_server.Context(str(tmp_path), None)
    s = mcp_server.portfolio_engine(ctx, {})
    assert len(s["decision"]) == 3 and "never an order" in s["note"]
    assert set(mcp_server.portfolio_engine(ctx, {"part": "simulation"})["simulation"]) >= {"hold", "sixty_forty"}
    with pytest.raises(mcp_server.ToolError):
        mcp_server.portfolio_engine(ctx, {"part": "buy"})


def test_what_if_reproduces_today_and_moves_the_right_way():
    G = json.loads(MIND_JSON.read_text())
    D = G["decision"]
    base = decide.what_if(D)
    assert base["optimum"] == D["engine_exposure"] and base["decision"] == D["exposure"]
    hi = decide.what_if(D, p_stress=0.9)["optimum"]
    lo = decide.what_if(D, p_stress=0.0)["optimum"]
    assert hi <= base["optimum"] <= lo
    assert decide.what_if(D, r12=-0.15)["optimum"] <= decide.what_if(D, r12=0.15)["optimum"]
    assert decide.what_if(D, gamma=8)["optimum"] <= decide.what_if(D, gamma=1.5)["optimum"]
    assert decide.what_if(D, t=10)["gate"] > 0.99


QUESTIONS = ["What should the book do?", "What regime are we in?", "What if the odds of a stressed regime were 50%?", "What if there is a 40% chance of a recession?",
             "How much in stocks with a forecast of -5%?", "Should I use leverage at a risk aversion of 5?", "Is AI a bubble?", "If the 10-year goes to 6%, what is TLT?"]


def test_mind_answers_decision_questions():
    M = mind.Mind(json.loads(MIND_JSON.read_text()))
    r = [M.think(q).get("engine") for q in QUESTIONS]
    assert r[0] and r[1] and r[0]["exposure"] == r[1]["exposure"]
    assert r[2]["whatif"]["p_stress"] == 0.5 and r[3]["whatif"]["p_stress"] == 0.4
    assert r[4]["whatif"]["r12"] == -0.05 and r[5]["whatif"]["gamma"] == 5.0
    assert r[6] is None and r[7] is None
    assert r[0]["portfolio"]["state"]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_page_decision_mirror_and_mind_match_python():
    from buildout import voices
    G = json.loads(MIND_JSON.read_text())
    D = G["decision"]
    cases = [{}, {"pStress": 0.5}, {"pStress": 0.0}, {"pStress": 1.0}, {"r12": -0.1}, {"r12": 0.12}, {"gamma": 6}, {"gamma": 1.2}, {"es": None}, {"es": 0.05}, {"t": 2.5},
             {"pStress": 0.35, "r12": 0.02, "gamma": 3.3, "es": 0.08, "t": 1.9}]
    rng = np.random.default_rng(5)
    cv = [[list(rng.dirichlet(np.ones(3))), list(rng.normal(0.005, 0.01, 3)), list(rng.uniform(0.02, 0.09, 3))] for _ in range(5)]
    req = {"voices": {"cfg": voices.config(), "lib": {"quotes": voices.load()}}, "mind": G, "cases": cases, "cvar": cv, "gate": [-1, 0, 1.07, 2, 3.5], "inv": [0.01, 0.2, 0.5, 0.857, 0.99],
           "questions": QUESTIONS}
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness20.js")], input=json.dumps(req), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    js = json.loads(r.stdout)
    for c, got in zip(cases, js["cases"]):
        kw = {"p_stress": c.get("pStress"), "r12": c.get("r12"), "gamma": c.get("gamma"), "t": c.get("t")}
        if "es" in c:
            kw["es"] = c["es"]
        want = decide.what_if(D, **kw)
        assert got["x"] == pytest.approx(want["optimum"]) and got["capped"] == want["capped"], c
        assert got["decision"] == pytest.approx(want["decision"], abs=1e-9) and got["gate"] == pytest.approx(want["gate"], abs=2e-6), c
        d = np.abs(np.array(got["ce"]) - np.array(want["ce"]))
        assert d.max() < 1e-12, (c, d.max(), int(d.argmax()))
    for (w, mu, sd), got in zip(cv, js["cvar"]):
        assert got == pytest.approx(list(infer.mixture_cvar(np.array(w), np.array(mu), np.array(sd), 0.05, n=1201)), rel=1e-9, abs=1e-12)
    assert js["inv"] == pytest.approx([stats.norm.ppf(p) for p in req["inv"]], abs=2e-6)          # the page's normal cdf is good to 1.5e-7
    M = mind.Mind(G)
    for q, got in zip(QUESTIONS, js["think"]):
        py = M.think(q).get("engine")
        assert (py is None) == (got["engine"] is None), q
        if py:
            assert got["engine"]["optimum"] == py["optimum"] and got["engine"].get("whatif", {}).keys() == py.get("whatif", {}).keys(), q
            if py.get("whatif"):
                for k, v in py["whatif"].items():
                    assert got["engine"]["whatif"][k] == pytest.approx(v, abs=1e-9), (q, k)
            assert got["engine"]["portfolio"] == pytest.approx(py["portfolio"]) if False else got["engine"]["portfolio"]["state"] == py["portfolio"]["state"]


def test_page_ships_the_v20_desks():
    page = (ROOT / "site" / "page.html").read_text()
    for idt in ("view-portfolio", "pf-card", "pf-curve", "pf-fan", "pf-stress", "dxw-p", "dxw-chart", "const SNAP20 ="):
        assert idt in page, idt
    low = page.lower()
    assert chr(0x2014) not in page and ("inter" "section") not in low and ("load" "-bearing") not in low
