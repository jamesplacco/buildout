"""The private credit lens (v0.34), centred on Blue Owl Capital: the manager (OWL), its listed BDC (OBDC), its
non-traded funds (OCIC, OTIC) and the data-center vehicles that finance the book's own names.

Private credit matters to an AI equity book for one reason: it is the marginal source of the equity and debt that
build the campuses the nine names lease, and it is marked by models, so stress shows in three places before it shows
in a mark. This module reads those three places from filings and computes what they imply:

  1. Liquidity. A non-traded fund repurchases at most 5% of its shares a quarter, pro rata. The fill rate is
     cap / requests, and a holder who keeps asking exits geometrically: after n quarters (1 - fill)^n remains.
  2. Marks. A listed BDC's discount to net asset value is the market's mark on the same kind of loans. With debt
     D and equity E, an equity discount d implies an asset markdown of d / (1 + D/E), to compare with the
     non-accruals the fund books.
  3. Income quality. Payment-in-kind interest is income that arrives as more loan. Net investment income less
     PIK against the dividend is the cash cover.

Every figure here is dated and sourced (OBS, and the cohort tables); the functions are arithmetic on them. The
cohort (v0.35) runs Apollo, HPS, Ares, Blackstone, Goldman and Golub through the same queue model, and the listed
peers (ARCC, BXSL) through the same marks and cover, to say whether Blue Owl is the outlier or the sector. Nothing here is a position;
the lens says what to watch and what would flip the thesis (data.js t6) in each direction.
"""
from __future__ import annotations

import math
from datetime import date

from . import accounting

CAP = 0.05                       # the quarterly repurchase cap of a non-traded BDC, share of shares outstanding

# ---------------------------------------------------------------- observations (dated, sourced)
SRC = {
    "owl_pr": ("Blue Owl Capital Inc., Q3 2026 results, 8-K exhibit 99.1, Oct 29, 2026", "https://www.sec.gov/Archives/edgar/data/0001823945/000182394526000050/a93026-ex991xearningspress.htm"),
    "owl_10q": ("Blue Owl Capital Inc., Form 10-Q for Sept 30, 2026", "https://www.sec.gov/Archives/edgar/data/1823945/000182394526000055/owl-20260930.htm"),
    "owl_call": ("Blue Owl Q3 2026 earnings call transcript, Oct 29, 2026 (Motley Fool)", "https://www.fool.com/earnings/call-transcripts/2026/10/29/blue-owl-owl-q3-2026-earnings-call-transcript/"),
    "obdc_pr": ("Blue Owl Capital Corporation, June 30, 2026 results, 8-K exhibit 99.1, Aug 5, 2026", "https://www.sec.gov/Archives/edgar/data/0001655888/000165588826000055/exhibit991-obdcxpressrelea.htm"),
    "obdc_10q": ("OBDC Q2 2026 10-Q figures (non-accrual schedule, PIK, buybacks), via Crowdfunded Wealth", "https://www.crowdfundedwealth.com/articles/blue-owl-capital-corporation-obdc-dividend-non-accruals-2026"),
    "obdc_date": ("OBDC sets Nov 4 third-quarter release (Quiver)", "https://www.quiverquant.com/news/Blue+Owl+Capital+OBDC+Sets+November+4+Third-Quarter+Results+Release"),
    "tender": ("Blue Owl BDCs pay $1.07B in Q3 tenders; OTIC fills 12.8% of requests (AltsWire, final results filed Oct 26, 2026)", "https://altswire.com/blue-owl-bdcs-pay-1-07-billion-in-q3-tenders-as-otic-fills-12-8-of-requests/"),
    "requests": ("Blue Owl's repurchase update puts liquidity limits in focus (Blue Vault, Oct 8, 2026)", "https://bluevaultpartners.com/blue-owl-repurchase-liquidity-limits/"),
    "cox": ("Cox Capital mini-tender for OCIC Class I at $7.31, about 20% below NAV (Oct 2026)", "https://www.stocktitan.net/news/OBDC/cox-capital-adjusts-commencement-date-for-blue-owl-credit-income-6t6ysbtreeii.html"),
    "fitch": ("Fitch, US Private Credit and Middle Market Performance Monitor 3Q26 (Oct 29, 2026), via Forbes Oct 29 and ABF Journal Oct 30", "https://www.forbes.com/sites/mayrarodriguezvalladares/2026/10/29/us-private-credit-defaults-hit-record-63-as-quiet-distress-grows/"),
    "fitch2": ("Fitch: US private credit default rate remains elevated in Q3 (ABF Journal, Oct 30, 2026)", "https://www.abfjournal.com/fitch-ratings-u-s-private-credit-default-rate-remains-elevated-in-q3/"),
    "hyperion": ("Meta and Blue Owl sign US$27 billion data centre campus deal (The Asset, Oct 2025)", "https://www.theasset.com/article/55209/meta-blue-owl-sign-us-27-billion-data-centre-campus-deal"),
    "bcred": ("BCRED caps Q3 repurchases at 5% as requests hit $4.3B, about 10% of shares (AltsWire, letter of Sept 3, 2026)", "https://altswire.com/bcred-caps-q3-repurchases-at-5-as-requests-hit-4-3b-about-10-of-shares/"),
    "ads": ("Apollo Debt Solutions caps third-quarter repurchases at $700M as requests reach 14.7% (Blue Vault, Sept 24, 2026)", "https://bluevaultpartners.com/apollo-debt-solutions-caps-third-quarter-repurchases-at-700-million-as-requests-reach-14-7/"),
    "ntbdc": ("Non-traded BDC list 2026: 67 funds by net assets with latest tender results (Crowdfunded Wealth, June 30, 2026 net assets)", "https://www.crowdfundedwealth.com/articles/non-traded-bdc-list-2026"),
    "arcc": ("Ares Capital, Sept 30, 2026 results (Oct 27, 2026)", "https://www.stocktitan.net/news/ARCC/ares-capital-corporation-announces-september-30-2026-financial-lrx7kfpu69zl.html"),
    "arcc_call": ("Ares Capital Q3 2026 earnings call transcript, Oct 27, 2026 (Motley Fool)", "https://www.fool.com/earnings/call-transcripts/2026/10/27/ares-capital-arcc-q3-2026-earnings-call-transcript/"),
    "bxsl": ("Blackstone Secured Lending Fund, June 30, 2026 results, 8-K exhibit 99.1 (Aug 6, 2026)", "https://www.sec.gov/Archives/edgar/data/1736035/000121390026085889/ea0300654-01_ex991.htm"),
}

