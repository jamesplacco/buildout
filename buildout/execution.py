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
from dataclasses import asdict, dataclass, field, replace
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
    drift_band: float = 0.02            # one name this share of equity from its target starts a rebalance
    gross_band: float = 0.01            # v0.47: so does the whole book, when what is held is this share of equity from the call's size
    min_trade_usd: float = 50.0
    collar_bp: float = 10.0             # limit price: ask plus 10 bp to buy, bid less 10 bp to sell
    max_spread_pct: float = 1.0
    ticket_ttl_min: int = 15
    max_tickets_per_day: int = 1
    max_data_age_bd: int = 3            # the call's data at most 3 business days old
    fractional: bool = False            # whole shares by default
    fee_bp: float = 0.0                 # commission, in basis points of each order (the Agentic account charges none)
    max_requote_bp: float = 50.0        # a staged ticket is planned again once a quote has moved this far from the one it used
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
    """v0.44.1: private/HALT (what `trade halt` writes) stops every run, the paper bot and any --state run included."""
    if os.environ.get("BUILDOUT_TRADING_HALT"):
        return "BUILDOUT_TRADING_HALT is set"
    for d in dict.fromkeys([state_root(), PRIVATE]):
        if (d / "HALT").exists():
            return f"{d.name}/HALT exists"
    return None


def _atomic_write_text(path: Path, text: str) -> None:
    """Write through a temporary file and rename it into place (v0.44.1), so a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


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
    # v0.48: a row with no word on whether it meets the limits is not one that does
    fr = [r for r in (call.get("frontier") or []) if r.get("meets") is True and r.get("short") is not None and r.get("gross") is not None]
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
    return {"book_gross": g, "short": h, "vix": vix, "gross_total": g + h + vix, "weights": tw, "variant": P.variant,
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


def call_in_force(today: str | None = None, now: datetime | None = None) -> dict | None:
    """The call that governs the session `today` (v0.42.4): the newest ledger entry whose governing session has come.
    Each day's call takes effect on a later trading day, so the newest call (latest_call) is never the one in force
    on the day it is written. Rebuilt from the ledger entry, with its two-point menu as the frontier the hedged
    variant walks. None when the ledger holds no entry in force.

    v0.47: the governing session is ledger.governs_from (the same rule the live record marks by), not the stored
    effective date: a call written on a Saturday governs from Tuesday, the session after the first close that
    followed it. `now` leaves out entries written after that moment, so a pass replayed at an earlier time sees
    the ledger as it stood then."""
    from . import ledger
    today = today or datetime.now(timezone.utc).date().isoformat()
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ") if now is not None else None
    rows = [(ledger.governs_from(e) or "9999", e) for e in ledger.read() if stamp is None or str(e.get("ts_utc", "")) <= stamp]
    rows = [(g, e) for g, e in rows if g <= today]
    if not rows:
        return None
    g, e = max(rows, key=lambda r: (r[0], r[1]["seq"]))
    c = e.get("call", {})
    frontier = [{"gross": m["gross"], "short": m.get("short", 0.0), "meets": True} for m in (c.get("menu_low"), c.get("menu_high")) if isinstance(m, dict) and m.get("gross") is not None]
    return {"asof": e.get("data_asof"), "effective_from": g, "size": c.get("size"), "binding": c.get("binding"), "frontier": frontier,
            "menu_high": c.get("menu_high"), "ledger_seq": e["seq"], "source": f"ledger entry {e['seq']}",
            "decision_id": decision_id(e), "decision_ts": e.get("ts_utc"),
            **({"stored_effective_from": e.get("effective_from")} if g != e.get("effective_from") else {})}


def decision_id(entry: dict) -> str:
    """One name for one decision on every surface (v0.42.5): the ledger entry's number and the head of its hash."""
    return f"{entry['seq']}-{str(entry.get('hash', ''))[:8]}"


POLICY_KEYS = ("max_gross", "cash_floor", "max_order_usd", "max_order_pct")


