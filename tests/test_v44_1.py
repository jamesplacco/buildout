"""v0.44.1: the bug-hunt fixes. The trader's halts read yesterday (not the point it just wrote), the account is marked
at the pass's own quotes, the mandate's max_gross is enforced, `trade halt` stops every state root, the assistant
route never hands the same orders over twice, the Yahoo stand-ins work and drop a session still trading, and a
malformed MCP request is an error reply, not a dead server."""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from buildout import broker as br
from buildout import execution as ex
from buildout import mandate as md
from buildout import trader

ROOT = Path(__file__).resolve().parents[1]
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


# ---------------------------------------------------------------- the review's additions
def test_a_handed_off_ticket_still_takes_its_fills(state, monkeypatch):
    """The hand-off marks the ticket so it is not handed over twice; the mark must not stop the fills coming back."""
    monkeypatch.setattr(trader, "evidence", lambda *a, **k: {"open": True, "missing": []})
    M = md.Mandate(mode="autonomous", armed=True, broker="assistant", signed_by="J", signed_on="2026-11-08", notes="rehearsal", max_order_usd=50_000)

    def ab():
        return br.AssistantBroker({"equity": 50_000.0, "cash": 50_000.0, "account_type": "Agentic", "positions": []}, _qf(list(PX)))
    r1 = trader.run_once(ab(), M, _params(), now=NOW, call=_call())
    t = ex.load_ticket(r1["ticket"])
    assert t["status"] == "handed_off"
    fills = [{"symbol": o["symbol"], "side": o["side"], "quantity": o["quantity"], "price": o["limit_price"], "order_id": f"rh-{o['seq']}", "status": "filled"} for o in t["orders"]]
    rec = ex.record_fills(r1["ticket"], fills, NOW + timedelta(minutes=10))
    assert rec["status"] == "filled" and rec["chain_ok"] and ex.load_ticket(r1["ticket"])["status"] == "filled"
    r3 = trader.run_once(ab(), M, _params(), now=NOW + timedelta(minutes=20), call=_call())
    assert r3["outcome"] == "already traded today"


def test_fills_the_account_holds_and_the_log_does_not_are_recorded_by_the_next_pass(state):
    """settle() saves the account before the fills reach the log. A pass that dies between the two is repaired by the
    next one, once."""
    pb = br.PaperBroker(state / "paper_account.json", quote_fn=_qf)
    M = md.Mandate(mode="autonomous", broker="paper", max_order_usd=50_000)
    r1 = trader.run_once(pb, M, _params(), now=NOW, call=_call(), poll_seconds=0.01)
    assert r1["outcome"] == "orders resting until the close"
    later = NOW + timedelta(days=1)
    pb.clock = lambda: later
    pb.quotes(sorted({o["symbol"] for o in pb.open_orders()}))
    changed = pb.settle(later)                                      # the account trades; the pass "dies" before the log
    filled = [o for o in changed if o["status"] == "filled"]
    assert filled and not ex._fills() and not pb.open_orders()
    r2 = trader.run_once(pb, M, _params(), now=later, call=_call())
    assert r2["reconciled"]["recorded"] == len(filled)
    log = ex._fills()
    assert len(log) == 1 and {f["order_id"] for f in log[0]["fills"]} == {o["order_id"] for o in filled} and ex.verify_fills()["ok"]
    j = [e for e in trader.journal(50) if e.get("event") == "executed"]
    assert len(j) == 1 and j[0]["reconciled"] is True and j[0]["fill_session"] == "2026-11-09"
    r3 = trader.run_once(pb, M, _params(), now=later + timedelta(hours=1), call=_call())
    assert "reconciled" not in r3 and len(ex._fills()) == 1, "once"


def test_the_inflation_reading_is_the_one_published_by_the_decision():
    """A month's CPI comes out in the middle of the next month. The regime a month-end decision reads is the one the
    last published CPI gives: inflation that turns up in June's index changes the August book, not July's."""
    import numpy as np
    from buildout import track
    assert track.CPI_LAG_MONTHS == 1
    months = pd.date_range("2010-01-01", "2020-12-01", freq="MS")
    rng = np.random.default_rng(0)
    H = pd.DataFrame({"stock": rng.normal(0.007, 0.04, len(months)), "bond": rng.normal(0.003, 0.02, len(months)),
                      "infl": np.where(months >= "2019-06-01", 0.03, 0.02), "y10": 0.03}, index=months)
    days = pd.bdate_range("2018-01-02", "2020-06-30")
    r = pd.Series(rng.normal(0.0005, 0.01, len(days)), index=days)
    flat = pd.Series(0.0, index=days)
    pol = pd.Series("on hold", index=pd.date_range("2009-12-31", "2020-12-31", freq="ME"))
    rows = {x["month"]: x["regime"] for x in track.regime_hedge_walk(r, flat, H, pol, flat)["rows"]}
    assert rows["2019-06"].startswith("inflation falling")
    assert rows["2019-07"].startswith("inflation falling"), "June's CPI is not out at the end of June"
    assert rows["2019-08"].startswith("inflation rising")


