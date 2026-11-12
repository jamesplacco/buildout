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
                return r.get("effective_from")
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
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    return rows[-n:]


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
    (_tdir() / "approvals.json").write_text(json.dumps(A, indent=1))
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
PAPER_DAYS_REQUIRED = 60            # trading days the public paper bot has held a position, marked daily
LIVE_MANUAL_TICKETS_REQUIRED = 5    # live tickets filled after the person approved that ticket's id


def evidence(paper_dir: Path | None = None, private_dir: Path | None = None) -> dict:
    """Has unattended live trading been earned? Two records, both read from files the trader itself writes:
      1. the paper bot (paper/, committed by the daily run): days marked since its first filled ticket;
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

    pj = rows(paper_dir / "trader" / "journal.jsonl")
    first = min((r["ts_utc"][:10] for r in pj if r.get("event") == "executed"), default=None)
    paper_days = len({r["date"] for r in rows(paper_dir / "trader" / "equity.jsonl") if first and r.get("date", "") >= first})
    lj = rows(private_dir / "trader" / "journal.jsonl")
    approved = {r["ticket"] for r in lj if r.get("event") in ("executed", "handoff") and r.get("broker") not in (None, "paper") and r.get("approval") == "ticket"}
    filled = {r["ticket"] for r in rows(private_dir / "fills.jsonl") if r.get("status") in ("filled", "partially_filled")}
    live = len(approved & filled)
    missing = []
    if paper_days < PAPER_DAYS_REQUIRED:
        missing.append(f"the paper bot has {paper_days} of {PAPER_DAYS_REQUIRED} trading days with a position")
    if live < LIVE_MANUAL_TICKETS_REQUIRED:
        missing.append(f"{live} of {LIVE_MANUAL_TICKETS_REQUIRED} live tickets have filled under an approval of their own id")
    return {"open": not missing, "paper_days": paper_days, "paper_days_required": PAPER_DAYS_REQUIRED, "paper_first_fill": first,
            "live_manual_tickets": live, "live_manual_tickets_required": LIVE_MANUAL_TICKETS_REQUIRED, "missing": missing}


def _equity_history() -> dict:
    p = _tdir() / "equity.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
    out = {"peak_equity": max((r["equity"] for r in rows), default=None), "prev_equity": rows[-1]["equity"] if rows else None, "n": len(rows)}
    done = [r for r in journal(1000) if r.get("event") == "executed"]
    out["tickets_executed"] = len(done)
    out["last_ticket_date"] = done[-1]["ts_utc"][:10] if done else None
    return out


def _mark_equity(account: dict, now: datetime) -> None:
    p = _tdir() / "equity.jsonl"
    day = now.date().isoformat()
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
    row = {"date": day, "equity": float(account["equity"]), **({"marks_asof": account["marks_asof"]} if account.get("marks_asof") else {})}
    if rows and rows[-1]["date"] == day:
        rows[-1] = row
    else:
        rows.append(row)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


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
        fills = [{"symbol": o["symbol"], "side": o["side"], "quantity": o["filled_qty"], "price": o["avg_price"], "order_id": o["order_id"], "status": "filled",
                  "session": o["fill_session"], "filled": o["filled"], "ordered": o["placed"], "inside_limit": o.get("inside_limit")} for o in done]
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
    if getattr(broker, "fills_at_close", False):        # v0.42.5: yesterday's resting orders meet their close first
        try:
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
    # the account
    try:
        account = broker.account()
    except Exception as exc:  # noqa: BLE001
        return stop("broker error reading the account", reasons=[str(exc)])
    _mark_equity(account, now)
    hist = _equity_history()
    rep["account"] = {"equity": account.get("equity"), "cash": account.get("cash"), "positions": len(account.get("positions") or [])}
    # the recommendation and the quotes
    call = call or ex.call_in_force(today)
    if call is None:
        return stop("no call in force today", reasons=["the ledger holds no call whose effective date has come"])
    T = ex.target(call, P, dict(bk.BOOK))
    symbols = sorted(set(T["weights"]) | {p["symbol"] for p in account.get("positions") or []})
    try:
        quotes = broker.quotes(symbols)
    except Exception as exc:  # noqa: BLE001
        return stop("broker error reading quotes", reasons=[str(exc)])
    missing = [s for s in symbols if s not in quotes]
    if missing:
        return stop("no quote for a symbol the ticket needs", reasons=missing)
    # a staged ticket from an earlier pass today, still valid? else plan a new one
    staged = [t for t in todays if not t.get("status") and t.get("all_checks_pass")]
    ticket = None
    if staged:
        t = staged[-1]
        if t["expires"] > now.strftime("%Y-%m-%dT%H:%M:%SZ"):
            ticket = t
        else:
            _journal({"event": "expired", "ticket": t["id"]})
    if ticket is None:
        ticket = ex.plan(account, quotes, call=call, P=P, today=today, now=now)
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
            continue
        deadline = min(time.time() + max_wait_seconds, _epoch(ticket["expires"]))
        for o, od in placed:
            st = od
            while st.get("status") not in ("filled", "cancelled", "rejected", "failed") and time.time() < deadline:
                time.sleep(poll_seconds)
                st = broker.order(od["order_id"])
            if st.get("status") not in ("filled", "cancelled", "rejected", "failed") and st.get("status") != "filled":
                try:
                    st = broker.cancel(od["order_id"])
                except Exception as exc:  # noqa: BLE001
                    failures.append({"symbol": o["symbol"], "side": side, "error": f"cancel: {exc}"})
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
        j = [r for r in journal(2000) if r.get("event") in ("executed", "unfilled", "pass", "handoff", "resting", "cancelled")]
        fills = ex._fills()
        chain = ex.verify_fills()
    finally:
        if prev is None:
            os.environ.pop("BUILDOUT_TRADER_STATE", None)
        else:
            os.environ["BUILDOUT_TRADER_STATE"] = prev
    opened = str(pb.state.get("opened") or "")
    orders = list(pb.state.get("orders", {}).values())
    old = [o for o in orders if o.get("status") == "filled" and o.get("type") != "market_on_close"]
    timeline = []
    for e in fills:
        if e.get("status") not in ("filled", "partially_filled"):
            continue
        ex_ev = next((r for r in reversed(j) if r.get("event") == "executed" and r.get("ticket") == e.get("ticket")), {})
        at_close = bool(e.get("convention"))
        timeline.append({"ticket": e.get("ticket"), "fills": len(e.get("fills", [])), "status": e.get("status"),
                         "decision_id": ex_ev.get("decision_id"), "decision_ts": ex_ev.get("decision_ts"), "ordered": ex_ev.get("ordered"),
                         "fill_session": ex_ev.get("fill_session"), "filled_at": ex_ev.get("filled_at"), "recorded": e.get("ts_utc"),
                         "outside_limit": ex_ev.get("outside_limit"),
                         "convention": "close of the order's session" if at_close else "limit against the previous close (before v0.42.5)", "causal": at_close})
    return {"schema": 2, "opened": opened, "start_cash": pb.state.get("start_cash"), "equity": acct["equity"], "cash": acct["cash"], "marks_asof": acct.get("marks_asof"),
            "positions": acct["positions"], "equity_history": [h for h in pb.state.get("equity_history", []) if not opened or h[0] >= opened],
            "pre_inception_marks": pb.state.get("pre_inception_marks", []),
            "tickets_filled": sum(1 for e in fills if e.get("status") in ("filled", "partially_filled")),
            "resting": [{"symbol": o["symbol"], "side": o["side"], "quantity": o["quantity"], "ordered": o["placed"], "fills_in_session": o.get("fills_in_session")} for o in orders if o.get("status") == "open"],
            "timeline": timeline, "non_causal_fills": len(old),
            "fills_chain": chain, "passes": len(j), "last": j[-1] if j else None, "recent": j[-12:],
            "mode": "paper, autonomous, unhedged, no VIX sleeve (PSQ and VIXY are not in the price mirror)",
            "convention": {"order": "written by the daily pass, before the open on most days", "fill": "the close of the first exchange session that ends after the order was written",
                           "cost": "5 bp half-spread on every fill; no commission", "limit": "the ticket's limit is recorded; the paper fill does not depend on it",
                           "since": "v0.42.5"},
            "note": ("A model account of $100,000 run by the trader from the daily workflow. Each order rests until the close of the first exchange session that ends after it was "
                     "written and fills at that close with a 5 bp half-spread, so the price is never older than the order. "
                     + (f"The first {len(old)} fills (written Nov 11, 2026) were made under the earlier convention, at the limit against the previous day's close: a price older than the order. They are kept as recorded and marked. " if old else "")
                     + "A simulation convention, not evidence of an achievable execution. Not a personal account.")}
