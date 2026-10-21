"""Synthetic market with KNOWN answers, used to prove the engine works before trusting it on real data.

Two Markov regimes govern the stock-bond relationship:
  hedging    : long bonds rally when equities fall (growth shocks dominate)
  amplifying : long bonds fall with equities (inflation / term-premium shocks dominate)
Each stock's market, AI and rates betas are drawn once and returned as ground truth. Alphas are zero,
so any "edge" a signal finds here is overfitting by construction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class World:
    prices: pd.DataFrame
    factors: pd.DataFrame            # true factor returns: market, ai, rates
    yields: pd.DataFrame             # DGS10, DGS30 in percent
    rf: pd.Series                    # annualized cash rate, decimal
    regime: pd.Series                # 'hedging' / 'amplifying'
    true_betas: pd.DataFrame         # index ticker, columns market, ai, rates
    true_corr: dict[str, float] = field(default_factory=dict)


def simulate(book: list[str], hedges: tuple[str, ...] = ("TLT", "IEF"), market: str = "QQQ",
             n_days: int = 2520, seed: int = 7, p_stay: float = 0.996,
             rho: dict[str, float] | None = None, end: str = "2026-10-16",
             ipo_days: dict[str, int] | None = None) -> World:
    rho = rho or {"hedging": -0.45, "amplifying": 0.45}
    ipo_days = {"SPCX": 90} if ipo_days is None else ipo_days
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=end, periods=n_days)

    states = np.zeros(n_days, dtype=int)
    for t in range(1, n_days):
        states[t] = 1 - states[t - 1] if rng.random() > p_stay else states[t - 1]
    labels = np.where(states == 0, "hedging", "amplifying")

    z = rng.standard_normal((n_days, 4))
    h = np.ones(n_days)                      # GARCH(1,1) variance multiplier, long-run mean 1
    for t in range(1, n_days):
        h[t] = 0.02 + 0.08 * z[t - 1, 0] ** 2 * h[t - 1] + 0.90 * h[t - 1]
    v = np.sqrt(h)

    sig_m, sig_b, sig_a = 0.013, 0.009, 0.008
    mu_m, mu_b = 0.0004, 0.00018
    rho_t = np.where(states == 0, rho["hedging"], rho["amplifying"])
    mkt = mu_m + sig_m * v * z[:, 0]
    bond = mu_b + sig_b * v * (rho_t * z[:, 0] + np.sqrt(1 - rho_t ** 2) * z[:, 1])
    ai = sig_a * v * z[:, 2]

    betas = pd.DataFrame({"market": rng.uniform(0.9, 1.5, len(book)),
                          "ai": rng.uniform(0.4, 1.6, len(book)),
                          "rates": rng.uniform(-0.3, 0.4, len(book))}, index=book)
    idio = rng.uniform(0.010, 0.020, len(book))
    rets = {}
    for i, name in enumerate(book):
        eps = rng.standard_normal(n_days)
        b = betas.loc[name]
        rets[name] = b["market"] * mkt + b["ai"] * ai + b["rates"] * bond + idio[i] * v * eps
    rets[market] = mkt
    if "TLT" in hedges:
        rets["TLT"] = bond
    if "IEF" in hedges:
        rets["IEF"] = 0.45 * bond + 0.001 * v * z[:, 3]
    r = pd.DataFrame(rets, index=dates)
    prices = 100 * (1 + r).cumprod()
    for name, days in ipo_days.items():
        if name in prices:
            prices.loc[prices.index[: n_days - days], name] = np.nan

    duration = 16.0
    y30 = 4.0 - np.cumsum((bond - mu_b) / duration * 100)
    y10 = y30 - 0.35 + 0.02 * rng.standard_normal(n_days).cumsum() * 0.05
    yields = pd.DataFrame({"DGS10": y10, "DGS30": y30}, index=dates)
    factors = pd.DataFrame({"market": mkt, "ai": ai, "rates": bond}, index=dates)
    return World(prices=prices, factors=factors, yields=yields, rf=pd.Series(0.04, index=dates, name="rf"),
                 regime=pd.Series(labels, index=dates, name="regime"), true_betas=betas, true_corr=dict(rho))
