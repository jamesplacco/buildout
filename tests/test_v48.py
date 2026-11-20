"""v0.48: release 1 of the second audit's plan (E01 to E05), merged onto v0.48. The behaviour is tested by domain, in
test_accounting_invariants.py, test_execution_events.py and test_policy_constraints.py; this file pins what the
release says about itself: the two gross limits by name, how the restatement is produced and shown, the notes."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
sys.path.insert(0, str(ROOT / "scripts"))


def test_the_two_gross_limits_have_two_names():
    book = (SRC / "book.js").read_text()
    assert '"Long exposure cap"' in book and '"Total gross limit"' in book and "Gross cap" not in book
    assert "B30_FAILED(r)" in book and 'gross_total: "the total gross limit"' in book
    for f, gone in (("today7.js", "gross cap"), ("journal.js", "gross cap"), ("decide.js", "gross capped"), ("body.html", "1.5x gross limit")):
        assert gone not in (SRC / f).read_text(), (f, gone)
    cfg = (ROOT / "config.toml").read_text()
    assert re.search(r"max_gross = 1\.50\s+# leverage cap on the long side", cfg) and re.search(r"max_total_gross = 2\.00\s+# long plus short", cfg)
    from buildout import book as bk, limits
    assert bk.MAX_GROSS == 1.50 and bk.MAX_TOTAL_GROSS == 2.00 and "max_total_gross" in limits.__doc__
    # today's published menu: its high end is inside both
    B = json.loads((ROOT / "site" / "data" / "book.json").read_text())
    hi = [r for r in B["frontier"] if r.get("meets")][-1]
    ev = limits.evaluate_row(hi, {**B["limits"], "max_total_gross": 2.0})
    assert ev["meets"] and hi["gross"] + hi["short"] <= 2.0


def test_the_record_holds_the_hedged_row_to_the_menus_high_end():
    import inspect
    from buildout import track
    src = inspect.getsource(track)
    assert "hi = fr[-1] if fr else None" in src and '"short_gross": sg' in src
    wf = inspect.getsource(track.walk_forward) + inspect.getsource(track.build)
    assert 'pol["call_short"] = run(held["short_gross"], short=held["short"])' in wf and "h_ok = h <= bk.MAX_TOTAL_GROSS - 1.0" in wf
    assert '"high_end_below_full_size"' in wf and '"total_gross_limit": bk.MAX_TOTAL_GROSS' in wf
    assert "nav.sleeve_turnover(gh, Rn, Wn, g_hed)" in inspect.getsource(track.live_record), "the live record nets too"


def test_the_restatement_is_computed_on_the_same_prices_and_shown_from_its_file():
    import restate
    old = {"pit": {"policies": {"call": {"net": {"sharpe": 0.78, "cagr": 0.15, "maxdd": 0.233}, "gross": {"maxdd": 0.23}, "meta": {"turnover_yr": 3.1}},
                                "call_short": {"net": {"sharpe": 0.94, "cagr": 0.17, "maxdd": 0.241}, "gross": {"maxdd": 0.24}, "meta": {"turnover_yr": 5.9}}}}}
    new = {"pit": {"policies": {"call": {"net": {"sharpe": 0.782, "cagr": 0.151, "maxdd": 0.233}, "gross": {"maxdd": 0.23}, "meta": {"turnover_yr": 2.3}},
                                "call_short": {"net": {"sharpe": 0.88, "cagr": 0.155, "maxdd": 0.241}, "gross": {"maxdd": 0.24}, "meta": {"turnover_yr": 4.3}},
                                "hold": {"net": {"sharpe": 0.89, "cagr": 0.3, "maxdd": 0.52}, "gross": {"maxdd": 0.52}, "meta": {"turnover_yr": 3.6}}}}}
    c = restate.compare(old, new)
    assert set(c["policies"]) == {"call", "call_short"}, "a policy missing before is not compared"
    assert c["policies"]["call"]["sharpe"] == [0.78, 0.782] and c["policies"]["call"]["turnover"] == [3.1, 2.3]
    assert c["max_sharpe_move"] == pytest.approx(0.06) and c["max_sharpe_move_unhedged"] == pytest.approx(0.002), "the hedged row's move is reported apart"
    src = (ROOT / "scripts" / "restate.py").read_text()
    assert '"worktree", "add", "--detach"' in src and 'for name, root in (("before", wt), ("after", ROOT))' in src and "pickle.dump" in src
    wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text()
    step = wf[wf.index("Restatement of the record for v0.48"):wf.index("- name: Status")]
    assert "hashFiles('site/data/restatement.json') == ''" in step and "steps.record.outcome == 'success'" in step and "continue-on-error: true" in step
    base = re.search(r"--base ([0-9a-f]{40})", step).group(1)
    assert base == "1c8e926ebd90e7870fe3fec81498728fa745a265" and f"git fetch --depth=1 origin {base}" in step
    boot = (SRC / "boot.js").read_text()
    assert 'mf.data["restatement.json"] ? loadJSON("data/restatement.json")' in boot and "T.restated.revised2 = rs" in boot
    desk = (SRC / "trackdesk.js").read_text()
    assert "Revised again ${isoNice(RS.revised2.date)}" in desk and "The hedged row changed for a second reason too" in desk


def test_version_and_notes():
    import buildout
    assert buildout.__version__ >= "0.48.0"
    assert '["v0.48", "Nov 20, 2026"' in (SRC / "reference.js").read_text() and "Version 0.48:" in (ROOT / "CHANGELOG.md").read_text()
    log = [line for line in (SRC / "memos.js").read_text().splitlines() if '"v0.48"' in line]
    assert len(log) == 3 and "Two limits shared one name" in log[0] and "charged the same trade twice" in log[1] and "not by execution" in log[2]
    for p in ("tests/test_v48.py", "tests/test_accounting_invariants.py", "tests/test_execution_events.py", "tests/test_policy_constraints.py",
              "buildout/nav.py", "buildout/limits.py", "scripts/restate.py"):
        low = (ROOT / p).read_text().lower()
        for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
            assert b not in low, (p, b)
