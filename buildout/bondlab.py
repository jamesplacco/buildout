"""Bonds, broken down to what they are: promised cash flows discounted at a yield.

A Treasury ETF is a ladder of such bonds. Set where the 10-year and 30-year yields go and this module reprices each
fund bond by bond, so the answer carries convexity and the shape of the curve, not just a duration rule of thumb:

  curve      today's par curve, moved so the 10-year and 30-year land exactly where you set them: maturities from 10
             to 30 years move by a straight-line blend of the two moves, shorter ones by the 10-year's move (or
             anchored at the front end), and today's bumps in the curve (the 20-year sitting above the line) are kept
  funds      each ETF as an equal-face ladder across its maturity range, with one coupon calibrated so the ladder's
             modified duration equals the duration the issuer reports (zero-coupon funds hold STRIPS)
  scenario   the price now and at the new yields, the instant gain or loss, the 12-month total return with income, the
             break-even yield rise (how far yields can rise before a year's income is gone) and the grid of prices
             over a range of 10-year and 30-year yields
  stocks     the measured read-through: how the S&P 500 has moved per point of 10-year yield change, by inflation
             regime, since 1871 (bonds and stocks fall together when inflation is the story, and diverge when growth is)

Python is canonical; site/src/bondlab.js runs the same functions (tests/test_v17.py holds them equal).
"""
from __future__ import annotations

import math

import numpy as np


TENORS = [1 / 12, 2 / 12, 3 / 12, 4 / 12, 6 / 12, 1, 2, 3, 5, 7, 10, 20, 30]
TENOR_KEYS = ["1m", "2m", "3m", "4m", "6m", "1y", "2y", "3y", "5y", "7y", "10y", "20y", "30y"]
FUNDS = {
    "SHY": {"name": "iShares 1-3 Year Treasury Bond ETF", "lo": 1, "hi": 3, "zero": False},
    "IEI": {"name": "iShares 3-7 Year Treasury Bond ETF", "lo": 3, "hi": 7, "zero": False},
    "IEF": {"name": "iShares 7-10 Year Treasury Bond ETF", "lo": 7, "hi": 10, "zero": False},
    "TLH": {"name": "iShares 10-20 Year Treasury Bond ETF", "lo": 10, "hi": 20, "zero": False},
    "TLT": {"name": "iShares 20+ Year Treasury Bond ETF", "lo": 20, "hi": 30, "zero": False},
    "EDV": {"name": "Vanguard Extended Duration Treasury ETF (STRIPS)", "lo": 20, "hi": 30, "zero": True},
    "ZROZ": {"name": "PIMCO 25+ Year Zero Coupon US Treasury ETF", "lo": 25, "hi": 30, "zero": True},
}
STEP = 0.5   # ladder spacing in years
LOW, HIGH = 0.0275, 0.0425   # 36-month annualized inflation bands for the stock read-through


def times(T: float) -> list[float]:
    """Coupon dates counted back from maturity every half year (a bond of 20.25 years pays at 0.25, 0.75, ... 20.25)."""
    return [T - j / 2 for j in range(int(math.floor(T * 2 + 1e-9)) + 1) if T - j / 2 > 1e-9]


def bond_price(y: float, T: float, c: float, shift: float = 0.0) -> float:
    """Price per 100 face of a bond with T years left and semiannual coupon c (decimal), discounted at y; `shift` years
    later, the cash flows still to come only."""
    pv = 0.0
    for t in times(T):
        u = t - shift
        if u > 1e-9:
            pv += (100 * c / 2 + (100 if t == T else 0)) * (1 + y / 2) ** (-2 * u)
    return pv


