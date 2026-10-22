"""v0.16: technical and fundamental analysis, the data hub, the reinforcement-learning agent, the restricted
combination forecast, the faster layout, and the page's mirror of the broker-export reader. Planted answers throughout."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import datahub, ml, rl, statements, technicals as T

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _ohlc(n=1500, drift=0.0003, seed=1, mom=0.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, 0.015, n)
    if mom:
        for i in range(1, n):
            r[i] += mom * r[i - 1]
    c = 100 * np.exp(np.cumsum(r))
    h = c * (1 + np.abs(rng.normal(0, 0.008, n)))
    l = c * (1 - np.abs(rng.normal(0, 0.008, n)))
    return pd.DataFrame({"open": c, "high": h, "low": l, "close": c, "volume": rng.integers(1_000_000, 2_000_000, n).astype(float)},
                        index=pd.bdate_range("2019-01-01", periods=n))


# ---------------------------------------------------------------- technicals
def test_indicators_match_their_definitions():
    df = _ohlc(400)
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    assert T.sma(c, 20)[-1] == pytest.approx(c[-20:].mean())
    tr = T.true_range(h, l, c)
    assert tr[5] == pytest.approx(max(h[5] - l[5], abs(h[5] - c[4]), abs(l[5] - c[4])))
    a = T.atr(h, l, c, 14)
    assert a[13] == pytest.approx(tr[:14].mean()) and a[14] == pytest.approx(a[13] + (tr[14] - a[13]) / 14)
    k, d = T.stochastic(h, l, c)
    assert np.nanmin(k) >= 0 and np.nanmax(k) <= 100
    adx, pdi, mdi = T.adx(h, l, c)
    assert np.nanmin(adx) >= 0 and np.nanmax(adx) <= 100
    assert T.obv(np.array([1, 2, 1, 1, 3.0]), np.array([5, 7, 2, 4, 1.0]))[-1] == pytest.approx(0 + 7 - 2 + 0 + 1)
    f = T.fibonacci(np.array([1, 2, 3, 4, 5.0]), np.array([1, 2, 3, 4, 5.0]))
    assert f["direction"] == "up" and f["levels"]["0.500"] == pytest.approx(3.0)
    assert T.wma(np.arange(1, 6.0), 3)[-1] == pytest.approx((3 * 1 + 4 * 2 + 5 * 3) / 6)


def test_signals_never_look_ahead():
    df = _ohlc(800)
    s1 = T.signals(df)
    df2 = df.copy()
    df2.iloc[-50:, :] *= 1.5                                        # change only the future
    s2 = T.signals(df2)
    pd.testing.assert_frame_equal(s1.iloc[:-50], s2.iloc[:-50])


def test_event_study_finds_planted_momentum_and_noise_earns_little_weight():
    noise = T.analyze(_ohlc(3000, drift=0.0, seed=7), "noise")
    assert abs(noise["composite"]) < 0.25
    trend = T.analyze(_ohlc(3000, drift=0.0, seed=7, mom=0.25), "momentum")
    st = trend["studies"]
    assert st["macd"]["t"] > 2 and st["breakout_55"]["t"] > 0
    assert st["rsi_extreme"]["t"] is None or st["rsi_extreme"]["t"] < st["macd"]["t"]


def test_analysis_handles_close_only_series():
    df = _ohlc(600)[["close"]]
    a = T.analyze(df, "close only")
    assert not a["ohlc"] and "adx14" not in a["readings"] and a["structure"]["range_52w"]["high"] >= df["close"].iloc[-1]
    assert all(isinstance(x, str) for x in T.text(a))


# ---------------------------------------------------------------- fundamentals
def _facts(years: dict[str, dict[str, float]]) -> dict:
    """years: fiscal year end -> line -> value, turned into company facts with annual durations."""
    tag = {k: v[0] for k, v in statements.TAGS.items()}
    out = {}
    for end, lines in years.items():
        e = pd.Timestamp(end)
        for k, v in lines.items():
            row = {"end": end, "val": v, "form": "10-K", "filed": str((e + pd.Timedelta(days=60)).date())}
            if k in statements.FLOWS:
                row["start"] = str((e - pd.Timedelta(days=364)).date())
            out.setdefault(tag[k], []).append(row)
    return {"facts": {"us-gaap": {t: {"units": {"USD": rows}} for t, rows in out.items()}}}


GOOD = {"2023-12-31": dict(revenue=100, gross_profit=40, op_income=15, net_income=10, cfo=14, capex=5, assets=200, current_assets=60, current_liabilities=40, debt=50,
                            shares=10, equity=100, liabilities=100, retained=50, receivables=10, ppe=80, da=5, sga=10, cash=20),
        "2024-12-31": dict(revenue=120, gross_profit=50, op_income=20, net_income=14, cfo=20, capex=6, assets=210, current_assets=70, current_liabilities=40, debt=45,
                            shares=9.8, equity=115, liabilities=95, retained=64, receivables=12, ppe=82, da=6, sga=11, cash=25)}


def test_piotroski_altman_and_ratios_on_a_planted_company():
    a = statements.analyze(_facts(GOOD), "GOOD")
    p = a["piotroski"]
    assert p["known"] == 9 and p["score"] == 9, p["tests"]
    r = a["ratios"][-1]
    assert r["revenue_growth"] == pytest.approx(0.2) and r["fcf"] == pytest.approx(14) and r["cash_conversion"] == pytest.approx(20 / 14)
    assert r["op_margin"] == pytest.approx(20 / 120) and r["rule_of_40"] == pytest.approx(0.2 + 14 / 120)
    z = a["altman_z2"]
    assert z["z"] == pytest.approx(6.56 * 30 / 210 + 3.26 * 64 / 210 + 6.72 * 20 / 210 + 1.05 * 115 / 95)
    v = statements.analyze(_facts(GOOD), "GOOD", price=20.0)["valuation"]
    assert v["market_cap"] == pytest.approx(196.0) and v["pe"] == pytest.approx(14.0)


def test_beneish_is_neutral_when_nothing_changes_and_unknowns_stay_unknown():
    same = {"2023-12-31": GOOD["2023-12-31"], "2024-12-31": dict(GOOD["2023-12-31"], cfo=10)}
    b = statements.beneish(*[{k: float(v) for k, v in d.items()} for d in (same["2024-12-31"], same["2023-12-31"])][::1])
    assert b["m"] == pytest.approx(-4.84 + 0.92 + 0.528 + 0.404 + 0.892 + 0.115 - 0.172 - 0.327)
    thin = statements.analyze(_facts({k: {x: v[x] for x in ("revenue", "cfo", "capex", "op_income")} for k, v in GOOD.items()}), "THIN")
    assert thin["piotroski"]["known"] < 9 and all(v is None for k, v in thin["piotroski"]["tests"].items() if k in ("no_dilution", "current_ratio_rising"))


def test_fixture_companies_parse_and_report_their_tags():
    from buildout import fundamentals
    u = fundamentals.parse_fixture(ROOT / "tests" / "fixtures" / "sec_facts_2026q3.txt")
    F = statements.from_fixture_rows(u)
    msft = statements.analyze(F["MSFT"], "MSFT")
    assert msft["ok"] and msft["fiscal_year_end"] == "2026-06-30" and msft["tags"]["capex"] == "PaymentsToAcquirePropertyPlantAndEquipment"
    assert msft["ratios"][-1]["capex_to_da"] > 1


# ---------------------------------------------------------------- the data hub
def test_yahoo_and_stooq_parsers_adjust_and_clean():
    js = {"chart": {"result": [{"timestamp": [1700000000, 1700086400, 1700172800], "indicators": {
        "quote": [{"open": [10, 11, None], "high": [11, 12, None], "low": [9, 10, None], "close": [10, 12, None], "volume": [100, 200, None]}],
        "adjclose": [{"adjclose": [5, 6, None]}]}}]}}
    df = datahub.parse_yahoo(js)
    assert len(df) == 2 and df["close"].tolist() == [5, 6] and df["high"].iloc[1] == pytest.approx(6.0)
    csv = "Date,Open,High,Low,Close,Volume\n2026-10-20,1,2,0.5,1.5,100\n2026-10-21,1.5,2,1,1.8,200\nbad,row\n"
    s = datahub.parse_stooq(csv)
    assert list(s["close"]) == [1.5, 1.8] and s.index[-1] == pd.Timestamp("2026-10-21")


def test_ohlcv_falls_back_in_order_and_records_errors(monkeypatch):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    monkeypatch.setattr(datahub, "yahoo", lambda t, years=10: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(datahub, "stooq", lambda t: _ohlc(300))
    df, src, errs = datahub.ohlcv("NVDA")
    assert src == "stooq" and len(df) == 300 and errs["databento"] == "no key" and "blocked" in errs["yahoo"]


def test_broker_export_reader_handles_common_layouts(tmp_path):
    rh = tmp_path / "rh.csv"
    rh.write_text("﻿Symbol,Quantity,Price,Name\nNVDA,10,100,Nvidia\nMSFT,2,500,Microsoft\nCASH,1,50,\n")
    p = datahub.import_positions(rh)
    assert p["weights"] == pytest.approx({"MSFT": 0.5, "NVDA": 0.5}) and p["n"] == 2
    sw = tmp_path / "sw.csv"
    sw.write_text('Symbol,Market Value\n"AAPL","$1,500.00"\nBRK.B,"$500"\nAccount Total,"$2,000"\n')
    assert datahub.import_positions(sw)["weights"] == pytest.approx({"AAPL": 0.75, "BRK.B": 0.25})
    with pytest.raises(ValueError):
        bad = tmp_path / "bad.csv"
        bad.write_text("Name,Value\nx,1\n")
        datahub.import_positions(bad)


def test_page_reads_broker_exports_like_python(tmp_path):
    texts = ["Symbol,Quantity,Price\nNVDA,10,100\nMSFT,2,500\nCASH,1,50\n", 'Symbol,Market Value\n"AAPL","$1,500.00"\nBRK.B,"$500"\nAccount Total,"$2,000"\n',
             "Ticker,Weight\nQQQ,60%\nTLT,40%\n"]
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness16.js")], input=json.dumps({"csv": texts}), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)["weights"]
    for t, j in zip(texts, js):
        f = tmp_path / "x.csv"
        f.write_text(t)
        py = datahub.import_positions(f)
        assert j["weights"] == pytest.approx(py["weights"]) and j["n"] == py["n"]


def test_connection_check_reports_every_source_and_never_a_secret(monkeypatch):
    monkeypatch.setenv("DATABENTO_API_KEY", "db-SECRET123")
    monkeypatch.setattr(datahub.http, "get", lambda url, **kw: (_ for _ in ()).throw(RuntimeError("offline")))
    rows = datahub.check()
    assert {r["source"] for r in rows} == set(datahub.SOURCES)
    assert "SECRET" not in json.dumps(rows)
    db = next(r for r in rows if r["source"] == "databento")
    assert db["credential"] is True and db["reachable"] is False and db["ok"] is False


# ---------------------------------------------------------------- reinforcement learning
def test_rl_rewards_match_and_the_agent_learns_a_planted_policy():
    r = np.random.default_rng(1).normal(0.005, 0.04, 40)
    R = rl.rewards(r, 2.0)
    assert all(abs(R[t, p, a] - rl.reward(rl.ACTIONS[a], rl.ACTIONS[p], r[t], 2.0)) < 1e-12 for t in range(40) for p in range(4) for a in range(4))
    rng = np.random.default_rng(2)
    b = rng.integers(0, 54, 4000)
    ret = np.where(b >= 27, 0.02, -0.02) + rng.normal(0, 0.01, 4000)      # trend-on states pay, trend-off states lose
    Q = rl.fit(b, ret, 0.9, 0.0, 5)
    assert all(rl.ACTIONS[rl.act(Q, s, 2)] >= 1.0 for s in range(27, 54))
    assert all(rl.ACTIONS[rl.act(Q, s, 2)] == 0.0 for s in range(0, 27))


def test_rl_states_use_only_earlier_data():
    idx = pd.date_range("1900-01-01", periods=300, freq="MS")
    D = pd.DataFrame({"r": 0.0, "trend": 1.0, "vol": np.linspace(0, 1, 300), "cape": np.linspace(10, 40, 300), "dd": 0.0}, index=idx)
    a = rl.encode(D, 150)
    D2 = D.copy()
    D2.iloc[150:, D2.columns.get_loc("vol")] = 99.0
    b = rl.encode(D2, 150)
    assert (a[:150] == b[:150]).all()


# ---------------------------------------------------------------- ML: the restricted combination and accuracy weights
def test_combination_obeys_its_sign_restrictions_and_floor():
    X = np.column_stack([np.linspace(0, 1, 200)] * len(ml.FEATURES))
    y = 0.05 + 0.1 * X[:, 0]                                            # log_cape with a positive slope: the wrong sign
    m = ml.Combination(ml.FEATURES).fit(X, y)
    assert m.coef[0][0] == 0.0
    assert (m.predict(np.full((3, len(ml.FEATURES)), -50.0)) >= 0).all()


def test_dmspe_weights_use_only_outcomes_already_known():
    rng = np.random.default_rng(3)
    n = 120
    y = rng.normal(size=n)
    P = [rng.normal(size=n), rng.normal(size=n)]
    ok = np.ones(n, bool)
    a = ml.dmspe(P, y, ok)
    y2 = y.copy()
    y2[80:] += 100
    b = ml.dmspe(P, y2, ok)
    assert np.allclose(a[:80 + ml.H + 1], b[:80 + ml.H + 1])


# ---------------------------------------------------------------- speed and the shipped page
def test_galaxy_layout_is_fast_and_deterministic():
    from buildout import mind
    rng = np.random.default_rng(0)
    n = 900
    G = {"nodes": [{"id": str(i), "g": f"g{i % 12}"} for i in range(n)], "edges": [[int(a), int(b), 1.0, 0] for a, b in rng.integers(0, n, (3000, 2)) if a != b]}
    t = time.time()
    mind.place(G)
    first = [(x["x"], x["y"]) for x in G["nodes"]]
    assert time.time() - t < 20
    mind.place(G)
    assert first == [(x["x"], x["y"]) for x in G["nodes"]]


def test_mcp_and_page_ship_v16():
    from buildout import mcp_server as MS
    c = MS.Context()
    assert MS.technical_analysis(c, {"ticker": "BRENT"})["name"].startswith("Brent")
    t = MS._snap16("technicals")["assets"]
    assert set(t) >= {"brent", "wti", "gas", "vix"}
    assert MS.rl_policy(c, {})["now"]["action"] in rl.ACTIONS
    assert MS.fundamental_analysis(c, {"ticker": "MSFT"})["ok"]
    with pytest.raises(MS.ToolError):
        MS.technical_analysis(c, {"ticker": "ZZZZ"})
    page = (ROOT / "site" / "page.html").read_text()
    for id_ in ("view-analysis", "an-ev", "an-co", "an-conn", "an-file", "rlx-curve", "ed-dist"):
        assert f'id="{id_}"' in page, id_
    low = page.lower()
    assert chr(0x2014) not in page and ("inter" "section") not in low and ("load" "-bearing") not in low
