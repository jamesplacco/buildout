"""Market reads from the free FRED run: what moved, the price of insurance, and the plumbing.

Three blocks for macro.json:
  moves      one row per market: level, 1-day to 1-year changes, and how unusual this week's change is
  vol        implied against realized volatility (the volatility risk premium) and the VIX term structure
  liquidity  Fed balance sheet net of the Treasury's cash and reverse repo, bank reserves, SOFR minus IORB

Units follow FRED: WALCL and WTREGEN are millions of dollars, RRPONTSYD and WRESBAL billions, rates percent.
Liquidity figures are reported in trillions of dollars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import roc
from .jsonout import series

# (key, label, FRED id or (a, b) for a - b, kind). kind: pct (prices), bp (yields and spreads), pts (vol indexes)
MOVES = [
    ("ndx", "Nasdaq-100", "NASDAQ100", "pct"),
    ("spx", "S&P 500", "SP500", "pct"),
    ("y2", "2-year Treasury", "DGS2", "bp"),
    ("y10", "10-year Treasury", "DGS10", "bp"),
    ("y30", "30-year Treasury", "DGS30", "bp"),
    ("c2s10s", "2s10s curve", ("DGS10", "DGS2"), "bp"),
    ("real10", "10-year real yield", "DFII10", "bp"),
    ("be10", "10-year breakeven", "T10YIE", "bp"),
    ("ig", "Investment-grade spread", "BAMLC0A0CM", "bp"),
    ("hy", "High-yield spread", "BAMLH0A0HYM2", "bp"),
    ("ccc", "CCC spread", "BAMLH0A3HYC", "bp"),
    ("vix", "VIX", "VIXCLS", "pts"),
    ("vxn", "Nasdaq-100 volatility (VXN)", "VXNCLS", "pts"),
    ("brent", "Brent crude", "DCOILBRENTEU", "pct"),
    ("dollar", "Broad dollar", "DTWEXBGS", "pct"),
    ("usdjpy", "Yen per dollar", "DEXJPUS", "pct"),
    ("btc", "Bitcoin", "CBBTCUSD", "pct"),
]
VOL_PAIRS = [("spx", "S&P 500", "SP500", "VIXCLS"), ("ndx", "Nasdaq-100", "NASDAQ100", "VXNCLS")]
TERM_IDS = ("VIXCLS", "VXVCLS")                      # VIX and 3-month VIX
LIQ_IDS = ["WALCL", "WTREGEN", "RRPONTSYD", "WRESBAL", "SOFR", "IORB"]
# v0.5 macro state: inflation (the hedge line), labor, the curve, financial conditions
MACRO_IDS = ["CPIAUCSL", "SAHMREALTIME", "UNRATE", "T10Y3M", "NFCI", "ICSA",
             "UMCSENT", "PCEC96", "DHHNGSP", "DRTSCILM", "MORTGAGE30US"]   # v0.6: the field manual's monitors
HEDGE_LINE = 0.0275   # average inflation over 36 months above which bonds rarely hedged stocks, 1871-2026
MIN_Z_OBS = 100                                      # fewer seven-day changes than this: no z-score


def ids() -> list[str]:
    out: list[str] = []
    for _, _, sid, _ in MOVES:
        out += list(sid) if isinstance(sid, tuple) else [sid]
    for _, _, px, iv in VOL_PAIRS:
        out += [px, iv]
    out += list(TERM_IDS) + LIQ_IDS + MACRO_IDS
    return list(dict.fromkeys(out))


def _col(fred: pd.DataFrame, sid) -> pd.Series | None:
    if isinstance(sid, tuple):
        a, b = sid
        if a not in fred or b not in fred:
            return None
        s = (fred[a] - fred[b]).dropna()
    else:
        if sid not in fred:
            return None
        s = fred[sid].dropna()
    return s.astype(float) if len(s) else None


def _at(s: pd.Series, when: pd.Timestamp) -> float | None:
    x = s.loc[:when]
    return float(x.iloc[-1]) if len(x) else None


def change(kind: str, a: float | None, b: float | None) -> float | None:
    """Change from a to b in the unit the desk quotes: percent for prices, basis points for rates, points for vol."""
    if a is None or b is None or not np.isfinite(a) or not np.isfinite(b):
        return None
    if kind == "pct":
        return b / a - 1 if a > 0 else None
    if kind == "bp":
        return (b - a) * 100
    return b - a


def weekly_z(s: pd.Series, kind: str, years: int = 3) -> float | None:
    """This week's change in standard deviations of every seven-day change over the past `years` (log changes for prices)."""
    last = s.index[-1]
    daily = s.loc[last - pd.DateOffset(years=years) - pd.Timedelta(days=7):].resample("D").last().ffill()
    if kind == "pct":
        daily = np.log(daily.where(daily > 0))
    ch = (daily - daily.shift(7)).dropna()
    if len(ch) < MIN_Z_OBS:
        return None
    sd = float(ch.std())
    if not np.isfinite(sd) or sd <= 0:
        return None
    return float((ch.iloc[-1] - ch.mean()) / sd)


