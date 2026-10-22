"""v0.15: machine learning judged honestly, the reality check of every model's assumptions, Damodaran's tools, the
belief network with what-if questions, the information-edge sources, the key modes and the editors, and the page's
mirror of all of it. Synthetic tests plant the answer and check the method finds it."""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import assumptions as A
from buildout import damodaran as D
from buildout import mind, ml, voices

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
MIND_JSON = ROOT / "buildout" / "assets" / "mind.json"
SNAP15 = ROOT / "site" / "src" / "snap15.js"
QUESTIONS = ["Is the stock market overvalued?", "What if oil spikes, what happens to bonds?", "If AI capex slows, what happens to the book?", "If the Fed cuts",
             "What is the Kelly criterion?", "What is BowTied Bull?", "Can I trust quant models?", "Does machine learning predict returns?", "Is Nvidia overvalued?",
             "Suppose inflation rises, what happens to gold?", "What if zzqx", "Should I buy long bonds?", "What are fat tails?"]


@pytest.fixture(scope="module")
def snap():
    return json.loads(MIND_JSON.read_text())


@pytest.fixture(scope="module")
def M(snap):
    return mind.Mind(snap, voices.Library(voices.load()))


def _snap15() -> dict:
    t = SNAP15.read_text()
    i = t.index("const SNAP15 = ") + len("const SNAP15 = ")
    return json.loads(t[i:t.index(";\n", i)].replace("<\\/", "</"))


def _node(req: dict) -> dict:
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness15.js")], input=json.dumps(req), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


# ---------------------------------------------------------------- machine learning, on planted answers
def _synthetic(n=900, beta=0.0, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1900-01-01", periods=n, freq="MS")
    X = pd.DataFrame({f: np.cumsum(rng.standard_normal(n)) * 0.02 + rng.standard_normal(n) * 0.1 for f in ml.FEATURES}, index=idx)
    X["y_ret"] = beta * X["log_cape"] + rng.standard_normal(n) * 0.05
    X["y_crash"] = (X["y_ret"] < np.quantile(X["y_ret"], 0.2)).astype(float)
    return X


def _cheap_models(task):
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.neighbors import KNeighborsRegressor
    if task == "return":
        return {"cape_ols": ("CAPE", lambda: LinearRegression(), ["log_cape"]), "ridge": ("All", lambda: LinearRegression(), ml.FEATURES),
                "analogs": ("kNN 1", lambda: KNeighborsRegressor(n_neighbors=1), ml.FEATURES)}
    return {"logit": ("Logit", lambda: LogisticRegression(max_iter=500), ml.FEATURES)}


def test_walk_forward_finds_a_planted_predictor_and_not_a_fake_one(monkeypatch):
    monkeypatch.setattr(ml, "models", _cheap_models)
    W = ml.walk_forward(_synthetic(beta=1.0), "return", start=1940, permute=False)
    S = ml.score(W)
    assert S["cape_ols"]["skill"] > 0.3 and S["cape_ols"]["dm"]["t"] > 2
    W0 = ml.walk_forward(_synthetic(beta=0.0), "return", start=1940, permute=False)
    S0 = ml.score(W0)
    assert S0["cape_ols"]["skill"] < 0.05 and S0["analogs"]["skill"] < 0          # nearest-neighbour noise loses to the mean
    assert len(W["dates"]) == W["n"] == 420 and W["refits"] == 35


def test_walk_forward_never_trains_on_an_overlapping_outcome(monkeypatch):
    seen = []

    def spy(make, feats, Xtr, ytr, Xte, task):
        seen.append((Xtr.index[-1], Xte.index[0]))
        return np.zeros(len(Xte)), None
    monkeypatch.setattr(ml, "models", _cheap_models)
    monkeypatch.setattr(ml, "_fit_predict", spy)
    ml.walk_forward(_synthetic(), "return", start=1940, permute=False)
    for last_train, first_test in seen:
        months = (first_test.year - last_train.year) * 12 + first_test.month - last_train.month
        assert months >= ml.H + ml.EMBARGO


def test_cpcv_overfitting_odds_low_for_a_real_signal_high_for_noise(monkeypatch):
    linear = lambda task: {k: v for k, v in _cheap_models(task).items() if k != "analogs"}
    monkeypatch.setattr(ml, "models", linear)
    real = ml.cpcv(_synthetic(beta=1.0), "return", groups=6, k=2)
    assert real["splits"] == 15 and real["pbo"] <= 0.2
    assert real["oos_mean"]["cape_ols"] > 0.3
    monkeypatch.setattr(ml, "models", _cheap_models)
    memo = ml.cpcv(_synthetic(beta=1.0), "return", groups=6, k=2)
    assert memo["pbo"] >= 0.5                                                     # a memorizing model wins in sample and misleads
    noise = ml.cpcv(_synthetic(beta=0.0), "return", groups=6, k=2)
    assert noise["in_mean"]["analogs"] > 0.9 and noise["oos_mean"]["analogs"] < 0     # memorizes the past, loses the future
    assert noise["pbo"] >= 0.5


def test_conformal_interval_covers_as_promised_and_dm_has_the_right_sign():
    rng = np.random.default_rng(5)
    e = rng.standard_normal(3000)
    c = ml.conformal(e, 0.8)
    assert abs(c["coverage"] - 0.8) < 0.03 and c["halfwidth"] == pytest.approx(1.2816, abs=0.12)
    better = ml.diebold_mariano(e * 0.5, e)
    assert better["t"] > 5 and ml.diebold_mariano(e, e * 0.5)["t"] < -5
    assert ml._auc(np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9])) == 1.0


