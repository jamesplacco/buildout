"""Merge the concept writers' batches (b1.json ... b8.json) into buildout/assets/concepts17.json: first copy of an id or
a name wins, ids and names already in the ontology are skipped, relation targets that resolve nowhere are dropped, and
the house style is enforced (no em dashes, never the banned words).

    python scripts/merge_concepts.py <dir with b*.json>
"""
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from buildout import ontology  # noqa: E402

BANNED = (chr(0x2014), "inter" "section", "load" "-bearing")
TYPES = {"is_a", "part_of", "related", "causes+", "causes-", "measures", "uses", "opposes", "hedges", "example_of"}
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def main(d: str) -> None:
    base = ontology.concepts(extra=False)
    ids = {c["id"][2:] for c in base}
    names = {c["name"].lower() for c in base}
    raw, stats = [], {"dup_id": 0, "dup_name": 0, "bad": 0, "dropped_rel": 0}
    for f in sorted(glob.glob(f"{d}/b[0-9].json")):
        for c in json.load(open(f)):
            cid, nm = str(c.get("id", "")).strip(), str(c.get("name", "")).strip()
            if not ID.match(cid) or c.get("cluster") not in ontology.CLUSTERS or not c.get("def"):
                stats["bad"] += 1
                continue
            if cid in ids:
                stats["dup_id"] += 1
                continue
            if nm.lower() in names:
                stats["dup_name"] += 1
                continue
            txt = json.dumps(c, ensure_ascii=False).lower()
            if any(b in txt for b in BANNED):
                stats["bad"] += 1
                continue
            ids.add(cid)
            names.add(nm.lower())
            raw.append(c)
    out = []
    for c in raw:
        rels = []
        for part in (c.get("rel") or "").split(";"):
            if ":" not in part:
                continue
            k, ts = part.split(":", 1)
            k = k.strip()
            if k not in TYPES:
                stats["dropped_rel"] += 1
                continue
            keep = [t.strip() for t in ts.split(",") if t.strip() in ids and t.strip() != c["id"]]
            stats["dropped_rel"] += len([t for t in ts.split(",") if t.strip()]) - len(keep)
            if keep:
                rels.append(f"{k}:{','.join(keep)}")
        out.append({"id": c["id"], "name": c["name"].strip(), "cluster": c["cluster"], "def": c["def"].strip().replace(chr(0x2013), "-"),
                    "rel": "; ".join(rels), "formula": (c.get("formula") or None), "aliases": (c.get("aliases") or "").lower()})
    audit = Path(d) / "audit_out.json"          # a fact checker's corrections, applied last
    if audit.exists():
        fix = {a["id"]: a for a in json.loads(audit.read_text())}
        out = [c for c in out if fix.get(c["id"], {}).get("action") != "drop"]
        for c in out:
            a = fix.get(c["id"])
            if a and a.get("action") == "fix":
                c["def"] = a["def"] or c["def"]
                if "formula" in a:
                    c["formula"] = a["formula"]
        stats["audited"] = len(fix)
    (ROOT / "buildout/assets/concepts17.json").write_text(json.dumps({"schema": 1, "note": "Written by eight concept agents for v0.17, merged and checked by scripts/merge_concepts.py.", "concepts": out}, indent=0, ensure_ascii=False))
    from collections import Counter
    print(len(out), "concepts added;", stats, dict(Counter(c["cluster"] for c in out)))


if __name__ == "__main__":
    main(sys.argv[1])
