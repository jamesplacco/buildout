"""10-K and 10-Q analysis of the AI builders, straight from SEC XBRL facts.

Every figure is a trailing-twelve-month (TTM) sum of discrete quarters recovered from the filings
(10-Qs report cash flows year to date, so quarters are differenced within each fiscal year), or the
latest balance-sheet value. On top of the raw numbers the desk computes:

  capex / OCF          how much of the build operating cash flow pays for (above 1: new money needed)
  capex / D&A          the build multiple: how far today's spending runs ahead of today's depreciation
  non-operating share  how much of pre-tax income is marks on investments rather than operations
  Minsky stage         hedge (cash flow pays for the build), speculative (the build needs new money but
                       income covers interest), Ponzi (income does not cover interest)
  depreciation path    what the build adds to depreciation, by year, at the stated and a shorter server life
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .data.edgar_source import instant_values, quarterly_flow

FLOWS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "leases": ["RightOfUseAssetObtainedInExchangeForFinanceLeaseLiability"],
    "da": ["DepreciationDepletionAndAmortization", "Depreciation", "DepreciationAmortizationAndAccretionNet"],
    "op_income": ["OperatingIncomeLoss"],
    "nonop": ["NonoperatingIncomeExpense"],
    "net_income": ["NetIncomeLoss"],
    "interest": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],          # v0.6: the manual's red flags
}
INSTANTS = {
    "debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "cash_total": ["CashCashEquivalentsAndShortTermInvestments"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "securities": ["MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent", "ShortTermInvestments"],
    "rpo": ["RevenueRemainingPerformanceObligation"],
    "receivables": ["AccountsReceivableNetCurrent"],
}
STAGES = {"hedge": "Hedge finance", "speculative": "Speculative finance", "ponzi": "Ponzi edge"}


def parse_fixture(path: str | Path) -> dict[str, dict[str, list[dict]]]:
    """Read the plain-text fact file used by the tests and the page snapshot (one block per ticker and concept)."""
    out: dict[str, dict[str, list[dict]]] = {}
    cur = None
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("# "):
            continue
        if line.startswith("## "):
            t, concept = line[3:].split()
            cur = out.setdefault(t, {}).setdefault(concept, [])
            continue
        start, end, val, form, filed = line.split(",")
        row = {"end": end, "val": float(val), "form": form, "filed": filed}
        if start:
            row["start"] = start
        cur.append(row)
    return out


def from_companyfacts(facts: dict) -> dict[str, list[dict]]:
    """The us-gaap USD facts of an SEC companyfacts document, keyed by concept."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    return {k: v.get("units", {}).get("USD", []) for k, v in gaap.items() if v.get("units", {}).get("USD")}


def _first(units: dict[str, list[dict]], names: list[str], fn) -> pd.Series:
    out = pd.Series(dtype=float)
    for name in names:
        rows = units.get(name)
        if rows:
            s = fn(rows)
            out = s if out.empty else out.combine_first(s)
    return out.sort_index()


def ttm(q: pd.Series, end: pd.Timestamp | None = None) -> float | None:
    """Sum of the four discrete quarters ending at `end` (default: the latest), only if they are contiguous."""
    q = q.dropna().sort_index()
    if q.empty:
        return None
    end = q.index[-1] if end is None else end
    sub = q.loc[:end]
    if sub.empty or sub.index[-1] != end:
        return None
    sub = sub.iloc[-4:]
    if len(sub) < 4:
        return None
    gaps = np.diff(sub.index.values).astype("timedelta64[D]").astype(int)
    if not all(80 <= g <= 100 for g in gaps):
        return None
    return float(sub.sum())


def _at(s: pd.Series, when: pd.Timestamp, tol_days: int = 10) -> float | None:
    s = s.dropna()
    if s.empty:
        return None
    near = s[(s.index >= when - pd.Timedelta(days=tol_days)) & (s.index <= when + pd.Timedelta(days=tol_days))]
    return float(near.iloc[-1]) if len(near) else None


