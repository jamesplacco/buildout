"""The book, sized and measured (v0.30): the nine names' own daily prices run through the engine's risk analytics.

Every other desk sizes the S&P 500 or the Nasdaq-100; this one measures the book that is actually held. Inputs are
the names' daily closes, volumes and cash dividends (the yennanliu/finance_data mirror on GitHub, prices already
split-adjusted, dividends on their ex-dates), three external factors (the Nasdaq-100 through QQQ, semiconductors
through SOXX in excess of QQQ, rates through a 20-year par bond built from the Treasury's daily par yields) and the
model weights. Nothing here is fitted on the book's own composite, so the factor exposures are measured, not defined.

What comes out:
  * exposures: each name's betas to market, semis and rates (exponentially weighted, half-life 126 days; SPCX, with
    a few months of history, shrinks toward TSLA), and the book's;
  * risk: ex-ante volatility from the factor model and from the names' own covariance, the variance split into
    market, semis, rates and stock-specific parts, risk contributions, effective independent bets (Meucci),
    diversification ratio;
  * tail: one-month expected shortfall at 95% (the page's budget definition) and 97.5% (the Basel standard) by
    historical simulation of today's weights, filtered historical simulation (today's volatility, history's shapes)
    and a Student-t at today's ex-ante volatility; one-day 99% VaR backtested on the book (Kupiec);
  * size: the exposure each limit allows (expected-shortfall budget, volatility target, drawdown cap), the binding
    limit, and the Nasdaq-100 hedge that would keep the names at full size inside the budget;
  * hedges tested out of sample on the book's own days: Nasdaq-100 short at the walked-forward beta, Nasdaq-100 plus
    semis, the long bond only when its correlation says it hedges, and a static 30% long bond (the page's TLT 0.3x);
  * stress: the engine's episodes replayed on the names' own returns, the engine's scenarios through the measured
    betas, worst days with what the long bond did, stock-bond correlation under one stated definition;
  * liquidity: days to sell each position at 20% of its 20-day average dollar volume, at $100m and at $1bn of NAV.

Derived numbers only leave this module; prices stay in the run's cache.
"""
from __future__ import annotations

import io
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from . import sizing_rules
from .analytics import exposures, regime, risk, sizing, stress
from .analytics.bonds import constant_maturity_returns, duration_convexity

ROOT = Path(__file__).resolve().parent
TREASURY = ROOT.parent / ".cache" / "book" / "treasury_par_daily.json"   # raw data: cached, never committed
MIRROR = "https://raw.githubusercontent.com/yennanliu/finance_data/main/data/prices/{}.csv"
MIRROR_REPO = "https://github.com/yennanliu/finance_data"

BOOK = {"MSFT": 0.14, "AMZN": 0.14, "GOOGL": 0.14, "NVDA": 0.14, "META": 0.12, "TSLA": 0.10, "AVGO": 0.08,
        "SPCX": 0.08, "ORCL": 0.06}
FILE = {"GOOGL": "goog"}               # the mirror carries GOOG (class C), which trades within a fraction of GOOGL
FACTOR_ETF = {"QQQ": "qqq", "SOXX": "soxx", "VTI": "vti"}
FACTORS = ["market", "semis", "rates"]
FACTOR_NAME = {"market": "Nasdaq-100 (QQQ)", "semis": "Semiconductors net of the Nasdaq-100 (SOXX less its walked-forward beta times QQQ)",
               "rates": "20-year Treasury par bond (daily par yields)"}
PRIORS = {"SPCX": "TSLA"}              # config.toml [universe.priors]

NAV_USD = 100e6                        # the page's model NAV
ES_BUDGET = 0.12                       # one-month expected shortfall at 95%, the Desk's budget
VOL_TARGET = 0.20                      # config.toml [risk] target_vol
MAX_DD = 0.25                          # config.toml [risk] max_drawdown, 95th percentile over a year
MAX_GROSS = 1.50                       # config.toml [risk] max_gross
BETA_HL, COV_HL = 126, 63              # config.toml [risk] beta_halflife, corr_halflife
EWMA_LAMBDA = 0.94                     # RiskMetrics daily decay for the filtered simulation and the VaR backtest
HORIZON = 21                           # trading days in a month
T_NU = 5.0                             # Student-t degrees of freedom for the parametric tail (an assumption)
EQUITY_PREMIUM = 0.05                  # drift for the drawdown cap: cash plus 5% a year per unit of S&P beta
ADV_SHARE = 0.20                       # sell no more than this share of a day's volume
STATIC_BOND = 0.30                     # the page's standing TLT 0.3x
LIMITATIONS = [
    "Today's weights applied to history: the record is what this book would have done, not what anyone held.",
    "GOOG (class C) stands in for GOOGL; the two trade within a fraction of a percent of each other.",
    "SPCX has traded since June 12, 2026. Before that its weight is spread over the other names pro rata, and its "
    "betas lean on TSLA's until it has two years of its own.",
    "The rates factor is a 20-year par bond rebuilt from the Treasury's daily par yields, a TLT proxy with duration "
    "about 12 against TLT's 16. Cash is proxied by the 2-year yield (older Treasury files here carry 2, 10 and 20 "
    "years only). That overstates what idle cash earned when the curve was steep (2021 and 2022) and understates it "
    "when the curve was inverted (2023 and 2024); a bill rate is the right series and is not in use yet.",
    "The drawdown cap is read from a constant-volatility simulation (geometric Brownian motion, 4,000 paths) at an "
    "assumed drift. It has no volatility clustering, no jumps and no change in correlation, so the 25% is a modelled "
    "95th percentile under those assumptions and not a stop: a real drawdown at that size can be deeper. From "
    "v0.44 the page shows the size under fat tails, the book's own days in runs, volatility that moves, no equity "
    "premium and higher volatility (sensitivity.py), and whether the cap held in the walk-forward. The call still "
    "uses the constant-volatility number.",
    "The menu's rows are at or inside each limit exactly, in 5% steps of the short. The exact minimum short is "
    "reported beside the logged row; the logged row is the decision.",
    "Hedge legs are measured as futures: their returns are in excess of cash. No transaction costs, no margin, no borrow.",
    "Ten years of daily data hold one bear market (2022) and two fast crashes (2020, 2025); the tail numbers are "
    "only as wide as that record, which is why the most cautious of three methods governs.",
]


# ---------------------------------------------------------------- data
TREASURY_CSV = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
                "?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")


TREASURY_MAX_AGE = 86400.0             # seconds: a cache file older than a day is refreshed (v0.47)
TREASURY_STATUS: dict = {}             # how the last treasury() call got its data: {"source", "error"}


def _read_treasury(path: Path) -> pd.DataFrame:
    o = json.loads(path.read_text())
    return pd.DataFrame({k: o[k] for k in o["series"]}, index=pd.to_datetime(o["dates"])).astype(float)


def treasury(path: Path = TREASURY, start_year: int = 2017, max_age: float = TREASURY_MAX_AGE) -> pd.DataFrame:
    """The Treasury's daily par yields (2, 10 and 20 years, percent), from a local cache file (git-ignored: raw data
    stays out of the repository) that is downloaded year by year from home.treasury.gov.

    v0.47: a cache older than `max_age` seconds is refreshed (the years from its last one on are downloaded again
    and merged). Before, a file that existed was never read again from the source, so a machine that had run once
    sized every later day on yields frozen at that first run. If the refresh fails the old file is used and
    TREASURY_STATUS says so; build() then stops if the file is too far behind the prices."""
    path = Path(path)
    have = _read_treasury(path) if path.exists() else None
    TREASURY_STATUS.clear()
    TREASURY_STATUS.update({"source": "cache", "error": None})
    stale = have is None or (pd.Timestamp.now().timestamp() - path.stat().st_mtime) > max_age
    if stale:
        try:
            from .data import http
            first = start_year if have is None else int(have.index[-1].year)
            frames = [] if have is None else [have[have.index.year < first]]
            for y in range(first, pd.Timestamp.now().year + 1):
                d = pd.read_csv(io.StringIO(http.get(TREASURY_CSV.format(y=y), timeout=45).decode()))
                d["Date"] = pd.to_datetime(d["Date"])
                frames.append(d.set_index("Date")[["2 Yr", "10 Yr", "20 Yr"]].rename(columns={"2 Yr": "DGS2", "10 Yr": "DGS10", "20 Yr": "DGS20"}).astype(float))
            f = pd.concat(frames).sort_index()
            f = f[~f.index.duplicated(keep="last")].astype(float)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"source": "US Treasury, daily par yield curve rates (home.treasury.gov); percent", "series": list(f.columns),
                                        "from": str(f.index[0].date()), "to": str(f.index[-1].date()), "dates": [str(d.date()) for d in f.index],
                                        **{c: [round(float(v), 4) for v in f[c]] for c in f.columns}}))
            TREASURY_STATUS["source"] = "download"
        except Exception as exc:  # noqa: BLE001 - with a file in hand the run goes on and says so; with none it cannot
            if have is None:
                raise
            TREASURY_STATUS["error"] = f"refresh failed, using the file to {have.index[-1].date()}: {type(exc).__name__}: {exc}"[:240]
    return _read_treasury(path)


