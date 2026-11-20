"""Executions and paper settlement (v0.48): fills are told apart by execution, bad rows change nothing, and the
paper account takes its fills in the order the closes happened. No broker and no network: a temporary state folder."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from buildout import broker as br
from buildout import execution as ex


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path))
    monkeypatch.setattr(ex, "PRIVATE", tmp_path / "private")
    return tmp_path


def _ticket(orders, mode="live"):
    core = {"mode": mode, "orders": [{"seq": i + 1, "type": "limit", **o} for i, o in enumerate(orders)]}
    t = {"id": "tkt-" + ex._sha(core)[:16], **core}
    ex._save_ticket(t)
    return t["id"]


BUY10 = [{"symbol": "NVDA", "side": "buy", "quantity": 10.0, "limit_price": 200.0}]


def _fill(q, px=199.0, **kw):
    return {"symbol": "NVDA", "side": "buy", "quantity": q, "price": px, "order_id": "rh-1", **kw}


def test_two_partial_fills_on_one_order_are_ten_shares(state):
    tid = _ticket(BUY10)
    r1 = ex.record_fills(tid, [_fill(4, execution_id="e1")])
    assert r1["status"] == "partially_filled" and r1["accepted"] == 1 and not r1["issues"]
    r2 = ex.record_fills(tid, [_fill(6, 199.5, execution_id="e2")])
    assert r2["status"] == "filled" and not r2["issues"], "before v0.48 the second fill was dropped as already recorded"
    assert sum(f["quantity"] for f in ex.accepted_fills(tid)) == 10
    # the same two reports again: recorded once, no issue, no new entry, status unchanged
    n = len(ex._fills())
    r3 = ex.record_fills(tid, [_fill(4, execution_id="e1"), _fill(6, 199.5, execution_id="e2")])
    assert r3["duplicates"] == 2 and r3["accepted"] == 0 and r3["entry"] is None and r3["status"] == "filled" and len(ex._fills()) == n
    assert ex.load_ticket(tid)["status"] == "filled" and ex.verify_fills()["ok"]
    assert ex.replay(10_000.0)["positions"] == {"NVDA": 10.0}
    assert ex.replay(10_000.0)["cash"] == pytest.approx(10_000 - 4 * 199.0 - 6 * 199.5)


def test_without_an_execution_id_the_fill_itself_is_the_identity(state):
    tid = _ticket(BUY10)
    assert ex.record_fills(tid, [_fill(4)])["accepted"] == 1
    assert ex.record_fills(tid, [_fill(4)])["duplicates"] == 1, "the same report again"
    r = ex.record_fills(tid, [_fill(6, 199.5)])
    assert r["accepted"] == 1 and r["status"] == "filled", "a different fill on the same order is a new execution"


def test_an_orders_total_so_far_adds_only_what_is_new(state):
    tid = _ticket(BUY10)
    seen = [ex.record_fills(tid, [_fill(q, px, cumulative=True)]) for q, px in ((4, 199.0), (10, 199.3), (10, 199.3))]
    assert [r["accepted"] for r in seen] == [1, 1, 0] and seen[1]["status"] == "filled" and seen[2]["duplicates"] == 1
    fills = ex.accepted_fills(tid)
    assert [f["quantity"] for f in fills] == [4, 6]
    # the second execution's price is what makes the average 199.30 over ten shares: (1993 - 796) / 6 = 199.50
    assert fills[1]["price"] == pytest.approx(199.50) and fills[1]["from_total"] == {"quantity": 10.0, "avg_price": 199.3}
    assert sum(f["quantity"] * f["price"] for f in fills) == pytest.approx(1993.0)
    # a total that falls is refused and changes nothing
    r = ex.record_fills(tid, [_fill(7, 199.0, cumulative=True)])
    assert r["rejected"] == 1 and r["accepted"] == 0 and "fell" in r["issues"][0]
    assert sum(f["quantity"] for f in ex.accepted_fills(tid)) == 10
    assert ex.record_fills(tid, [{"symbol": "NVDA", "side": "buy", "quantity": 3, "price": 199, "cumulative": True}])["rejected"] == 1, "a total needs its order"


@pytest.mark.parametrize("bad", [{"quantity": -5}, {"quantity": 0}, {"quantity": float("nan")}, {"quantity": float("inf")}, {"quantity": "many"},
                                 {"price": -1.0}, {"price": 0}, {"price": float("nan")}, {"price": float("inf")}, {"fees": float("nan")},
                                 {"side": "short"}, {"currency": "EUR"}])
def test_a_bad_row_changes_no_holding_and_no_total(state, bad):
    tid = _ticket(BUY10)
    ex.record_fills(tid, [_fill(4, execution_id="e1")])
    before = ex.replay(10_000.0)
    r = ex.record_fills(tid, [{**_fill(3, execution_id="e9"), **bad}])
    assert r["accepted"] == 0 and r["rejected"] == 1 and r["issues"] and r["status"] == "partially_filled"
    assert ex.replay(10_000.0) == before and sum(f["quantity"] for f in ex.accepted_fills(tid)) == 4
    last = ex._fills()[-1]
    assert last["fills"] == [] and last["rejected"][0]["why"] and ex.verify_fills()["ok"], "kept, with the reason, apart from the accepted fills"
    # the good fill still completes the order afterwards, but a ticket that has had an issue is not marked filled
    r2 = ex.record_fills(tid, [_fill(6, execution_id="e2")])
    assert r2["accepted"] == 1 and r2["status"] == "partially_filled" and sum(f["quantity"] for f in ex.accepted_fills(tid)) == 10


def test_excess_and_strangers_are_recorded_and_flagged(state):
    tid = _ticket(BUY10)
    r = ex.record_fills(tid, [_fill(12, execution_id="e1")])
    assert r["accepted"] == 1 and any("12 in all against 10 ordered" in i for i in r["issues"]) and r["status"] == "partially_filled"
    r = ex.record_fills(tid, [{"symbol": "TSLA", "side": "buy", "quantity": 1, "price": 400.0, "order_id": "rh-2", "execution_id": "e2"}])
    assert r["accepted"] == 1 and any("not on the ticket" in i for i in r["issues"])
    assert ex.replay(0.0)["positions"] == {"NVDA": 12.0, "TSLA": 1.0}, "what the broker did is what the account holds"


def test_a_cancelled_order_keeps_what_it_filled_and_fees_are_counted_once(state):
    tid = _ticket(BUY10)
    r = ex.record_fills(tid, [_fill(4, execution_id="e1", status="cancelled", fees=0.35)])
    assert r["status"] == "partially_filled" and ex.accepted_fills(tid)[0]["status"] == "cancelled"
    assert ex.replay(1_000.0)["cash"] == pytest.approx(1_000.0 - 4 * 199.0 - 0.35)
    ex.record_fills(tid, [_fill(4, execution_id="e1", status="cancelled", fees=0.35)])
    assert ex.replay(1_000.0)["cash"] == pytest.approx(1_000.0 - 4 * 199.0 - 0.35), "a retry does not charge the fee again"
    sell = _ticket([{"symbol": "NVDA", "side": "sell", "quantity": 2.0, "limit_price": 190.0}])
    ex.record_fills(sell, [{"symbol": "NVDA", "side": "sell", "quantity": 2, "price": 200.0, "order_id": "rh-9", "execution_id": "s1", "fees": -0.10}])
    assert ex.replay(0.0, {"NVDA": 2.0}, sell) == {"cash": pytest.approx(400.10), "positions": {}}, "a negative fee is a rebate"


def test_every_broker_route_says_what_it_sends():
    assert set(ex.FILL_ADAPTERS) == {"paper", "robinhood_mcp", "assistant"}
    assert "cumulative" in ex.FILL_ADAPTERS["robinhood_mcp"] and "one execution per order" in ex.FILL_ADAPTERS["paper"]
    import inspect
    from buildout import trader
    assert '"cumulative": True' in inspect.getsource(trader.run_once), "the poller reports an order's total so far, and says so"
    assert "execution_id" in inspect.getsource(trader._paper_fill_rows)


# ---------------------------------------------------------------- paper settlement in economic time
CLOSES = {"A": {"2026-11-10": 100.0, "2026-11-11": 100.0, "2026-11-12": 100.0, "2026-11-13": 100.0},
          "B": {"2026-11-10": 99.0, "2026-11-11": 110.0, "2026-11-12": 110.0, "2026-11-13": 110.0}}


def _at(day, hour=15):
    return datetime(2026, 11, day, hour, 0, tzinfo=timezone.utc)


def _paper(path, upto):
    clock = {"now": _at(10, 22)}

    def qf(S):
        return {s: {"last": [c for d, c in sorted(CLOSES[s].items()) if d <= upto["d"]][-1], "asof": upto["d"],
                    "closes": {d: c for d, c in CLOSES[s].items() if d <= upto["d"]}} for s in S}
    pb = br.PaperBroker(path, quote_fn=qf, start_cash=100.0, clock=lambda: clock["now"])
    pb.state["positions"] = {"A": 1.0}
    pb.quotes(["A", "B"])
    return pb, clock


def _run(path, passes):
    """Write the two orders at their own times, then settle at each of `passes` (day numbers, after the close)."""
    upto = {"d": "2026-11-10"}
    pb, clock = _paper(path, upto)
    events = [("order", 11, ("B", "buy", 1.0, 99.5, "t1-1")), ("order", 12, ("A", "sell", 1.0, 99.0, "t2-1"))] + [("settle", d, None) for d in passes]
    for kind, day, o in sorted(events, key=lambda e: (e[1], e[0] != "order")):
        if kind == "order":
            clock["now"] = _at(day, 15)                          # 10:00 in New York: before that day's close
            pb.place(*o)
        else:
            clock["now"] = _at(day, 22)                          # after the close
            upto["d"] = f"2026-11-{day}"
            pb.quotes(["A", "B"])
            pb.settle(clock["now"])
    return pb.state


def test_a_later_sale_does_not_pay_for_an_earlier_purchase(tmp_path):
    """Cash 100 and one share of A. A buy of B fills at the 11 November close: 110 plus the half-spread is 110.055,
    more than the 100 in cash, so it is refused. The sale of A at the 12 November close raises 99.95. Settled
    together on the 13th, the sale's proceeds must not reach back to the 11th."""
    late = _run(tmp_path / "late.json", [13])
    b, a = late["orders"]["t1-1"], late["orders"]["t2-1"]
    assert b["status"] == "rejected" and "110.06" in b["reason"] and "100.00 in cash" in b["reason"]
    assert a["status"] == "filled" and a["fill_session"] == "2026-11-12" and a["avg_price"] == pytest.approx(99.95)
    assert late["cash"] == pytest.approx(199.95) and late["positions"] == {}
    # settling after each session gives the same account, order for order
    daily = _run(tmp_path / "daily.json", [11, 12, 13])
    pick = lambda st: {k: {f: o.get(f) for f in ("status", "fill_session", "avg_price", "filled", "reason")} for k, o in st["orders"].items()}
    assert pick(daily) == pick(late) and daily["cash"] == pytest.approx(late["cash"]) and daily["positions"] == late["positions"]


