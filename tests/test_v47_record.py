"""v0.47: the record. A call governs only a return that began after it was written; the ledger's verify reports more
and says what it cannot prove; the live record refuses a ledger whose published head has gone; the hedged variant
holds the gross its menu row says, borrowing costs, and a drawdown counts the fall from the start; the paper
account's first, stale-priced fill is corrected once in the chained log; the paper bot follows the call's size,
trades the call the live record marks, and its evidence is counted in exchange sessions; a staged ticket is chosen
by time and never reused on another call. Every trader test runs on a temporary state folder."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import book as bk
from buildout import broker as br
from buildout import execution as ex
from buildout import ledger
from buildout import mandate as md
from buildout import sessions
from buildout import track
from buildout import trader

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _book(asof: str, size: float = 0.53, **more) -> dict:
    return {"asof": asof, "size": size, "binding": "drawdown_cap",
            "frontier": [{"gross": size, "short": 0.0, "meets": True}, {"gross": 1.0, "short": 0.85, "meets": True}], **more}


def _rehash(rows: list[dict]) -> str:
    """A chain rewritten the way its owner could: every hash after an edit recomputed."""
    prev, out = ledger.GENESIS, []
    for e in rows:
        e = {**e, "prev": prev}
        e["hash"] = ledger.entry_hash(e)
        prev = e["hash"]
        out.append(ledger._canon(e))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- A. when a call governs
@pytest.mark.parametrize("ts, asof, want, why", [
    ("2026-11-17T19:34:25Z", "2026-11-16", "2026-11-18", "mid-session Tuesday: Tuesday's close is still to come"),
    ("2026-11-17T11:17:00Z", "2026-11-16", "2026-11-18", "before Tuesday's open: the same"),
    ("2026-11-14T17:22:36Z", "2026-11-13", "2026-11-17", "Saturday: the first close after it is Monday's, so Tuesday"),
    ("2026-11-13T21:30:00Z", "2026-11-12", "2026-11-17", "Friday after the close: the same as Saturday"),
    ("2026-11-26T19:30:00Z", "2026-11-25", "2026-11-30", "Thanksgiving: the first close after it is Friday's"),
    ("2026-11-27T19:25:00Z", "2026-11-25", "2026-12-01", "after the 1:00 pm close on the half day"),
    ("2026-11-27T17:30:00Z", "2026-11-25", "2026-11-30", "before the 1:00 pm close on the half day"),
    ("2026-07-01T20:30:00Z", "2026-06-30", "2026-07-06", "summer: the close is 20:00 UTC, and July 3 is a holiday"),
    ("2026-11-17T11:17:00Z", "2026-11-18", "2026-11-19", "never earlier than the session after the data"),
])
def test_a_new_call_governs_only_a_return_that_starts_after_it_was_written(ts, asof, want, why):
    e = ledger.make_entry(_book(asof), "0.47.0", None, ts=ts)
    assert e["effective_from"] == want == ledger.causal_effective(ts, asof) == ledger.governs_from(e), why
    start = sessions.close_utc(sessions.prev_session(want))                  # the close that begins the first governed return
    assert ledger._ts(ts) < start and sessions.is_session(want), why
    assert not ledger.restated([e])


def test_the_stored_dates_stand_and_the_saturday_entries_govern_a_session_later():
    rows = ledger.read()[:12]
    assert ledger.verify()["ok"], "the committed entries still verify, unedited"
    g = {e["seq"]: ledger.governs_from(e) for e in rows}
    assert g[5] == "2026-11-10" and rows[4]["effective_from"] == "2026-11-09"      # written Sat Nov 7
    assert g[10] == "2026-11-17" and rows[9]["effective_from"] == "2026-11-16"     # written Sat Nov 14
    assert all(g[e["seq"]] == e["effective_from"] for e in rows if e["seq"] not in (5, 10))
    assert [(r["seq"], r["effective_from"], r["governs_from"]) for r in ledger.restated(rows)] == [(5, "2026-11-09", "2026-11-10"), (10, "2026-11-16", "2026-11-17")]
    for e in rows:                                                                # no entry governs a return that began before it existed
        assert ledger._ts(e["ts_utc"]) < sessions.close_utc(sessions.prev_session(g[e["seq"]])), e["seq"]
    # entries 4 and 9, which under the stored dates never governed a day, now hold the Mondays
    assert ex.call_in_force("2026-11-09")["ledger_seq"] == 4 and ex.call_in_force("2026-11-16")["ledger_seq"] == 9
    assert ex.call_in_force("2026-11-17")["ledger_seq"] == 10 and ex.call_in_force("2026-11-03") is None
    # a pass replayed at an earlier moment sees the ledger as it stood then
    assert ex.call_in_force("2026-11-12", now=datetime(2026, 11, 11, 15, 0, tzinfo=UTC))["ledger_seq"] == 6


# ---------------------------------------------------------------- B. what verify reports, and what only a held head catches
def test_verify_reports_what_it_used_to_pass_or_crash_on(tmp_path):
    P = tmp_path / "calls.jsonl"
    rows = ledger.read()[:4]
    now = datetime(2026, 11, 18, 20, 0, tzinfo=UTC)
    P.write_text(_rehash(rows))
    assert ledger.verify(P, now=now)["ok"]
    back = [dict(r) for r in rows]; back[2]["data_asof"] = "2026-11-03"                                # the same data date twice
    P.write_text(_rehash(back))
    assert any("data date 2026-11-03 is not after" in p for p in ledger.verify(P, now=now)["problems"])
    sat = [dict(r) for r in rows]; sat[1]["effective_from"] = "2026-11-07"
    P.write_text(_rehash(sat))
    assert any("2026-11-07 is not an exchange session" in p for p in ledger.verify(P, now=now)["problems"])
    fut = [dict(r) for r in rows]; fut[3]["ts_utc"], fut[3]["effective_from"] = "2031-01-01T00:00:00Z", "2031-01-02"
    P.write_text(_rehash(fut))
    assert any("written in the future" in p for p in ledger.verify(P, now=now)["problems"])
    P.write_text(_rehash(rows))
    assert ledger.verify(P, now=ledger._ts(rows[-1]["ts_utc"]) - timedelta(minutes=5))["ok"], "a few minutes of clock skew is not a problem"
    assert not ledger.verify(P, now=ledger._ts(rows[-1]["ts_utc"]) - timedelta(hours=1))["ok"]
    gone = [dict(r) for r in rows]; del gone[1]["ts_utc"]; del gone[2]["effective_from"]
    P.write_text(_rehash(gone))
    v = ledger.verify(P, now=now)                                                                     # reported, not a KeyError
    assert not v["ok"] and any("entry 2: missing ts_utc" in p for p in v["problems"]) and any("entry 3: missing effective_from" in p for p in v["problems"])
    P.write_text("[1, 2]\n")                                                                          # a line that is JSON but not an entry
    v = ledger.verify(P, now=now)
    assert not v["ok"] and any("not a JSON object" in p for p in v["problems"])


def test_append_is_safe_on_a_file_without_a_last_newline(tmp_path):
    P = tmp_path / "calls.jsonl"
    ledger.append(_book("2026-10-23"), "0.47.0", P, ts="2026-11-03T15:00:00Z")
    P.write_text(P.read_text().rstrip("\n"))                                    # an editor or a merge dropped it
    assert ledger.verify(P)["ok"]
    r = ledger.append(_book("2026-11-03", 0.6), "0.47.0", P, ts="2026-11-04T15:00:00Z")
    assert r["appended"] and ledger.verify(P)["ok"] and ledger.verify(P)["entries"] == 2, "before, the new entry landed on the old line and broke the file"
    assert ledger.head(P) == r["entry"]["hash"] and ledger.head(tmp_path / "none.jsonl") is None


def test_a_rewritten_or_shortened_chain_passes_verify_and_fails_against_a_held_head(tmp_path):
    rows = ledger.read()[:12]
    published = {"ledger_head": rows[-1]["hash"], "ledger_entries": 12}
    now = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    P = tmp_path / "calls.jsonl"
    P.write_text(_rehash(rows))
    assert ledger.verify(P, now=now)["ok"] and ledger.continuity(published, P) is None
    # 1. an edit that does not rehash: verify alone catches it
    edited = [dict(r) for r in rows]; edited[5] = {**edited[5], "call": {**edited[5]["call"], "size": 0.99}}
    P.write_text("\n".join(ledger._canon(e) for e in edited) + "\n")
    assert not ledger.verify(P, now=now)["ok"]
    # 2. the same edit with every later hash recomputed: verify passes; the head published yesterday is gone
    P.write_text(_rehash(edited))
    assert ledger.verify(P, now=now)["ok"], "the chain is not keyed: its owner can rehash it"
    assert "rewritten or removed" in ledger.continuity(published, P)
    # 3. entries cut off the end: verify passes; the published head is gone
    P.write_text(_rehash(rows[:9]))
    assert ledger.verify(P, now=now)["ok"] and ledger.verify(P, now=now)["entries"] == 9
    assert ledger.continuity(published, P) is not None
    # 4. the last entry swapped for another: the same
    swapped = [dict(r) for r in rows]; swapped[-1] = {**swapped[-1], "call": {**swapped[-1]["call"], "size": 0.25}}
    P.write_text(_rehash(swapped))
    assert ledger.verify(P, now=now)["ok"] and ledger.continuity(published, P) is not None
    # 5. an honest day: one more entry on the same chain keeps the published head inside it
    P.write_text(_rehash(rows))
    r = ledger.append(_book("2026-11-18"), "0.47.0", P, ts="2026-11-19T11:17:00Z")
    assert r["appended"] and ledger.continuity(published, P) is None
    # the file written before v0.47 kept the head under ledger.head; a first run and an unreadable file hold nothing
    old = tmp_path / "live.json"; old.write_text(json.dumps({"ledger": {"ok": True, "entries": 12, "head": rows[-1]["hash"]}}))
    assert ledger.continuity(old, P) is None
    P.write_text(_rehash(rows[:9]))
    assert ledger.continuity(old, P) is not None
    assert ledger.continuity(tmp_path / "missing.json", P) is None and ledger.continuity({"calls": 0}, P) is None


def _prices(idx, seed=7):
    rng = np.random.default_rng(seed)
    out = {}
    for f in sorted({bk.FILE.get(k, k.lower()) for k in bk.BOOK} | set(bk.FACTOR_ETF.values())):
        c = 100 * np.cumprod(1 + rng.normal(0.0004, 0.015, len(idx)))
        out[f] = pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), "open": c, "high": c, "low": c, "close": c, "volume": 1e6})
    return out


def _ust(end="2026-11-20"):
    return pd.DataFrame({"DGS2": 4.0, "DGS10": 4.5, "DGS20": 4.8}, index=pd.bdate_range("2017-01-03", end))


def test_the_live_command_publishes_the_head_and_refuses_a_ledger_that_lost_it(tmp_path, monkeypatch, capsys):
    from buildout import cli
    rows = ledger.read()[:12]
    P = tmp_path / "calls.jsonl"
    P.write_text(_rehash(rows))
    out = tmp_path / "data"
    monkeypatch.setattr(ledger, "PATH", P)
    monkeypatch.setattr(bk, "download", lambda *a, **k: _prices(pd.bdate_range("2026-09-01", "2026-11-17")))
    monkeypatch.setattr(bk, "treasury", lambda *a, **k: _ust())
    cli.main(["live", "--out", str(out)])
    L = json.loads((out / "live.json").read_text())
    assert L["ledger_head"] == rows[-1]["hash"] == ledger.head(P) and L["ledger_entries"] == 12 and L["ledger"]["head"] == L["ledger_head"]
    assert [r["seq"] for r in L["restated"]] == [5, 10] and L["marked_days"] == 10 and L["first_effective"] == "2026-11-04"
    cli.main(["live", "--out", str(out)])                                       # the same chain again: nothing to refuse
    was = (out / "live.json").read_text()
    monkeypatch.setattr(bk, "download", lambda *a, **k: pytest.fail("the run must stop before it fetches a price"))
    for bad in (rows[:9], [dict(r) if r["seq"] != 5 else {**r, "call": {**r["call"], "size": 0.10}} for r in rows]):
        P.write_text(_rehash(bad))
        assert ledger.verify(P)["ok"], "verify alone does not see it"
        with pytest.raises(SystemExit) as stop:
            cli.main(["live", "--out", str(out)])
        assert stop.value.code not in (0, None) and "refusing to write live.json" in str(stop.value.code) and "rewritten or removed" in str(stop.value.code)
        assert (out / "live.json").read_text() == was, "the file that holds the evidence is left as it was"


# ---------------------------------------------------------------- the bond hedge flag reads today's regime
def test_the_bond_hedge_flag_follows_todays_regime_and_logs_what_it_read():
    hist = {"policies": {"bond_when_it_hedges": {"variance_cut": 0.02}}}          # the whole history says the hedge barely helps
    on = ledger.make_entry(_book("2026-11-17", correlation={"state": "hedging", "book_63d": -0.16}, hedges={**hist, "now": {"bond_ratio": 0.43}}), "0.47.0", None, ts="2026-11-18T19:00:00Z")
    assert on["call"]["bond_hedge"] == "on" and on["call"]["bond_state"] == "hedging" and on["call"]["bond_ratio"] == 0.43, "before, this logged off"
    hist2 = {"policies": {"bond_when_it_hedges": {"variance_cut": 0.30}}}         # and here the history says it helps a lot
    off = ledger.make_entry(_book("2026-11-17", correlation={"state": "neutral"}, hedges={**hist2, "now": {"bond_ratio": 0.007286}}), "0.47.0", None, ts="2026-11-18T19:00:00Z")
    assert off["call"]["bond_hedge"] == "off" and off["call"]["bond_state"] == "neutral" and off["call"]["bond_ratio"] == 0.0073, "before, this logged on"
    zero = ledger.bond_call({"correlation": {"state": "hedging"}, "hedges": {"now": {"bond_ratio": 0.0}}})
    assert zero == {"bond_hedge": "off", "bond_state": "hedging", "bond_ratio": 0.0}
    assert ledger.bond_call({}) == {"bond_hedge": "off", "bond_state": None, "bond_ratio": None}      # the page's snapshot carries neither reading
    assert ledger.entry_hash(on) == on["hash"] and ledger.entry_hash(off) == off["hash"]
    old = ledger.read()[0]
    assert "bond_state" not in old["call"] and ledger.entry_hash(old) == old["hash"], "an entry's hash covers the fields it has"


# ---------------------------------------------------------------- C. the live record's arithmetic
def _row(seq, ts, asof, eff, size, menu):
    return {"seq": seq, "ts_utc": ts, "data_asof": asof, "effective_from": eff, "call": {"size": size, "menu_high": menu}}


def test_the_live_record_marks_a_saturday_call_from_tuesday():
    P, ust = _prices(pd.bdate_range("2026-09-01", "2026-11-13")), _ust("2026-11-13")
    top = {"gross": 1.0, "short": 0.85}
    rows = [_row(1, "2026-11-03T15:00:00Z", "2026-11-02", "2026-11-04", 0.60, top),
            _row(2, "2026-11-06T18:14:25Z", "2026-11-05", "2026-11-09", 0.50, top),        # Friday, before the close
            _row(3, "2026-11-07T17:08:01Z", "2026-11-06", "2026-11-09", 0.40, top)]        # Saturday: stored Monday, governs Tuesday
    L = track.live_record(rows, P, ust)
    size = {d: s for d, _, _, _, s in L["series"]}
    assert size["2026-11-06"] == 0.60 and size["2026-11-09"] == 0.50 and size["2026-11-10"] == 0.40
    assert L["restated"] == [{"seq": 3, "ts_utc": "2026-11-07T17:08:01Z", "data_asof": "2026-11-06", "effective_from": "2026-11-09", "governs_from": "2026-11-10",
                              "why": "written after the close that begins the stored effective day's return"}]
    assert L["first_effective"] == "2026-11-04" and L["marked_days"] == len(L["series"]) == 8


def test_the_hedged_variant_holds_the_gross_its_menu_row_says_and_borrowing_costs(monkeypatch):
    P, ust = _prices(pd.bdate_range("2026-09-01", "2026-11-13")), _ust("2026-11-13")
    one = lambda size, menu: track.live_record([_row(1, "2026-11-03T15:00:00Z", "2026-11-02", "2026-11-04", size, menu)], P, ust)
    # a menu whose top row is the call itself (no short): the two variants are the same position
    same = one(0.5, {"gross": 0.5, "short": 0.0})
    assert same["total_hedged"] == pytest.approx(same["total"], abs=1e-12)
    assert one(0.5, {"gross": 0.9, "short": 0.6})["total_hedged"] != pytest.approx(one(0.5, {"gross": 1.0, "short": 0.6})["total_hedged"], abs=1e-9), "before, 0.9x was marked as 1.0x"
    assert one(0.5, None)["total_hedged"] == pytest.approx(one(0.5, {"gross": 1.0, "short": 0.0})["total_hedged"], abs=1e-12)
    # above 1.00x the record pays the walk-forward's spread on what it borrows, every day
    paid = one(1.2, {"gross": 1.0, "short": 0.85})
    monkeypatch.setitem(track.COST, "borrow_spread", 0.0)
    free = one(1.2, {"gross": 1.0, "short": 0.85})
    drag = (1 + free["total"]) / (1 + paid["total"]) - 1
    assert drag == pytest.approx(0.2 * 0.005 / 252 * paid["marked_days"], rel=0.02) and paid["total_hedged"] == pytest.approx(free["total_hedged"], abs=1e-12)
    monkeypatch.setitem(track.COST, "borrow_spread", 0.005)
    assert one(0.6, {"gross": 1.0, "short": 0.85})["total"] == pytest.approx(track.live_record([_row(1, "2026-11-03T15:00:00Z", "2026-11-02", "2026-11-04", 0.6, {"gross": 1.0, "short": 0.85})], P, ust)["total"])


def test_a_drawdown_counts_the_fall_from_the_starting_value():
    idx = pd.bdate_range("2026-01-05", periods=30)
    cash = pd.Series(0.0, index=idx)
    assert track.max_drawdown(pd.Series([-0.10, -0.05] + [0.0] * 28, index=idx)) == pytest.approx(1 - 0.9 * 0.95)       # before: 0.05
    assert track.stats(pd.Series([-0.10] + [0.0] * 29, index=idx), cash)["maxdd"] == pytest.approx(0.10)                   # before: 0.0
    up = pd.Series([0.10, -0.05] + [0.0] * 28, index=idx)
    assert track.stats(up, cash)["maxdd"] == pytest.approx(0.05), "a record that opens with a gain reads as it did"
    assert track.max_drawdown(pd.Series(dtype=float)) == 0.0


# ---------------------------------------------------------------- the paper account: fixtures
FIRST = [("AMZN", 27.0, 271.28), ("NVDA", 43.0, 169.14), ("GOOGL", 25.0, 285.35), ("MSFT", 13.0, 533.96), ("META", 9.0, 642.35),
         ("TSLA", 13.0, 380.35), ("SPCX", 29.0, 143.3), ("AVGO", 12.0, 332.48), ("ORCL", 26.0, 118.16)]      # the committed first ticket's fills
C11 = dict(trader.PAPER_CORRECTIONS[0]["closes"])                                                              # the Nov 11 closes
TID = trader.PAPER_CORRECTIONS[0]["ticket"]
AMOUNT = 379.90
WIDE = dict(mode="autonomous", broker="paper", max_order_usd=1e9, max_order_pct=1.0, max_equity_usd=1e9)


def _params(**kw):
    P = ex.load_params()
    P.vix_share, P.variant, P.mode = 0.0, "unhedged", "paper"
    for k, v in kw.items():
        setattr(P, k, v)
    return P


def _quotes(closes: dict):
    """closes: {date: {symbol: close}}; the newest date is the last quote, as the price mirror serves it."""
    def fn(symbols):
        last = max(closes)
        return {s: {"bid": closes[last][s] * 0.9995, "ask": closes[last][s] * 1.0005, "last": closes[last][s], "asof": last,
                    "closes": {d: c[s] for d, c in closes.items() if s in c}} for s in symbols if s in closes[last]}
    return fn


def _stale_account(state: Path, with_session_closes: bool = True) -> br.PaperBroker:
    """The committed account as it stood on Nov 18: the nine stale-priced fills, nothing else, marked at the Nov 17
    close (here the Nov 11 closes again, so the only thing that moves equity is the correction)."""
    spent = sum(q * p for _, q, p in FIRST)
    fills = [{"order_id": f"paper-{TID}-{i}", "price": p, "quantity": q, "side": "buy", "status": "filled", "symbol": s} for i, (s, q, p) in enumerate(FIRST, 1)]
    e = {"seq": 1, "ticket": TID, "mode": "paper", "ts_utc": "2026-11-11T19:54:15Z", "fills": fills, "issues": [], "status": "filled", "prev": "0" * 64}
    e["hash"] = ex._sha(e)
    state.mkdir(parents=True, exist_ok=True)
    (state / "fills.jsonl").write_text(ex._canon(e) + "\n")
    marks ={s: {"last": C11[s], "asof": "2026-11-17", "closes": ({"2026-11-11": C11[s], "2026-11-17": C11[s]} if with_session_closes else {"2026-11-17": C11[s]})} for s in C11}
    value = sum(q * C11[s] for s, q, _ in FIRST)
    acct = {"account_type": "agentic (paper)", "cash": 100_000.0 - spent, "positions": {s: q for s, q, _ in FIRST}, "marks": marks, "opened": "2026-11-11",
            "orders": {f"{TID}-{i}": {"order_id": f"paper-{TID}-{i}", "client_id": f"{TID}-{i}", "symbol": s, "side": "buy", "quantity": q, "limit": p, "status": "filled",
                                      "filled_qty": q, "avg_price": p, "placed": "2026-11-11T19:54:16+00:00"} for i, (s, q, p) in enumerate(FIRST, 1)},
            "equity_history": [["2026-11-16", 99_000.0], ["2026-11-17", round(100_000.0 - spent + value, 2)]], "start_cash": 100_000.0}
    (state / "paper_account.json").write_text(json.dumps(acct))
    return br.PaperBroker(state / "paper_account.json", quote_fn=_quotes({"2026-11-11": C11, "2026-11-17": C11} if with_session_closes else {"2026-11-17": C11}))


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path / "paper"))
    monkeypatch.setattr(ex, "PRIVATE", tmp_path / "private")
    return tmp_path / "paper"


# ---------------------------------------------------------------- D. the correction
def test_the_first_fill_is_corrected_once_in_the_chained_log(state):
    pb = _stale_account(state)
    before, cash0, line1 = pb.account()["equity"], pb.state["cash"], (state / "fills.jsonl").read_text()
    assert before == 100_354.41 and trader.paper_reconcile(pb.state)["ok"]
    now = datetime(2026, 11, 18, 19, 35, tzinfo=UTC)
    r1 = trader.run_once(pb, md.Mandate(**WIDE), _params(), now=now, force_window=True)
    assert r1["corrections"] == [{"id": "corr-2026-11-11-stale-close", "cash_delta": -AMOUNT, "equity_before": before, "equity_after": round(before - AMOUNT, 2)}]
    assert pb.account()["equity"] == pytest.approx(before - AMOUNT, abs=1e-9), "equity falls by exactly the correction: the marks did not move"
    assert pb.state["cash"] == pytest.approx(cash0 - AMOUNT, abs=1e-9)
    log = ex._fills()
    assert (state / "fills.jsonl").read_text().startswith(line1) and len(log) == 2, "the stale entry is still the first line, byte for byte"
    c = log[1]
    assert c["kind"] == "correction" and c["id"] == "corr-2026-11-11-stale-close" and c["corrects"] == TID and c["cash_delta"] == -AMOUNT and c["amount"] == AMOUNT
    assert c["fills"] == [] and c["status"] == "correction" and "ticket" not in c and c["prev"] == log[0]["hash"] and ex.verify_fills() == {"ok": True, "entries": 2}
    assert len(c["detail"]) == 9 and sum(d["difference"] for d in c["detail"]) == pytest.approx(379.89527, abs=1e-5)
    amzn = next(d for d in c["detail"] if d["symbol"] == "AMZN")
    assert amzn["price_under_the_rule"] == round(266.17 * 1.0005, 6) and amzn["paid"] == 271.28 and amzn["close_from"] == "the account's marks"
    assert trader.paper_reconcile(pb.state) == {"ok": True, "cash": round(cash0 - AMOUNT, 2), "cash_from_log": round(cash0 - AMOUNT, 2), "positions_match": True, "corrections": 1}
    # a second pass, and a broker loaded afresh from disk: nothing more
    cash1 = pb.state["cash"]
    r2 = trader.run_once(pb, md.Mandate(**WIDE), _params(), now=now + timedelta(minutes=5), force_window=True)
    pb2 = br.PaperBroker(state / "paper_account.json", quote_fn=pb.quote_fn)
    r3 = trader.run_once(pb2, md.Mandate(**WIDE), _params(), now=now + timedelta(minutes=10), force_window=True)
    assert "corrections" not in r2 and "corrections" not in r3 and pb2.state["cash"] == pytest.approx(cash1, abs=1e-9)
    assert len(ex.corrections()) == 1 and ex.verify_fills()["ok"] and [j["event"] for j in trader.journal()].count("correction") == 1
    assert ex.record_correction("corr-2026-11-11-stale-close", -1.0, "again")["recorded"] is False and len(ex._fills()) == len(log) == 2
    # the page's summary says it in words and carries the path both ways
    S = trader.paper_summary(state)
    k = S["corrections"][0]
    assert len(S["corrections"]) == 1 and k["amount"] == AMOUNT and k["cash_delta"] == -AMOUNT and k["ticket"] == TID and k["session"] == "2026-11-11"
    assert k["first_corrected_mark"] == "2026-11-17" and k["equity_before"] == before and k["equity_after"] == round(before - AMOUNT, 2)
    assert "$379.90 taken from cash on 2026-11-18" in k["summary"] and "price older than the order" in k["reason"] and "Correction: $379.90" in S["note"]
    assert S["equity_history"] == [["2026-11-16", 99_000.0], ["2026-11-17", round(before - AMOUNT, 2)]], "marks already published are left; the mark in hand carries it"
    assert S["equity_history_corrected"] == [["2026-11-16", round(99_000.0 - AMOUNT, 2)], ["2026-11-17", round(before - AMOUNT, 2)]]
    assert S["reconcile"]["ok"] and S["fills_chain"] == {"ok": True, "entries": 2} and S["tickets_filled"] == 1 and S["timeline"][0]["corrected_by"] == k["id"]
    assert trader._reconcile_paper(pb2, now, md.Mandate(**WIDE)) is None, "the correction is not mistaken for an unrecorded fill"


def test_the_correction_survives_a_pass_that_dies_halfway_and_closes_that_have_rolled_off(state, monkeypatch):
    pb = _stale_account(state, with_session_closes=False)                        # the mirror's twelve closes no longer reach back to Nov 11
    cash0 = pb.state["cash"]
    now = datetime(2026, 12, 3, 19, 35, tzinfo=UTC)
    real = ex.record_correction
    monkeypatch.setattr(ex, "record_correction", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    r = trader.run_once(pb, md.Mandate(**WIDE), _params(), now=now, force_window=True)
    assert "disk full" in r["corrections_error"] and pb.state["cash"] == pytest.approx(cash0 - AMOUNT, abs=1e-9) and len(ex._fills()) == 1
    assert not trader.paper_reconcile(pb.state)["ok"], "the account moved and the log has not said why yet"
    monkeypatch.setattr(ex, "record_correction", real)
    pb2 = br.PaperBroker(state / "paper_account.json", quote_fn=pb.quote_fn)
    r2 = trader.run_once(pb2, md.Mandate(**WIDE), _params(), now=now + timedelta(days=1), force_window=True)
    assert r2["corrections"][0]["cash_delta"] == -AMOUNT and pb2.state["cash"] == pytest.approx(cash0 - AMOUNT, abs=1e-9), "the next pass writes the record and takes nothing more"
    c = ex.corrections()
    assert len(c) == 1 and c[0]["amount"] == AMOUNT and c[0]["detail"][0]["close_from"] == "the correction's recorded closes" and trader.paper_reconcile(pb2.state)["ok"]
    # the other way round: the chain says it was applied and the account file is an older copy
    acct = json.loads((state / "paper_account.json").read_text())
    acct["cash"], acct["corrections"] = cash0, []
    (state / "paper_account.json").write_text(json.dumps(acct))
    pb3 = br.PaperBroker(state / "paper_account.json", quote_fn=pb.quote_fn)
    trader.run_once(pb3, md.Mandate(**WIDE), _params(), now=now + timedelta(days=2), force_window=True)
    assert pb3.state["cash"] == pytest.approx(cash0 - AMOUNT, abs=1e-9) and len(ex.corrections()) == 1 and trader.paper_reconcile(pb3.state)["ok"]


def test_an_account_that_never_held_the_stale_ticket_is_not_touched(state):
    pb = br.PaperBroker(state / "paper_account.json", quote_fn=_quotes({"2026-11-09": C11}))
    assert trader._apply_corrections(pb, datetime(2026, 11, 10, 15, 0, tzinfo=UTC)) is None and pb.state["cash"] == 100_000 and not ex._fills()
    assert trader._apply_corrections(br.AssistantBroker({"equity": 1.0}, {}), datetime(2026, 11, 10, 15, 0, tzinfo=UTC)) is None


def test_the_committed_paper_account_takes_the_correction_exactly_once(tmp_path, monkeypatch):
    """On a copy of paper/ as committed. Until the daily bot has run on this build the copy takes the correction on
    its first pass; after that it already carries it, and a pass adds nothing. Either way: once."""
    st = tmp_path / "paper"
    shutil.copytree(ROOT / "paper", st)
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(st))
    monkeypatch.setattr(ex, "PRIVATE", tmp_path / "private")
    acct = json.loads((st / "paper_account.json").read_text())
    marks = acct["marks"]
    qf = lambda S: {s: {"bid": marks[s]["last"] * 0.9995, "ask": marks[s]["last"] * 1.0005, **marks[s]} for s in S if s in marks}
    already = bool(ex.corrections())
    pb = br.PaperBroker(st / "paper_account.json", quote_fn=qf)
    eq0, n0 = pb.account()["equity"], len(ex._fills())
    asof = max(m["asof"] for m in marks.values())
    now = datetime.combine(sessions.next_session(asof), datetime.min.time(), tzinfo=UTC) + timedelta(hours=19, minutes=35)
    for k in range(2):
        trader.run_once(pb, md.Mandate(**WIDE), _params(), now=now + timedelta(minutes=5 * k), force_window=True)
    assert len(ex.corrections()) == 1 and ex.verify_fills()["ok"] and trader.paper_reconcile(pb.state)["ok"]
    assert ex.corrections()[0]["amount"] == AMOUNT
    assert len(ex._fills()) == n0 + (0 if already else 1)
    assert pb.account()["equity"] == pytest.approx(eq0 - (0 if already else AMOUNT), abs=0.005)


# ---------------------------------------------------------------- E, F. the bot follows the call the record marks
BASE = {"MSFT": 505.1, "AMZN": 236.2, "GOOGL": 280.4, "META": 610.0, "NVDA": 198.6, "AVGO": 349.0, "TSLA": 430.2, "SPCX": 48.3, "ORCL": 230.5}


def _call_at(now: datetime, size: float | None = None) -> dict:
    """The ledger entry a paper pass at `now` trades (the one governing the session after its fill), at another size."""
    held = sessions.next_session(sessions.session_of_close_after(now)).isoformat()
    c = ex.call_in_force(held, now=now)
    if size is not None:
        c = {**c, "size": size, "frontier": [{"gross": size, "short": 0.0, "meets": True}, {"gross": 1.0, "short": 0.85, "meets": True}]}
    return c


def _gross(pb) -> float:
    a = pb.account()
    return 1 - a["cash"] / a["equity"]


def _walk(state, sizes, P=None):
    """One pass a day at 10:00 New York from Tue Nov 10; prices drift a little each day. Returns the passes' reports."""
    days = ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18"]
    rng = np.random.default_rng(47)
    closes = {"2026-11-09": dict(BASE)}
    pb = br.PaperBroker(state / "paper_account.json", quote_fn=_quotes(closes), clock=lambda: datetime(2026, 11, 10, 15, 0, tzinfo=UTC))
    out = []
    for d, size in zip(days, sizes):
        now = datetime.fromisoformat(d + "T15:00:00+00:00")
        r = trader.run_once(pb, md.Mandate(**WIDE), P or _params(), now=now, call=_call_at(now, size), force_window=True)
        out.append({"day": d, "size": size, "outcome": r["outcome"], "resting": r.get("resting") or [], "settled": (r.get("settled") or {}).get("filled", 0),
                    "gross": _gross(pb), "ticket": r.get("ticket")})
        last = closes[max(closes)]
        closes[d] = {s: round(p * (1 + rng.normal(0, 0.012)), 2) for s, p in last.items()}      # that day's close, seen by the next pass
    return pb, out