def move_row(key: str, label: str, s: pd.Series, kind: str) -> dict:
    last, v = s.index[-1], float(s.iloc[-1])
    prev = float(s.iloc[-2]) if len(s) > 1 else None
    row = {"key": key, "label": label, "kind": kind, "value": v, "date": last.strftime("%Y-%m-%d"),
           "d1": change(kind, prev, v),
           "w1": change(kind, _at(s, last - pd.Timedelta(days=7)), v),
           "m1": change(kind, _at(s, last - pd.DateOffset(months=1)), v),
           "ytd": change(kind, _at(s, pd.Timestamp(last.year - 1, 12, 31)), v),
           "y1": change(kind, _at(s, last - pd.DateOffset(years=1)), v),
           "z_w1": weekly_z(s, kind)}
    if kind != "pct":                              # where today's level sits in ten years (yields, spreads, vol)
        ten = s.loc[last - pd.DateOffset(years=10):]
        row["rank10y"] = float((ten <= v).mean()) if len(ten) >= 250 else None
    row["spark"] = series(s.loc[last - pd.DateOffset(years=1):])
    # rates of change in the unit the desk quotes: bp per week for rates, points per week for vol, % per week for prices
    if kind == "pct":
        row.update(roc.roc_row(np.log(s.where(s > 0)).dropna(), scale=100))
    else:
        row.update(roc.roc_row(s, scale=100 if kind == "bp" else 1))
    return row


def moves_block(fred: pd.DataFrame) -> list[dict]:
    rows = []
    for key, label, sid, kind in MOVES:
        s = _col(fred, sid)
        if s is not None and len(s) >= 2:
            rows.append(move_row(key, label, s, kind))
    return rows


def realized_vol(px: pd.Series, n: int = 21) -> pd.Series:
    """Annualized close-to-close volatility over n trading days, in vol points (20 = 20%)."""
    r = np.log(px.where(px > 0)).diff()
    return r.rolling(n).std() * np.sqrt(252) * 100


def _rank(s: pd.Series, v: float, years: int = 10) -> float | None:
    w = s.loc[s.index[-1] - pd.DateOffset(years=years):].dropna()
    return float((w <= v).mean()) if len(w) >= 250 else None


