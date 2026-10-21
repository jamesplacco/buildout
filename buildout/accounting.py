"""The accounting stress test from the 2026 field manual, as pure functions the page mirrors exactly.

  depreciation_table   straight-line depreciation of a server cohort by assumed life, and the gap to book life
  ddb_first_year       first-year double-declining depreciation (the "front-loaded" schedule)
  cash_eps             the cash earnings bridge: reported earnings less the costs accounting defers or hides
  reverse_dcf          the 10-year free-cash-flow growth a price already assumes
  credit_stress        net yield to an unlevered private-credit investor after defaults, recoveries and fees
  red_flags            the six tech and high-growth tests, graded healthy, watch or red

Every function takes plain numbers and returns plain numbers, so tests/test_page.py checks the browser's copy
against these to machine precision.
"""
from __future__ import annotations

import math

LIVES = (6, 5, 4, 3, 2)


def depreciation_table(cohort: float, lives=LIVES, book_life: float = 6.0) -> list[dict]:
    book = cohort / book_life
    return [{"life": L, "annual": cohort / L, "gap": cohort / L - book} for L in lives]


def ddb_first_year(cohort: float, life: float) -> float:
    """Double-declining balance: twice the straight-line rate on the full cost in year one."""
    return cohort * min(1.0, 2.0 / life)


def cash_eps(net_income: float, d_economic: float, d_book: float, sbc: float, d_cap_software: float,
             d_deferred_revenue: float, diluted_shares: float) -> float:
    """Cash EPS = [NI - (D_econ - D_book) - SBC - change in capitalized software + change in deferred revenue] / shares.

    Pre-tax adjustments on an after-tax figure, as the manual writes it: a conservative (lower) cash EPS.
    """
    if diluted_shares <= 0:
        return float("nan")
    return (net_income - (d_economic - d_book) - sbc - d_cap_software + d_deferred_revenue) / diluted_shares


def dcf_value(fcf0: float, growth: float, rate: float, terminal_growth: float, years: int = 10) -> float:
    """Present value of free cash flow growing at `growth` for `years`, then at `terminal_growth` forever."""
    if rate <= terminal_growth:
        return float("inf")
    pv, f = 0.0, fcf0
    for t in range(1, years + 1):
        f *= 1 + growth
        pv += f / (1 + rate) ** t
    term = f * (1 + terminal_growth) / (rate - terminal_growth)
    return pv + term / (1 + rate) ** years


def reverse_dcf(market_value: float, fcf0: float, rate: float, terminal_growth: float = 0.03, years: int = 10) -> float:
    """The constant growth over `years` that makes the DCF equal the market value (bisection on -50% to +150%)."""
    if fcf0 <= 0 or market_value <= 0 or rate <= terminal_growth:
        return float("nan")
    lo, hi = -0.5, 1.5
    if dcf_value(fcf0, hi, rate, terminal_growth, years) < market_value:
        return float("inf")
    if dcf_value(fcf0, lo, rate, terminal_growth, years) > market_value:
        return lo
    for _ in range(200):
        mid = (lo + hi) / 2
        if dcf_value(fcf0, mid, rate, terminal_growth, years) > market_value:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def credit_stress(base: float, spread: float, default_rate: float, recovery: float, mgmt_fee: float = 0.0125,
                  incentive: float = 0.125, treasury: float = 0.052) -> dict:
    """Unlevered direct-lending fund, one year: gross yield, credit loss, net to the investor, spread over Treasuries.

    The incentive fee is charged on income after losses and the management fee, and only when that is positive.
    """
    gross = base + spread
    loss = default_rate * (1 - recovery)
    pre_fee = gross - loss - mgmt_fee
    net = pre_fee * (1 - incentive) if pre_fee > 0 else pre_fee
    return {"gross": gross, "loss": loss, "net": net, "over_treasury": net - treasury}


RED_FLAG_TESTS = [
    # key, label, healthy edge, red edge, direction ("lt": lower is healthier)
    ("capex_to_dep", "Capex / depreciation", 1.5, 2.5, "lt"),
    ("fcf_to_ni", "Free cash flow / net income", 0.9, 0.6, "gt"),
    ("sbc_to_rev", "Stock compensation / revenue", 0.05, 0.12, "lt"),
    ("recv_minus_rev", "Receivables growth minus revenue growth", 0.05, 0.10, "lt"),
    ("top3_customers", "Top three customers / revenue", 0.30, 0.50, "lt"),
]


def grade(value: float | None, healthy: float, red: float, direction: str) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    if direction == "lt":
        return "healthy" if value < healthy else "red" if value > red else "watch"
    return "healthy" if value > healthy else "red" if value < red else "watch"


def red_flags(metrics: dict) -> list[dict]:
    return [{"key": k, "test": label, "value": metrics.get(k), "grade": grade(metrics.get(k), h, r, d)}
            for k, label, h, r, d in RED_FLAG_TESTS]
