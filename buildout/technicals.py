"""Technical analysis, built to be tested rather than believed.

A full indicator library on OHLCV (close-only series get every indicator that needs only closes), the readings and
signals for today, chart structure (swing pivots, support and resistance, Fibonacci retracements, 52-week range,
divergences, squeezes, breakouts, the trend template), relative strength against a benchmark, and an event study of
every signal on the asset's own history: the average forward return after the signal against all days, with
Newey-West t-statistics and Benjamini-Hochberg across the signals tried. The composite score weights each signal by
its own out-of-sample evidence, shrunk toward zero, so a signal that never worked on this asset counts for nothing.

Conventions: arrays are float numpy, NaN until an indicator has enough history; Wilder smoothing is alpha = 1/n; every
signal at date t uses data through t and is judged on returns from t+1.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import labs

NAN = float("nan")


# ---------------------------------------------------------------- moving averages and smoothing
def sma(x, n):
    return labs.sma(np.asarray(x, float), n)


def ema(x, n):
    return labs.ema(np.asarray(x, float), n)


def wilder(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder's smoothing: seeded with the first n-value mean, then alpha = 1/n."""
    x = np.asarray(x, float)
    out = np.full(len(x), NAN)
    ok = np.where(~np.isnan(x))[0]
    if len(ok) < n:
        return out
    s = ok[0]
    out[s + n - 1] = np.nanmean(x[s:s + n])
    for i in range(s + n, len(x)):
        v = x[i]
        out[i] = out[i - 1] if np.isnan(v) else out[i - 1] + (v - out[i - 1]) / n
    return out


def wma(x, n):
    x = np.asarray(x, float)
    w = np.arange(1, n + 1, dtype=float)
    out = np.full(len(x), NAN)
    if len(x) >= n:
        c = np.convolve(x, w[::-1], mode="valid") / w.sum()
        out[n - 1:] = c
    return out