def plan(account: dict, quotes: dict, call: dict | None = None, P: TradingParams | None = None, weights: dict | None = None,
         today: str | None = None, ledger_check: dict | None = None, now: datetime | None = None, held_session: str | None = None,
         limits: dict | None = None) -> dict:
    """The ticket. `account`: {"equity": .., "cash": .., "account_type": "agentic", "positions": [{"symbol", "quantity"}]}.
    `quotes`: {symbol: {"bid": .., "ask": .., "last": ..}}. Nothing here places an order.

    held_session (v0.47): the first session the position will be held through, when that is not today. The paper
    broker fills at a close, so what it buys is held through the next session, and the call it must trade is the
    one that governs that session (the live record marks the same call over the same day).

    When it trades (v0.47). The holdings are left alone while every name is inside its band (drift_band of equity)
    and the book as a whole is inside gross_band of equity of the call's size. Outside either, every name is
    brought to its target, in whole shares rounded to the nearest (to the floor if the nearest would breach the cash
    floor or the gross cap). Before, only names outside their own band traded, so a call cut from 0.53x to 0.40x
    moved no name far enough and traded nothing.

    The account the orders leave (v0.48). `limits` are a second set of account limits (the mandate's): the ticket is
    planned under the tighter of the two, limit by limit (limits.tighter), so the planner does not size a ticket the
    mandate will refuse. The gross and cash checks are made on the account the orders would actually leave
    (limits.project): every position at its mark, untouched ones included, each order at its own price, whole
    shares, fees out of cash, gross and cash both over that account's value. Buys that would take it past a limit
    are cut to fit and the ticket says so. An account already past a limit is brought back: it rebalances whatever
    the bands say, and a ticket that only sells and moves the account toward the limit passes, with the breach stated."""
    from . import book as bk
    from . import ledger
    from . import limits as lm
    P = P or load_params()
    policy = lm.tighter({k: getattr(P, k) for k in POLICY_KEYS}, {k: v for k, v in (limits or {}).items() if k in POLICY_KEYS})
    P = replace(P, **policy)
    call = call or call_in_force(held_session or today) or latest_call()
    weights = weights or dict(bk.BOOK)
    now = now or datetime.now(timezone.utc)
    today = today or now.date().isoformat()
    held_session = held_session or today
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
        logged, eff = bool(ent), (ledger.governs_from(ent[-1]) if ent else None)      # v0.47: the session it governs, as the live record reads it
    else:
        logged, eff = ledger_check.get("logged", True), ledger_check.get("effective_from")
    chk("call logged in the verified ledger before trading", lv.get("ok") and logged, {"ledger_ok": lv.get("ok"), "logged": logged})
    if held_session == today:
        chk("the call is in force today (on or after its effective date)", eff is None or eff <= today, {"effective_from": eff, "today": today},
            "a call governs from the trading day after it is logged; trading it sooner would run ahead of the record")
    else:
        chk("the call is in force for the session the position is held through", eff is None or eff <= held_session,
            {"effective_from": eff, "today": today, "held_session": held_session},
            "an order filled at a close is held through the next session; the call traded is the one that governs that session, never a later one")

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
    mark_of = {s: (lambda r: ((r[1] + r[2]) / 2) if r[1] and r[2] else r[3])(px(s, "buy")) for s in syms}
    start = lm.account_checks(lm.project(held, cash, [], mark_of), policy)
    in_breach = [c["metric"] for c in start["checks"] if c["status"] == "fail"]          # the account as it stands, before any order
    gaps, missing, wide = [], [], []
    for s in syms:
        ref, bid, ask, last = px(s, "buy")
        mid = ((bid + ask) / 2) if bid and ask else last
        if not mid:
            missing.append(s)
            continue
        if bid and ask and (ask - bid) / mid * 100 > P.max_spread_pct:
            wide.append(s)
        gaps.append((s, T["weights"].get(s, 0.0) * eq - held.get(s, 0.0) * mid))        # target less held, in dollars
    # v0.47: one name outside its band, or the whole book outside the gross band, brings every name to target
    name_band = max(P.drift_band * eq, P.min_trade_usd)
    gross_gap = sum(d for s, d in gaps if s in T["weights"])
    outside = sorted(s for s, d in gaps if s in T["weights"] and abs(d) >= name_band)
    rebalance = bool(outside) or abs(gross_gap) > max(P.gross_band * eq, P.min_trade_usd) or bool(in_breach)      # v0.48: an account past a limit is brought back

    def build(nearest: bool) -> list[dict]:
        out = []
        for s, diff in gaps:
            exit_ = s not in T["weights"] and bool(held.get(s))
            if not exit_ and (not rebalance or abs(diff) < P.min_trade_usd):
                continue
            side = "buy" if diff > 0 else "sell"
            ref = px(s, side)[0]
            lim = round(ref * (1 + P.collar_bp / 1e4) if side == "buy" else ref * (1 - P.collar_bp / 1e4), 2)
            if exit_:
                qty = held.get(s, 0.0)                 # out of the plan: sell all of it, fractions included
            elif P.fractional:
                qty = round(abs(diff) / lim, 4)
            else:
                qty = float(math.floor(abs(diff) / lim + (0.5 if nearest else 1e-9)))
            if side == "sell":
                qty = min(qty, held.get(s, 0.0))
            if qty <= 0:
                continue
            out.append({"symbol": s, "side": side, "quantity": qty, "type": "limit", "limit_price": lim, "time_in_force": "gfd",
                        "notional": round(qty * lim, 2), "target_share": round(T["weights"].get(s, 0.0), 4),
                        "reason": HEDGE_LABEL.get(s, "book name to the call's size") if s in T["weights"] else "not in the plan"})
        return out

    def fits(os_: list[dict]) -> bool:
        b = sum(o["notional"] for o in os_ if o["side"] == "buy")
        sl = sum(o["notional"] for o in os_ if o["side"] == "sell")
        aft = dict(held)
        for o in os_:
            aft[o["symbol"]] = aft.get(o["symbol"], 0.0) + (o["quantity"] if o["side"] == "buy" else -o["quantity"])
        g = sum(q * (px(s, "buy")[0] or 0) for s, q in aft.items() if q > 0) / eq if eq else 0
        return cash + sl - b >= P.cash_floor * eq - 1e-6 and g <= P.max_gross + 1e-6

    orders = build(nearest=True)
    rounding = "nearest share"
    if not P.fractional and not fits(orders):          # the nearest share would borrow or eat the cash floor: round down instead
        orders, rounding = build(nearest=False), "whole shares, rounded down"
    orders.sort(key=lambda o: (o["side"] != "sell", -o["notional"]))   # sells first
    stage = "single"
    sell_orders = [o for o in orders if o["side"] == "sell"]
    if sell_orders and sum(o["notional"] for o in orders if o["side"] == "buy") > cash - P.cash_floor * eq + 1e-6:
        orders, stage = sell_orders, "sells first"     # buys that need the sale proceeds wait: plan again once the sells have filled
    # v0.48: the account these orders would leave, under the tighter policy. Buys that take it past a limit are cut
    # to fit, in whole shares. The rounding check above uses the same limits but the opening equity as its base.
    def projected(os_):
        return lm.project(held, cash, os_, mark_of, P.fee_bp)

    def scaled(f):
        out = []
        for o in orders:
            if o["side"] != "buy":
                out.append(o); continue
            q = o["quantity"] * f
            q = round(q, 4) if P.fractional else float(math.floor(q + 1e-9))
            if q > 0 and q * o["limit_price"] >= P.min_trade_usd:
                out.append({**o, "quantity": q, "notional": round(q * o["limit_price"], 2)})
        return out

    def fits_acct(os_):
        return lm.account_checks(projected(os_), policy, sum(o["notional"] for o in os_ if o["side"] == "buy"))

    resized = None
    buys0 = sum(o["notional"] for o in orders if o["side"] == "buy")
    if buys0 and not fits_acct(orders)["meets"]:
        lo, hi = 0.0, 1.0                                # the largest share of the buys that fits both limits
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if fits_acct(scaled(mid))["meets"] else (lo, mid)
        was = fits_acct(orders)
        orders = scaled(lo) if fits_acct(scaled(lo))["meets"] else [o for o in orders if o["side"] != "buy"]
        resized = {"buys_usd_wanted": round(buys0, 2), "buys_usd": round(sum(o["notional"] for o in orders if o["side"] == "buy"), 2),
                   "binding": was["failed"], "why": "the buys as first sized would leave the account past " + " and ".join(
                       f"{'max gross' if c['metric'] == 'gross' else 'the cash floor'} ({c['value']:.2%} against {c['limit']:.2%})" for c in was["checks"] if c["status"] == "fail")
                   + "; positions the ticket does not trade still count"}
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
    proj = projected(orders)
    acct = lm.account_checks(proj, policy, buys)
    by_metric = {c["metric"]: c for c in acct["checks"]}
    gross_after = proj["after"]["gross"] if proj["after"]["gross"] is not None else 0.0
    cash_after = proj["after"]["cash"]
    chk(f"gross after at most {P.max_gross:.0%} of equity (no borrowing)", by_metric["gross"]["status"] == "pass", round(gross_after, 4), by_metric["gross"]["note"])
    chk(f"cash after at least {P.cash_floor:.0%} of equity", by_metric["cash"]["status"] == "pass", round(cash_after, 2), by_metric["cash"]["note"])
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
                                                                **({"held_session": held_session} if held_session != today else {}),
                                                                **({"decision_id": call["decision_id"], "decision_ts": call.get("decision_ts")} if call.get("decision_id") else {})},
            "target": T, "orders": orders, "stage": stage, "account": {"equity": eq, "cash": cash, "positions": held}, "quotes": Q,
            "rebalance": {"triggered": rebalance, "gross_gap": round(gross_gap / eq, 4) if eq else None, "gross_band": P.gross_band,
                          "names_outside_band": outside, "name_band": P.drift_band, "rounding": "fractional" if P.fractional else rounding,
                          **({"because": "the account is outside " + " and ".join(in_breach)} if in_breach else {})},
            "policy": policy,
            "projected": {"basis": "every position at its mark, each order at its limit price, fees out of cash; gross and cash over the account's value after the orders",
                          "before": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in proj["before"].items()},
                          "after": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in proj["after"].items() if k != "positions"},
                          "checks": [{k: c.get(k) for k in ("metric", "value", "limit", "headroom", "units", "kind", "status", "note", "repair") if c.get(k) is not None} for c in acct["checks"]],
                          **({"breach_before": in_breach} if in_breach else {}), **({"resized": resized} if resized else {})}}
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
    _atomic_write_text(_tickets_dir() / f"{t['id']}.json", json.dumps(t, indent=1))


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


