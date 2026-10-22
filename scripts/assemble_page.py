"""Assemble site/page.html, the single-file page, from the sources in site/src.

head.html and body.html are the markup. The scripts are concatenated in SCRIPTS order inside one strict-mode
function scope, so nothing leaks into the global scope: math.js (pure functions), ui.js (DOM and charts),
data.js and reference.js (v0.4 desk content and the appendix), research.js (v0.5 data: filings, findings,
swans, legends, assumptions, chains), views.js (the v0.4 desks), decide.js, journal.js, desks.js, wisdom.js
and lab.js (the v0.5 desks), snap6.js (the generated v0.6 engine snapshot), brain.js, noteworthy.js, trading.js,
buyside6.js and pulse.js (the v0.6 desks), and boot.js (navigation, live data and boot, last).

    python scripts/assemble_page.py           # write site/page.html
    python scripts/assemble_page.py --check   # exit 1 if site/page.html is out of date
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site" / "src"
OUT = ROOT / "site" / "page.html"
SCRIPTS = ["math.js", "engine7.js", "ui.js", "data.js", "reference.js", "research.js", "views.js", "decide.js", "journal.js", "desks.js", "wisdom.js",
           "lab.js", "snap6.js", "snap7.js", "snap9.js", "brain.js", "brainx.js", "noteworthy.js", "trading.js", "buyside6.js", "pulse.js", "solve.js", "games.js", "field.js", "snap11.js", "hedgebook.js", "ooda.js", "snap12.js", "robustb.js", "hero.js", "voices.js", "snap13.js", "atlas.js", "snap14.js", "mind.js", "labs.js", "today7.js",
           "boot.js"]


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
