"""The trader (v0.42): from the model's recommendation to orders, under a written mandate, in one of three modes.

    recommendation()    what the model says today: the call (the live rule's size and short), the deep RL sizer's view,
                        the hedge terms, and the target holdings for an Agentic account
    run_once()          one pass: halt? window? already acted today? account and quotes from the broker, the ticket
                        (execution.plan), the mandate's checks, then the mode gate:
                          manual       stage the ticket and stop; it executes on a later pass once approved
                          supervised   stage; execute on a later pass if an approval (or a standing approval) is in force
                          autonomous   execute now, if armed
                        execution: sells first, then buys, each polled to its fill or cancelled at the ticket's expiry;
                        fills recorded to the hash-chained log; the account marked; a journal line and a digest written
    loop()              run_once every N minutes until stopped (private/HALT, Ctrl-C)

Idempotent by construction: one executed ticket a day (execution.plan's check), one order per client id (the broker's
check), the ticket's id covering every field. State under execution.state_root(): tickets/, fills.jsonl, trader/
(journal.jsonl, approvals.json, equity.jsonl, digest.md). The paper bot runs this with BUILDOUT_TRADER_STATE=paper.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import execution as ex
from . import mandate as md

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- the model's recommendation
def recommendation(P: ex.TradingParams | None = None, M: md.Mandate | None = None) -> dict:
    """What the model recommends today, before any account is looked at."""
    from . import book as bk
    P = P or ex.load_params()
    M = M or md.load()
    newest = ex.latest_call()
    call = ex.call_in_force() or newest
    T = ex.target(call, P, dict(bk.BOOK))
    out = {"asof": call.get("asof"), "effective_from": call.get("effective_from") or _effective(call), "size": call.get("size"), "binding": call.get("binding"),
           "menu_high": call.get("keep_names_hedge") or call.get("menu_high"), "variant": P.variant, "target_weights": {k: round(v, 4) for k, v in T["weights"].items()},
           "book_gross": round(T["book_gross"], 4), "index_short_as_psq": round(T["short"], 4), "vix_sleeve": round(T["vix"], 4),
           "mandate": {"mode": M.mode, "armed": M.armed, "broker": M.broker, "hash": M.hash(), "problems": M.problems()},
           "in_force": call.get("source", "the newest call"), "next_call": {"asof": newest.get("asof"), "size": newest.get("size")} if newest.get("asof") != call.get("asof") else None,
           "evidence_gate": evidence(),
           "reasons": [f"The live rule sizes the book at {float(call.get('size') or 0):.2f}x of equity; binding limit: {call.get('binding')}.",
                       f"The {P.variant} variant: " + ("the smallest size every limit allows, no index short." if P.variant == "unhedged" else "the largest size the cash account can hold with its index short as PSQ."),
                       f"VIX sleeve {P.vix_share:.0%} of equity in {P.vix_symbol}; the Hedge test desk's study says it pays in crashes and costs carry otherwise."]}
    rl = _deeprl_view()
    if rl:
        out["deep_rl"] = rl
        out["reasons"].append(f"The deep RL sizer (research, not the call): {rl.get('action')}x for the market as of {rl.get('date')}; on the book it lost to the call, so it does not size the book.")
    return out


def _effective(call: dict) -> str | None:
    try:
        from . import ledger
        rows = ledger.read()
        for r in reversed(rows):
            if r.get("call", {}).get("asof") == call.get("asof") or r.get("data_asof") == call.get("asof"):
                return ledger.governs_from(r)              # v0.47: the session it governs, not the date it stored
    except Exception:  # noqa: BLE001
        return None
    return None


def _deeprl_view() -> dict | None:
    import re
    p = ROOT / "site" / "src" / "snap38.js"
    if not p.exists():
        return None
    try:
        T = json.loads(re.search(r"const SNAP38 = (\{.*\});", p.read_text()).group(1))
        n = T.get("deeprl", {}).get("now")
        return {"date": n["date"], "action": n["action"], "plan_action": n["plan_action"], "probs": n["probs"]} if n else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- state
def _tdir() -> Path:
    d = ex.state_root() / "trader"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _journal(entry: dict) -> None:
    entry = {"ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **entry}
    with (_tdir() / "journal.jsonl").open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def journal(n: int = 50) -> list[dict]:
    p = _tdir() / "journal.jsonl"
    if not p.exists():
        return []
    return _jsonl(p)[-n:]


def _jsonl(p: Path) -> list[dict]:
    """The rows of a .jsonl file; a line cut short by a crash mid-write is skipped, not fatal (v0.44.1)."""
    out = []
    for x in p.read_text().splitlines():
        if not x.strip():
            continue
        try:
            out.append(json.loads(x))
        except json.JSONDecodeError:
            continue
    return out


def _approvals() -> dict:
    p = _tdir() / "approvals.json"
    return json.loads(p.read_text()) if p.exists() else {}


def approve(ticket_id: str, by: str = "", standing_minutes: int | None = None, now: datetime | None = None) -> dict:
    """Approve a staged ticket (its id must verify), or with ticket_id "standing" give a standing approval for the
    next `standing_minutes` (supervised mode)."""
    now = now or datetime.now(timezone.utc)
    A = _approvals()
    if ticket_id == "standing":
        until = now + timedelta(minutes=int(standing_minutes or 60))
        A["standing"] = {"by": by, "until": until.strftime("%Y-%m-%dT%H:%M:%SZ"), "given": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    else:
        t = ex.load_ticket(ticket_id)                                   # raises if unknown or altered
        if t.get("status"):
            raise ValueError(f"ticket {ticket_id} is already {t['status']}")
        A[ticket_id] = {"by": by, "given": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "expires": t["expires"]}
    ex._atomic_write_text(_tdir() / "approvals.json", json.dumps(A, indent=1))
    _journal({"event": "approved", "ticket": ticket_id, "by": by})
    return A


def _approved(tid: str, M: md.Mandate, now: datetime, mode: str | None = None) -> tuple[bool, str, str | None]:
    """(approved, why, kind): kind is "ticket" for an approval of this ticket id, "standing" for a standing one."""
    mode = mode or M.mode
    A = _approvals()
    a = A.get(tid)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if a:
        given = datetime.strptime(a["given"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if (now - given) <= timedelta(minutes=M.approval_ttl_min):
            return True, f"approved by {a.get('by') or 'the person'} at {a['given']}", "ticket"
        return False, f"the approval of {a['given']} is older than the mandate's {M.approval_ttl_min} minutes", None
    s = A.get("standing")
    if s and mode == "supervised" and s["until"] >= stamp:
        return True, f"standing approval until {s['until']}", "standing"
    return False, "no approval on file", None


# ---------------------------------------------------------------- the evidence gate (v0.42.4)
PAPER_DAYS_REQUIRED = 60            # exchange sessions the public paper bot has closed holding a position, after its first causal fill
LIVE_MANUAL_TICKETS_REQUIRED = 5    # live tickets filled after the person approved that ticket's id


def paper_sessions_held(paper_dir: Path) -> tuple[int, str | None]:
    """(sessions, first causal fill): the exchange sessions the paper account closed holding a position, counted
    after the session of its first causal fill (v0.47). A causal fill is one made at a close that came after its
    order (the v0.42.5 convention; its entry in the fills log says so and carries the session). A session counts
    when the account's own equity path has a mark for it, the exchange was open, and the fills log shows shares
    held at that close. Before, the count was of the dates the trader ran: a Saturday pass counted, so did the day
    of a fill priced before its order, and a week with a holiday counted five."""
    from . import sessions
    paper_dir = Path(paper_dir)

    def jsonl(p: Path) -> list[dict]:
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict):
                out.append(r)
        return out

    moves, causal = [], []                               # (session, signed shares) for every fill; the causal fills' sessions
    for e in jsonl(paper_dir / "fills.jsonl"):
        if e.get("status") not in ("filled", "partially_filled"):
            continue
        for f in e.get("fills", []):
            day = str(f.get("session") or e.get("ts_utc", ""))[:10]
            try:
                q = float(f.get("quantity") or 0) * (1.0 if f.get("side") == "buy" else -1.0)
            except (TypeError, ValueError):
                continue
            moves.append((day, q))
            if e.get("convention") and f.get("session"):
                causal.append(str(f["session"])[:10])
    first = min(causal, default=None)
    if first is None:
        return 0, None
    try:
        hist = json.loads((paper_dir / "paper_account.json").read_text()).get("equity_history") or []
    except (OSError, ValueError, AttributeError):
        hist = []
    days = set()
    for h in hist:
        try:
            d = str(h[0])[:10]
            ok = d > first and sessions.is_session(d)
        except (TypeError, ValueError, IndexError):
            continue
        if ok and sum(q for day, q in moves if day <= d) > 1e-9:
            days.add(d)
    return len(days), first


def evidence(paper_dir: Path | None = None, private_dir: Path | None = None) -> dict:
    """Has unattended live trading been earned? Two records, both read from files the trader itself writes:
      1. the paper bot (paper/, committed by the daily run): exchange sessions closed holding a position, after its
         first causal fill (paper_sessions_held);
      2. the live route (private/): tickets filled through a live broker after an approval of that ticket's id.
    Until both are met, a live broker trades in manual mode whatever the mandate says. The thresholds are constants
    in this file on purpose: changing them is a code change, visible in the repository's history."""
    paper_dir = Path(paper_dir) if paper_dir else ROOT / "paper"
    private_dir = Path(private_dir) if private_dir else ex.PRIVATE

    def rows(p: Path) -> list[dict]:
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    paper_days, first = paper_sessions_held(paper_dir)
    lj = rows(private_dir / "trader" / "journal.jsonl")
    approved = {r["ticket"] for r in lj if r.get("event") in ("executed", "handoff") and r.get("broker") not in (None, "paper") and r.get("approval") == "ticket"}
    filled = {r["ticket"] for r in rows(private_dir / "fills.jsonl") if r.get("status") in ("filled", "partially_filled") and r.get("ticket")}
    live = len(approved & filled)
    missing = []
    if paper_days < PAPER_DAYS_REQUIRED:
        missing.append(f"the paper bot has closed {paper_days} of {PAPER_DAYS_REQUIRED} exchange sessions holding a position since its first causal fill"
                       + ("" if first else " (it has none yet: no fill at a close that came after its order)"))
    if live < LIVE_MANUAL_TICKETS_REQUIRED:
        missing.append(f"{live} of {LIVE_MANUAL_TICKETS_REQUIRED} live tickets have filled under an approval of their own id")
    return {"open": not missing, "paper_days": paper_days, "paper_days_required": PAPER_DAYS_REQUIRED, "paper_first_fill": first,
            "live_manual_tickets": live, "live_manual_tickets_required": LIVE_MANUAL_TICKETS_REQUIRED, "missing": missing}


