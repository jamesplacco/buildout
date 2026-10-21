"""Write buildout/assets/brain_graph.json: the page's brain graph (nodes, links at today's regime weights, roots,
holdings, snapshot readings) and the field desk's cases, so the MCP server reasons on exactly what the page shows.

    python scripts/export_graph.py          # needs node; tests/test_v08.py fails if the file is out of date
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "buildout" / "assets" / "brain_graph.json"


def generate() -> dict:
    node = shutil.which("node")
    if node is None:
        sys.exit("node is required to read the page's graph")
    r = subprocess.run([node, str(ROOT / "site" / "tests" / "export8.js")], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


if __name__ == "__main__":
    data = generate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    g = data["graph"]
    print(f"wrote {OUT.relative_to(ROOT)}: {len(g['nodes'])} nodes, {len(g['edges'])} links, {len(data['field']['cases'])} field cases")
