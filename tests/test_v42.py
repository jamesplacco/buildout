"""v0.42: the trader, the mandate and the brokers. Every mode and route on a paper account with a fixed clock; the
direct MCP client against a small JSON-RPC server in-process; the public paper bot's summary; the MCP tools."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from buildout import broker as br
from buildout import execution as ex
from buildout import mandate as md
from buildout import trader

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)          # a Monday, 10:00 New York, the Nov 6 call in force
PX = {"MSFT": 505.1, "AMZN": 236.2, "GOOGL": 280.4, "META": 610.0, "NVDA": 198.6, "AVGO": 349.0, "TSLA": 430.2, "SPCX": 48.3, "ORCL": 230.5, "VIXY": 38.0, "PSQ": 30.0}


def _qf(S):
    return {s: {"bid": PX[s] * 0.9995, "ask": PX[s] * 1.0005, "last": PX[s], "asof": "2026-11-09"} for s in S if s in PX}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path))
    return tmp_path


def _params():
    P = ex.load_params()
    P.vix_share = 0.0
    P.variant = "unhedged"
    return P


def _call():
    """The latest call's shape, pinned to the ledger's Nov 6 entry (in force from Nov 9, the fixed clock). Pinned
    because the repo's latest call moves every day: read live, these tests failed the day after they were written."""
    c = dict(ex.latest_call())
    c["asof"] = "2026-11-06"
    c["effective_from"] = "2026-11-09"
    return c


def test_mandate_defaults_are_safe_and_problems_are_named():
    M = md.Mandate()
    assert M.mode == "manual" and not M.armed and M.broker == "paper" and M.problems() == []
    bad = md.Mandate(mode="autonomous", armed=True, broker="assistant")
    p = bad.problems()
    assert any("signed_by" in x for x in p) and any("signed_on" in x for x in p) and any("notes" in x for x in p)
    assert md.Mandate(max_gross=0.99, cash_floor=0.02).problems()
    assert md.Mandate().hash() != md.Mandate(max_order_usd=1).hash()


def test_mandate_template_round_trips_and_unknown_keys_are_refused(tmp_path):
    p = tmp_path / "mandate.toml"
    p.write_text(md.template())
    M = md.load(p)
    assert M.mode == "manual" and M.problems() == []
    p.write_text(md.template().replace("max_order_usd", "max_ordr_usd"))
    with pytest.raises(ValueError):
        md.load(p)


def test_window_is_new_york_weekdays():
    M = md.Mandate()
    assert md.in_window(M, NOW)[0]
    assert not md.in_window(M, datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc))[0]           # Sunday
    assert not md.in_window(M, datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc))[0]           # 17:00 New York


def test_autonomous_paper_pass_executes_once_a_day_and_idles_in_the_band(state):
    pb = br.PaperBroker(state / "paper_account.json", quote_fn=_qf)
    M = md.Mandate(mode="autonomous", broker="paper", max_order_usd=50_000)
    r = trader.run_once(pb, M, _params(), now=NOW, call=_call(), poll_seconds=0.01)
    assert r["outcome"] == "executed" and len(r["fills"]) == 9 and r["recorded"]["status"] == "filled" and r["recorded"]["issues"] == []
    assert 99_800 < r["account_after"]["equity"] < 100_000                   # the collar and the half-spread are the only cost
    assert trader.run_once(pb, M, _params(), now=NOW + timedelta(hours=1), call=_call())["outcome"] == "already traded today"
    r3 = trader.run_once(pb, M, _params(), now=NOW + timedelta(days=1), call=_call())
    assert r3["outcome"].startswith("nothing to trade")
    j = trader.journal()
    assert [e["event"] for e in j][-3:] == ["executed", "pass", "pass"]
    assert ex.verify_fills()["ok"] and ex.verify_fills()["entries"] == 1
    assert (state / "trader" / "digest.md").exists()


