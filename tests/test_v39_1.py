"""v0.39.1: the audit's fixes."""
from __future__ import annotations

import json
import urllib.request

import pytest

from buildout import jsonout
from buildout.data import http


def test_published_json_never_carries_an_email(tmp_path):
    p = jsonout.write({"skipped": ["MSFT: Invalid header value b'Jane Doe\\r\\njane.doe@example.com'"], "n": {"x": "ok"}}, tmp_path, "t.json")
    t = p.read_text()
    assert "example.com" not in t and "[email removed]" in t


def test_contact_header_with_a_line_break_is_sent_as_one_line(monkeypatch):
    seen = {}

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    def fake(req, timeout=30):
        seen["ua"] = req.get_header("User-agent")
        return R()

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    http.reset()
    assert http.get("https://data.sec.gov/x", user_agent="Jane Doe\r\njane@example.com") == b"{}"
    assert seen["ua"] == "Jane Doe jane@example.com"


# ---------------------------------------------------------------- the ticket planner (the audit's findings, each pinned)
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from buildout import execution as ex
from buildout import ledger

ROOT = Path(__file__).resolve().parents[1]
CALL = {"asof": "2026-10-23", "size": 0.586, "binding": "drawdown_cap",
        "frontier": [{"gross": 0.586, "short": 0.0, "meets": True}, {"gross": 0.7, "short": 0.2, "meets": True}, {"gross": 0.8, "short": 0.4, "meets": True},
                     {"gross": 1.2, "short": None, "meets": False}]}
W = {"MSFT": 0.14, "AMZN": 0.14, "GOOGL": 0.14, "NVDA": 0.14, "META": 0.12, "TSLA": 0.10, "AVGO": 0.08, "SPCX": 0.08, "ORCL": 0.06}
PX = {"MSFT": 520, "AMZN": 230, "GOOGL": 260, "NVDA": 190, "META": 720, "TSLA": 440, "AVGO": 350, "SPCX": 180, "ORCL": 280, "PSQ": 30, "VIXY": 32}
Q = {s: {"bid": p * 0.9995, "ask": p * 1.0005, "last": p} for s, p in PX.items()}
NOW = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)


@pytest.fixture()
def priv(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "PRIVATE", tmp_path / "private")
    monkeypatch.delenv("BUILDOUT_TRADING_HALT", raising=False)
    return tmp_path / "private"


def acct(cash=100_000.0, positions=()):
    return {"equity": cash + sum(q * PX[s] for s, q in positions), "cash": cash, "account_type": "Agentic",
            "positions": [{"symbol": s, "quantity": q} for s, q in positions]}


def plan(a=None, P=None, quotes=None, lc=None, **kw):
    return ex.plan(a or acct(), quotes or Q, kw.pop("call", CALL), P or ex.TradingParams(), W, today=kw.pop("today", "2026-10-26"),
                   ledger_check=lc or {"ok": True, "logged": True, "effective_from": "2026-10-26"}, now=kw.pop("now", NOW))


def bad(t):
    return [c["check"] for c in t["checks"] if not c["pass"]]


def test_paper_fill_runs_once(priv):
    t = plan()
    ex.paper_fill(t["id"])
    with pytest.raises(ValueError, match="already been filled"):
        ex.paper_fill(t["id"])


def test_fills_add_up_and_repeats_are_caught(priv):
    t = plan(P=ex.TradingParams(mode="live"))
    o = t["orders"][0]
    half = o["quantity"] // 2 + 1
    r1 = ex.record_fills(t["id"], [{"symbol": o["symbol"], "side": "buy", "quantity": half, "price": o["limit_price"], "order_id": "a1"}])
    r2 = ex.record_fills(t["id"], [{"symbol": o["symbol"], "side": "buy", "quantity": half, "price": o["limit_price"], "order_id": "a2"}])
    assert r1["status"] == "partially_filled" and any("in all against" in i for i in r2["issues"])
    r3 = ex.record_fills(t["id"], [{"symbol": o["symbol"], "side": "buy", "quantity": 1, "price": o["limit_price"], "order_id": "a1"}])
    assert any("already recorded" in i for i in r3["issues"])
    t2 = plan(P=ex.TradingParams(mode="live"), today="2026-10-27", now=NOW + timedelta(days=1), lc={"ok": True, "logged": True, "effective_from": "2026-10-27"})
    r = ex.record_fills(t2["id"], [{"symbol": x["symbol"], "side": x["side"], "quantity": 1, "price": x["limit_price"]} for x in t2["orders"]])
    assert r["status"] == "partially_filled"                     # one share of every order is not a fill


