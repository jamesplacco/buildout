"""One evaluator for every limit, and the mandate on the account the orders would leave (buildout/limits.py, v0.48)."""
from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from buildout import book as bk
from buildout import broker as br
from buildout import execution as ex
from buildout import limits as lim
from buildout import mandate as md
from buildout import sizing_rules, trader

ROOT = Path(__file__).resolve().parents[1]
LIMITS = {"es_budget": 0.12, "vol_target": 0.20, "max_drawdown": 0.25, "max_gross": 1.50, "max_total_gross": 2.00}
INSIDE = {"es95": 0.0963, "vol": 0.149, "drawdown95": 0.246}


# ---------------------------------------------------------------- the evaluator
def test_a_check_says_what_it_measured_and_how_much_room_is_left():
    c = lim.check("gross_total", 1.85, 2.00, units=lim.X_NAV)
    assert c["status"] == "pass" and c["headroom"] == pytest.approx(0.15) and c["units"] == "x NAV" and c["limit"] == 2.0
    assert lim.check("gross_total", 1.85, 1.50, units=lim.X_NAV)["status"] == "fail"
    assert lim.check("vol", 0.20, 0.20)["status"] == "pass", "a value exactly at its limit is inside it"
    assert lim.check("vol", 0.2000001, 0.20)["status"] == "fail", "and a hair over is not: there is no tolerance"
    assert lim.check("cash", 0.40, 0.40, kind="min")["status"] == "pass" and lim.check("cash", 0.3485, 0.40, kind="min")["status"] == "fail"
    for missing in (None, float("nan"), float("inf"), "n/a"):
        assert lim.check("vol", missing, 0.20)["status"] == "unchecked", "a missing value is not a pass"
        assert lim.check("vol", 0.10, missing)["status"] == "unchecked", "nor is a missing limit"
    u = lim.check("gross", 0.55, 60, units="percent of NAV", value_units=lim.FRACTION)
    assert u["status"] == "unchecked" and "fraction of NAV" in u["note"] and "percent of NAV" in u["note"], "different units are not compared"
    with pytest.raises(ValueError):
        lim.check("x", 1, 2, kind="about")


def test_exposure_has_four_names():
    e = lim.exposure(1.00, 0.85)
    assert e == {"long": 1.0, "short": 0.85, "net": pytest.approx(0.15), "gross_total": pytest.approx(1.85), "units": "x NAV"}
    assert lim.exposure(1.00, -0.85)["gross_total"] == pytest.approx(1.85), "a short given as a negative number is the same short"
    assert lim.exposure(1.0, None)["gross_total"] is None


def test_compliant_means_every_required_check_passed():
    ev = lim.evaluate_row({"gross": 1.00, "short": 0.85, **INSIDE}, LIMITS)
    assert ev["meets"] and ev["status"] == "pass" and ev["required"] == ["es95", "vol", "drawdown95", "long", "gross_total"]
    assert ev["binding"] == "drawdown95", "the limit with the least room, relative to the limit"
    # one failed: not compliant, and it is named
    over = lim.evaluate_row({"gross": 1.00, "short": 0.85, **INSIDE, "vol": 0.21}, LIMITS)
    assert not over["meets"] and over["failed"] == ["vol"]
    # one that cannot be judged: not compliant either
    blind = lim.evaluate_row({"gross": 1.00, "short": 0.85, "es95": 0.09, "vol": 0.14}, LIMITS)
    assert not blind["meets"] and blind["status"] == "unchecked" and blind["unchecked"] == ["drawdown95"]
    # the long cap is on the long side alone
    assert lim.evaluate_row({"gross": 1.55, "short": 0.0, **INSIDE}, LIMITS)["failed"] == ["long"]
    assert lim.summarize([], ["vol"])["meets"] is False, "a required check that was never made is not a pass"


