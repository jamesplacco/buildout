"""The long-history research recovers effects planted in synthetic data, and refuses to invent them."""
import numpy as np
import pandas as pd
import pytest

from buildout import research as rs


def _panel(n=900, seed=1, planted=True):
    """Monthly stock and bond returns whose correlation flips sign when inflation runs above 3%."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1900-01-01", periods=n, freq="MS")
    regime_hot = (np.arange(n) // 120) % 2 == 1                          # ten-year spells of hot inflation
    monthly_infl = np.where(regime_hot, 0.05, 0.015) / 12
    cpi = 100 * np.exp(np.cumsum(monthly_infl + rng.normal(0, 0.0005, n)))
    z1, z2 = rng.normal(size=n), rng.normal(size=n)
    rho = np.where(regime_hot, 0.5, -0.5) if planted else np.zeros(n)
    eq = 0.006 + 0.04 * z1
    bd = 0.003 + 0.02 * (rho * z1 + np.sqrt(1 - rho ** 2) * z2)
    return pd.DataFrame({"r_eq": eq, "r_bd": bd, "cpi": cpi}, index=idx)


def test_hedge_line_finds_a_planted_inflation_threshold():
    out = rs.hedge_line(_panel(), 36)
    rows = {r["bucket"]: r for r in out["rows"]}
    assert rows["0 to 2%"]["share_hedging"] > 0.8
    assert rows["4 to 6%"]["share_hedging"] < 0.2
    assert 0.015 <= out["line"] <= 0.05 and out["zone"][0] <= out["zone"][1]


def test_hedge_line_finds_nothing_when_nothing_is_planted():
    out = rs.hedge_line(_panel(planted=False, seed=2), 36)
    shares = [r["share_hedging"] for r in out["rows"] if r["months"] > 100]
    assert max(shares) - min(shares) < 0.35          # no regime: hedging is a coin flip in every bucket
    # and the engine must REJECT a threshold, not report the best of the noise
    assert out["status"] in ("no_reliable_threshold", "insufficient_evidence") and out["line"] is None and out["zone"] is None


def test_planted_threshold_survives_validation():
    out = rs.hedge_line(_panel(n=1500), 36)
    assert out["status"] == "ok" and out["bootstrap"]["gap_p05"] > 0.05
    assert all(w["held"] for w in out["walk_forward"]) and out["holdout"]["months"] == 120


def test_null_result_flows_through_cli_and_policy(tmp_path, capsys):
    """A null finding prints, writes, and switches the inflation gate to 'unavailable' instead of reusing an old line."""
    import json
    from buildout import policy as P
    from buildout.cli import research_line
    (tmp_path / "research.json").write_text(json.dumps({"hedge": {"line": None, "status": "no_reliable_threshold"}}))
    line, status = research_line(tmp_path)
    assert line is None and status == "no_reliable_threshold"
    d = P.tlt_decision("hedging", 0.031, line, status, 0.4)
    assert d["gates"]["inflation"]["status"] == "no_reliable_threshold" and d["on"] is True and d["ratio"] == 0.4
    assert research_line(tmp_path / "missing") == (None, "unavailable")


def test_hedge_experiment_is_information_timed():
    df = _panel(n=1500)
    df["y10"] = 4.0
    out = rs.hedge_experiment(df, start="1940-01-01")
    assert set(out["rules"]) == {"never", "always", "correlation_only", "correlation_and_inflation", "less_equity"}
    assert out["rules"]["never"]["share_on"] == 0 and out["rules"]["always"]["share_on"] == 1
    # with a planted regime, conditioning on inflation must not do worse in the tail than ignoring it
    assert out["rules"]["correlation_and_inflation"]["worst5"] >= out["rules"]["never"]["worst5"] - 1e-9


def test_fat_tails_counts_against_the_normal():
    rng = np.random.default_rng(5)
    normal = pd.Series(np.exp(rng.normal(0.005, 0.04, 20000)) - 1)
    rows = {r["sigma"]: r for r in rs.fat_tails(normal)["rows"]}
    assert rows[3]["observed"] == pytest.approx(rows[3]["expected_normal"], rel=0.45)
    t = pd.Series(np.exp(0.03 * rng.standard_t(3, 20000)) - 1)            # fat-tailed returns
    rows_t = {r["sigma"]: r for r in rs.fat_tails(t)["rows"]}
    assert rows_t[5]["observed"] > 20 * max(rows_t[5]["expected_normal"], 0.01)


def test_oil_shock_classification():
    days = pd.date_range("1995-01-01", "2012-12-31", freq="D")              # five years of history before the spike
    price = pd.Series(50.0, index=days)
    price[(days >= "2004-01-01") & (days < "2005-06-01")] = 100.0         # a spike far above its five-year average
    px = pd.Series(np.linspace(1000, 1500, len(days)), index=days)
    y10 = pd.Series(4.0, index=days)
    out = rs.oil_shocks(price, px, y10)
    assert [r["kind"] for r in out["rows"]] == ["supply"]
    assert out["rows"][0]["month"] == "2004-01" and out["summary"]["supply"]["n"] == 1


def test_inflation_spells():
    idx = pd.date_range("1990-01-01", periods=120, freq="MS")
    rate = np.r_[np.full(36, 0.02), np.full(24, 0.08), np.full(60, 0.01)] / 12
    cpi = pd.Series(100 * np.exp(np.cumsum(rate)), index=idx)
    out = rs.inflation_spells(cpi)
    assert len(out["episodes"]) == 1 and out["episodes"][0]["months"] is not None


def test_a_missing_month_never_shortens_a_window():
    """BLS published no October 2025 CPI. A dropped month must not turn a 12-month change into a 13-month one."""
    idx = pd.date_range("2023-01-01", "2026-09-01", freq="MS")
    cpi = pd.Series(300 * 1.003 ** np.arange(len(idx)), index=idx)        # exactly 0.3% a month
    gappy = cpi.drop(pd.Timestamp("2025-10-01"))
    full = rs.monthly_calendar(gappy)
    assert pd.Timestamp("2025-10-01") in full.index
    assert full["2025-10-01"] == pytest.approx(cpi["2025-10-01"], rel=1e-12)     # geometric fill of a geometric path
    yoy = full / full.shift(12) - 1
    assert yoy.iloc[-1] == pytest.approx(1.003 ** 12 - 1, rel=1e-12)
    naive = gappy / gappy.shift(12) - 1                                     # the bug: 13 months of inflation
    assert naive.iloc[-1] == pytest.approx(1.003 ** 13 - 1, rel=1e-12)
    long_gap = cpi.drop(pd.date_range("2025-06-01", "2025-09-01", freq="MS"))
    assert rs.monthly_calendar(long_gap)["2025-07-01":"2025-08-01"].isna().all()   # long gaps stay empty


def _synthetic_raw(seed=3):
    """Every input file in the shape the GitHub mirrors publish, with no gaps and a known structure."""
    rng = np.random.default_rng(seed)
    m = pd.date_range("1871-01-01", "2026-09-01", freq="MS")
    n = len(m)
    px = 4 * np.exp(np.cumsum(0.004 + 0.04 * rng.standard_t(4, n) / np.sqrt(2)))
    cpi = 10 * np.exp(np.cumsum(0.0025 + 0.004 * rng.normal(size=n)))
    y10 = np.clip(4 + np.cumsum(0.05 * rng.normal(size=n)), 0.5, 15)
    eps = px / 15 * np.exp(0.1 * np.sin(np.arange(n) / 30))
    sh = pd.DataFrame({"Date": m.strftime("%Y-%m-%d"), "SP500": px, "Dividend": px * 0.04, "Earnings": eps, "Consumer Price Index": cpi,
                       "Long Interest Rate": y10, "PE10": px / eps * 1.2})
    bls = pd.DataFrame({"Date": m[m >= "1913-01-01"].strftime("%Y-%m-%d"), "Index": cpi[m >= "1913-01-01"]})
    gs10 = pd.DataFrame({"Date": m[m >= "1953-04-01"].strftime("%Y-%m-%d"), "Rate": y10[m >= "1953-04-01"]})
    d = pd.bdate_range("1987-05-20", "2026-10-14")
    brent = pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Price": 20 * np.exp(np.cumsum(0.0002 + 0.02 * rng.normal(size=len(d))))})
    dv = pd.bdate_range("1990-01-02", "2026-10-19")
    lv = np.empty(len(dv)); lv[0] = np.log(18)
    for i in range(1, len(dv)):
        lv[i] = lv[i - 1] + 0.02 * (np.log(18) - lv[i - 1]) + 0.07 * rng.normal()
    vix = pd.DataFrame({"DATE": dv.strftime("%Y-%m-%d"), "CLOSE": np.exp(lv)})
    gold = pd.DataFrame({"Date": m.strftime("%Y-%m"), "Price": 20 * np.exp(np.cumsum(0.003 + 0.03 * rng.normal(size=n)))})
    return {"shiller": sh, "cpi": bls, "y10": gs10, "brent": brent, "vix": vix, "gold": gold}


def test_compact_output_has_exactly_the_pages_shape():
    """The daily run writes research.json in the shape the page's FINDINGS snapshot has, key for key."""
    import json
    import re
    from pathlib import Path
    out = rs.compact(rs.run(_synthetic_raw()))
    src = (Path(__file__).resolve().parent.parent / "site" / "src" / "research.js").read_text()
    page = json.loads(re.search(r"const FINDINGS = (\{.*?\});\n", src).group(1))

    def shape(x):
        if isinstance(x, dict):
            return {k: shape(v) for k, v in x.items()}
        if isinstance(x, list):
            return [shape(x[0])] if x and isinstance(x[0], (dict, list)) else "list"
        return "any" if x is None else "leaf"

    def same(a, b, path="root"):
        """'any' (a null) matches anything: a null result is a valid shape. Empty lists match any list."""
        if "any" in (a, b) or (a == "list" and isinstance(b, list)) or (b == "list" and isinstance(a, list)):
            return
        if isinstance(a, dict) and isinstance(b, dict):
            assert set(a) == set(b), (path, set(a) ^ set(b))
            for k in a:
                same(a[k], b[k], f"{path}.{k}")
        elif isinstance(a, list) and isinstance(b, list):
            same(a[0], b[0], path + "[]")
        else:
            assert a == b, (path, a, b)
    got, want = shape(out), shape(page)
    got.pop("source")
    same(got, want)
    assert out["panel"]["months"] == len(pd.date_range("1871-02-01", "2026-09-01", freq="MS"))
