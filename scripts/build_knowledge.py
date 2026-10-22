"""Merge the research agents' items (k*.json or r*.json) with the independent checkers' verdicts (v*.json) into
buildout/assets/knowledge.json; the World Bank country tables into buildout/assets/world.json; the S&P 500 list into
buildout/assets/companies.json.

    python scripts/build_knowledge.py --world <dir> --companies <constituents.csv> <research dir> [<research dir> ...]
"""
import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BANNED = (chr(0x2014), "inter" "section")   # house style: no em dashes, never that word (spelled split so this file can be shown)
AGG = ("income", "World", "Euro area", "IDA", "IBRD", "dividend", "& ", "OECD", "Fragile", "Heavily", "Least developed", "small states", "Small states",
       "Sub-Saharan", "Latin America", "Middle East", "North America", "Arab World", "Central Europe", "European Union", "Not classified", "Pacific island",
       "Africa Eastern", "Africa Western", "South Asia", "East Asia", "Europe & Central", "members", "Upper middle", "Lower middle")


def knowledge(dirs: list[str]) -> list[dict]:
    items, verdict = [], {}
    for d in dirs:
        for f in sorted(glob.glob(f"{d}/k*.json")) + sorted(glob.glob(f"{d}/r*.json")):
            items += json.load(open(f))
        for f in sorted(glob.glob(f"{d}/v*.json")):
            for v in json.load(open(f)):
                verdict[v["id"]] = v
    out, seen = [], set()
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
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
    return out


def world(wdir: str) -> dict:
    from buildout.mind import COUNTRIES
    g = pd.read_csv(f"{wdir}/gdp.csv")
    p = pd.read_csv(f"{wdir}/population.csv")
    curated = {c[0] for c in COUNTRIES}
    c = {}
    for iso, grp in g.groupby("Country Code"):
        name = str(grp["Country Name"].iloc[0])
        if iso not in curated and any(a in name for a in AGG):
            continue
        gg = grp.dropna().sort_values("Year")
        row = {"name": name}
        if len(gg) and int(gg.iloc[-1]["Year"]) >= 2015:
            row["gdp"], row["gdp_year"] = float(gg.iloc[-1]["Value"]), int(gg.iloc[-1]["Year"])
        pp = p[p["Country Code"] == iso].dropna().sort_values("Year")
        if len(pp):
            row["pop"], row["pop_year"] = float(pp.iloc[-1]["Value"]), int(pp.iloc[-1]["Year"])
        c[iso] = row
    for iso, *_ in COUNTRIES:
        c.setdefault(iso, {})
    return c


def main(argv: list[str]) -> None:
    wdir = argv[argv.index("--world") + 1]
    comp = argv[argv.index("--companies") + 1]
    dirs = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or not argv[i - 1].startswith("--"))]
    items = knowledge(dirs)
    (ROOT / "buildout/assets/knowledge.json").write_text(json.dumps({"schema": 1, "built": "2026-10-22", "note": "Each item was found on its source page by a research agent and checked on the same page by a second, independent agent; corrections are recorded in 'checked'.", "items": items}, indent=1, ensure_ascii=False))
    w = world(wdir)
    (ROOT / "buildout/assets/world.json").write_text(json.dumps({"schema": 2, "source": "World Bank via the datahub GitHub mirrors (datasets/gdp, datasets/population). Inflation is left out: the mirror's consumer-price file matches the GDP deflator, so it is not used.", "countries": w}, indent=1))
    d = pd.read_csv(comp)
    cos = [{"symbol": r["Symbol"], "name": r["Security"], "sector": r["GICS Sector"], "industry": r["GICS Sub-Industry"], "hq": r["Headquarters Location"],
            "added": str(r["Date added"]), "founded": str(r["Founded"])} for _, r in d.iterrows()]
    (ROOT / "buildout/assets/companies.json").write_text(json.dumps({"schema": 1, "source": "GitHub datasets/s-and-p-500-companies (constituents.csv), fetched 2026-10-22", "companies": cos}, indent=1, ensure_ascii=False))
    print(len(items), "items;", sum(1 for x in w.values() if x.get("gdp")), "economies with GDP;", len(cos), "companies")


if __name__ == "__main__":
    main(sys.argv[1:])
