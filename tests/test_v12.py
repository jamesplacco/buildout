"""v0.12: the brain's self-checks, the landing brain's arithmetic, and the voices library and retrieval."""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from buildout import brain_robust as R
from buildout import voices as V
from buildout.brain import PARENTS, REGIMES

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
LIB = ROOT / "buildout" / "assets" / "voices.json"
SERIES = json.loads((ROOT / "buildout" / "assets" / "brain_graph.json").read_text())["series"]


def _node(req: dict) -> dict:
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness12.js")], input=json.dumps(req), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


# ---------------------------------------------------------------- the brain's self-checks
def test_robustness_value_matches_cinelli_hazlett():
    """The Darfur example in Cinelli and Hazlett (2020): t = 4.18 on 783 degrees of freedom gives RV = 13.9% and
    RV at 5% = 7.6%."""
    assert R.robustness_value(4.18, 783) == pytest.approx(0.139, abs=0.0006)
    assert R.robustness_value(4.18, 783, alpha=0.05) == pytest.approx(0.076, abs=0.0006)
    assert R.robustness_value(1.0, 783, alpha=0.05) == 0.0                 # already insignificant
    assert R.robustness_value(-4.18, 783) == R.robustness_value(4.18, 783)  # sign-free


def test_stacking_finds_the_true_model_and_a_true_mixture():
    rng = np.random.default_rng(3)
    y = rng.normal(0, 1, 800)
    good, bad = R.log_density(y, np.zeros_like(y), np.ones_like(y)), R.log_density(y, np.full_like(y, 0.9), np.ones_like(y))
    w = R.stack(np.array([good, bad]))
    assert w[0] > 0.95 and w.sum() == pytest.approx(1.0)
    z = np.where(rng.random(4000) < 0.5, rng.normal(-2, 1, 4000), rng.normal(2, 1, 4000))
    w2 = R.stack(np.array([R.log_density(z, np.full_like(z, -2.0), np.ones_like(z)), R.log_density(z, np.full_like(z, 2.0), np.ones_like(z))]))
    assert w2[0] == pytest.approx(0.5, abs=0.05)


def _synthetic(n=420, seed=5, df=None):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 2))
    e = rng.standard_t(df, n) / math.sqrt(df / (df - 2)) if df else rng.normal(size=n)
    y = 0.6 * x[:, 0] - 0.3 * x[:, 1] + 0.8 * e
    return y, x, [f"{1990 + i // 12}-{i % 12 + 1:02d}" for i in range(n)]


def test_conformal_keeps_coverage_near_target():
    for df in (None, 3):                       # Gaussian errors, then fat-tailed ones
        y, X, dates = _synthetic(df=df)
        c = R.conformal(y, R.predictions(y, X), dates)
        assert 0.86 <= c["coverage"]["aci"] <= 0.94, (df, c["coverage"])


def test_predictions_never_look_ahead():
    y, X, _ = _synthetic(n=200)
    a = R.predictions(y, X)
    y2 = y.copy()
    y2[-1] += 50.0                             # a wild last month must not change any earlier forecast
    b = R.predictions(y2, X)
    for m in R.MODELS:
        assert np.allclose(a["mu"][m], b["mu"][m]) and np.allclose(a["var"][m], b["var"][m])


@pytest.fixture(scope="module")
def robust_real():
    r = R.analyze(SERIES, PARENTS, REGIMES)
    r["findings"] = R.summary(r)
    return r


def test_self_checks_on_the_shipped_series(robust_real):
    r = robust_real
    assert set(r["equations"]) == set(PARENTS)
    for k, e in r["equations"].items():
        assert e["from"] == "2000-02" and e["months"] > 300
        for key in ("weights", "weights_recent", "weights_now"):
            assert sum(e[key].values()) == pytest.approx(1.0, abs=1e-6) and all(v >= -1e-12 for v in e[key].values())
        for v in e["coverage"].values():
            assert 0.6 <= v <= 1.0
        assert 0.8 <= e["coverage"]["aci"] <= 0.97      # adaptive conformal keeps long-run coverage near 90%
    for reg in r["confounding"].values():
        for l in reg["links"].values():
            assert 0 <= l["rv_alpha"] <= l["rv"] <= 1 and 0 <= l["partial_r2"] <= 1
    assert r["findings"] and all("—" not in f and "intersection" not in f.lower() for f in r["findings"])


def test_snapshot_matches_engine(robust_real):
    txt = (ROOT / "site" / "src" / "snap12.js").read_text()
    snap = json.loads(re.search(r"const ROBUST_SNAP = (\{.*?\});\n", txt).group(1))
    assert snap["equations"]["eq"]["coverage"]["aci"] == pytest.approx(robust_real["equations"]["eq"]["coverage"]["aci"], abs=1e-6)
    assert snap["confounding"]["inflation"]["links"]["y10>eq"]["rv"] == pytest.approx(robust_real["confounding"]["inflation"]["links"]["y10>eq"]["rv"], abs=1e-6)


# ---------------------------------------------------------------- the landing brain
@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_hero_limit_is_the_infinite_sum():
    out = _node({"hero": ["hormuz", "pivot", "capex-cut", "gates"]})["hero"]
    for r in out:
        assert r["rho"] < 1
        assert np.allclose(r["lim"], r["long"], atol=1e-9)                        # Leontief = the series summed to convergence
        assert np.allclose(r["D_last"], np.array(r["x0"]) + np.array(r["total"]), atol=1e-12)
        assert r["n_draws"] == 300 and r["mc"]["p10"] <= r["mc"]["p50"] <= r["mc"]["p90"] and r["flux_sorted"]


