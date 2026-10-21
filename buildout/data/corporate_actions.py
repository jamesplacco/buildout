"""Free fallback for corporate actions, used when Databento's adjustment factors are not on the account.

Databento sells split and dividend adjustment factors as reference data (a separate paid plan). Without them the
engine refuses unadjusted prices, because a 10-for-1 split reads as a 90% crash. This module replaces them with:

  1. SPLITS: the public split history of every symbol the model book trades, since the data starts (2018-05-01).
     Splits are public facts, announced by the companies and listed by the exchanges. Back-adjustment is the same
     arithmetic Databento's factors use: every close before the ex-date is multiplied by 1 / ratio.
  2. Bond-fund income: TLT and IEF pay most of their return as monthly distributions, so price alone understates a
     bond hedge by about 2 to 4.5 points a year. The fallback accrues the matching constant-maturity Treasury yield
     (FRED), less the fund's expense ratio, one 252nd per trading day. Labelled Estimated: when a fund's bonds trade
     below par, the yield to maturity exceeds the cash it distributes (the gap returns as pull to par in the price),
     so this overstates income by roughly that gap, about half a point a year in 2023 to 2026, and much less before.
  3. Stock dividends are left out (price return). For this book they are small (0 to 1.3% a year) and barely move
     daily betas or correlations; the report says so.

The 45% one-day jump guard still runs after this, so a split missing from the table stops the run by name.
"""
from __future__ import annotations

import pandas as pd

# symbol: [(ex-date, shares after per share before)]. Verified against company announcements.
SPLITS: dict[str, list[tuple[str, float]]] = {
    "TSLA": [("2020-08-31", 5.0), ("2022-08-25", 3.0)],
    "NVDA": [("2021-07-20", 4.0), ("2024-06-10", 10.0)],
    "AMZN": [("2022-06-06", 20.0)],
    "GOOGL": [("2022-07-18", 20.0)],
    "AVGO": [("2024-07-15", 10.0)],
}
# no splits since 2018-05-01: MSFT, META, ORCL, QQQ, TLT, IEF, SPCX (listed June 12, 2026)
NO_SPLITS = ("MSFT", "META", "ORCL", "QQQ", "TLT", "IEF", "SPCX")
# announced, dates not yet set: add the row to SPLITS on the ex-date (the jump guard will insist)
PENDING = {"META": "2-for-1 through a non-voting Class C share for each Class A share, announced Oct 21, 2026; "
                   "record and distribution dates not yet announced"}

# fund: (FRED constant-maturity series, expense ratio)
BOND_INCOME = {"TLT": ("DGS20", 0.0015), "IEF": ("DGS7", 0.0015)}

PRICE_ONLY_NOTE = "public split table; stock dividends excluded (price return); bond-fund income estimated from Treasury yields"


def split_factors(symbols, splits: dict | None = None) -> pd.DataFrame:
    """The table in the shape Databento's adjustment factors use: symbol, ex_date, factor (1 / ratio)."""
    rows = [{"symbol": s, "ex_date": pd.Timestamp(d), "factor": 1.0 / r}
            for s, evs in (splits or SPLITS).items() if s in set(symbols) for d, r in evs]
    return pd.DataFrame(rows, columns=["symbol", "ex_date", "factor"])


def add_bond_income(closes: pd.DataFrame, yields_pct: pd.DataFrame, funds: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Rebuild each bond fund's close as a total-return index: price return plus the day's accrued income.

    yields_pct: FRED yields in percent, indexed by date. Returns the new closes and, per fund, the income used.
    """
    out = closes.astype(float).copy()
    used = {}
    for fund, (series, fee) in (funds or BOND_INCOME).items():
        if fund not in out.columns or series not in yields_pct.columns:
            continue
        px = out[fund]
        y = (yields_pct[series].astype(float) / 100).reindex(px.index).ffill()
        income = ((y - fee) / 252).where(px.notna()).fillna(0.0)
        r = px.pct_change(fill_method=None)
        tr = (r + income).where(r.notna())
        first = px.first_valid_index()
        if first is None:
            continue
        idx = (1 + tr.fillna(0.0)).cumprod()
        idx = idx / idx.loc[first] * px.loc[first]
        out[fund] = idx.where(px.notna())
        used[fund] = {"series": series, "expense_ratio": fee, "avg_income_ann": float(((y - fee).loc[first:]).mean())}
    return out, used
