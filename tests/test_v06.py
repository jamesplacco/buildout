"""v0.6 engine modules: the field manual's accounting, microstructure, the brain, the buyside selector and the feeds.

Every test plants an answer and checks the code finds it, or reproduces a published table to the rounding shown.
"""
import datetime as dt
import json
import math

import numpy as np
import pandas as pd
import pytest

from buildout import accounting as ac
from buildout import brain, buyside, feeds, microstructure as ms, sources


# ---------------------------------------------------------------- accounting: the manual's tables
def test_depreciation_table_matches_the_manual():
    rows = {r["life"]: r for r in ac.depreciation_table(425)}
    assert [round(rows[L]["annual"]) for L in (6, 5, 4, 3, 2)] == [71, 85, 106, 142, 212]   # manual rounds 212.5 up to 213
    assert round(rows[3]["gap"]) == 71 and round(rows[2]["gap"]) == 142 and rows[6]["gap"] == 0
    assert ac.ddb_first_year(425, 6) == pytest.approx(425 / 3)


def test_private_credit_stress_matches_the_manual():
    normal = ac.credit_stress(0.039, 0.055, 0.02, 0.60)
    today = ac.credit_stress(0.039, 0.055, 0.06, 0.50)
    worst = ac.credit_stress(0.039, 0.055, 0.14, 0.40)
    assert normal["net"] == pytest.approx(0.064, abs=0.001)          # "about 6.4%"
    assert today["net"] == pytest.approx(0.045, abs=0.002)           # "about 4.6%"
    assert worst["net"] < 0 and worst["over_treasury"] < -0.05       # "negative", "deeply negative"
    assert normal["over_treasury"] == pytest.approx(0.012, abs=0.001) # "+1.2 pts"


def test_cash_eps_and_reverse_dcf():
    assert ac.cash_eps(100, 30, 20, 15, 5, 4, 10) == pytest.approx((100 - 10 - 15 - 5 + 4) / 10)
    assert math.isnan(ac.cash_eps(1, 0, 0, 0, 0, 0, 0))
    g = ac.reverse_dcf(1000, 20, 0.09, 0.03)
    assert ac.dcf_value(20, g, 0.09, 0.03) == pytest.approx(1000, rel=1e-9)
    assert ac.reverse_dcf(1000, 20, 0.09, 0.03) > ac.reverse_dcf(800, 20, 0.09, 0.03)   # a higher price assumes more growth
    assert math.isnan(ac.reverse_dcf(1000, -5, 0.09))


def test_red_flags_grade_both_directions():
    g = {r["key"]: r["grade"] for r in ac.red_flags({"capex_to_dep": 3.0, "fcf_to_ni": 0.95, "sbc_to_rev": 0.08, "recv_minus_rev": None})}
    assert g == {"capex_to_dep": "red", "fcf_to_ni": "healthy", "sbc_to_rev": "watch", "recv_minus_rev": "n/a", "top3_customers": "n/a"}


# ---------------------------------------------------------------- microstructure
def test_avellaneda_stoikov_quotes():
    flat = ms.as_quotes(100, 0, 0.1, 2, 1, 1.5)
    assert flat["reservation"] == 100 and flat["ask"] - flat["bid"] == pytest.approx(flat["spread"])
    long = ms.as_quotes(100, 5, 0.1, 2, 1, 1.5)
    assert long["reservation"] < 100 and long["ask"] < flat["ask"]        # long inventory: quote lower to sell it
    assert ms.as_quotes(100, 0, 0.1, 2, 0.5, 1.5)["spread"] < flat["spread"]   # less time left, less inventory risk


def test_inventory_skew_cuts_inventory_risk():
    a = ms.simulate_as(n_paths=600, steps=200, seed=3)
    s = ms.simulate_as(n_paths=600, steps=200, seed=3, symmetric=True)
    assert a["inv_sd"] < 0.7 * s["inv_sd"]
    assert a["sd"] < s["sd"]


def test_impact_and_execution():
    assert ms.sqrt_impact(4e5, 1e7, 0.02) == pytest.approx(2 * ms.sqrt_impact(1e5, 1e7, 0.02))
    assert ms.gm_spread(0.2, 101, 99) == pytest.approx(0.4)
    twap = ms.ac_trajectory(1e6, 5, 10, 0.02, 1e-6, 0)
    fast = ms.ac_trajectory(1e6, 5, 10, 0.02, 1e-6, 1e-3)
    assert twap[0] == fast[0] == 1e6 and abs(fast[-1]) < 1e-6 and twap[5] == pytest.approx(5e5)
    assert fast[5] < twap[5]                                      # risk aversion front-loads the selling
    c_twap, c_fast = ms.ac_cost(twap, 5, 0.02, 1e-6), ms.ac_cost(fast, 5, 0.02, 1e-6)
    assert c_fast["expected"] > c_twap["expected"] and c_fast["sd"] < c_twap["sd"]