def vol_block(fred: pd.DataFrame) -> dict:
    latest, history = {}, {}
    for key, _, px_id, iv_id in VOL_PAIRS:
        px, iv = _col(fred, px_id), _col(fred, iv_id)
        if px is None or iv is None or len(px) < 30:
            continue
        rv = realized_vol(px)
        both = pd.concat({"iv": iv, "rv": rv}, axis=1).dropna()
        if both.empty:
            continue
        vrp = both["iv"] - both["rv"]
        last = both.index[-1]
        # what the insurance seller actually earned: implied today against what the next month realized
        earned = (both["iv"] - both["rv"].shift(-21)).dropna()
        e5 = earned.loc[last - pd.DateOffset(years=5):]
        latest[key] = {"date": last.strftime("%Y-%m-%d"), "implied": float(both["iv"].iloc[-1]),
                       "realized": float(both["rv"].iloc[-1]), "vrp": float(vrp.iloc[-1]),
                       "implied_rank10y": _rank(both["iv"], float(both["iv"].iloc[-1])),
                       "vrp_rank10y": _rank(vrp, float(vrp.iloc[-1])),
                       "vrp_median10y": float(vrp.loc[last - pd.DateOffset(years=10):].median()),
                       "earned_mean5y": float(e5.mean()) if len(e5) >= 60 else None,
                       "earned_share_positive5y": float((e5 > 0).mean()) if len(e5) >= 60 else None}
        since = last - pd.DateOffset(years=8)
        history[key] = {"implied": series(both["iv"].loc[since:]), "realized": series(both["rv"].loc[since:])}
    vix, vix3m = _col(fred, TERM_IDS[0]), _col(fred, TERM_IDS[1])
    if vix is not None and vix3m is not None:
        t = pd.concat({"vix": vix, "vix3m": vix3m}, axis=1).dropna()
        t = t[t["vix3m"] > 0]
        if len(t):
            ratio = t["vix"] / t["vix3m"]
            last = ratio.index[-1]
            latest["term"] = {"date": last.strftime("%Y-%m-%d"), "ratio": float(ratio.iloc[-1]), "vix": float(t["vix"].iloc[-1]),
                              "vix3m": float(t["vix3m"].iloc[-1]), "rank10y": _rank(ratio, float(ratio.iloc[-1])),
                              "days_inverted_1y": int((ratio.loc[last - pd.DateOffset(years=1):] > 1).sum())}
            history["term"] = series(ratio.loc[last - pd.DateOffset(years=8):])
    return {"latest": latest, "history": history}


def liquidity_block(fred: pd.DataFrame) -> dict:
    latest, history = {}, {}
    assets, tga, rrp = _col(fred, "WALCL"), _col(fred, "WTREGEN"), _col(fred, "RRPONTSYD")
    if assets is not None and tga is not None and rrp is not None:
        # align on the Fed's Wednesday: assets and TGA are weekly, reverse repo daily (take that Wednesday's print)
        r = rrp.reindex(assets.index, method="ffill")
        t = tga.reindex(assets.index, method="ffill")
        net = (assets / 1e6 - t / 1e6 - r / 1e3).dropna()          # trillions
        if len(net):
            last = net.index[-1]
            def back(weeks: int) -> float | None:
                prev = _at(net, last - pd.Timedelta(weeks=weeks))
                return None if prev is None else float(net.iloc[-1] - prev)
            latest["net"] = {"date": last.strftime("%Y-%m-%d"), "value": float(net.iloc[-1]),
                             "fed_assets": float(assets.loc[last] / 1e6), "tga": float(t.loc[last] / 1e6),
                             "rrp": float(r.loc[last] / 1e3), "chg_13w": back(13), "chg_52w": back(52)}
            history["net"] = series(net.loc[last - pd.DateOffset(years=8):], freq=None)
    res = _col(fred, "WRESBAL")
    if res is not None:
        last = res.index[-1]
        prev = _at(res, last - pd.Timedelta(weeks=13))
        latest["reserves"] = {"date": last.strftime("%Y-%m-%d"), "value": float(res.iloc[-1] / 1e3),
                              "chg_13w": None if prev is None else float((res.iloc[-1] - prev) / 1e3)}
    sofr, iorb = _col(fred, "SOFR"), _col(fred, "IORB")
    if sofr is not None and iorb is not None:
        both = pd.concat({"sofr": sofr, "iorb": iorb.reindex(sofr.index, method="ffill")}, axis=1).dropna()
        if len(both):
            gap = (both["sofr"] - both["iorb"]) * 100
            last = gap.index[-1]
            latest["funding"] = {"date": last.strftime("%Y-%m-%d"), "sofr": float(both["sofr"].iloc[-1]),
                                 "iorb": float(both["iorb"].iloc[-1]), "gap_bp": float(gap.iloc[-1]),
                                 "gap_5d_bp": float(gap.iloc[-5:].mean()),
                                 "gap_max_3m_bp": float(gap.loc[last - pd.DateOffset(months=3):].max()),
                                 "days_above_1y": int((gap.loc[last - pd.DateOffset(years=1):] > 0).sum())}
            history["funding_gap_bp"] = series(gap.loc[last - pd.DateOffset(years=3):], freq=None)
    return {"latest": latest, "history": history}