def test_shipped_ml_lab_is_honest_and_complete():
    o = _snap15()["ml"]
    assert o["start_oos"] == 1940 and o["horizon"] == 12 and o["embargo"] == 1
    for task in ("return", "crash"):
        assert set(o[task]["scores"]) >= {"ensemble", "forest", "boost", "analogs"}
        assert o[task]["n_oos"] > 900 and o[task]["cpcv"]["splits"] == 28 and 0 <= o[task]["cpcv"]["pbo"] <= 1
    assert 0.7 < o["return"]["interval"]["coverage"] < 0.9
    assert len(o["analogs"]) == 8 and 0 <= o["shift"]["novelty_pct"] <= 1
    assert all(len(f) > 20 for f in o["findings"])


# ---------------------------------------------------------------- the reality check, on planted answers
def test_kappa_is_zero_for_a_bell_curve_and_positive_for_fat_tails():
    rng = np.random.default_rng(1)
    g = A.kappa(rng.standard_normal(20000))
    t = A.kappa(rng.standard_t(3, 20000))
    assert abs(g["kappa"]) < 0.05 and g["n_equivalent_30"] == pytest.approx(30, rel=0.15)
    assert t["kappa"] > 0.1 and t["n_equivalent_30"] > 35


def test_tail_and_dependence_tests_pass_normal_iid_data():
    rng = np.random.default_rng(2)
    x = rng.standard_normal(2000) * 0.04
    tt = A.tails_test(x, "normal", 12)
    assert tt["observed_beyond"] <= tt["gaussian_expects"] * 3 + 3 and abs(tt["var_understatement"]) < 0.15
    assert A.ljung_box(x)["p"] > 0.01


def test_sup_f_finds_a_planted_break():
    rng = np.random.default_rng(4)
    x = np.concatenate([rng.standard_normal(300) * 0.03, rng.standard_normal(300) * 0.03 + 0.03])
    r = A.sup_f(x, sims=200)
    assert r["p"] < 0.05 and abs(r["at"] - 300) < 40


def test_hedge_breakpoint_is_where_the_sleeve_stops_reducing_risk():
    w, se, sb = 0.3, 0.18, 0.12
    rho = -w * sb / (2 * se)
    var = lambda r: se ** 2 + w ** 2 * sb ** 2 + 2 * w * r * se * sb
    assert var(rho) == pytest.approx(se ** 2, abs=1e-12)
    assert var(rho - 0.05) < se ** 2 < var(rho + 0.05)


def test_fragility_flags_short_puts_and_clears_the_collar():
    F = A.fragility()["structures"]
    assert F["short_put"]["verdict"] == "fragile" and F["short_put"]["H_min"] < 0
    assert F["collar"]["H_min"] >= -1e-4 and F["unhedged"]["verdict"] == "linear"