def test_the_bot_follows_a_cut_in_the_call_and_does_not_churn_on_an_unchanged_one(state):
    pb, w = _walk(state, [0.53, 0.53, 0.53, 0.53, 0.45, 0.45, 0.45])
    assert w[0]["outcome"] == "orders resting until the close" and len(w[0]["resting"]) == 9
    # the build was sized on Monday's close and filled at Tuesday's, so what it holds is a little off the call; one
    # small top-up brings it inside the band (three single shares here), and then the unchanged call trades nothing
    assert w[1]["settled"] == 9 and abs(w[1]["gross"] - 0.53) < 0.015
    assert ex.load_ticket(w[1]["ticket"])["summary"]["buys_usd"] < 1_500 and len(w[1]["resting"]) <= 3
    for k in (2, 3):                                                             # prices moving about 1% a day, the call the same: nothing
        assert w[k]["outcome"].startswith("nothing to trade") and not w[k]["resting"] and abs(w[k]["gross"] - 0.53) < 0.01, w[k]
    cut = w[4]                                                                   # 0.53x to 0.45x: before v0.47 no name moved 2% of equity, and nothing traded
    assert cut["outcome"] == "orders resting until the close" and len(cut["resting"]) == 9 and all(o["side"] == "sell" for o in cut["resting"])
    assert all(float(o["quantity"]) == int(o["quantity"]) and o["quantity"] >= 1 for o in cut["resting"]), "whole shares"
    t = ex.load_ticket(cut["ticket"])
    assert t["rebalance"]["triggered"] and t["rebalance"]["names_outside_band"] == [] and t["rebalance"]["gross_gap"] < -0.05, "the book as a whole is outside its band; no single name is"
    assert w[5]["settled"] == 9 and abs(w[5]["gross"] - 0.45) < 0.01
    for k in (5, 6):
        assert w[k]["outcome"].startswith("nothing to trade") and not w[k]["resting"], w[k]
    assert sum(1 for e in ex._fills() if e.get("status") == "filled") == 3 and ex.verify_fills()["ok"] and trader.paper_reconcile(pb.state)["ok"]
    assert len(ex._tickets_on("2026-11-13")) == 1 and ex._tickets_on("2026-11-13")[0]["rebalance"]["triggered"] is False


