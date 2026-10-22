"""Fundamentals, accounting quality and what the market is pricing in, per position.

The question for each holding is not "is it a good company" but "what does today's price require, how often has that
ever happened, and if the price looks irrational, why might it be". Every input is either reported (SEC filings,
labelled Observed), a market price (Observed), or a stated assumption (Assumed); every output is labelled.

  quality           the accounting under the earnings: cash conversion (OCF / net income), Sloan accruals
                    ((net income - OCF) / assets), stock pay as a real cost (SBC-adjusted free cash flow),
                    maintenance versus growth capex (maintenance taken as D&A), steady-state free cash flow (what
                    the business would throw off if it stopped growing: the lower of
                    after-tax operating income and OCF - D&A - SBC, so prepayments do not flatter it), capex-normalized operating
                    income (operating income if D&A caught up with today's capex: EBIT + D&A - capex), coverage,
                    leverage and returns on capital
  implied_growth    a reverse DCF (Rappaport and Mauboussin, Expectations Investing): the 10-year revenue growth rate
                    that makes the present value of free cash flow equal today's enterprise value, with the free
                    cash flow margin moving in a straight line from today's (after stock pay) to the steady-state
                    margin, and a Gordon terminal value at year 10
  base_rates        Mauboussin, The Base Rate Book (2016), 10-year real sales CAGR of US companies 1950-2015 by
                    starting sales: the share of companies that ever achieved a given growth rate
  verdict           how far outside the base rates the implied growth sits (exuberance below 5%, extreme below 1%;
                    pessimism when the price assumes far less than the base rates and the company's own record)
  why               the gap decomposed into points of implied growth: discount rate (duration), the steady-state
                    margin assumed, depreciation catch-up, and the expectation gap against the company's own growth
"""
from __future__ import annotations


# 10-year real sales CAGR, 1950-2015, by starting sales (US$ millions, 2015 dollars). Bins in percent; share of firms.
BASE_RATES = {
    "over_50b": {"label": "sales above $50 billion", "mean": 0.8, "sd": 5.8,
                 "bins": [(-35, -25, 0.0), (-25, -20, 0.3), (-20, -15, 1.0), (-15, -10, 3.1), (-10, -5, 9.8), (-5, 0, 26.9), (0, 5, 37.8),
                          (5, 10, 17.2), (10, 15, 3.0), (15, 20, 0.9), (20, 25, 0.0), (25, 30, 0.0), (30, 35, 0.0), (35, 40, 0.0), (40, 45, 0.0), (45, 60, 0.0)]},
    "over_25b": {"label": "sales above $25 billion", "mean": 1.7, "sd": 6.1,
                 "bins": [(-35, -25, 0.1), (-25, -20, 0.2), (-20, -15, 0.8), (-15, -10, 2.5), (-10, -5, 9.0), (-5, 0, 22.9), (0, 5, 37.1),
                          (5, 10, 20.2), (10, 15, 5.8), (15, 20, 1.3), (20, 25, 0.2), (25, 30, 0.0), (30, 35, 0.0), (35, 40, 0.0), (40, 45, 0.0), (45, 60, 0.0)]},
    "12_25b": {"label": "sales of $12 to $25 billion", "mean": 2.9, "sd": 6.1,
               "bins": [(-35, -25, 0.0), (-25, -20, 0.1), (-20, -15, 0.5), (-15, -10, 1.4), (-10, -5, 5.7), (-5, 0, 20.2), (0, 5, 41.7),
                        (5, 10, 20.8), (10, 15, 6.3), (15, 20, 2.5), (20, 25, 0.6), (25, 30, 0.1), (30, 35, 0.1), (35, 40, 0.0), (40, 45, 0.0), (45, 60, 0.1)]},
}
BASE_RATE_SOURCE = "Mauboussin, Callahan and Majd, The Base Rate Book (Credit Suisse, 2016), 10-year sales CAGR by starting size, 1950-2015, real"
SMOOTH_FLOOR = 0.0005   # 0.05% of mass per empty bin, so "never observed" reads as rare, not impossible
ASSUMED = {"erp": 0.045, "inflation": 0.025, "terminal_growth": 0.03, "tax": 0.18, "years": 10, "cost_of_debt_spread": 0.012}


def size_bucket(revenue_bn: float | None) -> str:
    if revenue_bn is None or revenue_bn >= 50:
        return "over_50b"
    return "over_25b" if revenue_bn >= 25 else "12_25b"


