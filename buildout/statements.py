"""Fundamental analysis from the filings themselves.

Standardized annual and trailing-twelve-month statements from SEC XBRL company facts (the same JSON the daily Action
downloads from data.sec.gov), then the scores an analyst would compute by hand, each with its published formula:

  profitability  gross, operating, net and free-cash-flow margins; ROA, ROE with the DuPont split, ROIC on NOPAT
  cash quality   cash conversion (CFO / net income), Sloan accruals, stock pay as a share of cash flow, capex to D&A
  growth         revenue growth, its acceleration, three-year CAGR, incremental operating margin, operating leverage
  balance sheet  net debt to EBITDA, interest cover, current ratio
  scores         Piotroski F (2000), Altman Z'' (1995, non-manufacturers), Beneish M (1999), the Rule of 40
  valuation      with a market value: EV/sales, EV/EBIT, P/E, FCF yield, earnings yield and Greenblatt's return on capital

Every line records which XBRL tag supplied it, so a reader can check it against the filing.
"""
from __future__ import annotations

import math

import pandas as pd

TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "gross_profit": ["GrossProfit"],
    "op_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "interest": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "rnd": ["ResearchAndDevelopmentExpense"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet", "Depreciation"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "dividends": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "liabilities": ["Liabilities"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "retained": ["RetainedEarningsAccumulatedDeficit"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "securities": ["MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent", "ShortTermInvestments"],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "ppe": ["PropertyPlantAndEquipmentNet"],
    "debt": ["LongTermDebt", "LongTermDebtNoncurrent", "DebtInstrumentCarryingAmount"],
    "debt_current": ["LongTermDebtCurrent", "DebtCurrent"],
    "shares": ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
}
FLOWS = {"revenue", "cogs", "gross_profit", "op_income", "net_income", "pretax", "tax", "interest", "sga", "rnd", "da", "sbc", "cfo", "capex",
         "buybacks", "dividends", "shares"}
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "40-F"}


def _rows(facts: dict, tag: str) -> list[dict]:
    node = facts.get("facts", {}).get("us-gaap", {}).get(tag) or facts.get("facts", {}).get("dei", {}).get(tag)
    if not node:
        return []
    units = node.get("units", {})
    return units.get("USD") or units.get("shares") or next(iter(units.values()), [])


def annual(facts: dict, years: int = 6) -> tuple[pd.DataFrame, dict]:
    """One row per fiscal year end: flows over ~12-month periods from annual filings, balances at the year end.
    The latest filing wins for restated years. Returns the table and the tag used for each line."""
    data, used = {}, {}
    for key, tags in TAGS.items():
        for tag in tags:
            rows = _rows(facts, tag)
            if not rows:
                continue
            df = pd.DataFrame(rows)
            if "form" in df:
                df = df[df["form"].isin(ANNUAL_FORMS)]
            if df.empty:
                continue
            df["end"] = pd.to_datetime(df["end"])
            df["filed"] = pd.to_datetime(df["filed"])
            if key in FLOWS:
                if "start" not in df:
                    continue
                df["start"] = pd.to_datetime(df["start"])
                df = df[((df["end"] - df["start"]).dt.days > 340) & ((df["end"] - df["start"]).dt.days < 380)]
            df = df.sort_values("filed").drop_duplicates("end", keep="last")
            if df.empty:
                continue
            s = df.set_index("end")["val"].astype(float)
            if key in data:                                   # a later tag fills years the first one lacks
                data[key] = data[key].combine_first(s)
            else:
                data[key], used[key] = s, tag
    if not data:
        return pd.DataFrame(), used
    T = pd.DataFrame(data).sort_index()
    T = T[T.index.isin(T.dropna(how="all").index)]
    # keep fiscal year ends (balances also arrive at quarter ends in 10-K comparatives): rows with revenue or cfo
    key = [c for c in ("revenue", "cfo", "net_income") if c in T]
    if key:
        T = T[T[key].notna().any(axis=1)]
    T = T.tail(years)
    if "gross_profit" not in T and {"revenue", "cogs"} <= set(T):
        T["gross_profit"] = T["revenue"] - T["cogs"]
    return T, used


def _g(row, k):
    v = row.get(k) if hasattr(row, "get") else None
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _div(a, b):
    return None if a is None or b is None or b == 0 else a / b


