"""v0.42.5: an outside buyside audit's findings, each as an invariant that fails if the fault returns.

    final risk obeys the budget         the evidence gate cannot blend the size back over the risk budget (Python and the page)
    rebalancing is paid for             a target-weight book's daily trades are in its turnover and its costs
    no pre-trade profit                 a fall before the put is bought cannot pay the put
    time is causal                      a paper order fills at a close that comes after it, and never before the account opened
    one decision across surfaces        every surface quotes the ledger's entry; the static page carries no figure of its own
    limits mean limits                  no frontier row marked as meeting a limit exceeds it
    the calendar is tradable            the exchange's holidays and early closes, checked against its published dates
    corrections propagate               the page loads the published decision and tells a revision from a repeat by content
    more cost cannot help               doubling every cost lowers every fixed policy's net return
    words mean what they say            expected shortfall is not "the worst month in twenty"; the page says who can send an order
    one document                        the published page declares one doctype and opens one html element
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import book as bk
from buildout import broker as br
from buildout import decide, ledger, sessions, sizing_rules, track, trader
from buildout import execution as ex
from buildout import mandate as md

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
NODE = "node"


def _snap(name: str, var: str) -> dict:
    s = (SRC / name).read_text()
    i = s.index(f"const {var} = ") + len(f"const {var} = ")
    return json.loads(s[i:s.index(";\n", i)].replace("<\\/", "</"))


def _page_sources() -> str:
    """The page's own text: body and scripts, without the generated snapshots (which carry data and embedded source)."""
    return (SRC / "body.html").read_text() + "".join(p.read_text() for p in sorted(SRC.glob("*.js")) if not p.name.startswith("snap"))


# ---------------------------------------------------------------- 1. the gate cannot undo the risk budget
DEC = None


def _dec() -> dict:
    global DEC
    if DEC is None:
        DEC = _snap("snap19.js", "SNAP19")["decision"]
    return DEC


BUDGETS = [0.02, 0.03, 0.04, 0.05, 0.06, 0.065, 0.07, 0.08, 0.10, 0.12, 0.15, 0.20, 0.29]
GATES = [-1.0, 0.0, 0.34, 1.0, 1.8, 2.5, 4.0]
STRESS = [None, 0.0, 0.2, 0.5, 0.9]


def test_the_final_size_is_inside_the_budget_for_every_setting_python():
    N = _dec()["now"]
    for p in STRESS:
        for t in GATES:
            last = None
            for b in BUDGETS:                                   # loosest last: a looser budget may never allow less
                w = decide.what_if(N, p_stress=p, t=t, es=b)
                assert w["decision_es"] <= b + 1e-12, (p, t, b, w["decision"], w["decision_es"])
                assert w["decision"] <= w["feasible_max"] + 1e-12
                if last is not None:
                    assert w["decision"] >= last - 1e-12, f"a looser budget ({b}) allowed a smaller size than a tighter one at p={p}, t={t}"
                last = w["decision"]


def test_the_audits_case_a_tight_budget_with_the_gate_shut():
    """Budget 3%, gate 0: the optimum was 0.45x and the final answer 1.00x with a 6.6% shortfall. Now the answer is the optimum."""
    w = decide.what_if(_dec()["now"], t=0.0, es=0.03)
    assert w["gate"] == 0.0 and w["decision"] == pytest.approx(w["optimum"]) and w["decision"] < 1.0 and w["budget_binds_decision"]
    assert w["decision_es"] <= 0.03 + 1e-12
    assert decide.gate_blend(0.45, 0.0) == 1.0 and decide.gate_blend(0.45, 0.0, 0.45) == 0.45        # the cap is the only change
    assert decide.gate_blend(1.5, 0.5, 1.5) == 1.25 and decide.gate_blend(1.5, 1.0, 1.2) == 1.2


def test_the_final_size_is_inside_the_budget_for_every_setting_on_the_page():
    """The page's own copy (dxlive.js), run on its own: agreement with Python would not catch a shared mistake."""
    cases = [{"pStress": p, "t": t, "es": b} for p in STRESS for t in GATES for b in BUDGETS]
    for c in cases:
        if c["pStress"] is None:
            del c["pStress"]
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness425.js")], input=json.dumps({"now": _dec()["now"], "cases": cases}), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    got = json.loads(r.stdout)["cases"]
    assert len(got) == len(cases)
    prev = {}
    for c, g in zip(cases, got):
        assert g["decisionEs"] <= c["es"] + 1e-12, (c, g)
        key = (c.get("pStress"), c["t"])
        if key in prev:
            assert g["decision"] >= prev[key] - 1e-12, (c, g)
        prev[key] = g["decision"]
        want = decide.what_if(_dec()["now"], p_stress=c.get("pStress"), t=c["t"], es=c["es"])
        assert g["decision"] == pytest.approx(want["decision"], abs=1e-9) and g["budgetBinds"] == want["budget_binds_decision"], c


