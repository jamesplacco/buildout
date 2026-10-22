"""The reality check: every model in the engine states its assumptions, the data test each one, and each conclusion is
re-run in worlds where the assumption fails. A portfolio manager's complaint about quants is that the assumptions that
make a model tractable (normal returns, independent months, stable parameters, stable correlations, no costs, known
parameters, no crowding) are the ones the market breaks; this module measures by how much, and where each model's
conclusion flips.

  tests        fat tails (kurtosis, Jarque-Bera, Hill, 3-sigma months and 5-sigma days against the Gaussian count, the
               normal VaR's understatement), dependence (Ljung-Box on returns and squared returns, the effective sample
               size), stability (a sup-F break test with a simulated p-value, rolling Sharpe and volatility), correlation
               (stock-bond correlation by window and by inflation regime; correlations in stocks' worst months)
  breakpoints  the transaction cost that erases the trend rule's Sharpe gain; the delay that does; the edge error that
               turns full Kelly into over-betting; the stock-bond correlation above which the TLT hedge adds risk
  Taleb        kappa (how fat-tailed, in sample-size terms: 2 minus the log ratio of n to the growth of the mean absolute
               deviation of n-sums; 0 Gaussian, 1 Cauchy) and the months of data needed to match 30 Gaussian ones; the
               Taleb-Douady fragility heuristic (does the loss accelerate in the tail?) for the book and its hedges
  worlds       400 alternative histories by stationary block bootstrap (dependence kept), in which each decision is re-run;
               the share of worlds in which the decision still holds, overall and in inflationary worlds only
  map          which engine model rests on which assumption, and whether it survives
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from . import labs

SEED = 17
TLT_W = 0.30                 # the hedge book's default TLT ratio, x equity
BOOK_VOL = 0.18              # assumed annual volatility of the model book (beta 1.15 to a 16% market)
D_10Y = 7.5                  # modified duration of a 10-year par bond near 5%, for the approximate bond series


def _r(x, d=6):
    return None if x is None or not np.isfinite(x) else round(float(x), d)


def status(ok: bool | None, strained: bool = False) -> str:
    return "holds" if ok else ("strained" if strained else "broken")


# ---------------------------------------------------------------- tests
def tails_test(r: np.ndarray, label: str, per_year: int) -> dict:
    r = r[np.isfinite(r)]
    mu, sd = r.mean(), r.std(ddof=1)
    z = (r - mu) / sd
    k = float(stats.kurtosis(r, fisher=False))
    jb = stats.jarque_bera(r)
    n = len(r)
    thr = 3.0 if per_year == 12 else 5.0
    obs = int(np.sum(np.abs(z) >= thr))
    exp_ = float(n * 2 * stats.norm.sf(thr))
    q = float(np.quantile(r, 0.01))
    var_norm = mu - 2.3263 * sd
    tail = labs.tails(r)
    return {"series": label, "n": n, "kurtosis": k, "jb_p": float(jb.pvalue), "hill_alpha": tail.get("hill_alpha"), "threshold_sd": thr,
            "observed_beyond": obs, "gaussian_expects": exp_, "ratio": obs / exp_ if exp_ > 0 else None, "var99_empirical": q, "var99_normal": var_norm,
            "var_understatement": (q / var_norm - 1) if var_norm < 0 else None, "status": status(k < 4, k < 6)}


def ljung_box(x: np.ndarray, lags: int = 12) -> dict:
    x = x[np.isfinite(x)] - np.nanmean(x)
    n = len(x)
    d = float(x @ x)
    rho = [float(x[k:] @ x[:-k]) / d for k in range(1, lags + 1)]
    Q = n * (n + 2) * sum(r * r / (n - k) for k, r in zip(range(1, lags + 1), rho))
    return {"Q": Q, "p": float(stats.chi2.sf(Q, lags)), "rho1": rho[0]}


def dependence_test(r: np.ndarray) -> dict:
    lb, lb2 = ljung_box(r), ljung_box(r ** 2)
    n = len(r)
    nw = labs.nw_mean(r, lags=12)
    iid_se = r.std(ddof=1) / math.sqrt(n)
    n_eff = n * (iid_se / nw["se"]) ** 2 if nw.get("se") else n
    # Shiller's monthly prices are averages of daily closes, which alone gives a first-order autocorrelation near 0.25
    # (Working 1960); the clustering of volatility (squared returns) is the dependence that is real
    return {"returns": lb, "squared": lb2, "n": n, "n_effective": float(n_eff), "working_rho1": 0.25, "status": status(lb2["p"] > 0.05, False)}


def sup_f(x: np.ndarray, trim: float = 0.15, sims: int = 200, seed: int = SEED) -> dict:
    """Largest Chow F statistic for a break in the mean over all dates in the middle 70%, with a p-value simulated
    under no break (Gaussian, same n)."""
    def stat(v):
        n = len(v)
        c = np.cumsum(v)
        tot = c[-1]
        ss = float(np.sum((v - v.mean()) ** 2))
        best, at = 0.0, 0
        for k in range(int(trim * n), int((1 - trim) * n)):
            m1, m2 = c[k - 1] / k, (tot - c[k - 1]) / (n - k)
            ssr = ss - (k * (m1 - v.mean()) ** 2 + (n - k) * (m2 - v.mean()) ** 2)
            f = (ss - ssr) / (ssr / (n - 2))
            if f > best:
                best, at = f, k
        return best, at
    F, at = stat(x)
    rng = np.random.default_rng(seed)
    null = [stat(rng.standard_normal(len(x)))[0] for _ in range(sims)]
    return {"F": F, "at": at, "p": float(np.mean(np.array(null) >= F))}


def stability_test(r: pd.Series) -> dict:
    x = r.dropna().to_numpy()
    sf = sup_f(x)
    roll = r.rolling(360)
    sh = (roll.mean() / roll.std() * math.sqrt(12)).dropna()
    vol = (r.rolling(120).std() * math.sqrt(12)).dropna()
    return {"sup_f": sf, "break_date": r.dropna().index[sf["at"]].strftime("%Y-%m"), "sharpe30_min": float(sh.min()), "sharpe30_max": float(sh.max()),
            "sharpe30_min_at": sh.idxmin().strftime("%Y-%m"), "sharpe30_max_at": sh.idxmax().strftime("%Y-%m"), "vol10_min": float(vol.min()), "vol10_max": float(vol.max()),
            "status": status(sf["p"] > 0.05 and sh.max() - sh.min() < 0.5, sf["p"] > 0.05)}


def bond_series(S: pd.DataFrame) -> pd.Series:
    """Approximate real monthly return of a 10-year par Treasury from Shiller's long rate: carry minus duration times
    the yield change, less inflation. Labelled approximate wherever shown."""
    y = S["y10"] / 100
    nominal = y.shift(1) / 12 - D_10Y * (y - y.shift(1))
    infl = S["cpi"] / S["cpi"].shift(1) - 1
    return ((1 + nominal) / (1 + infl) - 1).dropna()


def correlation_test(r: pd.Series, b: pd.Series, S: pd.DataFrame, research_latest: dict | None) -> dict:
    j = r.index[r.index.isin(b.index)]
    rr, bb = r.loc[j], b.loc[j]
    c36 = rr.rolling(36).corr(bb).dropna()
    infl36 = (np.log(S["cpi"] / S["cpi"].shift(36)) / 3).reindex(j)
    hi = infl36 >= 0.0275
    out = {"full": float(np.corrcoef(rr, bb)[0, 1]), "share_windows_positive": float(np.mean(c36 > 0)), "low_inflation": float(np.corrcoef(rr[~hi], bb[~hi])[0, 1]),
           "high_inflation": float(np.corrcoef(rr[hi], bb[hi])[0, 1]), "months_high": int(hi.sum()), "window_min": float(c36.min()), "window_max": float(c36.max())}
    if research_latest and research_latest.get("corr") is not None:
        out["now"] = {"corr36": research_latest["corr"], "month": research_latest.get("month"), "source": "research (daily run)"}
    out["status"] = status(out["share_windows_positive"] < 0.2, out["share_windows_positive"] < 0.5)
    return out


def crisis_correlation(series: dict) -> dict:
    """Correlations with stocks in all months and in stocks' worst months (z below -1), from the brain's monthly
    series since 1990."""
    cols, Z = series["cols"], np.array([[np.nan if v is None else v for v in row] for row in series["z"]], float)
    eq = Z[cols.index("eq")]
    bad = eq < -1
    out = {}
    for c in cols:
        if c == "eq":
            continue
        x = Z[cols.index(c)]
        ok = np.isfinite(x) & np.isfinite(eq)
        allc = float(np.corrcoef(eq[ok], x[ok])[0, 1])
        m = ok & bad
        badc = float(np.corrcoef(eq[m], x[m])[0, 1]) if m.sum() > 10 else None
        out[c] = {"all": allc, "worst": badc, "n_worst": int(m.sum())}
    return out


# ---------------------------------------------------------------- breakpoints
def trend_breakpoints(S: pd.DataFrame) -> dict:
    r, px, _ = labs.total_return_index(S)
    px = px.reindex(r.index.union(px.index)).ffill()
    hold = labs.sharpe(r.to_numpy())

    def rule(skip, cost):
        rr, on = labs.ma_rule(px, r, 10, skip=skip)
        sw = on.astype(int).diff().abs().fillna(0).reindex(rr.index).fillna(0).to_numpy()
        return rr.to_numpy() - sw * cost
    by_delay = {str(s): labs.sharpe(rule(s, 0.0)) - hold for s in (1, 2, 3, 4, 6)}
    lo, hi = 0.0, 0.05
    base = labs.sharpe(rule(2, 0.0)) - hold
    if base <= 0:
        be = 0.0
    else:
        for _ in range(60):
            mid = (lo + hi) / 2
            if labs.sharpe(rule(2, mid)) - hold > 0:
                lo = mid
            else:
                hi = mid
        be = (lo + hi) / 2
    _, on = labs.ma_rule(px, r, 10, skip=2)
    switches = float(on.astype(int).diff().abs().sum()) / (len(on) / 12)
    return {"sharpe_gain_by_delay": by_delay, "breakeven_cost": be, "switches_per_year": switches, "hold_sharpe": hold}


def kelly_uncertainty(r: pd.Series, years: int = 30) -> dict:
    """Continuous-time Kelly fraction mu / sigma^2 for real stock returns over cash, from the full record and from every
    30-year window: how far a typical backtest's estimate can sit from the long-run value."""
    x = r.dropna()
    mu, var = x.mean() * 12, x.var() * 12
    full = mu / var
    w = years * 12
    est = [(x.iloc[i:i + w].mean() * 12) / (x.iloc[i:i + w].var() * 12) for i in range(0, len(x) - w + 1, 12)]
    est = np.array(est)
    nw = labs.nw_mean(x.iloc[-w:].to_numpy(), lags=12)
    mu30, se30 = x.iloc[-w:].mean() * 12, nw["se"] * 12
    v30 = x.iloc[-w:].var() * 12
    return {"full": full, "window_years": years, "min": float(est.min()), "max": float(est.max()), "share_over_2x": float(np.mean(est > 2 * full)),
            "share_below_half": float(np.mean(est < 0.5 * full)), "last_window": float(mu30 / v30), "last_window_ci90": [float((mu30 - 1.645 * se30) / v30), float((mu30 + 1.645 * se30) / v30)]}


