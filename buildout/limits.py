"""One evaluator for every limit (v0.48).

Before this, three places compared a portfolio with the limits, each in its own words: the menu of sizes
(sizing_rules.frontier), the recheck at publication (sizing_rules.recheck, scripts/build_site.py) and the planner
(execution.plan). They did not check the same things, and a row could be called compliant by a check that had
left a limit out. Here a limit is checked one way, and the result says what was measured, against what, in which
units, and with how much room:

    {"metric", "value", "limit", "headroom", "units", "kind": "max" | "min", "status": "pass" | "fail" | "unchecked",
     "model", "note"}

    pass        the value is at or inside the limit (a value exactly at the limit passes; TOL is rounding only)
    fail        it is outside
    unchecked   it could not be judged: the value or the limit is missing or not a number, or the two are stated
                in different units. Unchecked is never a pass.

A portfolio is compliant when every required check passes: `summarize` derives that one word from the checks, so
nothing can be called compliant with a required check failed, missing or unjudged.

Exposure has four names, each in multiples of NAV, and they are not interchangeable:

    long          the names held (and any other long sleeve)
    short         the short, as a positive number
    net           long - short
    gross_total   long + short: the economic gross

THE TWO GROSS RULES. The engine has always had two (buildout/config.py): max_gross = 1.50, "leverage cap on the
equity book", a limit on the LONG side; and max_total_gross = 2.00, "equity + bond notional, after every hedge is
added", the limit on the whole (policy limits.portfolio.v1 in buildout/policy.py). The menu of sizes checked
neither, and the page showed the 1.50x as a "gross cap" beside a row of 1.00x long with a 0.85x Nasdaq-100 short,
whose total gross is 1.85x: two quantities under one name. From v0.48 every menu row is checked against both,
by name: `long` <= max_long (1.50x) and `gross_total` <= max_total_gross (2.00x). Neither number is new and
neither was moved. A book.json written before v0.48 carries no max_total_gross; its rows report that check as
"unchecked: no limit set" and it is not among their required ones.

This module is the evaluator. The decision policies themselves (when to hedge, how to size, the portfolio limits
after a hedge) are in buildout/policy.py.
"""
from __future__ import annotations

import math

TOL = 1e-9          # numerical noise only; a limit is a limit
STATUSES = ("pass", "fail", "unchecked")
X_NAV, FRACTION = "x NAV", "fraction of NAV"


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def check(metric: str, value, limit, kind: str = "max", units: str = "", model: str = "", value_units: str | None = None, note: str = "") -> dict:
    """One limit, judged. kind "max": value <= limit. kind "min": value >= limit."""
    if kind not in ("max", "min"):
        raise ValueError(f"kind {kind!r} is not max or min")
    v, lim = _f(value), _f(limit)
    out = {"metric": metric, "value": v, "limit": lim, "headroom": None, "units": units, "kind": kind, "model": model, "status": "unchecked", "note": note}
    if value_units is not None and value_units != units:
        out["note"] = f"the value is in {value_units} and the limit in {units}"
        return out
    if lim is None:
        out["note"] = note or "no limit set"
        return out
    if v is None:
        out["note"] = note or "the value is missing or not a number"
        return out
    out["headroom"] = (lim - v) if kind == "max" else (v - lim)
    out["status"] = "pass" if out["headroom"] >= -TOL else "fail"
    return out


def summarize(checks: list[dict], required: list[str]) -> dict:
    """Compliant only if every required check is present and passes. Names what failed, what was not judged, and
    the limit with the least room (in its own units, relative to the limit)."""
    by = {c["metric"]: c for c in checks}
    failed = [m for m in required if m in by and by[m]["status"] == "fail"]
    unchecked = [m for m in required if m not in by or by[m]["status"] == "unchecked"]
    rel = [(by[m]["headroom"] / abs(by[m]["limit"]) if by[m]["limit"] else by[m]["headroom"], m) for m in required if m in by and by[m]["headroom"] is not None]
    return {"status": "fail" if failed else ("unchecked" if unchecked else "pass"), "meets": not failed and not unchecked,
            "failed": failed, "unchecked": unchecked, "required": list(required), "binding": min(rel)[1] if rel else None}


def exposure(long, short=0.0) -> dict:
    """Long, short, net and total gross, in multiples of NAV. A short may be given with either sign."""
    lg, sh = _f(long), _f(short)
    if lg is None or sh is None:
        return {"long": lg, "short": None if sh is None else abs(sh), "net": None, "gross_total": None, "units": X_NAV}
    sh = abs(sh)
    return {"long": lg, "short": sh, "net": lg - sh, "gross_total": lg + sh, "units": X_NAV}


def risk_limits(L: dict) -> dict:
    """The research limits from a book's `limits` block (or the menu's short names), one spelling."""
    g = lambda *ks: next((L[k] for k in ks if L.get(k) is not None), None)
    return {"es95": g("es_budget", "es"), "vol": g("vol_target", "vol"), "drawdown95": g("max_drawdown", "dd"),
            "long": g("max_long", "max_gross", "long"), "gross_total": g("max_total_gross", "gross_total")}


def required(limits: dict) -> list[str]:
    """The checks a menu row must pass: the three risk limits, the long cap, and total gross when these limits state one."""
    return ["es95", "vol", "drawdown95"] + [m for m in ("long", "gross_total") if _f(limits.get(m)) is not None]


