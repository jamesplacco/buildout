"""Stock-bond regime detection and shock classification.

Sign convention: correlation of equity RETURNS with bond RETURNS (prices, not yields).
Negative = bonds hedge equities. Positive = bonds amplify equity losses.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HEDGING, NEUTRAL, AMPLIFYING = "hedging", "neutral", "amplifying"


def ewm_corr(x: pd.Series, y: pd.Series, halflife: int = 63) -> pd.Series:
    return x.ewm(halflife=halflife, min_periods=halflife).corr(y)


def rolling_corr(x: pd.Series, y: pd.Series, window: int = 126) -> pd.Series:
    return x.rolling(window, min_periods=window // 2).corr(y)


def classify(corr: pd.Series, band: float = 0.10) -> pd.Series:
    """Three states with hysteresis so the label does not flicker around zero.

    Enter 'hedging' below -band and stay until corr crosses above 0; enter 'amplifying' above +band and
    stay until corr crosses below 0; otherwise 'neutral'.
    """
    out, state = [], NEUTRAL
    for c in corr.to_numpy():
        if np.isnan(c):
            out.append(None)
            continue
        if state == HEDGING and c > 0:
            state = NEUTRAL
        elif state == AMPLIFYING and c < 0:
            state = NEUTRAL
        if state == NEUTRAL:
            if c <= -band:
                state = HEDGING
            elif c >= band:
                state = AMPLIFYING
        out.append(state)
    return pd.Series(out, index=corr.index, name="regime")


def shock_table(equity: pd.Series, bond: pd.Series, q: float = 0.05, by: pd.Series | None = None) -> pd.DataFrame:
    """On the worst q of equity days, what did long bonds do? One fixed severity threshold for all groups.

    offset = bond move as a share of the equity loss (1.0 would fully offset at 1:1 notional).
    """
    df = pd.concat({"eq": equity, "bond": bond}, axis=1).dropna()
    cut = df["eq"].quantile(q)
    tail = df[df["eq"] <= cut]
    groups = by.reindex(tail.index) if by is not None else pd.Series("all", index=tail.index)
    rows = []
    for g, d in tail.groupby(groups):
        rows.append({"group": g, "days": len(d), "avg_equity": d["eq"].mean(), "avg_bond": d["bond"].mean(),
                     "bond_up_share": (d["bond"] > 0).mean(), "offset": -d["bond"].mean() / d["eq"].mean()})
    return pd.DataFrame(rows).set_index("group")


def episodes(regime: pd.Series) -> pd.DataFrame:
    """Contiguous runs of each regime label."""
    r = regime.dropna()
    change = r.ne(r.shift()).cumsum()
    g = r.groupby(change)
    return pd.DataFrame({"regime": g.first(), "start": g.apply(lambda s: s.index[0]),
                         "end": g.apply(lambda s: s.index[-1]), "days": g.size()}).reset_index(drop=True)
