"""v0.42.6: the universe checks. How much of the record is owed to a candidate list written in 2026, tested with the
same sizing rule on a list frozen at the end of 2017, on that list without its most valuable name, and on index
baskets whose members someone else chose before 2018. The page's claims about the short follow what these show."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import book as bk
from buildout import track

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"


def _snap38() -> dict:
    s = (SRC / "snap38.js").read_text()
    i = s.index("const SNAP38 = ") + 15
    return json.loads(s[i:s.rindex(";\n")].replace("<\\/", "</"))


def _world(days: int = 1100):
    """A synthetic market with the candidates' files: the book's nine names, the rest copied from them, ROBO from VTI."""
    prices, ust, _ = bk.synthetic(seed=5, days=days)
    have = [k for k in prices if k not in ("qqq", "soxx", "vti")]
    for i, t in enumerate(track.CANDIDATES):
        if t not in prices:
            prices[t] = prices[have[i % len(have)]].copy()
    prices["robo"] = prices["vti"].copy()
    return prices, ust


def test_a_frozen_list_holds_only_names_that_existed_at_the_freeze():
    prices, ust = _world()
    late = prices["nvda"].copy()
    late = late[pd.to_datetime(late["date"]) > pd.Timestamp("2019-06-01")]          # a name listed after the freeze
    prices["pltr"] = late
    fz = track.frozen_candidates(prices)
    assert "pltr" not in fz and "nvda" in fz and set(fz) < set(track.CANDIDATES)
    assert track.frozen_candidates(prices, freeze="2016-12-30") == [], "nothing has a year of prices before the data starts"
    cal = bk.panel(prices, ust)["R"].index
    _, mem, _ = track.pit_book(prices, cal, fz)
    assert all("pltr" not in m for m in mem.values()), "a later listing can never enter a frozen list"
    _, mem_all, _ = track.pit_book(prices, cal)
    assert mem_all == track.pit_members(prices, sorted({d.year for d in cal})), "the default list is unchanged"


def test_members_are_ranked_among_the_candidates_given():
    prices, ust = _world()
    years = [2019, 2020]
    few = ["msft", "nvda", "amzn"]
    m = track.pit_members(prices, years, few)
    assert all(set(v) <= set(few) and len(v) == 3 for v in m.values())
    assert track.dollar_volume(prices, few).columns.tolist() == few


def test_the_checks_run_and_every_row_is_the_same_rule_on_a_different_universe():
    prices, ust = _world(900)
    U = track.universe_checks(prices, ust, rule=False)
    keys = [r["key"] for r in U["rows"]]
    assert keys == ["pit", "frozen", "ex_top", "qqq", "soxx", "robo"]
    for r in U["rows"]:
        P = r["policies"]
        assert set(P) == {"hold", "call", "call_short"} and all(np.isfinite(P[k]["sharpe"]) for k in P)
        assert r["rule_effect"]["sharpe"] == pytest.approx(P["call"]["sharpe"] - P["hold"]["sharpe"])
        assert r["rule_effect"]["maxdd"] == pytest.approx(P["call"]["maxdd"] - P["hold"]["maxdd"])
        assert P["hold"]["from"] == U["rows"][0]["policies"]["hold"]["from"], "the same dates on every universe"
    b = [r for r in U["rows"] if r.get("basket")]
    assert len(b) == 3 and all(r["policies"]["hold"]["turnover_yr"] < 0.5 for r in b), "a single fund is bought once and not rebalanced"
    assert U["rows"][0]["policies"]["hold"]["turnover_yr"] > 1, "the nine names are"
    assert U["top_name"].lower().replace("googl", "goog") not in [t for v in U["rows"][2]["members"].values() for t in map(str.lower, v)]
    L = U["leave_one_out"]
    assert len(L) == len(U["frozen"]) and [x["d_cagr"] for x in L] == sorted(x["d_cagr"] for x in L) and L[0]["without"] == U["top_name"]
    only = track.universe_checks(prices, ust, rule=False, only=["qqq"])
    assert [r["key"] for r in only["rows"]] == ["qqq"]
    assert only["rows"][0]["policies"]["call"]["sharpe"] == pytest.approx([r for r in U["rows"] if r["key"] == "qqq"][0]["policies"]["call"]["sharpe"])


def test_the_published_checks_agree_with_the_published_record():
    T = _snap38()
    U = T["universe"]
    by = {r["key"]: r for r in U["rows"]}
    assert set(by) == {"pit", "frozen", "ex_top", "qqq", "soxx", "robo"} and all(r["rule"] == "live" for r in U["rows"])
    for k in ("hold", "call", "call_short"):                           # the first row is the record itself, run again
        assert by["pit"]["policies"][k]["sharpe"] == pytest.approx(T["pit"]["policies"][k]["net"]["sharpe"], abs=1e-9), k
        assert by["pit"]["policies"][k]["maxdd"] == pytest.approx(T["pit"]["policies"][k]["net"]["maxdd"], abs=1e-9), k
    assert by["qqq"]["policies"]["hold"]["sharpe"] == pytest.approx(T["pit"]["bench"]["sharpe"], abs=2e-3), "holding QQQ is the benchmark, less the cost of buying it once"
    assert by["qqq"]["policies"]["hold"]["sharpe"] <= T["pit"]["bench"]["sharpe"]
    assert U["listed_later"] == ["PLTR", "SPCX"] and len(U["frozen"]) == 14 and U["freeze"] == "2017-12-29"
    assert U["asof"] == T["asof"]
    for r in U["rows"]:
        assert r["fallbacks"] is not None and r["fallbacks"] <= 3, (r["key"], r["fallbacks"])


def test_the_pages_claims_follow_the_checks():
    """What the checks found is asserted here so a rerun that changes a finding fails loudly and the copy is reread."""
    U = _snap38()["universe"]
    by = {r["key"]: r for r in U["rows"]}
    B = [r for r in U["rows"] if r.get("basket")]
    P = lambda r, k: r["policies"][k]
    assert all(P(r, "call")["maxdd"] < P(r, "hold")["maxdd"] for r in U["rows"]), "the call cut the worst fall on every universe"
    assert all(P(r, "call")["sharpe"] < P(r, "hold")["sharpe"] for r in U["rows"]), "and gave up Sharpe ratio on every one"
    assert all(P(by["pit"], "hold")["cagr"] > P(r, "hold")["cagr"] for r in B), "the nine names grew faster than every basket"
    assert P(by["pit"], "call_short")["sharpe"] > P(by["pit"], "call")["sharpe"], "on the names the short beat cutting size"
    a = {k: r["vs_index"] for k, r in by.items()}
    assert a["pit"]["alpha_ann"] > 0.05 and a["pit"]["alpha_t"] > 2, "the names beat the index"
    assert all(a[r["key"]]["alpha_ann"] < a["pit"]["alpha_ann"] for r in B), "by more than any basket"
    assert a["qqq"]["alpha_ann"] == pytest.approx(0.0, abs=1e-9) and a["qqq"]["beta"] == pytest.approx(1.0, abs=1e-9), "the index against itself"
    assert abs(a["soxx"]["alpha_t"]) < 2 and a["robo"]["alpha_ann"] < 0
    assert sum(P(r, "call")["maxdd"] > 0.25 for r in U["rows"]) >= 1, "the cap is not a stop"
    td = (SRC / "trackdesk.js").read_text()
    assert "function universeVerdict" in td and "edgeIsNames" in td and "function renderUniverse" in td
    assert "the short's edge is the names beating the index" in td and "No source this build can reach carries delisted names" in td
    assert "The cap is not a stop" in td
    body = (SRC / "body.html").read_text()
    for i in ("tr-univ-s", "tr-univ", "tr-univ-read", "tr-loo"):
        assert f'id="{i}"' in body, i
    readme = (ROOT / "README.md").read_text()
    assert "the short keeps the return." not in readme and "baskets" in readme
    assert any('"v0.42.6"' in line and "hedge, not the cash" in line for line in (SRC / "memos.js").read_text().splitlines()), "the overturned claim is in the failure log"


def test_what_a_short_leaves_is_the_regression_residual():
    idx = pd.bdate_range("2018-01-02", periods=800)
    rng = np.random.default_rng(1)
    q = pd.Series(rng.normal(0.0004, 0.012, len(idx)), index=idx)
    cash = pd.Series(0.0001, index=idx)
    r = cash + 1.3 * q + 0.0003 + pd.Series(rng.normal(0, 0.004, len(idx)), index=idx)      # beta 1.3, about 7.6% a year left over
    v = track.vs_index(r, q, cash)
    assert v["beta"] == pytest.approx(1.3, abs=0.03) and v["alpha_ann"] == pytest.approx(0.0003 * 252, abs=0.03) and v["alpha_t"] > 1
    same = track.vs_index(cash + q, q, cash)
    assert same["beta"] == pytest.approx(1.0) and abs(same["alpha_ann"]) < 1e-12 and same["alpha_t"] is None


def test_house_style_and_version():
    import buildout
    assert buildout.__version__ >= "0.42.6"
    for p in ("tests/test_v42_6.py", "site/src/trackdesk.js", "buildout/track.py"):
        low = (ROOT / p).read_text().lower()
        for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
            assert b not in low, (p, b)
    assert '["v0.42.6", "Nov 11, 2026"' in (SRC / "reference.js").read_text() and "Version 0.42.6" in (ROOT / "CHANGELOG.md").read_text()
