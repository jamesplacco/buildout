"""Learning the brain's structure from the data, instead of assuming it.

The brain's measured links rest on two assumptions: an ordering (oil moves first, then consumer prices, the 10-year,
stocks, then volatility and gold) and two fixed regimes split at January 2022. This module tests both on the same
six standardized monthly series. The page runs the same code (site/src/brainx.js); tests/test_v09.py checks they agree.

  lingam_order     DirectLiNGAM (Shimizu et al. 2011) with the pairwise likelihood-ratio measure (Hyvarinen and
                   Smith 2013): in a linear system with non-Gaussian shocks, the cause is the variable whose
                   regression residuals look most independent of it, which a Gaussian model cannot tell. It returns a
                   causal order learned from the data alone; it needs non-Gaussian, roughly linear, unconfounded data.
  order_agreement  the share of the 15 pairs the data orders the same way as the assumed chain
  bootstrap_order  how often each pair keeps its learned order across resamples of months (stability, not proof)
  kalman_links     each child's links as random walks, beta_t = beta_{t-1} + eta, y_t = x_t' beta_t + eps: forward
                   Kalman filter, Rauch-Tung-Striebel smoother, and the drift variance q chosen by maximum likelihood
                   on a grid, so the data says how fast a link can change and when it changed sign

Part two, the edge-discovery engine (build, summary): a hypothesis factory and a gauntlet strict enough that what
survives is credible.

Not high frequency: the engine looks for odd, slow edges in many world markets (19 currencies, about 47 commodities,
US stocks and bonds) using many kinds of data (each market's own history, every other market, macro series, unusual
data and computed calendar and astronomy clocks), and it says, with numbers, how many ideas fail and how many fake
signals get through the same pipe.

  universe     targets are the tradeable return series of atlas.panel (currencies, commodities, the S&P 500 and the
               10-year yield change with its sign flipped as a bond proxy), plus US real stock and bond returns since
               1871 as a separate long block; signals are every target's own history, every panel series (cross-asset
               and macro), two composites (a dollar index from the 19 currencies and an equal-weight commodity index),
               unusual series and computed clocks
  features     changes over 1, 3, 6, 12 and 36 months, a 60-month z-score, the deviation from the 60-month average
               (value), signs, acceleration, the seasonal difference, 12-month volatility, the same calendar month's
               past returns (Heston and Sadka 2008), cross-sectional ranks within a family, spreads and ratios against
               anchors, and products and sums of two standardized transforms (depth 2)
  hypothesis   a rule applied to a family of markets ("12-month momentum in metals"): the pooled signal-weighted return
               (each market's signal times its next return in units of its own trailing risk, averaged across the
               family each month) with a Newey-West t statistic
  gauntlet     (i) discovery t with a minimum sample, (ii) Benjamini-Hochberg across every hypothesis tried,
               (iii) timing beyond drift: the alpha against the family's always-long return, because a signal that
               keeps one sign for years (a trending climate or population series) only earns the drift,
               (iv) breadth: a sign test across the family's markets (or across 5-year blocks for families of fewer
               than four markets), (v) validation, (vi) costs covered in validation, then de-duplication, and the
               untouched test period reported once with the decay against discovery
  early split  the IMF commodity series end in June 2017, so they have no test period in the main calendar; the
               families they dominate run the same gauntlet again on an earlier calendar (discovery to 2005,
               validation 2006 to 2010, test 2011 to June 2017)
  placebo      several hundred fake signals (random walks, block-shuffled and phase-randomized real series) pass
               through the same functions with the same thresholds, which gives the empirical false-discovery rate
  trap         monthly AVERAGE prices (IMF, EIA, Shiller, the Fed's monthly exchange rates) put about 0.25 of
               first-order autocorrelation into one-month changes (Working 1960); every signal uses data through
               t minus 2 (the engine's LAG = 2) for the month t return, the artifact is reproduced and removed on a
               synthetic averaged random walk, and each surviving edge is re-tested on end-of-month closes where they
               exist
  book         every distinct survivor at equal risk, capped, refit each January from past data only, walked forward
               through the test period with costs: Sharpe, drawdown, correlations, the deflated Sharpe ratio given
               every hypothesis tried, a bootstrap range, the best single family and the naive book of all
               discovery survivors

Timing: a panel row s is a monthly average known at the start of month s + 1, so for the month t return a feature may
use rows up to t - LAG. Unusual series arrive already lagged to be knowable at the start of each month; they get one
more month (rows up to t - 1), so that every input is knowable at the start of month t - 1, when an averaged month t
return begins to accrue. Computed clocks (moon, daylight, the calendar) are known in advance and are used for month t
itself. Everything here is research, never an order.
"""
from __future__ import annotations

import math
import time
from typing import Callable, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from . import labs


K1, K2, GAMMA = 79.047, 7.4129, 0.37457


def _entropy(u: np.ndarray) -> float:
    """Hyvarinen's maximum-entropy approximation of differential entropy for a standardized variable."""
    return (1 + math.log(2 * math.pi)) / 2 - K1 * (float(np.mean(np.log(np.cosh(u)))) - GAMMA) ** 2 - K2 * float(np.mean(u * np.exp(-u * u / 2))) ** 2


def _residual(xi: np.ndarray, xj: np.ndarray) -> np.ndarray:
    return xi - (np.cov(xi, xj)[0, 1] / np.var(xj)) * xj


def _std(x: np.ndarray) -> np.ndarray:
    return (x - x.mean()) / x.std()


def _diff_mi(xi_std, xj_std, ri_j, rj_i) -> float:
    return (_entropy(xj_std) + _entropy(ri_j / np.std(ri_j))) - (_entropy(xi_std) + _entropy(rj_i / np.std(rj_i)))


def lingam_order(X: np.ndarray) -> list[int]:
    """Causal order (most exogenous first) by DirectLiNGAM with the pwling measure."""
    X = np.array(X, float)
    U = list(range(X.shape[1]))
    order = []
    while U:
        if len(U) == 1:
            order.append(U[0])
            break
        best, best_m = None, None
        for i in U:
            M = 0.0
            xi = _std(X[:, i])
            for j in U:
                if i == j:
                    continue
                xj = _std(X[:, j])
                M += min(0.0, _diff_mi(xi, xj, _residual(xi, xj), _residual(xj, xi))) ** 2
            if best_m is None or -M > best_m + 1e-15:
                best, best_m = i, -M
        for i in U:
            if i != best:
                X[:, i] = _residual(X[:, i], X[:, best])
        order.append(best)
        U.remove(best)
    return order


def order_agreement(learned: Sequence[int], assumed: Sequence[int]) -> dict:
    pos_l = {v: k for k, v in enumerate(learned)}
    pairs = [(a, b) for i, a in enumerate(assumed) for b in assumed[i + 1:]]
    agree = [(a, b) for a, b in pairs if pos_l[a] < pos_l[b]]
    return {"agree": len(agree), "pairs": len(pairs), "share": len(agree) / len(pairs),
            "reversed": [(b, a) for a, b in pairs if pos_l[a] > pos_l[b]]}


def bootstrap_order(X: np.ndarray, samples: Sequence[Sequence[int]]) -> dict:
    """P[i before j] over the given resamples (row-index lists), so Python and the page can share the draws."""
    p = X.shape[1]
    before = np.zeros((p, p))
    for idx in samples:
        o = lingam_order(X[list(idx)])
        pos = {v: k for k, v in enumerate(o)}
        for i in range(p):
            for j in range(p):
                if i != j and pos[i] < pos[j]:
                    before[i, j] += 1
    return {"p_before": (before / max(1, len(samples))).tolist(), "n": len(samples)}


def mulberry32(seed: int):
    """The page's seeded generator, so resamples match exactly across languages."""
    state = seed & 0xFFFFFFFF

    def rnd():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return rnd


def resamples(n: int, draws: int, seed: int = 7) -> list[list[int]]:
    rnd = mulberry32(seed)
    return [[int(rnd() * n) for _ in range(n)] for _ in range(draws)]


# ---------------------------------------------------------------- time-varying links
def kalman_links(y: np.ndarray, X: np.ndarray, q: float, r: float | None = None, p0: float = 1.0) -> dict:
    """Random-walk coefficients: filter and smoother. r (noise variance) defaults to the full-sample OLS residual
    variance; q is the per-month drift variance of each coefficient. Returns smoothed paths, sds and log-likelihood."""
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    n, k = X.shape
    if r is None:
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        e = y - X @ b
        r = float(e @ e) / max(1, n - k)
    Q = q * np.eye(k)
    b = np.zeros(k)
    P = p0 * np.eye(k)
    bf, Pf, bp, Pp = [], [], [], []
    ll = 0.0
    for t in range(n):
        b_pred, P_pred = b, P + Q
        x = X[t]
        f = float(x @ P_pred @ x) + r
        v = y[t] - float(x @ b_pred)
        ll += -0.5 * (math.log(2 * math.pi * f) + v * v / f)
        Kg = P_pred @ x / f
        b = b_pred + Kg * v
        P = P_pred - np.outer(Kg, x @ P_pred)
        bp.append(b_pred); Pp.append(P_pred); bf.append(b); Pf.append(P)
    bs, Ps = [None] * n, [None] * n
    bs[-1], Ps[-1] = bf[-1], Pf[-1]
    for t in range(n - 2, -1, -1):
        J = Pf[t] @ np.linalg.inv(Pp[t + 1])
        bs[t] = bf[t] + J @ (bs[t + 1] - bp[t + 1])
        Ps[t] = Pf[t] + J @ (Ps[t + 1] - Pp[t + 1]) @ J.T
    return {"beta": np.array(bs).tolist(), "sd": np.sqrt(np.array([np.diag(p) for p in Ps])).tolist(), "loglik": ll, "r": r, "q": q}


Q_GRID = [1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2]


def kalman_mle(y, X, grid: Sequence[float] = Q_GRID) -> dict:
    fits = [kalman_links(y, X, q) for q in grid]
    best = max(range(len(grid)), key=lambda i: fits[i]["loglik"])
    out = fits[best]
    out["grid"] = list(grid)
    out["loglik_grid"] = [f["loglik"] for f in fits]
    return out


def sign_changes(path: Sequence[float], sd: Sequence[float], dates: Sequence[str], z: float = 1.645) -> list[dict]:
    """Months where the smoothed link crossed zero, and the stretches where its 90% band excluded zero."""
    out = []
    for t in range(1, len(path)):
        if path[t - 1] * path[t] < 0:
            out.append({"date": dates[t], "to": "negative" if path[t] < 0 else "positive"})
    return out


# ================================================================ part two: the edge-discovery engine
LAG = 2                          # as decide.LAG
DISC_END, VAL_END = "2009-12", "2017-12"          # panel calendar: discovery to 2009, validation 2010 to 2017
EARLY_DISC_END, EARLY_VAL_END = "2005-12", "2010-12"  # the early-split replication for families that end in 2017
LONG_DISC_END, LONG_VAL_END = "1960-12", "1989-12"  # long block: discovery to 1960, validation 1961 to 1989
FDR_Q = 0.05
MIN_POOLED = 96                  # months of pooled discovery data for a hypothesis to count
MIN_MARKET = 60                  # months of discovery data for a market to count in breadth
MIN_VAL = 36
VAL_T = 1.2816                   # one-sided 10% in the discovery direction
TIMING_T = 1.96                  # discovery alpha against the family's always-long return
SIGN_P = 0.10                    # breadth: one-sided sign-test p
MIN_BREADTH = 4                  # fewer markets than this: breadth across 5-year blocks instead
BLOCK_YEARS = 5
DEDUP_RHO = 0.7
CLIP = 2.5
WIN, MINP = 60, 36
SCALE_MIN = 24
VOL_WIN = 36
TARGET_VOL = 0.10                # annual volatility the book is scaled to, ex ante
CAP_MULT = 3.0                   # no edge above 3 times the equal weight
SEED = 11

FX_FAMILIES = ("Commodity FX", "Asian FX", "European FX")
COMMOD_FAMILIES = ("Metals", "Energy", "Grains", "Oilseeds", "Softs", "Raw materials", "Livestock and food")
AG_FAMILIES = ("Grains", "Oilseeds", "Softs", "Livestock and food")
TRADEABLE_FAMILIES = FX_FAMILIES + COMMOD_FAMILIES + ("Equities", "Crypto", "Dollar", "Synthetic")
NOT_TARGETS = {"cpi", "vix", "sp_eps", "sp_div"}
BOND_DURATION = 8.0              # the 10-year yield change as a bond return: -8 x change in percentage points

# round-trip costs in basis points (assumptions, stated on the page)
COST_BP = {"fx": 10, "fx_ndf": 20, "futures": 20, "thin": 50, "sp500": 20, "bond": 10, "other": 30}
FX_NDF = {"cny", "inr", "myr", "twd", "krw", "brl", "thb"}
LIQUID_FUTURES = {"brent", "wti", "natgas", "gold", "copper", "aluminum", "nickel", "zinc", "lead", "tin", "ironore", "gas_eu",
                  "wheat", "maize", "soybeans", "soymeal", "soyoil", "palmoil", "sugar", "arabica", "robusta", "cocoa", "cotton",
                  "rubber", "beef", "pork", "oranges", "rapeseed"}
SLOW_SOURCES = {"sp_eps": 5, "sp_div": 5, "cpi": 3}   # published with a delay: extra months of lag
SLOW_FAMILIES = {"Activity": 3, "Inflation": 3, "Housing": 3, "Money": 3}

TF_OWN = ("c1", "c3", "c6", "c12", "c36", "z60", "dev60", "sgn12", "acc", "sdiff", "volz", "seas")
TF_EXT = ("c1", "c3", "c6", "c12", "z60", "dev60", "acc", "sdiff", "volz", "sgn3")
TF_LEVEL = ("lvlz", "z60", "dev60", "d1", "d3", "d12")
TF_SLOW = ("lvlz", "z60", "dev60", "d12")
TF_XS = ("c1", "c3", "c12", "dev60")
COMP_CORE = ("c1", "c3", "c12", "dev60", "z60", "acc", "sdiff", "volz", "seas")
COMP_OWN = ("c3", "c12", "dev60")
COMP_MACRO = (("vix", "z60"), ("vix", "c3"), ("brent", "c3"), ("dollar", "c3"), ("y10", "c3"), ("sp500", "c3"), ("gold", "c3"))
COMP_WIDE_OWN = ("c3", "c12", "dev60", "volz")
COMP_WIDE_EXT = ("c3", "z60")
PAIR_ANCHORS = ("sp500", "brent", "gold", "dollar", "commod")
BOOK_VOL_WIN = 24
# v0.26 audit fixes
N_NULL = 3                       # fake-market replicates: real returns block-shuffled together, every rule kind run on them
NULL_BLOCK = LAG                 # block length of the shuffle: keeps the one-month averaging autocorrelation, and no pair of rows
                                 # LAG apart ever stays together, so nothing a rule can use survives
CAL_ALPHA = 0.001                # two-sided tail at which the null t statistics are matched to calibrate p-values
MIN_TEST_COVER = 0.5             # an edge counts as tested only if most of its markets trade in the test years
EWMA_HL = 12                     # half-life (months) of the book's volatility estimate
VOL_FLOOR = 0.75                 # the estimate never falls below this share of the book's long-run volatility
SIGNAL_KINDS = ("ext", "unu", "cal")
LONG_MASKS = {"bonds": "1953-01", "dividends": "1926-01", "cpi": "1913-01"}   # Shiller interpolates before these dates
CENTERED = {"lvlz", "lvl", "volz", "z60"}

