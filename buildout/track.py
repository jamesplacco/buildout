"""The track record (v0.38): the book's calls tested the way a portfolio manager judges an analyst.

Three records, never mixed:
  1. Backtest (in-sample). The size the Book risk desk chose using the whole history, applied to that same history.
     It shows what the rule looks like with hindsight and nothing more.
  2. Walk-forward (out-of-sample). At every month-end the size and the hedge are recomputed from data up to that
     close, frozen, and held through the next month. Costs are charged. The universe is chosen point in time.
  3. Live paper. The calls logged in the append-only ledger (buildout/ledger.py) before the next bar, marked to
     market as prices arrive. It starts on Nov 3, 2026, and it is the only record that cannot have been fitted.

The universe. Today's nine names were not the obvious nine in 2017. The walk-forward record therefore holds, each
January, the nine names with the largest trailing-year dollar volume among a fixed candidate list of US-listed AI
buildout names; the same record on today's nine names, chosen with hindsight, is shown beside it, and the gap
between them is the survivorship the hindsight version carries. The candidate list is itself chosen today, so a
company that failed and left the price mirror cannot appear: that residual bias is stated, not removed.

Costs (assumptions, stated): stocks 5 bp per dollar traded (2 bp half-spread, 3 bp slippage); Nasdaq-100 futures
1 bp per contract traded plus a quarterly roll of 1 bp of notional, and futures returns are in excess of cash, so the
short earns cash on its margin implicitly; borrowing above 1.00x costs cash plus 50 bp; the long bond is the 20-year
par bond's total return, financed from the book's cash; a short stock basket pays 30 bp a year to borrow plus 5 bp a
trade.

The hedge study. The stock-bond correlation by regime since 1962 (inflation rising or falling, from CPI; policy
tightening or easing, from the 3-month rate futures since 1984, whose price is 100 less the expected rate), and the
hedges compared on the same months: the long bond, the 2-year note, gold, index puts (modelled), cash and a short
basket of the weakest AI names. Then a hedge ratio that changes with the regime, chosen walk-forward.
"""
from __future__ import annotations

import io
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import book as bk
from . import sizing_rules
from .analytics import sizing

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "track"

CANDIDATES = ["msft", "amzn", "goog", "meta", "nvda", "avgo", "tsla", "orcl", "amd", "intc", "mu", "tsm", "mrvl", "wdc", "pltr", "spcx"]
N_NAMES = 9
START = "2018-01-01"            # one year of warm-up after the bond series starts (2017)
COST = {"stock_bp": 5.0, "fut_bp": 1.0, "roll_bp_q": 1.0, "borrow_spread": 0.005, "short_borrow": 0.003, "short_trade_bp": 5.0}
KELLY_FRACTION = 0.25
DD_STOP = 0.15                  # hard stop: from a 15% drawdown, exposure is halved until the drawdown is back inside 10%
DD_RESUME = 0.10
WEEKS = [("COVID: the first week", "2020-02-24", "2020-02-28"), ("COVID: the circuit-breaker week", "2020-03-09", "2020-03-13"),
         ("COVID: the bottom", "2020-03-16", "2020-03-20"), ("2022: the CPI shock", "2022-06-13", "2022-06-17"),
         ("2022: the September CPI", "2022-09-12", "2022-09-16"), ("2024: the yen carry unwind", "2024-08-01", "2024-08-07"),
         ("2025: the tariff week", "2025-04-03", "2025-04-09"), ("2026: the AI growth scare", "2026-10-19", "2026-10-23")]
GH = "https://raw.githubusercontent.com/datasets/{}"


# ---------------------------------------------------------------- the universe
def dollar_volume(prices: dict[str, pd.DataFrame], candidates: list[str] | None = None) -> pd.DataFrame:
    out = {}
    for t in (candidates or CANDIDATES):
        if t in prices:
            f = bk._frame(prices[t])
            out[t] = f["close"] * f["volume"]
    return pd.DataFrame(out)


def pit_members(prices: dict[str, pd.DataFrame], years: list[int], candidates: list[str] | None = None) -> dict[int, list[str]]:
    """Each January, the N_NAMES candidates with the largest average dollar volume over the trailing 252 trading days,
    among those with that much history at the decision date. Uses only data before the year starts. `candidates`
    (v0.42.6) swaps the list ranked, for the universe checks; the default is CANDIDATES."""
    dv = dollar_volume(prices, candidates)
    out = {}
    for y in years:
        hist = dv.loc[: pd.Timestamp(f"{y}-01-01") - pd.Timedelta(days=1)]
        need = min(250, max(40, int(hist.notna().sum().max()) - 5)) if len(hist) else 250   # the first year: what history exists
        ok = hist.tail(252).notna().sum() >= need
        avg = hist.tail(252).mean()[ok]
        out[y] = list(avg.sort_values(ascending=False).index[:N_NAMES])
    return out


def rebalance_turnover(R: pd.DataFrame, W: pd.DataFrame) -> pd.Series:
    """The trading a target-weight book needs, as a share of the book, booked on the day the trade is made (v0.42.5).
    W[t] is the weight held through day t. By the close of t the weights have drifted to W[t] (1 + R[t]) / (1 + r[t]);
    restoring W[t+1] trades the sum of the absolute differences, counting buys and sells. A change of membership
    is in the same number. The first day is zero: the opening build is charged where the size is set."""
    R, W = R.fillna(0.0), W.fillna(0.0)
    rp = (R * W).sum(axis=1)
    drift = (W * (1 + R)).div((1 + rp).replace(0, np.nan), axis=0)
    return (W - drift.shift(1)).abs().sum(axis=1).where(np.arange(len(W)) > 0, 0.0).rename("turnover")


def pit_book(prices: dict[str, pd.DataFrame], cal: pd.DatetimeIndex, candidates: list[str] | None = None) -> tuple[pd.Series, dict, pd.Series]:
    """Equal-weight daily returns of the point-in-time members: the membership is reset each January and the weights
    are restored to equal every day. Returns the book's return, the members, and the turnover that policy needs each
    day (the daily trades back to equal weight and each January's change of names), so the record pays for the
    rebalancing it earns from (v0.42.5; before, only the January change was counted)."""
    cands = candidates or CANDIDATES
    R = pd.DataFrame({t: bk.total_returns(prices[t]) for t in cands if t in prices}).reindex(cal)
    years = sorted({d.year for d in cal})
    mem = pit_members(prices, years, cands)
    w = pd.DataFrame(0.0, index=cal, columns=R.columns)
    for y in years:
        m = [t for t in mem[y] if t in R.columns]
        rows = w.index.year == y
        if not m:
            continue
        w.loc[rows, m] = 1.0 / len(m)
    have = R.notna()
    wt = (w * have)
    wt = wt.div(wt.sum(axis=1).replace(0, np.nan), axis=0)
    r = (R.fillna(0.0) * wt).sum(axis=1, min_count=1)
    return r.rename("pit"), mem, rebalance_turnover(R, wt)


