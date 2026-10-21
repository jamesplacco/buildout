"""Original research on 155 years of public data, reproducible with one command:

    python -m buildout research --out site/data      # writes research.json

Inputs are public datasets mirrored on GitHub (no key, no cost): Robert Shiller's monthly S&P 500 with
dividends, earnings, CPI and the long rate (1871 on), BLS CPI-U (1913 on), the 10-year Treasury (1953 on),
EIA Brent (1987 on), CBOE VIX (1990 on) and monthly gold (1833 on).

Findings it computes (the page's Findings desk shows the same tables):
  hedge_line        stock-bond correlation (36 months) by the inflation of the same 36 months
  fat_tails         how often 3- to 6-sigma down months happened against what a normal model allows
  earnings_roc      forward returns by the level and the rate of change of earnings growth
  oil_shocks        what followed supply-driven oil spikes versus demand rebounds
  vix_spikes        what followed the first VIX close above 30 and 40
  inflation_spells  how long inflation took to fall from above 5% to below 3%
  gold              gold against stocks when inflation runs hot and when stocks fall
  cape              forward 10-year real returns by starting valuation decile
"""
from __future__ import annotations

import io
import math

import numpy as np
import pandas as pd

from .analytics.bonds import constant_maturity_returns
from .data import http

RAW = "https://raw.githubusercontent.com/datasets/{}"
SOURCES = {
    "shiller": "s-and-p-500/main/data/data.csv",
    "cpi": "cpi-us/main/data/cpiai.csv",
    "y10": "bond-yields-us-10y/main/data/monthly.csv",
    "brent": "oil-prices/main/data/brent-daily.csv",
    "vix": "finance-vix/main/data/vix-daily.csv",
    "gold": "gold-prices/main/data/monthly.csv",
}
HEDGE_BUCKETS = ([-1, 0.0, 0.02, 0.03, 0.04, 0.06, 1], ["Deflation", "0 to 2%", "2 to 3%", "3 to 4%", "4 to 6%", "Above 6%"])


def download(cache=None) -> dict[str, pd.DataFrame]:
    out = {}
    for k, path in SOURCES.items():
        raw = http.get(RAW.format(path), user_agent="buildout-research")
        out[k] = pd.read_csv(io.BytesIO(raw))
    return out


def monthly_calendar(s: pd.Series, max_gap: int = 2) -> pd.Series:
    """A complete month-start calendar, so that shift(12) is always twelve calendar months.

    BLS published no CPI for October 2025 (the federal shutdown). Dropping the month silently turns every
    later "12-month" change into a 13-month one (August 2026 reads 3.69% instead of the published 3.4%).
    Gaps of up to `max_gap` months are filled geometrically (log-linear); longer gaps stay empty.
    """
    s = s.dropna().sort_index()
    s.index = s.index.to_period("M").to_timestamp()
    s = s[~s.index.duplicated(keep="last")]
    full = s.reindex(pd.date_range(s.index[0], s.index[-1], freq="MS"))
    gap = full.isna()
    run_len = gap.groupby((~gap).cumsum()).transform("sum")              # length of the gap each month sits in
    filled = np.exp(np.log(full).interpolate(limit_area="inside"))
    return full.where(~gap, filled.where(run_len <= max_gap))


def tidy(raw: dict[str, pd.DataFrame]) -> dict[str, pd.Series | pd.DataFrame]:
    sh = raw["shiller"].copy()
    sh["Date"] = pd.to_datetime(sh["Date"])
    sh = sh.set_index("Date").rename(columns={"SP500": "px", "Dividend": "div", "Earnings": "eps", "Consumer Price Index": "cpi",
                                              "Long Interest Rate": "y10", "PE10": "cape"})
    for c in ["div", "eps", "cpi", "y10", "cape"]:
        sh.loc[sh[c] <= 0, c] = np.nan
    cpi = monthly_calendar(raw["cpi"].assign(Date=lambda d: pd.to_datetime(d["Date"])).set_index("Date")["Index"])
    y10 = raw["y10"].assign(Date=lambda d: pd.to_datetime(d["Date"])).set_index("Date")["Rate"]
    gold = raw["gold"].copy()
    gold.index = pd.to_datetime(gold["Date"].astype(str).str.slice(0, 7) + "-01")
    brent = raw["brent"].assign(Date=lambda d: pd.to_datetime(d["Date"])).set_index("Date")["Price"]
    vcol = "DATE" if "DATE" in raw["vix"].columns else "Date"
    vix = raw["vix"].assign(**{vcol: lambda d: pd.to_datetime(d[vcol])}).set_index(vcol)["CLOSE"]
    return {"shiller": sh, "cpi": cpi, "y10": y10, "gold": gold["Price"], "brent": brent, "vix": vix}


