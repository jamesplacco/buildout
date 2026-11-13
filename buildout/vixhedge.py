"""VIX as a hedge (v0.39): does owning volatility protect the AI book, in which regimes, and at what carry?

Three ways to own the VIX, each priced from data:
  vix_fut    long VIX futures, the contract held rolled monthly (pysystemtrade's VIX record, Feb 2006 to Mar 2024).
             This is what a VIX ETF such as VIXY holds (a constant one-month blend of the first two contracts), so it
             carries the same roll cost: VIX futures sit above spot in calm markets and drift down toward it.
  vix_call   a one-month call on the VIX future, strike 125% of the future, bought each month-end and held to the
             next (Black-76 at a volatility of volatility `VOV`; modelled, not traded; the figures are reported at
             0.8, 1.0 and 1.2 so the assumption is visible).
  vix_index  the VIX index itself: not investable (nothing tracks it), shown only as the upper bound a hedge could reach.

Against the Nasdaq-100 future, monthly: correlation, the hedge's average in the index's down months, its return in
the worst 5% of months, the variance a min-variance weight removes, and the carry (its average return a year), by
regime. Then on the book: each hedge sized at a fixed share of NAV, walked through the book's daily path, with the
one-month expected shortfall, the worst drawdown, 2020 and 2022, and the CAGR given up.

On Robinhood: VIX futures are not open to agents; VIX ETFs (VIXY) trade as shares, and VIX index options are listed
(single-leg long options are open to agents; index options through the agent are not confirmed in Robinhood's docs).
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CARVER_VIX = "https://raw.githubusercontent.com/robcarver17/pysystemtrade/master/data/futures/multiple_prices_csv/VIX.csv"
VOV = 1.0                    # volatility of the VIX future for the call's price; reported at 0.8, 1.0, 1.2
STRIKE = 1.25
COST_BP = 5.0                # a round trip in the future, bp of notional; options pay a 3% bid-ask on premium
OPTION_SPREAD = 0.03
SHARES = (0.0, 0.05, 0.10, 0.20)


def vix_frame(cache: str | Path | None = None) -> pd.DataFrame:
    """pysystemtrade's VIX multiple prices, one row a day (cached for a week)."""
    from . import futures as fu
    from .data import http
    path = Path(cache or ROOT / ".cache" / "vix") / "VIX.csv"
    if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(http.get(CARVER_VIX, timeout=60).decode())
    return fu.parse_carver(path.read_text())


def vix_index(cache: str | Path | None = None) -> pd.Series:
    from .track import _gh
    v = _gh("finance-vix/main/data/vix-daily.csv")
    v["DATE"] = pd.to_datetime(v["DATE"])
    return v.set_index("DATE")["CLOSE"].astype(float)


def _black76_call(F, K, T, s):
    from scipy.stats import norm
    d1 = (np.log(F / K) + 0.5 * s ** 2 * T) / (s * np.sqrt(T))
    return F * norm.cdf(d1) - K * norm.cdf(d1 - s * np.sqrt(T))


def monthly(frames: dict, vxf: pd.DataFrame, vix: pd.Series, vov: float = VOV) -> pd.DataFrame:
    """Monthly returns per $1 of notional: the Nasdaq-100 future, VIX futures, the modelled VIX call (per $1 of the
    future's value, net of the spread), and the VIX index's change."""
    from . import futures as fu
    nq = (1 + fu.front_returns(frames["NQ"]).dropna()).resample("ME").prod() - 1
    vd = fu.front_returns(vxf).dropna()
    vf = (1 + vd).resample("ME").prod() - 1 - COST_BP / 1e4 / 12            # one roll a month
    F0 = vxf["price"].resample("ME").last().shift(1)                        # the future at the start of the month
    K = STRIKE * F0
    prem = _black76_call(F0, K, 1 / 12, vov) * (1 + OPTION_SPREAD / 2)
    F1 = F0 * (1 + vf)                                                      # the same contract at the month's end
    call = (np.maximum(F1 - K, 0) * (1 - OPTION_SPREAD / 2) - prem) / F0
    vi = vix.resample("ME").last().pct_change()
    M = pd.DataFrame({"NQ": nq, "vix_fut": vf, "vix_call": call, "vix_index": vi}).dropna(subset=["NQ", "vix_fut", "vix_call"])
    return M


