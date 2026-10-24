"""Write site/src/snap25.js (v0.25: the reasoning engine's deductions, inductions, abductions and invented concepts;
the legendary traders' and Taleb's principles tested on 156 years of data; the forecast verification and tail
backtests borrowed from weather services and actuaries; every upgrade tried on the decision core with its verdict) and
rebuild snap14 to snap24 through snapshot_v24, so the mind carries the v0.25 concepts. Derived results only.

    python scripts/snapshot_v25.py --reason-json reason_o.json --cf-json eval.json --evt-json evt.json ... (the v24 flags)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from buildout import crossfield, reason  # noqa: E402
import snapshot_v14 as S14  # noqa: E402
import snapshot_v15 as S15  # noqa: E402
import snapshot_v24 as S24  # noqa: E402

S15.EXTRA_CODE += ["buildout/reason.py", "buildout/crossfield.py", "scripts/snapshot_v25.py"]


def _load(argv, flag):
    if flag in argv:
        p = Path(argv[argv.index(flag) + 1])
        if p.exists():
            return json.loads(p.read_text())
    return None


def _ml_why(t: dict) -> str:
    tt, after = t.get("t") or 0.0, t.get("after")
    if t.get("adopted"):
        return ("Best of the variants tried and above the bar (DM t over 1.5 against v0.24); the margin is smaller than its t because it was the best of several."
                + (" It still loses to the base rate, so the lab reports it beside the base rate." if t.get("task") == "crash" else ""))
    if "Winkler" in str(t.get("metric")):
        return "Wider-scoring intervals than the conformal ones (a worse Winkler score); the conformal interval stays."
    if tt > 1.5 and t.get("task") == "return" and after is not None and after < 0:
        return f"Beats v0.24 (t {tt:+.2f}) but still loses to the historical mean, so it is not an improvement worth adopting."
    if tt > 1.5:
        return f"Also clears the bar (t {tt:+.2f}); its discounted sibling was adopted so the return and crash forecasts share one rule and one discount."
    return f"Below the bar (t {tt:+.2f} against v0.24, needing 1.5)."


def trials(cf: dict | None, evt: dict | None, extra: list | None = None) -> list[dict]:
    """Every upgrade tried on the decision core in v0.25, with the out-of-sample evidence and the verdict."""
    out = []
    if cf:
        names = {"emos": "EMOS recalibration of the predictive mixture (weather post-processing)", "emos_normal": "Textbook EMOS, a single normal (weather post-processing)",
                 "bma": "Bayesian model averaging by EM in place of dynamic model averaging (ensemble weather forecasting)",
                 "credibility": "Regime shrinkage with a Buhlmann-estimated pseudo-count instead of the hand-set 120 (actuarial credibility)"}
        for k, v in (cf.get("variants") or {}).items():
            d = v.get("vs_as_is")
            if not d:
                continue
            a = v.get("adoption") or {}
            why = {"bma": "Passes the written rule only marginally: its log score and CRPS are slightly worse (not significantly), and its one fix is a 1% tail p value moving from 0.02 to 0.07 with no improvement in the paired VaR-ES score. Not adopted.",
                   "emos": "Narrows the forecast and adds tail breaches (2.0% at 1%); fails the rule.",
                   "emos_normal": "Worse log score (t -2.36) and worse tails; fails the rule.",
                   "credibility": "Credibility puts the pseudo-count near 4 months against the hand-set 120, but using it worsens the log score (t -2.09), because the states are fit to the same data; the out-of-sample evidence keeps 120, which now has a test behind it."}.get(k)
            out.append({"id": k, "name": names.get(k, k), "field": "weather" if "emos" in k or k == "bma" else "actuarial",
                        "log_t": d.get("log_score_t"), "crps_t": d.get("crps_t"), "fz0_t_05": d.get("fz0_t_0.05"), "fz0_t_01": d.get("fz0_t_0.01"),
                        "passes_rule": bool(a.get("adopt")), "strength": a.get("strength"),
                        "adopted": False, "why": why})
    if evt:
        u = evt.get("evt_vs_engine_utility") or {}
        g = evt.get("evt_vs_engine_gated_utility") or {}
        out.append({"id": "evt_floor", "name": "Risk budget measured with an EVT floor: the larger of the mixture's ES and a walk-forward peaks-over-threshold ES (actuarial extreme value theory)",
                    "field": "actuarial", "utility_t": u.get("t"), "gated_utility_t": g.get("t"), "adopted": False,
                    "why": "It binds in most months and cuts the engine's optimum from 1.5x toward 1.3x, but it does not raise a cautious investor's expected utility (raw t "
                           f"{u.get('t', 0):+.2f}, gated t {g.get('t', 0):+.2f}); the mixture's own 5% ES is already calibrated, so the floor stays a cross-check on the limits table."})
    return out + (extra or [])


def main(argv: list[str]) -> int:
    S24.main(argv)
    ro, cf, evt = _load(argv, "--reason-json"), _load(argv, "--cf-json"), _load(argv, "--evt-json")
    import pickle
    pk = lambda k: pickle.loads(Path(argv[argv.index(k) + 1]).read_bytes()) if k in argv and Path(argv[argv.index(k) + 1]).exists() else None
    mlo, rlo = pk("--ml-pickle"), pk("--rl-pickle")
    ml_trials = []
    for t in (mlo or {}).get("v25_trials", []):
        ml_trials.append({"id": "ml-" + t["task"] + "-" + t["variant"][:40], "name": f"ML {'12-month return' if t['task'] == 'return' else 'crash probability'}: {t['variant']}", "field": "machine learning",
                          "metric": t["metric"], "before": t.get("before"), "after": t.get("after"), "t": t.get("t"), "adopted": bool(t.get("adopted")),
                          "why": _ml_why(t)})
    seen = set()
    for t in (rlo or {}).get("v25_trials", []):
        if t["variant"] in seen:
            continue
        seen.add(t["variant"])
        ml_trials.append({"id": "rl-" + t["variant"], "name": f"RL sizing agent: {t['variant'].replace('_', ' ')}", "field": "reinforcement learning", "metric": t["metric"],
                          "before": t.get("before"), "after": t.get("after"), "t": t.get("t"), "adopted": bool(t.get("adopted")),
                          "why": "Sharpe and CRRA both pass their 90% ranges against v0.24; it beats holding on Sharpe but not on a cautious investor's utility, so it stays in the learning lab and does not size the book." if t.get("adopted") else "Its 90% range includes zero on Sharpe or utility."})
    assets = ROOT / "buildout" / "assets"
    rules = json.loads((assets / "rules25.json").read_text())
    methods = json.loads((assets / "methods25.json").read_text())
    conc = json.loads((assets / "concepts25.json").read_text())
    corpus = {"concepts": len(conc["concepts"]), "rules": len(rules["rules"]), "methods": len(methods["methods"]),
              "by_domain": {}}
    for c in conc["concepts"]:
        corpus["by_domain"].setdefault(c["domain"], {"concepts": 0})["concepts"] += 1
    K = json.loads((assets / "knowledge.json").read_text())["items"]
    V = json.loads((assets / "voices.json").read_text())["quotes"]
    for d in ("taleb", "traders", "actuarial", "weather", "bigdata"):
        corpus["by_domain"].setdefault(d, {"concepts": 0})["items"] = sum(1 for i in K if i.get("cluster") == d)
    corpus["quotes"] = sum(1 for q in V if q.get("topic") in ("tails_uncertainty", "trading_discipline") or q["id"].endswith("261024") or "261024" in q["id"])
    concepts_out = [{k: c.get(k) for k in ("id", "name", "cluster", "def", "formula", "source_url", "source_title", "originator", "domain")} for c in conc["concepts"]]
    body = {"reason": ro, "crossfield": cf, "evt": evt, "trials": trials(cf, evt, (ml_trials or [])), "methods": methods["methods"],
            "rules_meta": {r["id"]: {"source_url": r.get("source_url"), "source_title": r.get("source_title"), "quote": r.get("quote"), "note": r.get("note"), "domain": r.get("domain")} for r in rules["rules"]},
            "corpus": corpus, "concepts": concepts_out,
            "summary": {"reason": reason.summary(ro) if ro else [], "crossfield": crossfield.summary(cf) if cf else []}}
    s = json.dumps(S14._clean(body), separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    for b in S14.BANNED:
        assert b not in s.lower(), b
    (ROOT / "site" / "src" / "snap25.js").write_text("  /* snap25.js (v0.25, generated by scripts/snapshot_v25.py; do not edit): reasoning, the legends on trial, borrowed methods, every upgrade tried. Derived results only. */\n"
                                                     f"  const SNAP25 = {s};\n")
    print("snap25.js", len(s) // 1024, "KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