def test_a_tighter_total_gross_policy_fails_the_full_size_row_at_every_step():
    """The engine's total-gross limit is 2.00x. Were it 1.50x, 1.00x long with a 0.85x short (1.85x) must fail in the
    menu, in the recheck and at publication, and 0.90x with 0.60x (exactly 1.50x) must pass."""
    tight = {**LIMITS, "max_total_gross": 1.50}
    row = {"gross": 1.00, "short": 0.85, "meets": True, **INSIDE}
    assert lim.evaluate_row(row, tight)["failed"] == ["gross_total"]
    assert lim.evaluate_row({"gross": 0.90, "short": 0.60, **INSIDE}, tight)["meets"]
    out = sizing_rules.recheck([dict(row), {"gross": 0.90, "short": 0.60, "meets": True, **INSIDE}], tight)
    assert out[0]["meets"] is False and out[0]["over_limit"] and out[0]["constraints"]["failed"] == ["gross_total"] and out[1]["meets"] is True
    assert sizing_rules.recheck([dict(row)], LIMITS)[0]["meets"] is True, "under the limit the engine states, the row stands"
    # publication uses the same evaluator
    src = (ROOT / "scripts" / "build_site.py").read_text()
    assert "_limits.evaluate_row(r, L)" in src and 'r.get("es95", 0) > L.get("es_budget", 9)' not in src
    # and so does the menu itself, with both gross rules among its limits
    assert "lim.evaluate_row(" in inspect.getsource(sizing_rules.frontier) and "lim.evaluate_row(r, limits)" in inspect.getsource(sizing_rules.recheck)
    assert '"long": MAX_GROSS, "gross_total": MAX_TOTAL_GROSS' in inspect.getsource(bk.build)
    assert bk.MAX_GROSS == 1.50 and bk.MAX_TOTAL_GROSS == 2.00
    from buildout import config
    assert config.RiskParams().max_gross == 1.50 and config.RiskParams().max_total_gross == 2.00, "neither number is new"
    # a file written before the limit was stated: the check is reported as not made, and is not required
    old = lim.evaluate_row(row, {k: v for k, v in LIMITS.items() if k != "max_total_gross"})
    assert old["meets"] and [c for c in old["checks"] if c["metric"] == "gross_total"][0]["status"] == "unchecked"
    # the planner does not use a row that does not say it meets the limits
    assert 'r.get("meets") is True' in inspect.getsource(ex.target)


def test_two_sets_of_limits_are_one_policy():
    p = lim.tighter({"max_gross": 0.98, "cash_floor": 0.02, "max_order_usd": 25_000}, {"max_gross": 0.60, "cash_floor": 0.40, "max_order_usd": 10_000})
    assert p == {"max_gross": 0.60, "cash_floor": 0.40, "max_order_usd": 10_000}, "the lower maximum, the higher minimum"
    assert lim.tighter({"max_gross": 0.98}, None) == {"max_gross": 0.98}
    assert lim.tighter({"max_gross": 0.98, "cash_floor": 0.02}, {"cash_floor": 0.40})["max_gross"] == pytest.approx(0.60), "in a cash account what is not cash is the most that can be held"
    with pytest.raises(ValueError):
        lim.tighter({"max_leverage": 2.0}, {})


# ---------------------------------------------------------------- the mandate on the projected account
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
NAMES = ["MSFT", "AMZN", "GOOGL", "META", "NVDA", "AVGO", "TSLA", "SPCX", "ORCL"]
W9 = {n: 1 / 9 for n in NAMES}
OK = {"ok": True, "logged": True, "effective_from": "2026-11-09"}
CALL = {"asof": "2026-11-06", "size": 0.50, "binding": "drawdown_cap", "frontier": [{"gross": 0.50, "short": 0.0, "meets": True}]}


def _fixture():
    """Equity 100,000. Nine equal names wanted at 0.50 in all (5.56% each). Eight are held at 0.50 / 9 + 0.019 each
    (7.46%), inside the 2% drift band, so none is sold; the ninth is not held. Cash is the rest: 40,355.56."""
    px = {n: 100.0 for n in NAMES}
    quotes = {n: {"bid": 100.0, "ask": 100.0, "last": 100.0} for n in NAMES}
    each = (0.50 / 9 + 0.019) * 100_000 / 100.0
    pos = [{"symbol": n, "quantity": each} for n in NAMES[:8]]
    cash = 100_000 - 8 * each * 100.0
    return {"equity": 100_000.0, "cash": cash, "account_type": "agentic", "positions": pos}, quotes


def _P(**kw):
    return ex.TradingParams(vix_share=0.0, variant="unhedged", max_order_usd=50_000, **kw)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path))
    monkeypatch.setattr(ex, "PRIVATE", tmp_path / "private")
    return tmp_path


