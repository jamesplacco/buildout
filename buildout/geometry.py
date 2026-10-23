"""The shape of the market: geometry, topology and transport applied to 156 years of returns, each idea tested for
whether it says anything about what came next.

    covariance   every 36-month window of stocks, 10-year Treasuries and gold is a covariance matrix, a point on the
                 curved space of positive-definite matrices. Distances there (affine-invariant: how much one window's
                 risk must be stretched to become another's) find the past windows whose structure looks most like
                 today's; a classical multidimensional scaling of the log-Euclidean distances draws 150 years of market
                 structure as a path on a page; the Frechet mean is the typical structure of an era
    spectrum     random matrix theory on the atlas's monthly series since 1990: the eigenvalues of a correlation matrix
                 that rise above the Marchenko-Pastur edge are real common factors, the rest is noise of a finite
                 sample; the absorption ratio (the share of variance the top fifth of eigenvectors absorbs) measures how
                 tightly markets move together, and its jumps are tested as a warning of drawdowns
    topology     persistent homology of the same correlation geometry (distance sqrt(2 (1 - rho))): how components merge
                 (H0, the minimum spanning tree) and how loops appear and die (H1, by reducing the boundary matrix of the
                 Vietoris-Rips filtration over the two-field) as the scale grows; total persistence through time is
                 tested as an early warning
    transport    Wasserstein distances between whole distributions of returns (sorted samples in one dimension, sliced
                 over random directions in three): the past windows whose distribution, not only whose mean and
                 variance, matches today's, and the Bures distance between regimes
    paths        the Levy area of the two-dimensional path of cumulative stock and bond returns, the second level of the
                 path signature: which of the two has been leading the other
    scaling      detrended fluctuation analysis: the Hurst exponent of returns by era (0.5 a random walk, above it
                 trending, below it mean-reverting)
    compounding  the geometry of growth: the geometric mean against the arithmetic, and how closely the volatility drag
                 sigma^2 / 2 explains the gap, decade by decade

Every predictive claim is walked forward (only windows whose outcome was known), scored against a benchmark, and its
p-value is corrected across all the tests here (Benjamini-Hochberg).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .core import cache

W = 36                  # months in a window
H = 12                  # months ahead
GAP = 36                # analogs at least this far apart, and this far from the present
K_AN = 8
SEED = 29


# ---------------------------------------------------------------- covariance geometry
def rolling_cov(X: np.ndarray, w: int = W) -> np.ndarray:
    """Covariance of every trailing window at once from cumulative sums of outer products: [T, d, d], NaN before w."""
    T, d = X.shape
    O = np.einsum("ti,tj->tij", X, X)
    cO = np.concatenate([np.zeros((1, d, d)), np.cumsum(O, 0)])
    cX = np.concatenate([np.zeros((1, d)), np.cumsum(X, 0)])
    out = np.full((T, d, d), np.nan)
    sO = cO[w:] - cO[:-w]
    sX = cX[w:] - cX[:-w]
    out[w - 1:] = (sO - np.einsum("ti,tj->tij", sX, sX) / w) / (w - 1)
    return out


def spd_fn(S: np.ndarray, fn) -> np.ndarray:
    """Apply a scalar function to a stack of symmetric positive-definite matrices through their eigenvalues."""
    lam, U = np.linalg.eigh(S)
    return np.einsum("...ij,...j,...kj->...ik", U, fn(lam), U)


def log_euclid(C: np.ndarray, floor: float = 1e-10) -> np.ndarray:
    return spd_fn(C, lambda v: np.log(np.maximum(v, floor)))


def affine_invariant(A: np.ndarray, Bs: np.ndarray) -> np.ndarray:
    """d(A, B) = || log(A^-1/2 B A^-1/2) ||_F for one A against a stack of B: unchanged if every asset is rescaled or the
    assets are mixed, so it compares the shape of risk, not its units."""
    Wm = spd_fn(A, lambda v: 1 / np.sqrt(v))
    M = Wm @ Bs @ Wm
    lam = np.linalg.eigvalsh(M)
    return np.sqrt((np.log(np.maximum(lam, 1e-12)) ** 2).sum(-1))


def frechet_mean(Cs: np.ndarray) -> np.ndarray:
    """The log-Euclidean mean: average the matrix logarithms, map back."""
    return spd_fn(log_euclid(Cs).mean(0), np.exp)


def bures(m1, S1, m2, S2) -> float:
    """2-Wasserstein distance between two normal distributions (the Bures metric on their covariances)."""
    r2 = spd_fn(S2, np.sqrt)
    cross = spd_fn(r2 @ S1 @ r2, np.sqrt)
    return float(math.sqrt(max(float(np.sum((np.asarray(m1) - np.asarray(m2)) ** 2) + np.trace(S1 + S2 - 2 * cross)), 0.0)))


def classical_mds(D: np.ndarray, k: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Points in k dimensions whose distances best match D: the top eigenvectors of the double-centred squared
    distances. Returns the coordinates and the share of the structure each axis carries."""
    n = len(D)
    J = np.eye(n) - 1.0 / n
    B = -0.5 * J @ (D ** 2) @ J
    lam, U = np.linalg.eigh(B)
    o = np.argsort(lam)[::-1]
    lam, U = lam[o], U[:, o]
    pos = np.maximum(lam, 0)
    return U[:, :k] * np.sqrt(pos[:k]), pos[:k] / max(pos.sum(), 1e-300)


