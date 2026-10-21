"""Free-data regime monitor: is the long Treasury hedging US growth stocks right now?

FRED only, no key. Equity side: the Nasdaq-100 index. Bond side: a 20-year par bond repriced daily from
the constant-maturity yield (DGS20 runs unbroken since October 1993). Correlation is scale-free, so the
bond's lower duration versus TLT does not change the regime read; hedge ratios are in 20-year-bond notional.
"""
from __future__ import annotations

import pandas as pd

from .analytics import hedge, regime
from .analytics.bonds import constant_maturity_returns
from .jsonout import series

CURVE = [("1M", "DGS1MO", 1 / 12), ("3M", "DGS3MO", 0.25), ("6M", "DGS6MO", 0.5), ("1Y", "DGS1", 1.0),
         ("2Y", "DGS2", 2.0), ("3Y", "DGS3", 3.0), ("5Y", "DGS5", 5.0), ("7Y", "DGS7", 7.0),
         ("10Y", "DGS10", 10.0), ("20Y", "DGS20", 20.0), ("30Y", "DGS30", 30.0)]
MARKETS = {"real10": "DFII10", "breakeven10": "T10YIE", "term_premium10": "THREEFYTP10", "ig_oas": "BAMLC0A0CM",
           "hy_oas": "BAMLH0A0HYM2", "vix": "VIXCLS", "dollar_broad": "DTWEXBGS", "brent": "DCOILBRENTEU",
           "wti": "DCOILWTICO"}
FRED_IDS = ["NASDAQ100"] + [c for _, c, _ in CURVE] + list(MARKETS.values())
REQUIRED = ["NASDAQ100", "DGS20"]
# Stress episodes: (key, name, kind, search window). The code finds the Nasdaq-100 peak and trough inside
# each window, so the windows only need to bracket the event. kind: growth | inflation | liquidity | credit | rates | mixed
EPISODES = [
    ("crash-1987", "October 1987 crash", "liquidity", "1987-08-01", "1987-12-31"),
    ("gulf-1990", "1990 Gulf War recession", "growth", "1990-07-01", "1990-10-31"),
    ("bonds-1994", "1994 bond rout", "inflation", "1994-01-01", "1994-12-31"),
    ("ltcm-1998", "1998 Russia default and LTCM", "liquidity", "1998-07-01", "1998-10-31"),
    ("dotcom-2000", "2000 to 2002 dot-com bust", "growth", "2000-03-01", "2002-10-31"),
    ("gfc-2008", "2007 to 2009 financial crisis", "credit", "2007-10-01", "2009-03-31"),
    ("downgrade-2011", "2011 euro crisis and US downgrade", "growth", "2011-04-01", "2011-10-31"),
    ("taper-2013", "2013 taper tantrum", "rates", "2013-05-01", "2013-09-30"),
    ("china-2015", "2015 to 2016 China and oil", "growth", "2015-07-01", "2016-02-29"),
    ("vol-2018", "February 2018 volatility shock", "liquidity", "2018-01-15", "2018-02-28"),
    ("q4-2018", "Late 2018 tightening scare", "growth", "2018-09-15", "2018-12-31"),
    ("covid-2020", "2020 COVID crash", "liquidity", "2020-02-01", "2020-03-31"),
    ("inflation-2022", "2022 inflation bear market", "inflation", "2021-11-01", "2022-12-31"),
    ("banks-2023", "March 2023 bank failures", "credit", "2023-03-01", "2023-03-31"),
    ("carry-2024", "August 2024 yen carry unwind", "liquidity", "2024-07-01", "2024-08-31"),
    ("tariffs-2025", "2025 tariff shock", "mixed", "2025-02-01", "2025-04-30"),
    ("iran-2026", "2026 Iran war and oil shock", "inflation", "2026-02-15", "2026-04-30"),
]
ERAS = [("1994–1999", "1994-01-01", "1999-12-31"), ("2000–2009", "2000-01-01", "2009-12-31"),
        ("2010–2019", "2010-01-01", "2019-12-31"), ("2020–2021", "2020-01-01", "2021-12-31"),
        ("2022–now", "2022-01-01", None)]


def build_returns(fred: pd.DataFrame) -> pd.DataFrame:
    eq = fred["NASDAQ100"].dropna().pct_change(fill_method=None)
    bond = constant_maturity_returns(fred["DGS20"].dropna(), maturity=20.0)
    return pd.concat({"equity": eq, "bond": bond}, axis=1).dropna()