def test_the_audited_fixture_is_refused_on_the_account_it_would_leave(state):
    acct, quotes = _fixture()
    M = md.Mandate(max_gross=0.60, cash_floor=0.40, max_order_usd=50_000)
    # The audit's ticket: the ninth name bought in full (55 shares at 100.10) with the eight inside their band left alone.
    # By hand: longs 59,644.44 + 5,500 = 65,144.44; cash 40,355.56 - 5,505.50 = 34,850.06; value 99,994.50.
    # The target's gross is 0.50, inside 0.60; before v0.48 that was all the mandate looked at, and the ticket passed.
    base = ex.plan(acct, quotes, CALL, _P(), W9, today="2026-11-09", ledger_check=OK, now=NOW)
    audited = {**base, "orders": [{"symbol": "ORCL", "side": "buy", "quantity": 55.0, "limit_price": 100.1, "seq": 1, "notional": 5505.5}]}
    auth = md.authorize(audited, acct, M, {}, NOW)
    assert not auth["ok"] and audited["target"]["gross_total"] == pytest.approx(0.50)
    assert any("65.15% gross, above the mandate's max_gross 60.00%" in r for r in auth["reasons"])
    assert any("34.85% cash, below the mandate's cash_floor 40.00%" in r for r in auth["reasons"])
    assert auth["projected"]["gross"] == pytest.approx(65_144.44 / 99_994.50, abs=1e-6)
    # the planner itself (v0.48's whole-book rebalance) brings every name back once the ninth is outside its band, so
    # its own ticket leaves the account at the target, and the mandate passes it on the same projection
    assert base["rebalance"]["triggered"] and base["rebalance"]["names_outside_band"] == ["ORCL"]
    assert base["projected"]["after"]["gross"] == pytest.approx(0.5005, abs=1e-3) and md.authorize(base, acct, M, {}, NOW)["ok"]


C70 = {"asof": "2026-11-06", "size": 0.70, "binding": "drawdown_cap", "frontier": [{"gross": 0.70, "short": 0.0, "meets": True}]}
CASH = {"equity": 100_000.0, "cash": 100_000.0, "account_type": "agentic", "positions": []}


def test_the_ticket_is_planned_under_the_tighter_policy(state):
    quotes = {n: {"bid": 100.0, "ask": 100.0, "last": 100.0} for n in NAMES}
    M = md.Mandate(max_gross=0.60, cash_floor=0.40, max_order_usd=50_000)
    loose = ex.plan(CASH, quotes, C70, _P(), W9, today="2026-11-09", ledger_check=OK, now=NOW)
    assert loose["projected"]["after"]["gross"] == pytest.approx(0.7025, abs=1e-3), "the planner's own 98% allows the call's 0.70"
    assert not md.authorize(loose, CASH, M, {}, NOW)["ok"], "and the mandate refuses it"
    t = ex.plan(CASH, quotes, C70, _P(), W9, today="2026-11-09", ledger_check=OK, now=NOW, limits={"max_gross": M.max_gross, "cash_floor": M.cash_floor})
    assert t["policy"]["max_gross"] == 0.60 and t["policy"]["cash_floor"] == 0.40
    # 0.60 / 9 of 100,000 at 100 is 66.7 shares a name: 66 whole shares, 59,400 held, 40,540.60 cash after the collar
    assert {o["quantity"] for o in t["orders"]} == {66.0} and len(t["orders"]) == 9 and t["all_checks_pass"]
    assert t["projected"]["after"]["cash"] == pytest.approx(100_000 - 9 * 66 * 100.10)
    assert t["projected"]["after"]["gross"] <= 0.60 and t["projected"]["after"]["cash_share"] >= 0.40
    assert md.authorize(t, CASH, M, {}, NOW)["ok"]


def test_buys_that_breach_after_fees_are_cut_to_fit(state):
    """A 3% commission: the target fits 0.60 / 0.40 before fees, and the fees take the cash under its floor. The buys
    are cut, in whole shares, until the projected account is inside both limits, and the ticket says why."""
    quotes = {n: {"bid": 100.0, "ask": 100.0, "last": 100.0} for n in NAMES}
    t = ex.plan(CASH, quotes, C70, _P(fee_bp=300.0), W9, today="2026-11-09", ledger_check=OK, now=NOW, limits={"max_gross": 0.60, "cash_floor": 0.40})
    rz = t["projected"]["resized"]
    assert "cash" in rz["binding"] and "the cash floor" in rz["why"]          # the fees also shrink the NAV the gross is measured on and rz["buys_usd"] < rz["buys_usd_wanted"]
    after = t["projected"]["after"]
    assert after["cash_share"] >= 0.40 and after["gross"] <= 0.60 and t["all_checks_pass"]
    one_more = lim.project({}, CASH["cash"], [{**o, "quantity": o["quantity"] + 1} for o in t["orders"]], {n: 100.0 for n in NAMES}, 300.0)
    assert not lim.account_checks(one_more, {"max_gross": 0.60, "cash_floor": 0.40})["meets"], "one more share of each would not fit"


