"""v0.25: the engine reasons (deduction with proofs, induction walked forward, abduction, invention), the legends'
principles are tested on 156 years, methods from actuarial science, weather forecasting and big data are scored on the
engine, and the page shows the math by default with the Methods group always in view."""
from __future__ import annotations

import json
import re
from pathlib import Path

from buildout import decide, mcp_server, mind, ontology, reason, voices

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
ASSETS = ROOT / "buildout" / "assets"
BANNED = (chr(0x2014), "inter" "section", "load" "-bearing")


def _snap25() -> dict:
    s = (SRC / "snap25.js").read_text()
    i = s.index("const SNAP25 = ")
    return json.loads(s[i + len("const SNAP25 = "):s.index(";\n", i)].replace("<\\/", "</"))


# ---------------------------------------------------------------- the corpus: checked, linked, in house style
def test_v25_corpus_is_checked_and_resolves():
    C = json.loads((ASSETS / "concepts25.json").read_text())["concepts"]
    assert len(C) >= 200
    ids = {c["id"] for c in ontology.concepts()}
    for c in C:
        assert c["checked"].startswith(("confirmed", "corrected", "written by the lead")), c["id"]
        assert c["cluster"] in ontology.CLUSTERS and "c:" + c["id"] in ids
        for b in BANNED:
            assert b not in json.dumps(c, ensure_ascii=False).lower(), c["id"]
    for c in ontology.concepts():                                   # every relation target resolves
        for _, t in c["rel"]:
            assert ":" in t or "c:" + t in ids, (c["id"], t)        # typed targets (e:, s:) resolve elsewhere
    K = json.loads((ASSETS / "knowledge.json").read_text())["items"]
    new = [i for i in K if i.get("cluster") in ("taleb", "traders", "actuarial", "weather", "bigdata")]
    assert len(new) >= 100 and all(i["checked"].startswith(("confirmed", "corrected")) and i["source_url"].startswith("https://") for i in new)
    assert all(c in mind.FACT_CLUSTER for c in ("taleb", "traders", "actuarial", "weather", "bigdata"))
    V = json.loads((ASSETS / "voices.json").read_text())["quotes"]
    assert {"tails_uncertainty", "trading_discipline"} <= set(voices.TOPICS)
    texts = [(re.sub(r"\W+", " ", q["text"].lower()).strip(), q["topic"]) for q in V]
    assert len(texts) == len(set(texts)), "a quote appears twice under one topic"        # the same line may be filed under two topics
    assert sum(1 for q in V if q["speaker"] == "Nassim Nicholas Taleb") >= 20


def test_rules_are_well_formed_and_were_all_tested():
    R = json.loads((ASSETS / "rules25.json").read_text())["rules"]
    assert len(R) >= 40
    for r in R:
        assert r["if"] and all(c[0] in reason.FEATURES and c[1] in ("<", ">", "<=", ">=") for c in r["if"]), r["id"]
        assert r["then"]["outcome"] in reason.OUTCOMES and r["source_url"].startswith("https://")
    O = _snap25()["reason"]
    tested = {x["id"]: x for x in O["rules"]}
    assert all(r["id"] in tested for r in R)
    for x in tested.values():
        assert x["verdict"] in ("supported", "one era only", "reversed", "no evidence", "untestable")
        if x["verdict"] == "supported":
            assert x["halves_agree"] and x["q"] <= 0.10                 # supported means both halves agree and BH passes


# ---------------------------------------------------------------- the reasoner and the decision
def test_the_shipped_call_is_derived_by_the_proof():
    D = _snap25()["reason"]["decision"]
    s19 = (SRC / "snap19.js").read_text()
    i = s19.index("const SNAP19 = ")
    N = json.loads(s19[i + len("const SNAP19 = "):s19.index(";\n", i)].replace("<\\/", "</"))["decision"]["now"]
    assert abs(D["conclusions"]["exposure"] - N["exposure"]) < 1e-9
    assert D["conclusions"]["bond_hedge"] == "off" and D["conclusions"]["state"] == "amplifying"
    flips = {c["premise"]: c for c in D["counterfactuals"] if c.get("flips_down") or c.get("flips_up")}
    assert abs(flips["corr36"]["flips_down"]["at"] + 0.10) < 0.01 and flips["corr36"]["flips_down"]["bond_hedge"] == "on"
    live = reason.decision_proof({**reason.DEFAULT_FACTS, "corr36": -0.2, "prev_state": "neutral"})
    assert live["conclusions"]["bond_hedge"] == "on"