def test_manual_stages_then_executes_after_approval(state):
    pb = br.PaperBroker(state / "paper_account.json", quote_fn=_qf)
    M = md.Mandate(mode="manual", broker="paper", max_order_usd=50_000)
    r = trader.run_once(pb, M, _params(), now=NOW, call=_call())
    assert r["outcome"] == "staged, awaiting approval" and "--approve" in r["approve_with"]
    with pytest.raises(KeyError):
        trader.approve("tkt-0000000000000000")
    trader.approve(r["ticket"], by="test", now=NOW)
    r2 = trader.run_once(pb, M, _params(), now=NOW + timedelta(minutes=5), call=_call(), poll_seconds=0.01)
    assert r2["outcome"] == "executed" and r2["ticket"] == r["ticket"]
    # an approval older than the mandate's life is refused
    pb2 = br.PaperBroker(state / "paper2.json", quote_fn=_qf)
    os.environ["BUILDOUT_TRADER_STATE"] = str(state / "late")
    r3 = trader.run_once(pb2, M, _params(), now=NOW, call=_call())
    trader.approve(r3["ticket"], by="test", now=NOW - timedelta(minutes=M.approval_ttl_min + 1))
    r4 = trader.run_once(pb2, M, _params(), now=NOW, call=_call())
    assert r4["outcome"] == "staged, awaiting approval" and "older" in r4["reasons"][0]


def test_supervised_takes_a_standing_approval(state):
    pb = br.PaperBroker(state / "paper_account.json", quote_fn=_qf)
    M = md.Mandate(mode="supervised", broker="paper", max_order_usd=50_000)
    assert trader.run_once(pb, M, _params(), now=NOW, call=_call())["outcome"].startswith("staged")
    trader.approve("standing", by="test", standing_minutes=120, now=NOW)
    assert trader.run_once(pb, M, _params(), now=NOW + timedelta(minutes=1), call=_call(), poll_seconds=0.01)["outcome"] == "executed"


def test_the_mandate_refuses_and_the_halt_stops_everything(state):
    pb = br.PaperBroker(state / "paper_account.json", quote_fn=_qf)
    M = md.Mandate(mode="autonomous", broker="paper", max_order_usd=1_000)
    r = trader.run_once(pb, M, _params(), now=NOW, call=_call())
    assert r["outcome"] == "outside the mandate" and any("max_order_usd" in x for x in r["reasons"])
    (state / "HALT").write_text("x")
    assert trader.run_once(pb, md.Mandate(mode="autonomous", max_order_usd=50_000), _params(), now=NOW, call=_call())["outcome"] == "halted"
    (state / "HALT").unlink()
    assert trader.run_once(pb, md.Mandate(mode="autonomous", max_order_usd=50_000), _params(), now=datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc), call=_call())["outcome"] == "outside the window"
    unarmed = md.Mandate(mode="autonomous", broker="assistant", max_order_usd=50_000)
    ab = br.AssistantBroker({"equity": 50_000.0, "cash": 50_000.0, "account_type": "Agentic", "positions": []}, _qf(list(PX)))
    assert trader.run_once(ab, unarmed, _params(), now=NOW, call=_call())["outcome"].startswith("autonomous but not armed")


def test_the_assistant_route_hands_over_exact_orders(state):
    ab = br.AssistantBroker({"equity": 50_000.0, "cash": 50_000.0, "account_type": "Agentic", "positions": []}, _qf(list(PX)))
    M = md.Mandate(mode="autonomous", armed=True, broker="assistant", signed_by="J", signed_on="2026-11-08", notes="rehearsal", max_order_usd=50_000)
    r = trader.run_once(ab, M, _params(), now=NOW, call=_call())
    assert r["outcome"] == "handed to the assistant" and len(r["handoff"]) == 9
    t = ex.load_ticket(r["ticket"])
    assert [(h["symbol"], h["side"], h["quantity"], h["limit"]) for h in r["handoff"]] == [(o["symbol"], o["side"], o["quantity"], o["limit_price"]) for o in t["orders"]]
    assert all("Robinhood" in h["instruction"] for h in r["handoff"])


