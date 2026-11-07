"""v0.40: the walk-forward sizes the call with the live rule itself; the ledger's calls are marked daily (live.json)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from buildout import book as bk
from buildout import track

ROOT = Path(__file__).resolve().parents[1]


def _series(n=900, seed=4):
    idx = pd.bdate_range("2017-06-01", periods=n)
    rng = np.random.default_rng(seed)
    r = pd.Series(rng.normal(0.0005, 0.018, n), index=idx)
    q = r * 0.8 + pd.Series(rng.normal(0, 0.004, n), index=idx)
    cash = pd.Series(0.0001, index=idx)
    return r, q, cash


def test_the_walk_forward_takes_the_live_rule_when_given_one():
    r, q, cash = _series()
    mes = track.month_ends(r.index)[:-1]
    rule = pd.DataFrame({"size": 0.4, "binding": "drawdown_cap", "short": 0.6, "ok": True}, index=mes)
    rule.loc[mes[0], "ok"] = False                          # a month the live rule could not size falls back, marked
    W = track.walk_forward(r, q - cash, pd.Series(0.0, index=r.index), cash, None, rule)
    D = W["decisions"]
    assert (D["size"].iloc[1:] == 0.4).all() and (D["short"].iloc[1:] == 0.6).all()
    assert D["rule"].iloc[0] == "simple" and (D["rule"].iloc[1:] == "live").all()
    assert "call_simple" in W["policies"] and "call_simple" in track.POLICY_NAME
    W0 = track.walk_forward(r, q - cash, pd.Series(0.0, index=r.index), cash)
    assert "call_simple" not in W0["policies"] and (W0["decisions"]["rule"] == "simple").all()


def _prices(idx, seed=7):
    rng = np.random.default_rng(seed)
    out = {}
    for f in sorted({bk.FILE.get(k, k.lower()) for k in bk.BOOK} | set(bk.FACTOR_ETF.values())):
        c = 100 * np.cumprod(1 + rng.normal(0.0004, 0.015, len(idx)))
        out[f] = pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), "open": c, "high": c, "low": c, "close": c, "volume": 1e6})
    return out


def test_the_live_record_marks_each_call_from_its_effective_day():
    idx = pd.bdate_range("2026-09-01", "2026-11-13")
    P = _prices(idx)
    ust = pd.DataFrame({"DGS2": 4.0, "DGS10": 4.5, "DGS20": 4.8}, index=pd.bdate_range("2017-01-03", "2026-11-13"))
    rows = [{"ts_utc": "2026-11-03T15:00:00Z", "effective_from": "2026-11-04", "call": {"size": 0.6, "menu_high": {"gross": 1.0, "short": 0.85}}},
            {"ts_utc": "2026-11-05T15:00:00Z", "effective_from": "2026-11-09", "call": {"size": 0.5, "menu_high": {"gross": 1.0, "short": 0.9}}},
            {"ts_utc": "2026-11-06T15:00:00Z", "effective_from": "2026-11-09", "call": {"size": 0.55, "menu_high": {"gross": 1.0, "short": 0.88}}}]
    L = track.live_record(rows, P, ust)
    S = {d: (a, b, c, s) for d, a, b, c, s in L["series"]}
    assert L["first_effective"] == "2026-11-04" and min(S) == "2026-11-04" and L["marked_days"] == len(S)
    assert S["2026-11-05"][3] == 0.6 and S["2026-11-09"][3] == 0.55              # the newer of two calls effective the same day
    assert L["total"] == pytest.approx(S[max(S)][0] - 1, abs=1e-6) and "total_hedged" in L and L["stats"] is None
    assert track.live_record([], P, ust)["marked_days"] == 0


def test_daily_run_writes_live_json_and_the_page_reads_it():
    daily = (ROOT / ".github" / "workflows" / "daily.yml").read_text()
    assert "python -m buildout live --out site/data" in daily
    boot = (ROOT / "site" / "src" / "boot.js").read_text()
    assert 'loadJSON("data/live.json")' in boot
    T = json.loads(__import__("re").search(r"const SNAP38 = (\{.*\});", (ROOT / "site" / "src" / "snap38.js").read_text()).group(1))
    assert T["live_rule"]["months"] >= 100 and T["live_rule"]["fallbacks"] <= 3
    pol = T["pit"]["policies"]
    assert {"call", "call_short", "call_simple"} <= set(pol)
    assert T["live"]["marked_days"] >= 1 and len(T["live"]["series"]) == T["live"]["marked_days"]


def test_costs_never_raise_a_return():
    r, q, cash = _series()
    W = track.walk_forward(r, q - cash, pd.Series(0.0, index=r.index), cash)
    for k, (g, n, m) in W["policies"].items():
        assert g.notna().all() and n.notna().all() and (n <= g + 1e-12).all(), k


def test_v40_1_every_card_list_sits_under_a_section_heading():
    """Positions, Methods, Findings and Math lab put h3 cards straight under the h1; each list now has an h2 above it."""
    body = (ROOT / "site" / "src" / "body.html").read_text()
    for name, box in (("holdings", "ps-grid"), ("methods", "mt-list"), ("findings", "fi-read"), ("models", "lab-list")):
        at = body.index(f'id="{box}"')
        assert f'<h2 class="sr-only">The {name}</h2>' in body[at - 200:at], box


def test_v40_1_the_page_embeds_a_small_png_icon_and_a_light_logo():
    import base64, re
    head = __import__("scripts.assemble_page", fromlist=["assemble"]).assemble()[:400_000]
    icon = re.search(r'rel="icon" type="image/png" href="data:image/png;base64,([A-Za-z0-9+/=]+)"', head)
    assert icon and base64.b64decode(icon.group(1))[:8] == b"\x89PNG\r\n\x1a\n" and len(icon.group(1)) < 20_000
    assert len((ROOT / "site" / "src" / "logo.html").read_text()) < 60_000


def test_v40_1_live_chart_ticks_are_pairs():
    """xyChart reads ticks as [x, label]; bare numbers threw and emptied the Track desk."""
    js = (ROOT / "site" / "src" / "trackdesk.js").read_text()
    seg = js[js.index("function renderLive"):js.index("function renderTrack")]
    assert ".map((i) => [xs[i], " in seg and "xticks: xs.length > 1 ? [xs[0]" not in seg
