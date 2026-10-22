"""v0.18: the engine's framework (cache, runner, contracts, doctor, bench) under faults, the faster mind, and property
tests of the bond lab. Faults are planted: crashes, hangs, bad output, corrupted cache entries, unwritable folders."""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from buildout import bondlab as B
from buildout.core import cache, contracts, runner
from buildout.core.runner import Task

CURVE = {"1m": .0409, "2m": .0416, "3m": .0425, "4m": .0434, "6m": .0435, "1y": .0452, "2y": .0481, "3y": .0489, "5y": .0495,
         "7y": .0503, "10y": .0513, "20y": .0547, "30y": .0542}


@pytest.fixture()
def tmpcache(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDOUT_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("BUILDOUT_NO_CACHE", raising=False)
    for k in cache.STATS:
        cache.STATS[k] = 0
    return tmp_path / "cache"


# ---------------------------------------------------------------- cache
CALLS = {"n": 0}


@cache.memo("test.square")
def _square(x, scale=1):
    CALLS["n"] += 1
    return {"v": np.asarray(x) ** 2 * scale}


def test_memo_hits_on_equal_data_and_misses_on_different(tmpcache):
    CALLS["n"] = 0
    a = _square([1, 2, 3])
    b = _square([1, 2, 3])
    c = _square([1, 2, 4])
    assert CALLS["n"] == 2 and np.array_equal(a["v"], b["v"]) and not np.array_equal(a["v"], c["v"])
    assert cache.STATS["hits"] == 1 and cache.STATS["misses"] == 2


def test_digest_is_canonical():
    assert cache.digest({"a": 1, "b": [1, 2]}) == cache.digest({"b": [1, 2], "a": 1})
    df1 = pd.DataFrame({"x": [1.0, 2.0]}, index=pd.date_range("2020", periods=2))
    assert cache.digest(df1) == cache.digest(df1.copy()) and cache.digest(df1) != cache.digest(df1 * 2)
    assert cache.digest(np.arange(3.0)) != cache.digest(np.arange(3))         # dtype matters


def test_a_corrupted_entry_is_dropped_and_recomputed(tmpcache):
    CALLS["n"] = 0
    _square([5])
    entry = next(Path(tmpcache).glob("*/*.pkl"))
    entry.write_bytes(entry.read_bytes()[:20])                                   # truncated mid-write
    assert _square([5])["v"].tolist() == [25] and CALLS["n"] == 2 and cache.STATS["errors"] >= 1


def test_an_unwritable_cache_never_breaks_the_computation(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("BUILDOUT_CACHE", str(blocker))
    assert _square([3])["v"].tolist() == [9]


def test_require_bypasses_impure_calls(tmpcache):
    n = {"k": 0}

    @cache.memo("test.fetchy", require=("dl",))
    def f(dl=None):
        n["k"] += 1
        return n["k"]
    assert f() == 1 and f() == 2                                                # dl missing: runs every time
    assert f(dl={"a": 1}) == 3 and f(dl={"a": 1}) == 3                          # dl given: cached


def test_fetch_falls_back_to_the_last_good_copy(tmpcache):
    v, meta = cache.fetch("test.feed", lambda: {"rows": 3}, max_age=0)
    assert v == {"rows": 3} and meta["source"] == "live"

    def broken():
        raise ConnectionError("source down")
    v2, meta2 = cache.fetch("test.feed", broken, max_age=0)
    assert v2 == {"rows": 3} and meta2["stale"] is True and "source down" in meta2["error"]
    with pytest.raises(ConnectionError):
        cache.fetch("test.never", broken, max_age=0)


def test_disabled_cache_still_computes(monkeypatch, tmp_path):
    monkeypatch.setenv("BUILDOUT_NO_CACHE", "1")
    monkeypatch.setenv("BUILDOUT_CACHE", str(tmp_path / "c"))
    CALLS["n"] = 0
    _square([2])
    _square([2])
    assert CALLS["n"] == 2 and not (tmp_path / "c").exists()


# ---------------------------------------------------------------- runner (task functions live at module level so a forked child can run them)
def _write_a(out: Path):
    (out / "a.json").write_text(json.dumps({"schema": 2, "x": 1}))


def _read_a_write_b(out: Path):
    x = json.loads((out / "a.json").read_text())["x"]
    (out / "b.json").write_text(json.dumps({"schema": 2, "x": x + 1}))


def _sleep_one(out: Path):
    time.sleep(1.0)


def _hang(out: Path):
    time.sleep(30)


def _crash(out: Path):
    os._exit(3)


def _raise(out: Path):
    raise RuntimeError("planted failure")


def _write_nan(out: Path):
    (out / "c.json").write_text('{"schema": 2, "x": NaN}')


def _flaky(out: Path):
    f = out / "attempts"
    n = int(f.read_text()) if f.exists() else 0
    f.write_text(str(n + 1))
    if n == 0:
        raise ConnectionError("first try fails")
    (out / "d.json").write_text(json.dumps({"schema": 2}))


def test_runner_respects_dependencies_and_records_hashes(tmp_path):
    m = runner.run([Task("b", _read_a_write_b, ["a.json"], ["b.json"]), Task("a", _write_a, [], ["a.json"])], tmp_path, jobs=2)
    assert m["levels"] == [["a"], ["b"]]
    assert m["tasks"]["a"]["status"] == m["tasks"]["b"]["status"] == "ok"
    assert json.loads((tmp_path / "b.json").read_text())["x"] == 2 and m["tasks"]["b"]["inputs"]["a.json"]


def test_runner_runs_independent_tasks_in_parallel(tmp_path):
    m = runner.run([Task(f"s{i}", _sleep_one) for i in range(2)], tmp_path, jobs=2)
    assert m["serial_seconds"] >= 1.95 and m["wall_seconds"] < 0.8 * m["serial_seconds"] and m["speedup"] > 1.25


def test_a_hung_engine_is_stopped_and_the_rest_finish(tmp_path):
    t0 = time.perf_counter()
    m = runner.run([Task("hang", _hang, timeout=0.5), Task("a", _write_a, writes=["a.json"])], tmp_path, jobs=2)
    assert m["tasks"]["hang"]["status"] == "timeout" and m["tasks"]["a"]["status"] == "ok" and time.perf_counter() - t0 < 10


def test_a_crashing_engine_is_isolated(tmp_path):
    m = runner.run([Task("crash", _crash), Task("a", _write_a, writes=["a.json"])], tmp_path, jobs=2)
    assert m["tasks"]["crash"]["status"] == "failed" and "exit code 3" in m["tasks"]["crash"]["error"] and m["tasks"]["a"]["status"] == "ok"


def test_failure_and_bad_output_restore_the_last_good_files(tmp_path):
    (tmp_path / "c.json").write_text(json.dumps({"schema": 2, "x": 7}))
    m = runner.run([Task("nan", _write_nan, writes=["c.json"])], tmp_path)
    r = m["tasks"]["nan"]
    assert r["status"] == "rejected" and r["kept_last_good"] and any("non-finite" in p or "not valid JSON" in p for p in r["contract"])
    assert json.loads((tmp_path / "c.json").read_text())["x"] == 7
    (tmp_path / "e.json").write_text(json.dumps({"schema": 2, "keep": True}))
    m2 = runner.run([Task("boom", _raise, writes=["e.json"])], tmp_path)
    assert m2["tasks"]["boom"]["status"] == "failed" and "planted failure" in m2["tasks"]["boom"]["error"]
    assert json.loads((tmp_path / "e.json").read_text())["keep"] is True


def test_retries_with_backoff_recover_a_flaky_engine(tmp_path):
    m = runner.run([Task("flaky", _flaky, writes=["d.json"], retries=2, backoff=0.05)], tmp_path)
    r = m["tasks"]["flaky"]
    assert r["status"] == "ok" and r["attempts"] == 2 and "first try fails" in r["errors"][0]


def test_dependents_of_a_failed_engine_run_on_last_good_inputs(tmp_path):
    _write_a(tmp_path)
    m = runner.run([Task("a", _raise, writes=["a.json"]), Task("b", _read_a_write_b, ["a.json"], ["b.json"])], tmp_path)
    assert m["tasks"]["b"]["status"] == "ok" and m["tasks"]["b"]["stale_inputs"] == ["a"]


def test_a_cycle_is_refused_before_anything_runs(tmp_path):
    with pytest.raises(runner.CycleError):
        runner.run([Task("x", _write_a, ["y.json"], ["x.json"]), Task("y", _write_a, ["x.json"], ["y.json"])], tmp_path)
    assert not list(tmp_path.glob("*.json"))


def test_the_engine_registry_runs_through_the_runner(tmp_path):
    from buildout import engine
    m = engine.run(tmp_path, only=["voices", "status"], jobs=2)
    rows = {r["name"]: r for r in m["engines"]}
    assert rows["voices"]["status"] == "ok" and rows["status"]["status"] == "ok" and m["runner"]["jobs"] == 2
    assert contracts.check(tmp_path / "engines.json") == []


# ---------------------------------------------------------------- contracts
def test_contracts_catch_missing_fields_ranges_and_nonfinite():
    spec = contracts.C(required=["a.b"], finite=["a.b"], ranges={"a.b": (0, 1)}, nonempty=["l"])
    assert contracts.check_obj("x.json", {"schema": 2, "a": {"b": 0.5}, "l": [1]}, spec) == []
    bad = contracts.check_obj("x.json", {"a": {"b": 2.0}, "l": [], "z": [1.0, float("inf")]}, spec)
    assert any("schema" in b for b in bad) and any("outside" in b for b in bad) and any("empty" in b for b in bad) and any("non-finite" in b for b in bad)


# ---------------------------------------------------------------- doctor and bench
def test_doctor_finds_nothing_broken_in_this_repository():
    from buildout.core import doctor
    rows = doctor.run()
    fails = [r for r in rows if r[0] == "FAIL"]
    assert not fails, fails
    assert any("bond ladders" in r[1] for r in rows) and any("mind graph" in r[1] for r in rows)


def test_bench_measures_the_mind_and_the_bond_lab():
    from buildout.core import bench
    m, b = bench.mind_bench(), bench.bonds_bench()
    assert m["nodes"] > 8000 and m["think_ms"] > 0 and b["scenario_ms"] > 0
    p = bench.page_bench()
    assert "think_ms" in p or "skipped" in p


def test_python_mind_is_fast():
    from buildout import mind
    G = json.loads((Path(__file__).resolve().parents[1] / "buildout" / "assets" / "mind.json").read_text())
    M = mind.Mind(G)
    M.think("Is the stock market overvalued?")
    t = time.perf_counter()
    for _ in range(3):
        M.think("Should I buy long bonds?")
    assert (time.perf_counter() - t) / 3 < 0.5                                 # was about 0.4s before v0.18 on this machine; now well under


# ---------------------------------------------------------------- bond lab properties
@settings(max_examples=60, deadline=None)
@given(st.floats(0.005, 0.12), st.floats(0.0005, 0.03))
def test_ladder_price_falls_as_yields_rise_and_bends_upward(y, d):
    F = B.setup(CURVE, {"TLT": {"duration": 14.85, "wam": 26.04}})
    v = lambda a: B.scenario(CURVE, {"TLT": F["TLT"]}, a, a + (CURVE["30y"] - CURVE["10y"]))["TLT"]["change"]
    lo, mid, hi = v(y - d), v(y), v(y + d)
    assert lo > mid > hi                                                       # price falls as yields rise
    assert lo + hi - 2 * mid > -1e-12                                          # and is convex in the yield


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=120))
def test_reading_a_yield_question_never_fails(text):
    r = B.parse(text, CURVE)
    assert r is None or (0 <= r["y10"] <= 0.2 and 0 <= r["y30"] <= 0.2)


@settings(max_examples=40, deadline=None)
@given(st.floats(0.01, 0.1), st.floats(0.25, 29.75))
def test_a_bond_is_worth_par_at_its_own_coupon(y, T):
    T = max(0.5, round(T * 2) / 2)                                            # on the coupon grid
    assert B.bond_price(y, T, y) == pytest.approx(100.0, abs=1e-9)
    assert math.isfinite(B.bond_price(y, T, 0.0))