# ---------------------------------------------------------------- the cohort (v0.35): is Blue Owl the outlier, or the sector?
COHORT_QUEUES = [  # non-traded funds: requests as a share of shares where reported, else inferred from the fill (cap / fill)
    {"fund": "Blue Owl Technology Income (OTIC)", "sponsor": "Blue Owl", "asof": "2026-09-30", "requests": 0.39, "fill": 0.128, "requests_basis": "reported", "net_assets": None, "src": ["tender"]},
    {"fund": "Blue Owl Credit Income (OCIC)", "sponsor": "Blue Owl", "asof": "2026-09-30", "requests": 0.168, "fill": 0.298, "requests_basis": "reported", "net_assets": 18.43e9, "src": ["tender", "ntbdc"]},
    {"fund": "Apollo Debt Solutions (ADS)", "sponsor": "Apollo", "asof": "2026-09-14", "requests": 0.147, "fill": 0.34, "requests_basis": "reported (preliminary)", "net_assets": 14.00e9, "src": ["ads", "ntbdc"]},
    {"fund": "HPS Corporate Lending", "sponsor": "HPS (BlackRock)", "asof": "2026-06-08", "requests": None, "fill": 0.376, "requests_basis": "inferred from the fill", "net_assets": 12.05e9, "src": ["ntbdc"]},
    {"fund": "Ares Strategic Income (ASIF)", "sponsor": "Ares", "asof": "2026-09-18", "requests": None, "fill": 0.382, "requests_basis": "inferred from the fill", "net_assets": 10.21e9, "src": ["ntbdc"]},
    {"fund": "Blackstone Private Credit (BCRED)", "sponsor": "Blackstone", "asof": "2026-09-03", "requests": 0.10, "fill": None, "requests_basis": "reported (about 10%); fill implied by the 5% cap", "net_assets": 42.78e9, "src": ["bcred", "ntbdc"]},
    {"fund": "Goldman Sachs Private Credit", "sponsor": "Goldman Sachs", "asof": "2026-09-22", "requests": None, "fill": 1.0, "requests_basis": "all requests met", "net_assets": 9.19e9, "src": ["ntbdc"]},
    {"fund": "Golub Capital Private Credit", "sponsor": "Golub", "asof": "2026-07-29", "requests": None, "fill": 1.0, "requests_basis": "all requests met", "net_assets": 4.47e9, "src": ["ntbdc"]},
]
COHORT_CHECKS = [  # the queue model inverted (requests = cap / fill) against a figure the fund reported separately
    {"fund": "Apollo Debt Solutions, Q3 2026", "fill": 0.34, "requests_reported": 0.147, "src": "ads"},
    {"fund": "Blue Owl Credit Income, Q2 2026", "fill": 0.266, "requests_reported": 0.188, "src": "ntbdc"},
]
COHORT_SECTOR = {"funds": 67, "prorated": 16, "prorated_share_of_net_assets": 0.650, "top5_all_prorated": True, "top5_share_of_net_assets": 0.551, "asof": "2026-06-30", "src": ["ntbdc"]}
COHORT_LISTED = [  # listed BDCs: the marks the funds book, and the dividend cover before any cut
    {"fund": "Blue Owl Capital Corp (OBDC)", "asof": "2026-06-30", "nav_ps": 14.26, "nav_ps_year_end": 14.81, "non_accrual_cost": 0.028, "non_accrual_fv": 0.008, "debt_to_equity": 1.11, "first_lien": 0.732,
     "earnings_ps": 0.36, "earnings_basis": "GAAP NII", "dividend_ps": 0.33, "dividend_note": "base cut from $0.37 to $0.31 in 2026", "price_to_nav": 0.774, "price_basis": "own June buybacks", "src": ["obdc_pr", "obdc_10q"]},
    {"fund": "Ares Capital (ARCC)", "asof": "2026-09-30", "nav_ps": 19.31, "nav_ps_year_end": 19.94, "non_accrual_cost": 0.024, "non_accrual_fv": 0.014, "debt_to_equity": 1.06, "first_lien": 0.58,
     "earnings_ps": 0.46, "earnings_basis": "core EPS", "dividend_ps": 0.48, "dividend_note": "unchanged; one small software loan on non-accrual", "price_to_nav": None, "price_basis": "no verified price", "src": ["arcc", "arcc_call"]},
    {"fund": "Blackstone Secured Lending (BXSL)", "asof": "2026-06-30", "nav_ps": 25.53, "nav_ps_year_end": None, "nav_ps_prior_q": 26.26, "non_accrual_cost": 0.036, "non_accrual_fv": 0.018, "debt_to_equity": 1.28, "first_lien": 0.968,
     "earnings_ps": 0.75, "earnings_basis": "NII", "dividend_ps": 0.77, "dividend_note": "unchanged", "price_to_nav": None, "price_basis": "no verified price", "src": ["bxsl"]},
    {"fund": "Blackstone Private Credit (BCRED), non-traded", "asof": "2026-06-30", "nav_ps": 23.65, "nav_ps_year_end": 24.79, "non_accrual_cost": 0.022, "non_accrual_fv": 0.011, "debt_to_equity": 0.80, "first_lien": None,
     "earnings_ps": None, "earnings_basis": None, "dividend_ps": None, "dividend_note": "monthly distribution cut from $0.22 to $0.18 since Oct 2025", "price_to_nav": None, "price_basis": "not listed", "src": ["bcred"]},
]