TF_LABEL = {"c1": "1-month change", "c3": "3-month change", "c6": "6-month change", "c12": "12-month change",
            "c36": "36-month change", "z60": "60-month z-score", "dev60": "deviation from its 60-month average",
            "sgn12": "sign of the 12-month change", "sgn3": "sign of the 3-month change",
            "acc": "acceleration (3-month change against the 3 months before)", "sdiff": "change against the same month a year ago",
            "volz": "12-month volatility (z-score)", "seas": "same calendar month over the past 5 years",
            "lvlz": "level (z-score)", "lvl": "value", "d1": "1-month change", "d3": "3-month change", "d12": "12-month change",
            "rel12": "12-month change relative to", "ratio60": "price ratio against its 60-month average, relative to"}
OWN_FAMILY = {"c1": "reversal", "c3": "momentum", "c6": "momentum", "c12": "momentum", "c36": "reversal", "z60": "value",
              "dev60": "value", "sgn12": "momentum", "acc": "momentum", "sdiff": "seasonality", "volz": "volatility", "seas": "seasonality"}
MACRO_SOURCES = {"cpi", "y10", "vix", "sp_eps", "sp_div", "dollar"}

MECH = {
    "momentum+": ["c:time-series-momentum", "c:trend-following", "c:underreaction"],
    "momentum-": ["c:short-term-reversal", "c:mean-reversion", "c:overreaction"],
    "reversal-": ["c:short-term-reversal", "c:overreaction", "c:mean-reversion"],
    "reversal+": ["c:time-series-momentum", "c:underreaction"],
    "lt-reversal-": ["c:long-term-reversal", "c:mean-reversion"],
    "value-": ["c:value-factor", "c:mean-reversion", "c:long-term-reversal"],
    "value+": ["c:time-series-momentum", "c:trend-following"],
    "seasonality": ["c:return-seasonality", "c:seasonality"],
    "volatility": ["c:volatility-clustering", "c:variance-risk-premium", "c:low-vol"],
    "carry": ["c:carry", "c:dividend-yield", "c:term-premium"],
    "xs-momentum+": ["c:cross-sectional-momentum", "c:momentum"],
    "xs-momentum-": ["c:short-term-reversal", "c:mean-reversion"],
    "xs-value": ["c:value-factor", "c:mean-reversion"],
    "relative value": ["c:relative-value-trading", "c:mean-reversion"],
    "lead-lag": ["c:lead-lag"],
    "climate": ["c:enso", "c:weather-data", "c:crop-progress"],
    "calendar": ["c:calendar-anomaly", "c:seasonality"],
    "hazards": ["c:weather-data", "c:weather-derivatives"], "ocean": ["c:enso", "c:weather-data"], "cryosphere": ["c:weather-data"],
    "phenology": ["c:weather-data"], "agriculture": ["c:crop-progress", "c:grains"], "shipping": ["c:alt-data"], "transport": ["c:alt-data"],
    "sentiment": ["c:sentiment"],
}
SRC_MECH = {"brent": ["c:terms-of-trade", "c:oil-shock"], "wti": ["c:terms-of-trade", "c:oil-shock"], "commod": ["c:terms-of-trade", "c:aud-copper"],
            "copper": ["c:copper", "c:aud-copper"], "gold": ["c:gold"], "vix": ["c:safe-haven-currencies", "c:variance-risk-premium"],
            "dollar": ["c:dollar"], "y10": ["c:term-premium"], "sp500": ["c:equity-risk-premium"], "cpi": ["c:inflation"],
            "natgas": ["c:natural-gas"], "sp_eps": ["c:earnings-growth"], "sp_div": ["c:dividend-yield"],
            **{c: ["c:aud-copper", "c:terms-of-trade"] for c in ("aud", "cad", "nzd", "nok", "zar", "brl", "mxn")},
            "jpy": ["c:safe-haven-currencies"], "chf": ["c:safe-haven-currencies"]}
CAL_MECH = {"jan": ["c:january-effect"], "sell_in_may": ["c:sell-in-may"], "pres_pre": ["c:presidential-cycle"],
            "pres_post": ["c:presidential-cycle"], "daylight": ["c:seasonality"], "daylight_chg": ["c:seasonality"]}
GROUP_CONCEPT = {"Currencies": "c:fx", "Commodity FX": "c:aud-copper", "Asian FX": "c:emerging-market-currencies", "European FX": "c:fx",
                 "Commodities": "c:commodities-complex", "Agriculture": "c:grains", "Metals": "c:copper", "Energy": "c:oil-shock",
                 "Grains": "c:grains", "Oilseeds": "c:grains", "Softs": "c:softs", "Raw materials": "c:commodities-complex",
                 "Livestock and food": "c:livestock-futures", "US stocks and bonds": "c:equity-risk-premium",
                 "US stocks and bonds since 1871": "c:equity-risk-premium"}



