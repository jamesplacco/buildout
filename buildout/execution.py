"""From the call to orders (v0.39): the engine's call turned into a hashed, risk-checked order ticket for a
Robinhood Agentic account, and the fills recorded back against it.

Buildout never places, routes or cancels an order and holds no brokerage credential. The orders go through
Robinhood's own Trading MCP (https://agent.robinhood.com/mcp/trading, OAuth, orders only in the separate Agentic
account), placed by the assistant after the person approves the ticket. This module does the two parts that must
not be left to judgment in the moment: what to trade, and whether it is allowed.

    plan(account, quotes)        target holdings, the orders to reach them, every check, a ticket id; nothing placed
    record_fills(ticket, fills)  fills checked against the ticket and appended to a hash-chained private log
    paper_fill(ticket)           in paper mode, fills the ticket at its limit prices in a private paper account (a
                                 rehearsal of the ticket's arithmetic, not a market simulation: the public paper bot
                                 uses broker.PaperBroker, whose orders fill at the next close)

What Robinhood's Agentic account allows (support pages read Nov 5, 2026): long stocks and ETFs; single-leg long
options; market, limit and stop orders; no margin borrowing, no short selling, no futures, no multi-leg options. So:
  - the book is held long, at the call's size, never above the account's equity (gross at most 98% of equity);
  - the Nasdaq-100 short becomes a long position in PSQ (ProShares Short QQQ, -1x daily, 0.95% a year);
  - the VIX sleeve is VIXY (long short-term VIX futures), the closest listed form of the hedge studied in vixhedge.py;
  - options are not used by the planner (VIX and Nasdaq-100 calls and puts are researched, not automated).

Private state lives in private/ (git-ignored): tickets, fills, the paper account, and the halt file.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "private"


def state_root() -> Path:
    """Where tickets, fills and the paper account live: private/ (git-ignored), or BUILDOUT_TRADER_STATE, which the
    public paper bot (v0.42) points at paper/ so its record is committed."""
    return Path(os.environ["BUILDOUT_TRADER_STATE"]) if os.environ.get("BUILDOUT_TRADER_STATE") else PRIVATE


HEDGE_LABEL = {"PSQ": "Nasdaq-100 short through an inverse ETF (the call's index short)", "VIXY": "VIX sleeve (short-term VIX futures ETF)"}


@dataclass
class TradingParams:
    mode: str = "paper"                 # paper | live: live tickets are marked executable; paper ones never are
    broker: str = "robinhood_agentic"
    variant: str = "unhedged"           # unhedged: the call's smallest size; hedged: the largest size the cash account allows with PSQ
    vix_share: float = 0.05             # VIX sleeve as a share of equity (0 turns it off)
    vix_symbol: str = "VIXY"
    short_symbol: str = "PSQ"
    max_gross: float = 0.98             # everything long, as a share of equity (no margin borrowing in the Agentic account)
    cash_floor: float = 0.02
    max_order_pct: float = 0.25         # one order at most this share of equity
    max_order_usd: float = 25_000.0
    max_turnover_pct: float = 0.60      # one ticket's total notional (a first build from cash may reach 100%)
    drift_band: float = 0.02            # leave a holding alone within this share of equity of its target
    min_trade_usd: float = 50.0
    collar_bp: float = 10.0             # limit price: ask plus 10 bp to buy, bid less 10 bp to sell
    max_spread_pct: float = 1.0
    ticket_ttl_min: int = 15
    max_tickets_per_day: int = 1
    max_data_age_bd: int = 3            # the call's data at most 3 business days old
    fractional: bool = False            # whole shares by default
    extra_allowed: list[str] = field(default_factory=list)


def load_params(path: str | Path | None = None) -> TradingParams:
    """[trading] from config.toml, then config.private.toml over it (both optional)."""
    import tomllib
    raw: dict = {}
    for p in ([Path(path)] if path else [ROOT / "config.toml", ROOT / "config.private.toml"]):
        if p.exists():
            raw.update(tomllib.loads(p.read_text()).get("trading", {}))
    known = set(TradingParams.__dataclass_fields__)
    return TradingParams(**{k: v for k, v in raw.items() if k in known})


def halted() -> str | None:
    if os.environ.get("BUILDOUT_TRADING_HALT"):
        return "BUILDOUT_TRADING_HALT is set"
    if (state_root() / "HALT").exists():
        return f"{state_root().name}/HALT exists"
    return None


def _bdays_between(a: str, b: str) -> int:
    """Exchange sessions after a, up to and including b (v0.42.5: holidays count as closed, not as stale days)."""
    from . import sessions
    return sessions.sessions_between(a, b)


def _canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)


def _sha(o) -> str:
    return hashlib.sha256(_canon(o).encode()).hexdigest()


def target(call: dict, P: TradingParams, weights: dict[str, float]) -> dict:
    """Target shares of equity by symbol: the book at the chosen size, the PSQ short sleeve, the VIX sleeve."""
    vix = max(0.0, float(P.vix_share))
    room = P.max_gross - vix
    fr = [r for r in (call.get("frontier") or []) if r.get("meets", True) and r.get("short") is not None and r.get("gross") is not None]
    fr = sorted(fr or [{"gross": call["size"], "short": 0.0}], key=lambda r: r["gross"])      # rows that meet every limit only
    g, h = float(fr[0]["gross"]), float(fr[0].get("short") or 0.0)
    if P.variant == "hedged":
        for a, b in zip(fr, fr[1:]):                    # walk the frontier while book + short fits the cash account
            if b["gross"] + b["short"] <= room:
                g, h = float(b["gross"]), float(b["short"])
                continue
            da, db = a["gross"] + a["short"], b["gross"] + b["short"]
            if da <= room < db:                          # the point on the segment where it just fits
                t = (room - da) / (db - da)
                g, h = a["gross"] + t * (b["gross"] - a["gross"]), a["short"] + t * (b["short"] - a["short"])
            break
    if g > room:                                         # the call itself does not fit beside the VIX sleeve: the sleeve gives way
        vix = max(0.0, P.max_gross - g)
    if g + h + vix > P.max_gross:                        # a call above what a cash account can hold is held at the most it can
        g = max(0.0, P.max_gross - h - vix)
    tw = {k: g * w for k, w in weights.items()}
    if h > 1e-6:
        tw[P.short_symbol] = h
    if vix > 1e-6:
        tw[P.vix_symbol] = vix
    return {"book_gross": g, "short": h, "vix": vix, "weights": tw, "variant": P.variant,
            "note": "PSQ is a daily-reset inverse ETF, close to but not the same as a futures short; VIXY carries the VIX futures roll cost."}


def latest_call() -> dict:
    """The freshest call: the daily run's site/data/book.json when it is newer than the page's snapshot."""
    from . import ledger
    snap = ledger._snap_book()
    p = ROOT / "site" / "data" / "book.json"
    if p.exists():
        try:
            d = json.loads(p.read_text())
            if d.get("asof", "") > snap.get("asof", "") and d.get("frontier"):
                return d
        except (json.JSONDecodeError, OSError):
            pass
    return snap


def call_in_force(today: str | None = None) -> dict | None:
    """The call a trade may act on today (v0.42.4): the newest ledger entry whose effective date has come. Each day's
    call takes effect on the next trading day, so the newest call (latest_call) is never the one in force on the day
    it is written; trading it was refused every day. Rebuilt from the ledger entry, with its two-point menu as the
    frontier the hedged variant walks. None when the ledger holds no entry in force."""
    from . import ledger
    today = today or datetime.now(timezone.utc).date().isoformat()
    rows = [e for e in ledger.read() if e.get("effective_from", "9999") <= today]
    if not rows:
        return None
    e = max(rows, key=lambda r: (r["effective_from"], r["seq"]))
    c = e.get("call", {})
    frontier = [{"gross": m["gross"], "short": m.get("short", 0.0), "meets": True} for m in (c.get("menu_low"), c.get("menu_high")) if isinstance(m, dict) and m.get("gross") is not None]
    return {"asof": e.get("data_asof"), "effective_from": e["effective_from"], "size": c.get("size"), "binding": c.get("binding"), "frontier": frontier,
            "menu_high": c.get("menu_high"), "ledger_seq": e["seq"], "source": f"ledger entry {e['seq']}",
            "decision_id": decision_id(e), "decision_ts": e.get("ts_utc")}


def decision_id(entry: dict) -> str:
    """One name for one decision on every surface (v0.42.5): the ledger entry's number and the head of its hash."""
    return f"{entry['seq']}-{str(entry.get('hash', ''))[:8]}"