def monthly_panel(sh: pd.DataFrame, cpi: pd.Series, y10: pd.Series) -> pd.DataFrame:
    """Monthly S&P total return and 10-year bond total return.

    The official series win wherever they exist: BLS CPI-U from 1913 and the 10-year Treasury from 1953. Shiller's
    file fills the earlier years only, because its last months are preliminary estimates (its August and September
    2023 CPI sit a full point below what BLS later published) and it carries at least one stray long rate (July 2019).
    """
    df = sh[["px", "div", "cpi", "y10", "eps", "cape"]].copy()
    df["cpi"] = cpi.reindex(df.index).combine_first(df["cpi"])
    df["y10"] = y10.reindex(df.index).combine_first(df["y10"])
    last_yield = (df["div"] / df["px"]).dropna().iloc[-1]
    df["div"] = df["div"].fillna(df["px"] * last_yield)      # dividend yield held at its last value after the file ends
    df = df.dropna(subset=["px", "cpi", "y10"])
    df = df.reindex(pd.date_range(df.index[0], df.index[-1], freq="MS"))     # a dropped month must not shorten any window
    df["r_eq"] = (df["px"] + df["div"] / 12) / df["px"].shift(1) - 1
    df["r_bd"] = constant_maturity_returns(df["y10"], maturity=10.0)
    df["infl"] = df["cpi"] / df["cpi"].shift(12) - 1
    return df