def _last(fred: pd.DataFrame, col: str) -> tuple[float | None, str | None]:
    if col not in fred:
        return None, None
    s = fred[col].dropna()
    return (float(s.iloc[-1]), s.index[-1].strftime("%Y-%m-%d")) if len(s) else (None, None)


def _curve_at(f: pd.DataFrame, date: pd.Timestamp) -> dict | None:
    rows = f.loc[:date]
    if rows.empty:
        return None
    row = rows.iloc[-1]
    pts = [{"tenor": t, "years": y, "yield": float(row[c])} for t, c, y in CURVE if c in f and pd.notna(row[c])]
    return {"date": rows.index[-1].strftime("%Y-%m-%d"), "points": pts}


def rates_block(fred: pd.DataFrame, since: str = "2000-01-01") -> dict:
    """Curve snapshots, spread history and cross-asset levels for the Rates and Desk views."""
    f = fred.ffill()
    if "DGS10" not in f or f["DGS10"].dropna().empty:
        return {}
    last = f["DGS10"].dropna().index[-1]
    curves = {"latest": _curve_at(f, last), "start_of_year": _curve_at(f, pd.Timestamp(last.year, 1, 1) - pd.Timedelta(days=1)),
              "year_ago": _curve_at(f, last - pd.DateOffset(years=1)), "two_years_ago": _curve_at(f, last - pd.DateOffset(years=2))}
    spreads = {}
    for name, (a, b) in {"2s10s": ("DGS10", "DGS2"), "3m10y": ("DGS10", "DGS3MO"), "10s30s": ("DGS30", "DGS10")}.items():
        if a in fred and b in fred:
            spreads[name] = series((fred[a] - fred[b]).dropna().loc[since:] * 100)
    history = {k: series(fred[c].dropna().loc[since:]) for k, c in MARKETS.items() if c in fred and fred[c].notna().any()}
    levels = {}
    for k, c in MARKETS.items():
        v, d = _last(fred, c)
        if v is not None:
            levels[k] = {"value": v, "date": d}
    return {"curves": curves, "spreads_bp": spreads, "history": history, "levels": levels}


def _asof(s: pd.Series | None, date: pd.Timestamp) -> float | None:
    if s is None:
        return None
    s = s.dropna().loc[:date]
    return float(s.iloc[-1]) if len(s) else None


def _bp(s: pd.Series | None, a: pd.Timestamp, b: pd.Timestamp) -> float | None:
    x, y = _asof(s, a), _asof(s, b)
    return None if x is None or y is None else (y - x) * 100


def episode_stats(fred: pd.DataFrame, start: str, end: str | None, to_end: bool = False) -> dict | None:
    """Nasdaq-100 peak to trough inside the window, and what bonds, rates, volatility and oil did over it.

    to_end measures from the peak to the last day instead (a drawdown still in progress).
    """
    eq = fred["NASDAQ100"].dropna().loc[start:end]
    if len(eq) < 5:
        return None
    trough = eq.index[-1] if to_end else eq.idxmin()
    peak = eq.loc[:trough].idxmax()
    if peak == trough:
        return None
    def has(c: str) -> bool:                      # the series must actually print inside the episode
        return c in fred and fred[c].dropna().loc[peak:trough].size >= 3

    col = "DGS20" if has("DGS20") else "DGS30"    # DGS20 was not published from 1987 to late 1993
    get = lambda c: fred[c] if c in fred else None  # noqa: E731
    out = {"peak": peak.strftime("%Y-%m-%d"), "trough": trough.strftime("%Y-%m-%d"), "days": int((trough - peak).days),
           "equity_return": float(eq[trough] / eq[peak] - 1), "bond_series": None, "bond_return": None, "corr": None}
    if has(col):
        y = fred[col].dropna().loc[peak - pd.Timedelta(days=10):trough]
        r = constant_maturity_returns(y, maturity=20.0 if col == "DGS20" else 30.0).loc[peak:trough].iloc[1:].dropna()
        if len(r):
            out["bond_series"], out["bond_return"] = col, float((1 + r).prod() - 1)
            both = pd.concat({"e": eq.pct_change(fill_method=None), "b": r}, axis=1).dropna()
            if len(both) >= 15:
                out["corr"] = float(both["e"].corr(both["b"]))
    out["d10_bp"], out["d2_bp"] = _bp(get("DGS10"), peak, trough), _bp(get("DGS2"), peak, trough)
    out["breakeven_bp"], out["hy_oas_bp"] = _bp(get("T10YIE"), peak, trough), _bp(get("BAMLH0A0HYM2"), peak, trough)
    vix = get("VIXCLS")
    window = vix.dropna().loc[peak:trough] if vix is not None else pd.Series(dtype=float)
    out["vix_max"] = float(window.max()) if len(window) else None
    oil = get("DCOILBRENTEU") if has("DCOILBRENTEU") else get("DCOILWTICO")
    a, b = _asof(oil, peak), _asof(oil, trough)
    out["oil_return"] = (b / a - 1) if a and b else None
    out["bonds_hedged"] = None if out["bond_return"] is None else out["bond_return"] > 0
    return out


