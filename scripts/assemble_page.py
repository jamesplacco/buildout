"""Assemble site/page.html, the single-file page, from the sources in site/src.

head.html and body.html are the markup. The scripts are concatenated in SCRIPTS order inside one strict-mode
function scope, so nothing leaks into the global scope: pure math and the chart helpers first, then each version's
desks with the generated snapshots (snapN.js, written by scripts/snapshot_vN.py) just before the desks that read them,
and boot.js (navigation, live data and boot) last. Because the scope is shared, a second top-level function with the
same name would silently replace the first, so assembly stops if it finds one.

    python scripts/assemble_page.py           # write site/page.html (every desk) and site/core.html (the core page)
    python scripts/assemble_page.py --check   # exit 1 if either is out of date

v0.43: the same sources build two pages. page.html carries every desk and is the library; core.html carries only
the desks the call depends on (CORE_VIEWS) and none of the snapshots only the library reads (CORE_STUBS).
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
           "lab.js", "snap6.js", "snap7.js", "snap9.js", "brain.js", "brainx.js", "noteworthy.js", "trading.js", "buyside6.js", "pulse.js", "solve.js", "games.js", "field.js", "snap11.js", "hedgebook.js", "ooda.js", "snap12.js", "robustb.js", "hero.js", "voices.js", "snap13.js", "atlas.js", "snap14.js", "mind.js", "labs.js", "snap15.js", "ml.js", "reality.js", "edge.js", "snap16.js", "analysis.js", "snap17.js", "bondlab.js", "bonds.js", "complexity.js", "snap19.js", "dx.js", "dxlive.js", "snap20.js", "pf.js", "snap21.js", "mx.js", "snap22.js", "geo.js", "snap23.js", "params.js", "explain.js", "snap24.js", "digest.js", "snap25.js", "reasoning.js", "snap26.js", "edges.js", "snap27.js", "nowcast.js", "snap28.js", "filings.js", "snap29.js", "futures.js", "snap30.js", "book.js", "snappc.js", "credit.js", "sources.js", "reading.js", "snap38.js", "trackdesk.js", "memos.js", "levers_data.js", "levers.js", "execdesk.js", "deeprl.js", "landing.js", "guide.js", "keys.js", "today7.js",
           "boot.js"]


# ---------------------------------------------------------------- the core page (v0.43)
CORE_OUT = ROOT / "site" / "core.html"
CORE_VIEWS = ["home", "desk", "book", "decision", "hedgetest", "track", "execution", "inventory", "memos", "fundamentals", "explained", "parameters", "engines", "engine", "appendix"]
# Files only the library's desks use are left out of the core page: each is replaced by inert stand-ins for the names it
# declares (STUB below), so the modules that read them at load still load, and nothing on the core page renders from
# them. The list is scripts/core_stubs.json, found by scripts/prune_core.py, which leaves a file out only if every core
# desk then renders and behaves the same and no step fails.
CORE_STUBS_FILE = ROOT / "scripts" / "core_stubs.json"


def core_stubs() -> dict:
    import json
    return json.loads(CORE_STUBS_FILE.read_text())["stubs"] if CORE_STUBS_FILE.exists() else {}
STUB = """  // An inert stand-in for data the core page does not carry: any property, call or loop on it yields nothing.
  const __stub = (() => { const f = () => {}; const p = new Proxy(f, {
    get: (t, k) => (k === Symbol.iterator ? function* () {} : k === Symbol.toPrimitive ? () => 0 : k === "length" ? 0 : k === "then" ? undefined : p),
    apply: () => p, has: () => false, ownKeys: () => [], getOwnPropertyDescriptor: () => undefined, set: () => true }); return p; })();"""
CORE_NAV = """    <nav class="tabs" aria-label="Sections">
      <a href="#home" data-group="today">Call</a>
      <a href="#track" data-group="record">Record</a>
      <a href="#inventory" data-group="evidence">Evidence</a>
      <a href="#explained" data-group="engine">Method</a>
      <a href="page.html" class="lib-link" id="lib-link" title="Every other desk: the research library">Library</a>
    </nav>"""


# Parts of a core desk the core page leaves out: on the Desk, everything under "how the call is derived" (the six
# stages, what the engine has learned, the codebase, where it plugs in). The Method group answers those; the Desk
# on the core page is the call, what changed, what would reverse it, and what is coming.
CORE_CUTS = ["desk-more"]


def cut_element(body: str, el_id: str) -> str:
    """Remove the element with this id, whatever it holds (balanced by its own tag)."""
    m = re.search(r"[ \t]*<([a-z]+)\b[^>]*\bid=\"" + re.escape(el_id) + r"\"[^>]*>", body)
    if not m:
        raise SystemExit(f"no element with id {el_id} to cut")
    tag, depth, pos = m.group(1), 1, m.end()
    for t in re.finditer(rf"<(/?){tag}\b[^>]*>", body[m.end():]):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            pos = m.end() + t.end()
            break
    else:
        raise SystemExit(f"the element with id {el_id} is not closed")
    return body[: m.start()] + body[pos:].lstrip("\n")


def core_body(body: str, keep: list[str] = CORE_VIEWS) -> str:
    """The body with only the core desks. A desk is a top-level <section class="view" id="view-NAME">; it runs to the
    next desk or to the end of <main>. Each piece removed must be balanced markup, or the build stops."""
    starts = [(m.start(), m.group(1)) for m in re.finditer(r'<section class="view" id="view-([a-z0-9]+)"', body)]
    end = body.index("\n</main>")
    out, pos = [], 0
    for i, (a, name) in enumerate(starts):
        b = starts[i + 1][0] if i + 1 < len(starts) else end
        seg = body[a:b]
        if name in keep:
            continue
        if len(re.findall(r"<section\b", seg)) != len(re.findall(r"</section>", seg)) or len(re.findall(r"<div\b", seg)) != len(re.findall(r"</div>", seg)):
            raise SystemExit(f"the {name} desk is not balanced markup; the core page cannot leave it out")
        out.append(body[pos:a])
        pos = b
    out.append(body[pos:])
    body = "".join(out)
    missing = [v for v in keep if f'id="view-{v}"' not in body]
    if missing:
        raise SystemExit(f"core desks missing from the body: {missing}")
    for el in CORE_CUTS:
        if f'id="{el}"' in body:
            body = cut_element(body, el)
    nav = re.search(r'    <nav class="tabs" aria-label="Sections">.*?</nav>', body, flags=re.S)
    return body[: nav.start()] + CORE_NAV + body[nav.end():]


def stand_in(name: str, d: dict) -> str:
    """A file the core page leaves out, as inert stand-ins for the names it declares."""
    lines = [f"  /* {name}: not on the core page (scripts/prune_core.py) */"]
    lines += [f"  let {c} = __stub;" for c in d.get("consts", [])]      # v0.44.1: let, so shared code that resets one (boot.js) does not throw
    lines += [f"  function {f}() {{ return __stub; }}" for f in d.get("funcs", [])]
    return "\n".join(lines)


def empty_raw(text: str, names: dict) -> str:
    """Replace a constant written as String.raw with backticks (JSON kept as text and parsed on demand) by an empty
    document of the same kind."""
    for name, empty in names.items():
        m = re.search(r"^  const " + re.escape(name) + r" = String\.raw`", text, flags=re.M)
        if not m:
            raise SystemExit(f"{name} is not a raw-string constant")
        end = text.index("`;", m.end())
        import json
        text = text[: m.start()] + f"  const {name} = {json.dumps(empty)};   /* not on the core page */" + text[end + 2:]
    return text


def assemble(src: Path = SRC, core: bool = False, stubs: dict | None = None) -> str:
    head = (src / "head.html").read_text().rstrip()
    if (src / "fonts.css").exists():                     # the typeface, inlined (site/src/fonts.css, SIL OFL)
        head = head.replace("/*FONTS*/", (src / "fonts.css").read_text().rstrip(), 1)
    body = (src / "body.html").read_text().strip()
    if (src / "logo.html").exists():                     # the lotus symbols (scripts/make_logo.py)
        body = body.replace("<!--LOGO-->", (src / "logo.html").read_text().strip(), 1)
    if (src / "favicon.png").exists():                   # v0.40.1: 64 px PNG, a few KB, in place of the 57 KB vector
        import base64
        head = head.replace("</title>", '</title>\n<link rel="icon" type="image/png" href="data:image/png;base64,' + base64.b64encode((src / "favicon.png").read_bytes()).decode() + '">', 1)
    elif (src / "favicon.svg").exists():
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
    flag = "  const BUILD_CORE = false;"
    if core:
        body = core_body(body)
        flag = "  const BUILD_CORE = true;\n" + STUB
        for name, d in (core_stubs() if stubs is None else stubs).items():
            if name in texts:
                texts[name] = empty_raw(texts[name], d["raw"]) if "raw" in d else stand_in(name, d)
    js = "\n\n".join(texts.values())
    return f'{SKELETON}\n{head}\n{body}\n<script>\n(() => {{\n  "use strict";\n{flag}\n{js}\n}})();\n</script>\n\n</body></html>\n'


def main(argv: list[str]) -> int:
    page, core = assemble(), assemble(core=True)
    if "--check" in argv:
        stale = [o.name for o, t in ((OUT, page), (CORE_OUT, core)) if not o.exists() or o.read_text() != t]
        if stale:
            print(f"{', '.join('site/' + n for n in stale)} out of date: run python scripts/assemble_page.py", file=sys.stderr)
            return 1
        print("site/page.html and site/core.html are current")
        return 0
    OUT.write_text(page)
    CORE_OUT.write_text(core)
    print("wrote", CORE_OUT.relative_to(ROOT), f"({len(core):,} bytes)")
    print("wrote", OUT.relative_to(ROOT), f"({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
