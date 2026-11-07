"""Add modules to the source desk's listing in site/src/snap14.js without rebuilding the mind (v0.41).

    python3 scripts/snap14_add_code.py buildout/deeprl.py buildout/track.py ...
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import snap14_writer as W  # noqa: E402

BANNED = (chr(0x2014), "inter" "section", "load" "-bearing")


def entry(rel: str) -> dict:
    src = (ROOT / rel).read_text()
    low = src.lower()
    for b in BANNED:
        if b in low:
            raise SystemExit(f"{rel} contains banned text {b!r}; fix the source before shipping it to the page")
    m = re.match(r'\s*"""(.*?)"""', src, re.S)
    doc = m.group(1).strip().split("\n\n")[0].replace("\n", " ") if m else ""
    return {"path": rel, "lines": src.count("\n") + 1, "doc": doc[:400], "src": src}


def main(paths: list[str]) -> None:
    snap = W.read()
    have = {c["path"]: i for i, c in enumerate(snap["code"])}
    for rel in paths:
        e = entry(rel)
        if rel in have:
            snap["code"][have[rel]] = e
        else:
            snap["code"].append(e)
    W.write(snap)
    print(len(snap["code"]), "files on the source desk;", sum(c["lines"] for c in snap["code"]), "lines")


if __name__ == "__main__":
    main(sys.argv[1:])
