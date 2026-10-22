"""The atlas: the brain grown from 6 measured series to every monthly series the engine can read, with its structure
learned from the data instead of drawn by hand.

    python -m buildout atlas --out site/data          # writes atlas.json (GitHub mirrors; FRED where reachable)

Data. Equities (S&P 500 price, earnings and dividends, Shiller), consumer prices, the 10-year yield, Brent, WTI, Henry
Hub gas, gold, the VIX, 19 currencies against the dollar (Fed H.10), and 43 primary commodities (IMF). Each becomes a
monthly change (log change for prices, difference for yields), standardized by its own history and winsorized at 6
robust standard deviations so one broken print cannot set a link. The free IMF mirror stops in June 2017; where FRED
is reachable (the daily Action) the same commodities and about 30 macro series (credit spreads, the curve, jobs,
activity, money, housing, breakevens, real yields, bitcoin) come in current, and the atlas grows with them.

Structure, in five steps, each chosen to be robust rather than clever:
  skeleton      the graphical lasso (Friedman, Hastie and Tibshirani 2008) on the pairwise-complete correlation
                matrix (series have different spans), projected to the nearest positive definite matrix; the penalty is
                chosen by the extended BIC (Foygel and Drton 2010, gamma = 0.5), which favours sparse graphs when the
                number of series is large against the months
  stability     stability selection (Meinshausen and Buhlmann 2010): 60 half-samples of months; an edge is kept if it
                is selected in at least 70% of them. The expected number of false edges is bounded by
                q^2 / ((2 pi - 1) P), q the average edges per half-sample, P the candidate pairs
  direction     each kept edge is oriented by the pairwise likelihood ratio of Hyvarinen and Smith (2013) (in a linear
                model with non-Gaussian shocks, the cause is the variable whose regression residual looks more
                independent of it), then one global causal order is found greedily from the net evidence, so the
                contemporaneous graph is acyclic; we report how many edges agree with their own pairwise evidence
  weights       each series is regressed on its parents (same month) and on its neighbours' and its own previous month:
                y_t = B y_t + A y_t-1 + e_t, a structural VAR identified by the learned order (VAR-LiNGAM, Hyvarinen
                et al. 2010). Lagged links are kept at |t| >= 2.5 (Newey-West)
  dynamics      impulse responses Phi_0 = (I - B)^-1, Phi_h = (Phi_0 A)^h Phi_0; connectedness (Diebold and Yilmaz
                2012) from the forecast-error variance decomposition at 12 months, exact because the structural shocks
                are orthogonal; and a rolling 5-year connectedness index (generalized FEVD, Pesaran and Shin 1998, so
                it does not depend on any ordering) on the series with current data
Then: communities by modularity (Newman's leading eigenvector), importance by PageRank and by total effect, a
deterministic force-directed layout, 2022 regime flips, an out-of-sample test of the lagged links, and the
robustness value of every link to an unseen common cause. The core map's judged nodes (Hormuz, the Fed, AI capex,
the holdings and the book) join the learned graph by their judged links, so one brain carries both.
"""
from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .data import http

ASSETS = Path(__file__).resolve().parent / "assets"
RAW = "https://raw.githubusercontent.com/datasets/{}"
START = "1990-01-01"
MIN_PAIR = 60          # months of overlap needed to measure a pair
WINSOR = 6.0
PI_THR = 0.70          # a link is kept ("likely") if selected in 70% of half-samples at the EBIC penalty
PI_EST = 0.90          # "established": selected in 90% at the stricter penalty that bounds false links
FDR_TARGET = 0.10      # the stricter penalty is the loosest whose false-link bound is at most 10% of what it keeps
N_SUB = 60
LAG_T = 2.5
PAR_T = 2.0            # a same-month parent stays only if its own |t| (Newey-West) is at least 2 given the others
H = 12

GH = {
    "shiller": "s-and-p-500/main/data/data.csv", "cpi": "cpi-us/main/data/cpiai.csv", "y10": "bond-yields-us-10y/main/data/monthly.csv",
    "brent": "oil-prices/main/data/brent-monthly.csv", "wti": "oil-prices/main/data/wti-monthly.csv", "gas": "natural-gas/main/data/monthly.csv",
    "gold": "gold-prices/main/data/monthly.csv", "vix": "finance-vix/main/data/vix-daily.csv", "fx": "exchange-rates/main/data/monthly.csv",
    "imf": "commodity-prices/main/data/commodity-prices.csv",
}


@dataclass(frozen=True)
class Series:
    id: str
    name: str
    short: str
    family: str
    gh: tuple | None          # (dataset key, column or country)
    fred: str | None
    tf: str = "dlog"          # dlog | diff


FX = [("aud", "Australia", "Australian dollar"), ("brl", "Brazil", "Brazilian real"), ("cad", "Canada", "Canadian dollar"),
      ("cny", "China", "Chinese yuan"), ("eur", "Euro", "Euro"), ("inr", "India", "Indian rupee"), ("jpy", "Japan", "Japanese yen"),
      ("myr", "Malaysia", "Malaysian ringgit"), ("mxn", "Mexico", "Mexican peso"), ("nzd", "New Zealand", "New Zealand dollar"),
      ("nok", "Norway", "Norwegian krone"), ("sgd", "Singapore", "Singapore dollar"), ("zar", "South Africa", "South African rand"),
      ("krw", "South Korea", "Korean won"), ("sek", "Sweden", "Swedish krona"), ("chf", "Switzerland", "Swiss franc"),
      ("twd", "Taiwan", "Taiwan dollar"), ("thb", "Thailand", "Thai baht"), ("gbp", "United Kingdom", "British pound")]
FX_FAMILY = {"aud": "Commodity FX", "cad": "Commodity FX", "nzd": "Commodity FX", "nok": "Commodity FX", "zar": "Commodity FX", "brl": "Commodity FX",
             "mxn": "Commodity FX", "eur": "European FX", "gbp": "European FX", "chf": "European FX", "sek": "European FX",
             "cny": "Asian FX", "inr": "Asian FX", "jpy": "Asian FX", "myr": "Asian FX", "sgd": "Asian FX", "krw": "Asian FX", "twd": "Asian FX", "thb": "Asian FX"}