def analyze_company(units: dict[str, list[dict]], supplements: dict | None = None) -> dict:
    """TTM metrics, balance sheet, ratios and the Minsky stage for one company (USD billions)."""
    qs = {k: _first(units, v, quarterly_flow) for k, v in FLOWS.items()}
    inst = {k: _first(units, v, instant_values) for k, v in INSTANTS.items()}
    base = qs["capex"] if not qs["capex"].empty else qs["ocf"]
    if base.empty:
        raise ValueError("no capex or operating cash flow facts")
    end = base.index[-1]
    m: dict = {"quarter_end": end.strftime("%Y-%m-%d")}
    for k, s in qs.items():
        v = ttm(s, end)
        m[k] = None if v is None else v / 1e9
    lq = qs["capex"].get(end) if not qs["capex"].empty else None
    yago = _at(qs["capex"], end - pd.DateOffset(years=1))
    m["capex_last_q"] = None if lq is None else float(lq) / 1e9
    m["capex_last_q_yoy"] = (float(lq) / yago - 1) if lq is not None and yago else None
    # second derivative of the build: this quarter's growth minus last quarter's
    prev_end = qs["capex"].loc[:end].index[-2] if len(qs["capex"].loc[:end]) >= 2 else None
    if prev_end is not None and m["capex_last_q_yoy"] is not None:
        p, pya = qs["capex"].get(prev_end), _at(qs["capex"], prev_end - pd.DateOffset(years=1))
        m["capex_yoy_prev_q"] = (float(p) / pya - 1) if pya else None
        m["capex_accel"] = None if m["capex_yoy_prev_q"] is None else m["capex_last_q_yoy"] - m["capex_yoy_prev_q"]
    else:
        m["capex_yoy_prev_q"] = m["capex_accel"] = None
    rev_yago = ttm(qs["revenue"], end - pd.DateOffset(years=1)) if not qs["revenue"].empty else None
    # TTM a year earlier needs that quarter end exactly; look for the nearest quarter end within ten days
    if rev_yago is None and not qs["revenue"].empty:
        cands = [d for d in qs["revenue"].index if abs((d - (end - pd.DateOffset(years=1))).days) <= 10]
        rev_yago = ttm(qs["revenue"], cands[-1]) if cands else None
    m["revenue_growth"] = (m["revenue"] * 1e9 / rev_yago - 1) if m["revenue"] and rev_yago else None
    rq = qs["revenue"].get(end) if not qs["revenue"].empty else None
    rqa = _at(qs["revenue"], end - pd.DateOffset(years=1))
    m["revenue_last_q"] = None if rq is None else float(rq) / 1e9
    m["revenue_last_q_yoy"] = (float(rq) / rqa - 1) if rq is not None and rqa else None
    oq = qs["op_income"].get(end) if not qs["op_income"].empty else None
    oqa = _at(qs["op_income"], end - pd.DateOffset(years=1))
    m["op_income_last_q_yoy"] = (float(oq) / oqa - 1) if oq is not None and oqa and oqa > 0 else None

    def last(name: str) -> tuple[float | None, str | None]:
        s = inst[name].dropna()
        return (float(s.iloc[-1]) / 1e9, s.index[-1].strftime("%Y-%m-%d")) if len(s) else (None, None)

    m["debt"], m["debt_date"] = last("debt")
    total, total_date = last("cash_total")
    cash, cash_date = last("cash")
    sec, _ = last("securities")
    m["cash"], m["cash_date"] = (total, total_date) if total is not None else ((cash + (sec or 0.0)), cash_date) if cash is not None else (None, None)
    m["rpo"], m["rpo_date"] = last("rpo")
    m["receivables"], _ = last("receivables")
    rc = inst["receivables"].dropna()
    rprior = _at(rc, rc.index[-1] - pd.DateOffset(years=1), 40) if len(rc) else None
    m["receivables_yoy"] = (m["receivables"] * 1e9 / rprior - 1) if m["receivables"] is not None and rprior else None
    d = inst["debt"].dropna()
    prior = _at(d, d.index[-1] - pd.DateOffset(years=1), 40) if len(d) else None
    m["debt_yoy"] = (m["debt"] * 1e9 / prior - 1) if m["debt"] is not None and prior else None
    if supplements:
        for k, v in supplements.items():
            if v is not None and (m.get(k) is None or k in supplements.get("_override", ())):
                m[k] = v
    return derive(m)