def test_roll_spread_recovers_a_planted_bounce():
    rng = np.random.default_rng(1)
    mid = 100 + np.cumsum(rng.normal(0, 0.02, 20000))
    trade = mid + 0.05 * rng.choice([-1, 1], 20000)              # half-spread 0.05: spread 0.10
    assert ms.roll_spread(trade) == pytest.approx(0.10, rel=0.1)
    r = rng.normal(0, 0.01, 5000)
    dv = rng.uniform(1e6, 2e6, 5000)
    assert ms.kyle_lambda(r + 1e-9 * np.sign(r) * dv, dv) > 0
    assert ms.amihud(r, dv) > 0


# ---------------------------------------------------------------- the brain recovers planted structure
def test_brain_recovers_planted_weights_by_regime():
    rng = np.random.default_rng(0)
    idx = pd.date_range("1990-02-01", "2026-09-01", freq="MS")
    n = len(idx)
    oil = rng.normal(size=n)
    cpi = 0.5 * oil + rng.normal(size=n)
    late = idx >= "2022-01-01"
    y10 = 0.3 * cpi + rng.normal(size=n)
    eq = np.where(late, -0.4, 0.2) * y10 + rng.normal(size=n)        # the sign flips in 2022
    vix = -0.7 * eq + rng.normal(size=n) * 0.6
    gold = -0.2 * y10 + rng.normal(size=n)
    df = pd.DataFrame({"oil": oil, "cpi": cpi, "y10": y10, "eq": eq, "vix": vix, "gold": gold}, index=idx)
    dz = (df - df.mean()) / df.std()
    lo = brain.estimate(dz, "1990-02-01", "2021-12-01")["edges"]
    hi = brain.estimate(dz, "2022-01-01", None)["edges"]
    sd = df.std()
    assert lo["y10>eq"]["w"] == pytest.approx(0.2 * sd["y10"] / sd["eq"], abs=0.08)
    assert hi["y10>eq"]["w"] < 0 < lo["y10>eq"]["w"]
    assert lo["oil>cpi"]["t"] > 5
    st = brain.node_state(df)
    assert set(st) == set(brain.ORDER)


# ---------------------------------------------------------------- buyside: selector, tails, regime
def test_hedge_selector_finds_the_hedge_that_pays_in_bad_periods():
    rng = np.random.default_rng(2)
    idx = pd.date_range("1990-01-01", periods=600, freq="MS")
    book = pd.Series(rng.standard_t(4, 600) * 0.04, index=idx)
    good = -0.5 * book.clip(upper=0) * 2 - 0.002                 # pays in down months, small carry cost
    noise = pd.Series(rng.normal(0, 0.03, 600), index=idx)
    regime = pd.Series(np.where(np.arange(600) < 300, "a", "b"), index=idx)
    sel = buyside.hedge_selector(book, {"good": good, "noise": noise}, regime)
    for reg in ("a", "b"):
        rows = sel[reg]["rows"]
        assert rows[0]["hedge"] == "good" and rows[0]["es_removed"] > 0 and rows[0]["hit"] > 0.9


def test_student_t_shortfall_exceeds_the_normal_on_fat_tails():
    rng = np.random.default_rng(4)
    r = pd.Series(np.exp(rng.standard_t(3, 4000) * 0.03) - 1)
    t = buyside.tail_risk(r)
    assert t["student_t"] > t["normal"] and 2 < t["nu"] < 5
    assert buyside.es(pd.Series([-0.1, -0.05, 0, 0.05] * 5), 0.25) == pytest.approx(0.1)


def test_regime_label_follows_rule_7a1():
    now = buyside.regime_label(cpi_3m_ann=3.6, real10=2.74, fed=1, brent_vs_5y=1.5, corr=0.15, infl36=0.0306)
    assert now["label"] == "Supply-shock stagflation scare" and (now["gross_lo"], now["gross_hi"]) == (0.60, 0.75)
    assert not now["bonds_in_stack"]
    calm = buyside.regime_label(cpi_3m_ann=2.0, real10=0.5, fed=-1, brent_vs_5y=0.9, corr=-0.3, infl36=0.02)
    assert calm["label"] == "Easing, disinflation" and calm["gross_hi"] == 1.2 and calm["bonds_in_stack"]


def test_put_spread_pays_in_a_crash_and_costs_in_calm():
    idx = pd.date_range("2020-01-01", periods=3, freq="MS")
    px = pd.Series([0.0, -0.30, 0.02], index=idx)
    vix = pd.Series([15.0, 40.0, 30.0], index=pd.DatetimeIndex(["2019-12-31", "2020-01-31", "2020-02-28"]))
    ps = buyside.put_spread_returns(px, vix)
    assert ps.loc["2020-02-01"] > 0.05 and ps.loc["2020-03-01"] < 0