def test_triage_matches_the_published_formulas():
    t = A.triage(1.0, 5, 45, trial_sd=1.0)
    assert t["minbtl_years"] == pytest.approx(5.0, abs=0.01)                    # Bailey et al.: 45 tries need about five years
    one = A.triage(1.0, 10, 1)
    assert one["dsr"] == pytest.approx(one["psr"]) and one["minbtl_years"] == 0
    c = A.triage(1.0, 10, 1, cost_bps=10, turns=30, vol=0.15)
    assert c["net"] == pytest.approx(1.0 - 0.001 * 30 / 0.15) and c["live"] == pytest.approx(c["net"] * 0.74)
    assert A.triage(1.0, 10, 1, published=True)["live"] == pytest.approx(0.42)
    assert A.triage(0.5, 3, 500)["verdict"] == "likely noise" and A.triage(1.5, 30, 2)["verdict"] == "credible"


def test_shipped_reality_check_registers_every_model():
    o = _snap15()["reality"]
    assert len(o["map"]) >= 8 and all(m["verdict"] in ("holds", "strained", "broken", "untested") for m in o["map"])
    c = o["checks"]
    assert c["kappa"]["series"]["Gaussian (check)"]["kappa"] == pytest.approx(0, abs=0.03)
    assert c["tails_month"]["observed_beyond"] > 3 * c["tails_month"]["gaussian_expects"]
    assert c["hedge"]["rho_star"] < 0 and c["worlds"]["n"] == 400


# ---------------------------------------------------------------- Damodaran, against closed forms
def test_implied_erp_reduces_to_gordon_when_growth_equals_the_risk_free_rate():
    e = D.implied_erp(100.0, 0.04, 0.05, 0.05)
    assert e["r"] == pytest.approx(0.05 + 0.04 * 1.05, abs=1e-9)
    assert D.implied_erp(100.0, 0.035, 0.06, 0.0513)["erp"] == pytest.approx(0.0382, abs=0.0005)


def test_narrative_dcf_reduces_to_a_perpetuity_with_no_growth():
    d = D.narrative_dcf(100.0, 0.0, 0.2, 0.2, wacc_start=0.08, wacc_mature=0.08, rf=0.0)
    assert d["ev"] == pytest.approx(100 * 0.2 * 0.79 / 0.08, rel=1e-9)
    f = D.narrative_dcf(100.0, 0.0, 0.2, 0.2, wacc_start=0.08, wacc_mature=0.08, rf=0.0, p_fail=0.2)
    assert f["equity"] == pytest.approx(d["ev"] * (0.8 + 0.2 * 0.5), rel=1e-9)
    assert D.narrative_dcf(100.0, 0.3, 0.1, 0.3, rf=0.04, g_terminal=0.09)["g_terminal"] == 0.04     # capped at the risk-free rate


# ---------------------------------------------------------------- the belief network and what-if
def test_propagation_without_links_returns_each_claims_own_evidence():
    net = {"axes": ["a", "b"], "links": [], "base": [0.5, -1.0], "gamma": 0.6, "iters": 60}
    p = mind.propagate(net)
    assert p == pytest.approx([1 / (1 + math.exp(-0.5)), 1 / (1 + math.exp(1.0))], abs=1e-9)
    linked = dict(net, links=[[0, 1, 1.0]])
    hi, lo = mind.propagate(linked, {"a": 0.9}), mind.propagate(linked, {"a": 0.1})
    assert hi[0] == pytest.approx(0.9) and lo[0] == pytest.approx(0.1) and hi[1] > lo[1]


def test_shipped_network_is_well_formed(snap):
    net = snap["net"]
    assert len(net["axes"]) >= 10 and all(abs(w) <= 1 and abs(w) >= mind.NET_MIN for _, _, w in net["links"])
    assert net["p"] == pytest.approx(mind.propagate(net), abs=1e-6)


def test_think_handles_what_if_explain_and_caps_the_network(M):
    r = M.think("If AI capex slows, what happens to the book?")
    assert r["mode"] == "whatif" and r["whatif"]["axis"] == "ai_boom" and r["whatif"]["side"] == "bear"
    t = r["whatif"]["target"]
    assert t["axis"] == "book" and t["lean1"] < t["lean0"]
    b = M.think("What if oil spikes, what happens to bonds?")
    assert b["axis"] == "bonds_rates" and b["whatif"]["axis"] == "oil_energy" and b["whatif"]["target"]["axis"] == "bonds_rates"
    k = M.think("What is the Kelly criterion?")
    assert k["mode"] == "explain" and k["define"]["name"] == "Kelly criterion"
    bt = M.think("What is BowTied Bull?")
    assert "BowTied" in bt["define"]["name"]
    for q in ("Is Nvidia overvalued?", "Is the stock market overvalued?"):
        rows = [x for x in M.think(q)["pros"] + M.think(q)["cons"] if x["group"] == "network"]
        assert all(abs(x["c"]) <= mind.NET_CAP + 1e-9 for x in rows)
    assert M.think("What if zzqx")["found"] is False