OBS = {
    "owl": {  # the manager
        "name": "Blue Owl Capital Inc. (OWL)", "asof": "2026-09-30", "reported": "2026-10-29", "src": ["owl_pr", "owl_10q", "owl_call"],
        "aum": 330e9, "aum_growth_yoy": 0.12, "aum_not_yet_fee_paying": 36.3e9, "fees_expected_from_undeployed": 400e6,
        "revenue_q": 806.5e6, "revenue_q_prior_year": 728.0e6, "gaap_net_income_q": 20.0e6, "gaap_net_income_q_prior_year": 6.3e6,
        "fre_q": 427.5e6, "fre_q_prior_year": 376.2e6, "fre_margin": 0.588, "fre_ps": 0.27, "de_ps": 0.24, "dividend_ps": 0.23,
        "raised_q": 12.6e9, "raised_ttm": 49e9, "credit_raised_q": 5.6e9, "credit_raised_split": {"investment_grade": 2.3e9, "direct_lending": 1.8e9, "alternative_credit": 1.1e9},
        "direct_lending_realized_loss_ann": 0.0012, "originations_q": 5.2e9, "repayments_q": 4.7e9,
        "data_centers": 130, "gw_leased_or_owned": 14, "gw_pipeline": 21, "next_digital_fund_target": 10e9,
        "wealth_inflows_qoq": 0.14, "wealth_equity_raised_ttm": 11e9,
        "quotes": [("Marc Lipschultz, co-CEO", "There had been broad speculation that the industry was going to go through a stress test ... the data has proven out in our favor in terms of credit quality."),
                   ("Alan Kirshenbaum, CFO", "We are taking Microsoft, Amazon, Meta credit risk.")],
        "chip_financing": ["SpaceX (originally xAI)", "IREN"],
    },
    "obdc": {  # the listed BDC
        "name": "Blue Owl Capital Corporation (OBDC)", "asof": "2026-06-30", "reported": "2026-08-05", "next_report": "2026-11-04", "src": ["obdc_pr", "obdc_10q", "obdc_date"],
        "nav_ps": 14.26, "nav_history": [("2024-12-31", 15.26), ("2025-06-30", 15.03), ("2025-12-31", 14.81), ("2026-03-31", 14.41), ("2026-06-30", 14.26)],
        "nii_ps": 0.36, "nii_ps_adjusted": 0.34, "dividend_base": 0.31, "dividend_base_prior": 0.37, "dividend_supplemental": 0.02,
        "non_accrual_cost": 0.028, "non_accrual_fv": 0.008, "non_accrual_cost_usd": 428.7e6, "non_accrual_fv_usd": 126.4e6, "non_accrual_count": 7,
        "non_accrual_history": [("2025-09-30", 0.027, 0.013), ("2025-12-31", 0.023, 0.011), ("2026-03-31", 0.020, 0.010), ("2026-06-30", 0.028, 0.008)],
        "pik_share_income_q": 31.6e6 / 401.3e6, "pik_share_income_mdna": 0.107, "pik_usd_q": 31.6e6, "total_investment_income_q": 401.3e6, "shares_out": 493.1e6,
        "portfolio_fv": 14.96e9, "companies": 229, "debt_principal": 8.02e9, "net_debt_to_equity": 1.11, "first_lien_share": 0.732,
        "software_share_mgmt": 0.18, "software_share_prior_q": 0.16, "software_alleged_economic": (0.20, 0.30),
        "net_realized_unrealized_loss_q": 110.4e6, "net_increase_from_operations_q": 65.7e6, "repurchased_q_usd": 35e6,
        "buyback_prices": [("2026-03", 11.20), ("2026-05", 11.20), ("2026-06", 11.04)],
        "largest_non_accruals": [("National Dentex Labs", "healthcare", 167.0e6, 76.9e6), ("Loparex Midco", "industrial", 135.3e6, 8.3e6),
                                 ("Feradyne Outdoors", "consumer", 78.2e6, 34.7e6), ("Pluralsight", "software", 25.7e6, 2.3e6)],
    },
    "ocic": {  # the flagship non-traded fund
        "name": "Blue Owl Credit Income Corp. (OCIC)", "asof": "2026-09-30", "reported": "2026-10-26", "src": ["tender", "requests", "cox"],
        "requests_share": 0.168, "requests_share_prior": 0.188, "requests_usd": 3.1e9, "shares_tendered": 341.4e6, "shares_bought": 101.6e6, "paid_usd": 931.1e6,
        "fill_reported": 0.298, "fill_history": [("2026-03-31", 0.228), ("2026-06-30", 0.266), ("2026-09-30", 0.298)],
        "nav_ps": 9.17, "nav_total": 18e9, "investments_fv": 35.1e9, "companies": 328, "net_leverage": 0.91, "liquidity": 11.9e9,
        "paid_with": "non-interest-bearing promissory notes", "third_party_tender_price": 7.31, "third_party_nav_ref": 9.14, "third_party_nav_ref_date": "2026-08-31",
    },
    "otic": {  # the technology fund
        "name": "Blue Owl Technology Income Corp. (OTIC)", "asof": "2026-09-30", "reported": "2026-10-26", "src": ["tender", "requests"],
        "requests_share": 0.39, "requests_share_prior": 0.381, "requests_usd": 1.1e9, "shares_tendered": 108.6e6, "shares_bought": 13.9e6, "paid_usd": 137.2e6,
        "fill_reported": 0.128, "nav_ps": 9.85, "nav_ps_prior_year_end": 10.38, "portfolio_fv": 5e9, "net_leverage": 0.86, "liquidity": 1.2e9,
        "paid_with": "non-interest-bearing promissory notes",
    },
    "fitch": {  # the sector
        "name": "Fitch US private credit default rate (PCDR), trailing twelve months", "asof": "2026-09-30", "reported": "2026-10-29", "src": ["fitch", "fitch2"],
        "pcdr": 0.063, "pcdr_prior_q": 0.060, "record": True, "events_q": 27, "index_start": "2024-08", "rises": "every quarter since 3Q25 (5.6%, 5.7%, 6.0%, 6.3%)", "unique_defaulters_ttm": 91,
        "soft_share": 0.88, "mix": {"pik_or_deferral": 0.50, "maturity_extension": 0.38, "payment_default": 0.08, "bankruptcy_or_restructuring": 0.04},
        "sector": {"Technology software": 0.006, "Healthcare providers": 0.087, "Industrials and manufacturing": 0.097, "Consumer products and services": 0.097},
        "sector_prior": {"Technology software": 0.012, "Healthcare providers": 0.094},
        "moodys_mm_clo_default_12m_to_jun26": 0.04, "moodys_incl_distressed_exchanges": 0.058, "ccc_share_of_2027_28_maturities": "more than half",
    },
    "hyperion": {  # the template deal
        "name": "Meta Hyperion campus joint venture (Louisiana)", "asof": "2025-10-21", "src": ["hyperion"],
        "debt_usd": 27.3e9, "development_cost_usd": 27e9, "capital_raised_usd": 30e9, "blue_owl_share": 0.80, "blue_owl_cash_usd": 7e9, "meta_distribution_usd": 3e9, "initial_lease_years": 4, "residual_guarantee_years": 16, "ltv": None, "dscr": None, "dscr_unofficial": 1.12,
        "lender": "PIMCO and other bond investors, Morgan Stanley bookrunner",
    },
}