def test_a_cash_only_mandate_is_also_a_ceiling(state):
    quotes = {n: {"bid": 100.0, "ask": 100.0, "last": 100.0} for n in NAMES}
    t = ex.plan(CASH, quotes, C70, _P(), W9, today="2026-11-09", ledger_check=OK, now=NOW, limits={"cash_floor": 0.38})
    # a 38% cash floor in a cash account is a 62% ceiling on what is held: 0.62 / 9 of 100,000 is 68.9 shares, 68 whole
    assert t["policy"] == {"cash_floor": 0.38, "max_gross": pytest.approx(0.62), "max_order_pct": 0.25, "max_order_usd": 50_000}
    assert {o["quantity"] for o in t["orders"]} == {68.0} and t["projected"]["after"]["cash_share"] >= 0.38


def test_the_mandate_reads_the_account_as_it_is_now(state):
    quotes = {n: {"bid": 100.0, "ask": 100.0, "last": 100.0} for n in NAMES}
    M = md.Mandate(max_gross=0.60, cash_floor=0.40, max_order_usd=50_000)
    t = ex.plan(CASH, quotes, C70, _P(), W9, today="2026-11-09", ledger_check=OK, now=NOW, limits={"max_gross": 0.60, "cash_floor": 0.40})
    assert md.authorize(t, CASH, M, {}, NOW)["ok"]
    # the same ticket against an account that has since spent 1,000 of its cash on a position
    spent = {**CASH, "cash": 99_000.0, "positions": [{"symbol": "ORCL", "quantity": 10.0}]}
    a2 = md.authorize(t, spent, M, {}, NOW)
    assert not a2["ok"] and any("max_gross" in r for r in a2["reasons"]), "an approval of the ticket is not an approval of the changed account"
    P = _P()
    call = {"asof": C70["asof"], "size": C70["size"], "decision_id": None}
    assert "holdings changed: ORCL" in trader.stale(t, spent, quotes, call, P)
    moved = {**quotes, "ORCL": {"bid": 101.0, "ask": 101.0, "last": 101.0}}
    assert "ORCL moved 1.00%" in trader.stale(t, CASH, moved, call, P) and trader.stale(t, CASH, quotes, call, P) is None
    assert "the decision changed" in trader.stale(t, CASH, quotes, {"asof": "2026-11-09", "size": 0.70, "decision_id": "9-abc"}, P)
    assert "the cash changed" in trader.stale(t, {**CASH, "cash": 99_500.0}, quotes, call, P)
    src = inspect.getsource(trader.run_once)
    assert "stale(t, account, quotes, call, P)" in src and '"restaged"' in src and "limits=mandate_limits" in src


def test_an_account_already_in_breach_may_only_be_repaired(state):
    """Gross 64% against a 60% limit. The drift band does not hold back the reductions, the ticket only sells, and
    the breach is stated. A buy in the same state is refused."""
    px = 100.0
    quotes = {n: {"bid": px, "ask": px, "last": px} for n in NAMES}
    each = 0.08 * 100_000 / px                         # eight names at 8% each: 64% gross, each 2.4% over its 5.56% target
    acct = {"equity": 100_000.0, "cash": 36_000.0, "account_type": "agentic", "positions": [{"symbol": n, "quantity": each} for n in NAMES[:8]]}
    t = ex.plan(acct, quotes, CALL, _P(drift_band=0.03), W9, today="2026-11-09", ledger_check=OK, now=NOW, limits={"max_gross": 0.60, "cash_floor": 0.40})
    assert t["projected"]["breach_before"] == ["gross", "cash"]
    assert t["orders"] and all(o["side"] == "sell" for o in t["orders"]), "inside a 3% band none of these would have traded; a repair is not held back"
    assert t["stage"] == "sells first" and t["projected"]["after"]["gross"] < t["projected"]["before"]["gross"]
    assert [c for c in t["checks"] if c["check"].startswith("gross after")][0]["pass"]
    M = md.Mandate(max_gross=0.60, cash_floor=0.40, max_order_usd=50_000)
    assert md.authorize(t, acct, M, {}, NOW)["ok"]
    # a ticket that sells too little to get inside still passes as a repair, and says so; one that buys does not
    part = {**t, "orders": [{**t["orders"][0], "quantity": 1.0}]}
    a = md.authorize(part, acct, M, {}, NOW)
    assert a["ok"] and a["projected"]["repairs"] == ["gross", "cash"] and a["projected"]["gross"] > 0.60
    buy = {**t, "orders": [{"symbol": "ORCL", "side": "buy", "quantity": 1.0, "limit_price": 100.1, "seq": 1}]}
    assert not md.authorize(buy, acct, M, {}, NOW)["ok"]
    # a held position with no mark cannot be checked, and that is not a pass
    blind = lim.account_checks(lim.project({"XYZ": 10.0}, 1_000.0, [], {}), {"max_gross": 0.6, "cash_floor": 0.4})
    assert not blind["meets"] and blind["unchecked"] == ["gross", "cash"]