def book_turnover(R: pd.DataFrame, w: pd.Series) -> pd.Series:
    """The same count for book.book_returns: fixed target weights, restored daily (v0.42.5)."""
    w = w.reindex(R.columns).fillna(0.0)
    have = R.notna()
    wt = have.mul(w, axis=1)
    wt = wt.mul(w.sum() / wt.sum(axis=1).replace(0, np.nan), axis=0)
    return rebalance_turnover(R, wt)


# ---------------------------------------------------------------- walk-forward sizing
_DD_CACHE: dict = {}


def dd_size(mu: float, sigma: float, rf: float) -> float:
    """The largest size whose 95th-percentile one-year drawdown stays inside MAX_DD, memoised on a 0.5% vol grid."""
    key = (round(sigma * 200) / 200, round(mu, 3), round(rf, 3))
    if key not in _DD_CACHE:
        _DD_CACHE[key] = sizing.max_leverage(key[1], max(key[0], 0.01), bk.MAX_DD, cash_rate=key[2], hi=3.0)
    return _DD_CACHE[key]


def limits_at(r: pd.Series, q: pd.Series, t: pd.Timestamp, rf: float) -> dict:
    """The book's three limits computed from data through the close of t only."""
    x = r.loc[:t].dropna()
    qq = q.reindex(x.index)
    vol = float(x.tail(63).std() * math.sqrt(252))
    lam = bk.ewma_vol(x).iloc[-1] * math.sqrt(252) if len(x) > 30 else vol
    sig = max(vol, float(lam))
    h21 = bk.horizon_returns(x)
    sig_m = sig / math.sqrt(12)                                    # the Student-t tail is scaled to the one-month sigma
    es_hist = bk.es(h21, 0.05) if len(h21) > 100 else bk.t_es(sig_m, 0.05)
    es_now = max(es_hist * sig / max(float(x.std() * math.sqrt(252)), 1e-6), bk.t_es(sig_m, 0.05))
    beta = float(np.cov(x.tail(252), qq.tail(252))[0, 1] / max(np.var(qq.tail(252)), 1e-12))
    mu = rf + bk.EQUITY_PREMIUM * beta
    s = {"es": bk.ES_BUDGET / es_now if es_now > 0 else bk.MAX_GROSS, "vol": bk.VOL_TARGET / sig, "dd": dd_size(mu, sig, rf), "gross": bk.MAX_GROSS}
    k = min(s, key=s.get)
    return {"sizes": s, "size": min(1.0, float(s[k])), "binding": k, "sigma": sig, "es": es_now, "beta": beta, "mu": mu}


def short_to_meet(r: pd.Series, q: pd.Series, t: pd.Timestamp, rf: float, gross: float = 1.0) -> float:
    """At full size, the smallest Nasdaq-100 short (step 5% of NAV) that brings trailing two-year volatility and
    one-month 95% ES inside the limits. Trailing data only."""
    x = r.loc[:t].tail(504).dropna()
    qq = q.reindex(x.index).fillna(0.0)
    for h in np.round(np.arange(0.0, 1.21, 0.05), 2):
        y = gross * x - h * qq
        sig = float(y.std() * math.sqrt(252))
        e = max(bk.es(bk.horizon_returns(y), 0.05) if len(y) > 100 else 0.0, bk.t_es(sig / math.sqrt(12), 0.05))
        if sig <= bk.VOL_TARGET and e <= bk.ES_BUDGET:
            return float(h)
    return 1.2


def month_ends(idx: pd.DatetimeIndex, start: str = START) -> list[pd.Timestamp]:
    s = pd.Series(idx, index=idx)
    me = s.groupby(idx.to_period("M")).last()
    return [d for d in me if d >= pd.Timestamp(start) - pd.offsets.MonthEnd(1)]


def _next_vm(vm: pd.Series, t: pd.Timestamp) -> float | None:
    """The volatility-managed exposure for the month after t (exposure_path already sets it at t's close). Taking the
    value held during t's own month and then holding it a further month, as before v0.39.1, lagged the rule twice."""
    nxt = vm[vm.index > t]
    return None if not len(nxt) or pd.isna(nxt.iloc[0]) else float(nxt.iloc[0])


# ---------------------------------------------------------------- v0.40: the live rule, walked forward
_LR: dict = {}


def _lr_init(prices, ust):
    _LR["prices"], _LR["ust"] = prices, ust


def _lr_one(job):
    t, members = job
    P, U = _LR["prices"], _LR["ust"]
    pp = {k: v[v.iloc[:, 0].astype(str) <= t] for k, v in P.items()}
    book = {m.upper(): 1.0 / len(members) for m in members}
    try:
        o = bk.build(pp, U.loc[:t], book)
        k = o.get("keep_names_hedge") or {}
        # v0.42.5: the short the ledger would have logged that day (the menu's full-size row, the smallest 5% step
        # inside every limit), so the record tests the decision that is recorded; the exact minimum rides along
        fr = [r for r in (o.get("frontier") or []) if r.get("meets")]
        exact = float(k.get("short_nasdaq_frac") or 0.0)
        short = float(fr[-1]["short"]) if fr and abs(fr[-1]["gross"] - 1) < 1e-9 else exact
        return {"date": t, "size": float(o["size"]), "binding": o["binding"], "short": short, "short_exact": exact,
                "asof": o["asof"], "ok": True}
    except Exception as exc:                              # noqa: BLE001 - the month falls back to the simple limits, counted
        return {"date": t, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}


def live_rule_path(prices: dict, ust: pd.DataFrame, members: dict, month_ends: list, workers: int | None = None) -> pd.DataFrame:
    """The live call's own rule (book.build: factor-model volatility, the three expected-shortfall methods, the drawdown
    simulation, the gross cap) run at each month-end on the data to that close, for that year's point-in-time names
    equally weighted. Before v0.40 the walk-forward used a simpler stand-in (realized volatility and one tail model),
    so the record tested a cousin of the rule that trades; now it tests the rule itself."""
    import os
    from concurrent.futures import ProcessPoolExecutor
    jobs = [(str(t.date()), members[t.year]) for t in month_ends if members.get(t.year)]
    n = workers or max(1, min(4, os.cpu_count() or 1))
    if n == 1:
        _lr_init(prices, ust)
        out = [_lr_one(j) for j in jobs]
    else:
        with ProcessPoolExecutor(n, initializer=_lr_init, initargs=(prices, ust)) as ex:
            out = list(ex.map(_lr_one, jobs, chunksize=4))
    D = pd.DataFrame(out)
    D.index = pd.to_datetime(D["date"])
    return D


