"""Wrap site/page.html (the artifact body) into a standalone page for GitHub Pages.

The Claude artifact host supplies the document skeleton and a small reset; GitHub Pages does not,
so this adds both and copies the daily JSON next to the page.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0;font:14px system-ui,-apple-system,"Segoe UI",sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>
"""


def build(src: str = "site", out: str = "_site") -> Path:
    page = Path(src, "page.html").read_text()
    cut = page.index("</style>") + len("</style>")
    html = HEAD + page[:cut] + "\n</head>\n<body>\n" + page[cut:] + "\n</body>\n</html>\n"
    dest = Path(out)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "index.html").write_text(html)
    (dest / ".nojekyll").write_text("")
    pdf = Path(src, "tearsheet.pdf")
    if pdf.exists():                      # v0.38: the tear sheet the Home and Track record pages link to
        shutil.copy(pdf, dest / "tearsheet.pdf")
    data = Path(src, "data")
    if data.exists():
        shutil.copytree(data, dest / "data")
    led = Path(src).resolve().parent / "ledger" / "calls.jsonl"
    if led.exists():                      # v0.39.1: the ledger, verified, so the published page shows every call logged since its build
        import sys as _sys
        _sys.path.insert(0, str(Path(src).resolve().parent))
        from buildout import ledger as _ledger
        (dest / "data").mkdir(parents=True, exist_ok=True)
        (dest / "data" / "calls.json").write_text(json.dumps({"verify": _ledger.verify(led), "entries": _ledger.read(led)}))
    (dest / "data").mkdir(parents=True, exist_ok=True)
    (dest / "data" / "manifest.json").write_text(json.dumps(manifest(dest), indent=1))
    return dest / "index.html"


def manifest(dest: Path) -> dict:
    """What this deployment serves (v0.42.3): the source commit, when it was built, and how old each data file is.
    A fresh build is not fresh data; this says which is which. Standard library only."""
    import hashlib
    import os
    import subprocess
    from datetime import datetime, timezone
    sha = os.environ.get("GITHUB_SHA")
    if not sha:
        try:
            sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            sha = None
    files = {}
    for p in sorted((dest / "data").glob("*.json")):
        if p.name == "manifest.json":
            continue
        try:
            d = json.loads(p.read_text())
        except ValueError:
            d = {}
        asof = None
        if isinstance(d, dict):
            for k in ("asof", "as_of", "generated_utc", "last_mark", "marks_asof", "date"):
                if isinstance(d.get(k), str):
                    asof = d[k]
                    break
            if asof is None and isinstance(d.get("summary"), dict):
                asof = d["summary"].get("as_of")
        files[p.name] = {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16], "asof": asof}
    page = dest / "index.html"
    return {"source_commit": sha, "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "page_bytes": page.stat().st_size if page.exists() else None, "data": files}


if __name__ == "__main__":
    print("built", build(*sys.argv[1:]))