def hedge_breakpoint(S: pd.DataFrame, research_latest: dict | None) -> dict:
    """Adding w of a long bond to a book lowers variance only if corr < -w sigma_b / (2 sigma_e)."""
    y = (S["y10"] / 100).dropna()
    dy_sd = float(y.diff().std() * math.sqrt(12))
    from .reasoner import DEFAULTS
    sig_b = DEFAULTS["tlt_duration"] * dy_sd
    rho_star = -TLT_W * sig_b / (2 * BOOK_VOL)
    now = research_latest.get("corr") if research_latest else None
    return {"weight": TLT_W, "sigma_bond": sig_b, "sigma_book": BOOK_VOL, "rho_star": rho_star, "now": now,
            "status": None if now is None else status(now < rho_star, now < 0)}


def multiple_testing(L: dict | None) -> dict | None:
    if not L:
        return None
    rows = L["multiple_testing"]["rows"]
    return {"n": len(rows), "p05": sum(1 for x in rows if x["p"] < 0.05), "t3": sum(1 for x in rows if x["p"] < 0.0027), "holm": sum(1 for x in rows if x["holm"] < 0.05)}


# ---------------------------------------------------------------- Taleb
def kappa(x: np.ndarray, n: int = 30, n0: int = 1, draws: int = 4000, seed: int = SEED) -> dict:
    """Taleb's kappa between n0 and n: 2 - (log n - log n0) / log(M(n) / M(n0)), M(n) the mean absolute deviation of a
    sum of n independent draws (here resampled from the data). 0 for the Gaussian, 1 for the Cauchy. From
    M(n)/M(1) = n^(1/(2 - kappa)), matching the sample mean's error of n_g Gaussian draws takes
    n = n_g^((2 - kappa) / (2 (1 - kappa))) draws."""
    x = x[np.isfinite(x)]
    x = x - x.mean()
    rng = np.random.default_rng(seed)

    def M(k):
        s = x[rng.integers(0, len(x), size=(draws, k))].sum(axis=1)
        return float(np.mean(np.abs(s - s.mean())))
    m0, mn = M(n0), M(n)
    k = 2 - (math.log(n) - math.log(n0)) / math.log(mn / m0) if mn > m0 else 1.0
    k = max(0.0, min(0.999, k))
    neq = 30 ** ((2 - k) / (2 * (1 - k)))
    return {"kappa": k, "n": n, "n_equivalent_30": neq}