def walk_forward(r: pd.Series, qx: pd.Series, bond: pd.Series, cash: pd.Series, turn_names: pd.Series | None = None,
                 rule: pd.DataFrame | None = None, rl_rule: pd.DataFrame | None = None) -> dict:
    """Monthly decisions frozen at each month-end close; daily returns with and without costs for each policy.
    r: the book's daily return; qx: QQQ in excess of cash (the futures leg); bond: 20-year par bond total return.
    rule: the live rule's size and short at each month-end (live_rule_path); without it, the simple limits stand in.
    rl_rule: v0.41, the deep RL sizer's exposure at each month-end (deeprl.book_rule); adds the policy call_rl."""
    idx = r.dropna().index
    mes = month_ends(idx)
    rf_ann = (cash.reindex(idx).fillna(0.0) * 252).rolling(21, min_periods=1).mean()
    rows, dec = [], []
    stop_on = False
    peak, level = 1.0, 1.0
    vm = sizing_rules.exposure_path(r.dropna(), sizing_rules.HEADLINE)
    for i, t in enumerate(mes[:-1]):
        rf = float(rf_ann.loc[t])
        L = limits_at(r, qx + cash.reindex(qx.index).fillna(0), t, rf)
        h = short_to_meet(r, qx + cash.reindex(qx.index).fillna(0), t, rf)
        kelly = max(0.0, (L["mu"] - rf) / max(L["sigma"] ** 2, 1e-6)) * KELLY_FRACTION
        vt = bk.VOL_TARGET / L["sigma"]
        product = min(vt, kelly, bk.MAX_GROSS)
        lr = rule.loc[t] if rule is not None and t in rule.index and bool(rule.loc[t].get("ok")) else None
        dec.append({"date": str(t.date()), "size": float(lr["size"]) if lr is not None else L["size"], "binding": lr["binding"] if lr is not None else L["binding"],
                    "short": float(lr["short"]) if lr is not None else h, "rule": "live" if lr is not None else "simple",
                    "size_simple": L["size"], "short_simple": h, "sigma": L["sigma"], "es": L["es"],
                    "vol_target": vt, "kelly": kelly, "product": product, "vm_rule": _next_vm(vm, t),
                    "es_size": L["sizes"]["es"], "dd_size": L["sizes"]["dd"]})
    D = pd.DataFrame(dec).set_index(pd.to_datetime([d["date"] for d in dec]))
    if rl_rule is not None:
        Drl = rl_rule.reindex(D.index)
        okm = Drl["ok"].fillna(False).astype(bool)
        D["size_rl"] = Drl["size"].where(okm, D["size"])          # a month the sizer could not see falls back to the call, and is counted
        D["rl_ok"] = okm.to_numpy()
    # hold each decision through the next month
    held = D.reindex(idx, method="ffill").shift(1)
    held = held.loc[held.index > D.index[0]]          # v0.40: from the first day a decision is held (the decision day itself held none)
    x = r.reindex(held.index).fillna(0.0)
    q = qx.reindex(held.index).fillna(0.0)
    b = bond.reindex(held.index).fillna(0.0)
    c = cash.reindex(held.index).fillna(0.0)
    tn = (turn_names.reindex(held.index).fillna(0.0) if turn_names is not None else 0.0)

    def run(gross: pd.Series, short: pd.Series | float = 0.0, bondw: pd.Series | float = 0.0, stop: bool = False) -> tuple[pd.Series, pd.Series, dict]:
        gross = gross if isinstance(gross, pd.Series) else pd.Series(gross, index=held.index)
        short = short if isinstance(short, pd.Series) else pd.Series(short, index=held.index)
        bondw = bondw if isinstance(bondw, pd.Series) else pd.Series(bondw, index=held.index)
        g = gross.copy()
        if stop:                                       # path-dependent: needs the running drawdown day by day
            lvl, pk, on, gv = 1.0, 1.0, False, []
            for d in held.index:
                gi = gross[d] * (0.5 if on else 1.0)
                ret = gi * x[d] + (1 - gi) * c[d] - max(gi - 1, 0) * COST["borrow_spread"] / 252
                lvl *= 1 + ret; pk = max(pk, lvl); dd = 1 - lvl / pk
                on = (dd >= DD_STOP) or (on and dd > DD_RESUME)
                gv.append(gi)
            g = pd.Series(gv, index=held.index)
        fin = (1 - g - bondw) * c - (g + bondw - 1).clip(lower=0) * COST["borrow_spread"] / 252
        gross_ret = g * x + fin + bondw * b - short * q
        # costs
        # v0.42.5: holding the names at g of NAV is itself a trade each day, because the names and the rest of the
        # account do not move together; the size held into today is yesterday's g carried by yesterday's returns
        nav1 = (1 + gross_ret).shift(1)
        dg = (g - g.shift(1) * (1 + x.shift(1)) / nav1).abs().fillna(g.iloc[0])
        stock_cost = (dg + g * tn) * COST["stock_bp"] / 1e4
        ds = (short - short.shift(1) * (1 + q.shift(1) + c.shift(1)) / nav1).abs().fillna(short.iloc[0])
        q_end = pd.Series(held.index.month.isin([3, 6, 9, 12]) & (pd.Series(held.index.day, index=held.index) >= 15) & (pd.Series(held.index.to_period("M"), index=held.index) != pd.Series(held.index.to_period("M"), index=held.index).shift(-1)), index=held.index)
        fut_cost = ds * COST["fut_bp"] / 1e4 + short * q_end.astype(float) * COST["roll_bp_q"] / 1e4
        db = bondw.diff().abs().fillna(bondw.iloc[0])
        bond_cost = db * 2.0 / 1e4
        net = gross_ret - stock_cost - fut_cost - bond_cost
        turnover = float((dg.sum() + (g * tn).sum()) / max(len(held) / 252, 1e-9))
        return gross_ret, net, {"turnover_yr": turnover, "avg_gross": float(g.mean()), "avg_short": float(short.mean())}

    pol = {}
    pol["hold"] = run(pd.Series(1.0, index=held.index))
    pol["call"] = run(held["size"])
    pol["call_short"] = run(pd.Series(1.0, index=held.index), short=held["short"])
    if rule is not None:                                  # the stand-in rule, kept beside the live one so the change is visible
        pol["call_simple"] = run(held["size_simple"])
    if rl_rule is not None:
        pol["call_rl"] = run(held["size_rl"])
    pol["bond30"] = run(pd.Series(1.0, index=held.index), bondw=bk.STATIC_BOND)
    pol["product"] = run(held["product"].clip(upper=bk.MAX_GROSS), stop=True)
    pol["vm_rule"] = run(held["vm_rule"].fillna(1.0).clip(0, sizing_rules.HEADLINE["cap"]))
    bench = qx.reindex(held.index).fillna(0.0) + c
    return {"decisions": D, "held": held, "policies": pol, "bench": bench, "cash": c, "factors_ret": {"market": q + c, "rates": b}}


# ---------------------------------------------------------------- statistics
def stats(x: pd.Series, cash: pd.Series, turnover: float | None = None, F: pd.DataFrame | None = None) -> dict:
    x = x.dropna()
    if len(x) < 20:
        return {"days": int(len(x))}
    lv = (1 + x).cumprod()
    yrs = len(x) / 252
    m = (1 + x).resample("ME").prod() - 1
    ex = x - cash.reindex(x.index).fillna(0.0)
    out = {"from": str(x.index[0].date()), "to": str(x.index[-1].date()), "days": int(len(x)),
           "cagr": float(lv.iloc[-1] ** (1 / yrs) - 1), "vol": float(x.std() * math.sqrt(252)),
           "sharpe": float(ex.mean() / x.std() * math.sqrt(252)) if x.std() > 0 else None,
           "maxdd": float(1 - (lv / lv.cummax()).min()), "hit_month": float((m > 0).mean()), "months": int(len(m)),
           "best_month": float(m.max()), "worst_month": float(m.min()), "y2022": float((1 + x.loc["2022"]).prod() - 1) if (x.index.year == 2022).any() else None,
           "turnover_yr": turnover}
    if F is not None:
        Z = F.reindex(x.index).fillna(0.0)
        A = np.column_stack([np.ones(len(Z)), Z.to_numpy()])
        coef = np.linalg.lstsq(A, x.to_numpy(), rcond=None)[0]
        out["exposure"] = {k: float(v) for k, v in zip(Z.columns, coef[1:])}
    return out