def ratios(T: pd.DataFrame) -> list[dict]:
    """Per-year ratios, oldest first."""
    out = []
    rows = [r for _, r in T.iterrows()]
    for i, r in enumerate(rows):
        p = rows[i - 1] if i else None
        g = lambda k: _g(r, k)
        rev, op, ni, cfo, capex = g("revenue"), g("op_income"), g("net_income"), g("cfo"), g("capex")
        assets, eq, da = g("assets"), g("equity"), g("da")
        fcf = None if cfo is None or capex is None else cfo - capex
        debt = (g("debt") or 0) + (g("debt_current") or 0)
        cash = (g("cash") or 0) + (g("securities") or 0)
        tax_rate = _div(g("tax"), g("pretax"))
        tax_rate = 0.21 if tax_rate is None or not 0 <= tax_rate <= 0.5 else tax_rate
        invested = None if eq is None else eq + debt - cash
        ebitda = None if op is None else op + (da or 0)
        avg_assets = assets if p is None or _g(p, "assets") is None or assets is None else (assets + _g(p, "assets")) / 2
        d = {"end": str(T.index[i].date()), "revenue": rev, "gross_margin": _div(g("gross_profit"), rev), "op_margin": _div(op, rev), "net_margin": _div(ni, rev),
             "fcf": fcf, "fcf_margin": _div(fcf, rev), "roa": _div(ni, avg_assets), "roe": _div(ni, eq),
             "roic": _div(None if op is None else op * (1 - tax_rate), invested if invested and invested > 0 else None),
             "asset_turnover": _div(rev, avg_assets), "leverage": _div(assets, eq), "cash_conversion": _div(cfo, ni),
             "accruals": _div(None if ni is None or cfo is None else ni - cfo, avg_assets), "sbc_share_of_cfo": _div(g("sbc"), cfo),
             "capex_to_da": _div(capex, da), "capex_intensity": _div(capex, rev), "rnd_intensity": _div(g("rnd"), rev),
             "net_debt": debt - cash, "net_debt_to_ebitda": _div(debt - cash, ebitda), "interest_cover": _div(op, g("interest")),
             "current_ratio": _div(g("current_assets"), g("current_liabilities")), "ebitda": ebitda}
        if p is not None:
            prev = lambda k: _g(p, k)
            d["revenue_growth"] = _div(None if rev is None or prev("revenue") is None else rev - prev("revenue"), prev("revenue"))
            dop = None if op is None or prev("op_income") is None else op - prev("op_income")
            drev = None if rev is None or prev("revenue") is None else rev - prev("revenue")
            d["incremental_margin"] = _div(dop, drev)
            d["operating_leverage"] = _div(_div(dop, prev("op_income")), d["revenue_growth"])
        out.append(d)
    for i in range(1, len(out)):
        if out[i].get("revenue_growth") is not None and out[i - 1].get("revenue_growth") is not None:
            out[i]["growth_acceleration"] = out[i]["revenue_growth"] - out[i - 1]["revenue_growth"]
    if len(out) >= 4 and out[-1]["revenue"] and out[-4]["revenue"]:
        out[-1]["cagr_3y"] = (out[-1]["revenue"] / out[-4]["revenue"]) ** (1 / 3) - 1
    for d in out:
        if d.get("revenue_growth") is not None and d.get("fcf_margin") is not None:
            d["rule_of_40"] = d["revenue_growth"] + d["fcf_margin"]
    return out