# ---------------------------------------------------------------- 1. liquidity
def queue(requests_share: float, cap: float = CAP) -> dict:
    """A pro-rata tender: the fill rate, and how long a holder who keeps asking takes to get 90% out if the queue
    stays the same size. (1 - fill)^n of the position remains after n quarters."""
    fill = 1.0 if requests_share <= cap else cap / requests_share
    q90 = 0.0 if fill >= 1 else math.log(0.10) / math.log(1 - fill)
    return {"requests_share": requests_share, "cap": cap, "fill": fill, "quarters_to_90pct_exit": q90, "years_to_90pct_exit": q90 / 4,
            "left_after_4_quarters": (1 - fill) ** 4}


def queue_check(fund: dict) -> dict:
    """The model's fill rate against the fund's reported one: the model is right if they agree within a point."""
    q = queue(fund["requests_share"])
    q["fill_reported"] = fund["fill_reported"]
    q["model_matches"] = abs(q["fill"] - fund["fill_reported"]) < 0.01
    return q


# ---------------------------------------------------------------- 2. marks
def implied_markdown(price_to_nav: float, debt_to_equity: float, non_accrual_fv: float | None = None) -> dict:
    """The asset-level markdown a listed BDC's equity discount implies: equity E, debt D, assets A = E + D; the
    market's equity E' = (1 - d) E; if the debt is whole, A' = A - d E, a markdown of d E / A = d / (1 + D/E)."""
    d = 1 - price_to_nav
    md = d / (1 + debt_to_equity)
    out = {"price_to_nav": price_to_nav, "equity_discount": d, "debt_to_equity": debt_to_equity, "implied_asset_markdown": md}
    if non_accrual_fv is not None and non_accrual_fv > 0:
        out["multiple_of_non_accruals_fv"] = md / non_accrual_fv
    return out