def monthly_table(x: pd.Series) -> dict:
    m = (1 + x.dropna()).resample("ME").prod() - 1
    return {str(d.date())[:7]: float(v) for d, v in m.items()}


# ---------------------------------------------------------------- the hedge study
def _gh(path: str) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (path.replace("/", "_"))
    if not f.exists():
        from .data import http
        f.write_bytes(http.get(GH.format(path), timeout=60))
    return pd.read_csv(f)


def monthly_history() -> pd.DataFrame:
    """Shiller's S&P Composite with dividends, CPI and the 10-year yield, monthly. Bond returns from the 10-year yield:
    carry plus the price change of a 10-year par bond.

    Shiller's file pads its last months with zeros for the dividend, CPI and yield (they end in 2023 while the price
    runs on): zeros are treated as missing, CPI and the 10-year yield are filled from the datasets' own CPI and
    10-year series, and the dividend from the last known dividend yield. A zero is never read as a value."""
    d = _gh("s-and-p-500/main/data/data.csv")
    d["Date"] = pd.to_datetime(d["Date"])
    d = d.set_index("Date").sort_index()
    for c in ("Dividend", "Consumer Price Index", "Long Interest Rate"):
        d[c] = d[c].where(d[c] > 0)
    try:
        cpi2 = _gh("cpi-us/main/data/cpiai.csv")
        cpi2 = cpi2.set_index(pd.to_datetime(cpi2["Date"]))["Index"]
        y2 = _gh("bond-yields-us-10y/main/data/monthly.csv")
        y2 = y2.set_index(pd.to_datetime(y2[y2.columns[0]]))[y2.columns[1]]
        d["Consumer Price Index"] = d["Consumer Price Index"].fillna(cpi2.reindex(d.index))
        d["Long Interest Rate"] = d["Long Interest Rate"].fillna(y2.reindex(d.index))
    except Exception:  # noqa: BLE001 - offline: the history ends where Shiller's does
        pass
    p = d["SP500"]
    dy = (d["Dividend"] / p).ffill()
    dv = d["Dividend"].fillna(dy * p)
    y = d["Long Interest Rate"] / 100
    stock = (p + dv / 12) / p.shift(1) - 1
    dur = (1 - (1 + y / 2) ** -20) / (y / 2) / 2 / (1 + y / 2)          # modified duration of a 10-year par bond
    bond = y.shift(1) / 12 - dur.shift(1) * y.diff()
    cpi = d["Consumer Price Index"]
    infl = cpi / cpi.shift(12) - 1
    return pd.DataFrame({"stock": stock, "bond": bond, "infl": infl, "y10": y}).dropna()


def policy_proxy(frames: dict) -> pd.Series:
    """Expected 3-month rate from the 3-month rate futures held (100 less price), month-end; the change over six
    months above +0.25 points is tightening, below -0.25 easing, else on hold. A proxy for the Fed's direction."""
    f = frames["SR3"]
    rate = (100 - f["price"]).resample("ME").last()
    ch = rate.diff(6)
    return pd.Series(np.where(ch > 0.25, "tightening", np.where(ch < -0.25, "easing", "on hold")), index=ch.index).where(ch.notna())


def regime_table(H: pd.DataFrame, pol: pd.Series | None, start: str = "1962-01-01") -> dict:
    """Stock-bond correlation and the bond's hedge value by regime, monthly."""
    X = H.loc[start:].copy()
    X["infl_dir"] = np.where(X["infl"] > X["infl"].shift(12), "rising", "falling")
    X["infl_lvl"] = np.where(X["infl"] > 0.03, "above 3%", "below 3%")
    if pol is not None:
        X["policy"] = pol.reindex(X.index, method="ffill")
    rows = []

    def one(name: str, mask: pd.Series) -> None:
        g = X[mask]
        if len(g) < 24:
            return
        c = float(g["stock"].corr(g["bond"]))
        h = -float(np.cov(g["stock"], g["bond"])[0, 1] / np.var(g["bond"]))      # min-variance bond weight per $1 of stock
        v0 = float(g["stock"].var())
        cut_min = 1 - float((g["stock"] + max(h, 0) * g["bond"]).var()) / v0
        cut_30 = 1 - float((g["stock"] + 0.3 * g["bond"]).var()) / v0
        sell = g[g["stock"] < -0.05]
        rows.append({"regime": name, "months": int(len(g)), "corr": c, "minvar_weight": h, "var_cut_minvar": cut_min, "var_cut_30": cut_30,
                     "bond_in_selloffs": float(sell["bond"].mean()) if len(sell) else None, "selloffs": int(len(sell))})

    one("All months", pd.Series(True, index=X.index))
    for col in ("infl_dir", "infl_lvl") + (("policy",) if pol is not None else ()):
        for v in sorted(X[col].dropna().unique()):
            one(f"{ {'infl_dir': 'Inflation', 'infl_lvl': 'Inflation', 'policy': 'Policy'}[col]} {v}", X[col] == v)
    if pol is not None:
        for a in ("rising", "falling"):
            for b in ("tightening", "easing", "on hold"):
                one(f"Inflation {a}, policy {b}", (X["infl_dir"] == a) & (X["policy"] == b))
    last = str(X.index[-1].year)
    for y0, y1 in (("1962", "1999"), ("2000", "2020"), ("2021", last)):
        one(f"{y0} to {y1}", pd.Series((X.index.year >= int(y0)) & (X.index.year <= int(y1)), index=X.index))
    return {"from": str(X.index[0].date())[:7], "to": str(X.index[-1].date())[:7], "rows": rows}


def put_returns(q_excess: pd.Series, vol_index: pd.Series, k: float = 0.90, scale: float = 1.25) -> pd.Series:
    """A one-month 90%-strike put on the Nasdaq-100, bought at each month-end close and held to the next month-end,
    as a return per $1 of index hedged. Strike and premium are set at the purchase close: the strike is 90% of that
    close and the implied vol is that day's VIX x 1.25 (an assumption for the Nasdaq-100's premium over the S&P
    500), priced by Black-Scholes. The payoff comes from the index's move over the month that follows, so nothing
    that happened before the purchase can pay the put (v0.42.5: before, the premium used the month's first close
    and the payoff the whole month, which paid the put for a fall into its own purchase). Modelled, not traded: no
    skew, no bid-ask, no listed expiry."""
    from scipy.stats import norm
    m = (1 + q_excess.dropna()).resample("ME").prod() - 1
    v = (vol_index.resample("ME").last().shift(1) / 100 * scale).reindex(m.index)
    T = 1 / 12
    d1 = (np.log(1 / k) + 0.5 * v ** 2 * T) / (v * np.sqrt(T))
    d2 = d1 - v * np.sqrt(T)
    prem = k * norm.cdf(-d2) - norm.cdf(-d1)
    payoff = (k - (1 + m)).clip(lower=0)
    return (payoff - prem).dropna().rename("put")


