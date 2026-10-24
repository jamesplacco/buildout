"""The edge-discovery engine (buildout.discovery, part two) on synthetic data: a planted edge survives every stage,
noise survives no more often than the placebos, the placebo path is the real path, no feature sees the future, the
monthly-average artifact appears without the skip month and vanishes with it, the book walks forward on past data
only, and the output is JSON-safe and in house style."""
import json

import numpy as np
import pandas as pd
import pytest

from buildout import discovery as D

IDX = pd.date_range("1990-01-01", "2026-09-01", freq="MS")
BAD = ("—", "inter" + "section", "load" + "-bearing")


def _meta(cols, fam="Synthetic"):
    return {c: {"name": c, "short": c, "family": fam} for c in cols}


def _planted(n=20, beta=0.3, seed=1):
    """Twenty markets where the sign of the 12-month change through t minus 2 predicts the month t return."""
    rng = np.random.default_rng(seed)
    T = len(IDX)
    r = np.zeros((T, n))
    e = rng.normal(0, 0.04, (T, n))
    for t in range(T):
        if t >= 14:
            sig = np.sign(r[t - 13:t - 1].sum(0))
            r[t] = 0.04 * beta * sig + e[t]
        else:
            r[t] = e[t]
    cols = [f"m{j:02d}" for j in range(n)]
    return pd.DataFrame(r, index=IDX, columns=cols)


def _noise(n=20, seed=2):
    rng = np.random.default_rng(seed)
    cols = [f"m{j:02d}" for j in range(n)]
    return pd.DataFrame(rng.normal(0, 0.04, (len(IDX), n)), index=IDX, columns=cols)


@pytest.fixture(scope="module")
def planted():
    P = _planted()
    return D.build(P, _meta(P.columns), n_placebo=30, quick=True, seed=5)


@pytest.fixture(scope="module")
def noise():
    P = _noise()
    return D.build(P, _meta(P.columns), n_placebo=60, quick=True, seed=6)


def test_planted_edge_survives_every_stage(planted):
    o = planted
    mom = [e for e in o["edges"] if e["kind"] == "own history" and e["family"] == "momentum" and e["direction"] == "follow"
           and e["group"] == "Synthetic"]
    assert mom, [e["name"] for e in o["edges"]]
    e = mom[0]
    assert e["discovery"]["t"] > 4 and e["breadth"]["pass"] and e["breadth"]["agree"] >= 15
    assert e["timing_beyond_drift"]["disc"]["t_alpha"] >= D.TIMING_T
    assert e["validation"]["t"] >= D.VAL_T and e["validation"]["net"]["mean"] > 0
    assert e["test"]["net"]["mean"] > 0 and e["test"]["net"]["t"] > 2
    f = {r["key"]: r for r in o["funnel"]}
    assert f["tried"]["real"] > f["bh"]["real"] >= f["distinct"]["real"] >= 1
    assert f["costs"]["placebo_signals"] <= 2          # fake signals; the fake-markets null keeps each market's period mean, so it reproduces sorting by average return
    assert o["book"]["test"]["sharpe"] > 0.5


def test_noise_survives_at_placebo_rate_or_less(noise):
    f = {r["key"]: r for r in noise["funnel"]}
    assert f["tried"]["real"] > 200
    # nothing planted: real survivors after validation and costs no more frequent than placebo survivors (plus
    # one hypothesis of slack per thousand for small counts)
    assert f["costs"]["real"] <= max(2, f["costs"]["placebo_rate"] * f["tried"]["real"] * 3 + 1)
    assert f["bh"]["real_rate"] <= f["bh"]["placebo_rate"] + 0.005
    assert f["test_t2"]["real"] <= 1


def test_placebo_pipeline_is_the_real_pipeline():
    P = _noise(8, seed=3)
    P["sig"] = _planted(1, seed=4).iloc[:, 0].to_numpy()
    meta = _meta(P.columns)
    meta["sig"]["family"] = "Rates"                      # a signal, not a target
    B = D.panel_block(P, meta, quick=True)
    real = D.ext_rules(B, {"sig": B.ext["sig"]})
    copy = {"placebo_copy": {**B.ext["sig"], "kind": "placebo", "family": "placebo"}}
    D.add_sources(B, copy)
    fake = D.ext_rules(B, copy, family="placebo", kind="placebo")
    assert [r["tf"] for r in real] == [r["tf"] for r in fake]
    s1, s2 = D.screen(B, real), D.screen(B, fake)
    for p in ("disc", "val", "test"):
        for k in ("mean", "t", "n"):
            np.testing.assert_array_equal(s1["res"][p][k], s2["res"][p][k])
    np.testing.assert_array_equal(s1["valid"], s2["valid"])
    g1, g2 = D.gauntlet(B, real, s1, 0.5), D.gauntlet(B, fake, s2, 0.5)
    assert g1["counts"] == g2["counts"]


def _all_W(B):
    return [(r["name"], r.get("groups"), r["W"]()) for r in D.rules(B)]