def evaluate_row(row: dict, L: dict, model: str = "") -> dict:
    """A menu row (long `gross`, `short`, and its measured es95, vol, drawdown95) against the limits. Returns the
    checks and their summary; `meets` is the summary's word, never an assertion of the caller's."""
    lim = risk_limits(L)
    ex = exposure(row.get("long", row.get("gross")), row.get("short") or 0.0)
    checks = [check("es95", row.get("es95"), lim["es95"], units=FRACTION + ", one month", model=model),
              check("vol", row.get("vol"), lim["vol"], units="a year", model=model),
              check("drawdown95", row.get("drawdown95"), lim["drawdown95"], units=FRACTION + ", one year", model=model),
              check("long", ex["long"], lim["long"], units=X_NAV, note="" if lim["long"] is not None else "no leverage cap in these limits"),
              check("gross_total", ex["gross_total"], lim["gross_total"], units=X_NAV,
                    note="" if lim["gross_total"] is not None else "no limit on total gross (long plus short) is set")]
    return {"checks": checks, "exposure": ex, **summarize(checks, required(lim))}


def tighter(a: dict | None, b: dict | None) -> dict:
    """Two sets of account limits as one: the lower of two maxima, the higher of two minima. Keys are
    {"max_gross", "max_order_usd", "max_order_pct", "max_turnover_pct"} (maxima) and {"cash_floor"} (a minimum).
    A limit only one side states stands as it is. A key neither knows is an error, not a guess."""
    maxima, minima = {"max_gross", "max_order_usd", "max_order_pct", "max_turnover_pct"}, {"cash_floor"}
    out = {}
    for k in sorted(set(a or {}) | set(b or {})):
        if k not in maxima | minima:
            raise ValueError(f"{k!r} is not a limit this policy knows how to combine")
        vals = [x for x in (_f((a or {}).get(k)), _f((b or {}).get(k))) if x is not None]
        if vals:
            out[k] = min(vals) if k in maxima else max(vals)
    if out.get("max_gross") is not None and out.get("cash_floor") is not None and out["max_gross"] + out["cash_floor"] > 1.0 + TOL:
        out["max_gross"] = 1.0 - out["cash_floor"]          # a cash account: what is not cash is the most that can be held
    return out


def project(positions: dict, cash: float, orders: list[dict], marks: dict, fee_bp: float = 0.0) -> dict:
    """The account the orders would leave, on one basis: every position (the ones no order touches included) at
    its mark, each order at its own price, fees out of cash. Returns shares, cash, the long value, NAV, gross and
    cash as shares of that NAV, and the same for the account before the orders."""
    pos = {str(k).upper(): float(v) for k, v in positions.items() if abs(float(v)) > 1e-12}
    missing = sorted(s for s in pos if _f(marks.get(s)) is None)

    def read(p, c):
        longs = sum(q * (_f(marks.get(s)) or 0.0) for s, q in p.items() if q > 0)
        nav = c + sum(q * (_f(marks.get(s)) or 0.0) for s, q in p.items())
        return {"cash": c, "long_value": longs, "nav": nav, "gross": longs / nav if nav > 0 else None, "cash_share": c / nav if nav > 0 else None}

    before = read(pos, float(cash))
    after_pos, c = dict(pos), float(cash)
    for o in orders or []:
        s, q, px = str(o["symbol"]).upper(), float(o["quantity"]), float(o.get("limit_price", o.get("price")))
        sgn = 1.0 if o["side"] == "buy" else -1.0
        after_pos[s] = after_pos.get(s, 0.0) + sgn * q
        c -= sgn * q * px + q * px * float(fee_bp) / 1e4
        if _f(marks.get(s)) is None and s not in missing:
            missing.append(s)
    after_pos = {k: v for k, v in after_pos.items() if abs(v) > 1e-9}
    return {"before": before, "after": {**read(after_pos, c), "positions": after_pos}, "missing_marks": sorted(missing)}


def account_checks(proj: dict, limits: dict, buys: float = 0.0) -> dict:
    """The projected account against max_gross and cash_floor, both on the projected NAV.

    An account already outside a limit may be repaired: a ticket with no buy that moves the breached figure toward
    its limit passes that check, and the breach is reported with it. Anything else outside a limit fails."""
    b, a = proj["before"], proj["after"]
    checks = []
    for metric, kind, key, limit in (("gross", "max", "gross", limits.get("max_gross")), ("cash", "min", "cash_share", limits.get("cash_floor"))):
        c = check(metric, a[key] if not proj["missing_marks"] else None, limit, kind=kind, units=FRACTION,
                  note="a held position has no mark: " + ", ".join(proj["missing_marks"]) if proj["missing_marks"] else "")
        if c["status"] == "fail" and buys <= 1e-9 and b[key] is not None:
            better = a[key] < b[key] - TOL if kind == "max" else a[key] > b[key] + TOL
            was_out = check(metric, b[key], limit, kind=kind, units=FRACTION)["status"] == "fail"
            if was_out and better:
                c.update({"status": "pass", "repair": True,
                          "note": f"the account was already outside this limit ({b[key]:.4f}); the ticket only sells, and moves it toward the limit ({a[key]:.4f})"})
        checks.append(c)
    return {"checks": checks, **summarize(checks, ["gross", "cash"])}