def test_a_call_is_traded_only_once_in_force(priv):
    t = plan(lc={"ok": True, "logged": True, "effective_from": "2026-10-27"})
    assert "the call is in force today (on or after its effective date)" in bad(t)


def test_every_field_that_gates_execution_is_hashed(priv):
    t = plan(quotes={k: v for k, v in Q.items() if k != "NVDA"}, P=ex.TradingParams(mode="live"))
    assert not t["execute"]
    p = priv / "tickets" / f"{t['id']}.json"
    d = json.loads(p.read_text())
    d["execute"] = d["all_checks_pass"] = True
    for c in d["checks"]:
        c["pass"] = True
    p.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="altered"):
        ex.load_ticket(t["id"])
    with pytest.raises(KeyError):
        ex.load_ticket("../../etc/passwd")


def test_a_second_live_ticket_the_same_day_is_refused_before_fills(priv):
    P = ex.TradingParams(mode="live")
    assert plan(P=P)["execute"]
    t2 = plan(P=P, now=NOW + timedelta(minutes=5))
    assert "at most 1 executed ticket a day" in bad(t2) and not t2["execute"]


def test_frontier_rows_that_miss_the_limits_are_ignored_and_size_is_clipped():
    T = ex.target(CALL, ex.TradingParams(variant="hedged"), W)
    assert T["book_gross"] + T["short"] + T["vix"] == pytest.approx(0.98)
    big = ex.target({"asof": "x", "size": 1.4, "frontier": [{"gross": 1.4, "short": 0.0, "meets": True}]}, ex.TradingParams(), W)
    assert big["book_gross"] + big["short"] + big["vix"] <= 0.98 + 1e-12


def test_quotes_and_equity_are_sanity_checked(priv):
    assert "every quote is a positive number with bid at most ask" in bad(plan(quotes={**Q, "NVDA": {"bid": -1, "ask": 190, "last": 190}}))
    assert "every quote is a positive number with bid at most ask" in bad(plan(quotes={**Q, "NVDA": {"bid": "nan", "ask": 190, "last": 190}}))
    a = acct(cash=20_000, positions=[("MSFT", 100)])
    a["equity"] = 120_000
    assert "equity matches cash plus positions (within 2%)" in bad(plan(a))


def test_buys_that_need_sale_proceeds_wait_for_the_sells(priv):
    a = acct(cash=1_000, positions=[("NVDA", 300), ("MSFT", 40)])
    t = plan(a, P=ex.TradingParams(max_turnover_pct=1.0))
    assert t["stage"] == "sells first" and {o["side"] for o in t["orders"]} == {"sell"} and "plan again" in t["instructions"]


def test_an_exit_sells_fractional_shares_too(priv):
    a = acct(cash=90_000, positions=[("MSFT", 10)])
    a["positions"].append({"symbol": "PSQ", "quantity": 0.4}); a["equity"] += 0.4 * 30
    t = plan(a, P=ex.TradingParams(vix_share=0.0))
    psq = [o for o in t["orders"] if o["symbol"] == "PSQ"]
    assert psq and psq[0]["quantity"] == pytest.approx(0.4)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_execution_desk_targets_match_the_planner():
    src = (ROOT / "site" / "src" / "execdesk.js").read_text()
    js = src[src.index("const EX_DEFAULT"):src.index("  function renderExecution")] + \
        "\nconst c=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(c.map(([call,v])=>exTarget(call,v))));"
    cases = [[CALL, "unhedged"], [CALL, "hedged"], [{"asof": "x", "size": 0.96, "frontier": [{"gross": 0.96, "short": 0.0, "meets": True}]}, "unhedged"],
             [{"asof": "x", "size": 1.4, "frontier": [{"gross": 1.4, "short": 0.0, "meets": True}]}, "unhedged"]]
    out = json.loads(subprocess.run(["node", "-e", js], input=json.dumps(cases), capture_output=True, text=True, check=True).stdout)
    for (call, v), g in zip(cases, out):
        T = ex.target(call, ex.TradingParams(variant=v), W)
        assert g["gross"] == pytest.approx(T["book_gross"]) and g["short"] == pytest.approx(T["short"]) and g["vix"] == pytest.approx(T["vix"])


