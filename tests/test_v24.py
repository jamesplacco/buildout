"""v0.24: the research deepened and checked, the engine explained in plain English with a replay, and the audit fixes.
The knowledge store is checked for provenance (every item dated, linked, checked), the digest for freshness and
consistency with the store, the How-it-works desk for the live numbers it quotes, and the page for the two new desks."""
from __future__ import annotations

import json
import re
from pathlib import Path

from buildout import decide, mind

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
BANNED = (chr(0x2014), "inter" "section", "load" "-bearing")


def _const(src: str, name: str) -> dict:
    i = src.index(f"const {name} = ")
    return json.loads(src[i + len(f"const {name} = "):src.index(";\n", i)].replace("<\\/", "</"))


# ---------------------------------------------------------------- the knowledge store
def test_every_knowledge_item_is_dated_linked_and_checked():
    K = json.load(open(ROOT / "buildout" / "assets" / "knowledge.json"))
    ids = [i["id"] for i in K["items"]]
    assert len(ids) == len(set(ids))
    for it in K["items"]:
        assert str(it.get("source_url", "")).startswith("https://"), it["id"]
        if it.get("cluster") in ("tape", "capex_earnings", "ai_credit", "fed_inflation", "power"):
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", str(it.get("as_of") or "")), it["id"]
        assert it.get("checked", "").startswith(("confirmed", "corrected")), it["id"]
        for k, v in it.items():
            if isinstance(v, str):
                for b in BANNED:
                    assert b not in v.lower(), (it["id"], k)
    new = [i for i in K["items"] if i.get("cluster") in ("capex_earnings", "ai_credit", "fed_inflation", "power")]
    assert len(new) >= 40, "the v0.24 research clusters are thin"
    assert all(c in mind.FACT_CLUSTER for c in ("capex_earnings", "ai_credit", "fed_inflation", "power"))


def test_voices_are_verbatim_dated_and_linked():
    V = json.load(open(ROOT / "buildout" / "assets" / "voices.json"))
    ids = [q["id"] for q in V["quotes"]]
    assert len(ids) == len(set(ids))
    for q in V["quotes"]:
        assert q["source_url"].startswith("https://") and q["stance"] in (-2, -1, 0, 1, 2) and q["kind"] in ("legend", "current")
        assert q["date"] and q["verification"].startswith("verbatim")
        if q["date"] >= "2026-09":
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", q["date"]), q["id"]        # the v0.24 quotes carry a full date
        for b in BANNED:
            assert b not in q["text"].lower() and b not in q["gist"].lower(), q["id"]
    recent = [q for q in V["quotes"] if q["date"] >= "2026-09-01"]
    assert len(recent) >= 15


def test_digest_matches_the_store_and_is_fresh():
    D = _const((SRC / "snap24.js").read_text(), "SNAP24")["digest"]
    K = {i["id"]: i for i in json.load(open(ROOT / "buildout" / "assets" / "knowledge.json"))["items"]}
    assert D["n"] == len(D["items"]) >= 60 and D["since"] <= "2026-10-13"
    for x in D["items"]:
        k = K[x["id"]]
        assert x["as_of"] >= D["since"] and x["source_url"] == k["source_url"] and x["text"] == k["text"]
        assert x["cluster"] in ("tape", "capex_earnings", "ai_credit", "fed_inflation", "power", "distribution", "private_markets", "commodities")
    assert sum(D["by_cluster"].values()) == D["n"]
    assert D["items"] == sorted(D["items"], key=lambda x: (x["as_of"], x["id"]), reverse=True)
    body = (SRC / "body.html").read_text()
    assert 'id="view-digest"' in body and 'id="dg-list"' in body
    js = (SRC / "digest.js").read_text()
    for c in D["by_cluster"]:
        assert f'["{c}",' in js, c                                   # every cluster in the digest has a group definition


# ---------------------------------------------------------------- the explainer
def test_how_it_works_quotes_the_engine_and_replays_its_record():
    body = (SRC / "body.html").read_text()
    D = _const((SRC / "snap19.js").read_text(), "SNAP19")["decision"]
    N = D["now"]
    desk = body[body.index('id="view-explained"'):body.index('id="view-parameters"')]
    assert f'<span id="hw-es">{round(D["es_limit"] * 100)}%</span>' in desk
    assert f'<span id="hw-opt">{N["engine_exposure"]:.2f}x</span>' in desk and f'<span id="hw-x">{N["exposure"]:.2f}x</span>' in desk
    f_words = f'adopted at {D["overlay"]["adopted"]:.2f}' if D["overlay"]["adopted"] < 1.0 else "tested and not adopted, because it failed the same walk-forward test the engine applies to itself"
    assert f'<span id="hw-f">{f_words}</span>' in desk
    assert D["overlay"]["walk_forward"]["burn_in_months"] == 120 and D["overlay"]["walk_forward"]["refit_months"] == 12
    assert 'id="hw-when"' in desk and 'id="hw-read"' in desk and 'id="hw-exp"' in desk and 'id="hw-growth"' in desk
    assert len(D["exposure_hist"]["dates"]) == len(D["gate_hist"]["dates"]) == len(D["curve"]["dates"])
    assert D["exposure_hist"]["dates"][0] == "1940-01"
    assert "weather service" in desk.lower() and "What the engine is not" in desk
    js = (SRC / "explain.js").read_text()
    assert "exposure_hist" in js and "model_weights_hist" in js and "forecast_weights_hist" in js and "vmarks" in js
    for b in BANNED:
        assert b not in desk.lower() and b not in js.lower()


