"""v0.33: a blocked site fails fast instead of hanging the daily run; a missing file does not count as a blocked
site; FRED's official API is used when a key is set; every daily data step has its own limit and never blocks the
steps after it; the filings engine names a bad SEC contact string before it downloads anything."""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest
import yaml

from buildout.data import fred_source, http

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh_breaker():
    http.reset()
    yield
    http.reset()


def _patch(monkeypatch, handler):
    calls = []

    def fake(req, timeout=None):
        calls.append(req.full_url)
        return handler(req.full_url)
    monkeypatch.setattr(http.urllib.request, "urlopen", fake)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    return calls


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_blocked_host_is_skipped_after_two_failed_files(monkeypatch):
    def h(url):
        if "blocked.example" in url:
            raise urllib.error.URLError("timed out")
        return _Resp(b"ok")
    calls = _patch(monkeypatch, h)
    for i in range(2):
        with pytest.raises(RuntimeError):
            http.get(f"https://blocked.example/{i}")
    n = len(calls)
    assert n == 6                                                   # three tries each for the first two files
    for i in range(20):
        with pytest.raises(RuntimeError, match="skipped"):
            http.get(f"https://blocked.example/more{i}")
    assert len(calls) == n                                          # the other twenty never touched the network
    assert http.get("https://fine.example/x") == b"ok"             # other hosts are untouched


def test_a_missing_file_does_not_trip_the_breaker(monkeypatch):
    def h(url):
        if "missing" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return _Resp(b"{}")
    calls = _patch(monkeypatch, h)
    for i in range(5):
        with pytest.raises(RuntimeError, match="404"):
            http.get(f"https://data.sec.example/missing{i}")
    assert len(calls) == 5 and not http.host_down("https://data.sec.example/x")   # one try each, host still up
    assert http.get("https://data.sec.example/present") == b"{}"


def test_a_refusal_is_not_retried(monkeypatch):
    calls = _patch(monkeypatch, lambda url: (_ for _ in ()).throw(urllib.error.HTTPError(url, 403, "Forbidden", {}, None)))
    with pytest.raises(RuntimeError, match="HTTP 403"):
        http.get("https://www.sec.example/tickers")
    assert len(calls) == 1


def test_fred_uses_the_api_when_a_key_is_set(monkeypatch):
    body = json.dumps({"observations": [{"date": "2026-10-01", "value": "4.1"}, {"date": "2026-10-02", "value": "."}]}).encode()
    calls = _patch(monkeypatch, lambda url: _Resp(body if "api.stlouisfed.org" in url else b"DATE,X\n2026-10-01,9\n"))
    monkeypatch.setenv("FRED_API_KEY", "abc")
    s = fred_source.fetch("DGS10")
    assert "api.stlouisfed.org" in calls[0] and "api_key=abc" in calls[0] and list(s) == [4.1]
    monkeypatch.delenv("FRED_API_KEY")
    s2 = fred_source.fetch("DGS10")
    assert "fredgraph.csv" in calls[-1] and list(s2) == [9.0]


def test_every_daily_data_step_has_a_limit_and_never_blocks_the_rest():
    d = yaml.safe_load((ROOT / ".github" / "workflows" / "daily.yml").read_text())
    job = d["jobs"]["run"]
    assert job["timeout-minutes"] >= 60 and "FRED_API_KEY" in job["env"]
    data = [s for s in job["steps"] if "name" in s and not s["name"].startswith(("Install", "Smoke test", "Status", "Commit results"))]
    assert len(data) >= 15
    for s in data:
        assert s.get("continue-on-error") is True and 0 < s.get("timeout-minutes", 0) <= 20, s["name"]
    smoke = next(s for s in job["steps"] if s.get("name", "").startswith("Smoke test"))
    assert "pytest" in smoke["run"] and "tests/test_page.py" not in smoke["run"]


def test_filings_names_a_bad_contact_string_before_downloading(capsys, monkeypatch):
    from buildout import cli
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no download without a valid contact"))
    with pytest.raises(SystemExit):
        cli.main(["filings", "--ua", "Jamie Placco", "--out", str(ROOT / ".cache" / "t33")])
    assert "::error::SEC_USER_AGENT must be a name and an email" in capsys.readouterr().out