def test_the_walk_forward_gate_is_capped_too():
    src = (ROOT / "buildout" / "decide.py").read_text()
    assert 'gate_blend(R["x"][t], g[t], R["feasible_max"][t]' in src.replace("\n", " ") or re.search(r"gate_blend\(R\[\"x\"\]\[t\], g\[t\], R\[\"feasible_max\"\]", src)
    N = _dec()["now"]
    assert N["exposure"] <= N["feasible_max"] + 1e-12 and N["budget_binds_decision"] is False


# ---------------------------------------------------------------- 2. rebalancing is paid for
def test_the_two_stock_round_trip_has_turnover():
    idx = pd.bdate_range("2026-01-05", periods=4)
    R = pd.DataFrame({"a": [0.0, 0.10, -1 / 11, 0.0], "b": [0.0, -0.10, 1 / 9, 0.0]}, index=idx)
    W = pd.DataFrame(0.5, index=idx, columns=R.columns)
    r = (R * W).sum(axis=1)
    assert r.iloc[2] == pytest.approx(0.010101, abs=1e-6)             # the return daily rebalancing earns
    t = track.rebalance_turnover(R, W)
    assert t.iloc[0] == 0 and t.iloc[1] == 0 and t.iloc[2] == pytest.approx(0.10) and t.iloc[3] > 0.09   # and the trades it takes
    drift = pd.DataFrame({"a": [0.5, 0.5], "b": [0.5, 0.5]}, index=idx[:2])
    assert track.rebalance_turnover(pd.DataFrame(0.0, index=idx[:2], columns=["a", "b"]), drift).sum() == 0   # nothing moves, nothing trades


def test_the_point_in_time_book_reports_its_daily_trades():
    prices, ust, _ = bk.synthetic(seed=7, days=900)
    for t in track.CANDIDATES:
        if t not in prices:
            prices[t] = prices[bk.FILE.get("NVDA", "nvda")].copy()
    cal = bk.panel(prices, ust)["R"].index
    r, mem, turn = track.pit_book(prices, cal)
    held = turn.loc[turn[turn > 0].index[0]:]                          # from the first day the book holds names (the first year has no history to rank)
    assert (held > 0).mean() > 0.98, "an equal-weight book trades every day it is held"
    assert 0.5 < held.sum() / (len(held) / 252) < 20


def _walk(cost_scale: float = 1.0, monkeypatch=None):
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2016-01-04", periods=1300)
    r = pd.Series(rng.normal(0.0004, 0.015, len(idx)), index=idx)
    q = r * 0.8 + pd.Series(rng.normal(0, 0.004, len(idx)), index=idx)
    cash = pd.Series(0.0001, index=idx)
    bond = pd.Series(rng.normal(0.0001, 0.006, len(idx)), index=idx)
    tn = pd.Series(0.012, index=idx)
    if monkeypatch is not None:
        monkeypatch.setattr(track, "COST", {k: v * cost_scale for k, v in track.COST.items()})
    return track.walk_forward(r, q - cash, bond, cash, tn)


def test_holding_pays_for_its_rebalancing_and_more_cost_never_helps(monkeypatch):
    W1 = _walk()
    g, n, m = W1["policies"]["hold"]
    assert (g - n).sum() > 0 and m["turnover_yr"] > 2.5               # 1.2% a day of names traded is about 3x a year
    assert ((g - n) >= -1e-15).all(), "a cost can never add to a day's return"
    W2 = _walk(2.0, monkeypatch)
    for k in W1["policies"]:
        n1, n2 = W1["policies"][k][1], W2["policies"][k][1]
        assert (1 + n2).prod() <= (1 + n1).prod() + 1e-12, f"doubling every cost raised {k}'s net return"
        if k in ("hold", "call"):                                     # no borrowing: the return before trading costs is the same book
            assert np.allclose(W1["policies"][k][0], W2["policies"][k][0]), f"costs changed {k}'s gross return"


def test_the_size_held_at_its_share_of_nav_is_a_trade():
    W = _walk()
    g, n, m = W["policies"]["call"]
    assert m["avg_gross"] < 1 and m["turnover_yr"] > W["policies"]["hold"][2]["turnover_yr"] * m["avg_gross"] * 0.9