def base_rate_tail(g_real_pct: float, bucket: str = "over_50b", side: str = "above") -> float:
    """Share of companies whose 10-year real CAGR was at least (side="above") or at most (side="below") g, in [0, 1].
    Mass is uniform within each bin; empty bins carry a small floor and the total is renormalized."""
    bins = BASE_RATES[bucket]["bins"]
    w = [max(p / 100, SMOOTH_FLOOR) for _, _, p in bins]
    tot = sum(w)
    above = 0.0
    for (lo, hi, _), wi in zip(bins, w):
        if g_real_pct <= lo:
            above += wi
        elif g_real_pct < hi:
            above += wi * (hi - g_real_pct) / (hi - lo)
    above /= tot
    return above if side == "above" else 1 - above


def base_rate_quantile(q: float, bucket: str = "over_50b") -> float:
    """The real CAGR (percent) at cumulative share q, inverting base_rate_tail by bisection."""
    lo, hi = -35.0, 60.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if base_rate_tail(mid, bucket, "below") < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _share(p: float) -> str:
    return "fewer than 1 in 1,000" if p < 0.001 else f"only {p:.1%}" if p < 0.1 else f"{p:.0%}"


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


def quality(c: dict) -> dict:
    """c: TTM figures in $bn (revenue, op_income, net_income, ocf, capex, da, sbc, interest, debt, cash, assets, equity)."""
    g = lambda k: c.get(k)  # noqa: E731
    rev, ni_rep, ocf, capex, da, sbc = g("revenue"), g("net_income"), g("ocf"), g("capex"), g("da"), g("sbc") or 0.0
    core = None if g("op_income") is None else g("op_income") * (1 - ASSUMED["tax"])
    nonop_heavy = ni_rep is not None and core is not None and core > 0 and ni_rep > 1.3 * core
    ni = core if nonop_heavy else ni_rep            # judge cash conversion on operating earnings, not on marks
    fcf = None if ocf is None or capex is None else ocf - capex
    steady_cash = None if ocf is None or da is None else ocf - da - sbc
    ebit = g("op_income")
    nopat_ = None if ebit is None else ebit * (1 - ASSUMED["tax"])
    # steady state: maintenance capex equals D&A and working capital stops moving, so free cash flow is operating
    # earnings after tax (stock pay is already an expense). Take the lower of that and the cash measure, so neither a
    # working-capital inflow (customer prepayments) nor accruals flatter the value.
    if steady_cash is not None and nopat_ is not None and nopat_ > 0:
        steady, steady_basis = (nopat_, "operating earnings") if nopat_ < steady_cash else (steady_cash, "cash")
    else:
        steady, steady_basis = steady_cash, "cash"
    wc_lift = None if steady_cash is None or nopat_ is None or not rev else (steady_cash - nopat_) / rev
    capex_norm_ebit = None if ebit is None or da is None or capex is None else ebit + da - capex
    nopat = None if ebit is None else ebit * (1 - ASSUMED["tax"])
    invested = None if g("debt") is None or g("equity") is None or g("cash") is None else g("debt") + g("equity") - g("cash")
    ebitda = None if ebit is None or da is None else ebit + da
    out = {
        "op_margin": _div(ebit, rev), "net_margin": _div(ni_rep, rev), "core_net_income": core,
        "nonoperating_share": None if not nonop_heavy else 1 - core / ni_rep,
        "cash_conversion": _div(ocf, ni),
        "accruals": _div(None if ni is None or ocf is None else ni - ocf, g("assets")),
        "fcf": fcf, "fcf_margin": _div(fcf, rev),
        "sbc_to_revenue": _div(g("sbc"), rev),
        "owner_fcf": None if fcf is None else fcf - sbc, "owner_fcf_margin": _div(None if fcf is None else fcf - sbc, rev),
        "growth_capex": None if capex is None or da is None else max(capex - da, 0.0),
        "steady_fcf": steady, "steady_fcf_margin": _div(steady, rev), "steady_basis": steady_basis,
        "steady_fcf_cash": steady_cash, "steady_cash_margin": _div(steady_cash, rev), "working_capital_lift": wc_lift,
        "capex_to_da": _div(capex, da),
        "capex_norm_ebit": capex_norm_ebit, "capex_norm_margin": _div(capex_norm_ebit, rev),
        "depreciation_drag": None if capex_norm_ebit is None or ebit in (None, 0) else 1 - capex_norm_ebit / ebit,
        "interest_cover": _div(ebit, g("interest")),
        "net_debt": None if g("debt") is None or g("cash") is None else g("debt") - g("cash"),
        "net_debt_to_ebitda": _div(None if g("debt") is None or g("cash") is None else g("debt") - g("cash"), ebitda),
        "roic": _div(nopat, invested) if invested and invested > 0 else None,
        "roe": _div(ni_rep, g("equity")) if g("equity") and g("equity") > 0 else None,
    }
    flags = []
    if nonop_heavy:
        flags.append(("nonoperating", "watch", f"{out['nonoperating_share']:.0%} of net income is not from operations (gains on investments): quality is judged on operating earnings"))
    cc, acc = out["cash_conversion"], out["accruals"]
    if cc is not None and cc < 0.8:
        flags.append(("cash_conversion", "watch" if cc >= 0.5 else "red", f"operating cash flow is {cc:.0%} of net income"))
    if acc is not None and acc > 0.05:
        flags.append(("accruals", "watch" if acc <= 0.10 else "red", f"accruals are {acc:.1%} of assets: earnings ahead of cash"))
    if wc_lift is not None and wc_lift > 0.05:
        flags.append(("working_capital", "watch", f"operating cash flow runs {wc_lift * 100:.0f} points of revenue above operating earnings (customer prepayments, deferred taxes from accelerated depreciation, interest on cash, or other timing): the steady state uses operating earnings, since that lift does not last once capex settles"))
    sr = out["sbc_to_revenue"]
    if sr is not None and sr > 0.05:
        flags.append(("sbc", "watch" if sr <= 0.12 else "red", f"stock pay is {sr:.1%} of revenue: a real cost free cash flow leaves out"))
    dd = out["depreciation_drag"]
    if dd is not None and dd > 0.25:
        flags.append(("depreciation", "watch" if dd <= 0.5 else "red", f"if depreciation caught up with today's capex, operating income would be {dd:.0%} lower"))
    nd = out["net_debt_to_ebitda"]
    if nd is not None and nd > 2.0:
        flags.append(("leverage", "watch" if nd <= 3.5 else "red", f"net debt is {nd:.1f}x EBITDA"))
    ic = out["interest_cover"]
    if ic is not None and ic < 5:
        flags.append(("coverage", "watch" if ic >= 2 else "red", f"operating income covers interest {ic:.1f}x"))
    out["flags"] = [{"key": k, "grade": gr, "text": t} for k, gr, t in flags]
    score = sum({"watch": 1, "red": 2}[f["grade"]] for f in out["flags"])
    out["quality_grade"] = "high" if score == 0 else "mixed" if score <= 2 else "low"
    return out