def fragility() -> dict:
    """Taleb-Douady heuristic on the hedge book's own pricing: the book's P&L f(m) for an index move m over three months
    (the AI basket moving 0.8 m), and H = (f(-s - d) + f(-s + d)) / 2 - f(-s). Negative H means
    losses accelerate in the tail (fragile); positive means they slow (antifragile there). Reported at stress levels
    s = 5% to 30% with d = 5%."""
    from .hedgebook import _P, book_pnl, hedge_pnl, option_costs
    P = _P(None)
    costs = option_costs(P)
    e = 1.0
    structs = {"unhedged": {}, "put_spread": {"put_spread": 0.01}, "collar": {"collar": 0.5}, "vix_calls": {"vix_calls": 0.005},
               "levered_1_5x": "lev", "short_put": "short_put"}
    from .analytics.options import bs
    put90 = bs(1.0, 0.90, P["horizon"], 0.0, 0.0, P["vix"] / 100 + 0.03, "put")["price"]

    def f(m, on):
        s = {"market": m, "ai": 0.8 * m, "dy": 0.0, "oil": 0.0, "gold": 0.0}
        if on == "lev":
            return book_pnl(1.5, s, P)
        if on == "short_put":                                       # selling 90 puts on the whole book for income
            return book_pnl(e, s, P) + e * (put90 - max(0.0, 0.90 - (1 + m)))
        return book_pnl(e, s, P) + sum(hedge_pnl(h, x, e, s, P, costs) for h, x in on.items())
    grid = [round(-0.40 + 0.05 * i, 2) for i in range(13)]
    out = {}
    for k, on in structs.items():
        curve = [f(m, on) for m in grid]
        Hs = {f"{x:.2f}": (f(-x - 0.05, on) + f(-x + 0.05, on)) / 2 - f(-x, on) for x in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)}
        worst = min(Hs, key=lambda k: Hs[k])
        accel = f(-0.30, on) / f(-0.15, on) if f(-0.15, on) < 0 else None
        out[k] = {"H": Hs, "H_min": Hs[worst], "at": worst, "accel": accel, "curve": curve,
                  "verdict": ("convex, then fragile" if max(Hs.values()) > 1e-4 else "fragile") if Hs[worst] < -1e-4 else ("convex" if max(Hs.values()) > 1e-4 else "linear")}
    return {"grid": grid, "structures": out, "d": 0.05}