# ---------------------------------------------------------------- 3. no pre-trade profit
def test_a_fall_before_the_put_is_bought_cannot_pay_it():
    d = pd.bdate_range("2025-11-03", "2026-03-31")
    v = pd.Series(20.0, index=d)
    crash_on_purchase = pd.Series(0.0, index=d)
    crash_on_purchase[pd.Timestamp("2025-12-31")] = -0.20            # the December month-end close is where January's put is bought
    p = track.put_returns(crash_on_purchase, v)
    assert p[pd.Timestamp("2026-01-31")] < 0 and p[pd.Timestamp("2026-01-31")] == pytest.approx(p[pd.Timestamp("2026-02-28")])   # only the premium
    after = pd.Series(0.0, index=d)
    after[pd.Timestamp("2026-01-02")] = -0.20                        # the first session after the purchase: this one the put does pay
    p2 = track.put_returns(after, v)
    assert p2[pd.Timestamp("2026-01-31")] > 0.09 and p2[pd.Timestamp("2026-02-28")] < 0


def test_the_put_is_priced_from_the_purchase_close_only():
    d = pd.bdate_range("2025-11-03", "2026-03-31")
    q = pd.Series(0.0, index=d)
    v = pd.Series(20.0, index=d)
    v2 = v.copy()
    v2[d > pd.Timestamp("2025-12-31")] = 80.0                        # vol after the purchase must not move January's premium
    a, b = track.put_returns(q, v), track.put_returns(q, v2)
    assert a[pd.Timestamp("2026-01-31")] == pytest.approx(b[pd.Timestamp("2026-01-31")])
    assert b[pd.Timestamp("2026-02-28")] < a[pd.Timestamp("2026-02-28")]        # February's put, bought at the January close, costs more


# ---------------------------------------------------------------- 4. the paper account: time is causal, the books reconcile
PX = {"NVDA": 200.0, "MSFT": 500.0}


def _quotes(asof: str, closes: dict | None = None):
    def fn(S):
        return {s: {"bid": PX[s] * 0.9995, "ask": PX[s] * 1.0005, "last": (closes or {}).get(asof, {}).get(s, PX[s]), "asof": asof,
                    "closes": {d: c[s] for d, c in (closes or {asof: PX}).items() if s in c}} for s in S if s in PX}
    return fn


def test_a_stale_quote_cannot_fill_an_order():
    """The audit's reproduction: a Nov 10 quote and an order written Nov 11. Nothing fills until Nov 11 has closed."""
    now = datetime(2026, 11, 11, 19, 54, 16, tzinfo=timezone.utc)
    pb = br.PaperBroker(Path(__import__("tempfile").mkdtemp()) / "a.json", quote_fn=_quotes("2026-11-10"), clock=lambda: now)
    pb.quotes(["NVDA"])
    o = pb.place("NVDA", "buy", 10, 200.3, "c1")
    assert o["status"] == "open" and o["fills_in_session"] == "2026-11-11" and o["planning_quote"]["asof"] == "2026-11-10"
    assert pb.settle(now + timedelta(days=1)) == [] and pb.state["positions"] == {} and pb.state["cash"] == 100_000     # only the Nov 10 close is known
    pb.quote_fn = _quotes("2026-11-11", {"2026-11-10": {"NVDA": 200.0}, "2026-11-11": {"NVDA": 210.0}})
    pb.quotes(["NVDA"])
    assert pb.settle(datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc)) == []          # the close is at 21:00 UTC
    done = pb.settle(datetime(2026, 11, 12, 11, 17, tzinfo=timezone.utc))
    assert len(done) == 1 and done[0]["status"] == "filled" and done[0]["fill_session"] == "2026-11-11"
    assert done[0]["avg_price"] == pytest.approx(210.0 * 1.0005) and done[0]["inside_limit"] is False      # the limit is recorded, the close is the price
    assert done[0]["placed"] <= done[0]["filled"], "the fill is after the order"


def test_an_order_written_after_the_close_or_on_a_holiday_waits_for_the_next_session():
    f = sessions.session_of_close_after
    assert f(datetime(2026, 11, 11, 22, 0, tzinfo=timezone.utc)) == date(2026, 11, 12)
    assert f(datetime(2026, 11, 14, 11, 17, tzinfo=timezone.utc)) == date(2026, 11, 16)                      # Saturday's run
    assert f(datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc)) == date(2026, 11, 27)                       # Thanksgiving
    assert f(datetime(2026, 11, 27, 18, 30, tzinfo=timezone.utc)) == date(2026, 11, 30)                      # after the 1:00 pm close


def test_no_equity_point_before_the_account_opened(tmp_path):
    now = datetime(2026, 11, 11, 19, 54, tzinfo=timezone.utc)
    pb = br.PaperBroker(tmp_path / "a.json", quote_fn=_quotes("2026-11-10"), clock=lambda: now)
    pb.quotes(["NVDA"])
    pb.mark()
    assert pb.state["opened"] == "2026-11-11" and pb.state["equity_history"] == []
    pb.state["equity_history"] = [["2026-11-10", 99_924.21]]          # what the first run wrote
    pb.mark()
    assert pb.state["equity_history"] == [] and pb.state["pre_inception_marks"] == [["2026-11-10", 99_924.21]]   # moved aside, kept
    pb.quote_fn = _quotes("2026-11-11")
    pb.quotes(["NVDA"])
    pb.mark()
    assert [h[0] for h in pb.state["equity_history"]] == ["2026-11-11"]