def piotroski(cur: dict, prev: dict) -> dict:
    """Piotroski (2000), nine binary tests on this year against last; a test whose inputs are missing is None
    (unknown), so a partial filing set cannot pass for a weak company."""
    g = lambda d, k: _g(d, k)
    gt = lambda a, b: None if a is None or b is None else a > b
    a0 = g(prev, "assets")
    pp = g(prev, "_assets_prior") or a0
    roa1, roa0 = _div(g(cur, "net_income"), a0), _div(g(prev, "net_income"), pp)
    lev = lambda d: None if g(d, "debt") is None else _div(g(d, "debt"), g(d, "assets"))
    cr = lambda d: _div(g(d, "current_assets"), g(d, "current_liabilities"))
    gm = lambda d: _div(g(d, "gross_profit"), g(d, "revenue"))
    t = {"roa_positive": gt(roa1, 0.0), "cfo_positive": gt(g(cur, "cfo"), 0.0), "roa_rising": gt(roa1, roa0),
         "cfo_above_income": gt(g(cur, "cfo"), g(cur, "net_income")),
         "leverage_falling": None if lev(cur) is None or lev(prev) is None else lev(cur) <= lev(prev),
         "current_ratio_rising": gt(cr(cur), cr(prev)),
         "no_dilution": None if g(cur, "shares") is None or g(prev, "shares") is None else g(cur, "shares") <= g(prev, "shares"),
         "gross_margin_rising": gt(gm(cur), gm(prev)), "turnover_rising": gt(_div(g(cur, "revenue"), a0), _div(g(prev, "revenue"), pp))}
    known = [v for v in t.values() if v is not None]
    return {"score": int(sum(known)), "known": len(known), "of": 9, "tests": t}


def altman_z2(row: dict) -> dict | None:
    """Altman's Z'' for non-manufacturers and service firms (1995): 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4, with X1 =
    working capital / assets, X2 = retained earnings / assets, X3 = EBIT / assets, X4 = book equity / liabilities.
    Above 2.6 safe, below 1.1 distress."""
    g = lambda k: _g(row, k)
    A = g("assets")
    if not A or g("current_assets") is None or g("current_liabilities") is None or g("op_income") is None:
        return None
    L = g("liabilities") or (A - (g("equity") or 0))
    x1 = (g("current_assets") - g("current_liabilities")) / A
    x2 = (g("retained") or 0) / A
    x3 = g("op_income") / A
    x4 = (g("equity") or 0) / L if L else 0.0
    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    return {"z": z, "zone": "safe" if z > 2.6 else ("grey" if z > 1.1 else "distress"), "x": [x1, x2, x3, x4]}


