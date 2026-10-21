"""Decision math: sizing a bet, scoring forecasts, and telling skill from luck.

The decision journal on the page uses the same formulas (site/src/math.js); tests/test_page.py checks
that both languages agree. Every function is pure and works on plain numbers or lists.

  kelly(p, b)              growth-optimal fraction of capital for a bet won with probability p at payoff b:1
  log_growth(f, p, b)      expected log growth per bet at fraction f (the Kelly hill)
  brier(ps, outcomes)      mean squared error of probability forecasts (0 perfect, 0.25 a coin flip)
  calibration(ps, ys, k)   forecasts bucketed by stated probability against how often they came true
  binom_tail(n, k, p)      chance of k or more hits in n tries if the true hit rate is p (is the record luck?)
  years_to_significance    years of returns needed before a Sharpe ratio is statistically distinguishable from zero
  lev_growth               compound growth of a levered position: r + L(mu - r) - L^2 sigma^2 / 2
  hedge_cagr               compound growth of a book with and without a tail hedge across a scenario mix
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence


def kelly(p: float, b: float) -> float:
    """f* = p - (1 - p) / b, floored at zero (no edge, no bet). b is the win per unit lost."""
    if not (0 <= p <= 1) or b <= 0:
        return float("nan")
    return max(0.0, p - (1 - p) / b)


def position_kelly(p: float, win: float, loss: float) -> float:
    """Kelly fraction of capital for a position that gains `win` with probability p and loses `loss` otherwise.

    Maximizing p ln(1 + f win) + (1 - p) ln(1 - f loss) gives f* = p / loss - (1 - p) / win, floored at zero.
    It is kelly(p, win / loss) / loss: the bet form scaled by how much of the position is at risk.
    """
    if not (0.0 <= p <= 1.0) or not (win > 0) or not (loss > 0):
        return float("nan")
    return max(0.0, p / loss - (1.0 - p) / win)


def log_growth(f: float, p: float, b: float) -> float:
    """Expected log growth per bet when risking fraction f: p ln(1 + b f) + (1 - p) ln(1 - f)."""
    if f >= 1:
        return float("-inf") if p < 1 else math.log1p(b * f)
    return p * math.log1p(b * f) + (1 - p) * math.log1p(-f)


def brier(ps: Sequence[float], ys: Sequence[int]) -> float:
    if not ps or len(ps) != len(ys):
        return float("nan")
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def calibration(ps: Sequence[float], ys: Sequence[int], edges: Sequence[float] = (0, 0.2, 0.4, 0.6, 0.8, 1.0001)) -> list[dict]:
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        pick = [(p, y) for p, y in zip(ps, ys) if lo <= p < hi]
        if pick:
            out.append({"lo": lo, "hi": min(hi, 1.0), "n": len(pick), "stated": sum(p for p, _ in pick) / len(pick),
                        "realized": sum(y for _, y in pick) / len(pick)})
    return out


def binom_tail(n: int, k: int, p: float = 0.5) -> float:
    """P(X >= k) for X ~ Binomial(n, p), summed exactly."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def years_to_significance(sharpe: float, z: float = 2.0) -> float:
    """t = SR * sqrt(T) for annual Sharpe SR, so T = (z / SR)^2 years to reach a t-statistic of z."""
    return float("inf") if sharpe <= 0 else (z / sharpe) ** 2


def lev_growth(mu: float, sigma: float, r: float, lev: float) -> float:
    """Continuous-time compound growth of a constantly rebalanced levered position (borrowing at r)."""
    return r + lev * (mu - r) - 0.5 * lev * lev * sigma * sigma


def conjunction(ps: Iterable[float]) -> float:
    """Chance every assumption holds if they are independent (positively correlated assumptions do better)."""
    out = 1.0
    for p in ps:
        out *= p
    return out


def bayes(prior: float, sensitivity: float, specificity: float) -> float:
    """Posterior that the event is real after a positive signal with the given hit and false-alarm rates."""
    tp = prior * sensitivity
    fp = (1 - prior) * (1 - specificity)
    return tp / (tp + fp) if tp + fp > 0 else float("nan")