def derive(m: dict) -> dict:
    g = lambda k: m.get(k)  # noqa: E731
    div = lambda a, b: (a / b) if a is not None and b not in (None, 0) else None  # noqa: E731
    m["fcf"] = None if g("ocf") is None or g("capex") is None else g("ocf") - g("capex")
    m["capex_to_ocf"] = div(g("capex"), g("ocf"))
    m["capex_to_da"] = div(g("capex"), g("da"))
    pre = None if g("op_income") is None or g("nonop") is None else g("op_income") + g("nonop")
    m["nonop_share"] = div(g("nonop"), pre) if pre and pre > 0 else None
    m["net_cash"] = None if g("cash") is None or g("debt") is None else g("cash") - g("debt")
    m["rpo_years"] = div(g("rpo"), g("revenue"))
    m["ocf_to_interest"] = div(g("ocf"), g("interest"))
    m["stage"] = minsky_stage(m)
    m["coverage"] = coverage(m)
    gap = None if g("capex") is None or g("ocf") is None else g("capex") - g("ocf")
    m["funding_gap"] = gap if gap is not None and gap > 0 else (0.0 if gap is not None else None)
    m["gap_cover_years"] = div(g("cash"), gap) if gap is not None and gap > 0 else None
    # the field manual's red-flag tests (6c), where the filings carry the inputs
    m["fcf_to_ni"] = div(g("fcf"), g("net_income")) if (g("net_income") or 0) > 0 else None
    m["sbc_to_rev"] = div(g("sbc"), g("revenue"))
    ry, gy = g("receivables_yoy"), g("revenue_growth")
    m["recv_minus_rev"] = (ry - gy) if ry is not None and gy is not None else None
    from .accounting import red_flags
    m["red_flags"] = red_flags({"capex_to_dep": m.get("capex_to_da"), "fcf_to_ni": m.get("fcf_to_ni"), "sbc_to_rev": m.get("sbc_to_rev"),
                                "recv_minus_rev": m.get("recv_minus_rev")})
    return m


COVERAGE = {"self_funded": "Cash flow covers capex", "funding_gap": "Capex exceeds cash flow; interest covered",
            "interest_uncovered": "Operating income below interest, or negative cash flow"}


def coverage(m: dict) -> str | None:
    """Descriptive coverage category (replaces the Minsky labels on the page).

    It measures one year of cash flow against one year of capex and interest. It is NOT a solvency verdict: cash
    balances, asset sales, discretionary capex and debt maturities (not modelled here) all matter.
    """
    s = minsky_stage(m)
    return None if s is None else {"hedge": "self_funded", "speculative": "funding_gap", "ponzi": "interest_uncovered"}[s]


def minsky_stage(m: dict) -> str | None:
    """Hyman Minsky's three financing postures, applied to the build.

    hedge        operating cash flow pays for the whole build
    speculative  the build needs new money (debt, leases, partners), but income covers the interest
    ponzi        operating income does not cover interest (or cash flow is negative): survival depends on
                 refinancing and asset values
    """
    ocf, capex = m.get("ocf"), m.get("capex")
    if ocf is None or capex is None:
        return None
    op, interest = m.get("op_income_lq", m.get("op_income")), m.get("interest_lq", m.get("interest"))
    if ocf <= 0 or (op is not None and interest is not None and interest > 0 and op < interest):
        return "ponzi"
    return "hedge" if capex <= ocf else "speculative"


def depreciation_path(capex: dict[int, float], server_share: float, server_life: float, other_life: float = 25.0,
                      years: list[int] | None = None) -> dict[int, float]:
    """Straight-line depreciation by fiscal year for a capex history, assets placed in service mid-year.

    The server share of each year's capex depreciates over `server_life`, the rest (shells, power, cooling)
    over `other_life`. A vintage placed at mid-year v spreads its cost evenly over [v + 0.5, v + 0.5 + life].
    Land and construction still in progress are not separated out, so near-term depreciation is overstated
    and the wave arrives later than modeled; the life sensitivity is the point, not the level.
    """
    years = years or sorted(capex)
    out = {}
    for t in years:
        tot = 0.0
        for v, c in capex.items():
            for share, life in ((server_share, server_life), (1 - server_share, other_life)):
                a, b = v + 0.5, v + 0.5 + life
                overlap = max(0.0, min(t + 1, b) - max(t, a))
                tot += c * share * overlap / life
        out[t] = tot
    return out


def fit_server_share(capex: dict[int, float], year: int, actual: float, server_life: float, other_life: float = 25.0) -> float:
    """The server share that makes the model's depreciation in `year` equal the reported figure (it is linear in the share)."""
    a = depreciation_path(capex, 1.0, server_life, other_life, [year])[year]
    b = depreciation_path(capex, 0.0, server_life, other_life, [year])[year]
    if a == b:
        return float("nan")
    return float(min(1.0, max(0.0, (actual - b) / (a - b))))


def life_sensitivity(capex: dict[int, float], fit_year: int, actual_da: float, stated_life: float, short_life: float,
                     years: list[int], other_life: float = 25.0) -> dict:
    """Depreciation by year at the stated server life and at a shorter one, with the server share fitted to the filings."""
    s = fit_server_share(capex, fit_year, actual_da, stated_life, other_life)
    if not math.isfinite(s):
        return {}
    at_stated = depreciation_path(capex, s, stated_life, other_life, years)
    at_short = depreciation_path(capex, s, short_life, other_life, years)
    return {"server_share": s, "stated": at_stated, "short": at_short, "extra": {y: at_short[y] - at_stated[y] for y in years}}
