"""v0.8: the brain's reasoner, checked in Python against the page's JavaScript on the page's own graph, and against
planted answers."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from buildout import thinking as TH

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


def _js(cases):
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness8.js")], input=json.dumps(cases), capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def _chain():
    """a -> b -> c, d -> c; roots a and d; observe b and c."""
    return 4, [(0, 1, 0.8), (1, 2, 0.5), (3, 2, 0.9)]


def test_abduction_recovers_a_planted_cause():
    n, E = _chain()
    T = TH.total_effect(n, E, 4)
    truth = np.array([1.5, 0.0])                       # a shocked, d quiet
    y = T[np.ix_([1, 2], [0, 3])] @ truth
    ab = TH.abduce(T, {1: y[0], 2: y[1]}, [0, 3], obs_sd=0.05, prior_sd=10)
    assert abs(ab["s"][0] - 1.5) < 0.02 and abs(ab["s"][1]) < 0.02 and ab["explained"] > 0.999
    ex = TH.explanations(T, {1: y[0], 2: y[1]}, [0, 3], obs_sd=0.2)
    assert ex[0]["root"] == 0 and ex[0]["p"] > 0.9            # the planted cause wins the comparison


def test_noise_only_wins_when_nothing_moved():
    n, E = _chain()
    T = TH.total_effect(n, E, 4)
    ex = TH.explanations(T, {1: 0.01, 2: -0.02}, [0, 3])
    assert ex[0]["root"] is None


def test_next_observation_prefers_the_node_that_separates_causes():
    # a and d both move c; only a moves b. Observing c alone cannot tell them apart; b can.
    n, E = _chain()
    T = TH.total_effect(n, E, 4)
    ex = TH.explanations(T, {2: 1.0}, [0, 3], obs_sd=0.3)
    nx = TH.next_observation(T, ex, [1], obs_sd=0.3)
    assert nx[0]["node"] == 1 and nx[0]["info"] > 0.05
    nx0 = TH.next_observation(T, [{"root": 0, "p": 1.0, "s": 1, "s_sd": 0.1}], [1])
    assert nx0[0]["info"] < 1e-6                              # one hypothesis: nothing left to learn


def test_doing_cuts_incoming_links_seeing_does_not():
    n, E = _chain()
    do = TH.intervene(n, E, 4, 1, 1.0)
    assert do[0] == 0 and abs(do[1] - 1) < 1e-12 and abs(do[2] - 0.5) < 1e-12
    T = TH.total_effect(n, E, 4)
    ab = TH.abduce(T, {1: 1.0}, [0, 3], obs_sd=0.05, prior_sd=10)
    seen = TH.predict(T, ab)["mean"]
    assert seen[0] > 1.0                                         # seeing b implies its cause a moved


def test_criticism_blames_the_wrong_link():
    n, E = _chain()
    T_true = TH.total_effect(n, [(0, 1, 0.8), (1, 2, 0.5), (3, 2, 0.9)], 4)
    y = T_true[np.ix_([1, 2], [0, 3])] @ np.array([1.0, 0.0])
    wrong = [(0, 1, 0.8), (1, 2, -0.2), (3, 2, 0.9)]              # b -> c has the wrong sign
    T = TH.total_effect(n, wrong, 4)
    ab = TH.abduce(T, {1: y[0], 2: y[1]}, [0], obs_sd=0.05, prior_sd=10)
    cr = TH.criticize(n, wrong, 4, ab)
    assert int(np.argmax(np.abs(cr["grad"]))) == 1


def test_shared_exposure_flags_one_bet_in_two_names():
    T = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [2, 0.1, 1, 0], [4, 0.2, 0, 1]], float)
    sh = TH.shared_exposure(T, [2, 3], [0, 1])
    assert sh["cos"][0][1] > 0.999


@needs_node
def test_brain_reasoner_matches_the_page():
    cases = [{"blend": 1.0, "K": 6, "do": ["fed", -1.5]}, {"blend": 0.0, "K": 4, "do": ["capex", 1.0], "extra": {"credit": 1.2, "memory": -1.0}},
             {"blend": 0.5, "K": 8, "do": ["hormuz", 2.0], "edit": {"tlt>book": 0.3}}]
    for c, g in zip(cases, _js(cases)):
        observed = {int(k): v for k, v in g["observed"].items()}
        E = [tuple(e) for e in g["edges"]]
        th = TH.think(g["n"], E, c["K"], observed, g["roots"], g["holds"])
        assert np.allclose(th["T"], g["T"], atol=1e-12)
        ab = th["abduce"]
        assert np.allclose(ab["s"], g["s"], atol=1e-10) and np.allclose(ab["sd"], g["sd"], atol=1e-10)
        assert abs(ab["explained"] - g["explained"]) < 1e-10
        assert np.allclose(th["predict"]["mean"], g["mean"], atol=1e-10) and np.allclose(th["predict"]["sd"], g["psd"], atol=1e-10)
        assert np.allclose(th["criticize"]["resid"], g["resid"], atol=1e-10)
        assert np.allclose(th["criticize"]["grad"], g["grad"], atol=1e-5)
        py = [(r["root"], r["p"]) for r in th["explanations"]]
        assert [r for r, _ in py] == [r for r, *_ in g["expl"]]
        assert np.allclose([p for _, p in py], [x[1] for x in g["expl"]], atol=1e-10)
        assert [r["node"] for r in th["next"][:5]] == [x[0] for x in g["next"][:5]]
        assert np.allclose([r["info"] for r in th["next"]], [x[1] for x in g["next"]], atol=1e-8)
        assert np.allclose(th["shared"]["cos"], g["cos"], atol=1e-12)
        assert np.allclose(TH.intervene(g["n"], E, c["K"], _node_index(g, c["do"][0]), c["do"][1]), g["doing"], atol=1e-12)


def _node_index(g, node_id):
    js = "const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');const m=src.match(/const BR_NODES = (\\[[\\s\\S]*?\\n  \\]);/);" \
         "const N=new Function('return '+m[1])();process.stdout.write(JSON.stringify(N.map(n=>n.id)));"
    ids = json.loads(subprocess.run([NODE, "-e", js, str(ROOT / "site" / "src" / "brain.js")], capture_output=True, text=True, check=True).stdout)
    return ids.index(node_id)


@needs_node
def test_the_graph_is_well_formed_and_the_book_adds_up():
    js = "const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');" \
         "const N=new Function('return '+src.match(/const BR_NODES = (\\[[\\s\\S]*?\\n  \\]);/)[1])();" \
         "const E=new Function('return '+src.match(/const BR_EDGES = (\\[[\\s\\S]*?\\n  \\]);/)[1])();" \
         "process.stdout.write(JSON.stringify({N,E}));"
    d = json.loads(subprocess.run([NODE, "-e", js, str(ROOT / "site" / "src" / "brain.js")], capture_output=True, text=True, check=True).stdout)
    ids = [n["id"] for n in d["N"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 34
    keys = [f"{e[0]}>{e[1]}" for e in d["E"]]
    assert len(keys) == len(set(keys)) and all(e[0] in ids and e[1] in ids for e in d["E"])
    weights = {e[0]: e[2] for e in d["E"] if e[1] == "book" and e[0] != "tlt"}
    import tomllib
    book = tomllib.loads((ROOT / "config.toml").read_text())["universe"]["book"]
    assert weights == {k: pytest.approx(v) for k, v in book.items()}           # the book node uses config.toml's weights


# ---------- field research (review revision 5) ----------
from buildout import field as FD  # noqa: E402


def _field_js(runs, ms):
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness8f.js")], input=json.dumps({"runs": runs, "ms": ms}), capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def test_field_posterior_and_next_evidence_by_hand():
    prior = [0.5, 0.5]
    lik = {"a": [0.9, 0.1], "b": [0.5, 0.5]}
    post = FD.posterior(prior, lik, {"a": True})
    assert post[0] == pytest.approx(0.9)
    nx = FD.next_evidence(prior, lik, {})
    assert nx[0]["evidence"] == "a" and nx[0]["info_bits"] == pytest.approx(1 - (-(0.9 * math.log2(0.9) + 0.1 * math.log2(0.1))))
    assert nx[1]["info_bits"] == pytest.approx(0.0, abs=1e-12)   # evidence equally likely under every story teaches nothing
    assert FD.posterior(prior, {"z": [0.0, 0.0]}, {"z": True}) == [0.5, 0.5]   # impossible evidence falls back to the prior


@needs_node
def test_field_matches_python_and_is_well_formed():
    runs = [{"id": "leadtime", "seen": {}}, {"id": "leadtime", "seen": {"Deferrals and cancellations rise": True, "Output and deliveries rise": False}},
            {"id": "pipeline", "seen": {"One campus appears in several parties' announcements": True}}, {"id": "credit", "seen": {"Average loan term lengthens": True}}]
    ms = [[{"due": "2026-11-10", "lag": 0}, "2026-10-21"], [{"due": "2026-10-25", "lag": 0}, "2026-10-21"], [{"due": "2026-10-18", "lag": 7}, "2026-10-21"], [{"due": "2026-10-01", "lag": 7}, "2026-10-21"]]
    js = _field_js(runs, ms)
    for r, out in zip(runs, js["runs"]):
        c = next(x for x in js["cases"] if x["id"] == r["id"])
        prior = [1 / len(c["hyps"])] * len(c["hyps"])
        assert out["post"] == pytest.approx(FD.posterior(prior, c["ev"], r["seen"]), abs=1e-12)
        py = FD.next_evidence(prior, c["ev"], r["seen"])
        assert [x["evidence"] for x in out["next"]] == [x["evidence"] for x in py]
        assert [x["info_bits"] for x in out["next"]] == pytest.approx([x["info_bits"] for x in py], abs=1e-12)
    assert js["ms"] == ["upcoming", "due", "lag", "overdue"]
    for c in js["cases"]:
        assert c["node"] in js["nodes"]
        for e, ls in c["ev"].items():
            assert len(ls) == len(c["hyps"]) and all(0 < l < 1 for l in ls), e
    assert len(js["indicators"]) == 10 and all(r[5] in js["nodes"] and r[3] in ("Economic", "Publication", "Market") for r in js["indicators"])
    assert all(m["node"] in js["nodes"] for m in js["milestones"])


# ---------- the MCP server: protocol, tools, and the promise that it never executes ----------
import sys  # noqa: E402

from buildout import mcp_server as MS  # noqa: E402


def _session(msgs, *extra):
    lines = "\n".join(m if isinstance(m, str) else json.dumps(m) for m in msgs) + "\n"
    r = subprocess.run([sys.executable, "-m", "buildout.mcp_server", *extra], input=lines, capture_output=True, text=True, timeout=180, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    return [json.loads(x) for x in r.stdout.splitlines()]


def _call(i, name, args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}


def test_mcp_handshake_and_tool_list_over_stdio():
    out = _session([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, "not json", {"jsonrpc": "2.0", "id": 3, "method": "nope"}])
    assert [o.get("id") for o in out] == [1, 2, None, 3]              # the notification gets no reply
    assert out[0]["result"]["protocolVersion"] == "2024-11-05" and out[0]["result"]["serverInfo"]["version"] == __import__("buildout").__version__
    names = [t["name"] for t in out[1]["result"]["tools"]]
    assert names == ["get_research_snapshot", "get_portfolio_risk", "analyze_positions", "decision_loop", "position_valuation", "hedge_book", "reason", "labs_lookup", "game_math", "ml_forecast", "reality_check", "triage_backtest", "damodaran_value", "technical_analysis", "fundamental_analysis", "rl_policy", "bond_scenario", "market_history", "data_connections", "investor_voices", "atlas_trace", "brain_selfcheck", "run_hedge_scenario", "evaluate_trade", "create_order_proposal",
                     "review_decision", "compare_explanations", "learned_structure", "trace_exposure"]
    assert all(t["annotations"]["readOnlyHint"] for t in out[1]["result"]["tools"])
    assert out[2]["error"]["code"] == -32700 and out[3]["error"]["code"] == -32601


def test_mcp_tools_agree_with_the_engine():
    ctx = MS.Context()
    ok = lambda name, args: MS.handle(ctx, _call(1, name, args))["result"]  # noqa: E731
    r = ok("run_hedge_scenario", {"correlations": [0.2, -0.05, -0.12, -0.04], "inflation_36m": 0.031, "line": 0.0425})["structuredContent"]
    assert r["state_path_tail"] == ["amplifying", "neutral", "hedging", "hedging"] and r["decision"]["on"] is True
    r = ok("run_hedge_scenario", {"correlation": -0.3, "inflation_36m": 0.05, "line": 0.0425})["structuredContent"]
    assert r["decision"]["on"] is False                                    # hedging regime, but inflation above the line
    from buildout import reasoner as RZ
    e = ok("evaluate_trade", {"portfolio": {"equity": 1.0}, "signals": {"infl": True}})["structuredContent"]
    post = RZ.posterior([s["prior"] for s in RZ.SCENARIOS], RZ.SIGNALS, {"infl": True})["posterior"]
    ref = RZ.evaluate((1.0, 0, 0, 0), post, RZ.SCENARIOS, RZ.DEFAULTS)
    assert e["result"]["worst_3m"] == pytest.approx(ref["worst"], abs=1e-4) and e["result"]["meets_loss_limit"] == ref["feasible"]
    c = ok("compare_explanations", {"case": "credit", "seen": {"Average loan term lengthens": True}})["structuredContent"]
    assert c["leading"] == "Longer terms and more financing risk"
    t = ok("trace_exposure", {"readings": {"capex": -2.0}, "do": {"node": "y10", "value": 1.0}})["structuredContent"]
    assert t["explain"]["single_causes"][0]["cause"] in {n["id"] for n in ctx.graph["graph"]["nodes"]}
    assert set(t["deduce"]) == set(ctx.graph["graph"]["holdings"]) | {"book"}
    assert t["do_vs_see"]["book_if_set"] != pytest.approx(t["do_vs_see"]["book_if_seen"])
    risk = ok("get_portfolio_risk", {})["structuredContent"]
    assert risk["weights"] == dict(ctx.config.universe.book) and "not personal positions" in risk["book"]


def test_mcp_never_executes_and_rejects_bad_input():
    ctx = MS.Context()
    res = lambda name, args: MS.handle(ctx, _call(1, name, args))["result"]  # noqa: E731
    p = res("create_order_proposal", {"symbol": "NVDA", "side": "buy", "weight_change": 0.2, "rationale": "Data-center demand", "kill_criteria": "Guide cut"})
    sc = p["structuredContent"]
    assert sc["executed"] is False and sc["status"] == "proposal_only" and sc["requires_human_review"] is True
    assert sc["all_checks_pass"] is False                                  # 14% + 20% breaks the single-name cap
    assert len(sc["sha256"]) == 64
    for name, args in [("create_order_proposal", {"symbol": "NVDA", "side": "buy", "weight_change": -0.1, "rationale": "x" * 20, "kill_criteria": "y" * 6}),
                       ("create_order_proposal", {"symbol": "NVDA", "side": "sell", "weight_change": -0.5, "rationale": "x" * 20, "kill_criteria": "y" * 6}),
                       ("evaluate_trade", {"portfolio": {"equity": float("inf")}}), ("evaluate_trade", {"portfolio": {"equity": 9}}),
                       ("trace_exposure", {"readings": {"oil": 99}}), ("trace_exposure", {"orders": 50}),
                       ("compare_explanations", {"case": "nope"}), ("run_hedge_scenario", {"correlations": [2]}),
                       ("get_portfolio_risk", {"surprise": 1})]:
        assert res(name, args)["isError"] is True, (name, args)
    tools = {t["name"] for t in MS.tool_list()}
    assert not tools & {"place_order", "submit_order", "cancel_order", "execute"}
    with pytest.raises(SystemExit):
        MS.Context(config_path=str(ROOT / "config.private.toml"))


@needs_node
def test_exported_graph_is_in_sync_with_the_page():
    import importlib.util
    spec = importlib.util.spec_from_file_location("export_graph", ROOT / "scripts" / "export_graph.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fresh = mod.generate()
    shipped = json.loads((ROOT / "buildout" / "assets" / "brain_graph.json").read_text())
    assert fresh == shipped, "run python scripts/export_graph.py"



def test_mcp_analyze_positions_is_exact_and_stores_nothing(tmp_path):
    ctx = MS.Context(data_dir=str(tmp_path))
    call = lambda args: MS.handle(ctx, _call(1, "analyze_positions", args))["result"]  # noqa: E731
    r = call({"positions": [{"symbol": "NVDA", "quantity": 10, "price": 100}, {"symbol": "goog", "market_value": 500},
                            {"symbol": "TLT", "market_value": 300}, {"symbol": "ZZZZ", "market_value": 100}], "cash": 100})["structuredContent"]
    assert r["weights"] == {"NVDA": 0.5, "GOOGL": 0.25, "TLT": 0.15, "ZZZZ": 0.05} and r["cash_weight"] == pytest.approx(0.05)
    assert r["brain"]["unmapped"] == ["ZZZZ"] and r["brain"]["mapped"]["GOOGL"] == "GOOGL"
    assert r["as_portfolio_vector"]["equity"] == pytest.approx(0.8) and r["as_portfolio_vector"]["hedge_ratio"] == pytest.approx(0.15 / 0.8, abs=1e-4)
    assert not next(c for c in r["checks"] if "single name" in c["check"])["pass"]
    # the same weights as the model book reproduce the model book's sensitivities exactly
    book = dict(ctx.config.universe.book)
    mine = call({"positions": [{"symbol": k, "weight": v} for k, v in book.items()]})["structuredContent"]["brain"]["sensitivity_to_root_causes"]
    model = MS.handle(ctx, _call(2, "get_portfolio_risk", {}))["result"]["structuredContent"]["book_sensitivity_to_root_causes"]
    assert mine == pytest.approx(model, abs=1e-9)
    assert list(tmp_path.iterdir()) == []                                # nothing written
    for bad in [{"positions": []}, {"positions": [{"symbol": "NVDA"}]}, {"positions": [{"symbol": "NVDA", "weight": 0.5}, {"symbol": "AMZN", "market_value": 9}]},
                {"positions": [{"symbol": "<script>", "weight": 0.1}]}, {"positions": [{"symbol": "NVDA", "market_value": -5}]}]:
        assert call(bad)["isError"] is True, bad


# ---------- free corporate-actions fallback ----------
import pandas as pd  # noqa: E402

from buildout.data import corporate_actions as CA  # noqa: E402
from buildout.data.databento_source import DatabentoSource  # noqa: E402


def _fake_source(closes_long, factors_ok):
    src = DatabentoSource.__new__(DatabentoSource)
    src.raw_daily_bars = lambda symbols, start, end=None: closes_long
    def factors(symbols, start, end=None):
        if not factors_ok:
            raise PermissionError("403: reference data not in plan")
        return CA.split_factors(symbols)
    src.adjustment_factors = factors
    return src


def _bars():
    d = pd.bdate_range("2024-06-03", "2024-06-14")
    nv = [1100.0] * 5 + [110.0] * 5                                     # NVDA's 10-for-1 on 2024-06-10
    ms = [420.0] * 10
    rows = [{"date": t, "symbol": s, "open": p, "high": p, "low": p, "close": p, "volume": 1} for t, a, b in zip(d, nv, ms) for s, p in (("NVDA", a), ("MSFT", b))]
    return pd.DataFrame(rows)


def test_public_split_table_replaces_missing_vendor_factors():
    src = _fake_source(_bars(), factors_ok=False)
    c = src.adjusted_closes(["NVDA", "MSFT"], "2024-06-01", adjustments="auto")
    assert src.adjustments_used == "public" and "403" in src.adjustments_error
    assert c["NVDA"].pct_change().abs().max() < 1e-12 and c["NVDA"].iloc[0] == pytest.approx(110.0)
    with pytest.raises(RuntimeError, match="public"):
        _fake_source(_bars(), factors_ok=False).adjusted_closes(["NVDA"], "2024-06-01", adjustments="databento")
    ok = _fake_source(_bars(), factors_ok=True)
    ok.adjusted_closes(["NVDA", "MSFT"], "2024-06-01")
    assert ok.adjustments_used == "databento"


def test_a_split_missing_from_the_table_stops_the_run_by_name():
    b = _bars()
    b.loc[(b.symbol == "MSFT") & (b.date >= "2024-06-10"), "close"] = 210.0
    with pytest.raises(ValueError, match="MSFT.*corporate_actions.py"):
        _fake_source(b, factors_ok=False).adjusted_closes(["NVDA", "MSFT"], "2024-06-01")


def test_split_table_is_well_formed_and_covers_the_universe():
    from buildout.config import load_config
    u = load_config(ROOT / "config.toml").universe
    covered = set(CA.SPLITS) | set(CA.NO_SPLITS)
    assert set(u.equities) <= covered, set(u.equities) - covered
    assert not set(CA.SPLITS) & set(CA.NO_SPLITS)
    for s, evs in CA.SPLITS.items():
        dates = [d for d, _ in evs]
        assert dates == sorted(dates) and len(set(dates)) == len(dates)
        assert all(r > 1 and pd.Timestamp(d) >= pd.Timestamp("2018-05-01") for d, r in evs)


def test_bond_income_accrues_the_yield_less_fees():
    d = pd.bdate_range("2025-01-01", periods=253)
    closes = pd.DataFrame({"TLT": 90.0, "NVDA": 100.0}, index=d)
    y = pd.DataFrame({"DGS20": 4.15, "DGS7": 3.9}, index=d)
    out, used = CA.add_bond_income(closes, y)
    assert out["TLT"].iloc[-1] / out["TLT"].iloc[0] == pytest.approx((1 + 0.04 / 252) ** 252)
    assert (out["NVDA"] == 100.0).all() and out["TLT"].iloc[0] == 90.0
    assert used["TLT"]["avg_income_ann"] == pytest.approx(0.04)
