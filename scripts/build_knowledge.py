"""Merge the research agents' items (k*.json) with the independent checkers' verdicts (v*.json) into
buildout/assets/knowledge.json, and the World Bank country tables into buildout/assets/world.json.

    python scripts/build_knowledge.py <research dir> <world dir>
"""
import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BANNED = ("\u2014", "inter" "section")   # house style: no em dashes, never that word (spelled split so this file can be shown)


def main(kdir: str, wdir: str) -> None:
    items = []
    for f in sorted(glob.glob(f"{kdir}/k*.json")):
        items += json.load(open(f))
    verdict = {}
    for f in sorted(glob.glob(f"{kdir}/v*.json")):
        for v in json.load(open(f)):
            verdict[v["id"]] = v
    out = []
    for it in items:
        v = verdict.get(it["id"])
        if v is None or v["status"] in ("fail", "unreachable"):
            continue
        if v["status"] == "fixed":
            it.update(v.get("fix") or {})
            it["checked"] = "corrected by a second checker: " + v.get("note", "")
        else:
            it["checked"] = "confirmed by a second checker" + (": " + v["note"] if v.get("note") else "")
        bad = [k for k, x in it.items() if isinstance(x, str) and any(b in x.lower() for b in BANNED)]
        assert not bad, (it["id"], bad)
        out.append(it)
    (ROOT / "buildout/assets/knowledge.json").write_text(json.dumps({"schema": 1, "built": "2026-10-21", "note": "Each item was found on its source page by a research agent and checked on the same page by a second, independent agent; corrections are recorded in 'checked'.", "items": out}, indent=1, ensure_ascii=False))
    from buildout.mind import COUNTRIES
    g = pd.read_csv(f"{wdir}/gdp.csv")
    p = pd.read_csv(f"{wdir}/population.csv")
    c = {}
    for iso, *_ in COUNTRIES:
        row = {}
        gg = g[g["Country Code"] == iso].dropna().sort_values("Year")
        if len(gg):
            row["gdp"], row["gdp_year"] = float(gg.iloc[-1]["Value"]), int(gg.iloc[-1]["Year"])
        pp = p[p["Country Code"] == iso].dropna().sort_values("Year")
        if len(pp):
            row["pop"], row["pop_year"] = float(pp.iloc[-1]["Value"]), int(pp.iloc[-1]["Year"])
        c[iso] = row
    (ROOT / "buildout/assets/world.json").write_text(json.dumps({"schema": 1, "source": "World Bank via the datahub GitHub mirrors (datasets/gdp, datasets/population). Inflation is left out: the mirror's consumer-price file matches the GDP deflator, so it is not used.", "countries": c}, indent=1))
    print(len(out), "items;", sum(1 for x in c.values() if x), "countries with data")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
