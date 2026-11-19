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

The split guard (a one-day fall beyond 30% or rise beyond 45%, unexplained_jumps below) still runs after this, so a
split missing from the table stops the run by name.
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

# A ticker is not a company (v0.42.2). Two of the book's tickers named other securities earlier in the data window, and a
# pull by ticker returns those securities' prices under the book's name.
#   SPCX  SpaceX listed on Nasdaq on June 12, 2026. Until April 6, 2026 SPCX was Tuttle Capital's SPAC and New Issue ETF
#         (renamed SPCK on April 7, 2026).
#   META  Meta Platforms took the ticker on June 9, 2022 (it was FB). Until January 28, 2022 META was the Roundhill Ball
#         Metaverse ETF (renamed METV on January 31, 2022).
TICKER_SINCE = {"SPCX": "2026-06-12", "META": "2022-06-09"}       # the first session the ticker is this company
FORMER_TICKER = {"META": ("FB", "2022-06-09")}                    # the same company's earlier ticker, up to (not including) the date

# fund: (FRED constant-maturity series, expense ratio)
BOND_INCOME = {"TLT": ("DGS20", 0.0015), "IEF": ("DGS7", 0.0015)}

PRICE_ONLY_NOTE = "public split table; stock dividends excluded (price return); bond-fund income estimated from Treasury yields"


# The split guard (v0.47). After adjustment, a one-day fall beyond SPLIT_GUARD_DOWN or a rise beyond SPLIT_GUARD_UP is
# treated as a corporate action nobody recorded, and stops the run by name. A forward split is a fall (2-for-1 is -50%,
# 3-for-2 is -33%); a reverse split is a rise of 100% or more. Before, one symmetric 45% line let a 2-for-1 through on
# any day the stock itself rose 10% (-44.5%), and every 3-for-2. The lines sit outside every genuine one-day move of
# the book's names and factor funds since 2016 (largest fall: Meta -26.4% on Feb 3, 2022; largest rise: Oracle +35.9%
# on Sep 10, 2025). A genuine move beyond them is possible: once checked against the company's own news it is listed
# in CONFIRMED_MOVES and the run goes on. Failing closed costs a day; sizing a book on a phantom -50% costs more.
SPLIT_GUARD_DOWN = 0.30
SPLIT_GUARD_UP = 0.45
CONFIRMED_MOVES: dict[str, tuple[str, ...]] = {}       # symbol: ("YYYY-MM-DD", ...) genuine moves beyond the guard, verified by hand


def unexplained_jumps(closes: pd.DataFrame, down: float = SPLIT_GUARD_DOWN, up: float = SPLIT_GUARD_UP,
                      confirmed: dict | None = None) -> dict[str, list[dict]]:
    """One-day moves in adjusted closes that look like an unrecorded corporate action: {symbol: [{date, change,
    looks_like}]}. `closes` is indexed by date, one column a symbol; `looks_like` names the standard split the ratio
    is nearest ('2:1', '3:2', '1:10') when there is one."""
    from .validate import match_split
    ok = CONFIRMED_MOVES if confirmed is None else confirmed
    out: dict[str, list[dict]] = {}
    for sym in closes.columns:
        s = closes[sym].astype(float).dropna()
        r = s / s.shift(1) - 1.0
        bad = r[(r < -down) | (r > up)]
        skip = set(ok.get(str(sym).upper(), ())) | set(ok.get(str(sym), ()))
        rows = [{"date": d.strftime("%Y-%m-%d"), "change": float(v), "looks_like": match_split(1.0 + float(v), tol=0.15)}
                for d, v in bad.items() if d.strftime("%Y-%m-%d") not in skip]
        if rows:
            out[str(sym)] = rows
    return out


def jump_message(bad: dict[str, list[dict]]) -> str:
    """The error text for unexplained_jumps: every move by name and date, what it looks like, and what to do."""
    parts = []
    for sym, rows in bad.items():
        parts.append(f"{sym}: " + ", ".join(f"{r['date']} {r['change']:+.0%}" + (f" (a {r['looks_like']} split?)" if r["looks_like"] else "") for r in rows[:5]))
    hint = "; ".join(f"{k}: {v}" for k, v in PENDING.items() if k in bad)
    return ("One-day moves beyond the split guard look like unadjusted corporate actions: " + "; ".join(parts)
            + ". Add the split to SPLITS in buildout/data/corporate_actions.py, or, if the move is genuine, the date to CONFIRMED_MOVES."
            + (f" Pending: {hint}" if hint else ""))


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