def cost_of_capital(rf: float, beta: float, market_cap: float, debt: float | None, erp: float | None = None) -> float:
    erp = ASSUMED["erp"] if erp is None else erp
    ke = rf + beta * erp
    d = max(debt or 0.0, 0.0)
    kd = (rf + ASSUMED["cost_of_debt_spread"]) * (1 - ASSUMED["tax"])
    return (ke * market_cap + kd * d) / (market_cap + d)


def pv_firm(rev0: float, g: float, m0: float, m_star: float, rate: float, tg: float, years: int = 10) -> tuple[float, float]:
    """Present value of free cash flow with revenue compounding at g and the FCF margin moving linearly from m0 to
    m_star over `years`, plus a terminal value. Returns (value, terminal share)."""
    pv, rev, fcf = 0.0, rev0, 0.0
    for t in range(1, years + 1):
        rev *= 1 + g
        m = m0 + (m_star - m0) * t / years
        fcf = rev * m
        pv += fcf / (1 + rate) ** t
    tv = fcf * (1 + tg) / (rate - tg) / (1 + rate) ** years if rate > tg else float("inf")
    return pv + tv, (tv / (pv + tv) if pv + tv > 0 else float("nan"))


def implied_growth(ev: float, rev0: float, m0: float, m_star: float, rate: float, tg: float, years: int = 10,
                   lo: float = -0.5, hi: float = 1.5) -> float | None:
    """The 10-year revenue CAGR that equates the PV of free cash flow to enterprise value (bisection; value rises with
    growth whenever the steady-state margin is positive)."""
    if m_star <= 0 or ev <= 0 or rev0 <= 0:
        return None
    f = lambda g: pv_firm(rev0, g, m0, m_star, rate, tg, years)[0] - ev  # noqa: E731
    flo, fhi = f(lo), f(hi)
    if flo > 0:
        return lo
    if fhi < 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def analyze_position(t: str, c: dict, market_cap: float, rf: float, beta: float, brain: dict | None = None) -> dict:
    """Everything for one holding. c: TTM figures in $bn; market_cap in $bn; rf decimal; beta Assumed or measured."""
    q = quality(c)
    rev = c.get("revenue")
    out = {"ticker": t, "name": c.get("name", t), "market_cap": market_cap, "quality": q, "inputs": {"rf": rf, "beta": beta, **ASSUMED}}
    if not rev or rev <= 0:
        out["verdict"] = {"code": "insufficient", "text": "Not enough reported data to read what the price implies."}
        return out
    net_cash = (c.get("cash") or 0.0) - (c.get("debt") or 0.0)
    ev = market_cap - net_cash
    rate = cost_of_capital(rf, beta, market_cap, c.get("debt"))
    tg = ASSUMED["terminal_growth"]
    m0 = q["owner_fcf_margin"] if q["owner_fcf_margin"] is not None else (q["fcf_margin"] or 0.0)
    m_star = q["steady_fcf_margin"]
    if m_star is None or m_star <= 0:
        m_star = q["op_margin"] * (1 - ASSUMED["tax"]) if q["op_margin"] and q["op_margin"] > 0 else None
    out.update({"ev": ev, "discount_rate": rate, "m0": m0, "m_star": m_star, "pe": _div(market_cap, c.get("net_income")),
                "ev_sales": ev / rev, "ev_ebit": _div(ev, c.get("op_income")), "fcf_yield": _div(q["fcf"], market_cap),
                "owner_fcf_yield": _div(q["owner_fcf"], market_cap)})
    if m_star is None:
        out["verdict"] = {"code": "insufficient", "text": "No positive steady-state margin to value: the price rests on margins the company does not yet earn."}
        return out
    g = implied_growth(ev, rev, m0, m_star, rate, tg)
    if g is None:
        out["verdict"] = {"code": "insufficient", "text": "No growth rate under 150% a year justifies the price at these margins."}
        return out
    tshare = pv_firm(rev, g, m0, m_star, rate, tg)[1]
    g_real = (g - ASSUMED["inflation"]) * 100
    bucket = size_bucket(rev)
    p_above = base_rate_tail(g_real, bucket, "above")
    p_below = 1 - p_above
    own = c.get("revenue_growth")
    own_real = None if own is None else (own - ASSUMED["inflation"]) * 100
    out.update({"implied_growth": g, "implied_real_pct": g_real, "terminal_share": tshare, "base_rate_bucket": bucket,
                "p_achieve": p_above, "p_at_or_below": p_below, "own_growth": own})
    # verdict
    if p_above < 0.01:
        code, txt = "extreme", f"The price needs about {g:.0%} a year of revenue growth for ten years ({g_real:.0f}% real). {_share(p_above).capitalize()} of companies this size ever did that."
    elif p_above < 0.05:
        code, txt = "exuberant", f"The price needs about {g:.0%} a year for ten years ({g_real:.0f}% real), achieved by about {p_above:.1%} of companies this size."
    elif p_below < 0.10 and own_real is not None and own_real - g_real > 10:
        code, txt = "pessimistic", f"The price implies only {g:.0%} a year against {own:.0%} last year: roughly the bottom {p_below:.0%} of outcomes for companies this size."
    else:
        code, txt = "within", f"The price implies about {g:.0%} a year ({g_real:.0f}% real), inside the range companies this size have achieved ({p_above:.0%} did at least that)."
    out["verdict"] = {"code": code, "text": txt}
    # why: two sides, each driver in points of required growth. why_right: what a buyer at this price is betting on;
    # why: what would make the price wrong. Points are how much each consideration moves the growth the price needs.
    why, right = [], []
    if code in ("exuberant", "extreme", "within"):
        why.append({"driver": "base_rate", "points": max(0.0, g_real - base_rate_quantile(0.5, bucket)),
                    "text": f"Outside view: {_share(p_above)} of companies with {BASE_RATES[bucket]['label']} grew at least {g_real:.0f}% a year in real terms for a decade."})
    g_lo = implied_growth(ev, rev, m0, m_star, rate - 0.01, tg)
    if g_lo is not None:
        right.append({"driver": "discount_rate", "points": (g - g_lo) * 100,
                      "text": f"Rates: {tshare:.0%} of value lies beyond year ten; a 1-point lower discount rate cuts the growth required by {(g - g_lo) * 100:.1f} points. A buyer here is partly betting on rates or the risk premium falling."})
    if own is not None and own > g:
        right.append({"driver": "momentum", "points": (own - g) * 100,
                      "text": f"Momentum: revenue grew {own:.0%} last year; the price only needs it to average {g:.0%}. It already assumes a slowdown."})
    elif own is not None:
        why.append({"driver": "expectations", "points": (g - own) * 100,
                    "text": f"Expectations: the price needs {g:.0%} a year for a decade, faster than the {own:.0%} the company grew last year."})
    m_up = min(m_star * 1.5, 0.6)
    g_up = implied_growth(ev, rev, m0, m_up, rate, tg) if m_up > m_star else None
    if g_up is not None:
        right.append({"driver": "margin_expansion", "points": (g - g_up) * 100,
                      "text": f"Margins: if the steady-state free cash flow margin rose to {m_up:.0%} from {m_star:.0%} (mix shift, operating leverage), the growth required falls {(g - g_up) * 100:.1f} points."})
    g_m = implied_growth(ev, rev, m0, m_star * 2 / 3, rate, tg)
    if g_m is not None:
        why.append({"driver": "margin", "points": (g_m - g) * 100,
                    "text": f"Margins: if the steady-state free cash flow margin settled a third lower ({m_star * 2 / 3:.0%} instead of {m_star:.0%}), the growth required rises {(g_m - g) * 100:.1f} points."})
    if q["capex_norm_margin"] is not None and q["op_margin"]:
        m_norm = q["capex_norm_margin"] * (1 - ASSUMED["tax"])
        if m_norm > 0:
            g_n = implied_growth(ev, rev, m0, min(m_star, m_norm), rate, tg)
            if g_n is not None and g_n - g > 0.001:
                why.append({"driver": "depreciation", "points": (g_n - g) * 100,
                            "text": f"Depreciation catch-up: if D&A rose to today's capex the growth required would be {(g_n - g) * 100:.1f} points higher. The price may be capitalizing earnings the build will absorb."})
        elif q["capex_to_da"] and q["capex_to_da"] > 1.5:
            why.append({"driver": "depreciation", "points": 25.0,
                        "text": "Depreciation catch-up: once D&A reaches today's capex, operating income turns negative. The price assumes the build slows or pays off."})
    for f in q["flags"]:
        if f["key"] in ("cash_conversion", "accruals", "sbc", "leverage", "coverage", "nonoperating"):
            why.append({"driver": f"quality_{f['key']}", "points": 3.0 if f["grade"] == "red" else 1.5, "text": f"Accounting: {f['text']}."})
    if brain:
        crowd = brain.get("pods")
        if crowd is not None and abs(crowd) >= 0.3:
            why.append({"driver": "crowding", "points": abs(crowd) * 5,
                        "text": f"Positioning: the brain reads pod crowding at {crowd:+.1f} sigma, so flows rather than fundamentals may be setting the marginal price (Hypothesis)."})
    why.sort(key=lambda d: -d["points"])
    right.sort(key=lambda d: -d["points"])
    out["why"] = why
    out["why_right"] = right
    # margin of safety at a generous base rate: the 90th percentile of real growth for this size, plus inflation
    g90 = base_rate_quantile(0.90, bucket) / 100 + ASSUMED["inflation"]
    v90 = pv_firm(rev, g90, m0, m_star, rate, tg)[0] + net_cash
    out["value_at_p90_growth"] = v90
    out["price_to_p90_value"] = market_cap / v90 if v90 > 0 else None
    return out


def analyze_book(companies: dict, market_caps: dict, rf: float, betas: dict, brain: dict | None = None) -> dict:
    rows = {t: analyze_position(t, companies[t], market_caps[t], rf, betas.get(t, 1.2), brain) for t in companies if t in market_caps}
    return {"positions": rows, "base_rates": {"source": BASE_RATE_SOURCE, "buckets": {k: {"label": v["label"], "mean": v["mean"], "sd": v["sd"], "bins": v["bins"]} for k, v in BASE_RATES.items()}},
            "assumed": ASSUMED, "rf": rf,
            "labels": {"inputs": "Observed (filings, prices)", "discount_rate": "Assumed (CAPM with a stated ERP)", "implied_growth": "Estimated", "base_rates": "Historical pattern", "why": "Estimated, crowding Hypothesis"}}
