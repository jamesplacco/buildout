"""The field manual's engine work: regime and gross, the hedge selector, fat-tail risk and scenario replays.

    python -m buildout buyside --out site/data        # writes buyside.json (public GitHub datasets, free)

regime_label     the manual's rule 7a.1: policy direction and real yields scale gross; inflation and the stock-bond
                 correlation decide whether long bonds are in the hedge stack at all
hedge_selector   for a book, each candidate hedge's return on the book's worst 5% of periods, the expected shortfall it
                 removes and what it costs to carry, separately in each inflation regime
tail_risk        97.5% expected shortfall three ways: normal, Student-t (fitted by maximum likelihood) and history
replays          the five episodes the manual names, replayed on monthly data for a bonds-only and a stacked hedge

The monthly datasets average daily prices within each month, which understates moves inside the month; the daily run
repeats the selector on daily FRED data (Nasdaq-100, the 20-year Treasury, VIX and Brent) when it is available.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

LINE = 0.0275          # the low edge of the research step's 2.75% to 4.25% inflation band (36-month average CPI); the validated line is 4.25%


def gross_scaler(fed: int, real10: float) -> tuple[float, float, str]:
    """Rule 7a.1: easing with falling real yields 100-120% of max gross; on hold about 85%; hiking with real yields
    above 1.5%, 60-75%. fed: +1 hiking, 0 on hold, -1 easing."""
    if fed > 0 and real10 > 1.5:
        return 0.60, 0.75, "Hiking with real yields above 1.5%"
    if fed > 0:
        return 0.75, 0.85, "Hiking with real yields below 1.5%"
    if fed < 0:
        return 1.00, 1.20, "Easing"
    return 0.85, 0.85, "On hold"


def regime_label(cpi_3m_ann: float, real10: float, fed: int, brent_vs_5y: float, corr: float, infl36: float) -> dict:
    hot = cpi_3m_ann >= 3.0 or brent_vs_5y >= 1.3
    supply = brent_vs_5y >= 1.3
    if hot and fed > 0:
        label = "Supply-shock stagflation scare" if supply else "Tightening into inflation"
    elif hot and fed == 0:
        label = "Sticky inflation, Fed on hold"
    elif hot:
        label = "Easing into inflation"
    elif fed < 0:
        label = "Easing, disinflation"
    elif fed > 0:
        label = "Late-cycle tightening"
    else:
        label = "Neutral"
    lo, hi, why = gross_scaler(fed, real10)
    bonds_on = corr < -0.10 and infl36 * 100 < LINE * 100
    return {"label": label, "gross_lo": lo, "gross_hi": hi, "gross_why": why, "bonds_in_stack": bonds_on,
            "inputs": {"cpi_3m_ann": cpi_3m_ann, "real10": real10, "fed": fed, "brent_vs_5y": brent_vs_5y, "corr": corr, "infl36": infl36}}


def es(x: pd.Series, q: float = 0.05) -> float:
    """Expected shortfall: minus the mean of the worst q share of outcomes (a positive number is a loss)."""
    x = x.dropna().sort_values()
    k = max(1, int(math.floor(q * len(x))))
    return float(-x.iloc[:k].mean())


def hedge_selector(book: pd.Series, hedges: dict[str, pd.Series], regime: pd.Series, weight: float = 0.3, q: float = 0.05,
                   periods_per_year: int = 12) -> dict:
    """Per regime and hedge: mean hedge return on the book's worst q periods, ES removed at `weight`, yearly carry."""
    out = {}
    for reg in [r for r in regime.dropna().unique()]:
        idx = regime[regime == reg].index
        b = book.reindex(idx).dropna()
        cut = b.quantile(q)
        worst = b[b <= cut].index
        es_book = es(b, q)
        rows = []
        for name, h in hedges.items():
            hh = h.reindex(b.index)
            ok = hh.notna()
            if ok.sum() < 24:
                continue
            bb, hh = b[ok], hh[ok]
            combo = bb + weight * hh
            carry = float(hh.mean() * periods_per_year)
            removed = es(bb, q) - es(combo, q)
            rows.append({"hedge": name, "on_worst": float(hh.reindex(worst).mean()), "es_removed": removed,
                         "carry": carry, "per_carry": removed / (-carry * weight) if carry < 0 else None,
                         "hit": float((hh.reindex(worst) > 0).mean()), "periods": int(ok.sum())})
        rows.sort(key=lambda r: -r["es_removed"])
        out[str(reg)] = {"periods": int(len(b)), "book_es": es_book, "rows": rows}
    return out


def fit_student_t(x: np.ndarray) -> tuple[float, float, float]:
    from scipy import stats
    df, loc, scale = stats.t.fit(x)
    return float(df), float(loc), float(scale)


def tail_risk(r: pd.Series, alpha: float = 0.975) -> dict:
    from scipy import stats
    x = np.log(1 + r.dropna().to_numpy())
    mu, sd = float(x.mean()), float(x.std(ddof=1))
    p = 1 - alpha
    z = stats.norm.ppf(p)
    es_norm = -(mu - sd * stats.norm.pdf(z) / p)
    nu, loc, sc = fit_student_t(x)
    tq = stats.t.ppf(p, nu)
    es_t = -(loc - sc * (stats.t.pdf(tq, nu) / p) * (nu + tq ** 2) / (nu - 1))
    hist = float(-np.sort(x)[: max(1, int(p * len(x)))].mean())
    return {"months": int(len(x)), "alpha": alpha, "normal": float(es_norm), "student_t": float(es_t), "historical": hist, "nu": nu,
            "var_normal": float(-(mu + sd * z)), "var_t": float(-(loc + sc * tq))}