# ---------------------------------------------------------------- stressed worlds
def worlds(r: pd.Series, b: pd.Series, S: pd.DataFrame, n: int = 400, block: int = 12, seed: int = SEED, cost: float = 0.001) -> dict:
    """Alternative histories by stationary block bootstrap of the joint monthly (stock, bond, inflation) record. In each,
    the trend rule (acting a month late, 10bp a switch, on the total-return index) against holding, and a 60/40
    stock-bond mix against all stocks. Then the same in worlds drawn only from inflationary months."""
    j = r.index[r.index.isin(b.index)]
    infl36 = (np.log(S["cpi"] / S["cpi"].shift(36)) / 3).reindex(j)
    R, B = r.loc[j].to_numpy(), b.loc[j].to_numpy()
    rng = np.random.default_rng(seed)
    T = 600

    def boot(m):
        """T positions in 0..m-1 by stationary bootstrap: blocks of geometric length (mean `block`), wrapping."""
        out = np.empty(T, dtype=int)
        out[0] = rng.integers(0, m)
        jump = rng.random(T) < 1.0 / block
        to = rng.integers(0, m, T)
        for t in range(1, T):
            out[t] = to[t] if jump[t] else (out[t - 1] + 1) % m
        return out

    def one(pool):
        sel = pool[boot(len(pool))]
        rs, bs = R[sel], B[sel]
        tri = np.cumprod(1 + rs)
        ma = pd.Series(tri).rolling(10).mean().to_numpy()
        on = np.zeros(T, bool)
        on[2:] = (tri[:-2] > ma[:-2])
        sw = np.abs(np.diff(on.astype(int), prepend=0))
        rule = np.where(on, rs, 0.0) - sw * cost
        mix = 0.6 * rs + 0.4 * bs
        dd = lambda x: float(labs.drawdown(np.cumprod(1 + x)).min())  # noqa: E731
        return (labs.sharpe(rule) > labs.sharpe(rs), dd(rule) > dd(rs), labs.sharpe(mix) > labs.sharpe(rs), float(np.corrcoef(rs, bs)[0, 1]),
                dd(mix) > dd(rs))
    allpool = np.arange(len(j))
    hipool = np.where(infl36.to_numpy() >= 0.04)[0]
    A = np.array([one(allpool) for _ in range(n)], float)
    Hh = np.array([one(hipool) for _ in range(n)], float) if len(hipool) > 60 else None
    res = {"n": n, "block": block, "months": T, "cost": cost,
           "all": {"trend_sharpe": float(A[:, 0].mean()), "trend_dd": float(A[:, 1].mean()), "mix_sharpe": float(A[:, 2].mean()), "corr_median": float(np.median(A[:, 3])), "mix_dd": float(A[:, 4].mean())}}
    if Hh is not None:
        res["inflation"] = {"trend_sharpe": float(Hh[:, 0].mean()), "trend_dd": float(Hh[:, 1].mean()), "mix_sharpe": float(Hh[:, 2].mean()), "corr_median": float(np.median(Hh[:, 3])),
                            "mix_dd": float(Hh[:, 4].mean()), "pool_months": int(len(hipool))}
    return res


