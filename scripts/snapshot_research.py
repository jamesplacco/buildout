"""Refresh the page's research snapshot (site/src/research.js FINDINGS) from a research.json the engine wrote.

    python scripts/snapshot_research.py site/data/research.json
"""
import json
import re
import sys
from pathlib import Path

src = Path(__file__).resolve().parents[1] / "site" / "src" / "research.js"
new = json.loads(Path(sys.argv[1]).read_text())
new.pop("source", None)
new.pop("schema", None)
text = src.read_text()
line = "  const FINDINGS = " + json.dumps(new, separators=(",", ":")) + ";"
text, n = re.subn(r"^  const FINDINGS = .*;$", lambda m: line, text, count=1, flags=re.M)
assert n == 1, "FINDINGS line not found"
src.write_text(text)
print("FINDINGS refreshed from", sys.argv[1])
