"""The brain: measured links between the parts of the financial system, by regime.

    python -m buildout brain --out site/data          # writes brain.json (public GitHub datasets, free)

Six series have long monthly histories in the public datasets the research step already reads: Brent (EIA, 1987 on),
CPI-U (BLS), the 10-year Treasury, the S&P 500 (Shiller), the VIX (CBOE, 1990 on) and gold. Each is turned into a
monthly change and standardized by its full-sample standard deviation, so "1 sigma" means the same move in every era.

Identification is by ordering, stated up front: oil moves first, then consumer prices, then the 10-year yield, then
stocks, then volatility and gold. Each series is regressed on the series before it in that order (same month), one
regime at a time. A weight of -0.30 on "y10>eq" reads: a 1-sigma rise in the 10-year yield came with a 0.30-sigma
fall in stocks the same month, holding oil and CPI fixed. The ordering is an assumption; the page lets a quant
flip or zero any edge and see what survives.

Regimes: 1990 to 2021 (the low-inflation era, when bonds hedged) and 2022 on (the inflation era). The page blends the
two, adds judged edges for the parts of the system with no long free history (private credit, power, memory), and
propagates shocks through the whole graph.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ORDER = ["oil", "cpi", "y10", "eq", "vix", "gold"]
PARENTS = {"cpi": ["oil"], "y10": ["oil", "cpi"], "eq": ["oil", "cpi", "y10"], "vix": ["eq", "y10"], "gold": ["oil", "y10", "eq"]}
LABELS = {"oil": "Brent, monthly average (EIA)", "cpi": "CPI-U, monthly change (BLS)", "y10": "10-year Treasury yield, change",
          "eq": "S&P 500, monthly return (Shiller)", "vix": "VIX, monthly average (CBOE)", "gold": "Gold, monthly"}
REGIMES = {"low_inflation": ("1990-02-01", "2021-12-01"), "inflation": ("2022-01-01", None)}


def changes(t: dict) -> pd.DataFrame:
    """Monthly changes from the research step's tidy() output: log changes for prices, differences for the yield."""
    sh = t["shiller"]
    brent = t["brent"].resample("MS").mean()
    vix = t["vix"].resample("MS").mean()
    df = pd.DataFrame({
        "oil": np.log(brent).diff(),
        "cpi": np.log(t["cpi"]).diff(),
        "y10": t["y10"].diff(),
        "eq": np.log(sh["px"]).diff(),
        "vix": np.log(vix).diff(),
        "gold": np.log(t["gold"]).diff(),
    })
    return df.dropna()


def _ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    X1 = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid = y - X1 @ beta
    dof = max(1, len(y) - X1.shape[1])
    s2 = float(resid @ resid) / dof
    cov = s2 * np.linalg.pinv(X1.T @ X1)
    r2 = 1 - float(resid @ resid) / float(((y - y.mean()) ** 2).sum()) if len(y) > 1 else float("nan")
    return beta[1:], np.sqrt(np.diag(cov))[1:], r2


def estimate(dz: pd.DataFrame, start: str, end: str | None) -> dict:
    """Standardized structural weights for one regime: every edge parent>child with weight, standard error, t and n."""
    d = dz.loc[start:end] if end else dz.loc[start:]
    edges, fit = {}, {}
    for child, parents in PARENTS.items():
        b, se, r2 = _ols(d[child].to_numpy(), d[parents].to_numpy())
        fit[child] = round(r2, 4)
        for p, w, s in zip(parents, b, se):
            edges[f"{p}>{child}"] = {"w": float(w), "se": float(s), "t": float(w / s) if s > 0 else None}
    return {"start": d.index[0].strftime("%Y-%m"), "end": d.index[-1].strftime("%Y-%m"), "months": int(len(d)), "edges": edges, "r2": fit}


def node_state(df: pd.DataFrame, months: int = 3) -> dict:
    """Where each series is now: its latest 3-month change in standard deviations of all 3-month changes."""
    out = {}
    for c in ORDER:
        s = df[c].rolling(months).sum().dropna()
        z = (s.iloc[-1] - s.mean()) / s.std()
        out[c] = {"z3m": float(z), "month": s.index[-1].strftime("%Y-%m")}
    return out


def stock_bond_flip(dz: pd.DataFrame) -> dict:
    """The single most important edge for this book: yields and stocks, by regime (positive weight = bonds hedged)."""
    out = {}
    for name, (a, b) in REGIMES.items():
        d = dz.loc[a:b] if b else dz.loc[a:]
        out[name] = float(np.corrcoef(d["y10"], d["eq"])[0, 1])
    return out