FILL_ADAPTERS = {
    "paper": "one execution per order, at the close of its session; the id is the order id and the session",
    "robinhood_mcp": "cumulative order observations (filled so far and the average price), read after the wait; "
                     "each is turned into the quantity that is new since the last one",
    "assistant": "execution events as Robinhood reports them; pass execution_id when it gives one, or cumulative=true "
                 "when the figure is an order's total so far",
}


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _exec_id(row: dict) -> str:
    """An execution's identity (v0.48): the broker's execution id when it gives one; else what the fill is (order,
    symbol, side, quantity, price and its own time), so a retry of the same report is the same execution and a
    second, different fill on the same order is a new one. Rows written before v0.48 carry no id and are read
    the same way."""
    if row.get("execution_id"):
        return str(row["execution_id"])[:96]
    return "c:" + _sha([str(row.get("order_id", "")), str(row.get("symbol", "")).upper(), str(row.get("side", "")).lower(),
                        round(float(row.get("quantity") or 0), 8), round(float(row.get("price") or 0), 8), str(row.get("filled") or row.get("event_time") or "")])[:20]


def accepted_fills(tid: str | None = None) -> list[dict]:
    """Every accepted execution in the log, in the order it was accepted (one ticket's, or all)."""
    return [{**f, "ticket": e.get("ticket")} for e in _fills() if tid is None or e.get("ticket") == tid for f in e.get("fills", [])]


