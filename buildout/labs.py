"""The labs: every claim a trader repeats, tested on the longest data the engine can read, with the statistics that keep
a lucky backtest from passing for an edge. Python is canonical; the page renders labs.json (or snap14.js).

    python -m buildout labs --out site/data

Data (GitHub mirrors of public datasets, no key): Shiller's monthly S&P 500 with dividends, earnings and CPI from 1871;
daily Brent (1987), WTI (1986), Henry Hub gas (1997) and the VIX (1990); monthly gold. Raw data never enters the repo.

  indicators     the textbook definitions: simple and exponential moving averages, Wilder's RSI (1978), Appel's MACD,
                 Bollinger bands, rate of change, drawdown, realized volatility, the 50/200-day cross
  trend          the 10-month moving average rule (about 200 trading days; Faber 2007) on 155 years of the S&P 500, by
                 era, with a stationary-bootstrap interval for the Sharpe difference; then all 22 lengths from 3 to 24
                 months at once, a bootstrap of the best one under the null (Sullivan, Timmermann and White 1999 in
                 spirit) and the deflated Sharpe ratio (Bailey and Lopez de Prado 2014), because the best of 22 tries
                 always looks good
  oscillators    RSI, MACD and the golden cross: does the signal change the next period's return? Conditional means with
                 Newey-West t-statistics on monthly stocks and daily oil, gas and the VIX, then Holm and
                 Benjamini-Hochberg corrections across every test
  valuation      CAPE (Campbell and Shiller), trailing P/E, dividend yield and the Fed-model gap against the next ten
                 years' real total return: overlapping regressions with Newey-West (120 lags), out-of-sample R squared
                 against the historical mean (Campbell and Thompson 2008), and today's implied return with an 80% range
  regimes        a two-state Markov-switching model of monthly returns (Hamilton 1989) by EM with the Hamilton filter
                 and Kim smoother: each regime's mean, volatility and expected duration, and today's probabilities
  volatility     GARCH(1,1) (Bollerslev 1986) by maximum likelihood on daily oil and gas: persistence, half-life, long-run
                 and current volatility; fat tails by kurtosis, Jarque-Bera and the Hill tail index
  spreads        Brent and WTI: Engle-Granger cointegration with a simulated p-value, the hedge ratio, the half-life of
                 the spread and today's z-score; gold to oil
  randomness     Lo-MacKinlay variance ratios with heteroskedasticity-robust z: momentum (above 1) or mean reversion
  calendar       "Sell in May" since 1871 and since 1950, and gas's seasonal shape, each with Newey-West errors
Every p-value goes into one multiple-testing table at the end.
"""
from __future__ import annotations

import io
import math

import numpy as np
import pandas as pd
from scipy import optimize, stats

from .data import http

RAW = "https://raw.githubusercontent.com/datasets/{}"
FILES = {"shiller": "s-and-p-500/main/data/data.csv", "cpi": "cpi-us/main/data/cpiai.csv", "brent": "oil-prices/main/data/brent-daily.csv",
         "wti": "oil-prices/main/data/wti-daily.csv", "gas": "natural-gas/main/data/daily.csv", "vix": "finance-vix/main/data/vix-daily.csv",
         "gold": "gold-prices/main/data/monthly.csv"}


def download() -> dict:
    raw, failed = {}, {}
    for k, p in FILES.items():
        try:
            raw[k] = pd.read_csv(io.BytesIO(http.get(RAW.format(p), user_agent="buildout-labs")))
        except Exception as exc:
            failed[k] = str(exc)[:160]
    return {"raw": raw, "failed": failed}


