"""The futures engine (v0.29): carry, trend, basis momentum and hedgers' positioning across liquid CME futures, tested
for whether they still pay after costs, and read for the book's hedge.

The filings engine (v0.28) looks for edges inside one asset class, large US stocks. Futures add bets of a different
kind: Treasuries, currencies, metals, energy, grains and livestock beside the equity indexes. Their best known
premia, carry and trend, have survived publication better than most equity anomalies, which makes them a fair test of
whether known edges still pay. And the book's hedge is a Treasury position, so the engine also reads what Treasury
futures pay to hold and how they behaved when stocks fell.

  data          per market, each day: the price of the contract held, the price of the next contract, and which
                contracts they are. Two sources in one format: pysystemtrade's published multiple prices (Rob
                Carver's open-source project, daily since the 1970s and 1980s, through March 2024; reachable from the
                build workspace) and Databento's CME Globex daily bars with contract definitions (from 2010 to now; needs
                DATABENTO_API_KEY). Returns are those of the contract held: on a roll day the new contract's return is
                taken from its own previous close, so a roll is never a jump (with no such close the day is missing)
  signals       carry, the annualized log price gap between the nearer and the further contract (Koijen, Moskowitz,
                Pedersen and Vrugt 2018); trend, the return over the past 1, 3 and 12 months (Moskowitz, Ooi and Pedersen
                2012); basis momentum, the past 12 months' return of the held contract less that of the next contract
                when it expires one to three months later, on the days both have prices (Boons and Prado 2019); and hedging pressure, commercial hedgers' net short share of their positions in
                the CFTC's Commitments of Traders, used only after its release and not at all in the months when
                government shutdowns delayed it (de Roon, Nijman and Veld 2000; Basu and Miffre 2013). Every signal
                is known at the month's last close and trades from it
  tests         each signal as two portfolios rebalanced monthly: across markets (long the top, short the bottom by
                rank, each market sized to equal risk) and over time (each market long or short by the signal's sign,
                sized to equal risk). Net of trading and roll costs. One-sided p-values (in the published direction) from
                each portfolio's monthly returns by the equal-weighted cosine test (Lazarus, Lewis, Stock and Watson 2018), Benjamini-Hochberg across every
                signal and design, both halves of the record (split at its middle month), the return beyond its beta
                to a passive long portfolio of all the markets at equal risk, the record since publication, and random persistent signals through the same test for the false-pass rate
  book          for the Treasury and equity index futures: today's carry and trend with their history, how each
                Treasury future did in the months stocks fell most, and its correlation with stocks by decade. Research
                only.

Run here on pysystemtrade data, or with Databento and the CFTC where they are reachable:
    python -m buildout futures --source pysystemtrade --out out
    python -m buildout futures --source databento --out out          (needs DATABENTO_API_KEY)
"""
from __future__ import annotations

import io
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from scipy.stats import rankdata
from scipy.stats import t as student_t

from .filings import ewc_test

CARVER_URL = "https://raw.githubusercontent.com/robcarver17/pysystemtrade/master/data/futures/multiple_prices_csv/{name}.csv"
CFTC_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"           # Legacy Commitments of Traders, futures only
DATASET = "GLBX.MDP3"

# market: (name, Databento root, pysystemtrade name, CFTC code, CFTC name check, asset class, round-trip cost in bp of notional)
# CFTC codes checked against the CFTC's own records (2026-10-20 report; Eurodollar and the dollar Nikkei in 2020).
MARKETS = {
    "ES": ("S&P 500 E-mini", "ES", "SP500", "13874A", "S&P 500", "equity", 1.5),
    "NQ": ("Nasdaq-100 E-mini", "NQ", "NASDAQ", "209742", "NASDAQ", "equity", 1.5),
    "YM": ("Dow E-mini", "YM", "DOW_mini", "124603", "DJIA", "equity", 2.0),
    "RTY": ("Russell 2000 E-mini", "RTY", "RUSSELL_mini", "239742", "RUSSELL", "equity", 2.0),
    "NKD": ("Nikkei 225 (dollar)", "NKD", "NIKKEI-CME", "240741", "NIKKEI", "equity", 3.0),
    "ZT": ("2-year Treasury note", "ZT", "US2", "042601", "2Y", "rates", 1.0),
    "ZF": ("5-year Treasury note", "ZF", "US5", "044601", "5Y", "rates", 1.0),
    "ZN": ("10-year Treasury note", "ZN", "US10", "043602", "10Y", "rates", 1.0),
    "TN": ("Ultra 10-year Treasury", "TN", "US10U", "043607", "ULTRA UST 10Y", "rates", 1.5),
    "ZB": ("Treasury bond", "ZB", "US20", "020601", "BOND", "rates", 1.5),
    "UB": ("Ultra Treasury bond", "UB", "US30", "020604", "ULTRA UST BOND", "rates", 2.0),
    "GE": ("Eurodollar (to 2023)", "GE", "EDOLLAR", "132741", "EURODOLLAR", "rates", 0.5),
    "SR3": ("3-month SOFR", "SR3", "SOFR", "134741", "SOFR", "rates", 0.5),
    "6E": ("Euro", "6E", "EUR", "099741", "EURO FX", "currency", 1.0),
    "6J": ("Japanese yen", "6J", "JPY", "097741", "YEN", "currency", 1.5),
    "6B": ("British pound", "6B", "GBP", "096742", "POUND", "currency", 1.5),
    "6S": ("Swiss franc", "6S", "CHF", "092741", "FRANC", "currency", 2.0),
    "6A": ("Australian dollar", "6A", "AUD", "232741", "AUSTRALIAN", "currency", 1.5),
    "6C": ("Canadian dollar", "6C", "CAD", "090741", "CANADIAN", "currency", 1.5),
    "6M": ("Mexican peso", "6M", "MXP", "095741", "PESO", "currency", 3.0),
    "6N": ("New Zealand dollar", "6N", "NZD", "112741", "NZ DOLLAR", "currency", 3.0),
    "GC": ("Gold", "GC", "GOLD", "088691", "GOLD", "metals", 2.0),
    "SI": ("Silver", "SI", "SILVER", "084691", "SILVER", "metals", 3.0),
    "HG": ("Copper", "HG", "COPPER", "085692", "COPPER", "metals", 3.0),
    "PL": ("Platinum", "PL", "PLAT", "076651", "PLATINUM", "metals", 5.0),
    "PA": ("Palladium", "PA", "PALLAD", "075651", "PALLADIUM", "metals", 6.0),
    "CL": ("WTI crude oil", "CL", "CRUDE_W", "067651", "CRUDE", "energy", 3.0),
    "RB": ("RBOB gasoline", "RB", "GASOILINE", "111659", "GASOLINE", "energy", 4.0),
    "HO": ("Heating oil (ULSD)", "HO", "HEATOIL", "022651", "HEATING OIL|ULSD", "energy", 4.0),
    "NG": ("Natural gas", "NG", "GAS_US", "023651", "NAT", "energy", 5.0),
    "ZC": ("Corn", "ZC", "CORN", "002602", "CORN", "grains", 4.0),
    "ZW": ("Wheat (Chicago)", "ZW", "WHEAT", "001602", "WHEAT", "grains", 5.0),
    "KE": ("Wheat (Kansas City)", "KE", "REDWHEAT", "001612", "WHEAT", "grains", 6.0),
    "ZS": ("Soybeans", "ZS", "SOYBEAN", "005602", "SOYBEAN", "grains", 3.0),
    "ZM": ("Soybean meal", "ZM", "SOYMEAL", "026603", "SOYBEAN MEAL", "grains", 5.0),
    "ZL": ("Soybean oil", "ZL", "SOYOIL", "007601", "SOYBEAN OIL", "grains", 5.0),
    "LE": ("Live cattle", "LE", "LIVECOW", "057642", "LIVE CATTLE", "livestock", 5.0),
    "GF": ("Feeder cattle", "GF", "FEEDCOW", "061641", "FEEDER CATTLE", "livestock", 6.0),
    "HE": ("Lean hogs", "HE", "LEANHOG", "054642", "LEAN HOGS|HOGS", "livestock", 6.0),
}
TREASURIES = ("ZT", "ZF", "ZN", "TN", "ZB", "UB")
EQUITY_INDEX = ("ES", "NQ", "YM", "RTY")
BOOK_MARKETS = TREASURIES + EQUITY_INDEX

