"""v0.42.3: the outside review's reliability findings (Nov 11, 2026), each reproduced, then pinned.
  B-01  the Pages job builds the site with no packages installed; the ledger imported pandas
  B-03  a refused paper order changed the account in memory (cash -102 after a refused $202 buy on $100)
  B-04  the direct broker sent an order before recording it, so a failed write and a retry could send it twice
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from buildout import broker as br
from buildout.broker import OrderJournal, OrderUnknown, PaperBroker, validate_order

ROOT = Path(__file__).resolve().parents[1]


def _pb(tmp_path, cash=100.0):
    pb = PaperBroker(tmp_path / "acct.json", quote_fn=lambda S: {s: {"bid": 100.0, "ask": 100.1, "last": 100.0} for s in S}, start_cash=cash)
    pb.quotes(["X"])
    pb.save()
    return pb


def _snapshot(pb):
    return json.dumps(pb.state, sort_keys=True), pb.path.read_text()


# ---------------------------------------------------------------- B-03, the paper broker
def test_an_unaffordable_buy_changes_nothing_in_memory_or_on_disk(tmp_path):
    pb = _pb(tmp_path)
    before = _snapshot(pb)
    with pytest.raises(RuntimeError, match="costs 202.00"):
        pb.place("X", "buy", 2, 101.0, "c1")
    assert _snapshot(pb) == before and pb.state["cash"] == 100.0 and pb.state["positions"] == {} and pb.state["orders"] == {}


def test_an_oversell_changes_nothing(tmp_path):
    pb = _pb(tmp_path, cash=1000.0)
    pb.place("X", "buy", 3, 101.0, "c1")
    before = _snapshot(pb)
    with pytest.raises(RuntimeError, match="selling 4"):
        pb.place("X", "sell", 4, 99.0, "c2")
    assert _snapshot(pb) == before


@pytest.mark.parametrize("side,qty,lim,cid,msg", [("hold", 1, 101.0, "c", "side"), ("buy", -1, 101.0, "c", "quantity"), ("buy", 0, 101.0, "c", "quantity"),
                                                   ("buy", 1, math.nan, "c", "limit"), ("buy", math.inf, 101.0, "c", "quantity"), ("buy", 1, 101.0, "", "client id")])
def test_bad_input_is_refused_without_mutation(tmp_path, side, qty, lim, cid, msg):
    pb = _pb(tmp_path)
    before = _snapshot(pb)
    with pytest.raises(ValueError, match=msg):
        pb.place("X", side, qty, lim, cid)
    assert _snapshot(pb) == before


def test_a_repeated_client_id_has_one_effect_and_a_reused_one_is_refused(tmp_path):
    pb = _pb(tmp_path, cash=1000.0)
    a = pb.place("X", "buy", 2, 101.0, "c1")
    b = pb.place("X", "buy", 2, 101.0, "c1")
    assert a == b and len(pb.state["orders"]) == 1 and a["status"] == "open"          # v0.42.5: one resting order, nothing filled yet
    assert pb.state["positions"] == {} and pb.state["cash"] == pytest.approx(1000.0)
    with pytest.raises(ValueError, match="different order"):
        pb.place("X", "buy", 3, 101.0, "c1")
    assert len(pb.state["orders"]) == 1


def test_a_failed_disk_write_leaves_the_committed_account(tmp_path, monkeypatch):
    pb = _pb(tmp_path, cash=1000.0)
    before = _snapshot(pb)

    def boom(path, obj):
        raise OSError("disk full")
    monkeypatch.setattr(br, "_atomic_write_json", boom)
    with pytest.raises(OSError):
        pb.place("X", "buy", 2, 101.0, "c1")
    assert _snapshot(pb) == before                                       # neither memory nor the file moved
    assert PaperBroker(tmp_path / "acct.json").state["cash"] == 1000.0  # and a restart reads the prior account


def test_writes_are_atomic(tmp_path):
    br._atomic_write_json(tmp_path / "a.json", {"x": 1})
    assert json.loads((tmp_path / "a.json").read_text()) == {"x": 1} and not list(tmp_path.glob(".a.json.*.tmp"))


# ---------------------------------------------------------------- B-04, the direct broker
class _Remote:
    """A Robinhood stand-in: records every placement; can fail before or after accepting one."""

    def __init__(self, fail_after_accept=False, fail_before=False, list_by_client_id=True):
        self.placed, self.fail_after_accept, self.fail_before, self.list = [], fail_after_accept, fail_before, list_by_client_id

    def call(self, role, **kw):
        if role == "place":
            if self.fail_before:
                raise ConnectionError("connection refused")
            self.placed.append(kw)
            if self.fail_after_accept:
                raise TimeoutError("read timed out")                 # the order exists; the reply was lost
            return {"id": f"rh-{len(self.placed)}", "state": "queued"}
        if role == "recent_orders":
            return [{"id": f"rh-{i + 1}", "state": "queued", "client_id": p["client_id"]} for i, p in enumerate(self.placed)] if self.list else []
        if role == "review":
            return {"ok": True}
        raise KeyError(role)


def _mcp(remote, with_listing=True):
    tools = {"place": "place_equity_order"}
    if with_listing:
        tools["recent_orders"] = "get_orders"
    b = br.MCPBroker({"url": "http://127.0.0.1:1/mcp", "tools": tools, "args": {}, "paths": {}}, oauth=br.OAuth("http://127.0.0.1:1/mcp", Path("/nonexistent")))
    b.call = remote.call
    return b


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path))
    return tmp_path


def test_a_lost_reply_is_unknown_and_a_retry_reconciles_instead_of_resending(state):
    r = _Remote(fail_after_accept=True)
    b = _mcp(r)
    with pytest.raises(OrderUnknown):
        b.place("NVDA", "buy", 3, 199.0, "tkt-1-1")
    assert len(r.placed) == 1 and OrderJournal("robinhood_mcp", "agentic").get("tkt-1-1")["state"] == "unknown"
    r.fail_after_accept = False
    o = b.place("NVDA", "buy", 3, 199.0, "tkt-1-1")                       # the retry
    assert len(r.placed) == 1                                             # still one order at the broker
    assert o["state"] == "acknowledged" and o["order_id"] == "rh-1" and o["note"] == "reconciled by client id"


def test_without_a_way_to_reconcile_an_unknown_order_is_never_resent(state):
    r = _Remote(fail_after_accept=True)
    b = _mcp(r, with_listing=False)
    with pytest.raises(OrderUnknown):
        b.place("NVDA", "buy", 3, 199.0, "tkt-1-1")
    r.fail_after_accept = False
    for _ in range(3):
        with pytest.raises(OrderUnknown, match="not sending again"):
            b.place("NVDA", "buy", 3, 199.0, "tkt-1-1")
    assert len(r.placed) == 1
    br.resolve("tkt-1-1", order_id="rh-1")                               # the person checks the app and says so
    assert b.place("NVDA", "buy", 3, 199.0, "tkt-1-1")["state"] == "acknowledged" and len(r.placed) == 1


def test_a_failed_journal_write_after_placement_does_not_resend(state, monkeypatch):
    r = _Remote()
    b = _mcp(r)
    real = OrderJournal.update
    calls = {"n": 0}

    def flaky(self, cid, state, **kw):
        calls["n"] += 1
        if state == "acknowledged" and calls["n"] < 3:
            raise OSError("disk full")
        return real(self, cid, state, **kw)
    monkeypatch.setattr(OrderJournal, "update", flaky)
    o = b.place("NVDA", "buy", 3, 199.0, "tkt-2-1")
    assert "journal_warning" in o and len(r.placed) == 1
    assert OrderJournal("robinhood_mcp", "agentic").get("tkt-2-1")["state"] == "submitting"
    o2 = b.place("NVDA", "buy", 3, 199.0, "tkt-2-1")                      # the retry the review reproduced
    assert len(r.placed) == 1 and o2["order_id"] == "rh-1"


def test_a_refused_connection_is_still_unknown(state):
    r = _Remote(fail_before=True)
    with pytest.raises(OrderUnknown):
        _mcp(r).place("NVDA", "buy", 3, 199.0, "tkt-3-1")
    assert OrderJournal("robinhood_mcp", "agentic").unresolved()[0]["client_id"] == "tkt-3-1"


def test_a_client_id_journaled_for_another_order_is_refused(state):
    r = _Remote()
    b = _mcp(r)
    b.place("NVDA", "buy", 3, 199.0, "tkt-4-1")
    with pytest.raises(ValueError, match="different order"):
        b.place("NVDA", "buy", 4, 199.0, "tkt-4-1")
    assert len(r.placed) == 1 and b.place("NVDA", "buy", 3, 199.0, "tkt-4-1")["order_id"] == "rh-1"


def test_the_journal_refuses_a_second_prepare_and_unknown_states(state):
    J = OrderJournal("robinhood_mcp", "acct")
    J.prepare("c", {"symbol": "X", "side": "buy", "quantity": 1.0, "limit": 1.0})
    with pytest.raises(ValueError):
        J.prepare("c", {"symbol": "X", "side": "buy", "quantity": 1.0, "limit": 1.0})
    with pytest.raises(ValueError):
        J.update("c", state="maybe")
    assert J.path.name == "orders_robinhood_mcp_acct.json"                  # namespaced by broker and account


def test_the_trader_stops_after_an_unknown_order(state):
    """One unknown order, and nothing after it is sent."""
    from datetime import datetime, timezone
    from buildout import execution as ex, mandate as md, trader
    sys.path.insert(0, str(ROOT / "tests"))
    import test_v42 as T

    class Unknowing(br.PaperBroker):
        sent = 0

        def place(self, *a, **k):
            Unknowing.sent += 1
            raise OrderUnknown("lost reply")
    pb = Unknowing(state / "acct.json", quote_fn=T._qf)
    r = trader.run_once(pb, md.Mandate(mode="autonomous", broker="paper", max_order_usd=50_000), T._params(), now=T.NOW, call=T._call(), poll_seconds=0.01)
    assert Unknowing.sent == 1 and r["failures"][0]["unknown"] is True


# ---------------------------------------------------------------- B-01, the Pages build
def test_the_site_builds_with_no_packages(tmp_path):
    """The Pages job installs nothing; build in an interpreter that cannot see this one's packages."""
    out = tmp_path / "_site"
    r = subprocess.run([sys.executable, "-S", "-I", str(ROOT / "scripts" / "build_site.py"), str(ROOT / "site"), str(out)], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-600:]
    m = json.loads((out / "data" / "manifest.json").read_text())
    assert m["built_utc"] and m["page_bytes"] > 1_000_000 and "book.json" in m["data"]
    assert (out / "data" / "calls.json").exists() and (out / "tearsheet.pdf").exists()


def test_validate_order_normalizes():
    assert validate_order(" nvda ", "buy", "3", 199, "c") == ("NVDA", "buy", 3.0, 199.0)