def monthly_roc(s: pd.Series, name: str) -> dict:
    """Rates of change of a monthly series, per month: v3 is the least-squares slope of the last four prints
    (three months, the monthly twin of the 13-week pace), v1 the last one-month change, a3 = v3 now minus v3
    three months earlier."""
    def slope(w: pd.Series) -> float | None:
        return float(np.polyfit(np.arange(len(w)), w.to_numpy(), 1)[0]) if len(w) == 4 and w.notna().all() else None
    v3, v3p = slope(s.iloc[-4:]), slope(s.iloc[-7:-3])
    return {f"{name}_v3": v3, f"{name}_v1": float(s.iloc[-1] - s.iloc[-2]) if len(s) > 1 else None,
            f"{name}_a3": v3 - v3p if v3 is not None and v3p is not None else None}


def macro_state_block(fred: pd.DataFrame) -> dict:
    """Inflation against the hedge line, the labor market, the curve and financial conditions."""
    out: dict = {"hedge_line": HEDGE_LINE}
    cpi = _col(fred, "CPIAUCSL")
    if cpi is not None and len(cpi) > 37:
        # complete calendar: BLS published no October 2025 CPI, and a dropped month turns 12-month changes into 13-month ones
        m = np.exp(np.log(cpi.resample("MS").last()).interpolate(limit=2, limit_area="inside")).dropna()
        last = m.index[-1]
        yoy = float(m.iloc[-1] / m.iloc[-13] - 1)
        infl36 = float((m.iloc[-1] / m.iloc[-37]) ** (1 / 3) - 1)
        # months until the 36-month average falls below the line if inflation from here runs at 2% a year
        months, path = None, list(m.to_numpy())
        for k in range(1, 61):
            path.append(path[-1] * (1.02 ** (1 / 12)))
            if (path[-1] / path[-37]) ** (1 / 3) - 1 < HEDGE_LINE:
                months = k
                break
        yoy_s = (m / m.shift(12) - 1).dropna()
        avg_s = ((m / m.shift(36)) ** (1 / 3) - 1).dropna()
        out["inflation"] = {"date": last.strftime("%Y-%m-%d"), "yoy": yoy, "avg36": infl36, "above_line": infl36 >= HEDGE_LINE,
                            "ann3m": float((m.iloc[-1] / m.iloc[-4]) ** 4 - 1),
                            "months_to_line_at_2pct": months, "yoy_3m_ago": float(m.iloc[-4] / m.iloc[-16] - 1) if len(m) > 16 else None,
                            **monthly_roc(yoy_s, "yoy"), **monthly_roc(avg_s, "avg36")}
    for key, sid, scale in (("sahm", "SAHMREALTIME", 1), ("unrate", "UNRATE", 1), ("t10y3m", "T10Y3M", 100), ("nfci", "NFCI", 1), ("claims", "ICSA", 1),
                            ("umich", "UMCSENT", 1), ("real_pce", "PCEC96", 1), ("henry_hub", "DHHNGSP", 1), ("sloos_ci", "DRTSCILM", 1),
                            ("mortgage30", "MORTGAGE30US", 1)):
        s = _col(fred, sid)
        if s is None:
            continue
        row = {"date": s.index[-1].strftime("%Y-%m-%d"), "value": float(s.iloc[-1])}
        if sid == "ICSA":
            row["avg4w"] = float(s.iloc[-4:].mean())
        if sid == "PCEC96" and len(s) > 3:          # the manual's trigger: real spending down two months running
            ch = s.diff().dropna()
            row["down_2m"] = bool(ch.iloc[-1] < 0 and ch.iloc[-2] < 0)
        row.update(roc.roc_row(s, scale=scale))
        out[key] = row
    return out