def alternatives(frames: dict, H: pd.DataFrame, vix: pd.Series, pol: pd.Series) -> dict:
    """Monthly, since 2000 (the Nasdaq-100 future's record): each hedge's return in the Nasdaq-100's down months, its
    correlation, and the variance it removes at its min-variance weight, overall and by regime."""
    from . import futures as fu
    ret = {k: (1 + fu.front_returns(frames[k]).dropna()).resample("ME").prod() - 1 for k in ("NQ", "ZT", "ZN", "UB", "ZB", "GC")}
    M = pd.DataFrame(ret).dropna(subset=["NQ", "ZT", "ZN", "GC"])
    M["long_bond"] = M["UB"].fillna(M["ZB"])
    M["put"] = put_returns(fu.front_returns(frames["NQ"]), vix).reindex(M.index)
    M["cash"] = 0.0
    M = M.drop(columns=["UB", "ZB"])
    infl = H["infl"].resample("ME").last()
    M["infl_dir"] = np.where(infl.reindex(M.index) > infl.shift(12).reindex(M.index), "rising", "falling")
    M["policy"] = pol.reindex(M.index, method="ffill")
    hedges = {"long_bond": "Long Treasury bond (ZB/UB)", "ZN": "10-year note", "ZT": "2-year note", "GC": "Gold", "put": "Nasdaq-100 put, 1 month, 90% (modelled)", "cash": "Cash (cut size)"}
    out = []
    for name, g in [("All months since 2000", M), ("Inflation rising", M[M["infl_dir"] == "rising"]), ("Inflation falling", M[M["infl_dir"] == "falling"]),
                    ("Policy tightening", M[M["policy"] == "tightening"]), ("Policy easing", M[M["policy"] == "easing"]), ("2022", M.loc["2022"])]:
        if len(g) < 8:
            continue
        row = {"regime": name, "months": int(len(g)), "nq": float(g["NQ"].mean()), "h": {}}
        down = g[g["NQ"] < -0.03]
        for k in hedges:
            if k == "cash":
                row["h"][k] = {"corr": 0.0, "down": 0.0, "var_cut": None}
                continue
            s = g[k].dropna()
            nq = g["NQ"].reindex(s.index)
            v = float(np.var(s)) if len(s) > 2 else 0.0
            w = -float(np.cov(nq, s)[0, 1] / v) if v > 0 else 0.0
            w = max(w, 0.0)
            cut = 1 - float((nq + w * s).var()) / float(nq.var()) if w > 0 else 0.0
            row["h"][k] = {"corr": float(nq.corr(s)), "down": float(down[k].mean()) if len(down) else None, "var_cut": cut, "weight": w}
        row["down_months"] = int(len(down))
        out.append(row)
    return {"labels": hedges, "rows": out, "from": str(M.index[0].date())[:7], "to": str(M.index[-1].date())[:7]}


def weak_basket(prices: dict[str, pd.DataFrame], cal: pd.DatetimeIndex) -> pd.Series:
    """A short basket of the three weakest candidates by trailing 12-month return (skipping the last month), rebalanced
    monthly, as the return of the short per $1 (negative of the basket, less borrow)."""
    R = pd.DataFrame({t: bk.total_returns(prices[t]) for t in CANDIDATES if t in prices}).reindex(cal)
    lv = (1 + R.fillna(0)).cumprod().where(R.notna().cumsum() > 0)
    mom = lv.shift(21) / lv.shift(252) - 1
    me = month_ends(cal, "2018-01-01")
    w = pd.DataFrame(0.0, index=cal, columns=R.columns)
    for a, b in zip(me[:-1], me[1:]):
        m = mom.loc[a].dropna().sort_values()
        pick = list(m.index[:3])
        w.loc[(w.index > a) & (w.index <= b), pick] = 1 / 3
    basket = (R.fillna(0) * w).sum(axis=1)
    return (-basket - COST["short_borrow"] / 252).loc[me[0]:].rename("short_weak")


def regime_hedge_walk(r: pd.Series, bond: pd.Series, H: pd.DataFrame, pol: pd.Series, cash: pd.Series) -> dict:
    """A bond hedge ratio that changes with the regime, walked forward: each month-end, the regime (inflation
    direction, policy direction) is read, and the min-variance bond weight is estimated from the past months of the
    long record in that same regime only (the stock-bond relation of the S&P since 1962, a monthly record that ends
    before the decision). Negative weights are floored at zero. Applied to the book's next month."""
    X = H.copy()
    X["infl_dir"] = np.where(X["infl"] > X["infl"].shift(12), "rising", "falling")
    X["policy"] = pol.reindex(X.index, method="ffill")
    rm = (1 + r.dropna()).resample("ME").prod() - 1
    bm = (1 + bond.reindex(r.dropna().index).fillna(0)).resample("ME").prod() - 1
    cm = (1 + cash.reindex(r.dropna().index).fillna(0)).resample("ME").prod() - 1
    rows = []
    for t in rm.index[12:]:
        past = X[X.index < t - pd.offsets.MonthBegin(1)]
        if not len(past):
            continue
        last = past.iloc[-1]
        same = past[(past["infl_dir"] == last["infl_dir"]) & (past["policy"] == last["policy"])]
        if len(same) >= 24:
            w = max(0.0, -float(np.cov(same["stock"], same["bond"])[0, 1] / np.var(same["bond"])))
        else:
            w = 0.0
        w = min(w, 1.0)
        rows.append({"month": str(t.date())[:7], "regime": f"inflation {last['infl_dir']}, {last['policy']}", "weight": w,
                     "book": float(rm[t]), "hedged": float(rm[t] + w * (bm[t] - cm[t])), "static30": float(rm[t] + 0.3 * (bm[t] - cm[t]))})
    D = pd.DataFrame(rows)
    if D.empty:
        return {"rows": []}
    s = lambda col: {"vol": float(D[col].std() * math.sqrt(12)), "worst": float(D[col].min()),
                     "maxdd": float(1 - ((1 + D[col]).cumprod() / (1 + D[col]).cumprod().cummax()).min()), "mean_ann": float(D[col].mean() * 12),
                     "y2022": float((1 + D[D["month"].str.startswith("2022")][col]).prod() - 1)}
    return {"rows": rows, "summary": {"book": s("book"), "regime_switching": s("hedged"), "static30": s("static30")},
            "avg_weight": float(D["weight"].mean()), "share_off": float((D["weight"] == 0).mean())}