def _frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.drop_duplicates("date", keep="last").set_index("date").sort_index()


def total_returns(df: pd.DataFrame) -> pd.Series:
    """Close to close plus the cash dividend on its ex-date. Prices on the mirror are split-adjusted already."""
    f = _frame(df)
    div = f["div"].fillna(0.0) if "div" in f else 0.0
    return ((f["close"] + div) / f["close"].shift(1) - 1).iloc[1:]


def bond_returns(ust: pd.DataFrame, dates: pd.DatetimeIndex, col: str = "DGS20", maturity: float = 20.0) -> pd.Series:
    """The par bond's daily total return, carried onto the equity calendar: on a day the bond market is shut and
    stocks trade (Columbus Day, Veterans Day) the bond return is zero and the next open day carries the move."""
    r = constant_maturity_returns(ust[col], maturity=maturity).dropna()
    idx = (1 + r).cumprod()
    on = idx.reindex(idx.index.union(dates)).ffill().reindex(dates)
    return on.pct_change().rename("rates")


def cash_returns(ust: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    y = ust["DGS2"].reindex(ust.index.union(dates)).ffill().reindex(dates) / 100
    days = pd.Series(dates, index=dates).diff().dt.days.fillna(1)
    return (y.shift(1) * days / 365.0).rename("cash")


def semis_factor(soxx: pd.Series, qqq: pd.Series, halflife: int = BETA_HL) -> pd.Series:
    """Semiconductors net of the market: SOXX less its beta to QQQ times QQQ, the beta measured through the day
    before (semis run at about twice the Nasdaq-100's beta, so SOXX less QQQ alone would still carry the market)."""
    b = (soxx.ewm(halflife=halflife, min_periods=63).cov(qqq) / qqq.ewm(halflife=halflife, min_periods=63).var()).shift(1)
    return (soxx - b * qqq).rename("semis")


def panel(prices: dict[str, pd.DataFrame], ust: pd.DataFrame, book: dict[str, float] = BOOK) -> dict:
    """Daily returns of the names and the factors on the equity calendar, from the first day the bond series exists."""
    names = {k: total_returns(prices[FILE.get(k, k.lower())]) for k in book}
    etf = {k: total_returns(prices[v]) for k, v in FACTOR_ETF.items()}
    cal = etf["QQQ"].index
    cal = cal[cal > ust.index[0]]
    R = pd.DataFrame(names).reindex(cal)
    bond = bond_returns(ust, cal)
    cash = cash_returns(ust, cal)
    E = pd.DataFrame(etf).reindex(cal)
    F = pd.DataFrame({"market": E["QQQ"], "semis": semis_factor(E["SOXX"], E["QQQ"]), "rates": bond}, index=cal)
    first = {k: str(R[k].first_valid_index().date()) for k in R}
    last = {k: str(R[k].last_valid_index().date()) for k in R}
    vol = {k: _frame(prices[FILE.get(k, k.lower())])[["close", "volume"]] for k in book}
    return {"R": R, "F": F, "E": E, "cash": cash, "bond": bond, "first": first, "last": last, "vol": vol}


# ---------------------------------------------------------------- book returns
def book_returns(R: pd.DataFrame, w: pd.Series) -> pd.Series:
    """Today's weights, rebalanced daily; a name without a price that day (before its listing) has its weight spread
    over the others pro rata, so every day's book is fully invested and the same mix where data allows."""
    w = w.reindex(R.columns).fillna(0.0)
    have = R.notna()
    wt = have.mul(w, axis=1)
    wt = wt.mul(w.sum() / wt.sum(axis=1).replace(0, np.nan), axis=0)
    return (R.fillna(0.0) * wt).sum(axis=1, min_count=1).where(have.any(axis=1)).rename("book")


def horizon_returns(r: pd.Series, h: int = HORIZON) -> pd.Series:
    """Overlapping compounded h-day returns."""
    lr = np.log1p(r.dropna())
    return np.expm1(lr.rolling(h).sum()).dropna()


def es(x: pd.Series | np.ndarray, alpha: float) -> float:
    """Expected shortfall as a positive loss: the mean of the worst alpha share of outcomes."""
    a = np.sort(np.asarray(x, dtype=float)[np.isfinite(x)])
    k = max(int(math.floor(alpha * len(a))), 1)
    return float(-a[:k].mean())


def var(x: pd.Series | np.ndarray, alpha: float) -> float:
    a = np.asarray(x, dtype=float)
    return float(-np.quantile(a[np.isfinite(a)], alpha))


def t_es(sigma: float, alpha: float, nu: float = T_NU) -> float:
    """ES of a Student-t scaled to standard deviation sigma (McNeil, Frey and Embrechts 2015, eq. 2.23)."""
    q = stats.t.ppf(alpha, nu)
    return float(sigma * math.sqrt((nu - 2) / nu) * stats.t.pdf(q, nu) / alpha * (nu + q * q) / (nu - 1))


def ewma_vol(r: pd.Series, lam: float = EWMA_LAMBDA) -> pd.Series:
    """The RiskMetrics forecast for each day, made at the close before it (s[t] uses returns through t-1), seeded with
    the first 20 days' variance. For the forecast made at the last close, which includes that day's move, use ewma_next."""
    x = r.dropna()
    v = np.empty(len(x))
    v[0] = float(np.var(x.iloc[:20])) if len(x) >= 20 else float(x.iloc[0] ** 2)
    for i in range(1, len(x)):
        v[i] = lam * v[i - 1] + (1 - lam) * x.iloc[i - 1] ** 2
    s = pd.Series(np.sqrt(v), index=x.index)        # s[t] is known at the close of t-1: the forecast for day t
    return s


def ewma_next(r: pd.Series, lam: float = EWMA_LAMBDA) -> float:
    """The daily volatility forecast made at the last close in r, for the day after it (v0.44.1). ewma_vol's last
    value is the forecast for the last day itself and leaves that day's return out; a sizing decision made at a
    close should see the close."""
    x = r.dropna()
    return float(math.sqrt(lam * float(ewma_vol(x, lam).iloc[-1]) ** 2 + (1 - lam) * float(x.iloc[-1]) ** 2))


def tail_block(r: pd.Series, sigma_ann: float) -> dict:
    """One-month ES at 95% and 97.5% by three methods, one-day VaR and ES at 99%."""
    m = horizon_returns(r)
    s = ewma_vol(r)
    z = (r.dropna() / s).dropna()
    s_next = ewma_next(r)
    fhs_m = horizon_returns(z * s_next)
    sig_m = sigma_ann / math.sqrt(12)
    out = {"months": int(len(m)), "daily_vol_now_ann": s_next * math.sqrt(252)}
    for tag, a in (("95", 0.05), ("97.5", 0.025)):
        out[f"es{tag}"] = {"historical": es(m, a), "filtered": es(fhs_m, a), "student_t": t_es(sig_m, a)}
        out[f"es{tag}"]["governing"] = max(out[f"es{tag}"].values())
        out[f"es{tag}"]["method"] = max(("historical", "filtered", "student_t"), key=lambda k: out[f"es{tag}"][k])
    d = r.dropna()
    out["day"] = {"var99_hist": var(d, 0.01), "es99_hist": es(d, 0.01), "var99_now": 2.326 * s_next,
                  "es97_5_now": t_es(s_next, 0.025)}
    return out


def kupiec(r: pd.Series, q: float = 0.01, model: str = "normal") -> dict:
    """Backtest of the one-day 99% VaR on the book's own days (Kupiec 1995 proportion test). "normal": the normal
    quantile at the RiskMetrics volatility; "filtered": the 1% quantile of the standardized returns seen so far
    (filtered historical simulation, walked forward) at the same volatility."""
    s = ewma_vol(r)
    z = (r / s).dropna()
    mult = (-stats.norm.ppf(q) if model == "normal" else -z.expanding(min_periods=250).quantile(q).shift(1))
    d = pd.concat([r.rename("r"), s.rename("s"), (mult if isinstance(mult, pd.Series) else pd.Series(mult, index=s.index)).rename("m")], axis=1).dropna().iloc[60:]
    hit = d["r"] < -d["m"] * d["s"]
    n, x = len(d), int(hit.sum())
    p_hat = x / n
    ll0 = (n - x) * math.log(1 - q) + x * math.log(q)
    ll1 = (n - x) * math.log(1 - p_hat) + (x * math.log(p_hat) if x else 0.0) if 0 < p_hat < 1 else 0.0
    lr = -2 * (ll0 - ll1)
    t = d[hit]
    return {"days": n, "breaches": x, "expected": n * q, "rate": p_hat, "p": float(stats.chi2.sf(lr, 1)),
            "avg_loss_given_breach": float(-t["r"].mean()) if x else None,
            "avg_var_on_breach": float((t["m"] * t["s"]).mean()) if x else None, "from": str(d.index[0].date()),
            "model": {"normal": "normal quantile at the RiskMetrics volatility (lambda 0.94)",
                      "filtered": "walked-forward 1% quantile of standardized returns at the RiskMetrics volatility"}[model]}


# ---------------------------------------------------------------- factor model
def factor_model(R: pd.DataFrame, F: pd.DataFrame, w: pd.Series, beta_hl: int = BETA_HL, cov_hl: int = COV_HL) -> dict:
    """beta_hl and cov_hl (v0.44) are the two half-lives; the defaults are the engine's, and sensitivity.py varies them."""
    B = exposures.latest_betas(R, F[FACTORS], list(R.columns), halflife=beta_hl, priors=PRIORS)
    Fc = risk.ewma_cov(F[FACTORS].dropna(), halflife=cov_hl) * 252
    Bm = B[FACTORS].astype(float)
    D = np.diag(B["resid_vol_ann"].astype(float) ** 2)
    S = pd.DataFrame(Bm.to_numpy() @ Fc.to_numpy() @ Bm.to_numpy().T + D, index=R.columns, columns=R.columns)
    x = w.reindex(R.columns).to_numpy()
    b = Bm.to_numpy().T @ x
    fv = Fc.to_numpy() @ b
    var_tot = float(x @ S.to_numpy() @ x)
    parts = {f: float(b[i] * fv[i]) for i, f in enumerate(FACTORS)}
    parts["specific"] = float(x @ D @ x)
    sample = risk.ewma_cov(R.drop(columns=[c for c in R if R[c].count() < 2 * cov_hl]).dropna(), halflife=cov_hl) * 252
    xs = w.reindex(sample.index).to_numpy()
    xs = xs / xs.sum() * w.sum()
    rc = risk.risk_contributions(w.reindex(R.columns), S / 252)
    return {"betas": B, "factor_cov": Fc, "cov": S, "exposure": dict(zip(FACTORS, map(float, b))),
            "vol": math.sqrt(var_tot), "vol_sample": float(math.sqrt(xs @ sample.to_numpy() @ xs)),
            "sample_names": list(sample.index),
            "variance_share": {k: v / var_tot for k, v in parts.items()}, "rc": rc,
            "effective_bets": risk.effective_independent_bets(w.reindex(R.columns), S),
            "effective_names": risk.effective_risk_contributors(rc["share"]),
            "diversification_ratio": risk.diversification_ratio(w.reindex(R.columns), S),
            "factor_vol": {f: float(math.sqrt(Fc.loc[f, f])) for f in FACTORS}}


# ---------------------------------------------------------------- hedges, walked forward
def hedge_tests(rb: pd.Series, F: pd.DataFrame, E: pd.DataFrame, cash: pd.Series) -> dict:
    """Every hedge ratio is known at the close before the day it is applied. Hedge legs are excess of cash."""
    d = pd.concat([rb, F, E[["QQQ", "SOXX"]], cash], axis=1).dropna()
    qx, sx, bx = d["QQQ"] - d["cash"], d["SOXX"] - d["cash"], d["rates"] - d["cash"]
    beta_q = (d["book"].ewm(halflife=COV_HL, min_periods=COV_HL).cov(qx) / qx.ewm(halflife=COV_HL, min_periods=COV_HL).var())
    two = exposures.ewls_betas(d["book"], pd.DataFrame({"q": qx, "s": sx}), halflife=COV_HL, min_obs=COV_HL)
    h_bond = (-d["book"].ewm(halflife=COV_HL, min_periods=COV_HL).cov(bx) / bx.ewm(halflife=COV_HL, min_periods=COV_HL).var()).clip(0, 1)
    legs = {"none": pd.Series(0.0, index=d.index),
            "nasdaq_beta": -beta_q.shift(1) * qx,
            "nasdaq_and_semis": -(two["q"].shift(1) * qx + two["s"].shift(1) * sx),
            "bond_when_it_hedges": h_bond.shift(1) * bx,
            "bond_static_30": STATIC_BOND * bx}
    start = max(beta_q.first_valid_index(), two["q"].first_valid_index(), h_bond.first_valid_index())
    start = d.index[d.index.get_loc(start) + 1]
    base = d["book"].loc[start:]
    worst_days = base.nsmallest(max(int(0.05 * len(base)), 1)).index
    base_m = (1 + base).resample("ME").prod() - 1
    worst_months = base_m.nsmallest(max(int(0.10 * len(base_m)), 1)).index
    y22 = slice("2022-01-01", "2022-12-31")
    out = {"from": str(start.date()), "to": str(d.index[-1].date()), "days": int(len(base)), "policies": {}}
    for k, leg in legs.items():
        x = (d["book"] + leg).loc[start:]
        xm = (1 + x).resample("ME").prod() - 1
        lv = horizon_returns(x)
        out["policies"][k] = {
            "vol": float(x.std() * math.sqrt(252)), "variance_cut": float(1 - x.var() / base.var()),
            "mean_ann": float(x.mean() * 252), "leg_mean_ann": float(leg.loc[start:].mean() * 252),
            "worst_5pct_days": float(x.loc[worst_days].mean()), "worst_10pct_months": float(xm.loc[worst_months].mean()),
            "es95_month": es(lv, 0.05), "max_drawdown": float(1 - ((1 + x).cumprod() / (1 + x).cumprod().cummax().clip(lower=1.0)).min()),      # v0.47: from the starting value too
            "y2022": float((1 + x.loc[y22]).prod() - 1), "sharpe": float((x - d["cash"].loc[start:]).mean() / x.std() * math.sqrt(252))}
    out["now"] = {"nasdaq_beta": float(beta_q.iloc[-1]), "nasdaq": float(two["q"].iloc[-1]), "semis": float(two["s"].iloc[-1]),
                  "bond_ratio": float(h_bond.iloc[-1])}
    return out


def keep_names_hedge(rb: pd.Series, E: pd.DataFrame, cash: pd.Series, fm: dict, w: pd.Series, rf: float) -> dict:
    """The Nasdaq-100 futures short (fraction of NAV) that brings the book inside every limit with each name kept at
    full size: the most cautious one-month 95% ES within the budget, the factor-model volatility within the target and
    the 95th-percentile one-year drawdown within the cap. Bisection on the worst of the three ratios."""
    d = pd.concat([rb, (E["QQQ"] - cash).rename("qx"), E["VTI"]], axis=1).dropna()
    beta_q_vti = float(d["qx"].cov(d["VTI"]) / d["VTI"].var())
    beta_b_vti = float(d["book"].cov(d["VTI"]) / d["VTI"].var())
    S, Fc = fm["cov"].to_numpy(), fm["factor_cov"]
    x = w.reindex(fm["cov"].index).to_numpy()
    b = np.array([fm["exposure"][f] for f in FACTORS])
    cross = float((Fc.to_numpy() @ b)[0])

    def read(h: float) -> dict:
        sig = math.sqrt(max(float(x @ S @ x) - 2 * h * cross + h * h * float(Fc.loc["market", "market"]), 1e-12))
        e = tail_block(d["book"] - h * d["qx"], sig)["es95"]["governing"]
        mu = rf + EQUITY_PREMIUM * (beta_b_vti - h * beta_q_vti)
        dd = sizing.drawdown_quantile(mu, sig, 1.0, cash_rate=rf)
        return {"es95": e, "vol": sig, "drawdown95": dd, "worst": max(e / ES_BUDGET, sig / VOL_TARGET, dd / MAX_DD),
                "market_beta_left": fm["exposure"]["market"] - h}

    grid = np.round(np.arange(0.0, 1.51, 0.02), 2)
    reads = [(h, read(h)) for h in grid]
    ok = [(h, r) for h, r in reads if r["worst"] <= 1]
    h, r = ok[0] if ok else min(reads, key=lambda t: t[1]["worst"])
    if ok and h > 0:                                  # refine between the last failing and the first passing step
        lo, hi = h - 0.02, h
        for _ in range(12):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if read(mid)["worst"] > 1 else (lo, mid)
        h, r = hi, read(hi)
    ratios = {"es_budget": r["es95"] / ES_BUDGET, "vol_target": r["vol"] / VOL_TARGET, "drawdown_cap": r["drawdown95"] / MAX_DD}
    return {"short_nasdaq_frac": float(h) if ok else None, "best_short": float(h), **r, "meets_all": bool(ok),
            "binding_after": max(ratios, key=ratios.get), "notional_usd_per_100m": float(h) * NAV_USD}


# ---------------------------------------------------------------- stress
def episodes(rb: pd.Series, R: pd.DataFrame, F: pd.DataFrame, E: pd.DataFrame) -> list[dict]:
    lv = (1 + pd.concat([rb, E["QQQ"], E["SOXX"], F["rates"]], axis=1).fillna(0.0)).cumprod()
    names = (1 + R.fillna(0.0)).cumprod()
    out = []
    for name, (s, e) in stress.EPISODES.items():
        if lv.index[0] > pd.Timestamp(s) - pd.Timedelta(days=5) or lv.index[-1] < pd.Timestamp(e):
            continue
        a, b = lv.loc[:s].iloc[-1], lv.loc[:e].iloc[-1]
        path = lv["book"].loc[s:e] / a["book"]
        nm = names.loc[:e].iloc[-1] / names.loc[:s].iloc[-1] - 1
        nm = nm[[c for c in R if R[c].loc[:s].notna().any()]]
        out.append({"episode": name, "from": s, "to": e, "book": float(b["book"] / a["book"] - 1),
                    "nasdaq": float(b["QQQ"] / a["QQQ"] - 1), "semis_etf": float(b["SOXX"] / a["SOXX"] - 1),
                    "bond20": float(b["rates"] / a["rates"] - 1), "worst_point": float(min(path.min(), 1.0) - 1),
                    "worst_name": nm.idxmin(), "worst_name_return": float(nm.min()),
                    "names_missing": [c for c in R if not R[c].loc[:s].notna().any()]})
    return out


SCENARIO_FACTORS = ["market", "ai", "rates"]
SCENARIO_METHOD = (
    "Each scenario states three moves: the Nasdaq-100, the AI names beyond the Nasdaq-100, and the long yield. "
    "Nasdaq leg: each name's loading on QQQ times the Nasdaq-100 move. "
    "AI leg: each name's loading on the book's own daily return less QQQ's (today's weights), times the scenario's AI move; "
    "the scenario's AI basket is these nine names, so the whole book's loading on this leg is about 1 by construction "
    "and a name's is its share of that. "
    "Rates leg: each name's loading on the 20-year par bond's return, given the other two, times the bond's repriced "
    "return for the yield move (duration and convexity at today's 20-year yield). "
    "Loadings are exponentially weighted least squares, half-life 126 days, on all three at once; a name with under "
    "two years of history leans on its prior. Before v0.47 the AI move was put on semiconductors net of the "
    "Nasdaq-100, a factor this book loads on negatively, so an AI sell-off raised the book and an AI rally lowered it.")


def scenario_betas(R: pd.DataFrame, F: pd.DataFrame, rb: pd.Series, halflife: int = BETA_HL) -> pd.DataFrame:
    """Each name's loadings for the scenarios (v0.47): the Nasdaq-100, the AI leg and the bond, measured together.

    The engine's scenarios (stress.SCENARIOS) give the AI names' move in excess of the Nasdaq-100. The AI names are
    this book, so the leg is the book's own return less QQQ's. That is a definition at the level of the book (its
    loading is about 1, as it must be: if the nine names fall 15% more than the index, a book of the nine names does
    too) and a measurement at the level of a name (which names carry it). It is used for the scenario table only:
    the risk model, the limits and the size still rest on the three external factors, which are measured."""
    X = pd.DataFrame({"market": F["market"], "ai": rb - F["market"], "rates": F["rates"]})
    return exposures.latest_betas(R, X, list(R.columns), halflife=halflife, priors=PRIORS)


def scenarios(betas: pd.DataFrame, w: pd.Series, y20: float, h_short: float | None) -> list[dict]:
    """The engine's scenarios (stress.SCENARIOS) through scenario_betas: see SCENARIO_METHOD, which is published
    beside the rows. `legs` splits the book's move into the three parts, so the Nasdaq leg can be read on its own."""
    D, C = duration_convexity(y20, 20.0, y20)
    B = betas.reindex(w.index)[SCENARIO_FACTORS].astype(float)
    rows = []
    for sc in stress.SCENARIOS:
        dy = sc["dy_bp"] / 1e4
        bond = -D * dy + 0.5 * C * dy * dy
        move = {"market": sc["market"], "ai": sc["ai"], "rates": bond}
        names = sum(B[f] * move[f] for f in SCENARIO_FACTORS)
        legs = {f: float((w * B[f]).sum() * move[f]) for f in SCENARIO_FACTORS}
        book = float((w * names).sum())
        rows.append({"scenario": sc["name"], "nasdaq": sc["market"], "ai_vs_nasdaq": sc["ai"],
                     "semis_vs_nasdaq": sc["ai"],             # the old name of the same input, kept for pages built before v0.47
                     "dy_bp": sc["dy_bp"], "bond20": float(bond), "book": book,
                     "legs": {"nasdaq": legs["market"], "ai": legs["ai"], "rates": legs["rates"]},
                     "with_bond_30": book + STATIC_BOND * float(bond),
                     "with_nasdaq_hedge": book - (h_short or 0.0) * sc["market"],
                     "worst_name": str(names.idxmin()), "worst_name_move": float(names.min())})
    return rows


def worst_days(rb: pd.Series, F: pd.DataFrame, E: pd.DataFrame, n: int = 10) -> list[dict]:
    d = pd.concat([rb, E["QQQ"], E["SOXX"], F["rates"]], axis=1).dropna()
    return [{"date": str(t.date()), "book": float(r["book"]), "nasdaq": float(r["QQQ"]), "semis_etf": float(r["SOXX"]),
             "bond20": float(r["rates"])} for t, r in d.nsmallest(n, "book").iterrows()]


def correlation_block(rb: pd.Series, F: pd.DataFrame) -> dict:
    """One stated definition: the 63-day exponentially weighted correlation of daily returns against the 20-year par
    bond, with the engine's hysteresis (enter at 0.10, leave at 0). Two context numbers beside it, each labelled."""
    d = pd.concat([rb, F["market"], F["rates"]], axis=1).dropna()
    c_book = regime.ewm_corr(d["book"], d["rates"], COV_HL)
    c_q = regime.ewm_corr(d["market"], d["rates"], COV_HL)
    lab = regime.classify(c_book)
    m = (1 + d).resample("ME").prod() - 1
    m36 = float(m["book"].iloc[-36:].corr(m["rates"].iloc[-36:]))
    shock = regime.shock_table(d["book"], d["rates"], q=0.05,
                               by=pd.Series(np.where(d.index < "2022-01-01", "2017 to 2021", "2022 on"), index=d.index))
    yearly = c_book.groupby(c_book.index.year).mean()
    return {"definition": "63-day exponentially weighted correlation of daily returns, book vs the 20-year par bond",
            "book_63d": float(c_book.iloc[-1]), "nasdaq_63d": float(c_q.iloc[-1]), "book_36m_monthly": m36,
            "state": lab.iloc[-1], "state_since": str(lab.index[(lab != lab.shift()).to_numpy()][-1].date()) if (lab != lab.iloc[-1]).any() else None,      # v0.44.1: the first day of the state, not the last day before it
            "share_days_hedging": float((lab.dropna() == regime.HEDGING).mean()),      # v0.47: of the days that have a state (the warm-up has none)
            "by_year": {int(k): float(v) for k, v in yearly.items()},
            "shock": [{"group": g, **{k: float(v) for k, v in r.items()}} for g, r in shock.iterrows()]}


def liquidity(vol: dict[str, pd.DataFrame], w: pd.Series, asof: pd.Timestamp) -> list[dict]:
    rows = []
    for k, f in vol.items():
        f = f.loc[:asof].tail(20)
        adv = float((f["close"] * f["volume"]).mean())
        rows.append({"name": k, "adv_usd": adv, "position_usd": float(w[k] * NAV_USD),
                     "days_100m": float(w[k] * NAV_USD / (ADV_SHARE * adv)), "days_1bn": float(w[k] * 10 * NAV_USD / (ADV_SHARE * adv)),
                     "share_of_adv_100m": float(w[k] * NAV_USD / adv)})
    return rows


def drawdowns(rb: pd.Series, q: pd.Series) -> dict:
    lv = (1 + rb.dropna()).cumprod()
    dd = lv / lv.cummax().clip(lower=1.0) - 1          # v0.47: the record starts at 1.0, so a fall on its first days is a fall from there
    t = dd.idxmin()
    peak = lv.loc[:t].idxmax() if lv.loc[:t].max() >= 1.0 else lv.index[0]      # a peak at the start is dated to the first day
    lq = (1 + q.reindex(lv.index).fillna(0.0)).cumprod()
    mo = pd.DataFrame({"book": lv, "nasdaq": lq}).resample("ME").last()
    return {"max": float(max(-dd.min(), 0.0)), "peak": str(peak.date()), "trough": str(t.date()), "now": float(max(-dd.iloc[-1], 0.0)),
            "nasdaq_max": float(max(-(lq / lq.cummax().clip(lower=1.0) - 1).min(), 0.0)),
            "monthly": {"months": [str(i.date())[:7] for i in mo.index], "book": [round(float(v), 4) for v in mo["book"]],
                        "nasdaq": [round(float(v), 4) for v in mo["nasdaq"]]},
            "cagr": float(lv.iloc[-1] ** (252 / len(lv)) - 1), "nasdaq_cagr": float(lq.iloc[-1] ** (252 / len(lq)) - 1)}


# ---------------------------------------------------------------- the build
def _slim(o: dict) -> dict:
    """A rule test without the per-rule table's bulk: the headline, the best, the bar and every rule's t and Sharpe."""
    return {"name": o["name"], "verdict": o["verdict"], "headline": o["headline"], "best": {"rule": o["best"]["rule"], "t": o["best"]["t"]},
            "t_bar": o["t_bar"], "n_rules": o["n_rules"], "months": o["months"],
            "rules": [{"rule": t["rule"], "t": t["t"], "sharpe_rule": t["sharpe_rule"], "maxdd_rule": t["maxdd_rule"]} for t in o["tests"]]}


TREASURY_LAG_OK = 1                    # sessions the yields may trail the prices without comment: one bond-market holiday on which stocks trade
TREASURY_LAG_MAX = 3                   # beyond this the run stops, as it does for a price that stale (download: stale_bdays=3)


def inputs(prices: dict[str, pd.DataFrame], ust: pd.DataFrame | None = None, book: dict[str, float] = BOOK) -> dict:
    """The panel and the rates a call is sized on, all as of the prices' last session (v0.47). build() and
    sensitivity.build() both start here, so they cannot read different rates.

    The yields are cut at the prices' as-of date: a Treasury row that posts after that session is not this call's
    data, and a second run later the same day must give the same size. The cash rate and the 20-year yield are the
    last ones actually printed (a blank on the last row used to become a size of zero). Yields that end more than
    TREASURY_LAG_OK sessions before the prices are reported in `warnings`; more than TREASURY_LAG_MAX stops the
    run, because every later day's bond return would be a silent zero."""
    warn = []
    if ust is None:
        ust = treasury()
        if TREASURY_STATUS.get("error"):
            warn.append(f"Treasury yields: {TREASURY_STATUS['error']}")
    P = panel(prices, ust, book)
    asof = P["R"].dropna(how="all").index[-1]
    ignored = int((ust.index > asof).sum())
    if ignored or P["R"].index[-1] > asof:
        ust = ust.loc[:asof]
        P = panel(prices, ust, book)
        for k in ("R", "F", "E", "cash", "bond"):
            P[k] = P[k].loc[:asof]
    lag = int(np.busday_count(ust.index[-1].date(), asof.date()))
    if lag > TREASURY_LAG_MAX:
        raise ValueError(f"Treasury yields end {ust.index[-1].date()}, {lag} sessions before the prices ({asof.date()}): "
                         f"refusing to size on bond returns and a cash rate that stale (limit {TREASURY_LAG_MAX})")
    if lag > TREASURY_LAG_OK:
        warn.append(f"Treasury yields end {ust.index[-1].date()}, {lag} sessions before the prices ({asof.date()}); the bond's "
                    "return on the sessions between is carried as zero and the cash rate is the last one printed.")

    def last(col: str) -> tuple[float, pd.Timestamp]:
        s = ust[col].dropna()
        if s.empty or int(np.busday_count(s.index[-1].date(), asof.date())) > TREASURY_LAG_MAX:
            raise ValueError(f"no {col} yield printed within {TREASURY_LAG_MAX} sessions of {asof.date()} "
                             f"(last: {s.index[-1].date() if len(s) else 'none'}): the call needs a cash rate and a long yield")
        return float(s.iloc[-1]) / 100, s.index[-1]

    rf, rf_date = last("DGS2")
    y20, _ = last("DGS20")
    if rf_date < ust.index[-1]:
        warn.append(f"The 2-year yield is blank after {rf_date.date()}; the cash rate is that day's.")
    return {"ust": ust, "P": P, "asof": asof, "rf": rf, "rf_date": rf_date, "y20": y20, "treasury_lag_bdays": lag,
            "treasury_rows_after_asof": ignored, "warnings": warn}


def build(prices: dict[str, pd.DataFrame], ust: pd.DataFrame | None = None, book: dict[str, float] = BOOK,
          meta: dict | None = None, long_record: dict | None = None) -> dict:
    I = inputs(prices, ust, book)
    ust, P, asof, rf, y20 = I["ust"], I["P"], I["asof"], I["rf"], I["y20"]
    w = pd.Series(book, dtype=float)
    R, F, E, cash = P["R"], P["F"], P["E"], P["cash"]
    rb = book_returns(R, w)
    fm = factor_model(R, F, w)
    sigma = fm["vol"]
    tail = tail_block(rb, sigma)
    beta_vti = float(pd.concat([rb, E["VTI"]], axis=1).dropna().cov().iloc[0, 1] / E["VTI"].var())
    broad = {}                                       # each name's single-factor beta to the broad US market (VTI), as the page's other desks use
    for k in R:
        b = exposures.ewls_betas(R[k], E[["VTI"]].rename(columns={"VTI": "m"}), halflife=BETA_HL, min_obs=20).dropna()
        own = float(b["m"].iloc[-1]) if len(b) else float("nan")
        n = float(b["n_obs"].iloc[-1]) if len(b) else 0.0
        broad[k] = own if n >= 504 else exposures.shrink(own, n, broad.get(PRIORS.get(k), own), 126.0)
    mu = rf + EQUITY_PREMIUM * beta_vti              # rf: the last 2-year yield printed on or before the as-of date (inputs)
    sizes = {"es_budget": ES_BUDGET / tail["es95"]["governing"], "vol_target": VOL_TARGET / sigma,
             "drawdown_cap": sizing.max_leverage(mu, sigma, MAX_DD, cash_rate=rf), "gross_cap": MAX_GROSS}
    binding = min(sizes, key=sizes.get)
    hedge_need = keep_names_hedge(rb, E, cash, fm, w, rf)
    rc = fm["rc"]
    B = fm["betas"]
    SB = scenario_betas(R, F, rb)                    # v0.47: the scenario table's own loadings; nothing above this line reads them
    out = {
        "schema": 1, "asof": str(asof.date()), "treasury_to": str(ust.index[-1].date()),
        "treasury_lag_bdays": I["treasury_lag_bdays"], "treasury_rows_after_asof": I["treasury_rows_after_asof"], "warnings": I["warnings"],
        "from": str(rb.dropna().index[0].date()), "days": int(rb.notna().sum()),
        "weights": book, "nav_usd": NAV_USD, "first_date": P["first"], "last_date": P["last"],
        "exposure": {**fm["exposure"], "beta_broad_market": float(exposures.ewls_betas(rb, E[["VTI"]].rename(columns={"VTI": "m"}), halflife=BETA_HL, min_obs=60).dropna()["m"].iloc[-1]),
                     "beta_broad_market_10y": beta_vti,
                     "rates_dv01_per_100m": float(fm["exposure"]["rates"] * duration_convexity(y20, 20.0, y20)[0] * NAV_USD * 1e-4)},
        "betas": [{"name": k, **{f: float(B.loc[k, f]) for f in FACTORS}, "broad_market": broad[k], "days": int(B.loc[k, "n_obs"]),
                   "specific_vol": float(B.loc[k, "resid_vol_ann"]), "prior": PRIORS.get(k)} for k in w.index],
        "factors": {f: {"name": FACTOR_NAME[f], "vol": fm["factor_vol"][f]} for f in FACTORS},
        "factor_corr": {a: {b: float(fm["factor_cov"].loc[a, b] / math.sqrt(fm["factor_cov"].loc[a, a] * fm["factor_cov"].loc[b, b])) for b in FACTORS} for a in FACTORS},
        "risk": {"vol": sigma, "vol_names_cov": fm["vol_sample"], "vol_names_cov_over": fm["sample_names"],
                 "vol_ewma_now": tail["daily_vol_now_ann"], "variance_share": fm["variance_share"],
                 "effective_bets": fm["effective_bets"], "effective_names": fm["effective_names"],
                 "diversification_ratio": fm["diversification_ratio"], "weight_hhi": float((w ** 2).sum()),
                 "contributions": [{"name": k, "weight": float(rc.loc[k, "weight"]), "share": float(rc.loc[k, "share"])} for k in rc.index]},
        "tail": tail, "var_backtest": {"normal": kupiec(rb), "filtered": kupiec(rb, model="filtered")},
        "limits": {"es_budget": ES_BUDGET, "vol_target": VOL_TARGET, "max_drawdown": MAX_DD, "max_gross": MAX_GROSS,
                   "drawdown_drift": mu, "cash_rate": rf, "cash_rate_date": str(I["rf_date"].date())},
        "sizes": sizes, "binding": binding, "size": min(sizes.values()),
        "at_full": {"es95": tail["es95"]["governing"], "vol": sigma,
                    "drawdown95": sizing.drawdown_quantile(mu, sigma, 1.0, cash_rate=rf)},
        "keep_names_hedge": hedge_need,
        "frontier": sizing_rules.frontier(rb, (E["QQQ"] - cash), fm, beta_vti,
                                          float(pd.concat([E["QQQ"] - cash, E["VTI"]], axis=1).dropna().cov().iloc[0, 1] / E["VTI"].var()), rf,
                                          {"es": ES_BUDGET, "vol": VOL_TARGET, "dd": MAX_DD}, lambda x, sig: tail_block(x, sig)["es95"]["governing"],
                                          grosses=tuple(sorted({float(min(sizes.values()))} | {g for g in (0.6, 0.7, 0.8, 0.9, 1.0) if g > min(sizes.values()) + 0.02})),
                                          cash=cash),
        "vol_rule": {"book": _slim(sizing_rules.test_all(rb, cash.reindex(rb.index).fillna(0.0), "the book, 2017 on")),
                     "nasdaq_2017": _slim(sizing_rules.test_all(E["QQQ"].dropna(), cash.reindex(E["QQQ"].dropna().index).fillna(0.0), "the Nasdaq-100 (QQQ), 2017 on")),
                     "long_record": long_record, "rule": sizing_rules.HEADLINE, "n_rules": sizing_rules.N_RULES, "t_bar": sizing_rules.expected_max_t(sizing_rules.N_RULES),
                     "gamma": sizing_rules.GAMMA},
        "hedges": hedge_tests(rb, F, E, cash), "episodes": episodes(rb, R, F, E),
        "scenarios": scenarios(SB, w, y20, hedge_need.get("best_short")),
        "scenarios_method": SCENARIO_METHOD,
        "scenario_loadings": {"book": {f: float((w * SB.reindex(w.index)[f].astype(float)).sum()) for f in SCENARIO_FACTORS},
                              "names": [{"name": k, **{f: float(SB.loc[k, f]) for f in SCENARIO_FACTORS}} for k in w.index]},
        "worst_days": worst_days(rb, F, E), "correlation": correlation_block(rb, F),
        "liquidity": liquidity(P["vol"], w, asof), "drawdowns": drawdowns(rb, E["QQQ"]),
        "limitations": LIMITATIONS, "meta": meta or {},
        # v0.47: what the price validation found (download()), published with the call it guards
        **({"validation": prices.validation} if getattr(prices, "validation", None) else {}),
        "sources": {"prices": MIRROR_REPO, "treasury": "US Treasury daily par yield curve rates (home.treasury.gov)",
                    "method": "buildout/book.py"},
    }
    return _clean(out)


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


# ---------------------------------------------------------------- download and the synthetic world
# ---- v0.47: the price pull and what it must pass before a call is sized on it ----------------------------------
# The mirror is one person's GitHub repository, refreshed from Yahoo Finance by yfinance (its README) at about 10:30 to
# 12:20 UTC, Tuesday to Saturday. The call ledger, the marked record and the paper account are all built on it, so the
# pull is checked four ways and any failure stops the step (the daily job then turns red and opens the issue):
#   form       duplicates, order, non-positive or missing closes (buildout/data/validate.py)
#   date       every file ends on the session before today in New York (buildout/sessions.py). Before, staleness was
#              measured against the newest date inside the pull itself, so a mirror frozen for six weeks passed
#   together   every file ends on the same day: a name a session behind the others is not quietly re-weighted
#   jumps      no one-day fall beyond 30% or rise beyond 45% (data/corporate_actions.py): the mirror's prices are
#              already split-adjusted, so such a move is a split it missed or a bad print, unless listed as confirmed
# and the newest closes are compared with a second source (Stooq, then Yahoo; datahub.recent_closes). A newest close
# more than CROSS_CHECK_TOL away fails the step; a second source that does not answer is recorded and warned about.
CROSS_CHECK_TOL = 0.01          # 1%: wider than any dividend adjustment on a close of the last week, far inside a bad print
CROSS_CHECK_DAYS = 5
CROSS_CHECK_EXTRA = ("qqq",)    # besides the book's own names
SECOND_SOURCE_ORDER = ("stooq", "yahoo")      # Stooq first: the mirror is itself built from Yahoo, so Yahoo is not independent of it
MIRROR_SOURCE = "yennanliu/finance_data on GitHub (Yahoo Finance via yfinance); split-adjusted closes, dividends on ex-dates"


class Prices(dict):
    """What download() returns: the frames by file name, and what the validation found (`validation`, None when
    validate=False). A dict in every other way; a filtered copy is a plain dict and carries no validation."""
    validation: dict | None = None


def expected_asof(now=None) -> pd.Timestamp:
    """The newest close a pull made now should have: the session before today in New York."""
    from datetime import datetime, timezone
    from . import sessions
    t = pd.Timestamp(now).to_pydatetime() if now is not None else datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return pd.Timestamp(sessions.prev_session(t.astimezone(sessions.NY).date()))


def _closes(df: pd.DataFrame) -> pd.Series:
    d = pd.to_datetime(df.iloc[:, 0], errors="coerce")
    s = pd.Series(pd.to_numeric(df["close"], errors="coerce").to_numpy(), index=d)
    return s[s.index.notna()].dropna().sort_index()


def cross_check(prices: dict, names: list[str], fetch=None, tol: float = CROSS_CHECK_TOL, days: int = CROSS_CHECK_DAYS) -> dict:
    """The newest closes of `names` (file names) against a second source. Returns
        status   "ok" (every name's newest close agrees), "disagrees" (one or more differ by more than tol),
                 "partial" (some names had no second quote; the rest agree) or "unavailable" (no second quote at all)
        names    per file: the second source, the newest date compared, both closes, the gap, and earlier closes that
                 differ by more than tol (reported, not fatal: an older close can differ by an adjustment)
    `fetch(ticker, days, order)` returns (closes indexed by date, source, errors); default datahub.recent_closes.
    Never raises: the caller decides what a disagreement means."""
    from . import datahub
    fetch = fetch or (lambda t, n, order: datahub.recent_closes(t, n, order))
    order, rows, bad, missing = list(SECOND_SOURCE_ORDER), {}, [], []
    for f in names:
        mine = _closes(prices[f]).tail(days)
        try:
            other, src, errs = fetch(f.upper(), days + 5, tuple(order))
        except Exception as exc:  # noqa: BLE001 - a second source that breaks is a second source that did not answer
            other, src, errs = pd.Series(dtype=float), "none", {"error": f"{type(exc).__name__}: {exc}"[:120]}
        if f == names[0] and src != "none":         # a source that had nothing for the first name (Stooq behind its browser
            order = [s for s in order if s == src or s not in (errs or {})] or order      # check) is not asked ten more times
        other = pd.Series(other, dtype=float)
        other.index = pd.to_datetime(other.index)
        last = mine.index[-1] if len(mine) else None
        if last is None or last not in other.index:
            missing.append(f)
            rows[f] = {"source": src, "status": "unavailable",
                       "why": (f"the second source has no close for {last.date()}" if last is not None and len(other) else "no second quote") + (f" ({errs})" if errs else "")[:200]}
            continue
        gap = float(mine[last] / other[last] - 1.0)
        earlier = [{"date": d.strftime("%Y-%m-%d"), "gap": float(mine[d] / other[d] - 1.0)} for d in mine.index[:-1] if d in other.index and abs(mine[d] / other[d] - 1.0) > tol]
        rows[f] = {"source": src, "independent": src != "yahoo", "date": last.strftime("%Y-%m-%d"), "close": float(mine[last]), "second": float(other[last]), "gap": gap,
                   "status": "ok" if abs(gap) <= tol else "disagrees", "earlier_gaps": earlier}
        if abs(gap) > tol:
            bad.append(f)
    checked = [f for f in names if rows[f]["status"] != "unavailable"]
    status = "disagrees" if bad else "unavailable" if not checked else "partial" if missing else "ok"
    used = sorted({rows[f]["source"] for f in checked})
    detail = ("; ".join(f"{f} {rows[f]['date']}: {rows[f]['close']:.2f} here, {rows[f]['second']:.2f} at {rows[f]['source']} ({rows[f]['gap']:+.2%})" for f in bad) if bad
              else f"{len(checked)} of {len(names)} names within {tol:.1%} of {', '.join(used) or 'no source'}" + (f"; no second quote for {', '.join(missing)}" if missing else ""))
    return {"status": status, "tolerance": tol, "sources": used, "independent": bool(used) and "yahoo" not in used,
            "note": None if not used or "yahoo" not in used else "Yahoo answered; the mirror is built from Yahoo, so this checks the copy against its origin, not the origin itself",
            "detail": detail, "names": rows}


def validate_pull(out: dict, book: dict[str, float] = BOOK, now=None, check: dict | None = None) -> dict:
    """Every rule above on one pull. Returns the validation record that book.json publishes (ok, failed, notes,
    dates, the cross-check); `ok` False means the call must not be sized on this pull. Does not raise."""
    from datetime import datetime, timezone
    from . import sessions
    from .data.corporate_actions import SPLIT_GUARD_DOWN, SPLIT_GUARD_UP, unexplained_jumps
    from .data.validate import FATAL, validate_all
    rep = validate_all(out, asof=None)
    failed: dict[str, list[str]] = {r["name"]: [i["kind"] + ": " + i["detail"] for i in r["issues"] if i["kind"] in FATAL] for r in rep["results"] if not r["ok"]}
    notes = [f"{r['name']}: {i['kind'][5:]}: {i['detail']}" for r in rep["results"] for i in r["issues"] if i["kind"].startswith("warn_") and i["kind"] != "warn_columns"]
    lasts = {k: _closes(df).index[-1] for k, df in out.items() if len(df) and "close" in df and len(_closes(df))}
    want, newest = expected_asof(now), (max(lasts.values()) if lasts else None)
    for k, d in sorted(lasts.items()):
        n = sessions.sessions_between(d.date(), want.date())
        if n > 0:
            failed.setdefault(k, []).append(f"stale: ends {d.date()}, {n} session{'s' if n != 1 else ''} before the last completed session ({want.date()})")
        elif d < newest:
            failed.setdefault(k, []).append(f"stale: ends {d.date()}, behind the other names ({newest.date()})")
    closes = pd.DataFrame({k.upper(): _closes(df) for k, df in out.items() if len(df) and "close" in df})
    for sym, rows in unexplained_jumps(closes).items():
        failed.setdefault(sym.lower(), []).append("jump: " + ", ".join(f"{r['date']} {r['change']:+.0%}" + (f" (a {r['looks_like']} split?)" if r["looks_like"] else "") for r in rows[:5])
                                                  + " with no split recorded; if genuine, add the date to CONFIRMED_MOVES in buildout/data/corporate_actions.py")
    if check is not None:
        for f in [f for f, r in (check.get("names") or {}).items() if r.get("status") == "disagrees"]:
            r = check["names"][f]
            failed.setdefault(f, []).append(f"cross-check: the {r['date']} close is {r['close']:.2f} here and {r['second']:.2f} at {r['source']} ({r['gap']:+.2%}, limit {check['tolerance']:.1%})")
        if check.get("status") in ("unavailable", "partial", "not_run"):
            notes.append(f"cross-check {check['status']}: {check.get('detail', '')}")
        notes += [f"{f}: the second source's {g['date']} close differs by {g['gap']:+.2%}" for f, r in (check.get("names") or {}).items() for g in r.get("earlier_gaps") or []]
    return {"ok": not failed, "n": len(out), "failed": sorted(failed), "problems": {k: v for k, v in sorted(failed.items())}, "warnings": len(notes), "notes": notes[:40],
            "asof": newest.strftime("%Y-%m-%d") if newest is not None else None, "expected_asof": want.strftime("%Y-%m-%d"), "source": MIRROR_SOURCE,
            "rules": {"stale": "every file ends on the session before today in New York, and on the same day as the others",
                      "jump": f"no one-day fall beyond {SPLIT_GUARD_DOWN:.0%} or rise beyond {SPLIT_GUARD_UP:.0%} without a recorded split",
                      "cross_check": f"the newest close within {CROSS_CHECK_TOL:.0%} of a second source"},
            "cross_check": check or {"status": "not_run", "detail": "no second source was asked"},
            "checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def download(cache: Path | None = None, book: dict[str, float] = BOOK, validate: bool = True, now=None, second_source=None) -> dict[str, pd.DataFrame]:
    """The mirror's CSVs, one per name and ETF, cached for a day. One missing file raises: a book without a name is
    a different book. Every pull is validated (validate_pull above) and a pull that fails raises ValueError, so the
    step stops rather than sizing on it. The result carries the validation record (`.validation`), which build()
    publishes in book.json. The second-source check runs when prices were fetched in this call (not when every file
    came from the day's cache: the check made when they were fetched is stored beside them and reused).
    `now` and `second_source` are for tests."""
    from .data import http
    files = sorted({FILE.get(k, k.lower()) for k in book} | set(FACTOR_ETF.values()))
    out, fetched = Prices(), False
    for f in files:
        p = Path(cache) / f"{f}.csv" if cache else None
        if p and p.exists() and (pd.Timestamp.now().timestamp() - p.stat().st_mtime) < 86400:
            text = p.read_text()
        else:
            text = http.get(MIRROR.format(f), timeout=45).decode()
            fetched = True
            if p:
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_name(f".{p.name}.tmp")          # a killed run never leaves half a file for tomorrow's cache hit
                tmp.write_text(text)
                tmp.replace(p)
        out[f] = pd.read_csv(io.StringIO(text))
    if validate:
        names = sorted({FILE.get(k, k.lower()) for k in book} | set(CROSS_CHECK_EXTRA) & set(out))
        lasts = [_closes(df).index[-1] for df in out.values() if len(df) and "close" in df and len(_closes(df))]
        newest = max(lasts).strftime("%Y-%m-%d") if lasts else None
        stored = Path(cache) / "cross_check.json" if cache else None
        check = None
        if fetched or second_source is not None:
            try:
                check = cross_check(out, [n for n in names if n in out and len(out[n]) and "close" in out[n]], fetch=second_source)
            except Exception as exc:  # noqa: BLE001 - the check itself must never be what stops the call
                check = {"status": "unavailable", "detail": f"the cross-check could not run: {type(exc).__name__}: {exc}"[:200], "names": {}, "tolerance": CROSS_CHECK_TOL}
            if stored is not None:
                stored.parent.mkdir(parents=True, exist_ok=True)
                stored.write_text(json.dumps({"asof": newest, "check": check}))
        elif stored is not None and stored.exists():
            try:
                prev = json.loads(stored.read_text())
                check = prev["check"] if prev.get("asof") == newest else None
            except (OSError, ValueError, KeyError):
                check = None
        if check is None:
            check = {"status": "not_run", "detail": "the prices came from the local cache and no check is stored for this date", "names": {}, "tolerance": CROSS_CHECK_TOL}
        v = validate_pull(out, book, now=now, check=check)
        out.validation = v
        LAST_VALIDATION.clear(); LAST_VALIDATION.update(v)
        if not v["ok"]:   # v0.38: a bad pull stops the run (and the daily job alerts) rather than sizing on it
            raise ValueError("price validation failed: " + "; ".join(f"{k}: " + "; ".join(p) for k, p in v["problems"].items()))
    return out


LAST_VALIDATION: dict = {}


def synthetic(seed: int = 30, days: int = 1500, beta: dict | None = None, ipo_days: int = 90) -> tuple[dict, pd.DataFrame, dict]:
    """A world with known factor betas: QQQ, a semis factor, a bond from simulated yields, nine names with planted
    loadings and specific risk; the last name lists `ipo_days` before the end. Returns (prices, treasury, truth)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2017-01-02", periods=days)
    y20 = 3.0 + np.cumsum(rng.normal(0, 0.06, days))
    y2 = np.clip(y20 - 0.6 + rng.normal(0, 0.02, days), 0.1, None)
    ust = pd.DataFrame({"DGS2": y2, "DGS10": y20 - 0.3, "DGS20": y20}, index=dates)
    bond = constant_maturity_returns(ust["DGS20"]).fillna(0.0).to_numpy()
    mkt = rng.standard_t(5, days) * 0.013 / math.sqrt(5 / 3) + 0.0004 - 0.15 * bond
    semi = rng.normal(0, 0.008, days)
    beta = beta or {k: (1.0 + 0.1 * i, 0.3 * (i % 3), -0.2 + 0.05 * i) for i, k in enumerate(BOOK)}
    def px(r, vol=1e7):
        c = 100 * np.cumprod(1 + r)
        return pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "close": c, "volume": vol, "div": np.nan})
    prices = {"qqq": px(mkt), "soxx": px(mkt + semi), "vti": px(0.8 * mkt + rng.normal(0, 0.002, days))}
    for i, (k, (bm, bs, br)) in enumerate(beta.items()):
        r = bm * mkt + bs * semi + br * bond + rng.normal(0, 0.012, days)
        f = px(r, vol=2e7)
        if i == len(beta) - 1:
            f = f.iloc[-ipo_days:]
        prices[FILE.get(k, k.lower())] = f
    return prices, ust, beta


def validate(seed: int = 30) -> dict:
    """The engine on a world with known betas: how close the measured betas come to the planted ones, the book's
    exposure against the planted weighted sum, and the pro-rata rule for a name before it lists."""
    prices, ust, truth = synthetic(seed=seed)
    o = build(prices, ust, meta={"synthetic": True})
    rows, err = [], []
    for b in o["betas"]:
        t = truth[b["name"]]
        rows.append({"name": b["name"], "planted": [round(v, 3) for v in t], "measured": [b[f] for f in FACTORS], "days": b["days"]})
        if b["days"] >= 504:
            err += [abs(b[f] - t[i]) for i, f in enumerate(FACTORS)]
    w = pd.Series(BOOK)
    planted = {f: float(sum(w[k] * truth[k][i] for k in BOOK)) for i, f in enumerate(FACTORS)}
    R = pd.DataFrame({"A": [0.01, 0.02], "B": [np.nan, 0.04]})
    pro = float(book_returns(R, pd.Series({"A": 0.5, "B": 0.5})).iloc[0])
    return {"names": rows, "mean_abs_beta_error": float(np.mean(err)), "max_abs_beta_error": float(np.max(err)),
            "book_exposure": {f: o["exposure"][f] for f in FACTORS}, "planted_exposure": planted,
            "pro_rata_day_before_listing": pro, "es95": o["tail"]["es95"], "short_history_name": rows[-1]["name"]}


def summary(o: dict) -> list[str]:
    """The run in sentences, every number from the run."""
    t, s, k, H = o["tail"]["es95"], o["sizes"], o["keep_names_hedge"], o["hedges"]["policies"]
    lim = {"es_budget": "the expected-shortfall budget", "vol_target": "the volatility target", "drawdown_cap": "the drawdown cap", "gross_cap": "the gross cap"}
    e, c, v = o["exposure"], o["correlation"], o["var_backtest"]
    out = [
        f"Measured on the nine names' own daily prices from {o['from']} to {o['asof']}, the book at 1.00x runs {o['risk']['vol']:.0%} volatility, "
        f"a one-month 95% expected shortfall of {t['governing']:.1%} (the most cautious of historical {t['historical']:.1%}, filtered {t['filtered']:.1%} and "
        f"Student-t {t['student_t']:.1%}) and a one-year 95% drawdown of {o['at_full']['drawdown95']:.0%}, against limits of {o['limits']['es_budget']:.0%}, "
        f"{o['limits']['vol_target']:.0%} and {o['limits']['max_drawdown']:.0%}.",
        f"The limits allow {s['es_budget']:.2f}x (shortfall), {s['vol_target']:.2f}x (volatility) and {s['drawdown_cap']:.2f}x (drawdown); "
        f"{lim[o['binding']]} binds, so the book's size is {o['size']:.2f}x."
        + (f" Keeping every name at full size instead takes a Nasdaq-100 futures short of {k['short_nasdaq_frac']:.0%} of NAV." if k.get("meets_all") else
           " No Nasdaq-100 short alone brings the full-size book inside every limit: the stock-specific risk is too large."),
        f"Exposures: Nasdaq-100 beta {e['market']:.2f} (broad market {e['beta_broad_market']:.2f} now, {e['beta_broad_market_10y']:.2f} over ten years), semis net of the market {e['semis']:+.2f}, "
        f"rates {e['rates']:+.2f}. {o['risk']['variance_share']['market']:.0%} of the variance is the market and {o['risk']['variance_share']['specific']:.0%} is stock-specific: "
        f"effective independent bets {o['risk']['effective_bets']:.1f} of nine.",
        f"Hedges walked forward from {o['hedges']['from']}: a Nasdaq-100 short at the measured beta cut the variance {H['nasdaq_beta']['variance_cut']:.0%} and turned 2022 from "
        f"{H['none']['y2022']:.0%} to {H['nasdaq_beta']['y2022']:+.1%}; the long bond held only when its correlation said it hedged cut it {H['bond_when_it_hedges']['variance_cut']:.0%} "
        f"(2022 {H['bond_when_it_hedges']['y2022']:.0%}), and a standing 30% long bond {H['bond_static_30']['variance_cut']:.0%} (2022 {H['bond_static_30']['y2022']:.0%}).",
        f"Stock-bond correlation (63-day, book against the 20-year bond): {c['book_63d']:+.2f}, state {c['state']}. On the book's worst 5% of days since 2022 the bond "
        f"rose {next((g['bond_up_share'] for g in c['shock'] if g['group'] == '2022 on'), float('nan')):.0%} of the time.",
        f"The one-day 99% VaR, backtested on the book: a normal model at today's volatility was breached {v['normal']['breaches']} times against "
        f"{v['normal']['expected']:.0f} expected (p {v['normal']['p']:.3f}); filtered historical simulation {v['filtered']['breaches']} against {v['filtered']['expected']:.0f} (p {v['filtered']['p']:.2f}).",
    ]
    return out