def analogs(dist: np.ndarray, t: int, ok_until: int, k: int = K_AN, gap: int = GAP) -> list[int]:
    """The k nearest windows ending at or before ok_until, at least `gap` months apart from each other."""
    cand = np.argsort(dist[:ok_until + 1])
    out: list[int] = []
    for j in cand:
        if not np.isfinite(dist[j]):
            continue
        if all(abs(int(j) - i) >= gap for i in out):
            out.append(int(j))
        if len(out) == k:
            break
    del t
    return out


def forward(x: np.ndarray, h: int = H) -> np.ndarray:
    """Compound return over the next h months for each month (NaN where not yet known)."""
    lx = np.log1p(x)
    c = np.concatenate([[0.0], np.cumsum(lx)])
    out = np.full(len(x), np.nan)
    n = len(x) - h
    if n > 0:
        out[:n] = np.expm1(c[1 + h:1 + h + n] - c[1:1 + n])
    return out


def forward_vol(x: np.ndarray, h: int = H) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for t in range(len(x) - h):
        out[t] = float(np.std(x[t + 1:t + 1 + h], ddof=1) * math.sqrt(12))
    return out


def oos_skill(y: np.ndarray, f: np.ndarray, b: np.ndarray) -> dict:
    from . import ml
    m = np.isfinite(y) & np.isfinite(f) & np.isfinite(b)
    e, eb = y[m] - f[m], y[m] - b[m]
    if m.sum() < 60:
        return {"n": int(m.sum()), "skill": None, "t": None, "p": None}
    dm = ml.diebold_mariano(e, eb, lags=H)
    return {"n": int(m.sum()), "skill": float(1 - (e ** 2).mean() / (eb ** 2).mean()), "t": float(dm["t"]), "p": float(dm["p_one_sided"])}


def covariance_study(D: pd.DataFrame, start_year: int = 1940) -> dict:
    """Geometric analogs walked forward: at each month from start_year, the 8 past windows nearest today's by the
    affine-invariant distance, among windows whose next 12 months had ended; their average next-12-month stock return
    and realized volatility as forecasts, against the historical mean and against today's trailing volatility."""
    X = D[["stocks", "bonds", "gold"]].to_numpy()
    T = len(X)
    C = rolling_cov(X)
    valid = np.isfinite(C[:, 0, 0])
    C[valid] += np.eye(3)[None] * 1e-8
    s = X[:, 0]
    fr, fv = forward(s), forward_vol(s)
    trail_vol = np.full(T, np.nan)
    trail_vol[W - 1:] = np.sqrt(C[W - 1:, 0, 0] * 12)
    start = int(np.searchsorted(D.index.year, start_year))
    f_ret, f_vol, b_ret = np.full(T, np.nan), np.full(T, np.nan), np.full(T, np.nan)
    for t in range(max(start, W + GAP + H), T):
        ok = t - W                                            # windows that do not overlap today's, so their outcome was known
        d = np.full(T, np.inf)
        idx = np.flatnonzero(valid[:ok + 1])
        d[idx] = affine_invariant(C[t], C[idx])
        an = analogs(d, t, ok)
        if len(an) < K_AN // 2:
            continue
        f_ret[t] = float(np.nanmean(fr[an]))
        f_vol[t] = float(np.nanmean(fv[an]))
        b_ret[t] = float(np.nanmean(fr[:ok + 1]))
    # today
    t = T - 1
    ok = t - W
    d_now = np.full(T, np.inf)
    idx = np.flatnonzero(valid[:ok + 1])
    d_now[idx] = affine_invariant(C[t], C[idx])
    an = analogs(d_now, t, ok)
    dates = [x.strftime("%Y-%m") for x in D.index]
    sd = lambda Cm: np.sqrt(np.diag(Cm) * 12)
    corr = lambda Cm: (Cm / np.outer(np.sqrt(np.diag(Cm)), np.sqrt(np.diag(Cm))))
    now_analogs = [{"date": dates[j], "distance": float(d_now[j]), "next12_stocks": None if not np.isfinite(fr[j]) else float(fr[j]),
                    "next12_vol": None if not np.isfinite(fv[j]) else float(fv[j]), "vol": sd(C[j]).tolist(), "corr_sb": float(corr(C[j])[0, 1])} for j in an]
    # the map: one point per year (December windows), classical MDS of log-Euclidean distances
    yr = [i for i, x in enumerate(D.index) if x.month == 12 and valid[i]] + ([T - 1] if D.index[-1].month != 12 else [])
    L = log_euclid(C[yr]).reshape(len(yr), -1)
    G = L @ L.T
    sq = np.diag(G)
    Dm = np.sqrt(np.maximum(sq[:, None] + sq[None, :] - 2 * G, 0))       # every pairwise distance from one Gram matrix
    xy, share = classical_mds(Dm, 2)
    eras = {"1871-1913": (1871, 1913), "1914-1945": (1914, 1945), "1946-1972": (1946, 1972), "1973-1999": (1973, 1999), "2000-2019": (2000, 2019), "2020-now": (2020, 2100)}
    era_means = {}
    for name, (a, b) in eras.items():
        sel = [i for i, x in enumerate(D.index) if a <= x.year <= b and valid[i]]
        if sel:
            M = frechet_mean(C[sel])
            era_means[name] = {"vol": sd(M).tolist(), "corr_sb": float(corr(M)[0, 1]), "corr_sg": float(corr(M)[0, 2]),
                               "distance_now": float(affine_invariant(C[T - 1], M[None])[0])}
    return {
        "window": W, "now": {"date": dates[-1], "vol": sd(C[T - 1]).tolist(), "corr": corr(C[T - 1]).tolist(), "analogs": now_analogs,
                             "analog_next12": float(np.nanmean([a["next12_stocks"] for a in now_analogs if a["next12_stocks"] is not None])) if now_analogs else None,
                             "analog_vol": float(np.nanmean([a["next12_vol"] for a in now_analogs if a["next12_vol"] is not None])) if now_analogs else None,
                             "uncond_next12": float(np.nanmean(fr))},
        "tests": {"return": oos_skill(fr, f_ret, b_ret), "volatility": oos_skill(fv, f_vol, trail_vol)},
        "map": {"years": [D.index[i].year if i != T - 1 or D.index[-1].month == 12 else dates[-1] for i in yr], "x": xy[:, 0].tolist(), "y": xy[:, 1].tolist(),
                "share": share.tolist(), "corr_sb": [float(corr(C[i])[0, 1]) for i in yr], "vol_s": [float(sd(C[i])[0]) for i in yr]},
        "eras": era_means,
    }