def test_page_mind_v2_matches_python(snap, M):
    s15 = _snap15()
    fixed = [{}, {"oil_energy": 0.9}, {"ai_boom": 0.1, "inflation_fed": 0.9}]
    req = {"voices": {"cfg": voices.config(), "lib": {"quotes": voices.load()}}, "mind": snap, "snap15": s15, "questions": QUESTIONS, "propagate": fixed,
           "triage": [[1.2, 8, 40, 12, 0, 3, True, 5, 24, 0.15], [1.0, 5, 45, 12, -0.5, 6, False, 0, 0, 0.15, 1.0], [0.4, 2, 1]],
           "erp": [[100, 0.035, 0.06, 0.0513], [100, 0.04, 0.05, 0.05], [100, 0.001, 0.0, 0.05]],
           "dcf": [dict(revenue=100, growth_high=0.25, margin_now=0.3, margin_target=0.3531, sales_to_capital=1.21, wacc_start=0.1055, rf=0.0513, p_fail=0.05),
                   dict(revenue=50, growth_high=-0.05, margin_now=-0.1, margin_target=0.15, years_to_target=7, sales_to_capital=2.0, wacc_start=0.12, wacc_mature=0.09, rf=0.04, debt=10, cash=5, shares=3)]}
    out = _node(req)
    for q, js in zip(QUESTIONS, out["think"]):
        py = M.think(q)
        assert js["found"] == py["found"], q
        if not py["found"]:
            continue
        assert (js["mode"], js["axis"], js["side"]) == (py["mode"], py["axis"], py["side"]), q
        assert js["seeds"] == [s["id"] for s in py["seeds"]], q
        assert js["p"] == pytest.approx(py["p"], abs=1e-6) and js["range"] == pytest.approx(py["range"], abs=1e-6), q
        assert [x[0] for x in js["pros"]] == [x["id"] for x in py["pros"]] and [x[0] for x in js["cons"]] == [x["id"] for x in py["cons"]], q
        assert js["hinge"] == (py["hinge"]["id"] if py["hinge"] else None) and js["decision"] == py["decision"]["action"], q
        assert js.get("define") == (py["define"]["id"] if py.get("define") else None), q
        if "whatif" in py:
            w, pw = js["whatif"], py["whatif"]
            assert w["found"] == pw["found"], q
            if pw["found"]:
                assert (w["axis"], w["side"], w["p_fixed"]) == (pw["axis"], pw["side"], pw["p_fixed"]), q
                assert [e["axis"] for e in w["effects"]] == [e["axis"] for e in pw["effects"]], q
                assert [e["p1"] for e in w["effects"]] == pytest.approx([e["p1"] for e in pw["effects"]], abs=1e-6), q
                assert (w["target"] is None) == (pw["target"] is None), q
                if pw["target"]:
                    assert w["target"]["axis"] == pw["target"]["axis"], q
    for fx, js in zip(fixed, out["propagate"]):
        assert js == pytest.approx(mind.propagate(snap["net"], fx), abs=1e-12)
    for a, js in zip(req["triage"], out["triage"]):
        py = A.triage(*a)
        for k in ("net", "live", "psr", "dsr", "emax_annual", "minbtl_years"):
            assert js[k] == pytest.approx(py[k], abs=1e-6), k
        assert js["verdict"] == py["verdict"]
    for a, js in zip(req["erp"], out["erp"]):
        py = D.implied_erp(*a)
        assert (js["r"] is None) == (py["r"] is None)
        if py["r"] is not None:
            assert js["erp"] == pytest.approx(py["erp"], abs=1e-12)
    for o, js in zip(req["dcf"], out["dcf"]):
        py = D.narrative_dcf(**o)
        for k in ("ev", "equity", "per_share", "terminal", "terminal_share", "g_terminal"):
            assert js[k] == pytest.approx(py[k], rel=1e-12, abs=1e-12), k


