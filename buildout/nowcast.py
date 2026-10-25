"""Nowcasting the AI buildout (v0.27): facts published early against the book's quarterly reports.

The edge lab (v0.26) showed that free monthly prices on a few dozen markets cannot support an edge: too few independent
bets, data everyone has, and returns nobody can trade. This module goes where edges are usually found instead: facts
that are published before the reports they predict, aimed at the companies in the book, each fact used only after the
date it became knowable.

  inputs        daily prices (split-adjusted, dividends separate) and quarterly SEC XBRL financials for the book and
                the AI supply chain, from a public GitHub mirror refreshed nightly; TSMC's monthly revenue from TSMC's
                investor site (buildout/assets/tsmc_monthly.json, every figure checked against the year-over-year
                change TSMC prints), knowable from the 11th of the next month; earnings release dates
                (buildout/assets/release_dates.json): SEC Form 8-K Item 2.02 filing dates, and for Tesla, for releases
                after November 2025 and for Broadcom and Marvell under their former registrants, dates read from the
                companies' own releases, each with its source
  events        each company quarter's first earnings release 7 to 100 days after the quarter's end; the report day is
                the first trading day the market could react (the next trading day for a release after the close, the
                same day for one before the open); the information cutoff is the close two trading days before it.
                Quarters with no release on record are left out, never guessed from trading volume
  outcomes      revenue acceleration (this quarter's year-over-year growth minus last quarter's, in logs): what a
                forecaster who expects growth to persist gets wrong; the three-day abnormal return around the report
                against the sector fund (SOXX for chips, QQQ otherwise); and the 60-day drift after it
  lead signals  TSMC's revenue growth over the company's own quarter, as an acceleration; the four hyperscalers'
                combined capital spending growth, as an acceleration, from the reports already out; and the
                acceleration of peers that reported earlier in the same season (information transfer within an
                industry, Thomas and Zhang 2008): peers that reported on the same quarter before the cutoff; and, as the
                first definition tried, any peer report in the 80 days before the cutoff (both are counted as tried)
  nowcast       revenue acceleration forecast walked forward by group (chips, cloud, other) from those signals, scored
                against the persistence forecast out of sample (Diebold-Mariano, Newey-West errors and errors clustered
                by quarter), with each company left out in turn to show what carries the gain
  priced?       two designs. Across companies within a season: signal and return demeaned within each season, the
                signal shuffled within seasons, under three ways of drawing a season (the quarter reported on, the
                calendar quarter of the report, its month), and the largest p-value kept: a joint test, so a result
                must hold however a season is drawn (chip makers report in a fixed order, and one draw alone
                made a strong artifact).
                Across quarters: each quarter's average signal against its average report-day return, whole quarters
                shuffled (the question for TSMC and capital spending, which mostly move all companies together). And
                whether the actual surprise and the report-day return predict the drift after (post-announcement drift,
                Bernard and Thomas 1989; on revenue, Jegadeesh and Livnat 2006)
  gauntlet      Benjamini-Hochberg across every hypothesis tried, the same sign in both halves of the record (2017 to
                2021, 2022 on), costs, and random signals (with the same split of variance between and within quarters
                as the real ones) through the same tests for the false-pass rate
  today         each holding's next report: the date expected, the signals published by now, the nowcast with its
                out-of-sample error (persistence where the model has not beaten it), and any drift position the rule
                would hold. Research only, never an order.
"""
from __future__ import annotations

import io
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

MIRROR = "https://raw.githubusercontent.com/yennanliu/finance_data/main/data/{}/{}.csv"
MIRROR_REPO = "https://github.com/yennanliu/finance_data"
ASSETS = Path(__file__).resolve().parent / "assets"
TSMC_ASSET = ASSETS / "tsmc_monthly.json"
RELEASE_ASSET = ASSETS / "release_dates.json"

TARGETS = {"nvda": ("NVIDIA", "chips"), "avgo": ("Broadcom", "chips"), "amd": ("AMD", "chips"), "mu": ("Micron", "chips"),
           "mrvl": ("Marvell", "chips"), "intc": ("Intel", "chips"), "wdc": ("Western Digital", "chips"),
           "msft": ("Microsoft", "cloud"), "amzn": ("Amazon", "cloud"), "goog": ("Alphabet", "cloud"), "meta": ("Meta", "cloud"),
           "orcl": ("Oracle", "cloud"), "tsla": ("Tesla", "other"), "pltr": ("Palantir", "other"), "vst": ("Vistra", "other")}
BENCH = {"chips": "soxx", "cloud": "qqq", "other": "qqq"}
HYPERSCALERS = ("msft", "amzn", "goog", "meta")
EXTRA = ("soxx", "qqq", "vti", "tsm", "2330.tw", "spcx")
BOOK = ("msft", "amzn", "goog", "meta", "nvda", "avgo", "tsla", "spcx", "orcl")
GROUPS = ("chips", "cloud", "all")

MIN_GAP, MAX_GAP = 7, 75          # days after the quarter's end in which its first release is looked for
STRATA = ("season", "quarter", "month")   # within-season tests must hold under each: the quarter reported on, the calendar quarter of the report, its month
ACC_CAP = 0.5                     # accelerations capped at +/- 50 log points in training and in the peer signal
CUTOFF = 2                        # trading days before the report day whose close is the information cutoff
DRIFT = 60                        # trading days of post-report drift
RUNUP = 10                        # trading days of pre-report run-up
MIN_TRAIN = 20
N_PERM = 2000
N_FAKE = 240
FDR_Q = 0.05
SPLIT = "2022-01-01"              # the two halves of the record
COST_BP = 10                      # round trip for a long-short pair in these names
TSMC_AVAIL_DAY = 11
SEED = 27

# Quarters whose revenue acceleration mixes accounting bases in the mirror's data, left out of every target and signal
DATA_BREAKS = [("wdc", "2024-06-01", "2026-04-30", "the SanDisk separation: the mirror mixes revenue recast after the spin-off with revenue as first reported"),
               ("msft", "2016-09-01", "2017-09-30", "the 2018 revenue standard: fiscal 2017 is restated, fiscal 2016 is not")]

# Release dates checked independently (company releases and SEC filings), none used to set any rule: after the close
VERIFIED_RELEASES = [("nvda", "2023-08-23"), ("nvda", "2024-05-22"), ("nvda", "2024-08-28"), ("nvda", "2025-02-26"), ("nvda", "2025-05-28"),
                     ("nvda", "2025-08-27"), ("nvda", "2025-11-19"), ("msft", "2024-07-30"), ("meta", "2024-02-01"), ("amzn", "2024-08-01"),
                     ("goog", "2024-10-29"), ("avgo", "2024-12-12"), ("orcl", "2025-09-09"), ("msft", "2019-07-18"), ("msft", "2023-07-25"),
                     ("intc", "2018-04-26"), ("intc", "2025-01-30"), ("mu", "2020-03-25"), ("mu", "2025-09-23"), ("avgo", "2022-05-26"),
                     ("avgo", "2021-06-03"), ("intc", "2025-10-23"), ("mu", "2025-03-20"), ("orcl", "2021-06-15"), ("amzn", "2017-07-27"),
                     ("wdc", "2023-01-31")]

PRE_SIGNALS = {"d_tsmc": "TSMC revenue growth over the company's quarter, change from last quarter",
               "d_capex": "Hyperscaler capital spending growth, change from last quarter",
               "peer": "Revenue acceleration of peers that reported earlier this season",
               "nowcast": "The walked-forward nowcast of revenue acceleration (all three signals)"}
POST_SIGNALS = {"acc": "The reported revenue acceleration (the surprise against persistence)",
                "car3": "The report-day abnormal return"}