EPISODES = [
    ("gulf-1990", "1990 Gulf War oil shock", "1990-08", "1990-10"),
    ("quant-2007", "August 2007 quant quake", "2007-07", "2007-08"),
    ("gfc-2008", "2008 credit crisis", "2008-09", "2009-02"),
    ("covid-2020", "March 2020 dash for cash", "2020-02", "2020-03"),
    ("inflation-2022", "2022 inflation bear market", "2022-01", "2022-09"),
]


def put_spread_returns(px_ret: pd.Series, vix: pd.Series, upper: float = 0.95, lower: float = 0.85, skew: float = 3.0) -> pd.Series:
    """A one-month 95/85 put spread on 100% of the book, bought each month at the prior month's VIX plus `skew` points
    (Black-Scholes, zero rates and dividends), paid out on the month's price return. Returns per $1 of book."""
    from .analytics.options import bs
    v = (vix.resample("MS").last().shift(1, freq="MS") + skew) / 100      # the prior month's last VIX, dated to this month
    out = {}
    for d, R in px_ret.dropna().items():
        sig = v.get(d)
        if sig is None or not np.isfinite(sig):
            continue
        prem = bs(1.0, upper, 1 / 12, 0.0, 0.0, sig, "put")["price"] - bs(1.0, lower, 1 / 12, 0.0, 0.0, sig, "put")["price"]
        pay = max(upper - (1 + R), 0) - max(lower - (1 + R), 0)
        out[d] = pay - prem
    return pd.Series(out)


def replays(panel: pd.DataFrame, gold: pd.Series, brent_m: pd.Series, ps: pd.Series) -> list[dict]:
    """Cumulative returns over each episode window for the book, bonds, the hedge stack legs and two hedged books."""
    rows = []
    g = gold.pct_change()
    o = brent_m.pct_change()
    for key, name, a, b in EPISODES:
        sl = slice(a + "-01", b + "-01")
        r_eq = panel["r_eq"].loc[sl]
        if r_eq.empty:
            continue
        def cum(s):
            s = s.reindex(r_eq.index).fillna(0.0)
            return float((1 + s).prod() - 1)
        bonds_only = r_eq + 0.30 * panel["r_bd"].reindex(r_eq.index).fillna(0)
        stack = r_eq + ps.reindex(r_eq.index).fillna(0) + 0.04 * g.reindex(r_eq.index).fillna(0) + 0.04 * o.reindex(r_eq.index).fillna(0)
        rows.append({"key": key, "name": name, "from": a, "to": b, "book": cum(r_eq), "bond10": cum(panel["r_bd"]), "gold": cum(g),
                     "brent": cum(o), "put_spread": cum(ps), "book_plus_bonds": cum(bonds_only), "book_plus_stack": cum(stack)})
    return rows


def cpi_3m_annualized(cpi: pd.Series) -> float:
    c = cpi.dropna()
    return float((c.iloc[-1] / c.iloc[-4]) ** 4 - 1)


def run(raw: dict) -> dict:
    from .research import monthly_panel, tidy
    t = tidy(raw)
    panel = monthly_panel(t["shiller"], t["cpi"], t["y10"])
    px_ret = panel["px"] / panel["px"].shift(1) - 1
    infl36 = (panel["cpi"] / panel["cpi"].shift(36)) ** (1 / 3) - 1
    regime = pd.Series(np.where(infl36 >= LINE, "above_line", "below_line"), index=panel.index).where(infl36.notna())
    brent_m = t["brent"].resample("MS").mean()
    gold = t["gold"]
    ps = put_spread_returns(px_ret, t["vix"])
    hedges = {"10-year Treasury": panel["r_bd"], "Gold": gold.pct_change(), "Brent (spot)": brent_m.pct_change(), "Put spread 95/85": ps}
    since = "1990-02-01"
    sel = hedge_selector(panel["r_eq"].loc[since:], {k: v.loc[since:] for k, v in hedges.items()}, regime.loc[since:])
    corr36 = panel["r_eq"].rolling(36).corr(panel["r_bd"])
    brent_ratio = float(brent_m.iloc[-1] / brent_m.iloc[-61:-1].mean()) if len(brent_m) > 61 else float("nan")
    latest = {"month": panel.index[-1].strftime("%Y-%m"), "cpi_3m_ann": cpi_3m_annualized(t["cpi"]), "infl36": float(infl36.dropna().iloc[-1]),
              "corr36": float(corr36.dropna().iloc[-1]), "brent_vs_5y": brent_ratio}
    return {"schema": 1, "latest": latest, "selector": sel, "selector_since": since[:7], "tail": tail_risk(panel["r_eq"]),
            "tail_post1990": tail_risk(panel["r_eq"].loc[since:]), "replays": replays(panel, gold, brent_m, ps), "line": LINE}
