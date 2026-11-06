"""v0.38: the track record (ledger, walk-forward, sizing), the hedge study's data hygiene, the value-creation levers, and
the home page as the default view."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import ledger, levers, track

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"


def _book(asof: str, size: float = 0.58) -> dict:
    return {"asof": asof, "size": size, "binding": "drawdown_cap", "frontier": [{"gross": size, "short": 0.0, "meets": True}, {"gross": 1.0, "short": 0.85, "meets": True}]}


def test_ledger_chain_appends_verifies_and_rejects_tampering(tmp_path):
    P = tmp_path / "calls.jsonl"
    assert ledger.verify(P)["ok"] and ledger.read(P) == []
    e1 = ledger.append(_book("2026-10-23"), "0.38.0", P, ts="2026-11-03T15:00:00Z")["entry"]
    e2 = ledger.append(_book("2026-11-03", 0.6), "0.38.0", P, ts="2026-11-04T15:00:00Z")["entry"]
    assert e2["prev"] == e1["hash"] and e2["seq"] == 2 and e1["call"]["menu_high"]["short"] == 0.85
    assert not ledger.append(_book("2026-11-03", 0.7), "0.38.0", P, ts="2026-11-04T16:00:00Z")["appended"]   # same data date
    assert ledger.verify(P)["ok"]
    lines = P.read_text().splitlines()
    first = json.loads(lines[0]); first["call"]["size"] = 0.99                                             # rewrite history
    P.write_text("\n".join([json.dumps(first)] + lines[1:]) + "\n")
    assert not ledger.verify(P)["ok"]
    with pytest.raises(RuntimeError):
        ledger.append(_book("2026-11-05"), "0.38.0", P)


def test_ledger_never_backdates_a_call():
    e = ledger.make_entry(_book("2026-10-23"), "0.38.0", None, ts="2026-11-03T15:38:15Z")
    assert e["effective_from"] == "2026-11-04"                     # the next trading day after writing, not after the data
    assert ledger.next_trading_day("2026-11-06") == "2026-11-09"   # Friday -> Monday


def test_committed_ledger_verifies():
    v = ledger.verify()
    assert v["ok"] and v["entries"] >= 1, v
    for e in ledger.read():
        assert e["effective_from"] > e["ts_utc"][:10] and e["effective_from"] > e["data_asof"]


def test_walk_forward_cuts_after_a_volatility_jump_and_has_no_lookahead():
    c = track.synthetic_check()
    assert c["cuts_after_jump"] and c["no_lookahead"]


def test_history_treats_zero_padding_as_missing(monkeypatch):
    idx = pd.date_range("2022-01-01", periods=30, freq="MS")
    sh = pd.DataFrame({"Date": idx.strftime("%Y-%m-%d"), "SP500": np.linspace(4000, 4600, 30), "Dividend": [60.0] * 20 + [0.0] * 10,
                       "Consumer Price Index": list(np.linspace(280, 300, 25)) + [0.0] * 5, "Long Interest Rate": [3.5] * 25 + [0.0] * 5})
    cpi = pd.DataFrame({"Date": idx.strftime("%Y-%m-%d"), "Index": np.linspace(280, 305, 30)})
    y10 = pd.DataFrame({"Date": idx.strftime("%Y-%m-%d"), "Rate": [3.5] * 30})
    files = {"s-and-p-500": sh, "cpi-us": cpi, "bond-yields-us-10y": y10}
    monkeypatch.setattr(track, "_gh", lambda path: files[path.split("/")[0]].copy())
    H = track.monthly_history()
    assert H.index[-1] == idx[-1]                       # runs to the end on the filled series
    assert (H["y10"] > 0).all() and H["bond"].abs().max() < 0.05 and (H["infl"] > -0.5).all()


def test_regime_rows_label_the_last_era_by_its_data():
    T = json.loads(re.search(r"const SNAP38 = (\{.*\});", (SRC / "snap38.js").read_text()).group(1))
    labels = [r["regime"] for r in T["regimes"]["rows"]]
    last = [l for l in labels if l.startswith("2021 to ")][0]
    assert last == "2021 to " + T["regimes"]["to"][:4]
    for r in T["regimes"]["rows"]:
        assert r["bond_in_selloffs"] is None or abs(r["bond_in_selloffs"]) < 0.10, r     # no fictitious 33% bond month


def test_snap38_keeps_the_three_records_apart():
    T = json.loads(re.search(r"const SNAP38 = (\{.*\});", (SRC / "snap38.js").read_text()).group(1))
    assert {"backtest", "pit", "hindsight", "live", "ledger", "regimes", "alternatives", "weeks", "sizing_path"} <= set(T)
    for k in ("call", "call_short", "product", "vm_rule", "bond30", "hold"):
        p = T["pit"]["policies"][k]
        assert {"net", "gross", "meta", "monthly"} <= set(p) and p["net"]["from"] >= "2018"
    assert T["ledger"]["verify"]["ok"] and T["tearsheet_pdf_b64"].startswith("JVBER")   # a PDF
    assert len(T["weeks"]) >= 6


def test_lever_bridge_reconciles_and_leverage_swing_is_honest():
    for q in ({}, {"margin_gain_yr": 0.02}, {"leverage": 0.5}, {"bolt_on_ebitda": 0, "years": 3}, {"sweep": False}):
        m = levers.model(q)
        assert m["bridge"]["total"] == pytest.approx(m["exit"]["equity"] - m["entry"]["equity_total"], rel=1e-9, abs=1e-6)
    m = levers.model()
    assert m["sensitivity"][0]["ten_pct"] == pytest.approx(1.0, abs=1e-9)       # 90% debt: a 10% EBITDA move is the whole equity
    assert levers.equity_sensitivity(100, 0) == pytest.approx(0.10)
    assert levers.DEFAULTS["platform_multiple"] == 6.0                         # the checked figure, not the plan's 7 to 8x
    assert not m["exit"]["platform"] and m["exit"]["multiple"] == levers.DEFAULTS["entry_multiple"]
    assert levers.model({"margin_gain_yr": 0.02})["exit"]["platform"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_lever_model_js_matches_python():
    src = (SRC / "levers.js").read_text()
    js = "const fx=(v,d)=>v.toFixed(d);\n" + src[src.index("const LV_DEFAULTS"):src.index("  const LV_SLIDERS")] + \
         "\nconst cases=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(cases.map(c=>leverModel(c))));"
    cases = [{}, {"margin_gain_yr": 0.02}, {"leverage": 0.7, "rate": 0.08, "sweep": False}, {"bolt_on_ebitda": 0, "years": 3}]
    out = json.loads(subprocess.run(["node", "-e", js], input=json.dumps(cases), capture_output=True, text=True, check=True).stdout)
    for c, g in zip(cases, out):
        m = levers.model(c)
        assert g["moic"] == pytest.approx(m["moic"], rel=1e-9) and g["bridge"]["total"] == pytest.approx(m["bridge"]["total"], rel=1e-9)
        assert all(a["ebitda"] == pytest.approx(b["ebitda"], rel=1e-9) for a, b in zip(g["rows"], m["rows"]))


def test_levers_data_is_sourced_and_generic():
    t = (SRC / "levers_data.js").read_text()
    D = json.loads(re.search(r"const LEVERS_DATA = (\{.*\});", t).group(1))
    assert len(D["claims"]) >= 15 and all(c["source"].startswith("http") for c in D["claims"])
    assert {c["verdict"] for c in D["claims"]} <= {"Confirmed", "Overstated", "Wrong", "Unverifiable"}
    assert len(D["companies"]) == 9 and all(len(c["cells"]) == len(D["levers_cols"]) == 6 for c in D["companies"])
    assert all(c["urls"] for c in D["company_sources"])
    page = t + (SRC / "levers.js").read_text() + (SRC / "trackdesk.js").read_text()
    for banned in ("Hollencrest", "Pellizon", "Timmy", "jamesplacco"):
        assert banned not in page


def test_home_is_the_default_view_and_new_views_are_wired():
    boot = (SRC / "boot.js").read_text()
    body = (SRC / "body.html").read_text()
    views = (SRC / "views.js").read_text()
    for v in ("home", "track", "hedgetest", "memos", "levers"):
        assert f'id="view-{v}"' in body and re.search(rf"\b{v}: ", views), v
    assert 'today: { name: "Today", views: ["home",' in boot
    scripts = (ROOT / "scripts" / "assemble_page.py").read_text()
    assert '"snap38.js", "trackdesk.js", "memos.js", "levers_data.js", "levers.js", "execdesk.js"' in scripts


def test_a_bad_pull_stops_the_book(tmp_path):
    from buildout import book as bk
    files = sorted({bk.FILE.get(k, k.lower()) for k in bk.BOOK} | set(bk.FACTOR_ETF.values()))
    d = pd.bdate_range("2026-01-02", periods=60)
    good = pd.DataFrame({"date": d.strftime("%Y-%m-%d"), "open": 10.0, "high": 10.5, "low": 9.5, "close": np.linspace(10, 12, 60), "volume": 1e6})
    for f in files:
        good.to_csv(tmp_path / f"{f}.csv", index=False)
    assert len(bk.download(tmp_path)) == len(files) and bk.LAST_VALIDATION["ok"]
    bad = pd.concat([good, good.tail(1)])                     # a duplicated last bar
    bad.to_csv(tmp_path / f"{files[0]}.csv", index=False)
    with pytest.raises(ValueError, match="duplicate_dates"):
        bk.download(tmp_path)
    assert len(bk.download(tmp_path, validate=False)) == len(files)
