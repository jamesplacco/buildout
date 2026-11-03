"""v0.36: the Reading room's sources are complete, dated and mapped; the railway test on the page matches the engine;
thesis cards read the latest scorecard by date; house style in the new files."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from buildout import accounting as A

ROOT = Path(__file__).resolve().parents[1]


def _sources():
    s = (ROOT / "site" / "src" / "sources.js").read_text()
    i = s.index("const SOURCES = ")
    return json.loads(s[i + 16:s.index(";\n", i)].replace("<\\/", "</"))


def test_every_source_is_complete_dated_and_mapped():
    S = _sources()
    assert S["n"] == len(S["rows"]) >= 100
    lanes = {r["lane"] for r in S["rows"]}
    assert lanes == {"research", "data", "books", "dissent"}
    urls = [r["url"] for r in S["rows"]]
    assert len(urls) == len(set(urls))
    for r in S["rows"]:
        assert r["url"].startswith(("https://", "http://")) and r["claim"] and r["changes"] and r["who"]
        assert re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", r["date"]), r["date"]
        assert r["type"] in S["types"]
    theses = set(re.findall(r'\{ id: "(t\d+)"', (ROOT / "site" / "src" / "data.js").read_text()))
    for t in theses:
        assert any(t in r["bears_on"] for r in S["rows"]), t                          # every thesis has reading
    dissent = {t for r in S["rows"] if r["lane"] == "dissent" for t in r["bears_on"]}
    assert len(theses & dissent) >= 9                                                  # and nearly every one a dissent


def test_the_railway_test_matches_the_engine():
    C = sum(A.CAPEX_2026.values())
    r = A.required_revenue(C, 6, 0.09, 0.36)
    assert C == pytest.approx(730e9) and r["required_revenue"] == pytest.approx(730e9 * (1 / 6 + 0.09) / 0.36)
    run = sum(A.CLOUD_Q3_2026.values()) * 4
    js = (ROOT / "site" / "src" / "reading.js").read_text()
    assert "(46.0 + 30.7 + 63.9) * 4" in js and run == pytest.approx((46.0 + 30.7 + 63.9) * 4e9)
    assert 'value="730"' in (ROOT / "site" / "src" / "body.html").read_text()
    assert A.odlyzko_ratio(A.required_revenue(C, 3)["required_revenue"], run) > A.odlyzko_ratio(r["required_revenue"], run)


def test_thesis_cards_take_the_latest_scorecard_by_date():
    v = (ROOT / "site" / "src" / "views.js").read_text()
    assert "t.sc.slice().sort(" in v and "SC[SC.length - 1]" in v


def test_house_style():
    for p in ("site/src/reading.js", "scripts/snapshot_sources.py", "site/src/sources.js"):
        src = (ROOT / p).read_text().lower()
        for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
            assert b not in src, p
