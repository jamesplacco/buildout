"""How much of a backtest would survive a different history, and how much is selection?

  stationary_bootstrap  Politis and Romano (1994): resample the days in blocks of random (geometric) length, so
                        volatility clustering and autocorrelation survive the resampling. Every variant is resampled
                        on the SAME days, so the comparison between them is paired.
  bootstrap_stats       5th to 95th percentile of annualized Sharpe, CAGR and maximum drawdown per variant, and the
                        share of resampled histories in which each variant beats the unhedged book on Sharpe
  cscv_pbo              Bailey, Borwein, Lopez de Prado and Zhu (2017), combinatorially symmetric cross-validation:
                        split the history into S blocks, and for every way of choosing half of them as "in sample",
                        pick the best rule in sample and rank it out of sample. The probability of backtest
                        overfitting is the share of splits where that winner lands in the bottom half out of sample.
                        About 0.5 means picking the best backtest is no better than picking at random.
  rule_family           the hedge policy's neighbours: every entry threshold, exit threshold and hedge-ratio scale
                        near the chosen one, each backtested the same way (signal at t, position at t + 1, costs)
  plateau               the chosen rule's Sharpe against its neighbours': a choice on a plateau is robust; a lone peak
                        is a fitted accident
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


def stationary_bootstrap(n: int, draws: int, mean_block: float = 21.0, seed: int = 11) -> np.ndarray:
    """draws x n day indices: blocks start at random days and run for a geometric number of days, wrapping around."""
    rng = np.random.default_rng(seed)
    new = rng.random((draws, n)) < 1.0 / mean_block
    new[:, 0] = True
    starts = rng.integers(n, size=(draws, n))
    t = np.broadcast_to(np.arange(n), (draws, n))
    seg = np.maximum.accumulate(np.where(new, t, 0), axis=1)
    return (np.take_along_axis(starts, seg, axis=1) + t - seg) % n


def _ann_sharpe(R: np.ndarray, cash: np.ndarray, periods: int) -> np.ndarray:
    ex = R - cash
    sd = ex.std(axis=-1, ddof=1)
    return np.where(sd > 0, ex.mean(axis=-1) / np.where(sd > 0, sd, 1) * np.sqrt(periods), 0.0)


def _max_dd(R: np.ndarray) -> np.ndarray:
    eq = np.cumprod(1 + R, axis=-1)
    return (eq / np.maximum.accumulate(eq, axis=-1) - 1).min(axis=-1)


def bootstrap_stats(returns: dict[str, pd.Series], rf: pd.Series | float = 0.0, draws: int = 500, mean_block: float = 21.0,
                    periods: int = 252, base: str | None = None, seed: int = 11) -> dict:
    df = pd.concat(returns, axis=1).dropna()
    n = len(df)
    cash = (rf.reindex(df.index).ffill().fillna(0.0).to_numpy() if isinstance(rf, pd.Series) else np.full(n, float(rf))) / periods
    idx = stationary_bootstrap(n, draws, mean_block, seed)
    out = {}
    sharpes = {}
    for name in df.columns:
        R = df[name].to_numpy()[idx]
        C = cash[idx]
        sh = _ann_sharpe(R, C, periods)
        cagr = np.prod(1 + R, axis=1) ** (periods / n) - 1
        mdd = _max_dd(R)
        sharpes[name] = sh
        q = lambda a: [float(np.percentile(a, 5)), float(np.percentile(a, 50)), float(np.percentile(a, 95))]  # noqa: E731
        out[name] = {"sharpe": q(sh), "cagr": q(cagr), "max_drawdown": q(mdd)}
    if base and base in sharpes:
        for name in out:
            out[name]["p_beats_base"] = float(np.mean(sharpes[name] > sharpes[base])) if name != base else None
    return {"variants": out, "draws": draws, "mean_block_days": mean_block, "days": n, "base": base}


def cscv_pbo(M: np.ndarray, S: int = 12, periods: int = 252) -> dict:
    """M: T x N returns of N candidate rules. Probability of backtest overfitting over all C(S, S/2) splits."""
    M = np.asarray(M, float)
    T, N = M.shape
    if N < 2 or T < S * 5:
        return {"pbo": None, "reason": "too few rules or days"}
    T = (T // S) * S
    B = M[:T].reshape(S, T // S, N)
    s1, s2, cnt = B.sum(axis=1), (B ** 2).sum(axis=1), T // S
    logits, deg = [], []
    for ins in combinations(range(S), S // 2):
        mask = np.zeros(S, bool)
        mask[list(ins)] = True

        def sharpe(m):
            k = m.sum() * cnt
            mu = s1[m].sum(axis=0) / k
            var = s2[m].sum(axis=0) / k - mu ** 2
            return mu / np.sqrt(np.maximum(var, 1e-18))
        sin, sout = sharpe(mask), sharpe(~mask)
        best = int(np.argmax(sin))
        rank = (np.sum(sout < sout[best]) + 0.5 * (np.sum(sout == sout[best]) - 1) + 1) / (N + 1)   # relative rank in (0, 1)
        logits.append(float(np.log(rank / (1 - rank))))
        deg.append(float(sout[best] * np.sqrt(periods)))
    lg = np.array(logits)
    return {"pbo": float(np.mean(lg <= 0)), "splits": len(lg), "rules": N, "blocks": S, "median_logit": float(np.median(lg)),
            "oos_sharpe_of_is_winner": [float(np.percentile(deg, 25)), float(np.median(deg)), float(np.percentile(deg, 75))]}


def rule_returns(book: pd.Series, hedge: pd.Series, ratio: pd.Series, cost_bps: float = 2.0, rf: pd.Series | float = 0.0,
                 periods: int = 252) -> pd.Series:
    """Book plus a financed hedge at yesterday's ratio, less trading costs on ratio changes."""
    h = ratio.reindex(book.index).shift(1)
    cash = (rf.reindex(book.index).ffill().fillna(0.0) if isinstance(rf, pd.Series) else pd.Series(float(rf), index=book.index)) / periods
    r = book + h * (hedge.reindex(book.index) - cash) - h.diff().abs() * cost_bps / 1e4
    return r.where(h.notna())