def test_the_paper_books_reconcile_and_every_fill_is_recorded_once(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path))
    import tests.test_v42 as T
    t0 = T.NOW
    pb = br.PaperBroker(tmp_path / "paper_account.json", quote_fn=T._qf)
    M = md.Mandate(mode="autonomous", broker="paper", max_order_usd=50_000)
    r1 = trader.run_once(pb, M, T._params(), now=t0, call=T._call())
    assert r1["outcome"] == "orders resting until the close"
    r2 = trader.run_once(pb, M, T._params(), now=t0 + timedelta(days=1), call=T._call())
    a = pb.account()
    value = sum(p["quantity"] * T.PX[p["symbol"]] for p in a["positions"])
    assert a["equity"] == pytest.approx(a["cash"] + value, abs=0.01), "positions at their marks plus cash is the equity"
    F = ex._fills()
    assert len(F) == 1 and F[0]["status"] == "filled" and "market on close" in F[0]["convention"] and ex.verify_fills()["ok"]
    ids = [f["order_id"] for f in F[0]["fills"]]
    assert len(ids) == len(set(ids)) == 9
    spent = sum(f["quantity"] * f["price"] for f in F[0]["fills"])
    assert a["cash"] == pytest.approx(100_000 - spent, abs=0.01), "every fill came out of cash exactly once"
    trader.run_once(pb, M, T._params(), now=t0 + timedelta(days=1, hours=1), call=T._call())
    assert len(ex._fills()) == 1, "a second pass records nothing twice"
    j = [e for e in trader.journal() if e["event"] == "executed"][-1]
    assert j["decision_ts"] is None or j["decision_ts"] <= j["ordered"]
    assert j["ordered"] <= j["filled_at"] <= r2["ts_utc"].replace("Z", "+00:00") and j["fill_session"] == "2026-11-09"
    S = trader.paper_summary(tmp_path)
    assert S["timeline"][0]["causal"] and S["non_causal_fills"] == 0 and "never older than the order" in S["note"]


def test_a_halt_cancels_resting_orders(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path))
    import tests.test_v42 as T
    pb = br.PaperBroker(tmp_path / "paper_account.json", quote_fn=T._qf)
    M = md.Mandate(mode="autonomous", broker="paper", max_order_usd=50_000)
    assert trader.run_once(pb, M, T._params(), now=T.NOW, call=T._call())["outcome"] == "orders resting until the close"
    (tmp_path / "HALT").write_text("x")
    r = trader.run_once(pb, M, T._params(), now=T.NOW + timedelta(days=1), call=T._call())
    assert r["outcome"] == "halted" and r["settled"]["cancelled"] == 9 and pb.open_orders() == [] and pb.state["positions"] == {}


def test_the_committed_paper_record_is_marked_for_what_it_is():
    S = trader.paper_summary(ROOT / "paper")
    assert all(h[0] >= S["opened"] for h in S["equity_history"]), "no equity point before inception"
    old = [t for t in S["timeline"] if not t["causal"]]
    assert S["non_causal_fills"] >= 9 and old and "previous close" in old[0]["convention"], "the first fills are kept and named"
    assert "kept as recorded" in S["note"] and "not evidence of an achievable execution" in S["note"]
    js = (SRC / "execdesk.js").read_text()
    assert "ex-pb-tl" in js and "Order before price" in js and 'id="ex-pb-tl"' in (SRC / "body.html").read_text()


# ---------------------------------------------------------------- 5. one decision across surfaces
def test_every_surface_quotes_the_ledgers_entry():
    js = (SRC / "book.js").read_text()
    assert "decisionFor(B.asof)" in js and "menu_high" in js and "short: k.short_nasdaq_frac }" not in js, "the exact minimum must not stand in for the logged row"
    body = (SRC / "body.html").read_text()
    h1 = re.search(r'<h1 id="desk-title">(.*?)</h1>', body).group(1)
    assert not re.search(r"\d(%|x\b)", h1), "the static headline carries no figure: search indexed an 86% short two calls old"
    v = (SRC / "views.js").read_text()
    assert "reindexDesk" in v and "renderHeadline(DX19.now)" in v and "guard(\"Search\", reindexDesk)" in (SRC / "boot.js").read_text()
    td = (SRC / "trackdesk.js").read_text()
    assert "decisionInForce" in td and "takes effect" in td and "In force today" in td