def _equity_history(before: str | None = None) -> dict:
    """The equity record the mandate's halts read. before (v0.44.1): only points dated before this day, so
    "yesterday" is never today's own point (which the pass writes first, and which made the day-loss halt read 0%)."""
    p = _tdir() / "equity.jsonl"
    rows = _jsonl(p) if p.exists() else []
    if before:
        rows = [r for r in rows if str(r.get("date", "")) < before]
    out = {"peak_equity": max((r["equity"] for r in rows), default=None), "prev_equity": rows[-1]["equity"] if rows else None, "n": len(rows)}
    done = [r for r in journal(1000) if r.get("event") == "executed"]
    out["tickets_executed"] = len(done)
    # v0.44.1: a close-filled ticket is journalled the day after its session; the spacing rule counts from the
    # session it traded in (else the bot could only trade every other day)
    last = done[-1] if done else None
    out["last_ticket_date"] = str(last.get("fill_session") or last.get("ordered") or last["ts_utc"])[:10] if last else None
    return out


def _mark_equity(account: dict, now: datetime) -> None:
    p = _tdir() / "equity.jsonl"
    day = now.date().isoformat()
    rows = _jsonl(p) if p.exists() else []
    row = {"date": day, "equity": float(account["equity"]), **({"marks_asof": account["marks_asof"]} if account.get("marks_asof") else {})}
    if rows and rows[-1]["date"] == day:
        rows[-1] = row
    else:
        rows.append(row)
    ex._atomic_write_text(p, "".join(json.dumps(r) + "\n" for r in rows))