# ---------------------------------------------------------------- the map
def model_map(c: dict) -> list[dict]:
    """Each engine model, what it assumes, and whether the data let the assumption stand."""
    st = lambda k: c[k]["status"]  # noqa: E731
    rows = [
        {"model": "Value at risk and the Sharpe ratio", "where": "analytics/risk.py, labs.py", "assumes": ["normal returns", "independent months"], "checks": ["tails_month", "dependence"],
         "consequence": f"A normal 1-in-100 month understates the empirical one by {abs(c['tails_month']['var_understatement'] or 0):.0%}; the engine reports historical and fat-tailed VaR beside it."},
        {"model": "The 10-month trend rule", "where": "labs.py trend_lab", "assumes": ["no costs", "no delay", "stable parameters"], "checks": ["trend", "stability"],
         "consequence": f"Its Sharpe gain is gone at {c['trend']['breakeven_cost'] * 1e4:.0f} basis points a switch and vanishes with longer delays."},
        {"model": "Kelly sizing", "where": "decisions.py, games2.py", "assumes": ["known edge", "stable parameters"], "checks": ["kelly"],
         "consequence": f"30-year windows put the Kelly fraction anywhere from {c['kelly']['min']:.1f} to {c['kelly']['max']:.1f} times capital, and monthly-averaged prices understate volatility, so every one of them is too high. Size at half or less."},
        {"model": "The TLT hedge", "where": "research.py, hedgebook.py", "assumes": ["negative stock-bond correlation"], "checks": ["hedge", "correlation"],
         "consequence": f"A {c['hedge']['weight']:.0%} TLT sleeve adds variance once the correlation is above {c['hedge']['rho_star']:+.2f}" + (f"; it is {c['hedge']['now']:+.2f} now." if c['hedge']['now'] is not None else ".")},
        {"model": "The brain's linear links (structural VAR)", "where": "atlas.py, brain.py", "assumes": ["stable parameters", "linear links", "no hidden causes"], "checks": ["stability", "crisis"],
         "consequence": "Links are learned on 1990 onward and re-estimated monthly; robustness values say how strong a hidden cause must be to erase each one."},
        {"model": "Valuation regressions (CAPE)", "where": "labs.py valuation_lab", "assumes": ["stable parameters", "earnings known when used"], "checks": ["stability"],
         "consequence": "Judged only out of sample with a four-month earnings lag; a decade tool, not a timing tool."},
        {"model": "Machine-learning forecasts", "where": "ml.py", "assumes": ["the past resembles the future", "enough independent data"], "checks": ["ml", "dependence", "kappa"],
         "consequence": "Out of sample against the historical mean, with purged validation and the probability of backtest overfitting shown beside every number."},
        {"model": "Black-Scholes option prices", "where": "analytics/options.py, hedgebook.py", "assumes": ["normal returns", "constant volatility"], "checks": ["tails_day", "garch"],
         "consequence": "Puts are priced with a skew add-on and stress scenarios, never at one flat volatility."},
        {"model": "The mind's evidence weights", "where": "mind.py", "assumes": ["reliabilities set by hand", "families are independent"], "checks": [],
         "consequence": "Every weight is shown, every verdict comes with a leave-one-family-out range and its hinge; the weights are not yet learned from outcomes."},
    ]
    for r in rows:
        ss = [st(k) for k in r["checks"] if k in c and isinstance(c[k], dict) and c[k].get("status")]
        r["statuses"] = ss
        r["verdict"] = "broken" if "broken" in ss else ("strained" if "strained" in ss else ("holds" if ss else "untested"))
    return rows