TS_SIGNALS = ("d_tsmc", "d_capex")
WINCOL = {"event": "car3", "runup": "runup", "drift": "drift"}
WINDOWS = {"event": "three days around the report", "runup": f"{RUNUP} days before the cutoff (diagnostic: priced as it became known?)",
           "drift": f"{DRIFT} days after the report"}


# ---------------------------------------------------------------- data
def _fetch(folder: str, t: str) -> pd.DataFrame:
    from .data import http
    return pd.read_csv(io.StringIO(http.get(MIRROR.format(folder, t), timeout=45).decode()))


def download(max_age: float = 12 * 3600, use_cache: bool = True) -> dict:
    """Prices and financials from the mirror: {"prices": {t: DataFrame}, "fund": {t: DataFrame}, "failed": {...}, "asof"}.
    One failing file only adds a failed entry."""
    def live() -> dict:
        out = {"prices": {}, "fund": {}, "failed": {}, "asof": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")}
        for t in list(TARGETS) + list(EXTRA):
            for kind, folder in (("prices", "prices"), ("fund", "fundamentals")):
                if kind == "fund" and t not in TARGETS:
                    continue
                try:
                    out[kind][t] = _fetch(folder, t)
                except Exception as exc:          # one file down never stops the rest
                    out["failed"][f"{kind}:{t}"] = f"{type(exc).__name__}: {exc}"[:160]
        return out
    if not use_cache:
        return live()
    from .core import cache
    try:
        dl, _ = cache.fetch("nowcast.download", live, max_age, ok=lambda d: len(d["prices"]) >= 0.8 * (len(TARGETS) + len(EXTRA)))
    except Exception:
        dl = live()
    return dl


def tsmc_monthly() -> pd.DataFrame:
    """TSMC's monthly revenue (NT$ millions) by month, with the date each figure is knowable."""
    d = json.loads(TSMC_ASSET.read_text())
    df = pd.DataFrame(d["rows"])
    df["month"] = pd.to_datetime(df["month"] + "-01")
    df["avail"] = df["month"] + pd.offsets.MonthBegin(1) + pd.Timedelta(days=TSMC_AVAIL_DAY - 1)
    return df.set_index("month").sort_index()


def release_dates() -> tuple[pd.DataFrame, dict]:
    """Every earnings release on record: ticker, date, source; and each company's usual timing (after the close or
    before the open)."""
    d = json.loads(RELEASE_ASSET.read_text())
    R = pd.DataFrame(d["rows"])
    R["release_date"] = pd.to_datetime(R["release_date"])
    R = R.sort_values(["ticker", "release_date"]).drop_duplicates(["ticker", "release_date"])
    return R, d.get("timing_by_ticker", {})


def _prices(df: pd.DataFrame) -> pd.DataFrame:
    p = df.copy()
    p["date"] = pd.to_datetime(p["date"])
    p = p.set_index("date").sort_index()
    p = p[~p.index.duplicated(keep="last")]
    p["ret"] = (p["close"] + p["div"].fillna(0.0)) / p["close"].shift(1) - 1   # total return; the mirror's closes are split-adjusted
    return p


def _fund(df: pd.DataFrame) -> pd.DataFrame:
    """One row per quarter; where the mirror has several filings for a quarter, the earliest (usually the first print)."""
    f = df.copy()
    f["period_end"] = pd.to_datetime(f["period_end"])
    f["filed"] = pd.to_datetime(f["filed"], errors="coerce")
    f = f.sort_values(["period_end", "filed"]).drop_duplicates("period_end", keep="first").set_index("period_end")
    return f[f["revenue"].notna() & (f["revenue"] > 0)]


def _match(idx: pd.DatetimeIndex, d: pd.Timestamp, lo: int, hi: int) -> pd.Timestamp | None:
    c = [x for x in idx if lo <= (d - x).days <= hi]
    return c[-1] if c else None


def _broken(t: str, pe: pd.Timestamp) -> str | None:
    for tk, a, b, why in DATA_BREAKS:
        if tk == t and pd.Timestamp(a) <= pe <= pd.Timestamp(b):
            return why
    return None


# ---------------------------------------------------------------- events
def reaction_day(idx: pd.DatetimeIndex, release: pd.Timestamp, timing: str) -> int | None:
    """Index of the first trading day that can react: the release day itself for a release before the open (if it is
    a trading day), otherwise the next trading day."""
    if timing == "before_open":
        k = idx.searchsorted(release, side="left")
    else:
        k = idx.searchsorted(release, side="right")
    return int(k) if k < len(idx) else None


def events(dl: dict) -> tuple[pd.DataFrame, dict, dict]:
    """One row per company quarter with a release on record: revenue growth and acceleration, the report-day, run-up
    and drift abnormal returns, and the trading-day positions."""
    P = {t: _prices(df) for t, df in dl["prices"].items()}
    R, timing = release_dates()
    rows, undated = [], []
    for t, (name, grp) in TARGETS.items():
        if t not in dl["fund"] or t not in P:
            continue
        f, px = _fund(dl["fund"][t]), P[t]
        bench = P.get(BENCH[grp])
        if bench is None:
            continue
        ex = (px["ret"] - bench["ret"].reindex(px.index)).fillna(0.0)
        idx = px.index
        rel = R[R["ticker"] == t]["release_date"].sort_values()
        tm = (timing.get(t) or {}).get("timing", "after_close")
        used = pd.Timestamp("1900-01-01")
        for pe, r in f.iterrows():
            if pe < idx[0] + pd.Timedelta(days=60):
                continue
            cand = rel[(rel >= pe + pd.Timedelta(days=MIN_GAP)) & (rel <= pe + pd.Timedelta(days=MAX_GAP)) & (rel > used)]
            if cand.empty:
                undated.append({"ticker": t, "period_end": pe.strftime("%Y-%m-%d")})
                continue
            release = cand.iloc[0]
            used = release
            k0 = reaction_day(idx, release, tm)
            if k0 is None or k0 < CUTOFF + RUNUP + 1:
                continue
            prev_y = _match(f.index, pe, 340, 390)
            prev_q = _match(f.index, pe, 70, 110)
            yoy = math.log(r["revenue"] / f.loc[prev_y, "revenue"]) if prev_y is not None and f.loc[prev_y, "revenue"] > 0 else np.nan
            prev_yoy = np.nan
            if prev_q is not None:
                pyy = _match(f.index, prev_q, 340, 390)
                if pyy is not None and f.loc[pyy, "revenue"] > 0:
                    prev_yoy = math.log(f.loc[prev_q, "revenue"] / f.loc[pyy, "revenue"])
            brk = _broken(t, pe)
            acc = yoy - prev_yoy if (np.isfinite(yoy) and np.isfinite(prev_yoy) and brk is None) else np.nan
            capex = r.get("capex", np.nan)
            capex_y = f.loc[prev_y, "capex"] if prev_y is not None and "capex" in f else np.nan

            def car(a, b):
                if a < 1 or b >= len(idx):
                    return np.nan
                return float(ex.iloc[a:b + 1].sum())
            rows.append({"ticker": t, "name": name, "group": grp, "period_end": pe, "release": release, "timing": tm, "d0": idx[k0], "k0": k0,
                         "cutoff": idx[k0 - CUTOFF], "revenue": float(r["revenue"]), "yoy": yoy if brk is None else np.nan, "prev_yoy": prev_yoy,
                         "acc": acc, "data_break": brk,
                         "capex": float(capex) if pd.notna(capex) else np.nan, "capex_prev_y": float(capex_y) if pd.notna(capex_y) else np.nan,
                         "car3": car(k0 - 1, k0 + 1), "runup": car(k0 - CUTOFF - RUNUP + 1, k0 - CUTOFF),
                         "drift": car(k0 + 2, k0 + 1 + DRIFT) if k0 + 1 + DRIFT < len(idx) else np.nan,
                         "drift_partial": k0 + 1 + DRIFT >= len(idx)})
    E = pd.DataFrame(rows).sort_values("d0").reset_index(drop=True)
    E["quarter"] = E["d0"].dt.to_period("Q").astype(str)                                       # calendar quarter of the report
    E["season"] = (E["period_end"] - pd.Timedelta(days=15)).dt.to_period("Q").astype(str)     # the fiscal season: the quarter reported on
    E["month"] = E["d0"].dt.to_period("M").astype(str)                                         # the month of the report
    return E, P, {"undated": undated, "releases_on_record": int(len(R)), "timing": timing}


# ---------------------------------------------------------------- signals, each as of the event's cutoff
def _tsmc_growth(T: pd.DataFrame, end_month: pd.Timestamp, cutoff: pd.Timestamp) -> tuple[float, bool]:
    """Log growth of TSMC's revenue over the three months ending end_month against a year earlier, if published by
    the cutoff; otherwise over the latest three published months (flagged as not aligned)."""
    pub = T[T["avail"] <= cutoff]
    if pub.empty:
        return np.nan, False
    aligned = end_month in pub.index
    m = end_month if aligned else pub.index[-1]
    cur = [m - pd.DateOffset(months=k) for k in range(3)]
    old = [x - pd.DateOffset(years=1) for x in cur]
    if not all(x in T.index for x in cur + old):
        return np.nan, aligned
    return math.log(T.loc[cur, "revenue_ntd_m"].sum() / T.loc[old, "revenue_ntd_m"].sum()), aligned


def _capex_growth(E: pd.DataFrame, cutoff: pd.Timestamp, lag_q: int = 0) -> float:
    """The four hyperscalers' combined capital spending growth (log, year over year) for the latest calendar quarter
    all four had reported by the cutoff (lag_q quarters earlier when asked)."""
    H = E[E["ticker"].isin(HYPERSCALERS) & (E["d0"] <= cutoff)].copy()
    if H.empty:
        return np.nan
    H["cq"] = (H["period_end"] - pd.Timedelta(days=20)).dt.to_period("Q")
    full = H.groupby("cq")["ticker"].nunique()
    full = full[full == len(HYPERSCALERS)].index.sort_values()
    if len(full) <= lag_q:
        return np.nan
    q = full[-1 - lag_q]
    g = H[H["cq"] == q]
    a, b = g["capex"].sum(), g["capex_prev_y"].sum()
    if not (np.isfinite(a) and np.isfinite(b)) or a <= 0 or b <= 0 or g["capex_prev_y"].isna().any():
        return np.nan
    return math.log(a / b)


def _peer(E: pd.DataFrame, grp: str, t: str, c: pd.Timestamp, season: str) -> tuple[float, list]:
    """Mean revenue acceleration (capped) of the same group's companies that reported on the same season (the same
    calendar quarter of results) before the cutoff."""
    P = E[(E["group"] == grp) & (E["ticker"] != t) & (E["d0"] <= c) & (E["season"] == season)]
    a = P["acc"].dropna().clip(-ACC_CAP, ACC_CAP)
    return (float(a.mean()) if len(a) else np.nan), sorted(P.loc[P["acc"].notna(), "ticker"].unique().tolist())


def add_signals(E: pd.DataFrame) -> pd.DataFrame:
    T = tsmc_monthly()
    E = E.copy()
    ts, ts_al, dcap, peer, peer80 = [], [], [], [], []
    for _, e in E.iterrows():
        c = e["cutoff"]
        endm = (e["period_end"] - pd.Timedelta(days=14)).to_period("M").to_timestamp()
        g1, al = _tsmc_growth(T, endm, c)
        g0, _ = _tsmc_growth(T, endm - pd.DateOffset(months=3), c)
        ts.append(g1 - g0 if (al and np.isfinite(g1) and np.isfinite(g0)) else np.nan)   # only when the quarter's own months are out
        ts_al.append(al)
        c1, c0 = _capex_growth(E, c, 0), _capex_growth(E, c, 1)
        dcap.append(c1 - c0 if np.isfinite(c1) and np.isfinite(c0) else np.nan)
        peer.append(_peer(E, e["group"], e["ticker"], c, e["season"])[0])
        P80 = E[(E["group"] == e["group"]) & (E["ticker"] != e["ticker"]) & (E["d0"] <= c) & (E["d0"] > c - pd.Timedelta(days=PEER_DAYS))]
        a80 = P80["acc"].dropna().clip(-ACC_CAP, ACC_CAP)
        peer80.append(float(a80.mean()) if len(a80) else np.nan)
    E["d_tsmc"], E["tsmc_aligned"], E["d_capex"], E["peer"], E["peer80"] = ts, ts_al, dcap, peer, peer80
    return E


# ---------------------------------------------------------------- the nowcast, walked forward
FEATS = {"tsmc": ["d_tsmc"], "capex": ["d_capex"], "peers": ["peer"], "peers_80d": ["peer80"], "all": ["d_tsmc", "d_capex", "peer"]}
PEER_DAYS = 80                    # the first definition tried for the peer signal: any peer report in the 80 days before the cutoff


def _fit(X: np.ndarray, y: np.ndarray, ridge: float = 1.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd > 1e-6, sd, np.inf)              # a feature with no spread in training gets no weight
    y = np.clip(y, -ACC_CAP, ACC_CAP)
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    pen = ridge * np.eye(Z.shape[1])
    pen[0, 0] = 0
    b = np.linalg.solve(Z.T @ Z + pen, Z.T @ y)
    return b, mu, sd


def _pred(b, mu, sd, x: np.ndarray) -> float:
    return float(b[0] + ((x - mu) / sd) @ b[1:])


def walk_forward(E: pd.DataFrame, model: str, group: str) -> pd.Series:
    """Out-of-sample nowcast of revenue acceleration for each event, trained only on events whose reports came before
    its cutoff. Missing signals are set to the training mean (no information)."""
    cols = FEATS[model]
    out = pd.Series(np.nan, index=E.index)
    G = E if group == "all" else E[E["group"] == group]
    for i, e in G.iterrows():
        if not np.isfinite(e["acc"]):
            continue
        tr = G[(G["d0"] < e["cutoff"]) & G["acc"].notna()]
        tr = tr[tr[cols].notna().any(axis=1)]
        if len(tr) < MIN_TRAIN:
            continue
        X = tr[cols].to_numpy(float)
        m = np.nanmean(X, 0)
        X = np.where(np.isfinite(X), X, m)
        b, mu, sd = _fit(X, tr["acc"].to_numpy(float))
        x = e[cols].to_numpy(float)
        x = np.where(np.isfinite(x), x, m)
        out[i] = _pred(b, mu, sd, x)
    return out


def _dm(y: np.ndarray, yhat: np.ndarray, quarters: np.ndarray, tickers: np.ndarray) -> dict:
    """Out-of-sample gain against persistence (acceleration 0), Diebold-Mariano with Newey-West errors and with errors
    clustered by calendar quarter (several companies report in one season), and each company left out in turn."""
    from . import labs
    ok = np.isfinite(y) & np.isfinite(yhat)
    y, yhat, q, tk = y[ok], yhat[ok], quarters[ok], tickers[ok]
    d = y ** 2 - (y - yhat) ** 2
    if len(d) < 12:
        return {"n": int(len(d))}
    m = labs.nw_mean(d)
    dq = pd.Series(d).groupby(q).sum()
    tq = float(dq.mean() / (dq.std(ddof=1) / math.sqrt(len(dq)))) if len(dq) > 2 and dq.std(ddof=1) > 0 else None
    loo = {}
    for t in np.unique(tk):
        k = tk != t
        loo[str(t)] = float(1 - np.sum((y[k] - yhat[k]) ** 2) / np.sum(y[k] ** 2)) if np.sum(y[k] ** 2) > 0 else None
    share = {str(t): float(d[tk == t].sum() / d.sum()) if d.sum() != 0 else None for t in np.unique(tk)}
    return {"n": int(len(d)), "mse_naive": float(np.mean(y ** 2)), "mse_model": float(np.mean((y - yhat) ** 2)),
            "r2_oos": float(1 - np.sum((y - yhat) ** 2) / np.sum(y ** 2)), "t": m["t"], "p_one_sided": float(stats.norm.sf(m["t"])),
            "t_clustered": tq, "p_clustered": float(stats.norm.sf(tq)) if tq is not None else None, "quarters": int(len(dq)),
            "r2_leave_one_out": loo, "gain_share_by_company": share}


# ---------------------------------------------------------------- does it predict returns?
def _demean(v: np.ndarray, s: np.ndarray) -> np.ndarray:
    return v - pd.Series(v).groupby(s).transform("mean").to_numpy()


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    v = float(x @ x)
    return float(x @ y / v) if v > 0 else 0.0


def perm_test(x: np.ndarray, y: np.ndarray, strata: np.ndarray, n: int = N_PERM, seed: int = SEED) -> dict:
    """Across companies within a stratum: x and y demeaned within each stratum, the slope of y on x, and a two-sided
    permutation p with x shuffled within strata. Only the variation within strata is tested, so a period in which every
    stock rose cannot pass for skill and the null is centred on zero."""
    ok = np.isfinite(x) & np.isfinite(y)
    x, y, s = x[ok], y[ok], np.asarray(strata)[ok]
    keep = pd.Series(s).map(pd.Series(s).value_counts()).to_numpy() >= 2
    x, y, s = x[keep], y[keep], s[keep]
    if len(x) < 20:
        return {"n": int(len(x))}
    xd, yd = _demean(x, s), _demean(y, s)
    if np.std(xd) == 0:
        return {"n": int(len(x))}
    rng = np.random.default_rng(seed)
    b0 = _slope(xd, yd)
    codes = pd.factorize(s)[0]
    R = rng.random((n, len(xd)))
    order = np.lexsort((R, np.broadcast_to(codes, R.shape)), axis=1)        # a random order within each stratum, per draw
    base = np.lexsort((np.arange(len(xd)), codes))                           # the stratum-sorted positions
    XP = np.empty((n, len(xd)))
    XP[:, base] = xd[order]
    v = float(xd @ xd)
    cnt = int(np.sum(np.abs(XP @ yd / v) >= abs(b0) - 1e-15))
    r = float(np.corrcoef(xd, yd)[0, 1])
    return {"n": int(len(x)), "design": "within seasons", "slope": b0, "corr": r, "p_perm": (cnt + 1) / (n + 1),
            "within_share_of_signal_variance": float(np.var(xd) / np.var(x)) if np.var(x) > 0 else None}


def perm_all(G: pd.DataFrame, x: np.ndarray, y: np.ndarray, n: int, seed: int) -> dict:
    """The within test under every stratum; the p-value is the largest of them (a joint test: the
    result counts only if it holds whichever way a season is drawn, and the choice of stratum cannot be mined)."""
    by = {st: perm_test(x, y, G[st].to_numpy(), n, seed) for st in STRATA}
    main = dict(by["season"])
    ps = [b.get("p_perm") for b in by.values()]
    main["p_perm"] = max(ps) if all(p is not None for p in ps) else None
    main["by_stratum"] = {st: {"corr": b.get("corr"), "p": b.get("p_perm"), "n": b.get("n")} for st, b in by.items()}
    return main


def ts_test(x: np.ndarray, y: np.ndarray, strata: np.ndarray, n: int = N_PERM, seed: int = SEED) -> dict:
    """Across quarters: each calendar quarter's average signal against its average outcome, whole quarters shuffled.
    This is the question for signals such as TSMC's growth that move every company together."""
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 20:
        return {"n": int(ok.sum())}
    df = pd.DataFrame({"x": x[ok], "y": y[ok], "s": strata[ok]}).groupby("s").mean()
    if len(df) < 12 or df["x"].std() == 0:
        return {"n": int(len(df))}
    xq, yq = (df["x"] - df["x"].mean()).to_numpy(), (df["y"] - df["y"].mean()).to_numpy()
    rng = np.random.default_rng(seed)
    b0 = _slope(xq, yq)
    cnt = sum(abs(_slope(rng.permutation(xq), yq)) >= abs(b0) - 1e-15 for _ in range(n))
    return {"n": int(len(df)), "design": "across quarters", "events": int(ok.sum()), "slope": b0, "corr": float(np.corrcoef(xq, yq)[0, 1]),
            "p_perm": (cnt + 1) / (n + 1)}


def _bh(p: np.ndarray, q: float = FDR_Q) -> float:
    p = np.sort(np.asarray(p, float))
    m = len(p)
    ok = np.flatnonzero(p <= q * np.arange(1, m + 1) / m)
    return float(p[ok[-1]]) if len(ok) else 0.0


def strategy(E: pd.DataFrame, P: dict, signal: str, window: str, group: str, direction: float = 1.0) -> dict:
    """Trade the hypothesis: on each event, the stock against its sector fund in the tested direction (the sign of
    the slope times the sign of the signal, both known when the window starts), over the window's days, equal weight
    across open positions, after costs. Days with nothing open count as zero, so the Sharpe is that of the strategy,
    not of its active days. The run-up window ends at the signal's cutoff, so it cannot be traded and is refused."""
    if window == "runup":
        return {"note": "not tradeable: the run-up ends when the signal becomes known"}
    G = E if group == "all" else E[E["group"] == group]
    G = G[G[signal].notna()]
    if G.empty:
        return {}
    days: dict[pd.Timestamp, list] = {}
    for _, e in G.iterrows():
        px, b = P[e["ticker"]], P[BENCH[e["group"]]]
        idx = px.index
        k0 = e["k0"]
        a, z = {"event": (k0 - 1, k0 + 1), "drift": (k0 + 2, k0 + 1 + DRIFT)}[window]
        z = min(z, len(idx) - 1)
        if a < 1 or z < a:
            continue
        sgn = float(np.sign(e[signal]) * np.sign(direction))
        if sgn == 0:
            continue
        exr = (px["ret"] - b["ret"].reindex(idx)).iloc[a:z + 1].fillna(0.0)
        cost = COST_BP / 1e4
        for j, (d, v) in enumerate(exr.items()):
            days.setdefault(d, []).append(sgn * v - (cost if j == 0 else 0.0))
    if not days:
        return {}
    s = pd.Series({d: float(np.mean(v)) for d, v in days.items()}).sort_index()
    allday = P[BENCH["cloud"]].index
    s = s.reindex(allday[(allday >= s.index[0]) & (allday <= s.index[-1])]).fillna(0.0)
    active = float((s != 0).mean())
    from . import labs
    m = labs.nw_mean(s.to_numpy())
    sh = float(s.mean() / s.std(ddof=1) * math.sqrt(252)) if s.std(ddof=1) > 0 else None
    half = {}
    for nm, part in (("first", s[s.index < SPLIT]), ("second", s[s.index >= SPLIT])):
        half[nm] = float(part.mean() / part.std(ddof=1) * math.sqrt(252)) if len(part) > 20 and part.std(ddof=1) > 0 else None
    w = np.cumprod(1 + s.to_numpy())
    return {"days": int(len(s)), "active_share": active, "from": s.index[0].strftime("%Y-%m-%d"), "to": s.index[-1].strftime("%Y-%m-%d"),
            "sharpe": sh, "t": m["t"], "return_annual": float(s.mean() * 252), "vol_annual": float(s.std(ddof=1) * math.sqrt(252)),
            "max_drawdown": float((w / np.maximum.accumulate(w) - 1).min()), "sharpe_by_half": half, "direction": "with the signal" if direction >= 0 else "against the signal",
            "curve": {"dates": [d.strftime("%Y-%m-%d") for d in s.index[::5]], "w": [float(x) for x in w[::5]]}}


def robustness(G: pd.DataFrame, signal: str, outcome: str) -> dict:
    """Two checks on a within-quarter result: the correlation with reporting order (position in the season) partialled
    out, and the correlation with each company left out in turn."""
    H = G[G[signal].notna() & G[outcome].notna()].copy()
    H = H[H.groupby("season")[signal].transform("size") >= 2]
    if len(H) < 20:
        return {}
    H["order"] = H.groupby("season")["d0"].rank(pct=True)
    d = {c: _demean(H[c].to_numpy(float), H["season"].to_numpy()) for c in (signal, outcome, "order")}

    def resid(v, o):
        return v - (np.dot(v, o) / np.dot(o, o)) * o if np.dot(o, o) > 0 else v
    xs, ys = resid(d[signal], d["order"]), resid(d[outcome], d["order"])
    loo = {}
    for t in H["ticker"].unique():
        k = (H["ticker"] != t).to_numpy()
        if k.sum() > 10:
            loo[str(t)] = float(np.corrcoef(d[signal][k], d[outcome][k])[0, 1])
    return {"corr_with_order": float(np.corrcoef(d[signal], d["order"])[0, 1]), "partial_corr_given_order": float(np.corrcoef(xs, ys)[0, 1]),
            "leave_one_company_out": loo, "loo_min": min(loo.values()) if loo else None, "loo_max": max(loo.values()) if loo else None}


def realtime_check(E: pd.DataFrame, P: dict, signal: str, group: str, slope: float) -> dict:
    """The tradeable form of a within-quarter result. The test compares each company with the season's average, which
    includes peers that report later; a trader knows only the ones already out. So: the signal minus the average
    signal of the same group's reports already out this season (before the cutoff), traded over the three report days
    against the sector fund in the tested direction, after costs. Built after the test passed, so it is a check, not
    a further discovery."""
    G = E if group == "all" else E[E["group"] == group]
    G = G.sort_values("d0")
    out = []
    for _, e in G.iterrows():
        if not np.isfinite(e[signal]) or not np.isfinite(e["car3"]):
            continue
        prior = G[(G["season"] == e["season"]) & (G["d0"] < e["cutoff"]) & G[signal].notna()]
        if prior.empty:
            continue
        rel = e[signal] - prior[signal].mean()
        if rel == 0:
            continue
        out.append({"d0": e["d0"], "ret": float(np.sign(slope) * np.sign(rel) * e["car3"] - COST_BP / 1e4), "rel": rel, "car3": e["car3"]})
    if len(out) < 20:
        return {"n": len(out)}
    D = pd.DataFrame(out)
    r = D["ret"].to_numpy()
    first, second = D[D["d0"] < SPLIT]["ret"], D[D["d0"] >= SPLIT]["ret"]
    return {"n": int(len(r)), "mean_per_report": float(r.mean()), "t": float(r.mean() / (r.std(ddof=1) / math.sqrt(len(r)))), "hit": float((r > 0).mean()),
            "corr": float(np.corrcoef(D["rel"], D["car3"])[0, 1]), "first_half": float(first.mean()) if len(first) else None,
            "second_half": float(second.mean()) if len(second) else None, "note": "built after the test passed: a check, not a discovery"}


# ---------------------------------------------------------------- today
def today(E: pd.DataFrame, P: dict, models: dict, fund_last: dict | None = None) -> list[dict]:
    """Each target's next report: the date expected, the signals published by now, the nowcast with its out-of-sample
    error (persistence where the group's model has not beaten it out of sample), and any drift position still open."""
    T = tsmc_monthly()
    fund_last = fund_last or {}
    last_day = max(p.index[-1] for p in P.values())
    out = []
    for t, (name, grp) in TARGETS.items():
        G = E[E["ticker"] == t]
        if G.empty:
            continue
        last = G.iloc[-1]
        f_last = fund_last.get(t)
        if f_last is not None and f_last > last["period_end"] + pd.Timedelta(days=30):
            continue                                   # a newer quarter is filed but its release is not on record: no clean nowcast
        nxt_pe = last["period_end"] + pd.Timedelta(days=91)
        ly = G[(G["period_end"] - (nxt_pe - pd.Timedelta(days=364))).abs() <= pd.Timedelta(days=20)]
        nxt_rel = (ly["release"].iloc[-1] + pd.Timedelta(days=364)) if len(ly) else last["release"] + pd.Timedelta(days=91)   # same quarter a year ago
        endm = (nxt_pe - pd.Timedelta(days=14)).to_period("M").to_timestamp()
        g1, al = _tsmc_growth(T, endm, last_day)
        g0, _ = _tsmc_growth(T, endm - pd.DateOffset(months=3), last_day)
        d_tsmc = g1 - g0 if (al and np.isfinite(g1) and np.isfinite(g0)) else np.nan
        c1, c0 = _capex_growth(E, last_day, 0), _capex_growth(E, last_day, 1)
        d_capex = c1 - c0 if np.isfinite(c1) and np.isfinite(c0) else np.nan
        peer, peers = _peer(E, grp, t, last_day, (nxt_pe - pd.Timedelta(days=15)).to_period("Q").strftime("%YQ%q"))   # peers already out on the coming season
        M = models.get(grp)
        acc_hat, basis = None, None
        if M:
            if M["beats_persistence"]:
                P80 = E[(E["group"] == grp) & (E["ticker"] != t) & (E["d0"] <= last_day) & (E["d0"] > last_day - pd.Timedelta(days=PEER_DAYS))]
                a80 = P80["acc"].dropna().clip(-ACC_CAP, ACC_CAP)
                peer80 = float(a80.mean()) if len(a80) else np.nan
                x = np.array([{"d_tsmc": d_tsmc, "d_capex": d_capex, "peer": peer, "peer80": peer80}[c] for c in M["cols"]], float)
                x = np.where(np.isfinite(x), x, M["fill"])
                acc_hat, basis = _pred(M["b"], M["mu"], M["sd"], x), "model"
            else:
                acc_hat, basis = 0.0, "persistence (the model has not beaten it out of sample)"
        drift_on = bool(last["drift_partial"]) and np.isfinite(last["acc"])
        out.append({"ticker": t, "name": name, "group": grp, "in_book": t in BOOK,
                    "last_release": last["release"].strftime("%Y-%m-%d"), "last_quarter_end": last["period_end"].strftime("%Y-%m-%d"),
                    "last_yoy": float(last["yoy"]) if np.isfinite(last["yoy"]) else None, "last_acc": float(last["acc"]) if np.isfinite(last["acc"]) else None,
                    "next_quarter_end": nxt_pe.strftime("%Y-%m-%d"), "next_report_expected": nxt_rel.strftime("%Y-%m-%d"),
                    "already_reported": bool(nxt_rel < last_day - pd.Timedelta(days=10)),
                    "signals": {"d_tsmc": None if not np.isfinite(d_tsmc) else float(d_tsmc), "tsmc_aligned": al,
                                "d_capex": None if not np.isfinite(d_capex) else float(d_capex), "peer": None if not np.isfinite(peer) else float(peer),
                                "peers_reported": peers},
                    "nowcast_acc": acc_hat, "nowcast_basis": basis,
                    "nowcast_yoy": (float(last["yoy"]) + acc_hat) if (acc_hat is not None and np.isfinite(last["yoy"])) else None,
                    "rmse_oos": M["rmse_oos"] if M else None,
                    "drift_position": ({"side": "long" if last["acc"] > 0 else "short", "since": last["d0"].strftime("%Y-%m-%d"),
                                        "days_left": int(DRIFT + 1 - (len(P[t].index) - 1 - last["k0"]))} if drift_on else None)})
    return out


# ---------------------------------------------------------------- build
def _tsmc_3m(T: pd.DataFrame) -> dict:
    v = T["revenue_ntd_m"].astype(float)
    r3 = v.rolling(3).sum()
    g = np.log(r3 / r3.shift(12)).dropna()
    return {"months": [m.strftime("%Y-%m") for m in g.index], "growth": [float(x) for x in g]}


def build(dl: dict, n_perm: int = N_PERM, n_fake: int = N_FAKE, seed: int = SEED) -> dict:
    t0 = time.time()
    E, P, rinfo = events(dl)
    E = add_signals(E)
    # 1. the nowcast, walked forward, against persistence
    acc_tests, preds = [], {}
    for g in GROUPS:
        for mname in FEATS:
            pr = walk_forward(E, mname, g)
            preds[(mname, g)] = pr
            G = E if g == "all" else E[E["group"] == g]
            res = _dm(G["acc"].to_numpy(float), pr[G.index].to_numpy(float), G["quarter"].to_numpy(), G["ticker"].to_numpy())
            res.update({"kind": "accuracy", "model": mname, "group": g, "signal": f"nowcast ({mname})", "target": "revenue acceleration"})
            res["p"] = res.get("p_clustered") if res.get("p_clustered") is not None else res.get("p_one_sided")   # errors clustered by quarter
            acc_tests.append(res)
    E["nowcast"] = np.nan                          # each event's out-of-sample nowcast from its own group's model ("other" uses the pooled one)
    for g in ("chips", "cloud", "other"):
        ix = E.index[E["group"] == g]
        E.loc[ix, "nowcast"] = preds[("all", g if g != "other" else "all")][ix]
    # 2. return hypotheses: within quarters for every signal, across quarters for TSMC and capital spending
    ret_tests = []
    for sig in list(PRE_SIGNALS) + list(POST_SIGNALS):
        for win in (("event", "runup") if sig in PRE_SIGNALS else ("drift",)):
            for g in GROUPS:
                G = E if g == "all" else E[E["group"] == g]
                x, y = G[sig].to_numpy(float), G[WINCOL[win]].to_numpy(float)
                r = perm_all(G, x, y, n_perm, seed)
                halves = {}
                for nm, part in (("first", G[G["d0"] < SPLIT]), ("second", G[G["d0"] >= SPLIT])):
                    xx, yy, ss = part[sig].to_numpy(float), part[WINCOL[win]].to_numpy(float), part["season"].to_numpy()
                    ok = np.isfinite(xx) & np.isfinite(yy)
                    xd, yd = _demean(xx[ok], ss[ok]), _demean(yy[ok], ss[ok])
                    halves[nm] = {"n": int(ok.sum()), "corr": float(np.corrcoef(xd, yd)[0, 1]) if ok.sum() > 8 and np.std(xd) > 0 and np.std(yd) > 0 else None}
                r.update({"kind": "returns", "signal": sig, "signal_name": (PRE_SIGNALS | POST_SIGNALS)[sig], "window": win, "window_name": WINDOWS[win],
                          "group": g, "halves": halves, "p": r.get("p_perm"), "tradeable": win != "runup"})
                ret_tests.append(r)
    for sig in TS_SIGNALS:
        for g in GROUPS:
            G = E if g == "all" else E[E["group"] == g]
            r = ts_test(G[sig].to_numpy(float), G["car3"].to_numpy(float), G["quarter"].to_numpy(), n_perm, seed)
            halves = {}
            for nm, part in (("first", G[G["d0"] < SPLIT]), ("second", G[G["d0"] >= SPLIT])):
                rr = ts_test(part[sig].to_numpy(float), part["car3"].to_numpy(float), part["quarter"].to_numpy(), 1, seed)
                halves[nm] = {"n": rr.get("n"), "corr": rr.get("corr")}
            r.update({"kind": "returns", "signal": sig, "signal_name": PRE_SIGNALS[sig], "window": "event", "window_name": WINDOWS["event"] + ", across quarters",
                      "group": g, "halves": halves, "p": r.get("p_perm"), "tradeable": False})
            ret_tests.append(r)
    tests = acc_tests + ret_tests
    p = np.array([x["p"] if x.get("p") is not None else 1.0 for x in tests])
    cut = _bh(p)
    for x, pv in zip(tests, p):
        x["pass_bh"] = bool(cut > 0 and pv <= cut)
        if x["kind"] == "returns":
            h = x["halves"]
            x["same_sign_both_halves"] = bool(h["first"]["corr"] is not None and h["second"]["corr"] is not None and x.get("corr") is not None
                                              and np.sign(h["first"]["corr"]) == np.sign(h["second"]["corr"]) == np.sign(x["corr"]))
        else:
            x["same_sign_both_halves"] = None
    # power: the smallest correlation the first BH step can detect with this many reports
    n_typ = int(np.median([x["n"] for x in ret_tests if x.get("design") == "within seasons" and x.get("n")]))
    power = {"reports": n_typ, "first_step_p": FDR_Q / len(tests),
             "min_detectable_corr": float(stats.norm.isf(FDR_Q / len(tests) / 2) / math.sqrt(n_typ))}
    for x in ret_tests:                            # the real-time form and robustness of every within-quarter result that passed
        if x["pass_bh"] and x.get("design") == "within seasons":
            G = E if x["group"] == "all" else E[E["group"] == x["group"]]
            x["robust"] = robustness(G, x["signal"], WINCOL[x["window"]])
            if x["window"] == "event":
                x["realtime"] = realtime_check(E, P, x["signal"], x["group"], x.get("slope") or 1.0)
    # 3. strategies: every tradeable return hypothesis that passed BH, and always the classic drift rules
    for x in ret_tests:
        if x.get("tradeable") and (x["pass_bh"] or (x["signal"] in POST_SIGNALS and x["group"] == "all")):
            x["strategy"] = strategy(E, P, x["signal"], x["window"], x["group"], direction=np.sign(x.get("slope") or 1.0) or 1.0)
            st = x["strategy"]
            x["pass_costs"] = bool(st and st.get("t") is not None and st["t"] >= 2.0 and (st["sharpe_by_half"].get("first") or 0) > 0 and (st["sharpe_by_half"].get("second") or 0) > 0)
    # 4. placebos through the same tests at the same cut. (a) Random signals with the real signals' split of variance
    # between and within seasons; (b) the real peer signal and nowcast moved to another season of the same company, so
    # the report calendar and each company's own pattern are kept and only the link to that season's returns is cut
    rng = np.random.default_rng(seed + 1)
    share = np.nanmedian([x.get("within_share_of_signal_variance") for x in ret_tests if x.get("within_share_of_signal_variance") is not None])
    fake = {"random, within seasons": [0, 0], "random, across quarters": [0, 0], "real signal, seasons shuffled": [0, 0]}
    fake_p = []
    combos = [(g, w) for g in GROUPS for w in ("event", "runup", "drift")]
    for k in range(n_fake):
        g, win = combos[k % len(combos)]
        G = E if g == "all" else E[E["group"] == g]
        kind = ("random, within seasons", "random, within seasons", "random, across quarters", "real signal, seasons shuffled")[(k // len(combos)) % 4]
        if kind == "real signal, seasons shuffled":
            sig = ("peer", "nowcast")[k % 2]
            seas = sorted(G["season"].unique())
            perm = dict(zip(seas, rng.permutation(seas)))
            look = {(r_["ticker"], r_["season"]): r_[sig] for _, r_ in G.iterrows()}
            x = np.array([look.get((r_["ticker"], perm[r_["season"]]), np.nan) for _, r_ in G.iterrows()], float)
        else:
            qs = G["season"].to_numpy()
            uq = {q: rng.normal() for q in np.unique(qs)}
            x = math.sqrt(1 - share) * np.array([uq[q] for q in qs]) + math.sqrt(share) * rng.normal(size=len(G))
        y = G["car3" if kind == "random, across quarters" else WINCOL[win]].to_numpy(float)
        r = ts_test(x, y, G["quarter"].to_numpy(), n_perm, seed + 100 + k) if kind == "random, across quarters" else perm_all(G, x, y, n_perm, seed + 100 + k)
        if r.get("p_perm") is not None:
            fake[kind][0] += 1
            fake[kind][1] += int(cut > 0 and r["p_perm"] <= cut)
            fake_p.append(r["p_perm"])
    # 5. the final models for today
    models = {}
    acc_all = {t["group"]: t for t in acc_tests if t["model"] == "all"}
    for g in ("chips", "cloud", "other"):
        G = E if g == "other" else E[E["group"] == g]
        tr = G[G["acc"].notna() & G[FEATS["all"]].notna().any(axis=1)]
        if len(tr) < MIN_TRAIN:
            continue
        X = tr[FEATS["all"]].to_numpy(float)
        fill = np.nanmean(X, 0)
        X = np.where(np.isfinite(X), X, fill)
        b, mu, sd = _fit(X, tr["acc"].to_numpy(float))
        key = ("all", g if g != "other" else "all")
        ok = preds[key].notna() & E["acc"].notna() & ((E["group"] == g) if g != "other" else (E["group"] == "other"))
        err_m = (E.loc[ok, "acc"] - preds[key][ok]).to_numpy(float)
        err_p = E.loc[ok, "acc"].to_numpy(float)
        gg = g if g != "other" else "all"
        passing = [t for t in acc_tests if t["group"] == gg and t["pass_bh"] and (t.get("r2_oos") or 0) > 0]
        best_t = max(passing, key=lambda t: t["r2_oos"]) if passing else None
        r2 = best_t["r2_oos"] if best_t else acc_all.get(gg, {}).get("r2_oos")
        beats = best_t is not None                     # a model is used only where it passed the multiple-testing cut
        if beats and best_t["model"] != "all":         # refit the passing model's own signals
            cols = FEATS[best_t["model"]]
            Xb = tr[cols].to_numpy(float)
            fill_b = np.nanmean(Xb, 0)
            b, mu, sd = _fit(np.where(np.isfinite(Xb), Xb, fill_b), tr["acc"].to_numpy(float))
            fill = fill_b
            key = (best_t["model"], gg)
            ok = preds[key].notna() & E["acc"].notna() & ((E["group"] == g) if g != "other" else (E["group"] == "other"))
            err_m = (E.loc[ok, "acc"] - preds[key][ok]).to_numpy(float)
            err_p = E.loc[ok, "acc"].to_numpy(float)
        err = err_m if beats else err_p
        cols_used = FEATS[best_t["model"]] if beats else FEATS["all"]
        models[g] = {"b": b, "mu": mu, "sd": sd, "fill": fill, "rmse_oos": float(np.sqrt(np.mean(err ** 2))) if len(err) else None, "cols": cols_used,
                     "coef_std": {f: float(c) for f, c in zip(cols_used, b[1:])}, "n": int(len(tr)), "beats_persistence": beats, "r2_oos": r2,
                     "model": best_t["model"] if beats else None}
    td = today(E, P, models, {t: _fund(dl["fund"][t]).index[-1] for t in TARGETS if t in dl["fund"]})
    # 6. dating: releases on record against the independently verified dates
    R, _ = release_dates()
    have = set(zip(R["ticker"], R["release_date"].dt.strftime("%Y-%m-%d")))
    spot = [{"ticker": t, "release": d, "on_record": (t, d) in have} for t, d in VERIFIED_RELEASES]
    srcs = R["source"].value_counts().to_dict()
    T = tsmc_monthly()
    tsmc_recent = [{"month": m.strftime("%Y-%m"), "revenue_ntd_m": int(r["revenue_ntd_m"]), "yoy_printed_pct": r["yoy_printed_pct"], "knowable": r["avail"].strftime("%Y-%m-%d")}
                   for m, r in T.tail(18).iterrows()]
    by_t = E.groupby("ticker").agg(events=("d0", "size"), first=("d0", "min"), last=("d0", "max")).reset_index()
    out = {
        "schema": 2, "asof": dl.get("asof"), "data_through": max(p.index[-1] for p in P.values()).strftime("%Y-%m-%d"), "fdr_q": FDR_Q,
        "sources": {"prices_and_financials": MIRROR_REPO, "tsmc": "https://investor.tsmc.com/english/monthly-revenue/",
                    "releases": "SEC Form 8-K Item 2.02 filing dates (via the stocks-earnings-dates package) and companies' own releases",
                    "note": "a public GitHub mirror of Yahoo Finance daily prices and SEC XBRL company facts, refreshed nightly; TSMC's own monthly revenue pages"},
        "universe": {"targets": {t: {"name": n, "group": g} for t, (n, g) in TARGETS.items()}, "bench": BENCH, "hyperscalers": list(HYPERSCALERS),
                     "book_without_history": [t for t in BOOK if t not in TARGETS]},
        "events": {"n": int(len(E)), "with_acc": int(E["acc"].notna().sum()), "from": E["d0"].min().strftime("%Y-%m-%d"), "to": E["d0"].max().strftime("%Y-%m-%d"),
                   "undated": rinfo["undated"], "releases_on_record": rinfo["releases_on_record"], "release_sources": srcs,
                   "data_breaks": [{"ticker": t, "from": a, "to": b, "why": w} for t, a, b, w in DATA_BREAKS],
                   "data_break_quarters": int(E["data_break"].notna().sum()),
                   "by_ticker": [{"ticker": r["ticker"], "events": int(r["events"]), "first": r["first"].strftime("%Y-%m-%d"), "last": r["last"].strftime("%Y-%m-%d")}
                                 for _, r in by_t.iterrows()],
                   "date_check": {"verified": spot, "verified_on_record": int(sum(x["on_record"] for x in spot)),
                                  "note": "independently verified release dates (company releases and SEC filings); none was used to set a rule"},
                   "signal_coverage": {s: float(E[s].notna().mean()) for s in ("d_tsmc", "d_capex", "peer", "peer80", "nowcast")},
                   "timing": rinfo["timing"]},
        "tests": tests, "bh_cut": cut, "n_hypotheses": int(len(tests)), "power": power,
        "fakes": {"signals": n_fake, "tried": sum(v[0] for v in fake.values()), "passed_at_cut": sum(v[1] for v in fake.values()),
                  "by_design": fake,
                  "share_p_below_05": float(np.mean(np.array(fake_p) <= 0.05)) if fake_p else None, "within_share_used": float(share)},
        "models": {g: {"coef_std": m["coef_std"], "rmse_oos": m["rmse_oos"], "n": m["n"], "beats_persistence": m["beats_persistence"], "r2_oos": m["r2_oos"], "model": m["model"]}
                   for g, m in models.items()},
        "today": td, "tsmc_recent": tsmc_recent, "tsmc_3m": _tsmc_3m(T),
        "scatter": [{"t": e["ticker"], "q": e["period_end"].strftime("%Y-%m"), "x": None if not np.isfinite(e["nowcast"]) else float(e["nowcast"]),
                     "acc": None if not np.isfinite(e["acc"]) else float(e["acc"]), "car3": None if not np.isfinite(e["car3"]) else float(e["car3"]),
                     "drift": None if not np.isfinite(e["drift"]) else float(e["drift"])} for _, e in E.iterrows()],
        "timing_s": round(time.time() - t0, 1),
        "assumptions": {"cutoff": f"the close {CUTOFF} trading days before the report day", "tsmc_knowable": f"the {TSMC_AVAIL_DAY}th of the next month",
                        "report_day": f"the first release {MIN_GAP} to {MAX_GAP} days after the quarter's end; the next trading day for a release after the close, the same day before the open",
                        "abnormal_return": "the stock's total return minus its sector fund's (SOXX for chips, QQQ otherwise)", "costs_bp_round_trip": COST_BP,
                        "permutations": n_perm, "split": SPLIT, "fdr_q": FDR_Q, "acc_cap": ACC_CAP, "strata": list(STRATA)},
        "limitations": LIMITATIONS,
    }
    out = _clean(out)
    out["findings"] = summary(out)
    return out


LIMITATIONS = [
    "Fifteen companies and about ten years give a few hundred company quarters: the tests can detect only correlations of about 0.2 or more with report-day returns, not smaller ones, and the groups (seven chip makers, five cloud companies) are smaller still.",
    "Two independent audits changed this engine before release: report days now come from the companies' releases (dating from trading volume was wrong for most quarters), and two strong-looking results for chip makers turned out to depend on how a season was drawn. Every variant tried is in the count; the forking paths behind them are not all countable.",
    "The SEC financials are the mirror's values: mostly first prints, but where only a later filing survives, a restated figure. Two known breaks are left out: Western Digital around the SanDisk separation and Microsoft's fiscal 2017 under the 2018 revenue standard.",
    "There is no analyst consensus here (it is licensed data), so a surprise is measured against persistence of growth, not against what the market expected; a signal can predict revenue well and still be fully priced.",
    "Most of TSMC's and the hyperscalers' variation is common to every company in a quarter, so across companies it is barely testable; the across-quarter tests have only about forty quarters.",
    "TSMC's figures are consolidated, unaudited and in New Taiwan dollars, so currency moves enter its growth; the hyperscalers' capital spending is cash spent on property and equipment, without finance leases.",
    "Release dates are SEC filing dates of the earnings release (Form 8-K Item 2.02) and, where those are missing, dates read from the companies' releases; each company's usual timing (after the close or before the open) sets the report day.",
    "The mirror is a third party's nightly copy of Yahoo Finance and SEC data; prices and filings are spot-checked here, not audited. SpaceX has traded only since June 2026 and has no reports yet, so it has no nowcast.",
]


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d")
    return o


def _f(x, nd=2):
    return "n/a" if x is None else f"{x:.{nd}f}"


def _pct(x, nd=0):
    return "n/a" if x is None else f"{x * 100:.{nd}f}%"


def _growth(x):
    """Log growth as a percentage change."""
    return "n/a" if x is None else f"{(math.exp(x) - 1) * 100:.0f}%"


def summary(o: dict) -> list[str]:
    ev = o["events"]
    dc = ev["date_check"]
    out = [f"{ev['n']} company quarters from {ev['from'][:4]} to {ev['to'][:4]} across {len(o['universe']['targets'])} companies, each dated by its "
           f"earnings release ({ev['releases_on_record']} releases on record; {dc['verified_on_record']} of {len(dc['verified'])} independently verified "
           f"dates are among them); {len(ev['undated'])} quarters with no release on record are left out, not guessed."]
    acc = [t for t in o["tests"] if t["kind"] == "accuracy" and t.get("r2_oos") is not None]
    best = max(acc, key=lambda t: t["r2_oos"]) if acc else None
    if best:
        loo = best.get("r2_leave_one_out") or {}
        worst = min(loo.items(), key=lambda kv: kv[1] if kv[1] is not None else 9) if loo else None
        out.append(f"Nowcasting revenue acceleration: the best of {len(acc)} walked-forward models ({best['model']}, {best['group']}) cut the persistence "
                   f"forecast's squared error by {_pct(best['r2_oos'])} (t {_f(best['t'], 1)}; clustered by quarter {_f(best.get('t_clustered'), 1)}; "
                   f"{best['n']} quarters)" + (f"; without {worst[0].upper()} the gain is {_pct(worst[1])}" if worst else "")
                   + ("; it passes the multiple-testing cut." if best["pass_bh"] else "; it does not pass the multiple-testing cut."))
    rt = [t for t in o["tests"] if t["kind"] == "returns"]
    passed = [t for t in rt if t["pass_bh"]]
    pw = o["power"]
    out.append(f"{o['n_hypotheses']} hypotheses were tested (permutation p-values, Benjamini-Hochberg at q = {o['fdr_q']}): "
               f"{sum(t['pass_bh'] for t in o['tests'])} passed, {len(passed)} of them about returns. Of {o['fakes']['tried']} random signals through the "
               f"same tests, {o['fakes']['passed_at_cut']} passed. With about {pw['reports']} reports a test can detect a correlation of about "
               f"{_f(pw['min_detectable_corr'])} or more, so smaller mispricings are not ruled out.")
    for t in passed:
        rt_ = t.get("realtime") or {}
        out.append(f"Among {t['group']}, {t['signal_name'][0].lower() + t['signal_name'][1:]} goes with the {t['window_name']} return against the season's other "
                   f"companies with correlation {_f(t.get('corr'))} (permutation p {t['p']:.3g}, the largest across three ways of drawing a season; same sign in "
                   f"both halves: {'yes' if t['same_sign_both_halves'] else 'no'})"
                   + (f". Traded in real time (against only the companies already out), it earned {_pct(rt_.get('mean_per_report'), 2)} a report after costs "
                      f"(t {_f(rt_.get('t'), 1)}, {rt_.get('n')} reports): not yet a trade." if rt_.get("t") is not None else "."))
    nw = [t for t in rt if t["signal"] == "nowcast" and t["window"] == "event" and t["group"] == "all"]
    if nw:
        t = nw[0]
        out.append(f"Within seasons, the nowcast's correlation with the report-day return is {_f(t.get('corr'))} (permutation p {_f(t.get('p'), 3)}, "
                   "the largest across three ways of drawing a season).")
    dr = [t for t in rt if t["signal"] == "acc" and t["window"] == "drift" and t["group"] == "all"]
    if dr and dr[0].get("strategy"):
        st = dr[0]["strategy"]
        out.append(f"Drift after the report on the revenue surprise: correlation {_f(dr[0].get('corr'))} (p {_f(dr[0].get('p'), 2)}); traded in the tested "
                   f"direction after costs, Sharpe {_f(st.get('sharpe'))} (t {_f(st.get('t'), 1)}) over all days, positions open {_pct(st.get('active_share'))} of them.")
    nxt = [x for x in o["today"] if x["in_book"] and x.get("nowcast_yoy") is not None and not x["already_reported"]]
    if nxt:
        out.append("Next reports in the book (research only): " + "; ".join(
            f"{x['name']} about {x['next_report_expected']}, revenue growth {_growth(x['nowcast_yoy'])} a year (last {_growth(x['last_yoy'])}"
            + (", persistence" if x.get("nowcast_basis", "").startswith("persistence") else "") + ")" for x in nxt[:6]) + ".")
    return out
