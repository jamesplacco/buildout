"""v0.29: the futures engine is wired into the page, the tools and the weekly GitHub run; the shipped snapshot holds a
real run on pysystemtrade's published prices and the engine's validation; nothing in a build reaches the network."""
from __future__ import annotations

import json
import re
from pathlib import Path

from buildout import futures, mcp_server, mind

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
BANNED = (chr(0x2014), "inter" "section", "load" "-bearing")


def _snap29() -> dict:
    s = (SRC / "snap29.js").read_text()
    i = s.index("const SNAP29 = ")
    return json.loads(s[i + len("const SNAP29 = "):s.index(";\n", i)].replace("<\\/", "</"))["futures"]


def test_the_snapshot_holds_a_real_long_run_and_an_honest_verdict_for_every_test():
    O = _snap29()
    L = O["runs"]["pysystemtrade"]
    assert L and not L["meta"].get("synthetic") and L["meta"]["source"] == "pysystemtrade" and L["universe"]["markets"] >= 30
    assert L["n_hypotheses"] == len(L["tests"]) and all(t["verdict"] in O["verdicts"] for t in L["tests"])
    for t in L["tests"]:
        if t["supported"]:
            assert t["pass_bh"] and t["alpha_p"] <= 0.05 and t["same_sign_both_halves"] and (t["since_publication"].get("sharpe") or 0) >= O["assumptions"]["faded_sharpe"]
            assert t["design"] != "xs" or t["within_class"]["sharpe_net"] > 0
        if t["pass_bh"]:
            assert t["p"] <= L["bh_cut"]
    assert {u["signal"] for u in L["untested"]} >= {"hedging_pressure"}          # positioning needs the CFTC, not reachable here


def test_the_engine_finds_a_planted_edge_and_the_test_is_calibrated():
    O = _snap29()
    V = O["validation"]
    assert V["planted"]["carry:xs"]["pass_bh"] and sum(t["pass_bh"] for t in V["others"]) <= 1
    C = O["calibration"]["pooled"]
    assert C["worlds"] >= 8 and C["tests_p_below_05"] <= 0.09 and C["fakes_p_below_05"] <= 0.09
    F = O["runs"]["pysystemtrade"]["fakes"]
    assert F["runs"] >= 100 and F["share_p_below_05"] <= 0.12


def test_build_never_touches_the_network():
    src = (ROOT / "buildout" / "futures.py").read_text()
    body = src[src.index("def month_panel("):src.index("def carver_download(")]
    assert "http." not in body and "import databento" not in body and "sec_get" not in body


def test_the_desk_the_tools_and_the_weekly_run():
    boot, body = (SRC / "boot.js").read_text(), (SRC / "body.html").read_text()
    groups = dict(re.findall(r'(\w+): \{ name: "[^"]+", views: \[([^\]]+)\] \}', boot))
    assert '"futures"' in groups["markets"] and 'id="view-futures"' in body and "renderFutures" in boot and any(d[0] == "futures" for d in mind.DESKS)
    assert '"snap29.js", "futures.js"' in (ROOT / "scripts" / "assemble_page.py").read_text()
    assert "futures_engine" in mcp_server.TOOLS and not any(re.search(r"place|execute|submit|send_order", n) for n in mcp_server.TOOLS)
    wf = (ROOT / ".github" / "workflows" / "futures.yml").read_text()
    assert "DATABENTO_API_KEY" in wf and "python -m buildout futures --source databento" in wf and "secrets.DATABENTO_API_KEY" in wf
    assert len({v[3] for v in futures.MARKETS.values()}) == len(futures.MARKETS)            # one CFTC code per market
    for f in (SRC / "futures.js", ROOT / "buildout" / "futures.py", ROOT / ".github" / "workflows" / "futures.yml", SRC / "snap29.js"):
        t = f.read_text().lower()
        for b in BANNED:
            assert b not in t, (f, b)
