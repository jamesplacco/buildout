"""Assemble site/page.html, the single-file page, from the sources in site/src.

head.html and body.html are the markup. math.js (pure functions), ui.js (DOM and charts), data.js
(desk content), reference.js (the appendix knowledge base) and views.js (desks, tools, routing) are
concatenated in that order inside one strict-mode function scope, so nothing leaks into the global scope.

    python scripts/assemble_page.py           # write site/page.html
    python scripts/assemble_page.py --check   # exit 1 if site/page.html is out of date
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site" / "src"
OUT = ROOT / "site" / "page.html"
SCRIPTS = ["math.js", "ui.js", "data.js", "reference.js", "views.js"]


def assemble(src: Path = SRC) -> str:
    head = (src / "head.html").read_text().rstrip()
    body = (src / "body.html").read_text().strip()
    js = "\n\n".join((src / name).read_text().rstrip() for name in SCRIPTS)
    return f'{head}\n{body}\n<script>\n(() => {{\n  "use strict";\n{js}\n}})();\n</script>\n'


def main(argv: list[str]) -> int:
    page = assemble()
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text() != page:
            print("site/page.html is out of date: run python scripts/assemble_page.py", file=sys.stderr)
            return 1
        print("site/page.html is current")
        return 0
    OUT.write_text(page)
    print("wrote", OUT.relative_to(ROOT), f"({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