def episode_atlas(fred: pd.DataFrame) -> list[dict]:
    rows = []
    for key, name, kind, start, end in EPISODES:
        st = episode_stats(fred, start, end)
        if st is not None:
            rows.append({"key": key, "name": name, "kind": kind, **st})
    eq = fred["NASDAQ100"].dropna()
    if len(eq) > 260:                             # the drawdown in progress, from the trailing one-year high
        last = eq.index[-1]
        peak = eq.loc[last - pd.DateOffset(years=1):].idxmax()
        if peak != last:
            st = episode_stats(fred, peak.strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d"), to_end=True)
            if st is not None:
                rows.append({"key": "current", "name": "Current drawdown from the one-year high", "kind": "open", **st})
    return rows


def coverage(fred: pd.DataFrame) -> dict:
    out = {}
    for c in fred.columns:
        s = fred[c].dropna()
        if len(s):
            out[c] = {"first": s.index[0].strftime("%Y-%m-%d"), "last": s.index[-1].strftime("%Y-%m-%d"), "n": int(len(s))}
    return out


def analyze_macro(fred: pd.DataFrame, halflife: int = 63, q: float = 0.05, since: str = "2018-01-01",
                  failed: dict | None = None) -> dict:
    missing = [c for c in REQUIRED if c not in fred or fred[c].dropna().empty]
    if missing:
        raise ValueError(f"required FRED series missing: {missing}")
    df = build_returns(fred)
    eq, bd = df["equity"], df["bond"]
    c63 = regime.ewm_corr(eq, bd, halflife)
    c252 = regime.rolling_corr(eq, bd, 252)
    lab = regime.classify(c63)

    yearly = [{"year": int(y), "corr": float(g["equity"].corr(g["bond"])), "days": int(len(g))}
              for y, g in df.groupby(df.index.year) if len(g) >= 40]
    era = pd.Series(None, index=df.index, dtype=object)
    for name, s, e in ERAS:
        era.loc[s:e] = name
    pol = hedge.policies(eq, bd, halflife, static=0.30)
    recent = slice("2022-01-01", None)

    latest = {"as_of": df.index[-1].strftime("%Y-%m-%d"), "corr63": float(c63.dropna().iloc[-1]),
              "corr252": float(c252.dropna().iloc[-1]), "regime": lab.dropna().iloc[-1],
              "regime_since": regime.episodes(lab).iloc[-1]["start"].strftime("%Y-%m-%d"),
              "hedge_ratio_gated": float(pol["regime_gated"].dropna().iloc[-1]),
              "hedge_ratio_minvar": float(pol["min_var_long_only"].dropna().iloc[-1])}
    for col in ["DGS3MO", "DGS2", "DGS10", "DGS30", "T10YIE", "VIXCLS", "NASDAQ100"]:
        v, d = _last(fred, col)
        latest[col] = v
        latest[f"{col}_date"] = d
    if latest["DGS30"] is not None and latest["DGS3MO"] is not None:
        latest["curve_30y_3m"] = latest["DGS30"] - latest["DGS3MO"]

    return {
        "source": "FRED (NASDAQ100, DGS20 and companions); 20-year par bond repriced daily",
        "start": df.index[0].strftime("%Y-%m-%d"),
        "latest": latest,
        "corr63": series(c63.loc[since:]),
        "corr252": series(c252.loc[since:]),
        "yearly": yearly,
        "shock_by_era": regime.shock_table(eq, bd, q, by=era).reindex([e[0] for e in ERAS]).dropna(how="all"),
        "shock_by_regime": regime.shock_table(eq, bd, q, by=lab),
        "policies_full": hedge.evaluate_policies(eq, bd, pol, q),
        "policies_since_2022": hedge.evaluate_policies(eq.loc[recent], bd.loc[recent], pol.loc[recent], q),
        "rates": rates_block(fred),
        "episodes": episode_atlas(fred),
        "coverage": coverage(fred),
        "failed_series": failed or {},
    }