def plan(account: dict, quotes: dict, call: dict | None = None, P: TradingParams | None = None, weights: dict | None = None,
         today: str | None = None, ledger_check: dict | None = None, now: datetime | None = None) -> dict:
    """The ticket. `account`: {"equity": .., "cash": .., "account_type": "agentic", "positions": [{"symbol", "quantity"}]}.
    `quotes`: {symbol: {"bid": .., "ask": .., "last": ..}}. Nothing here places an order."""
    from . import book as bk
    from . import ledger
    P = P or load_params()
    call = call or call_in_force(today) or latest_call()
    weights = weights or dict(bk.BOOK)
    now = now or datetime.now(timezone.utc)
    today = today or now.date().isoformat()
    eq = float(account.get("equity") or 0.0)
    cash = float(account.get("cash") or 0.0)
    held = {str(p["symbol"]).upper(): float(p["quantity"]) for p in account.get("positions", []) if float(p.get("quantity", 0)) != 0}
    Q = {str(k).upper(): v for k, v in (quotes or {}).items()}
    T = target(call, P, weights)
    allowed = set(weights) | {P.short_symbol, P.vix_symbol} | {s.upper() for s in P.extra_allowed}
    checks: list[dict] = []

    def chk(name, ok, value=None, note=""):
        checks.append({"check": name, "pass": bool(ok), "value": value, "note": note})

    stop = halted()
    chk("not halted", stop is None, stop, "touch private/HALT or set BUILDOUT_TRADING_HALT to stop every ticket")
    chk("Agentic account", "agentic" in str(account.get("account_type", "")).lower(), account.get("account_type"),
        "Robinhood lets agents trade only the Agentic account; any other account is refused here too")
    chk("equity known", eq > 0, eq)
    age = _bdays_between(call["asof"], today) if call.get("asof") else 99
    chk(f"call's data at most {P.max_data_age_bd} business days old", age <= P.max_data_age_bd, {"data": call.get("asof"), "business_days": age})
    lv = ledger_check if ledger_check is not None else ledger.verify()
    if ledger_check is None:
        ent = [e for e in (ledger.read() if lv.get("ok") else []) if e.get("data_asof") == call.get("asof")]
        logged, eff = bool(ent), (ent[-1]["effective_from"] if ent else None)
    else:
        logged, eff = ledger_check.get("logged", True), ledger_check.get("effective_from")
    chk("call logged in the verified ledger before trading", lv.get("ok") and logged, {"ledger_ok": lv.get("ok"), "logged": logged})
    chk("the call is in force today (on or after its effective date)", eff is None or eff <= today, {"effective_from": eff, "today": today},
        "a call governs from the trading day after it is logged; trading it sooner would run ahead of the record")

    def num(v):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        return x if math.isfinite(x) and x > 0 else None

    bad_quotes = sorted(s for s, q in Q.items() if not isinstance(q, dict) or any(q.get(k) not in (None, "") and num(q.get(k)) is None for k in ("bid", "ask", "last"))
                        or (num(q.get("bid")) and num(q.get("ask")) and num(q["bid"]) > num(q["ask"])))

    def px(sym, side):
        q = Q.get(sym) if isinstance(Q.get(sym), dict) else {}
        bid, ask, last = (num(q.get(k)) for k in ("bid", "ask", "last"))
        ref = (ask if side == "buy" else bid) or last
        return ref, bid, ask, last

    marks = {s: (lambda r: ((r[1] + r[2]) / 2) if r[1] and r[2] else r[3])(px(s, "buy")) for s in held}
    implied = cash + sum(q * (marks.get(s) or 0) for s, q in held.items())
    chk("equity matches cash plus positions (within 2%)", eq > 0 and abs(implied - eq) <= 0.02 * eq, {"reported": round(eq, 2), "implied": round(implied, 2)},
        "a stale or wrong equity figure would size every order wrong")
    chk("every quote is a positive number with bid at most ask", not bad_quotes, bad_quotes)
    syms = sorted(set(T["weights"]) | set(held))
    orders, missing, wide = [], [], []
    for s in syms:
        ref, bid, ask, last = px(s, "buy")
        mid = ((bid + ask) / 2) if bid and ask else last
        if not mid:
            missing.append(s)
            continue
        if bid and ask and (ask - bid) / mid * 100 > P.max_spread_pct:
            wide.append(s)
        tgt_usd = T["weights"].get(s, 0.0) * eq
        cur_usd = held.get(s, 0.0) * mid
        diff = tgt_usd - cur_usd
        if abs(diff) < max(P.drift_band * eq, P.min_trade_usd) and not (s not in T["weights"] and held.get(s)):
            continue
        side = "buy" if diff > 0 else "sell"
        ref, bid, ask, last = px(s, side)
        lim = round(ref * (1 + P.collar_bp / 1e4) if side == "buy" else ref * (1 - P.collar_bp / 1e4), 2)
        qty = abs(diff) / lim
        if s not in T["weights"]:
            qty = held.get(s, 0.0)                     # out of the plan: sell all of it
        if s not in T["weights"]:
            pass                                       # an exit sells the whole holding, fractions included
        else:
            qty = round(qty, 4) if P.fractional else float(math.floor(qty + 1e-9))
        if side == "sell":
            qty = min(qty, held.get(s, 0.0))
        if qty <= 0:
            continue
        orders.append({"symbol": s, "side": side, "quantity": qty, "type": "limit", "limit_price": lim, "time_in_force": "gfd",
                       "notional": round(qty * lim, 2), "target_share": round(T["weights"].get(s, 0.0), 4),
                       "reason": HEDGE_LABEL.get(s, "book name to the call's size") if s in T["weights"] else "not in the plan"})
    orders.sort(key=lambda o: (o["side"] != "sell", -o["notional"]))   # sells first
    stage = "single"
    sell_orders = [o for o in orders if o["side"] == "sell"]
    if sell_orders and sum(o["notional"] for o in orders if o["side"] == "buy") > cash - P.cash_floor * eq + 1e-6:
        orders, stage = sell_orders, "sells first"     # buys that need the sale proceeds wait: plan again once the sells have filled
    for i, o in enumerate(orders, 1):
        o["seq"] = i
    chk("every symbol has a quote", not missing, missing)
    chk(f"spreads within {P.max_spread_pct}%", not wide, wide)
    chk("every symbol on the allowlist", all(o["symbol"] in allowed for o in orders), sorted({o["symbol"] for o in orders} - allowed))
    chk("no short sale (a sale at most what is held)", all(o["side"] == "buy" or o["quantity"] <= held.get(o["symbol"], 0) + 1e-9 for o in orders))
    buys = sum(o["notional"] for o in orders if o["side"] == "buy")
    sells = sum(o["notional"] for o in orders if o["side"] == "sell")
    cash_after = cash + sells - buys
    chk("buys funded from cash on hand", buys <= cash - P.cash_floor * eq + 1e-6 or not buys, {"buys": round(buys, 2), "cash": round(cash, 2)})
    after = dict(held)
    for o in orders:
        after[o["symbol"]] = after.get(o["symbol"], 0.0) + (o["quantity"] if o["side"] == "buy" else -o["quantity"])
    gross_after = sum(q * (px(s, "buy")[0] or 0) for s, q in after.items() if q > 0) / eq if eq else 0
    chk(f"gross after at most {P.max_gross:.0%} of equity (no borrowing)", gross_after <= P.max_gross + 1e-6, round(gross_after, 4))
    chk(f"cash after at least {P.cash_floor:.0%} of equity", cash_after >= P.cash_floor * eq - 1e-6, round(cash_after, 2))
    big = [o["symbol"] for o in orders if o["notional"] > min(P.max_order_pct * eq, P.max_order_usd) + 1e-6]
    chk(f"each order at most {P.max_order_pct:.0%} of equity and ${P.max_order_usd:,.0f}", not big, big)
    first_build = not held
    cap = 1.0 if first_build else P.max_turnover_pct
    turn = (buys + sells) / eq if eq else 0
    chk(f"turnover at most {cap:.0%} of equity", turn <= cap + 1e-6, round(turn, 4), "a first build from cash may reach 100%")
    n_today = sum(1 for t in _tickets_on(today) if t.get("execute") or t.get("status") in ("filled", "partially_filled"))
    chk(f"at most {P.max_tickets_per_day} executed ticket a day", n_today < P.max_tickets_per_day, n_today)
    ok = all(c["pass"] for c in checks)
    body = {"created": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "expires": (now + timedelta(minutes=P.ticket_ttl_min)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": P.mode, "broker": P.broker, "call": {"asof": call.get("asof"), "size": call.get("size"), "binding": call.get("binding"), "effective_from": eff,
                                                                **({"decision_id": call["decision_id"], "decision_ts": call.get("decision_ts")} if call.get("decision_id") else {})},
            "target": T, "orders": orders, "stage": stage, "account": {"equity": eq, "cash": cash, "positions": held}, "quotes": Q}
    ticket = {**body, "checks": checks, "all_checks_pass": ok, "execute": bool(ok and P.mode == "live" and orders),
              "summary": {"orders": len(orders), "buys_usd": round(buys, 2), "sells_usd": round(sells, 2), "cash_after": round(cash_after, 2), "gross_after": round(gross_after, 4)},
              "placed_by_buildout": False,
              "instructions": ("Show the person every order and check. Place nothing unless execute is true, every check passes, the ticket has not "
                               "expired, and the person has approved this ticket id. Place each order through Robinhood's Trading MCP in seq order "
                               "as a limit order at limit_price, then call record_fills with what Robinhood reports."
                               + (" This is the sells-only first stage: after the sells fill and are recorded, plan again for the buys." if stage != "single" else ""))}
    ticket = {"id": "tkt-" + _sha(ticket)[:16], **ticket}      # the id covers every field, the checks and execute included
    _save_ticket(ticket)
    return ticket


