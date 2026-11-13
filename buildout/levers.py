"""Value creation, lever by lever (v0.38): the arithmetic of a leveraged buyout of a small services business, with
the equity value bridge a private-equity investment committee reads, and the same six levers applied to the AI
buildout's companies.

The deal model (all inputs are assumptions a user sets on the page; the defaults are a worked example):
  entry EV = entry multiple x entry EBITDA; debt = leverage x EV (an SBA 7(a) loan, level amortisation over
  `amort_years` at `rate`); equity = EV - debt.
  Each year: revenue grows by the price lift (in the first year), the mix and set-aside revenue, and a bolt-on;
  EBITDA = revenue x margin, where the margin rises by the margin levers; free cash flow = EBITDA x (1 - tax and
  capex drag) + working capital released - debt service; cash pays down debt beyond the schedule if `sweep`.
  Exit EV = exit multiple x exit EBITDA, where the exit multiple is the platform multiple only if EBITDA has reached
  the platform threshold and a GM is in the seat; otherwise it stays at the entry multiple.

The bridge splits the equity gain into EBITDA growth (at the entry multiple), multiple expansion (on exit EBITDA) and
debt paydown, the usual attribution.
"""
from __future__ import annotations

DEFAULTS = {
    "revenue0": 7.0e6, "margin0": 0.14, "entry_multiple": 3.5, "leverage": 0.90, "rate": 0.10, "amort_years": 10,
    "price_lift": 0.05, "price_flow_through": 0.80, "growth": 0.04, "set_aside_rev": 1.0e6, "set_aside_margin": 0.18, "set_aside_year": 2,
    "margin_gain_yr": 0.010, "margin_years": 3, "wc_release": 0.5e6, "bolt_on_ebitda": 0.6e6, "bolt_on_multiple": 4.0, "bolt_on_year": 3, "bolt_on_margin": 0.12,
    "members_y3": 1500, "member_fee": 240.0, "member_margin": 0.50,
    "gm_year": 3, "platform_threshold": 2.5e6, "platform_multiple": 6.0, "tax_capex_drag": 0.35, "years": 5, "sweep": True,
}


def model(p: dict | None = None) -> dict:
    p = {**DEFAULTS, **(p or {})}
    e0 = p["revenue0"] * p["margin0"]
    ev0 = p["entry_multiple"] * e0
    debt = p["leverage"] * ev0
    eq0 = ev0 - debt
    r = p["rate"]
    n = p["amort_years"]
    pay = debt * r / (1 - (1 + r) ** -n) if r > 0 else debt / n          # level annual debt service
    rev, margin, rows = p["revenue0"], p["margin0"], []
    bolt_ebitda = bolt_rev = 0.0
    for y in range(1, p["years"] + 1):
        rev *= 1 + p["growth"]
        price = 0.0
        if y == 1:
            price = p["revenue0"] * p["price_lift"]
            rev += price
        if y <= p["margin_years"]:
            margin += p["margin_gain_yr"]
        set_aside = p["set_aside_rev"] if y >= p["set_aside_year"] else 0.0
        members = p["members_y3"] * min(y, 3) / 3                      # the membership base ramps to its year-3 size
        member_rev = members * p["member_fee"]
        if y == p["bolt_on_year"]:
            bolt_ebitda = p["bolt_on_ebitda"]
            bolt_rev = p["bolt_on_ebitda"] / p["bolt_on_margin"]
            debt += p["bolt_on_ebitda"] * p["bolt_on_multiple"] * p["leverage"]          # financed on the same terms
            eq0 += p["bolt_on_ebitda"] * p["bolt_on_multiple"] * (1 - p["leverage"])   # equity put in for it
            pay = debt * r / (1 - (1 + r) ** -n) if r > 0 else debt / n
        ebitda = rev * margin + price * (p["price_flow_through"] - margin) + set_aside * p["set_aside_margin"] + member_rev * p["member_margin"] + bolt_ebitda
        interest = debt * r
        principal = min(debt, pay - interest)
        wc = p["wc_release"] if y == 1 else 0.0
        fcf = ebitda * (1 - p["tax_capex_drag"]) + wc - (interest + principal)
        extra = min(debt - principal, max(fcf, 0.0)) if p["sweep"] else 0.0
        debt = max(0.0, debt - principal - extra)
        total_rev = rev + set_aside + member_rev + bolt_rev
        rows.append({"year": y, "revenue": total_rev, "ebitda": ebitda, "margin": ebitda / total_rev, "debt": debt, "fcf_after_debt": fcf, "swept": extra, "members": members})
    eN = rows[-1]["ebitda"]
    platform = eN >= p["platform_threshold"] and p["years"] >= p["gm_year"]
    m_exit = p["platform_multiple"] if platform else p["entry_multiple"]
    evN = m_exit * eN
    eqN = evN - rows[-1]["debt"]
    moic = eqN / eq0 if eq0 > 0 else float("nan")
    irr = moic ** (1 / p["years"]) - 1 if moic > 0 else float("nan")
    debt_in = p["leverage"] * ev0 + (p["bolt_on_ebitda"] * p["bolt_on_multiple"] * p["leverage"] if p["years"] >= p["bolt_on_year"] else 0.0)
    # equity out less equity in = m0 (E_N - E0) + (m_exit - m0) E_N + (debt borrowed - debt left) - bolt-on price
    bridge = {"ebitda_growth": (eN - e0) * p["entry_multiple"], "multiple": (m_exit - p["entry_multiple"]) * eN, "paydown": debt_in - rows[-1]["debt"],
              "bolt_on_price": -(p["bolt_on_ebitda"] * p["bolt_on_multiple"]) if p["years"] >= p["bolt_on_year"] else 0.0}
    bridge["total"] = sum(bridge.values())
    return {"inputs": p, "entry": {"ebitda": e0, "ev": ev0, "debt": p["leverage"] * ev0, "equity": p["revenue0"] * p["margin0"] * p["entry_multiple"] * (1 - p["leverage"]), "equity_total": eq0},
            "rows": rows, "exit": {"ebitda": eN, "multiple": m_exit, "platform": platform, "ev": evN, "equity": eqN, "equity_at_entry_multiple": p["entry_multiple"] * eN - rows[-1]["debt"]},
            "moic": moic, "irr": irr, "bridge": bridge, "gap_to_platform": max(0.0, p["platform_threshold"] - eN),
            "sensitivity": [{"year": 0, "ten_pct": equity_sensitivity(ev0, p["leverage"] * ev0)}] + [{"year": r_["year"], "ten_pct": equity_sensitivity(p["entry_multiple"] * r_["ebitda"], r_["debt"])} for r_ in rows]}


def equity_sensitivity(ev: float, debt: float, move: float = 0.10) -> float:
    """The change in equity value from a `move` change in EBITDA at a fixed multiple: (move x EV) / (EV - debt)."""
    eq = ev - debt
    return move * ev / eq if eq > 0 else float("inf")


# The same six levers read on the AI buildout's companies: what moves equity value for a hyperscaler is the same list,
# in a different order of importance. The figures live in the page's data (site/src/levers.js), each dated and sourced.
LEVERS = ["Multiple", "Revenue growth", "Margin", "Capital efficiency", "Leverage", "Management"]