def build(dl: dict | None = None, L: dict | None = None, mlo: dict | None = None, research_latest: dict | None = None, brain_series: dict | None = None,
          n_worlds: int = 400) -> dict:
    dl = dl or labs.download()
    S = labs.shiller(dl)
    r, _, _ = labs.total_return_index(S)
    b = bond_series(S)
    c = {}
    c["tails_month"] = tails_test(r.to_numpy(), "S&P 500 real total return, monthly since 1871", 12)
    br = labs.daily(dl, "brent")
    if len(br) > 500:
        c["tails_day"] = tails_test(np.diff(np.log(br.to_numpy())), "Brent, daily since 1987", 252)
    c["dependence"] = dependence_test(r.to_numpy())
    c["stability"] = stability_test(r)
    c["correlation"] = correlation_test(r, b, S, research_latest)
    if brain_series:
        cc = crisis_correlation(brain_series)
        c["crisis"] = {"series": cc, "status": status(all((v["worst"] or 0) - v["all"] < 0.2 for v in cc.values()), True)}
    c["trend"] = trend_breakpoints(S)
    c["trend"]["status"] = status(c["trend"]["breakeven_cost"] > 0.005, c["trend"]["breakeven_cost"] > 0.001)
    c["kelly"] = kelly_uncertainty(r)
    c["kelly"]["status"] = "broken" if c["kelly"]["share_over_2x"] > 0.25 else ("strained" if c["kelly"]["max"] / max(c["kelly"]["min"], 1e-9) > 2 else "holds")
    c["hedge"] = hedge_breakpoint(S, research_latest)
    c["testing"] = multiple_testing(L)
    if L:
        vb = L["volatility"].get("brent", {})
        c["garch"] = {"persistence": vb.get("persistence"), "status": status(False, True)}
    ks = {"S&P 500, monthly": r.to_numpy()}
    if len(br) > 500:
        ks["Brent, daily"] = np.diff(np.log(br.to_numpy()))
    gs = labs.daily(dl, "gas")
    if len(gs) > 500:
        ks["Henry Hub gas, daily"] = np.diff(np.log(gs.to_numpy()))
    vx = labs.daily(dl, "vix")
    if len(vx) > 500:
        ks["VIX, daily change"] = np.diff(np.log(vx.to_numpy()))
    rng_g = np.random.default_rng(SEED).standard_normal(20000)
    ks["Gaussian (check)"] = rng_g
    c["kappa"] = {"series": {k: kappa(v) for k, v in ks.items()}}
    c["kappa"]["status"] = status(c["kappa"]["series"]["S&P 500, monthly"]["kappa"] < 0.1, c["kappa"]["series"]["S&P 500, monthly"]["kappa"] < 0.3)
    if mlo:
        sk = mlo["return"]["scores"]["ensemble"]["skill"]
        c["ml"] = {"skill": sk, "pbo": mlo["return"]["cpcv"]["pbo"], "novelty_pct": mlo["shift"]["novelty_pct"], "status": status(sk > 0, sk > -0.05)}
    c["fragility"] = fragility()
    c["worlds"] = worlds(r, b, S, n=n_worlds)
    out = {"schema": 1, "checks": c, "map": model_map(c)}
    out["findings"] = summary(out)
    return out