# ---------------------------------------------------------------- feeds: parsers, scoring, a run with dead sources
RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Dated Brent premium to futures hits $27 as Hormuz flows stall</title><link>https://x.example/a</link>
<description>&lt;p&gt;Physical &lt;b&gt;backwardation&lt;/b&gt; deepens&lt;/p&gt;</description><pubDate>Wed, 21 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Unrelated story</title><link>javascript:alert(1)</link><pubDate>Wed, 21 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>BDC redemption queue grows</title>
<link href="https://y.example/b"/><updated>2026-10-21T07:00:00Z</updated><summary>PIK share rises</summary></entry></feed>"""
TG = b"""<div class="tgme_widget_message_wrap"><div data-post="WalterBloomberg/101"><div class="tgme_widget_message_text js-message_text">
FED'S WALLER: ANOTHER RATE HIKE MAY BE NEEDED</div><span class="tgme_widget_message_views">12.5K</span>
<time datetime="2026-10-21T10:00:00+00:00" class="time">10:00</time></div></div>"""


def test_parsers_read_rss_atom_telegram_x_and_hn():
    r = feeds.parse_rss(RSS)
    assert r[0]["title"].startswith("Dated Brent") and "<" not in r[0]["text"] and r[0]["time"].year == 2026
    a = feeds.parse_rss(ATOM)
    assert a[0]["url"] == "https://y.example/b" and a[0]["text"] == "PIK share rises"
    t = feeds.parse_telegram(TG)
    assert t[0]["url"] == "https://t.me/WalterBloomberg/101" and t[0]["engagement"] == 12500 and "HIKE" in t[0]["title"]
    x = feeds.parse_x({"data": [{"id": "9", "text": "HBM sold out", "author_id": "1", "created_at": "2026-10-21T06:00:00Z",
                                 "public_metrics": {"like_count": 10, "retweet_count": 5}}], "includes": {"users": [{"id": "1", "username": "SemiAnalysis_"}]}})
    assert x[0]["url"] == "https://x.com/SemiAnalysis_/status/9" and x[0]["engagement"] == 20
    h = feeds.parse_hn({"hits": [{"title": "PJM capacity auction", "objectID": "5", "created_at": "2026-10-21T05:00:00Z", "points": 50}]})
    assert h[0]["url"].endswith("id=5")


def test_theme_matching_heat_and_lead():
    themes = [{"id": "c", "name": "Consumer", "terms": ["delinquen*", "umich"], "query": "q"}]
    items = [{"title": "Auto delinquencies jump", "text": ""}, {"title": "Delinquent? no", "text": ""}, {"title": "unrelated", "text": ""}]
    feeds.tag(items, themes)
    assert [it["themes"] for it in items] == [["c"], ["c"], []]
    assert feeds.heat(1, [0] * 28) < 2                      # one mention on a quiet theme is not news
    assert feeds.heat(12, [1, 2, 1, 0, 1] * 5) > 2
    niche = [0, 0, 5, 0, 0, 0, 8, 0, 0, 0, 3, 0, 0, 0, 6, 0, 0, 0, 9, 0, 0, 0, 4, 0, 0]
    main = [0, 0] + niche[:-2]                               # mainstream echoes niche two days later
    assert feeds.lead_days(niche, main) == 2
    assert feeds.lead_days(niche[:10], main[:10]) is None


def test_run_survives_dead_sources_and_scores_themes():
    cfg = feeds.load_config("feeds.toml")
    now = dt.datetime(2026, 10, 21, 12, tzinfo=dt.timezone.utc)

    def getter(url, user_agent=""):
        if "federalreserve" in url:
            return RSS
        if "t.me/s/" in url:
            return TG
        if "eventhorizoniq" in url:
            return ATOM
        if "hn.algolia" in url:
            return json.dumps({"hits": []}).encode()
        if "news.google" in url:
            return b"<rss><channel></channel></rss>"
        raise RuntimeError("feed is down")

    doc, hist = feeds.run(cfg, {}, getter=getter, now=now, token=None)
    names = {t["id"]: t for t in doc["themes"]}
    assert names["oil-physical"]["count24"] >= 1 and names["private-credit"]["count24"] >= 1 and names["fed-hike"]["count24"] >= 1
    assert any(f["source"] == "X" for f in doc["sources"]["failed"])      # no token: X skipped, said so
    assert len(doc["sources"]["failed"]) > 5 and doc["sources"]["ok"]
    assert all(it["url"].startswith("https://") or it["url"] == "" for it in doc["items"])
    assert "2026-10-21" in hist["days"] and doc["bluf"]
    doc2, _ = feeds.run(cfg, hist, getter=getter, now=now + dt.timedelta(days=1), token=None)
    assert doc2["themes"]


def test_source_registry_counts_every_source():
    r = sources.run("feeds.toml")
    assert r["count"] >= 80 and r["by_kind"]["series"] >= 40 and r["by_kind"]["telegram"] >= 1
