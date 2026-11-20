"""Portfolio accounting in one place (v0.48): net asset value, drawdown, and the trades a rebalance needs.

Not to be confused with buildout/accounting.py, which is corporate (capex, depreciation, required revenue).

One order of events, the same for a backtest day and a paper pass:

    starting positions and cash
      -> marks (each position at today's price; the sum with cash is the pre-trade NAV)
      -> desired dollar positions (target weight x pre-trade NAV: targets are stated before costs)
      -> net trades per instrument (desired minus held, after every component's request is added up)
      -> costs and fees (charged once, on the net trade, out of cash)
      -> ending positions, cash and NAV

Conventions, stated once:

    turnover    two-way: buys plus sells, in dollars, over the pre-trade NAV. A book that sells 1.875 and buys 0.625
                of a 102.50 NAV has traded 2.50, a turnover of 2.439%.
    targets     weights of the pre-trade, pre-cost NAV. Costs then come out of cash, so the post-cost weights of
                the risky positions are a hair above target; nothing is re-solved for that.
    drawdown    the fall from the highest value so far, and the starting value is a value: a path that opens with
                a loss is below its peak from the first day.
    fees        a positive fee is a cost and lowers cash; a negative one is a rebate. Charged once, where it occurs.

Before v0.48 the record's drawdown took the first day's close as the first peak, so a loss on day one was not a
drawdown, and the walk-forward charged the change in the sleeve's size and the trades inside the sleeve as two
separate sums, so a name sold by one and bought by the other paid for both.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def levels(returns, start: float = 1.0) -> np.ndarray:
    """The value path including its starting value: [start, start (1 + r1), ...]."""
    r = np.asarray(pd.Series(returns).dropna(), dtype=float)
    return np.concatenate([[float(start)], float(start) * np.cumprod(1.0 + r)])


def drawdown_path(returns, start: float = 1.0) -> np.ndarray:
    """Fraction below the running peak after each return (the starting value counts as a peak)."""
    lv = levels(returns, start)
    return (1.0 - lv / np.maximum.accumulate(lv))[1:]


def max_drawdown(returns, start: float = 1.0) -> float:
    """The worst peak-to-trough fall, as a positive fraction. An empty path has none."""
    d = drawdown_path(returns, start)
    return float(d.max()) if len(d) else 0.0


def net_trades(*components: dict) -> dict:
    """Signed dollar trades per instrument once every component's request is added up. Two parts of a strategy
    that ask for equal and opposite trades in one instrument ask the market for nothing."""
    out: dict = {}
    for c in components:
        for k, v in (c or {}).items():
            out[k] = out.get(k, 0.0) + float(v)
    return {k: v for k, v in out.items() if abs(v) > 1e-12}


def traded(trades: dict) -> float:
    """Dollars traded: buys plus sells."""
    return float(sum(abs(v) for v in trades.values()))


def rebalance(positions: dict, cash: float, returns: dict | None, targets: dict, cost_bp: float = 0.0, fee: float = 0.0) -> dict:
    """One accounting step. `positions` are dollars held before the marks; `returns` the move in each since then;
    `targets` the weights wanted, of the pre-trade NAV (what is not named is cash). Trades are the net per
    instrument; `cost_bp` is charged on the dollars traded and `fee` once, both out of cash."""
    for name, v in (("cash", cash), ("cost_bp", cost_bp), ("fee", fee)):
        if not math.isfinite(float(v)):
            raise ValueError(f"{name} is not a finite number")
    marked = {k: float(v) * (1.0 + float((returns or {}).get(k, 0.0))) for k, v in positions.items()}
    pre_nav = float(cash) + sum(marked.values())
    if pre_nav <= 0:
        raise ValueError("the pre-trade NAV is not positive")
    want = {k: float(w) * pre_nav for k, w in targets.items()}
    trades = net_trades(want, {k: -v for k, v in marked.items()})
    dollars = traded(trades)
    cost = dollars * float(cost_bp) / 1e4
    after = {k: marked.get(k, 0.0) + trades.get(k, 0.0) for k in set(marked) | set(trades)}
    after = {k: v for k, v in after.items() if abs(v) > 1e-12}
    cash_after = float(cash) - sum(trades.values()) - cost - float(fee)
    return {"pre_nav": pre_nav, "trades": trades, "traded": dollars, "turnover": dollars / pre_nav, "cost": cost, "fee": float(fee),
            "positions": after, "cash": cash_after, "nav": cash_after + sum(after.values())}


def charge_fee(cash: float, nav: float, fee: float) -> tuple[float, float]:
    """A fee comes out of cash, and so out of NAV, once."""
    if not math.isfinite(float(fee)):
        raise ValueError("the fee is not a finite number")
    return float(cash) - float(fee), float(nav) - float(fee)


def sleeve_turnover(g: pd.Series, R: pd.DataFrame, W: pd.DataFrame, nav_ret: pd.Series) -> pd.Series:
    """Two-way turnover, as a share of NAV, of holding the names at g of NAV with weights W inside the sleeve.

    g[t] and W[t] are what is held through day t; R[t] is each name's return on day t; nav_ret[t] the whole
    account's. The share of NAV in name i coming into day t is g[t-1] W[i,t-1] (1 + R[i,t-1]) / (1 + nav_ret[t-1]);
    the share wanted is g[t] W[i,t]. The trade is the difference, per name, and the turnover is the sum of the
    absolute differences. A change of the sleeve's size and a change of the weights inside it are one trade in
    each name here; charged separately they can never be less, and are more whenever they point opposite ways.
    The first day is the opening build."""
    Rf, Wf = R.reindex(g.index).fillna(0.0), W.reindex(g.index).fillna(0.0)
    A = Wf.mul(g, axis=0)
    pre = (A.shift(1) * (1.0 + Rf.shift(1))).div((1.0 + nav_ret.shift(1)), axis=0)
    t = (A - pre).abs().sum(axis=1)
    t.iloc[0] = float(A.iloc[0].abs().sum())
    return t.rename("turnover")