def _row(g: pd.DataFrame, k: str) -> dict:
    s, nq = g[k].dropna(), g["NQ"]
    nq = nq.reindex(s.index)
    v = float(s.var())
    w = max(-float(np.cov(nq, s)[0, 1] / v), 0.0) if v > 0 else 0.0
    cut = 1 - float((nq + w * s).var()) / float(nq.var()) if w > 0 else 0.0
    down = nq < -0.03
    tail = nq <= nq.quantile(0.05)
    return {"corr": float(nq.corr(s)), "down": float(s[down].mean()) if down.any() else None, "tail": float(s[tail].mean()) if tail.any() else None,
            "var_cut": cut, "weight": w, "ann": float(s.mean() * 12), "carry_at_weight": float(w * s.mean() * 12)}


def regimes(M: pd.DataFrame, H: pd.DataFrame | None, pol: pd.Series | None) -> list[dict]:
    X = M.copy()
    if H is not None:
        infl = H["infl"].resample("ME").last().reindex(X.index, method="ffill")
        X["infl_lvl"] = np.where(infl > 0.03, "above", "below")
    if pol is not None:
        X["policy"] = pol.reindex(X.index, method="ffill")
    out = []
    groups = [("All months", X)]
    if "infl_lvl" in X:
        groups += [("Inflation below 3%", X[X["infl_lvl"] == "below"]), ("Inflation above 3%", X[X["infl_lvl"] == "above"])]
    if "policy" in X:
        groups += [("Policy tightening", X[X["policy"] == "tightening"]), ("Policy easing", X[X["policy"] == "easing"])]
    groups += [(y, X[X.index.year == int(y)]) for y in ("2008", "2020", "2022")]
    for name, g in groups:
        if len(g) < 8:
            continue
        out.append({"regime": name, "months": int(len(g)), "down_months": int((g["NQ"] < -0.03).sum()), "nq": float(g["NQ"].mean() * 12),
                    "h": {k: _row(g, k) for k in ("vix_fut", "vix_call", "vix_index")}})
    return out


def _es21(x: pd.Series, alpha: float = 0.05) -> float:
    from .book import es
    r21 = (1 + x).rolling(21).apply(np.prod, raw=True) - 1
    return es(r21.dropna().to_numpy(), alpha)


def _dd(x: pd.Series) -> float:
    lv = (1 + x).cumprod()
    return float((1 - lv / lv.cummax()).max())


def option_daily(level_ret: pd.Series, vol: pd.Series | float, kind: str, k: float, spread: float = OPTION_SPREAD) -> pd.Series:
    """A one-month option bought at each month's first close and held to the month's last, marked every day at
    Black-Scholes with no rate (Black-76 on a future): the daily change in its value per $1 of the underlying at the
    purchase. The underlying's level is chained from its daily returns, so a futures roll is not a jump. Half the
    bid-ask is paid on the way in and half on the way out (at intrinsic value on the last day)."""
    from scipy.stats import norm
    idx = level_ret.index
    per = idx.to_period("M")
    pos = pd.Series(np.arange(len(idx)), index=idx).groupby(per).cumcount()
    n = pd.Series(1, index=idx).groupby(per).transform("sum")
    S = (1 + level_ret.fillna(0)).groupby(per).cumprod() / (1 + level_ret.fillna(0)).where(pos == 0).ffill()    # level / level at the purchase close
    K = k
    T = ((n - 1 - pos) / n).clip(lower=0) / 12
    sig = (vol if isinstance(vol, float) else vol.reindex(idx).ffill()).astype(float) if not isinstance(vol, float) else pd.Series(vol, index=idx)
    sT = sig * np.sqrt(T)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + 0.5 * sT ** 2) / sT
    d2 = d1 - sT
    if kind == "call":
        val = np.where(T > 0, S * norm.cdf(d1) - K * norm.cdf(d2), np.maximum(S - K, 0))
    else:
        val = np.where(T > 0, K * norm.cdf(-d2) - S * norm.cdf(-d1), np.maximum(K - S, 0))
    val = pd.Series(val, index=idx)
    pnl = val.groupby(per).diff()
    first, last = pos == 0, pos == n - 1
    pnl[first] = -(spread / 2) * val[first]                    # bought at the close: only the half spread is lost that day
    pnl[last] = pnl[last] - (spread / 2) * val[last]
    return pnl.fillna(0.0)


