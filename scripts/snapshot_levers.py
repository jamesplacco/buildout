"""Write site/src/levers_data.js (v0.38): the value-creation plan's claims checked against sources, and the same six
levers read on the nine AI names, from buildout/assets/levers/{claims,companies}.json (each figure dated and sourced).

    python3 scripts/snapshot_levers.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / "buildout" / "assets" / "levers"
TICK = {"Microsoft": "MSFT", "Alphabet": "GOOGL", "Amazon": "AMZN", "Meta": "META", "Nvidia": "NVDA", "Broadcom": "AVGO", "Tesla": "TSLA", "SpaceX": "SPCX", "Oracle": "ORCL"}
COLS = ["Multiple: forward P/E now vs its 5-year average", "Revenue growth, last quarter", "Operating margin, change on a year",
        "Capital efficiency: capex as a share of operating cash, and free cash flow (12 months)", "Leverage: net cash or debt, borrowing", "Management"]


def short(text: str, limit: int = 320) -> str:
    """The first sentences of a correction, up to `limit` characters, cut at a sentence end."""
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(])", text)
    out = ""
    for s in parts:
        if out and len(out) + len(s) + 1 > limit:
            break
        out = (out + " " + s).strip()
    return out


def money(s: str) -> float | None:
    m = re.search(r"(-?)\$(\d[\d.,]*)B", s)
    return float(m.group(1) + m.group(2).replace(",", "")) if m else None


def usd(x: float) -> str:
    return ("-" if x < 0 else "") + f"${abs(x):,.1f}B"


def first(s: str) -> str:
    return re.split(r"(?<=\.)\s|\(|;", s)[0].strip().rstrip(".")


def cells(c: dict) -> list[str]:
    v = lambda k: (c.get(k) or {}).get("value", "")
    pe, avg = v("forward_pe_now"), v("forward_pe_5yr_avg")
    pe_n = re.match(r"([\d.]+)x", pe)
    avg_n = re.match(r"([\d.]+)x", avg)
    if pe_n and avg_n:
        alt = re.search(r"shows ([\d.]+x)", pe)
        mult = f"{pe_n.group(1)}x vs {avg_n.group(1)}x" + (f" (another provider: {alt.group(1)})" if alt else "")
    elif pe_n:
        mult = f"{pe_n.group(1)}x; no 5-year forward average"
    else:
        mult = "No reliable forward P/E"
    growth = first(v("revenue_growth_last_q_yoy"))
    chg = first(v("operating_margin_change_yoy"))
    margin = f"{first(v('operating_margin_last_q'))}, {chg[0].lower() + chg[1:]}"
    cap, ocf, fcf = money(v("capex_ttm")), money(v("operating_cash_flow_ttm")), money(v("free_cash_flow_ttm"))
    if cap is None or ocf is None:   # SpaceX: nine months only
        cap, ocf = money(re.sub(r".*Nine months 2026: ", "", v("capex_ttm"))), money(re.sub(r".*Nine months 2026: ", "", v("operating_cash_flow_ttm")))
        fcf = money(re.sub(r".*Nine months 2026: ", "", v("free_cash_flow_ttm")))
        eff = f"capex {cap / ocf * 100:.0f}% of operating cash; free cash flow {usd(fcf)} (nine months)" if cap and ocf and fcf is not None else "n/a"
    else:
        eff = f"capex {cap / ocf * 100:.0f}% of operating cash; free cash flow {usd(fcf)}"
    bond = first(v("recent_bond_issuance"))
    lev = first(v("net_cash_or_debt")) + "; " + ("no new debt in the quarter" if bond.lower().startswith("none") else bond[0].lower() + bond[1:])
    mg = re.split(r"(?<=[.;])\s", v("management"))[0].rstrip(".;")
    mg = mg if len(mg) <= 140 else mg[:137].rsplit(" ", 1)[0] + "..."
    return [mult, growth, margin, eff, lev, mg]


def main() -> None:
    claims = json.loads((A / "claims.json").read_text())
    comp = json.loads((A / "companies.json").read_text())
    rows = []
    for c in claims:
        rows.append({"claim": re.sub(r"^\d+[a-z]?\.\s*", "", c["claim"]), "verdict": c["verdict"].capitalize(), "correct": short(c["correct"]),
                     "source": (re.findall(r"https?://[^\s;,)]+", c["source"]) or [""])[0], "basis": "arithmetic" if c["source"].lower().startswith("arithmetic") else "source"})
    companies, sources = [], []
    for name, c in comp.items():
        companies.append({"name": f"{name} ({TICK[name]})", "cells": cells(c)})
        urls = sorted({u.strip() for d in c.values() if isinstance(d, dict) for u in str(d.get("source", "")).split(" ; ") if u.strip().startswith("http")})
        sources.append({"name": name, "urls": urls[:6]})
    neg = [n for n, c in comp.items() if (money((c.get("free_cash_flow_ttm") or {}).get("value", "")) or 0) < 0 or "-$" in (c.get("free_cash_flow_ttm") or {}).get("value", "")]
    ai_read = ("Read with the same six levers, the buildout's equity story runs on different ones. In the services deal the cheap levers are price and cash "
               "conversion, and leverage amplifies an EBITDA gain. For the AI names the lever moving is capital efficiency, and it is moving the wrong way: "
               f"{', '.join(neg)} had negative free cash flow over the last twelve months (SpaceX over nine), and Alphabet, Amazon, Meta and Oracle borrowed "
               "about $112B, $153B, $55B and $49B over four quarters to pay for capex. Leverage here funds spending ahead of revenue rather than amplifying "
               "a margin gain. The multiple lever is not stretched on the providers' own numbers: most forward P/Es sit below their five-year averages, "
               "but providers disagree by a factor of two or more for Nvidia and Broadcom, so treat that column as a range, not a reading. Margin and growth "
               "are where the sellers (Nvidia, Broadcom) show up; the buyers show growth with flat or falling cash conversion. The test the deal model "
               "teaches carries over: the value rests on a cliff (there, the platform threshold; here, revenue arriving before the debt does).")
    D = {"asof": "2026-11-03", "claims": rows, "levers_cols": COLS, "companies": companies, "company_sources": sources, "ai_read": ai_read,
         "verdict_counts": {k: sum(r["verdict"] == k for r in rows) for k in ("Confirmed", "Overstated", "Wrong", "Unverifiable")}}
    s = json.dumps(D, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    (ROOT / "site" / "src" / "levers_data.js").write_text("  /* levers_data.js (v0.38, generated by scripts/snapshot_levers.py; do not edit): sourced lever checks. */\n"
                                                          f"  const LEVERS_DATA = {s};\n")
    print("levers_data.js", len(s) // 1024, "KB", D["verdict_counts"])
    for c in companies:
        print(c["name"], "|", " | ".join(c["cells"]))


if __name__ == "__main__":
    main()