def test_navigation_has_the_two_new_desks_first_in_their_groups():
    boot = (SRC / "boot.js").read_text()
    groups = dict(re.findall(r'(\w+): \{ name: "[^"]+", views: \[([^\]]+)\] \}', boot))
    assert groups["engine"].startswith('"explained"') and '"parameters"' in groups["engine"] and groups["research"].startswith('"digest", "findings"')
    body = (SRC / "body.html").read_text()
    assert '<a href="#explained" data-group="engine">Engine</a>' in body and '<a href="#digest" data-group="research">Research</a>' in body
    views = set(re.findall(r'<section class="view" id="view-([\w-]+)"', body))
    assert {"explained", "digest"} <= views
    guide = (SRC / "guide.js").read_text()
    assert '"explained": {"q":' in guide and '"digest": {"q":' in guide
    scripts = (ROOT / "scripts" / "assemble_page.py").read_text()
    assert '"explain.js"' in scripts and '"snap24.js", "digest.js"' in scripts
    assert any(d[0] == "explained" for d in mind.DESKS) and any(d[0] == "digest" for d in mind.DESKS)
    assert "Every month the engine reads 156 years of data" in body[body.index('id="view-desk"'):body.index('id="view-decision"')]


def test_overlay_constants_still_match_the_explainer():
    assert decide.OVERLAY_FACTORS == (0.0, 0.25, 0.5, 0.75, 1.0) and decide.ES_LIMIT == 0.12


# ---------------------------------------------------------------- the audit fixes
def test_one_governing_size_reaches_every_desk_that_sizes():
    views = (SRC / "views.js").read_text()
    assert "function govSize()" in views and "function govNote(" in views
    for f, what in (("decide.js", "The volatility rule's size"), ("solve.js", "The solver's allocation"), ("ooda.js", "The solver's choice"),
                    ("buyside6.js", "Rule 7a.1"), ("views.js", "This lab's size")):
        assert f'govNote("{what}"' in (SRC / f).read_text(), f
    pulse = (SRC / "pulse.js").read_text()
    assert "govSize()" in pulse and "Bond hedge health" not in pulse
    assert "Run ${xx(g)} gross`" in (SRC / "decide.js").read_text()   # only as the fallback when the engine is absent


def test_today_shows_limits_and_the_honest_run_state():
    body, land = (SRC / "body.html").read_text(), (SRC / "landing.js").read_text()
    assert 'id="t7-limits"' in body and "function renderLimits(" in land and 'renderLimits(O.now, O)' in land
    assert "Expected shortfall budget" in land and "Scenario loss limit" in land
    assert "Daily run on GitHub Actions" not in body and "daily run not yet live" in body
    head = (SRC / "head.html").read_text()
    assert re.search(r"^\.fund \{", head, re.M) is None and ".fundgrid {" in head      # the Fundamentals table is a table again
    assert 'class="fundgrid" id="fund"' in body and 'table class="fund" id="fund-table"' in body


def test_the_level_store_is_dated_and_read_by_the_rules():
    data = (SRC / "data.js").read_text()
    for k in ("vix", "vxn", "y10", "real10", "breakeven10", "hy_oas", "ccc_oas", "brent"):
        assert re.search(r'key: "%s", date: "2026-10-2[23]"' % k, data), k
    assert "function levelStatic(key)" in data and 'vxn: [28.30, "Oct 23"]' in data
    dec = (SRC / "decide.js").read_text()
    assert "levelStatic(k)" in dec and "function rocNewerLevel(" in dec
    assert '[4.0, "Bonds hedged 1 month in 8"' not in dec                       # no rule line that no rule uses


def test_overlay_factors_count_in_the_deflation():
    assert decide.N_TRIED == len(decide.CONFIGS) + 4 + 4 + 5 + 11 == 28          # v0.25 counts its borrowed and RL variants too