def _tickets_dir() -> Path:
    d = state_root() / "tickets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_ticket(t: dict) -> None:
    (_tickets_dir() / f"{t['id']}.json").write_text(json.dumps(t, indent=1))


TICKET_ID = re.compile(r"^tkt-[0-9a-f]{16}$")


def load_ticket(tid: str) -> dict:
    if not TICKET_ID.match(str(tid)):
        raise KeyError(f"no ticket {tid!r}")
    p = _tickets_dir() / f"{tid}.json"
    if not p.exists():
        raise KeyError(f"no ticket {tid}")
    t = json.loads(p.read_text())
    core = {k: v for k, v in t.items() if k not in ("id", "status")}
    if "tkt-" + _sha(core)[:16] != tid:
        raise ValueError(f"ticket {tid} was altered after it was written")
    return t


def _tickets_on(day: str) -> list[dict]:
    out = []
    for p in sorted(_tickets_dir().glob("tkt-*.json")):
        try:
            t = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        if str(t.get("created", "")).startswith(day):
            out.append(t)
    return out


def _fills_path() -> Path:
    return state_root() / "fills.jsonl"


def _fills() -> list[dict]:
    f = _fills_path()
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]


def verify_fills() -> dict:
    prev, n = "0" * 64, 0
    for e in _fills():
        body = {k: v for k, v in e.items() if k != "hash"}
        if e.get("prev") != prev or _sha(body) != e.get("hash"):
            return {"ok": False, "entries": n, "broken_at": e.get("seq")}
        prev, n = e["hash"], n + 1
    return {"ok": True, "entries": n}