# (id, IMF column, short name, family, FRED id)
COMMOD = [
    ("aluminum", "Aluminum", "Aluminum", "Metals", "PALUMUSDM"), ("copper", "Copper", "Copper", "Metals", "PCOPPUSDM"),
    ("nickel", "Nickel", "Nickel", "Metals", "PNICKUSDM"), ("zinc", "Zinc", "Zinc", "Metals", "PZINCUSDM"), ("lead", "Lead", "Lead", "Metals", "PLEADUSDM"),
    ("tin", "Tin", "Tin", "Metals", "PTINUSDM"), ("ironore", "China import Iron Ore Fines 62% FE spot", "Iron ore", "Metals", "PIORECRUSDM"),
    ("uranium", "Uranium", "Uranium", "Energy", "PURANUSDM"), ("coal", "Coal", "Coal", "Energy", "PCOALAUUSDM"),
    ("gas_eu", "Natural Gas - Russian Natural Gas border price in Germany", "EU gas", "Energy", "PNGASEUUSDM"),
    ("lng_jp", "Natural Gas - Indonesian Liquefied Natural Gas in Japan", "Japan LNG", "Energy", "PNGASJPUSDM"),
    ("wheat", "Wheat", "Wheat", "Grains", "PWHEAMTUSDM"), ("maize", "Maize corn", "Corn", "Grains", "PMAIZMTUSDM"), ("barley", "Barley", "Barley", "Grains", "PBARLUSDM"),
    ("rice", "Rice", "Rice", "Grains", "PRICENPQUSDM"), ("soybeans", "Soybeans", "Soybeans", "Oilseeds", "PSOYBUSDM"), ("soymeal", "Soybean Meal", "Soy meal", "Oilseeds", "PSMEAUSDM"),
    ("soyoil", "Soybean Oil", "Soy oil", "Oilseeds", "PSOILUSDM"), ("palmoil", "Palm oil", "Palm oil", "Oilseeds", "PPOILUSDM"),
    ("rapeseed", "Rapeseed oil", "Rapeseed oil", "Oilseeds", "PROILUSDM"), ("sunflower", "Sunflower oil", "Sunflower oil", "Oilseeds", "PSUNOUSDM"),
    ("olive", "Olive Oil", "Olive oil", "Oilseeds", "POLVOILUSDM"), ("peanuts", "Groundnuts peanuts", "Peanuts", "Oilseeds", "PGNUTSUSDM"),
    ("sugar", "Sugar Free Market", "Sugar", "Softs", "PSUGAISAUSDM"), ("arabica", "Coffee Other Mild Arabicas", "Arabica", "Softs", "PCOFFOTMUSDM"),
    ("robusta", "Coffee Robusta", "Robusta", "Softs", "PCOFFROBUSDM"), ("cocoa", "Cocoa beans", "Cocoa", "Softs", "PCOCOUSDM"), ("tea", "Tea", "Tea", "Softs", "PTEAUSDM"),
    ("cotton", "Cotton", "Cotton", "Raw materials", "PCOTTINDUSDM"), ("rubber", "Rubber", "Rubber", "Raw materials", "PRUBBUSDM"),
    ("wool", "Wool fine", "Wool", "Raw materials", "PWOOLFUSDM"), ("hides", "Hides", "Hides", "Raw materials", "PHIDEUSDM"),
    ("logs", "Soft Logs", "Logs", "Raw materials", "PLOGSKUSDM"), ("sawnwood", "Hard Sawnwood", "Sawnwood", "Raw materials", "PSAWMALUSDM"),
    ("beef", "Beef", "Beef", "Livestock and food", "PBEEFUSDM"), ("pork", "Swine - pork", "Pork", "Livestock and food", "PPORKUSDM"),
    ("poultry", "Poultry chicken", "Poultry", "Livestock and food", "PPOULTUSDM"), ("lamb", "Lamb", "Lamb", "Livestock and food", "PLAMBUSDM"),
    ("salmon", "Fish salmon", "Salmon", "Livestock and food", "PSALMUSDM"), ("shrimp", "Shrimp", "Shrimp", "Livestock and food", "PSHRIUSDM"),
    ("fishmeal", "Fishmeal", "Fishmeal", "Livestock and food", "PFSHMEALUSDM"), ("bananas", "Bananas", "Bananas", "Livestock and food", "PBANSOPUSDM"),
    ("oranges", "Oranges", "Oranges", "Livestock and food", "PORANGUSDM"),
]
# FRED only (the daily Action): the macro system around the markets
MACRO = [
    ("y2", "2-year Treasury yield", "2-year", "Rates", "GS2", "diff"), ("y3m", "3-month Treasury bill", "3-month", "Rates", "TB3MS", "diff"),
    ("ff", "Fed funds rate", "Fed funds", "Rates", "FEDFUNDS", "diff"), ("mort", "30-year mortgage rate", "Mortgage", "Rates", "MORTGAGE30US", "diff"),
    ("real10", "10-year real yield (TIPS)", "Real yield", "Rates", "DFII10", "diff"), ("be10", "10-year breakeven inflation", "Breakeven", "Inflation", "T10YIE", "diff"),
    ("corecpi", "Core CPI", "Core CPI", "Inflation", "CPILFESL", "dlog"), ("ppi", "Producer prices", "PPI", "Inflation", "PPIACO", "dlog"),
    ("corepce", "Core PCE prices", "Core PCE", "Inflation", "PCEPILFE", "dlog"), ("hy", "High-yield spread", "HY spread", "Credit", "BAMLH0A0HYM2", "diff"),
    ("ig", "Investment-grade spread", "IG spread", "Credit", "BAMLC0A0CM", "diff"), ("baa", "Baa corporate yield", "Baa", "Credit", "BAA", "diff"),
    ("nfci", "Chicago Fed financial conditions", "NFCI", "Credit", "NFCI", "diff"), ("unrate", "Unemployment rate", "Unemployment", "Activity", "UNRATE", "diff"),
    ("payrolls", "Nonfarm payrolls", "Payrolls", "Activity", "PAYEMS", "dlog"), ("indpro", "Industrial production", "Ind. production", "Activity", "INDPRO", "dlog"),
    ("retail", "Retail sales", "Retail sales", "Activity", "RSAFS", "dlog"), ("claims", "Initial jobless claims", "Claims", "Activity", "ICSA", "dlog"),
    ("sentiment", "Consumer sentiment (Michigan)", "Sentiment", "Activity", "UMCSENT", "diff"), ("houst", "Housing starts", "Housing starts", "Housing", "HOUST", "dlog"),
    ("caseshiller", "Home prices (Case-Shiller)", "Home prices", "Housing", "CSUSHPINSA", "dlog"), ("m2", "M2 money supply", "M2", "Money", "M2SL", "dlog"),
    ("fedbs", "Fed balance sheet", "Fed assets", "Money", "WALCL", "dlog"), ("loans", "Bank C&I loans", "C&I loans", "Money", "BUSLOANS", "dlog"),
    ("nasdaq", "Nasdaq Composite", "Nasdaq", "Equities", "NASDAQCOM", "dlog"), ("usd", "Broad dollar index", "Dollar index", "Dollar", "DTWEXBGS", "dlog"),
    ("btc", "Bitcoin (Coinbase)", "Bitcoin", "Crypto", "CBBTCUSD", "dlog"), ("dgorder", "Durable goods orders", "Durables", "Activity", "DGORDER", "dlog"),
    ("capu", "Capacity utilization", "Capacity use", "Activity", "TCU", "diff"), ("oilprod", "US crude production", "US crude output", "Energy", "IPG211111CN", "dlog"),
]


def catalog() -> list[Series]:
    out = [
        Series("sp500", "S&P 500 (Shiller)", "S&P 500", "Equities", ("shiller", "SP500"), None),
        Series("sp_eps", "S&P 500 earnings (Shiller)", "Earnings", "Equities", ("shiller", "Earnings"), None),
        Series("sp_div", "S&P 500 dividends (Shiller)", "Dividends", "Equities", ("shiller", "Dividend"), None),
        Series("cpi", "Consumer prices (CPI-U)", "CPI", "Inflation", ("cpi", "Index"), "CPIAUCSL"),
        Series("y10", "10-year Treasury yield", "10-year", "Rates", ("y10", "Rate"), "GS10", "diff"),
        Series("brent", "Brent crude", "Brent", "Energy", ("brent", "Price"), "POILBREUSDM"),
        Series("wti", "WTI crude", "WTI", "Energy", ("wti", "Price"), "MCOILWTICO"),
        Series("natgas", "Henry Hub natural gas", "US gas", "Energy", ("gas", "Price"), "MHHNGSP"),
        Series("gold", "Gold", "Gold", "Metals", ("gold", "Price"), None),
        Series("vix", "VIX", "VIX", "Volatility", ("vix", "CLOSE"), "VIXCLS"),
    ]
    out += [Series(i, n + " (per US dollar, inverted)", i.upper(), FX_FAMILY[i], ("fx", c), None) for i, c, n in FX]
    out += [Series(i, s + " (IMF)", s, f, ("imf", col), fr) for i, col, s, f, fr in COMMOD]
    out += [Series(i, n, s, f, None, fr, tf) for i, n, s, f, fr, tf in MACRO]
    return out