# ---------------------------------------------------------------- spectrum
def mp_edges(q: float, sigma2: float = 1.0) -> tuple[float, float]:
    """Marchenko-Pastur support for the eigenvalues of a correlation matrix of pure noise with N/T = q."""
    return sigma2 * (1 - math.sqrt(q)) ** 2, sigma2 * (1 + math.sqrt(q)) ** 2


def mp_density(x: np.ndarray, q: float) -> np.ndarray:
    lo, hi = mp_edges(q)
    with np.errstate(invalid="ignore", divide="ignore"):
        d = np.sqrt(np.maximum((hi - x) * (x - lo), 0)) / (2 * math.pi * q * x)
    return np.where((x > lo) & (x < hi), d, 0.0)


def window_corr(P: pd.DataFrame, end: int, w: int, min_frac: float = 0.95) -> tuple[np.ndarray | None, list[str]]:
    seg = P.iloc[end - w + 1:end + 1]
    keep = [c for c in seg if seg[c].notna().mean() >= min_frac and seg[c].std() > 0]
    if len(keep) < 5:
        return None, keep
    Z = seg[keep]
    Z = (Z - Z.mean()) / Z.std()
    Z = Z.fillna(0.0).to_numpy()
    R = (Z.T @ Z) / (len(Z) - 1)
    d = np.sqrt(np.diag(R))
    return R / np.outer(d, d), keep


def spectrum_study(P: pd.DataFrame, sp: pd.Series, w: int = 60, step: int = 1) -> dict:
    """Eigenvalues of rolling correlation matrices against the Marchenko-Pastur edge; the absorption ratio and its
    one-year jump; a walk-forward test of whether a jump warns of a fall of 10% or more in the next 12 months."""
    T = len(P)
    rows = []
    for e in range(w - 1, T, step):
        R, keep = window_corr(P, e, w)
        if R is None:
            continue
        lam = np.linalg.eigvalsh(R)[::-1]
        N = len(keep)
        q = N / w
        lo, hi = mp_edges(q)
        k = max(1, N // 5)
        rows.append({"i": e, "date": P.index[e].strftime("%Y-%m"), "N": N, "above": int((lam > hi).sum()), "ar": float(lam[:k].sum() / N),
                     "top": float(lam[0] / N), "edge": hi})
    df = pd.DataFrame(rows).set_index("i")
    ar = df["ar"]
    shift = (ar - ar.rolling(12).mean()) / ar.rolling(36).std()
    # S&P 500 log changes from the atlas panel: next-12-month change and the worst drawdown within it
    s = sp.reindex(P.index).to_numpy()
    lvl = np.exp(np.nancumsum(np.nan_to_num(s)))
    fwd_dd = np.full(T, np.nan)
    for t in range(T - H):
        path = lvl[t + 1:t + 1 + H] / lvl[t]
        fwd_dd[t] = float(path.min() - 1)
    fall = fwd_dd <= -0.10
    sig = pd.Series(np.nan, index=range(T))
    sig[df.index] = shift.to_numpy()
    sv = sig.to_numpy()
    ok = np.isfinite(sv) & np.isfinite(fwd_dd)
    hi_m = ok & (sv > 1)
    lo_m = ok & (sv <= 1)
    p_hi = float(fall[hi_m].mean()) if hi_m.any() else None
    p_lo = float(fall[lo_m].mean()) if lo_m.any() else None
    pval = _two_prop_p(fall[hi_m], fall[lo_m], blocks=H)
    R, keep = window_corr(P, T - 1, 120)
    lam, V = np.linalg.eigh(R)
    lam, V = lam[::-1], V[:, ::-1]
    q = len(keep) / 120
    factors = []
    for f in range(int((lam > mp_edges(q)[1]).sum())):
        v = V[:, f] * (1 if V[:, f].sum() >= 0 else -1)
        o = np.argsort(-np.abs(v))[:6]
        factors.append({"share": float(lam[f] / len(keep)), "top": [{"name": keep[i], "loading": float(v[i])} for i in o]})
    grid = np.linspace(1e-3, max(lam.max() * 1.05, mp_edges(q)[1] * 1.2), 200)
    return {"window": w, "series": {"dates": df["date"].tolist()[::3], "ar": [round(v, 4) for v in df["ar"].tolist()[::3]],
                                    "above": df["above"].tolist()[::3], "N": df["N"].tolist()[::3], "shift": [None if not np.isfinite(v) else round(float(v), 3) for v in shift.to_numpy()[::3]]},
            "now": {"date": P.index[-1].strftime("%Y-%m"), "N": len(keep), "T": 120, "q": q, "edges": mp_edges(q), "eigen": lam.tolist(), "above": int((lam > mp_edges(q)[1]).sum()),
                    "ar": float(df["ar"].iloc[-1]), "shift": None if not np.isfinite(shift.iloc[-1]) else float(shift.iloc[-1]), "factors": factors,
                    "mp": {"x": grid.tolist(), "density": mp_density(grid, q).tolist()}},
            "test": {"p_fall_after_jump": p_hi, "p_fall_otherwise": p_lo, "months_jump": int(hi_m.sum()), "months_other": int(lo_m.sum()), "p": pval}}


def _two_prop_p(a: np.ndarray, b: np.ndarray, blocks: int = 12, B: int = 2000, seed: int = SEED) -> float | None:
    """One-sided p-value that the event is more frequent in a than in b, by permuting labels in blocks of `blocks`
    months (overlapping 12-month outcomes are not independent, so single months must not be shuffled)."""
    if len(a) < 12 or len(b) < 12:
        return None
    x = np.concatenate([a, b]).astype(float)
    lab = np.concatenate([np.ones(len(a)), np.zeros(len(b))])
    obs = x[lab == 1].mean() - x[lab == 0].mean()
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(len(x) / blocks))
    cnt = 0
    for _ in range(B):
        perm = np.concatenate([np.arange(i * blocks, min((i + 1) * blocks, len(x))) for i in rng.permutation(nb)])
        l2 = lab[perm]
        d = x[l2 == 1].mean() - x[l2 == 0].mean() if (l2 == 1).any() and (l2 == 0).any() else 0.0
        cnt += d >= obs
    return float((cnt + 1) / (B + 1))


