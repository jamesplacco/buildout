"""The mind's memory of market history: every month since 1871 as a node, each year, and the famous episodes, built
from Shiller's monthly data so every number is measured, not remembered.

  months     one node per month: valuation (CAPE and its percentile so far), the 10-year yield, inflation, how far real
             prices stood below their prior peak, and what the next 12 months returned (once known)
  analogs    each month linked to the 8 months most like it on valuation, rates, inflation, trend, volatility and
             drawdown, never within three years of itself: thinking about a month recalls the months that looked the same
  years      a node per year with its real total return and the year's worst drawdown
  episodes   named periods with fixed dates (the 1929 crash, the Great Inflation, the dot-com bust...), with the measured
             fall, the move in yields and valuation over the window
  now        the latest month and its nearest analogs, with the median and the spread of what followed them

Layout: months lie on a spiral, one turn per decade, so the history reads as a clock face from 1871 at the centre.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import labs, ml
from .core import cache

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
LONG = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
ANALOG_K = 8
ANALOG_GAP = 36           # months: an analog must be at least three years away
ANALOG_FEATURES = ["log_cape", "y10", "infl12", "trend_gap", "vol12", "drawdown"]

# Named periods with conventional dates (start and end months). The numbers shown for each are computed from the data.
EPISODES = [
    ("panic-1873", "Panic of 1873", "1873-01", "1877-06", "A railroad-finance bust that began with the failure of Jay Cooke and Company in September 1873 and a long depression after it.", ["history", "crisis"]),
    ("panic-1893", "Panic of 1893", "1893-01", "1896-08", "A bank and railroad panic, a run on gold and a deep depression.", ["history", "crisis"]),
    ("panic-1907", "Panic of 1907", "1906-01", "1907-11", "A trust-company run in New York, stopped when J. P. Morgan organized the banks; it led to the founding of the Federal Reserve in 1913.", ["history", "crisis"]),
    ("depression-1920", "The 1920 to 1921 depression", "1919-07", "1921-08", "A sharp postwar deflation and recession, with prices falling as the Fed raised rates.", ["history", "deflation"]),
    ("roaring-twenties", "The 1920s boom", "1921-08", "1929-09", "Eight years of rising earnings, margin buying and valuations that reached the highest CAPE before 1999.", ["history", "bubble"]),
    ("crash-1929", "The 1929 crash and the Great Depression", "1929-09", "1932-06", "The crash of October 1929 and the fall to the 1932 low, with bank failures and deflation.", ["history", "crash", "deflation"]),
    ("recession-1937", "The 1937 to 1938 recession", "1937-03", "1938-03", "A relapse inside the Depression after fiscal and monetary tightening.", ["history", "recession"]),
    ("ww2", "World War II", "1939-09", "1945-08", "The war years, with yields capped by the Treasury and the Fed.", ["history", "war", "yield cap"]),
    ("postwar-1946", "The 1946 to 1949 postwar bear market", "1946-05", "1949-06", "Demobilization, a burst of inflation and a long slide in prices.", ["history", "inflation"]),
    ("bull-1949", "The 1949 to 1966 bull market", "1949-06", "1966-01", "The postwar expansion, with low inflation for most of it and valuations rising from deep value.", ["history", "bull market"]),
    ("kennedy-slide", "The 1962 Kennedy slide", "1961-12", "1962-06", "A fast fall in stocks from high valuations in the first half of 1962.", ["history", "correction"]),
    ("great-inflation", "The Great Inflation", "1966-01", "1982-08", "Sixteen years of rising inflation and yields, ending with the Volcker disinflation; stocks lost ground after inflation.", ["history", "inflation", "stagflation"]),
    ("bear-1973", "The 1973 to 1974 bear market", "1973-01", "1974-12", "The end of the Nifty Fifty, the oil embargo and stagflation.", ["history", "stagflation", "oil shock"]),
    ("volcker", "The Volcker disinflation", "1979-10", "1982-08", "The Fed under Paul Volcker targeted money growth from October 1979; short rates rose above 19% and inflation broke.", ["history", "fed", "disinflation"]),
    ("bull-1982", "The 1982 to 2000 bull market", "1982-08", "2000-03", "Falling inflation and yields, rising margins and the largest valuation expansion on record.", ["history", "bull market", "disinflation"]),
    ("crash-1987", "The 1987 crash", "1987-08", "1987-12", "Black Monday, October 19, 1987: the Dow fell 22.6% in one day, with portfolio insurance selling into the fall.", ["history", "crash"]),
    ("bond-1994", "The 1994 bond rout", "1994-01", "1994-12", "The Fed doubled its policy rate from 3% in a year and long bond yields jumped.", ["history", "bonds", "fed"]),
    ("ltcm-1998", "The 1998 Russian default and LTCM", "1998-07", "1998-10", "Russia defaulted in August 1998; the hedge fund Long-Term Capital Management was rescued by its lenders in September.", ["history", "crisis", "leverage"]),
    ("dotcom", "The dot-com bubble and bust", "1995-01", "2002-10", "The internet boom took CAPE above 44 in December 1999; the Nasdaq then fell about 78% to October 2002.", ["history", "bubble", "crash", "technology"]),
    ("gfc", "The global financial crisis", "2007-10", "2009-03", "The housing and credit bust, Lehman's failure in September 2008 and the low of March 2009.", ["history", "crisis", "credit"]),
    ("euro-2011", "The 2011 euro crisis and US downgrade", "2011-04", "2011-10", "Sovereign debt stress in Europe and S&P's downgrade of the United States in August 2011.", ["history", "crisis"]),
    ("taper-2013", "The 2013 taper tantrum", "2013-05", "2013-09", "Long yields jumped when the Fed signalled it would slow its bond buying.", ["history", "bonds", "fed"]),
    ("covid", "The 2020 pandemic crash", "2020-02", "2020-08", "The fastest 30% fall on record and the fastest recovery, with emergency rate cuts and asset purchases.", ["history", "crash"]),
    ("inflation-2022", "The 2022 inflation and bond rout", "2021-12", "2022-10", "Inflation above 9% and the fastest Fed hikes since the 1980s; stocks and long bonds fell together.", ["history", "inflation", "bonds", "fed"]),
    ("ai-buildout", "The AI buildout", "2023-01", "2026-12", "The rally led by AI chips and the hyperscalers' capital spending, financed increasingly with debt.", ["ai", "capex", "bubble"]),
]


ALIASES = {"panic-1873": ["panic of 1873"], "panic-1893": ["panic of 1893"], "panic-1907": ["panic of 1907", "knickerbocker"], "depression-1920": ["depression of 1920", "1920 depression"],
           "roaring-twenties": ["roaring twenties", "1920s boom"], "crash-1929": ["1929 crash", "crash of 1929", "great depression", "black tuesday"], "recession-1937": ["1937 recession"],
           "ww2": ["world war ii", "world war 2", "second world war"], "postwar-1946": ["1946 bear market"], "bull-1949": ["postwar boom", "1950s bull market"], "kennedy-slide": ["kennedy slide", "1962 crash"],
           "great-inflation": ["great inflation", "1970s inflation"], "bear-1973": ["1973 bear market", "1974 bear market", "nifty fifty", "oil embargo"], "volcker": ["volcker shock", "volcker disinflation"],
           "bull-1982": ["1980s bull market", "1990s bull market"], "crash-1987": ["black monday", "1987 crash", "crash of 1987"], "bond-1994": ["1994 bond rout", "bond massacre", "great bond massacre"],
           "ltcm-1998": ["russian default", "1998 crisis"], "dotcom": ["dot com bubble", "dotcom bubble", "internet bubble", "tech bubble", "dot com bust"],
           "gfc": ["global financial crisis", "financial crisis", "great recession", "2008 crash", "2008 crisis", "lehman"], "euro-2011": ["euro crisis", "2011 downgrade"],
           "taper-2013": ["taper tantrum"], "covid": ["covid crash", "pandemic crash", "2020 crash"], "inflation-2022": ["2022 bear market", "2022 bond rout", "2022 inflation"], "ai-buildout": ["ai buildout"]}


def label(ts) -> str:
    return f"{MONTHS[ts.month - 1]} {ts.year}"


def mid(ts) -> str:
    return "m:" + ts.strftime("%Y-%m")


def frame(S: pd.DataFrame) -> pd.DataFrame:
    D = ml.panel(S)
    r, px, _ = labs.total_return_index(S)
    real = (S["px"] / S["cpi"]).reindex(D.index)
    D["dd_now"] = real / real.cummax() - 1
    D["cape_now"] = np.exp(D["log_cape"].shift(-1))           # log_cape is lagged a month in the panel
    D["cape_pct"] = D["cape_now"].expanding().rank(pct=True)
    D["y10_now"] = S["y10"].reindex(D.index) / 100
    D["infl_now"] = np.log(S["cpi"] / S["cpi"].shift(12)).reindex(D.index)
    D["ret_next"] = np.expm1(D["y_ret"])
    return D


def analogs(D: pd.DataFrame, k: int = ANALOG_K, gap: int = ANALOG_GAP) -> dict[int, list[tuple[int, float]]]:
    F = D[ANALOG_FEATURES]
    ok = F.notna().all(axis=1).to_numpy()
    X = F.to_numpy()
    mu, sd = np.nanmean(X[ok], axis=0), np.nanstd(X[ok], axis=0)
    Z = (X - mu) / sd
    out = {}
    pos = np.flatnonzero(ok)
    Zp = Z[pos]
    for a, i in enumerate(pos):
        d = np.sqrt(((Zp - Z[i]) ** 2).sum(1))
        d[np.abs(pos - i) < gap] = np.inf
        nn = np.argsort(d)[:k]
        out[int(i)] = [(int(pos[j]), float(d[j])) for j in nn if np.isfinite(d[j])]
    return out


def describe(row) -> str:
    parts = []
    if np.isfinite(row["cape_now"]):
        parts.append(f"CAPE {row['cape_now']:.1f} (" + ("the highest on record to then" if row["cape_pct"] >= 0.9995 else f"above {row['cape_pct']:.0%} of the months to then") + ")")
    if np.isfinite(row["y10_now"]):
        parts.append(f"10-year yield {row['y10_now']:.1%}")
    if np.isfinite(row["infl_now"]):
        parts.append(f"inflation {row['infl_now']:+.1%} over 12 months")
    if np.isfinite(row["dd_now"]):
        parts.append("real prices at a new high" if row["dd_now"] > -0.005 else f"real prices {-row['dd_now']:.0%} below their prior peak")
    txt = "; ".join(parts) + "."
    if np.isfinite(row["ret_next"]):
        txt += f" The next 12 months returned {row['ret_next']:+.0%} after inflation, dividends included."
    return txt


@cache.memo("chronicle.build", deps=("buildout.ml", "buildout.labs"), require=("S",))
def build(S: pd.DataFrame) -> dict:
    """Nodes (id, kind, name, text, aliases, group, extra) and edges (a, b, type, weight) for mind.build to add."""
    D = frame(S)
    D = D[D["dd_now"].notna()]
    nodes, edges = [], []
    rows = list(D.iterrows())
    for ts, row in rows:
        nodes.append({"id": mid(ts), "k": "month", "n": label(ts), "g": "chronicle", "t": f"{label(ts)}. " + describe(row),
                      "a": [ts.strftime("%Y-%m"), f"{LONG[ts.month - 1]} {ts.year}"], "yr": ts.year, "mo": ts.month,
                      "ret_next": None if not np.isfinite(row["ret_next"]) else round(float(row["ret_next"]), 4)})
    A = analogs(D)
    seen = set()
    for i, nn in A.items():
        for j, d in nn:
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            edges.append((mid(rows[i][0]), mid(rows[j][0]), "analog", round(0.25 + 0.5 / (1 + d), 4)))
    r, _, _ = labs.total_return_index(S)
    years = sorted({ts.year for ts, _ in rows})
    real = S["px"] / S["cpi"]
    for y in years:
        ry = r[r.index.year == y]
        tr = float(np.prod(1 + ry) - 1) if len(ry) == 12 else None
        ry_px = real[real.index.year == y]
        dd = float((ry_px / ry_px.cummax() - 1).min()) if len(ry_px) else None
        t = f"{y}." + (f" Real total return {tr:+.0%}." if tr is not None else " Part year.") + (f" Worst drawdown inside the year {dd:.0%}." if dd is not None and dd < -0.005 else "")
        nodes.append({"id": f"y:{y}", "k": "year", "n": str(y), "g": "chronicle", "t": t, "a": [], "ret": None if tr is None else round(tr, 4)})
        for ts, _ in rows:
            pass
    for ts, _ in rows:
        edges.append((mid(ts), f"y:{ts.year}", "part_of", 0.5))
    for a, b in zip(years, years[1:]):
        edges.append((f"y:{a}", f"y:{b}", "related", 0.3))
    for eid, name, a, b, text, _tags in EPISODES:
        st = measure(S, a, b)
        if st is None:
            continue
        nodes.append({"id": f"h:{eid}", "k": "episode", "n": name, "g": "chronicle", "t": f"{name}, {a} to {b}. {text} " + st["text"], "a": ALIASES.get(eid, []), "start": a, "end": b,
                      "dd": st["dd"], "dy": st["dy"]})
        for y in range(int(a[:4]), int(b[:4]) + 1):
            if y in years:
                edges.append((f"h:{eid}", f"y:{y}", "part_of", 0.6))
    last = max(A) if A else len(rows) - 1                    # the latest month with every analog input
    now = rows[last][0]
    nn = A.get(last, [])
    fwd = [rows[j][1]["ret_next"] for j, _ in nn if np.isfinite(rows[j][1]["ret_next"])]
    now_txt = (f"The latest month with every input, {label(now)} (Shiller's earnings and yields stop there; prices run to {label(rows[-1][0])}): " + describe(rows[last][1])
               + " Its closest analogs: ") + ", ".join(label(rows[j][0]) for j, _ in nn) + "."
    if fwd:
        now_txt += f" After them, real 12-month returns ran from {min(fwd):+.0%} to {max(fwd):+.0%}, median {float(np.median(fwd)):+.0%}."
    nodes.append({"id": "m:now", "k": "month", "n": "Now, in history", "g": "chronicle", "t": now_txt, "a": ["now", "today", "months like now", "historical analogs", "analog months"]})
    for j, d in nn:
        edges.append(("m:now", mid(rows[j][0]), "analog", round(0.25 + 0.5 / (1 + d), 4)))
    return {"nodes": nodes, "edges": edges, "now": {"month": now.strftime("%Y-%m"), "analogs": [{"month": rows[j][0].strftime("%Y-%m"), "d": round(d, 3), "ret_next": None if not np.isfinite(rows[j][1]["ret_next"]) else round(float(rows[j][1]["ret_next"]), 4)} for j, d in nn],
                                                     "median_next": None if not fwd else round(float(np.median(fwd)), 4)}}


def measure(S: pd.DataFrame, a: str, b: str) -> dict | None:
    real = (S["px"] / S["cpi"]).loc[a:b]
    if len(real) < 2:
        return None
    dd = float((real / real.cummax() - 1).min())
    chg = float(real.iloc[-1] / real.iloc[0] - 1)
    y = (S["y10"] / 100).loc[a:b].dropna()
    dy = float(y.iloc[-1] - y.iloc[0]) if len(y) > 1 else None
    infl = float(S["cpi"].loc[a:b].iloc[-1] / S["cpi"].loc[a:b].iloc[0] - 1)
    end = real.index[-1].strftime("%Y-%m")
    txt = f"Measured from {real.index[0].strftime('%Y-%m')} to {end}: real S&P 500 prices {chg:+.0%}, worst fall from a peak inside the window {dd:.0%}"
    txt += f", 10-year yield {dy * 1e4:+.0f}bp" if dy is not None else ""
    txt += f", consumer prices {infl:+.0%}."
    return {"text": txt, "dd": round(dd, 4), "dy": None if dy is None else round(dy, 5), "chg": round(chg, 4)}


def spiral(nodes: list[dict]) -> np.ndarray:
    """Positions for the chronicle group in the unit disc: months on an Archimedean spiral (one turn per decade), years
    just outside their January, episodes outside the turn of their start, 'now' at the outer end."""
    ms = [n for n in nodes if n["k"] == "month" and "yr" in n]
    y0 = min(n["yr"] for n in ms) if ms else 1871
    T = ((max(n["yr"] for n in ms) - y0) * 12 + 12) if ms else 1
    out = []
    for n in nodes:
        if n["k"] == "month" and "yr" in n:
            t = ((n["yr"] - y0) * 12 + n["mo"] - 1) / T
            r, rad = 0.15 + 0.8 * t, 0.0
        elif n["k"] == "year":
            t = (int(n["n"]) - y0) * 12 / T
            r, rad = 0.15 + 0.8 * t, 0.035
        elif n["k"] == "episode":
            t = ((int(n["start"][:4]) - y0) * 12 + int(n["start"][5:7]) - 1) / T
            r, rad = 0.15 + 0.8 * t, 0.08
        else:
            t, r, rad = 1.0, 0.98, 0.0
        ang = 2 * math.pi * t * T / 120                         # one turn per decade
        out.append([(r + rad) * math.cos(ang), (r + rad) * math.sin(ang)])
    X = np.array(out)
    return X / (np.abs(X).max() or 1)