# ---------------------------------------------------------------- data
def _month(idx) -> pd.DatetimeIndex:
    return pd.to_datetime(idx).to_period("M").to_timestamp()


def _monthly(s: pd.Series, how: str = "mean") -> pd.Series:
    s = s.dropna()
    s.index = _month(s.index)
    return (s.groupby(level=0).mean() if how == "mean" else s.groupby(level=0).last()).sort_index()


def download(fred: bool = True) -> dict:
    """Raw frames from the GitHub mirrors, plus FRED series where reachable. Returns {key: DataFrame}, failures."""
    raw, failed = {}, {}
    for k, path in GH.items():
        try:
            raw[k] = pd.read_csv(io.BytesIO(http.get(RAW.format(path), user_agent="buildout-atlas")))
        except Exception as exc:                    # one source down never stops the rest
            failed[k] = str(exc)[:160]
    raw["fred"] = {}
    if fred:
        from .data.fred_source import FRED_CSV, parse_fred_csv
        for s in catalog():
            if not s.fred:
                continue
            try:
                raw["fred"][s.fred] = parse_fred_csv(http.get(FRED_CSV.format(sid=s.fred), retries=1, timeout=20).decode(), s.fred)
            except Exception as exc:
                failed[s.fred] = str(exc)[:120]
                if len(failed) > 8 and not raw["fred"]:   # FRED unreachable: stop asking
                    break
    return {"raw": raw, "failed": failed}


def _gh_series(raw: dict, s: Series) -> pd.Series | None:
    key, col = s.gh
    d = raw.get(key)
    if d is None:
        return None
    if key == "shiller":
        v = d.set_index(pd.to_datetime(d["Date"]))[col]
        return _monthly(v.where(v > 0), "last")
    if key == "fx":
        v = d[d["Country"] == col]
        return _monthly(pd.Series(v["Exchange rate"].to_numpy(float), index=pd.to_datetime(v["Date"])), "last")
    if key == "imf":
        return _monthly(pd.Series(pd.to_numeric(d[col], errors="coerce").to_numpy(), index=pd.to_datetime(d["Date"])), "last")
    if key == "vix":
        dc = "DATE" if "DATE" in d.columns else "Date"
        return _monthly(pd.Series(d[col].to_numpy(float), index=pd.to_datetime(d[dc])), "mean")
    dc = "Month" if "Month" in d.columns else "Date"
    dates = d[dc].astype(str).str.slice(0, 7) + "-01"
    return _monthly(pd.Series(pd.to_numeric(d[col], errors="coerce").to_numpy(), index=pd.to_datetime(dates)), "last")


def panel(dl: dict) -> tuple[pd.DataFrame, dict]:
    """Monthly changes for every series that has at least ten years since 1990. FRED where current, else GitHub."""
    raw, cols, meta = dl["raw"], {}, {}
    for s in catalog():
        lvl, src = None, None
        fr = raw.get("fred", {}).get(s.fred) if s.fred else None
        if fr is not None and len(fr) > 24:
            lvl, src = _monthly(fr, "mean" if s.id in ("vix", "claims", "nfci", "mort", "hy", "ig", "real10", "be10") else "last"), "FRED " + s.fred
        if lvl is None and s.gh:
            g = _gh_series(raw, s)
            if g is not None and len(g.dropna()) > 24:
                lvl, src = g, "GitHub datasets/" + GH[s.gh[0]].split("/")[0]
        if lvl is None:
            continue
        lvl = lvl.dropna()
        if s.tf == "dlog":
            lvl = lvl[lvl > 0]
            ch = np.log(lvl).diff()
        else:
            ch = lvl.diff()
        # a gap in the data is not a one-month move
        gaps = lvl.index.to_series().diff().dt.days > 40
        ch[gaps] = np.nan
        if s.gh and s.gh[0] == "fx":
            ch = -ch                                # units per dollar: a rise is a weaker currency; flip so up = stronger
        ch = ch.loc[START:]
        if ch.notna().sum() < 120:
            continue
        cols[s.id] = ch
        meta[s.id] = {"name": s.name, "short": s.short, "family": s.family, "source": src, "tf": s.tf,
                      "from": ch.first_valid_index().strftime("%Y-%m"), "to": ch.last_valid_index().strftime("%Y-%m")}
    P = pd.DataFrame(cols).sort_index()
    return P, meta