# signal: (name, direction, reference, year published)
SIGNALS = {
    "carry": ("Carry: annualized gap between the nearer and the further contract", +1, "Koijen, Moskowitz, Pedersen and Vrugt 2018", 2018),
    "trend_1": ("Trend: past 1 month's return", +1, "Moskowitz, Ooi and Pedersen 2012", 2012),
    "trend_3": ("Trend: past 3 months' return", +1, "Moskowitz, Ooi and Pedersen 2012", 2012),
    "trend_12": ("Trend: past 12 months' return", +1, "Moskowitz, Ooi and Pedersen 2012", 2012),
    "basis_mom": ("Basis momentum: held contract's 12-month return less the next contract's", +1, "Boons and Prado 2019", 2019),
    "hedging_pressure": ("Hedging pressure: commercial hedgers' net short share (CFTC)", +1, "de Roon, Nijman and Veld 2000; Basu and Miffre 2013", 2000),
}
DESIGNS = {"xs": "across markets", "ts": "over time"}

START = "1990-01-31"              # first month tested
SPLIT = "middle"                  # each test's record is split at its middle month (a Databento run starts in 2010)
FDR_Q = 0.05
MIN_MARKETS_XS = 10               # an across-markets month needs this many markets
MIN_MARKETS_TS = 5
MIN_MONTHS = 60
N_FAKE = 60
VOL_COM = 60                      # days: centre of mass of the exponentially weighted volatility (Moskowitz, Ooi and Pedersen)
TARGET_VOL = 0.10                 # each portfolio's returns are reported at a 10% annual volatility, in sample, for reading only
COT_LAG_DAYS = 6                  # positions as of Tuesday are released Friday afternoon; usable from the next Monday's close
# US government shutdowns stopped the CFTC's weekly releases, which came out late as a backlog; months whose cutoff falls
# in these windows (generous, from the shutdown's start to after the backlog cleared) get no positioning reading
COT_SHUTDOWNS = (("2013-10-01", "2013-11-30"), ("2018-12-22", "2019-03-31"), ("2025-10-01", "2026-01-31"))
STALE_ROWS = 5                    # a deferred contract's price unchanged for this many rows in a row is stale, not a price
SEED = 29
FADED_SHARPE = 0.25               # since publication, below this Sharpe a premium counts as faded (its standard error over 5 to 11 years is 0.3 to 0.45)


# ---------------------------------------------------------------- data: one daily format for every source
def _yyyymm(x) -> float:
    """pysystemtrade's contract ids (20240600) and maturity year/month pairs to yyyymm; NaN if unknown."""
    try:
        v = int(float(x))
    except (TypeError, ValueError):
        return np.nan
    if v > 10_000_000:
        v //= 100
    return float(v) if 190001 <= v <= 210012 else np.nan


def parse_carver(text: str) -> pd.DataFrame:
    """pysystemtrade's multiple prices (DATETIME, CARRY, CARRY_CONTRACT, PRICE, PRICE_CONTRACT, FORWARD,
    FORWARD_CONTRACT; several rows a day in recent years) to one row per day: the last price of the day for the held
    contract, the carry contract and the forward contract, each with its contract month."""
    d = pd.read_csv(io.StringIO(text))
    d["date"] = pd.to_datetime(d["DATETIME"]).dt.normalize()
    d = d.sort_values("DATETIME", kind="mergesort")
    out = {}
    for col, con, a, b in (("PRICE", "PRICE_CONTRACT", "price", "m_price"), ("CARRY", "CARRY_CONTRACT", "carry", "m_carry"),
                           ("FORWARD", "FORWARD_CONTRACT", "forward", "m_forward")):
        x = d[d[col].notna()].groupby("date").last()
        out[a] = x[col].astype(float)
        out[b] = x[con].map(_yyyymm)
    f = pd.DataFrame(out).sort_index()
    f = f[f["price"].notna() & (f.index.dayofweek < 5)]                  # Sunday-evening rows are the next session's open, not a close
    return f[["price", "m_price", "carry", "m_carry", "forward", "m_forward"]]


def front_returns(f: pd.DataFrame) -> pd.Series:
    """Daily returns of the contract held. On a roll day the new contract's previous close comes from yesterday's
    forward or carry column, so the roll is not a jump; with no such close the day is missing. A non-positive previous
    price (as in crude oil in April 2020) gives no return."""
    p, m = f["price"].to_numpy(float), f["m_price"].to_numpy(float)
    prev = np.full(len(f), np.nan)
    pp, pm = np.roll(p, 1), np.roll(m, 1)
    same = m == pm
    prev[same] = pp[same]
    for col, mc in (("forward", "m_forward"), ("carry", "m_carry")):
        q, qm = np.roll(f[col].to_numpy(float), 1), np.roll(f[mc].to_numpy(float), 1)
        use = ~same & np.isnan(prev) & (m == qm)
        prev[use] = q[use]
    prev[0] = np.nan
    r = p / prev - 1
    r[~(prev > 0) | ~np.isfinite(r)] = np.nan
    return pd.Series(r, index=f.index)