def obdc_price_to_nav(o: dict = OBS["obdc"]) -> dict:
    """OBDC's own buyback prices against its quarter-end NAV: the only dated prices in the record (no live quote)."""
    p = o["buyback_prices"][-1][1]
    return {"price": p, "price_month": o["buyback_prices"][-1][0], "nav_ps": o["nav_ps"], "price_to_nav": p / o["nav_ps"], "basis": "the fund's own June 2026 repurchases against June 30 NAV"}


# ---------------------------------------------------------------- 3. income quality
def dividend_cover(o: dict = OBS["obdc"]) -> dict:
    """NII against the declared dividend, and cash cover with PIK taken out: (NII x shares - PIK) / shares, over the
    dividend, on the June 30 share count. Approximate, since PIK accrued is not all of the non-cash income."""
    div = o["dividend_base"] + o["dividend_supplemental"]
    shares_est = o["shares_out"]
    nii_usd_est = o["nii_ps"] * shares_est
    cash_nii_ps_est = (nii_usd_est - o["pik_usd_q"]) / shares_est
    return {"nii_ps": o["nii_ps"], "dividend": div, "cover": o["nii_ps"] / div, "dividend_cut": o["dividend_base"] / o["dividend_base_prior"] - 1,
            "pik_share_income": o["pik_share_income_q"], "shares_est": shares_est, "cash_nii_ps_est": cash_nii_ps_est, "cash_cover_est": cash_nii_ps_est / div,
            "nav_change_since_2024": o["nav_ps"] / o["nav_history"][0][1] - 1}


def loss_gap(owl: dict = OBS["owl"], fitch: dict = OBS["fitch"], severity: float = 0.40) -> dict:
    """Both numbers are true: the manager's realized losses (12 bp) and the sector's record default rate (6.3%).
    Hard defaults are the 12% of Fitch's events that are payment defaults or bankruptcies; applying that event share to
    the issuer rate (an approximation) and a 40% loss severity, they cost about 30 bp a year. The other 88% (PIK, deferrals, extensions) produce no realized loss until they do."""
    hard = fitch["pcdr"] * (fitch["mix"]["payment_default"] + fitch["mix"]["bankruptcy_or_restructuring"])
    return {"realized_loss_manager": owl["direct_lending_realized_loss_ann"], "pcdr": fitch["pcdr"], "hard_default_rate": hard,
            "hard_loss_at_severity": hard * severity, "severity": severity, "soft_share": fitch["soft_share"],
            "ratio_pcdr_to_realized": fitch["pcdr"] / owl["direct_lending_realized_loss_ann"]}


RATES = {"bill3m": 0.0422, "y10": 0.0500, "asof": "2026-10-23", "src": "US Treasury daily par yield curve (site LEVELS)"}


def net_yield_at_sector_default(default_rate: float | None = None, recovery: float = 0.5) -> dict:
    """The page's unlevered direct-lending fund (base 3.9%, spread 5.5%, 1.25% and 12.5% fees) at the sector's default
    rate, against the dated 3-month bill (the floating-rate comparison) and the dated 10-year."""
    d = OBS["fitch"]["pcdr"] if default_rate is None else default_rate
    r = accounting.credit_stress(0.039, 0.055, d, recovery, treasury=RATES["y10"])
    r["over_bill3m"] = r["net"] - RATES["bill3m"]
    r["over_y10"] = r.pop("over_treasury")
    r["default_rate"], r["recovery"], r["rates"] = d, recovery, RATES
    return r


def fre_from_undeployed(owl: dict = OBS["owl"]) -> dict:
    """Management's $400M of annual fees from $36B not yet fee-paying, against today's run-rate FRE."""
    run = owl["fre_q"] * 4
    return {"fre_run_rate": run, "fees_from_undeployed": owl["fees_expected_from_undeployed"], "uplift": owl["fees_expected_from_undeployed"] / run,
            "implied_fee_rate": owl["fees_expected_from_undeployed"] / owl["aum_not_yet_fee_paying"]}


def jv_cushion(hy: dict = OBS["hyperion"]) -> dict:
    """The template deal's structure as disclosed. Loan to value and debt service cover were not disclosed (a private
    offering); debt is about the size of the development cost, so the debt is underwritten on Meta's lease and residual
    value guarantee, not on a cushion of equity value."""
    return {"debt_usd": hy["debt_usd"], "development_cost_usd": hy["development_cost_usd"], "capital_raised_usd": hy["capital_raised_usd"],
            "debt_to_cost": hy["debt_usd"] / hy["development_cost_usd"], "ltv_disclosed": False, "dscr_unofficial": hy["dscr_unofficial"]}