# ---------------------------------------------------------------- the weeks
def weeks(pol: dict, bench: pd.Series) -> list[dict]:
    out = []
    for name, a, b in WEEKS:
        days = bench.loc[a:b].index
        if not len(days):
            continue
        row = {"week": name, "from": a, "to": b, "days": [str(d.date()) for d in days], "policies": {}}
        for k, (gross, net, meta) in pol.items():
            x = net.reindex(days).fillna(0.0)
            row["policies"][k] = {"daily": [float(v) for v in x], "week": float((1 + x).prod() - 1)}
        row["policies"]["qqq"] = {"daily": [float(v) for v in bench.reindex(days).fillna(0)], "week": float((1 + bench.reindex(days).fillna(0)).prod() - 1)}
        out.append(row)
    return out


# ---------------------------------------------------------------- build
POLICY_NAME = {"hold": "The book at 1.00x, unhedged", "call": "The call: the live rule's size", "call_short": "Full size, the live rule's Nasdaq-100 short",
               "call_simple": "The simple limits (the stand-in before v0.40)", "call_rl": "The deep RL sizer (v0.41), unhedged",
               "bond30": "Full size, long bond 30% (the old TLT rule)", "product": "Vol target, quarter Kelly, drawdown stop", "vm_rule": "Volatility-managed rule (Moreira and Muir)"}


def build(prices: dict[str, pd.DataFrame], ust: pd.DataFrame, frames: dict | None = None, ledger_rows: list | None = None, rl_nets: dict | None = None) -> dict:
    """rl_nets (v0.41): deeprl.build()["nets"], the sizer trained through each year; adds the call_rl policy to the
    point-in-time record and out["deeprl_book"]."""
    P = bk.panel(prices, ust)
    cal = P["R"].index
    cash, bond = P["cash"], P["bond"]
    qx = P["E"]["QQQ"] - cash
    w = pd.Series(bk.BOOK)
    hind = bk.book_returns(P["R"], w)
    pit, members, turn = pit_book(prices, cal)
    F = pd.DataFrame({"market": P["F"]["market"], "semis": P["F"]["semis"], "rates": P["F"]["rates"]})
    out = {"members": {str(y): [t.upper().replace("GOOG", "GOOGL") for t in m] for y, m in members.items() if y >= 2018}, "policy_name": POLICY_NAME, "cost": COST}
    recs = {}
    for name, r, tn in (("pit", pit, turn), ("hindsight", hind, book_turnover(P["R"], w))):
        rule = None
        if name == "pit" and os.environ.get("BUILDOUT_SIMPLE_RULE") != "1":
            rule = live_rule_path(prices, ust, members, [t for t in month_ends(r.dropna().index)[:-1] if t >= pd.Timestamp(START)])
            out["live_rule"] = {"months": int(len(rule)), "fallbacks": int((~rule["ok"].astype(bool)).sum()),
                                "errors": rule.loc[~rule["ok"].astype(bool), "error"].dropna().head(3).tolist() if "error" in rule else []}
        rl_rule = None
        if name == "pit" and rl_nets:
            from . import deeprl, labs
            rl_rule = deeprl.book_rule(rl_nets, r, labs.shiller(labs.download()), [t for t in month_ends(r.dropna().index)[:-1] if t >= pd.Timestamp(START)])
            out["deeprl_book"] = {"months": int(rl_rule["ok"].astype(bool).sum()), "fallbacks": int((~rl_rule["ok"].astype(bool)).sum()),
                                  "avg_exposure": float(rl_rule.loc[rl_rule["ok"].astype(bool), "action"].mean()), "time_out": float((rl_rule.loc[rl_rule["ok"].astype(bool), "action"] == 0).mean()),
                                  "path": [[str(d.date()), float(v)] for d, v in rl_rule.loc[rl_rule["ok"].astype(bool), "size"].items()]}
        W = walk_forward(r, qx, bond, cash, tn, rule, rl_rule)
        pol = W["policies"]
        recs[name] = W
        out[name] = {"policies": {k: {"gross": stats(g, W["cash"], None, F), "net": stats(n, W["cash"], m["turnover_yr"], F), "meta": m,
                                      "monthly": monthly_table(n)} for k, (g, n, m) in pol.items()},
                     "bench": stats(W["bench"], W["cash"]),
                     "decisions": [{**{k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in d.items()}} for d in W["decisions"].reset_index(drop=True).to_dict("records")],
                     "curve": {k: [[str(d.date()), float(v)] for d, v in ((1 + n).cumprod()).resample("W").last().items()] for k, (g, n, m) in pol.items()} | {"qqq": [[str(d.date()), float(v)] for d, v in (1 + W["bench"]).cumprod().resample("W").last().items()]}}
    out["weeks"] = weeks(recs["pit"]["policies"], recs["pit"]["bench"])
    # in-sample backtest: the full-history size, applied to the same history
    full = bk.build(prices, ust)
    size_is = float(full["size"])
    is_ret = size_is * hind.loc[START:] + (1 - size_is) * cash.reindex(hind.loc[START:].index).fillna(0)
    out["backtest"] = {"size": size_is, "binding": full["binding"], "stats": stats(is_ret, cash), "note": "Sized with the whole history's tail, then applied to that history: hindsight on both the names and the size."}
    out["survivorship"] = {"hindsight_hold_cagr": out["hindsight"]["policies"]["hold"]["net"]["cagr"], "pit_hold_cagr": out["pit"]["policies"]["hold"]["net"]["cagr"],
                           "gap_cagr": out["hindsight"]["policies"]["hold"]["net"]["cagr"] - out["pit"]["policies"]["hold"]["net"]["cagr"]}
    # the hedge study
    try:
        Hm = monthly_history()
        pol = policy_proxy(frames) if frames else None
        out["regimes"] = regime_table(Hm, pol)
        if frames:
            vix = _gh("finance-vix/main/data/vix-daily.csv")
            vix["DATE"] = pd.to_datetime(vix["DATE"])
            vx = vix.set_index("DATE")["CLOSE"].astype(float)
            out["alternatives"] = alternatives(frames, Hm, vx, pol)
            out["regime_walk"] = regime_hedge_walk(pit, bond, Hm, pol, cash)
            try:                                               # v0.39: VIX as a hedge (needs the VIX futures record)
                from . import vixhedge
                out["vix"] = vixhedge.build(frames, pit, cash, Hm, pol, vix=vx)
            except Exception as exc:                           # noqa: BLE001
                out["vix_error"] = f"{type(exc).__name__}: {exc}"[:200]
        wb = weak_basket(prices, cal)
        rm = (1 + pit.loc[wb.index]).resample("ME").prod() - 1
        wm = (1 + wb).resample("ME").prod() - 1
        bm = (1 + bond.loc[wb.index]).resample("ME").prod() - 1
        down = rm < -0.05
        out["book_hedges"] = {"from": str(wb.index[0].date())[:7], "to": str(wb.index[-1].date())[:7], "down_months": int(down.sum()),
                              "short_weak": {"corr": float(rm.corr(wm)), "down": float(wm[down].mean()), "mean_ann": float(wm.mean() * 12)},
                              "long_bond": {"corr": float(rm.corr(bm)), "down": float(bm[down].mean()), "mean_ann": float(bm.mean() * 12)}}
    except Exception as exc:                                   # the long-history pieces need public data; the record does not
        out["hedge_study_error"] = f"{type(exc).__name__}: {exc}"[:200]
    # leverage against realized vol, for the sizing page
    D = recs["pit"]["decisions"]
    out["sizing_path"] = [{"date": str(d.date()), "sigma": float(r["sigma"]), "vol_target": float(min(r["vol_target"], bk.MAX_GROSS)), "kelly": float(min(r["kelly"], bk.MAX_GROSS)),
                           "product": float(r["product"]), "es_size": float(min(r["es_size"], bk.MAX_GROSS)), "dd_size": float(min(r["dd_size"], bk.MAX_GROSS)), "size": float(r["size"])} for d, r in D.iterrows()]
    out["asof"] = str(cal[-1].date())
    out["live"] = live_record(ledger_rows or [], prices, ust)
    return out


