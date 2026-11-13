"""v0.44.1: the bug-hunt fixes. The trader's halts read yesterday (not the point it just wrote), the account is marked
at the pass's own quotes, the mandate's max_gross is enforced, `trade halt` stops every state root, the assistant
route never hands the same orders over twice, the Yahoo stand-ins work and drop a session still trading, and a
malformed MCP request is an error reply, not a dead server."""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from buildout import broker as br
from buildout import execution as ex
from buildout import mandate as md
from buildout import trader

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
PX = {"MSFT": 505.1, "AMZN": 236.2, "GOOGL": 280.4, "META": 610.0, "NVDA": 198.6, "AVGO": 349.0, "TSLA": 430.2, "SPCX": 48.3, "ORCL": 230.5, "VIXY": 38.0, "PSQ": 30.0}


def _qf(S, px=PX):
    return {s: {"bid": px[s] * 0.9995, "ask": px[s] * 1.0005, "last": px[s], "asof": "2026-11-09"} for s in S if s in px}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path))
    monkeypatch.setattr(ex, "PRIVATE", tmp_path / "private")
    return tmp_path


def _params():
    P = ex.load_params()
    P.vix_share, P.variant = 0.0, "unhedged"
    return P


def _call():
    c = dict(ex.latest_call())
    c["asof"], c["effective_from"] = "2026-11-06", "2026-11-09"
    return c