def test_without_the_gross_band_the_same_cut_trades_nothing(state):
    """The behaviour before v0.47, reproduced by switching the new band off: each name alone stays inside 2% of equity."""
    pb, w = _walk(state, [0.53, 0.53, 0.53, 0.53, 0.45, 0.45, 0.45], P=_params(gross_band=1.0))
    assert [x["outcome"].startswith("nothing to trade") for x in w[1:]] == [True] * 6 and abs(w[-1]["gross"] - 0.53) < 0.02
    assert ex.TradingParams().gross_band == 0.01 and ex.TradingParams().drift_band == 0.02


def test_the_planner_rounds_to_the_nearest_share_unless_that_would_borrow():
    q = {s: {"bid": p * 0.9995, "ask": p * 1.0005, "last": p} for s, p in BASE.items()}
    acct = {"equity": 100_000.0, "cash": 100_000.0, "account_type": "agentic (paper)", "positions": []}
    chk = {"ok": True, "logged": True, "effective_from": None}
    call = lambda g: {"asof": "2026-11-06", "size": g, "binding": "drawdown_cap", "frontier": [{"gross": g, "short": 0.0, "meets": True}]}
    t = ex.plan(acct, q, call=call(0.53), P=_params(), weights=dict(bk.BOOK), today="2026-11-09", ledger_check=chk, now=datetime(2026, 11, 9, 15, 0, tzinfo=UTC))
    assert t["all_checks_pass"] and t["rebalance"]["rounding"] == "nearest share" and abs(t["summary"]["gross_after"] - 0.53) < 0.006
    full = ex.plan(acct, q, call=call(0.98), P=_params(), weights=dict(bk.BOOK), today="2026-11-09", ledger_check=chk, now=datetime(2026, 11, 9, 15, 1, tzinfo=UTC))
    assert full["all_checks_pass"] and full["summary"]["gross_after"] <= 0.98 and full["summary"]["cash_after"] >= 2_000.0
    for p in (ex._tickets_dir() / f"{t['id']}.json", ex._tickets_dir() / f"{full['id']}.json"):
        p.unlink()