def series_block(t: dict) -> dict:
    """The six standardized monthly changes, rounded, for the page's causal discovery and time-varying links."""
    df = changes(t)
    dz = (df - df.mean()) / df.std()
    return {"cols": ORDER, "dates": [d.strftime("%Y-%m") for d in dz.index], "z": [[round(float(v), 4) for v in dz[c]] for c in ORDER]}


def learn(block: dict) -> dict:
    """Discovery on the series block: the learned causal order by regime with bootstrap stability, and each measured
    link's time-varying path (Kalman smoother, drift chosen by likelihood)."""
    from . import discovery as D
    dates = block["dates"]
    Z = np.array(block["z"]).T
    out = {"order": {}, "links": {}}
    for name, (a, b) in REGIMES.items():
        a_, b_ = a[:7], (b or "9999-12")[:7]
        rows = [i for i, d in enumerate(dates) if a_ <= d <= b_]
        X = Z[rows]
        o = D.lingam_order(X)
        bs = D.bootstrap_order(X, D.resamples(len(rows), 200)) if len(rows) >= 120 else None
        out["order"][name] = {"months": len(rows), "learned": [ORDER[i] for i in o], "agreement": D.order_agreement(o, list(range(6))),
                              "p_before": bs["p_before"] if bs else None}
    for child, parents in PARENTS.items():
        ci, pi = ORDER.index(child), [ORDER.index(p) for p in parents]
        k = D.kalman_mle(Z[:, ci], Z[:, pi])
        for j, p in enumerate(parents):
            path = [row[j] for row in k["beta"]]
            out["links"][f"{p}>{child}"] = {"beta": [round(v, 4) for v in path], "sd": [round(row[j], 4) for row in k["sd"]], "q": k["q"],
                                            "sign_changes": D.sign_changes(path, None, dates)}
    out["dates"] = dates
    return out


def _robust(block: dict) -> dict:
    from .robust import link_robustness
    return link_robustness(block, PARENTS, REGIMES)


def run(raw: dict) -> dict:
    from .research import tidy
    t = tidy(raw)
    df = changes(t)
    sd = df.std()
    dz = (df - df.mean()) / sd
    regimes = {name: estimate(dz, a, b) for name, (a, b) in REGIMES.items()}
    from .reasoner import factor_cov
    block = series_block(t)
    return {"schema": 1, "order": ORDER, "parents": PARENTS, "labels": LABELS, "sd": {k: float(v) for k, v in sd.items()},
            "regimes": regimes, "state": node_state(df), "y10_eq_corr": stock_bond_flip(dz), "factor_cov": factor_cov(raw),
            "series": block, "learned": learn(block), "robust_links": _robust(block),
            "method": "Recursive regression on standardized monthly changes, ordered oil, CPI, 10-year, stocks, VIX, gold"}


# ---------------------------------------------------------------- propagation (the page's brain does the same arithmetic)
def link_matrix(nodes: list[str], edges: list[tuple[str, str, float]]) -> np.ndarray:
    idx = {n: i for i, n in enumerate(nodes)}
    W = np.zeros((len(nodes), len(nodes)))
    for f, t, w in edges:
        W[idx[f], idx[t]] += w
    return W


def propagate(nodes: list[str], edges: list[tuple[str, str, float]], shock: dict[str, float], K: int) -> dict:
    """x_k = W' x_k-1 for k = 1..K; returns each order's vector and their sum (the shock itself is not included)."""
    W = link_matrix(nodes, edges)
    x = np.zeros(len(nodes))
    for n, v in shock.items():
        x[nodes.index(n)] = v
    orders, total = [], np.zeros(len(nodes))
    for _ in range(K):
        x = W.T @ x
        orders.append(x.copy())
        total += x
    return {"orders": orders, "total": total}


def leontief_total(nodes, edges, shock) -> np.ndarray:
    """The infinite-order sum [(I - W')^-1 - I] x0, defined when the spectral radius is below 1."""
    W = link_matrix(nodes, edges)
    x0 = np.zeros(len(nodes))
    for n, v in shock.items():
        x0[nodes.index(n)] = v
    return np.linalg.solve(np.eye(len(nodes)) - W.T, x0) - x0


def spectral_radius(nodes, edges) -> float:
    return float(np.max(np.abs(np.linalg.eigvals(link_matrix(nodes, edges)))))