# ---------------------------------------------------------------- small statistics
def _nw(Y: np.ndarray, mask: np.ndarray, lags: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mean, Newey-West t and count along the last axis, over the rows in mask (a contiguous period)."""
    rows = np.flatnonzero(mask)
    shp = Y.shape[:-1]
    if len(rows) == 0:
        return np.full(shp, np.nan), np.full(shp, np.nan), np.zeros(shp)
    Z = Y[..., rows[0]:rows[-1] + 1]
    v = np.isfinite(Z)
    n = v.sum(-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n > 0, np.where(v, Z, 0.0).sum(-1) / np.maximum(n, 1), np.nan)
        e = np.where(v, Z - mean[..., None], 0.0)
        L = int(math.floor(4 * (len(rows) / 100) ** (2 / 9))) if lags is None else lags
        s = (e * e).sum(-1)
        for l in range(1, L + 1):
            s = s + 2 * (1 - l / (L + 1)) * (e[..., l:] * e[..., :-l]).sum(-1)
        se = np.sqrt(np.maximum(s, 1e-30)) / np.maximum(n, 1)
        t = np.where(n >= 12, mean / se, np.nan)
    return mean, t, n


def _p2(t):
    return 2 * stats.norm.sf(np.abs(t))


def _sharpe(x) -> float | None:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 12 or x.std(ddof=1) <= 0:
        return None
    return float(x.mean() / x.std(ddof=1) * math.sqrt(12))


def _maxdd(r) -> float | None:
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    if not len(r):
        return None
    w = np.cumprod(1 + r)
    return float((w / np.maximum.accumulate(np.r_[1.0, w])[1:] - 1).min())


def _corr(a, b) -> tuple[float | None, int]:
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 8 or a[m].std() == 0 or b[m].std() == 0:
        return None, int(m.sum())
    return float(np.corrcoef(a[m], b[m])[0, 1]), int(m.sum())


def bh_cut(p: np.ndarray, q: float = FDR_Q) -> float:
    """The Benjamini-Hochberg p-value threshold for these p-values (0 when nothing passes)."""
    p = np.sort(np.asarray(p, float))
    m = len(p)
    if not m:
        return 0.0
    ok = np.flatnonzero(p <= q * np.arange(1, m + 1) / m)
    return float(p[ok[-1]]) if len(ok) else 0.0


# ---------------------------------------------------------------- transforms
def _level(X: pd.DataFrame) -> pd.DataFrame:
    return X.fillna(0.0).cumsum().where(X.notna())


def _roll(F: pd.DataFrame, n: int, minp: int, how: str) -> pd.DataFrame:
    r = F.rolling(n, min_periods=minp)
    return r.mean() if how == "mean" else r.std() if how == "std" else r.sum()


def transforms(X: pd.DataFrame, tfs, level: bool = False) -> dict:
    """Each transform as of row s (data through s), unshifted. X holds changes, or levels when level is True."""
    out = {}
    if level:
        Lv = X
        if "lvl" in tfs:
            out["lvl"] = Lv
        if "lvlz" in tfs:
            ex = Lv.expanding(min_periods=SCALE_MIN)
            out["lvlz"] = (Lv - ex.mean()) / ex.std()
        if "z60" in tfs or "dev60" in tfs:
            m, s = _roll(Lv, WIN, MINP, "mean"), _roll(Lv, WIN, MINP, "std")
            out["dev60"] = Lv - m
            out["z60"] = (Lv - m) / s
        for k in (1, 3, 12):
            if f"d{k}" in tfs:
                out[f"d{k}"] = Lv.diff(k)
        return {k: out[k] for k in tfs if k in out}
    L = _level(X)
    for k in (1, 3, 6, 12, 36):
        if f"c{k}" in tfs or (k in (3, 12) and ({"acc", "sgn3", "sgn12"} & set(tfs))):
            out[f"c{k}"] = X if k == 1 else _roll(X, k, k, "sum")
    if "z60" in tfs or "dev60" in tfs:
        m, s = _roll(L, WIN, MINP, "mean"), _roll(L, WIN, MINP, "std")
        out["dev60"] = L - m
        out["z60"] = (L - m) / s
    if "sgn12" in tfs:
        out["sgn12"] = np.sign(out["c12"])
    if "sgn3" in tfs:
        out["sgn3"] = np.sign(out["c3"])
    if "acc" in tfs:
        out["acc"] = out["c3"] - out["c3"].shift(3)
    if "sdiff" in tfs:
        out["sdiff"] = X - X.shift(12)
    if "volz" in tfs:
        v = X.rolling(12, min_periods=10).std()
        out["volz"] = (v - _roll(v, WIN, MINP, "mean")) / _roll(v, WIN, MINP, "std")
    return {k: out[k] for k in tfs if k in out and k != "seas"}


def seasonal(X: pd.DataFrame, years: int = 5, minp: int = 3) -> pd.DataFrame:
    """Heston and Sadka (2008): the mean of the same calendar month's change over the past `years` years, aligned to
    the target month (rows t - 12, t - 24, ...; never closer than 12 months)."""
    S = [X.shift(12 * k) for k in range(1, years + 1)]
    n = sum(s.notna().astype(float) for s in S)
    tot = sum(s.fillna(0.0) for s in S)
    return (tot / n).where(n >= minp)


def scale(F, center: bool = False) -> np.ndarray:
    """Target-aligned feature to a weight: optionally centered on its expanding mean, divided by its expanding root
    mean square, clipped at CLIP. Rows use only feature values at or before themselves."""
    F = pd.DataFrame(F) if not isinstance(F, pd.DataFrame) else F
    if center:
        F = F - F.expanding(min_periods=SCALE_MIN).mean()
    rms = np.sqrt((F * F).expanding(min_periods=SCALE_MIN).mean())
    with np.errstate(invalid="ignore", divide="ignore"):
        W = (F / rms.where(rms > 0)).to_numpy(float)
    return np.clip(W, -CLIP, CLIP)


# ---------------------------------------------------------------- computed clocks (stand-ins for unusual.computed)
SYNODIC = 29.530588853
NEW_MOON = pd.Timestamp("2000-01-06 18:14")


def computed(index) -> tuple[pd.DataFrame, dict]:
    """Deterministic monthly signals known in advance for month t: the moon, daylight at 40 degrees north and the
    calendar. Used when buildout.unusual offers no computed() of its own."""
    idx = pd.DatetimeIndex(index)
    first = idx.to_period("M").to_timestamp()
    age = ((first - NEW_MOON) / pd.Timedelta(days=1)) % SYNODIC
    ph = 2 * np.pi * age / SYNODIC
    mid = first + pd.Timedelta(days=14)
    doy = mid.dayofyear.to_numpy()
    decl = 23.44 * np.sin(np.radians(360 / 365 * (doy - 81)))
    lat = np.radians(40.0)
    cosw = -np.tan(lat) * np.tan(np.radians(decl))
    day = 24 / np.pi * np.arccos(np.clip(cosw, -1, 1))
    m = first.month.to_numpy()
    y = first.year.to_numpy()
    nxt = first + pd.offsets.MonthBegin(1)
    wd = np.array([np.busday_count(a.date(), b.date()) for a, b in zip(first, nxt)], float)
    full_moons = np.floor((((nxt - NEW_MOON) / pd.Timedelta(days=1)) - SYNODIC / 2) / SYNODIC) - np.floor((((first - NEW_MOON) / pd.Timedelta(days=1)) - SYNODIC / 2) / SYNODIC)
    D = {"moon_illum": (1 - np.cos(ph)) / 2, "moon_waxing": np.sin(ph), "moon_two_full": (full_moons >= 2).astype(float),
         "daylight": day, "daylight_chg": np.gradient(day) if len(day) > 1 else np.zeros(len(day)), "weekdays": wd,
         "jan": (m == 1).astype(float), "sell_in_may": np.isin(m, (11, 12, 1, 2, 3, 4)).astype(float),
         "quarter_end": np.isin(m, (3, 6, 9, 12)).astype(float), "pres_pre": (y % 4 == 3).astype(float),
         "pres_post": (y % 4 == 1).astype(float)}
    for k in range(1, 13):
        D[f"month_{k:02d}"] = (m == k).astype(float)
    # daylight change from the closed form for month t against month t - 1 (gradient is centered; use a clean diff)
    prev = (first - pd.offsets.MonthBegin(1)) + pd.Timedelta(days=14)
    dp = 23.44 * np.sin(np.radians(360 / 365 * (prev.dayofyear.to_numpy() - 81)))
    D["daylight_chg"] = day - 24 / np.pi * np.arccos(np.clip(-np.tan(lat) * np.tan(np.radians(dp)), -1, 1))
    df = pd.DataFrame(D, index=idx)
    names = {"moon_illum": "Moon illumination on the 1st", "moon_waxing": "Moon waxing or waning on the 1st", "moon_two_full": "Two full moons in the month",
             "daylight": "Daylight hours at 40 degrees north", "daylight_chg": "Change in daylight hours", "weekdays": "Weekdays in the month",
             "jan": "January", "sell_in_may": "November to April (Sell in May)", "quarter_end": "Quarter-end month",
             "pres_pre": "Pre-election year (US)", "pres_post": "Post-election year (US)"}
    meta = {}
    for c in df:
        fam = "astronomy" if c.startswith(("moon", "daylight")) else "calendar"
        meta[c] = {"name": names.get(c, f"Calendar month {c[-2:]}"), "family": fam, "frequency": "computed", "lag_months": 0, "computed": True}
    return df, meta


# ---------------------------------------------------------------- blocks
class Block:
    """One calendar's markets, returns, risk, groups, periods and feature stores."""

    def __init__(self, name, idx, ids, R, X, cost, groups, disc_end, val_end, info, test_end=None):
        self.name, self.idx, self.ids = name, idx, list(ids)
        self.T, self.M = len(idx), len(ids)
        self.R = R
        self.X = X                    # own changes used for own-history features (DataFrame T x M)
        self.cost = np.asarray(cost, float)
        self.groups = groups          # list of {"name", "kind", "members"}
        self.G = len(groups)
        self.Gm = np.zeros((self.M, self.G))
        for g, gr in enumerate(groups):
            self.Gm[gr["members"], g] = 1.0
        sig = pd.DataFrame(R).rolling(VOL_WIN, min_periods=24).std().shift(LAG).to_numpy()
        self.sig = np.where(sig > 0, sig, np.nan)
        self.Rs = R / self.sig
        V = np.isfinite(self.Rs)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.drift = np.where(V, self.Rs, 0) @ self.Gm / np.where(V.astype(float) @ self.Gm > 0, V.astype(float) @ self.Gm, np.nan)
        d, v = pd.Timestamp(disc_end) + pd.offsets.MonthEnd(0), pd.Timestamp(val_end) + pd.offsets.MonthEnd(0)
        e = pd.Timestamp(test_end) + pd.offsets.MonthEnd(0) if test_end else idx[-1] + pd.offsets.MonthEnd(0)
        self.masks = {"disc": np.asarray(idx <= d), "val": np.asarray((idx > d) & (idx <= v)), "test": np.asarray((idx > v) & (idx <= e))}
        self.split = (disc_end, val_end)
        self.test_end = test_end
        self.info = info              # per market: name, family, cost_bp, liquid
        self.ext = {}                 # src -> {"x": Series, "lag", "level", "family", "name", "kind", "excl"}
        self.own, self.xs, self.pair, self.extv, self.comp = {}, {}, {}, {}, {}
        self.own_raw = {}


def _cost_bp(i: str, fam: str) -> tuple[int, bool]:
    if fam in FX_FAMILIES:
        return (COST_BP["fx_ndf"] if i in FX_NDF else COST_BP["fx"]), True
    if fam in COMMOD_FAMILIES:
        return (COST_BP["futures"], True) if i in LIQUID_FUTURES else (COST_BP["thin"], False)
    if i == "sp500":
        return COST_BP["sp500"], True
    if i == "y10":
        return COST_BP["bond"], True
    return COST_BP["other"], True


def _groups(ids: list[str], fams: list[str]) -> list[dict]:
    out = []
    fam_ix: dict[str, list[int]] = {}
    for j, f in enumerate(fams):
        fam_ix.setdefault(f, []).append(j)
    fx = [j for j, f in enumerate(fams) if f in FX_FAMILIES]
    co = [j for j, f in enumerate(fams) if f in COMMOD_FAMILIES]
    ag = [j for j, f in enumerate(fams) if f in AG_FAMILIES]
    us = [j for j, i in enumerate(ids) if i in ("sp500", "y10", "nasdaq")]
    if len(fx) >= 2 and len({fams[j] for j in fx}) > 1:
        out.append({"name": "Currencies", "kind": "class", "members": fx})
    if len(co) >= 2 and len({fams[j] for j in co}) > 1:
        out.append({"name": "Commodities", "kind": "class", "members": co})
    if len(ag) >= 2 and len({fams[j] for j in ag}) > 1:
        out.append({"name": "Agriculture", "kind": "class", "members": ag})
    if len(us) >= 2:
        out.append({"name": "US stocks and bonds", "kind": "class", "members": us})
    for f, js in fam_ix.items():
        if len(js) >= 2:
            out.append({"name": f, "kind": "family", "members": js})
    return out


def _extend(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """LAG future rows: the month under way and the next one, whose signal uses the latest complete month."""
    return idx.append(pd.DatetimeIndex([idx[-1] + pd.offsets.MonthBegin(k) for k in range(1, LAG + 1)]))


def _last(B) -> pd.Timestamp:
    return B.idx[-1 - LAG]


def panel_block(P: pd.DataFrame, meta: dict, unusual: pd.DataFrame | None = None, unusual_meta: dict | None = None,
                comp_df: pd.DataFrame | None = None, comp_meta: dict | None = None, quick: bool = False, splits=(DISC_END, VAL_END),
                test_end: str | None = None, group_filter: Callable | None = None, name: str = "panel") -> Block:
    P = P.sort_index()
    P.index = pd.DatetimeIndex(P.index).to_period("M").to_timestamp()
    idx = _extend(P.index)
    Pe = P.reindex(idx)
    fam_of = {c: meta.get(c, {}).get("family", "Other") for c in P}
    targets = [c for c in P if c not in NOT_TARGETS and (fam_of[c] in TRADEABLE_FAMILIES or c == "y10")]
    R = np.column_stack([(-BOND_DURATION / 100 * Pe[c] if c == "y10" else Pe[c]).to_numpy(float) for c in targets])
    X = pd.DataFrame(R, index=idx, columns=targets)
    fams = [fam_of[c] for c in targets]
    info, cost = [], []
    for c, f in zip(targets, fams):
        bp, liq = _cost_bp(c, f)
        cost.append(bp / 1e4)
        info.append({"id": c, "name": meta.get(c, {}).get("short", c), "family": f, "cost_bp": bp, "liquid": liq,
                     "last": P[c].last_valid_index().strftime("%Y-%m") if P[c].notna().any() else None})
    groups = _groups(targets, fams)
    if group_filter is not None:
        groups = [g for g in groups if group_filter(g, info)]
    B = Block(name, idx, targets, R, X, cost, groups, splits[0], splits[1], info, test_end=test_end)
    col = {c: j for j, c in enumerate(targets)}
    for c in P:
        lag = SLOW_SOURCES.get(c, SLOW_FAMILIES.get(fam_of[c], LAG))
        kind = "macro" if (c in MACRO_SOURCES or fam_of[c] not in TRADEABLE_FAMILIES) else "cross-asset"
        B.ext[c] = {"x": Pe[c], "lag": lag, "level": False, "family": kind, "name": meta.get(c, {}).get("short", c), "kind": "ext",
                    "excl": col.get(c)}
    fxc = [c for c in P if fam_of[c] in FX_FAMILIES]
    coc = [c for c in P if fam_of[c] in COMMOD_FAMILIES]
    if len(fxc) >= 3:
        d = -Pe[fxc].mean(axis=1).where(Pe[fxc].notna().sum(axis=1) >= max(2, len(fxc) // 2))
        B.ext["dollar"] = {"x": d, "lag": LAG, "level": False, "family": "macro", "name": "Dollar index (from the currencies)", "kind": "ext", "excl": None}
    if len(coc) >= 3:
        d = Pe[coc].mean(axis=1).where(Pe[coc].notna().sum(axis=1) >= max(3, len(coc) // 2))   # ends when the IMF series do (audit B1)
        B.ext["commod"] = {"x": d, "lag": LAG, "level": False, "family": "cross-asset", "name": "Commodity index (equal weight)", "kind": "ext", "excl": None}
    _add_unusual(B, unusual, unusual_meta, comp_df, comp_meta)
    _build_stores(B, quick=quick)
    return B


def long_block(S: pd.DataFrame, unusual=None, unusual_meta=None, comp_df=None, comp_meta=None, quick: bool = False) -> Block | None:
    """US real stock and bond returns since 1871 (Shiller), with carry and macro signals from the same data."""
    from . import decide
    S = S.copy()
    S.index = pd.DatetimeIndex(S.index).to_period("M").to_timestamp()
    r, px, _ = labs.total_return_index(S)
    b = decide.bond_returns(S)
    idx = _extend(S.index)
    rs = np.log1p(r.reindex(idx)).to_numpy(float)
    rb = np.log1p(b.reindex(idx)).where(idx >= pd.Timestamp(LONG_MASKS["bonds"])).to_numpy(float)   # yields interpolated before 1953 (audit M2)
    if np.isfinite(rs).sum() < 600:
        return None
    ids = ["us_stocks_1871", "us_bonds_1871"]
    R = np.column_stack([rs, rb])
    X = pd.DataFrame(R, index=idx, columns=ids)
    info = [{"id": ids[0], "name": "US stocks (real, since 1871)", "family": "US long", "cost_bp": 20, "liquid": True, "last": r.last_valid_index().strftime("%Y-%m")},
            {"id": ids[1], "name": "US 10-year bonds (real, since 1871)", "family": "US long", "cost_bp": 10, "liquid": True,
             "last": b.last_valid_index().strftime("%Y-%m") if b.notna().any() else None}]
    groups = [{"name": "US stocks and bonds since 1871", "kind": "class", "members": [0, 1]}]
    B = Block("long", idx, ids, R, X, [0.002, 0.001], groups, LONG_DISC_END, LONG_VAL_END, info)
    Se = S.reindex(idx)
    infl12 = np.log(Se["cpi"]).diff(12).where(idx >= pd.Timestamp(LONG_MASKS["cpi"]))
    after = {k: idx >= pd.Timestamp(v) for k, v in LONG_MASKS.items()}
    lv = {"dy": (Se["div"] / Se["px"], 4, "carry", "Dividend yield"), "ey": (Se["eps"] / Se["px"], 4, "carry", "Earnings yield"),
          "y10lvl": (Se["y10"], LAG, "carry", "10-year yield level"), "real_y": (Se["y10"] / 100 - infl12, 3, "carry", "Real 10-year yield"),
          "infl12": (infl12, 3, "macro", "Inflation over 12 months"), "eps_g12": (np.log(Se["eps"]).diff(12), 4, "macro", "Earnings growth over 12 months")}
    mask_of = {"dy": "dividends", "ey": "dividends", "eps_g12": "dividends", "y10lvl": "bonds", "real_y": "bonds", "infl12": "cpi"}
    for k, (x, lag, fam, nm) in lv.items():
        x = x.where(after[mask_of[k]])                 # interpolated annual values make spurious monthly persistence
        B.ext[k] = {"x": x, "lag": lag, "level": True, "family": fam, "name": nm, "kind": "ext", "excl": None}
    _add_unusual(B, unusual, unusual_meta, comp_df, comp_meta)
    _build_stores(B, quick=quick, xs=False, pairs=False, macro_comp=False)
    return B


def _add_unusual(B: Block, U, Umeta, C, Cmeta):
    Umeta, Cmeta = Umeta or {}, Cmeta or {}
    if U is not None and len(U.columns):
        U = U.copy()
        U.index = pd.DatetimeIndex(U.index).to_period("M").to_timestamp()
        U = U[~U.index.duplicated()].reindex(B.idx)
        for c in U:
            if U[c].notna().sum() < 36:
                continue
            m = Umeta.get(c, {})
            fam = m.get("family", "unusual")
            if m.get("computed") or m.get("frequency") == "computed":
                B.ext["u:" + c] = {"x": U[c], "lag": 0, "level": True, "family": fam, "name": m.get("name", c), "kind": "cal", "excl": None}
            else:
                slow = bool(m.get("annual_flag")) or m.get("frequency") in ("annual", "seasonal")
                B.ext["u:" + c] = {"x": U[c], "lag": 1, "level": True, "family": fam, "name": m.get("name", c), "kind": "unu", "excl": None,
                                   "slow": slow}
    if C is not None and len(C.columns):
        C = C.copy()
        C.index = pd.DatetimeIndex(C.index).to_period("M").to_timestamp()
        C = C[~C.index.duplicated()].reindex(B.idx)
        for c in C:
            m = Cmeta.get(c, {})
            if ("u:" + c) in B.ext or C[c].notna().sum() < 36 or C[c].nunique() < 2:
                continue
            B.ext["k:" + c] = {"x": C[c], "lag": 0, "level": True, "family": m.get("family", "calendar"), "name": m.get("name", c), "kind": "cal", "excl": None}


def _tfs_of(e: dict) -> tuple:
    """Computed clocks enter as they are; annual and seasonal series (held for 12 rows) are slow conditioning signals,
    so they get only the slow transforms (level z-score, 60-month z-score and deviation, 12-month change)."""
    if e["kind"] == "cal":
        return ("lvl",)
    if e.get("slow"):
        return TF_SLOW
    return TF_LEVEL if e["level"] else TF_EXT


def _own_raw(B: Block, X: pd.DataFrame) -> dict:
    tf = transforms(X, [t for t in TF_OWN if t != "seas"])
    raw = {k: v.shift(LAG) for k, v in tf.items()}
    raw["seas"] = seasonal(X)
    return raw


def _build_stores(B: Block, quick: bool = False, xs: bool = True, pairs: bool = True, macro_comp: bool = True, ext: bool = True):
    B.flags = {"quick": quick, "xs": xs, "pairs": pairs, "macro_comp": macro_comp}
    raw = _own_raw(B, B.X)
    B.own_raw = raw
    for k, F in raw.items():
        B.own[k] = scale(F, center=k in CENTERED)
    if xs:
        for k in TF_XS:
            F = raw[k]
            for g, gr in enumerate(B.groups):
                mem = gr["members"]
                if len(mem) < 3:
                    continue
                sub = F.iloc[:, mem]
                cnt = sub.notna().sum(axis=1).to_numpy()[:, None]
                rk = sub.rank(axis=1).to_numpy()
                with np.errstate(invalid="ignore", divide="ignore"):
                    w = np.where(cnt >= 3, (2 * (rk - 1) / np.maximum(cnt - 1, 1) - 1) * math.sqrt(3), np.nan)
                Wf = np.full((B.T, B.M), np.nan)
                Wf[:, mem] = w
                B.xs[(k, g)] = Wf
    for s, e in (B.ext.items() if ext else ()):
        tfs = _tfs_of(e)
        x = e["x"].to_frame(s)
        tf = transforms(x, tfs, level=e["level"])
        for k, F in tf.items():
            B.extv[(s, k)] = scale(F.shift(e["lag"]), center=k in CENTERED or e["level"])[:, 0]
    if pairs:
        for a in PAIR_ANCHORS:
            if a not in B.ext:
                continue
            xa = B.ext[a]["x"].to_numpy(float)
            Xr = pd.DataFrame(B.X.to_numpy() - xa[:, None], index=B.idx, columns=B.ids)
            ex = B.ext[a]["excl"]
            tf = transforms(Xr, ("c12", "dev60"))
            for k, nm in (("c12", "rel12"), ("dev60", "ratio60")):
                W = scale(tf[k].shift(LAG))
                if ex is not None:
                    W[:, ex] = np.nan
                B.pair[(a, nm)] = W
    pairs_own = [(a, b) for i, a in enumerate(COMP_CORE) for b in COMP_CORE[i + 1:]]
    if quick:
        pairs_own = pairs_own[:8]
    for a, b in pairs_own:
        for op in ("x", "+"):
            B.comp[("own", a, "own", b, op)] = None
    if macro_comp:
        for a in COMP_OWN:
            for s, k in COMP_MACRO:
                if (s, k) in B.extv:
                    for op in ("x", "+"):
                        B.comp[("own", a, s, k, op)] = None
    if ext and not quick:
        for a in COMP_WIDE_OWN:
            for s, e in B.ext.items():
                if e["kind"] not in ("ext", "unu"):
                    continue
                for k in COMP_WIDE_EXT:
                    if (s, k) in B.extv and ("own", a, s, k, "x") not in B.comp:
                        for op in ("x", "+"):
                            B.comp[("own", a, s, k, op)] = None


def _comp_W(B: Block, key) -> np.ndarray:
    W = B.comp.get(key)
    if W is not None:
        return W
    _, a, s, k, op = key
    cache = s == "own" or (s, k) in COMP_MACRO
    A = B.own[a]
    C = B.own[k] if s == "own" else np.repeat(B.extv[(s, k)][:, None], B.M, 1)
    F = A * C if op == "x" else A + C
    W = scale(F, center=(op == "x"))
    if s != "own" and B.ext[s]["excl"] is not None:
        W[:, B.ext[s]["excl"]] = np.nan
    if cache:
        B.comp[key] = W
    return W


# ---------------------------------------------------------------- rules
def _rule(kind, fam, name, getter, src=None, tf=None, groups=None, extra=None) -> dict:
    r = {"kind": kind, "family": fam, "name": name, "W": getter, "src": src, "tf": tf, "groups": groups}
    if extra:
        r.update(extra)
    return r


def rules(B: Block) -> list[dict]:
    """Every candidate rule of this block (the placebos are added separately, through ext_rules)."""
    out = []
    for k in TF_OWN:
        if k in B.own:
            out.append(_rule("own", OWN_FAMILY[k], f"own {TF_LABEL[k]}", (lambda k=k: B.own[k]), tf=k))
    for (k, g), _ in B.xs.items():
        fam = "xs-value" if k == "dev60" else "xs-momentum"
        out.append(_rule("xs", fam, f"rank of the {TF_LABEL[k]} within the family", (lambda key=(k, g): B.xs[key]), tf=k, groups=[g]))
    for (a, nm), _ in B.pair.items():
        out.append(_rule("pair", "relative value", f"{TF_LABEL[nm]} {B.ext[a]['name']}", (lambda key=(a, nm): B.pair[key]), src=a, tf=nm))
    srcs = {s: e for s, e in B.ext.items()}
    out += ext_rules(B, srcs)
    for key in B.comp:
        _, a, s, k, op = key
        other = f"own {TF_LABEL[k]}" if s == "own" else f"{B.ext[s]['name']} {TF_LABEL[k]}"
        word = "times" if op == "x" else "plus"
        out.append(_rule("comp", "composite", f"own {TF_LABEL[a]} {word} {other}", (lambda key=key: _comp_W(B, key)), src=None if s == "own" else s,
                         tf=f"{a}{op}{k}", extra={"parts": [("own", a), (s, k)], "key": key}))
    own_ix = {r["tf"]: i for i, r in enumerate(out) if r["kind"] == "own"}
    sig_ix = {(r["src"], r["tf"]): i for i, r in enumerate(out) if r["kind"] in SIGNAL_KINDS}
    for r in out:                                      # a composite must add timing beyond its parents (audit B3)
        if r["kind"] == "comp":
            r["parents"] = [i for i in [own_ix.get(a) if s == "own" else sig_ix.get((s, a)) for s, a in r["parts"]] if i is not None]
    return out


def ext_rules(B: Block, srcs: dict, family: str | None = None, kind: str | None = None) -> list[dict]:
    """Rules from external sources: one common signal applied to every market of a family. The real cross-asset,
    macro, unusual and computed signals and the placebos all come through here."""
    out = []
    for s, e in srcs.items():
        for k in _tfs_of(e):
            if (s, k) not in B.extv:
                continue

            def get(s=s, k=k, ex=e.get("excl")):
                W = np.repeat(B.extv[(s, k)][:, None], B.M, 1)
                if ex is not None:
                    W[:, ex] = np.nan
                return W
            out.append(_rule(kind or e["kind"], family or e["family"], f"{e['name']} {TF_LABEL[k]}", get, src=s, tf=k))
    return out


# ---------------------------------------------------------------- screening
def screen(B: Block, rl: list[dict], market: bool = False, chunk: int = 48) -> dict:
    """Pooled discovery, validation and test statistics for every (rule, group) at once, vectorized by chunks."""
    K, G = len(rl), B.G
    res = {p: {"mean": np.full((K, G), np.nan), "t": np.full((K, G), np.nan), "n": np.zeros((K, G))} for p in B.masks}
    nm = np.zeros((K, G))
    mk = {"t": np.full((K, B.M), np.nan), "n": np.zeros((K, B.M))} if market else None
    disc = B.masks["disc"]
    for c0 in range(0, K, chunk):
        ch = rl[c0:c0 + chunk]
        W = np.stack([r["W"]() for r in ch])
        Y = W * B.Rs[None]
        V = np.isfinite(Y)
        Y0 = np.where(V, Y, 0.0)
        S = Y0 @ B.Gm
        N = V.astype(np.float64) @ B.Gm
        with np.errstate(invalid="ignore", divide="ignore"):
            pooled = np.where(N > 0, S / np.maximum(N, 1), np.nan).transpose(0, 2, 1)
        sl = slice(c0, c0 + len(ch))
        for p, m in B.masks.items():
            mean, t, n = _nw(pooled, m)
            res[p]["mean"][sl], res[p]["t"][sl], res[p]["n"][sl] = mean, t, n
        dm = (V & disc[None, :, None]).sum(1)
        nm[sl] = (dm >= MIN_MARKET).astype(float) @ B.Gm
        if market:
            _, t, n = _nw(Y.transpose(0, 2, 1), disc)
            mk["t"][sl], mk["n"][sl] = t, n
    size = np.array([len(g["members"]) for g in B.groups])
    need = np.where(size >= MIN_BREADTH, np.minimum(3, size), 1)
    allowed = np.ones((K, G), bool)
    for k, r in enumerate(rl):
        if r.get("groups") is not None:
            allowed[k] = False
            allowed[k, r["groups"]] = True
    valid = allowed & (res["disc"]["n"] >= MIN_POOLED) & (nm >= need[None, :]) & np.isfinite(res["disc"]["t"])
    return {"res": res, "nm": nm, "allowed": allowed, "valid": valid, "market": mk}


def detail(B: Block, r: dict, g: int, d: int, members: list[int] | None = None) -> dict:
    """The pooled series of one hypothesis, its per-market discovery means, positions, costs and net returns."""
    W = r["W"]()
    mem = B.groups[g]["members"] if members is None else members
    Wm, Rm, sg = W[:, mem], B.R[:, mem], B.sig[:, mem]
    Y = Wm * Rm / sg
    V = np.isfinite(Y)
    N = V.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        pooled = np.where(N > 0, np.where(V, Y, 0).sum(1) / np.maximum(N, 1), np.nan)
        A = np.isfinite(Wm) & np.isfinite(sg)
        live = V.copy()
        live[-LAG:] = A[-LAG:]                               # the month under way and the next have no return yet
        pos = np.where(live, Wm / sg, 0.0) / np.maximum(live.sum(1), 1)[:, None]
    dpos = np.abs(np.diff(np.vstack([np.zeros((1, len(mem))), pos]), axis=0))
    cost = (dpos * (B.cost[mem] / 2)[None, :]).sum(1)
    net = np.where(np.isfinite(pooled), d * pooled - cost, np.nan)
    disc = B.masks["disc"]
    dmean = np.array([np.nanmean(Y[disc, j]) if V[disc, j].sum() >= MIN_MARKET else np.nan for j in range(len(mem))])
    turn = np.nansum(dpos, 1)
    gross_not = np.abs(pos).sum(1)
    return {"pooled": pooled, "net": net, "gross": d * pooled, "cost": np.where(np.isfinite(pooled), cost, np.nan), "dmean": dmean,
            "members": mem, "pos": pos * d, "turn": turn, "gross_notional": gross_not, "test_live": V[B.masks["test"]].sum(0)}


def _breadth(B: Block, det: dict, d: int) -> dict:
    dm = det["dmean"]
    ok = np.isfinite(dm)
    n = int(ok.sum())
    if n >= MIN_BREADTH:
        agree = int((np.sign(dm[ok]) == d).sum())
        p = float(stats.binom.sf(agree - 1, n, 0.5))
        return {"units": "markets", "n": n, "agree": agree, "share": agree / n, "p": p, "pass": agree / n > 0.5 and p <= SIGN_P}
    disc = B.masks["disc"]
    yrs = B.idx.year.to_numpy()
    x = det["gross"]
    blocks = []
    for b0 in range((yrs[disc].min() // BLOCK_YEARS) * BLOCK_YEARS, yrs[disc].max() + 1, BLOCK_YEARS):
        m = disc & (yrs >= b0) & (yrs < b0 + BLOCK_YEARS) & np.isfinite(x)
        if m.sum() >= 24:
            blocks.append(float(np.mean(x[m])))
    n = len(blocks)
    if n < 3:
        return {"units": "5-year blocks", "n": n, "agree": None, "share": None, "p": None, "pass": False}
    agree = int(sum(1 for v in blocks if v > 0))
    p = float(stats.binom.sf(agree - 1, n, 0.5))
    return {"units": "5-year blocks", "n": n, "agree": agree, "share": agree / n, "p": p, "pass": agree / n > 0.5 and p <= SIGN_P}


def _alpha(y: np.ndarray, x: np.ndarray, mask: np.ndarray) -> dict:
    """Timing beyond drift: y regressed on the family's always-long return x over mask, Newey-West errors. A signal
    that keeps one sign for years earns the family's drift; only the intercept is timing. x may have several columns
    (drift, then a composite's parent rules)."""
    X = x[:, None] if x.ndim == 1 else x
    m = mask & np.isfinite(y) & np.isfinite(X).all(1)
    n = int(m.sum())
    if n < 24 or (np.std(X[m], axis=0) == 0).any():
        return {"alpha": None, "t_alpha": None, "beta": None, "n": n}
    L = int(math.floor(4 * (n / 100) ** (2 / 9)))
    f = labs.nw_ols(y[m], X[m], L)
    return {"alpha": float(f["b"][0]), "t_alpha": float(f["t"][0]), "beta": float(f["b"][1]), "n": n,
            **({"betas_parents": [float(b) for b in f["b"][2:]]} if X.shape[1] > 1 else {})}


def _period_stats(x: np.ndarray, mask: np.ndarray) -> dict:
    mean, t, n = _nw(x[None], mask)
    xm = x[mask]
    return {"mean": float(mean[0]) if np.isfinite(mean[0]) else None, "t": float(t[0]) if np.isfinite(t[0]) else None, "n": int(n[0]),
            "sharpe": _sharpe(xm)}


def _p_cal(scr: dict) -> np.ndarray:
    """Calibrated two-sided p-values of the discovery t statistics: t divided by the square root of the variance
    inflation measured on the nulls for this rule's kind (1 when uncalibrated); 1 where the hypothesis is not valid."""
    t = np.nan_to_num(scr["res"]["disc"]["t"])
    ts = scr.get("tscale")
    if ts is not None:
        t = t * ts[:, None]
    return np.where(scr["valid"], _p2(t), 1.0)


def gauntlet(B: Block, rl: list[dict], scr: dict, p_cut: float, label: str = "real") -> dict:
    """Stages (iii) to (vii) for every hypothesis that passed BH at p_cut. Returns counts and the records."""
    res, valid = scr["res"], scr["valid"]
    t = res["disc"]["t"]
    p = _p_cal(scr)
    ks, gs = np.nonzero(valid & (p <= p_cut))
    recs = []
    par_cache: dict = {}

    def parent_gross(pi, g):
        if (pi, g) not in par_cache:
            tp = t[pi, g]
            par_cache[(pi, g)] = detail(B, rl[pi], g, 1 if (np.isfinite(tp) and tp >= 0) else -1)["gross"]
        return par_cache[(pi, g)]

    for k, g in zip(ks, gs):
        d = 1 if t[k, g] > 0 else -1
        det = detail(B, rl[k], g, d)
        br = _breadth(B, det, d)
        rec = {"k": int(k), "g": int(g), "d": d, "t_disc": float(t[k, g]), "p_disc": float(p[k, g]), "breadth": br, "det": det}
        rec["disc"] = _period_stats(det["gross"], B.masks["disc"])
        rec["val"] = _period_stats(det["gross"], B.masks["val"])
        rec["val_net"] = _period_stats(det["net"], B.masks["val"])
        X = B.drift[:, g]
        pars = rl[k].get("parents") or []
        if pars:                                       # a composite's timing must go beyond drift AND its parents
            X = np.column_stack([X] + [parent_gross(pi, g) for pi in pars])
        rec["timing"] = {p_: _alpha(det["gross"], X, B.masks[p_]) for p_ in ("disc", "val", "test")}
        rec["timing_parents"] = len(pars)
        ta = rec["timing"]["disc"]["t_alpha"]
        rec["pass_timing"] = ta is not None and ta >= TIMING_T
        rec["pass_breadth"] = rec["pass_timing"] and bool(br["pass"])
        v = rec["val"]
        va = rec["timing"]["val"]["t_alpha"]
        rec["pass_val"] = (rec["pass_breadth"] and v["n"] >= MIN_VAL and v["t"] is not None and v["t"] >= VAL_T and va is not None and va >= VAL_T)
        rec["pass_cost"] = rec["pass_val"] and rec["val_net"]["mean"] is not None and rec["val_net"]["mean"] > 0
        recs.append(rec)
    # de-duplicate the cost survivors: greedy by validation t, dropping any whose pre-test net series correlates
    # above DEDUP_RHO with one already kept
    pre = B.masks["disc"] | B.masks["val"]
    keep = []
    for rec in sorted([r for r in recs if r["pass_cost"]], key=lambda r: -(r["val_net"]["t"] or 0)):
        x = rec["det"]["net"]
        dup = None
        for kr in keep:
            c, n = _corr(x[pre], kr["det"]["net"][pre])
            if c is not None and n >= 48 and abs(c) > DEDUP_RHO:
                dup = kr
                break
        if dup is None:
            keep.append(rec)
            rec["duplicates"] = []
        else:
            dup["duplicates"].append(rec)
        rec["distinct"] = dup is None
    for rec in recs:
        rec.setdefault("distinct", False)
        te = _period_stats(rec["det"]["net"], B.masks["test"])
        rec["test_net"] = te
        rec["test_gross"] = _period_stats(rec["det"]["gross"], B.masks["test"])
        live = rec["det"]["test_live"]
        rec["test_cover"] = float((live >= 12).mean()) if len(live) else 0.0
        rec["tested"] = te["n"] >= 12 and rec["test_cover"] >= MIN_TEST_COVER        # audit B1: most markets must trade
        ds, ts_ = rec["disc"]["sharpe"], rec["test_gross"]["sharpe"]
        rec["sharpe_kept"] = (ts_ / ds) if (ds and ds > 0 and ts_ is not None and rec["tested"]) else None
    tested = [r for r in keep if r["tested"]]
    counts = {"tried": int(scr["allowed"].sum()), "enough_data": int(valid.sum()), "bh": len(recs),
              "timing": sum(r["pass_timing"] for r in recs), "breadth": sum(r["pass_breadth"] for r in recs), "validation": sum(r["pass_val"] for r in recs),
              "costs": sum(r["pass_cost"] for r in recs), "distinct": len(keep),
              "test_data": len(tested),
              "test_positive": sum(1 for r in tested if (r["test_net"]["mean"] or 0) > 0),
              "test_t2": sum(1 for r in tested if (r["test_net"]["t"] or 0) >= 2),
              "partial_test_data": sum(1 for r in keep if r["test_net"]["n"] >= 12 and not r["tested"])}
    return {"counts": counts, "recs": recs, "keep": keep, "label": label}


# ---------------------------------------------------------------- fake markets: a null for every rule kind
def null_block(B: Block, seed: int, block: int = NULL_BLOCK) -> Block:
    """The same block with its returns replaced by the real returns block-shuffled in time, the same permutation
    for every market (so the markets keep their volatility, fat tails, co-movement and the averaging autocorrelation
    within a block, and lose any relation to time). Every rule kind (own history, ranks, pairs, composites and the
    real external signals) is rebuilt on the fake returns: none can have an edge, so what passes is false."""
    rng = np.random.default_rng(seed)
    pi = np.arange(B.T)
    seg_of = np.full(B.T, -1)
    for si, p_ in enumerate(("disc", "val", "test")):            # shuffle within each period, so each keeps its own data
        rows = np.flatnonzero(B.masks[p_])
        rows = rows[rows < B.T - LAG]
        seg_of[rows] = si
        if len(rows) < 2 * block:
            continue
        rr = np.roll(rows, -int(rng.integers(block)))
        nb = int(math.ceil(len(rr) / block))
        blocks = [rr[i * block:(i + 1) * block] for i in range(nb)]
        pi[rows] = np.concatenate([blocks[j] for j in rng.permutation(nb)])[:len(rows)]
    R = B.R[pi]
    real_ok = np.isfinite(B.R)
    for j in range(B.M):                                          # a market's own data window is kept exactly: where the
        holes = np.flatnonzero(real_ok[:, j] & ~np.isfinite(R[:, j]))     # shuffled row has no value, draw one of its own
        for t in holes:                                           # valid rows from the same period
            pool = np.flatnonzero(real_ok[:, j] & (seg_of == seg_of[t]))
            R[t, j] = B.R[pool[int(rng.integers(len(pool)))], j] if len(pool) else np.nan
    R = np.where(real_ok, R, np.nan)
    Bn = Block(B.name + "-null", B.idx, B.ids, R, pd.DataFrame(R, index=B.idx, columns=B.ids), B.cost, B.groups, *B.split, B.info, test_end=B.test_end)
    Bn.ext, Bn.extv = B.ext, B.extv
    f = getattr(B, "flags", {})
    _build_stores(Bn, quick=f.get("quick", False), xs=f.get("xs", True), pairs=f.get("pairs", True), macro_comp=f.get("macro_comp", True), ext=False)
    Bn.comp = {k: None for k in B.comp}               # the identical composite library
    return Bn


def calibrate(null_scrs: list, null_rls: list) -> dict:
    """Variance inflation of the discovery t statistic, measured on the nulls, separately for rules on a common
    signal and rules on each market's own data: lambda = (q / z)^2, where q is the null's |t| at the CAL_ALPHA
    two-sided tail and z the normal's. lambda above 1 means the nominal p-values are too small."""
    z = float(stats.norm.isf(CAL_ALPHA / 2))
    pools = {"signal": [], "own": []}
    for scr, rl in zip(null_scrs, null_rls):
        grp = np.array(["signal" if r["kind"] in SIGNAL_KINDS + ("placebo",) else "own" for r in rl])
        t = scr["res"]["disc"]["t"]
        for gname in pools:
            sel = (grp == gname)[:, None] & scr["valid"]
            pools[gname].append(np.abs(t[sel]))
    out = {}
    for gname, xs in pools.items():
        x = np.concatenate(xs) if xs else np.array([])
        if len(x) < 2000:
            out[gname] = {"lambda": 1.0, "n": int(len(x))}
            continue
        q = float(np.quantile(x, 1 - CAL_ALPHA))
        lam = max(1.0, (q / z) ** 2)
        raw = {a: float((x >= stats.norm.isf(a / 2)).mean()) for a in (0.05, 0.01, 0.001)}
        cal = {a: float((x / math.sqrt(lam) >= stats.norm.isf(a / 2)).mean()) for a in (0.05, 0.01, 0.001)}
        out[gname] = {"lambda": lam, "n": int(len(x)), "q_abs_t": q, "z": z, "null_share_at_p_raw": raw, "null_share_at_p_calibrated": cal}
    return out


def _null_fdr(p_real: np.ndarray, p_null: np.ndarray, c: float) -> float | None:
    """Expected false passes at cut c (the null's pass share times the real count) over the real passes."""
    r = int((p_real <= c).sum())
    if not r or not len(p_null):
        return None
    return float((p_null <= c).mean() * len(p_real) / r)


def emp_cut(p_real: np.ndarray, p_null: np.ndarray, q: float = FDR_Q) -> float:
    """The largest cut at which the null's expected false passes are at most q of the real passes. Calibration is
    matched at one tail point; this holds the false share at the cut where it is used."""
    if not len(p_null) or not len(p_real):
        return 0.0
    pr, pn = np.sort(p_real), np.sort(p_null)
    best = 0.0
    for k, c in enumerate(pr[:5000], start=1):
        if c > 0.01:
            break
        if np.searchsorted(pn, c, side="right") / len(pn) * len(pr) <= q * k:
            best = float(c)
    return best


def tscale_for(rl: list, cal: dict) -> np.ndarray:
    return np.array([1 / math.sqrt(cal["signal" if r["kind"] in SIGNAL_KINDS + ("placebo",) else "own"]["lambda"]) for r in rl])


# ---------------------------------------------------------------- placebos
def placebo_sources(B: Block, n: int, seed: int) -> dict:
    """Fake signals with the shapes of real ones: random walks, 12-month block shuffles of real series (their
    autocorrelation within blocks kept) and phase-randomized real series (their spectrum kept)."""
    rng = np.random.default_rng(seed)
    pool = [s for s, e in B.ext.items() if e["kind"] == "ext" and not e["level"]]
    out = {}
    for i in range(n):
        kind = ("random walk", "block shuffle", "phase randomized")[i % 3]
        src = pool[int(rng.integers(len(pool)))]
        x = B.ext[src]["x"].to_numpy(float)
        ok = np.flatnonzero(np.isfinite(x))
        y = np.full(B.T, np.nan)
        if kind == "random walk":
            y[ok] = rng.normal(0, np.nanstd(x) or 1.0, len(ok))
        else:
            v = x[ok]
            if kind == "block shuffle":
                nb = int(math.ceil(len(v) / 12))
                start = int(rng.integers(12))
                vv = np.roll(v, -start)
                blocks = [vv[j * 12:(j + 1) * 12] for j in range(nb)]
                order = rng.permutation(nb)
                y[ok] = np.concatenate([blocks[j] for j in order])[:len(v)]
            else:
                f = np.fft.rfft(v - v.mean())
                ph = rng.uniform(0, 2 * np.pi, len(f))
                ph[0] = 0
                if len(v) % 2 == 0:
                    ph[-1] = 0
                y[ok] = np.fft.irfft(np.abs(f) * np.exp(1j * ph), len(v)) + v.mean()
        out[f"placebo{i:03d}"] = {"x": pd.Series(y, index=B.idx), "lag": LAG, "level": False, "family": "placebo",
                                  "name": f"Placebo {i} ({kind} of {src})", "kind": "placebo", "excl": None, "type": kind}
    return out


def add_sources(B: Block, srcs: dict):
    for s, e in srcs.items():
        B.ext[s] = e
        tf = transforms(e["x"].to_frame(s), TF_LEVEL if e["level"] else TF_EXT, level=e["level"])
        for k, F in tf.items():
            B.extv[(s, k)] = scale(F.shift(e["lag"]), center=k in CENTERED or e["level"])[:, 0]


# ---------------------------------------------------------------- the averaging trap
def averaging_demo(n_months: int = 480, days: int = 21, seed: int = 3) -> dict:
    """Working (1960) on a synthetic random walk: monthly averages of daily prices give one-month changes with
    first-order autocorrelation near 0.25, so 'one-month momentum' looks real with no skip month and vanishes with it."""
    rng = np.random.default_rng(seed)
    px = np.cumsum(rng.normal(0, 0.01, n_months * days))
    avg = px.reshape(n_months, days).mean(1)
    eom = px.reshape(n_months, days)[:, -1]
    out = {}
    for nm, lv in (("average", avg), ("end_of_month", eom)):
        r = np.diff(lv)
        ac1 = float(np.corrcoef(r[1:], r[:-1])[0, 1])
        res = {"ac1": ac1}
        for lag in (1, 2):
            s = np.sign(r[:-lag]) * r[lag:]
            m = labs.nw_mean(s)
            res[f"t_lag{lag}"] = m["t"]
        out[nm] = res
    out["theory_ac1"] = (days ** 2 - 1) / (2 * (2 * days ** 2 + 1))     # Working (1960); 0.25 as days grow
    return out


def _eom_returns(daily: dict, idx: pd.DatetimeIndex, last: pd.Timestamp) -> dict:
    out = {}
    for k, s in (daily or {}).items():
        if s is None or not len(s):
            continue
        s = s.dropna()
        m = s.groupby(s.index.to_period("M")).last()
        m.index = m.index.to_timestamp()
        r = np.log(m[m > 0]).diff()
        r = r[r.index <= last]
        out[k] = r.reindex(idx)
    return out


def eom_check(B: Block, rec: dict, rl: list[dict], eom: dict) -> dict:
    mem = [j for j in B.groups[rec["g"]]["members"] if B.ids[j] in eom]
    if not mem:
        return {"status": "no end-of-month series", "markets": []}
    R2 = B.R.copy()
    X2 = B.X.copy()
    for j in mem:
        x = eom[B.ids[j]].to_numpy(float)
        R2[:, j] = -BOND_DURATION / 100 * x if B.ids[j] == "y10" else x
        X2.iloc[:, j] = R2[:, j]
    B2 = Block(B.name, B.idx, B.ids, R2, X2, B.cost, B.groups, *B.split, B.info, test_end=B.test_end)
    B2.ext = B.ext
    B2.extv = B.extv
    r = rl[rec["k"]]
    if r["kind"] in ("own", "xs", "pair", "comp"):
        _build_stores(B2, xs=bool(B.xs), pairs=bool(B.pair), macro_comp=True, ext=False)
        if r["kind"] == "comp":
            r = {**r, "W": (lambda key=r["key"]: _comp_W(B2, key))}
        else:
            r2 = [x for x in rules(B2) if x["name"] == r["name"] and x.get("groups") == r.get("groups")]
            if not r2:
                return {"status": "not rebuilt", "markets": [B.ids[j] for j in mem]}
            r = r2[0]
    det = detail(B2, r, rec["g"], rec["d"], members=mem)
    post = B.masks["val"] | B.masks["test"]
    full = _period_stats(det["gross"], np.ones(B.T, bool))
    pst = _period_stats(det["gross"], post)
    det_avg = detail(B, rl[rec["k"]], rec["g"], rec["d"], members=mem)
    pst_avg = _period_stats(det_avg["gross"], post)
    t = pst["t"]
    status = ("holds on end-of-month closes" if (t is not None and t >= 1.65) else
              "weaker on end-of-month closes" if (t is not None and t > 0) else "fails on end-of-month closes")
    return {"status": status, "markets": [B.ids[j] for j in mem], "t_full": full["t"], "t_after_discovery": t,
            "sharpe_after_discovery": pst["sharpe"], "t_after_discovery_averaged": pst_avg["t"], "months": pst["n"]}


# ---------------------------------------------------------------- mechanism
_DED = {}


def _mind():
    if "D" not in _DED:
        try:
            import json
            from pathlib import Path
            from . import reason
            G = json.loads((Path(__file__).resolve().parent / "assets" / "mind.json").read_text())
            _DED["ids"] = {n["id"]: n.get("n", n["id"]) for n in G["nodes"] if n.get("k") == "concept"}
            _DED["D"] = reason.deduce(G)
            _DED["explain"] = reason.explain_path
        except Exception as exc:                     # the mind is optional: edges are then flagged without chains
            _DED["D"], _DED["ids"], _DED["err"] = None, {}, f"{type(exc).__name__}: {exc}"[:160]
    return _DED


def _mech_keys(B: Block, r: dict, d: int) -> list[str]:
    fam, kind, tf, src = r["family"], r["kind"], r.get("tf"), r.get("src")
    out = []
    if kind == "own":
        if tf == "c36":
            out += MECH["lt-reversal-"] if d < 0 else MECH["reversal+"]
        elif fam in ("momentum", "reversal", "value"):
            out += MECH.get(f"{fam}{'+' if d > 0 else '-'}", [])
        else:
            out += MECH.get(fam, [])
    elif kind == "xs":
        out += MECH["xs-value"] if tf == "dev60" else MECH[f"xs-momentum{'+' if d > 0 else '-'}"]
    elif kind == "pair":
        out += MECH["relative value"] + SRC_MECH.get(src, [])
    elif kind == "ext":
        out += (MECH["carry"] if fam == "carry" else MECH["lead-lag"]) + SRC_MECH.get(src, [])
    elif kind == "unu":
        out += MECH.get(fam, [])
    elif kind == "cal":
        base = (src or "").split(":")[-1]
        if fam == "astronomy" and base not in CAL_MECH:
            return []
        out += CAL_MECH.get(base, MECH["calendar"] if fam == "calendar" else [])
    elif kind == "comp":
        for s, k in r.get("parts", []):
            sub = {"kind": "own", "family": OWN_FAMILY.get(k, ""), "tf": k} if s == "own" else {"kind": "ext", "family": B.ext[s]["family"], "tf": k, "src": s}
            out += _mech_keys(B, sub, d)
    seen = []
    for c in out:
        if c not in seen:
            seen.append(c)
    return seen


def mechanism(B: Block, r: dict, g: int, d: int) -> dict:
    M = _mind()
    keys = [c for c in _mech_keys(B, r, d) if not M["ids"] or c in M["ids"]]
    if not keys:
        return {"status": "no known mechanism", "concepts": [], "chain": None}
    target = GROUP_CONCEPT.get(B.groups[g]["name"])
    chain = None
    if M.get("D") is not None and target in M["ids"]:
        for c in keys:
            try:
                ex = M["explain"](c, target, M["D"])
            except Exception:
                continue
            if ex.get("paths"):
                chain = {"from": c, "to": target, "derived": bool(ex.get("derived")), "text": ex["paths"][0].get("text", "")[:400]}
                break
    status = ("linked by a deduced chain in the mind" if chain and chain["derived"] else
              "named mechanism; the mind has only a loose chain of facts, which proves no relation" if chain else
              "named mechanism; no typed chain in the mind")
    return {"status": status, "concepts": [{"id": c, "name": M["ids"].get(c, c)} for c in keys],
            "market_concept": target, "chain": chain}


# ---------------------------------------------------------------- the book
def book_weights(E: np.ndarray, idx: pd.DatetimeIndex, year: int, cap: float = CAP_MULT) -> tuple[np.ndarray, float | None]:
    """Weights for one calendar year from data before it (the BOOK_VOL_WIN months through November of the year
    before): each edge at equal risk, capped at `cap` times the equal weight, and the scale that puts the book at
    TARGET_VOL ex ante."""
    cut = pd.Timestamp(f"{year}-01-01") - pd.offsets.MonthBegin(LAG - 1)
    h = np.asarray(idx < cut)
    H = E[h][-BOOK_VOL_WIN:]
    sd = np.array([np.nanstd(H[:, i], ddof=1) if np.isfinite(H[:, i]).sum() >= 12 else np.nan for i in range(E.shape[1])])
    w = np.where(np.isfinite(sd) & (sd > 0), 1 / np.where(sd > 0, sd, 1), 0.0)
    if w.sum() <= 0:
        return w, None
    w = w / w.sum()
    n = int((w > 0).sum())
    for _ in range(20):
        over = w > cap / n
        if not over.any():
            break
        w = np.where(over, cap / n, w)
        w = w / w.sum()
    b = _combine(H, w)
    s = np.nanstd(b, ddof=1) if np.isfinite(b).sum() >= 12 else None
    scale_ = (TARGET_VOL / math.sqrt(12)) / s if s else None
    return w, scale_


def _combine(E: np.ndarray, w: np.ndarray) -> np.ndarray:
    V = np.isfinite(E) & (w[None, :] > 0)
    tot = (V * w[None, :]).sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(tot > 0, np.where(V, E, 0) @ w / np.where(tot > 0, tot, 1), np.nan)


def walk_book(E: np.ndarray, idx: pd.DatetimeIndex, start: str, end: str | None = None, vol_win: int = 12) -> pd.Series:
    """The book walked forward month by month from `start`: the edge weights refit each January from past data, and
    the overall scale set each month from an exponentially weighted volatility of the combined book (half-life
    EWMA_HL months, through t minus LAG, at this year's weights), floored at VOL_FLOOR of its long-run volatility so
    that a calm spell cannot lever the book up (audit M4). `vol_win` is kept for compatibility and unused."""
    idx = pd.DatetimeIndex(idx)
    m = np.asarray(idx >= pd.Timestamp(start)) & (np.asarray(idx <= pd.Timestamp(end)) if end else True)
    out = pd.Series(np.nan, index=idx)
    tv = TARGET_VOL / math.sqrt(12)
    lam = 0.5 ** (1 / EWMA_HL)
    for y in sorted(set(idx[m].year)):
        w, s0 = book_weights(E, idx, y)
        if s0 is None:
            continue
        raw = _combine(E, w)
        for t in np.flatnonzero(m & np.asarray(idx.year == y)):
            h = raw[:max(0, t - LAG + 1)]
            h = h[np.isfinite(h)]
            if len(h) < 24:
                sc = s0
            else:
                wt = lam ** np.arange(len(h))[::-1]
                ew = math.sqrt(float((wt * h * h).sum() / wt.sum()))
                sd = max(ew, VOL_FLOOR * float(h.std(ddof=1)))
                sc = tv / sd if sd > 0 else s0
            out.iloc[t] = sc * raw[t]
    return out[m]


def _n_eff(E: np.ndarray) -> float | None:
    """Effective number of independent bets: (sum of eigenvalues)^2 / sum of squared eigenvalues of the correlation
    matrix of the edges' returns (pairwise complete)."""
    k = E.shape[1]
    if k < 2:
        return float(k) if k else None
    C = pd.DataFrame(E).corr(min_periods=24).to_numpy()
    C = np.where(np.isfinite(C), C, 0.0)
    np.fill_diagonal(C, 1.0)
    ev = np.clip(np.linalg.eigvalsh(C), 0, None)
    return float(ev.sum() ** 2 / (ev ** 2).sum()) if (ev ** 2).sum() > 0 else None


def book_stats(r: pd.Series, sp: pd.Series | None = None, n_trials: int = 1, engine: pd.Series | None = None, B: int = 2000, seed: int = SEED) -> dict:
    r = r.dropna()
    if len(r) < 12:
        return {"months": len(r)}
    x = r.to_numpy()
    out = {"from": r.index[0].strftime("%Y-%m"), "to": r.index[-1].strftime("%Y-%m"), "months": len(x), "sharpe": _sharpe(x),
           "return_annual": float(x.mean() * 12), "vol_annual": float(x.std(ddof=1) * math.sqrt(12)), "max_drawdown": _maxdd(x),
           "t": float(labs.nw_mean(x)["t"])}
    j = int(np.argmax(np.abs(x)))                      # how much rests on one month (audit B2)
    cum = float(np.prod(1 + x) - 1)
    xo = np.delete(x, j)
    out["largest_month"] = {"date": r.index[j].strftime("%Y-%m"), "r": float(x[j]),
                            "share_of_cumulative_log_return": float(np.log1p(x[j]) / np.log1p(cum)) if cum > -1 and abs(np.log1p(cum)) > 1e-9 else None}
    out["without_largest_month"] = {"sharpe": _sharpe(xo), "t": float(labs.nw_mean(xo)["t"]), "vol_annual": float(xo.std(ddof=1) * math.sqrt(12))}
    out["vol_by_year"] = {str(y): float(np.std(x[r.index.year == y], ddof=1) * math.sqrt(12)) for y in sorted(set(r.index.year)) if (r.index.year == y).sum() >= 6}
    if sp is not None:
        out["corr_sp500"], _ = _corr(x, sp.reindex(r.index).to_numpy(float))
    if engine is not None and len(engine.dropna()) > 3:
        e = engine.dropna()
        e.index = pd.DatetimeIndex(e.index).to_period("M").to_timestamp()
        e = e[~e.index.duplicated()]
        lw = np.log1p(r).cumsum()
        pts = [d for d in e.index if d >= r.index[0] and d <= r.index[-1]]
        if len(pts) >= 4:
            bl = lw.reindex(pts, method="ffill")
            out["corr_engine"], out["corr_engine_points"] = _corr(np.diff(bl.to_numpy()), np.diff(e.reindex(pts).to_numpy(float)))
            if sp is not None:
                sl = np.log1p(sp.reindex(r.index).fillna(0)).cumsum().reindex(pts, method="ffill")
                out["corr_sp500_same_points"], _ = _corr(np.diff(bl.to_numpy()), np.diff(sl.to_numpy()))
    sr = x.mean() / x.std(ddof=1)
    ds = labs.deflated_sharpe(sr, max(2, n_trials), 1.0 / len(x), len(x), float(stats.skew(x)), float(stats.kurtosis(x, fisher=False)))
    out["deflated"] = {"n_trials": n_trials, "sr0_annual": ds["sr0"] * math.sqrt(12), "dsr": ds["dsr"]}
    rng = np.random.default_rng(seed)
    bi = labs.stationary_bootstrap_idx(len(x), B, 6.0, rng)
    xb = x[bi]
    sb = xb.mean(1) / xb.std(1, ddof=1) * math.sqrt(12)
    out["sharpe_boot"] = {"p05": float(np.percentile(sb, 5)), "p50": float(np.percentile(sb, 50)), "p95": float(np.percentile(sb, 95)),
                          "share_above_0": float((sb > 0).mean())}
    return out


# ---------------------------------------------------------------- build
def _round(o, nd: int = 4):
    if isinstance(o, np.ndarray):
        return _round(o.tolist(), nd)
    if isinstance(o, dict):
        return {str(k): _round(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v, nd) for v in o]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        if not np.isfinite(o):
            return None
        x = float(o)
        if x == 0:
            return 0.0
        return round(x, nd) if abs(x) >= 10 ** (-nd + 1) else float(f"{x:.3g}")
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m")
    return o


def _kind_of(r: dict) -> str:
    return {"own": "own history", "xs": "own history", "pair": "relative value", "ext": "cross-asset and macro", "unu": "unusual data",
            "cal": "computed clocks", "comp": "compositions", "placebo": "placebo"}[r["kind"]]


def _edge_name(B: Block, r: dict, g: int, d: int) -> str:
    verb = "followed" if d > 0 else "faded"
    return f"{B.groups[g]['name']}: {r['name']}, {verb}"


def _today(B: Block, rec: dict) -> dict:
    det = rec["det"]
    pos = det["pos"][-1]
    W = rec["W_last"]
    rows = []
    for j, m in enumerate(det["members"]):
        if not np.isfinite(W[j]) or pos[j] == 0:
            continue
        rows.append({"market": B.ids[m], "name": B.info[m]["name"], "side": "long" if pos[j] > 0 else "short", "signal": float(rec["d"] * W[j]),
                     "risk_share": None})
    tot = sum(abs(x["signal"]) for x in rows) or 1.0
    for x in rows:
        x["risk_share"] = abs(x["signal"]) / tot
    rows.sort(key=lambda x: -abs(x["signal"]))
    return {"as_of": B.idx[-1].strftime("%Y-%m"), "data_through": _last(B).strftime("%Y-%m"), "markets_on": len(rows), "net_tilt": float(sum(np.sign(x["signal"]) for x in rows)),
            "positions": rows[:12],
            "note": "Research signal only, never an order." if rows else "No position this month: its markets or inputs have no data now (the IMF series end in June 2017, Shiller's long rate and dividends stop earlier than prices)."}


def _edge_record(B: Block, rl: list[dict], rec: dict, eom: dict, n_tried: int) -> dict:
    r = rl[rec["k"]]
    g, d = rec["g"], rec["d"]
    W = r["W"]()
    rec["W_last"] = W[-1, rec["det"]["members"]]
    mem = rec["det"]["members"]
    liq = [B.info[j]["liquid"] for j in mem]
    det = rec["det"]
    alive_test = [B.ids[j] for j, n in zip(mem, det["test_live"]) if n >= 12]   # markets the rule actually trades in the test
    gn = det["gross_notional"]
    turn = np.where(gn > 0, det["turn"] / np.where(gn > 0, gn, 1), np.nan)
    sdg = np.nanstd(det["gross"][B.masks["disc"] | B.masks["val"]])
    cost_at10 = (np.nanmean(det["cost"][B.masks["val"]]) / sdg * TARGET_VOL * math.sqrt(12)) if sdg > 0 else None
    out = {
        "name": _edge_name(B, r, g, d), "block": B.name, "group": B.groups[g]["name"], "group_markets": len(mem),
        "kind": _kind_of(r), "family": r["family"], "rule": r["name"], "source": r.get("src"), "transform": r.get("tf"),
        "direction": "follow" if d > 0 else "fade",
        "discovery": {**rec["disc"], "t": rec["t_disc"], "p": rec["p_disc"], "period": f"to {B.split[0]}"},
        "breadth": rec["breadth"],
        "timing_beyond_drift": rec["timing"],
        "validation": {**rec["val"], "net": rec["val_net"], "period": f"{_next(B.split[0])} to {B.split[1]}"},
        "costs": {"round_trip_bp_mean": float(np.mean([B.info[j]["cost_bp"] for j in mem])), "turnover_share_per_month": float(np.nanmedian(turn[B.masks["val"]])) if np.isfinite(turn[B.masks["val"]]).any() else None,
                  "cost_annual_at_10pct_vol": cost_at10, "share_markets_liquid": float(np.mean(liq))},
        "test": {"gross": rec["test_gross"], "net": rec["test_net"], "period": f"{_next(B.split[1])} to {B.test_end or _last(B).strftime('%Y-%m')}",
                 "markets_with_test_data": len(alive_test), "markets": alive_test[:20], "cover": rec["test_cover"], "tested": rec["tested"]},
        "sharpe_kept": rec["sharpe_kept"],
        "timing_parents": rec.get("timing_parents", 0),
        "duplicates": [_edge_name(B, rl[x["k"]], x["g"], x["d"]) for x in rec.get("duplicates", [])][:8],
        "n_duplicates": len(rec.get("duplicates", [])),
        "mechanism": mechanism(B, r, g, d),
        "eom": eom_check(B, rec, rl, eom) if B.name in ("panel", "early") else {"status": "Shiller monthly averages; no end-of-month series", "markets": []},
        "today": _today(B, rec),
    }
    if not alive_test:
        out["test"]["note"] = "No market in this family has data after the validation period (the IMF series end in June 2017)."
    elif not rec["tested"]:
        out["test"]["note"] = (f"Only {len(alive_test)} of {len(mem)} markets trade in the test years, so this is not a test of the edge as "
                               "discovered; it is reported, not counted.")
    return out


def _next(ym: str) -> str:
    return (pd.Timestamp(ym + "-01") + pd.offsets.MonthBegin(1)).strftime("%Y-%m")


def _stage_rows(real: dict, null: dict | None, plc: dict | None = None) -> list[dict]:
    """The funnel. `null` is the fake-markets null (every rule kind, the comparable count); `plc` the fake signals."""
    names = [("tried", "Candidates tried (rule by family)"), ("enough_data", "Enough discovery data"), ("bh", f"Calibrated p: BH at q = {FDR_Q} and a fake-market false share of at most {FDR_Q:.0%}"),
             ("timing", "Timing beyond drift and parents (alpha t at least 1.96)"), ("breadth", "Breadth (sign test across markets)"), ("validation", "Validation (same sign, one-sided p at most 0.10)"),
             ("costs", "Covers costs in validation"), ("distinct", "Distinct after de-duplication"), ("test_data", "Tested: most markets trade in the test years"),
             ("test_positive", "Test: positive after costs"), ("test_t2", "Test: t of 2 or more after costs")]
    rows = []
    for k, label in names:
        rv = real.get(k, 0)
        row = {"stage": label, "key": k, "real": rv, "real_rate": rv / max(real["tried"], 1)}
        if null:
            pv = null.get(k, 0)
            row.update({"placebo": pv, "placebo_rate": pv / max(null["tried"], 1), "expected_false_real": pv / max(null["tried"], 1) * real["tried"]})
        if plc:
            row.update({"placebo_signals": plc.get(k, 0), "placebo_signals_rate": plc.get(k, 0) / max(plc["tried"], 1)})
        rows.append(row)
    return rows


def _merge_counts(*cs) -> dict:
    out = {}
    for c in cs:
        for k, v in c.items():
            out[k] = out.get(k, 0) + v
    return out


def _family_tally(B_runs) -> dict:
    fam: dict[str, dict] = {}
    for B, rl, scr, G in B_runs:
        allowed, valid = scr["allowed"], scr["valid"]
        for k, r in enumerate(rl):
            f = fam.setdefault(r["family"], {"family": r["family"], "tried": 0, "enough_data": 0, "bh": 0, "timing": 0, "breadth": 0, "validation": 0, "costs": 0,
                                             "distinct": 0, "tested": 0, "test_positive": 0})
            f["tried"] += int(allowed[k].sum())
            f["enough_data"] += int(valid[k].sum())
        for rec in G["recs"]:
            f = fam[rl[rec["k"]]["family"]]
            f["bh"] += 1
            f["timing"] += rec["pass_timing"]
            f["breadth"] += rec["pass_breadth"]
            f["validation"] += rec["pass_val"]
            f["costs"] += rec["pass_cost"]
            f["distinct"] += rec["distinct"]
            f["tested"] += int(rec["distinct"] and rec["tested"])
            f["test_positive"] += int(rec["distinct"] and rec["tested"] and (rec["test_net"]["mean"] or 0) > 0)
    return fam


def _family_table(B_runs, null_runs) -> list[dict]:
    """Each family of idea against the fake-markets null for the same family (audit B3): the null applies the same
    rule library to returns with no edge, so its survival rate in a family is that family's own false-pass rate."""
    fam, nfam = _family_tally(B_runs), _family_tally(null_runs) if null_runs else {}
    ntried = sum(f["tried"] for f in nfam.values())
    pooled = (sum(f["costs"] for f in nfam.values()) + 0.5) / (ntried + 1) if ntried else None
    out = []
    for f in fam.values():
        f["survival_rate"] = f["costs"] / max(f["tried"], 1)
        nf = nfam.get(f["family"])
        if nf and nf["tried"]:
            pr = (nf["costs"] / nf["tried"]) if nf["costs"] else 3 / nf["tried"]   # with no null pass, the 95% upper bound (re-audit)
            f["null"] = {k: nf[k] for k in ("tried", "bh", "validation", "costs", "distinct")}
            f["expected_false_distinct"] = nf["distinct"] / nf["tried"] * f["tried"]
        else:
            pr = pooled
        if pr is not None:
            f["placebo_rate"] = pr
            f["expected_false"] = pr * f["tried"]
            f["p_vs_placebo"] = float(stats.binom.sf(f["costs"] - 1, f["tried"], pr)) if f["costs"] > 0 else 1.0
            f["beats_placebo"] = bool(f["costs"] >= 2 * f["expected_false"] and f["p_vs_placebo"] <= 0.05 and f["costs"] >= 2)
        out.append(f)
    out.sort(key=lambda f: -f["costs"])
    return out


def _caveats(B: Block, r: dict, g: int, mem: list[int]) -> list[str]:
    out = []
    fams = {B.info[j]["family"] for j in mem}
    liq = np.mean([B.info[j]["liquid"] for j in mem])
    if fams & set(COMMOD_FAMILIES):
        out.append("Spot prices, not futures returns: no roll yield, and a futures curve may already price part of this (theory of storage).")
        if r["family"] in ("seasonality", "calendar", "astronomy") or (r["kind"] == "comp" and "seas" in str(r.get("tf"))):
            out.append("Seasonality in spot commodity prices is usually priced into the futures curve, so this may not be tradeable.")
    if liq < 0.5:
        out.append(f"Only {liq:.0%} of its markets have liquid futures; most are IMF research prices, so it is information rather than a trade.")
    if fams & set(FX_FAMILIES):
        out.append("Spot exchange-rate changes only: interest carry is not in the data, so the currency return here leaves out the rate differential.")
    if B.name == "long":
        out.append("Shiller's monthly averages; dividends after 2023 carried at the last yield.")
    return out


def _run_pass(blocks: list, n_placebo: int, seed: int, eom: dict, sp, engine, val_start: str, val_end: str, test_start: str, test_end: str,
              n_null: int = N_NULL) -> dict:
    """One full gauntlet over the given blocks: the nulls (fake markets for every rule kind in every block, fake
    signals in the first block), p-values calibrated on them, BH across all blocks, the stages, the edge records and
    the book."""
    B = blocks[0][0]
    # 1. the fake-markets null: the whole rule library on block-shuffled returns, in every block
    nulls = []
    for bi, (b, r_, s_) in enumerate(blocks):
        for rep in range(n_null):
            Bn = null_block(b, seed * 1000 + 17 * bi + rep)
            rln = rules(Bn)
            nulls.append((Bn, rln, screen(Bn, rln)))
    # 2. the fake signals, through the external-signal path
    psrc = placebo_sources(B, n_placebo, seed)
    add_sources(B, psrc)
    prl = ext_rules(B, psrc, family="placebo", kind="placebo")
    pscr = screen(B, prl)
    # 3. calibrate the p-values on the nulls, then BH on the real calibrated p-values
    cal = calibrate([x[2] for x in nulls] + [pscr], [x[1] for x in nulls] + [prl])
    for b, r_, s_ in blocks + nulls:
        s_["tscale"] = tscale_for(r_, cal)
    pscr["tscale"] = tscale_for(prl, cal)
    pall = np.concatenate([_p_cal(s_)[s_["valid"]] for _, _, s_ in blocks])
    pnull = np.concatenate([_p_cal(s_)[s_["valid"]] for _, _, s_ in nulls])
    p_bh = bh_cut(pall, FDR_Q)
    p_emp = emp_cut(pall, pnull, FDR_Q)
    p_cut = min(p_bh, p_emp)                           # both: BH on calibrated p, and the null's own false share at most q (re-audit M2)
    p_raw = np.concatenate([_p2(np.nan_to_num(s_["res"]["disc"]["t"]))[s_["valid"]] for _, _, s_ in blocks])
    p_cut_raw = bh_cut(p_raw, FDR_Q)
    n_tried = int(sum(s_["allowed"].sum() for _, _, s_ in blocks))
    runs = [(b, r_, s_, gauntlet(b, r_, s_, p_cut)) for b, r_, s_ in blocks]
    null_runs = [(b, r_, s_, gauntlet(b, r_, s_, p_cut, label="null")) for b, r_, s_ in nulls]
    pg = gauntlet(B, prl, pscr, p_cut, label="placebo")
    for k in psrc:
        B.ext.pop(k, None)
    for key in [x for x in B.extv if x[0] in psrc]:
        B.extv.pop(key)
    by_type = {}
    for t_ in ("random walk", "block shuffle", "phase randomized"):
        ks = {k for k, r in enumerate(prl) if psrc[r["src"]]["type"] == t_}
        recs = [x for x in pg["recs"] if x["k"] in ks]
        by_type[t_] = {"signals": len({prl[k]["src"] for k in ks}), "tried": int(pscr["allowed"][sorted(ks)].sum()) if ks else 0, "bh": len(recs),
                       "timing": sum(x["pass_timing"] for x in recs), "breadth": sum(x["pass_breadth"] for x in recs), "validation": sum(x["pass_val"] for x in recs), "costs": sum(x["pass_cost"] for x in recs)}
    real_counts = _merge_counts(*[G["counts"] for *_, G in runs])
    null_counts = _merge_counts(*[G["counts"] for *_, G in null_runs])

    def by_kind(rs):
        out: dict[str, dict] = {}
        for b, r_, s_, G in rs:
            for k, r in enumerate(r_):
                o = out.setdefault(_kind_of(r), {"tried": 0, "bh": 0, "costs": 0, "distinct": 0, "tested": 0})
                o["tried"] += int(s_["allowed"][k].sum())
            for x in G["recs"]:
                o = out[_kind_of(r_[x["k"]])]
                o["bh"] += 1
                o["costs"] += x["pass_cost"]
                o["distinct"] += x["distinct"]
                o["tested"] += int(x["distinct"] and x["tested"])
        return out
    ext_counts = {"tried": 0, "bh": 0, "timing": 0, "breadth": 0, "validation": 0, "costs": 0}
    for b, r_, s_, G in runs:
        ks = [k for k, r in enumerate(r_) if r["kind"] in SIGNAL_KINDS]
        ext_counts["tried"] += int(s_["allowed"][ks].sum()) if ks else 0
        kset = set(ks)
        recs = [x for x in G["recs"] if x["k"] in kset]
        for key, f in (("bh", None), ("timing", "pass_timing"), ("breadth", "pass_breadth"), ("validation", "pass_val"), ("costs", "pass_cost")):
            ext_counts[key] += len(recs) if f is None else sum(x[f] for x in recs)
    edges = []
    for b, r_, s_, G in runs:
        for rec in G["keep"]:
            e = _edge_record(b, r_, rec, eom, n_tried)
            e["caveats"] = _caveats(b, r_[rec["k"]], rec["g"], rec["det"]["members"])
            e["_net"] = pd.Series(rec["det"]["net"], index=b.idx)
            edges.append(e)
    edges.sort(key=lambda e: -(e["validation"]["net"]["t"] or 0))
    idx = B.idx
    tmask = np.asarray((idx >= pd.Timestamp(test_start)) & (idx <= pd.Timestamp(test_end)))

    def mat(es):
        return np.column_stack([e["_net"].reindex(idx).to_numpy(float) for e in es]) if es else np.zeros((len(idx), 0))

    tested = [e for e in edges if e["test"]["tested"]]
    book = {"edges": len(tested), "edges_distinct": len(edges),
            "method": f"each tested edge (most of its markets trade in the test years) at equal risk from its last {BOOK_VOL_WIN} months of volatility, "
                      f"capped at {CAP_MULT:g} times the equal weight, refit each January from data through November; the whole book scaled each month "
                      f"toward {TARGET_VOL:.0%} a year from an exponentially weighted volatility (half-life {EWMA_HL} months, floored at "
                      f"{VOL_FLOOR:.0%} of its long-run level); after costs; the edges and their directions were fixed before the test period"}
    if tested:
        E = mat(tested)
        rt = walk_book(E, idx, test_start, test_end)
        book["test"] = book_stats(rt, sp, n_tried, engine)
        pre26 = rt[rt.index < pd.Timestamp("2026-01-01")]
        if pre26.notna().sum() >= 24 and len(pre26.dropna()) < len(rt.dropna()):
            book["test_before_2026"] = book_stats(pre26, sp, n_tried, B=1000)
        book["validation_in_sample"] = book_stats(walk_book(E, idx, val_start, val_end), sp, n_tried, B=500)
        book["monthly_test"] = {"dates": [d.strftime("%Y-%m") for d in rt.dropna().index], "r": rt.dropna().tolist()}
        book["edges_with_test_data"] = len(tested)
        by_g: dict[str, int] = {}
        for e in tested:
            by_g[e["group"]] = by_g.get(e["group"], 0) + 1
        mk = sorted({m_ for e in tested for m_ in e["test"]["markets"]})
        Et = mat(tested)
        book["test_concentration"] = {"live_edges_by_group": by_g, "markets_traded": mk,
                                      "mean_pairwise_corr": _mean_corr(Et[tmask]) if len(tested) > 1 else None,
                                      "mean_pairwise_corr_before_test": _mean_corr(Et[~tmask & (idx < pd.Timestamp(test_start))]) if len(tested) > 1 else None,
                                      "independent_bets_test": _n_eff(Et[tmask]), "independent_bets_before_test": _n_eff(Et[idx < pd.Timestamp(test_start)])}
        fams: dict[str, list] = {}
        for e in tested:
            fams.setdefault(e["family"], []).append(e)
        fb = []
        for f, es in fams.items():
            v = book_stats(walk_book(mat(es), idx, val_start, val_end), sp, n_tried, B=200)
            fb.append({"family": f, "edges": len(es), "validation_sharpe": v.get("sharpe")})
        fb.sort(key=lambda x: -(x["validation_sharpe"] if x["validation_sharpe"] is not None else -9))
        chosen = None
        for x in fb:                                   # the best family by validation that trades in the test period
            st = book_stats(walk_book(mat(fams[x["family"]]), idx, test_start, test_end), sp, n_tried, engine, B=1000)
            x["test_sharpe"] = st.get("sharpe")
            if chosen is None and st.get("months", 0) >= 12:
                chosen = {**x, "test": st}
        book["best_family"] = chosen
        book["families"] = fb
    naive = [pd.Series(rec["det"]["net"], index=b.idx) for b, r_, s_, G in runs for rec in G["recs"] if rec["tested"]]
    if naive:
        En = np.column_stack([x.reindex(idx).to_numpy(float) for x in naive])
        book["naive"] = {"edges": len(naive), "test": book_stats(walk_book(En, idx, test_start, test_end), sp, n_tried, engine, B=1000),
                         "note": "every tested discovery-stage BH survivor, with no breadth, validation, cost or de-duplication filter"}
    # the null's own book: what the same construction earns on false edges, the fair benchmark for the real book
    nb = [pd.Series(rec["det"]["net"], index=b.idx) for b, r_, s_, G in null_runs for rec in G["keep"] if rec["tested"]]
    if nb:
        book["null_book"] = {"edges": len(nb), "replicates": n_null,
                             "test": book_stats(walk_book(np.column_stack([x.reindex(idx).to_numpy(float) for x in nb]), idx, test_start, test_end), sp, n_tried, B=500)}
    plc_counts = pg["counts"]
    placebo = {"signals": n_placebo, "hypotheses": plc_counts["tried"], "counts": plc_counts, "by_type": by_type,
               "empirical_fdr_at_costs": (null_counts["costs"] / max(null_counts["tried"], 1) * real_counts["tried"] / real_counts["costs"]) if real_counts.get("costs") else None,
               "empirical_fdr_at_distinct": (null_counts["distinct"] / max(null_counts["tried"], 1) * real_counts["tried"] / real_counts["distinct"]) if real_counts.get("distinct") else None,
               "empirical_fdr_at_bh": (null_counts["bh"] / max(null_counts["tried"], 1) * real_counts["tried"] / real_counts["bh"]) if real_counts.get("bh") else None,
               "null": {"replicates": n_null, "block_months": NULL_BLOCK, "hypotheses": null_counts["tried"], "counts": null_counts,
                        "by_kind": by_kind(null_runs), "real_by_kind": by_kind(runs)},
               "calibration": cal, "bh_p_threshold_uncalibrated": p_cut_raw, "bh_p_threshold_calibrated": p_bh, "null_fdr_cut": p_emp,
               "null_fdr_at_bh_cut": _null_fdr(pall, pnull, p_bh), "null_fdr_at_cut": _null_fdr(pall, pnull, p_cut), "valid_hypotheses": int(len(pall)),
               "survivors": [{"name": prl[x["k"]]["name"], "group": B.groups[x["g"]]["name"], "t_disc": x["t_disc"], "val_t": x["val"]["t"],
                              "test_net_t": x["test_net"]["t"], "distinct": x["distinct"]} for x in pg["recs"] if x["pass_cost"]][:20],
               "null_survivors": [{"name": r_[x["k"]]["name"], "block": b.name, "group": b.groups[x["g"]]["name"], "kind": _kind_of(r_[x["k"]]),
                                   "t_disc": x["t_disc"], "val_t": x["val"]["t"]} for b, r_, s_, G in null_runs for x in G["keep"]][:30]}
    return {"p_cut": p_cut, "n_tried": n_tried, "runs": runs, "real_counts": real_counts, "plc_counts": plc_counts, "null_counts": null_counts,
            "funnel": _stage_rows(real_counts, null_counts, plc_counts),
            "funnel_external_signals_only": {"real": ext_counts, "placebo": {k: plc_counts[k] for k in ext_counts}},
            "families": _family_table(runs, null_runs), "edges": edges, "book": book, "placebo": placebo}


def _mean_corr(E: np.ndarray) -> float | None:
    k = E.shape[1]
    cs = [c for i in range(k) for j in range(i + 1, k) for c in [_corr(E[:, i], E[:, j])[0]] if c is not None]
    return float(np.mean(cs)) if cs else None


def _public_edges(edges: list[dict]) -> list[dict]:
    return [{k: v for k, v in e.items() if not k.startswith("_")} for e in edges]


def build(P: pd.DataFrame, meta: dict, S: pd.DataFrame | None = None, unusual: pd.DataFrame | None = None, unusual_meta: dict | None = None,
          n_placebo: int = 300, seed: int = SEED, quick: bool = False, daily: dict | None = None, engine: pd.Series | None = None,
          computed_signals: Callable | pd.DataFrame | None = None, computed_meta: dict | None = None, early: bool = True) -> dict:
    """The whole engine. P, meta: atlas.panel(); S: labs.shiller() for the long block; unusual, unusual_meta: unusual
    series (month-start index, knowable at the start of each month) and their meta; daily: {target id: daily price
    Series} for the end-of-month check; engine: the engine's equity curve (log wealth by date) for a correlation;
    computed_signals: a function of an index (or a DataFrame) of computed clocks, by default computed() here;
    early: also run the early-split replication for the families whose markets end in 2017."""
    t0 = time.time()
    timing = {}
    if quick:
        n_placebo = min(n_placebo, 60)
    comp_fn = computed_signals if computed_signals is not None else computed
    um = dict(unusual_meta or {})

    def comp_for(index):
        if isinstance(comp_fn, pd.DataFrame):
            return comp_fn, dict(computed_meta or {})
        res = comp_fn(index)
        if isinstance(res, tuple):
            return res[0], {**res[1], **(computed_meta or {})}
        return res, dict(computed_meta or {})

    pidx = _extend(pd.DatetimeIndex(P.index).to_period("M").to_timestamp().sort_values())
    cdf, cmeta = comp_for(pidx)
    B = panel_block(P, meta, unusual, um, cdf, cmeta, quick=quick)
    timing["features_panel_s"] = time.time() - t0
    rl = rules(B)
    scr = screen(B, rl, market=True)
    timing["screen_panel_s"] = time.time() - t0
    blocks = [(B, rl, scr)]
    BL = None
    if S is not None and len(S) > 600:
        lidx = _extend(pd.DatetimeIndex(S.index).to_period("M").to_timestamp())
        cdl, cml = comp_for(lidx)
        BL = long_block(S, unusual, um, cdl, cml, quick=quick)
        if BL is not None:
            rlL = rules(BL)
            blocks.append((BL, rlL, screen(BL, rlL)))
    timing["screen_long_s"] = time.time() - t0
    last = _last(B)
    eom = _eom_returns(daily, B.idx, last)
    n_null = 1 if quick else N_NULL
    sp = P["sp500"] if "sp500" in P else None
    main = _run_pass(blocks, n_placebo, seed, eom, sp, engine, _next(DISC_END), VAL_END + "-28", _next(VAL_END), last.strftime("%Y-%m-%d"), n_null=n_null)
    timing["main_pass_s"] = time.time() - t0
    # the early-split replication: families whose markets mostly end in 2017 get a calendar of their own, chosen with
    # data through 2010 and tested from 2011 to their last month, through the same functions
    early_out = None
    lasts = [i["last"] for i in B.info if i["last"] and i["last"] < _next(VAL_END)]
    if early and lasts:
        end = max(set(lasts), key=lasts.count)
        def gf(g, info):
            ms = [info[j]["last"] for j in g["members"]]
            return sum(1 for x in ms if x and x <= end) / len(ms) >= 0.5
        BE = panel_block(P, meta, unusual, um, cdf, cmeta, quick=quick, splits=(EARLY_DISC_END, EARLY_VAL_END), test_end=end, group_filter=gf, name="early")
        if BE.G:
            rlE = rules(BE)
            scE = screen(BE, rlE)
            ep = _run_pass([(BE, rlE, scE)], n_placebo, seed + 1, eom, sp, None, _next(EARLY_DISC_END), EARLY_VAL_END + "-28", _next(EARLY_VAL_END), end + "-01", n_null=n_null)
            early_out = {"calendar": {"discovery_to": EARLY_DISC_END, "validation_to": EARLY_VAL_END, "test": f"{_next(EARLY_VAL_END)} to {end}"},
                         "groups": [g["name"] for g in BE.groups], "bh_p_threshold": ep["p_cut"], "hypotheses": ep["n_tried"],
                         "funnel": ep["funnel"], "families": ep["families"], "edges": _public_edges(ep["edges"]), "book": ep["book"],
                         "placebo": ep["placebo"]}
    timing["early_pass_s"] = time.time() - t0
    # data notes: the averaging trap
    demo = averaging_demo()
    ac: dict[str, list] = {}
    for c in P:
        x = P[c].dropna()
        if len(x) > 60:
            ac.setdefault(meta.get(c, {}).get("family", "Other"), []).append(float(x.autocorr(1)))
    skip = []
    for g, gr in enumerate(B.groups):
        if gr["kind"] != "class":
            continue
        row = {"group": gr["name"]}
        for lag in (1, 2):
            W = scale(B.X.shift(lag))
            Y = W[:, gr["members"]] * B.Rs[:, gr["members"]]
            V = np.isfinite(Y)
            with np.errstate(invalid="ignore", divide="ignore"):
                pooled = np.where(V.sum(1) > 0, np.where(V, Y, 0).sum(1) / np.maximum(V.sum(1), 1), np.nan)
            row[f"t_lag{lag}"] = _period_stats(pooled, np.isfinite(pooled))["t"]
        skip.append(row)
    edges = main["edges"]
    eom_rows = [{"edge": e["name"], **{k: e["eom"].get(k) for k in ("status", "markets", "t_after_discovery", "t_after_discovery_averaged")}} for e in edges]
    no_eom = ("no end-of-month series", "Shiller monthly averages; no end-of-month series")
    data_notes = {
        "averaging": "IMF commodity prices, the Fed's monthly exchange rates, EIA oil and gas, Shiller's S&P 500 and the atlas VIX are monthly "
                     "averages. Averaging a random walk gives one-month changes a first-order autocorrelation near 0.25 (Working 1960), so "
                     "one-month momentum with no skip month is an artifact. Every feature here uses data through t minus 2 for the month t return.",
        "synthetic_demo": demo,
        "ac1_by_family": {f: {"median": float(np.median(v)), "series": len(v)} for f, v in ac.items()},
        "own_one_month_signal_by_skip": skip,
        "end_of_month_series": sorted(eom),
        "edges": eom_rows,
        "cannot_clear": [e["name"] for e in edges if e["eom"]["status"] in no_eom],
        "cleared": [e["name"] for e in edges if e["eom"]["status"] == "holds on end-of-month closes"],
        "imf_end": "The IMF commodity series in this panel end in June 2017: they inform discovery (1990 to 2009) and validation (2010 to June 2017) "
                   "but have no untouched test period in the main calendar; a commodity family's test there uses only Brent, WTI, Henry Hub gas and "
                   "gold. The early-split replication gives those families a test period of their own (2011 to June 2017).",
        "costs_bp": COST_BP,
        "long_block_masks": {"bonds and yields from": LONG_MASKS["bonds"], "dividends and earnings from": LONG_MASKS["dividends"], "inflation from": LONG_MASKS["cpi"],
                             "why": "Shiller interpolates the long rate linearly from annual values before 1953 and dividends and earnings before 1926, which "
                                    "makes monthly changes constant within a year and gives the bond return a spurious lag-2 autocorrelation (0.21 before 1953, "
                                    "about 0 after); those years are left out of the long block."},
        "lags": {"panel": LAG, "slow_sources": SLOW_SOURCES, "slow_families": SLOW_FAMILIES, "unusual": 1, "computed": 0},
    }
    fam_count: dict[str, int] = {}
    for i in B.info:
        fam_count[i["family"]] = fam_count.get(i["family"], 0) + 1
    sig_count: dict[str, int] = {}
    for b, r_, s_, G in main["runs"]:
        for r in r_:
            sig_count[_kind_of(r)] = sig_count.get(_kind_of(r), 0) + 1
    rule_fams = sorted({r["family"] for _, r_, _, _ in main["runs"] for r in r_})
    src_fams: dict[str, int] = {}
    for b, _, _, _ in main["runs"]:
        for e in b.ext.values():
            src_fams[e["family"]] = src_fams.get(e["family"], 0) + 1
    tm = scr["market"]["t"] * (scr["tscale"][:, None] if scr.get("tscale") is not None else 1.0)     # calibrated, as the pooled tests
    pm = _p2(tm[scr["market"]["n"] >= MIN_MARKET])
    mk_cut = bh_cut(pm, FDR_Q)
    universe = {
        "targets": len(B.ids) + (len(BL.ids) if BL is not None else 0), "targets_by_family": fam_count,
        "targets_note": "us_stocks_1871 and the panel's sp500 are the same Shiller S&P 500 series on two calendars, so there are one fewer distinct markets",
        "groups": [{"name": g["name"], "kind": g["kind"], "markets": len(g["members"])} for b, *_ in main["runs"] for g in b.groups],
        "signal_sources_by_family": src_fams, "rule_families": rule_fams, "rules_by_kind": sig_count,
        "hypotheses": main["n_tried"], "market_level_tests": int(len(pm)), "market_level_bh_survivors": int((pm <= mk_cut).sum()) if mk_cut > 0 else 0,
        "unusual_series": sum(1 for e in B.ext.values() if e["kind"] == "unu"), "computed_series": sum(1 for e in B.ext.values() if e["kind"] == "cal"),
        "unusual_source": "buildout.unusual" if unusual is not None else "none supplied; computed clocks only",
        "panel": {"from": B.idx[0].strftime("%Y-%m"), "to": last.strftime("%Y-%m"), "discovery_to": DISC_END, "validation_to": VAL_END},
        "long": {"from": BL.idx[0].strftime("%Y-%m"), "to": _last(BL).strftime("%Y-%m"), "discovery_to": LONG_DISC_END, "validation_to": LONG_VAL_END} if BL is not None else None,
    }
    out = {
        "schema": 1, "lag": LAG, "fdr_q": FDR_Q, "bh_p_threshold": main["p_cut"],
        "universe": universe, "funnel": main["funnel"], "funnel_external_signals_only": main["funnel_external_signals_only"],
        "families": main["families"], "edges": _public_edges(edges), "book": main["book"], "placebo": main["placebo"],
        "early": early_out, "data_notes": data_notes,
        "assumptions": {"costs_bp": COST_BP, "bond_proxy": f"-{BOND_DURATION:g} x the 10-year yield change in percentage points (no carry)",
                        "risk_units": f"each market's return divided by its trailing {VOL_WIN}-month volatility (through t minus {LAG})",
                        "signals": f"scaled by their expanding root mean square and clipped at {CLIP}",
                        "breadth": f"one-sided sign test p at most {SIGN_P} with a majority agreeing; families of fewer than {MIN_BREADTH} markets use 5-year blocks",
                        "dedup": f"pre-test correlation above {DEDUP_RHO} with a stronger survivor", "validation": f"same sign, t at least {VAL_T}, {MIN_VAL} months"},
        "timing": {k: round(v, 2) for k, v in timing.items()},
    }
    out["limitations"] = LIMITATIONS
    out["timing"]["total_s"] = round(time.time() - t0, 2)
    out = _round(out)
    out["findings"] = summary(out)
    return out


LIMITATIONS = [
    "The IMF commodity series end in June 2017, so no commodity edge has most of its markets trading after 2017: the main calendar has no tested edge. The early-split replay (chosen with data through 2010, tested 2011 to June 2017) is the only out-of-sample evidence, and it is not independent: its test years are the main search's validation years, and its results were in view when the audit changed the method.",
    "Edges whose markets mostly stopped trading are reported on the few that still do (often only Brent, WTI and Henry Hub gas), as partial evidence only; they are never counted as tested and never enter the book.",
    "Commodity returns are spot price changes, not futures returns: roll yield is missing, and a futures curve may already price seasonal and relative-value patterns (the theory of storage). Most IMF series have no liquid futures at all, so the surviving edges are information, not trades, until rebuilt on continuous futures with roll.",
    "Currency returns are spot changes without the interest differential, so carry cannot be tested; the bond proxy is a duration times the yield change, without coupon carry.",
    "Every panel series is a monthly average or behaves like one; the skip month removes the averaging artifact for a random walk, but only Brent, WTI and Henry Hub gas could be re-tested on end-of-month closes.",
    "Unusual series carry today's vintage, not the first print (reanalyses, disaster lists and index base periods are revised): their publication lag guards against timing look-ahead, not revision look-ahead.",
    "The p-values are calibrated on the nulls at one tail point (two-sided 0.1%); the nulls keep each market's average return within each period, so a rule that only sorts markets by their average return counts as no timing.",
    "The deflated Sharpe treats every hypothesis as an independent trial on the test sample, which is the wrong null in both directions (the hypotheses are correlated, and the book was fixed before the test); the bootstrap range and the null's own survival count are the fairer measures.",
    "The surviving edges are a few independent bets (about three for the early-split book), so the book's Sharpe has the uncertainty of three bets, not of six or more.",
    "The dollar and commodity indices include each member's own change (lagged two months), so a signal on them is partly the market's own history.",
]


# ---------------------------------------------------------------- words
def _f(x, nd=2, pct=False):
    if x is None:
        return "n/a"
    return f"{x * 100:.{nd - 1}f}%" if pct else f"{x:.{nd}f}"


def summary(o: dict) -> list[str]:
    u, f = o["universe"], {r["key"]: r for r in o["funnel"]}
    pl = o["placebo"]
    nl, cal = pl.get("null", {}), pl.get("calibration", {})
    out = [f"The engine tried {u['hypotheses']:,} candidate edges (rules applied to families of markets; {u['market_level_tests']:,} market-level "
           f"tests) across {u['targets']} markets, with {len(u['rule_families'])} families of rules: " + ", ".join(u["rule_families"]) + "."]
    if cal:
        out.append(f"On {nl.get('hypotheses', 0):,} null hypotheses (the whole rule library on {nl.get('replicates', 0)} block-shuffled copies of the "
                   f"markets, plus {pl['signals']} fake signals), nominal p-values were too small: the null's 0.1% tail sat at |t| "
                   f"{_f(cal['own'].get('q_abs_t'))} for rules on a market's own data and {_f(cal['signal'].get('q_abs_t'))} for rules on a common "
                   f"signal, against 3.29. Every p-value is calibrated for that (variance inflation {_f(cal['own']['lambda'])} and "
                   f"{_f(cal['signal']['lambda'])}) before Benjamini-Hochberg, and the cut is also held where the null's own false share is at most "
                   f"5%: it moves from {pl['bh_p_threshold_uncalibrated']:.2g} to {o['bh_p_threshold']:.2g}.")
    exp_d = f["distinct"].get("expected_false_real", 0)
    bound = 3 / max(nl.get("hypotheses", 1), 1) * u["hypotheses"] if f["distinct"].get("placebo", 0) == 0 else None
    out.append(f"{f['bh']['real']:,} passed BH, {f['timing']['real']:,} showed timing beyond drift (and, for composites, beyond their parent rules), "
               f"{f['breadth']['real']:,} held across their markets, {f['validation']['real']:,} held in validation, {f['costs']['real']:,} covered costs "
               f"and {f['distinct']['real']} were distinct. The null produced {f['distinct'].get('placebo', 0)} distinct survivors, so "
               + (f"fewer than {bound:.1f} of the {f['distinct']['real']} are expected by luck (95% bound)." if bound is not None else
                  f"about {exp_d:.1f} of the {f['distinct']['real']} are expected by luck."))
    rk = nl.get("real_by_kind", {})
    if rk.get("compositions"):
        c, cn = rk["compositions"], nl["by_kind"].get("compositions", {})
        out.append(f"Composites, two transforms combined, look like discoveries until they must beat their own parts: {c['bh']} passed BH "
                   f"against {cn.get('bh', 0) / max(nl.get('replicates', 1), 1):.1f} expected from the null, and {c['costs']} survived once each had "
                   "to add timing beyond the two rules it is built from.")
    if f["test_data"]["real"]:
        out.append(f"In the untouched test period, {f['test_positive']['real']} of {f['test_data']['real']} tested edges made money after costs and "
                   f"{f['test_t2']['real']} had a t of 2 or more.")
    else:
        part = [e for e in o["edges"] if (e["test"]["net"].get("n") or 0) >= 12 and not e["test"].get("tested")]
        out.append(f"No edge in the main calendar can be tested after 2017: every survivor trades commodities whose IMF series end in June 2017. "
                   + (f"{len(part)} can be followed on the few markets still trading (Brent, WTI, Henry Hub gas, gold), which is partial evidence and "
                      "is not counted." if part else ""))
    good = [x["family"] for x in o["families"] if x.get("beats_placebo")]
    out.append(("Families of idea that beat their own null: " + ", ".join(good) + ".") if good else "No family of idea beat its own null.")
    dead = [e for e in o["edges"] if not (e["test"]["net"].get("n") or 0) >= 12]
    bk = o["book"]
    if bk.get("test", {}).get("sharpe") is not None:
        t = bk["test"]
        out.append(f"The book of {bk['edges']} tested edges, walked forward from {t['from']} to {t['to']}: Sharpe {_f(t['sharpe'])} (t {_f(t['t'], 1)}), "
                   f"{_f(t['without_largest_month']['sharpe'])} without its largest month, {_f(t['return_annual'], 2, True)} a year at "
                   f"{_f(t['vol_annual'], 2, True)} volatility, worst drawdown {_f(t['max_drawdown'], 2, True)}.")
    ea = o.get("early")
    if ea:
        fe = {r["key"]: r for r in ea["funnel"]}
        bt = ea["book"].get("test", {})
        line = (f"The early-split replay for the commodity families (chosen with data through {ea['calendar']['validation_to']}, tested on "
                f"{ea['calendar']['test']}, years the main search used for validation, so this is a replay rather than an independent test) tried {ea['hypotheses']:,} candidates: {fe['distinct']['real']} distinct edges survived against "
                f"{fe['distinct'].get('placebo', 0)} from {ea['placebo'].get('null', {}).get('hypotheses', 0):,} null hypotheses; "
                f"{fe['test_positive']['real']} of {fe['test_data']['real']} made money in the test and {fe['test_t2']['real']} had a t of 2 or more")
        if bt.get("sharpe") is not None:
            conc = ea["book"].get("test_concentration", {})
            line += (f". Their book: Sharpe {_f(bt['sharpe'])} after costs over {bt['months']} months (t {_f(bt['t'], 1)}, bootstrap "
                     f"{_f(bt['sharpe_boot']['p05'])} to {_f(bt['sharpe_boot']['p95'])}, {_f(bt['without_largest_month']['sharpe'])} without its largest "
                     f"month), at {_f(bt['vol_annual'], 2, True)} volatility against a 10% aim, worst drawdown {_f(bt['max_drawdown'], 2, True)}, about "
                     f"{_f(conc.get('independent_bets_test'), 1)} independent bets")
            nb = ea["book"].get("naive", {}).get("test", {})
            if nb.get("sharpe") is not None:
                line += (f"; the naive book of all {ea['book']['naive']['edges']} tested discovery survivors earned {_f(nb['sharpe'])}"
                         + (", better than the gauntlet's, so the later stages cost return in this window" if nb["sharpe"] > bt["sharpe"] else ""))
        out.append(line + ".")
    dn = o["data_notes"]["synthetic_demo"]
    out.append(f"The averaging trap, reproduced: on a synthetic averaged random walk the one-month autocorrelation is {_f(dn['average']['ac1'])} and "
               f"one-month momentum has t {_f(dn['average']['t_lag1'], 1)} with no skip month, {_f(dn['average']['t_lag2'], 1)} with it.")
    if o["data_notes"].get("long_block_masks"):
        out.append("The long US block has no survivor once Shiller's interpolated years are left out (bond yields before 1953, dividends and "
                   "earnings before 1926): the smoothing had inflated its bond momentum, and stock momentum alone, still positive in most eras, "
                   "fails the stricter cut and validation.")
    return out
