"""v0.34: the private credit lens. The queue model reproduces the fills Blue Owl reported; the markdown identity
is exact; every observation is dated and sourced; the scorecard's grades follow its thresholds; the page's snapshot
is the engine's own; the MCP tool is read-only; house style."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from buildout import private_credit as PC

ROOT = Path(__file__).resolve().parents[1]


def _snap():
    s = (ROOT / "site" / "src" / "snappc.js").read_text()
    i = s.index("const SNAPPC = ")
    return json.loads(s[i + 15:s.index(";\n", i)].replace("<\\/", "</"))["credit"]


def test_the_queue_model_reproduces_the_reported_fills():
    for fund in ("ocic", "otic"):
        q = PC.queue_check(PC.OBS[fund])
        assert q["model_matches"] and abs(q["fill"] - q["fill_reported"]) < 0.001, fund
    q = PC.queue(0.04)                                                       # under the cap: everyone is paid
    assert q["fill"] == 1.0 and q["quarters_to_90pct_exit"] == 0.0
    q = PC.queue(0.39)
    assert 16 < q["quarters_to_90pct_exit"] < 17 and abs((1 - q["fill"]) ** q["quarters_to_90pct_exit"] - 0.1) < 1e-9


def test_the_markdown_identity_is_exact():
    """Equity E = 100, debt D = 111: the market pays 77.4 for the equity; if the debt is whole the assets are worth
    211 - 22.6, a markdown of 22.6 / 211."""
    m = PC.implied_markdown(0.774, 1.11, 0.008)
    assert m["implied_asset_markdown"] == pytest.approx(0.226 / 2.11) and m["multiple_of_non_accruals_fv"] == pytest.approx(0.226 / 2.11 / 0.008)
    assert PC.implied_markdown(1.0, 1.0)["implied_asset_markdown"] == 0.0


def test_every_observation_is_dated_and_sourced():
    for k, o in PC.OBS.items():
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", o["asof"]), k
        assert o["src"] and all(s in PC.SRC for s in o["src"]), k
    for k, (title, url) in PC.SRC.items():
        assert url.startswith("https://") and len(title) > 20, k
    r = PC.report("2026-11-01")
    assert r["latest_observation"] == "2026-09-30" and set(r["sources"]) == set(PC.SRC)


def test_the_scorecard_follows_its_thresholds():
    sc = PC.scorecard()
    assert len(sc) == len(PC.GAUGES) == 8
    for r in sc:
        g = PC.grade(r["value"], r["green"], r["red"], r["direction"])
        assert r["grade"] == g and g in ("green", "amber", "red")
    by = {r["id"]: r for r in sc}
    assert by["ocic_queue"]["grade"] == "red" and by["software"]["grade"] == "green" and by["obdc_cover"]["grade"] == "amber"
    assert PC.grade(0.04, 0.05, 0.15, "low") == "green" and PC.grade(0.10, 0.05, 0.15, "low") == "amber" and PC.grade(0.9, 0.95, 0.85, "high") == "amber"


def test_income_and_loss_gap_arithmetic():
    c = PC.dividend_cover()
    assert c["dividend"] == pytest.approx(0.33) and c["cover"] == pytest.approx(0.36 / 0.33) and c["cash_cover_est"] < c["cover"] < 1.1
    g = PC.loss_gap()
    assert g["hard_default_rate"] == pytest.approx(0.063 * 0.12) and g["hard_loss_at_severity"] == pytest.approx(0.063 * 0.12 * 0.4)
    y = PC.net_yield_at_sector_default()
    assert y["over_y10"] < 0 < y["net"] and abs(y["over_bill3m"]) < 0.005   # at 6.3% the fund nets about the bill
    assert PC.fre_from_undeployed()["uplift"] == pytest.approx(400e6 / (427.5e6 * 4))


def test_the_page_snapshot_is_the_engines_own_and_the_tool_is_read_only():
    S = _snap()
    r = PC.report(S["asof"])
    assert S["headline"] == r["headline"] and S["scorecard"] == json.loads(json.dumps(r["scorecard"])) and S["reds"] == r["reds"]
    assert S["findings"] == PC.summary(r)
    from buildout import mcp_server
    assert "private_credit" in mcp_server.TOOLS and mcp_server.TOOLS["private_credit"][3]["readOnlyHint"] is True
    fn = mcp_server.TOOLS["private_credit"][0]
    out = fn(None, {"part": "liquidity"})
    assert out["liquidity"]["ocic"]["model_matches"] is True
    with pytest.raises(Exception):
        fn(None, {"part": "orders"})
    page = (ROOT / "site" / "src" / "body.html").read_text()
    assert 'id="view-credit"' in page and 'id="pc-score"' in page
    boot = (ROOT / "site" / "src" / "boot.js").read_text()
    assert '"positions", "credit", "swans"' in boot


def test_house_style():
    for p in (PC.__file__, ROOT / "site" / "src" / "credit.js", ROOT / "scripts" / "snapshot_pc.py"):
        src = open(p).read().lower()
        for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
            assert b not in src, p


def test_the_cohort_runs_the_same_model_and_its_inversions_check():
    """v0.35: requests inferred as cap / fill where only the fill was reported; checked on two funds that reported both."""
    K = PC.cohort()
    assert all(c["matches"] for c in K["checks"]) and len(K["checks"]) == 2
    for q in K["queues"]:
        if q["queued"]:
            assert abs(q["fill"] - PC.CAP / q["requests"]) < 0.02 or q["requests_basis"].startswith("reported"), q["fund"]
            assert q["quarters_to_90pct_exit"] > 0
        else:
            assert q["fill"] == 1.0 and q["quarters_to_90pct_exit"] == 0.0
        assert all(s in PC.SRC for s in q["src"]) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", q["asof"])
    assert K["queues"][0]["sponsor"] == "Blue Owl" and K["read"]["blue_owl_max_requests"] > K["read"]["peers_max_requests"]
    for l in K["listed"]:
        assert all(s in PC.SRC for s in l["src"])
        if l["cover"] is not None:
            assert l["cover"] == pytest.approx(l["earnings_ps"] / l["dividend_ps"])
    assert set(K["read"]["peers_cover_below_1"]) == {"Ares Capital (ARCC)", "Blackstone Secured Lending (BXSL)"}
    S = _snap()
    assert S["cohort"]["read"] == json.loads(json.dumps(K["read"]))