def _paper_fill_rows(done: list[dict]) -> list[dict]:
    return [{"symbol": o["symbol"], "side": o["side"], "quantity": o["filled_qty"], "price": o["avg_price"], "order_id": o["order_id"], "status": "filled",
             "session": o["fill_session"], "filled": o["filled"], "ordered": o["placed"], "inside_limit": o.get("inside_limit")} for o in done]


def _reconcile_paper(broker, now: datetime, M: md.Mandate) -> dict | None:
    """Fills the paper account holds that the fills log does not (v0.44.1). settle() changes the account and saves
    it; the fills are written to the log after that. A pass that died between the two left an account that had
    traded and a log that said it had not, and no later pass looked. Every pass now looks first: a filled order
    with no entry in the log is recorded against its ticket and journalled as reconciled."""
    st = getattr(broker, "state", None)
    if not isinstance(st, dict):
        return None
    logged = {f.get("order_id") for e in ex._fills() for f in e.get("fills", [])}
    by: dict[str, list] = {}
    for o in (st.get("orders") or {}).values():
        if o.get("status") == "filled" and o.get("order_id") not in logged:
            by.setdefault(str(o["client_id"]).rsplit("-", 1)[0], []).append(o)
    if not by:
        return None
    out = {"recorded": 0, "tickets": []}
    for tid, done in sorted(by.items()):
        rec = ex.record_fills(tid, _paper_fill_rows(done), now, at_close=True)
        _journal({"event": "executed", "ticket": tid, "fills": len(done), "failures": 0, "status": rec.get("status"), "mandate_hash": M.hash(),
                  "broker": getattr(broker, "name", "?"), "mode": M.mode, "reconciled": True,
                  "why": "the account held these fills and the fills log did not; an earlier pass stopped between the two",
                  "ordered": min((o["placed"] for o in done), default=None), "fill_session": min((o["fill_session"] for o in done), default=None),
                  "filled_at": min((o["filled"] for o in done), default=None)})
        out["recorded"] += len(done)
        out["tickets"].append({"ticket": tid, "fills": len(done), "status": rec.get("status")})
    return out


# ---------------------------------------------------------------- corrections to the paper record (v0.47)
# A correction puts right an entry the chained fills log already holds, without touching that entry: a dated cash
# adjustment in the account and a record of kind "correction" appended to the same chain. Each is listed here, in
# code, so what was corrected and by how much is a commit, and each is applied once, by the first pass that finds it
# due. The closes are those the price mirror carried for that session when the correction was written (the paper
# account's own marks held the same figures); the account's marks are used when they still hold that session, and
# these when they no longer do.
PAPER_CORRECTIONS = (
    {"id": "corr-2026-11-11-stale-close", "ticket": "tkt-5c12ef101db360fd", "session": "2026-11-11",
     "closes": {"AMZN": 266.17, "NVDA": 173.73, "GOOGL": 290.63, "MSFT": 521.13, "META": 628.77, "TSLA": 390.84, "SPCX": 139.75, "AVGO": 345.22, "ORCL": 128.38},
     "reason": ("The account's first ticket was written on Nov 11, 2026 at 19:54 UTC, during that day's session, and filled at once at a price built on "
                "the Nov 10 close: a price older than the order, under the convention in use before v0.42.5. The rule since then fills an order at the "
                "close of the first session that ends after it was written, with a 5 basis point half-spread. This takes from cash the difference "
                "between what those fills paid and what the same shares cost at the Nov 11 close under that rule. The fills stay in the log as recorded.")},
)


def _correction_amount(C: dict, entry: dict, state: dict) -> tuple[float, list[dict]]:
    """(cash to take out, per-fill detail): what the entry's fills would have cost at the session's close under the
    paper broker's rule (the close plus the half-spread to buy, less it to sell, to six decimals as the broker
    rounds), less what they paid. Rounded to the cent, the unit the account's equity is kept in."""
    from .broker import PaperBroker
    half = PaperBroker.HALF_SPREAD
    detail, total = [], 0.0
    for f in entry.get("fills", []):
        s, side, qty, paid = f["symbol"], f["side"], float(f["quantity"]), float(f["price"])
        held = (((state.get("marks") or {}).get(s) or {}).get("closes") or {}).get(C["session"])
        close = float(held) if held is not None else float(C["closes"][s])
        px = round(close * (1 + half if side == "buy" else 1 - half), 6)
        diff = qty * (px - paid) if side == "buy" else qty * (paid - px)
        detail.append({"symbol": s, "side": side, "quantity": qty, "paid": paid, "close": close, "price_under_the_rule": px,
                       "difference": round(diff, 6), "close_from": "the account's marks" if held is not None else "the correction's recorded closes"})
        total += diff
    return round(total, 2), detail