def test_the_forecast_made_at_a_close_sees_the_close():
    import math
    import numpy as np
    from buildout import book as bk, track
    r = pd.Series(np.random.default_rng(0).normal(0, 0.01, 400), index=pd.bdate_range("2024-01-02", periods=400))
    calm = bk.ewma_next(r)
    r.iloc[-1] = -0.12
    s = bk.ewma_vol(r)
    assert float(s.iloc[-1]) == pytest.approx(float(bk.ewma_vol(r.iloc[:-1].reindex(r.index).fillna(0.0)).iloc[-1])), "the last value of the series does not see the last day"
    assert bk.ewma_next(r) == pytest.approx(math.sqrt(bk.EWMA_LAMBDA * float(s.iloc[-1]) ** 2 + (1 - bk.EWMA_LAMBDA) * 0.12 ** 2)) and bk.ewma_next(r) > 2.5 * calm
    q = pd.Series(0.0, index=r.index)
    crash, quiet = track.limits_at(r, q, r.index[-1], 0.04), track.limits_at(r.iloc[:-1], q, r.index[-2], 0.04)
    assert crash["sigma"] > 1.5 * quiet["sigma"] and crash["size"] < quiet["size"], "a crash on the decision day shrinks that evening's size"
    assert "bk.ewma_next(x)" in (ROOT / "buildout" / "track.py").read_text() and "s_next = ewma_next(r)" in (ROOT / "buildout" / "book.py").read_text()


def test_decembers_decision_is_sized_on_the_names_it_will_hold(monkeypatch):
    from buildout import track
    seen = []
    monkeypatch.setattr(track, "_lr_one", lambda job: seen.append(job) or {"date": job[0], "ok": False})
    mes = [pd.Timestamp(d) for d in ("2019-11-29", "2019-12-31", "2020-01-31", "2020-12-31")]
    track.live_rule_path({}, pd.DataFrame(), {2019: ["a"], 2020: ["b"]}, mes, workers=1)
    assert seen == [("2019-11-29", ["a"]), ("2019-12-31", ["b"]), ("2020-01-31", ["b"]), ("2020-12-31", ["b"])], "the last list stands when the next is not known"


def test_the_backtest_arithmetic():
    import numpy as np
    from buildout import track
    src = (ROOT / "buildout" / "track.py").read_text()
    # modified duration of a 10-year par bond with semiannual coupons, against repricing the bond
    y = 0.05
    price = lambda yy: sum((y / 2) / (1 + yy / 2) ** k for k in range(1, 21)) + 1 / (1 + yy / 2) ** 20
    numeric = -(price(y + 1e-6) - price(y - 1e-6)) / 2e-6
    assert (1 - (1 + y / 2) ** -20) / y == pytest.approx(numeric, rel=1e-6) and "dur = (1 - (1 + y / 2) ** -20) / y " in src
    assert (1 - (1 + y / 2) ** -20) / (y / 2) / 2 / (1 + y / 2) < 0.98 * numeric, "the old line was short by 1 + y/2"
    # a hedge ratio is a regression slope: covariance and variance on the same divisor
    assert all("ddof=1" in line for line in src.splitlines() if "np.var(" in line), "every np.var beside an np.cov carries ddof=1"
    rng = np.random.default_rng(2)
    b = rng.normal(0, 1, 30); a = 0.7 * b + rng.normal(0, 0.3, 30)
    assert np.cov(a, b)[0, 1] / np.var(b, ddof=1) == pytest.approx(np.polyfit(b, a, 1)[0])
    # the weak-name short pays to trade
    idx = pd.bdate_range("2017-01-02", "2019-06-28")
    prices = {t: pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), "close": 100 * np.cumprod(1 + rng.normal(0.0003 * (i + 1), 0.015, len(idx)))}) for i, t in enumerate(track.CANDIDATES[:6])}
    monkey = dict(track.COST)
    try:
        track.COST["short_trade_bp"] = 0.0
        free = track.weak_basket(prices, idx)
    finally:
        track.COST.update(monkey)
    paid = track.weak_basket(prices, idx)
    drag = float((free - paid).sum())
    assert (free - paid).min() >= -1e-15 and 0.0005 < drag < 0.05, drag


def test_a_library_link_on_the_core_page_goes_to_the_library():
    """v0.43 shipped a core page that stayed blank on a link to a legend: the filter the link resets was a constant
    stand-in, and assigning to it threw. The stand-ins are variables now, and the link opens the library."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import assemble_page as A
    assert "let X = __stub;" in A.stand_in("x.js", {"consts": ["X"]}) and "const X" not in A.stand_in("x.js", {"consts": ["X"]})
    boot = (ROOT / "site" / "src" / "boot.js").read_text()
    assert "if (!el && CORE && /^(sec|ep|lg)-/.test(token)) { toLibrary(token);" in boot
    assert boot.index("lazyFlushAll(); el = document.getElementById(token);") < boot.index("/^(sec|ep|lg)-/.test(token)) { toLibrary")
    # Back from the library returns to where the reader was: the hand-off replaces the #<desk> entry, it does not add to it
    assert 'location.replace(LIBRARY_HREF + "#" + v)' in boot and "location.href = LIBRARY_HREF" not in boot
    stress = (ROOT / "site" / "tests" / "stress.py").read_text()
    assert "going back from the library did not return to the core page" in stress and "lg-buffett" in stress


def test_version_and_notes():
    import buildout
    assert buildout.__version__ >= "0.44.1"
    src = ROOT / "site" / "src"
    assert '["v0.44.1", "Nov 13, 2026"' in (src / "reference.js").read_text() and "Version 0.44.1" in (ROOT / "CHANGELOG.md").read_text()
    log = [line for line in (src / "memos.js").read_text().splitlines() if '"v0.44.1"' in line]
    assert len(log) >= 3 and any("max_gross" in x for x in log) and any("blank" in x for x in log) and any("consumer price" in x.lower() or "CPI" in x for x in log)
    for p in ("tests/test_v44_1.py", "buildout/trader.py", "buildout/track.py", "buildout/execution.py", "buildout/datahub.py"):
        low = (ROOT / p).read_text().lower()
        for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
            assert b not in low, (p, b)