def test_the_published_call_is_the_logged_call():
    """The committed book.json and the ledger entry for the same data date carry the same menu and size."""
    book = json.loads((ROOT / "site" / "data" / "book.json").read_text())
    e = next((x for x in reversed(ledger.read()) if x["data_asof"] == book["asof"]), None)
    if e is None:
        pytest.skip("the day's call is not in the ledger yet")
    fr = [r for r in book["frontier"] if r.get("meets")]
    c = e["call"]
    assert round(fr[0]["gross"], 4) == c["menu_low"]["gross"] and fr[0]["short"] == c["menu_low"]["short"]
    assert round(float(book["size"]), 4) == c["size"]
    assert ex.decision_id(e) == f"{e['seq']}-{e['hash'][:8]}"
    cf = ex.call_in_force(e["effective_from"])
    assert cf["decision_id"] and cf["decision_ts"] and [m["short"] for m in cf["frontier"]][-1] == cf["menu_high"]["short"]


def test_the_site_build_reconciles_the_call_and_marks_rows_over_a_limit(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_site
    (tmp_path / "data").mkdir()
    book = json.loads((ROOT / "site" / "data" / "book.json").read_text())
    L = book["limits"]
    book["frontier"].insert(1, {"gross": 0.6, "short": 0.1, "meets": True, "es95": 0.1, "vol": 0.15, "drawdown95": L["max_drawdown"] + 0.000923})
    (tmp_path / "data" / "book.json").write_text(json.dumps(book))
    out = build_site.reconcile(tmp_path, ROOT)
    assert out["checked"] and out["rows_marked_over_limit"] >= 1
    after = json.loads((tmp_path / "data" / "book.json").read_text())
    bad = [r for r in after["frontier"] if r.get("over_limit")]
    assert bad and all(not r["meets"] for r in bad)
    assert all(r["drawdown95"] <= L["max_drawdown"] + 1e-9 for r in after["frontier"] if r.get("meets"))
    if out.get("logged"):
        assert re.fullmatch(r"\d+-[0-9a-f]{8}", out["decision_id"])


def test_the_walk_forward_shorts_what_the_ledger_would_log():
    src = (ROOT / "buildout" / "track.py").read_text()
    assert '"short_exact": exact' in src and 'fr[-1]["short"]' in src


# ---------------------------------------------------------------- 6. limits mean limits
def _frontier(tol_case: bool = False):
    prices, ust, _ = bk.synthetic(seed=3, days=1200)
    return bk.build(prices, ust)


def test_no_row_marked_as_meeting_a_limit_exceeds_it():
    B = _frontier()
    L = B["limits"]
    F = [r for r in B["frontier"] if r["meets"]]
    assert len(F) >= 2
    for r in F:
        assert r["es95"] <= L["es_budget"] + 1e-9 and r["vol"] <= L["vol_target"] + 1e-9 and r["drawdown95"] <= L["max_drawdown"] + 1e-9, r
        assert r["gross_total"] == pytest.approx(r["gross"] + r["short"]) and r["net"] == pytest.approx(r["gross"] - r["short"]) and r["cash_in_record"]
    assert sizing_rules.SOLVER_TOL <= 1e-8 and "tol = 0.005" not in (ROOT / "buildout" / "sizing_rules.py").read_text()
    assert F[0]["short"] == 0.0 and F[0]["gross"] <= B["size"] + 1e-9 and F[0]["gross"] >= B["size"] * 0.99


def test_the_audits_row_cannot_pass():
    rows = [{"gross": 0.6, "short": 0.1, "meets": True, "es95": 0.10088, "vol": 0.1561, "drawdown95": 0.250923},
            {"gross": 1.0, "short": 0.85, "meets": True, "es95": 0.09707, "vol": 0.1502, "drawdown95": 0.24844}]
    out = sizing_rules.recheck(rows, {"es": 0.12, "vol": 0.20, "dd": 0.25})
    assert out[0]["meets"] is False and out[0]["over_limit"] and out[1]["meets"] is True
    assert rows[0]["meets"] is True, "the input is not edited"


def test_the_embedded_and_published_menus_hold_to_the_limits():
    for B in (_snap("snap30.js", "SNAP30")["book"],):
        L = B["limits"]
        for r in B["frontier"]:
            if r["meets"]:
                assert r["drawdown95"] <= L["max_drawdown"] + 1e-9 and r["es95"] <= L["es_budget"] + 1e-9 and r["vol"] <= L["vol_target"] + 1e-9, r


def test_the_frontiers_record_includes_the_cash_sleeve():
    idx = pd.bdate_range("2020-01-01", periods=600)
    rb = pd.Series(0.0, index=idx)
    qx = pd.Series(0.0, index=idx)
    cash = pd.Series(0.04 / 252, index=idx)
    fm = {"factor_cov": pd.DataFrame([[0.04]], index=["market"], columns=["market"]), "exposure": {"market": 1.0}, "vol": 0.10}
    rows = sizing_rules.frontier(rb, qx, fm, 1.0, 1.0, 0.04, {"es": 1.0, "vol": 1.0, "dd": 1.0}, lambda x, s: 0.0, grosses=(0.25, 1.0), cash=cash)
    assert rows[0]["cagr"] == pytest.approx((1 + 0.04 / 252) ** (252 * 0.75) - 1, rel=1e-3), "three quarters of NAV in cash earns three quarters of the cash rate"
    assert rows[1]["cagr"] == pytest.approx(0.0, abs=1e-12)
    bare = sizing_rules.frontier(rb, qx, fm, 1.0, 1.0, 0.04, {"es": 1.0, "vol": 1.0, "dd": 1.0}, lambda x, s: 0.0, grosses=(0.25,))
    assert bare[0]["cagr"] == pytest.approx(0.0, abs=1e-12) and bare[0]["cash_in_record"] is False


# ---------------------------------------------------------------- 7. the calendar is tradable
NYSE = {  # nyse.com/markets/hours-calendars, read Nov 11, 2026
    2026: ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"],
    2027: ["2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"],
    2028: ["2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19", "2028-07-04", "2028-09-04", "2028-11-23", "2028-12-25"],
}
EARLY = ["2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"]


def test_the_holidays_are_the_exchanges():
    for y, want in NYSE.items():
        assert sorted(d.isoformat() for d in sessions.holidays(y)) == want, y
    got = [d.isoformat() for y in NYSE for d in (date(y, 1, 1) + timedelta(days=i) for i in range(366)) if d.year == y and sessions.early_close(d)]
    assert got == EARLY
    assert not sessions.is_session("2028-01-01") and sessions.is_session("2027-12-31"), "a Saturday New Year's Day closes no weekday"
    assert not sessions.is_session("2025-01-09") and not sessions.is_session("2018-12-05")          # days of mourning
    assert sessions.easter(2026) == date(2026, 4, 5) and sessions.easter(2027) == date(2027, 3, 28)


def test_a_call_cannot_take_effect_on_a_day_with_no_session():
    assert ledger.next_trading_day("2026-11-25") == "2026-11-27"      # the audit's case: it returned Thanksgiving
    assert ledger.next_trading_day("2026-11-06") == "2026-11-09" and ledger.next_trading_day("2026-12-24") == "2026-12-28"
    assert ledger.next_trading_day("2026-07-02") == "2026-07-06" and ledger.next_trading_day("2027-12-31") == "2028-01-03"
    e = ledger.make_entry({"asof": "2026-11-24", "size": 0.5, "binding": "drawdown_cap", "frontier": [{"gross": 0.5, "short": 0.0, "meets": True}, {"gross": 1.0, "short": 0.85, "meets": True}]},
                          "0.42.5", None, ts="2026-11-25T11:17:00Z")
    assert e["effective_from"] == "2026-11-27" and sessions.is_session(e["effective_from"])
    for row in ledger.read():                                          # the entries already written keep their dates, and each was a session
        assert sessions.is_session(row["effective_from"]), row["seq"]
    assert ledger.verify()["ok"]


def test_the_close_follows_daylight_saving_and_early_closes():
    assert sessions.close_utc("2026-07-01").hour == 20 and sessions.close_utc("2026-11-11").hour == 21      # EDT, then EST
    assert sessions.close_utc("2026-03-06").hour == 21 and sessions.close_utc("2026-03-09").hour == 20      # across the March change
    assert sessions.close_utc("2026-11-27").hour == 18 and sessions.close_time("2026-11-27").hour == 13
    assert sessions.sessions_between("2026-11-25", "2026-11-30") == 2 and sessions.sessions_between("2026-11-06", "2026-11-09") == 1
    assert ex._bdays_between("2026-11-25", "2026-11-27") == 1, "a holiday is not a stale day"
    assert sessions.prev_session("2026-11-27") == date(2026, 11, 25)


def test_the_window_knows_holidays_and_early_closes():
    M = md.Mandate()
    assert not md.in_window(M, datetime(2026, 11, 26, 16, 0, tzinfo=timezone.utc))[0] and "holiday" in md.in_window(M, datetime(2026, 11, 26, 16, 0, tzinfo=timezone.utc))[1]
    assert md.in_window(M, datetime(2026, 11, 27, 16, 0, tzinfo=timezone.utc))[0]                 # 11:00 on the half day
    late = md.in_window(M, datetime(2026, 11, 27, 18, 30, tzinfo=timezone.utc))                    # 13:30: the exchange has closed
    assert not late[0] and "1:00 pm" in late[1]
    assert md.in_window(M, datetime(2026, 11, 25, 20, 30, tzinfo=timezone.utc))[0]                 # 15:30 on a full day


def test_the_calendar_needs_no_packages():
    src = (ROOT / "buildout" / "sessions.py").read_text()
    assert not re.search(r"^\s*(import|from) (pandas|numpy)", src, re.M), "the site build imports the ledger and installs nothing"
    r = subprocess.run([sys.executable, "-I", "-S", "-c", "import sys; sys.path.insert(0, %r); from buildout import ledger; print(ledger.next_trading_day('2026-11-25'))" % str(ROOT)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "2026-11-27", r.stderr[-500:]


# ---------------------------------------------------------------- 8. corrections propagate
def test_a_decision_package_is_named_by_its_content():
    D = dict(_dec())
    h = decide.content_hash(D)
    assert D["content_sha256"] == h and re.fullmatch(r"[0-9a-f]{16}", h)
    later = {**D, "computed_utc": "2027-01-01T00:00:00Z", "v30_patch": "x"}
    assert decide.content_hash(later) == h, "when it was computed is not content"
    rev = json.loads(json.dumps(D))
    rev["now"]["regime"]["next"][0] += 0.01                           # the same month, a revised input
    assert rev["end"] == D["end"] and decide.content_hash(rev) != h, "a same-date correction is a different package"


def test_the_page_carries_the_published_decision():
    pub = json.loads((ROOT / "site" / "data" / "decision.json").read_text())
    D = _dec()
    # Each copy names its own content. They are not required to be the same copy: the daily run rewrites the published
    # one (a new computed time every day, new content when a month's data arrives), which is what the page's overlay
    # is for. v0.42.5 asserted that the two were equal, and the first daily run after it failed the suite (v0.42.6).
    assert pub["content_sha256"] == decide.content_hash(pub) and D["content_sha256"] == decide.content_hash(D)
    assert pub["computed_utc"] and D["computed_utc"] and pub["computed_utc"] >= D["computed_utc"] and pub["end"] >= D["end"]
    assert pub["now"]["feasible_max"] >= pub["now"]["exposure"]
    boot = (SRC / "boot.js").read_text()
    assert 'loadJSON("data/decision.json")' in boot and "content_sha256 !== DX19.content_sha256" in boot and "dxRebuild" in boot
    assert "content_sha256" in (ROOT / "buildout" / "cli.py").read_text() and "computed_utc" in (ROOT / "buildout" / "cli.py").read_text()
    assert "function dxRebuild" in (SRC / "dx.js").read_text() and "function dxlReset" in (SRC / "dxlive.js").read_text()


def test_a_failed_fetch_leaves_a_trace():
    v = (SRC / "views.js").read_text()
    assert "LIVE.fetch[path] = `not published (HTTP ${res.status})`" in v and 'LIVE.fetch[path] = "not reachable"' in v and "function renderPackages" in v
    assert 'id="pkg-body"' in (SRC / "body.html").read_text() and "this build's snapshot" in v
    td = (SRC / "trackdesk.js").read_text()
    assert "Call on prices through" in td and "record through" in td and "monthly model through" in td, "three cadences, three dates"


# ---------------------------------------------------------------- 9. words mean what they say
def test_expected_shortfall_is_not_the_worst_month_in_twenty():
    bad = []
    for p in [SRC / "body.html"] + sorted(SRC.glob("*.js")) + sorted((ROOT / "buildout").glob("*.py")):
        t = p.read_text().lower()
        if p.name == "memos.js":
            t = "\n".join(line for line in t.splitlines() if '"v0.42.5"' not in line)     # the failure log quotes the old wording
        if p.name == "reference.js":
            t = "\n".join(line for line in t.splitlines() if not line.strip().startswith('["v0.42.5"'))
        if "month in twenty" in t:                                     # collected by name: a failed assert on a 7 MB string hangs the reporter
            bad.append(p.name)
    assert not bad, bad
    body = (SRC / "body.html").read_text()
    assert "average loss across the worst 5% of months" in body and "not a worst case" in body
    assert "Average loss in the worst 5% of months, at 1.00x" in (SRC / "book.js").read_text()


def test_the_page_says_who_can_send_an_order():
    t = _page_sources()
    assert "Orders Buildout can place" not in t.replace("0 orders Buildout can place", "") and "nothing executes without a person" not in t
    assert "has no tool that places an order.</p></div>\n  <div class=\"at-tiles\" id=\"ex-tiles\">" not in t
    js = (SRC / "execdesk.js").read_text()
    for s in ("The paper bot (the daily workflow)", "Yes, simulated orders only, with no person in the loop", "broker = robinhood_mcp", "Untested against the live endpoint", "60 paper days and 5 approved live tickets"):
        assert s in js, s
    assert 'id="ex-who"' in (SRC / "body.html").read_text()
    assert "Works today" not in js


def test_the_record_is_labelled_for_its_universe_and_its_restatement():
    td = (SRC / "trackdesk.js").read_text()
    assert td.count("retrospectively selected universe") >= 2 and "tr-restate" in td
    T = _snap("snap38.js", "SNAP38")
    R = T["restated"]
    assert R["version"] == "v0.42.5" and {"call", "call_short", "hold"} <= set(R["policies"])
    for k, v in R["policies"].items():
        assert v["sharpe"][1] <= v["sharpe"][0] + 1e-9, f"{k}: charging more trades cannot raise a Sharpe ratio on the same prices"
        assert v["turnover"][1] >= v["turnover"][0], k
        assert T["pit"]["policies"][k]["net"]["sharpe"] == pytest.approx(v["sharpe"][1])
    assert R["policies"]["hold"]["turnover"][1] > 3 and R["put"]["var_cut_min"][1] > 0.2
    assert "candidate list" in (ROOT / "README.md").read_text() and "Restated in v0.42.5" in (ROOT / "README.md").read_text()


def test_the_limitations_name_the_drawdown_model_and_the_cash_proxy():
    L = " ".join(bk.LIMITATIONS)
    assert "geometric Brownian motion" in L and "not a stop" in L and "bill rate" in L
    assert "5% steps" in L


# ---------------------------------------------------------------- 10. one document
def test_the_published_page_is_one_document(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_site
    page = (ROOT / "site" / "page.html").read_text()
    html = build_site.document(page)
    low = html.lower()
    markup = re.sub(r"<script\b.*?</script>", "", low, flags=re.S)
    counts = {k: markup.count(k) for k in ("<!doctype", "<html", "<head>", "<body>")}
    assert counts == {"<!doctype": 1, "<html": 1, "<head>": 1, "<body>": 1}, counts
    assert markup.count("<meta charset") == 1
    plain = {k: low.count(k) for k in ("<!doctype", "<html", "</html>")}
    assert plain == {"<!doctype": 1, "<html": 1, "</html>": 1}, f"a plain scan must find one document too (embedded source is escaped): {plain}"
    assert low.rstrip().endswith("</html>")
    assert html.index("<title>") < html.index("</head>") < html.index("<body>")
    old_style = "<title>t</title><style>a{}</style><p>x</p>"          # a page without a skeleton is wrapped as before
    assert build_site.document(old_style).lower().count("<!doctype") == 1


# ---------------------------------------------------------------- house rules
def test_house_style_and_version():
    import buildout
    assert buildout.__version__ >= "0.42.5"
    for p in ("buildout/sessions.py", "buildout/broker.py", "buildout/trader.py", "buildout/track.py", "buildout/sizing_rules.py", "buildout/decide.py", "scripts/build_site.py",
              "scripts/snapshot_v19_refresh.py", "tests/test_v42_5.py", "paper/README.md", "site/src/memos.js", "site/src/execdesk.js", "site/src/book.js"):
        low = (ROOT / p).read_text().lower()
        for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
            assert b not in low, (p, b)
    assert '["v0.42.5", "Nov 11, 2026"' in (SRC / "reference.js").read_text()
    assert "Version 0.42.5" in (ROOT / "CHANGELOG.md").read_text()


def test_a_day_with_nothing_to_trade_still_advances_the_equity_path(tmp_path, monkeypatch):
    """Found while fixing the fills: the paper account's marks were saved only when an order was placed."""
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path))
    import tests.test_v42 as T
    day = {"d": "2026-11-09"}
    qf = lambda S: {s: {**v, "asof": day["d"]} for s, v in T._qf(S).items()}
    pb = br.PaperBroker(tmp_path / "paper_account.json", quote_fn=qf, clock=lambda: T.NOW)       # opened on the fixed clock's day
    M = md.Mandate(mode="autonomous", broker="paper", max_order_usd=50_000)
    trader.run_once(pb, M, T._params(), now=T.NOW, call=T._call())
    trader.run_once(pb, M, T._params(), now=T.NOW + timedelta(days=1), call=T._call())          # fills at the Nov 9 close
    day["d"] = "2026-11-10"
    r = trader.run_once(pb, M, T._params(), now=T.NOW + timedelta(days=2), call=T._call())
    assert r["outcome"].startswith("nothing to trade")
    on_disk = json.loads((tmp_path / "paper_account.json").read_text())
    assert [h[0] for h in on_disk["equity_history"]] == ["2026-11-09", "2026-11-10"], "the no-trade day is on the record"
    assert trader.paper_summary(tmp_path)["marks_asof"] == "2026-11-10"