def _write_equity(state, rows):
    d = state / "trader"
    d.mkdir(parents=True, exist_ok=True)
    (d / "equity.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_yesterday_is_not_the_point_just_written(state):
    _write_equity(state, [{"date": "2026-11-06", "equity": 100_000.0}, {"date": "2026-11-09", "equity": 92_000.0}])
    h = trader._equity_history(before="2026-11-09")
    assert h["prev_equity"] == 100_000.0 and h["peak_equity"] == 100_000.0
    eq = 92_000.0
    M = md.Mandate()
    assert eq / h["prev_equity"] - 1 < -M.halt_day_loss          # an 8% day now trips the 5% halt


def test_a_torn_equity_line_is_skipped_not_fatal(state):
    d = state / "trader"
    d.mkdir(parents=True)
    (d / "equity.jsonl").write_text('{"date": "2026-11-06", "equity": 100000.0}\n{"date": "2026-11-0')
    assert trader._equity_history()["prev_equity"] == 100_000.0


def test_the_spacing_rule_counts_from_the_session_traded(state):
    d = state / "trader"
    d.mkdir(parents=True)
    (d / "journal.jsonl").write_text(json.dumps({"ts_utc": "2026-11-10T15:00:00Z", "event": "executed", "fill_session": "2026-11-09", "ordered": "2026-11-09T15:00:00Z"}) + "\n")
    assert trader._equity_history()["last_ticket_date"] == "2026-11-09"


def test_the_target_carries_gross_total_and_the_mandate_enforces_it():
    P = _params()
    T = ex.target(_call(), P, {"NVDA": 0.5, "MSFT": 0.5})
    assert T["gross_total"] == pytest.approx(T["book_gross"] + T["short"] + T["vix"])
    M = md.Mandate(max_gross=0.10, max_order_usd=1e9, max_order_pct=1.0, max_day_turnover_pct=10.0)
    ticket = {"target": {"gross_total": 0.5}, "orders": [], "id": "tkt-0000000000000000"}
    auth = md.authorize(ticket, {"equity": 100_000.0, "cash": 100_000.0}, M, {"tickets_executed": 0}, NOW)
    assert any("max_gross" in r for r in auth["reasons"])


def test_private_halt_stops_a_run_under_another_state_root(state):
    assert ex.halted() is None
    (state / "private").mkdir()
    (state / "private" / "HALT").write_text("x")
    assert "HALT" in ex.halted()


def test_the_paper_pass_marks_equity_at_its_own_quotes(state):
    pb = br.PaperBroker(state / "paper_account.json", quote_fn=_qf)
    M = md.Mandate(mode="autonomous", broker="paper", max_order_usd=50_000)
    trader.run_once(pb, M, _params(), now=NOW, call=_call(), poll_seconds=0.01)
    trader.run_once(pb, M, _params(), now=NOW + timedelta(days=1), call=_call())       # fills at the Nov 9 close
    up = {k: v * 1.10 for k, v in PX.items()}
    pb.quote_fn = lambda S: _qf(S, up)
    r = trader.run_once(pb, M, _params(), now=NOW + timedelta(days=2), call=_call())
    rows = [json.loads(x) for x in (state / "trader" / "equity.jsonl").read_text().splitlines()]
    assert rows[-1]["equity"] == pytest.approx(r["account"]["equity"]) and rows[-1]["equity"] > rows[-2]["equity"] * 1.03


def test_the_assistant_route_never_hands_the_same_orders_twice(state, monkeypatch):
    monkeypatch.setattr(trader, "evidence", lambda *a, **k: {"open": True, "missing": []})
    M = md.Mandate(mode="autonomous", armed=True, broker="assistant", signed_by="J", signed_on="2026-11-08", notes="rehearsal", max_order_usd=50_000)

    def ab():
        return br.AssistantBroker({"equity": 50_000.0, "cash": 50_000.0, "account_type": "Agentic", "positions": []}, _qf(list(PX)))
    r1 = trader.run_once(ab(), M, _params(), now=NOW, call=_call())
    assert r1["outcome"] == "handed to the assistant"
    r2 = trader.run_once(ab(), M, _params(), now=NOW + timedelta(minutes=5), call=_call())
    assert r2["outcome"] == "already handed to the assistant" and r2["ticket"] == r1["ticket"] and "handoff" not in r2


class _LiveBroker:
    """A live route whose every order partly fills and then times out; cancel() answers without a fill count, as
    Robinhood's MCP cancel does."""
    name = "mcp"

    def __init__(self):
        self.orders = {}

    def account(self):
        return {"equity": 100_000.0, "cash": 100_000.0, "account_type": "Agentic", "positions": []}

    def quotes(self, symbols):
        return _qf(symbols)

    def place(self, symbol, side, quantity, limit, client_id):
        self.orders[client_id] = {"order_id": client_id, "status": "open", "filled_qty": 0.0}
        return dict(self.orders[client_id])

    def order(self, oid):
        o = self.orders[oid]
        return {"order_id": oid, "status": o["status"], "filled_qty": 1.0, "avg_price": None}

    def cancel(self, oid):
        self.orders[oid]["status"] = "cancelled"
        return {"order_id": oid, "raw": {}}

    def open_orders(self):
        return []


def test_a_timed_out_live_order_keeps_what_filled(state, monkeypatch):
    monkeypatch.setattr(trader, "evidence", lambda *a, **k: {"open": True, "missing": []})
    M = md.Mandate(mode="autonomous", armed=True, broker="robinhood_mcp", signed_by="J", signed_on="2026-11-08", notes="rehearsal", max_order_usd=50_000)
    r = trader.run_once(_LiveBroker(), M, _params(), now=NOW, call=_call(), poll_seconds=0.0, max_wait_seconds=0.0)
    assert r["outcome"] == "executed" and r["fills"] and all(f["quantity"] == 1.0 for f in r["fills"])


def test_parse_yahoo_drops_a_session_still_trading():
    from buildout import datahub
    day = 86_400
    t0 = 1_762_700_000
    js = {"chart": {"result": [{"timestamp": [t0, t0 + day], "meta": {"currentTradingPeriod": {"regular": {"start": t0 + day - 10, "end": t0 + day + 23_400}}},
                                "indicators": {"quote": [{"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1.0, 2.0], "volume": [10, 20]}]}}]}}
    assert len(datahub.parse_yahoo(js, now=t0 + day + 3_600)) == 1               # mid-session: the live bar is not a close
    assert len(datahub.parse_yahoo(js, now=t0 + day + 30_000)) == 2              # after the close it is


def test_the_fred_index_fallback_reads_yahoos_frame(monkeypatch):
    from buildout import datahub
    from buildout.data import fred_source
    idx = pd.DatetimeIndex(["2026-11-10", "2026-11-11"], name="date")
    monkeypatch.setattr(datahub, "yahoo", lambda t, years=10: pd.DataFrame({"close": [1.0, 2.0]}, index=idx))
    sid = next(iter(fred_source.INDEX_TICKERS))
    s = fred_source.from_index(sid)
    assert list(s) == [1.0, 2.0] and s.index[0] == pd.Timestamp("2026-11-10")


def test_a_malformed_mcp_request_is_an_error_not_a_crash():
    from buildout import mcp_server
    ctx = mcp_server.Context(None, None)
    for msg in ({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": [1]},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": []}}):
        assert "error" in mcp_server.handle(ctx, msg)
    out = io.StringIO()
    mcp_server.serve(ctx, io.StringIO('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":[1]}\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n'), out)
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert lines[0]["id"] == 1 and "error" in lines[0] and lines[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}