def div_ratio(n: int, rho: float) -> float:
    """Volatility of an equal-weight mix of n streams with equal vol and pairwise correlation rho, relative to one stream."""
    return math.sqrt((1 + (n - 1) * rho) / n)


def hedge_cagr(scenarios: Sequence[tuple[float, float]], cost: float, payoff: dict | None = None) -> float:
    """Compound growth exp(sum p ln(1 + r)) - 1 across (probability, book return) scenarios.

    A hedge costs `cost` (fraction of capital per year) in every scenario and pays payoff[i] in scenario i.
    """
    tot = 0.0
    for i, (p, r) in enumerate(scenarios):
        x = 1 + r - cost + (payoff or {}).get(i, 0.0)
        if x <= 0:
            return -1.0
        tot += p * math.log(x)
    return math.exp(tot) - 1


def alpha_stats(returns: Sequence[float], bench: Sequence[float], betas: Sequence[float]) -> dict:
    """Per-decision alpha (return minus beta times the benchmark), its mean, spread and t-statistic."""
    a = [r - b * m for r, m, b in zip(returns, bench, betas)]
    n = len(a)
    if n < 2:
        return {"n": n, "mean": a[0] if a else float("nan"), "sd": float("nan"), "t": float("nan")}
    mean = sum(a) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in a) / (n - 1))
    return {"n": n, "mean": mean, "sd": sd, "t": mean / (sd / math.sqrt(n)) if sd > 0 else float("nan"),
            "decisions_for_t2": (2 * sd / mean) ** 2 if mean > 0 and sd > 0 else float("inf")}


PROCESS_ITEMS = ("logged_before", "sized_by_rule", "kill_respected", "two_sources")


def process_score(rec: dict) -> float | None:
    pr = rec.get("process") or {}
    vals = [bool(pr.get(k)) for k in PROCESS_ITEMS if k in pr]
    return sum(vals) / len(PROCESS_ITEMS) if vals else None


def scorecard(records: Sequence[dict]) -> dict:
    """Score closed decisions: calibration, hit rate, payoff, alpha after beta, and the process-outcome grid."""
    closed = [r for r in records if r.get("status") == "closed" and r.get("right") in (0, 1, 0.5)
              and isinstance(r.get("p"), (int, float)) and isinstance(r.get("ret"), (int, float))]
    ps = [float(r["p"]) for r in closed]
    ys = [1 if r["right"] == 1 else 0 for r in closed]
    rets = [float(r["ret"]) for r in closed]
    bench = [float(r.get("bench_ret") or 0.0) for r in closed]
    betas = [float(r.get("beta") if r.get("beta") is not None else 1.0) for r in closed]
    wins = [x for x in rets if x > 0]
    losses = [-x for x in rets if x < 0]
    grid = {"earned": 0, "bad_luck": 0, "dumb_luck": 0, "deserved": 0}
    for r, a in zip(closed, [x - b * m for x, m, b in zip(rets, bench, betas)]):
        good_process = (process_score(r) or 0) >= 0.75
        good_outcome = a > 0
        key = ("earned" if good_outcome else "bad_luck") if good_process else ("dumb_luck" if good_outcome else "deserved")
        grid[key] += 1
    n = len(closed)
    hits = sum(ys)
    return {
        "n_closed": n, "n_open": sum(1 for r in records if r.get("status") != "closed"),
        "brier": brier(ps, ys) if n else None,
        "mean_stated": sum(ps) / n if n else None, "hit_rate": hits / n if n else None,
        "overconfidence": (sum(ps) / n - hits / n) if n else None,
        "calibration": calibration(ps, ys) if n else [],
        "payoff_ratio": (sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else None,
        "expectancy": sum(rets) / n if n else None,
        "alpha": alpha_stats(rets, bench, betas) if n else None,
        "luck_p_value": binom_tail(n, hits, 0.5) if n else None,
        "grid": grid,
    }
