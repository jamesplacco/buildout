"""v0.17: the bond lab (Treasury ETFs repriced bond by bond at any 10-year and 30-year yield), its exact mirror in the
page, and the complexity study (why flexible models backtest better and forecast worse). Planted answers throughout."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import bondlab as B, complexity as C

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
CURVE = {"1m": .0409, "2m": .0416, "3m": .0425, "4m": .0434, "6m": .0435, "1y": .0452, "2y": .0481, "3y": .0489, "5y": .0495,
         "7y": .0503, "10y": .0513, "20y": .0547, "30y": .0542}
FACTS = {"TLT": {"duration": 14.85, "wam": 26.04, "price": 80.24}, "IEF": {"duration": 6.83, "wam": 8.42}, "IEI": {"duration": 4.21, "wam": 4.72},
         "SHY": {"duration": 1.79, "wam": 1.9}, "EDV": {"duration": 23.9, "wam": 24.6}}
FLAT = {k: 0.05 for k in B.TENOR_KEYS}


# ---------------------------------------------------------------- the curve move
def test_shift_hits_the_ten_and_thirty_exactly_and_blends_between():
    assert B.moved(CURVE, 10, 0.04, 0.06) == pytest.approx(0.04)
    assert B.moved(CURVE, 30, 0.04, 0.06) == pytest.approx(0.06)
    d10, d30 = 0.04 - CURVE["10y"], 0.06 - CURVE["30y"]
    assert B.shift_at(20, d10, d30) == pytest.approx((d10 + d30) / 2)
    assert B.shift_at(5, d10, d30) == pytest.approx(d10)
    assert B.shift_at(1, d10, d30, "anchored") == 0.0
    # today's hump is kept: the 20-year stays above the straight line after a move
    assert B.moved(CURVE, 20, 0.05, 0.05) > 0.05


def test_zero_coupon_ladder_duration_is_its_average_maturity_over_one_plus_half_yield():
    f = {"lo": 20, "hi": 30, "zero": True}
    mats = B.ladder(f)
    d = B.fund_duration(FLAT, mats, 0.0)
    # on a flat curve: price-weighted mean of T / (1 + y/2)
    w = np.array([B.bond_price(0.05, T, 0.0) for T in mats])
    want = float((w * np.array(mats)).sum() / w.sum()) / 1.025
    assert d == pytest.approx(want, rel=1e-5)


def test_calibration_matches_the_reported_duration_and_centres_on_the_reported_maturity():
    F = B.setup(CURVE, FACTS)
    for t in ("TLT", "IEF", "IEI"):
        assert F[t]["duration"] == pytest.approx(FACTS[t]["duration"], abs=1e-4)
        assert np.mean(F[t]["mats"]) == pytest.approx(FACTS[t]["wam"], abs=1e-9)
    assert F["EDV"]["coupon"] == 0.0 and F["TLT"]["convexity"] > F["IEF"]["convexity"] > F["SHY"]["convexity"]


def test_par_bonds_on_a_flat_curve_lose_what_duration_and_convexity_say():
    f = B.setup(FLAT, {})["TLT"]
    s = B.scenario(FLAT, {"TLT": f}, 0.06, 0.06)["TLT"]
    taylor = -f["duration"] * 0.01 + 0.5 * f["convexity"] * 0.01 ** 2
    assert s["change"] == pytest.approx(taylor, abs=0.004)
    # convexity: a fall of 1 point gains more than a rise of 1 point loses
    up = B.scenario(FLAT, {"TLT": f}, 0.06, 0.06)["TLT"]["change"]
    dn = B.scenario(FLAT, {"TLT": f}, 0.04, 0.04)["TLT"]["change"]
    assert dn > -up > 0


def test_unchanged_yields_earn_the_yield_over_a_year():
    F = B.setup(FLAT, {})
    s = B.scenario(FLAT, F, 0.05, 0.05)
    for t in F:
        assert s[t]["change"] == pytest.approx(0.0, abs=1e-12)
        assert s[t]["total"] == pytest.approx(0.05 + 0.05 ** 2 / 4, abs=0.002)   # semiannual compounding on a flat curve


def test_breakeven_and_grid_are_consistent():
    F = B.setup(CURVE, FACTS)
    t = F["TLT"]
    be = B.breakeven(t)
    assert be == pytest.approx(t["ytm"] / t["duration"])
    g = B.grid(CURVE, t)
    assert len(g["y"]) == 9 and g["change"][0][0] > 0 > g["change"][-1][-1]
    i = g["y"].index(0.05)
    assert g["change"][i][i] == pytest.approx(B.scenario(CURVE, {"TLT": t}, 0.05, 0.05)["TLT"]["change"])


def test_build_reports_the_three_headline_cases():
    o = B.build(CURVE, FACTS)
    tl = o["cases"]
    assert tl["both_4"]["funds"]["TLT"]["change"] > 0.15 and tl["both_6"]["funds"]["TLT"]["change"] < -0.05
    assert tl["both_4"]["funds"]["TLT"]["price"] == pytest.approx(80.24 * (1 + tl["both_4"]["funds"]["TLT"]["change"]))
    assert "mats" not in o["funds"]["TLT"]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_page_bond_lab_matches_python():
    req = {"curve": CURVE, "funds": B.FUNDS, "facts": FACTS, "scenarios": [[0.04, 0.04], [0.06, 0.06], [0.045, 0.055, "anchored"], [0.05, 0.05, "parallel", 0.5]],
           "grid": "TLT", "shifts": [[5, 0.01, 0.02, "parallel"], [1, 0.01, 0.02, "anchored"], [25, -0.01, 0.01, "parallel"]]}
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness17.js")], input=json.dumps(req), capture_output=True, text=True, check=True)
    js = json.loads(r.stdout)
    F = B.setup(CURVE, FACTS)
    for t, f in F.items():
        for k in ("coupon", "duration", "convexity", "ytm"):
            assert js["funds"][t][k] == pytest.approx(f[k], rel=1e-6 if k == "convexity" else 1e-9, abs=1e-12), (t, k)
        assert js["funds"][t]["mats"] == pytest.approx(f["mats"])
    for s, got in zip(req["scenarios"], js["scenarios"]):
        want = B.scenario(CURVE, F, s[0], s[1], s[2] if len(s) > 2 else "parallel", s[3] if len(s) > 3 else 1.0)
        for t in F:
            assert got[t]["change"] == pytest.approx(want[t]["change"], abs=1e-12)
            assert got[t]["total"] == pytest.approx(want[t]["total"], abs=1e-12)
    g = B.grid(CURVE, F["TLT"])
    assert np.allclose(js["grid"]["change"], g["change"], atol=1e-12)
    assert js["shifts"] == pytest.approx([B.shift_at(*s) for s in req["shifts"]])


QUESTIONS = ["If the 10yr and 30yr both go closer to 4% what is the price of TLT", "what if the 10-year goes to 4.5%", "if the 30 year hits 6% and the 10 year 5%",
             "yields down 50bp", "TLT if rates rise 100 bps", "the 10-year at 6 percent", "what is TLT", "10y up 25bp", "both at 5%", "the 10\u2011year falls 30 bps"]


def test_yield_questions_are_read_as_planted():
    c = CURVE
    want = [(0.04, 0.04), (0.045, 0.045 + c["30y"] - c["10y"]), (0.05, 0.06), (c["10y"] - 0.005, c["30y"] - 0.005), (c["10y"] + 0.01, c["30y"] + 0.01),
            (0.06, 0.06 + c["30y"] - c["10y"]), None, (c["10y"] + 0.0025, c["30y"] + 0.0025), (0.05, 0.05), (c["10y"] - 0.003, c["30y"] - 0.003)]
    for q, w in zip(QUESTIONS, want):
        got = B.parse(q, c)
        if w is None:
            assert got is None, q
        else:
            assert (got["y10"], got["y30"]) == pytest.approx(w, abs=1e-6), q


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_page_reads_yield_questions_like_python():
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness17.js")], input=json.dumps({"curve": CURVE, "funds": B.FUNDS, "parse": QUESTIONS}),
                       capture_output=True, text=True, check=True)
    assert json.loads(r.stdout)["parse"] == [B.parse(q, CURVE) for q in QUESTIONS]


# ---------------------------------------------------------------- complexity
def _panel(n=900, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1900-01-31", periods=n, freq="ME")
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.99 * x[t - 1] + rng.normal(0, 0.05)
    D = pd.DataFrame({f: rng.normal(size=n) for f in C.ml.FEATURES}, index=idx)
    D["log_cape"] = 3 + x
    D["y_ret"] = -0.1 * x + pd.Series(rng.normal(0, 0.04, n)).rolling(12, min_periods=1).sum().to_numpy()
    return D


def test_information_counts_overlap_and_persistence():
    I = C.information(_panel())
    assert I["n_eff"] == pytest.approx(I["months"] / 12)
    assert I["y_autocorr_1"] > 0.8 and 0.95 < I["cape_ar1"] < 1
    assert I["ols_cost"] == pytest.approx(I["p"] / I["n_eff"])


def test_drift_windows_recover_a_planted_negative_slope():
    d = C.drift(_panel(), window=360, step=120)
    assert len(d) >= 3 and all(r["slope"] < 0 for r in d)


def test_planted_experiment_ranks_linear_first_at_low_signal():
    e = C.experiment(sims=2)
    lo = next(r for r in e["rows"] if r["shape"] == "linear" and r["true_r2"] == 0.02)
    assert lo["linear"] > lo["boost"]


def test_conclusions_carry_no_banned_words():
    o = {"sweep": {"Nearest neighbours": [{"label": "k = 400", "in_sample": 0.1, "out_of_sample": -0.02}, {"label": "k = 1", "in_sample": 1.0, "out_of_sample": -1.6}]},
         "extrapolation": {"train": "1881 to 1948", "test": "1950 to 1979", "y10_coef": -20.8, "y10_train": [0.02, 0.05], "y10_test": [0.02, 0.1], "r2_all": -9.8, "r2_cape": 0.01,
                           "worst_forecast": -1.4, "worst_actual": -0.5},
         "information": {"months": 1710, "n_eff": 142.5, "y_autocorr_1": 0.95, "cape_ar1": 0.995, "cape_half_life_months": 140, "r2_in_sample_all": 0.1, "p": 8,
                         "ols_cost": 0.056, "ols_cost_cape": 0.007},
         "drift": [{"end": "1950-01", "slope": -0.2}], "stambaugh": {"phi_annual": 0.92, "rho": 0.98, "bias_mean": -0.026, "years": 140, "slope": -0.076,
                                                                      "slope_corrected": -0.05, "p_naive": 0.03, "p_bias_aware": 0.12},
         "experiment": {"rows": [{"shape": "linear", "true_r2": 0.05, "linear": 0.03, "forest": -0.03, "boost": -0.08},
                                 {"shape": "threshold", "true_r2": 0.40, "linear": 0.18, "forest": 0.33, "boost": 0.29}]}}
    txt = json.dumps(C.conclusions(o))
    assert chr(0x2014) not in txt and ("inter" "section") not in txt and ("load" "-bearing") not in txt
    assert len(C.conclusions(o)) == 8


# ---------------------------------------------------------------- the mind's bond and history answers
MIND_Q = ["If the 10yr and 30yr both go closer to 4% what is the price of TLT", "What happened in 1974?", "Months like now", "March 2009", "black monday",
          "What if the 10-year goes to 6%?", "Is the stock market overvalued?"]


@pytest.fixture(scope="module")
def mind_snap():
    return json.loads((ROOT / "buildout" / "assets" / "mind.json").read_text())


def test_mind_answers_yield_and_history_questions(mind_snap):
    from buildout import mind
    M = mind.Mind(mind_snap)
    r = M.think(MIND_Q[0])
    tlt = next(x for x in r["bonds"]["rows"] if x["t"] == "TLT")
    assert r["bonds"]["y10"] == 0.04 and r["bonds"]["y30"] == 0.04 and tlt["change"] > 0.15
    assert M.think(MIND_Q[1])["history"]["id"] == "y:1974" and M.think(MIND_Q[2])["history"]["id"] == "m:now"
    assert M.think(MIND_Q[3])["history"]["id"] == "m:2009-03" and M.think(MIND_Q[4])["history"]["id"] == "h:crash-1987"
    w = M.think(MIND_Q[5])
    assert w.get("mode") == "whatif" and w["bonds"]["y10"] == 0.06 and "history" not in w
    assert "history" not in M.think(MIND_Q[6]) and "bonds" not in M.think(MIND_Q[6])


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_page_mind_bond_and_history_answers_match_python(mind_snap):
    from buildout import mind, voices
    req = {"voices": {"cfg": voices.config(), "lib": {"quotes": voices.load()}}, "mind": mind_snap, "questions": MIND_Q}
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness17m.js")], input=json.dumps(req), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    M = mind.Mind(mind_snap)
    for q, js in zip(MIND_Q, json.loads(r.stdout)):
        py = M.think(q)
        assert js["history"] == py.get("history"), q
        pb, jb = py.get("bonds"), js["bonds"]
        assert (pb is None) == (jb is None), q
        if pb:
            assert jb["y10"] == pb["y10"] and jb["y30"] == pb["y30"]
            for a, b in zip(jb["rows"], pb["rows"]):
                assert a["t"] == b["t"] and a["change"] == pytest.approx(b["change"], abs=2e-6) and a["total"] == pytest.approx(b["total"], abs=2e-6)
            assert jb["stocks"]["move"] == pytest.approx(pb["stocks"]["move"], abs=1e-9)