def record_fills(tid: str, fills: list[dict], now: datetime | None = None, at_close: bool = False) -> dict:
    """Fills as Robinhood reports them ({symbol, side, quantity, price, order_id, status}) checked against the
    ticket's orders and appended, one hash-chained entry per ticket. A fill for an order not on the ticket, on the
    other side, for more shares, or far from the limit price is flagged. at_close (v0.42.5) is for the paper
    broker alone: its orders fill at the session's close, so the limit is not the test; the entry says so and
    carries each fill's session and close time."""
    t = load_ticket(tid)
    v = verify_fills()
    if not v["ok"]:
        raise RuntimeError(f"private/fills.jsonl fails verification at entry {v.get('broken_at')}; nothing was appended")
    by = {(o["symbol"], o["side"]): o for o in t["orders"]}
    earlier = [f for e in _fills() if e.get("ticket") == tid for f in e.get("fills", [])]
    seen_ids = {f["order_id"] for f in earlier if f.get("order_id")}
    total = {}
    for f in earlier:
        total[(f["symbol"], f["side"])] = total.get((f["symbol"], f["side"]), 0.0) + float(f["quantity"])
    issues, clean = [], []
    for f in fills:
        s, side = str(f.get("symbol", "")).upper(), str(f.get("side", "")).lower()
        try:
            q, p = float(f.get("quantity") or 0), float(f.get("price") or 0)
        except (TypeError, ValueError):
            issues.append(f"{s}: quantity or price is not a number"); continue
        oid = str(f.get("order_id", ""))[:64]
        if oid and oid in seen_ids:
            issues.append(f"{s}: order {oid} was already recorded"); continue
        seen_ids.add(oid)
        o = by.get((s, side))
        if not o:
            issues.append(f"{s} {side}: not on the ticket")
        else:
            total[(s, side)] = total.get((s, side), 0.0) + q
            if total[(s, side)] > o["quantity"] + 1e-9:
                issues.append(f"{s}: filled {total[(s, side)]:g} in all against {o['quantity']:g} ordered")
            if not at_close and ((side == "buy" and p > o["limit_price"] + 1e-6) or (side == "sell" and p < o["limit_price"] - 1e-6)):
                issues.append(f"{s}: price {p} through the limit {o['limit_price']}")
        row = {"symbol": s, "side": side, "quantity": q, "price": p, "order_id": oid, "status": str(f.get("status", "filled"))[:20]}
        if at_close:
            row.update({k: f[k] for k in ("session", "filled", "ordered", "inside_limit") if f.get(k) is not None})
        clean.append(row)
    complete = all(abs(total.get(k, 0.0) - o["quantity"]) < 1e-9 for k, o in by.items())
    status = "filled" if complete and not issues else ("partially_filled" if any(v > 0 for v in total.values()) else "unfilled")
    prev = _fills()[-1]["hash"] if _fills() else "0" * 64
    e = {"seq": len(_fills()) + 1, "ticket": tid, "mode": t["mode"], "ts_utc": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "fills": clean, "issues": issues, "status": status, "prev": prev}
    if at_close:
        e["convention"] = "market on close: each order filled at the close of the first session ending after it was written, 5 bp half-spread"
    e["hash"] = _sha(e)
    _fills_path().parent.mkdir(parents=True, exist_ok=True)
    with _fills_path().open("a") as fh:
        fh.write(_canon(e) + "\n")
    t["status"] = status
    (_tickets_dir() / f"{tid}.json").write_text(json.dumps(t, indent=1))
    return {"ticket": tid, "status": status, "issues": issues, "entry": e["seq"], "chain_ok": verify_fills()["ok"]}