# ---------------------------------------------------------------- topology
def mst_h0(Dm: np.ndarray) -> np.ndarray:
    """H0 deaths of the Vietoris-Rips filtration: the edge lengths of the minimum spanning tree (Prim, O(n^2))."""
    n = len(Dm)
    seen = np.zeros(n, bool)
    best = np.full(n, np.inf)
    best[0] = 0
    out = []
    for _ in range(n):
        i = int(np.argmin(np.where(seen, np.inf, best)))
        if best[i] > 0:
            out.append(best[i])
        seen[i] = True
        best = np.minimum(best, Dm[i])
    return np.sort(np.array(out))


def rips_h1(Dm: np.ndarray, rmax: float | None = None) -> list[tuple[float, float]]:
    """H1 persistence pairs (birth, death) of the Vietoris-Rips filtration up to triangles, by the standard column
    reduction of the edge-to-triangle boundary matrix over the two-element field (bitsets as Python integers)."""
    n = len(Dm)
    iu = np.triu_indices(n, 1)
    el = Dm[iu]
    if rmax is not None:
        keep = el <= rmax
    else:
        keep = np.ones(len(el), bool)
    E = sorted(zip(el[keep], iu[0][keep], iu[1][keep]))
    eid = {(int(a), int(b)): k for k, (_, a, b) in enumerate(E)}
    tris = []
    for a in range(n):
        for b in range(a + 1, n):
            if (a, b) not in eid:
                continue
            for c in range(b + 1, n):
                if (a, c) in eid and (b, c) in eid:
                    f = max(E[eid[(a, b)]][0], E[eid[(a, c)]][0], E[eid[(b, c)]][0])
                    tris.append((f, eid[(a, b)], eid[(a, c)], eid[(b, c)]))
    tris.sort()
    # which edges create H1 classes: an edge is negative (kills H0) if it joins two components (union-find in filtration order)
    par = list(range(n))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    negative = set()
    for k, (_, a, b) in enumerate(E):
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            par[ra] = rb
            negative.add(k)
    low_of: dict[int, int] = {}
    pairs = []
    for f, e1, e2, e3 in tris:
        col = (1 << e1) ^ (1 << e2) ^ (1 << e3)
        while col:
            low = col.bit_length() - 1
            if low in low_of:
                col ^= low_of[low]
            else:
                low_of[low] = col
                birth = E[low][0]
                if f > birth:
                    pairs.append((float(birth), float(f)))
                break
    killed = {k for k in low_of}
    for k, (f, _, _) in enumerate(E):
        if k not in negative and k not in killed:
            pairs.append((float(f), math.inf))
    return pairs