# ---------------------------------------------------------------- the record
def test_two_calls_effective_the_same_day_do_not_break_the_live_record():
    from buildout import track
    s = pd.Series([0.58, 0.60], index=[pd.Timestamp("2026-11-09")] * 2).groupby(level=0).last()
    assert s.iloc[0] == 0.60
    src = (ROOT / "buildout" / "track.py").read_text()
    assert "groupby(level=0).last().reindex(x.index" in src


def test_a_torn_ledger_line_is_reported_not_raised(tmp_path):
    p = tmp_path / "calls.jsonl"
    p.write_text('{"seq": 1}\n{"seq": 2, "trunc')
    v = ledger.verify(p)
    assert v["ok"] is False and "not valid JSON" in v["problems"][0]


def test_vol_managed_rule_is_lagged_once():
    from buildout import track
    idx = pd.bdate_range("2019-01-01", "2019-12-31")
    vm = pd.Series(np.where(idx.month >= 7, 0.28, 1.4), index=idx)       # exposure for July is set at June's close
    assert track._next_vm(vm, idx[idx.month == 6][-1]) == pytest.approx(0.28)


def test_one_stale_name_stops_the_book(tmp_path):
    from buildout import book as bk
    files = sorted({bk.FILE.get(k, k.lower()) for k in bk.BOOK} | set(bk.FACTOR_ETF.values()))
    d = pd.bdate_range("2026-01-02", periods=60)
    good = pd.DataFrame({"date": d.strftime("%Y-%m-%d"), "open": 10.0, "high": 10.5, "low": 9.5, "close": np.linspace(10, 12, 60), "volume": 1e6})
    for f in files:
        good.to_csv(tmp_path / f"{f}.csv", index=False)
    good.iloc[:-6].to_csv(tmp_path / f"{files[0]}.csv", index=False)     # six sessions behind the rest
    with pytest.raises(ValueError, match="stale"):
        bk.download(tmp_path)


def test_drawdown_paths_are_reused_and_answers_unchanged():
    from buildout.analytics import sizing
    a = sizing.drawdown_quantile(0.1, 0.3, 1.2)
    sizing._PATHS.clear()
    assert sizing.drawdown_quantile(0.1, 0.3, 1.2) == a
    lv = sizing.max_leverage(0.12, 0.32, 0.25, cash_rate=0.04, hi=3.0)
    assert sizing.drawdown_quantile(0.12, 0.32, lv, cash_rate=0.04) <= 0.25 < sizing.drawdown_quantile(0.12, 0.32, lv + 2e-4, cash_rate=0.04)


def test_stated_counts_match_the_repo():
    import re as _re
    from buildout import mcp_server
    land = (ROOT / "site" / "src" / "landing.js").read_text()
    body = (ROOT / "site" / "src" / "body.html").read_text()
    ref = (ROOT / "site" / "src" / "reference.js").read_text()
    files = len(list((ROOT / "tests").glob("test_*.py")))
    n = len(mcp_server.TOOLS)
    assert f"const TEST_FILES = {files};" in land and f"const MCP_TOOLS = {n};" in land
    assert f"every one of its {n} tools" in body and f"and {files} test files" in body
    assert f"offers {n} " in ref
    assert not _re.search(r"\b(42|33) tools\b", body + ref[:ref.index("const CHANGELOG")])     # the changelog keeps its history