def _paper_path() -> Path:
    return state_root() / "paper_account.json"


def paper_account(start_cash: float = 100_000.0) -> dict:
    if _paper_path().exists():
        return json.loads(_paper_path().read_text())
    return {"account_type": "agentic (paper)", "cash": start_cash, "positions": [], "equity": start_cash}


def paper_fill(tid: str) -> dict:
    """Paper mode: fill every order at its limit price in the paper account and record the fills."""
    t = load_ticket(tid)
    if t.get("status") or any(e.get("ticket") == tid for e in _fills()):
        raise ValueError(f"ticket {tid} has already been filled; plan again for a new ticket")
    if t["mode"] != "paper":
        raise ValueError("paper_fill is for paper tickets; live tickets are filled at Robinhood")
    if not t["all_checks_pass"]:
        raise ValueError("the ticket failed a check; nothing to fill")
    A = paper_account()
    pos = {p["symbol"]: p["quantity"] for p in A["positions"]}
    fills = []
    for o in t["orders"]:
        q = o["quantity"] if o["side"] == "buy" else -o["quantity"]
        pos[o["symbol"]] = pos.get(o["symbol"], 0.0) + q
        A["cash"] -= q * o["limit_price"]
        fills.append({"symbol": o["symbol"], "side": o["side"], "quantity": o["quantity"], "price": o["limit_price"], "order_id": f"paper-{t['id']}-{o['seq']}"})
    A["positions"] = [{"symbol": s, "quantity": q} for s, q in sorted(pos.items()) if q > 1e-9]
    marks = {s: (t["quotes"].get(s) or {}).get("last") or 0 for s in pos}
    A["equity"] = round(A["cash"] + sum(q * float(marks.get(s) or 0) for s, q in pos.items()), 2)
    state_root().mkdir(parents=True, exist_ok=True)
    _paper_path().write_text(json.dumps(A, indent=1))
    return {"account": A, **record_fills(tid, fills)}


def status(P: TradingParams | None = None) -> dict:
    P = P or load_params()
    today = datetime.now(timezone.utc).date().isoformat()
    return {"mode": P.mode, "halted": halted(), "params": asdict(P), "tickets_today": [{k: t.get(k) for k in ("id", "created", "all_checks_pass", "execute", "status")} for t in _tickets_on(today)],
            "fills_chain": verify_fills(), "paper_account": paper_account() if P.mode == "paper" else None,
            "places_orders": False, "broker_mcp": "https://agent.robinhood.com/mcp/trading"}
