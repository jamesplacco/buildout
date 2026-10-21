"""Daily backtester with explicit dollars: positions, cash, financing, trading costs.

Timing rule: target weights at row t are decided with information through the close of t, traded at
the close of t, and first earn the return of day t+1. Look-ahead is impossible unless the targets
themselves peek, which the canary test in tests/ checks for.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Result:
    equity: pd.Series
    returns: pd.Series
    weights: pd.DataFrame
    turnover: pd.Series
    costs: pd.Series
    financing: pd.Series


def run(returns: pd.DataFrame, targets: pd.DataFrame, cost_bps: float = 2.0,
        cash_rate: pd.Series | float = 0.0, borrow_spread_bps: float = 100.0,
        rebalance_every: int = 1, band: float | None = None) -> Result:
    cols = list(targets.columns)
    idx = returns.index
    R = returns.reindex(columns=cols).fillna(0.0).to_numpy()
    T = targets.reindex(idx).to_numpy()
    rate = (cash_rate.reindex(idx).ffill().fillna(0.0).to_numpy() if isinstance(cash_rate, pd.Series)
            else np.full(len(idx), float(cash_rate))) / 252
    spread = borrow_spread_bps / 1e4 / 252

    n = len(idx)
    nav, pos = 1.0, np.zeros(len(cols))
    eq, rets, turn, cst, fin = (np.zeros(n) for _ in range(5))
    wts = np.zeros((n, len(cols)))
    last_trade = -10 ** 9
    for t in range(len(idx)):
        if t > 0:
            cash = nav - pos.sum()
            pos = pos * (1 + R[t])
            carry = cash * (rate[t] + (spread if cash < 0 else 0.0))
            new_nav = pos.sum() + cash + carry
            rets[t] = new_nav / nav - 1
            fin[t] = carry / nav
            nav = new_nav
        tgt = T[t]
        if not np.isnan(tgt).all() and t - last_trade >= rebalance_every:
            tgt = np.nan_to_num(tgt) * nav
            if band is not None:
                cur_w, tgt_w = pos / nav, tgt / nav
                keep = np.abs(cur_w - tgt_w) <= band * np.maximum(np.abs(tgt_w), 1e-9)
                tgt = np.where(keep, pos, tgt)
            trades = tgt - pos
            cost = np.abs(trades).sum() * cost_bps / 1e4
            if np.abs(trades).sum() > 0:
                turn[t] = np.abs(trades).sum() / nav
                cst[t] = cost / nav
                pos = tgt
                nav -= cost
                last_trade = t
        eq[t] = nav
        wts[t] = pos / nav
    return Result(equity=pd.Series(eq, idx, name="equity"), returns=pd.Series(rets, idx, name="ret"),
                  weights=pd.DataFrame(wts, idx, cols), turnover=pd.Series(turn, idx, name="turnover"),
                  costs=pd.Series(cst, idx, name="costs"), financing=pd.Series(fin, idx, name="financing"))
