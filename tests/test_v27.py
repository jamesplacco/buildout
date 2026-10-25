"""v0.27: the nowcast. Facts published early are used only after they were knowable, the TSMC figures agree with
TSMC's own printed growth, the report days match public release dates, every hypothesis tried is in the
multiple-testing count, random signals run beside the real ones, and the desk sits beside the call."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from buildout import mcp_server, mind, nowcast as N

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
BANNED = (chr(0x2014), "inter" "section", "load" "-bearing")


def _snap27() -> dict:
    s = (SRC / "snap27.js").read_text()
    i = s.index("const SNAP27 = ")
    return json.loads(s[i + len("const SNAP27 = "):s.index(";\n", i)].replace("<\\/", "</"))["nowcast"]


def test_tsmc_figures_agree_with_tsmcs_printed_growth_and_are_used_after_release():
    T = N.tsmc_monthly()
    v = T["revenue_ntd_m"].astype(float)
    yoy = (v / v.shift(12) - 1) * 100
    ok = yoy.notna()
    assert ok.sum() >= 120 and (yoy[ok] - T.loc[ok, "yoy_printed_pct"]).abs().max() <= 0.051
    assert (T["avail"] > T.index + pd.offsets.MonthEnd(0)).all() and (T["avail"].dt.day == N.TSMC_AVAIL_DAY).all()


def test_signals_are_known_before_the_cutoff():
    T = N.tsmc_monthly()
    end, cut = pd.Timestamp("2025-07-01"), pd.Timestamp("2025-08-08")          # July's figure is out on Aug 11
    g, aligned = N._tsmc_growth(T, end, cut)
    assert not aligned
    g2, aligned2 = N._tsmc_growth(T, end, pd.Timestamp("2025-08-12"))
    assert aligned2 and np.isfinite(g2)
    # the capex signal reads only hyperscaler reports dated on or before the cutoff
    E = pd.DataFrame({"ticker": list(N.HYPERSCALERS) * 2, "period_end": [pd.Timestamp("2025-03-31")] * 4 + [pd.Timestamp("2025-06-30")] * 4,
                      "d0": [pd.Timestamp("2025-04-30")] * 4 + [pd.Timestamp("2025-07-31")] * 3 + [pd.Timestamp("2025-08-20")],
                      "capex": [10.0] * 4 + [20.0] * 4, "capex_prev_y": [5.0] * 8})
    assert abs(N._capex_growth(E, pd.Timestamp("2025-08-01")) - np.log(2)) < 1e-9          # Q2 not complete by Aug 1: Q1's growth
    assert abs(N._capex_growth(E, pd.Timestamp("2025-08-21")) - np.log(4)) < 1e-9


def test_report_days_come_from_releases_on_record():
    O = _snap27()
    D = O["events"]["date_check"]
    assert D["verified_on_record"] == len(D["verified"]) >= 20               # independently verified dates are all on record
    R, timing = N.release_dates()
    assert set(R["ticker"]) >= set(N.TARGETS) and R["source"].notna().all()
    idx = pd.bdate_range("2025-01-01", "2025-12-31")
    k = N.reaction_day(idx, pd.Timestamp("2025-11-19"), "after_close")
    assert idx[k] == pd.Timestamp("2025-11-20") and idx[N.reaction_day(idx, pd.Timestamp("2025-11-19"), "before_open")] == pd.Timestamp("2025-11-19")
    assert O["events"]["data_break_quarters"] >= 1 and all(b["why"] for b in O["events"]["data_breaks"])


def test_every_hypothesis_is_counted_and_random_signals_run_beside_them():
    O = _snap27()
    assert O["n_hypotheses"] == len(O["tests"]) == len(N.GROUPS) * (len(N.FEATS) + len(N.PRE_SIGNALS) * 2 + len(N.POST_SIGNALS) + len(N.TS_SIGNALS))
    assert {t.get("design") for t in O["tests"] if t["kind"] == "returns"} == {"within seasons", "across quarters"}
    assert all(t.get("strategy", {}).get("note") or not t.get("strategy") for t in O["tests"] if t.get("window") == "runup")   # the run-up is never traded
    assert 0.1 < O["power"]["min_detectable_corr"] < 0.5
    for t in O["tests"]:
        if t["pass_bh"]:
            assert t["p"] <= O["bh_cut"]
        if t.get("design") == "within seasons" and t.get("by_stratum"):
            ps = [v["p"] for v in t["by_stratum"].values()]
            assert set(t["by_stratum"]) == set(N.STRATA)
            assert t["p"] == (max(ps) if all(p is not None for p in ps) else None)     # it must hold however a season is drawn
        if t["kind"] == "accuracy" and t.get("p_clustered") is not None:
            assert t["p"] == t["p_clustered"]
    F = O["fakes"]
    assert F["tried"] >= 100 and F["passed_at_cut"] <= max(1, 0.02 * F["tried"])
    assert 0.0 <= F["share_p_below_05"] <= 0.12                                   # the permutation test is not anti-conservative


def test_today_is_research_only_and_honest_about_what_is_known():
    O = _snap27()
    book = [x for x in O["today"] if x["in_book"]]
    assert {x["ticker"] for x in book} <= set(N.BOOK) and len(book) >= 6
    for x in O["today"]:
        if x["signals"]["d_tsmc"] is not None:
            assert x["signals"]["tsmc_aligned"]                                   # never a stale quarter passed off as the next one
        g = x["group"]
        if x.get("nowcast_acc") is not None and not O["models"][g]["beats_persistence"]:
            assert x["nowcast_acc"] == 0 and x["nowcast_basis"].startswith("persistence")
    assert "spcx" in O["universe"]["book_without_history"]


def test_the_desk_is_beside_the_call_and_in_the_tools():
    boot, body = (SRC / "boot.js").read_text(), (SRC / "body.html").read_text()
    groups = dict(re.findall(r'(\w+): \{ name: "[^"]+", views: \[([^\]]+)\] \}', boot))
    assert groups["today"].startswith('"desk", "nowcast"')
    assert 'id="view-nowcast"' in body and 'id="t7-nowcast"' in body and "renderNowcastToday" in boot
    assert any(d[0] == "nowcast" for d in mind.DESKS)
    assert '"snap27.js", "nowcast.js"' in (ROOT / "scripts" / "assemble_page.py").read_text()
    assert "nowcast" in mcp_server.TOOLS and not any(re.search(r"place|execute|submit|send_order", n) for n in mcp_server.TOOLS)
    js = (SRC / "nowcast.js").read_text()
    for b in BANNED:
        assert b not in js.lower() and b not in json.dumps(_snap27(), ensure_ascii=False).lower() and b not in (ROOT / "buildout" / "nowcast.py").read_text().lower()


def test_a_passing_return_result_carries_its_robustness_and_real_time_check():
    O = _snap27()
    for t in O["tests"]:
        if t["kind"] == "returns" and t["pass_bh"] and t.get("design") == "within seasons":
            r = t["robust"]
            assert abs(r["corr_with_order"]) < 0.3 and np.sign(r["partial_corr_given_order"]) == np.sign(t["corr"])
            assert r["loo_min"] is not None and np.sign(r["loo_min"]) == np.sign(r["loo_max"])
            if t["window"] == "event":
                assert t["realtime"]["note"].startswith("built after") and t["realtime"]["n"] >= 20
