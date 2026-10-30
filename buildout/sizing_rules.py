"""Sizing the book over time (v0.32): the frontier of size-and-hedge choices that meet the limits today, and a
volatility-managed sizing rule tested the way the engine tests everything, walked forward against the best of many
useless rules.

The frontier. For gross exposure g (the share of NAV in the nine names) and a Nasdaq-100 futures short h (fraction
of NAV), the book's returns are g r_book - h r_qqq_excess. For each g the engine finds the smallest h that brings
every limit inside bounds (the one-month 95% expected shortfall under the budget, the volatility under the target,
the 95th-percentile one-year drawdown under the cap), with the hedge's cost and the history's return and 2022 beside
it. The page shows the menu; the choice of a point on it is a judgment about these nine names against the index.

The rule. Moreira and Muir (2017, Journal of Finance): scale exposure by c / sigma^2 (realized variance over the
previous month), capped. Here it is tested as the engine tests a sizing rule: the monthly CRRA utility gain over
holding (the risk aversion the decision engine calibrated), its t by the equal-weighted cosine test, against the
best of the variants tried (three variance windows, two target vols, two caps, and the inverse-vol form: twelve
rules, so the bar is the expected maximum of twelve null t statistics), on the Nasdaq-100 future since 1999 and on
the book's own days since 2017, with both halves. A rule the test does not support stays a reading, not the call.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from .analytics import sizing

GAMMA = 2.2                 # the decision engine's calibrated risk aversion (decide.calibrate_gamma, 1871 to 1939)
RULES = [{"window": w, "target": t, "cap": c, "form": f} for w in (21, 63) for t in (0.15, 0.20) for c in (1.0, 1.5) for f in ("var",)] + \
        [{"window": w, "target": 0.20, "cap": 1.5, "form": "vol"} for w in (21, 63)] + \
        [{"window": 126, "target": 0.20, "cap": 1.5, "form": f} for f in ("var", "vol")]
N_RULES = len(RULES)         # 12: the count the test deflates for
HEADLINE = {"window": 21, "target": 0.20, "cap": 1.5, "form": "var"}     # Moreira and Muir's own form, published first
COST_BP = 2.0                # per unit of exposure changed, a side
MIN_MONTHS = 60


# ---------------------------------------------------------------- the rule
def realized_vol(r: pd.Series, window: int) -> pd.Series:
    """Annualized realized volatility over the past `window` trading days, known at the close of each day."""
    return r.rolling(window, min_periods=window).std() * math.sqrt(252)


def exposure_path(r: pd.Series, rule: dict) -> pd.Series:
    """The exposure held through each month, set at the previous month's last close from volatility known then.
    form "var": target^2 / sigma^2 (Moreira and Muir); form "vol": target / sigma. Capped at `cap`, floored at 0."""
    sig = realized_vol(r, rule["window"])
    raw = (rule["target"] ** 2 / sig ** 2) if rule["form"] == "var" else (rule["target"] / sig)
    per = r.index.to_period("M")
    last_of_month = raw.groupby(per).transform("last")                 # the value at each month's last trading close
    prev = pd.Series(last_of_month.groupby(per).first().shift(1).to_numpy(), index=last_of_month.groupby(per).first().index)
    daily = pd.Series(prev.reindex(per).to_numpy(), index=r.index)     # held through the following month
    return daily.clip(0.0, rule["cap"])


def rule_returns(r: pd.Series, cash: pd.Series, rule: dict, cost_bp: float = COST_BP) -> pd.Series:
    """Daily return of holding x_t of the asset and 1 - x_t in cash (borrowing at cash above 1), less costs on each
    change in exposure."""
    x = exposure_path(r, rule)
    ok = x.notna()
    turn = x.diff().abs().fillna(0.0)
    return (x * r + (1 - x) * cash - turn * cost_bp / 1e4)[ok]


def monthly(r: pd.Series) -> pd.Series:
    return (1 + r).resample("ME").prod() - 1


def utility(r: pd.Series, gamma: float = GAMMA) -> np.ndarray:
    v = np.maximum(1 + np.asarray(r, float), 0.02)
    return np.log(v) if abs(gamma - 1) < 1e-9 else (v ** (1 - gamma) - 1) / (1 - gamma)


def ewc(x: np.ndarray) -> dict:
    from .filings import ewc_test
    return ewc_test(x)


def test_rule(r: pd.Series, cash: pd.Series, rule: dict, gamma: float = GAMMA) -> dict:
    """The rule against holding the asset: monthly CRRA utility gain, EWC t, Sharpe ratios, both halves, drawdowns."""
    rr = rule_returns(r, cash, rule)
    hold = r.reindex(rr.index)
    m_rule, m_hold, m_cash = monthly(rr), monthly(hold), monthly(cash.reindex(rr.index))
    d = utility(m_rule, gamma) - utility(m_hold, gamma)
    e = ewc(d)
    half = len(d) // 2
    sharpe = lambda m: float((m - m_cash.reindex(m.index)).mean() / m.std() * math.sqrt(12)) if m.std() > 0 else float("nan")
    lv = lambda s: (1 + s).cumprod()
    mdd = lambda s: float(1 - (lv(s) / lv(s).cummax()).min())
    x = exposure_path(r, rule).reindex(rr.index)
    return {"rule": rule, "months": int(len(d)), "from": str(rr.index[0].date()), "to": str(rr.index[-1].date()),
            "utility_gain_month": float(d.mean()), "t": e["t"], "p": e["p"], "df": e["df"],
            "sharpe_rule": sharpe(m_rule), "sharpe_hold": sharpe(m_hold),
            "halves": {"first": {"t": ewc(d[:half])["t"], "gain": float(d[:half].mean())}, "second": {"t": ewc(d[half:])["t"], "gain": float(d[half:].mean())}},
            "maxdd_rule": mdd(rr), "maxdd_hold": mdd(hold), "avg_exposure": float(x.mean()), "time_below_1": float((x < 1).mean()),
            "cagr_rule": float(lv(rr).iloc[-1] ** (252 / len(rr)) - 1), "cagr_hold": float(lv(hold).iloc[-1] ** (252 / len(hold)) - 1)}


def expected_max_t(n: int) -> float:
    """The expected maximum of n independent standard normal t statistics (Bailey and Lopez de Prado's approximation)."""
    g = 0.5772156649
    return float((1 - g) * stats.norm.ppf(1 - 1 / n) + g * stats.norm.ppf(1 - 1 / (n * math.e)))


def test_all(r: pd.Series, cash: pd.Series, name: str, gamma: float = GAMMA) -> dict:
    """Every rule on one record, and the verdict on the headline rule against the best of all of them; the headline
    rule also on each third of the record, from 2003 (without the dot-com crash) and at five times the cost."""
    tests = [test_rule(r, cash, k, gamma) for k in RULES]
    t0 = expected_max_t(N_RULES)
    head = next(t for t in tests if t["rule"] == HEADLINE)
    n = len(r)
    thirds = []
    for k in range(3):
        rs = r.iloc[k * n // 3:(k + 1) * n // 3]
        if len(rs) > 300:
            ts = test_rule(rs, cash.reindex(rs.index), HEADLINE, gamma)
            thirds.append({"from": ts["from"], "to": ts["to"], "t": ts["t"], "sharpe_rule": ts["sharpe_rule"], "sharpe_hold": ts["sharpe_hold"]})
    head["thirds"] = thirds
    if r.index[0] < pd.Timestamp("2003-01-01") and r.index[-1] > pd.Timestamp("2008-01-01"):
        r3 = r.loc["2003-01-01":]
        t3 = test_rule(r3, cash.reindex(r3.index), HEADLINE, gamma)
        head["from_2003"] = {"t": t3["t"], "sharpe_rule": t3["sharpe_rule"], "sharpe_hold": t3["sharpe_hold"], "maxdd_rule": t3["maxdd_rule"], "maxdd_hold": t3["maxdd_hold"]}
    rr = rule_returns(r, cash, HEADLINE, cost_bp=5 * COST_BP)
    hold = r.reindex(rr.index)
    d5 = utility(monthly(rr), gamma) - utility(monthly(hold), gamma)
    head["t_at_5x_cost"] = ewc(d5)["t"]
    head["exposure_now"] = float(exposure_path(r, HEADLINE).dropna().iloc[-1])
    best = max(tests, key=lambda t: t["t"] if t["t"] is not None and np.isfinite(t["t"]) else -9)
    both = head["halves"]["first"]["gain"] > 0 and head["halves"]["second"]["gain"] > 0
    verdict = ("supported" if head["t"] > t0 and both else "one_era" if head["t"] > t0 else "chance" if head["t"] > 0 else "reversed")
    return {"name": name, "tests": tests, "headline": head, "best": best, "t_bar": t0, "n_rules": N_RULES, "verdict": verdict,
            "months": head["months"]}


# ---------------------------------------------------------------- the frontier
def frontier(rb: pd.Series, qx: pd.Series, fm: dict, beta_b: float, beta_q: float, rf: float, limits: dict,
             es_fn, grosses=(0.5, 0.6, 0.7, 0.8, 0.9, 1.0), equity_premium: float = 0.05) -> list[dict]:
    """For each gross exposure g (share of NAV in the names), the smallest Nasdaq-100 futures short h (fraction of
    NAV) that meets every limit, with its record. Volatility comes from the factor model (Var(g b - h q) =
    g^2 s_b^2 - 2 g h cov(b, q) + h^2 s_q^2); the one-month ES from es_fn(x, sigma), the most cautious of the engine's
    three methods; the drawdown from the engine's simulation at the drift the betas imply."""
    Fc = fm["factor_cov"]
    b = np.array([fm["exposure"][f] for f in fm["factor_cov"].index])
    s_b2, cov_bq, s_q2 = fm["vol"] ** 2, float((Fc.to_numpy() @ b)[0]), float(Fc.iloc[0, 0])
    rows = []
    for g in grosses:
        row = {"gross": g, "short": None, "meets": False}
        tol = 0.005                                       # the first row is the unhedged size the limits allow, to rounding
        for h in np.round(np.arange(0.0, 1.21, 0.05), 2):
            x = (g * rb - h * qx).dropna()
            sig = math.sqrt(max(g * g * s_b2 - 2 * g * h * cov_bq + h * h * s_q2, 1e-12))
            e = es_fn(x, sig)
            dd = sizing.drawdown_quantile(rf + equity_premium * (g * beta_b - h * beta_q), sig, 1.0, cash_rate=rf)
            if e <= limits["es"] * (1 + tol) and sig <= limits["vol"] * (1 + tol) and dd <= limits["dd"] * (1 + tol):
                lv = (1 + x).cumprod()
                row = {"gross": g, "short": float(h), "meets": True, "es95": e, "vol": sig, "drawdown95": dd,
                       "cagr": float(lv.iloc[-1] ** (252 / len(x)) - 1), "y2022": float((1 + x.loc["2022"]).prod() - 1) if x.index[0].year <= 2022 <= x.index[-1].year else None,
                       "maxdd": float(1 - (lv / lv.cummax()).min()), "hedge_drag_ann": float(h * qx.reindex(x.index).mean() * 252),
                       "market_beta_left": float(g * fm["exposure"]["market"] - h), "stock_specific_share": None}
                break
        rows.append(row)
    return rows
