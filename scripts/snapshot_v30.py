"""Write site/src/snap30.js (v0.30: the book, sized and measured on the nine names' own daily prices) and rebuild
snap14 to snap29 through snapshot_v29. Derived results only: the prices stay in the run's cache.

    python scripts/snapshot_v30.py [--book-json out/book.json | --mirror-pickle prices.pkl | --book-cache .cache/book]
                                   ... (the v29 flags)

--book-json reuses a finished run (python -m buildout book --out out); --mirror-pickle reads a pickled
{"prices": {file: DataFrame}} from an earlier download; otherwise the mirror is downloaded into --book-cache.
"""
from __future__ import annotations

import json
import pickle
import sys

import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from buildout import book  # noqa: E402
import snapshot_v14 as S14  # noqa: E402
import snapshot_v15 as S15  # noqa: E402
import snapshot_v29 as S29  # noqa: E402

S15.EXTRA_CODE += ["buildout/book.py", "buildout/sizing_rules.py", "scripts/snapshot_v30.py"]


def long_record(argv: list[str]) -> dict | None:
    """v0.32: the volatility rule on the Nasdaq-100 future since 1999 (the futures engine's cache, --carver-pickle),
    the record that holds the dot-com crash, 2008 and 2020. Futures returns are already in excess of cash."""
    from buildout import futures, sizing_rules
    arg = lambda k: Path(argv[argv.index(k) + 1]) if k in argv else None
    p = arg("--carver-pickle")
    if not p or not p.exists():
        return None
    frames = pickle.load(open(p, "rb"))
    nq = futures.front_returns(frames["NQ"]).dropna()
    return book._slim(sizing_rules.test_all(nq, pd.Series(0.0, index=nq.index), "the Nasdaq-100 future, December 1999 to March 2024"))


def book_run(argv: list[str]) -> dict:
    arg = lambda k: Path(argv[argv.index(k) + 1]) if k in argv else None
    if arg("--book-json"):
        return json.loads(arg("--book-json").read_text())
    lr = long_record(argv)
    if arg("--mirror-pickle"):
        prices = pickle.load(open(arg("--mirror-pickle"), "rb"))["prices"]
        return book.build(prices, meta={"source": "mirror download (pickled)"}, long_record=lr)
    return book.build(book.download(arg("--book-cache") or ROOT / ".cache" / "book"), meta={"source": "mirror download"}, long_record=lr)


# ---------------------------------------------------------------- the inventory: every edge tested, one ledger
def _snap(name: str, var: str):
    p = ROOT / "site" / "src" / name
    if not p.exists():
        return None
    s = p.read_text()
    if f"const {var} = " not in s:
        return None
    i = s.index(f"const {var} = ") + len(f"const {var} = ")
    return json.loads(s[i:s.index(";\n", i)].replace("<\\/", "</"))


FUT_VERDICT = {"supported": "works", "faded": "faded", "class_tilt": "faded", "beta_only": "faded", "one_era": "faded",
               "reversed": "failed", "chance": "failed", "untested": "untested"}