def test_paper_broker_is_idempotent_and_refuses_overselling(tmp_path):
    pb = br.PaperBroker(tmp_path / "a.json", quote_fn=_qf)
    pb.quotes(["NVDA"])
    o1 = pb.place("NVDA", "buy", 10, PX["NVDA"] * 1.001, "c1")
    o2 = pb.place("NVDA", "buy", 10, PX["NVDA"] * 1.001, "c1")
    assert o1 == o2 and o1["status"] == "filled" and pb.account()["positions"] == [{"symbol": "NVDA", "quantity": 10.0}]
    rest = pb.place("NVDA", "buy", 1, PX["NVDA"] * 0.99, "c2")
    assert rest["status"] == "open" and pb.open_orders() and pb.cancel(rest["order_id"])["status"] == "cancelled"
    with pytest.raises(RuntimeError):
        pb.place("NVDA", "sell", 11, PX["NVDA"] * 0.99, "c3")


class _FakeMCP(BaseHTTPRequestHandler):
    """A tiny MCP server: initialize, tools/list, tools/call for account, quotes, place, order."""
    orders: dict = {}

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        if self.headers.get("Authorization") != "Bearer tok":
            self.send_response(401); self.end_headers(); return
        m = req.get("method")
        if m == "notifications/initialized":
            self.send_response(202); self.end_headers(); return
        if m == "initialize":
            res = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "fake"}}
        elif m == "tools/list":
            res = {"tools": [{"name": "get_account", "inputSchema": {}}, {"name": "get_quotes", "inputSchema": {}}, {"name": "place_equity_order", "inputSchema": {}}, {"name": "get_order", "inputSchema": {}}]}
        elif m == "tools/call":
            name, a = req["params"]["name"], req["params"]["arguments"]
            if name == "get_account":
                res = _txt({"account": {"type": "agentic", "equity": "50000", "buying_power": "50000"}, "positions": [{"symbol": "NVDA", "quantity": "2"}]})
            elif name == "get_quotes":
                res = _txt({"results": [{"symbol": s, "bid_price": PX[s] * 0.9995, "ask_price": PX[s] * 1.0005, "last_trade_price": PX[s]} for s in a["symbols"]]})
            elif name == "place_equity_order":
                oid = f"rh-{len(_FakeMCP.orders) + 1}"
                _FakeMCP.orders[oid] = {"id": oid, "state": "filled", "filled_quantity": a["quantity"], "average_price": a["limit_price"]}
                res = _txt({"id": oid, "state": "queued"})
            elif name == "get_order":
                res = _txt(_FakeMCP.orders[a["order_id"]])
            else:
                res = {"isError": True, "content": [{"type": "text", "text": "unknown tool"}]}
        else:
            res = {}
        body = json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "result": res}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "s1")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _txt(d):
    return {"content": [{"type": "text", "text": json.dumps(d)}]}