def test_a_paper_pass_trades_the_call_the_live_record_marks_over_the_day_it_is_held(state):
    q = _quotes({"2026-11-13": dict(BASE)})
    # Saturday Nov 14, after the run wrote entry 10: the order fills at Monday's close and is held through Tuesday,
    # the day entry 10 governs. Before, the pass planned on entry 8 (in force on the Friday).
    sat = datetime(2026, 11, 14, 17, 23, tzinfo=UTC)
    pb = br.PaperBroker(state / "paper_account.json", quote_fn=q, clock=lambda: sat)
    r = trader.run_once(pb, md.Mandate(**WIDE), _params(), now=sat, force_window=True)
    t = ex.load_ticket(r["ticket"])
    assert r["outcome"] == "orders resting until the close" and r["fills_in_session"] == "2026-11-16"
    assert t["call"]["decision_id"].startswith("10-") and t["call"]["effective_from"] == "2026-11-17" == t["call"]["held_session"] and t["all_checks_pass"]
    assert {"held_session": "2026-11-17"} in r["steps"]
    L = {e["seq"]: e for e in ledger.read()[:12]}
    assert ledger.governs_from(L[10]) == t["call"]["held_session"], "the live record marks the same entry over the same session"


def test_a_weekday_paper_pass_trades_the_call_written_that_day(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path / "wed"))
    wed = datetime(2026, 11, 18, 19, 36, tzinfo=UTC)                             # the daily run: entry 12 written a minute before
    pb = br.PaperBroker(tmp_path / "wed" / "paper_account.json", quote_fn=_quotes({"2026-11-17": dict(BASE)}), clock=lambda: wed)
    r = trader.run_once(pb, md.Mandate(**WIDE), _params(), now=wed, force_window=True)
    t = ex.load_ticket(r["ticket"])
    assert t["call"]["decision_id"].startswith("12-") and t["call"]["held_session"] == "2026-11-19" and r["fills_in_session"] == "2026-11-18"
    # a live order is held through today, and trades the call that governs today
    assert ex.call_in_force("2026-11-18", now=wed)["ledger_seq"] == 11