def summary(o: dict) -> list[str]:
    c = o["checks"]
    t, k, h, w = c["tails_month"], c["kelly"], c["hedge"], c["worlds"]
    f = [f"Normal returns: monthly stocks show {t['observed_beyond']} moves beyond 3 standard deviations where a bell curve expects {t['gaussian_expects']:.1f}; "
         f"the normal 1-in-100 month understates the real one by {abs(t['var_understatement']):.0%}."]
    if "tails_day" in c:
        d = c["tails_day"]
        f.append(f"Brent has {d['observed_beyond']} daily moves beyond 5 standard deviations where a bell curve expects {d['gaussian_expects']:.2f}.")
    ksp = c["kappa"]["series"]["S&P 500, monthly"]
    f.append(f"Taleb's kappa for monthly stocks is {ksp['kappa']:.2f}: matching what 30 Gaussian months reveal about the mean takes about {ksp['n_equivalent_30']:.0f} months.")
    f.append(f"The trend rule's Sharpe gain disappears at {c['trend']['breakeven_cost'] * 1e4:.0f} basis points a switch, and by a four-month delay.")
    f.append(f"Kelly sizing on stocks from a 30-year backtest ranged from {k['min']:.1f} to {k['max']:.1f} times capital depending on which 30 years: the edge is not known well enough to bet full Kelly.")
    if h["now"] is not None:
        f.append(f"The TLT hedge adds risk above a stock-bond correlation of {h['rho_star']:+.2f}; the latest 36-month reading is {h['now']:+.2f}.")
    if "inflation" in w:
        f.append(f"In {w['n']} bootstrapped histories a 60/40 mix beats all stocks on Sharpe {w['all']['mix_sharpe']:.0%} of the time; in histories drawn from inflationary months, {w['inflation']['mix_sharpe']:.0%}.")
    return f