def replay(start_cash: float = 0.0, start_positions: dict | None = None, tid: str | None = None) -> dict:
    """The account the accepted executions imply: cash and shares, from a starting account. A buy costs quantity
    times price plus its fee; a sale raises quantity times price less its fee (a negative fee is a rebate). Over the
    whole log (no tid) each correction's cash adjustment is applied too, as cash_and_positions_from_log does."""
    cash, pos = float(start_cash), {k: float(v) for k, v in (start_positions or {}).items()}
    if tid is None:
        cash += sum(float(e.get("cash_delta") or 0.0) for e in corrections())
    for f in accepted_fills(tid):
        q, px, fee = float(f["quantity"]), float(f["price"]), float(f.get("fees") or 0.0)
        sgn = 1.0 if f["side"] == "buy" else -1.0
        pos[f["symbol"]] = pos.get(f["symbol"], 0.0) + sgn * q
        cash -= sgn * q * px + fee
    return {"cash": cash, "positions": {k: v for k, v in pos.items() if abs(v) > 1e-9}}


def record_fills(tid: str, fills: list[dict], now: datetime | None = None, at_close: bool = False) -> dict:
    """What the broker reports, checked against the ticket and appended to the hash-chained log.

    v0.48. A row is an execution ({symbol, side, quantity, price, order_id, execution_id, fees}) or, with
    cumulative=true, an order's total so far (quantity filled and average price), from which only what is new is
    accepted. Which one a broker sends is written down (FILL_ADAPTERS), not guessed.

      identity    executions are told apart by execution, not by order: a 10-share order that fills 4 and then 6
                  is two executions and 10 shares. The same execution reported twice is recorded once, and says
                  so under `duplicates`; it is not an issue and does not change the ticket's status.
      validation  quantity and price must be finite and above zero, the side buy or sell, a fee finite (positive
                  is a cost, negative a rebate). A row that fails is kept under `rejected` with the reason and
                  changes no holding and no total. A cumulative total that falls is rejected the same way.
      excess      a fill that takes an order past its quantity, a fill for an order not on the ticket, and a price
                  through the limit are recorded, because they are what happened, and flagged under `issues`; a
                  ticket with an issue is never marked filled.
      status      from the accepted quantities alone: filled, partially_filled or unfilled. A cancelled order
                  keeps what it filled.

    Nothing new (every row a duplicate or an unchanged total) appends nothing. at_close (v0.42.5) is for the paper
    broker alone: its orders fill at the session's close, so the limit is not the test; the entry says so and
    carries each fill's session and close time."""
    t = load_ticket(tid)
    v = verify_fills()
    if not v["ok"]:
        raise RuntimeError(f"private/fills.jsonl fails verification at entry {v.get('broken_at')}; nothing was appended")
    by = {(o["symbol"], o["side"]): o for o in t["orders"]}
    earlier = accepted_fills(tid)
    seen = {_exec_id(f) for f in earlier}
    total: dict = {}
    per_order: dict = {}                               # order id -> [quantity, dollars] accepted so far
    for f in earlier:
        total[(f["symbol"], f["side"])] = total.get((f["symbol"], f["side"]), 0.0) + float(f["quantity"])
        if f.get("order_id"):
            po = per_order.setdefault(f["order_id"], [0.0, 0.0])
            po[0] += float(f["quantity"]); po[1] += float(f["quantity"]) * float(f["price"])
    issues, clean, rejected, dup = [], [], [], 0
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def refuse(f, why):
        rejected.append({"row": {k: (f.get(k) if isinstance(f.get(k), (str, int, bool)) or f.get(k) is None else str(f.get(k))) for k in ("symbol", "side", "quantity", "price", "order_id", "execution_id", "cumulative", "fees")}, "why": why})

    for f in fills:
        s, side = str(f.get("symbol", "")).upper(), str(f.get("side", "")).lower()
        q, px = _num(f.get("quantity")), _num(f.get("price"))
        fee = _num(f.get("fees", 0.0) if f.get("fees") is not None else 0.0)
        oid = str(f.get("order_id", "") or "")[:64]
        if side not in ("buy", "sell"):
            refuse(f, f"side {side!r} is not buy or sell"); continue
        if q is None or q <= 0:
            refuse(f, "quantity is not a finite number above zero"); continue
        if px is None or px <= 0:
            refuse(f, "price is not a finite number above zero"); continue
        if fee is None:
            refuse(f, "the fee is not a finite number"); continue
        extra = {}
        if f.get("cumulative"):
            if not oid:
                refuse(f, "an order's total so far needs its order id"); continue
            pq, pd_ = per_order.get(oid, [0.0, 0.0])
            if q < pq - 1e-9:
                refuse(f, f"the order's total fell: {q:g} after {pq:g}"); continue
            if q - pq < 1e-9:
                dup += 1; continue                      # the same total again: nothing new
            nq = q - pq
            npx = (q * px - pd_) / nq
            if not math.isfinite(npx) or npx <= 0:
                refuse(f, f"the new {nq:g} shares would have a price of {npx:.4f}: the totals do not agree with what was recorded"); continue
            extra = {"execution_id": f"{oid}:total:{q:.8g}", "from_total": {"quantity": q, "avg_price": px}}
            q, px = nq, round(npx, 6)
        row = {"symbol": s, "side": side, "quantity": q, "price": px, "order_id": oid, "status": str(f.get("status", "filled"))[:20], **extra}
        if f.get("execution_id") and "execution_id" not in row:
            row["execution_id"] = str(f["execution_id"])[:96]
        if at_close:
            row.update({k: f[k] for k in ("session", "filled", "ordered", "inside_limit") if f.get(k) is not None})
        elif f.get("event_time"):
            row["event_time"] = str(f["event_time"])[:40]
        if fee:
            row["fees"] = fee
        if str(f.get("currency") or "USD").upper() != "USD":
            refuse(f, f"currency {f.get('currency')!r}: the account is in US dollars"); continue
        eid = _exec_id(row)
        if eid in seen:
            dup += 1; continue
        seen.add(eid)
        row.setdefault("execution_id", eid)
        row["observed"] = stamp
        o = by.get((s, side))
        if not o:
            issues.append(f"{s} {side}: not on the ticket")
        else:
            total[(s, side)] = total.get((s, side), 0.0) + q
            if total[(s, side)] > o["quantity"] + 1e-9:
                issues.append(f"{s}: filled {total[(s, side)]:g} in all against {o['quantity']:g} ordered")
            if not at_close and ((side == "buy" and px > o["limit_price"] + 1e-6) or (side == "sell" and px < o["limit_price"] - 1e-6)):
                issues.append(f"{s}: price {px} through the limit {o['limit_price']}")
        if oid:
            po = per_order.setdefault(oid, [0.0, 0.0])
            po[0] += q; po[1] += q * px
        clean.append(row)
    issues += [f"{r['row'].get('symbol') or '?'}: not accepted ({r['why']})" for r in rejected]
    earlier_issues = any(e.get("issues") for e in _fills() if e.get("ticket") == tid)
    complete = all(abs(total.get(k, 0.0) - o["quantity"]) < 1e-9 for k, o in by.items())
    status = "filled" if complete and not issues and not earlier_issues else ("partially_filled" if any(x > 0 for x in total.values()) else "unfilled")
    if not clean and not rejected and not issues:       # nothing new: the log is not written to, and a retry changes nothing
        return {"ticket": tid, "status": t.get("status") or status, "issues": [], "entry": None, "accepted": 0, "duplicates": dup, "rejected": 0, "chain_ok": True}
    prev = _fills()[-1]["hash"] if _fills() else "0" * 64
    e = {"seq": len(_fills()) + 1, "ticket": tid, "mode": t["mode"], "ts_utc": stamp, "schema": 2,
         "fills": clean, "issues": issues, "status": status, "prev": prev}
    if rejected:
        e["rejected"] = rejected
    if dup:
        e["duplicates"] = dup
    if at_close:
        e["convention"] = "market on close: each order filled at the close of the first session ending after it was written, 5 bp half-spread"
    e["hash"] = _sha(e)
    _fills_path().parent.mkdir(parents=True, exist_ok=True)
    with _fills_path().open("a") as fh:
        fh.write(_canon(e) + "\n")
    t["status"] = status
    _atomic_write_text(_tickets_dir() / f"{tid}.json", json.dumps(t, indent=1))
    return {"ticket": tid, "status": status, "issues": issues, "entry": e["seq"], "accepted": len(clean), "duplicates": dup, "rejected": len(rejected), "chain_ok": verify_fills()["ok"]}


