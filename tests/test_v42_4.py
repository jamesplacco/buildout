"""v0.42.4: the trader acts on the call in force today; live trading is manual until the evidence is in.
  - The paper bot ran three days and never traded: it took the newest call, which takes effect tomorrow.
  - `armed` was only checked in autonomous mode; a manual live mandate could hand orders over unarmed.
  - The evidence gate: 60 paper days with a position and 5 live tickets filled under an approval of their own id,
    before a live broker may run supervised or autonomous. Thresholds are constants in trader.py."""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from buildout import broker as br
from buildout import execution as ex
from buildout import ledger
from buildout import mandate as md
from buildout import trader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_v42 as T  # noqa: E402


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDOUT_TRADER_STATE", str(tmp_path))
    return tmp_path


def _live(mode):
    return md.Mandate(mode=mode, armed=True, broker="assistant", signed_by="J", signed_on="2026-11-08", notes="rehearsal", max_order_usd=50_000)


def _assistant():
    return br.AssistantBroker({"equity": 50_000.0, "cash": 50_000.0, "account_type": "Agentic", "positions": []}, T._qf(list(T.PX)))


def test_the_call_in_force_is_the_newest_entry_whose_day_has_come():
    rows = ledger.read()
    assert ex.call_in_force("2026-11-03") is None                                     # before the first effective date
    c = ex.call_in_force("2026-11-09")
    assert c["ledger_seq"] == 5 and c["asof"] == "2026-11-06" and c["effective_from"] == "2026-11-09"     # the newer of two effective that day
    assert ex.call_in_force("2026-11-11")["ledger_seq"] == 6 and ex.call_in_force("2026-11-10")["ledger_seq"] == 5
    last = ex.call_in_force("2099-01-01")
    assert last["ledger_seq"] == rows[-1]["seq"] and last["frontier"][0]["gross"] == pytest.approx(rows[-1]["call"]["size"], abs=1e-3)
    assert [f["meets"] for f in last["frontier"]] == [True, True]


def test_the_paper_bot_trades_the_day_after_a_call_is_written(state):
    """The daily run writes the call, then runs the bot: on Nov 11 the call written Nov 10 is in force and trades."""
    from datetime import datetime, timezone
    now = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)
    pb = br.PaperBroker(state / "paper_account.json", quote_fn=T._qf)
    r = trader.run_once(pb, md.Mandate(mode="autonomous", broker="paper", max_order_usd=1e9, max_order_pct=1.0), T._params(), now=now, poll_seconds=0.01)
    assert r["outcome"] == "executed" and len(r["fills"]) == 9
    t = ex.load_ticket(r["ticket"])
    assert t["call"]["asof"] == "2026-11-09" and t["call"]["effective_from"] == "2026-11-11"
    j = trader.journal()[-1]
    assert j["event"] == "executed" and j["broker"] == "paper" and j["approval"] == "autonomous"


def test_a_live_broker_needs_armed_in_every_mode(state):
    for mode in md.MODES:
        M = md.Mandate(mode=mode, armed=False, broker="assistant", max_order_usd=50_000)
        r = trader.run_once(_assistant(), M, T._params(), now=T.NOW, call=T._call())
        assert r["outcome"] == "not armed: staged only", mode


@pytest.mark.parametrize("mode", ["supervised", "autonomous"])
def test_until_the_evidence_is_in_a_live_broker_is_manual(state, mode):
    r = trader.run_once(_assistant(), _live(mode), T._params(), now=T.NOW, call=T._call())
    assert r["outcome"] == "staged, awaiting approval" and not r["gate"]["open"]
    assert any(x.startswith("gate: the paper bot has") for x in r["reasons"]) and any("live tickets" in x for x in r["reasons"])
    trader.approve("standing", by="test", standing_minutes=120, now=T.NOW)             # a standing approval does not open a gated pass
    assert trader.run_once(_assistant(), _live(mode), T._params(), now=T.NOW + timedelta(minutes=1), call=T._call())["outcome"] == "staged, awaiting approval"
    trader.approve(r["ticket"], by="test", now=T.NOW)                                  # this ticket's id does
    r2 = trader.run_once(_assistant(), _live(mode), T._params(), now=T.NOW + timedelta(minutes=2), call=T._call())
    assert r2["outcome"] == "handed to the assistant"
    j = [e for e in trader.journal() if e["event"] == "handoff"][-1]
    assert j["broker"] == "assistant" and j["mode"] == "manual" and j["approval"] == "ticket"


def test_with_the_evidence_in_the_mandates_mode_applies(state, monkeypatch):
    monkeypatch.setattr(trader, "evidence", lambda *a, **k: {"open": True, "missing": []})
    assert trader.run_once(_assistant(), _live("autonomous"), T._params(), now=T.NOW, call=T._call())["outcome"] == "handed to the assistant"


def _write(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_evidence_counts_what_the_records_show(tmp_path):
    paper, private = tmp_path / "paper", tmp_path / "private"
    assert trader.evidence(paper, private) == {**trader.evidence(paper, private), "open": False, "paper_days": 0, "live_manual_tickets": 0}
    days = [f"2026-11-{d:02d}" for d in range(10, 31)] + [f"2026-12-{d:02d}" for d in range(1, 32)] + [f"2027-01-{d:02d}" for d in range(1, 21)]
    _write(paper / "trader" / "equity.jsonl", [{"date": d, "equity": 1e5} for d in days])
    _write(paper / "trader" / "journal.jsonl", [{"event": "pass", "ts_utc": "2026-11-10T19:00:00Z"}, {"event": "executed", "ts_utc": "2026-11-12T19:00:00Z", "ticket": "p1"}])
    e = trader.evidence(paper, private)
    assert e["paper_first_fill"] == "2026-11-12" and e["paper_days"] == len(days) - 2 and e["paper_days"] >= trader.PAPER_DAYS_REQUIRED       # days before the first fill do not count
    assert not e["open"] and len(e["missing"]) == 1
    J = [{"event": "handoff", "ticket": f"t{i}", "broker": "assistant", "approval": "ticket"} for i in range(5)]
    J += [{"event": "handoff", "ticket": "s1", "broker": "assistant", "approval": "standing"}, {"event": "executed", "ticket": "pp", "broker": "paper", "approval": "ticket"}]
    _write(private / "trader" / "journal.jsonl", J)
    _write(private / "fills.jsonl", [{"ticket": f"t{i}", "status": "filled"} for i in range(4)] + [{"ticket": "s1", "status": "filled"}, {"ticket": "pp", "status": "filled"}])
    assert trader.evidence(paper, private)["live_manual_tickets"] == 4                 # approved and filled; standing and paper do not count
    _write(private / "fills.jsonl", [{"ticket": f"t{i}", "status": "filled"} for i in range(5)])
    assert trader.evidence(paper, private)["open"]


def test_the_thresholds_are_in_code_not_in_the_mandate():
    assert trader.PAPER_DAYS_REQUIRED == 60 and trader.LIVE_MANUAL_TICKETS_REQUIRED == 5
    assert not {"paper_days_required", "evidence", "gate"} & set(md.Mandate.__dataclass_fields__)
    rec = trader.recommendation()
    assert rec["evidence_gate"]["paper_days_required"] == 60 and rec["in_force"].startswith("ledger entry")


def test_the_repo_has_a_license():
    lic = (ROOT / "LICENSE").read_text()
    assert lic.startswith("MIT License") and "James Placco" in lic
    assert 'license = "MIT"' in (ROOT / "pyproject.toml").read_text() or "MIT" in (ROOT / "pyproject.toml").read_text()