def test_inside_one_close_the_sale_funds_the_purchase_and_ties_break_the_same_way(tmp_path):
    upto = {"d": "2026-11-10"}
    pb, clock = _paper(tmp_path / "same.json", upto)
    pb.state["cash"] = 100.0
    clock["now"] = _at(11, 15)
    pb.place("B", "buy", 0.9, 99.5, "t1-1")                      # written first; needs the sale's cash at 110
    pb.state["cash"] = 20.0                                       # the cash is spent elsewhere before the close
    pb.place("A", "sell", 1.0, 99.0, "t1-2")
    clock["now"], upto["d"] = _at(11, 22), "2026-11-11"
    pb.quotes(["A", "B"])
    changed = pb.settle(clock["now"])
    assert [o["client_id"] for o in changed] == ["t1-2", "t1-1"], "the sale first, at the same close"
    assert all(o["status"] == "filled" and o["fill_session"] == "2026-11-11" for o in changed)
    assert pb.state["cash"] == pytest.approx(20.0 + 99.95 - 0.9 * 110.055)
    again = pb.settle(clock["now"])
    assert again == [] and json.loads((tmp_path / "same.json").read_text())["cash"] == pytest.approx(pb.state["cash"]), "a second pass changes nothing"


def test_an_interrupted_pass_resumes_to_the_same_account(tmp_path):
    whole = _run(tmp_path / "whole.json", [13])
    upto = {"d": "2026-11-10"}
    pb, clock = _paper(tmp_path / "cut.json", upto)
    clock["now"] = _at(11, 15); pb.place("B", "buy", 1.0, 99.5, "t1-1")
    clock["now"] = _at(12, 15); pb.place("A", "sell", 1.0, 99.0, "t2-1")
    clock["now"], upto["d"] = _at(13, 22), "2026-11-13"
    pb.quotes(["A", "B"])
    pb.save = lambda state=None: (_ for _ in ()).throw(OSError("disk full"))        # the pass dies at the write
    with pytest.raises(OSError):
        pb.settle(clock["now"])
    assert all(o["status"] == "open" for o in pb.state["orders"].values()) and pb.state["cash"] == 100.0, "all or nothing"
    del pb.save
    pb.settle(clock["now"])
    assert pb.state["cash"] == pytest.approx(whole["cash"]) and {k: o["status"] for k, o in pb.state["orders"].items()} == {k: o["status"] for k, o in whole["orders"].items()}