def standardize(P: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """z-scores by each series' own history, winsorized at WINSOR robust standard deviations."""
    Z, clipped = {}, {}
    for c in P:
        x = P[c]
        med = x.median()
        mad = 1.4826 * (x - med).abs().median() or x.std()
        lo, hi = med - WINSOR * mad, med + WINSOR * mad
        clipped[c] = int(((x < lo) | (x > hi)).sum())
        x = x.clip(lo, hi)
        Z[c] = (x - x.mean()) / x.std()
    return pd.DataFrame(Z), clipped


# ---------------------------------------------------------------- skeleton
def pairwise_corr(Z: np.ndarray, min_n: int = MIN_PAIR) -> tuple[np.ndarray, np.ndarray]:
    """Correlations on each pair's common months (NaN-aware); pairs with fewer than min_n months get 0."""
    M = ~np.isnan(Z)
    X = np.where(M, Z, 0.0)
    N = M.T.astype(float) @ M.astype(float)
    S = X.T @ X
    S1 = X.T @ M.astype(float)                                  # sum of x_i over months where j observed
    S2 = (X * X).T @ M.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        mi, mj = S1 / N, S1.T / N
        vi, vj = S2 / N - mi ** 2, S2.T / N - mj ** 2
        C = (S / N - mi * mj) / np.sqrt(vi * vj)
    C[(N < min_n) | ~np.isfinite(C)] = 0.0
    np.fill_diagonal(C, 1.0)
    return C, N


def nearest_pd(C: np.ndarray, floor: float = 1e-3, shrink: float = 0.05) -> np.ndarray:
    """Eigenvalue clipping then a little shrinkage toward the identity, renormalized to a correlation matrix."""
    w, V = np.linalg.eigh((C + C.T) / 2)
    R = (V * np.maximum(w, floor)) @ V.T
    d = np.sqrt(np.diag(R))
    R = R / np.outer(d, d)
    R = (1 - shrink) * R + shrink * np.eye(len(R))
    return R


def glasso(S: np.ndarray, alpha: float) -> np.ndarray:
    import warnings
    from sklearn.covariance import graphical_lasso
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _, P = graphical_lasso(S, alpha=alpha, max_iter=500, tol=5e-4, mode="cd")
    return P


def ebic(S: np.ndarray, P: np.ndarray, n: float, gamma: float = 0.5, tol: float = 1e-4) -> tuple[float, int]:
    p = len(S)
    sign, logdet = np.linalg.slogdet(P)
    ll = n / 2 * (logdet - np.trace(S @ P))
    E = int(((np.abs(np.triu(P, 1)) > tol)).sum())
    return -2 * ll + E * math.log(n) + 4 * E * gamma * math.log(p), E


def choose_alpha(S: np.ndarray, n: float, grid=(0.02, 0.03, 0.045, 0.06, 0.08, 0.1, 0.13, 0.17, 0.22, 0.28)) -> dict:
    rows = []
    for a in grid:
        try:
            P = glasso(S, a)
        except Exception:
            continue
        e, E = ebic(S, P, n)
        rows.append({"alpha": a, "ebic": e, "edges": E})
    best = min(rows, key=lambda r: r["ebic"])
    return {"alpha": best["alpha"], "path": rows}


def partial_from_precision(P: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.diag(P))
    R = -P / np.outer(d, d)
    np.fill_diagonal(R, 1.0)
    return R


def stability(Z: np.ndarray, alpha: float, n_sub: int = N_SUB, seed: int = 7, tol: float = 1e-4) -> dict:
    """Selection frequency of every pair across half-samples of months (Meinshausen and Buhlmann 2010)."""
    rng = np.random.default_rng(seed)
    T, p = Z.shape
    freq = np.zeros((p, p))
    q = []
    done = 0
    for _ in range(n_sub):
        rows = np.sort(rng.choice(T, T // 2, replace=False))
        C, _ = pairwise_corr(Z[rows], min_n=MIN_PAIR // 2)
        try:
            P = glasso(nearest_pd(C), alpha)
        except Exception:
            continue
        sel = np.abs(P) > tol
        np.fill_diagonal(sel, False)
        freq += sel
        q.append(sel.sum() / 2)
        done += 1
    freq /= max(done, 1)
    P_pairs = p * (p - 1) / 2
    qm = float(np.mean(q)) if q else 0.0
    return {"freq": freq, "runs": done, "q": qm, "pfer_bound": qm * qm / ((2 * PI_THR - 1) * P_pairs) if P_pairs else 0.0}


def established(Z: np.ndarray, alpha0: float, n_sub: int = N_SUB, grid=(1.0, 1.25, 1.5, 1.75, 2.0, 2.5)) -> dict:
    """The loosest penalty (a multiple of the EBIC one) at which the Meinshausen-Buhlmann bound on expected false
    links, q^2 / ((2 pi - 1) P) at pi = PI_EST, is at most FDR_TARGET of the links it keeps."""
    p = Z.shape[1]
    P_pairs = p * (p - 1) / 2
    best = None
    for m in grid:
        st = stability(Z, alpha0 * m, n_sub=n_sub, seed=11)
        kept = int((np.triu(st["freq"], 1) >= PI_EST).sum())
        bound = st["q"] ** 2 / ((2 * PI_EST - 1) * P_pairs)
        best = {"alpha": alpha0 * m, "freq": st["freq"], "kept": kept, "bound": bound, "q": st["q"]}
        if kept and bound <= FDR_TARGET * kept:
            break
    return best


# ---------------------------------------------------------------- direction
def _entropy(u: np.ndarray) -> float:
    from .discovery import _entropy as H
    return H(u)


def pair_direction(x: np.ndarray, y: np.ndarray) -> float:
    """Hyvarinen-Smith log-likelihood ratio on the common months: > 0 means x causes y."""
    m = ~(np.isnan(x) | np.isnan(y))
    if m.sum() < MIN_PAIR:
        return 0.0
    a, b = x[m], y[m]
    a = (a - a.mean()) / a.std()
    b = (b - b.mean()) / b.std()
    r = float(np.mean(a * b))
    ra, rb = a - r * b, b - r * a
    return (_entropy(b) + _entropy(ra / ra.std())) - (_entropy(a) + _entropy(rb / rb.std()))


def orient(Z: np.ndarray, edges: list[tuple[int, int]]) -> dict:
    """Pairwise evidence for each edge, then one global order from net evidence (greedy, most exogenous first)."""
    p = Z.shape[1]
    D = np.zeros((p, p))
    for i, j in edges:
        d = pair_direction(Z[:, i], Z[:, j])
        D[i, j], D[j, i] = d, -d
    nbr = [set() for _ in range(p)]
    for i, j in edges:
        nbr[i].add(j)
        nbr[j].add(i)
    left, order = set(range(p)), []
    while left:
        best = max(sorted(left), key=lambda i: sum(D[i, j] for j in nbr[i] if j in left))
        order.append(best)
        left.remove(best)
    pos = {v: k for k, v in enumerate(order)}
    agree = sum(1 for i, j in edges if (D[i, j] > 0) == (pos[i] < pos[j]) and D[i, j] != 0)
    return {"order": order, "D": D, "agree": agree / max(1, sum(1 for i, j in edges if D[i, j] != 0))}


# ---------------------------------------------------------------- weights
def _ols(y: np.ndarray, X: np.ndarray, hac: bool = True) -> dict:
    n, k = X.shape
    A = np.column_stack([np.ones(n), X])
    G = np.linalg.pinv(A.T @ A)
    b = G @ A.T @ y
    e = y - A @ b
    if hac:
        L = int(math.floor(4 * (n / 100) ** (2 / 9)))
        U = A * e[:, None]
        S = U.T @ U
        for l in range(1, L + 1):
            w = 1 - l / (L + 1)
            Gl = U[l:].T @ U[:-l]
            S += w * (Gl + Gl.T)
        V = G @ S @ G
    else:
        V = G * float(e @ e) / max(1, n - k - 1)
    se = np.sqrt(np.maximum(np.diag(V), 0))
    return {"b": b[1:], "se": se[1:], "s2": float(e @ e) / max(1, n - k - 1), "n": n, "dof": n - k - 1}


def fit_svar(Z: np.ndarray, order: list[int], edges: list[tuple[int, int]], nbr_lag: bool = True) -> dict:
    """y_t = B y_t + A y_t-1 + e_t on each series' available months. Returns B, A (weights), SEs, residual variances."""
    T, p = Z.shape
    pos = {v: k for k, v in enumerate(order)}
    nbr = [set() for _ in range(p)]
    for i, j in edges:
        nbr[i].add(j)
        nbr[j].add(i)
    B, A = np.zeros((p, p)), np.zeros((p, p))          # B[j, i]: effect of i on j (row = child)
    SB, SA = np.zeros((p, p)), np.zeros((p, p))
    tB, nB = np.zeros((p, p)), np.zeros((p, p), int)
    sig2 = np.ones(p)
    pruned = 0
    Zl = np.vstack([np.full((1, p), np.nan), Z[:-1]])
    for j in range(p):
        par = sorted((i for i in nbr[j] if pos[i] < pos[j]), key=lambda i: pos[i])
        lag = sorted(nbr[j] | {j}) if nbr_lag else [j]
        while True:
            X = np.column_stack([Z[:, par], Zl[:, lag]]) if par else Zl[:, lag]
            ok = ~np.isnan(Z[:, j]) & ~np.isnan(X).any(axis=1)
            if ok.sum() >= MIN_PAIR or not (par or len(lag) > 1):
                break
            # too few common months: drop the series with the shortest history from the lag set, then the parents
            if len(lag) > 1:
                lag.remove(min((k for k in lag if k != j), key=lambda k: (~np.isnan(Z[:, k])).sum()))
            else:
                par.remove(min(par, key=lambda k: (~np.isnan(Z[:, k])).sum()))
        if ok.sum() < 24:
            continue
        f = _ols(Z[ok, j], X[ok])
        # backward elimination of same-month parents with |t| < PAR_T: removes the co-parent ("moral") links a
        # graphical model adds between two causes of one effect, and links the regression cannot support
        while par:
            ts = [abs(f["b"][k] / f["se"][k]) if f["se"][k] > 0 else 0.0 for k in range(len(par))]
            k = int(np.argmin(ts))
            if ts[k] >= PAR_T:
                break
            par.pop(k)
            pruned += 1
            X = np.column_stack([Z[:, par], Zl[:, lag]]) if par else Zl[:, lag]
            ok = ~np.isnan(Z[:, j]) & ~np.isnan(X).any(axis=1)
            f = _ols(Z[ok, j], X[ok])
        sig2[j] = f["s2"]
        for k, i in enumerate(par):
            B[j, i], SB[j, i] = f["b"][k], f["se"][k]
            tB[j, i] = f["b"][k] / f["se"][k] if f["se"][k] > 0 else 0.0
            nB[j, i] = f["n"]
        for k, i in enumerate(lag):
            b, se = f["b"][len(par) + k], f["se"][len(par) + k]
            if se > 0 and abs(b / se) >= LAG_T:
                A[j, i], SA[j, i] = b, se
    return {"B": B, "A": A, "SB": SB, "SA": SA, "tB": tB, "nB": nB, "sig2": sig2, "pruned": pruned}


# ---------------------------------------------------------------- dynamics
def irf(B: np.ndarray, A: np.ndarray, h: int = H) -> list[np.ndarray]:
    p = len(B)
    P0 = np.linalg.inv(np.eye(p) - B)
    M = P0 @ A
    out, cur = [P0], P0
    for _ in range(h):
        cur = M @ cur
        out.append(cur)
    return out


def stable_A(B: np.ndarray, A: np.ndarray, cap: float = 0.95) -> tuple[np.ndarray, float, float]:
    """Shrink the lag matrix if the companion matrix is explosive; returns (A, radius before, factor)."""
    M = np.linalg.inv(np.eye(len(B)) - B) @ A
    r = float(np.max(np.abs(np.linalg.eigvals(M)))) if len(M) else 0.0
    f = 1.0 if r < cap else cap / r
    return A * f, r, f


def connectedness(Phi: list[np.ndarray], sig2: np.ndarray) -> dict:
    """Diebold-Yilmaz with orthogonal structural shocks: theta[i, j] = share of i's H-step forecast-error variance
    due to j's shock. Rows sum to 1."""
    num = sum((P ** 2) * sig2[None, :] for P in Phi)
    th = num / num.sum(axis=1, keepdims=True)
    p = len(th)
    off = th.copy()
    np.fill_diagonal(off, 0.0)
    return {"theta": th, "total": float(100 * off.sum() / p), "to": 100 * off.sum(axis=0), "from": 100 * off.sum(axis=1),
            "net": 100 * (off.sum(axis=0) - off.sum(axis=1))}


def gfevd_total(X: np.ndarray, h: int = H, ridge: float = 2.0) -> float:
    """Total connectedness of a ridge VAR(1) on a complete window, generalized FEVD (Pesaran and Shin), normalized rows."""
    Y, L = X[1:], X[:-1]
    p = X.shape[1]
    Areg = np.linalg.solve(L.T @ L + ridge * np.eye(p), L.T @ Y).T
    E = Y - L @ Areg.T
    S = np.cov(E, rowvar=False)
    num = np.zeros((p, p))
    Ah = np.eye(p)
    for _ in range(h + 1):
        AS = Ah @ S
        num += (AS ** 2) / np.diag(S)[None, :]
        Ah = Areg @ Ah
    den = np.zeros(p)
    Ah = np.eye(p)
    for _ in range(h + 1):
        den += np.diag(Ah @ S @ Ah.T)
        Ah = Areg @ Ah
    th = num / den[:, None]
    th = th / th.sum(axis=1, keepdims=True)
    return float(100 * (th.sum() - np.trace(th)) / p)


def rolling_connectedness(Zdf: pd.DataFrame, window: int = 60, step: int = 1) -> dict:
    """The connectedness index through time on the series with data in every month of each window (no look-ahead:
    each value uses the window ending that month)."""
    dates, vals, ns = [], [], []
    idx = Zdf.index
    for end in range(window, len(idx) + 1, step):
        W = Zdf.iloc[end - window:end]
        W = W.loc[:, W.notna().all()]
        if W.shape[1] < 8:
            continue
        vals.append(round(gfevd_total(W.to_numpy()), 3))
        dates.append(idx[end - 1].strftime("%Y-%m"))
        ns.append(int(W.shape[1]))
    return {"dates": dates, "total": vals, "series": ns, "window": window}


# ---------------------------------------------------------------- network
def communities(W: np.ndarray, min_size: int = 3) -> list[int]:
    """Newman's leading-eigenvector method, applied recursively while modularity rises."""
    A = np.abs(W)
    A = (A + A.T) / 2
    np.fill_diagonal(A, 0)
    k = A.sum(axis=1)
    m2 = k.sum()
    if m2 <= 0:
        return [0] * len(A)
    Bm = A - np.outer(k, k) / m2
    groups = [list(range(len(A)))]
    final = []
    while groups:
        g = groups.pop()
        if len(g) < 2 * min_size:
            final.append(g)
            continue
        Bg = Bm[np.ix_(g, g)].copy()
        Bg -= np.diag(Bg.sum(axis=1))
        w, V = np.linalg.eigh(Bg)
        v = V[:, -1]
        s = np.where(v >= 0, 1.0, -1.0)
        dq = float(s @ Bg @ s) / (2 * m2)
        g1, g2 = [g[i] for i in range(len(g)) if s[i] > 0], [g[i] for i in range(len(g)) if s[i] < 0]
        if w[-1] <= 1e-10 or dq <= 1e-6 or len(g1) < min_size or len(g2) < min_size:
            final.append(g)
        else:
            groups += [g1, g2]
    lab = [0] * len(A)
    for c, g in enumerate(sorted(final, key=lambda g: (-len(g), min(g)))):
        for i in g:
            lab[i] = c
    return lab


def modularity(W: np.ndarray, lab: list[int]) -> float:
    A = np.abs(W)
    A = (A + A.T) / 2
    np.fill_diagonal(A, 0)
    k = A.sum(axis=1)
    m2 = k.sum()
    if m2 <= 0:
        return 0.0
    same = np.equal.outer(lab, lab)
    return float(((A - np.outer(k, k) / m2) * same).sum() / m2)


def pagerank(W: np.ndarray, d: float = 0.85, iters: int = 200) -> np.ndarray:
    """PageRank on the absolute weights, edges from cause to effect (W[child, parent])."""
    A = np.abs(W).T                                  # A[parent, child]
    p = len(A)
    out = A.sum(axis=1)
    r = np.full(p, 1.0 / p)
    for _ in range(iters):
        nr = (1 - d) / p + d * ((r / np.where(out > 0, out, 1))[None, :] @ A).ravel() + d * r[out == 0].sum() / p
        if np.abs(nr - r).sum() < 1e-12:
            r = nr
            break
        r = nr
    return r / r.sum()


def galaxy_layout(W: np.ndarray, groups: list[int], seed: int = 3) -> np.ndarray:
    """Each community laid out on its own (force-directed, then spread to an even disc of radius proportional to the
    square root of its size); the discs are then placed by a force layout of the communities themselves, attracted by
    the links between them and kept from overlapping. Deterministic."""
    p = len(W)
    A = np.abs(W) + np.abs(W.T)
    np.fill_diagonal(A, 0)
    gs = sorted(set(groups))
    X = np.zeros((p, 2))
    rad = {}
    for g in gs:
        idx = [i for i in range(p) if groups[i] == g]
        m = len(idx)
        rad[g] = 0.16 * math.sqrt(m)
        if m == 1:
            continue
        sub = layout(A[np.ix_(idx, idx)], [0] * m, seed=seed + g, iters=300, spread=True)
        X[idx] = sub
    # place the discs
    G = len(gs)
    gi = {g: k for k, g in enumerate(gs)}
    Cw = np.zeros((G, G))
    for i in range(p):
        for j in range(p):
            if A[i, j] and groups[i] != groups[j]:
                Cw[gi[groups[i]], gi[groups[j]]] += A[i, j]
    order = sorted(gs, key=lambda g: -rad[g])
    C = np.zeros((G, 2))
    for k, g in enumerate(order):
        a = 2 * math.pi * k / G
        C[gi[g]] = [math.cos(a) * (0.6 + 0.1 * (k % 2)), math.sin(a) * (0.6 + 0.1 * (k % 2))]
    R = np.array([rad[g] for g in gs])
    for it in range(600):
        F = np.zeros_like(C)
        for a_ in range(G):
            for b_ in range(G):
                if a_ == b_:
                    continue
                d = C[a_] - C[b_]
                dist = math.hypot(*d) + 1e-9
                need = R[a_] + R[b_] + 0.06
                if dist < need:
                    F[a_] += (need - dist) * d / dist * 0.5
                F[a_] -= 0.02 * Cw[a_, b_] * d / max(dist, 1e-3) * min(1.0, dist)
        F -= 0.01 * C
        C += F * (1 - it / 700)
    for g in gs:
        idx = [i for i in range(p) if groups[i] == g]
        X[idx] = C[gi[g]] + X[idx] * rad[g]
    ext = max(float(np.max(np.abs(C[:, 0]) + R)), float(np.max(np.abs(C[:, 1]) + R)))
    X = X - (np.max(C - R[:, None], axis=0) * 0 + (np.max(C + R[:, None], axis=0) + np.min(C - R[:, None], axis=0)) / 2)
    ext = float(np.max(np.abs(X))) or 1.0
    return X / ext * 0.97


def layout(W: np.ndarray, groups: list[int], seed: int = 3, iters: int = 400, spread: bool = False) -> np.ndarray:
    """Deterministic Fruchterman-Reingold, started with each community in its own sector of a circle."""
    rng = np.random.default_rng(seed)
    p = len(W)
    G = max(groups) + 1 if groups else 1
    ang = np.array([2 * math.pi * (g + 0.5) / G for g in groups]) + rng.normal(0, 0.25, p)
    rad = 0.55 + rng.uniform(-0.15, 0.15, p)
    X = np.column_stack([rad * np.cos(ang), rad * np.sin(ang)])
    A = np.abs(W) + np.abs(W.T)
    same = np.equal.outer(groups, groups)
    k = 2.2 / math.sqrt(p)
    t = 0.12
    for it in range(iters):
        d = X[:, None, :] - X[None, :, :]
        dist = np.sqrt((d ** 2).sum(-1)) + 1e-9
        rep = (k * k / dist ** 2)[:, :, None] * d
        att = -((A * (1 + 0.6 * same)) * dist / k)[:, :, None] * d
        att += -(0.04 * same * dist / k)[:, :, None] * d          # gentle pull toward one's community
        F = (rep + att).sum(axis=1) - 0.02 * X                     # and a little gravity to the centre
        L = np.sqrt((F ** 2).sum(-1)) + 1e-9
        X = X + (F / L[:, None]) * np.minimum(L, t)[:, None]
        t *= 0.992
    if spread:
        X = X - X.mean(axis=0)
        r = np.sqrt((X ** 2).sum(-1)) + 1e-12
        rank = np.argsort(np.argsort(r))
        return X * (np.sqrt((rank + 0.5) / p) / r)[:, None]
    # isolated nodes go to an outer ring by group; the connected part is scaled by a robust radius and squashed at the rim
    deg = (A > 0).sum(axis=1)
    iso = deg == 0
    core_ = ~iso
    if core_.any():
        # equal-area radii: keep every node's angle and radial rank, spread the disk evenly (r = 0.9 sqrt(rank / n))
        X = X - X[core_].mean(axis=0)
        r = np.sqrt((X ** 2).sum(-1)) + 1e-12
        ci = np.where(core_)[0]
        rank = np.argsort(np.argsort(r[ci]))
        rr = 0.9 * np.sqrt((rank + 0.5) / len(ci))
        X[ci] = X[ci] * (rr / r[ci])[:, None]
    ids_iso = [i for i in range(p) if iso[i]]
    ids_iso.sort(key=lambda i: (groups[i], i))
    for k, i in enumerate(ids_iso):
        a = -math.pi / 2 + 2 * math.pi * (k + 0.5) / max(1, len(ids_iso))
        X[i] = [1.0 * math.cos(a), 1.0 * math.sin(a)]
    return X


# ---------------------------------------------------------------- robustness
def robustness_value(t: float, dof: int) -> float:
    if dof <= 1:
        return 0.0
    f = abs(t) / math.sqrt(dof)
    return 0.5 * (math.sqrt(f ** 4 + 4 * f ** 2) - f ** 2)


def regime_flips(Zdf: pd.DataFrame, links: list[dict], ids: list[str], split: str = "2022-01-01") -> list[dict]:
    """Each contemporaneous link re-estimated before and after the split (the child on that one parent and its other
    parents): links whose sign reverses with |t| >= 2 on both sides, or that lose or gain significance."""
    out = []
    for l in links:
        if l["lag"]:
            continue
        j, i = ids.index(l["to"]), ids.index(l["from"])
        others = [ids.index(o) for o in l.get("coparents", []) if o in ids]
        cols = [i] + others
        res = {}
        for nm, sub in (("before", Zdf.loc[:split].iloc[:-1]), ("after", Zdf.loc[split:])):
            X = sub.iloc[:, cols].to_numpy()
            y = sub.iloc[:, j].to_numpy()
            ok = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
            if ok.sum() < 30:
                res = None
                break
            f = _ols(y[ok], X[ok])
            res[nm] = {"w": float(f["b"][0]), "t": float(f["b"][0] / f["se"][0]) if f["se"][0] > 0 else 0.0, "n": int(ok.sum())}
        if not res:
            continue
        b, a = res["before"], res["after"]
        flip = (b["w"] * a["w"] < 0) and abs(b["t"]) >= 2 and abs(a["t"]) >= 2
        change = (abs(b["t"]) >= 2) != (abs(a["t"]) >= 2)
        if flip or change:
            out.append({"from": l["from"], "to": l["to"], "before": b, "after": a, "flip": bool(flip)})
    out.sort(key=lambda r: -abs(r["after"]["w"] - r["before"]["w"]))
    return out


def oos_lags(Zdf: pd.DataFrame, A: np.ndarray, ids: list[str], start: str = "2005-01-01") -> dict:
    """Does the network's lagged structure forecast next month better than each series' own lag? Expanding-window
    refits each January (no look-ahead); out-of-sample R squared relative to the own-lag model."""
    out = {}
    Z = Zdf.to_numpy()
    T, p = Z.shape
    dates = Zdf.index
    s0 = int(np.searchsorted(dates, pd.Timestamp(start)))
    for j in range(p):
        lag = [i for i in range(p) if A[j, i] != 0 and i != j]
        if not lag:
            continue
        cols = [j] + lag
        e_own, e_net = [], []
        for t in range(max(s0, 60), T):
            if np.isnan(Z[t, j]) or np.isnan(Z[t - 1, cols]).any():
                continue
            m = slice(1, t)
            Xall = Z[0:t - 1][:, cols]
            yy = Z[1:t, j]
            ok = ~np.isnan(yy) & ~np.isnan(Xall).any(axis=1)
            if ok.sum() < 60:
                continue
            f_net = np.linalg.lstsq(np.column_stack([np.ones(ok.sum()), Xall[ok]]), yy[ok], rcond=None)[0]
            f_own = np.linalg.lstsq(np.column_stack([np.ones(ok.sum()), Xall[ok][:, :1]]), yy[ok], rcond=None)[0]
            x = Z[t - 1, cols]
            e_net.append(Z[t, j] - (f_net[0] + x @ f_net[1:]))
            e_own.append(Z[t, j] - (f_own[0] + x[0] * f_own[1]))
            del m
        if len(e_net) >= 36:
            r2 = 1 - float(np.sum(np.square(e_net))) / float(np.sum(np.square(e_own)))
            out[ids[j]] = {"months": len(e_net), "oos_r2_vs_own": r2}
    return out


# ---------------------------------------------------------------- the core map joins
CORE_MAP = {"oil": "brent", "eq": "sp500", "y10": "y10", "cpi": "cpi", "vix": "vix", "gold": "gold"}
BRIDGES = [  # judged links from the core map's concepts into series it did not have (from, to, w, why)
    ("dollar", "eur", -0.60, "The euro is the dollar's mirror: a stronger dollar is a weaker euro"),
    ("dollar", "jpy", -0.40, "The yen weakens as the dollar strengthens"),
    ("capex", "copper", 0.15, "Data centres and grids are built of copper"),
    ("power", "natgas", 0.20, "Gas sets the marginal price of power"),
    ("hormuz", "lng_jp", 0.30, "Qatar's LNG leaves through the strait"),
    ("hormuz", "gas_eu", 0.25, "Lost LNG cargoes tighten Europe"),
    ("fed", "usd", 0.35, "Higher rates attract capital"),
    ("aidemand", "twd", 0.10, "Taiwan's exports are the chips"),
    ("aidemand", "krw", 0.08, "Korea's exports are the memory"),
]


CORE_SHORT = {"hormuz": "Hormuz", "fed": "Fed", "fiscal": "Bond supply", "capex": "AI capex", "memory": "Memory", "power": "Power", "aidemand": "AI demand",
              "tp": "Term premium", "dep": "Depreciation", "pods": "Pods", "liq": "Liquidity", "credit": "Credit", "pcredit": "Private credit",
              "consumer": "Consumer", "dollar": "Dollar", "earn": "Earnings rev.", "tlt": "TLT", "corr": "Stock-bond corr.", "book": "Book"}


def _core() -> dict:
    return json.loads((ASSETS / "brain_graph.json").read_text())["graph"]


def build(dl: dict | None = None, n_sub: int = N_SUB) -> dict:
    dl = dl if dl is not None else download()
    P, meta = panel(dl)
    Zdf, clipped = standardize(P)
    ids = list(Zdf.columns)
    Z = Zdf.to_numpy()
    T, p = Z.shape
    C, Npair = pairwise_corr(Z)
    S = nearest_pd(C)
    n_eff = float(np.median(Npair[np.triu_indices(p, 1)]))
    ch = choose_alpha(S, n_eff)
    Pm = glasso(S, ch["alpha"])
    st = stability(Z, ch["alpha"], n_sub=n_sub)
    freq = st["freq"]
    est = established(Z, ch["alpha"], n_sub=n_sub)
    edges = [(i, j) for i in range(p) for j in range(i + 1, p) if freq[i, j] >= PI_THR]
    orn = orient(Z, edges)
    fit = fit_svar(Z, orn["order"], edges)
    B, A0 = fit["B"], fit["A"]
    A, rad0, shrink = stable_A(B, A0)
    Phi = irf(B, A)
    con = connectedness(Phi, fit["sig2"])
    pc = partial_from_precision(Pm)
    lab = communities(pc * (freq >= PI_THR))
    mod = modularity(pc * (freq >= PI_THR), lab)
    pr = pagerank(B + A)
    total = Phi[0] - np.eye(p)
    links = []
    for j in range(p):
        for i in range(p):
            if B[j, i] != 0:
                a, b = min(i, j), max(i, j)
                links.append({"from": ids[i], "to": ids[j], "w": float(B[j, i]), "se": float(fit["SB"][j, i]), "t": float(fit["tB"][j, i]), "lag": 0,
                              "stability": float(freq[a, b]), "established": bool(est["freq"][a, b] >= PI_EST), "agree": bool(orn["D"][i, j] > 0), "evidence": float(orn["D"][i, j]),
                              "rv": robustness_value(fit["tB"][j, i], int(fit["nB"][j, i]) - 2), "partial": float(pc[i, j]),
                              "coparents": [ids[k] for k in range(p) if B[j, k] != 0 and k != i]})
            if A[j, i] != 0:
                links.append({"from": ids[i], "to": ids[j], "w": float(A[j, i]), "se": float(fit["SA"][j, i]), "t": float(A[j, i] / fit["SA"][j, i]) if fit["SA"][j, i] else 0.0,
                              "lag": 1, "self": i == j})
    flips = regime_flips(Zdf, links, ids)
    oos = oos_lags(Zdf, A, ids)
    # a fixed set of series for the index: current today and present in every month since the latest start among them
    cur = [c for c in ids if meta[c]["to"] >= (Zdf.index[-1] - pd.DateOffset(months=6)).strftime("%Y-%m")]
    start = max(meta[c]["from"] for c in cur) + "-01"
    sub = Zdf.loc[start:, cur]
    sub = sub.loc[:, sub.iloc[:-1].notna().all()]
    roll = rolling_connectedness(sub.iloc[:-1] if sub.iloc[-1].isna().any() else sub)
    fam = {}
    for c in ids:
        fam.setdefault(meta[c]["family"], []).append(c)
    comm_names = []
    for g in range(max(lab) + 1):
        mem = [ids[i] for i in range(p) if lab[i] == g]
        counts = {}
        for c in mem:
            counts[meta[c]["family"]] = counts.get(meta[c]["family"], 0) + 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        name = top[0][0] if len(top) == 1 or top[1][1] < 0.3 * len(mem) else f"{top[0][0]} and {top[1][0]}"
        if top[0][0] != "Equities" and any(meta[c]["family"] in ("Equities", "Volatility") for c in mem) and "Equities" not in name:
            name += " with equities"
        lead = sorted(mem, key=lambda c: -float(np.abs(total[:, ids.index(c)]).sum()))[:2]
        comm_names.append({"id": g, "name": name, "members": mem, "size": len(mem), "lead": [meta[c]["short"] for c in lead]})
    seen = {}
    for c in comm_names:
        seen[c["name"]] = seen.get(c["name"], 0) + 1
    for c in comm_names:
        if seen[c["name"]] > 1:
            c["name"] = f"{c['name']}: {', '.join(c['lead'])}"
    # the core map's judged nodes join the learned graph
    core = _core()
    measured = set(CORE_MAP)
    core_nodes = [n for n in core["nodes"] if n["id"] not in measured]
    judged = []
    for e in core["edges"]:
        if e["measured"]:
            continue
        f, t = CORE_MAP.get(e["from"], e["from"]), CORE_MAP.get(e["to"], e["to"])
        judged.append({"from": f, "to": t, "w": float(e["w"]), "judged": True})
    for f, t, w, why in BRIDGES:
        if t in ids or t in {n["id"] for n in core_nodes}:
            judged.append({"from": f, "to": t, "w": w, "judged": True, "why": why, "bridge": True})
    # one layout for the whole brain: learned communities, plus the judged concepts and the holdings as two more
    jn = [n["id"] for n in core_nodes]
    full_ids = ids + jn
    fx = {k: i for i, k in enumerate(full_ids)}
    Wall = np.zeros((len(full_ids), len(full_ids)))
    Wall[:p, :p] = np.abs(B) + np.abs(A) * (1 - np.eye(p))
    for l in judged:
        if l["from"] in fx and l["to"] in fx:
            Wall[fx[l["to"]], fx[l["from"]]] += abs(l["w"])
    G = max(lab) + 1
    ring = {n["id"]: n["ring"] for n in core_nodes}
    groups = lab + [G if ring[k] <= 2 else G + 1 for k in jn]
    pos = galaxy_layout(Wall, groups)
    comm_names += [{"id": G, "name": "Judged concepts", "members": [k for k in jn if ring[k] <= 2], "size": sum(1 for k in jn if ring[k] <= 2), "judged": True},
                   {"id": G + 1, "name": "Holdings and the book", "members": [k for k in jn if ring[k] > 2], "size": sum(1 for k in jn if ring[k] > 2), "judged": True}]
    nodes = []
    for k, c in enumerate(ids):
        nodes.append({"id": c, **meta[c], "measured": True, "community": lab[k], "x": round(float(pos[fx[c], 0]), 4), "y": round(float(pos[fx[c], 1]), 4),
                      "pagerank": float(pr[k]), "systemic": float(np.abs(total[:, k]).sum()), "vulnerable": float(np.abs(total[k, :]).sum()),
                      "gives": float(con["to"][k]), "takes": float(con["from"][k]), "net": float(con["net"][k]), "clipped": clipped[c],
                      "sigma": float(fit["sig2"][k]), "core": next((cid for cid, aid in CORE_MAP.items() if aid == c), None)})
    for n in core_nodes:
        k = fx[n["id"]]
        nodes.append({"id": n["id"], "name": n["name"], "short": CORE_SHORT.get(n["id"], n["name"]), "family": "Judged" if n["ring"] <= 2 else "Book",
                      "measured": False, "ring": n["ring"], "community": groups[k], "x": round(float(pos[k, 0]), 4), "y": round(float(pos[k, 1]), 4)})
    return {
        "schema": 1, "as_of": Zdf.index[-1].strftime("%Y-%m"), "months": T, "series": p,
        "sources": sorted({m["source"] for m in meta.values()}),
        "failed": dl.get("failed", {}), "nodes": nodes, "links": links, "judged": judged,
        "skeleton": {"alpha": ch["alpha"], "ebic_path": [{k: float(v) if k != "edges" else int(v) for k, v in r.items()} for r in ch["path"]], "n_eff": n_eff,
                     "edges_full": int((np.abs(np.triu(Pm, 1)) > 1e-4).sum()), "edges_stable": len(edges), "pi_thr": PI_THR, "subsamples": st["runs"],
                     "q": st["q"], "established": {"alpha": est["alpha"], "pi": PI_EST, "kept": est["kept"], "pfer_bound": est["bound"], "q": est["q"]}},
        "direction": {"agree": float(np.mean([l["agree"] for l in links if not l["lag"]])) if any(not l["lag"] for l in links) else 0.0,
                      "agree_selected": orn["agree"], "order": [ids[i] for i in orn["order"]]},
        "pruned": fit["pruned"],
        "dynamics": {"radius_before": rad0, "shrink": shrink, "horizon": H, "lag_t": LAG_T, "lagged_links": int((A != 0).sum()),
                     "self_lags": int(sum(1 for j in range(p) if A[j, j] != 0))},
        "connectedness": {"total": con["total"], "rolling": roll},
        "communities": comm_names, "modularity": mod, "regime_flips": flips[:40], "oos": oos,
        "method": "Graphical lasso (EBIC) with stability selection, pairwise LiNGAM orientation, structural VAR(1), Diebold-Yilmaz connectedness",
    }


def summary(r: dict) -> list[str]:
    s, d, c = r["skeleton"], r["dynamics"], r["connectedness"]
    meas = [n for n in r["nodes"] if n["measured"]]
    top = sorted(meas, key=lambda n: -n["systemic"])[:3]
    roll = c["rolling"]
    e = s["established"]
    out = [f"{r['series']} monthly series and {len([n for n in r['nodes'] if not n['measured']])} judged concepts; {s['edges_stable']} same-month links are selected "
           f"in at least {int(100 * s['pi_thr'])}% of {s['subsamples']} half-samples. {e['kept']} are established (selected in {int(100 * e['pi'])}% at a stricter "
           f"penalty), with at most {e['pfer_bound']:.1f} expected false among them (Meinshausen-Buhlmann bound). Regressing each series on its "
           f"parents keeps {sum(1 for l in r['links'] if not l['lag'])} with |t| >= 2 ({r.get('pruned', 0)} removed), "
           f"{sum(1 for l in r['links'] if not l['lag'] and l.get('established'))} of them established.",
           f"{int(100 * r['direction']['agree'])}% of them point the way their own pairwise evidence says; {d['lagged_links'] - d['self_lags']} links from one series to another "
           f"next month pass |t| >= {d['lag_t']}, and {d['self_lags']} series carry their own momentum.",
           f"System connectedness is {c['total']:.0f}%: the share of a typical series' 12-month forecast error that comes from other series' shocks.",
           f"Most systemic: {', '.join(n['short'] for n in top)}."]
    if roll["total"]:
        i = int(np.argmax(roll["total"]))
        out.append(f"Rolling 5-year connectedness peaked at {roll['total'][i]:.0f}% in {roll['dates'][i]} and reads {roll['total'][-1]:.0f}% now.")
    return out


# ---------------------------------------------------------------- the whole brain as matrices (the page does the same)
def matrices(r: dict) -> dict:
    """Index every node; Wc[child, parent] = same-month weight (learned or judged), A = lagged learned weights,
    with the standard errors the page's Monte Carlo draws from (judged: half the weight) and each learned link's
    stability (the probability it exists, for structural doubt)."""
    ids = [n["id"] for n in r["nodes"]]
    ix = {k: i for i, k in enumerate(ids)}
    n = len(ids)
    Wc, A = np.zeros((n, n)), np.zeros((n, n))
    Sc, Sa, Pc = np.zeros((n, n)), np.zeros((n, n)), np.ones((n, n))
    for l in r["links"]:
        if l["from"] not in ix or l["to"] not in ix:
            continue
        i, j = ix[l["from"]], ix[l["to"]]
        if l["lag"]:
            A[j, i], Sa[j, i] = l["w"], l["se"]
        else:
            Wc[j, i], Sc[j, i], Pc[j, i] = l["w"], l["se"], l["stability"]
    for l in r["judged"]:
        if l["from"] not in ix or l["to"] not in ix:
            continue
        i, j = ix[l["from"]], ix[l["to"]]
        Wc[j, i] += l["w"]
        Sc[j, i] = abs(l["w"]) * 0.5
    return {"ids": ids, "ix": ix, "Wc": Wc, "A": A, "Sc": Sc, "Sa": Sa, "Pc": Pc}


def respond(r: dict, shock: dict, h: int = H, M: dict | None = None) -> np.ndarray:
    """Responses to a one-time shock (sigma units) at horizons 0..h: x_0 = Phi_0 e, x_k = Phi_0 A x_k-1."""
    M = M or matrices(r)
    n = len(M["ids"])
    e = np.zeros(n)
    for k, v in shock.items():
        e[M["ix"][k]] = v
    P0 = np.linalg.inv(np.eye(n) - M["Wc"])
    out = [P0 @ e]
    for _ in range(h):
        out.append(P0 @ (M["A"] @ out[-1]))
    return np.array(out)


def radius(W: np.ndarray) -> float:
    return float(np.max(np.abs(np.linalg.eigvals(W)))) if len(W) else 0.0