# ---------------------------------------------------------------- G. the evidence is counted in sessions
def test_the_committed_paper_record_counts_only_sessions_after_a_causal_fill():
    n, first = trader.paper_sessions_held(ROOT / "paper")
    hist = json.loads((ROOT / "paper" / "paper_account.json").read_text())["equity_history"]
    e = trader.evidence(ROOT / "paper", ROOT / "private-does-not-exist")
    assert e["paper_days"] == n and e["paper_first_fill"] == first and not e["open"]
    if first is None:                                                            # as committed on Nov 18: the only fill was priced before its order
        assert n == 0 and "it has none yet" in e["missing"][0]
    else:
        assert n <= len([h for h in hist if h[0] > first and sessions.is_session(h[0])])


# ---------------------------------------------------------------- H. staged tickets
def test_the_newest_unexpired_staged_ticket_is_the_one_acted_on(tmp_path, monkeypatch):
    M = md.Mandate(mode="manual", broker="paper", max_order_usd=50_000)
    orders = set()
    for k in range(10):                                                          # ticket ids are hashes: both orders of A and B come up
        st = tmp_path / f"s{k}"
        monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(st))
        t0 = datetime(2026, 11, 10, 15, 0, k, tzinfo=UTC)
        pb = br.PaperBroker(st / "paper_account.json", quote_fn=_quotes({"2026-11-09": dict(BASE)}), clock=lambda: t0)
        a = trader.run_once(pb, M, _params(), now=t0, call=_call_at(t0, 0.53))["ticket"]
        b = trader.run_once(pb, M, _params(), now=t0 + timedelta(minutes=20), call=_call_at(t0, 0.53))["ticket"]      # A has expired: B is staged
        assert a != b and ex._tickets_on("2026-11-10") and json.loads((st / "tickets" / f"{a}.json").read_text())["status"] == "expired"
        trader.approve(b, by="test", now=t0 + timedelta(minutes=21))
        r = trader.run_once(pb, M, _params(), now=t0 + timedelta(minutes=22), call=_call_at(t0, 0.53))
        assert r["outcome"] == "orders resting until the close" and r["ticket"] == b, "before, an expired ticket whose id sorted last hid the approved one"
        with pytest.raises(ValueError):
            trader.approve(a, by="test", now=t0 + timedelta(minutes=23))         # an expired ticket cannot be approved
        assert [j["ticket"] for j in trader.journal() if j["event"] == "expired"] == [a], "and it is journalled once"
        orders.add(a > b)
    assert orders == {True, False}, "both orderings were exercised"