def test_no_feature_uses_data_after_t_minus_lag():
    P = _planted(6, seed=7)
    P["ext"] = np.random.default_rng(8).normal(size=len(P))
    U = pd.DataFrame({"weird": np.random.default_rng(9).normal(size=len(P)).cumsum()}, index=P.index)
    um = {"weird": {"name": "weird", "family": "climate", "frequency": "monthly", "lag_months": 1}}
    meta = _meta(P.columns)
    meta["ext"]["family"] = "Rates"
    s = 250
    P2, U2 = P.copy(), U.copy()
    P2.iloc[s:] = np.random.default_rng(10).normal(size=P2.iloc[s:].shape) * 5
    U2.iloc[s:] = 999.0
    B1, B2 = D.panel_block(P, meta, U, um), D.panel_block(P2, meta, U2, um)
    W1, W2 = _all_W(B1), _all_W(B2)
    assert len(W1) == len(W2) > 200
    for (n1, g1, a), (n2, g2, b) in zip(W1, W2):
        assert n1 == n2
        lim = s + (1 if "weird" in n1 else D.LAG)  # unusual rows are knowable at the start of their month
        np.testing.assert_allclose(a[:lim], b[:lim], equal_nan=True, err_msg=n1)
    np.testing.assert_allclose(B1.sig[:s + D.LAG], B2.sig[:s + D.LAG], equal_nan=True)
    # and the perturbation does reach the features right after, so the check has teeth
    own = dict((n, w) for n, _, w in W1)["own 1-month change"]
    own2 = dict((n, w) for n, _, w in W2)["own 1-month change"]
    assert not np.allclose(own[s + D.LAG:s + D.LAG + 12], own2[s + D.LAG:s + D.LAG + 12], equal_nan=True)


def test_averaging_artifact_reproduced_and_removed_by_skip_month():
    d = D.averaging_demo()
    assert 0.18 < d["average"]["ac1"] < 0.33 and abs(d["theory_ac1"] - 0.25) < 0.01
    assert d["average"]["t_lag1"] > 3                    # one-month "momentum" with no skip month: an artifact
    assert abs(d["average"]["t_lag2"]) < 2.5             # gone with the skip month
    assert abs(d["end_of_month"]["t_lag1"]) < 2.5        # and absent on end-of-month prices
    # the same through the engine: twenty averaged random walks
    rng = np.random.default_rng(12)
    days = 21
    px = np.cumsum(rng.normal(0, 0.01, (len(IDX) * days, 20)), axis=0)
    avg = px.reshape(len(IDX), days, 20).mean(1)
    P = pd.DataFrame(np.vstack([np.full((1, 20), np.nan), np.diff(avg, axis=0)]), index=IDX, columns=[f"m{j:02d}" for j in range(20)])
    B = D.panel_block(P, _meta(P.columns), quick=True)
    lag1 = D._rule("own", "reversal", "own 1-month change, no skip", lambda: D.scale(B.X.shift(1)), tf="c1")
    lag2 = [r for r in D.rules(B) if r["name"] == "own 1-month change"][0]
    s = D.screen(B, [lag1, lag2])
    g = [i for i, gr in enumerate(B.groups) if gr["name"] == "Synthetic"][0]
    assert s["res"]["disc"]["t"][0, g] > 4
    assert abs(s["res"]["disc"]["t"][1, g]) < 2.5


def test_book_walk_forward_uses_only_past_data():
    rng = np.random.default_rng(13)
    E = rng.normal(0.1, 1, (len(IDX), 5))
    E[:, 2] *= 3
    cut = IDX.get_loc(pd.Timestamp("2019-12-01"))
    E2 = E.copy()
    E2[cut:] = rng.normal(0, 50, E2[cut:].shape)
    w1, s1 = D.book_weights(E, IDX, 2020)
    w2, s2 = D.book_weights(E2, IDX, 2020)
    np.testing.assert_allclose(w1, w2)
    assert s1 == pytest.approx(s2)
    assert w1[2] < w1[0]                                 # the riskier edge gets less weight
    b1, b2 = D.walk_book(E, IDX, "2010-01-01"), D.walk_book(E2, IDX, "2010-01-01")
    before = b1.index < pd.Timestamp("2019-12-01")
    np.testing.assert_allclose(b1[before].to_numpy(), b2[before].to_numpy())
    assert not np.allclose(b1[~before].to_numpy(), b2[~before].to_numpy())


def _strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)
    elif isinstance(o, str):
        yield o


def _floats(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _floats(v)
    elif isinstance(o, list):
        for v in o:
            yield from _floats(v)
    elif isinstance(o, float):
        yield o


def test_output_json_safe_and_house_style(planted):
    o = planted
    json.dumps(o, allow_nan=False)
    assert all(np.isfinite(x) for x in _floats(o))
    text = " ".join(_strings(o)).lower()
    for w in BAD:
        assert w not in text, w
    src = open(D.__file__).read().lower()
    for w in BAD:
        assert w not in src, w
    assert o["findings"] and all(isinstance(x, str) for x in o["findings"])
    for k in ("universe", "funnel", "families", "edges", "book", "placebo", "data_notes", "timing"):
        assert k in o