def topology_study(P: pd.DataFrame, sp: pd.Series, w: int = 60, step: int = 3, max_series: int = 30) -> dict:
    """Rolling persistent homology of the correlation geometry of the most complete series; total persistence of H0
    and H1 through time; a walk-forward test of whether a jump in H1 total persistence warns of a 10% fall."""
    T = len(P)
    cover = P.notna().mean().sort_values(ascending=False)
    cols = list(cover.index[:max_series])
    rows = []
    for e in range(w - 1, T, step):
        R, keep = window_corr(P[cols], e, w)
        if R is None:
            continue
        Dm = np.sqrt(np.maximum(2 * (1 - R), 0))
        h0 = mst_h0(Dm)
        h1 = [(b, d) for b, d in rips_h1(Dm, rmax=1.2) if math.isfinite(d)]
        rows.append({"i": e, "date": P.index[e].strftime("%Y-%m"), "N": len(keep), "h0": float(h0.sum()), "h1": float(sum(d - b for b, d in h1)), "n1": len(h1)})
    df = pd.DataFrame(rows).set_index("i")
    s = sp.reindex(P.index).to_numpy()
    lvl = np.exp(np.nancumsum(np.nan_to_num(s)))
    fwd_dd = np.full(T, np.nan)
    for t in range(T - H):
        fwd_dd[t] = float((lvl[t + 1:t + 1 + H] / lvl[t]).min() - 1)
    z = (df["h1"] - df["h1"].rolling(8).mean()) / df["h1"].rolling(16).std()
    zz = pd.Series(np.nan, index=range(T))
    zz[df.index] = z.to_numpy()
    zv = zz.to_numpy()
    ok = np.isfinite(zv) & np.isfinite(fwd_dd)
    fall = fwd_dd <= -0.10
    hi_m, lo_m = ok & (zv > 1), ok & (zv <= 1)
    R, keep = window_corr(P[cols], T - 1, w)
    Dm = np.sqrt(np.maximum(2 * (1 - R), 0))
    h0 = mst_h0(Dm)
    h1 = rips_h1(Dm, rmax=1.2)
    return {"window": w, "series": {"dates": df["date"].tolist(), "h0": [round(v, 4) for v in df["h0"]], "h1": [round(v, 4) for v in df["h1"]], "n1": df["n1"].tolist()},
            "now": {"date": P.index[-1].strftime("%Y-%m"), "names": keep, "h0": h0.tolist(), "h1": [[b, d if math.isfinite(d) else None] for b, d in h1],
                    "mst": _mst_edges(Dm, keep)},
            "test": {"p_fall_after_jump": float(fall[hi_m].mean()) if hi_m.any() else None, "p_fall_otherwise": float(fall[lo_m].mean()) if lo_m.any() else None,
                     "months_jump": int(hi_m.sum()), "months_other": int(lo_m.sum()), "p": _two_prop_p(fall[hi_m], fall[lo_m], blocks=4)}}


def _mst_edges(Dm: np.ndarray, names: list[str]) -> list[dict]:
    n = len(Dm)
    seen = np.zeros(n, bool)
    best = np.full(n, np.inf)
    src = np.full(n, -1)
    best[0] = 0
    out = []
    for _ in range(n):
        i = int(np.argmin(np.where(seen, np.inf, best)))
        if src[i] >= 0:
            out.append({"a": names[int(src[i])], "b": names[i], "d": float(Dm[i, src[i]])})
        seen[i] = True
        upd = Dm[i] < best
        src[upd & ~seen] = i
        best = np.minimum(best, Dm[i])
    return out


# ---------------------------------------------------------------- transport
def sliced_w(A: np.ndarray, B: np.ndarray, dirs: np.ndarray) -> float:
    """Sliced 1-Wasserstein distance between two equal-size samples: project on each direction, sort, compare."""
    pa = np.sort(A @ dirs.T, 0)
    pb = np.sort(B @ dirs.T, 0)
    return float(np.abs(pa - pb).mean())


def transport_study(D: pd.DataFrame, start_year: int = 1940, n_dirs: int = 64) -> dict:
    """Distributional analogs: the past 36-month windows whose joint distribution of stock, bond and gold returns is
    nearest today's in sliced Wasserstein distance (all windows at once: sort every window's projections, one
    broadcast), and a walk-forward test of their next-12-month stock return against the historical mean."""
    X = D[["stocks", "bonds", "gold"]].to_numpy()
    X = (X - X.mean(0)) / X.std(0)
    T = len(X)
    rng = np.random.default_rng(SEED)
    dirs = rng.normal(size=(n_dirs, 3))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    proj = X @ dirs.T                                                        # [T, n_dirs]
    win = np.lib.stride_tricks.sliding_window_view(proj, W, axis=0)          # [T-W+1, n_dirs, W]
    S = np.sort(win, axis=-1)                                                # every window's sorted projections
    ends = np.arange(W - 1, T)
    fr = forward(D["stocks"].to_numpy())
    start = int(np.searchsorted(D.index.year, start_year))
    f_ret, b_ret = np.full(T, np.nan), np.full(T, np.nan)
    for t in range(max(start, W + GAP + H), T, 1):
        ok = t - W
        m = ends <= ok
        d = np.full(T, np.inf)
        d[ends[m]] = np.abs(S[m] - S[t - W + 1][None]).mean(axis=(1, 2))
        an = analogs(d, t, ok)
        if len(an) < K_AN // 2:
            continue
        f_ret[t] = float(np.nanmean(fr[an]))
        b_ret[t] = float(np.nanmean(fr[:ok + 1]))
    t = T - 1
    ok = t - W
    m = ends <= ok
    d = np.full(T, np.inf)
    d[ends[m]] = np.abs(S[m] - S[t - W + 1][None]).mean(axis=(1, 2))
    an = analogs(d, t, ok)
    dates = [x.strftime("%Y-%m") for x in D.index]
    return {"window": W, "directions": n_dirs, "now": {"analogs": [{"date": dates[j], "distance": float(d[j]), "next12_stocks": None if not np.isfinite(fr[j]) else float(fr[j])} for j in an]},
            "test": {"return": oos_skill(fr, f_ret, b_ret)}}


# ---------------------------------------------------------------- paths
def levy_area(x: np.ndarray, y: np.ndarray) -> float:
    """Signed area between the path (x, y) and its chord: positive when moves in x tend to come before moves in y."""
    x = x - x[0]
    y = y - y[0]
    return float(0.5 * np.sum(x[:-1] * np.diff(y) - y[:-1] * np.diff(x)))


