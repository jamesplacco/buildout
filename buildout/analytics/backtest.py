"""Daily backtester with explicit dollars: positions, cash, financing, trading costs.

Timing rule: target weights at row t use information through the close of t. With exec_lag=0 they trade at
that same close (the optimistic close-to-close convention); with exec_lag=1 (the pipeline default) they trade
at the next session's close, so a signal computed from today's official close is never filled at it.
Look-ahead is impossible unless the targets themselves peek, which the canary test in tests/ checks for.

Accounting convention (one NAV, one return series): NAV starts at 1.0 before the first trade. Every cost and
every financing charge is taken out of NAV on the day it happens, and returns[t] = NAV[t] / NAV[t-1] - 1 with
NAV[-1] = 1.0, so the inception trade's cost is in the first return and prod(1 + returns) == equity[-1]
exactly. Charts, CAGR, Sharpe and drawdown all come from this one series.
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
        rebalance_every: int = 1, band: float | None = None, exec_lag: int = 0) -> Result:
    cols = list(targets.columns)
    idx = returns.index
    R = returns.reindex(columns=cols).fillna(0.0).to_numpy()
    T = targets.reindex(idx).shift(exec_lag).to_numpy() if exec_lag else targets.reindex(idx).to_numpy()
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
        rets[t] = nav / (eq[t - 1] if t > 0 else 1.0) - 1      # after costs and financing: reconciles to NAV
        wts[t] = pos / nav
    return Result(equity=pd.Series(eq, idx, name="equity"), returns=pd.Series(rets, idx, name="ret"),
                  weights=pd.DataFrame(wts, idx, cols), turnover=pd.Series(turn, idx, name="turnover"),
                  costs=pd.Series(cst, idx, name="costs"), financing=pd.Series(fin, idx, name="financing"))