# ---------------------------------------------------------------- sources, interfaces, the page
def test_edge_sources_are_profiled_and_checked():
    E = _snap15()["edge"]
    src = [x for x in E["edge"] if x["kind"] == "source"]
    ids = {x["id"] for x in src}
    assert {"es-src-bowtiedbull", "es-src-sixsigmaresearch", "es-src-taleb", "es-src-damodaran-data", "es-src-berkshire-letters"} <= ids
    for x in src:
        assert x["source_url"].startswith("https://") and x.get("edge") and x.get("biases") and x.get("checked"), x["id"]
        if x.get("feed_url"):
            assert x["feed_url"].startswith("https://")
    assert len(E["model_risk"]) >= 40 and len(E["ml_finance"]) >= 40


def test_mcp_tools_for_ml_reality_triage_and_damodaran_never_execute():
    from buildout import mcp_server as MS
    c = MS.Context()
    assert len(MS.TOOLS) >= 23
    assert MS.ml_forecast(c, {})["findings"] and MS.ml_forecast(c, {"part": "analogs"})["result"]
    assert MS.reality_check(c, {"part": "hedge"})["result"]["rho_star"] < 0
    assert MS.triage_backtest(c, {"sharpe": 1.0, "years": 5, "trials": 45})["minbtl_years"] > 4
    assert MS.damodaran_value(c, {"kind": "erp", "args": {"cash_yield": 0.035, "growth": 0.06}})["erp"] > 0
    for bad in ({"part": "nope"},):
        with pytest.raises(MS.ToolError):
            MS.ml_forecast(c, bad)
    with pytest.raises(MS.ToolError):
        MS.triage_backtest(c, {"sharpe": 1.0})
    with pytest.raises(MS.ToolError):
        MS.damodaran_value(c, {"kind": "dcf", "args": {}})
    src = (ROOT / "buildout" / "mcp_server.py").read_text()
    for word in ("place_order", "submit_order", "execute_order"):
        assert f"def {word}" not in src


def test_cli_think_prints_a_what_if_and_json():
    r = subprocess.run(["python", "-m", "buildout", "think", "If AI capex slows, what happens to the book?"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "what-if" in r.stdout and "model book" in r.stdout
    j = subprocess.run(["python", "-m", "buildout", "think", "What is the Kelly criterion?", "--json"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert json.loads(j.stdout)["define"]["name"] == "Kelly criterion"
    t = subprocess.run(["python", "-m", "buildout", "triage", "1.0", "5", "45"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert "minimum backtest" in t.stdout


def test_editor_plugins_call_the_engine_and_never_trade():
    vim = (ROOT / "editors" / "buildout.vim").read_text()
    el = (ROOT / "editors" / "buildout.el").read_text()
    for cmd in ("BuildoutThink", "BuildoutWhatIf", "BuildoutTriage", "BuildoutERP", "BuildoutDCF"):
        assert re.search(r"command! -nargs=\S+ " + cmd + r"\b", vim), cmd
    for fn in ("buildout-think", "buildout-what-if", "buildout-triage", "buildout-erp", "buildout-dcf", "global-buildout-mode"):
        assert f"({'define-globalized-minor-mode' if fn.startswith('global') else 'defun'} {fn}" in el, fn
    if shutil.which("vim"):
        out = ROOT / ".pytest_vim.txt"
        subprocess.run(["vim", "-Nes", "-u", "NONE", "-i", "NONE", "-c", f"let g:buildout_root='{ROOT}'", "-c", "source editors/buildout.vim", "-c", "BuildoutTriage 1.0 5 45",
                        "-c", f"call writefile(getline(1, '$'), '{out}')", "-c", "qa!"], cwd=ROOT, timeout=120)
        try:
            assert "minimum backtest" in out.read_text()
        finally:
            out.unlink(missing_ok=True)


def test_page_ships_v15_desks_keys_and_no_banned_text():
    page = (ROOT / "site" / "page.html").read_text()
    for id_ in ("view-ml", "view-reality", "view-edge", "md-net", "ky-bar", "ky-mode", "rt-sr", "ed-erp-cy", "ed-dcf-g", "ml-ret", "rt-map"):
        assert f'id="{id_}"' in page, id_
    assert "const SNAP15 =" in page and "function wireKeys" in page and 'class="ver">v0.' in page
    low = page.lower()
    assert chr(0x2014) not in page and ("inter" "section") not in low and ("load" "-bearing") not in low
    assert "DATABENTO_API_KEY=" not in page
    snap = json.loads(MIND_JSON.read_text())
    assert f"{len(snap['nodes']):,} nodes" in page
    assert f"{sum(1 for x in snap['nodes'] if x['k'] == 'concept'):,} concepts" in page