def paths_study(D: pd.DataFrame, w: int = W) -> dict:
    """Rolling Levy area of cumulative (stocks, bonds), each scaled to unit variance in the window, and a test of
    whether it says anything about the next 12 months' stock-bond correlation beyond today's correlation."""
    s, b = D["stocks"].to_numpy(), D["bonds"].to_numpy()
    T = len(s)
    area = np.full(T, np.nan)
    corr = np.full(T, np.nan)
    for e in range(w - 1, T):
        xs, xb = s[e - w + 1:e + 1], b[e - w + 1:e + 1]
        zs, zb = (xs - xs.mean()) / xs.std(), (xb - xb.mean()) / xb.std()
        area[e] = levy_area(np.concatenate([[0], np.cumsum(zs)]), np.concatenate([[0], np.cumsum(zb)])) / w
        corr[e] = float(np.corrcoef(xs, xb)[0, 1])
    fut = np.full(T, np.nan)
    for t in range(T - H):
        fut[t] = float(np.corrcoef(s[t + 1:t + 1 + H], b[t + 1:t + 1 + H])[0, 1])
    m = np.isfinite(area) & np.isfinite(fut) & np.isfinite(corr)
    from . import labs
    fit = labs.nw_ols(fut[m], np.column_stack([corr[m], area[m]]), H)
    dates = [x.strftime("%Y-%m") for x in D.index]
    k = np.flatnonzero(np.isfinite(area))
    return {"window": w, "series": {"dates": [dates[i] for i in k[::6]], "area": [round(float(area[i]), 4) for i in k[::6]], "corr": [round(float(corr[i]), 4) for i in k[::6]]},
            "now": {"area": float(area[-1]), "corr": float(corr[-1]),
                    "path": {"stocks": np.concatenate([[0], np.cumsum(s[-w:])]).tolist(), "bonds": np.concatenate([[0], np.cumsum(b[-w:])]).tolist()}},
            "test": {"coef_area": float(fit["b"][2]), "t": float(fit["t"][2]), "p": float(2 * (1 - _ncdf(abs(fit["t"][2]))))}}


def _ncdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# ---------------------------------------------------------------- scaling and compounding
def dfa_hurst(x: np.ndarray, scales=(4, 6, 8, 12, 16, 24, 32, 48)) -> float:
    """Detrended fluctuation analysis: the slope of log F(n) on log n for the integrated, mean-removed series."""
    y = np.cumsum(x - x.mean())
    F = []
    used = []
    for n in scales:
        m = len(y) // n
        if m < 4:
            continue
        seg = y[:m * n].reshape(m, n)
        t = np.arange(n)
        A = np.column_stack([t, np.ones(n)])
        coef, *_ = np.linalg.lstsq(A, seg.T, rcond=None)
        res = seg.T - A @ coef
        F.append(math.sqrt(float((res ** 2).mean())))
        used.append(n)
    sl, _ = np.polyfit(np.log(used), np.log(F), 1)
    return float(sl)


def scaling_study(D: pd.DataFrame, seed: int = SEED) -> dict:
    s = D["stocks"].to_numpy()
    yrs = D.index.year
    rows = []
    for a in range(1871, 2026, 20):
        m = (yrs >= a) & (yrs < a + 20)
        if m.sum() < 120:
            continue
        rows.append({"era": f"{a} to {min(a + 19, yrs.max())}", "hurst": dfa_hurst(s[m]), "hurst_abs": dfa_hurst(np.abs(s[m] - s[m].mean()))})
    rng = np.random.default_rng(seed)
    null = [dfa_hurst(rng.permutation(s)) for _ in range(200)]
    null_a = [dfa_hurst(np.abs(z - z.mean())) for z in (rng.permutation(s) for _ in range(200))]
    ac1 = float(np.corrcoef(s[:-1], s[1:])[0, 1])
    m = yrs >= 1990
    ac1_recent = float(np.corrcoef(s[m][:-1], s[m][1:])[0, 1])
    return {"eras": rows, "all": dfa_hurst(s), "all_abs": dfa_hurst(np.abs(s - s.mean())), "null_q05": float(np.quantile(null, 0.05)), "null_q95": float(np.quantile(null, 0.95)),
            "null_abs_q05": float(np.quantile(null_a, 0.05)), "null_abs_q95": float(np.quantile(null_a, 0.95)), "ac1": ac1, "ac1_since_1990": ac1_recent}


def compounding_study(D: pd.DataFrame) -> list[dict]:
    """By decade, in annual rates: the arithmetic mean (12 times the average month), the geometric rate (12 times the
    average log return: what a holder actually compounded at) and the volatility drag sigma^2 / 2 that, to second order,
    is the gap between them. A decade's gap above the drag means fat tails or skew cost more than variance alone."""
    s = D["stocks"].to_numpy()
    yrs = D.index.year
    out = []
    for a in range(1870, 2030, 10):
        m = (yrs >= a) & (yrs < a + 10)
        if m.sum() < 60:
            continue
        x = s[m]
        ar = float(x.mean() * 12)
        geo = float(np.log1p(x).mean() * 12)
        drag = float(x.var(ddof=1) * 12 / 2)
        out.append({"decade": f"{a}s", "arithmetic": ar, "geometric": geo, "gap": ar - geo, "drag": drag, "vol": float(x.std(ddof=1) * math.sqrt(12)), "months": int(m.sum())})
    return out