# ---------------------------------------------------------------- the PM's triage: a quant's backtest, after reality
DECAY_OOS = 0.26     # McLean and Pontiff (2016): anomaly returns 26% lower out of sample
DECAY_PUB = 0.58     # and 58% lower after publication
EULER = 0.5772156649015329


def _emax_z(n: int) -> float:
    """Expected maximum of n independent standard normals (Bailey and Lopez de Prado's approximation)."""
    if n <= 1:
        return 0.0
    return (1 - EULER) * float(stats.norm.ppf(1 - 1 / n)) + EULER * float(stats.norm.ppf(1 - 1 / (n * math.e)))


def triage(sharpe: float, years: float, trials: int = 1, periods: int = 12, skew: float = 0.0, kurt: float = 3.0, published: bool = False,
           cost_bps: float = 0.0, turns: float = 0.0, vol: float = 0.15, trial_sd: float | None = None) -> dict:
    """What a backtested annual Sharpe is worth after the four things that usually break it: trading costs (cost_bps a
    trade, turns trades a year, on a strategy with annual volatility vol), decay out of sample or after publication
    (McLean and Pontiff), luck across the variants tried (the deflated Sharpe ratio: the chance the true Sharpe beats
    the best of trials skill-less tries whose annual Sharpes spread by trial_sd), and too little data (the minimum
    backtest length for that many tries). Kurtosis is raw (3 for a bell curve). trial_sd defaults to the sampling
    noise of an annual Sharpe estimated over the backtest, 1/sqrt(years): how far skill-less variants scatter."""
    n = max(2, int(round(years * periods)))
    if trial_sd is None:
        trial_sd = 1 / math.sqrt(max(years, 1e-9))
    drag = cost_bps / 1e4 * turns / vol if vol > 0 else 0.0
    net = sharpe - drag
    decay = DECAY_PUB if published else DECAY_OOS
    live = net * (1 - decay)
    srp = net / math.sqrt(periods)
    den = math.sqrt(max(1 - skew * srp + (kurt - 1) / 4 * srp ** 2, 1e-12))
    psr = float(stats.norm.cdf(srp * math.sqrt(n - 1) / den))
    emax = trial_sd / math.sqrt(periods) * _emax_z(trials)
    dsr = float(stats.norm.cdf((srp - emax) * math.sqrt(n - 1) / den))
    minbtl = (_emax_z(trials) / sharpe) ** 2 if trials > 1 and sharpe > 0 else 0.0
    verdict = "credible" if dsr >= 0.95 and years >= minbtl and live > 0.3 else ("doubtful" if dsr >= 0.5 and live > 0 else "likely noise")
    return {"sharpe": sharpe, "cost_drag": drag, "net": net, "decay": decay, "live": live, "psr": psr, "dsr": dsr, "emax_annual": emax * math.sqrt(periods),
            "minbtl_years": minbtl, "enough_data": years >= minbtl, "n": n, "trial_sd": trial_sd, "verdict": verdict}
