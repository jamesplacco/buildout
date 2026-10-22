"""Damodaran's two working tools, as he describes them: the implied equity risk premium (the discount rate that makes
the index equal the present value of the cash it is expected to return), and narrative-to-numbers valuation (a story
about a business turned into revenue growth, a target margin, reinvestment through a sales-to-capital ratio, a cost
of capital that drifts to a mature level, a terminal growth no higher than the risk-free rate, and a chance the story
fails). Python is canonical; site/src/edge.js runs the same functions (tests/test_v15.py holds them equal).
"""
from __future__ import annotations


def implied_erp(level: float, cash_yield: float, growth: float, rf: float, years: int = 5) -> dict:
    """Solve for r in level = sum_{t<=years} CF_t / (1+r)^t + CF_{years+1} / (r - rf) / (1+r)^years, where
    CF_t = level * cash_yield * (1+growth)^t and the terminal growth equals the risk-free rate. ERP = r - rf."""
    cf0 = level * cash_yield

    def pv(r: float) -> float:
        v, cf = 0.0, cf0
        for t in range(1, years + 1):
            cf *= 1 + growth
            v += cf / (1 + r) ** t
        return v + cf * (1 + rf) / (r - rf) / (1 + r) ** years
    lo, hi = rf + 1e-6, 1.0
    if pv(hi) > level or pv(lo) < level:
        return {"r": None, "erp": None}
    for _ in range(200):
        mid = (lo + hi) / 2
        if pv(mid) > level:
            lo = mid
        else:
            hi = mid
    r = (lo + hi) / 2
    return {"r": r, "erp": r - rf, "cash_flows": [cf0 * (1 + growth) ** t for t in range(1, years + 1)]}


def narrative_dcf(revenue: float, growth_high: float, margin_now: float, margin_target: float, years_to_target: int = 5, sales_to_capital: float = 1.5,
                  tax: float = 0.21, wacc_start: float = 0.10, wacc_mature: float = 0.085, rf: float = 0.0513, g_terminal: float | None = None,
                  p_fail: float = 0.0, distress_share: float = 0.5, debt: float = 0.0, cash: float = 0.0, shares: float = 1.0, years: int = 10) -> dict:
    """Ten years: growth at growth_high for five, then sliding linearly to the terminal rate by year ten; margin moving
    linearly from margin_now to margin_target over years_to_target; reinvestment = change in revenue / sales-to-capital;
    the cost of capital sliding from wacc_start to wacc_mature over years six to ten. Terminal value on year eleven's
    cash flow, with reinvestment that sustains g at a return on capital equal to the mature cost of capital. Terminal
    growth defaults to, and is capped at, the risk-free rate."""
    g_t = min(rf, rf if g_terminal is None else g_terminal)
    rows, rev, disc, pv = [], revenue, 1.0, 0.0
    for t in range(1, years + 1):
        g = growth_high if t <= 5 else growth_high - (growth_high - g_t) * (t - 5) / 5
        new = rev * (1 + g)
        m = margin_target if t >= years_to_target else margin_now + (margin_target - margin_now) * t / years_to_target
        ebit = new * m
        nopat = ebit * (1 - tax)
        reinv = (new - rev) / sales_to_capital
        fcff = nopat - reinv
        w = wacc_start if t <= 5 else wacc_start - (wacc_start - wacc_mature) * (t - 5) / 5
        disc /= 1 + w
        pv += fcff * disc
        rows.append({"year": t, "growth": g, "revenue": new, "margin": m, "ebit": ebit, "nopat": nopat, "reinvestment": reinv, "fcff": fcff, "wacc": w, "pv": fcff * disc})
        rev = new
    nopat11 = rev * (1 + g_t) * margin_target * (1 - tax)
    reinv11 = nopat11 * (g_t / wacc_mature) if wacc_mature > 0 else 0.0
    tv = (nopat11 - reinv11) / (wacc_mature - g_t)
    pv_tv = tv * disc
    ev = pv + pv_tv
    equity_going = ev - debt + cash
    equity = (1 - p_fail) * equity_going + p_fail * distress_share * max(0.0, equity_going)
    return {"rows": rows, "pv_years": pv, "terminal": tv, "pv_terminal": pv_tv, "ev": ev, "equity": equity, "per_share": equity / shares,
            "terminal_share": pv_tv / ev if ev else None, "g_terminal": g_t}