# ---------------------------------------------------------------- the cohort
def cohort() -> dict:
    """Every fund through the same queue model; requests inferred as cap / fill where only the fill was reported; the
    inversion checked against two funds that reported both; the listed peers' marks and dividend cover."""
    rows = []
    for f in COHORT_QUEUES:
        req = f["requests"] if f["requests"] is not None else (CAP / f["fill"] if f["fill"] and f["fill"] < 1 else None)
        fill = f["fill"] if f["fill"] is not None else (CAP / req if req and req > CAP else 1.0)
        q = queue(req) if req is not None else None
        rows.append({**f, "requests": req, "fill": fill, "quarters_to_90pct_exit": q["quarters_to_90pct_exit"] if q else 0.0, "queued": bool(req and req > CAP)})
    rows.sort(key=lambda r: -(r["requests"] or 0))
    checks = [{**c, "requests_model": CAP / c["fill"], "matches": abs(CAP / c["fill"] - c["requests_reported"]) < 0.005} for c in COHORT_CHECKS]
    listed = []
    for f in COHORT_LISTED:
        base = f.get("nav_ps_year_end") or f.get("nav_ps_prior_q")
        listed.append({**f, "nav_change": (f["nav_ps"] / base - 1) if base else None, "nav_change_basis": "since year-end" if f.get("nav_ps_year_end") else "on the quarter",
                       "cover": (f["earnings_ps"] / f["dividend_ps"]) if f.get("earnings_ps") and f.get("dividend_ps") else None,
                       "implied_markdown": implied_markdown(f["price_to_nav"], f["debt_to_equity"])["implied_asset_markdown"] if f.get("price_to_nav") else None})
    queued = [r for r in rows if r["queued"]]
    owl = [r for r in queued if r["sponsor"] == "Blue Owl"]
    others = [r for r in queued if r["sponsor"] != "Blue Owl"]
    return {"queues": rows, "checks": checks, "sector": COHORT_SECTOR, "listed": listed,
            "read": {"blue_owl_max_requests": max(r["requests"] for r in owl), "peers_max_requests": max(r["requests"] for r in others), "peers_range": [min(r["requests"] for r in others), max(r["requests"] for r in others)],
                     "non_accrual_cost_range": [min(x["non_accrual_cost"] for x in listed), max(x["non_accrual_cost"] for x in listed)],
                     "peers_cover_below_1": [x["fund"] for x in listed if x["cover"] is not None and x["cover"] < 1]}}


# ---------------------------------------------------------------- the scorecard
GAUGES = [  # id, label, read, unit, green, red (direction: "low" means lower is better)
    ("ocic_queue", "OCIC repurchase requests, share of shares", lambda: OBS["ocic"]["requests_share"], "pct", 0.05, 0.15, "low", "Above 15%: widen the haircut on every private mark (Buyside rule)."),
    ("otic_queue", "OTIC repurchase requests, share of shares", lambda: OBS["otic"]["requests_share"], "pct", 0.05, 0.15, "low", "A queue this size is a run in slow motion: 12.8% out a quarter."),
    ("obdc_discount", "OBDC price to NAV (June buybacks)", lambda: obdc_price_to_nav()["price_to_nav"], "ratio", 0.95, 0.85, "high", "Below 0.85: the market marks the loans a tenth lower than the fund does."),
    ("obdc_na", "OBDC non-accruals at cost", lambda: OBS["obdc"]["non_accrual_cost"], "pct", 0.02, 0.04, "low", "Above 4%: the booked stress catches up with the market's."),
    ("obdc_pik", "OBDC PIK share of income", lambda: OBS["obdc"]["pik_share_income_q"], "pct", 0.08, 0.15, "low", "Above 15%: the dividend is paid in loans, not cash."),
    ("obdc_cover", "OBDC NII cover of the dividend", lambda: dividend_cover()["cover"], "x", 1.10, 1.00, "high", "Below 1.0: a second cut follows the first."),
    ("pcdr", "Fitch private credit default rate", lambda: OBS["fitch"]["pcdr"], "pct", 0.03, 0.05, "low", "Below 3% is the thesis's kill condition; above 5% the losses are sector-wide."),
    ("software", "Fitch software default rate", lambda: OBS["fitch"]["sector"]["Technology software"], "pct", 0.02, 0.05, "low", "The market's fear is software; the defaults are in industrials, consumer and healthcare."),
]


def grade(v: float, green: float, red: float, direction: str) -> str:
    if direction == "low":
        return "green" if v <= green else "red" if v >= red else "amber"
    return "green" if v >= green else "red" if v <= red else "amber"


def scorecard() -> list[dict]:
    rows = []
    for gid, label, fn, unit, green, red, direction, note in GAUGES:
        v = fn()
        rows.append({"id": gid, "label": label, "value": v, "unit": unit, "green": green, "red": red, "direction": direction, "grade": grade(v, green, red, direction), "note": note})
    return rows