def corrections() -> list[dict]:
    """The correction records in the fills log (v0.47), in the order they were written."""
    return [e for e in _fills() if e.get("kind") == "correction"]


def record_correction(cid: str, cash_delta: float, reason: str, corrects: str | None = None, detail: list | None = None,
                      now: datetime | None = None, extra: dict | None = None) -> dict:
    """Append a correction to the hash-chained fills log (v0.47): a dated cash adjustment that puts right an entry
    already written, which is itself never edited. One record per id, ever: a second call with the same id appends
    nothing. The record carries no fills (`fills` is empty and `status` is "correction"), so every reader that
    walks fills sees none, and it names the ticket it corrects under `corrects`, not `ticket`, so it is never
    taken for that ticket's own entry. The caller changes the account; this only records why."""
    v = verify_fills()
    if not v["ok"]:
        raise RuntimeError(f"the fills log fails verification at entry {v.get('broken_at')}; nothing was appended")
    log = _fills()
    for e in log:
        if e.get("kind") == "correction" and e.get("id") == cid:
            return {"recorded": False, "id": cid, "entry": e["seq"], "chain_ok": True}
    amount = round(abs(float(cash_delta)), 2)
    e = {"seq": len(log) + 1, "kind": "correction", "id": cid, "corrects": corrects, "status": "correction", "fills": [],
         "ts_utc": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"), "cash_delta": round(float(cash_delta), 2), "amount": amount,
         "reason": reason, "detail": detail or [], **(extra or {}), "prev": log[-1]["hash"] if log else "0" * 64}
    e["hash"] = _sha(e)
    _fills_path().parent.mkdir(parents=True, exist_ok=True)
    with _fills_path().open("a") as fh:
        fh.write(_canon(e) + "\n")
    return {"recorded": True, "id": cid, "entry": e["seq"], "chain_ok": verify_fills()["ok"]}


