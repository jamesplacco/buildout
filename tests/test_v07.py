"""v0.7: the review's regression cases, the policy contract, the reasoner, game theory, fill quality and the
calculator, each checked in Python and against the page's JavaScript (site/src/engine7.js)."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import games as G
from buildout import microstructure as MS
from buildout import policy as P
from buildout import reasoner as R
from buildout.analytics import backtest, metrics, risk

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


def _js(cases):
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness7.js")], input=json.dumps(cases), capture_output=True,
                       text=True, check=True)
    return json.loads(r.stdout)


def close(a, b, tol=1e-9):
    if isinstance(a, dict):
        return all(close(a[k], b[k], tol) for k in a if k in b)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return a is None and b is None
        if b == "Infinity":
            return math.isinf(a)
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)))
    return a == b


# ---------------------------------------------------------------- the review's two regression cases
def test_returns_reconcile_to_nav_with_costs():
    """101 flat dates, alternating 100% asset and cash, 2bp costs: NAV 0.9799987 and the returns say the same."""
    idx = pd.bdate_range("2020-01-01", periods=101)
    res = backtest.run(pd.DataFrame({"A": 0.0}, index=idx), pd.DataFrame({"A": [1.0 - (i % 2) for i in range(101)]}, index=idx),
                       cost_bps=2, cash_rate=0.0, borrow_spread_bps=0)
    assert abs(res.equity.iloc[-1] - 0.9799987) < 1e-7
    assert abs((1 + res.returns).prod() - res.equity.iloc[-1]) < 1e-12
    st = metrics.perf(res.returns)
    assert st["cagr"] < 0 and abs(st["final_equity"] - res.equity.iloc[-1]) < 1e-12


def test_borrowing_costs_reconcile_too():
    idx = pd.bdate_range("2020-01-01", periods=60)
    res = backtest.run(pd.DataFrame({"A": 0.0}, index=idx), pd.DataFrame({"A": 1.5}, index=idx), cost_bps=0, cash_rate=0.04,
                       borrow_spread_bps=100)
    assert res.equity.iloc[-1] < 1 and abs((1 + res.returns).prod() - res.equity.iloc[-1]) < 1e-12
    assert abs(res.financing.sum() - (res.equity.iloc[-1] - 1)) < 1e-4


def test_next_session_execution_lags_the_fill():
    idx = pd.bdate_range("2020-01-01", periods=5)
    R_ = pd.DataFrame({"A": [0.0, 0.10, 0.0, 0.0, 0.0]}, index=idx)
    T = pd.DataFrame({"A": [1.0, 1.0, 1.0, 1.0, 1.0]}, index=idx)
    same = backtest.run(R_, T, cost_bps=0)
    nxt = backtest.run(R_, T, cost_bps=0, exec_lag=1)
    assert abs(same.equity.iloc[-1] - 1.10) < 1e-12 and abs(nxt.equity.iloc[-1] - 1.0) < 1e-12


def test_sharpe_is_excess_over_cash():
    idx = pd.bdate_range("2020-01-01", periods=500)
    r = pd.Series(0.04 / 252, index=idx)                     # earns exactly cash
    assert abs(metrics.perf(r + 1e-9 * np.sin(np.arange(500)), rf=pd.Series(0.04, index=idx))["sharpe"]) < 0.5


def test_false_diversification_is_named_correctly():
    S = pd.DataFrame([[0.04, 0.04], [0.04, 0.04]], index=["a", "b"], columns=["a", "b"])
    w = pd.Series([0.5, 0.5], index=["a", "b"])
    rc = risk.risk_contributions(w, S / 252)
    assert abs(risk.effective_risk_contributors(rc["share"]) - 2) < 1e-9          # two positions share the risk
    assert abs(risk.effective_independent_bets(w, S) - 1) < 1e-9                 # but it is one bet
    assert abs(risk.diversification_ratio(w, S) - 1) < 1e-9


# ---------------------------------------------------------------- the policy contract
CORR_PATH = [0.2, 0.05, -0.05, -0.10, -0.05, 0.0, 0.01, -0.2, 0.15, 0.10, 0.05, -0.01, None, -0.3]


def test_hedge_state_hysteresis_and_boundaries():
    st = P.hedge_state(CORR_PATH)
    assert st[:4] == ["amplifying", "amplifying", "neutral", "hedging"]            # -0.10 exactly enters
    assert st[4:7] == ["hedging", "hedging", "neutral"]                            # 0.0 stays, 0.01 leaves
    assert st[12] is None and st[13] == "hedging"


def test_tlt_decision_gates_and_missing_inputs():
    on = P.tlt_decision("hedging", 0.030, 0.0425, "ok", 0.55)
    assert on["on"] and on["ratio"] == 0.55
    assert P.tlt_decision("hedging", 0.0425, 0.0425, "ok", 0.55)["on"] is False     # at the line is above it
    assert P.tlt_decision("neutral", 0.02, 0.0425, "ok", 0.55)["ratio"] == 0.0
    miss = P.tlt_decision("hedging", None, 0.0425, "ok", 0.55)
    assert miss["status"] == "unavailable" and miss["on"] is None and miss["blocked"]
    assert P.tlt_decision(None, 0.02, 0.0425)["status"] == "unavailable"
    assert P.tlt_decision("hedging", 0.05, None, "no_reliable_threshold", 2.0)["ratio"] == 1.0


def test_policy_series_matches_the_decision_day_by_day():
    idx = pd.bdate_range("2021-01-01", periods=len(CORR_PATH))
    corr = pd.Series([np.nan if c is None else c for c in CORR_PATH], index=idx)
    mv = pd.Series(0.4, index=idx)
    infl = pd.Series(np.linspace(0.02, 0.05, len(idx)), index=idx)
    ser = P.tlt_ratio_series(corr, mv, infl, 0.0425)
    states = P.hedge_state(corr.to_numpy())
    for t, (s, i) in enumerate(zip(states, infl)):
        d = P.tlt_decision(s, float(i), 0.0425, "ok", 0.4)
        if d["status"] == "ok":
            assert ser.iloc[t] == d["ratio"], t


def test_sizing_names_its_binding_constraint():
    d = P.sizing_decision(0.7048, 0.4913, 1.5, 0.0778, 0.28)
    assert d["binding"] == "drawdown_cap" and d["scale"] == 0.4913 and d["kelly_check"]["kelly_supports_size"] is False
    assert P.sizing_decision(None, 0.5, 1.5)["status"] == "unavailable"


def test_portfolio_limit_covers_the_bond_leg():
    lim = P.portfolio_limits(1.5, 1.0, 0.03, 2.0, 0.02)
    assert abs(lim["total_gross"] - 2.0) < 1e-12 and lim["scaled_by"] < 1 and set(lim["binding"]) == {"max_total_gross", "max_premium"}


@needs_node
def test_policies_match_the_page():
    cases = [{"fn": "state", "corrs": [None if c is None else c for c in CORR_PATH], "prev": "neutral"},
             {"fn": "tlt", "args": ["hedging", 0.03, 0.0425, "ok", 0.55, 1.0]}, {"fn": "tlt", "args": ["hedging", 0.0425, 0.0425, "ok", 0.55, 1.0]},
             {"fn": "tlt", "args": ["hedging", None, 0.0425, "ok", 0.55, 1.0]}, {"fn": "tlt", "args": ["hedging", 0.05, None, "no_reliable_threshold", 2.0, 1.0]},
             {"fn": "size", "args": [0.7048, 0.4913, 1.5, 0.0778, 0.28, 0.25]}, {"fn": "limits", "args": [1.5, 1.0, 0.03, 2.0, 0.02]}]
    got = _js(cases)
    assert got[0] == P.hedge_state(CORR_PATH, "neutral")
    for c, g in zip(cases[1:5], got[1:5]):
        assert close(P.tlt_decision(*c["args"]), g)
    assert close(P.sizing_decision(*cases[5]["args"]), got[5])
    assert close(P.portfolio_limits(*cases[6]["args"]), got[6])


# ---------------------------------------------------------------- one effective fundamentals dataset
@needs_node
def test_a_newer_filing_updates_row_coverage_and_date_together():
    rows = [{"t": "ORCL", "quarter_end": "2026-08-31", "ocf": 46.94, "capex": 75.66, "cash": 36.4, "debt": 125.3, "op_income": 20.6, "interest": 5.1}]
    live = {"ORCL": {"quarter_end": "2026-11-30", "ocf": 90.0, "capex": 70.0, "cash": 50.0}}
    stale = {"ORCL": {"quarter_end": "2026-05-31", "ocf": 1.0, "capex": 99.0}}
    new, old = _js([{"fn": "fund", "rows": rows, "live": live}, {"fn": "fund", "rows": rows, "live": stale}])
    r = new[0]
    assert r["quarter_end"] == "2026-11-30" and r["coverage"] == "self_funded" and r["fcf"] == 20.0 and r["src"]["ocf"] == "filing 2026-11-30"
    assert r["src"]["debt"] == "filings to 2026-08-31" and abs(r["net_cash"] - (50.0 - 125.3)) < 1e-9
    assert old[0]["coverage"] == "funding_gap" and old[0]["quarter_end"] == "2026-08-31"   # an older filing never wins


# ---------------------------------------------------------------- the reasoner
OBS = {"infl": True, "corr": True, "oil": True, "vix": False, "hy": False, "capex": True, "curve": False}


def test_posterior_tempers_shared_drivers():
    pri = [s["prior"] for s in R.SCENARIOS]
    one = R.posterior(pri, R.SIGNALS, {"infl": True})["posterior"]
    two = R.posterior(pri, R.SIGNALS, {"infl": True, "corr": True})["posterior"]
    naive = np.array(pri) * np.array(R.SIGNALS[0]["lik"]) * np.array(R.SIGNALS[1]["lik"])
    naive /= naive.sum()
    i = [s["id"] for s in R.SCENARIOS].index("stagfl")
    assert one[i] < naive[i] and two[i] < naive[i]          # the second reading of one cause does not double-count
    assert abs(sum(two) - 1) < 1e-12
    assert R.posterior(pri, R.SIGNALS, {k: None for k in OBS})["posterior"] == pytest.approx(list(np.array(pri) / sum(pri)))


def test_solver_respects_every_constraint_and_beats_alternatives():
    pri = [s["prior"] for s in R.SCENARIOS]
    post = R.posterior(pri, R.SIGNALS, OBS)["posterior"]
    alts = R.alternatives(post, R.SCENARIOS, R.DEFAULTS, (1.0, 0.0, 0.0, 0.0))
    opt = alts["optimal"]
    assert opt["feasible"] and opt["worst"] >= -R.DEFAULTS["max_loss"] - 1e-12
    for k in ("reduce", "hedge"):
        if alts[k] and alts[k]["feasible"]:
            assert opt["elog"] >= alts[k]["elog"] - 1e-12
    assert alts["keep"]["feasible"] is False                 # the full book breaks the 15% loss limit in a crash


def test_zero_sum_solver_on_known_games():
    assert G.nash([[1, -1], [-1, 1]], [[-1, 1], [1, -1]])["equilibria"][0]["x"] == pytest.approx([0.5, 0.5])
    z = R.zero_sum([[0, -1, 1], [1, 0, -1], [-1, 1, 0]])
    assert z["row"] == pytest.approx([1 / 3] * 3) and z["col"] == pytest.approx([1 / 3] * 3) and abs(z["value"]) < 1e-12
    z = R.zero_sum([[3, 0], [5, 1]])
    assert z["row"] == pytest.approx([0, 1]) and z["col"] == pytest.approx([0, 1]) and abs(z["value"] - 1) < 1e-12


def test_reverse_stress_lands_exactly_on_the_loss():
    S = np.array([[0.04, 0.01], [0.01, 0.09]])
    b = [1.0, 0.5]
    rv = R.reverse_stress(b, S, 0.2)
    assert abs(np.dot(b, rv["shock"]) + 0.2) < 1e-12
    # it is the closest such point: any other point on the plane is farther in Mahalanobis distance
    Si = np.linalg.inv(S)
    alt = np.array(rv["shock"]) + np.array([0.5, -1.0]) * 0.01
    alt = alt - (np.dot(b, alt) + 0.2) / np.dot(b, b) * np.array(b)
    assert np.array(rv["shock"]) @ Si @ np.array(rv["shock"]) <= alt @ Si @ alt + 1e-15


@needs_node
def test_reasoner_matches_the_page():
    cov = [[0.012, 0, 1e-4, 0.007, -1e-3], [0, 0.0156, 0, 0, 0], [1e-4, 0, 4e-5, 6e-4, -1e-4], [0.007, 0, 6e-4, 0.094, 0.004], [-1e-3, 0, -1e-4, 0.004, 0.011]]
    [g] = _js([{"fn": "reason", "obs": OBS, "current": [1.0, 0.0, 0.0, 0.0], "voi": True, "cov": cov}])
    pri = [s["prior"] for s in R.SCENARIOS]
    post = R.posterior(pri, R.SIGNALS, OBS)["posterior"]
    assert close(post, g["post"], 1e-12)
    assert close(R.put_spread_cost(R.DEFAULTS["vix"]), g["cost"], 1e-10)
    alts = R.alternatives(post, R.SCENARIOS, R.DEFAULTS, (1.0, 0.0, 0.0, 0.0))
    for k in ("keep", "reduce", "hedge", "optimal"):
        assert g["alts"][k]["port"] == alts[k]["port"], k
        assert close(alts[k]["rets"], g["alts"][k]["rets"], 1e-10)
    assert g["alts"]["minimax_regret"] == alts["minimax_regret"]
    rb = R.robust(alts, post)
    assert close(rb["mix"], g["robust"]["mix"], 1e-9) and close(rb["value"], g["robust"]["value"], 1e-9)
    voi = R.value_of_info(pri, R.SIGNALS, OBS, R.SCENARIOS, R.DEFAULTS)
    assert close(voi["evpi_bp"], g["voi"]["evpi_bp"], 1e-6)
    js = {r["id"]: r for r in g["voi"]["signals"]}
    for r in voi["signals"]:
        assert close(r["evsi_bp"], js[r["id"]]["evsi_bp"], 1e-6) and r["flip_changes_choice"] == js[r["id"]]["flip_changes_choice"]
    rv = R.reverse_stress(R.exposure_vector((1.0, 0.0, 0.0, 0.0), R.DEFAULTS), cov, R.DEFAULTS["max_loss"])
    assert close(rv["shock"], g["rev"]["shock"], 1e-10) and close(rv["sigmas"], g["rev"]["sigmas"], 1e-10)


# ---------------------------------------------------------------- game theory
def test_capex_race_is_a_prisoners_dilemma_with_the_textbook_numbers():
    q = [115.9, 132.4, 173.0, 89.3, 75.7]
    c = [1 / 6 + .09, 1 / 6 + .09, 1 / 5 + .09, 1 / 5.5 + .09, 1 / 5 + .11]
    g = G.capex_game(q, c, 0.40)
    assert abs(g["nash"]["Q"] - sum(q)) < 1e-9 and abs(g["nash"]["P"] - 0.40) < 1e-12       # calibration reproduces the build
    d = G.capex_dilemma(g["calibration"]["a"], g["calibration"]["b"], float(np.mean(c)), 5)
    assert d["race_dominant"] and abs(d["cost_of_racing"] - 4 / 9) < 1e-12
    eq = d["duopoly"]["analysis"]["equilibria"]
    assert len(eq) == 1 and eq[0]["x"] == [0.0, 1.0] and abs(d["duopoly"]["analysis"]["price_of_anarchy"] - 9 / 8) < 1e-12


def test_cournot_drops_firms_that_cannot_compete():
    r = G.cournot(1.0, 0.01, [0.2, 0.2, 0.95])
    assert r["q"][2] == 0 and 2 not in r["active"] and r["P"] > 0.2


def test_chicken_has_three_equilibria():
    eqs = G.nash([[0, 7], [2, 6]], [[0, 2], [7, 6]])["equilibria"]
    assert len(eqs) == 3 and sum(e["pure"] for e in eqs) == 2


def test_crowded_exit_threshold_and_laplace_limit():
    r = G.crowded_exit(0.03, 0.003, 0.01, 1e6, 0.01)          # diffuse public information: the Laplace limit
    assert abs(r["x_star"] - (0.03 / 2 - 0.003)) < 1e-9 and r["unique"]
    loud = G.crowded_exit(0.03, 0.003, 0.01, 0.002, 0.03)      # precise public news, noisy private views: multiplicity
    assert loud["unique"] is False


def test_ladder_flags_incoherence_and_fee_aware_arbitrage():
    rows = [{"k": 3.0, "bid": .62, "ask": .64}, {"k": 3.25, "bid": .40, "ask": .43}, {"k": 3.5, "bid": .47, "ask": .49}, {"k": 3.75, "bid": .10, "ask": .12}]
    out = G.ladder(rows)
    assert out["violations"] and out["arbitrage"] and out["arbitrage"][0]["buy"] == 3.25 and out["arbitrage"][0]["sell"] == 3.5
    assert all(a >= b - 1e-12 for a, b in zip(out["coherent_fit"], out["coherent_fit"][1:]))
    assert abs(sum(b["p"] for b in out["pmf"]) - 1) < 1e-12
    assert G.kalshi_fee(0.5, 100) == 1.75 and G.kalshi_fee(0.01, 1) == 0.01


@needs_node
def test_games_match_the_page():
    q = [115.9, 132.4, 173.0, 89.3, 75.7]
    c = [1 / 6 + .09, 1 / 6 + .09, 1 / 5 + .09, 1 / 5.5 + .09, 1 / 5 + .11]
    games = [([[3, 0], [5, 1]], [[3, 5], [0, 1]]), ([[0, 7], [2, 6]], [[0, 2], [7, 6]]), ([[4, 0], [3, 3]], [[4, 3], [0, 3]]),
             ([[1, -1], [-1, 1]], [[-1, 1], [1, -1]]), ([[0, -1, 1], [1, 0, -1], [-1, 1, 0]], [[0, 1, -1], [-1, 0, 1], [1, -1, 0]])]
    ladder = [{"k": 3.0, "bid": .62, "ask": .64}, {"k": 3.25, "bid": .40, "ask": .43}, {"k": 3.5, "bid": .47, "ask": .49}, {"k": 3.75, "bid": .10, "ask": .12}]
    cases = [{"fn": "nash", "A": A, "B": B} for A, B in games] + [
        {"fn": "capex", "q": q, "c": c, "p": 0.40}, {"fn": "exit", "args": [0.03, 0.003, 0.01, 0.02, 0.01, None]},
        {"fn": "exit", "args": [0.03, 0.003, 0.01, 0.002, 0.03, 0.0]}, {"fn": "kyle", "args": [8.0, 1000.0]},
        {"fn": "ladder", "rows": ladder, "contracts": 100}, {"fn": "fee", "ps": [0.01, 0.2, 0.5, 0.77, 0.99], "n": 100},
        {"fn": "zerosum", "M": [[0.1, -0.2, 0.05], [-0.1, 0.3, 0.0], [0.02, 0.01, -0.03]]}]
    got = _js(cases)
    for (A, B), g in zip(games, got[:5]):
        py = G.nash(A, B)
        assert len(py["equilibria"]) == len(g["equilibria"])
        for e in py["equilibria"]:
            assert any(close(e["x"], h["x"], 1e-9) and close(e["y"], h["y"], 1e-9) for h in g["equilibria"])
        assert py["dominated_rows"] == g["dominated_rows"] and py["dominated_cols"] == g["dominated_cols"]
        assert [list(p) for p in py["pareto"]] == g["pareto"]
    cg = G.capex_game(q, c, 0.40)
    assert close(cg["nash"]["q"], got[5]["game"]["nash"]["q"], 1e-10) and close(cg["overbuild"], got[5]["game"]["overbuild"], 1e-12)
    assert close(cg["entrant_cut"], got[5]["game"]["entrant_cut"], 1e-10)
    d = G.capex_dilemma(cg["calibration"]["a"], cg["calibration"]["b"], float(np.mean(c)), 5)
    assert close(d["A"], got[5]["dilemma"]["A"], 1e-10) and d["race_dominant"] == got[5]["dilemma"]["race_dominant"]
    for args, g in zip(([0.03, 0.003, 0.01, 0.02, 0.01, None], [0.03, 0.003, 0.01, 0.002, 0.03, 0.0]), got[6:8]):
        py = G.crowded_exit(*args)
        assert close(py["x_star"], g["x_star"], 1e-9) and py["unique"] == g["unique"] and close(py["share_exiting"], g["share_exiting"], 1e-9)
    assert close(G.kyle(8.0, 1000.0), got[8], 1e-12)
    lp = G.ladder(ladder, 100)
    assert close(lp["coherent_fit"], got[9]["coherent_fit"], 1e-12) and len(lp["arbitrage"]) == len(got[9]["arbitrage"])
    assert close([b["p"] for b in lp["pmf"]], [b["p"] for b in got[9]["pmf"]], 1e-12)
    assert [G.kalshi_fee(p, 100) for p in [0.01, 0.2, 0.5, 0.77, 0.99]] == got[10]
    z = R.zero_sum([[0.1, -0.2, 0.05], [-0.1, 0.3, 0.0], [0.02, 0.01, -0.03]])
    assert close(z["row"], got[11]["row"], 1e-10) and close(z["col"], got[11]["col"], 1e-10) and close(z["value"], got[11]["value"], 1e-10)


# ---------------------------------------------------------------- fill quality and the calculator
@needs_node
def test_fill_quality_matches_the_review_example():
    b = MS.book_state(100.00, 100.02, 900, 100)
    assert abs(b["mid"] - 100.01) < 1e-9 and abs(b["imbalance"] - 0.8) < 1e-12 and abs(b["weighted_mid"] - 100.018) < 1e-9
    m = MS.markout(1, 100.00, 100.01, 99.99)
    assert abs(m["edge"] - 0.01) < 1e-9 and abs(m["markout"] + 0.01) < 1e-9
    v = MS.post_value(0.6, 0.004, 0.001, 0.008)
    [g] = _js([{"fn": "book", "b": [100.00, 100.02, 900, 100], "m": [1, 100.00, 100.01, 99.99], "v": [0.6, 0.004, 0.001, 0.008]}])
    assert close(b, g["b"], 1e-12) and close(m, g["m"], 1e-12) and close(v, g["v"], 1e-12)


@needs_node
def test_calculator_is_exact_and_refuses_what_it_cannot_read():
    from buildout.analytics.options import bs
    from scipy.stats import norm
    exprs = ["2+3*4", "2^3^2", "-2^2", "bsput(100, 95, 0.25, 0.22)", "kelly(0.55, 1.2)", "5bn / 3m", "25bp", "x = 3", "x^2 + 2x",
             "10!", "50%", "$vix * 1.1", "npv(0.1, -100, 60, 60)", "irr(-100, 60, 60)", "ninv(0.975)", "foo(1)", "2 +", "import os", "$y10"]
    [g] = _js([{"fn": "calc", "exprs": exprs, "env": {"$vix": 18.0, "$y10": None}}])
    want = [14, 512, -4, bs(100, 95, 0.25, 0, 0, 0.22, "put")["price"], 0.55 - 0.45 / 1.2, 5e9 / 3e6, 0.0025, 3, 15, 3628800, 0.5, 19.8,
            -100 + 60 / 1.1 + 60 / 1.21, None, norm.ppf(0.975)]
    for w, r in zip(want, g):
        if w is not None:
            assert "v" in r and abs(r["v"] - w) <= 1e-9 * max(1, abs(w)), (w, r)
    npv_at = lambda r: -100 + 60 / (1 + r) + 60 / (1 + r) ** 2
    assert abs(npv_at(g[13]["v"])) < 1e-9
    assert all("err" in r for r in g[15:])


def test_daily_reason_file_from_the_other_outputs(tmp_path):
    """python -m buildout reason reads the day's files, observes what it can, and never invents a missing signal."""
    import sys
    sys.path.insert(0, str(ROOT / "site" / "tests"))
    from fixtures import make_fixtures
    folder = make_fixtures(tmp_path)
    out = R.build(folder)
    post = out["posterior"]["posterior"]
    assert abs(sum(post) - 1) < 1e-12 and out["alternatives"]["optimal"]["feasible"]
    assert out["reverse_stress"] and set(out["reverse_stress"]) == {"low_inflation", "inflation"}
    assert all(v in (True, False, None) for v in out["observed"].values())
    empty = R.build(tmp_path / "nothing-here")
    assert all(v is None for v in empty["observed"].values()) and empty["games"]["capex"] is None