def inventory(book_run: dict) -> dict:
    """One row per edge or rule the engine has tested, from the desks' own shipped results: what was tested, how
    (walked forward, out of sample, in sample), the statistic, the verdict and the record's end. Nothing is re-run."""
    rows, notes = [], []
    add = lambda **r: rows.append(r)
    try:
        F = _snap("snap29.js", "SNAP29")["futures"]
        L = (F.get("runs") or {}).get("pysystemtrade") or {}
        SN = {"carry": "Carry", "trend_1": "Trend, 1 month", "trend_3": "Trend, 3 months", "trend_12": "Trend, 12 months",
              "basis_mom": "Basis momentum", "hedging_pressure": "Hedging pressure"}
        for t in L.get("tests", []):
            sp = (t.get("since_publication") or {}).get("sharpe")
            add(desk="Futures", href="#futures", family="Futures premia", test=f"{SN.get(t['signal'], t['signal'])} {'across markets' if t['design'] == 'xs' else 'over time'}",
                method="after costs, BH cut, beyond holding long, both halves, since publication",
                stat=f"Sharpe {t['sharpe_net']:.2f} after costs" + (f"; {sp:.2f} since publication" if sp is not None else ""),
                p=t.get("p"), verdict=FUT_VERDICT.get(t["verdict"], t["verdict"]), through=L["universe"]["to"])
    except Exception as exc:                       # one desk missing never stops the ledger
        notes.append(f"futures: {type(exc).__name__}")
    try:
        D = _snap("snap19.js", "SNAP19")["decision"]
        g = D["now"]["gate"]
        add(desk="Decision engine", href="#decision", family="Market timing", test="The engine's regime-aware sizing against holding 1x",
            method=f"walked forward since {D['start'][:4]}, utility t against the best of {g['n_tried']} useless strategies",
            stat=f"utility t {g['t']:.2f} against {g['t0']:.2f} needed; Sharpe {D['configs']['engine']['perf']['sharpe']:.2f} against {D['hold']['sharpe']:.2f}",
            p=None, verdict="failed", through=D["end"][:7])
        w = D["overlay"].get("walk_forward") or {}
        if w:
            add(desk="Decision engine", href="#decision", family="Market timing", test="10-month trend overlay, factor re-chosen yearly",
                method="walked forward, ten-year burn-in", stat=f"utility t {w['utility_t']:.2f}; Sharpe {w['perf']['sharpe']:.2f} against {D['hold']['sharpe']:.2f}",
                p=None, verdict="failed", through=D["end"][:7])
        dx = D.get("deflated_excess") or {}
        if dx.get("dsr") is not None:
            notes.append(f"decision: deflated Sharpe of the best configuration's timing alpha {dx['dsr']:.0%} ({str(dx.get('best', '')).replace('_', ' ')})")
    except Exception as exc:
        notes.append(f"decision: {type(exc).__name__}")
    try:
        M = _snap("snap15.js", "SNAP15")["ml"]["return"]
        for k, sc in M["scores"].items():
            dm = sc.get("dm") or {}
            ok = (dm.get("p_one_sided") or 1) <= 0.05 and sc["skill"] > 0
            add(desk="ML lab", href="#ml", family="Return forecasting", test=M["labels"].get(k, k) + ", 12-month real return",
                method="out of sample since 1940 against the historical mean (Diebold-Mariano)", stat=f"skill {sc['skill']:+.1%}; DM t {dm.get('t', float('nan')):.2f}",
                p=dm.get("p_one_sided"), verdict="works" if ok else ("promising" if sc["skill"] > 0 else "failed"), through="2026")
    except Exception as exc:
        notes.append(f"ml: {type(exc).__name__}")
    try:
        N = _snap("snap27.js", "SNAP27")["nowcast"]
        T = N.get("tests", [])
        passed = [t for t in T if t.get("pass_bh")]
        best = sorted(T, key=lambda t: t.get("p") if t.get("p") is not None else 1)[:3]
        for t in passed or best:
            add(desk="Nowcast", href="#nowcast", family="Early-published facts", test=f"{t.get('signal')} on {t.get('target')} ({t.get('group')})",
                method="walked forward, BH cut over all tests", stat=f"p {t['p']:.3f}" if t.get("p") is not None else "", p=t.get("p"),
                verdict="works" if t.get("pass_bh") else "failed", through=str(N.get("data_through", ""))[:10])
        notes.append(f"nowcast: {len(passed)} of {len(T)} tests passed the multiple-testing cut")
    except Exception as exc:
        notes.append(f"nowcast: {type(exc).__name__}")
    try:
        E = _snap("snap26.js", "SNAP26")["discovery"]
        fun = {f["key"]: f for f in E.get("funnel", [])}
        for e in E.get("edges", []):
            te = e.get("test") or {}
            v = e.get("validation") or {}
            add(desk="Edge lab", href="#edges", family="Machine-found edges", test=e["name"],
                method="discovery, then validation years, then test years the search never saw",
                stat=f"validation Sharpe {((v.get('net') or {}).get('sharpe') or 0):.2f} after costs" + ("" if te.get("tested") else "; no test-period data"),
                p=(e.get("discovery") or {}).get("p"), verdict=("works" if (te.get("net") or {}).get("sharpe", 0) and te["net"]["sharpe"] > 0 else "failed") if te.get("tested") else "untested",
                through=str((v.get("period") or "")).split(" to ")[-1])
        if "tried" in fun and "bh" in fun:
            notes.append(f"edge lab: {fun['tried']['real']:,} candidates tried, {fun['bh']['real']} past the calibrated cut, {len(E.get('edges', []))} survived every stage")
    except Exception as exc:
        notes.append(f"edges: {type(exc).__name__}")
    try:
        Lb = _snap("snap14.js", "SNAP14")["labs"]["multiple_testing"]["rows"]
        sig = [r for r in Lb if r.get("bh") is not None and r["bh"] <= 0.05]
        notes.append(f"labs: {len(sig)} of {len(Lb)} classic rules significant in sample after Benjamini-Hochberg (most on the VIX's own mean reversion, which is not tradable as such)")
        for r in [x for x in Lb if "S&P 500" in x["test"] or "Sell in May" in x["test"]][:4]:
            add(desk="Labs", href="#labs", family="Classic trading rules", test=r["test"], method="in sample, BH and Holm over every rule tried",
                stat=f"effect {r['effect']:+.2%} a month" if abs(r.get("effect") or 0) < 1 else f"effect {r['effect']:.2f}", p=r["p"],
                verdict="in sample only" if r["bh"] <= 0.05 else "failed", through="2026")
    except Exception as exc:
        notes.append(f"labs: {type(exc).__name__}")
    try:
        Fl = _snap("snap28.js", "SNAP28")["filings"]
        if Fl.get("status") == "awaiting first run":
            for s in Fl.get("signals", []):
                add(desk="Filings", href="#filings", family="Filings and insiders", test=s["name"], method="monthly rank IC, EWC test, BH, controls, both halves",
                    stat=f"{s['reference']}", p=None, verdict="untested", through="needs the SEC run")
    except Exception as exc:
        notes.append(f"filings: {type(exc).__name__}")
    VR = book_run.get("vol_rule") or {}                 # v0.32: the volatility-managed sizing rule, three records
    VV = {"supported": "works", "one_era": "faded", "chance": "failed", "reversed": "failed"}
    for key, rec in (("long_record", VR.get("long_record")), ("nasdaq_2017", VR.get("nasdaq_2017")), ("book", VR.get("book"))):
        if rec and rec.get("headline"):
            hd = rec["headline"]
            add(desk="Book risk", href="#bk-rule-t", family="Volatility-managed sizing", test=f"Scale exposure by target variance over realized variance (Moreira and Muir 2017), {rec['name']}",
                method=f"monthly CRRA utility gain over holding, EWC t against the best of {rec['n_rules']} rules tried, both halves",
                stat=f"utility t {hd['t']:.2f} against {rec['t_bar']:.2f} needed; Sharpe {hd['sharpe_rule']:.2f} against {hd['sharpe_hold']:.2f} holding",
                p=hd.get("p"), verdict=VV.get(rec["verdict"], rec["verdict"]), through=hd["to"])
    H = (book_run.get("hedges") or {}).get("policies") or {}
    for k, name in (("nasdaq_beta", "Nasdaq-100 short at the measured beta"), ("nasdaq_and_semis", "Nasdaq-100 and semis short"),
                    ("bond_when_it_hedges", "Long bond when its correlation says it hedges"), ("bond_static_30", "Standing 30% long bond")):
        if k in H:
            add(desk="Book risk", href="#book", family="Hedges for this book", test=name, method="walked forward on the book's own days, ratios known the day before",
                stat=f"variance cut {H[k]['variance_cut']:.0%}; 2022 {H[k]['y2022']:+.1%}", p=None,
                verdict="works" if H[k]["variance_cut"] >= 0.25 else "failed", through=book_run["asof"])
    count = {}
    for r in rows:
        count[r["verdict"]] = count.get(r["verdict"], 0) + 1
    return {"rows": rows, "counts": count, "notes": notes,
            "verdicts": {"works": "passed every test the desk sets, out of sample", "promising": "positive out of sample, not yet significant",
                         "faded": "real once, weaker now or only in one era or one class", "in sample only": "significant in sample after multiple-testing correction; no out-of-sample test",
                         "failed": "no evidence beyond chance or holding", "untested": "waiting for data"}}


def main(argv: list[str]) -> int:
    if "--only-v30" not in argv:              # --only-v30: rewrite snap30.js alone, keeping snap14 to snap29 as they are
        S29.main(argv)
    o = book_run(argv)
    o["findings"] = book.summary(o)
    o["validation"] = book.validate()
    inv = inventory(o)
    s = json.dumps(S14._clean({"book": o, "inventory": inv}), separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    for b in S14.BANNED:
        assert b not in s.lower(), b
    (ROOT / "site" / "src" / "snap30.js").write_text("  /* snap30.js (v0.30, generated by scripts/snapshot_v30.py; do not edit): the book, sized and measured. Derived results only. */\n"
                                                     f"  const SNAP30 = {s};\n")
    print("snap30.js", len(s) // 1024, "KB", "size", o["size"], "binding", o["binding"], "inventory", inv["counts"], inv["notes"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