def cash_and_positions_from_log(start_cash: float) -> dict:
    """What the fills log alone says the account holds (v0.47): opening cash, less every buy, plus every sell, plus
    every correction's cash adjustment; and the shares each fill left. The reconcile check sets this beside the
    account file."""
    cash, pos = float(start_cash), {}
    for e in _fills():
        if e.get("kind") == "correction":
            cash += float(e.get("cash_delta") or 0.0)
            continue
        for f in e.get("fills", []):
            q, p = float(f.get("quantity") or 0), float(f.get("price") or 0)
            sign = 1.0 if str(f.get("side")) == "buy" else -1.0
            cash -= sign * q * p
            pos[f["symbol"]] = pos.get(f["symbol"], 0.0) + sign * q
    return {"cash": cash, "positions": {s: q for s, q in pos.items() if abs(q) > 1e-9}}


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
    _atomic_write_text(_paper_path(), json.dumps(A, indent=1))
    return {"account": A, **record_fills(tid, fills)}


def status(P: TradingParams | None = None) -> dict:
    P = P or load_params()
    today = datetime.now(timezone.utc).date().isoformat()
    return {"mode": P.mode, "halted": halted(), "params": asdict(P), "tickets_today": [{k: t.get(k) for k in ("id", "created", "all_checks_pass", "execute", "status")} for t in _tickets_on(today)],
            "fills_chain": verify_fills(), "paper_account": paper_account() if P.mode == "paper" else None,
            "places_orders": False, "broker_mcp": "https://agent.robinhood.com/mcp/trading"}