def beneish(cur: dict, prev: dict) -> dict | None:
    """Beneish (1999) eight-variable M-score. Above -1.78 flags a higher chance of earnings manipulation. Missing
    lines default to the neutral value (index 1, accruals 0) and are listed."""
    g = lambda d, k: _g(d, k)
    miss = []

    def idx(num, den, name):
        if num is None or den is None or den == 0:
            miss.append(name)
            return 1.0
        return num / den
    r1, r0 = g(cur, "revenue"), g(prev, "revenue")
    if not r1 or not r0:
        return None
    dsri = idx(_div(g(cur, "receivables"), r1), _div(g(prev, "receivables"), r0), "DSRI")
    gm = lambda d: _div(g(d, "gross_profit"), g(d, "revenue"))
    gmi = idx(gm(prev), gm(cur), "GMI")
    aq = lambda d: None if not g(d, "assets") or g(d, "current_assets") is None or g(d, "ppe") is None else 1 - (g(d, "current_assets") + g(d, "ppe")) / g(d, "assets")
    aqi = idx(aq(cur), aq(prev), "AQI")
    sgi = r1 / r0
    dep = lambda d: None if g(d, "da") is None or g(d, "ppe") is None else g(d, "da") / (g(d, "da") + g(d, "ppe"))
    depi = idx(dep(prev), dep(cur), "DEPI")
    sgai = idx(_div(g(cur, "sga"), r1), _div(g(prev, "sga"), r0), "SGAI")
    lv = lambda d: _div((g(d, "current_liabilities") or 0) + (g(d, "debt") or 0), g(d, "assets"))
    lvgi = idx(lv(cur), lv(prev), "LVGI")
    tata = _div(None if g(cur, "net_income") is None or g(cur, "cfo") is None else g(cur, "net_income") - g(cur, "cfo"), g(cur, "assets"))
    if tata is None:
        miss.append("TATA")
        tata = 0.0
    if len(miss) > 3:                                   # with most inputs neutral the score says nothing
        return {"m": None, "flag": None, "parts": {}, "neutral_filled": miss}
    m = -4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi
    return {"m": m, "flag": m > -1.78, "parts": {"DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi, "DEPI": depi, "SGAI": sgai, "LVGI": lvgi, "TATA": tata},
            "neutral_filled": miss}


def valuation(last: dict, row: dict, market_cap: float | None) -> dict | None:
    if not market_cap:
        return None
    debt = (_g(row, "debt") or 0) + (_g(row, "debt_current") or 0)
    cash = (_g(row, "cash") or 0) + (_g(row, "securities") or 0)
    ev = market_cap + debt - cash
    op, ni = _g(row, "op_income"), _g(row, "net_income")
    nwc = None if _g(row, "current_assets") is None or _g(row, "current_liabilities") is None else _g(row, "current_assets") - _g(row, "current_liabilities") - cash
    cap = None if _g(row, "ppe") is None else _g(row, "ppe") + max(0.0, nwc or 0.0)
    return {"market_cap": market_cap, "ev": ev, "ev_sales": _div(ev, last.get("revenue")), "ev_ebit": _div(ev, op), "pe": _div(market_cap, ni),
            "fcf_yield": _div(last.get("fcf"), market_cap), "earnings_yield": _div(op, ev), "return_on_capital": _div(op, cap)}


def analyze(facts: dict, ticker: str, market_cap: float | None = None, price: float | None = None) -> dict:
    """market_cap, or a price times the latest diluted share count, turns the statements into valuation multiples."""
    T, used = annual(facts)
    if len(T) < 2:
        return {"ticker": ticker, "ok": False, "note": "fewer than two annual filings with standard tags"}
    R = ratios(T)
    rows = [{k: _g(r, k) for k in T.columns} for _, r in T.iterrows()]
    for i in range(1, len(rows)):
        rows[i]["_assets_prior"] = rows[i - 1].get("assets")
    cur, prev = rows[-1], rows[-2]
    if market_cap is None and price and cur.get("shares"):
        market_cap = price * cur["shares"]
    out = {"ticker": ticker, "ok": True, "years": [r["end"] for r in R], "fiscal_year_end": R[-1]["end"], "tags": used, "ratios": R,
           "piotroski": piotroski(cur, prev), "altman_z2": altman_z2(cur), "beneish": beneish(cur, prev), "valuation": valuation(R[-1], cur, market_cap)}
    out["flags"] = flags(out)
    return out


def flags(a: dict) -> list[str]:
    """Plain-English findings a PM would want first."""
    r, f = a["ratios"][-1], []
    if r.get("cash_conversion") is not None and r["cash_conversion"] < 0.8:
        f.append(f"Cash conversion is {r['cash_conversion']:.2f}: less than 80 cents of operating cash per dollar of reported profit.")
    if r.get("capex_to_da") is not None and r["capex_to_da"] > 2:
        f.append(f"Capex runs {r['capex_to_da']:.1f}x depreciation: today's spending becomes tomorrow's depreciation charge.")
    if r.get("sbc_share_of_cfo") is not None and r["sbc_share_of_cfo"] > 0.2:
        f.append(f"Stock pay equals {r['sbc_share_of_cfo']:.0%} of operating cash flow; free cash flow overstates owner earnings by that much.")
    if r.get("growth_acceleration") is not None:
        f.append(f"Revenue growth {'accelerated' if r['growth_acceleration'] > 0 else 'slowed'} by {abs(r['growth_acceleration']):.1%} points to {r['revenue_growth']:.1%}.")
    p = a["piotroski"]
    f.append(f"Piotroski F-score {p['score']} of 9." if p["known"] == 9 else f"Piotroski: {p['score']} of the {p['known']} tests the filed tags allow pass (of 9).")
    if a.get("beneish") and a["beneish"].get("flag"):
        f.append(f"Beneish M-score {a['beneish']['m']:.2f} is above -1.78, the level that flags a higher chance of earnings manipulation; read the parts, not the label.")
    if a.get("altman_z2") and a["altman_z2"]["zone"] != "safe":
        f.append(f"Altman Z'' {a['altman_z2']['z']:.2f}: {a['altman_z2']['zone']} zone.")
    return f


def from_fixture_rows(units: dict[str, dict[str, list[dict]]]) -> dict[str, dict]:
    """Adapt the test fixture's per-ticker concept lists (fundamentals.parse_fixture) to the companyfacts shape."""
    out = {}
    for t, concepts in units.items():
        out[t] = {"facts": {"us-gaap": {c: {"units": {"USD": rows}} for c, rows in concepts.items()}}}
    return out