def _apply_corrections(broker, now: datetime) -> list[dict] | None:
    """Apply every correction that is due and not yet applied; None when there is nothing to do. Two steps, each
    safe to repeat: the account (cash, a marker beside it, one atomic save), then the chained record. A pass that
    dies between them leaves the marker, and the next pass writes only the record; a second pass after both does
    nothing. The equity point for the marks in hand is restated in the same save (as any second pass on the same
    marks restates it) and the marker keeps the figure it replaced."""
    st = getattr(broker, "state", None)
    if not isinstance(st, dict) or not getattr(broker, "fills_at_close", False):
        return None
    log = ex._fills()
    out = []
    for C in PAPER_CORRECTIONS:
        entry = next((e for e in log if e.get("ticket") == C["ticket"] and e.get("status") in ("filled", "partially_filled") and not e.get("convention")), None)
        if entry is None:
            continue                                       # this account never held the entry the correction is for
        rec = next((e for e in log if e.get("kind") == "correction" and e.get("id") == C["id"]), None)
        marker = next((m for m in st.get("corrections") or [] if m.get("id") == C["id"]), None)
        if rec is not None and marker is not None:
            continue
        if marker is None:
            if rec is not None:                            # the chain says it was applied and the account file does not: the chain stands
                amount, detail = -float(rec["cash_delta"]), rec.get("detail") or []
            else:
                amount, detail = _correction_amount(C, entry, st)
            before = broker.mark()
            st["cash"] = float(st["cash"]) - amount
            marker = {"id": C["id"], "corrects": C["ticket"], "session": C["session"], "amount": abs(amount), "cash_delta": -amount,
                      "applied": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "equity_before": before["equity"], "first_corrected_mark": before["asof"] or None,
                      "detail": detail}
            st.setdefault("corrections", []).append(marker)
            marker["equity_after"] = broker.mark()["equity"]
            broker.save()
        if rec is None:
            ex.record_correction(C["id"], marker["cash_delta"], C["reason"], corrects=C["ticket"], detail=marker.get("detail"), now=now,
                                 extra={"session": C["session"], "equity_before": marker.get("equity_before"), "equity_after": marker.get("equity_after"),
                                        "first_corrected_mark": marker.get("first_corrected_mark")})
            _journal({"event": "correction", "id": C["id"], "ticket": C["ticket"], "broker": getattr(broker, "name", "?"),
                      "outcome": f"cash {marker['cash_delta']:+,.2f}: the first ticket repriced at the {C['session']} close", "cash_delta": marker["cash_delta"]})
        out.append({"id": C["id"], "cash_delta": marker["cash_delta"], "equity_before": marker.get("equity_before"), "equity_after": marker.get("equity_after")})
    return out or None


def paper_reconcile(state: dict) -> dict:
    """The account file against the fills log (v0.47): cash and shares rebuilt from the log alone, corrections
    included, beside what the account holds. ok when both agree to the cent and the share."""
    want = ex.cash_and_positions_from_log(float(state.get("start_cash") or 0.0))
    have = {s: float(q) for s, q in (state.get("positions") or {}).items() if abs(float(q)) > 1e-9}
    cash = float(state.get("cash") or 0.0)
    same = set(want["positions"]) == set(have) and all(abs(want["positions"][s] - have[s]) < 1e-6 for s in have)
    return {"ok": bool(abs(want["cash"] - cash) < 0.005 and same), "cash": round(cash, 2), "cash_from_log": round(want["cash"], 2), "positions_match": bool(same),
            "corrections": len(ex.corrections())}


def _settle_resting(broker, now: datetime, M: md.Mandate, cancel: bool = False) -> dict | None:
    """Resting paper orders meet the close of their session (v0.42.5). Reads the closes for the symbols with open
    orders, fills what is due, records the fills against their tickets and journals each ticket with the four
    times in order: the decision, the order, the close that priced it, and this pass, which only observed it. A
    halt cancels what is resting instead."""
    open_ = broker.open_orders()
    if not open_:
        return None
    if cancel:
        for o in open_:
            broker.cancel(o["order_id"])
        for tid in sorted({o["client_id"].rsplit("-", 1)[0] for o in open_}):
            try:
                t = ex.load_ticket(tid); t["status"] = "cancelled"; ex._save_ticket(t)
            except Exception:  # noqa: BLE001
                pass
            _journal({"event": "cancelled", "ticket": tid, "why": "halted while orders were resting"})
        return {"cancelled": len(open_)}
    broker.quotes(sorted({o["symbol"] for o in open_}))
    changed = broker.settle(now)
    if not changed:
        return {"filled": 0, "still_resting": len(broker.open_orders())}
    by: dict[str, list] = {}
    for o in changed:
        by.setdefault(o["client_id"].rsplit("-", 1)[0], []).append(o)
    out = {"filled": 0, "tickets": [], "still_resting": len(broker.open_orders())}
    for tid, orders in sorted(by.items()):
        done = [o for o in orders if o["status"] == "filled"]
        fills = _paper_fill_rows(done)
        t = ex.load_ticket(tid)
        still = any(x["client_id"].rsplit("-", 1)[0] == tid for x in broker.open_orders())
        if fills:
            rec = ex.record_fills(tid, fills, now, at_close=True)
        else:
            rec = {"status": "unfilled", "issues": [o.get("reason", o["status"]) for o in orders]}
            if not still:
                t["status"] = "unfilled"; ex._save_ticket(t)
        account = broker.account()
        _mark_equity(account, now)
        c = t.get("call") or {}
        _journal({"event": "executed" if fills else "unfilled", "ticket": tid, "fills": len(fills), "failures": len(orders) - len(done), "status": rec.get("status"), "mandate_hash": M.hash(),
                  "broker": getattr(broker, "name", "?"), "mode": M.mode, "approval": "autonomous" if M.mode == "autonomous" else "approved",
                  "equity_after": account.get("equity"), "decision_id": c.get("decision_id"), "decision_ts": c.get("decision_ts"),
                  "ordered": min((o["placed"] for o in orders), default=None), "fill_session": min((o["fill_session"] for o in done), default=None),
                  "filled_at": min((o["filled"] for o in done), default=None), "marks_asof": account.get("marks_asof"),
                  "outside_limit": sum(1 for o in done if o.get("inside_limit") is False)})
        out["filled"] += len(fills)
        out["tickets"].append({"ticket": tid, "fills": len(fills), "status": rec.get("status"), "fill_session": min((o["fill_session"] for o in done), default=None)})
    return out