# ---------------------------------------------------------------- the book
TRANSMISSION = [  # name, channel, exposure, watch
    ("META", "Lessee of the Hyperion campus: Blue Owl funds own 80% of a joint venture that sold about $27.3B of bonds against about $27B of development cost; Meta has a four-year initial lease with extensions and guarantees the residual value for 16 years.", "direct",
     "Whether the next campus is financed the same way or on Meta's balance sheet (on Oct 26 it also launched about $35B of equity for AI infrastructure)."),
    ("MSFT", "Named by Blue Owl's CFO as a tenant whose credit the data-center funds carry; investment-grade lessee.", "direct", "Lease terms and residual guarantees in Blue Owl's net-lease disclosures."),
    ("AMZN", "Named by Blue Owl's CFO as a tenant whose credit the data-center funds carry; investment-grade lessee.", "direct", "Same."),
    ("SPCX", "Chip financing: Blue Owl did GPU deals with SpaceX (originally xAI); an Apollo-managed entity is lessor on a $40B GPU finance lease, co-led with Goldman Sachs (Oct 26; thesis t1).", "direct", "The lease rate on the next chip financing; a gated wealth channel raises it."),
    ("NVDA", "Its GPUs are the collateral in chip leases; a lessor's loss is a residual-value loss on NVDA hardware.", "indirect", "Secondary GPU prices and lease residuals in lessor filings."),
    ("ORCL", "Blue Owl, Crusoe and Primary Digital formed the $15B joint venture that owns the Abilene, Texas campus leased to Oracle; Blue Owl walked away from financing Oracle's Michigan site in Dec 2025. Oracle came up on the Q3 call only in an analyst's question.", "direct", "Oracle's own lease commitments in its 10-Q."),
    ("GOOGL", "No direct Blue Owl channel found; Alphabet funds capex from cash flow and bonds (February and August 2026 issues).", "none", "Nothing specific; the sector channel only."),
    ("AVGO", "No direct channel; sells into the campuses the funds finance.", "indirect", "Hyperscaler capex guidance."),
    ("TSLA", "No direct channel.", "none", "Nothing specific."),
]

CHAIN = [
    "Wealth-channel holders queue to leave (OCIC 16.8%, OTIC 39% of shares a quarter) and are paid 5% a quarter in promissory notes.",
    "A manager with a queue raises less new equity through that channel (OWL's wealth raise was $11B over twelve months against $49B in total).",
    "Less fund equity means the next campus or chip lease is financed on the tenant's own balance sheet, or at a higher lease rate.",
    "Tenants issue more bonds and equity (Meta's $35B raise, Oct 26): the lane where long bonds stop hedging the book (thesis t2), measured below as the engine's financing-shock scenario.",
]

FLIPS = [  # what moves the lens, in each direction
    {"direction": "worse", "trigger": "OCIC requests above 25% of shares, or a tender suspended or paid below NAV", "now": "16.8%, falling two quarters; paid at NAV in notes"},
    {"direction": "worse", "trigger": "OBDC non-accruals above 4% at cost, or PIK above 15% of income", "now": "2.8% at cost; PIK 10.7%"},
    {"direction": "worse", "trigger": "A Blue Owl data-center vehicle's bonds below 90 cents, or a tenant exercising a lease break", "now": "no such print found; Hyperion bonds placed privately"},
    {"direction": "better", "trigger": "OCIC and OTIC requests back under the 5% cap (no queue)", "now": "16.8% and 39%"},
    {"direction": "better", "trigger": "Fitch's default rate below 3% (the thesis's kill condition)", "now": "6.3%, the highest since Fitch's index began in Aug 2024, up every quarter since 3Q25"},
    {"direction": "better", "trigger": "OBDC within 5% of NAV", "now": "about 77% of NAV on June buybacks"},
]

CATALYSTS = [
    ("2026-11-03", "Apollo Q3 2026 results: the first asset-level marks after the October credit scare", "Apollo's press release, Nov 3"),
    ("2026-11-04", "OBDC Q3 2026 results: NAV, non-accruals, PIK, buyback prices", "OBDC 8-K"),
    ("2027-01-15", "Blue Owl Q4 tender results for OCIC and OTIC: requests against the 5% cap", "Fund 8-Ks, early to mid January"),
    ("2027-01-31", "Fitch 4Q26 private credit monitor: whether 6.3% was the peak", "Fitch, late January"),
]


