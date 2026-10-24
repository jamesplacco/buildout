"""Assemble site/page.html, the single-file page, from the sources in site/src.

head.html and body.html are the markup. The scripts are concatenated in SCRIPTS order inside one strict-mode
function scope, so nothing leaks into the global scope: pure math and the chart helpers first, then each version's
desks with the generated snapshots (snapN.js, written by scripts/snapshot_vN.py) just before the desks that read them,
and boot.js (navigation, live data and boot) last. Because the scope is shared, a second top-level function with the
same name would silently replace the first, so assembly stops if it finds one.

    python scripts/assemble_page.py           # write site/page.html
    python scripts/assemble_page.py --check   # exit 1 if site/page.html is out of date
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site" / "src"
OUT = ROOT / "site" / "page.html"
# the document skeleton, byte for byte the one the artifact viewer wraps a published page in, so the raw file, the tests
# and the published copy render the same standards-mode document (without it the raw file renders in quirks mode)
SKELETON = '<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}html{scroll-padding-top:env(safe-area-inset-top,0px)}body{margin:0;padding:0;font:14px -apple-system,BlinkMacSystemFont,sans-serif;background:#fff;color:#000}img{max-width:100%}[hidden]:not([hidden=until-found i]){display:none!important}</style></head><body>'
SCRIPTS = ["math.js", "engine7.js", "ui.js", "data.js", "reference.js", "research.js", "views.js", "decide.js", "journal.js", "desks.js", "wisdom.js",
           "lab.js", "snap6.js", "snap7.js", "snap9.js", "brain.js", "brainx.js", "noteworthy.js", "trading.js", "buyside6.js", "pulse.js", "solve.js", "games.js", "field.js", "snap11.js", "hedgebook.js", "ooda.js", "snap12.js", "robustb.js", "hero.js", "voices.js", "snap13.js", "atlas.js", "snap14.js", "mind.js", "labs.js", "snap15.js", "ml.js", "reality.js", "edge.js", "snap16.js", "analysis.js", "snap17.js", "bondlab.js", "bonds.js", "complexity.js", "snap19.js", "dx.js", "dxlive.js", "snap20.js", "pf.js", "snap21.js", "mx.js", "snap22.js", "geo.js", "snap23.js", "params.js", "explain.js", "snap24.js", "digest.js", "landing.js", "guide.js", "keys.js", "today7.js",
           "boot.js"]


def assemble(src: Path = SRC) -> str:
    head = (src / "head.html").read_text().rstrip()
    if (src / "fonts.css").exists():                     # the typeface, inlined (site/src/fonts.css, SIL OFL)
        head = head.replace("/*FONTS*/", (src / "fonts.css").read_text().rstrip(), 1)
    body = (src / "body.html").read_text().strip()
    if (src / "logo.html").exists():                     # the lotus symbols (scripts/make_logo.py)
        body = body.replace("<!--LOGO-->", (src / "logo.html").read_text().strip(), 1)
    if (src / "favicon.svg").exists():
        from urllib.parse import quote
        head = head.replace("</title>", '</title>\n<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,' + quote((src / "favicon.svg").read_text().strip(), safe=" =:/,") + '">', 1)
    texts = {name: (src / name).read_text().rstrip() for name in SCRIPTS}
    # every file shares one function scope, so a second top-level function of the same name silently replaces the
    # first (v0.21's renderMatrix emptied the Games desk this way); refuse to build with one
    seen: dict[str, str] = {}
    for name, t in texts.items():
        for fn in re.findall(r"^  function ([A-Za-z_$][\w$]*)\s*\(", t, flags=re.M):
            if fn in seen:
                raise SystemExit(f"duplicate top-level function {fn} in {seen[fn]} and {name}")
            seen[fn] = name
    js = "\n\n".join(texts.values())
    return f'{SKELETON}\n{head}\n{body}\n<script>\n(() => {{\n  "use strict";\n{js}\n}})();\n</script>\n\n</body></html>\n'


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
