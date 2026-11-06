"""v0.39: VIX as a hedge, and the call turned into a risk-checked order ticket for a Robinhood Agentic account
(placed by Robinhood's own MCP after approval; never by Buildout)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import execution as ex
from buildout import mcp_server, vixhedge

ROOT = Path(__file__).resolve().parents[1]
CALL = {"asof": "2026-10-23", "size": 0.586, "binding": "drawdown_cap",
        "frontier": [{"gross": 0.586, "short": 0.0}, {"gross": 0.7, "short": 0.2}, {"gross": 0.8, "short": 0.4}, {"gross": 1.0, "short": 0.85}]}
W = {"MSFT": 0.14, "AMZN": 0.14, "GOOGL": 0.14, "NVDA": 0.14, "META": 0.12, "TSLA": 0.10, "AVGO": 0.08, "SPCX": 0.08, "ORCL": 0.06}
PX = {"MSFT": 520, "AMZN": 230, "GOOGL": 260, "NVDA": 190, "META": 720, "TSLA": 440, "AVGO": 350, "SPCX": 180, "ORCL": 280, "PSQ": 30, "VIXY": 32}
Q = {s: {"bid": p * 0.9995, "ask": p * 1.0005, "last": p} for s, p in PX.items()}
OK = {"ok": True, "logged": True}
NOW = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def private(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "PRIVATE", tmp_path / "private")
    monkeypatch.delenv("BUILDOUT_TRADING_HALT", raising=False)
    return tmp_path / "private"


def acct(cash=100_000.0, positions=(), kind="Agentic"):
    eq = cash + sum(q * PX[s] for s, q in positions)
    return {"equity": eq, "cash": cash, "account_type": kind, "positions": [{"symbol": s, "quantity": q} for s, q in positions]}


def plan(a=None, P=None, **kw):
    return ex.plan(a or acct(), kw.pop("quotes", Q), CALL, P or ex.TradingParams(), W, today=kw.pop("today", "2026-10-26"), ledger_check=kw.pop("lc", OK), now=kw.pop("now", NOW))


def failed(t):
    return [c["check"] for c in t["checks"] if not c["pass"]]


# ---------------------------------------------------------------- targets
def test_targets_fit_a_cash_account():
    T = ex.target(CALL, ex.TradingParams(), W)
    assert T["book_gross"] == pytest.approx(0.586) and T["short"] == 0 and T["vix"] == pytest.approx(0.05)
    H = ex.target(CALL, ex.TradingParams(variant="hedged"), W)
    assert H["book_gross"] + H["short"] + H["vix"] == pytest.approx(0.98)       # the largest the account allows
    assert 0.7 <= H["book_gross"] <= 0.8 and H["short"] == pytest.approx(0.2 + 2 * (H["book_gross"] - 0.7))
    assert ex.target(CALL, ex.TradingParams(vix_share=0.0), W)["vix"] == 0
    big = {**CALL, "frontier": [{"gross": 0.96, "short": 0.0}]}
    assert ex.target(big, ex.TradingParams(), W)["vix"] == pytest.approx(0.02)   # the sleeve gives way to the call


def test_first_build_passes_every_check_and_orders_sells_first():
    t = plan()
    assert t["all_checks_pass"], failed(t)
    assert t["execute"] is False and t["mode"] == "paper" and t["placed_by_buildout"] is False   # paper: never executable
    assert {o["symbol"] for o in t["orders"]} == set(W) | {"VIXY"}
    assert t["summary"]["gross_after"] <= 0.98 and t["summary"]["cash_after"] >= 0.02 * 100_000
    assert all(o["type"] == "limit" and o["quantity"] == int(o["quantity"]) for o in t["orders"])
    a = acct(cash=20_000, positions=[("MSFT", 100)])
    t2 = plan(a)
    sides = [o["side"] for o in t2["orders"]]
    assert sides == sorted(sides, key=lambda x: x != "sell")


def test_live_mode_marks_a_clean_ticket_executable_only():
    assert plan(P=ex.TradingParams(mode="live"))["execute"] is True
    assert plan(acct(kind="Individual"), P=ex.TradingParams(mode="live"))["execute"] is False


@pytest.mark.parametrize("case,expect", [
    ("halt", "not halted"), ("account", "Agentic account"), ("stale", "call's data at most 3 business days old"),
    ("ledger", "call logged in the verified ledger before trading"), ("quote", "every symbol has a quote"),
    ("stranger", "every symbol on the allowlist"), ("turnover", "turnover at most 60% of equity"), ("order", "each order at most 25% of equity and $25,000")])
def test_each_check_blocks(case, expect, private, monkeypatch):
    kw, a, P = {}, acct(), ex.TradingParams(mode="live")
    if case == "halt":
        private.mkdir(parents=True); (private / "HALT").write_text("x")
    if case == "account":
        a = acct(kind="Individual investing")
    if case == "stale":
        kw["today"] = "2026-11-05"
    if case == "ledger":
        kw["lc"] = {"ok": True, "logged": False}
    if case == "quote":
        kw["quotes"] = {k: v for k, v in Q.items() if k != "NVDA"}
    if case == "stranger":
        a = acct(cash=50_000, positions=[("MSFT", 10)]); a["positions"].append({"symbol": "GME", "quantity": 5}); kw["quotes"] = {**Q, "GME": {"bid": 20, "ask": 20.01, "last": 20}}
    if case == "turnover":
        a = acct(cash=0, positions=[("TSLA", 220)])              # all in one name: rebalancing it is most of the account
    if case == "order":
        a = acct(cash=1_000_000)
    t = plan(a, P, **kw)
    assert expect in failed(t) and t["execute"] is False


def test_env_halt_and_one_ticket_a_day(monkeypatch):
    t = plan()
    ex.paper_fill(t["id"])
    t2 = plan(acct(cash=50_000, positions=[("MSFT", 100)]))
    assert "at most 1 executed ticket a day" in failed(t2)
    monkeypatch.setenv("BUILDOUT_TRADING_HALT", "1")
    assert "not halted" in failed(plan(today="2026-10-27", now=NOW + timedelta(days=1)))


def test_no_short_sale_even_when_the_target_is_below_the_holding():
    a = acct(cash=0, positions=[("NVDA", 600)])
    t = plan(a, P=ex.TradingParams(max_turnover_pct=1.0))
    s = [o for o in t["orders"] if o["symbol"] == "NVDA"][0]
    assert s["side"] == "sell" and s["quantity"] <= 600 and "no short sale (a sale at most what is held)" not in failed(t)


# ---------------------------------------------------------------- tickets and fills
def test_ticket_is_tamper_evident(private):
    t = plan()
    p = private / "tickets" / f"{t['id']}.json"
    d = json.loads(p.read_text()); d["orders"][0]["quantity"] = 9999; p.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="altered"):
        ex.load_ticket(t["id"])


def test_fills_are_checked_and_chained(private):
    t = plan()
    o = t["orders"][0]
    r = ex.record_fills(t["id"], [{"symbol": o["symbol"], "side": "buy", "quantity": o["quantity"] + 5, "price": o["limit_price"] + 1, "order_id": "x"},
                                  {"symbol": "GME", "side": "buy", "quantity": 1, "price": 10}])
    assert r["status"] == "partially_filled" and len(r["issues"]) == 3 and r["chain_ok"]
    lines = (private / "fills.jsonl").read_text().splitlines()
    e = json.loads(lines[0]); e["fills"][0]["quantity"] = 1; (private / "fills.jsonl").write_text(json.dumps(e) + "\n")
    assert not ex.verify_fills()["ok"]
    with pytest.raises(RuntimeError):
        ex.record_fills(t["id"], [])


def test_paper_round_trip(private):
    t = plan()
    r = ex.paper_fill(t["id"])
    assert r["status"] == "filled" and not r["issues"]
    A = ex.paper_account()
    assert A["cash"] == pytest.approx(100_000 - t["summary"]["buys_usd"], abs=0.01)
    t2 = plan({**A, "account_type": "agentic (paper)"}, today="2026-10-27", now=NOW + timedelta(days=1))
    assert t2["orders"] == [] and t2["all_checks_pass"]                      # within the drift band: nothing to do
    with pytest.raises(ValueError):
        ex.paper_fill(plan(P=ex.TradingParams(mode="live"), today="2026-10-28", now=NOW + timedelta(days=2))["id"])


def test_buildout_still_places_no_orders():
    src = (ROOT / "buildout" / "execution.py").read_text()
    assert not re.search(r"^\s*(import|from)\s+.*(urllib|requests|http|socket)", src, re.M)      # no network at all
    assert {"trade_plan", "record_fills", "trading_status", "paper_fill"} <= set(mcp_server.TOOLS)
    assert not any(re.search(r"place|execute|submit|send_order", k) for k in mcp_server.TOOLS)
    assert "approves" in mcp_server.TOOLS["trade_plan"][1]
    cfg = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]
    assert cfg["robinhood-trading"]["url"] == "https://agent.robinhood.com/mcp/trading" and cfg["buildout"]["type"] == "stdio"
    cmd = (ROOT / ".claude" / "commands" / "rebalance.md").read_text()
    assert "approving this exact ticket id" in cmd and "Place nothing unless" in cmd
    assert "private/" in (ROOT / ".gitignore").read_text()


def test_mcp_trade_plan_validates_input():
    ctx = mcp_server.Context()
    with pytest.raises(mcp_server.ToolError):
        mcp_server.TOOLS["trade_plan"][0](ctx, {"account": "x"})
    with pytest.raises(mcp_server.ToolError):
        mcp_server.TOOLS["trade_plan"][0](ctx, {"account": acct(), "quotes": Q, "vix_share": 0.5})


# ---------------------------------------------------------------- the VIX study
def test_option_marked_daily_sums_to_payoff_less_premium():
    idx = pd.bdate_range("2024-01-01", "2024-03-29")
    r = pd.Series(np.random.default_rng(1).normal(0, 0.03, len(idx)), index=idx)
    pnl = vixhedge.option_daily(r, 0.0001, "call", 1.0, spread=0.0)          # tiny vol: the option is worth its intrinsic value
    for m, g in r.groupby(idx.to_period("M")):
        S = (1 + g).cumprod() / (1 + g.iloc[0])
        assert pnl[g.index].sum() == pytest.approx(max(S.iloc[-1] - 1, 0) - max(S.iloc[0] - 1, 0), abs=1e-4)
    p = vixhedge.option_daily(r, 0.8, "put", 0.9)
    assert p.notna().all() and np.isfinite(p).all()


def test_vix_study_on_synthetic_futures():
    idx = pd.bdate_range("2006-01-02", "2012-12-31")
    rng = np.random.default_rng(3)
    nq = rng.normal(0.0004, 0.015, len(idx))
    vx = -2.5 * nq + rng.normal(-0.002, 0.03, len(idx))                    # VIX futures rise when the index falls, and bleed
    def frame(r, p0):
        p = p0 * np.cumprod(1 + r)
        m = (idx.year * 100 + idx.month).astype(float)
        return pd.DataFrame({"price": p, "m_price": m, "carry": p, "m_carry": m, "forward": p, "m_forward": m}, index=idx)
    frames = {"NQ": frame(nq, 2000.0)}
    vxf = frame(vx, 20.0)
    vix = pd.Series(20 * np.cumprod(1 + vx), index=idx)
    book = pd.Series(1.2 * nq, index=idx)
    V = vixhedge.build(frames, book, pd.Series(0.0, index=idx), vxf=vxf, vix=vix)
    allm = V["regimes"][0]
    assert allm["h"]["vix_fut"]["corr"] < -0.5 and allm["h"]["vix_fut"]["var_cut"] > 0.2
    rows = {(r["hedge"], r["share"]): r for r in V["book"]["rows"]}
    assert rows[("vix_fut", 0.2)]["es21"] < rows[("none", 0.0)]["es21"]
    assert set(V["call_vov"]) == {"0.8", "1.0", "1.2"} and V["robinhood"]["vix_futures"] is False


def test_plan_uses_the_daily_runs_newer_call(tmp_path, monkeypatch):
    d = tmp_path / "site" / "data"
    d.mkdir(parents=True)
    (d / "book.json").write_text(json.dumps({**CALL, "asof": "2099-01-02"}))
    monkeypatch.setattr(ex, "ROOT", tmp_path)
    assert ex.latest_call()["asof"] == "2099-01-02"
    (d / "book.json").write_text(json.dumps({**CALL, "asof": "2000-01-03"}))
    assert ex.latest_call()["asof"] != "2000-01-03"                 # an older file never replaces the snapshot
