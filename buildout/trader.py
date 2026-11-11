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
    call = ex.latest_call()
    T = ex.target(call, P, dict(bk.BOOK))
    out = {"asof": call.get("asof"), "effective_from": call.get("effective_from") or _effective(call), "size": call.get("size"), "binding": call.get("binding"),
           "menu_high": call.get("keep_names_hedge") or call.get("menu_high"), "variant": P.variant, "target_weights": {k: round(v, 4) for k, v in T["weights"].items()},
           "book_gross": round(T["book_gross"], 4), "index_short_as_psq": round(T["short"], 4), "vix_sleeve": round(T["vix"], 4),
           "mandate": {"mode": M.mode, "armed": M.armed, "broker": M.broker, "hash": M.hash(), "problems": M.problems()},
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


def _approved(tid: str, M: md.Mandate, now: datetime) -> tuple[bool, str]:
    A = _approvals()
    a = A.get(tid)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if a:
        given = datetime.strptime(a["given"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if (now - given) <= timedelta(minutes=M.approval_ttl_min):
            return True, f"approved by {a.get('by') or 'the person'} at {a['given']}"
        return False, f"the approval of {a['given']} is older than the mandate's {M.approval_ttl_min} minutes"
    s = A.get("standing")
    if s and M.mode == "supervised" and s["until"] >= stamp:
        return True, f"standing approval until {s['until']}"
    return False, "no approval on file"


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
    if rows and rows[-1]["date"] == day:
        rows[-1]["equity"] = float(account["equity"])
    else:
        rows.append({"date": day, "equity": float(account["equity"])})
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


# ---------------------------------------------------------------- one pass
def run_once(broker, M: md.Mandate | None = None, P: ex.TradingParams | None = None, now: datetime | None = None, force_window: bool = False,
             call: dict | None = None, poll_seconds: float = 2.0, max_wait_seconds: float = 600.0) -> dict:
    """One pass of the trader. Returns a report that says exactly what happened and why it stopped where it did."""
    from . import book as bk
    now = now or datetime.now(timezone.utc)
    M = M or md.load()
    P = P or ex.load_params()
    rep: dict = {"ts_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "broker": getattr(broker, "name", "?"), "mode": M.mode, "armed": M.armed, "mandate_hash": M.hash(), "steps": []}

    def stop(why: str, **kw) -> dict:
        rep.update({"outcome": why, **kw})
        _journal({"event": "pass", "outcome": why, "broker": rep["broker"], **{k: v for k, v in kw.items() if k in ("ticket", "reasons")}})
        return rep

    if M.problems():
        return stop("mandate unusable", reasons=M.problems())
    h = ex.halted()
    if h:
        return stop("halted", reasons=[h])
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
    call = call or ex.latest_call()
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
    # the mode gate
    if M.mode == "manual":
        okd, why = _approved(ticket["id"], M, now)
        if not okd:
            return stop("staged, awaiting approval", reasons=[why], approve_with=f"python -m buildout trader --approve {ticket['id']}")
        rep["steps"].append({"approval": why})
    elif M.mode == "supervised":
        okd, why = _approved(ticket["id"], M, now)
        if not okd:
            return stop("staged, awaiting approval or a standing approval", reasons=[why], approve_with=f"python -m buildout trader --approve {ticket['id']}  (or --standing 120)")
        rep["steps"].append({"approval": why})
    else:
        if not M.armed and getattr(broker, "name", "") != "paper":
            return stop("autonomous but not armed: staged only", reasons=["set armed = true in the signed mandate"])
        rep["steps"].append({"approval": "autonomous under the mandate"})
    if getattr(broker, "name", "") == "assistant":
        for o in ticket["orders"]:
            broker.place(o["symbol"], o["side"], o["quantity"], o["limit_price"], f"{ticket['id']}-{o['seq']}")
        _journal({"event": "handoff", "ticket": ticket["id"], "orders": len(ticket["orders"])})
        return stop("handed to the assistant", handoff=broker.handoff, record_with="record_fills(ticket_id, fills) once Robinhood reports them")
    # execute: sells first, then buys
    fills, failures = [], []
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
    rec = ex.record_fills(ticket["id"], fills, now) if fills else {"status": "unfilled", "issues": []}
    if not fills:
        t = ex.load_ticket(ticket["id"])
        t["status"] = "unfilled"
        ex._save_ticket(t)
    account_after = broker.account()
    _mark_equity(account_after, now)
    rep.update({"fills": fills, "failures": failures, "recorded": rec, "account_after": {"equity": account_after.get("equity"), "cash": account_after.get("cash")}})
    _journal({"event": "executed" if fills else "unfilled", "ticket": ticket["id"], "fills": len(fills), "failures": len(failures), "status": rec.get("status"), "mandate_hash": M.hash(),
              "equity_after": account_after.get("equity")})
    _digest(rep, M)
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
    for f in rep.get("failures", []):
        lines.append(f"- FAILED {f['side']} {f['symbol']}: {f['error']}")
    a = rep.get("account_after") or {}
    lines += ["", f"Equity after: {a.get('equity')}; cash {a.get('cash')}. Mandate {rep['mandate_hash']}.", ""]
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
    """Quotes for the paper broker from the validated price mirror: last close, with a 5 bp half-spread."""
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
            out[s] = {"bid": last * (1 - 0.0005), "ask": last * (1 + 0.0005), "last": last, "asof": str(df["date"].iloc[-1])[:10]}
        return out
    return fn


def paper_summary(state_dir: str | Path) -> dict:
    """The public paper record for the page: equity path, holdings, the journal, today's outcome."""
    from .broker import PaperBroker
    sd = Path(state_dir)
    prev = os.environ.get("BUILDOUT_TRADER_STATE")
    os.environ["BUILDOUT_TRADER_STATE"] = str(sd)
    try:
        pb = PaperBroker(sd / "paper_account.json")
        acct = pb.account()
        j = [r for r in journal(2000) if r.get("event") in ("executed", "unfilled", "pass", "handoff")]
        fills = ex._fills()
        chain = ex.verify_fills()
    finally:
        if prev is None:
            os.environ.pop("BUILDOUT_TRADER_STATE", None)
        else:
            os.environ["BUILDOUT_TRADER_STATE"] = prev
    return {"schema": 1, "opened": pb.state.get("opened"), "start_cash": pb.state.get("start_cash"), "equity": acct["equity"], "cash": acct["cash"], "marks_asof": acct.get("marks_asof"),
            "positions": acct["positions"], "equity_history": pb.state.get("equity_history", []), "tickets_filled": sum(1 for e in fills if e.get("status") in ("filled", "partially_filled")),
            "fills_chain": chain, "passes": len(j), "last": j[-1] if j else None, "recent": j[-12:],
            "mode": "paper, autonomous, unhedged, no VIX sleeve (PSQ and VIXY are not in the price mirror)",
            "note": "A model account of $100,000 run by the trader every weekday from the daily workflow, filled at the day's close plus a 5 bp half-spread. Not a personal account."}