def hedge_line(df: pd.DataFrame, win: int = 36) -> dict:
    corr = df["r_eq"].rolling(win).corr(df["r_bd"])
    avg = (df["cpi"] / df["cpi"].shift(win)) ** (12 / win) - 1
    d = pd.DataFrame({"corr": corr, "infl": avg}).dropna()
    edges, labels = HEDGE_BUCKETS
    d["bucket"] = pd.cut(d["infl"], edges, labels=labels)
    rows = []
    for lab in labels:
        g = d[d["bucket"] == lab]["corr"]
        if len(g):
            rows.append({"bucket": lab, "months": int(len(g)), "mean_corr": float(g.mean()), "median_corr": float(g.median()),
                         "share_hedging": float((g < 0).mean())})
    scan = []
    for cut in np.round(np.arange(0.01, 0.0501, 0.0025), 4):
        lo, hi = d[d["infl"] < cut]["corr"], d[d["infl"] >= cut]["corr"]
        if len(lo) > 60 and len(hi) > 60:
            scan.append({"cut": float(cut), "below_hedging": float((lo < 0).mean()), "above_hedging": float((hi < 0).mean()),
                         "gap": float((lo < 0).mean() - (hi < 0).mean())})
    best = max(scan, key=lambda r: r["gap"]) if scan else None
    # the separation is nearly flat across a band of cuts: report the band, and use its low edge as the line
    near = [r["cut"] for r in scan if best and r["gap"] >= best["gap"] - 0.01]
    zone = [min(near), max(near)] if near else None
    decades = d.groupby((d.index.year // 10) * 10)["corr"].mean()
    return {"window_months": win, "rows": rows, "scan": scan, "line": zone[0] if zone else None, "zone": zone, "best": best,
            "latest": {"month": d.index[-1].strftime("%Y-%m"), "corr": float(d["corr"].iloc[-1]), "infl_avg": float(d["infl"].iloc[-1])},
            "decades": {str(int(k)): float(v) for k, v in decades.items()},
            "n_months": int(len(d)), "start": d.index[0].strftime("%Y-%m")}


def fat_tails(r: pd.Series) -> dict:
    from scipy.stats import norm
    lr = np.log(1 + r.dropna())
    z = (lr - lr.mean()) / lr.std()
    rows = []
    for k in (3, 4, 5, 6):
        n = int((z < -k).sum())
        p = float(norm.cdf(-k))
        rows.append({"sigma": k, "observed": n, "expected_normal": p * len(lr), "normal_once_every_years": 1 / (p * 12)})
    losses = np.sort(-lr[lr < 0].to_numpy())[::-1]
    k = max(10, int(0.05 * len(lr)))
    top = losses[:k]
    alpha = float(1 / np.mean(np.log(top[:-1] / top[-1]))) if len(top) > 2 else float("nan")
    worst = lr.nsmallest(5)
    return {"months": int(len(lr)), "sigma_monthly": float(lr.std()), "rows": rows, "hill_alpha": alpha,
            "worst": [{"month": d.strftime("%Y-%m") if hasattr(d, "strftime") else str(d), "log_return": float(v),
                       "sigmas": float((v - lr.mean()) / lr.std())} for d, v in worst.items()]}


def earnings_roc(df: pd.DataFrame) -> dict:
    e = df["eps"].dropna()
    g = e / e.shift(12) - 1
    a = g - g.shift(6)
    real = (1 + df["r_eq"]) / (df["cpi"] / df["cpi"].shift(1)) - 1
    fwd = (1 + real).rolling(12).apply(np.prod, raw=True).shift(-12) - 1
    d = pd.DataFrame({"g": g, "a": a, "fwd": fwd}).dropna()
    d = d[d.index >= "1880-01-01"]
    rows = []
    for gl, gm in (("Growth up", d["g"] > 0), ("Growth down", d["g"] <= 0)):
        for al, am in (("accelerating", d["a"] > 0), ("decelerating", d["a"] <= 0)):
            s = d[gm & am]["fwd"]
            if len(s):
                rows.append({"state": f"{gl}, {al}", "months": int(len(s)), "mean_fwd12": float(s.mean()),
                             "median_fwd12": float(s.median()), "share_positive": float((s > 0).mean())})
    return {"since": d.index[0].strftime("%Y"), "until": d.index[-1].strftime("%Y-%m"), "rows": rows,
            "unconditional_mean": float(d["fwd"].mean())}


def oil_shocks(brent: pd.Series, px: pd.Series, y10: pd.Series, threshold: float = 0.5, supply_ratio: float = 1.3) -> dict:
    """First month of each run with Brent up more than `threshold` on the year; supply if price > `supply_ratio` x its 5-year average."""
    m = brent.resample("MS").mean()
    yoy = m / m.shift(12) - 1
    avg5 = m.rolling(60).mean()
    rows, prev = [], False
    for d, v in yoy.items():
        hot = bool(v > threshold)
        if hot and not prev:
            t12 = d + pd.DateOffset(months=12)
            rel = float(m[d] / avg5[d]) if pd.notna(avg5[d]) else None
            rows.append({"month": d.strftime("%Y-%m"), "brent": float(m[d]), "yoy": float(v), "vs_5y_avg": rel,
                         "kind": "supply" if rel and rel > supply_ratio else "rebound",
                         "spx_fwd12": float(px.asof(t12) / px.asof(d) - 1) if t12 <= px.index[-1] else None,
                         "y10_chg12_bp": float((y10.asof(t12) - y10.asof(d)) * 100) if t12 <= y10.index[-1] else None})
        prev = hot
    summ = {}
    for k in ("supply", "rebound"):
        f = [r["spx_fwd12"] for r in rows if r["kind"] == k and r["spx_fwd12"] is not None]
        summ[k] = {"n": len(f), "mean_fwd12": float(np.mean(f)) if f else None, "share_up": float(np.mean([x > 0 for x in f])) if f else None}
    return {"rows": rows, "summary": summ, "threshold": threshold, "supply_ratio": supply_ratio}


def vix_spikes(vix: pd.Series, px: pd.Series) -> dict:
    m = vix.resample("MS").max()
    res = {}
    for lvl in (30, 40):
        ev, last = [], None
        for d, v in m.items():
            if v >= lvl and (last is None or (d - last).days > 365):
                last = d
                p0 = px.asof(d + pd.offsets.MonthEnd(0))
                row = {"month": d.strftime("%Y-%m"), "vix_max": float(v)}
                for hz in (3, 12):
                    t = d + pd.DateOffset(months=hz)
                    row[f"spx_fwd{hz}"] = float(px.asof(t) / p0 - 1) if t <= px.index[-1] else None
                ev.append(row)
        f12 = [e["spx_fwd12"] for e in ev if e["spx_fwd12"] is not None]
        res[str(lvl)] = {"events": ev, "n": len(f12), "mean_fwd12": float(np.mean(f12)) if f12 else None,
                         "share_up12": float(np.mean([x > 0 for x in f12])) if f12 else None}
    lv = np.log(vix.dropna())
    b = np.polyfit(lv.shift(1).dropna().to_numpy(), lv.iloc[1:].to_numpy(), 1)[0]
    res["half_life_days"] = float(math.log(0.5) / math.log(b)) if 0 < b < 1 else None
    res["median"] = float(vix.median())
    res["share_above_30"] = float((vix > 30).mean())
    return res


def inflation_spells(cpi: pd.Series, hi: float = 0.05, lo: float = 0.03) -> dict:
    yoy = (cpi / cpi.shift(12) - 1).dropna()
    eps, i, idx = [], 0, yoy.index
    while i < len(yoy):
        if yoy.iloc[i] > hi and (i == 0 or yoy.iloc[i - 1] <= hi):
            j = i
            while j < len(yoy) and yoy.iloc[j] >= lo:
                j += 1
            eps.append({"crossed": idx[i].strftime("%Y-%m"), "back_below": idx[j].strftime("%Y-%m") if j < len(yoy) else None,
                        "months": (j - i) if j < len(yoy) else None, "peak": float(yoy.iloc[i:max(j, i + 1)].max())})
            i = j
        i += 1
    done = [e["months"] for e in eps if e["months"] is not None]
    return {"episodes": eps, "median_months": float(np.median(done)) if done else None,
            "latest_yoy": float(yoy.iloc[-1]), "latest_month": yoy.index[-1].strftime("%Y-%m")}


def gold_study(gold: pd.Series, df: pd.DataFrame, since: str = "1972-01-01") -> dict:
    g = gold.reindex(df.index).ffill()
    cpi12 = df["cpi"] / df["cpi"].shift(12)
    real_g = (g / g.shift(12)) / cpi12 - 1
    real_eq = (1 + df["r_eq"]).rolling(12).apply(np.prod, raw=True) / cpi12 - 1
    d = pd.DataFrame({"gold": real_g, "eq": real_eq, "infl": df["infl"]}).dropna()
    d = d[d.index >= since]
    hi, lo, bad = d[d["infl"] > 0.04], d[d["infl"] <= 0.04], d[d["eq"] < -0.15]
    return {"since": since[:4], "high_infl": {"months": int(len(hi)), "gold": float(hi["gold"].mean()), "stocks": float(hi["eq"].mean())},
            "low_infl": {"months": int(len(lo)), "gold": float(lo["gold"].mean()), "stocks": float(lo["eq"].mean())},
            "stocks_down15": {"months": int(len(bad)), "gold": float(bad["gold"].mean()) if len(bad) else None,
                              "share_gold_up": float((bad["gold"] > 0).mean()) if len(bad) else None}}


def cape_deciles(df: pd.DataFrame) -> dict:
    real = (1 + df["r_eq"]) / (df["cpi"] / df["cpi"].shift(1))
    fwd10 = real.rolling(120).apply(np.prod, raw=True).shift(-120) ** (1 / 10) - 1
    d = pd.DataFrame({"cape": df["cape"], "fwd": fwd10}).dropna()
    d["dec"] = pd.qcut(d["cape"], 10, labels=False)
    rows = [{"decile": int(k) + 1, "cape_lo": float(g["cape"].min()), "cape_hi": float(g["cape"].max()), "fwd10_real": float(g["fwd"].mean()),
             "worst": float(g["fwd"].min()), "best": float(g["fwd"].max()), "months": int(len(g))} for k, g in d.groupby("dec")]
    above = d[d["cape"] > 30]["fwd"]
    return {"rows": rows, "months": int(len(d)), "above30": {"months": int(len(above)), "mean": float(above.mean()) if len(above) else None,
                                                             "max": float(above.max()) if len(above) else None},
            "last_cape": float(df["cape"].dropna().iloc[-1]), "last_cape_month": df["cape"].dropna().index[-1].strftime("%Y-%m")}


def run(raw: dict[str, pd.DataFrame]) -> dict:
    t = tidy(raw)
    df = monthly_panel(t["shiller"], t["cpi"], t["y10"])
    px = t["shiller"]["px"].dropna()
    return {
        "source": "Shiller S&P 500 data, BLS CPI-U, 10-year Treasury, EIA Brent, CBOE VIX, monthly gold (GitHub mirrors of public datasets)",
        "panel": {"start": df.index[1].strftime("%Y-%m"), "end": df.index[-1].strftime("%Y-%m"), "months": int(df["r_eq"].notna().sum())},
        "hedge_line": hedge_line(df, 36),
        "hedge_line_60": hedge_line(df, 60),
        "fat_tails": fat_tails(df["r_eq"]),
        "earnings_roc": earnings_roc(df),
        "oil_shocks": oil_shocks(t["brent"], px, t["y10"]),
        "vix_spikes": vix_spikes(t["vix"], px),
        "inflation_spells": inflation_spells(t["cpi"]),
        "gold": gold_study(t["gold"], df),
        "cape": cape_deciles(df),
    }


def _r(v, d=6):
    return round(v, d) if isinstance(v, float) else v


def compact(r: dict) -> dict:
    """The page's shape of `run`'s output (site/src/research.js FINDINGS has exactly these keys)."""
    hl, ft, er, oil, vx, sp, cp = (r["hedge_line"], r["fat_tails"], r["earnings_roc"], r["oil_shocks"], r["vix_spikes"],
                                   r["inflation_spells"], r["cape"])
    sig = lambda x: float("%.3g" % x)
    spike = lambda s: {"n": s["n"], "mean": _r(s["mean_fwd12"]), "up": _r(s["share_up12"], 3),
                       "events": [{"m": e["month"], "v": round(e["vix_max"], 1), "f": _r(e["spx_fwd12"], 3)} for e in s["events"]]}
    return {
        "source": r.get("source"),
        "panel": r["panel"],
        "hedge": {"rows": [{k: _r(v) for k, v in x.items()} for x in hl["rows"]], "line": hl["line"], "zone": hl["zone"],
                  "latest": {k: _r(v) for k, v in hl["latest"].items()}, "decades": {k: round(v, 3) for k, v in hl["decades"].items()},
                  "n": hl["n_months"], "start": hl["start"], "line60": r["hedge_line_60"]["line"], "zone60": r["hedge_line_60"]["zone"],
                  "split": next(({"cut": x["cut"], "below": round(x["below_hedging"], 6), "above": round(x["above_hedging"], 6)}
                                 for x in hl["scan"] if x["cut"] == hl["line"]), None)},
        "tails": {"months": ft["months"], "sigma": round(ft["sigma_monthly"], 6), "alpha": round(ft["hill_alpha"], 2),
                  "rows": [{"k": x["sigma"], "obs": x["observed"], "exp": sig(x["expected_normal"]), "every": sig(x["normal_once_every_years"])} for x in ft["rows"]],
                  "worst": [{"m": w["month"], "s": round(w["sigmas"], 1), "r": round(w["log_return"], 6)} for w in ft["worst"]]},
        "roc": {"since": er["since"], "until": er["until"], "uncond": round(er["unconditional_mean"], 6),
                "rows": [{"state": x["state"], "n": x["months"], "mean": round(x["mean_fwd12"], 6), "median": round(x["median_fwd12"], 6),
                          "up": round(x["share_positive"], 3)} for x in er["rows"]]},
        "oil": {"summary": {k: {kk: _r(vv) for kk, vv in v.items()} for k, v in oil["summary"].items()},
                "rows": [{"m": x["month"], "brent": round(x["brent"], 1), "yoy": round(x["yoy"], 3),
                          "rel": round(x["vs_5y_avg"], 2) if x["vs_5y_avg"] else None, "kind": x["kind"], "fwd": _r(x["spx_fwd12"], 3),
                          "dy": round(x["y10_chg12_bp"]) if x["y10_chg12_bp"] is not None else None} for x in oil["rows"]]},
        "vix": {"half_life": _r(vx["half_life_days"], 1), "median": round(vx["median"], 2), "above30": round(vx["share_above_30"], 6),
                "s30": spike(vx["30"]), "s40": spike(vx["40"])},
        "spells": {"median": sp["median_months"], "latest": round(sp["latest_yoy"], 6), "month": sp["latest_month"],
                   "eps": [{"from": e["crossed"], "to": e["back_below"], "n": e["months"], "peak": round(e["peak"], 3)} for e in sp["episodes"]]},
        "gold": {k: ({kk: _r(vv) for kk, vv in v.items()} if isinstance(v, dict) else v) for k, v in r["gold"].items()},
        "cape": {"rows": [{"d": x["decile"], "lo": x["cape_lo"], "hi": x["cape_hi"], "f": round(x["fwd10_real"], 6), "w": round(x["worst"], 6),
                           "b": round(x["best"], 6), "n": x["months"]} for x in cp["rows"]],
                 "above30": {k: _r(v) for k, v in cp["above30"].items()}, "n": cp["months"]},
    }