# ---------------------------------------------------------------- voices
@pytest.fixture(scope="module")
def library():
    if not LIB.exists():
        pytest.skip("voices.json not built")
    return V.load(LIB)


def test_library_integrity(library):
    ids = [q["id"] for q in library]
    assert len(ids) == len(set(ids)) and len(library) >= 150
    for q in library:
        assert q["topic"] in V.TOPICS and q["stance"] in V.STANCES and q["kind"] in ("legend", "current")
        assert q["verification"] in ("verbatim-on-source", "verbatim-secondary")
        assert q["source_url"].startswith("https://") and q["speaker"] and q["date"][:4].isdigit()
        assert len(q["text"].split()) <= 60, q["id"]          # one sentence or two; v0.24 admits a 49-word Damodaran sentence
        for f in ("text", "gist", "context", "role", "speaker", "source_title"):
            assert "—" not in (q.get(f) or ""), (q["id"], f)
            assert "intersection" not in (q.get(f) or "").lower(), (q["id"], f)
        if q["kind"] == "current":
            assert q["date"][:4] in ("2024", "2025", "2026"), q["id"]
    for k in V.TOPICS:
        own = [q for q in library if q["topic"] == k]
        assert len(own) >= 8, k
        assert any(q["stance"] < 0 for q in own) and any(q["stance"] > 0 for q in own), k


def test_examples_route_and_read_sides(library):
    lib = V.Library(library)
    r = lib.search("Is bitcoin digital gold and worth gold's market cap?")
    assert r["topic"] == "bitcoin" and "gold" in r["related"] and r["polarity"]["side"] == "bull" and r["polarity"]["question"]
    assert all(r["spectrum"][s] for s in (-2, 2))                                 # both extremes have a voice
    assert lib.search("Is AI a bubble?")["topic"] == "ai_boom" and lib.search("Is AI a bubble?")["polarity"]["side"] == "bear"
    assert lib.search("Are long bonds still a hedge?")["topic"] == "bonds_rates"
    y = lib.search("10-year yields will rise")
    assert y["topic"] == "bonds_rates" and y["polarity"]["side"] == "bear"       # rising yields are the bear case for bonds
    i = lib.search("inflation isn't beaten")
    assert i["topic"] == "inflation_fed" and i["polarity"]["side"] == "bear"      # negation flips it
    assert lib.search("Should I trim Nvidia?")["topic"] == "semis_nvidia"
    assert lib.search("purple elephants dance")["topic"] is None


QUERIES = [["Is bitcoin digital gold and worth gold's market cap?", None], ["Is AI a bubble?", None], ["Are long bonds still a hedge?", None],
           ["10-year yields will rise", None], ["inflation isn't beaten", None], ["Should I trim Nvidia?", None], ["Mag 7 concentration risk", None],
           ["Is private credit the next blowup?", None], ["china uninvestable?", None], ["oil to $150", None], ["Diversification is for idiots", None],
           ["Buy the dip or wait for the crash", None], ["Is the S&P 500 overvalued vs. its CAPE?", None], ["recession in 2027?", None],
           ["Tesla's valuation", None], ["purple elephants dance", None], ["Is bitcoin digital gold?", "gold"], ["“AI” won’t pay off", None],
           ["Gold vs bitcoin vs dollar", None], ["leverage and tail hedges", None], ["value or growth?", None], ["", None]]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_page_retrieval_equals_python(library):
    lib = V.Library(library)
    out = _node({"voices": {"cfg": json.loads(json.dumps(V.config())), "lib": {"quotes": library}, "queries": QUERIES}})["voices"]
    for (q, t), js in zip(QUERIES, out):
        py = lib.search(q, topic=t)
        assert js["tokens"] == py["tokens"], q
        assert js["topic"] == py["topic"], q
        assert js["related"] == py["related"], q
        assert js["polarity"] == py["polarity"], q
        assert {int(k): v for k, v in js["spectrum"].items()} == py["spectrum"], q
        if py["topic"]:
            assert js["lean"] == pytest.approx(py["lean"], abs=1e-12), q


def test_mcp_voices_never_invents(library):
    from buildout.mcp_server import Context, investor_voices, ToolError
    texts = {q["text"] for q in library}
    r = investor_voices(Context(), {"query": "Is bitcoin digital gold?", "limit": 10})
    assert r["found"] and r["topic"] == "Bitcoin and crypto"
    got = [x for v in r["voices"].values() for x in v]
    assert got and all(x["text"] in texts and x["source_url"].startswith("https://") for x in got)
    one = investor_voices(Context(), {"query": "Is bitcoin digital gold?", "stance": -2})
    assert list(one["voices"]) == ["Extreme bear"]
    assert investor_voices(Context(), {"query": "purple elephants"})["found"] is False
    for bad in ({"query": ""}, {"query": "x", "stance": 3}, {"query": "x", "stance": True}, {"query": "x", "topic": "nope"}):
        with pytest.raises(ToolError):
            investor_voices(Context(), bad)


def test_mcp_selfcheck():
    from buildout.mcp_server import Context, brain_selfcheck
    r = brain_selfcheck(Context(data_dir="/nonexistent"), {})
    assert r["findings"] and "eq" in r["equations"] and "inflation" in r["confounding"]
