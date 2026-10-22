"""Write site/src/snap15.js (the machine-learning lab, the reality check and the information-edge sources) and refresh
site/src/snap14.js (the labs, the mind and the code appendix), because the v0.15 mind reads the ML and assumption
results and links them into the same graph. Derived results only: forecasts, scores, test statistics and ratios,
never a raw price series.

    python scripts/snapshot_v15.py --labs-cache labs_dl.pkl [--labs-pickle labs_L.pkl] [--ml-pickle ml_o.pkl] [--as-pickle as_o.pkl]
"""
from __future__ import annotations

import json
import pickle
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from buildout import assumptions, damodaran, labs, mind, ml, voices  # noqa: E402
import snapshot_v14 as S14  # noqa: E402

BANNED = S14.BANNED
EXTRA_CODE = ["buildout/ml.py", "buildout/assumptions.py", "buildout/damodaran.py", "scripts/snapshot_v15.py", "editors/buildout.vim", "editors/buildout.el"]
Y10_NOW = 0.0513   # 10-year Treasury, Oct 21 2026 (treasury.gov par yield curve), the same reading the reasoner uses


def _arg(argv, k):
    return Path(argv[argv.index(k) + 1]) if k in argv else None


def _load(p):
    return pickle.loads(p.read_bytes()) if p and p.exists() else None


def edge_view(know: list[dict]) -> dict:
    keep = ("id", "kind", "title", "text", "value", "unit", "as_of", "source_title", "source_url", "publisher", "primary", "verification", "checked",
            "feed_url", "edge", "biases", "cadence", "cost", "authors", "speaker")
    pick = lambda cl: [{k: x.get(k) for k in keep if x.get(k) is not None} for x in know if x["cluster"] == cl]
    return {"edge": pick("edge_sources"), "model_risk": pick("model_risk"), "ml_finance": pick("ml_finance")}


def damodaran_defaults(know: list[dict]) -> dict:
    """The calculators open on inputs that are either sourced (and cited) or plainly labelled as a story to edit."""
    K = {k["id"]: k for k in know}
    g = lambda i: (K.get(i) or {}).get("value")
    erp = {"erp_oct": g("es-stat-damodaran-erp-oct2026"), "rf_oct": g("es-stat-damodaran-riskfree-oct2026"), "er_oct": g("es-stat-damodaran-expected-return-oct2026"),
           "erp_jan": g("es-stat-damodaran-erp-jan2026"), "y10_now": Y10_NOW}
    semis = {"sales_to_capital": 1.21, "wacc": 0.1055, "ev_sales": g("es-stat-damodaran-jan2026-semis"), "margin": 0.3531}
    dcf_story = dict(revenue=100.0, growth_high=0.25, margin_now=0.30, margin_target=0.3531, years_to_target=5, sales_to_capital=1.21, tax=0.21,
                     wacc_start=0.1055, wacc_mature=0.085, rf=Y10_NOW, p_fail=0.05, distress_share=0.5)
    return {"erp": erp, "semis": semis, "dcf_story": dcf_story, "dcf_example": damodaran.narrative_dcf(**dcf_story),
            "erp_example": damodaran.implied_erp(100.0, 0.035, 0.06, Y10_NOW)}


def main(argv: list[str]) -> int:
    know = mind.load_knowledge()
    K = {k["id"]: k for k in know}
    cape_now = (K.get("val-cape-2026-10-20") or {}).get("value")
    dl = _load(_arg(argv, "--labs-cache"))
    L = _load(_arg(argv, "--labs-pickle"))
    if L is None:
        dl = dl or labs.download()
        L = labs.build(dl, cape_now=cape_now)
    L["findings"] = labs.summary(L)
    mlo = _load(_arg(argv, "--ml-pickle"))
    if mlo is None:
        dl = dl or labs.download()
        mlo = ml.build(dl, cape_now=cape_now, y10_now=Y10_NOW * 100)
    rs = (ROOT / "site/src/research.js").read_text()
    m = re.search(r'"latest":\{"month":"([0-9-]+)","corr":([-0-9.e]+),"infl_avg":([-0-9.e]+)\}', rs)
    research_latest = {"month": m.group(1), "corr": float(m.group(2)), "infl_avg": float(m.group(3))} if m else None
    aso = _load(_arg(argv, "--as-pickle"))
    if aso is None:
        dl = dl or labs.download()
        bs = json.loads((ROOT / "buildout/assets/brain_graph.json").read_text()).get("series")
        aso = assumptions.build(dl, L, mlo, research_latest, bs)
    atlas = json.loads((ROOT / "buildout/assets/atlas.json").read_text())
    G = mind.build(atlas, voices.load(), know, mind.load_countries(), L, research_latest, mlo=mlo, aso=aso, positions=mind.load_positions(),
                   companies=mind.load_companies())
    C = S14._clean(mind.compact(G))
    (ROOT / "buildout/assets/mind.json").write_text(json.dumps(C, separators=(",", ":"), ensure_ascii=False))
    st = mind.stats(G)
    code = S14.code_view()
    S14_files = {c["path"] for c in code}
    S14.CODE_FILES[:] = [f for f in EXTRA_CODE if f not in S14_files]
    code += S14.code_view()
    snap14 = {"labs": S14._clean(S14.labs_view(L)), "mind": C, "stats": st, "code": code, "knowledge_note": json.loads((ROOT / "buildout/assets/knowledge.json").read_text())["note"]}
    body = json.dumps(snap14, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    for b in BANNED:
        assert b not in body.lower(), b
    (ROOT / "site/src/snap14.js").write_text(
        "  /* snap14.js (generated by scripts/snapshot_v15.py; do not edit): the labs, the unified mind and the engine's\n"
        "     source for the code appendix. Derived results only. */\n"
        f"  const SNAP14 = {body};\n  const LABS_SNAP = SNAP14.labs, MIND_SNAP = SNAP14.mind, CODE_SNAP = SNAP14.code;\n")
    mlo = dict(mlo)
    mlo["findings"] = ml.summary(mlo)
    aso = dict(aso)
    aso["findings"] = assumptions.summary(aso)
    snap = {"ml": S14._clean(mlo), "reality": S14._clean(aso), "edge": edge_view(know), "damodaran": S14._clean(damodaran_defaults(know)),
            "triage_example": S14._clean(assumptions.triage(1.2, 8, 40, published=True, cost_bps=5, turns=24))}
    body = json.dumps(snap, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    for b in BANNED:
        assert b not in body.lower(), b
    out = ROOT / "site/src/snap15.js"
    out.write_text("  /* snap15.js (v0.15, generated by scripts/snapshot_v15.py; do not edit): the machine-learning lab, the reality check of\n"
                   "     every model's assumptions, and the information-edge sources. Derived results only. */\n"
                   f"  const SNAP15 = {body};\n  const ML_SNAP = SNAP15.ml, REAL_SNAP = SNAP15.reality, EDGE_SNAP = SNAP15.edge, DAM_SNAP = SNAP15.damodaran;\n")
    print(f"wrote snap14 ({st['nodes']} nodes, {st['edges']} edges, {len(code)} code files) and snap15 {out.stat().st_size:,} bytes")
    for f in mlo["findings"] + aso["findings"]:
        print(" ", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