def test_the_direct_mcp_client_speaks_json_rpc_and_maps_tools(tmp_path, monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _FakeMCP)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/mcp"
        store = tmp_path / "oauth.json"
        store.write_text(json.dumps({"access_token": "tok", "expires_at": 9e12, "client_id": "c"}))
        cfg = {"url": url, "tools": {"account": "get_account", "quotes": "get_quotes", "place": "place_equity_order", "order": "get_order"},
               "args": {"place": {"symbol": "{symbol}", "side": "{side}", "quantity": "{quantity}", "type": "limit", "limit_price": "{limit}", "time_in_force": "gfd"}, "order": {"order_id": "{order_id}"}, "quotes": {"symbols": "{symbols}"}},
               "paths": {"account": "account", "account_type": "type", "equity": "equity", "cash": "buying_power", "positions": "positions", "quotes": "results", "q_bid": "bid_price", "q_ask": "ask_price", "q_last": "last_trade_price", "order_id": "id", "order_status": "state"}}
        monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path / "state"))   # the order journal lives under the state root
        b = br.MCPBroker(cfg, oauth=br.OAuth(url, store))
        b.asm = {}
        assert [t["name"] for t in b.list_tools()][:2] == ["get_account", "get_quotes"] and b.session_id == "s1"
        a = b.account()
        assert a == {"account_type": "agentic", "equity": 50000.0, "cash": 50000.0, "positions": [{"symbol": "NVDA", "quantity": 2.0}]}
        q = b.quotes(["NVDA", "MSFT"])
        assert q["NVDA"]["last"] == PX["NVDA"] and q["MSFT"]["bid"] < q["MSFT"]["ask"]
        o = b.place("NVDA", "buy", 3, 199.0, "tkt-x-1")
        assert o["order_id"] == "rh-1" and b.place("NVDA", "buy", 3, 199.0, "tkt-x-1")["order_id"] == "rh-1"      # never twice
        st = b.order("rh-1")
        assert st["status"] == "filled" and st["filled_qty"] == 3 and float(st["avg_price"]) == 199.0
        store.write_text(json.dumps({"access_token": "bad", "expires_at": 9e12, "client_id": "c"}))
        b2 = br.MCPBroker(cfg, oauth=br.OAuth(url, store)); b2.asm = {}
        with pytest.raises(RuntimeError, match="401"):
            b2.list_tools()
    finally:
        srv.shutdown()


def test_fill_templates_keep_types_and_dig_reads_paths():
    assert br._fill({"q": "{quantity}", "n": "id {client_id}", "l": ["{symbol}"]}, {"quantity": 3.0, "client_id": "a", "symbol": "X"}) == {"q": 3.0, "n": "id a", "l": ["X"]}
    assert br._dig({"a": {"b": [{"c": 1}]}}, "a.b.0.c") == 1 and br._dig({"a": 1}, "a.b") is None


def test_the_recommendation_and_the_mcp_tools(state):
    rec = trader.recommendation()
    assert rec["size"] and rec["target_weights"] and rec["mandate"]["mode"] == "manual" and rec["reasons"]
    from buildout import mcp_server as m
    assert {"trading_recommendation", "approve_ticket", "trader_status", "trading_halt", "trading_resume"} <= set(m.TOOLS)
    class C: pass
    r = m.trading_recommendation(C(), {})
    assert "next" in r and r["size"] == pytest.approx(rec["size"], abs=1e-4)
    m.trading_halt(C(), {"reason": "test"})
    assert m.trader_status(C(), {})["halted"]
    m.trading_resume(C(), {})
    assert m.trader_status(C(), {})["halted"] is None and m.trader_status(C(), {})["places_orders"] is False


def test_paper_summary_and_workflow_and_docs():
    daily = (ROOT / ".github" / "workflows" / "daily.yml").read_text()
    assert "python -m buildout trader --once --paper --out site/data" in daily and "git add site/data ledger/calls.jsonl paper" in daily
    assert (ROOT / "paper" / "README.md").exists() and "private/" in (ROOT / ".gitignore").read_text()
    doc = (ROOT / "docs" / "TRADING.md").read_text()
    assert "## The three modes" in doc and "armed = true" in doc and "broker probe" in doc
    assert (ROOT / ".claude" / "commands" / "autotrade.md").exists() and (ROOT / "deploy" / "com.buildout.trader.plist").exists()
    body = (ROOT / "site" / "src" / "body.html").read_text()
    assert 'id="ex-modes"' in body and 'id="ex-mandate"' in body and 'id="ex-pb-tiles"' in body
    assert 'loadJSON("data/paper.json")' in (ROOT / "site" / "src" / "boot.js").read_text()