ENTERS = (-0.05, -0.10, -0.15, -0.20, -0.30)
EXITS = (0.0, 0.05, 0.10)
SCALES = (0.5, 1.0)


def rule_family(book, hedge, corr, mv, ratio_fn, cost_bps=2.0, rf=0.0, enters=ENTERS, exits=EXITS, scales=SCALES) -> pd.DataFrame:
    """ratio_fn(enter, exit) -> daily hedge ratio (the policy's own function). One column per rule."""
    cols = {}
    for en in enters:
        for ex in exits:
            if ex <= en:
                continue
            base = ratio_fn(en, ex)
            for sc in scales:
                cols[f"enter {en:+.2f} exit {ex:+.2f} x{sc:g}"] = rule_returns(book, hedge, base * sc, cost_bps, rf)
    return pd.DataFrame(cols).dropna()


def plateau(F: pd.DataFrame, chosen: str, periods: int = 252) -> dict:
    sh = F.mean() / F.std() * np.sqrt(periods)
    rank = int((sh > sh[chosen]).sum()) + 1
    others = sh.drop(chosen)
    return {"chosen": chosen, "chosen_sharpe": float(sh[chosen]), "rank": rank, "of": len(sh),
            "neighbour_median": float(others.median()), "neighbour_min": float(others.min()), "neighbour_max": float(others.max()),
            "spread": float(sh.max() - sh.min()), "grid": {k: float(v) for k, v in sh.items()}}


def robustness_block(variant_returns: dict[str, pd.Series], rf, family: pd.DataFrame, chosen: str, base: str,
                     draws: int = 500) -> dict:
    out = {"bootstrap": bootstrap_stats(variant_returns, rf, draws=draws, base=base)}
    out["pbo"] = cscv_pbo(family.to_numpy()) if family.shape[1] >= 2 else {"pbo": None}
    out["plateau"] = plateau(family, chosen) if chosen in family else None
    return out