def engine_model_study(dl: dict, gh: dict, placebo_draws: int = 20, seed: int = SEED) -> dict:
    """The decision engine's geometric-analog model (decide.geo_walk) scored on its own: each month's predictive log
    score against the long-run average's, walked forward from 1940, with Newey-West errors. Then the placebo that
    matters: the same model built from 8 windows drawn at random (averaged over draws) and from the 8 farthest windows.
    If random windows score as well as the nearest ones, the gain comes from mixing several past years (fat tails),
    not from the geometry."""
    from . import decide, labs, ml
    D = decide.data(labs.shiller(dl), gh)
    start = int(np.searchsorted(D.index.year, decide.START))
    g = decide.geo_walk(D, start)
    r = D["r"].to_numpy()
    T = len(r)
    X = D[["r", "b"]].to_numpy()
    ok = np.isfinite(X).all(1)
    C = rolling_cov(np.nan_to_num(X), decide.GEO_W) + np.eye(2)[None] * 1e-10
    run = np.convolve(ok.astype(float), np.ones(decide.GEO_W), "full")[:T]
    good = np.zeros(T, bool)
    good[decide.GEO_W - 1:] = run[decide.GEO_W - 1:] >= decide.GEO_W - 1e-9
    rng = np.random.default_rng(seed)
    lam = 12 / (12 + decide.GEO_N0)

    def lls(w, mu, sd, x):
        return math.log(max(float((w * np.exp(-0.5 * ((x - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))).sum()), 1e-300))

    def from_windows(an, m0, v0, x):
        nxt = np.array([r[j + 1:j + 13] for j in an])
        return lls(np.full(len(an), 1 / len(an)), m0 + lam * (nxt.mean(1) - m0), np.sqrt(0.5 * nxt.var(1) + 0.5 * v0), x)
    d_geo, d_rand, d_far = [], [], []
    for t in range(start, T):
        e = t - decide.LAG
        past = r[:e + 1]
        m0, v0 = float(past.mean()), float(past.var())
        base = lls(np.ones(1), np.array([m0]), np.array([math.sqrt(v0)]), r[t])
        d_geo.append(lls(g["w"][t], g["mu"][t], g["sd"][t], r[t]) - base)
        cand = np.flatnonzero(good[:max(e - decide.GEO_W + 1, 0)])
        cand = cand[cand + 12 <= e]
        if len(cand) < decide.GEO_K * 3 or not good[e]:
            d_rand.append(d_geo[-1])
            d_far.append(d_geo[-1])
            continue
        d_rand.append(float(np.mean([from_windows(rng.choice(cand, decide.GEO_K, replace=False), m0, v0, r[t]) for _ in range(placebo_draws)])) - base)
        dist = np.full(T, np.inf)
        dist[cand] = -affine_invariant(C[e], C[cand])
        d_far.append(from_windows(analogs(dist, e, int(cand[-1]), k=decide.GEO_K, gap=decide.GEO_W), m0, v0, r[t]) - base)
    d_geo, d_rand, d_far = map(np.array, (d_geo, d_rand, d_far))

    def tstat(x):
        return float(x.mean() / math.sqrt(ml.nw_var(x, 12)))
    tt = tstat(d_geo)
    tg = tstat(d_geo - d_rand)
    return {"months": int(len(d_geo)), "mean_gain": float(d_geo.mean()), "t": tt, "p": float(1 - _ncdf(tt)),
            "placebo": {"random_gain": float(d_rand.mean()), "random_t": tstat(d_rand), "farthest_gain": float(d_far.mean()), "farthest_t": tstat(d_far),
                        "geometry_over_random": float((d_geo - d_rand).mean()), "geometry_t": tg, "geometry_p": float(1 - _ncdf(tg)),
                        "nearest_over_farthest": float((d_geo - d_far).mean()), "nearest_far_t": tstat(d_geo - d_far), "draws": placebo_draws}}


# ---------------------------------------------------------------- build
@cache.memo("geometry.build", deps=("buildout.portfolio", "buildout.atlas", "buildout.labs", "buildout.ml", "buildout.decide"), require=("dl", "gh"))
def build(dl: dict | None = None, gh: dict | None = None, atlas_dl: dict | None = None) -> dict:
    from . import atlas, labs, portfolio
    S = labs.shiller(dl)
    D, notes = portfolio.panel(S, gh or {})
    out = {"schema": 1, "notes": notes}
    out["covariance"] = covariance_study(D)
    out["transport"] = transport_study(D)
    out["paths"] = paths_study(D)
    out["scaling"] = scaling_study(D)
    out["compounding"] = compounding_study(D)
    out["engine_model"] = engine_model_study(dl, gh or {})
    if atlas_dl is not None:
        P, meta = atlas.panel(atlas_dl)
        out["labels"] = {k: {"name": m.get("short") or m.get("name") or k, "family": m.get("family", "")} for k, m in meta.items()}
        out["spectrum"] = spectrum_study(P, P["sp500"])
        out["topology"] = topology_study(P, P["sp500"])
    tests = [("Covariance analogs: next-12-month stock return", out["covariance"]["tests"]["return"].get("p")),
             ("Covariance analogs: next-12-month volatility", out["covariance"]["tests"]["volatility"].get("p")),
             ("Distributional analogs: next-12-month stock return", out["transport"]["test"]["return"].get("p")),
             ("Levy area: next-12-month stock-bond correlation", out["paths"]["test"]["p"]),
             ("Engine's analog model: next-month density against the long-run average", out["engine_model"]["p"]),
             ("Engine's analog model: nearest windows against random windows (placebo)", out["engine_model"]["placebo"]["geometry_p"])]
    if "spectrum" in out:
        tests.append(("Absorption-ratio jump: a 10% fall within 12 months", out["spectrum"]["test"]["p"]))
    if "topology" in out:
        tests.append(("Loop persistence jump: a 10% fall within 12 months", out["topology"]["test"]["p"]))
    ps = [p if p is not None else 1.0 for _, p in tests]
    adj = labs.bh(ps)
    out["tests"] = [{"test": n, "p": p, "q": q} for (n, p), q in zip(tests, adj)]
    out["findings"] = summary(out)
    return out


def summary(o: dict) -> list[str]:
    cv, tr, em = o["covariance"], o["transport"], o["engine_model"]
    rt, vt = cv["tests"]["return"], cv["tests"]["volatility"]
    out = []
    n = cv["now"]
    pl = em["placebo"]
    out.append(f"The decision engine's new geometric-analog model, which reads next month from the 8 past 36-month windows whose stock-bond covariance is nearest "
               f"today's, beats the long-run average's predictive log score by {em['mean_gain']:.3f} a month (t {em['t']:.1f}, walked forward since 1940). The placebo "
               f"says why: 8 windows drawn at random gain {pl['random_gain']:.3f} (t {pl['random_t']:.1f}) and the 8 farthest {pl['farthest_gain']:.3f}. Most of the gain is "
               f"mixing several past years, which fattens the tails a single normal misses; the geometry itself adds {pl['geometry_over_random']:+.4f} over random "
               f"(t {pl['geometry_t']:.1f}) and {pl['nearest_over_farthest']:+.3f} over the farthest (t {pl['nearest_far_t']:.1f}).")
    if rt.get("skill") is not None and vt.get("skill") is not None:
        out.append(f"As a point forecast the same geometry fails: covariance analogs forecast the next year's stock return with skill {rt['skill']:+.0%} against the historical "
                   f"mean (t {rt['t']:.1f}) and its volatility with {vt['skill']:+.0%} against trailing volatility (t {vt['t']:.1f}); matching whole distributions "
                   f"(sliced Wasserstein) gives {tr['test']['return']['skill']:+.0%} (t {tr['test']['return']['t']:.1f}). Eight neighbours are too few to average out "
                   f"what the next year does, so the engine uses analogs for spread and keeps their means shrunk hard toward the long run.")
    an = n["analogs"]
    out.append(f"Today's three-asset structure (stocks {n['vol'][0]:.0%} volatility, Treasuries {n['vol'][1]:.0%}, gold {n['vol'][2]:.0%}, stock-bond correlation "
               f"{n['corr'][0][1]:+.2f}) sits nearest {', '.join(a['date'] for a in an[:4])}; the year after those windows returned {n['analog_next12']:+.1%} on average "
               f"against {n['uncond_next12']:+.1%} for every month, a spread the tests above say not to trade on.")
    eras = o["covariance"]["eras"]
    if eras:
        near = min(eras.items(), key=lambda kv: kv[1]["distance_now"])
        out.append(f"Of six eras, today's covariance is closest to the Frechet mean of {near[0]} (distance {near[1]['distance_now']:.2f}, against "
                   f"{max(v['distance_now'] for v in eras.values()):.1f} for the farthest)" + (": the era of floating gold and stocks and bonds that fell together." if near[0] == "1973-1999" else "."))
    if "spectrum" in o:
        sp, lab = o["spectrum"], o.get("labels", {})
        out.append(f"Random matrix theory on {sp['now']['N']} monthly series over the last ten years: {sp['now']['above']} eigenvalues rise above the Marchenko-Pastur noise edge of "
                   f"{sp['now']['edges'][1]:.2f}, so the world's markets carry about {sp['now']['above']} real common factors and the rest is noise of a finite sample"
                   + ("; " + "; ".join(f"factor {i + 1} ({f['share']:.0%} of the variance) loads most on {', '.join(lab.get(x['name'], {}).get('name', x['name']) for x in f['top'][:3])}"
                                      for i, f in enumerate(sp["now"].get("factors", [])[:2])) if sp["now"].get("factors") else "") + ". "
                   f"After the absorption ratio jumped, a 10% fall followed within a year {sp['test']['p_fall_after_jump']:.0%} of the time against "
                   f"{sp['test']['p_fall_otherwise']:.0%} otherwise (block-permutation p {sp['test']['p']:.2f}).")
    if "topology" in o:
        tp = o["topology"]
        if tp["test"]["p_fall_after_jump"] is not None:
            out.append(f"Persistent homology of the same geometry: after loops grew unusually persistent, a 10% fall followed {tp['test']['p_fall_after_jump']:.0%} of the time "
                       f"against {tp['test']['p_fall_otherwise']:.0%} (p {tp['test']['p']:.2f}), suggestive on {tp['test']['months_jump']} months but not evidence.")
    sc = o["scaling"]
    out.append(f"Monthly real stock returns have a Hurst exponent of {sc['all']:.2f} against {sc['null_q05']:.2f} to {sc['null_q95']:.2f} for the same months shuffled; "
               f"much of that is Shiller's monthly-average prices, which smooth returns (first-month autocorrelation {sc['ac1']:+.2f} over the whole sample, "
               f"{sc['ac1_since_1990']:+.2f} since 1990).")
    surv = [t for t in o["tests"] if t["q"] <= 0.10]
    out.append(f"Of {len(o['tests'])} geometric claims tested, {len(surv)} {'survives' if len(surv) == 1 else 'survive'} a 10% false-discovery rate" + (": " + "; ".join(t["test"].lower() for t in surv) + "." if surv else "."))
    return out