# ---------------------------------------------------------------- one pass
def run_once(broker, M: md.Mandate | None = None, P: ex.TradingParams | None = None, now: datetime | None = None, force_window: bool = False,
             call: dict | None = None, poll_seconds: float = 2.0, max_wait_seconds: float = 600.0) -> dict:
    """One pass of the trader. Returns a report that says exactly what happened and why it stopped where it did."""
    from . import book as bk
    now = now or datetime.now(timezone.utc)
    M = M or md.load()
    P = P or ex.load_params()
    rep: dict = {"ts_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "broker": getattr(broker, "name", "?"), "mode": M.mode, "armed": M.armed, "mandate_hash": M.hash(), "steps": []}

    def keep() -> None:
        """A paper account's marks and equity point are saved on every pass (v0.42.5). Before, they were written
        only when an order was placed, so on a day with nothing to trade the public equity path did not advance."""
        if getattr(broker, "fills_at_close", False) and hasattr(broker, "save"):
            try:
                broker.mark()
                broker.save()
            except Exception:  # noqa: BLE001 - the pass's own outcome is what matters
                pass

    def stop(why: str, **kw) -> dict:
        keep()
        rep.update({"outcome": why, **kw})
        _journal({"event": "pass", "outcome": why, "broker": rep["broker"], **{k: v for k, v in kw.items() if k in ("ticket", "reasons")}})
        return rep

    if M.problems():
        return stop("mandate unusable", reasons=M.problems())
    h = ex.halted()
    if hasattr(broker, "clock"):
        broker.clock = lambda: now                      # one clock for the pass: the broker stamps orders with the trader's time
    if getattr(broker, "fills_at_close", False):        # v0.47: a correction that is due is booked before anything else reads the account
        try:
            cx = _apply_corrections(broker, now)
            if cx:
                rep["corrections"] = cx
        except Exception as exc:  # noqa: BLE001 - both steps are safe to repeat; the next pass tries again
            rep["corrections_error"] = str(exc)[:200]
    if getattr(broker, "fills_at_close", False):        # v0.42.5: yesterday's resting orders meet their close first
        try:
            rc = _reconcile_paper(broker, now, M)       # v0.44.1: and before that, anything a dead pass left unrecorded
            if rc:
                rep["reconciled"] = rc
            st = _settle_resting(broker, now, M, cancel=bool(h))
        except Exception as exc:  # noqa: BLE001
            return stop("broker error settling resting orders", reasons=[str(exc)])
        if st:
            rep["settled"] = st
    if h:
        return stop("halted", reasons=[h])
    if getattr(broker, "fills_at_close", False) and broker.open_orders():
        o = broker.open_orders()
        return stop("orders resting until the close", reasons=[f"{len(o)} order(s) fill at the close of {min(x.get('fills_in_session', '?') for x in o)}"])
    ok, why = md.in_window(M, now)
    rep["steps"].append({"window": why})
    if not ok and not force_window:
        return stop("outside the window", reasons=[why])
    # an executed or staged ticket today?
    today = now.date().isoformat()
    todays = ex._tickets_on(today)
    done = [t for t in todays if t.get("status") in ("filled", "partially_filled")]
    if done:
        return stop("already traded today", ticket=done[-1]["id"])
    handed = [t for t in todays if t.get("status") == "handed_off" and t.get("expires", "") > now.strftime("%Y-%m-%dT%H:%M:%SZ")]
    if handed:                                          # v0.44.1: the same orders are never handed over twice
        return stop("already handed to the assistant", ticket=handed[-1]["id"],
                    reasons=["record its fills with record_fills, or wait for the ticket to expire"])
    # the account
    try:
        account = broker.account()
    except Exception as exc:  # noqa: BLE001
        return stop("broker error reading the account", reasons=[str(exc)])
    hist = _equity_history(before=today)
    _mark_equity(account, now)
    rep["account"] = {"equity": account.get("equity"), "cash": account.get("cash"), "positions": len(account.get("positions") or [])}
    # the recommendation and the quotes
    # v0.47: the call to trade is the one that governs the first session the position is held through. A paper order
    # fills at the close of its session and is held through the next, which is the day the live record marks the
    # same call; before, the pass planned on the call in force on the day of the pass, one session behind the record
    # (and two entries behind on a Saturday). A live order fills now and is held through today.
    held_session = today
    if getattr(broker, "fills_at_close", False):
        from . import sessions
        held_session = sessions.next_session(sessions.session_of_close_after(now)).isoformat()
    rep["steps"].append({"held_session": held_session})
    call = call or ex.call_in_force(held_session, now=now)
    if call is None:
        return stop("no call in force today", reasons=[f"the ledger holds no call that governs {held_session}"])
    T = ex.target(call, P, dict(bk.BOOK))
    symbols = sorted(set(T["weights"]) | {p["symbol"] for p in account.get("positions") or []})
    try:
        quotes = broker.quotes(symbols)
    except Exception as exc:  # noqa: BLE001
        return stop("broker error reading quotes", reasons=[str(exc)])
    missing = [s for s in symbols if s not in quotes]
    if missing:
        return stop("no quote for a symbol the ticket needs", reasons=missing)
    # v0.44.1: the account again at the quotes just read; before, equity (and the plan's check against cash plus
    # positions, the targets and the halts) used the previous pass's marks
    try:
        account = broker.account()
    except Exception as exc:  # noqa: BLE001
        return stop("broker error reading the account", reasons=[str(exc)])
    _mark_equity(account, now)
    rep["account"] = {"equity": account.get("equity"), "cash": account.get("cash"), "positions": len(account.get("positions") or [])}
    # a staged ticket from an earlier pass today, still valid? else plan a new one
    # v0.47: the newest staged ticket that has not expired and was planned on this call. Before, the last by file
    # name (a hash) was taken, so an expired ticket could hide a valid, approved one planned after it; and a ticket
    # planned on another call was reused as it stood. One that has expired or been overtaken is marked, once.
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    ticket = None
    for t in sorted((t for t in todays if not t.get("status") and t.get("all_checks_pass")), key=lambda t: str(t.get("created", ""))):
        tc = t.get("call") or {}
        if str(t.get("expires", "")) <= stamp:
            t["status"] = "expired"
            _journal({"event": "expired", "ticket": t["id"]})
        elif not _same_call(tc, call):
            t["status"] = "superseded"
            _journal({"event": "superseded", "ticket": t["id"],
                      "why": f"planned on the call on data through {tc.get('asof')} at {tc.get('size')}x; the call to trade now is on data through {call.get('asof')} at {call.get('size')}x"})
        else:
            ticket = t                                   # sorted by creation: the last kept is the newest
            continue
        ex._save_ticket(t)
    if ticket is None:
        ticket = ex.plan(account, quotes, call=call, P=P, today=today, now=now, held_session=held_session)
        ex._save_ticket(ticket)
        rep["steps"].append({"planned": ticket["id"], "orders": len(ticket["orders"]), "checks_pass": ticket["all_checks_pass"]})
    rep["ticket"] = ticket["id"]
    if not ticket["all_checks_pass"]:
        failed = [c["check"] for c in ticket["checks"] if not c["pass"]]
        return stop("the ticket failed a check", reasons=failed)
    if not ticket["orders"]:
        return stop("nothing to trade: holdings are within the drift band")
    auth = md.authorize(ticket, account, M, hist, now)
    rep["authorization"] = auth
    if not auth["ok"]:
        return stop("outside the mandate", reasons=auth["reasons"])
    # live routes: armed, and manual until the evidence is in (v0.42.4)
    live = getattr(broker, "name", "") != "paper"
    mode = M.mode
    if live and not M.armed:
        return stop("not armed: staged only", reasons=["a live broker needs armed = true in the signed mandate, in every mode"])
    if live and mode != "manual":
        ev = evidence()
        rep["gate"] = ev
        if not ev["open"]:
            mode = "manual"
            rep["steps"].append({"gate": f"the mandate says {M.mode}; live trading is manual until the evidence is in: " + "; ".join(ev["missing"])})
    # the mode gate
    approval = "autonomous"
    if mode in ("manual", "supervised"):
        okd, why, approval = _approved(ticket["id"], M, now, mode)
        if not okd:
            gated = [f"gate: {m}" for m in (rep.get("gate") or {}).get("missing", [])] if mode != M.mode else []
            return stop("staged, awaiting approval" if mode == "manual" else "staged, awaiting approval or a standing approval", reasons=[why] + gated,
                        approve_with=f"python -m buildout trader --approve {ticket['id']}" + ("" if mode == "manual" else "  (or --standing 120)"))
        rep["steps"].append({"approval": why})
    else:
        rep["steps"].append({"approval": "autonomous under the mandate"})
    how = {"broker": getattr(broker, "name", "?"), "mode": mode, "approval": approval}
    if getattr(broker, "name", "") == "assistant":
        for o in ticket["orders"]:
            broker.place(o["symbol"], o["side"], o["quantity"], o["limit_price"], f"{ticket['id']}-{o['seq']}")
        t = ex.load_ticket(ticket["id"])
        t["status"] = "handed_off"
        ex._save_ticket(t)
        _journal({"event": "handoff", "ticket": ticket["id"], "orders": len(ticket["orders"]), **how})
        return stop("handed to the assistant", handoff=broker.handoff, record_with="record_fills(ticket_id, fills) once Robinhood reports them")
    # execute: sells first, then buys
    fills, failures, resting = [], [], []
    for side in ("sell", "buy"):
        batch = [o for o in ticket["orders"] if o["side"] == side]
        if not batch:
            continue
        if side == "buy":                     # v0.42.3: the buys must be funded by what the sells actually raised
            try:
                cash_now = float(broker.account().get("cash") or 0)
            except Exception as exc:  # noqa: BLE001
                failures.append({"symbol": "*", "side": "buy", "error": f"could not re-read cash before the buys: {exc}"})
                break
            need = sum(float(o["quantity"]) * float(o["limit_price"]) for o in batch)
            if need > cash_now + 1e-6:
                failures.append({"symbol": "*", "side": "buy", "error": f"the buys need {need:,.2f} and the account holds {cash_now:,.2f} after the sells; no buy sent"})
                break
        placed = []
        unknown = False
        for o in batch:
            try:
                placed.append((o, broker.place(o["symbol"], o["side"], o["quantity"], o["limit_price"], f"{ticket['id']}-{o['seq']}")))
            except Exception as exc:  # noqa: BLE001
                failures.append({"symbol": o["symbol"], "side": side, "error": str(exc), "unknown": type(exc).__name__ == "OrderUnknown"})
                if type(exc).__name__ == "OrderUnknown":
                    unknown = True            # an order that may be live: send nothing more until it is resolved
                    break
        if getattr(broker, "fills_at_close", False):
            resting += [(o, od) for o, od in placed if od.get("status") == "open"]
            if (side == "sell" and failures) or unknown:
                break
            continue
        deadline = min(time.time() + max_wait_seconds, _epoch(ticket["expires"]))
        for o, od in placed:
            st = od
            while st.get("status") not in ("filled", "cancelled", "rejected", "failed") and time.time() < deadline:
                time.sleep(poll_seconds)
                st = broker.order(od["order_id"])
            if st.get("status") not in ("filled", "cancelled", "rejected", "failed") and st.get("status") != "filled":
                try:
                    st = {**st, **broker.cancel(od["order_id"])}
                except Exception as exc:  # noqa: BLE001
                    failures.append({"symbol": o["symbol"], "side": side, "error": f"cancel: {exc}"})
                try:                                    # v0.44.1: what filled before (or during) the cancel is still a fill
                    st = {**st, **broker.order(od["order_id"])}
                except Exception as exc:  # noqa: BLE001
                    failures.append({"symbol": o["symbol"], "side": side, "error": f"order state after cancel unknown: {exc}", "unknown": True})
            fq = float(st.get("filled_qty") or (o["quantity"] if st.get("status") == "filled" else 0))
            if fq > 0:
                fills.append({"symbol": o["symbol"], "side": side, "quantity": fq, "price": float(st.get("avg_price") or o["limit_price"]), "order_id": od["order_id"], "status": st.get("status", "filled")})
            elif st.get("status") in ("rejected", "failed"):
                failures.append({"symbol": o["symbol"], "side": side, "error": st.get("status")})
        if (side == "sell" and failures) or unknown:
            break                                                         # buys are funded by the sells; a failed sell stops the buys
    if resting and not fills:                           # v0.42.5: nothing has filled, and nothing is claimed to have
        t = ex.load_ticket(ticket["id"])
        t["status"] = "working"
        ex._save_ticket(t)
        session = min(od.get("fills_in_session", "?") for _, od in resting)
        _journal({"event": "resting", "ticket": ticket["id"], "orders": len(resting), "failures": len(failures), "fills_in_session": session, "mandate_hash": M.hash(), **how,
                  "decision_id": (ticket.get("call") or {}).get("decision_id"), "decision_ts": (ticket.get("call") or {}).get("decision_ts"), "ordered": rep["ts_utc"]})
        rep.update({"resting": [{"symbol": o["symbol"], "side": o["side"], "quantity": o["quantity"], "fills_in_session": od.get("fills_in_session")} for o, od in resting],
                    "failures": failures, "outcome": "orders resting until the close", "fills_in_session": session})
        _digest(rep, M)
        keep()
        return rep
    rec = ex.record_fills(ticket["id"], fills, now) if fills else {"status": "unfilled", "issues": []}
    if not fills:
        t = ex.load_ticket(ticket["id"])
        t["status"] = "unfilled"
        ex._save_ticket(t)
    account_after = broker.account()
    _mark_equity(account_after, now)
    rep.update({"fills": fills, "failures": failures, "recorded": rec, "account_after": {"equity": account_after.get("equity"), "cash": account_after.get("cash")}})
    _journal({"event": "executed" if fills else "unfilled", "ticket": ticket["id"], "fills": len(fills), "failures": len(failures), "status": rec.get("status"), "mandate_hash": M.hash(), **how,
              "equity_after": account_after.get("equity")})
    _digest(rep, M)
    keep()
    rep["outcome"] = "executed" if fills else "unfilled"
    return rep


def _same_call(tc: dict, call: dict) -> bool:
    """Was a staged ticket planned on the call the pass would trade now? The data date and the size must match, and
    the ledger entry's id where both carry one."""
    if tc.get("asof") != call.get("asof"):
        return False
    try:
        if abs(float(tc.get("size")) - float(call.get("size"))) > 1e-9:
            return False
    except (TypeError, ValueError):
        return False
    return not (tc.get("decision_id") and call.get("decision_id") and tc["decision_id"] != call["decision_id"])


def _epoch(stamp: str) -> float:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def _digest(rep: dict, M: md.Mandate) -> None:
    p = ROOT / M.digest_path if not os.path.isabs(M.digest_path) else Path(M.digest_path)
    if os.environ.get("BUILDOUT_TRADER_STATE"):
        p = _tdir() / "digest.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"## {rep['ts_utc']}  ticket {rep.get('ticket')}  ({rep['mode']}, {rep['broker']})", ""]
    for f in rep.get("fills", []):
        lines.append(f"- {f['side']} {f['quantity']:g} {f['symbol']} at {f['price']:.2f} (order {f['order_id']})")
    for f in rep.get("resting", []):
        lines.append(f"- RESTING {f['side']} {f['quantity']:g} {f['symbol']}: fills at the close of {f.get('fills_in_session')}")
    for f in rep.get("failures", []):
        lines.append(f"- FAILED {f['side']} {f['symbol']}: {f['error']}")
    a = rep.get("account_after") or {}
    lines += ["", (f"Equity after: {a.get('equity')}; cash {a.get('cash')}. " if a else "Nothing has filled yet. ") + f"Mandate {rep['mandate_hash']}.", ""]
    with p.open("a") as fh:
        fh.write("\n".join(lines) + "\n")


def loop(broker, every_minutes: int = 15, M: md.Mandate | None = None, P: ex.TradingParams | None = None, max_passes: int | None = None) -> list[dict]:
    """run_once on a timer until the halt file appears, Ctrl-C, or max_passes."""
    out = []
    n = 0
    while True:
        rep = run_once(broker, M, P)
        out.append(rep)
        print(f"{rep['ts_utc']}  {rep['outcome']}" + (f"  {rep.get('reasons')}" if rep.get("reasons") else ""))
        n += 1
        if ex.halted() or (max_passes and n >= max_passes):
            break
        try:
            time.sleep(every_minutes * 60)
        except KeyboardInterrupt:
            break
    return out


# ---------------------------------------------------------------- the paper bot (public)
def paper_quote_fn(cache: str | Path | None = None):
    """Quotes for the paper broker from the validated price mirror: the last close with a 5 bp half-spread, and the
    last twelve closes by date so a resting order fills at the close of its own session."""
    from . import book as bk

    def fn(symbols: list[str]) -> dict:
        prices = bk.download(cache=Path(cache) if cache else None)
        out = {}
        for s in symbols:
            f = bk.FILE.get(s, s.lower())
            df = prices.get(f)
            if df is None or not len(df):
                continue
            last = float(df["close"].iloc[-1])
            tail = df.tail(12)
            out[s] = {"bid": last * (1 - 0.0005), "ask": last * (1 + 0.0005), "last": last, "asof": str(df["date"].iloc[-1])[:10],
                      "closes": {str(d)[:10]: float(c) for d, c in zip(tail["date"], tail["close"])}}      # v0.42.5: a resting order needs its own session's close
        return out
    return fn


def paper_summary(state_dir: str | Path) -> dict:
    """The public paper record for the page: equity path, holdings, the journal, today's outcome, and (v0.42.5) each
    filled ticket's four times in order with the convention it was filled under."""
    from .broker import PaperBroker
    sd = Path(state_dir)
    prev = os.environ.get("BUILDOUT_TRADER_STATE")
    os.environ["BUILDOUT_TRADER_STATE"] = str(sd)
    try:
        pb = PaperBroker(sd / "paper_account.json")
        acct = pb.account()
        j = [r for r in journal(2000) if r.get("event") in ("executed", "unfilled", "pass", "handoff", "resting", "cancelled", "correction")]
        fills = ex._fills()
        chain = ex.verify_fills()
        recon = paper_reconcile(pb.state)
    finally:
        if prev is None:
            os.environ.pop("BUILDOUT_TRADER_STATE", None)
        else:
            os.environ["BUILDOUT_TRADER_STATE"] = prev
    opened = str(pb.state.get("opened") or "")
    orders = list(pb.state.get("orders", {}).values())
    old = [o for o in orders if o.get("status") == "filled" and o.get("type") != "market_on_close"]
    # v0.47: the corrections booked against the record, from the chained log (the account's marker adds nothing the
    # record does not carry), in plain words for the page
    corrections = [{"id": e.get("id"), "applied": e.get("ts_utc"), "amount": e.get("amount"), "cash_delta": e.get("cash_delta"), "ticket": e.get("corrects"),
                    "session": e.get("session"), "equity_before": e.get("equity_before"), "equity_after": e.get("equity_after"),
                    "first_corrected_mark": e.get("first_corrected_mark"), "reason": e.get("reason"), "detail": e.get("detail") or [],
                    "summary": (f"${float(e.get('amount') or 0):,.2f} {'taken from' if float(e.get('cash_delta') or 0) <= 0 else 'added to'} cash on {str(e.get('ts_utc', ''))[:10]}: "
                                f"ticket {e.get('corrects')} repriced at the {e.get('session')} close under the current fill rule.")}
                   for e in fills if e.get("kind") == "correction"]
    by_ticket = {c["ticket"]: c for c in corrections}
    timeline = []
    for e in fills:
        if e.get("status") not in ("filled", "partially_filled"):
            continue
        ex_ev = next((r for r in reversed(j) if r.get("event") == "executed" and r.get("ticket") == e.get("ticket")), {})
        at_close = bool(e.get("convention"))
        c = by_ticket.get(e.get("ticket"))
        timeline.append({"ticket": e.get("ticket"), "fills": len(e.get("fills", [])), "status": e.get("status"),
                         "decision_id": ex_ev.get("decision_id"), "decision_ts": ex_ev.get("decision_ts"), "ordered": ex_ev.get("ordered"),
                         "fill_session": ex_ev.get("fill_session"), "filled_at": ex_ev.get("filled_at"), "recorded": e.get("ts_utc"),
                         "outside_limit": ex_ev.get("outside_limit"),
                         "convention": "close of the order's session" if at_close else "limit against the previous close (before v0.42.5)", "causal": at_close,
                         **({"corrected_by": c["id"], "correction_amount": c["amount"]} if c else {})})
    history = [h for h in pb.state.get("equity_history", []) if not opened or h[0] >= opened]
    # the path as it would read had each correction been in the account from the start: every mark dated before the
    # first one that already carries a correction moves by that correction's cash
    corrected = [[h[0], None if h[1] is None else
                  round(float(h[1]) + sum(float(c["cash_delta"] or 0) for c in corrections if c.get("first_corrected_mark") and h[0] < c["first_corrected_mark"]), 2)]
                 for h in history]
    return {"schema": 2, "opened": opened, "start_cash": pb.state.get("start_cash"), "equity": acct["equity"], "cash": acct["cash"], "marks_asof": acct.get("marks_asof"),
            "positions": acct["positions"], "equity_history": history,
            "corrections": corrections, "equity_history_corrected": corrected if corrections else history, "reconcile": recon,
            "pre_inception_marks": pb.state.get("pre_inception_marks", []),
            "tickets_filled": sum(1 for e in fills if e.get("status") in ("filled", "partially_filled")),
            "resting": [{"symbol": o["symbol"], "side": o["side"], "quantity": o["quantity"], "ordered": o["placed"], "fills_in_session": o.get("fills_in_session")} for o in orders if o.get("status") == "open"],
            "timeline": timeline, "non_causal_fills": len(old),
            "fills_chain": chain, "passes": len(j), "last": j[-1] if j else None, "recent": j[-12:],
            "mode": "paper, autonomous, unhedged, no VIX sleeve (PSQ and VIXY are not in the price mirror)",
            "convention": {"order": "written by the daily pass, which has started during the US session on every day so far (the ticket carries the time)", "fill": "the close of the first exchange session that ends after the order was written",
                           "cost": "5 bp half-spread on every fill; no commission", "limit": "the ticket's limit is recorded; the paper fill does not depend on it",
                           "since": "v0.42.5"},
            "note": ("A model account of $100,000 run by the trader from the daily workflow. Each order rests until the close of the first exchange session that ends after it was "
                     "written and fills at that close with a 5 bp half-spread, so the price is never older than the order. "
                     + (f"The first {len(old)} fills (written Nov 11, 2026) were made under the earlier convention, at the limit against the previous day's close: a price older than the order. They are kept as recorded and marked. " if old else "")
                     + "".join(f"Correction: {c['summary']} Equity marks dated before {c.get('first_corrected_mark') or 'it'} do not carry it. " for c in corrections)
                     + "A simulation convention, not evidence of an achievable execution. Not a personal account.")}