def hma(x, n):
    """Hull moving average: WMA(2 WMA(n/2) - WMA(n), sqrt n)."""
    a = 2 * wma(x, max(1, n // 2)) - wma(x, n)
    out = np.full(len(a), NAN)
    ok = ~np.isnan(a)
    if ok.sum() >= int(math.sqrt(n)):
        out[ok] = wma(a[ok], max(1, int(math.sqrt(n))))
    return out


def rolling(x, n, fn):
    s = pd.Series(np.asarray(x, float)).rolling(n, min_periods=n)
    return getattr(s, fn)().to_numpy()


# ---------------------------------------------------------------- momentum
def rsi(x, n=14):
    return labs.rsi(np.asarray(x, float), n)


def macd(x, fast=12, slow=26, signal=9):
    return labs.macd(np.asarray(x, float), fast, slow, signal)


def roc(x, n=12):
    x = np.asarray(x, float)
    out = np.full(len(x), NAN)
    out[n:] = x[n:] / x[:-n] - 1
    return out


def stochastic(h, l, c, n=14, d=3):
    hh, ll = rolling(h, n, "max"), rolling(l, n, "min")
    k = 100 * (np.asarray(c, float) - ll) / np.where(hh - ll == 0, NAN, hh - ll)
    return k, sma(k, d)


def williams_r(h, l, c, n=14):
    hh, ll = rolling(h, n, "max"), rolling(l, n, "min")
    return -100 * (hh - np.asarray(c, float)) / np.where(hh - ll == 0, NAN, hh - ll)


def cci(h, l, c, n=20):
    tp = (np.asarray(h, float) + np.asarray(l, float) + np.asarray(c, float)) / 3
    m = sma(tp, n)
    md = pd.Series(tp).rolling(n, min_periods=n).apply(lambda w: np.mean(np.abs(w - w.mean())), raw=True).to_numpy()
    return (tp - m) / (0.015 * np.where(md == 0, NAN, md))


def tsi(x, r=25, s=13):
    d = np.diff(np.asarray(x, float), prepend=NAN)
    d[0] = 0.0
    num = ema(ema(d, r), s)
    den = ema(ema(np.abs(d), r), s)
    return 100 * num / np.where(den == 0, NAN, den)


# ---------------------------------------------------------------- volatility and range
def true_range(h, l, c):
    h, l, c = (np.asarray(v, float) for v in (h, l, c))
    pc = np.concatenate([[NAN], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    tr[0] = h[0] - l[0]
    return tr


def atr(h, l, c, n=14):
    return wilder(true_range(h, l, c), n)


def bollinger(x, n=20, k=2.0):
    return labs.bollinger(np.asarray(x, float), n, k)


def keltner(h, l, c, n=20, m=1.5):
    mid = ema(c, n)
    a = atr(h, l, c, n)
    return mid - m * a, mid, mid + m * a


def donchian(h, l, n=20):
    return rolling(l, n, "min"), rolling(h, n, "max")


def realized_vol(c, n=21, per_year=252):
    r = np.diff(np.log(np.asarray(c, float)), prepend=NAN)
    return rolling(r, n, "std") * math.sqrt(per_year)


def parkinson_vol(h, l, n=21, per_year=252):
    hl = np.log(np.asarray(h, float) / np.asarray(l, float)) ** 2
    return np.sqrt(rolling(hl, n, "mean") / (4 * math.log(2)) * per_year)


# ---------------------------------------------------------------- trend strength and systems
def adx(h, l, c, n=14):
    h, l = np.asarray(h, float), np.asarray(l, float)
    up = np.diff(h, prepend=NAN)
    dn = -np.diff(l, prepend=NAN)
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pdm[0] = mdm[0] = NAN
    a = wilder(true_range(h, l, c)[1:], n)
    pdi = 100 * wilder(pdm[1:], n) / a
    mdi = 100 * wilder(mdm[1:], n) / a
    dx = 100 * np.abs(pdi - mdi) / np.where(pdi + mdi == 0, NAN, pdi + mdi)
    pad = lambda v: np.concatenate([[NAN], v])
    return pad(wilder(dx, n)), pad(pdi), pad(mdi)


def aroon(h, l, n=25):
    hi = pd.Series(np.asarray(h, float)).rolling(n + 1, min_periods=n + 1).apply(lambda w: np.argmax(w), raw=True).to_numpy()
    lo = pd.Series(np.asarray(l, float)).rolling(n + 1, min_periods=n + 1).apply(lambda w: np.argmin(w), raw=True).to_numpy()
    return 100 * hi / n, 100 * lo / n


def supertrend(h, l, c, n=10, m=3.0):
    """Supertrend: +1 when price is above the trailing ATR band, -1 below."""
    h, l, c = (np.asarray(v, float) for v in (h, l, c))
    a = atr(h, l, c, n)
    mid = (h + l) / 2
    ub, lb = mid + m * a, mid - m * a
    fu, fl = ub.copy(), lb.copy()
    d = np.full(len(c), np.nan)
    for i in range(1, len(c)):
        if np.isnan(a[i]):
            continue
        if not np.isnan(fu[i - 1]):
            fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
            fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        prev = d[i - 1] if not np.isnan(d[i - 1]) else 1.0
        d[i] = 1.0 if c[i] > fu[i] else (-1.0 if c[i] < fl[i] else prev)
    return d


def psar(h, l, step=0.02, cap=0.2):
    """Parabolic SAR (Wilder): returns the stop level and the side (+1 long, -1 short)."""
    h, l = np.asarray(h, float), np.asarray(l, float)
    n = len(h)
    sar, side = np.full(n, NAN), np.full(n, NAN)
    if n < 3:
        return sar, side
    up, af, ep, s = True, step, h[0], l[0]
    for i in range(1, n):
        s = s + af * (ep - s)
        if up:
            s = min(s, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < s:
                up, s, ep, af = False, ep, l[i], step
            elif h[i] > ep:
                ep, af = h[i], min(cap, af + step)
        else:
            s = max(s, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > s:
                up, s, ep, af = True, ep, h[i], step
            elif l[i] < ep:
                ep, af = l[i], min(cap, af + step)
        sar[i], side[i] = s, 1.0 if up else -1.0
    return sar, side


def ichimoku(h, l, c):
    hh = lambda n: rolling(h, n, "max")
    ll = lambda n: rolling(l, n, "min")
    tenkan = (hh(9) + ll(9)) / 2
    kijun = (hh(26) + ll(26)) / 2
    span_a = (tenkan + kijun) / 2                      # plotted 26 ahead; today's cloud is the value 26 bars back
    span_b = (hh(52) + ll(52)) / 2
    shift = lambda v: np.concatenate([np.full(26, NAN), v[:-26]]) if len(v) > 26 else np.full(len(v), NAN)
    return {"tenkan": tenkan, "kijun": kijun, "cloud_a": shift(span_a), "cloud_b": shift(span_b)}


# ---------------------------------------------------------------- volume
def obv(c, v):
    c, v = np.asarray(c, float), np.asarray(v, float)
    s = np.sign(np.diff(c, prepend=c[0]))
    return np.cumsum(s * v)


def mfi(h, l, c, v, n=14):
    tp = (np.asarray(h, float) + np.asarray(l, float) + np.asarray(c, float)) / 3
    raw = tp * np.asarray(v, float)
    d = np.diff(tp, prepend=NAN)
    pos = rolling(np.where(d > 0, raw, 0.0), n, "sum")
    neg = rolling(np.where(d < 0, raw, 0.0), n, "sum")
    return 100 - 100 / (1 + pos / np.where(neg == 0, NAN, neg))


def cmf(h, l, c, v, n=20):
    h, l, c, v = (np.asarray(x, float) for x in (h, l, c, v))
    mfm = ((c - l) - (h - c)) / np.where(h - l == 0, NAN, h - l)
    return rolling(np.nan_to_num(mfm) * v, n, "sum") / rolling(v, n, "sum")


def vwap(h, l, c, v, n=20):
    tp = (np.asarray(h, float) + np.asarray(l, float) + np.asarray(c, float)) / 3
    v = np.asarray(v, float)
    return rolling(tp * v, n, "sum") / rolling(v, n, "sum")


# ---------------------------------------------------------------- structure
def swings(h, l, k=5):
    """Swing highs and lows: a bar higher (lower) than the k bars on each side. Confirmed k bars later."""
    h, l = np.asarray(h, float), np.asarray(l, float)
    n = len(h)
    hi, lo = [], []
    for i in range(k, n - k):
        if h[i] == np.max(h[i - k:i + k + 1]) and h[i] > np.max(np.delete(h[i - k:i + k + 1], k)):
            hi.append(i)
        if l[i] == np.min(l[i - k:i + k + 1]) and l[i] < np.min(np.delete(l[i - k:i + k + 1], k)):
            lo.append(i)
    return hi, lo


def levels(h, l, c, k=5, tol=0.015, lookback=252):
    """Support and resistance: swing pivots in the lookback clustered within tol of each other; strength = touches."""
    h, l, c = (np.asarray(v, float) for v in (h, l, c))
    s = max(0, len(c) - lookback)
    hi, lo = swings(h[s:], l[s:], k)
    pts = sorted([h[s + i] for i in hi] + [l[s + i] for i in lo])
    clusters: list[list[float]] = []
    for p in pts:
        if clusters and abs(p / np.mean(clusters[-1]) - 1) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    last = c[-1]
    out = [{"level": float(np.mean(g)), "touches": len(g), "kind": "support" if np.mean(g) < last else "resistance",
            "distance": float(np.mean(g) / last - 1)} for g in clusters]
    sup = sorted([x for x in out if x["kind"] == "support"], key=lambda x: -x["level"])[:3]
    res = sorted([x for x in out if x["kind"] == "resistance"], key=lambda x: x["level"])[:3]
    return {"support": sup, "resistance": res}


def fibonacci(h, l, lookback=252):
    h, l = np.asarray(h, float)[-lookback:], np.asarray(l, float)[-lookback:]
    i_hi, i_lo = int(np.nanargmax(h)), int(np.nanargmin(l))
    hi, lo = float(h[i_hi]), float(l[i_lo])
    up = i_lo < i_hi                                    # the move ran up from the low to the high
    ratios = [0.236, 0.382, 0.5, 0.618, 0.786]
    lv = {f"{r:.3f}": (hi - r * (hi - lo)) if up else (lo + r * (hi - lo)) for r in ratios}
    return {"high": hi, "low": lo, "direction": "up" if up else "down", "levels": lv}


def pivots(h, l, c):
    """Classic floor-trader pivots from the last completed bar."""
    H, L, C = float(h[-1]), float(l[-1]), float(c[-1])
    p = (H + L + C) / 3
    return {"pivot": p, "r1": 2 * p - L, "s1": 2 * p - H, "r2": p + (H - L), "s2": p - (H - L)}


def divergence(c, osc, k=5, lookback=60):
    """Bearish: price makes a higher swing high while the oscillator makes a lower one (bullish mirrors it)."""
    c, osc = np.asarray(c, float), np.asarray(osc, float)
    s = max(0, len(c) - lookback)
    hi, lo = swings(c[s:], c[s:], k)
    out = None
    if len(hi) >= 2:
        a, b = s + hi[-2], s + hi[-1]
        if c[b] > c[a] and osc[b] < osc[a]:
            out = "bearish"
    if len(lo) >= 2:
        a, b = s + lo[-2], s + lo[-1]
        if c[b] < c[a] and osc[b] > osc[a] and (out is None or lo[-1] > hi[-1]):
            out = "bullish"
    return out


def trend_template(c):
    """Minervini's stage-2 checklist on daily closes: price above the 50, 150 and 200-day averages, stacked in that
    order, the 200 rising for a month, within 25% of the 52-week high and at least 30% above the 52-week low."""
    c = np.asarray(c, float)
    if len(c) < 260:
        return None
    s50, s150, s200 = sma(c, 50), sma(c, 150), sma(c, 200)
    hi, lo = np.nanmax(c[-252:]), np.nanmin(c[-252:])
    tests = {"above_50": c[-1] > s50[-1], "above_150_200": c[-1] > s150[-1] and c[-1] > s200[-1], "50_over_150": s50[-1] > s150[-1],
             "150_over_200": s150[-1] > s200[-1], "200_rising": s200[-1] > s200[-22], "near_high": c[-1] >= 0.75 * hi, "off_low": c[-1] >= 1.3 * lo}
    return {"passed": int(sum(bool(v) for v in tests.values())), "of": len(tests), "tests": {k: bool(v) for k, v in tests.items()}}


def mansfield_rs(c, bench, n=252):
    """Relative strength: the price ratio to the benchmark against its own n-bar average, minus one."""
    r = np.asarray(c, float) / np.asarray(bench, float)
    return r / sma(r, n) - 1


# ---------------------------------------------------------------- frame helpers
def _cols(df: pd.DataFrame):
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float) if "high" in df else c
    l = df["low"].to_numpy(float) if "low" in df else c
    v = df["volume"].to_numpy(float) if "volume" in df and df["volume"].notna().any() else None
    return h, l, c, v


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Every indicator as a column, aligned with df."""
    h, l, c, v = _cols(df)
    ohlc = "high" in df and "low" in df
    out = {"sma20": sma(c, 20), "sma50": sma(c, 50), "sma200": sma(c, 200), "ema12": ema(c, 12), "ema26": ema(c, 26), "hma21": hma(c, 21),
           "rsi14": rsi(c, 14), "roc63": roc(c, 63), "roc252": roc(c, 252), "tsi": tsi(c), "vol21": realized_vol(c, 21)}
    m, sig, hist = macd(c)
    out.update({"macd": m, "macd_signal": sig, "macd_hist": hist})
    bl, bm, bu = bollinger(c)
    out.update({"bb_lower": bl, "bb_mid": bm, "bb_upper": bu, "bb_pctb": (c - bl) / (bu - bl), "bb_width": (bu - bl) / bm})
    dl, du = donchian(h, l, 55)
    out.update({"don55_low": dl, "don55_high": du})
    if ohlc:
        k, d = stochastic(h, l, c)
        a, pdi, mdi = adx(h, l, c)
        kl, km, ku = keltner(h, l, c)
        sar, side = psar(h, l)
        ich = ichimoku(h, l, c)
        out.update({"stoch_k": k, "stoch_d": d, "williams_r": williams_r(h, l, c), "cci20": cci(h, l, c), "atr14": atr(h, l, c), "adx14": a, "plus_di": pdi,
                    "minus_di": mdi, "kelt_lower": kl, "kelt_upper": ku, "supertrend": supertrend(h, l, c), "psar": sar, "psar_side": side,
                    "parkinson21": parkinson_vol(h, l), **{f"ichi_{k_}": v_ for k_, v_ in ich.items()}})
        out["aroon_up"], out["aroon_down"] = aroon(h, l)
    if v is not None:
        out.update({"obv": obv(c, v), "vwap20": vwap(h, l, c, v), "vol_ratio": v / sma(v, 50)})
        if ohlc:
            out.update({"mfi14": mfi(h, l, c, v), "cmf20": cmf(h, l, c, v)})
    return pd.DataFrame(out, index=df.index)


# ---------------------------------------------------------------- signals: +1 bullish, -1 bearish, 0 neutral, per bar
SIGNALS = {
    "trend_200": ("Price above its 200-day average", "trend"),
    "golden_cross": ("50-day average above the 200-day", "trend"),
    "macd": ("MACD above its signal line", "momentum"),
    "rsi_extreme": ("RSI below 30 (bullish) or above 70 (bearish)", "mean reversion"),
    "bollinger": ("Close outside a Bollinger band (fade it)", "mean reversion"),
    "momentum_12m": ("Twelve-month return, skipping the last month", "momentum"),
    "breakout_55": ("A new 55-day high (bullish) or low (bearish)", "breakout"),
    "supertrend": ("Supertrend direction", "trend"),
    "adx_trend": ("ADX above 25, in the direction of the stronger DI", "trend"),
    "stochastic": ("Stochastic below 20 (bullish) or above 80 (bearish)", "mean reversion"),
    "cloud": ("Close above (bullish) or below (bearish) the Ichimoku cloud", "trend"),
    "obv_trend": ("On-balance volume above its 50-day average", "volume"),
    "mfi_extreme": ("Money flow below 20 (bullish) or above 80 (bearish)", "volume"),
}


def signals(df: pd.DataFrame, I: pd.DataFrame | None = None) -> pd.DataFrame:
    I = indicators(df) if I is None else I
    c = df["close"].to_numpy(float)
    sgn = lambda cond_up, cond_dn: np.where(cond_up, 1.0, np.where(cond_dn, -1.0, 0.0))
    nanify = lambda s, ref: np.where(np.isnan(ref), NAN, s)
    out = {}
    out["trend_200"] = nanify(sgn(c > I["sma200"], c <= I["sma200"]), I["sma200"].to_numpy())
    out["golden_cross"] = nanify(sgn(I["sma50"] > I["sma200"], I["sma50"] <= I["sma200"]), I["sma200"].to_numpy())
    out["macd"] = nanify(sgn(I["macd"] > I["macd_signal"], I["macd"] <= I["macd_signal"]), I["macd_signal"].to_numpy())
    out["rsi_extreme"] = nanify(sgn(I["rsi14"] < 30, I["rsi14"] > 70), I["rsi14"].to_numpy())
    out["bollinger"] = nanify(sgn(c < I["bb_lower"], c > I["bb_upper"]), I["bb_mid"].to_numpy())
    mom = np.full(len(c), NAN)
    if len(c) > 252:
        mom[252:] = c[231:-21] / c[:-252] - 1
    out["momentum_12m"] = nanify(np.sign(np.nan_to_num(mom)), mom)
    prev_hi = np.concatenate([[NAN], I["don55_high"].to_numpy()[:-1]])
    prev_lo = np.concatenate([[NAN], I["don55_low"].to_numpy()[:-1]])
    out["breakout_55"] = nanify(sgn(c > prev_hi, c < prev_lo), prev_hi)
    if "supertrend" in I:
        out["supertrend"] = I["supertrend"].to_numpy()
        a = I["adx14"].to_numpy()
        out["adx_trend"] = nanify(np.where(a > 25, np.sign(I["plus_di"] - I["minus_di"]), 0.0), a)
        out["stochastic"] = nanify(sgn(I["stoch_k"] < 20, I["stoch_k"] > 80), I["stoch_k"].to_numpy())
        top = np.fmax(I["ichi_cloud_a"], I["ichi_cloud_b"]).to_numpy()
        bot = np.fmin(I["ichi_cloud_a"], I["ichi_cloud_b"]).to_numpy()
        out["cloud"] = nanify(sgn(c > top, c < bot), top)
    if "obv" in I:
        o = I["obv"].to_numpy()
        out["obv_trend"] = nanify(sgn(o > sma(o, 50), o <= sma(o, 50)), sma(o, 50))
        if "mfi14" in I:
            out["mfi_extreme"] = nanify(sgn(I["mfi14"] < 20, I["mfi14"] > 80), I["mfi14"].to_numpy())
    return pd.DataFrame(out, index=df.index)


# ---------------------------------------------------------------- the event study
def event_study(c: np.ndarray, sig: np.ndarray, h: int = 21) -> dict:
    """Average log return over the next h bars when the signal is +1, minus when it is -1 (or minus all bars for
    one-sided signals), with a Newey-West t on the signed daily return series (sign x next-day return), which avoids
    the overlap problem of h-bar windows. The signal at t trades at t+1."""
    c = np.asarray(c, float)
    r1 = np.diff(np.log(c), append=NAN)                       # r1[t] = log(c[t+1]/c[t]): the return earned after signal t
    s = np.asarray(sig, float)
    ok = ~np.isnan(s) & ~np.isnan(r1)
    if ok.sum() < 120:
        return {"n": int(ok.sum()), "t": None}
    x = s[ok] * r1[ok]
    nw = labs.nw_mean(x, lags=max(5, h // 2))
    fwd = np.full(len(c), NAN)
    fwd[:-h] = np.log(c[h:] / c[:-h])
    on, off = (s == 1) & ~np.isnan(fwd), (s == -1) & ~np.isnan(fwd)
    return {"n": int(ok.sum()), "active": float(np.mean(s[ok] != 0)), "daily_edge": float(nw["mean"]), "t": float(nw["t"]),
            "p": float(nw["p"]), "fwd_bull": float(np.mean(fwd[on])) if on.any() else None, "fwd_bear": float(np.mean(fwd[off])) if off.any() else None,
            "fwd_all": float(np.nanmean(fwd)), "hit": float(np.mean(x[x != 0] > 0)) if (x != 0).any() else None}


def evidence_weight(t: float | None) -> float:
    """Shrink each signal's weight by its own t-statistic: t^2/(t^2 + 4) when the sign of the edge is right, 0 when it
    is wrong or unknown. A t of 2 earns half weight; a t of 0 earns none."""
    if t is None or not np.isfinite(t) or t <= 0:
        return 0.0
    return t * t / (t * t + 4)


def analyze(df: pd.DataFrame, name: str, bench: pd.Series | None = None, per_year: int = 252, h: int = 21, split: float = 0.5) -> dict:
    """Readings, signals, structure and the event study for one asset. The study's weights come from the first
    `split` of history and are judged on the rest (out of sample), then refit on all of it for today's score."""
    df = df.dropna(subset=["close"]).sort_index()
    I = indicators(df)
    S = signals(df, I)
    h_, l_, c, v = _cols(df)
    last = I.iloc[-1]
    cut = int(len(df) * split)
    studies, oos = {}, {}
    for k in S.columns:
        s = S[k].to_numpy()
        studies[k] = event_study(c, s, h)
        ins, out = event_study(c[:cut + 1], s[:cut + 1], h), event_study(c[cut:], s[cut:], h)
        oos[k] = {"t_in": ins.get("t"), "t_out": out.get("t"), "edge_out": out.get("daily_edge")}
    ps = [studies[k]["p"] for k in S.columns if studies[k].get("t") is not None]
    bh = labs.bh(ps) if ps else []
    j = 0
    for k in S.columns:
        if studies[k].get("t") is not None:
            studies[k]["bh"] = bh[j]
            j += 1
    # composite: today's signals weighted by in-sample evidence, judged out of sample, then today on full history
    sig_now = {k: (None if np.isnan(S[k].iloc[-1]) else int(S[k].iloc[-1])) for k in S.columns}
    w_full = {k: evidence_weight(studies[k].get("t")) for k in S.columns}
    composite = sum(w_full[k] * (sig_now[k] or 0) for k in S.columns) / len(S.columns)   # weak evidence shrinks it toward 0
    naive = float(np.mean([v_ for v_ in sig_now.values() if v_ is not None])) if any(v_ is not None for v_ in sig_now.values()) else 0.0
    w_in = {k: evidence_weight(oos[k]["t_in"]) for k in S.columns}
    comp_series = np.zeros(len(df))
    wsum = sum(w_in.values())
    if wsum > 0:
        for k in S.columns:
            comp_series += w_in[k] * np.nan_to_num(S[k].to_numpy())
        comp_series /= len(S.columns)
    oos_test = event_study(c[cut:], np.sign(comp_series[cut:]), h) if wsum > 0 else {"t": None}
    struct = {"levels": levels(h_, l_, c), "fibonacci": fibonacci(h_, l_), "pivots": pivots(h_, l_, c), "rsi_divergence": divergence(c, I["rsi14"].to_numpy()),
              "trend_template": trend_template(c), "range_52w": {"high": float(np.nanmax(c[-per_year:])), "low": float(np.nanmin(c[-per_year:])),
                                                               "from_high": float(c[-1] / np.nanmax(c[-per_year:]) - 1), "from_low": float(c[-1] / np.nanmin(c[-per_year:]) - 1)}}
    if "bb_width" in I and "kelt_upper" in I:
        struct["squeeze"] = bool(last["bb_upper"] < last["kelt_upper"] and last["bb_lower"] > last["kelt_lower"])
    if bench is not None:
        b = bench.reindex(df.index).ffill().to_numpy(float)
        rs = mansfield_rs(c, b)
        struct["relative_strength"] = {"mansfield": float(rs[-1]) if np.isfinite(rs[-1]) else None,
                                       "vs_bench_63": float((c[-1] / c[-64]) / (b[-1] / b[-64]) - 1) if len(c) > 64 and b[-64] > 0 else None}
    read = {k: (None if not np.isfinite(last[k]) else float(last[k])) for k in I.columns if k not in ("obv",)}
    read["close"] = float(c[-1])
    return {"name": name, "date": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1]), "bars": len(df), "ohlc": "high" in df,
            "volume": v is not None, "readings": read, "signals_now": sig_now, "studies": studies, "split": oos, "weights": w_full,
            "composite": float(composite), "naive_vote": naive, "composite_oos": {k: oos_test.get(k) for k in ("t", "daily_edge", "hit", "n")},
            "structure": struct, "horizon": h, "per_year": per_year}


def text(a: dict) -> list[str]:
    """Plain-English readings for one analysis."""
    r, st, out = a["readings"], a["structure"], []
    c = r["close"]
    if r.get("sma200"):
        out.append(f"{a['name']} is {c / r['sma200'] - 1:+.1%} from its 200-day average and {c / r['sma50'] - 1:+.1%} from its 50-day.")
    if r.get("rsi14") is not None:
        out.append(f"RSI(14) is {r['rsi14']:.0f}{' (overbought by the textbook)' if r['rsi14'] > 70 else ' (oversold by the textbook)' if r['rsi14'] < 30 else ''}.")
    rg = st["range_52w"]
    out.append(f"It sits {rg['from_high']:+.1%} from its 52-week high and {rg['from_low']:+.1%} above its low.")
    if st.get("trend_template"):
        tt = st["trend_template"]
        out.append(f"The stage-2 trend template passes {tt['passed']} of {tt['of']} tests.")
    if st.get("rsi_divergence"):
        out.append(f"A {st['rsi_divergence']} RSI divergence is in place.")
    good = [k for k, s in a["studies"].items() if s.get("t") is not None and s.get("bh", 1) < 0.05]
    out.append(f"Of {len(a['studies'])} signals tested on its own history, {len(good)} survive the false-discovery correction{': ' + ', '.join(good) if good else ''}.")
    out.append(f"The evidence-weighted composite is {a['composite']:+.2f} on a -1 to +1 scale (an equal vote would say {a['naive_vote']:+.2f}).")
    return out


def public(a: dict) -> dict:
    """What ships: readings, signals, studies and structure; no price series."""
    return {k: v for k, v in a.items()}
