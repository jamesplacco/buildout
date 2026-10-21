"""Wrap site/page.html (the artifact body) into a standalone page for GitHub Pages.

The Claude artifact host supplies the document skeleton and a small reset; GitHub Pages does not,
so this adds both and copies the daily JSON next to the page.
"""
from __future__ import annotations

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
    data = Path(src, "data")
    if data.exists():
        shutil.copytree(data, dest / "data")
    return dest / "index.html"


if __name__ == "__main__":
    print("built", build(*sys.argv[1:]))
