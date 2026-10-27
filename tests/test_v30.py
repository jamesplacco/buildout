"""v0.30: the book, sized and measured. The shipped snapshot holds a real run on the nine names' own prices; the Desk's
call is that book's size; the decision engine's audited numbers are fixed (deflated Sharpe, the stress flip, HAC t);
index puts are priced off the VXN; the shared analytics no longer understate a book with a late listing."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import book, decide, hedgebook, mcp_server, mind, reasoner
from buildout.analytics import exposures, returns, risk

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
BANNED = (chr(0x2014), "inter" "section", "load" "-bearing")


def _snap(name: str, var: str, key: str) -> dict:
    s = (SRC / name).read_text()
    i = s.index(f"const {var} = ")
    return json.loads(s[i + len(f"const {var} = "):s.index(";\n", i)].replace("<\\/", "</"))[key]


def test_the_snapshot_is_a_real_run_with_consistent_sizes():
    B = _snap("snap30.js", "SNAP30", "book")
    assert not B["meta"].get("synthetic") and B["days"] > 2000 and set(B["weights"]) == set(book.BOOK)
    S = B["sizes"]
    assert B["size"] == pytest.approx(min(S.values())) and B["binding"] == min(S, key=S.get)
    assert S["es_budget"] == pytest.approx(B["limits"]["es_budget"] / B["tail"]["es95"]["governing"], abs=1e-5)
    assert B["tail"]["es95"]["governing"] == max(B["tail"]["es95"][k] for k in ("historical", "filtered", "student_t"))
    assert 0.1 < B["risk"]["vol"] < 0.6 and 0.5 < B["exposure"]["market"] < 2.5
    assert len(B["findings"]) >= 5 and B["validation"]["mean_abs_beta_error"] < 0.1
    for f in B["findings"]:
        assert "nan" not in f.lower()


def test_the_desk_calls_the_book_and_the_desk_is_wired():
    boot, body, land = (SRC / "boot.js").read_text(), (SRC / "body.html").read_text(), (SRC / "landing.js").read_text()
    groups = dict(re.findall(r'(\w+): \{ name: "[^"]+", views: \[([^\]]+)\] \}', boot))
    assert groups["today"].startswith('"desk", "book"') and 'id="view-book"' in body and "renderBookRisk" in boot
    assert "bookCall(N)" in land and "Run the book at" in land and any(d[0] == "book" for d in mind.DESKS)
    assert '"snap30.js", "book.js"' in (ROOT / "scripts" / "assemble_page.py").read_text()
    assert "book_risk" in mcp_server.TOOLS and not any(re.search(r"place|execute|submit|send_order", n) for n in mcp_server.TOOLS)
    for f in (SRC / "book.js", ROOT / "buildout" / "book.py", SRC / "snap30.js", ROOT / "scripts" / "snapshot_v30.py"):
        t = f.read_text().lower()
        for b in BANNED:
            assert b not in t, (f, b)


def test_the_decision_numbers_the_audit_found_wrong():
    m = re.search(r'"deflated_excess":(\{[^}]*\})', (SRC / "snap19.js").read_text())
    D = json.loads(m.group(1))
    assert np.isfinite(D["dsr"]) and D["best"] != "gated"
    assert "is real is nan" not in (SRC / "snap19.js").read_text()
    rng = np.random.default_rng(0)
    r = rng.normal(0.005, 0.04, 600)
    e = np.zeros(600)
    for t in range(1, 600):                                      # a persistent deviation: OLS errors are too small
        e[t] = 0.9 * e[t - 1] + rng.normal(0, 0.01)
    _, t_hac, _ = decide.timing_alpha(e + 0.001, r)
    X = np.column_stack([np.ones(600), r])
    b = np.linalg.lstsq(X, e + 0.001, rcond=None)[0]
    res = e + 0.001 - X @ b
    t_ols = b[0] / np.sqrt((np.linalg.inv(X.T @ X) * (res @ res) / 598)[0, 0])
    assert abs(t_hac) < abs(t_ols)
    src = (ROOT / "buildout" / "decide.py").read_text()
    assert "w_hmm[i] / rest * (1 - p_)" in src and 'k != "gated"' in src


def test_index_puts_are_priced_off_the_index_vol():
    P = {**reasoner.DEFAULTS, "vix": 18.0, "index_vol": 28.0}
    assert reasoner.put_spread_cost(P["index_vol"]) > reasoner.put_spread_cost(P["vix"])
    c_vxn, c_vix = hedgebook.option_costs({**hedgebook.DEFAULTS, **P}), hedgebook.option_costs({**hedgebook.DEFAULTS, **P, "index_vol": None})
    assert c_vxn["put_spread"] > c_vix["put_spread"] and c_vxn["vix_spread"] == c_vix["vix_spread"]
    assert "index_vol: fin(I.vxn.v)" in (SRC / "solve.js").read_text() and "P.index_vol || P.vix" in (SRC / "engine7.js").read_text()


def test_filtered_var_hands_a_missing_names_weight_over():
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2020-01-01", periods=600)
    R = pd.DataFrame(rng.normal(0, 0.02, (600, 2)), index=idx, columns=["A", "B"])
    R.iloc[:500, 1] = np.nan                                      # B lists late
    w = pd.Series({"A": 0.5, "B": 0.5})
    v, _ = risk.fhs_var(R, w)
    v_a, _ = risk.fhs_var(R[["A"]], pd.Series({"A": 1.0}))
    assert v > 0.7 * v_a                                          # zero-filling B would have halved it on 500 of 600 days


def test_betas_never_go_silently_nan_and_the_basket_can_leave_a_name_out():
    rng = np.random.default_rng(4)
    idx = pd.bdate_range("2020-01-01", periods=300)
    m = pd.Series(rng.normal(0, 0.01, 300), index=idx)
    R = pd.DataFrame({k: 1.2 * m + rng.normal(0, 0.01, 300) for k in ("A", "B", "C")}, index=idx)
    R["M"], R["T"] = m, rng.normal(0, 0.005, 300)
    F = returns.factor_returns(R, "M", ["A", "B", "C"], "T")
    loo = returns.factor_returns(R, "M", ["A", "B", "C"], "T", exclude="A")
    assert not np.allclose(F["ai"], loo["ai"]) and np.allclose(loo["ai"], R[["B", "C"]].mean(axis=1) - m)
    b = exposures.latest_betas(R, F, ["A", "B", "C"], halflife=126)          # 300 days: no name is "established"
    assert b[["market", "ai", "rates"]].notna().all().all()