def on_book(book: pd.Series, cash: pd.Series, vxf: pd.DataFrame, frames: dict, vix: pd.Series, vov: float = VOV) -> dict:
    """The book's daily return with a hedge at a fixed share of NAV, rebalanced monthly and marked daily: VIX futures
    at that notional; VIX calls on that notional of the future; Nasdaq-100 puts (90% strike, implied vol VIX x 1.25)
    on that notional; a Nasdaq-100 futures short of that size. Over the days every record covers. Each row: the
    one-month 95% expected shortfall, the worst drawdown, Feb 19 to Mar 23 2020, 2022, the CAGR, and what each costs."""
    from . import futures as fu
    vd = fu.front_returns(vxf).dropna()
    nq = fu.front_returns(frames["NQ"]).dropna()
    idx = book.dropna().index
    idx = idx[idx.isin(vd.index) & idx.isin(nq.index)]                 # the days all three series share
    b, v, q = book.reindex(idx), vd.reindex(idx), nq.reindex(idx)
    hedges = {"vix_fut": (v - COST_BP / 1e4 / 21, SHARES),
              "vix_call": (option_daily(v, vov, "call", STRIKE), SHARES),
              "nq_put": (option_daily(q, vix.reindex(idx).ffill() / 100 * 1.25, "put", 0.90), (0.0, 0.25, 0.50, 1.0)),
              "nq_short": (-q - 1.5 / 1e4 / 21, (0.0, 0.25, 0.50))}
    rows = [{"hedge": "none", "share": 0.0, **_metrics(b)}]
    for k, (h, shares) in hedges.items():
        for s in shares[1:]:
            rows.append({"hedge": k, "share": s, **_metrics(b + s * h)})
    base = rows[0]
    for r in rows:
        r["es_cut"] = base["es21"] - r["es21"]
        r["cagr_cost"] = base["cagr"] - r["cagr"]
        r["es_cut_per_cost"] = (r["es_cut"] / r["cagr_cost"]) if r["cagr_cost"] > 1e-4 else None
    return {"from": str(idx[0].date()), "to": str(idx[-1].date()), "rows": rows}


def _metrics(x: pd.Series) -> dict:
    return {"es21": _es21(x), "maxdd": _dd(x), "cagr": float((1 + x).prod() ** (252 / len(x)) - 1),
            "y2020q1": float((1 + x[(x.index >= "2020-02-19") & (x.index <= "2020-03-23")]).prod() - 1), "y2022": float((1 + x[x.index.year == 2022]).prod() - 1)}


def weeks_vix(vix: pd.Series, weeks: list) -> list[dict]:
    """The VIX index over each named week: where it started, where it ended, and the change."""
    out = []
    for name, a, b in weeks:
        s = vix.loc[a:b]
        pre = vix.loc[:a].iloc[-2] if len(vix.loc[:a]) > 1 else None
        if len(s):
            out.append({"week": name, "start": float(pre if pre is not None else s.iloc[0]), "end": float(s.iloc[-1]), "high": float(s.max())})
    return out


def build(frames: dict, book: pd.Series, cash: pd.Series, H: pd.DataFrame | None = None, pol: pd.Series | None = None,
          vxf: pd.DataFrame | None = None, vix: pd.Series | None = None) -> dict:
    from .track import WEEKS
    vxf = vxf if vxf is not None else vix_frame()
    vix = vix if vix is not None else vix_index()
    M = monthly(frames, vxf, vix)
    sens = {}
    for vov in (0.8, 1.0, 1.2):
        g = monthly(frames, vxf, vix, vov)
        r = _row(g, "vix_call")
        sens[f"{vov:.1f}"] = {"ann": r["ann"], "var_cut": r["var_cut"], "down": r["down"]}
    out = {"from": str(M.index[0].date())[:7], "to": str(M.index[-1].date())[:7],
           "labels": {"vix_fut": "Long VIX futures (what VIXY holds)", "vix_call": "VIX call, 1 month, 125% strike (modelled)", "vix_index": "VIX index (not investable)"},
           "regimes": regimes(M, H, pol), "call_vov": sens, "book": on_book(book, cash, vxf, frames, vix),
           "weeks": weeks_vix(vix, WEEKS), "vix_now": {"date": str(vix.index[-1].date()), "level": float(vix.iloc[-1]),
                                                        "pct_since_1990": float((vix < vix.iloc[-1]).mean())},
           "robinhood": {"vix_futures": False, "vixy_shares": True, "vix_index_options": "listed; agent access to index options unconfirmed", "multi_leg": False}}
    # VIX futures curve now is not in the data (the record ends in 2024); the roll cost is read from the record
    vd = M["vix_fut"]
    out["carry"] = {"ann_all": float(vd.mean() * 12), "share_months_negative": float((vd < 0).mean()),
                    "calm_ann": float(vd[M["NQ"] > 0].mean() * 12), "down_ann": float(vd[M["NQ"] < -0.03].mean() * 12)}
    return out