# ---------------------------------------------------------------- the report
def report(today: str | None = None) -> dict:
    today = today or date.today().isoformat()
    oc, ot, ob, fi, ow = OBS["ocic"], OBS["otic"], OBS["obdc"], OBS["fitch"], OBS["owl"]
    p2n = obdc_price_to_nav()
    md = implied_markdown(p2n["price_to_nav"], ob["net_debt_to_equity"], ob["non_accrual_fv"])
    cov = dividend_cover()
    sc = scorecard()
    reds = [r for r in sc if r["grade"] == "red"]
    headline = (f"Blue Owl's wealth funds are in a slow run (OCIC {oc['requests_share']:.1%} and OTIC {ot['requests_share']:.0%} of shares asked out last quarter, "
                f"paid 5% a quarter in notes), its listed BDC bought back its own shares about {1 - p2n['price_to_nav']:.0%} below NAV in June (an asset markdown near {md['implied_asset_markdown']:.0%}, "
                f"{md['multiple_of_non_accruals_fv']:.0f} times the non-accruals it books), and the sector's default rate is a record {fi['pcdr']:.1%}. "
                f"The manager's fee earnings are up {ow['fre_q'] / ow['fre_q_prior_year'] - 1:.0%} (${ow['fre_q'] / 1e6:.0f}M in Q3) while the holders of its funds queue to leave. "
                f"For the book this is a financing lens, not a position: watch it, do not own it.")
    return {
        "asof": today, "latest_observation": max(o["asof"] for o in OBS.values()), "headline": headline,
        "stack": {"manager": ow, "listed_bdc": ob, "flagship_fund": oc, "technology_fund": ot, "sector": fi, "template_deal": OBS["hyperion"]},
        "liquidity": {"ocic": queue_check(oc), "otic": queue_check(ot), "cap": CAP, "third_party_tender_discount": 1 - oc["third_party_tender_price"] / oc["third_party_nav_ref"]},
        "marks": {"obdc": {**p2n, **md}, "otic_nav_change_ytd": ot["nav_ps"] / ot["nav_ps_prior_year_end"] - 1},
        "income": cov, "loss_gap": loss_gap(), "net_yield": net_yield_at_sector_default(), "manager": fre_from_undeployed(), "template": jv_cushion(),
        "sector": {"pcdr": fi["pcdr"], "prior": fi["pcdr_prior_q"], "events_q": fi["events_q"], "index_start": fi["index_start"], "rises": fi["rises"], "soft_share": fi["soft_share"], "mix": fi["mix"], "by_sector": fi["sector"], "by_sector_prior": fi["sector_prior"]},
        "cohort": cohort(), "scorecard": sc, "reds": len(reds), "transmission": [dict(zip(("name", "channel", "exposure", "watch"), t)) for t in TRANSMISSION], "chain": CHAIN, "flips": FLIPS,
        "catalysts": [dict(zip(("date", "event", "source"), c)) for c in CATALYSTS],
        "sources": {k: {"title": v[0], "url": v[1]} for k, v in SRC.items()},
        "limitations": ["OBDC's price is the fund's own June repurchase average; no live quote reaches the engine (the price mirror carries no BDC or alternative-manager tickers).",
                        "Cash cover takes PIK interest out of NII; other non-cash income (PIK dividends, accretion) is not removed, so cover is if anything lower.",
                        "OWL management's 12 bp realized-loss figure and Fitch's 6.3% default rate measure different things; the loss gap reconciles them by construction, not by audit.",
                        "The queue model assumes the queue stays its current size; requests have fallen two quarters at OCIC and risen at OTIC.",
                        "Hyperion's loan to value and debt service cover were not disclosed by Meta (a private bond offering); at the Brookings session the paper's author put them at roughly 90% and about 1.15x, and an unofficial reconstruction of the rating agency's pre-sale near 1.12x.", "OBDC's June buyback price is the only verified price; a secondary source puts its Oct 16 close near $10.23, about 72% of June NAV.",
                        "In the cohort, HPS's and Ares's request shares are inferred from their reported fills (cap divided by fill); the inversion is checked on two funds that reported both. The listed peers' prices are not verified, so their discounts are not shown."],
    }


def summary(r: dict) -> list[str]:
    L, M, I, G, C = r["liquidity"], r["marks"]["obdc"], r["income"], r["loss_gap"], r["cohort"]
    return [
        r["headline"],
        f"The 5% cap divided by the queue gives the fill rate: {L['ocic']['fill']:.1%} at OCIC (reported {L['ocic']['fill_reported']:.1%}), {L['otic']['fill']:.1%} at OTIC (reported {L['otic']['fill_reported']:.1%}). A holder who keeps asking has 90% out in {L['ocic']['quarters_to_90pct_exit']:.1f} quarters at OCIC and {L['otic']['quarters_to_90pct_exit']:.1f} at OTIC.",
        f"OBDC's June buybacks at {M['price_to_nav']:.0%} of NAV, with {M['debt_to_equity']:.2f}x debt to equity implies an asset markdown of {M['implied_asset_markdown']:.1%}, against {OBS['obdc']['non_accrual_fv']:.1%} of the portfolio on non-accrual at fair value.",
        f"NII covers the dividend {I['cover']:.2f} times; with PIK ({I['pik_share_income']:.1%} of total investment income) taken out the cash cover is about {I['cash_cover_est']:.2f}. The base dividend was cut {-I['dividend_cut']:.0%} and NAV is {-I['nav_change_since_2024']:.1%} below its end-2024 level.",
        f"Fitch's record {G['pcdr']:.1%} default rate is {G['soft_share']:.0%} soft restructurings; the hard defaults cost about {G['hard_loss_at_severity'] * 1e4:.0f} bp a year at an assumed {G['severity']:.0%} severity, the same order as the {G['realized_loss_manager'] * 1e4:.0f} bp of realized losses Blue Owl reports in the same market.",
        f"Fitch's software default rate is {r['sector']['by_sector']['Technology software']:.1%}, the lowest sector; industrials and consumer run {r['sector']['by_sector']['Industrials and manufacturing']:.1%}. Three of OBDC's four largest non-accruals are a dental lab, a films maker and an outdoor-goods company, not software.",
        f"The cohort: Blue Owl is the outlier on the queue (OTIC {C['read']['blue_owl_max_requests']:.0%} of shares against {C['read']['peers_range'][0]:.0%} to {C['read']['peers_range'][1]:.0%} at Apollo, HPS, Ares and Blackstone, and no queue at Goldman or Golub), the sector on marks (non-accruals {C['read']['non_accrual_cost_range'][0]:.1%} to {C['read']['non_accrual_cost_range'][1]:.1%} of cost across the peers), and the first listed fund in the cohort to cut its dividend: Ares Capital and Blackstone Secured Lending earn less than their dividends and have not cut (BCRED, non-traded, has cut twice).",
    ]