def live_record(rows: list, prices: dict, ust: pd.DataFrame) -> dict:
    """The ledger's calls marked to market, day by day: each call held from its effective date until the next call
    takes over (two effective the same day: the newer governs). Two variants, as the call offers them: the book at the
    call's size with the rest in cash, and the book at 1.00x with the call's Nasdaq-100 short. Costs: 5 bp of every
    trade in the names (each change in size, and from v0.42.5 the daily trades that hold the target weights and the
    target size); 1 bp of each change in the short. Written daily to site/data/live.json (buildout live)."""
    if not rows:
        return {"calls": 0, "marked_days": 0, "note": "No call logged yet."}
    P = bk.panel(prices, ust)
    rb = bk.book_returns(P["R"], pd.Series(bk.BOOK))
    first = pd.Timestamp(rows[0]["effective_from"])
    x = rb[rb.index >= first].dropna()
    base = {"calls": len(rows), "first_call": rows[0]["ts_utc"], "first_effective": rows[0]["effective_from"]}
    if not len(x):
        return {**base, "marked_days": 0, "note": "Calls logged; no price after the first call's effective date yet."}
    def path(key):
        s = pd.Series([float(key(r)) for r in rows], index=[pd.Timestamp(r["effective_from"]) for r in rows])
        return s.groupby(level=0).last().reindex(x.index, method="ffill")
    size = path(lambda r: r["call"]["size"])
    short = path(lambda r: (r["call"].get("menu_high") or {}).get("short") or 0.0)
    cash = P["cash"].reindex(x.index).fillna(0.0)
    qx = (P["E"]["QQQ"].reindex(x.index) - cash).fillna(0.0)
    tn = book_turnover(P["R"], pd.Series(bk.BOOK)).reindex(x.index).fillna(0.0)      # v0.42.5: the daily trades back to the target weights
    g_unh = size * x + (1 - size) * cash
    d_size = (size - size.shift(1) * (1 + x.shift(1)) / (1 + g_unh).shift(1)).abs().fillna(size.iloc[0])
    unh = g_unh - (d_size + size * tn) * COST["stock_bp"] / 1e4
    g_hed = x - short * qx
    nav1 = (1 + g_hed).shift(1)
    d_one = (1 - (1 + x.shift(1)) / nav1).abs().fillna(1.0)
    d_short = (short - short.shift(1) * (1 + qx.shift(1) + cash.shift(1)) / nav1).abs().fillna(short.iloc[0])
    hed = g_hed - d_short * COST["fut_bp"] / 1e4 - (d_one + tn) * COST["stock_bp"] / 1e4
    nav = lambda r: (1 + r).cumprod()
    q_tot = float((1 + P["E"]["QQQ"].reindex(x.index).fillna(0.0)).prod() - 1)
    return {**base, "marked_days": int(len(x)), "last_mark": str(x.index[-1].date()),
            "total": float(nav(unh).iloc[-1] - 1), "total_hedged": float(nav(hed).iloc[-1] - 1), "book_total": float(nav(x).iloc[-1] - 1), "qqq_total": q_tot,
            "series": [[str(d.date()), round(float(a), 6), round(float(b), 6), round(float(c), 6), round(float(s_), 4)]
                       for d, a, b, c, s_ in zip(x.index, nav(unh), nav(hed), nav(x), size)],
            "stats": stats(unh, cash) if len(unh) >= 20 else None}


# ---------------------------------------------------------------- the universe checks (v0.42.6)
FREEZE = "2017-12-29"            # the last session before the record's first decision year
BASKETS = {"qqq": ("The Nasdaq-100 (QQQ)", "the index the book is hedged with: every large Nasdaq name, winners and losers, at index weights"),
           "soxx": ("Semiconductors (SOXX)", "a semiconductor index fund listed in 2001: the hardware side of the buildout as an index committee defined it"),
           "robo": ("Robotics and AI (ROBO)", "the first robotics and AI theme fund, listed in 2013: what an AI theme could be bought as in 2017")}


def frozen_candidates(prices: dict[str, pd.DataFrame], freeze: str = FREEZE, need: int = 250) -> list[str]:
    """The candidates that already had `need` trading days of prices at `freeze`: the list as it could have been
    written then. Names listed later (Palantir in 2020, SpaceX in 2026) can never enter."""
    cut = pd.Timestamp(freeze)
    return [t for t in CANDIDATES if t in prices and int((bk._frame(prices[t]).index <= cut).sum()) >= need]


def vs_index(r: pd.Series, qx: pd.Series, cash: pd.Series) -> dict:
    """What a Nasdaq-100 short leaves: the universe's excess return regressed on the index's, over the record's own
    span. beta is the short that removes the index; alpha is the yearly return left after it. A short of the index
    keeps a return only where alpha is positive. The t statistic treats days as independent."""
    x = (r - cash.reindex(r.index).fillna(0.0)).dropna()
    x = x[x.index > month_ends(x.index)[0]]
    q = qx.reindex(x.index).fillna(0.0)
    beta = float(np.cov(x, q)[0, 1] / q.var())
    res = x - beta * q
    sd = float(res.std())
    return {"beta": beta, "alpha_ann": float(res.mean() * 252), "alpha_t": float(res.mean() / (sd / math.sqrt(len(res)))) if sd > 1e-9 else None,
            "resid_vol": sd * math.sqrt(252), "r2": float(1 - res.var() / x.var()) if x.var() > 0 else None}