def test_a_staged_ticket_planned_on_another_call_is_not_reused(state):
    M = md.Mandate(mode="manual", broker="paper", max_order_usd=50_000)
    t0 = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
    pb = br.PaperBroker(state / "paper_account.json", quote_fn=_quotes({"2026-11-09": dict(BASE)}), clock=lambda: t0)
    a = trader.run_once(pb, M, _params(), now=t0, call=_call_at(t0, 0.53))["ticket"]
    same = trader.run_once(pb, M, _params(), now=t0 + timedelta(minutes=2), call=_call_at(t0, 0.53))
    assert same["ticket"] == a, "the same call inside the ticket's life: the staged ticket stands"
    trader.approve(a, by="test", now=t0 + timedelta(minutes=3))
    r = trader.run_once(pb, M, _params(), now=t0 + timedelta(minutes=5), call=_call_at(t0, 0.40))
    assert r["ticket"] != a and r["outcome"] == "staged, awaiting approval", "the approval was of a ticket for 0.53x; the call is now 0.40x"
    assert ex.load_ticket(a)["status"] == "superseded" and ex.load_ticket(r["ticket"])["call"]["size"] == 0.40 and pb.open_orders() == []
    j = [x for x in trader.journal() if x["event"] == "superseded"]
    assert len(j) == 1 and j[0]["ticket"] == a and "0.53x" in j[0]["why"] and "0.4x" in j[0]["why"]
