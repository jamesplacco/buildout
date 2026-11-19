"""v0.47: the track command ranks the point-in-time universe among every candidate, and the tear sheet builds from
the day's track.json.

Before, `python -m buildout track` downloaded the nine names of today's book, so the universe "chosen point in time
each January" was chosen among today's survivors: holding read a worst drawdown of 44% where the published record,
built from all sixteen candidates, says 52%. The command now pulls every candidate, and a missing candidate is an
error rather than a shorter list.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from buildout import book as bk
from buildout import cli, track

ROOT = Path(__file__).resolve().parents[1]


def _prices(with_all: bool):
    prices, ust, _ = bk.synthetic(seed=7, days=900)
    if with_all:
        for t in track.CANDIDATES:
            if t not in prices:
                prices[t] = prices[bk.FILE.get("NVDA", "nvda")].copy()
    return prices, ust


def test_a_missing_candidate_is_an_error_not_a_shorter_list():
    prices, ust = _prices(with_all=False)
    missing = [t for t in track.CANDIDATES if t not in prices]
    assert missing, "the synthetic world carries the book, not the wider candidate list"
    cal = bk.panel(prices, ust)["R"].index
    with pytest.raises(ValueError, match="every candidate"):
        track.pit_book(prices, cal)
    prices, ust = _prices(with_all=True)
    _, members, _ = track.pit_book(prices, bk.panel(prices, ust)["R"].index)
    assert members


def test_the_track_command_downloads_every_candidate(monkeypatch, tmp_path):
    asked = {}

    def fake_download(cache=None, book=bk.BOOK, validate=True):
        asked["files"] = sorted({bk.FILE.get(k, k.lower()) for k in book})
        raise SystemExit(0)                      # the download is what is under test; the record itself takes minutes

    monkeypatch.setattr(bk, "download", fake_download)
    monkeypatch.setattr(sys, "argv", ["buildout", "track", "--out", str(tmp_path)])
    with pytest.raises(SystemExit):
        cli.main()
    assert set(track.CANDIDATES) <= set(asked["files"]), "the walk-forward universe needs every candidate's prices"
    assert {bk.FILE.get(k, k.lower()) for k in bk.BOOK} <= set(asked["files"])


def test_the_daily_run_rebuilds_the_record_and_the_tear_sheet():
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "daily.yml").read_text())
    runs = "\n".join(s.get("run", "") for s in wf["jobs"]["run"]["steps"])
    assert "buildout track --out site/data" in runs
    assert "snapshot_v38.py --pdf-only --track-json site/data/track.json" in runs
    assert "site/tearsheet.pdf" in runs, "the rebuilt tear sheet is committed with the day's data"


def test_the_tear_sheet_builds_from_a_track_file(tmp_path):
    pytest.importorskip("matplotlib")
    sys.path.insert(0, str(ROOT / "scripts"))
    import snapshot_v38 as snap
    s = (ROOT / "site" / "src" / "snap38.js").read_text()
    i = s.index("const SNAP38 = ")
    T = json.loads(s[i + 15:s.rindex(";")].replace("<\\/", "</"))
    out = tmp_path / "tear.pdf"
    pdf = snap.tearsheet_pdf(T, out, generated="Nov 19, 2026")
    assert pdf[:5] == b"%PDF-" and out.stat().st_size > 20_000
    assert snap._signed(-0.0001) == "0.0%" and snap._signed(0.0312) == "+3.1%" and snap._num(-0.001) == "0.00"   # never a negative zero
    assert snap._nice("2026-11-17") == "Nov 17, 2026" and snap._nice("2026-09") == "Sep 2026"
    assert snap._signed(-0.0312) == "\u22123.1%" and snap._num(-0.25) == "\u22120.25"      # a minus sign, as the pages print it


def test_the_book_step_waits_for_the_mirror_and_for_nothing_else(tmp_path):
    """A pull that ends a session short is retried until the mirror catches up; any other failure raises at once."""
    (tmp_path / "msft.csv").write_text("stale")
    (tmp_path / "cross_check.json").write_text("{}")
    t = {"now": 0.0, "slept": [], "calls": 0}

    class FakeBook:
        LAST_VALIDATION: dict = {}

        @staticmethod
        def download(cache):
            t["calls"] += 1
            if t["calls"] < 3:
                FakeBook.LAST_VALIDATION = {"asof": "2026-11-16", "expected_asof": "2026-11-17"}
                raise ValueError("price validation failed: msft: ends before the last completed session")
            return {"ok": True}

    def sleep(s):
        t["slept"].append(s); t["now"] += s

    out = cli._download_when_fresh(FakeBook, str(tmp_path), 30, sleep=sleep, clock=lambda: t["now"])
    assert out == {"ok": True} and t["calls"] == 3 and t["slept"] == [300.0, 300.0]
    assert not list(tmp_path.glob("*.csv")) and not (tmp_path / "cross_check.json").exists(), "a short pull is not left in the day's cache"

    class Late(FakeBook):                       # still short when the wait runs out: the step fails, it does not size on old prices
        @staticmethod
        def download(cache):
            Late.LAST_VALIDATION = {"asof": "2026-11-16", "expected_asof": "2026-11-17"}
            raise ValueError("price validation failed")

    t.update(now=0.0, slept=[])
    with pytest.raises(ValueError):
        cli._download_when_fresh(Late, None, 10, sleep=sleep, clock=lambda: t["now"])
    assert sum(t["slept"]) == pytest.approx(600.0)

    class Jump(FakeBook):                       # prices are current and something else is wrong: no waiting
        @staticmethod
        def download(cache):
            Jump.LAST_VALIDATION = {"asof": "2026-11-17", "expected_asof": "2026-11-17"}
            raise ValueError("price validation failed: nvda: an unexplained one-day fall")

    t.update(now=0.0, slept=[])
    with pytest.raises(ValueError, match="unexplained"):
        cli._download_when_fresh(Jump, None, 60, sleep=sleep, clock=lambda: t["now"])
    assert t["slept"] == []


def test_the_ledger_is_anchored_outside_the_repository():
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "daily.yml").read_text())
    perms = wf["permissions"]
    assert perms.get("id-token") == "write" and perms.get("attestations") == "write"
    steps = wf["jobs"]["run"]["steps"]
    ids = [s.get("id") for s in steps]
    anchor = next(s for s in steps if s.get("id") == "anchor")
    assert anchor["uses"].startswith("actions/attest-build-provenance@") and anchor["with"]["subject-path"] == "ledger/calls.jsonl"
    assert ids.index("anchor") > ids.index("commit"), "the digest signed is the ledger as committed"
    assert anchor.get("continue-on-error") is True, "an outage at the transparency log never loses the day's data"
