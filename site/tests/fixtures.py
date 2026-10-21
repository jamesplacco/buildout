"""Engine-shaped data files for page tests, built from the synthetic market by the real engine code.

The numbers are synthetic by design; only the shapes matter. Nothing here is ever served to the site.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from buildout.config import default_config  # noqa: E402
from buildout.data.synthetic import simulate  # noqa: E402
from buildout.jsonout import write  # noqa: E402
from buildout.macro import analyze_macro  # noqa: E402
from buildout.pipeline import analyze, load_inputs, write_report  # noqa: E402
from buildout.fundamentals import analyze_company, parse_fixture  # noqa: E402
from buildout.research import compact, run  # noqa: E402
from buildout.status import build_status  # noqa: E402

BOOK = ["MSFT", "AMZN", "GOOGL", "META", "NVDA", "AVGO", "TSLA", "SPCX", "ORCL"]


def fake_fred(seed: int = 3) -> pd.DataFrame:
    w = simulate(BOOK, n_days=2520, seed=7)
    idx, rng = w.prices.index, np.random.default_rng(seed)
    d10, d30 = w.yields["DGS10"] + 2.5, w.yields["DGS30"] + 2.5
    df = pd.DataFrame(index=idx)
    df["NASDAQ100"] = w.prices["QQQ"] * 100
    for k, o in {"DGS1MO": -1.0, "DGS3MO": -0.9, "DGS6MO": -0.8, "DGS1": -0.65, "DGS2": -0.4, "DGS3": -0.3, "DGS5": -0.2, "DGS7": -0.1}.items():
        df[k] = d10 + o
    df["DGS10"], df["DGS20"], df["DGS30"] = d10, d30 + 0.05, d30
    walk = lambda base, s: base + rng.normal(0, s, len(idx)).cumsum()  # noqa: E731
    df["DFII10"], df["T10YIE"], df["THREEFYTP10"] = walk(1.5, 0.02), walk(2.3, 0.01), walk(0.3, 0.01)
    df["BAMLC0A0CM"], df["BAMLH0A0HYM2"] = np.abs(walk(1.1, 0.01)), np.abs(walk(3.5, 0.03)) + 1
    df["VIXCLS"], df["DTWEXBGS"] = np.abs(walk(18, 0.3)) + 10, walk(120, 0.2)
    df["DCOILBRENTEU"], df["DCOILWTICO"] = np.abs(walk(80, 1)) + 20, np.abs(walk(75, 1)) + 20
    # v0.4 market reads: more spreads, volatility indexes, prices, and the Fed's plumbing
    df["T5YIE"], df["T5YIFR"] = walk(2.4, 0.01), walk(2.3, 0.01)
    df["BAMLC0A4CBBB"], df["BAMLH0A3HYC"] = np.abs(walk(1.4, 0.01)), np.abs(walk(9.0, 0.05)) + 3
    df["VXNCLS"] = df["VIXCLS"] * 1.25
    df["VXVCLS"] = df["VIXCLS"] * 1.05 + 1
    df["SP500"] = w.prices["QQQ"] * 20
    df["DEXJPUS"], df["CBBTCUSD"] = np.abs(walk(150, 0.4)) + 50, np.abs(walk(60000, 900)) + 5000
    wed = idx[idx.dayofweek == 2]
    df.loc[wed, "WALCL"] = np.abs(walk(6.8e6, 2e3))[: len(wed)]
    df.loc[wed, "WTREGEN"] = np.abs(walk(8.0e5, 5e3))[: len(wed)]
    df.loc[wed, "WRESBAL"] = np.abs(walk(3.1e3, 8))[: len(wed)]
    df["RRPONTSYD"] = np.abs(walk(300, 3))
    df["IORB"] = 3.90
    df["SOFR"] = 3.90 + rng.normal(-0.02, 0.01, len(idx))
    # v0.5 macro state: monthly CPI and labor, daily curve, weekly conditions and claims
    month_starts = idx[~idx.to_period("M").duplicated()]
    df.loc[month_starts, "CPIAUCSL"] = 300 * np.exp(np.cumsum(rng.normal(0.0027, 0.002, len(month_starts))))
    df.loc[month_starts, "SAHMREALTIME"] = np.clip(walk(0.1, 0.03)[: len(month_starts)], -0.2, 1.2)
    df.loc[month_starts, "UNRATE"] = np.clip(walk(4.2, 0.05)[: len(month_starts)], 3, 9)
    df["T10Y3M"] = df["DGS10"] - df["DGS3MO"]
    fri = idx[idx.dayofweek == 4]
    df.loc[fri, "NFCI"] = walk(-0.5, 0.01)[: len(fri)]
    df.loc[fri, "ICSA"] = np.abs(walk(220000, 2000)[: len(fri)]) + 150000
    return df


def make_fixtures(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    write(analyze_macro(fake_fred(), failed={"THREEFYTP10": "fixture: simulated failure"}), out, "macro.json")
    cfg = default_config()
    cfg.data.source = "synthetic"
    rep = analyze(cfg, load_inputs(cfg))
    rep["summary"]["data"] = "fixture"          # pretend market data so the page renders the book panel
    write_report(rep, out)
    q = pd.date_range("2023-09-30", periods=12, freq="QE")
    companies = {}
    for t, (o0, c0) in {"GOOGL": (30, 12), "MSFT": (35, 14), "AMZN": (30, 18), "META": (22, 10), "ORCL": (5, 4), "TSLA": (4, 2.5), "SPCX": (2, 3)}.items():
        d = pd.DataFrame({"ocf": o0 * (1 + 0.03 * np.arange(12)), "capex": c0 * (1 + 0.12 * np.arange(12)), "long_term_debt": 50.0, "cash": 20.0}, index=q)
        d = d.iloc[-3:] if t == "SPCX" else d
        d["fcf"], d["capex_to_ocf"] = d["ocf"] - d["capex"], d["capex"] / d["ocf"]
        companies[t] = d.reset_index(names="quarter_end")
    facts = parse_fixture(ROOT / "tests" / "fixtures" / "sec_facts_2026q3.txt")
    ttm = {t: analyze_company(facts[t]) for t in ("MSFT", "GOOGL", "AMZN", "META", "ORCL")}
    ttm["MSFT"]["quarter_end"] = "2026-09-30"            # a newer filing than the page's snapshot
    write({"units": "USD billions", "companies": companies, "ttm": ttm, "skipped": []}, out, "capex.json")
    write(fake_research(), out, "research.json")
    from buildout import brain, buyside, sources
    raw = fake_raw()
    write(brain.run(raw), out, "brain.json")
    write(buyside.run(raw), out, "buyside.json")
    write(fake_feeds(), out, "feeds.json")
    write(sources.run(ROOT / "feeds.toml"), out, "sources.json")
    write(build_status(out, now=datetime(2026, 10, 20, 12, tzinfo=timezone.utc)), out, "status.json")
    return out


def fake_research(seed: int = 3) -> dict:
    """The long-history research run on synthetic files in the shape of the public datasets, through 2026-09."""
    return compact(run(fake_raw(seed)))


def fake_raw(seed: int = 3) -> dict:
    """Synthetic files in the shape of the public datasets, through 2026-09."""
    rng = np.random.default_rng(seed)
    m = pd.date_range("1871-01-01", "2026-09-01", freq="MS")
    n = len(m)
    px = 4 * np.exp(np.cumsum(0.004 + 0.04 * rng.standard_t(4, n) / np.sqrt(2)))
    infl = 0.0025 + 0.0045 * np.sin(np.arange(n) / 90)                # inflation regimes from deflation to above 6%
    cpi = 10 * np.exp(np.cumsum(infl + 0.003 * rng.normal(size=n)))
    y10 = np.clip(4 + np.cumsum(0.05 * rng.normal(size=n)), 0.5, 15)
    eps = px / 15 * np.exp(0.1 * np.sin(np.arange(n) / 30))
    sh = pd.DataFrame({"Date": m.strftime("%Y-%m-%d"), "SP500": px, "Dividend": px * 0.04, "Earnings": eps, "Consumer Price Index": cpi,
                       "Long Interest Rate": y10, "PE10": px / eps * 1.2})
    bls = pd.DataFrame({"Date": m[m >= "1913-01-01"].strftime("%Y-%m-%d"), "Index": cpi[m >= "1913-01-01"]})
    gs10 = pd.DataFrame({"Date": m[m >= "1953-04-01"].strftime("%Y-%m-%d"), "Rate": y10[m >= "1953-04-01"]})
    d = pd.bdate_range("1987-05-20", "2026-10-14")
    brent = pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Price": 20 * np.exp(np.cumsum(0.0002 + 0.02 * rng.normal(size=len(d))))})
    dv = pd.bdate_range("1990-01-02", "2026-10-19")
    vix = pd.DataFrame({"DATE": dv.strftime("%Y-%m-%d"), "CLOSE": np.exp(np.log(18) + 0.3 * np.sin(np.arange(len(dv)) / 40) + 0.05 * rng.normal(size=len(dv)))})
    gold = pd.DataFrame({"Date": m.strftime("%Y-%m"), "Price": 20 * np.exp(np.cumsum(0.003 + 0.03 * rng.normal(size=n)))})
    return {"shiller": sh, "cpi": bls, "y10": gs10, "brent": brent, "vix": vix, "gold": gold}


def fake_feeds() -> dict:
    """A feeds run over canned items: one niche Substack post, one Telegram wire item, one mainstream headline."""
    import datetime as dt
    from buildout import feeds
    now = dt.datetime(2026, 10, 21, 12, tzinfo=dt.timezone.utc)
    rss = b"""<rss><channel><item><title>Dated Brent premium to futures hits $27 as Hormuz flows stall</title><link>https://example.com/a</link>
<pubDate>Wed, 21 Oct 2026 08:00:00 GMT</pubDate></item><item><title>BDC redemption queue grows as PIK climbs</title><link>https://example.com/b</link>
<pubDate>Wed, 21 Oct 2026 07:00:00 GMT</pubDate></item></channel></rss>"""
    tg = b"""<div class="tgme_widget_message_wrap"><div data-post="WalterBloomberg/7"><div class="tgme_widget_message_text">FED'S WALLER: ANOTHER RATE HIKE MAY BE NEEDED</div>
<span class="tgme_widget_message_views">9K</span><time datetime="2026-10-21T10:00:00+00:00"></time></div></div>"""

    def getter(url, user_agent=""):
        if "t.me/s/" in url:
            return tg
        if "eventhorizoniq" in url or "news.google" in url:
            return rss
        if "hn.algolia" in url:
            return b'{"hits": []}'
        raise RuntimeError("offline fixture")
    doc, _ = feeds.run(feeds.load_config(ROOT / "feeds.toml"), {}, getter=getter, now=now)
    return doc


if __name__ == "__main__":
    print("wrote", make_fixtures(Path(sys.argv[1] if len(sys.argv) > 1 else "out/fixtures")))
