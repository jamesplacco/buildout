"""v0.28: the filings engine is wired into the page, the tools and the weekly GitHub run; the shipped snapshot says
honestly whether a real run exists; its validation found the planted edge; nothing in the run reaches the network
except through collect()."""
from __future__ import annotations

import json
import re
from pathlib import Path

from buildout import filings, mcp_server, mind

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
BANNED = (chr(0x2014), "inter" "section", "load" "-bearing")


def _snap28() -> dict:
    s = (SRC / "snap28.js").read_text()
    i = s.index("const SNAP28 = ")
    return json.loads(s[i + len("const SNAP28 = "):s.index(";\n", i)].replace("<\\/", "</"))["filings"]


def test_the_snapshot_is_honest_about_its_status_and_validated():
    O = _snap28()
    assert O["status"] in ("run", "awaiting first run") and (O["run"] is None) == (O["status"] == "awaiting first run")
    assert len(O["signals"]) == len(filings.SIGNALS) and all(s["reference"] and s["published"] for s in O["signals"])
    V = O["validation"]
    assert V["planted"]["pass_bh"] and V["planted"]["as_published"] and V["planted"]["supported"] and sum(n["pass_bh"] for n in V["noise"]) <= 1
    assert (V["fakes"]["share_p_below_05"] or 0) <= 0.2 and V["checks"]["dual_class_rows_merged"] > 0
    assert abs(V["checks"]["split_issuance_with_splits"]) < 0.05 < abs(V["checks"]["split_issuance_without"])
    C = O["calibration"]["pooled"]                                  # across worlds with no edge, the test is honest and the old one is not
    assert C["tests_p_below_05"] <= 0.09 and C["persistent_noise_p_below_05"] <= 0.1 and C["factor_tilt_p_below_05"] <= 0.12 < C["factor_tilt_reassign_p_below_05"]
    assert all(x["share_p_below_05"] is None or 0.0 <= x["share_p_below_05"] <= 0.09 for x in O["calibration"]["sparse"])
    if O["run"]:
        assert not O["run"]["meta"].get("synthetic") and O["run"]["n_hypotheses"] == len(O["run"]["tests"])


def test_build_never_touches_the_network():
    src = (ROOT / "buildout" / "filings.py").read_text()
    body = src[src.index("def build("):src.index("LIMITATIONS = [")]
    assert "sec_get" not in body and "http." not in body and "datahub" not in body


def test_the_desk_the_tools_and_the_weekly_run():
    boot, body = (SRC / "boot.js").read_text(), (SRC / "body.html").read_text()
    groups = dict(re.findall(r'(\w+): \{ name: "[^"]+", views: \[([^\]]+)\] \}', boot))
    assert groups["evidence"].startswith('"inventory"') and '"filings"' in groups["evidence"]         # v0.31: the Inventory opens Evidence
    assert 'id="view-filings"' in body and "renderFilings" in boot and any(d[0] == "filings" for d in mind.DESKS)
    assert '"snap28.js", "filings.js"' in (ROOT / "scripts" / "assemble_page.py").read_text()
    assert "filings_engine" in mcp_server.TOOLS and not any(re.search(r"place|execute|submit|send_order", n) for n in mcp_server.TOOLS)
    wf = (ROOT / ".github" / "workflows" / "filings.yml").read_text()
    assert "SEC_USER_AGENT" in wf and "python -m buildout filings" in wf and "actions/cache" in wf and "DATABENTO" not in wf
    for f in (SRC / "filings.js", ROOT / "buildout" / "filings.py", ROOT / ".github" / "workflows" / "filings.yml"):
        t = f.read_text().lower()
        for b in BANNED:
            assert b not in t, (f, b)
