"""v0.26: the edge lab. The hypothesis factory's shipped run is internally consistent (the funnel only narrows, the
placebo runs beside the real candidates at every stage, survivors carry their test years and mechanisms), the
unusual data are lagged to when they were knowable, and the desk is prominent on the page."""
from __future__ import annotations

import json
import re
from pathlib import Path

from buildout import discovery, mcp_server, mind, unusual

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
BANNED = (chr(0x2014), "inter" "section", "load" "-bearing")


def _snap26() -> dict:
    s = (SRC / "snap26.js").read_text()
    i = s.index("const SNAP26 = ")
    return json.loads(s[i + len("const SNAP26 = "):s.index(";\n", i)].replace("<\\/", "</"))


def test_the_funnel_only_narrows_and_runs_real_beside_placebo():
    D = _snap26()["discovery"]
    F = D["funnel"]
    real, fake = [s["real"] for s in F], [s["placebo"] for s in F]
    assert real == sorted(real, reverse=True) and fake == sorted(fake, reverse=True)
    assert real[0] == D["universe"]["hypotheses"] >= 10000 and fake[0] >= 10000
    by = {s["key"]: s for s in F}
    assert by["distinct"]["real"] == len(D["edges"])
    assert D["placebo"]["counts"]["distinct"] < by["distinct"]["real"]          # fewer fakes than real survivors, or the factory finds noise
    assert 0 < D["bh_p_threshold"] < 0.01


def test_every_survivor_carries_its_record_and_only_tested_edges_count():
    D = _snap26()["discovery"]
    for e in D["edges"] + D["early"]["edges"]:
        assert e["breadth"]["pass"] and e["validation"]["net"]["t"] > 0, e["name"]
        assert e["mechanism"]["status"] and isinstance(e["mechanism"]["concepts"], list)
        if e["test"].get("net") and e["test"]["net"].get("t") is not None:
            v_end, t_start = e["validation"]["period"].split(" to ")[1], e["test"]["period"].split(" to ")[0]
            assert t_start > v_end, e["name"]
        assert e["test"]["tested"] == (e["test"]["cover"] >= 0.5 and (e["test"]["net"].get("n") or 0) >= 12), e["name"]   # audit B1
    f = {r["key"]: r for r in D["funnel"]}
    assert f["test_data"]["real"] == sum(e["test"]["tested"] for e in D["edges"])
    assert D["book"]["edges"] == f["test_data"]["real"]                         # the book holds tested edges only


def test_the_out_of_sample_book_is_reported_with_its_fragility():
    E = _snap26()["discovery"]["early"]
    B = E["book"]["test"]
    assert E["calendar"]["validation_to"] < B["from"] and B["deflated"]["n_trials"] == E["hypotheses"] and 0 <= B["deflated"]["dsr"] <= 1
    assert {"largest_month", "without_largest_month", "vol_by_year"} <= set(B)                       # audit B2
    assert 0.05 < B["vol_annual"] < 0.15                                        # EWMA scaling with a floor lands near the 10% aim (audit M4)
    assert E["book"]["test_concentration"]["independent_bets_test"] <= E["book"]["edges"]
    assert E["book"]["naive"]["edges"] >= E["book"]["edges"]


def test_p_values_are_calibrated_on_nulls_for_every_rule_kind():
    P = _snap26()["discovery"]["placebo"]
    cal, nl = P["calibration"], P["null"]
    assert nl["replicates"] >= 3 and nl["hypotheses"] > 100000 and nl["block_months"] == discovery.LAG
    assert {"own history", "compositions", "cross-asset and macro", "unusual data"} <= set(nl["by_kind"])   # audit B3: no kind without a null
    for g in ("own", "signal"):
        c = cal[g]
        assert c["lambda"] >= 1 and c["null_share_at_p_raw"]["0.001"] > 0.001                         # nominal p-values were too small (M1)
        assert abs(c["null_share_at_p_calibrated"]["0.001"] - 0.001) < 0.0003
    assert _snap26()["discovery"]["bh_p_threshold"] < P["bh_p_threshold_uncalibrated"]
    assert P["null_fdr_at_cut"] is not None and P["null_fdr_at_cut"] <= 0.05 < P["null_fdr_at_bh_cut"]       # the cut holds the false share where it is used (re-audit M2)


def test_composites_must_beat_their_parents_and_the_long_block_drops_interpolated_years():
    from buildout.discovery import LONG_MASKS
    assert LONG_MASKS["bonds"] == "1953-01" and LONG_MASKS["dividends"] == "1926-01"
    D = _snap26()["discovery"]
    for e in D["edges"] + D["early"]["edges"]:
        if e["kind"] == "compositions":
            assert e["timing_parents"] >= 1, e["name"]
    assert "long_block_masks" in D["data_notes"]
    pa = _snap26().get("preaudit")
    assert pa and pa["distinct"] > len(D["edges"])                              # the page shows what the audit changed


def test_the_averaging_trap_is_measured():
    N = _snap26()["discovery"]["data_notes"]
    rows = N["own_one_month_signal_by_skip"]
    assert rows and all(r["t_lag1"] > r["t_lag2"] for r in rows)                # the skip month removes most of the artifact


def test_unusual_data_are_lagged_and_documented():
    M = _snap26()["unusual"]
    assert len(M) >= 60
    for k, m in M.items():
        assert m["family"] and m["frequency"], k
        assert m.get("computed") or (isinstance(m["lag_months"], int) and m["lag_months"] >= 1), k     # nothing downloaded is used the month it describes
        if not m.get("computed"):
            assert str(m["url"]).startswith("https://"), k
    assert {"climate", "astronomy", "hazards", "shipping"} <= {m["family"] for m in M.values()}
    assert callable(unusual.download) and callable(discovery.build)


def test_the_edge_lab_is_on_the_page_and_in_the_mind():
    boot, body = (SRC / "boot.js").read_text(), (SRC / "body.html").read_text()
    groups = dict(re.findall(r'(\w+): \{ name: "[^"]+", views: \[([^\]]+)\] \}', boot))
    assert groups["engine"].startswith('"explained", "edges"')
    assert 'id="view-edges"' in body and 'id="t7-edges"' in body and "renderEdgesToday" in boot
    assert any(d[0] == "edges" for d in mind.DESKS)
    assert '"snap26.js", "edges.js"' in (ROOT / "scripts" / "assemble_page.py").read_text()
    assert "edge_lab" in mcp_server.TOOLS
    js = (SRC / "edges.js").read_text()
    for b in BANNED:
        assert b not in js.lower() and b not in json.dumps(_snap26(), ensure_ascii=False).lower()
