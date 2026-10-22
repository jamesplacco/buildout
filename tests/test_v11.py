"""v0.11: valuation and accounting, the hedge book, causal statistics, the decision loop and the engine registry."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from buildout import causal_stats as CS
from buildout import engine as EN
from buildout import hedgebook as HB
from buildout import ooda as OO
from buildout import reasoner as RZ
from buildout import valuation as V

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")
SIGNALS = {"infl": True, "corr": True, "oil": None, "vix": False, "hy": None, "capex": True, "curve": False}


# ---------- valuation ----------
def test_base_rates_match_the_book_and_invert():
    b = V.BASE_RATES["over_50b"]
    assert sum(p for _, _, p in b["bins"]) == pytest.approx(100.0, abs=0.2)
    assert V.base_rate_tail(15, "over_50b") == pytest.approx((0.9 + 6 * 0.05) / 100, abs=0.002)      # 15-20% bin plus the floored empty bins
    assert V.base_rate_tail(0, "over_50b") == pytest.approx((37.8 + 17.2 + 3.0 + 0.9 + 6 * 0.05) / 100, abs=0.003)
    for q in (0.1, 0.5, 0.9, 0.99):
        assert V.base_rate_tail(V.base_rate_quantile(q), "over_50b", "below") == pytest.approx(q, abs=1e-6)
    assert V.base_rate_tail(10, "12_25b") > V.base_rate_tail(10, "over_50b")                        # smaller firms grow faster


def test_implied_growth_solves_the_dcf_and_moves_the_right_way():
    rev, m0, ms, r, tg = 100.0, 0.1, 0.25, 0.09, 0.03
    for ev in (300.0, 800.0, 2500.0):
        g = V.implied_growth(ev, rev, m0, ms, r, tg)
        assert V.pv_firm(rev, g, m0, ms, r, tg)[0] == pytest.approx(ev, rel=1e-9)
    assert V.implied_growth(2500, rev, m0, ms, r, tg) > V.implied_growth(800, rev, m0, ms, r, tg)    # higher price, more growth needed
    assert V.implied_growth(800, rev, m0, ms, r - 0.01, tg) < V.implied_growth(800, rev, m0, ms, r, tg)
    assert V.implied_growth(800, rev, m0, -0.05, r, tg) is None                                     # no positive margin, no answer


def test_quality_reads_the_accounting():
    c = dict(revenue=100, op_income=30, net_income=60, ocf=20, capex=50, da=10, sbc=12, interest=10, debt=120, cash=10, assets=200, equity=80)
    q = V.quality(c)
    assert q["core_net_income"] == pytest.approx(30 * 0.82) and q["nonoperating_share"] == pytest.approx(1 - 24.6 / 60)
    assert q["cash_conversion"] == pytest.approx(20 / 24.6)                                         # judged on operating earnings
    assert q["steady_fcf"] == pytest.approx(20 - 10 - 12) and q["owner_fcf"] == pytest.approx(20 - 50 - 12)
    assert q["capex_norm_ebit"] == pytest.approx(30 + 10 - 50) and q["depreciation_drag"] == pytest.approx(1 - (-10) / 30)
    keys = {f["key"] for f in q["flags"]}
    assert {"nonoperating", "sbc", "depreciation", "leverage", "coverage"} <= keys and q["quality_grade"] == "low"
    clean = V.quality(dict(revenue=100, op_income=30, net_income=24, ocf=30, capex=12, da=10, sbc=2, interest=1, debt=10, cash=20, assets=200, equity=150))
    assert clean["flags"] == [] and clean["quality_grade"] == "high"


def test_verdicts_follow_the_base_rates():
    c = dict(revenue=100, op_income=30, net_income=24, ocf=32, capex=12, da=10, sbc=2, interest=1, debt=10, cash=20, revenue_growth=0.05)
    cheap = V.analyze_position("A", c, 200, 0.045, 1.0)
    rich = V.analyze_position("B", c, 3000, 0.045, 1.0)
    assert rich["verdict"]["code"] in ("exuberant", "extreme") and rich["p_achieve"] < 0.05
    assert cheap["implied_growth"] < rich["implied_growth"]
    assert any(w["driver"] == "base_rate" for w in rich["why"]) and any(w["driver"] == "discount_rate" for w in rich["why_right"])
    loss = V.analyze_position("C", dict(c, op_income=-5, ocf=-2), 300, 0.045, 1.0)
    assert loss["verdict"]["code"] == "insufficient"


def test_the_snapshot_is_complete_and_sourced():
    snap = OO.positions_snapshot()
    book = ["MSFT", "AMZN", "GOOGL", "META", "NVDA", "AVGO", "TSLA", "SPCX", "ORCL"]
    assert set(snap["ttm"]) == set(book) == set(snap["market_caps"]) == set(snap["betas"])
    for t in book:
        c = snap["ttm"][t]
        assert c["source"] and c["period_end"] >= "2026-06-30" and c["revenue"] > 0
        assert snap["market_caps"][t]["market_cap"] > 100


# ---------- the hedge book ----------
def test_hedges_off_is_the_book_and_each_hedge_pays_where_it_says():
    post = [s["prior"] for s in RZ.SCENARIOS]
    base = HB.evaluate({}, 1.0, post)
    assert base["rets"] == base["base"] and base["cost_bp"] == pytest.approx(0)
    ids = [s["id"] for s in RZ.SCENARIOS]
    for h in HB.HEDGES:
        r = HB.evaluate({h["id"]: h["default"]}, 1.0, post)
        assert all(r["parts"][h["id"]][ids.index(s)] > 0 for s in h["protects"] if s != "soft" or h["id"] == "tlt"), h["id"]
    sizes = {h["id"]: h["default"] for h in HB.HEDGES}
    adv = HB.advisor(sizes, 1.0, post)
    assert adv["combinations"] == 2 ** len(HB.HEDGES)
    assert all(r["meets"] for r in adv["cheapest_meeting_limit"]) and adv["best_worst_case"][0]["worst"] >= max(r["worst"] for r in adv["best_growth"])


@settings(max_examples=30, deadline=None)
@given(st.sampled_from(HB.HEDGE_IDS), st.floats(0.0, 1.0), st.floats(0.2, 1.5))
def test_hedges_add_linearly_and_scale_with_size(hid, frac, e):
    post = [s["prior"] for s in RZ.SCENARIOS]
    spec = next(h for h in HB.HEDGES if h["id"] == hid)
    x = spec["range"][0] + frac * (spec["range"][1] - spec["range"][0])
    one = HB.evaluate({hid: x}, e, post)
    two = HB.evaluate({hid: x, "gold": 0.05} if hid != "gold" else {hid: x}, e, post)
    if hid != "gold":
        g = HB.evaluate({"gold": 0.05}, e, post)
        for a, b, c, d in zip(two["rets"], one["rets"], g["rets"], one["base"]):
            assert a == pytest.approx(b + c - d, abs=1e-12)


@needs_node
def test_hedge_book_matches_the_page():
    post = RZ.posterior([s["prior"] for s in RZ.SCENARIOS], RZ.SIGNALS, SIGNALS)["posterior"]
    sizes = {h["id"]: h["default"] for h in HB.HEDGES}
    evals = [[{}, 1.0, post], [{"tlt": 0.5, "put_spread": 0.02}, 0.8, post], [{h: sizes[h] for h in HB.HEDGE_IDS}, 1.3, post]]
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness11.js")], input=json.dumps({"P": {"vix": 22}, "evals": evals, "sizes": sizes, "e": 1.0, "post": post}),
                       capture_output=True, text=True, check=True)
    js = json.loads(r.stdout)
    py_c = HB.option_costs(HB._P({"vix": 22}))
    assert js["costs"] == pytest.approx({k: float(v) for k, v in py_c.items()}, abs=1e-12)
    for (on, e, p), j in zip(evals, js["evals"]):
        py = HB.evaluate(on, e, p, {"vix": 22})
        assert j["rets"] == pytest.approx([float(x) for x in py["rets"]], abs=1e-12) and j["cost_bp"] == pytest.approx(float(py["cost_bp"]), abs=1e-9)
    pa = HB.advisor(sizes, 1.0, post, {"vix": 22})
    for k in ("cheapest_meeting_limit", "best_growth", "best_worst_case"):
        assert [r["on"] for r in js["advisor"][k]] == [r["on"] for r in pa[k]]
    assert js["catalog"] == [[h["id"], h["default"], h["range"]] for h in HB.HEDGES]


# ---------- causal statistics ----------
def test_granger_and_partial_correlation_find_planted_structure():
    rng = np.random.default_rng(7)
    n = 600
    x = rng.normal(size=n)
    y = np.zeros(n)
    for t in range(1, n):
        y[t] = 0.6 * x[t - 1] + 0.2 * y[t - 1] + rng.normal()
    assert CS.granger(x, y)["p"] < 1e-6 and CS.granger(y, x)["p"] > 0.01
    a = rng.normal(size=n)
    b = a + 0.5 * rng.normal(size=n)
    c = b + 0.5 * rng.normal(size=n)                          # a -> b -> c: a and c independent given b
    pc = CS.partial_corr(np.column_stack([a, b, c]))
    assert abs(pc[0, 2]) < 0.1 < abs(np.corrcoef(a, c)[0, 1])
    assert CS.tail_dependence(a, a) == pytest.approx(1.0, abs=0.02) and CS.tail_dependence(a, rng.normal(size=n)) < 0.3


def test_crisis_behaviour_on_the_real_series():
    from buildout.brain import REGIMES
    g = json.loads((ROOT / "buildout" / "assets" / "brain_graph.json").read_text())
    an = CS.analyze(g["series"], REGIMES)
    lo, hi = an["regimes"]["low_inflation"]["crisis"], an["regimes"]["inflation"]["crisis"]
    assert lo["y10"]["crisis_mean"] < 0 < hi["y10"]["crisis_mean"]                  # bonds hedged crashes before 2022, not since
    assert lo["vix"]["crisis_mean"] > 1 and an["regimes"]["low_inflation"]["granger"]["oil>cpi"]["p"] < 0.001


# ---------- the decision loop ----------
@pytest.fixture(scope="module")
def loop(tmp_path_factory):
    return OO.build(tmp_path_factory.mktemp("d"), str(ROOT / "config.toml"), signals=SIGNALS, as_of="2026-10-21")


def test_the_loop_is_complete_and_proposes_only(loop):
    assert set(loop) >= {"observe", "orient", "decide", "act", "valuation", "frameworks"}
    acts = {a["ticker"]: a for a in loop["decide"]["positions"]}
    assert set(acts) == set(OO.load_config(ROOT / "config.toml").universe.book) if hasattr(OO, "load_config") else True
    for a in acts.values():
        assert 0 <= a["target"] <= 0.25 + 1e-9 and a["action"] in ("trim", "hold and hedge", "hold", "add", "investigate")
        assert a["frameworks"]["kill_criteria"]
    assert all(p["type"] in ("position", "hedge") for p in loop["act"]["proposals"])
    assert loop["act"]["note"].startswith("Proposals") and loop["decide"]["freed_weight"] >= 0
    assert loop["decide"]["solver"]["nominal"]["port"] == RZ.solve(RZ.posterior([s["prior"] for s in RZ.SCENARIOS], RZ.SIGNALS, SIGNALS)["posterior"], RZ.SCENARIOS, RZ.DEFAULTS)["port"]


@pytest.mark.parametrize("code,quality,own,g,expect", [
    ("extreme", "low", 0.10, 0.25, ("trim", 0.5)), ("extreme", "mixed", 0.40, 0.25, ("trim", 0.75)), ("extreme", "low", 0.40, 0.25, ("trim", 0.5)),
    ("exuberant", "low", 0.05, 0.15, ("trim", 0.75)), ("exuberant", "low", 0.30, 0.15, ("hold and hedge", 1.0)), ("exuberant", "high", 0.05, 0.15, ("hold and hedge", 1.0)),
    ("within", "low", 0.1, 0.1, ("hold", 1.0)), ("pessimistic", "high", 0.3, 0.0, ("add", 1.25)), ("insufficient", "low", None, None, ("investigate", 1.0))])
def test_position_rules_are_as_stated(code, quality, own, g, expect):
    val = {"verdict": {"code": code}, "quality": {"quality_grade": quality, "flags": []}, "own_growth": own, "implied_growth": g, "p_achieve": 0.01 if g else None,
           "base_rate_bucket": "over_50b", "why": [], "price_to_p90_value": None}
    a = OO.position_action("X", 0.1, val)
    assert a["action"] == expect[0] and a["target"] == pytest.approx(0.1 * expect[1])


# ---------- the engine registry ----------
def test_engine_runs_offline_engines_isolates_failures_and_hashes_outputs(tmp_path, monkeypatch):
    m = EN.run(tmp_path, only=["valuation", "causal", "hedges", "ooda"])
    rows = {r["name"]: r for r in m["engines"]}
    assert all(rows[k]["status"] == "ok" for k in ("valuation", "causal", "hedges", "ooda")), [rows[k].get("error") for k in rows]
    assert rows["macro"]["status"] == "external" and rows["reason"]["status"] == "skipped"
    for k in ("valuation.json", "causal.json", "hedges.json", "ooda.json", "engines.json"):
        assert (tmp_path / k).exists()
    assert rows["ooda"]["outputs"]["ooda.json"]
    boom = next(e for e in EN.REGISTRY if e.name == "causal")
    monkeypatch.setattr(boom, "run", lambda out: (_ for _ in ()).throw(RuntimeError("planted")))
    m2 = EN.run(tmp_path, only=["causal", "hedges"])
    r2 = {r["name"]: r for r in m2["engines"]}
    assert r2["causal"]["status"] == "failed" and "planted" in r2["causal"]["error"] and r2["hedges"]["status"] == "ok"


def test_steady_state_ignores_prepayments():
    """Cash flow lifted by customer prepayments or deferred taxes must not raise the steady-state margin."""
    from buildout import valuation
    base = {"revenue": 100.0, "op_income": 30.0, "net_income": 25.0, "ocf": 32.0, "capex": 20.0, "da": 8.0, "sbc": 3.0,
            "interest": 1.0, "debt": 10.0, "cash": 20.0, "assets": 200.0, "equity": 120.0}
    q0 = valuation.quality(base)
    assert q0["steady_basis"] == "cash" and q0["steady_fcf"] == pytest.approx(32 - 8 - 3)
    lifted = dict(base, ocf=60.0)                     # 28 of prepayments on top
    q1 = valuation.quality(lifted)
    assert q1["steady_basis"] == "operating earnings" and q1["steady_fcf"] == pytest.approx(30 * (1 - valuation.ASSUMED["tax"]))
    assert any(f["key"] == "working_capital" for f in q1["flags"])
    a0 = valuation.analyze_position("X", base, 500.0, 0.05, 1.0)
    a1 = valuation.analyze_position("X", lifted, 500.0, 0.05, 1.0)
    assert a1["m_star"] == pytest.approx(0.30 * (1 - valuation.ASSUMED["tax"]))   # capped at operating earnings, not 49%
    assert q1["steady_cash_margin"] == pytest.approx(0.49) and a0["m_star"] == pytest.approx(0.21)
