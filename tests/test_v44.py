"""v0.44: how sure is the size. The drawdown cap binds the call's size and it comes from one model. Two outside audits
asked what the size becomes under other specifications and whether the cap held where it was used.

    other models        the same number with fat tails, with the book's own days in runs, with volatility that moves,
                        without the premium, at today's and the worst year's volatility (sensitivity.models)
    one setting         the size with each limit, the premium, the tail method and the half-lives changed one at a
                        time (sensitivity.settings)
    what happened       one-year windows of the walk-forward against the cap, on six universes (track.window_drawdowns)
    nothing moves       the call is the same number as before; this is how far to trust it
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import book as bk
from buildout import sensitivity as sens
from buildout import track
from buildout.analytics import sizing

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"


def _snap(name: str, const: str) -> dict:
    s = (SRC / name).read_text()
    i = s.index(f"const {const} = ") + len(const) + 9
    return json.loads(s[i:s.rindex(";")].replace("<\\/", "</"))


@pytest.fixture(scope="module")
def world():
    prices, ust, _ = bk.synthetic(seed=3, days=1200)
    return prices, ust, bk.build(prices, ust), sens.build(prices, ust)


# ---------------------------------------------------------------- 1. the block describes the call it sits beside
def test_the_engines_row_is_the_calls_size(world):
    prices, ust, o, S = world
    assert S["size"] == pytest.approx(o["size"], abs=1e-6) and S["binding"] == o["binding"]
    eng = S["models"]["rows"][0]
    assert eng["key"] == "gbm" and eng["d_size"] == 0.0
    assert eng["size"] == pytest.approx(S["sizes"]["drawdown_cap"], abs=1e-12), "the engine's own function, not a second simulation"
    if S["binding"] == "drawdown_cap":
        assert eng["dd_at_size"] == pytest.approx(bk.MAX_DD, abs=2e-3)
    assert [r["key"] for r in S["models"]["rows"]] == ["gbm", "student_t", "blocks", "clustered", "no_premium", "vol_now", "vol_worst"]
    for r in S["models"]["rows"]:
        assert 0 < r["dd_at_size"] < r["dd_full"] < 1 or S["size"] >= 1, r["key"]
        assert r["inside_at_size"] == (r["dd_at_size"] <= bk.MAX_DD + 1e-9)


def test_this_modules_simulator_agrees_with_the_engine_on_the_engines_model(world):
    """Normal shocks through this module's levered-return simulator against the engine's closed loop: the same
    question asked two ways. They differ by sampling error and by daily against continuous compounding."""
    *_, S = world
    M = S["models"]
    eng, chk, seeds = M["rows"][0], M["check_normal"], M["seeds"]
    assert chk["dd_full"] == pytest.approx(eng["dd_full"], abs=0.02)
    assert chk["size"] == pytest.approx(eng["size"], rel=0.05)
    assert seeds["n"] == sens.SEEDS and seeds["min"] <= seeds["mean"] <= seeds["max"]
    assert abs(seeds["mean"] - eng["size"]) < 4 * seeds["sd"] / math.sqrt(seeds["n"]) + 0.01 * eng["size"]
    assert 0 < seeds["sd"] < 0.05 * eng["size"], "the draws move the answer a little, and only a little"


def test_more_size_is_a_deeper_fall_and_the_solved_size_is_on_the_safe_side():
    rng = np.random.default_rng(4)
    X = 0.10 / 252 + 0.30 / math.sqrt(252) * rng.standard_normal((sens.N_PATHS, sens.STEPS))
    d = [sens.dd_quantile(X, g, 0.04) for g in (0.25, 0.5, 1.0, 1.5)]
    assert d == sorted(d) and d[0] > 0
    g = sens.size_inside(X, 0.04, 0.25)
    assert sens.dd_quantile(X, g, 0.04) <= 0.25 < sens.dd_quantile(X, g + 0.01, 0.04)
    assert sens.size_inside(X * 0.01, 0.04, 0.25) == 3.0, "a book that cannot fall that far is capped by the search, not by the cap"
    assert sens.dd_quantile(X, 0.0, 0.04) == 0.0, "all cash never falls"


def test_shocks_have_unit_variance_and_runs_keep_neighbours_together():
    rng = np.random.default_rng(0)
    t = sens._shocks_t(rng)
    assert t.std() == pytest.approx(1.0, abs=0.02) and float(pd.Series(t.ravel()).kurt()) > 1, "fat tails, the same variance"
    z = np.arange(500.0)
    b = sens._shocks_blocks(rng, z)
    step = np.diff(b, axis=1)
    kept = (step == 1).mean()
    assert kept == pytest.approx(1 - 1 / sens.BLOCK, abs=0.02), "a run ends about once in BLOCK days"
    c = sens._paths_clustered(np.random.default_rng(1), rng.standard_normal(2000), 0.30 / math.sqrt(252), 0.0)
    v = pd.DataFrame(c.T ** 2)
    assert float(np.mean([v[i].autocorr(1) for i in range(40)])) > 0.03, "a big move is followed by big moves"
    flat = 0.30 / math.sqrt(252) * np.random.default_rng(1).standard_normal((sens.N_PATHS, sens.STEPS))
    assert sens.dd_quantile(c, 1.0, 0.0) > sens.dd_quantile(flat, 1.0, 0.0), "and that deepens the bad year"


# ---------------------------------------------------------------- 2. one setting at a time
def test_each_setting_moves_the_size_the_way_it_must(world):
    *_, S = world
    G: dict[str, list] = {}
    for r in S["settings"]:
        G.setdefault(r["group"], []).append(r)
    assert list(G) == ["Loss budget, a month", "Volatility target", "Drawdown cap, a year", "Equity premium in the drift", "Method for the tail", "Half-lives of the factor model"]
    for g, rows in G.items():
        now = [r for r in rows if r["now"]]
        assert len(now) == 1 and now[0]["size"] == pytest.approx(S["size"], abs=1e-9) and now[0]["binding"] == S["binding"], g
        for r in rows:
            assert r["size"] == pytest.approx(min(r["sizes"].values())) and r["sizes"][r["binding"]] == r["size"]
    for g in ("Loss budget, a month", "Volatility target", "Drawdown cap, a year", "Equity premium in the drift"):
        s = [r["size"] for r in G[g]]
        assert s == sorted(s), f"a looser {g.lower()} never shrinks the book"
    cap = [r["sizes"]["drawdown_cap"] for r in G["Drawdown cap, a year"]]
    assert cap[0] < cap[1] < cap[2]
    prem = [r["sizes"]["drawdown_cap"] for r in G["Equity premium in the drift"]]
    assert prem == sorted(prem) and prem[0] < prem[-1], "an assumed premium is size"
    assert S["settings_range"] == [min(r["size"] for r in S["settings"]), max(r["size"] for r in S["settings"])]
    assert all("vol" in r and r["vol"] > 0 for r in G["Half-lives of the factor model"])


def test_the_half_lives_default_to_the_engines(world):
    prices, ust, *_ = world
    w = pd.Series(bk.BOOK, dtype=float)
    P = bk.panel(prices, ust)
    a, b = bk.factor_model(P["R"], P["F"], w), bk.factor_model(P["R"], P["F"], w, beta_hl=bk.BETA_HL, cov_hl=bk.COV_HL)
    assert a["vol"] == b["vol"]
    assert bk.factor_model(P["R"], P["F"], w, cov_hl=21)["vol"] != a["vol"]


# ---------------------------------------------------------------- 3. a failure here never touches the call
def test_attaching_never_raises_and_never_changes_the_call(world):
    prices, ust, o, _ = world
    before = json.dumps({k: v for k, v in o.items() if k != "sensitivity"}, sort_keys=True, default=str)
    out = sens.attach(dict(o), prices, ust)
    assert "failed" not in out["sensitivity"] and "mismatch" not in out["sensitivity"]
    assert json.dumps({k: v for k, v in out.items() if k != "sensitivity"}, sort_keys=True, default=str) == before
    bad = sens.attach({"size": 0.5}, {}, ust)
    assert set(bad["sensitivity"]) == {"failed"} and bad["size"] == 0.5
    off = sens.attach({"size": o["size"] + 0.1}, prices, ust)
    assert "mismatch" in off["sensitivity"], "a block that sized a different book says so"
    cli = (ROOT / "buildout" / "cli.py").read_text()
    assert "sensitivity.attach(o, prices)" in cli and cli.index("o = bk.build(prices") < cli.index("sensitivity.attach(o, prices)")


# ---------------------------------------------------------------- 4. did the cap hold
def _series(moves: dict[int, float], days: int = 252 * 5, drift: float = 0.0004) -> pd.Series:
    r = pd.Series(drift, index=pd.bdate_range("2018-01-02", periods=days))
    for i, v in moves.items():
        r.iloc[i] = v
    return r


def test_one_year_windows_against_the_cap():
    calm = track.window_drawdowns(_series({}))
    assert calm["windows"] > 40 and calm["breaches"] == 0 and calm["episodes"] == 0 and calm["worst"] == 0.0 and calm["share"] == 0.0
    one = track.window_drawdowns(_series({600: -0.30}))
    assert one["breaches"] >= 11 and one["episodes"] == 1 and one["worst"] == pytest.approx(0.30, abs=1e-9), "one fall fills a year of overlapping windows"
    assert one["breaches"] <= 13 and one["share"] == pytest.approx(one["breaches"] / one["windows"])
    two = track.window_drawdowns(_series({300: -0.30, 900: -0.30}))
    assert two["episodes"] == 2 and two["breaches"] > one["breaches"]
    small = track.window_drawdowns(_series({600: -0.20}))
    assert small["breaches"] == 0 and small["worst"] == pytest.approx(0.20, abs=1e-9)
    assert track.window_drawdowns(_series({600: -0.20}), cap=0.15)["breaches"] > 0, "the cap is the argument"
    assert track.window_drawdowns(_series({}, days=200)) == {"windows": 0}
    first = _series({}, days=600)
    me = track.month_ends(first.index)[0]
    first.loc[first.index > me] = 0.0
    first.iloc[first.index.get_loc(me) + 1] = -0.26
    assert track.window_drawdowns(first)["breaches"] >= 1, "a fall on the window's first day is a fall from where it started"
    slow = track.window_drawdowns(_series({}, drift=-0.0015))
    assert slow["breaches"] == slow["windows"] and slow["episodes"] == 1, "a slow slide counts as much as a crash"


def test_every_universe_row_carries_the_check():
    prices, ust, _ = bk.synthetic(seed=5, days=900)
    have = [k for k in prices if k not in ("qqq", "soxx", "vti")]
    for i, t in enumerate(track.CANDIDATES):
        if t not in prices:
            prices[t] = prices[have[i % len(have)]].copy()
    prices["robo"] = prices["vti"].copy()
    U = track.universe_checks(prices, ust, rule=False, only=["qqq"])
    c = U["rows"][0]["cap_check"]
    assert set(c) == {"hold", "call", "call_short"} and all(x["windows"] > 0 for x in c.values())
    assert c["call"]["worst"] <= c["hold"]["worst"] + 1e-9, "a smaller size cannot fall further on one fund"


# ---------------------------------------------------------------- 5. what was published
def test_the_published_block_is_the_published_calls():
    B = _snap("snap30.js", "SNAP30")["book"]
    S = B["sensitivity"]
    assert "failed" not in S and "mismatch" not in S
    assert S["size"] == pytest.approx(B["size"], abs=1e-6) and S["binding"] == B["binding"] and S["asof"] == B["asof"]
    assert S["models"]["rows"][0]["size"] == pytest.approx(B["sizes"]["drawdown_cap"], abs=1e-6)
    assert len(S["models"]["rows"]) == 7 and S["models"]["paths"] == sens.N_PATHS
    assert any("sensitivity.py" in x and "not a stop" in x for x in B["limitations"])


def test_the_pages_claims_follow_what_was_found():
    """Asserted here so that a rerun which changes a finding fails loudly and the copy is reread."""
    S = _snap("snap30.js", "SNAP30")["book"]["sensitivity"]
    by = {r["key"]: r for r in S["models"]["rows"]}
    eng = by["gbm"]["size"]
    assert abs(by["student_t"]["d_size"]) < 0.015 and abs(by["blocks"]["d_size"]) < 0.015, "the shape of the tail hardly matters over a year"
    assert by["clustered"]["size"] < 0.9 * eng and not by["clustered"]["inside_at_size"], "volatility that moves does"
    assert by["clustered"]["dd_at_size"] > 0.27
    assert by["no_premium"]["size"] < eng and by["vol_worst"]["size"] < by["vol_now"]["size"] < eng
    assert S["models"]["seeds"]["max"] - S["models"]["seeds"]["min"] > 0.01, "the third decimal of the size is noise"
    assert S["models"]["shape_range"][0] == by["clustered"]["size"]
    tail = [r for r in S["settings"] if r["group"] == "Method for the tail"]
    assert len({round(r["size"], 6) for r in tail}) == 1, "the tail method does not move the size while the drawdown cap binds"
    U = _snap("snap38.js", "SNAP38")["universe"]
    rows = {r["key"]: r["cap_check"] for r in U["rows"]}
    assert set(rows) == {"pit", "frozen", "ex_top", "qqq", "soxx", "robo"}
    for k, c in rows.items():
        assert c["call"]["windows"] >= 80 and c["call"]["cap"] == 0.25, k
        assert c["call"]["share"] <= c["hold"]["share"], f"{k}: the call went past the cap no more often than holding"
        assert c["call"]["episodes"] <= 3, f"{k}: a handful of stretches, which is the honest sample"
    assert all(c["hold"]["share"] > 0.05 for c in rows.values()), "holding at full size went past the cap far more than one year in twenty everywhere"
    assert rows["pit"]["call"]["breaches"] == 0 and 0.20 < rows["pit"]["call"]["worst"] < 0.25, "on the nine names the call's worst year was inside the cap, and not by much"
    assert sorted(k for k, c in rows.items() if c["call"]["breaches"]) == ["qqq", "robo"] and max(c["call"]["worst"] for c in rows.values()) < 0.30
    assert rows["pit"]["call_short"]["breaches"] == 0 and rows["soxx"]["call_short"]["share"] > 0.3, "the index short held the cap on the names and not on semiconductors"
    over = sorted(k for k, c in rows.items() if c["call"]["share"] > 0.05)
    assert over == OVER, "which universes the call went past the cap on more than one window in twenty"


OVER = ["qqq"]


def test_the_page_carries_the_section():
    body, book, boot = (SRC / "body.html").read_text(), (SRC / "book.js").read_text(), (SRC / "boot.js").read_text()
    for i in ("bk-sens-s", "bk-sens-t", "bk-sens-p", "bk-sens-tiles", "bk-sens-m", "bk-sens-mn", "bk-sens-cp", "bk-sens-c", "bk-sens-cn", "bk-sens-set", "bk-sens-setn"):
        assert body.count(f'id="{i}"') == 1, i
    assert re.search(r'<section class="section" aria-labelledby="bk-sens-t" id="bk-sens-s" hidden>', body), "hidden until there is something to show"
    assert body.index('id="bk-front-t"') < body.index('id="bk-sens-t"') < body.index('id="bk-hedge-t"')
    assert "function renderSensitivity(B)" in book and "sec.hidden = !S;" in book and "B.sensitivity.failed" in book
    assert 'guard("How sure is the size", () => renderSensitivity(B)' in book
    assert "None of it changes the call." in book and "The cap is a modelled percentile, not a stop." in book
    assert "the count of stretches is the honest sample" in book and "they can only fail to contradict it" in book
    assert '"bk-front-t", "bk-sens-t", "bk-hedge-t"' in boot
    for page in ("core.html", "page.html"):
        assert 'id="bk-sens-s"' in (ROOT / "site" / page).read_text(), page


def test_a_published_book_without_the_block_keeps_the_embedded_one():
    """The page prefers a newer data/book.json to its snapshot. Until a daily run on this code writes the block, the
    published book has none: the section then shows the embedded block and says which book and date it describes."""
    boot, book = (SRC / "boot.js").read_text(), (SRC / "book.js").read_text()
    assert "if (!(bkj.sensitivity && bkj.sensitivity.models) && SNAP30.book.sensitivity) bkj.sensitivity = SNAP30.book.sensitivity;" in boot
    assert boot.index("bkj.sensitivity = SNAP30.book.sensitivity") < boot.index("SNAP30.book = bkj; LIVE.book = bkj;")
    assert "const same = S.asof === B.asof;" in book and "as last computed, on the book of" in book and "S.mismatch" in book


def test_a_link_to_the_library_navigates_once():
    """The stress run caught the core page starting the library twice for one link: the second request cancels the
    first. The reader still arrived; the browser fetched 12 MB twice."""
    boot = (SRC / "boot.js").read_text()
    assert "if (leavingFor === v) return; leavingFor = v; location.href = LIBRARY_HREF" in boot
    assert 'window.addEventListener("pageshow", () => { leavingFor = null; })' in boot, "coming back from the library re-arms its links"


def test_counts_house_style_and_version():
    import buildout
    assert buildout.__version__ >= "0.44.0"
    n = len(list((ROOT / "tests").glob("test_*.py")))
    assert f"const TEST_FILES = {n};" in (SRC / "landing.js").read_text() and f"and {n} test files" in (SRC / "body.html").read_text()
    for p in ("tests/test_v44.py", "buildout/sensitivity.py", "site/src/book.js"):
        low = (ROOT / p).read_text().lower()
        for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
            assert b not in low, (p, b)
    assert '["v0.44", "Nov 12, 2026"' in (SRC / "reference.js").read_text() and "Version 0.44" in (ROOT / "CHANGELOG.md").read_text()
    assert any('"v0.44"' in line for line in (SRC / "memos.js").read_text().splitlines()), "what the checks found against the page's own model is in the failure log"