def interp(curve: dict, T: float) -> float:
    """Linear interpolation of a par curve given as {tenor key: yield in decimals}, flat beyond the ends."""
    xs = [t for t, k in zip(TENORS, TENOR_KEYS) if curve.get(k) is not None]
    ys = [curve[k] for k in TENOR_KEYS if curve.get(k) is not None]
    if T <= xs[0]:
        return ys[0]
    if T >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if T <= xs[i]:
            w = (T - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + w * (ys[i] - ys[i - 1])
    return ys[-1]


def shift_at(T: float, d10: float, d30: float, front: str = "parallel") -> float:
    """How far the yield at maturity T moves when the 10-year moves d10 and the 30-year d30 (decimals)."""
    if T >= 10:
        return d10 + (d30 - d10) * min(1.0, (T - 10) / 20)
    if front == "anchored":                                   # the front end held by the policy rate, ramping to the 10-year
        return d10 * max(0.0, (T - 1) / 9)
    return d10


def moved(curve: dict, T: float, y10: float, y30: float, front: str = "parallel") -> float:
    return interp(curve, T) + shift_at(T, y10 - curve["10y"], y30 - curve["30y"], front)


def ladder(f: dict) -> list[float]:
    """Equal-face maturities across the fund's range, or across the widest sub-range centred on the weighted average
    maturity the issuer reports (TLT's 26 years sits above the 25-year middle of 20 to 30, so its ladder runs 22 to 30)."""
    a, b = f.get("a", f["lo"]), f.get("b", f["hi"])
    n = max(2, int(round((b - a) / STEP)))
    h = (b - a) / n
    return [a + h * (i + 0.5) for i in range(n)]


def centre(f: dict, wam: float | None) -> dict:
    if not wam or not (f["lo"] < wam < f["hi"]):
        return f
    half = min(wam - f["lo"], f["hi"] - wam)
    return {**f, "a": wam - half, "b": wam + half}


def calibrate(curve: dict, f: dict, duration: float | None) -> float:
    """One coupon for the whole ladder, so its modified duration matches the reported one; STRIPS pay none. Without a
    reported duration, the coupon is today's par yield at the ladder's middle maturity (bonds bought at par today)."""
    if f["zero"]:
        return 0.0
    mats = ladder(f)
    mid = interp(curve, sum(mats) / len(mats))
    if not duration:
        return mid
    lo, hi = 0.0, 0.25
    dur = lambda c: fund_duration(curve, mats, c)
    if not (dur(hi) <= duration <= dur(lo)):
        return mid
    for _ in range(60):
        mid = (lo + hi) / 2
        if dur(mid) > duration:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def fund_value(curve: dict, mats: list[float], c: float, y10: float | None = None, y30: float | None = None, front: str = "parallel", shift: float = 0.0) -> float:
    y10 = curve["10y"] if y10 is None else y10
    y30 = curve["30y"] if y30 is None else y30
    return sum(bond_price(moved(curve, T, y10, y30, front), T, c, shift) for T in mats) / len(mats)


def fund_horizon(curve: dict, mats: list[float], c: float, y10: float, y30: float, front: str = "parallel", h: float = 1.0) -> float:
    """What the ladder is worth after h years if the yields move now and then hold: each bond is priced at the moved
    curve's yield for its remaining maturity (so it earns the roll down the curve), plus the coupons and principal it
    paid along the way (held as cash)."""
    tot = 0.0
    for T in mats:
        got = sum(100 * c / 2 + (100 if t == T else 0) for t in times(T) if t <= h + 1e-9)
        pv = bond_price(moved(curve, max(T - h, 1 / 12), y10, y30, front), T, c, h) if T - h > 1e-9 else 0.0
        tot += pv + got
    return tot / len(mats)


def fund_duration(curve: dict, mats: list[float], c: float, h: float = 1e-4) -> float:
    """Modified duration of the ladder to a parallel move of the whole curve."""
    p0 = sum(bond_price(interp(curve, T), T, c) for T in mats)
    up = sum(bond_price(interp(curve, T) + h, T, c) for T in mats)
    dn = sum(bond_price(interp(curve, T) - h, T, c) for T in mats)
    return (dn - up) / (2 * p0 * h)


def fund_convexity(curve: dict, mats: list[float], c: float, h: float = 1e-4) -> float:
    p0 = sum(bond_price(interp(curve, T), T, c) for T in mats)
    up = sum(bond_price(interp(curve, T) + h, T, c) for T in mats)
    dn = sum(bond_price(interp(curve, T) - h, T, c) for T in mats)
    return (up + dn - 2 * p0) / (p0 * h * h)


def fund_yield(curve: dict, mats: list[float], c: float) -> float:
    """The ladder's yield: the single yield that prices it at today's value."""
    v = sum(bond_price(interp(curve, T), T, c) for T in mats)
    lo, hi = -0.05, 0.30
    for _ in range(100):
        mid = (lo + hi) / 2
        if sum(bond_price(mid, T, c) for T in mats) > v:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def setup(curve: dict, facts: dict | None = None) -> dict:
    """Each fund's ladder, coupon, duration, convexity and yield on today's curve; facts give reported durations and
    prices ({ticker: {"duration": .., "price": .., "as_of": ..}})."""
    facts = facts or {}
    out = {}
    for t, f in FUNDS.items():
        fa = facts.get(t, {})
        f = centre(f, fa.get("wam"))
        c = calibrate(curve, f, fa.get("duration"))
        mats = ladder(f)
        out[t] = {**f, "mats": mats, "coupon": c, "duration": fund_duration(curve, mats, c), "convexity": fund_convexity(curve, mats, c),
                  "ytm": fund_yield(curve, mats, c), "price": fa.get("price"), "price_as_of": fa.get("as_of"), "reported_duration": fa.get("duration"), "wam": fa.get("wam"), "ytm_reported": fa.get("ytm")}
    return out


def scenario(curve: dict, funds: dict, y10: float, y30: float, front: str = "parallel", horizon: float = 1.0) -> dict:
    """Every fund at the new 10-year and 30-year yields: price, instant change, total return over the horizon (the
    shock happens now and the yields then hold; coupons and roll-down are earned)."""
    out = {}
    for t, f in funds.items():
        mats, c = f["mats"], f["coupon"]
        v0 = fund_value(curve, mats, c)
        v1 = fund_value(curve, mats, c, y10, y30, front)
        ch = v1 / v0 - 1
        tr = fund_horizon(curve, mats, c, y10, y30, front, horizon) / v0 - 1
        out[t] = {"change": ch, "total": tr, "price": None if f.get("price") is None else f["price"] * (1 + ch),
                  "price_total": None if f.get("price") is None else f["price"] * (1 + tr)}
    return out


def breakeven(f: dict) -> float:
    """The parallel rise in yields that wipes out a year of income: yield / duration (first order)."""
    return f["ytm"] / f["duration"] if f["duration"] else float("nan")


def grid(curve: dict, f: dict, lo: float = 0.03, hi: float = 0.07, step: float = 0.005, front: str = "parallel") -> dict:
    ys = [round(lo + i * step, 6) for i in range(int(round((hi - lo) / step)) + 1)]
    mats, c = f["mats"], f["coupon"]
    v0 = fund_value(curve, mats, c)
    return {"y": ys, "change": [[fund_value(curve, mats, c, a, b, front) / v0 - 1 for b in ys] for a in ys]}


def equity_readthrough(S) -> dict:
    """Monthly real S&P 500 return regressed on the month's change in the long yield, overall and by 36-month
    inflation regime (Shiller's data since 1871; Newey-West t). The slope is the measured percent move in stocks per
    one point of yield."""
    import pandas as pd
    from . import labs
    r, _, _ = labs.total_return_index(S)
    dy = (S["y10"] / 100).diff().reindex(r.index)
    infl = (np.log(S["cpi"] / S["cpi"].shift(36)) / 3).reindex(r.index)
    D = pd.DataFrame({"r": r, "dy": dy, "infl": infl}).dropna()
    out = {}
    iv = D["infl"].to_numpy()
    for name, m in (("all", np.ones(len(D), bool)), ("low_inflation", iv < LOW), ("middle_inflation", (iv >= LOW) & (iv <= HIGH)), ("high_inflation", iv > HIGH),
                    ("since_2000", D.index.year.to_numpy() >= 2000)):
        x, y = D["dy"].to_numpy()[m], D["r"].to_numpy()[m]
        if len(x) < 60:
            continue
        fit = labs.nw_ols(y, x, 6)
        out[name] = {"per_point": float(fit["b"][1]) / 100, "t": float(fit["t"][1]), "n": int(len(x)), "r2": float(fit["r2"])}
    full = (np.log(S["cpi"] / S["cpi"].shift(36)) / 3).dropna()
    now = float(full.iloc[-1])
    out["now"] = {"infl36": now, "as_of": full.index[-1].strftime("%Y-%m"), "regime": regime(now)}
    return out


# ---------------------------------------------------------------- reading a yield question (the mind uses this)
RX_NUM = r"(-?\d+(?:\.\d+)?)\s*(%|percent|pct|bps|bp|basis points)"
RX_TEN = r"\b(?:10|ten)[\s-]*(?:yr|y|year)s?\b"
RX_THIRTY = r"\b(?:30|thirty)[\s-]*(?:yr|y|year)s?\b"
RX_BOTH = r"\b(?:both|yields|rates|treasuries|treasury yields|the curve|long yields|bond yields|tlt|ief|tlh|edv|zroz|bonds)\b"
RX_PAIR = r"\b(?:10|ten)(?:[\s-]*(?:yr|y|year)s?)?\s*(?:and|&|/|,)\s*(?:the\s+)?(?:30|thirty)[\s-]*(?:yr|y|year)s?\b"
RX_GAP = r"[^%\d]{0,40}?"
RX_DOWN = r"\b(?:down|fall|falls|fell|drop|drops|lower|cut|decline|declines|rally|rallies)\b"


def _val(num: str, unit: str) -> tuple[float, bool]:
    """(decimal, relative?) from a number and its unit: 4% is a level, 50bp is a move."""
    x = float(num)
    if unit in ("bps", "bp", "basis points"):
        return x / 10000, True
    return x / 100, False


def parse(text: str, curve: dict) -> dict | None:
    """The 10-year and 30-year yields a question sets, or None. "if the 10yr and 30yr both go to 4%" sets both to 4%;
    "the 10-year at 6%" sets the 10-year and moves the 30-year by the same amount; "yields down 50bp" moves both."""
    import re
    t = text.lower().replace(chr(0x2011), "-").replace(chr(0x2013), "-")
    y10 = y30 = None

    def grab(rx):
        m = re.search(rx + RX_GAP + RX_NUM, t)
        if not m:
            return None
        v, rel = _val(m.group(1), m.group(2))
        if rel and re.search(RX_DOWN, m.group(0)):
            v = -abs(v)
        return v, rel

    pair = grab(RX_PAIR) or grab(RX_BOTH)
    ten, thirty = grab(RX_TEN), grab(RX_THIRTY)
    if pair and not (ten and thirty and not re.search(RX_PAIR, t)):
        v, rel = pair
        y10, y30 = (curve["10y"] + v, curve["30y"] + v) if rel else (v, v)
    else:
        if ten:
            y10 = curve["10y"] + ten[0] if ten[1] else ten[0]
        if thirty:
            y30 = curve["30y"] + thirty[0] if thirty[1] else thirty[0]
        if y10 is None and y30 is None:
            return None
        if y30 is None:
            y30 = curve["30y"] + (y10 - curve["10y"])
        if y10 is None:
            y10 = curve["10y"] + (y30 - curve["30y"])
    if not (0.0 <= y10 <= 0.2 and 0.0 <= y30 <= 0.2):
        return None
    return {"y10": round(y10, 6), "y30": round(y30, 6)}


def regime(infl36: float) -> str:
    return "low_inflation" if infl36 < LOW else "high_inflation" if infl36 > HIGH else "middle_inflation"


def from_knowledge(know: list[dict]) -> tuple[dict, dict, dict]:
    """Today's par curve and each fund's reported duration, average maturity, yield and price from the checked
    knowledge items (bd-par-*, bd-<ticker>-*, tp-<ticker>-close-*). Returns (curve, facts, curve_meta)."""
    K = {k["id"]: k for k in know}
    curve, dates = {}, set()
    for key in TENOR_KEYS:
        it = K.get("bd-par-" + key)
        if it and it.get("value") is not None:
            curve[key] = it["value"] / 100
            dates.add(it.get("as_of"))
    facts = {}
    for t in list(FUNDS) + ["GOVT", "SPTL", "VGLT", "TLTW"]:
        lo = t.lower()
        g = lambda k: K.get(f"bd-{lo}-{k}")
        f = {}
        if g("duration"):
            f["duration"], f["duration_as_of"] = g("duration")["value"], g("duration")["as_of"]
        if g("wam"):
            f["wam"] = g("wam")["value"]
        if g("ytm"):
            f["ytm"] = g("ytm")["value"] / 100
        if g("sec-yield"):
            f["sec_yield"] = g("sec-yield")["value"] / 100
        px = next((K[k] for k in sorted(K, reverse=True) if k.startswith(f"tp-{lo}-close-")), None) or g("close-price") or g("nav")
        if px and px.get("value") is not None:
            v = px["value"]
            if px["id"].startswith("tp-") and str(px.get("unit", "")).lower() not in ("usd", "usd per share"):
                import re                                           # an older tape item's value is the % move; the close is in the text
                m = re.search(r"\$(\d+(?:\.\d+)?)", px["text"])
                v = float(m.group(1)) if m else None
            if v is not None:
                f["price"], f["as_of"], f["price_src"] = v, px.get("as_of"), px["id"]
        if f:
            facts[t] = f
    return curve, facts, {"as_of": sorted(d for d in dates if d)[-1] if dates else None, "source": "US Treasury daily par yield curve"}


TREASURY_KEYS = {"1 Mo": "1m", "2 Mo": "2m", "3 Mo": "3m", "4 Mo": "4m", "6 Mo": "6m", "1 Yr": "1y", "2 Yr": "2y", "3 Yr": "3y", "5 Yr": "5y", "7 Yr": "7y",
                 "10 Yr": "10y", "20 Yr": "20y", "30 Yr": "30y"}


def from_treasury(d: dict) -> dict:
    """datahub.treasury_curve() output ({"date", "curve": {"1 Mo": 0.0409, ...}}) as this module's curve."""
    return {TREASURY_KEYS[k]: v for k, v in (d.get("curve") or {}).items() if k in TREASURY_KEYS}


def answer(y10: float, y30: float, front: str = "parallel", curve: dict | None = None, facts: dict | None = None) -> dict:
    """One question, answered: every fund at the 10-year and 30-year yields given (decimals), on today's curve from
    the checked knowledge unless a curve is passed."""
    if curve is None or facts is None:
        from . import mind
        c0, f0, _ = from_knowledge(mind.load_knowledge())
        curve, facts = curve or c0, facts if facts is not None else f0
    funds = setup(curve, facts)
    sc = scenario(curve, funds, y10, y30, front)
    return {"y10": y10, "y30": y30, "front": front, "curve": curve,
            "funds": {t: {"duration": funds[t]["duration"], "reported_duration": funds[t]["reported_duration"], "ytm": funds[t]["ytm"], "price_now": funds[t]["price"],
                          "price_at": sc[t]["price"], "price_12m": sc[t]["price_total"], "change": sc[t]["change"], "total": sc[t]["total"], "breakeven": breakeven(funds[t])} for t in funds}}


def build(curve: dict, facts: dict | None = None, S=None) -> dict:
    funds = setup(curve, facts)
    pub = {t: {k: v for k, v in f.items() if k != "mats"} for t, f in funds.items()}
    cases = {}
    for lab, y10, y30 in (("both_4", 0.04, 0.04), ("both_5", 0.05, 0.05), ("both_6", 0.06, 0.06), ("down_100", curve["10y"] - 0.01, curve["30y"] - 0.01),
                          ("up_100", curve["10y"] + 0.01, curve["30y"] + 0.01)):
        cases[lab] = {"y10": y10, "y30": y30, "funds": scenario(curve, funds, y10, y30)}
    out = {"curve": curve, "funds": pub, "cases": cases, "grid_tlt": grid(curve, funds["TLT"]), "breakeven": {t: breakeven(f) for t, f in funds.items()},
           "step": STEP}
    if S is not None:
        out["equity"] = equity_readthrough(S)
    return out
