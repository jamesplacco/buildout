"""Stress tests: replay historical episodes and price hypothetical factor shocks."""
from __future__ import annotations

import pandas as pd

from .bonds import calibrate_coupon, shock_return

EPISODES = {
    "COVID crash": ("2020-02-19", "2020-03-23"),
    "2022 inflation shock": ("2022-01-03", "2022-10-12"),
    "Yen carry unwind": ("2024-07-10", "2024-08-05"),
    "DeepSeek shock": ("2025-01-24", "2025-01-27"),
    "Tariff shock": ("2025-04-02", "2025-04-08"),
    "March 2026 risk-off": ("2026-02-27", "2026-03-31"),
}

# Assumptions, not forecasts. market = QQQ move, ai = AI basket move in excess of QQQ, dy_bp = long-end yield change.
SCENARIOS = [
    {"name": "AI capex digestion (growth scare)", "market": -0.15, "ai": -0.15, "dy_bp": -75},
    {"name": "AI financing / term-premium shock", "market": -0.10, "ai": -0.10, "dy_bp": 75},
    {"name": "Inflation + hikes (2022 replay)", "market": -0.20, "ai": -0.10, "dy_bp": 125},
    {"name": "AI melt-up, yields up", "market": 0.10, "ai": 0.15, "dy_bp": 50},
    {"name": "Soft landing, cuts", "market": 0.08, "ai": 0.05, "dy_bp": -50},
]


def episode_returns(prices: pd.DataFrame, episodes: dict[str, tuple[str, str]] = EPISODES) -> pd.DataFrame:
    """Close-to-close return of each column from the start date's close to the end date's close."""
    rows = {}
    for name, (s, e) in episodes.items():
        if prices.index[0] > pd.Timestamp(s) or prices.index[-1] < pd.Timestamp(e):
            continue
        rows[name] = prices.loc[:e].iloc[-1] / prices.loc[:s].iloc[-1] - 1
    return pd.DataFrame(rows).T


def long_bond_return(dy_bp: float, y0: float = 0.0558, maturity: float = 25.8, duration: float = 15.5) -> float:
    """Instant TLT-like return for a long-end yield shock, via a representative bond calibrated to TLT's duration."""
    coupon = calibrate_coupon(y0, maturity, duration)
    return shock_return(y0, dy_bp / 1e4, maturity, coupon)


def scenario_pnl(weights: pd.Series, betas: pd.DataFrame, hedge_ratio: float, scenario: dict,
                 y0: float = 0.0558, duration: float = 15.5) -> dict:
    """Book P&L (fraction of NAV) through factor betas, plus a TLT hedge of `hedge_ratio` x book notional."""
    bond = long_bond_return(scenario["dy_bp"], y0=y0, duration=duration)
    b = betas.reindex(weights.index)
    stock = b["market"] * scenario["market"] + b["ai"] * scenario["ai"] + b["rates"] * bond
    book = float((weights * stock).sum())
    hedge = float(hedge_ratio * weights.sum() * bond)
    return {"scenario": scenario["name"], "book": book, "hedge": hedge, "net": book + hedge, "long_bond": bond}