def _gap(a, b):
    return (b // 100 - a // 100) * 12 + (b % 100 - a % 100)


def second_returns(f: pd.DataFrame) -> pd.Series:
    """Daily returns of the second nearby contract for basis momentum: the forward column when it is the contract
    after the held one and expires one to three months later (Boons and Prado compare the first and second nearby;
    pysystemtrade's forward is a year out for crude oil and the grains, and Databento's v.1 is briefly the expiring
    contract after a roll, and both are left out). Same contract day to day, otherwise missing."""
    q, qm, m = f["forward"].to_numpy(float), f["m_forward"].to_numpy(float), f["m_price"].to_numpy(float)
    pq, pqm = np.roll(q, 1), np.roll(qm, 1)
    g = _gap(m, qm)
    r = np.where((qm == pqm) & (pq > 0) & (g >= 1) & (g <= 3), q / pq - 1, np.nan)
    r[0] = np.nan
    return pd.Series(r, index=f.index)


def carry_series(f: pd.DataFrame) -> pd.Series:
    """Annualized log carry: ln(P_near / P_far) x 12 / months between them, from the held and the carry contract
    (whichever expires first is the nearer). Positive when the further contract is cheaper (backwardation): holding
    the future then earns the roll if prices stand still. A carry price unchanged for STALE_ROWS rows in a row is a
    stale quote, not a price, and gives no reading."""
    a, ma, b, mb = f["price"], f["m_price"], f["carry"], f["m_carry"]
    months = (mb // 100 - ma // 100) * 12 + (mb % 100 - ma % 100)
    near_is_a = months > 0
    pn, pf = a.where(near_is_a, b), b.where(near_is_a, a)
    gap = months.abs()
    c = np.log(pn / pf) * 12 / gap
    same = (b == b.shift(1)) & (mb == mb.shift(1))
    run = same.groupby((~same).cumsum()).cumsum()                         # rows in a row with the carry price unchanged
    stale = run >= STALE_ROWS - 1
    return c.where((gap > 0) & (gap <= 24) & (pn > 0) & (pf > 0) & ~stale)


def daily_vol(r: pd.Series) -> pd.Series:
    """Annualized exponentially weighted volatility through each day (centre of mass VOL_COM days)."""
    v = (r.fillna(0.0) ** 2).ewm(com=VOL_COM, min_periods=40).mean()
    return np.sqrt(v * 261).where(r.notna().rolling(40, min_periods=1).sum() >= 30)


# ---------------------------------------------------------------- monthly panel
def month_panel(frames: dict, cot: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per (month, market): the signals known at the month's last close, the ex-ante volatility, the next
    month's return of the contract held, and the number of rolls in the next month. frames {market: daily frame}."""
    rows = []
    for k, f in frames.items():
        if f is None or f.empty:
            continue
        f = f.sort_index()
        r, r2 = front_returns(f), second_returns(f)
        vol = daily_vol(r)
        car = carry_series(f)
        per = f.index.to_period("M")
        last_day = pd.Series(f.index, index=f.index).groupby(per).max()
        lr = np.log1p(r.clip(lower=-0.99))                                  # a fall through zero (crude, April 2020) is kept as a near-total loss
        m_ret = lr.groupby(per).sum(min_count=1)
        m_obs = r.notna().groupby(per).sum()
        m_days = pd.Series(1, index=f.index).groupby(per).sum()
        m_ret = m_ret.where(m_obs >= 0.8 * m_days)                     # a month with many missing days has no return
        lastp = per[-1]
        if f.index[-1] < (lastp.start_time + pd.offsets.BMonthEnd(0)) - pd.offsets.BDay(1):
            m_ret.loc[lastp] = np.nan                                      # the month is still in progress: no return yet
        both = r.notna() & r2.notna()                                    # basis momentum compares the chains on the same days only
        bm = (np.log1p(r.clip(lower=-0.99)) - np.log1p(r2.clip(lower=-0.99))).where(both)
        m_bm = bm.groupby(per).sum(min_count=1).where(both.groupby(per).sum() >= 0.8 * m_days)
        mp = f["m_price"]
        rolls = (mp > mp.cummax().shift(1)).groupby(per).sum()              # a move to a later contract; a volume flip back is not a roll
        carm = car.groupby(per).apply(lambda x: x.dropna().tail(5).median() if x.notna().any() else np.nan)
        volm = vol.groupby(per).last()
        M = pd.DataFrame({"ret": np.expm1(m_ret), "lret": m_ret, "bm": m_bm, "vol": volm, "carry": carm, "rolls": rolls,
                          "cutoff": last_day}).sort_index()
        M = M.reindex(pd.period_range(M.index.min(), M.index.max(), freq="M"))   # a month with no data stays a gap: shifts never skip it
        M["trend_1"] = M["lret"]
        M["trend_3"] = M["lret"].rolling(3, min_periods=3).sum()
        M["trend_12"] = M["lret"].rolling(12, min_periods=11).sum()
        M["basis_mom"] = M["bm"].rolling(12, min_periods=11).sum()
        M["next_ret"] = M["ret"].shift(-1)
        M["next_rolls"] = M["rolls"].shift(-1)
        M["market"] = k
        M["month"] = M.index.to_timestamp(how="end").normalize()
        rows.append(M.reset_index(drop=True))
    P = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if cot is not None and not cot.empty and not P.empty:
        P = P.merge(cot_asof(cot, P[["market", "month", "cutoff"]]), on=["market", "month"], how="left")
    elif not P.empty:
        P["hedging_pressure"] = np.nan
    return P


def cot_asof(cot: pd.DataFrame, keys: pd.DataFrame) -> pd.DataFrame:
    """Hedging pressure at each month's cutoff from the latest report usable by then: positions as of the report
    date are released on Friday and used from the following Monday's close (report date + COT_LAG_DAYS); months whose
    cutoff falls in a government-shutdown window (COT_SHUTDOWNS) get none, since releases then came out late. cot:
    (market, report_date, comm_long, comm_short)."""
    c = cot.copy()
    c["known"] = pd.to_datetime(c["report_date"]) + pd.Timedelta(days=COT_LAG_DAYS)
    tot = c["comm_long"] + c["comm_short"]
    c["hp"] = ((c["comm_short"] - c["comm_long"]) / tot).where(tot > 0)
    out = []
    for k, g in keys.groupby("market"):
        h = c[c["market"] == k].sort_values("known", kind="mergesort")
        if h.empty:
            continue
        idx = np.searchsorted(h["known"].to_numpy(), pd.to_datetime(g["cutoff"]).to_numpy(), side="right") - 1
        ok = idx >= 0
        age = np.full(len(g), np.inf)
        age[ok] = (pd.to_datetime(g["cutoff"]).to_numpy()[ok] - h["known"].to_numpy()[idx[ok]]) / np.timedelta64(1, "D")
        v = np.where(ok & (age <= 21), h["hp"].to_numpy()[np.clip(idx, 0, None)], np.nan)
        out.append(pd.DataFrame({"market": k, "month": g["month"].to_numpy(), "hedging_pressure": v}))
    if not out:
        return pd.DataFrame(columns=["market", "month", "hedging_pressure"])
    res = pd.concat(out, ignore_index=True)
    cut = keys.set_index(["market", "month"])["cutoff"]
    cm = pd.to_datetime(cut.reindex(pd.MultiIndex.from_frame(res[["market", "month"]])).to_numpy())
    shut = np.zeros(len(res), bool)
    for a, b in COT_SHUTDOWNS:
        shut |= (cm >= pd.Timestamp(a)) & (cm <= pd.Timestamp(b))
    res.loc[shut, "hedging_pressure"] = np.nan                            # releases were late: what was public then is unknown here
    return res


# ---------------------------------------------------------------- portfolios and tests
def _xs(g: pd.DataFrame, signal: str) -> pd.Series:
    z = g[signal].rank() - (len(g) + 1) / 2
    if z.abs().sum() == 0:
        return pd.Series(0.0, index=g.index)
    z = z / z.abs().sum() * 2
    w = z / g["vol"]
    return w / w.abs().sum() * 2 * float((1 / g["vol"]).mean())         # scale by average inverse volatility; the risk level still varies by month


def weights(G: pd.DataFrame, signal: str, design: str) -> pd.Series:
    """One month's weights by market (notional per unit of capital). Across markets: centred ranks, scaled so the
    long and the short side each total one, then each market sized to equal risk (divided by its volatility). Over
    time: the sign of the signal over volatility, averaged over the markets that month."""
    g = G[[signal, "vol"]].dropna()
    g = g[g["vol"] > 0]
    if design == "xs":
        if len(g) < MIN_MARKETS_XS or g[signal].nunique() < 3:
            return pd.Series(dtype=float)
        return _xs(g, signal)
    if design == "xs_class":                         # ranked within each asset class only: no bet between classes
        if len(g) < MIN_MARKETS_XS:
            return pd.Series(dtype=float)
        cls = pd.Series({k: MARKETS.get(k, ("",) * 6)[5] for k in g.index})
        parts = [_xs(g[cls == c], signal) for c in cls.unique() if (cls == c).sum() >= 3]
        if not parts:
            return pd.Series(dtype=float)
        w = pd.concat(parts)
        return w / w.abs().sum() * 2 * float((1 / g.loc[w.index, "vol"]).mean()) if w.abs().sum() > 0 else pd.Series(dtype=float)
    if len(g) < MIN_MARKETS_TS:
        return pd.Series(dtype=float)
    return np.sign(g[signal]) / g["vol"] / len(g)


def _matrix(P: pd.DataFrame, col: str, months: np.ndarray, mk: np.ndarray) -> np.ndarray:
    return P.pivot_table(index="month", columns="market", values=col, aggfunc="last").reindex(index=months, columns=mk).to_numpy(float)


def _weights_matrix(S: np.ndarray, V: np.ndarray, design: str, cls: np.ndarray | None = None) -> np.ndarray:
    """The weights() rule for every month at once (months x markets; NaN where a market has no position)."""
    ok = np.isfinite(S) & np.isfinite(V) & (V > 0)
    W = np.zeros_like(S)
    n = ok.sum(1)
    if design == "ts":
        use = n >= MIN_MARKETS_TS
        with np.errstate(invalid="ignore", divide="ignore"):
            W = np.where(ok, np.sign(np.nan_to_num(S)) / np.where(ok, V, 1.0), 0.0) / np.maximum(n, 1)[:, None]
        W[~use] = 0.0
        return np.where(use[:, None], W, np.nan)
    groups = [np.ones(S.shape[1], bool)] if design == "xs" else [cls == c for c in np.unique(cls)]
    for t in range(S.shape[0]):
        if n[t] < MIN_MARKETS_XS:
            continue
        parts = np.zeros(S.shape[1])
        held = np.zeros(S.shape[1], bool)
        for g in groups:
            m = ok[t] & g
            k = int(m.sum())
            if k < (3 if design == "xs_class" else MIN_MARKETS_XS) or (design == "xs" and len(np.unique(S[t, m])) < 3):
                continue
            z = rankdata(S[t, m]) - (k + 1) / 2
            held |= m
            if np.abs(z).sum() == 0:
                continue
            z = z / np.abs(z).sum() * 2
            w = z / V[t, m]
            if design == "xs":
                parts[m] = w / np.abs(w).sum() * 2 * np.mean(1 / V[t, ok[t]])
            else:
                parts[m] = w / np.abs(w).sum() * 2 * np.mean(1 / V[t, m])
        if design == "xs_class" and np.abs(parts).sum() > 0:
            parts = parts / np.abs(parts).sum() * 2 * np.mean(1 / V[t, held])
        W[t] = parts
    empty = np.abs(W).sum(1) == 0
    W[empty] = np.nan
    return W


def portfolio(P: pd.DataFrame, signal: str, design: str, direction: int = 1, cost_bp: dict | None = None) -> pd.DataFrame:
    """Monthly returns of the portfolio, gross and net of costs. Costs per market in bp of notional per round trip:
    half on every change in weight, and a full round trip on the position for each roll in the month held."""
    cost_bp = cost_bp or {k: v[6] for k, v in MARKETS.items()}
    months, mk = np.sort(P["month"].unique()), np.sort(P["market"].unique())
    S, V, R, N = (_matrix(P, c, months, mk) for c in (signal, "vol", "next_ret", "next_rolls"))
    cls = np.array([MARKETS.get(k, ("",) * 6)[5] for k in mk])
    W = _weights_matrix(S, V, design, cls) * direction
    live = np.isfinite(W).any(1)
    W = np.where(np.isfinite(W), W, 0.0)                                 # a missing next return counts as zero, not as a position never taken
    c = np.array([cost_bp.get(k, 3.0) / 1e4 for k in mk])
    rows = {}
    prev = np.zeros(len(mk))
    for t in range(len(months)):
        if not live[t] or np.abs(W[t]).sum() == 0:
            prev = np.zeros(len(mk))
            continue
        w = W[t]
        dw = np.abs(w - prev)
        gross = float(np.nansum(w * np.nan_to_num(R[t])))
        trade = float((dw * c).sum() / 2)
        roll = float((np.abs(w) * c * np.nan_to_num(N[t])).sum())
        ge = float(np.abs(w).sum())
        # labelled by the month the return is earned
        rows[pd.Timestamp(months[t]) + pd.offsets.MonthEnd(1)] = {"gross": gross, "net": gross - trade - roll, "turnover": float(dw.sum() / ge) if ge > 0 else 0.0,
                                                                  "markets": int((w != 0).sum()), "gross_exposure": ge}
        prev = w
    return pd.DataFrame(rows).T.sort_index() if rows else pd.DataFrame(columns=["gross", "net", "turnover", "markets", "gross_exposure"])


def one_sided(e: dict) -> float | None:
    """The equal-weighted cosine test's p for a positive mean: the question asked of a signal in its published
    direction. After costs a strategy with no edge loses a little, so a two-sided test would count that loss as a
    discovery."""
    return None if e.get("t") is None or not np.isfinite(e["t"]) else float(student_t.sf(e["t"], e["df"]))


def _stats(x: pd.Series) -> dict:
    x = x.dropna()
    if len(x) < 12 or x.std(ddof=1) == 0:
        return {"months": int(len(x))}
    return {"months": int(len(x)), "sharpe": float(x.mean() / x.std(ddof=1) * math.sqrt(12)),
            "return_at_10pct_vol": float(x.mean() * 12 / (x.std(ddof=1) * math.sqrt(12)) * TARGET_VOL)}


def test_signal(P: pd.DataFrame, signal: str, design: str, bench: pd.Series) -> dict | None:
    name, direction, ref, year = SIGNALS[signal]
    pf = portfolio(P, signal, design, direction)
    x = pf["net"].dropna() if len(pf) else pd.Series(dtype=float)
    x = x[x.index >= pd.Timestamp(START)]
    if len(x) < MIN_MONTHS:
        return {"signal": signal, "design": design, "name": name, "untested": True, "months": int(len(x)),
                "why": f"only {len(x)} months with enough markets (a test needs {MIN_MONTHS})"}
    e = ewc_test(x.to_numpy(float))
    b = bench.reindex(x.index)
    ok = b.notna()
    beta = float(np.cov(x[ok], b[ok])[0, 1] / np.var(b[ok], ddof=1)) if ok.sum() > 24 and np.var(b[ok]) > 0 else 0.0
    alpha = (x - beta * b.fillna(0.0))
    ea = ewc_test(alpha.to_numpy(float))
    mid = x.index[len(x) // 2]
    halves = {"split": mid.strftime("%Y-%m"), "first": _stats(x[x.index < mid]), "second": _stats(x[x.index >= mid])}
    since = x[x.index >= pd.Timestamp(f"{year + 1}-01-01")]
    within = None
    if design == "xs":
        pc = portfolio(P, signal, "xs_class", direction)
        y = pc["net"].dropna() if len(pc) else pd.Series(dtype=float)
        y = y[y.index >= pd.Timestamp(START)]
        if len(y) >= MIN_MONTHS:
            ey = ewc_test(y.to_numpy(float))
            within = {"months": int(len(y)), "sharpe_net": float(y.mean() / y.std(ddof=1) * math.sqrt(12)), "p": one_sided(ey)}
    g = pf["gross"].reindex(x.index)
    first_m = halves["first"].get("sharpe")
    second_m = halves["second"].get("sharpe")
    return {"signal": signal, "design": design, "name": name, "reference": ref, "published": year, "direction": direction,
            "months": int(len(x)), "from": x.index[0].strftime("%Y-%m"), "to": x.index[-1].strftime("%Y-%m"),
            "markets_mean": float(pf.loc[x.index, "markets"].mean()), "turnover_monthly": float(pf.loc[x.index, "turnover"].mean()),
            "sharpe_net": float(x.mean() / x.std(ddof=1) * math.sqrt(12)), "sharpe_gross": float(g.mean() / g.std(ddof=1) * math.sqrt(12)),
            "cost_drag_sharpe": float((g.mean() - x.mean()) / x.std(ddof=1) * math.sqrt(12)),
            "t": e["t"], "df": e["df"], "p": one_sided(e), "p_two_sided": e["p"], "beta_to_long": beta, "alpha_t": ea["t"], "alpha_p": one_sided(ea),
            "alpha_sharpe": float(alpha.mean() / alpha.std(ddof=1) * math.sqrt(12)) if alpha.std(ddof=1) > 0 else None,
            "halves": halves, "same_sign_both_halves": bool(first_m is not None and second_m is not None and np.sign(first_m) == np.sign(second_m) == np.sign(x.mean())),
            "since_publication": _stats(since) | {"from": f"{year + 1}-01"}, "within_class": within,
            "curve": {"months": [d.strftime("%Y-%m") for d in x.index], "net": [float(v) for v in x]}}


def long_benchmark(P: pd.DataFrame) -> pd.Series:
    """A passive long portfolio of the same markets, each sized to equal risk: what a signal must beat."""
    out = {}
    for m, G in P.groupby("month"):
        g = G[["vol", "next_ret"]].dropna()
        g = g[g["vol"] > 0]
        if len(g) >= MIN_MARKETS_TS:
            out[m] = float((g["next_ret"] / g["vol"]).sum() / len(g))
    return pd.Series(out).sort_index()


def _bh(p: np.ndarray, q: float = FDR_Q) -> float:
    p = np.sort(np.asarray(p, float))
    m = len(p)
    ok = np.flatnonzero(p <= q * np.arange(1, m + 1) / m)
    return float(p[ok[-1]]) if len(ok) else 0.0


def fake_runs(P: pd.DataFrame, n: int, seed: int, rho: float = 0.9) -> dict:
    """Random persistent signals (AR(1) per market) through the same portfolios and the same one-sided test, on the real
    returns with each market's average return removed and before costs: an honest test puts about 5% of them below
    p = 0.05. With the averages left in, a random tilt can collect the premia some markets really paid (the bond rally),
    which is a real return, not a false alarm, so the average is removed to check the test alone."""
    rng = np.random.default_rng(seed)
    months = np.sort(P["month"].unique())
    mk = np.sort(P["market"].unique())
    mi, ki = {m: i for i, m in enumerate(months)}, {k: j for j, k in enumerate(mk)}
    rows = []
    Q = P[["month", "market", "vol", "next_ret", "next_rolls"]].copy()
    Q["next_ret"] = Q["next_ret"] - Q.groupby("market")["next_ret"].transform("mean")
    for s in range(n):
        Z = np.zeros((len(months), len(mk)))
        e = rng.normal(size=Z.shape)
        Z[0] = e[0]
        for i in range(1, len(months)):
            Z[i] = rho * Z[i - 1] + math.sqrt(1 - rho ** 2) * e[i]
        Q["_fake"] = Z[Q["month"].map(mi).to_numpy(), Q["market"].map(ki).to_numpy()]
        for d in DESIGNS:
            pf = portfolio(Q, "_fake", d)
            x = pf["gross"].dropna() if len(pf) else pd.Series(dtype=float)
            x = x[x.index >= pd.Timestamp(START)]
            if len(x) >= MIN_MONTHS:
                rows.append({"design": d, "p": one_sided(ewc_test(x.to_numpy(float)))})
    out = {"signals": n, "runs": len(rows)}
    for d in DESIGNS:
        ps = np.array([r["p"] for r in rows if r["design"] == d])
        out[d] = {"n": int(len(ps)), "share_p_below_05": float(np.mean(ps <= 0.05)) if len(ps) else None,
                  "share_p_below_01": float(np.mean(ps <= 0.01)) if len(ps) else None}
    ps = np.array([r["p"] for r in rows])
    out["share_p_below_05"] = float(np.mean(ps <= 0.05)) if len(ps) else None
    return out


# ---------------------------------------------------------------- the book's hedge
def hedge_readings(P: pd.DataFrame, frames: dict) -> dict:
    """For the Treasury and equity index futures: the latest carry and trend with their percentile in the market's
    own history; for each Treasury future, its average return in the months stocks (ES) fell most, and its
    correlation with ES by decade."""
    done = P[P["ret"].notna()]
    last = done["month"].max() if len(done) else pd.NaT                    # the last complete month: a month in progress has no full trend
    today = []
    for k in BOOK_MARKETS:
        H = P[(P["market"] == k) & (P["month"] >= pd.Timestamp(START))].sort_values("month")
        if H.empty:
            continue
        row = H[H["month"] == last]
        if row.empty:
            continue
        r = row.iloc[0]
        x = {"market": k, "name": MARKETS[k][0], "month": last.strftime("%Y-%m")}
        for s in ("carry", "trend_12", "trend_3"):
            v = r.get(s)
            x[s] = None if pd.isna(v) else float(v)
            hist = H[s].dropna()
            x[f"{s}_pct"] = None if pd.isna(v) or len(hist) < 24 else float((hist < v).mean())
        x["vol"] = None if pd.isna(r.get("vol")) else float(r["vol"])
        today.append(x)
    out = {"as_of": last.strftime("%Y-%m") if pd.notna(last) else None, "today": today, "selloffs": [], "correlation": []}
    es = P[P["market"] == "ES"].set_index("month")["ret"]
    if len(es.dropna()) >= 60:
        worst = es.dropna().nsmallest(max(10, int(len(es.dropna()) * 0.05)))
        for k in TREASURIES:
            t = P[P["market"] == k].set_index("month")["ret"]
            both = pd.concat([es, t], axis=1, keys=["es", "t"]).dropna()
            if len(both) < 60:
                continue
            w = both.loc[both.index.isin(worst.index)]
            out["selloffs"].append({"market": k, "name": MARKETS[k][0], "worst_es_months": int(len(w)), "es_mean": float(w["es"].mean()) if len(w) else None,
                                    "treasury_mean": float(w["t"].mean()) if len(w) else None,
                                    "treasury_up_share": float((w["t"] > 0).mean()) if len(w) else None})
            dec = both.groupby((both.index.year // 10) * 10)
            out["correlation"].append({"market": k, "name": MARKETS[k][0],
                                       "by_decade": {f"{d}s": float(g["es"].corr(g["t"])) for d, g in dec if len(g) >= 36},
                                       "last_36m": float(both.tail(36)["es"].corr(both.tail(36)["t"])) if len(both) >= 36 else None})
    return out


# ---------------------------------------------------------------- the whole run
VERDICTS = {"supported": "still works", "faded": "worked, but weak or gone since publication", "class_tilt": "only a bet between asset classes",
            "beta_only": "pays, but only like holding long", "one_era": "passes the cut, one era only",
            "reversed": "significant, but reversed", "chance": "no better than chance", "untested": "not testable here"}


def build(frames: dict, cot: pd.DataFrame | None = None, n_fake: int = N_FAKE, seed: int = SEED, meta: dict | None = None) -> dict:
    """Everything from data already in memory: frames {market: daily frame from parse_carver or databento_frames},
    cot (market, report_date, comm_long, comm_short) or None."""
    t0 = time.time()
    P = month_panel(frames, cot)
    P = P[P["month"] >= pd.Timestamp(START) - pd.DateOffset(years=2)]
    bench = long_benchmark(P)
    tests, untested = [], []
    for s in SIGNALS:
        if s not in P or P[s].notna().sum() == 0:
            for d in DESIGNS:
                untested.append({"signal": s, "design": d, "name": SIGNALS[s][0], "months": 0, "why": "no data for this signal in this run"})
            continue
        for d in DESIGNS:
            t = test_signal(P, s, d, bench)
            (untested if t.get("untested") else tests).append(t)
    cut = _bh(np.array([t["p"] for t in tests])) if tests else 0.0
    for t in tests:
        t["pass_bh"] = bool(cut > 0 and t["p"] <= cut)
        t["as_published"] = bool(t["sharpe_net"] > 0)
        sp = t["since_publication"]
        if not t["as_published"] and (t["p_two_sided"] or 1) <= 0.05 / max(1, len(tests)):
            v = "reversed"
        elif not t["pass_bh"]:
            v = "chance"
        elif t["alpha_p"] is None or t["alpha_p"] > 0.05:
            v = "beta_only"
        elif not t["same_sign_both_halves"]:
            v = "one_era"
        elif t["design"] == "xs" and (t["within_class"] is None or t["within_class"]["sharpe_net"] <= 0):
            v = "class_tilt"
        elif sp.get("months", 0) >= 36 and (sp.get("sharpe") is None or sp["sharpe"] < FADED_SHARPE):
            v = "faded"
        else:
            v = "supported"
        t["verdict"], t["supported"] = v, v == "supported"
    fakes = fake_runs(P, n_fake, seed + 1) if n_fake else {"signals": 0}
    months = P["month"][P["month"] >= pd.Timestamp(START)]
    cov = P[P["month"] >= pd.Timestamp(START)].groupby("market")["month"].agg(["min", "max", "count"])
    out = {"schema": 1, "built": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"), "meta": meta or {},
           "universe": {"markets": int(P["market"].nunique()), "from": months.min().strftime("%Y-%m") if len(months) else None,
                        "to": months.max().strftime("%Y-%m") if len(months) else None,
                        "by_market": {k: {"name": MARKETS.get(k, (k,))[0], "class": MARKETS.get(k, ("",) * 6)[5], "from": v["min"].strftime("%Y-%m"),
                                          "to": v["max"].strftime("%Y-%m"), "months": int(v["count"])} for k, v in cov.iterrows()},
                        "with_positioning": int(P.loc[P["hedging_pressure"].notna(), "market"].nunique()) if "hedging_pressure" in P else 0},
           "tests": tests, "untested": untested, "bh_cut": cut, "n_hypotheses": len(tests), "fakes": fakes,
           "benchmark": _stats(bench[bench.index >= pd.Timestamp(START)]) | {"curve": {"months": [d.strftime("%Y-%m") for d in bench.index if d >= pd.Timestamp(START)],
                                                                                     "net": [float(v) for d, v in bench.items() if d >= pd.Timestamp(START)]}},
           "correlations": _strategy_corr(P, tests), "book": hedge_readings(P, frames),
           "assumptions": {"start": START, "split": SPLIT, "fdr_q": FDR_Q, "min_markets_xs": MIN_MARKETS_XS, "min_markets_ts": MIN_MARKETS_TS,
                           "min_months": MIN_MONTHS, "vol_com_days": VOL_COM, "cot_lag_days": COT_LAG_DAYS, "faded_sharpe": FADED_SHARPE, "costs_bp_round_trip": {k: v[6] for k, v in MARKETS.items()}},
           "verdicts": VERDICTS, "limitations": LIMITATIONS, "timing_s": round(time.time() - t0, 1)}
    out = _clean(out)
    out["findings"] = summary(out)
    return out


def _strategy_corr(P: pd.DataFrame, tests: list) -> dict:
    cols = {f"{t['signal']}:{t['design']}": pd.Series(t["curve"]["net"], index=pd.to_datetime(t["curve"]["months"])) for t in tests}
    if len(cols) < 2:
        return {}
    C = pd.DataFrame(cols).corr()
    return {"labels": list(C.columns), "matrix": [[None if pd.isna(v) else float(v) for v in row] for row in C.to_numpy()]}


LIMITATIONS = [
    "pysystemtrade's published prices end in March 2024 and follow its own roll calendar (for crude oil and the grains it holds one contract a year); Databento's begin in 2010 and follow the most traded contract. The two are run separately, not spliced, and hold different contracts, so they are two records of the same markets, not one.",
    "Futures returns here are excess returns: they leave out the interest earned on the cash behind a futures position, which is the same for every signal and does not change the comparisons.",
    "Costs are a fixed estimate per market in basis points of notional per round trip, charged on every change in weight and on every roll; real costs vary with size, time and liquidity.",
    "Carry uses the held and the next quoted contract. A deferred price unchanged for five rows in a row is treated as stale and gives no reading; when a contract's terms change (the Treasury futures' move to a 6% notional coupon in 2000) the two contracts differ in kind, and the Treasury carry readings jump for a few months then and again in late 2014 and early 2015.",
    "A roll day on which the new contract has no previous close is left out rather than guessed; for some markets (the ultra Treasury contracts, feeder cattle, soybean meal) that is many of their rolls.",
    "The universe is today's liquid CME markets, picked with hindsight: markets that died are not in it, which flatters any signal that is long what survived. pysystemtrade's SOFR file is back-filled with Eurodollar prices before SOFR futures existed.",
    "Positioning needs the CFTC's site and runs only where it is reachable; positions as of Tuesday are used from the following Monday's close, and months when government shutdowns delayed the releases get no reading.",
    "Most of these signals were published before much of the sample, so the record before publication is the one the authors saw; the record since publication is shown on its own, and it is short (four to eleven years), so a Sharpe ratio there has a standard error of 0.3 to 0.5.",
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


def summary(o: dict) -> list[str]:
    u, T = o["universe"], o["tests"]
    out = [f"{u['markets']} futures markets, {u['from']} to {u['to']}, {o['n_hypotheses']} tests (each signal across markets and over time, net of costs), "
           f"Benjamini-Hochberg at q = {FDR_Q}: {sum(t['pass_bh'] for t in T)} passed; {sum(t['supported'] for t in T)} also beat a passive long portfolio of the "
           f"same markets, held in both halves, within asset classes and since publication."]
    fk = o.get("fakes") or {}
    if fk.get("share_p_below_05") is not None:
        out.append(f"Of {fk.get('runs')} runs of random persistent signals on the real returns (each market's average removed), {_f(fk['share_p_below_05'] * 100, 0)}% "
                   f"had p below 0.05 (about 5% is the honest rate).")
    for t in sorted(T, key=lambda t: t["p"])[:6]:
        sp = t["since_publication"]
        out.append(f"{t['name']}, {DESIGNS[t['design']]} ({t['reference']}): Sharpe {_f(t['sharpe_net'])} after costs, p {_f(t['p'], 4)}, beyond holding long "
                   f"{_f(t['alpha_sharpe'])}; since {sp.get('from', '')[:4]}: Sharpe {_f(sp.get('sharpe'))} over {sp.get('months', 0)} months. Verdict: {VERDICTS[t['verdict']]}.")
    b = o.get("book") or {}
    for s in b.get("selloffs", [])[:3]:
        out.append(f"{s['name']} in the {s['worst_es_months']} worst months for the S&P 500 (average {_f((s['es_mean'] or 0) * 100, 1)}%): "
                   f"{_f((s['treasury_mean'] or 0) * 100, 1)}% on average, up in {_f((s['treasury_up_share'] or 0) * 100, 0)}% of them.")
    return out


# ---------------------------------------------------------------- sources (network)
def carver_download(cache: str | Path, markets: list[str] | None = None) -> tuple[dict, dict]:
    """pysystemtrade's multiple prices for each market, cached on disk (raw files never enter git)."""
    from .data import http
    cache = Path(cache) / "carver"
    cache.mkdir(parents=True, exist_ok=True)
    frames, failed = {}, {}
    for k in markets or list(MARKETS):
        name = MARKETS[k][2]
        p = cache / f"{name}.csv"
        try:
            if not p.exists():
                p.write_bytes(http.get(CARVER_URL.format(name=name), timeout=120))
            frames[k] = parse_carver(p.read_text())
        except Exception as exc:  # noqa: BLE001
            failed[k] = f"{type(exc).__name__}: {str(exc)[:100]}"
    return frames, failed


def databento_frames(start: str = "2010-06-06", end: str | None = None, markets: list[str] | None = None, max_cost_usd: float = 5.0) -> tuple[dict, dict]:
    """CME Globex daily bars for each root's two most traded contracts (ROOT.v.0 and ROOT.v.1, Databento's volume
    roll) with their contract months from the definition schema, in the same daily format as parse_carver: the held
    contract is v.0, and v.1 serves as both the carry and the forward contract. Prices are Databento's, unadjusted;
    returns come from each contract's own closes. Refuses a pull estimated above max_cost_usd."""
    import databento as db
    client = db.Historical()
    roots = [MARKETS[k][1] for k in (markets or list(MARKETS)) if k not in ("GE",)]
    symbols = [f"{r}.v.{i}" for r in roots for i in (0, 1)]
    end = end or (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    cost = float(client.metadata.get_cost(dataset=DATASET, schema="ohlcv-1d", symbols=symbols, stype_in="continuous", start=start, end=end))
    cost += float(client.metadata.get_cost(dataset=DATASET, schema="definition", symbols=symbols, stype_in="continuous", start=start, end=end))
    if cost > max_cost_usd:
        raise RuntimeError(f"Databento estimates ${cost:.2f} for this pull, above the ${max_cost_usd:.2f} limit; raise max_cost_usd to proceed")
    bars = client.timeseries.get_range(dataset=DATASET, schema="ohlcv-1d", symbols=symbols, stype_in="continuous", start=start, end=end).to_df().reset_index()
    defs = client.timeseries.get_range(dataset=DATASET, schema="definition", symbols=symbols, stype_in="continuous", start=start, end=end).to_df().reset_index()
    def _day(x):
        x = pd.to_datetime(x)
        return (x.dt.tz_convert(None) if x.dt.tz is not None else x).dt.normalize()
    tcol = "ts_recv" if "ts_recv" in defs else ("ts_event" if "ts_event" in defs else defs.columns[0])
    D = pd.DataFrame({"instrument_id": defs["instrument_id"].astype("int64"), "dday": _day(defs[tcol]),
                      "m": [_yyyymm(int(y) * 100 + int(mo)) if pd.notna(y) and pd.notna(mo) else np.nan for y, mo in zip(defs["maturity_year"], defs["maturity_month"])]})
    D = D.dropna(subset=["m"]).sort_values("dday", kind="mergesort")
    bars["date"] = _day(bars["ts_event"])
    bars = bars[bars["date"].dt.dayofweek < 5].copy()
    bars["instrument_id"] = bars["instrument_id"].astype("int64")
    bars = bars.sort_values("date", kind="mergesort")
    back = pd.merge_asof(bars, D, left_on="date", right_on="dday", by="instrument_id", direction="backward")["m"].to_numpy()
    fwd = pd.merge_asof(bars, D, left_on="date", right_on="dday", by="instrument_id", direction="forward")["m"].to_numpy()
    bars["m"] = np.where(np.isfinite(back), back, fwd)                     # each bar takes the definition in force on its date
    frames, failed = {}, {"cost_usd": round(cost, 2)}
    for k in markets or list(MARKETS):
        r = MARKETS[k][1]
        a = bars[bars["symbol"] == f"{r}.v.0"].drop_duplicates("date", keep="last").set_index("date")
        b = bars[bars["symbol"] == f"{r}.v.1"].drop_duplicates("date", keep="last").set_index("date")
        if a.empty:
            failed[k] = "no bars"
            continue
        f = pd.DataFrame({"price": a["close"].astype(float), "m_price": a["m"]})
        f["carry"], f["m_carry"] = b["close"].astype(float).reindex(f.index), b["m"].reindex(f.index)
        f["forward"], f["m_forward"] = f["carry"], f["m_carry"]
        frames[k] = f.sort_index()
    return frames, failed


def cot_download(start: str = "1990-01-01", markets: list[str] | None = None) -> tuple[pd.DataFrame, dict]:
    """Commercial long and short positions per market from the CFTC's Legacy futures-only reports. Each market's
    contract code is checked against the name the CFTC gives it; a mismatch is dropped and reported."""
    from .data import http
    rows, checked = [], {}
    for k in markets or list(MARKETS):
        code, must = MARKETS[k][3], MARKETS[k][4]
        q = (f"{CFTC_URL}?$select=report_date_as_yyyy_mm_dd,market_and_exchange_names,comm_positions_long_all,comm_positions_short_all,open_interest_all"
             f"&$where=cftc_contract_market_code='{code}'%20AND%20report_date_as_yyyy_mm_dd>='{start}T00:00:00.000'&$order=report_date_as_yyyy_mm_dd&$limit=5000")
        try:
            data = json.loads(http.get(q, timeout=120, retries=2))
        except Exception as exc:  # noqa: BLE001
            checked[k] = f"failed: {type(exc).__name__}"
            continue
        if not data:
            checked[k] = "no reports"
            continue
        names = {d.get("market_and_exchange_names", "") for d in data}
        if not any(any(w in n.upper() for w in must.split("|")) for n in names):
            checked[k] = f"name check failed: {sorted(names)[:2]}"
            continue
        checked[k] = f"ok: {len(data)} reports"
        for d in data:
            rows.append({"market": k, "report_date": pd.Timestamp(d["report_date_as_yyyy_mm_dd"][:10]),
                         "comm_long": float(d.get("comm_positions_long_all") or np.nan), "comm_short": float(d.get("comm_positions_short_all") or np.nan)})
    return pd.DataFrame(rows), checked


# ---------------------------------------------------------------- validation on synthetic data
SECTOR_OF = {k: v[5] for k, v in MARKETS.items()}


def synthetic_frames(edge: float = 0.5, seed: int = 4, start: str = "1987-01-01", end: str = "2024-03-28", markets: list[str] | None = None) -> tuple[dict, pd.DataFrame]:
    """Synthetic daily multiple prices in pysystemtrade's layout, quarterly contracts rolled before expiry, for the
    engine's markets. Each market's carry is persistent (AR(1) by month, its own mean); prices move with a market
    factor, a sector factor and their own noise; and, when edge > 0, the next month's return earns `edge` times the
    month's carry (a fraction of the carry is earned, the planted edge). Weekly hedgers' positions are random."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, end)
    mk = markets or list(MARKETS)
    per = days.to_period("M")
    months = per.unique()
    nm = len(months)
    fm = rng.normal(0, 0.03, nm)
    fs = {s: rng.normal(0, 0.03, nm) for s in set(SECTOR_OF.values())}
    frames, cot = {}, []
    for k in mk:
        vol_m = {"equity": 0.045, "rates": 0.02, "currency": 0.025, "metals": 0.05, "energy": 0.08, "grains": 0.06, "livestock": 0.045}[SECTOR_OF[k]]
        mu = rng.normal(0, 0.03)
        c = np.zeros(nm)
        c[0] = mu
        for i in range(1, nm):
            c[i] = mu + 0.85 * (c[i - 1] - mu) + 0.02 * rng.normal()
        bm, bs = rng.normal(0.5, 0.2), rng.normal(0.6, 0.2)
        zf, zs = fm / 0.03, fs[SECTOR_OF[k]] / 0.03
        mret = edge * np.concatenate([[0.0], c[:-1] / 12]) + vol_m * (bm * zf + bs * zs + 0.7 * rng.normal(size=nm)) / math.sqrt(bm ** 2 + bs ** 2 + 0.49)
        idx = np.searchsorted(months, per)
        nd = pd.Series(1, index=days).groupby(per).transform("sum").to_numpy()
        z = 0.004 * rng.normal(size=len(days))
        z = z - pd.Series(z).groupby(idx).transform("mean").to_numpy()
        lr = np.log1p(mret)[idx] / nd + z
        # contracts: quarterly (Mar, Jun, Sep, Dec); the held contract rolls on the 14th of the month before delivery
        mi = np.array([d.year * 12 + d.month - 1 for d in days])
        qe = mi + (2 - mi % 3)
        late = np.array([(m % 3 == 2) or (m % 3 == 1 and d.day >= 14) for m, d in zip(mi, days)])
        held = np.where(late, qe + 3, qe)
        to_yyyymm = lambda q: float((q // 12) * 100 + q % 12 + 1)
        cd = c[idx]
        lvl = np.empty(len(days))
        lvl[0] = 100.0
        r = np.expm1(lr)
        for i in range(1, len(days)):
            prev = lvl[i - 1] if held[i] == held[i - 1] else lvl[i - 1] * math.exp(-cd[i - 1] * 3 / 12)     # the new contract's previous close
            lvl[i] = prev * (1 + r[i])
        nxt = lvl * np.exp(-cd * 3 / 12)
        f = pd.DataFrame({"price": lvl, "m_price": [to_yyyymm(h) for h in held], "carry": nxt, "m_carry": [to_yyyymm(h + 3) for h in held],
                          "forward": nxt, "m_forward": [to_yyyymm(h + 3) for h in held]}, index=days)
        frames[k] = f
        hp = 0.0
        for d in pd.date_range(start, end, freq="W-TUE"):
            hp = 0.9 * hp + 0.15 * rng.normal()
            cl = 1000 * (1 - hp)
            cot.append({"market": k, "report_date": d, "comm_long": cl, "comm_short": 1000 * (1 + hp)})
    return frames, pd.DataFrame(cot)


def validate(n_fake: int = 30) -> dict:
    """The engine end to end on synthetic_frames(): the planted carry edge should pass across markets and over time,
    and random persistent signals should land below p = 0.05 about 5% of the time."""
    frames, cot = synthetic_frames()
    o = build(frames, cot, n_fake=n_fake, meta={"synthetic": True, "planted": "carry"})
    T = {f"{t['signal']}:{t['design']}": t for t in o["tests"]}
    planted = {k: {x: T[k].get(x) for x in ("sharpe_net", "p", "pass_bh", "alpha_p", "supported", "verdict")} for k in ("carry:xs", "carry:ts") if k in T}
    out = {"planted": planted, "others": [{x: t.get(x) for x in ("signal", "design", "sharpe_net", "p", "pass_bh", "verdict")} for t in o["tests"] if t["signal"] != "carry"],
           "fakes": o["fakes"], "n_hypotheses": o["n_hypotheses"],
           "design": {"markets": len(frames), "from": "1987", "to": "2024-03", "edge": "half of each month's carry is earned the next month",
                      "factors": "a market factor and a sector factor"}}
    ok = all(v.get("pass_bh") for v in planted.values())
    out["findings"] = [f"On {len(frames)} synthetic futures markets in pysystemtrade's layout, with a market and a sector factor and half of each month's carry "
                       f"earned the next month, the engine {'found' if ok else 'did not find'} the planted carry edge: across markets Sharpe "
                       f"{_f((planted.get('carry:xs') or {}).get('sharpe_net'))} (p {_f((planted.get('carry:xs') or {}).get('p'), 4)}), over time Sharpe "
                       f"{_f((planted.get('carry:ts') or {}).get('sharpe_net'))} (p {_f((planted.get('carry:ts') or {}).get('p'), 4)}); "
                       f"{_f((o['fakes'].get('share_p_below_05') or 0) * 100, 0)}% of {o['fakes'].get('runs')} random-signal runs had p below 0.05."]
    return _clean(out)
