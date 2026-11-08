"""The mandate (v0.42): the written terms under which the trader may act for a person, and the check of every ticket
against them.

A mandate is a small TOML file (private/mandate.toml, git-ignored) that the person writes and signs by hand. Nothing
trades for real without one, and nothing in Buildout can write one. It holds:

  mode        manual       every ticket waits for the person's approval (the default)
              supervised   tickets execute once approved, and the approval may be given in advance for a window
              autonomous   tickets that pass every check execute without asking; the person reads the digest
  armed       false until the person sets it true; with armed = false the trader stages and never sends live orders
  broker      paper (the model account), assistant (orders handed to the assistant that holds Robinhood's MCP), or
              robinhood_mcp (Buildout's own client on Robinhood's Trading MCP)
  limits      the ceilings on one order, one day and the whole account, and the losses that halt trading

The mandate's hash is written into every ticket and every journal line, so a change of terms is visible in the record.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "private"
MODES = ("manual", "supervised", "autonomous")
BROKERS = ("paper", "assistant", "robinhood_mcp")


@dataclass
class Mandate:
    mode: str = "manual"
    armed: bool = False
    broker: str = "paper"
    signed_by: str = ""                     # the person's name, in their own hand; required to arm
    signed_on: str = ""                     # ISO date
    account_type: str = "agentic"           # the only account the trader may touch
    allowed_symbols: list[str] = field(default_factory=list)   # empty: the book's names plus PSQ and VIXY
    max_order_usd: float = 10_000.0
    max_order_pct: float = 0.25
    max_day_turnover_pct: float = 0.60
    max_gross: float = 0.98
    cash_floor: float = 0.02
    max_equity_usd: float = 250_000.0       # above this the trader refuses to act (the mandate was written for less)
    halt_drawdown: float = 0.20             # from the account's recorded peak
    halt_day_loss: float = 0.05             # from the previous close
    min_days_between_tickets: int = 1
    approval_ttl_min: int = 240             # supervised: how long an approval stays good
    window_start: str = "09:45"             # New York time; the trader acts inside this window only
    window_end: str = "15:45"
    quiet_days: list[str] = field(default_factory=list)       # ISO dates the trader skips (earnings, travel)
    digest_path: str = "private/trader/digest.md"
    notes: str = ""

    def hash(self) -> str:
        d = asdict(self)
        return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]

    def problems(self) -> list[str]:
        """Why this mandate cannot be used as written. Empty means usable."""
        p = []
        if self.mode not in MODES:
            p.append(f"mode must be one of {MODES}")
        if self.broker not in BROKERS:
            p.append(f"broker must be one of {BROKERS}")
        if self.armed and self.broker != "paper":
            if not self.signed_by.strip():
                p.append("an armed mandate must carry signed_by")
            try:
                datetime.fromisoformat(self.signed_on)
            except ValueError:
                p.append("an armed mandate must carry signed_on as an ISO date")
        if self.armed and self.mode == "autonomous" and self.broker != "paper" and not self.notes.strip():
            p.append("an armed autonomous mandate must say in notes why unattended trading is wanted")
        for k in ("max_order_pct", "max_day_turnover_pct", "max_gross", "cash_floor", "halt_drawdown", "halt_day_loss"):
            v = getattr(self, k)
            if not 0 <= float(v) <= 1:
                p.append(f"{k} must be between 0 and 1")
        if self.max_gross + self.cash_floor > 1.0 + 1e-9:
            p.append("max_gross plus cash_floor cannot exceed 1")
        if self.max_order_usd <= 0 or self.max_equity_usd <= 0:
            p.append("max_order_usd and max_equity_usd must be positive")
        for k in ("window_start", "window_end"):
            try:
                datetime.strptime(getattr(self, k), "%H:%M")
            except ValueError:
                p.append(f"{k} must be HH:MM")
        return p


def load(path: str | Path | None = None) -> Mandate:
    """private/mandate.toml, or the default (paper, manual, unarmed) when there is none."""
    import tomllib
    p = Path(path) if path else PRIVATE / "mandate.toml"
    if not p.exists():
        return Mandate()
    raw = tomllib.loads(p.read_text())
    raw = raw.get("mandate", raw)
    known = set(Mandate.__dataclass_fields__)
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"mandate has unknown keys {unknown}; a misspelt limit is not a limit")
    return Mandate(**{k: v for k, v in raw.items() if k in known})


def template() -> str:
    """A mandate for the person to edit and sign. Written to private/mandate.toml by `buildout trader --init`."""
    return '''# Buildout trading mandate. Edit by hand, then sign. Nothing trades for real until armed = true.
[mandate]
mode = "manual"            # manual | supervised | autonomous
armed = false
broker = "paper"           # paper | assistant | robinhood_mcp
signed_by = ""             # your name
signed_on = ""             # YYYY-MM-DD
max_order_usd = 10000.0
max_order_pct = 0.25
max_day_turnover_pct = 0.60
max_gross = 0.98
cash_floor = 0.02
max_equity_usd = 250000.0
halt_drawdown = 0.20       # stop trading if the account falls this far from its peak
halt_day_loss = 0.05       # or this far in a day
min_days_between_tickets = 1
approval_ttl_min = 240
window_start = "09:45"     # New York time
window_end = "15:45"
quiet_days = []
notes = ""                 # required for an armed autonomous mandate: why unattended trading is wanted
'''


def authorize(ticket: dict, account: dict, M: Mandate, history: dict | None = None, now: datetime | None = None) -> dict:
    """Is this ticket within the mandate? Every reason is listed; one failure refuses the ticket."""
    now = now or datetime.now(timezone.utc)
    history = history or {}
    reasons: list[str] = []
    eq = float(account.get("equity") or 0.0)
    if M.problems():
        reasons += [f"mandate: {p}" for p in M.problems()]
    if not ticket.get("all_checks_pass"):
        reasons.append("the ticket failed one of the planner's checks")
    at = str(account.get("account_type", "")).lower()
    if M.account_type not in at:
        reasons.append(f"account type {at!r} is not {M.account_type!r}")
    if eq > M.max_equity_usd:
        reasons.append(f"equity {eq:,.0f} is above the mandate's {M.max_equity_usd:,.0f}")
    allowed = {s.upper() for s in M.allowed_symbols} if M.allowed_symbols else None
    orders = ticket.get("orders") or []
    for o in orders:
        notional = float(o["quantity"]) * float(o["limit_price"])
        if notional > M.max_order_usd + 1e-6:
            reasons.append(f"{o['symbol']} {o['side']} {notional:,.0f} is above max_order_usd {M.max_order_usd:,.0f}")
        if eq and notional > M.max_order_pct * eq + 1e-6:
            reasons.append(f"{o['symbol']} {o['side']} is {notional / eq:.0%} of equity, above {M.max_order_pct:.0%}")
        if allowed is not None and o["symbol"].upper() not in allowed:
            reasons.append(f"{o['symbol']} is not in the mandate's allowed symbols")
        if o["side"] not in ("buy", "sell"):
            reasons.append(f"order side {o['side']!r} is not buy or sell")
    turnover = sum(float(o["quantity"]) * float(o["limit_price"]) for o in orders)
    if eq and turnover > M.max_day_turnover_pct * eq + 1e-6 and history.get("tickets_executed", 0) > 0:
        reasons.append(f"turnover {turnover / eq:.0%} is above the mandate's {M.max_day_turnover_pct:.0%} (a first build is exempt)")
    tgt = ticket.get("target") or {}
    if float(tgt.get("gross_total", 0) or 0) > M.max_gross + 1e-9:
        reasons.append(f"the target's gross {tgt.get('gross_total'):.2f} is above max_gross {M.max_gross:.2f}")
    peak = float(history.get("peak_equity") or eq or 0)
    prev = float(history.get("prev_equity") or eq or 0)
    if peak and eq and eq / peak - 1 < -M.halt_drawdown:
        reasons.append(f"the account is {1 - eq / peak:.0%} below its peak; the mandate halts at {M.halt_drawdown:.0%}")
    if prev and eq and eq / prev - 1 < -M.halt_day_loss:
        reasons.append(f"the account is {1 - eq / prev:.0%} below yesterday; the mandate halts at {M.halt_day_loss:.0%}")
    last = history.get("last_ticket_date")
    if last:
        days = (now.date() - datetime.fromisoformat(last).date()).days
        if days < M.min_days_between_tickets:
            reasons.append(f"a ticket executed {days} day(s) ago; the mandate wants {M.min_days_between_tickets}")
    today = now.date().isoformat()
    if today in set(M.quiet_days):
        reasons.append(f"{today} is a quiet day in the mandate")
    return {"ok": not reasons, "reasons": reasons, "mandate_hash": M.hash(), "mode": M.mode, "armed": M.armed, "checked_at": now.isoformat(timespec="seconds")}


def in_window(M: Mandate, now: datetime | None = None) -> tuple[bool, str]:
    """Inside the mandate's New York trading window on a weekday? (US market holidays are not known here; a
    holiday produces no fills, and the trader treats an unfilled day as nothing happened.)"""
    from zoneinfo import ZoneInfo
    now = now or datetime.now(timezone.utc)
    ny = now.astimezone(ZoneInfo("America/New_York"))
    if ny.weekday() >= 5:
        return False, f"{ny.strftime('%A')} is not a trading day"
    hm = ny.strftime("%H:%M")
    if not (M.window_start <= hm <= M.window_end):
        return False, f"{hm} New York is outside {M.window_start} to {M.window_end}"
    return True, f"{hm} New York, inside the window"