def test_induction_reports_survivors_out_of_sample_only():
    O = _snap25()["reason"]
    d = O["discover"]
    assert d["start_test"] == "1961-01" and d["n_candidates"] > 10000 and 0 <= len(d["survivors"]) <= d["testable"] <= d["tested"]
    byid = {r["id"]: r for r in d["rules"]}
    for sid in d["survivors"]:
        r = byid[sid]
        assert r["oos"]["n_in"] >= d["min_oos"] and abs(r["oos"]["t"]) > 1.5 and r["survives"]
    assert O["deduce"]["fixpoint"] and O["deduce"]["contradictions_n"] == 0
    assert O["invent"]["k"] >= 2 and len(O["invent"]["clusters"]) == O["invent"]["k"]


# ---------------------------------------------------------------- borrowed methods: every trial with its verdict
def test_every_borrowed_upgrade_is_listed_with_a_verdict_and_counted_by_the_gate():
    S = _snap25()
    T = S["trials"]
    ids = {t["id"] for t in T}
    assert {"emos", "emos_normal", "bma", "credibility", "evt_floor"} <= ids
    assert all(t["why"] for t in T) and not any(t["adopted"] for t in T if t["id"] in ("emos", "emos_normal", "bma", "credibility", "evt_floor"))
    assert decide.N_TRIED >= len(decide.CONFIGS) + 4 + 4 + 5                      # the v0.25 variants raise the bar
    cf = S["crossfield"]
    assert cf["variants"]["as_is"]["coverage90"]["n"] >= 900 and 0.85 < cf["variants"]["as_is"]["coverage90"]["coverage"] < 0.95
    assert set(cf["tail"]["methods"]) >= {"normal", "historical", "pot", "filtered_pot", "engine"}
    assert len(S["methods"]) >= 30 and all(m.get("source_url", "").startswith("https://") for m in S["methods"])


# ---------------------------------------------------------------- the page
def test_methods_group_is_visible_and_the_math_is_on_by_default():
    boot, body, head = (SRC / "boot.js").read_text(), (SRC / "body.html").read_text(), (SRC / "head.html").read_text()
    groups = dict(re.findall(r'(\w+): \{ name: "[^"]+", views: \[([^\]]+)\] \}', boot))
    assert groups["reference"].startswith('"methods", "crossfield"') and groups["engine"].startswith('"explained", "edges", "reasoning"')
    assert '<a href="#methods" data-group="reference">Methods</a>' in body
    assert "LS.get(\"bo-math25\", true) !== false" in boot and ":root.math-off .math { display: none; }" in head and ".math { display: block; }" in head
    assert re.search(r"@media \(max-width: 640px\) \{\s*\.tabs \{ grid-template-columns: repeat\(3", head)       # six tabs, two rows, never a scroll
    assert 'id="t7-math"' in body and "function renderCallMath" in (SRC / "landing.js").read_text()
    for v in ("reasoning", "methods", "crossfield"):
        assert f'id="view-{v}"' in body and any(d[0] == v for d in mind.DESKS)
    assert '"snap25.js", "reasoning.js"' in (ROOT / "scripts" / "assemble_page.py").read_text()
    js = (SRC / "reasoning.js").read_text()
    for b in BANNED:
        assert b not in js.lower()


def test_mcp_has_the_reasoning_and_verification_tools_and_still_no_order_tool():
    assert {"reasoning_engine", "forecast_verification"} <= set(mcp_server.TOOLS)
    assert not any(re.search(r"place|execute|submit|send_order", k) for k in mcp_server.TOOLS)     # proposals only, never an order
    js = (SRC / "landing.js").read_text()
    assert int(re.search(r"const MCP_TOOLS = (\d+);", js).group(1)) == len(mcp_server.TOOLS)