# ---------------------------------------------------------------- indicators (textbook definitions)
def sma(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def ema(x: np.ndarray, n: int) -> np.ndarray:
    """Exponential moving average with alpha = 2 / (n + 1), seeded with the first n-period simple average."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    a = 2.0 / (n + 1)
    out[n - 1] = x[:n].mean()
    for t in range(n, len(x)):
        out[t] = a * x[t] + (1 - a) * out[t - 1]
    return out


def rsi(x: np.ndarray, n: int = 14) -> np.ndarray:
    """Wilder's relative strength index: average gain over average loss, smoothed with alpha = 1/n."""
    x = np.asarray(x, float)
    d = np.diff(x)
    out = np.full(len(x), np.nan)
    if len(d) < n:
        return out
    up, dn = np.maximum(d, 0), np.maximum(-d, 0)
    au, ad = up[:n].mean(), dn[:n].mean()
    out[n] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
    for t in range(n, len(d)):
        au = (au * (n - 1) + up[t]) / n
        ad = (ad * (n - 1) + dn[t]) / n
        out[t + 1] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
    return out


def macd(x: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    line = ema(x, fast) - ema(x, slow)
    sig = np.full(len(x), np.nan)
    ok = ~np.isnan(line)
    if ok.sum() >= signal:
        sig[ok] = ema(line[ok], signal)
    return line, sig, line - sig


def bollinger(x: np.ndarray, n: int = 20, k: float = 2.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.asarray(x, float)
    m = sma(x, n)
    sd = pd.Series(x).rolling(n).std(ddof=0).to_numpy()
    return m - k * sd, m, m + k * sd


def drawdown(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, float)
    return x / np.maximum.accumulate(x) - 1


# ---------------------------------------------------------------- statistics helpers
def nw_mean(x: np.ndarray, lags: int | None = None) -> dict:
    """Mean with a Newey-West standard error (Bartlett kernel)."""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return {"mean": float("nan"), "se": float("nan"), "t": float("nan"), "p": float("nan"), "n": n}
    L = int(math.floor(4 * (n / 100) ** (2 / 9))) if lags is None else lags
    e = x - x.mean()
    s = float(e @ e) / n
    for l in range(1, L + 1):
        s += 2 * (1 - l / (L + 1)) * float(e[l:] @ e[:-l]) / n
    se = math.sqrt(max(s, 1e-18) / n)
    t = x.mean() / se
    return {"mean": float(x.mean()), "se": se, "t": float(t), "p": float(2 * stats.norm.sf(abs(t))), "n": n}


def nw_ols(y: np.ndarray, X: np.ndarray, lags: int) -> dict:
    n = len(y)
    A = np.column_stack([np.ones(n), X])
    G = np.linalg.pinv(A.T @ A)
    b = G @ A.T @ y
    e = y - A @ b
    U = A * e[:, None]
    S = U.T @ U
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        Gl = U[l:].T @ U[:-l]
        S += w * (Gl + Gl.T)
    V = G @ S @ G
    se = np.sqrt(np.maximum(np.diag(V), 0))
    r2 = 1 - float(e @ e) / float(((y - y.mean()) ** 2).sum())
    return {"b": b, "se": se, "t": b / np.where(se > 0, se, np.nan), "r2": r2, "resid": e}


def stationary_bootstrap_idx(n: int, B: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis and Romano (1994): blocks of geometric length with mean `mean_block`, wrapping around."""
    p = 1.0 / mean_block
    idx = np.empty((B, n), dtype=int)
    start = rng.integers(0, n, size=B)
    idx[:, 0] = start
    newb = rng.random((B, n)) < p
    jumps = rng.integers(0, n, size=(B, n))
    for t in range(1, n):
        idx[:, t] = np.where(newb[:, t], jumps[:, t], (idx[:, t - 1] + 1) % n)
    return idx


def sharpe(r: np.ndarray, per_year: int = 12) -> float:
    r = np.asarray(r, float)
    sd = r.std(ddof=1)
    return float(r.mean() / sd * math.sqrt(per_year)) if sd > 0 else float("nan")


def deflated_sharpe(sr_best: float, n_trials: int, var_trials: float, T: int, skew: float, kurt: float) -> dict:
    """Bailey and Lopez de Prado (2014). sr_* are per-period (not annualized). Returns DSR = P(true SR > SR0), where
    SR0 is the expected maximum of n_trials Sharpe ratios under the null."""
    g = 0.5772156649
    z1, z2 = stats.norm.ppf(1 - 1 / n_trials), stats.norm.ppf(1 - 1 / (n_trials * math.e))
    sr0 = math.sqrt(max(var_trials, 0)) * ((1 - g) * z1 + g * z2)
    den = math.sqrt(max(1 - skew * sr_best + (kurt - 1) / 4 * sr_best ** 2, 1e-12))
    z = (sr_best - sr0) * math.sqrt(T - 1) / den
    return {"sr0": sr0, "dsr": float(stats.norm.cdf(z)), "z": float(z)}


def holm(p: list[float]) -> list[float]:
    p = np.asarray(p, float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    run = 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (m - k) * p[i]))
        adj[i] = run
    return adj.tolist()


def bh(p: list[float]) -> list[float]:
    p = np.asarray(p, float)
    m = len(p)
    order = np.argsort(p)[::-1]
    adj = np.empty(m)
    run = 1.0
    for k, i in enumerate(order):
        rank = m - k
        run = min(run, p[i] * m / rank)
        adj[i] = run
    return adj.tolist()


# ---------------------------------------------------------------- data shaping
def shiller(dl: dict) -> pd.DataFrame:
    """Monthly S&P 500 price, dividends, earnings, CPI and long rate; CPI extended from BLS where Shiller stops."""
    s = dl["raw"]["shiller"].copy()
    s["Date"] = pd.to_datetime(s["Date"])
    s = s.set_index("Date").rename(columns={"SP500": "px", "Dividend": "div", "Earnings": "eps", "Consumer Price Index": "cpi", "Long Interest Rate": "y10", "PE10": "cape_pub"})
    for c in ("div", "eps", "cpi", "y10", "cape_pub"):
        s.loc[s[c] <= 0, c] = np.nan
    if "cpi" in dl["raw"]:
        c = dl["raw"]["cpi"].copy()
        c.index = pd.to_datetime(c["Date"]).dt.to_period("M").dt.to_timestamp()
        bls = c["Index"].astype(float)
        last = s["cpi"].last_valid_index()
        if last is not None and last in bls.index:
            ratio = s.loc[last, "cpi"] / bls.loc[last]
            ext = bls.loc[last:].iloc[1:] * ratio
            s.loc[ext.index[ext.index.isin(s.index)], "cpi"] = ext.reindex(s.index).dropna()
    s["cpi"] = s["cpi"].ffill()
    return s[["px", "div", "eps", "cpi", "y10", "cape_pub"]]


def daily(dl: dict, key: str) -> pd.Series:
    d = dl["raw"].get(key)
    if d is None:
        return pd.Series(dtype=float)
    dc = "DATE" if "DATE" in d.columns else "Date"
    vc = "CLOSE" if "CLOSE" in d.columns else "Price"
    s = pd.Series(pd.to_numeric(d[vc], errors="coerce").to_numpy(), index=pd.to_datetime(d[dc])).dropna()
    return s[s > 0].sort_index()


# ---------------------------------------------------------------- trend
def total_return_index(S: pd.DataFrame, div_fill: float | None = None) -> tuple[pd.Series, pd.Series, dict]:
    """Monthly real total return of the S&P 500 (price change plus a twelfth of the dividend), and cash at zero real.
    Where Shiller's dividends stop, the last dividend yield is carried (Assumed)."""
    px, dv, cpi = S["px"], S["div"].copy(), S["cpi"]
    last = dv.last_valid_index()
    dy = float((dv / px).loc[last])
    dv = dv.where(dv.notna(), px * dy)
    nominal = (px + dv / 12) / px.shift(1) - 1
    real = (1 + nominal) / (cpi / cpi.shift(1)) - 1
    return real.dropna(), px, {"dividends_to": last.strftime("%Y-%m"), "carried_yield": dy}


def ma_rule(px: pd.Series, r: pd.Series, n: int, skip: int = 1) -> pd.Series:
    """Hold when the price was above its n-month simple average `skip` months earlier; otherwise cash (0 real).
    Shiller's prices are monthly averages of daily closes, which by itself gives returns a first-order autocorrelation
    of about 0.25 (Working 1960) and flatters any rule that acts the next month; skip = 2 waits one month more, which
    removes that artifact. Both are reported; the corrected one is the honest test."""
    m = pd.Series(sma(px.to_numpy(), n), index=px.index)
    on = (px > m).shift(skip).reindex(r.index).fillna(False).astype(bool)
    return r.where(on, 0.0), on


def perf(r: pd.Series) -> dict:
    r = r.dropna()
    w = (1 + r).cumprod()
    yrs = len(r) / 12
    return {"cagr": float(w.iloc[-1] ** (1 / yrs) - 1), "vol": float(r.std() * math.sqrt(12)), "sharpe": sharpe(r.to_numpy()),
            "maxdd": float(drawdown(w.to_numpy()).min()), "months": int(len(r))}


def trend_lab(S: pd.DataFrame, B: int = 1000, seed: int = 5, skip: int = 2) -> dict:
    r, px, notes = total_return_index(S)
    px = px.reindex(r.index.union(px.index)).ffill()
    naive, _ = ma_rule(px, r, 10, skip=1)
    rule, on = ma_rule(px, r, 10, skip=skip)
    switches = int((on.astype(int).diff().abs() == 1).sum())
    eras = {"1871 to 1945": ("1871", "1945"), "1946 to 1999": ("1946", "1999"), "2000 to now": ("2000", "2100")}
    by_era = {k: {"rule": perf(rule.loc[a:b]), "hold": perf(r.loc[a:b])} for k, (a, b) in eras.items()}
    # bootstrap the Sharpe difference (rule minus hold) keeping months paired
    rng = np.random.default_rng(seed)
    x, y = rule.to_numpy(), r.to_numpy()
    idx = stationary_bootstrap_idx(len(x), B, 12, rng)
    d = np.array([sharpe(x[i]) - sharpe(y[i]) for i in idx])
    dd = np.array([drawdown(np.cumprod(1 + x[i])).min() - drawdown(np.cumprod(1 + y[i])).min() for i in idx[:300]])
    # all lengths at once, and the best one judged against the best of 22 under the null
    lengths = list(range(3, 25))
    srs, excess = {}, []
    for n in lengths:
        rn, _ = ma_rule(px, r, n, skip=skip)
        srs[n] = sharpe(rn.to_numpy())
        excess.append(rn.to_numpy() - y)
    E = np.array(excess)                      # variants x months: rule minus hold
    best = max(lengths, key=lambda n: srs[n])
    obs_max = max(float(np.mean(e)) for e in E)
    cen = E - E.mean(axis=1, keepdims=True)    # the null: no variant beats holding
    maxes = np.array([cen[:, i].mean(axis=1).max() for i in idx[:500]])
    p_spa = float(np.mean(maxes >= obs_max))
    # deflated Sharpe of the best variant's excess over holding: is beating buy-and-hold more than the luck of 22 tries?
    ex_sr = np.array([e.mean() / e.std(ddof=1) for e in E])
    bi = lengths.index(best)
    eb = E[bi]
    ds = deflated_sharpe(float(ex_sr[bi]), len(lengths), float(np.var(ex_sr, ddof=1)), len(eb), float(stats.skew(eb)), float(stats.kurtosis(eb, fisher=False)))
    ds["excess_sharpe_annual"] = float(ex_sr[bi] * math.sqrt(12))
    ma10 = sma(px.to_numpy(), 10)
    return {"full": {"rule": perf(rule), "hold": perf(r), "naive": perf(naive)}, "skip": skip, "eras": by_era, "switches": switches, "years": len(r) / 12, "in_market": float(on.mean()),
            "sharpe_diff": {"est": float(sharpe(x) - sharpe(y)), "lo": float(np.quantile(d, 0.05)), "hi": float(np.quantile(d, 0.95)), "p_le0": float(np.mean(d <= 0))},
            "maxdd_diff": {"lo": float(np.quantile(dd, 0.05)), "hi": float(np.quantile(dd, 0.95))},
            "lengths": {str(n): srs[n] for n in lengths}, "best": best, "spa_p": p_spa, "deflated": ds,
            "now": {"date": px.index[-1].strftime("%Y-%m"), "price": float(px.iloc[-1]), "ma10": float(ma10[-1]), "above": bool(px.iloc[-1] > ma10[-1]),
                    "gap": float(px.iloc[-1] / ma10[-1] - 1)}, "notes": notes,
            "curve": {"dates": [d.strftime("%Y-%m") for d in r.index[::6]], "hold": [round(float(v), 4) for v in np.log((1 + r).cumprod()).iloc[::6]],
                      "rule": [round(float(v), 4) for v in np.log((1 + rule).cumprod()).iloc[::6]]}}


# ---------------------------------------------------------------- oscillators and signal tests
def forward(x: np.ndarray, h: int) -> np.ndarray:
    """Log return over the next h periods, aligned to today."""
    lx = np.log(x)
    out = np.full(len(x), np.nan)
    out[:-h] = lx[h:] - lx[:-h]
    return out


def signal_test(name: str, asset: str, x: np.ndarray, sig: np.ndarray, h: int, per_year: int, skip: int = 0) -> dict:
    """Forward h-period return when the signal is on, minus when it is off, with Newey-West errors (h - 1 + 4 lags,
    for the overlap)."""
    f = forward(x, h)
    if skip:
        f = np.concatenate([f[skip:], np.full(skip, np.nan)])     # act one period later (averaged prices)
    ok = ~np.isnan(f) & ~np.isnan(sig.astype(float))
    on = sig.astype(bool) & ok
    off = ~sig.astype(bool) & ok
    if on.sum() < 20 or off.sum() < 20:
        return {"name": name, "asset": asset, "h": h, "n_on": int(on.sum()), "skipped": True}
    y = f[ok]
    X = on[ok].astype(float)
    reg = nw_ols(y, X[:, None], lags=h - 1 + 4)
    return {"name": name, "asset": asset, "h": h, "n_on": int(on.sum()), "n_off": int(off.sum()), "on_mean": float(f[on].mean()), "off_mean": float(f[off].mean()),
            "diff": float(reg["b"][1]), "t": float(reg["t"][1]), "p": float(2 * stats.norm.sf(abs(reg["t"][1]))), "per_year": per_year}


def oscillator_lab(S: pd.DataFrame, dailies: dict) -> list[dict]:
    tests = []
    px = S["px"].dropna().to_numpy()
    r_m = rsi(px, 14)
    tests.append(signal_test("RSI(14) above 70", "S&P 500 (monthly)", px, r_m > 70, 1, 12, skip=1))
    tests.append(signal_test("RSI(14) below 30", "S&P 500 (monthly)", px, r_m < 30, 1, 12, skip=1))
    tests.append(signal_test("Above the 10-month average", "S&P 500 (monthly)", px, px > sma(px, 10), 1, 12, skip=1))
    mom = np.full(len(px), np.nan)
    mom[12:] = px[11:-1] / px[:-12] - 1                     # 12-1 momentum: last year excluding the latest month
    tests.append(signal_test("12-1 month momentum positive", "S&P 500 (monthly)", px, np.nan_to_num(mom) > 0, 1, 12, skip=1))
    for key, nm in (("brent", "Brent"), ("wti", "WTI"), ("gas", "Henry Hub gas"), ("vix", "VIX")):
        s = dailies.get(key)
        if s is None or len(s) < 400:
            continue
        x = s.to_numpy()
        rr = rsi(x, 14)
        line, sig, _ = macd(x)
        tests.append(signal_test("RSI(14) above 70", nm, x, rr > 70, 5, 252))
        tests.append(signal_test("RSI(14) below 30", nm, x, rr < 30, 5, 252))
        tests.append(signal_test("MACD above its signal", nm, x, np.nan_to_num(line - sig) > 0, 5, 252))
        tests.append(signal_test("50-day above 200-day (golden cross)", nm, x, np.nan_to_num(sma(x, 50) - sma(x, 200)) > 0, 20, 252))
        lo, mid, hi = bollinger(x)
        tests.append(signal_test("Below the lower Bollinger band", nm, x, np.nan_to_num(lo - x) > 0, 5, 252))
    return tests


def readings(S: pd.DataFrame, dailies: dict) -> dict:
    out = {}
    px = S["px"].dropna()
    v = px.to_numpy()
    out["sp500"] = {"name": "S&P 500 (monthly)", "date": px.index[-1].strftime("%Y-%m"), "price": float(v[-1]), "ma10": float(sma(v, 10)[-1]), "rsi14": float(rsi(v, 14)[-1]),
                    "mom12_1": float(v[-2] / v[-13] - 1), "dd": float(drawdown(v)[-1]), "vs_ma": float(v[-1] / sma(v, 10)[-1] - 1)}
    for key, nm in (("brent", "Brent"), ("wti", "WTI"), ("gas", "Henry Hub gas"), ("vix", "VIX")):
        s = dailies.get(key)
        if s is None or len(s) < 260:
            continue
        x = s.to_numpy()
        line, sig, hist = macd(x)
        lo, mid, hi = bollinger(x)
        lr = np.diff(np.log(x[-253:]))
        out[key] = {"name": nm, "date": s.index[-1].strftime("%Y-%m-%d"), "price": float(x[-1]), "ma50": float(sma(x, 50)[-1]), "ma200": float(sma(x, 200)[-1]),
                    "vs_ma200": float(x[-1] / sma(x, 200)[-1] - 1), "rsi14": float(rsi(x, 14)[-1]), "macd": float(line[-1]), "macd_signal": float(sig[-1]),
                    "pct_b": float((x[-1] - lo[-1]) / (hi[-1] - lo[-1])) if hi[-1] > lo[-1] else None, "golden": bool(sma(x, 50)[-1] > sma(x, 200)[-1]),
                    "hi52": float(x[-252:].max()), "lo52": float(x[-252:].min()), "vol1y": float(lr.std() * math.sqrt(252)),
                    "series": {"dates": [d.strftime("%Y-%m-%d") for d in s.index[-500::5]], "price": [round(float(p), 3) for p in x[-500::5]],
                               "ma200": [None if np.isnan(m) else round(float(m), 3) for m in sma(x, 200)[-500::5]], "rsi": [None if np.isnan(m) else round(float(m), 1) for m in rsi(x, 14)[-500::5]]}}
    return out


# ---------------------------------------------------------------- valuation
def valuation_lab(S: pd.DataFrame, cape_now: float | None = None) -> dict:
    """Long-horizon predictability of real returns from valuation, with honest errors and out-of-sample checks."""
    real_px = S["px"] / S["cpi"]
    real_eps = S["eps"] / S["cpi"]
    cape = real_px / real_eps.rolling(120, min_periods=120).mean()
    pe = S["px"] / S["eps"]
    dy = S["div"] / S["px"]
    r, _, notes = total_return_index(S)
    w = np.log((1 + r).cumprod())
    fwd10 = (w.shift(-120) - w) / 10                       # annualized log real return over the next 120 months
    fwd1 = w.shift(-12) - w
    infl10 = np.log(S["cpi"] / S["cpi"].shift(120)) / 10
    ecy = 1 / cape - (S["y10"] / 100 - infl10)            # excess CAPE yield (Shiller), real-yield proxy
    out = {"notes": notes, "eps_to": S["eps"].last_valid_index().strftime("%Y-%m"), "signals": {}}
    for nm, sigl in (("CAPE", np.log(cape)), ("Trailing P/E", np.log(pe)), ("Dividend yield", np.log(dy)), ("Excess CAPE yield", ecy)):
        df = pd.DataFrame({"x": sigl, "y10": fwd10, "y1": fwd1}).dropna()
        df = df.loc["1881":]
        res = {}
        for hz, col, lags in (("10y", "y10", 120), ("1y", "y1", 12)):
            reg = nw_ols(df[col].to_numpy(), df[["x"]].to_numpy(), lags)
            # out of sample: expanding regression from 1930, forecast at t uses only data whose outcome is known by t
            dates = df.index
            e_m, e_r = [], []
            hstep = 120 if hz == "10y" else 12
            for k in range(len(df)):
                if dates[k] < pd.Timestamp("1930-01-01"):
                    continue
                known = np.arange(k - hstep + 1) if k - hstep + 1 > 60 else None
                if known is None:
                    continue
                xx, yy = df["x"].to_numpy()[known], df[col].to_numpy()[known]
                b = np.polyfit(xx, yy, 1)
                e_r.append(df[col].iloc[k] - np.polyval(b, df["x"].iloc[k]))
                e_m.append(df[col].iloc[k] - yy.mean())
            oos = 1 - float(np.sum(np.square(e_r))) / float(np.sum(np.square(e_m))) if e_m else None
            res[hz] = {"slope": float(reg["b"][1]), "t": float(reg["t"][1]), "r2": reg["r2"], "oos_r2": oos, "n": int(len(df))}
        out["signals"][nm] = res
    # today's implied ten-year real return from CAPE, with an 80% range from the regression's residuals
    df = pd.DataFrame({"x": np.log(cape), "y": fwd10}).dropna().loc["1881":]
    b = np.polyfit(df["x"], df["y"], 1)
    resid = df["y"] - np.polyval(b, df["x"])
    last_cape = float(cape.dropna().iloc[-1])
    c_now = cape_now if cape_now else last_cape
    mid = float(np.polyval(b, math.log(c_now)))
    pct = float((cape.dropna() < c_now).mean())
    out["cape"] = {"computed_last": last_cape, "computed_date": cape.last_valid_index().strftime("%Y-%m"), "now": c_now, "now_source": "research" if cape_now else "computed",
                   "percentile": pct, "median": float(cape.dropna().median()), "implied_10y_real": mid, "range80": [mid + float(np.quantile(resid, 0.1)), mid + float(np.quantile(resid, 0.9))],
                   "scatter": {"x": [round(float(v), 2) for v in np.exp(df["x"]).iloc[::3]], "y": [round(float(v), 4) for v in df["y"].iloc[::3]]}, "fit": [float(b[0]), float(b[1])]}
    out["pe"] = {"last": float(pe.dropna().iloc[-1]), "date": pe.last_valid_index().strftime("%Y-%m"), "percentile": float((pe.dropna() < pe.dropna().iloc[-1]).mean()), "median": float(pe.dropna().median())}
    return out


# ---------------------------------------------------------------- regimes (Hamilton 1989), by EM
def markov_switching(r: np.ndarray, iters: int = 300, tol: float = 1e-8) -> dict:
    """Two Gaussian regimes with a Markov chain. E step: Hamilton filter and Kim smoother; M step: closed form."""
    r = np.asarray(r, float)
    T = len(r)
    mu = np.array([np.quantile(r, 0.6), np.quantile(r, 0.2)])
    sd = np.array([r.std() * 0.7, r.std() * 1.6])
    P = np.array([[0.97, 0.03], [0.10, 0.90]])
    ll_old = -np.inf
    for _ in range(iters):
        f = np.column_stack([stats.norm.pdf(r, mu[k], sd[k]) for k in range(2)]) + 1e-300
        pi0 = np.array([P[1, 0], P[0, 1]]) / (P[1, 0] + P[0, 1])
        filt, pred = np.zeros((T, 2)), np.zeros((T, 2))
        ll = 0.0
        prev = pi0
        for t in range(T):
            pr = prev @ P if t else pi0
            pred[t] = pr
            num = pr * f[t]
            c = num.sum()
            ll += math.log(c)
            filt[t] = num / c
            prev = filt[t]
        sm = np.zeros((T, 2))
        sm[-1] = filt[-1]
        xi = np.zeros((2, 2))
        for t in range(T - 2, -1, -1):
            ratio = sm[t + 1] / pred[t + 1]
            sm[t] = filt[t] * (P @ ratio)
            xi += (filt[t][:, None] * P) * ratio[None, :]
        mu = (sm * r[:, None]).sum(0) / sm.sum(0)
        sd = np.sqrt((sm * (r[:, None] - mu) ** 2).sum(0) / sm.sum(0))
        P = xi / xi.sum(1, keepdims=True)
        if ll - ll_old < tol:
            break
        ll_old = ll
    k_calm = int(np.argmin(sd))
    o = [k_calm, 1 - k_calm]
    return {"mu": [float(mu[k]) for k in o], "sd": [float(sd[k]) for k in o], "P": [[float(P[i, j]) for j in o] for i in o],
            "duration": [float(1 / (1 - P[k, k])) for k in o], "p_now": [float(filt[-1][k]) for k in o], "smoothed": sm[:, o], "loglik": ll,
            "share": [float(sm[:, k].mean()) for k in o]}


# ---------------------------------------------------------------- volatility
def garch11(r: np.ndarray) -> dict:
    """GARCH(1,1) by Gaussian quasi-maximum likelihood: s2_t = w + a e_{t-1}^2 + b s2_{t-1}."""
    r = np.asarray(r, float)
    r = r - r.mean()
    v0 = r.var()

    def nll(th):
        w, a, b = th
        if w <= 0 or a < 0 or b < 0 or a + b >= 0.9999:
            return 1e12
        s2 = np.empty(len(r))
        s2[0] = v0
        for t in range(1, len(r)):
            s2[t] = w + a * r[t - 1] ** 2 + b * s2[t - 1]
        return 0.5 * float(np.sum(np.log(s2) + r ** 2 / s2))
    best = None
    for a0, b0 in ((0.05, 0.9), (0.1, 0.85), (0.03, 0.95)):
        res = optimize.minimize(nll, [v0 * (1 - a0 - b0), a0, b0], method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-10, "fatol": 1e-10})
        if best is None or res.fun < best.fun:
            best = res
    w, a, b = best.x
    s2 = np.empty(len(r))
    s2[0] = v0
    for t in range(1, len(r)):
        s2[t] = w + a * r[t - 1] ** 2 + b * s2[t - 1]
    nxt = w + a * r[-1] ** 2 + b * s2[-1]
    pers = a + b
    integrated = pers > 0.998
    return {"omega": float(w), "alpha": float(a), "beta": float(b), "persistence": float(pers), "integrated": bool(integrated),
            "half_life": None if integrated or not 0 < pers < 1 else float(math.log(0.5) / math.log(pers)),
            "long_run_vol": None if integrated else float(math.sqrt(w / (1 - pers))), "current_vol": float(math.sqrt(nxt)), "n": int(len(r))}


def tails(r: np.ndarray, k_frac: float = 0.05) -> dict:
    r = np.asarray(r, float)
    jb = stats.jarque_bera(r)
    loss = np.sort(-r[r < 0])[::-1]
    k = max(10, int(k_frac * len(loss)))
    hill = 1 / np.mean(np.log(loss[:k] / loss[k])) if len(loss) > k + 1 else None
    return {"kurtosis": float(stats.kurtosis(r, fisher=False)), "skew": float(stats.skew(r)), "jb": float(jb.statistic), "jb_p": float(jb.pvalue), "hill_alpha": float(hill) if hill else None}


# ---------------------------------------------------------------- cointegration with a simulated p-value
def _adf_t(e: np.ndarray, lags: int = 1) -> float:
    de = np.diff(e)
    y = de[lags:]
    X = [e[lags:-1]] + [de[lags - k:-k] for k in range(1, lags + 1)]
    A = np.column_stack([np.ones(len(y))] + X)
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    res = y - A @ b
    s2 = float(res @ res) / (len(y) - A.shape[1])
    se = math.sqrt(s2 * np.linalg.pinv(A.T @ A)[1, 1])
    return float(b[1] / se)


def engle_granger(y: np.ndarray, x: np.ndarray, sims: int = 400, seed: int = 9) -> dict:
    """Regress y on x, test the residual for a unit root; the p-value comes from simulating the same test on pairs of
    independent random walks of the same length (no table needed)."""
    A = np.column_stack([np.ones(len(x)), x])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    e = y - A @ b
    t = _adf_t(e)
    rng = np.random.default_rng(seed)
    n = min(len(y), 2500)
    null = []
    for _ in range(sims):
        u, v = np.cumsum(rng.normal(size=n)), np.cumsum(rng.normal(size=n))
        Ab = np.column_stack([np.ones(n), v])
        bb, *_ = np.linalg.lstsq(Ab, u, rcond=None)
        null.append(_adf_t(u - Ab @ bb))
    p = float(np.mean(np.array(null) <= t))
    ar = np.polyfit(e[:-1], e[1:], 1)[0]
    return {"beta": float(b[1]), "alpha": float(b[0]), "adf_t": t, "p": p, "half_life": float(math.log(0.5) / math.log(ar)) if 0 < ar < 1 else None,
            "z_now": float((e[-1] - e.mean()) / e.std()), "resid_sd": float(e.std())}


def working_vr(q: int, rho1: float = 0.25) -> float:
    """The variance ratio a random walk shows when sampled as monthly averages: first-order autocorrelation of about
    0.25 and none beyond (Working 1960), so VR(q) = 1 + 2 (1 - 1/q) rho1."""
    return 1 + 2 * (1 - 1 / q) * rho1


def variance_ratio(r: np.ndarray, q: int, null: float = 1.0) -> dict:
    """Lo and MacKinlay (1988) with the heteroskedasticity-robust z, against `null` (1 for point-in-time prices)."""
    r = np.asarray(r, float)
    n = len(r)
    mu = r.mean()
    s1 = float(np.sum((r - mu) ** 2)) / (n - 1)
    rq = np.convolve(r, np.ones(q), "valid")
    m = q * (n - q + 1) * (1 - q / n)
    sq = float(np.sum((rq - q * mu) ** 2)) / m
    vr = sq / s1
    e2 = (r - mu) ** 2
    den = float(np.sum(e2)) ** 2
    theta = sum(((2 * (q - j) / q) ** 2) * float(np.sum(e2[j:] * e2[:-j])) * n / den for j in range(1, q))
    z = (vr - null) / math.sqrt(theta / n) if theta > 0 else float("nan")
    return {"q": q, "vr": vr, "null": null, "z": z, "p": float(2 * stats.norm.sf(abs(z)))}


# ---------------------------------------------------------------- the whole lab
def build(dl: dict | None = None, cape_now: float | None = None) -> dict:
    dl = dl or download()
    S = shiller(dl)
    dailies = {k: daily(dl, k) for k in ("brent", "wti", "gas", "vix")}
    out = {"schema": 1, "failed": dl.get("failed", {})}
    out["trend"] = trend_lab(S)
    out["oscillators"] = oscillator_lab(S, dailies)
    out["readings"] = readings(S, dailies)
    out["valuation"] = valuation_lab(S, cape_now)
    r, _, _ = total_return_index(S)
    ms = markov_switching(r.loc["1926":].to_numpy())
    sm = ms.pop("smoothed")
    idx = r.loc["1926":].index
    ms["path"] = {"dates": [d.strftime("%Y-%m") for d in idx[::3]], "p_turbulent": [round(float(v), 3) for v in sm[::3, 1]]}
    ms["from"] = idx[0].strftime("%Y-%m")
    out["regimes"] = ms
    vol = {}
    for k, nm in (("brent", "Brent"), ("wti", "WTI"), ("gas", "Henry Hub gas")):
        s = dailies[k]
        if len(s) > 1000:
            lr = np.diff(np.log(s.loc["2000":].to_numpy()))
            g = garch11(lr)
            g.update({"name": nm, "annual_current": g["current_vol"] * math.sqrt(252), "annual_long": None if g["long_run_vol"] is None else g["long_run_vol"] * math.sqrt(252)})
            g["tails"] = tails(lr)
            vol[k] = g
    sp_m = r.loc["1926":].to_numpy()
    vol["sp500_monthly_tails"] = tails(sp_m)
    out["volatility"] = vol
    b, w = dailies["brent"], dailies["wti"]
    j = b.index[b.index.isin(w.index)]
    j = j[j >= pd.Timestamp("2000-01-01")]
    eg = engle_granger(np.log(b.loc[j].to_numpy()), np.log(w.loc[j].to_numpy()))
    sp = (b.loc[j] - w.loc[j])
    eg["spread_now"] = float(sp.iloc[-1])
    eg["spread_mean"] = float(sp.mean())
    eg["spread"] = {"dates": [d.strftime("%Y-%m") for d in sp.resample("MS").mean().index], "usd": [round(float(v), 2) for v in sp.resample("MS").mean().to_numpy()]}
    out["spreads"] = {"brent_wti": eg}
    gold = dl["raw"].get("gold")
    if gold is not None:
        gm = pd.Series(gold["Price"].to_numpy(float), index=pd.to_datetime(gold["Date"].astype(str).str.slice(0, 7) + "-01"))
        bm = b.resample("MS").mean()
        ratio = (gm / bm).dropna()
        out["spreads"]["gold_oil"] = {"now": float(ratio.iloc[-1]), "date": ratio.index[-1].strftime("%Y-%m"), "median": float(ratio.median()), "percentile": float((ratio < ratio.iloc[-1]).mean()), "from": ratio.index[0].strftime("%Y-%m")}
    rr = {"S&P 500 real, monthly since 1926": r.loc["1926":].to_numpy()}
    vrs = []
    for nm, x in rr.items():
        for q in (2, 4, 12):
            v = variance_ratio(x, q, null=working_vr(q))
            v["series"] = nm
            vrs.append(v)
    for k, nm in (("brent", "Brent, daily since 2000"), ("vix", "VIX, daily since 1990")):
        x = np.diff(np.log(dailies[k].loc["2000":].to_numpy())) if k == "brent" else np.diff(np.log(dailies[k].to_numpy()))
        for q in (5, 20):
            v = variance_ratio(x, q)
            v["series"] = nm
            vrs.append(v)
    out["randomness"] = vrs
    cal = {}
    for nm, start in (("since 1871", "1871"), ("since 1950", "1950")):
        rx = r.loc[start:]
        winter = rx.index.month.isin([11, 12, 1, 2, 3, 4])
        cal[nm] = {"winter": nw_mean(rx[winter].to_numpy()), "summer": nw_mean(rx[~winter].to_numpy())}
        d = rx.to_numpy() * np.where(winter, 1.0, 0.0) - rx.to_numpy() * np.where(winter, 0.0, 1.0)
        reg = nw_ols(rx.to_numpy(), winter.astype(float)[:, None], 6)
        cal[nm]["diff"] = {"est": float(reg["b"][1]), "t": float(reg["t"][1]), "p": float(2 * stats.norm.sf(abs(reg["t"][1])))}
        del d
    g = dailies["gas"].resample("MS").mean()
    gl = np.log(g).diff().dropna()
    cal["gas_seasonal"] = [{"month": m, **nw_mean(gl[gl.index.month == m].to_numpy(), lags=0)} for m in range(1, 13)]
    out["calendar"] = cal
    # one multiple-testing table
    rows = []
    for t in out["oscillators"]:
        if not t.get("skipped"):
            rows.append({"test": f"{t['name']} · {t['asset']}", "p": t["p"], "effect": t["diff"]})
    for v in vrs:
        rows.append({"test": f"Variance ratio q={v['q']} · {v['series']}", "p": v["p"], "effect": v["vr"] - v["null"]})
    for nm in ("since 1871", "since 1950"):
        rows.append({"test": f"Sell in May ({nm})", "p": cal[nm]["diff"]["p"], "effect": cal[nm]["diff"]["est"]})
    rows.append({"test": "Brent and WTI share a long-run path (Engle-Granger)", "p": eg["p"], "effect": eg["beta"]})
    ps = [x["p"] for x in rows]
    for x, h, q in zip(rows, holm(ps), bh(ps)):
        x["holm"], x["bh"] = h, q
    out["multiple_testing"] = {"rows": sorted(rows, key=lambda x: x["p"]), "n": len(rows), "raw_5pct": sum(p < 0.05 for p in ps),
                               "holm_5pct": sum(x["holm"] < 0.05 for x in rows), "bh_5pct": sum(x["bh"] < 0.05 for x in rows)}
    out["data"] = {"shiller_to": S["px"].last_valid_index().strftime("%Y-%m"), **{k: (dailies[k].index[-1].strftime("%Y-%m-%d") if len(dailies[k]) else None) for k in dailies}}
    return out


def summary(L: dict) -> list[str]:
    t, v, m, mt = L["trend"], L["valuation"], L["regimes"], L["multiple_testing"]
    out = [f"The 10-month average rule on {t['years']:.0f} years of the S&P 500, acting a month late so monthly averaging cannot flatter it: Sharpe {t['full']['rule']['sharpe']:.2f} against {t['full']['hold']['sharpe']:.2f} for holding, "
           f"worst drawdown {t['full']['rule']['maxdd']:.0%} against {t['full']['hold']['maxdd']:.0%}; the Sharpe gain's 90% range is {t['sharpe_diff']['lo']:+.2f} to {t['sharpe_diff']['hi']:+.2f}. "
           f"Of all 22 lengths the best is {t['best']} months; judged on return alone, a no-edge world produces one that good {t['spa_p']:.0%} of the time: the rule cuts risk, not the return.",
           f"CAPE {v['cape']['now']:.1f} is above {v['cape']['percentile']:.0%} of months since 1881; history implies {v['cape']['implied_10y_real']:.1%} a year real for ten years "
           f"(80% range {v['cape']['range80'][0]:.1%} to {v['cape']['range80'][1]:.1%}). Over one year valuation explains almost nothing.",
           f"Markov-switching: a calm regime ({m['sd'][0] * math.sqrt(12):.0%} annual volatility) lasting about {m['duration'][0]:.0f} months and a turbulent one ({m['sd'][1] * math.sqrt(12):.0%}) lasting about "
           f"{m['duration'][1]:.0f}; today's chance of the turbulent regime is {m['p_now'][1]:.0%}.",
           f"Of {mt['n']} indicator and calendar tests, {mt['raw_5pct']} pass at 5% before correction, {mt['bh_5pct']} after controlling the false discovery rate, {mt['holm_5pct']} after Holm."]
    return out


def public(L: dict) -> dict:
    """What leaves the engine: derived results only. Indicator readings keep their ratios and oscillator values; the
    price series behind them are dropped."""
    import json as _json
    L = _json.loads(_json.dumps(L, default=float))
    for r in L.get("readings", {}).values():
        s = r.pop("series", None)
        if s:
            r["derived"] = {"dates": s["dates"], "vs_ma200": [round(p / m - 1, 4) if (p and m) else None for p, m in zip(s["price"], s["ma200"])], "rsi": s["rsi"]}
    return L
