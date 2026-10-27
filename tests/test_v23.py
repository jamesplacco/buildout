"""v0.23: one engine, its parameters first. The inventory of Theta is checked against the modules it describes (shapes,
counts, layers, the constants set by hand), the trend overlay's rule is checked on data whose answer is known, and the
page is checked for the six groups, the one-screen landing page, the Parameters desk and the moved sections."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

from buildout import decide, mcp_server, ml, parameters, rl
from buildout.engine import REGISTRY

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
BANNED = (chr(0x2014), "inter" "section", "load" "-bearing")


def _const(src: str, name: str) -> dict:
    i = src.index(f"const {name} = ")
    return json.loads(src[i + len(f"const {name} = "):src.index(";\n", i)].replace("<\\/", "</"))


# ---------------------------------------------------------------- the inventory
def test_inventory_from_constants_is_complete_and_consistent():
    o = parameters.build()
    ids = [e["id"] for e in o["entries"]]
    assert len(ids) == len(set(ids)) == 22
    layers = {L["id"] for L in o["layers"]}
    for e in o["entries"]:
        for k in ("id", "layer", "name", "symbol", "shape", "count", "algorithm", "objective", "data", "refit", "feeds", "module"):
            assert k in e, (e["id"], k)
        assert e["layer"] in layers
        assert e["count"] > 0 and e["feeds"]
        if e.get("parts"):
            assert e["count"] == sum(int(np.prod(p["shape"])) for p in e["parts"])
        else:
            assert e["count"] == int(np.prod(e["shape"]))
    assert o["total"] == sum(e["count"] for e in o["entries"])
    assert o["core"] == sum(e["count"] for e in o["entries"] if e["layer"] in ("regimes", "forecasts", "allocation", "portfolio", "learning"))
    assert sum(v["count"] for v in o["by_layer"].values()) == o["total"]
    assert set(o["feeds"]) >= {"decision", "portfolio", "mind", "brain", "atlas", "geometry", "ml"}
    txt = json.dumps(o).lower()
    for b in BANNED:
        assert b not in txt


def test_shapes_follow_the_modules():
    o = parameters.build()
    E = {e["id"]: e for e in o["entries"]}
    n_feat = len(ml.FEATURES)
    assert E["ridge"]["shape"] == [n_feat + 1] and E["combo"]["shape"] == [2, n_feat]
    nn = E["deep_ensemble"]
    sizes = (n_feat, 16, 8, 1)
    assert nn["count"] == 5 * sum(sizes[i] * sizes[i + 1] + sizes[i + 1] for i in range(3)) == 1445
    assert E["q_table"]["shape"] == [54, len(rl.ACTIONS), len(rl.ACTIONS)]
    assert E["stacking"]["shape"] == [len(decide.FORECASTS)] and E["dma_weights"]["shape"] == [len(decide.MODELS)]
    assert E["hedge_selector"]["shape"] == [4, len(decide.HEDGES), 2]
    assert E["mind_spectral"]["parts"][0]["shape"][1] == 64
    assert "Expectation-maximisation" in E["hmm_stocks"]["algorithm"] and "Adam" in E["deep_ensemble"]["algorithm"]


def test_shapes_follow_the_run_when_outputs_are_given():
    dec = {"now": {"regime": {"K": 2, "A": [[0.9, 0.1], [0.2, 0.8]], "mu": [0.01, -0.02], "sd": [0.03, 0.08], "now": [0.7, 0.3], "persistence_months": [10, 5]},
                   "changepoint": {"map_run": 11, "recent": 0.1, "expected_run": 40}, "models": {"weights": {"hmm": 1.0}}, "mixture": {"geo": {"w": [0.5, 0.5]}},
                   "forecasts": {"now": {}, "weights": {}}, "gate": {"t": 0.0, "t0": 1.0, "value": 0.0}, "hedge": {}, "exposure": 1.0, "engine_exposure": 1.0},
           "months": 600, "end": "2000-01", "regime_fits": [1] * 10, "kalman": {"beta": [0.0] * 50, "now": 0.0, "now_se": 0.0}, "overlay": {"adopted": 0.75, "rule": "r"}, "gamma": 3.0}
    o = parameters.build(dec=dec, mind={"nodes": [{}] * 100, "edges": [{}] * 300, "params": {"alpha": 0.5, "steps": 10}})
    E = {e["id"]: e for e in o["entries"]}
    assert E["hmm_stocks"]["parts"][0]["shape"] == [2, 2] and E["hmm_stocks"]["count"] == 4 + 2 + 2
    assert E["bocpd"]["shape"] == [12, 4] and E["geo_analogs"]["shape"] == [3, 2]
    assert E["mind_weights"]["shape"] == [300] and E["mind_spectral"]["parts"][0]["shape"] == [100, 64]
    assert "10 fits since 1940" in E["hmm_stocks"]["refit"] and E["overlay"]["values"]["factor"] == 0.75 and E["gamma"]["values"]["gamma"] == 3.0
    assert E["kalman_beta"]["as_of"] == "2000-01"


def test_set_by_hand_names_every_judgment_with_a_reason():
    o = parameters.build()
    ids = {c["id"] for c in o["set_by_hand"]}
    assert {"lag", "es_limit", "forget", "refit_hmm", "refit_ml", "n_tried", "hazard", "overlay_factors"} <= ids
    for c in o["set_by_hand"]:
        assert c["reason"] and c["where"]
    by = {c["id"]: c for c in o["set_by_hand"]}
    assert by["lag"]["value"] == decide.LAG and by["es_limit"]["value"] == decide.ES_LIMIT and by["n_tried"]["value"] == decide.N_TRIED


def test_table_and_cli_print_the_inventory():
    o = parameters.build()
    t = parameters.table(o)
    assert "total" in t and f"{o['total']:,}" in t and "deep_ensemble" in t
    out = subprocess.run([sys.executable, "-m", "buildout", "parameters", "--data", str(ROOT / "nowhere")], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert out.returncode == 0 and "q_table" in out.stdout and "set by hand" in out.stdout
    out = subprocess.run([sys.executable, "-m", "buildout", "parameters", "--json", "--data", str(ROOT / "nowhere")], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert json.loads(out.stdout)["total"] == parameters.build(**parameters.load_outputs(ROOT / "nowhere"))["total"]   # the shipped assets fill the knowledge counts


def test_mcp_tool_serves_the_inventory_by_layer_and_object():
    ctx = mcp_server.Context(str(ROOT / "nowhere"), str(ROOT / "config.toml"))
    call = lambda args, i: mcp_server.handle(ctx, {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "parameter_inventory", "arguments": args}})
    r = call({}, 1)["result"]
    assert not r["isError"]
    sc = r["structuredContent"]
    assert sc["total"] > 0 and len(sc["entries"]) == 22 and sc["set_by_hand"] and "note" in sc
    assert "objective" not in sc["entries"][0]                     # the brief listing; the object view carries the rest
    r = call({"layer": "learning"}, 2)["result"]["structuredContent"]
    assert [e["id"] for e in r["entries"]] == ["q_table"] and r["layer"]["id"] == "learning"
    r = call({"id": "deep_ensemble"}, 3)["result"]["structuredContent"]
    assert r["entry"]["count"] == 1445 and "objective" in r["entry"]
    assert call({"layer": "nope"}, 4)["result"]["isError"] and call({"id": "nope"}, 5)["result"]["isError"]
    tool = next(t for t in mcp_server.tool_list() if t["name"] == "parameter_inventory")
    assert tool["annotations"]["readOnlyHint"] is True


def test_parameters_engine_is_registered_and_snapshotted():
    e = next(x for x in REGISTRY if x.name == "parameters")
    assert e.writes == ["parameters.json"] and e.offline and "decision.json" in e.reads
    reg = _const((SRC / "snap11.js").read_text(), "ENGINES_SNAP") if "const ENGINES_SNAP = {" in (SRC / "snap11.js").read_text() else None
    txt = (SRC / "snap11.js").read_text()
    i = txt.index("const ENGINES_SNAP = ")
    reg = json.loads(txt[i + len("const ENGINES_SNAP = "):txt.index(";\n", i)])
    assert len(reg) == len(REGISTRY) and any(r["name"] == "parameters" for r in reg)


def test_snapshot_agrees_with_the_mind_and_the_modules():
    T = _const((SRC / "snap23.js").read_text(), "SNAP23")["parameters"]
    o = parameters.build()
    assert [e["id"] for e in T["entries"]] == [e["id"] for e in o["entries"]]
    mind = json.loads((ROOT / "buildout" / "assets" / "mind.json").read_text())
    E = {e["id"]: e for e in T["entries"]}
    assert E["mind_weights"]["values"]["nodes"] == len(mind["nodes"]) and E["mind_weights"]["shape"] == [len(mind["edges"])]
    assert E["mind_spectral"]["parts"][0]["shape"] == [len(mind["nodes"]), 64]
    assert T["total"] == sum(e["count"] for e in T["entries"]) and T["core"] == o["core"]
    assert E["overlay"]["values"]["factor"] in decide.OVERLAY_FACTORS
    ids = {n["id"] for n in mind["nodes"]}
    assert "x:parameters" in ids and "d:parameters" in ids
    assert {f"th:{e['id']}" for e in T["entries"]} <= ids and {f"th:layer:{L['id']}" for L in T["layers"]} <= ids


# ---------------------------------------------------------------- the trend overlay
def test_overlay_rule_picks_the_shallowest_drawdown_that_keeps_utility():
    rng = np.random.default_rng(23)
    T = 1200
    # a market where the trend signal is informative: returns are poor when the signal is off
    sig = rng.random(T) < 0.7
    r = np.where(sig, rng.normal(0.008, 0.035, T), rng.normal(-0.012, 0.06, T))
    base, m = np.ones(T), np.ones(T, bool)
    gamma = 2.2
    bidx = np.array([rng.integers(0, T, T) for _ in range(40)])
    o = decide.overlay_study(r, sig, base, m, gamma, bidx)
    assert o["factors"] == list(decide.OVERLAY_FACTORS) and set(o["rows"]) == {f"{b}:{f}" for b in ("hold", "engine") for f in decide.OVERLAY_FACTORS}
    free = [f for f in decide.OVERLAY_FACTORS if o["rows"][f"hold:{f}"]["utility_gain_month"] >= 0.0]
    assert o["full_record_choice"] == max(free, key=lambda f: o["rows"][f"hold:{f}"]["perf"]["maxdd"])
    assert o["adopted"] == o["full_record_choice"] == 0.0        # here sitting out the bad months is free and shallowest, and it survives walked forward
    assert o["walk_forward"]["utility_gain_month"] > 0.0 and o["walk_forward"]["burn_in_months"] == 120 and len(o["walk_forward"]["chosen"]) == (T - 120 + 11) // 12
    assert o["rows"]["hold:1.0"]["perf"]["maxdd"] <= o["rows"]["hold:0.0"]["perf"]["maxdd"]
    assert o["trend_on_now"] == bool(sig[-1]) and "drawdown" in o["rule"]
    # a market where the signal is noise: no factor below one is free, so holding (1.0) stays
    sig2 = rng.random(T) < 0.5
    r2 = rng.normal(0.006, 0.04, T)
    o2 = decide.overlay_study(r2, sig2, base, m, gamma, bidx)
    free2 = [f for f in decide.OVERLAY_FACTORS if o2["rows"][f"hold:{f}"]["utility_gain_month"] >= 0.0]
    assert 1.0 in free2 and o2["full_record_choice"] == max(free2, key=lambda f: o2["rows"][f"hold:{f}"]["perf"]["maxdd"])
    assert o2["adopted"] == 1.0 or o2["walk_forward"]["utility_gain_month"] >= 0.0   # a factor is adopted only if it also survives walked forward


def test_shipped_decision_carries_the_overlay_and_the_headline_matches():
    D = _const((SRC / "snap19.js").read_text(), "SNAP19")["decision"]
    ov, now = D["overlay"], D["now"]
    assert ov["adopted"] in decide.OVERLAY_FACTORS and now["overlay"]["factor"] == ov["adopted"]
    assert now["overlay"]["trend_on"] == ov["trend_on_now"]
    if now["overlay"]["trend_on"]:
        assert abs(now["overlay"]["exposure_if_off"] - now["exposure"] * ov["adopted"]) < 1e-9
    assert any("overlay" in f.lower() or "below the 10-month average" in f for f in D["findings"])
    body = (SRC / "body.html").read_text()
    hedge = {"stocks": "no bond hedge", "bonds": "a 30% Treasury hedge", "cash": "a 30% cash sleeve"}[now["hedge"]["choice"]]
    if ov["adopted"] >= 1.0:
        tail = "no trend overlay after it failed its walk-forward test"
        assert ov["full_record_choice"] < 1.0 and ov["walk_forward"]["utility_gain_month"] < 0.0 and "walk-forward" in ov["adopted_reason"]
    else:
        tail = f"cut to {now['overlay']['exposure_if_off']:.2f}x if the 10-month trend breaks" if now["overlay"]["trend_on"] else f"scaled by {ov['adopted']:.2f} while the trend is off"
    assert f"Hold equity at {now['exposure']:.2f}x with {hedge}; {tail}." in body


# ---------------------------------------------------------------- the page
def test_six_groups_cover_every_desk_once():
    boot, body = (SRC / "boot.js").read_text(), (SRC / "body.html").read_text()
    groups = dict(re.findall(r'(\w+): \{ name: "[^"]+", views: \[([^\]]+)\] \}', boot))
    assert list(groups) == ["today", "engine", "markets", "research", "workshop", "reference"]
    views = [v.strip('" ') for g in groups.values() for v in g.split(",")]
    assert len(views) == len(set(views))
    assert set(views) == set(re.findall(r'<section class="view" id="view-([\w-]+)"', body))
    assert groups["engine"].startswith('"explained"') and '"parameters"' in groups["engine"] and '"code"' in groups["engine"] and '"agents"' in groups["engine"]
    assert groups["today"].startswith('"desk"')
    nav = re.findall(r'<a href="#(\w+)" data-group="(\w+)">', body)
    assert [g for _, g in nav] == list(groups) and all(v in views for v, _ in nav)
    assert "parameters:" in (SRC / "views.js").read_text().split("const TAB_NAME = ")[1][:200]
    guide = (SRC / "guide.js").read_text()
    assert '"parameters": {"q":' in guide and all(f'"{g}":' in guide.split("GUIDE_GROUPS = ")[1].split("\n")[0] for g in groups)
    assert "1 to 6 open a group" in guide and "/^[1-6]$/" in (SRC / "views.js").read_text()


def test_landing_page_is_the_call_and_the_engine():
    body = (SRC / "body.html").read_text()
    desk = body[body.index('id="view-desk"'):body.index('id="view-decision"')]
    for sel in ('id="call-board"', 'id="flow"', 'id="theta"', 'id="theta-layers"', 'id="hood"', 'id="fund"', 'id="t7-changes"', 'id="t7-reverse"', 'id="t7-trust"', 'id="brief"', 'id="chip-tests"'):
        assert sel in desk, sel
    for gone in ('id="hero"', 'id="voices"', 'id="pulse"', 'id="miss"', 'id="signals-grid"', 'id="map-box"', 'id="mv-table"', 'id="levels"', 'id="gauge"', 'id="macro-body"', 'id="t7-choices"', 'id="nw-teaser"', 'id="thesis-chips"'):
        assert gone not in desk, gone
    # the sections live on the desks that own them
    homes = {"hero": "mind", "voices": "legends", "pulse": "journal", "miss": "theses", "signals": "decide", "sysmap": "brain", "moves": "rates", "live": "engines"}
    for sec, view in homes.items():
        i = body.index(f'id="{sec}"')
        start = body.rfind('<section class="view" id="view-', 0, i)
        assert body[start:start + 60].split('id="view-')[1].split('"')[0] == view, sec
    assert 'id="view-parameters"' in body and 'id="pm-table"' in body and 'id="pm-hand"' in body and 'id="dx-overlay"' in body
    scripts = (ROOT / "scripts" / "assemble_page.py").read_text()
    assert '"snap23.js", "params.js", "explain.js", "snap24.js", "digest.js", "snap25.js", "reasoning.js", "snap26.js", "edges.js", "snap27.js", "nowcast.js", "snap28.js", "filings.js", "snap29.js", "futures.js", "landing.js"' in scripts
    assert "Thesis chips" not in (SRC / "boot.js").read_text()


def test_landing_counts_match_the_engine():
    js = (SRC / "landing.js").read_text()
    assert int(re.search(r"const MCP_TOOLS = (\d+);", js).group(1)) == len(mcp_server.TOOLS)
    assert f"{len(mcp_server.TOOLS)} tools" in (SRC / "reference.js").read_text().split('q: "Can the MCP server trade?"')[1][:60]
    agents = (SRC / "body.html").read_text()
    assert 'id="ag-v23-t"' in agents
    ref = (SRC / "reference.js").read_text()
    assert '["v0.23", "Oct 23, 2026",' in ref and 'g: "v0.23", q: "What is Theta' in ref
    assert (ROOT / "README.md").read_text().count("Version 0.23") == 1
    import buildout
    assert buildout.__version__ >= "0.23.0"


def test_no_banned_words_in_the_new_files():
    for p in (ROOT / "buildout" / "parameters.py", SRC / "landing.js", SRC / "params.js", ROOT / "scripts" / "snapshot_v23.py", ROOT / "tests" / "test_v23.py"):
        t = p.read_text().lower()
        for b in BANNED:
            assert b not in t.replace('"inter" "section"', "").replace('"load" "-bearing"', ""), (p.name, b)