def universe_returns(prices: dict[str, pd.DataFrame], ust: pd.DataFrame) -> dict:
    """Each universe's daily return, its turnover and its members: the inputs universe_checks sizes and charges."""
    P = bk.panel(prices, ust)
    cal = P["R"].index
    fz = frozen_candidates(prices)
    c = P["cash"]
    first = None
    out = {"P": P, "frozen": fz, "rows": {}}
    r, m, tn = pit_book(prices, cal)
    out["rows"]["pit"] = (r, tn, m)
    rf, mf, tf = pit_book(prices, cal, fz)
    out["rows"]["frozen"] = (rf, tf, mf)
    first = month_ends(rf.dropna().index)[0]                    # the walk-forward's own span: from the day after its first decision
    hold = lambda r_, tn_: stats((r_ - tn_.reindex(r_.index).fillna(0.0) * COST["stock_bp"] / 1e4).loc[lambda x: x.index > first], c, None)
    hb = hold(rf, tf)
    loo = []
    for t in fz:
        r1, _, t1 = pit_book(prices, cal, [x for x in fz if x != t])
        h1 = hold(r1, t1)
        loo.append({"without": t.upper().replace("GOOG", "GOOGL"), "cagr": h1["cagr"], "sharpe": h1["sharpe"], "maxdd": h1["maxdd"],
                    "d_cagr": h1["cagr"] - hb["cagr"], "d_sharpe": h1["sharpe"] - hb["sharpe"]})
    loo.sort(key=lambda x: x["d_cagr"])
    out["leave_one_out"], out["hold_frozen"] = loo, {k: hb[k] for k in ("cagr", "sharpe", "maxdd", "from", "to")}
    top = loo[0]["without"].lower().replace("googl", "goog")
    out["top"] = top
    out["rows"]["ex_top"] = pit_book(prices, cal, [x for x in fz if x != top])
    out["rows"]["ex_top"] = (out["rows"]["ex_top"][0], out["rows"]["ex_top"][2], out["rows"]["ex_top"][1])
    years = sorted({d.year for d in cal})
    for f in BASKETS:
        if f in prices:
            out["rows"][f] = (bk.total_returns(prices[f]).reindex(cal), pd.Series(0.0, index=cal), {y: [f] for y in years})
    return out


def _universe_row(key: str, label: str, what: str, r: pd.Series, tn, members: dict, prices: dict, ust: pd.DataFrame, P: dict, rule: bool, workers: int | None) -> dict:
    cash, bond = P["cash"], P["bond"]
    qx = P["E"]["QQQ"] - cash
    lr = None
    if rule:
        lr = live_rule_path(prices, ust, members, [t for t in month_ends(r.dropna().index)[:-1] if t >= pd.Timestamp(START)], workers)
    W = walk_forward(r, qx, bond, cash, tn, lr)
    row = {"key": key, "label": label, "what": what, "rule": "live" if rule else "simple",
           "fallbacks": int((~lr["ok"].astype(bool)).sum()) if lr is not None else None, "months": int(len(lr)) if lr is not None else None,
           "policies": {k: {**{f: v for f, v in stats(W["policies"][k][1], W["cash"], W["policies"][k][2]["turnover_yr"]).items() if f in ("from", "to", "cagr", "vol", "sharpe", "maxdd", "y2022", "turnover_yr")},
                            "avg_gross": W["policies"][k][2]["avg_gross"], "avg_short": W["policies"][k][2]["avg_short"]} for k in ("hold", "call", "call_short")}}
    h, c = row["policies"]["hold"], row["policies"]["call"]
    row["rule_effect"] = {"sharpe": c["sharpe"] - h["sharpe"], "maxdd": c["maxdd"] - h["maxdd"], "cagr": c["cagr"] - h["cagr"],
                          "sharpe_short": row["policies"]["call_short"]["sharpe"] - h["sharpe"], "maxdd_short": row["policies"]["call_short"]["maxdd"] - h["maxdd"]}
    return row


def universe_checks(prices: dict[str, pd.DataFrame], ust: pd.DataFrame, rule: bool = True, workers: int | None = None, only: list[str] | None = None) -> dict:
    """How much of the record is owed to knowing, in 2026, which names to put on the candidate list (v0.42.6).

    The walk-forward record ranks sixteen candidates each January on data to that date, but the sixteen were chosen
    in 2026. Nothing here can add a company that failed and left the data: no source this build can reach carries
    delisted names, so a broad historical universe is still not tested. What can be tested, with the same sizing
    rule, the same costs and the same dates:

      pit        the record as published: sixteen candidates, the nine most traded each January
      frozen     the candidates that already had a year of prices at the end of 2017; later listings never enter
      ex_top     the frozen list without the one name whose removal costs holding the most (found from the data)
      baskets    funds that existed before 2018 and whose members someone else chose: the Nasdaq-100, a semiconductor
                 index fund, the first robotics and AI theme fund. Their returns carry their own losers, so there is
                 no selection by this engine at all; the sizing rule is the only thing under test.

    And, for holding only (no rule to run): the frozen list with each name left out in turn, which shows how much
    of the level rests on any one pick. Each row carries what the rule changed against holding the same universe."""
    X = universe_returns(prices, ust)
    P, fz = X["P"], X["frozen"]
    cal = P["R"].index
    qx = P["E"]["QQQ"] - P["cash"]
    nm = lambda t: t.upper().replace("GOOG", "GOOGL")
    out = {"freeze": FREEZE, "candidates": [nm(t) for t in CANDIDATES], "frozen": [nm(t) for t in fz],
           "listed_later": [t.upper() for t in CANDIDATES if t in prices and t not in fz], "rows": [], "leave_one_out": X["leave_one_out"],
           "hold_frozen": X["hold_frozen"], "top_name": nm(X["top"]), "cost": COST}
    up = lambda m: {str(y): [nm(t) for t in v] for y, v in m.items() if y >= 2018}
    text = {"pit": ("The record as published", f"{len(CANDIDATES)} candidates chosen in 2026; the nine most traded each January"),
            "frozen": (f"Candidates frozen at the end of 2017 ({len(fz)} names)", "only names with a year of prices then; nothing listed later can enter"),
            "ex_top": (f"The frozen list without {out['top_name']}", "the one name whose removal costs holding the most, taken out for every year"),
            **BASKETS}
    for key, (r, tn, m) in X["rows"].items():
        if only is not None and key not in only:
            continue
        row = _universe_row(key, text[key][0], text[key][1], r, tn, m, prices, ust, P, rule, workers)
        row["vs_index"] = vs_index(r, qx, P["cash"])
        row.update({"basket": True} if key in BASKETS else {"members": up(m)})
        out["rows"].append(row)
    out["asof"] = str(cal[-1].date())
    return out


def synthetic_check(seed: int = 38) -> dict:
    """The walk-forward machinery on fake data where the answer is known: returns with a volatility jump halfway; the
    limits must cut size after the jump (and only after it), and no decision may depend on data after its date."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-04", periods=1800)
    sig = np.where(np.arange(1800) < 900, 0.012, 0.03)
    r = pd.Series(rng.normal(0.0003, 1, 1800) * sig, index=idx)
    q = r * 0.8 + pd.Series(rng.normal(0, 0.004, 1800), index=idx)
    cash = pd.Series(0.0001, index=idx)
    bond = pd.Series(rng.normal(0.0001, 0.006, 1800), index=idx)
    W = walk_forward(r, q - cash, bond, cash)
    D = W["decisions"]
    pre, post = D[D.index < idx[900]]["size"].mean(), D[D.index > idx[960]]["size"].mean()
    r2 = r.copy(); r2.iloc[1500:] *= 5                                       # change the future only
    W2 = walk_forward(r2, q - cash, bond, cash)
    same = np.allclose(W["decisions"]["size"].loc[:idx[1490]], W2["decisions"]["size"].loc[:idx[1490]])
    return {"size_before_jump": float(pre), "size_after_jump": float(post), "cuts_after_jump": bool(post < pre * 0.7), "no_lookahead": bool(same)}
