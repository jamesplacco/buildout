"""Find what the core page can leave out (v0.43), and prove it by rendering.

    python3 scripts/prune_core.py                 # snapshots only (data)
    python3 scripts/prune_core.py --code          # also the modules that only the library's desks use

The core page (site/core.html) is assembled from the same sources as the full page with the library's desks cut from
the markup. This script decides which scripts it can also do without. For each candidate file it builds the core
page with that file replaced by inert stand-ins for the names it declares (a constant becomes an object on which any
property, call or loop yields nothing; a function becomes one that does nothing), opens the result in a browser,
visits every core desk, then uses it (opens what folds, moves every slider, changes every select, presses every
toggle), and compares what rendered with the page that carries everything. A file is left out only if no desk's text
or chart marks change, no step reports an error, and search returns the same results. A module of code must pass a
second test first: no core module may refer to any name it declares. Large constants kept as raw JSON text (the mind's
graph, the embedded source) are tried one by one and replaced by an empty document. The list is written to
scripts/core_stubs.json, which scripts/assemble_page.py reads. Run it again when a core desk starts to use something
it did not; the tests fail if the core page stops matching the full page's core desks.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import assemble_page as A  # noqa: E402

PROBE = ROOT / "site" / "tests" / "core_probe.js"
OUT = ROOT / "scripts" / "core_stubs.json"
# never candidates: the shared machinery and the core desks' own modules
KEEP = {"math.js", "ui.js", "views.js", "boot.js", "reference.js", "guide.js", "keys.js", "landing.js", "book.js", "trackdesk.js", "execdesk.js", "dx.js", "dxlive.js",
        "memos.js", "today7.js", "snap19.js", "snap30.js", "snap38.js", "data.js", "sources.js", "hero.js", "engine7.js"}


def declared(text: str) -> dict | None:
    """The names a file declares at the top level of the shared scope, or None if it declares one this cannot stand in
    for (a destructuring pattern, a class). A declaration may name several things (const A = x.a, B = x.b;): the
    statement is read to its closing semicolon, and a comma outside every bracket and string starts the next name."""
    consts: list[str] = []
    for m in re.finditer(r"^  (?:const|let|var) ", text, flags=re.M):
        i, depth, quote, expect = m.end(), 0, "", True
        while i < len(text):
            c = text[i]
            if quote:
                if c == "\\":
                    i += 2
                    continue
                if c == quote:
                    quote = ""
                elif quote == "`" and c == "$" and text[i + 1: i + 2] == "{":
                    j, d = i + 2, 1                              # skip the expression inside a template
                    while j < len(text) and d:
                        d += {"{": 1, "}": -1}.get(text[j], 0)
                        j += 1
                    i = j
                    continue
                i += 1
                continue
            if expect and not c.isspace():
                if c in "[{":
                    return None                                   # destructuring
                nm = re.match(r"[A-Za-z_$][\w$]*", text[i:])
                if not nm:
                    return None
                consts.append(nm.group(0))
                i += nm.end()
                expect = False
                continue
            if c in "\"'`":
                quote = c
            elif c == "/" and text[i + 1: i + 2] == "/":
                i = text.index("\n", i) if "\n" in text[i:] else len(text)
                continue
            elif c == "/" and text[i + 1: i + 2] == "*":
                i = text.index("*/", i) + 2
                continue
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            elif c == "," and depth == 0:
                expect = True
            elif c == ";" and depth == 0:
                break
            i += 1
    funcs = re.findall(r"^  (?:async )?function\*? ?([A-Za-z_$][\w$]*)\s*\(", text, flags=re.M)
    if re.search(r"^  class [A-Za-z_$]", text, flags=re.M):
        return None
    return {"consts": consts, "funcs": funcs}


def probe(html: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "core.html"
        p.write_text(html)
        r = subprocess.run(["node", str(PROBE), str(p), "--wait=450"], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return {"errs": ["probe failed: " + r.stderr[-300:]], "views": {}}
    return json.loads(r.stdout)


def same(a: dict, b: dict) -> str | None:
    if b["errs"]:
        return "error: " + b["errs"][0][:120]
    if b.get("search") != a.get("search"):
        return "search differs"
    for v, x in a["views"].items():
        y = b["views"].get(v)
        if not y or y["hash"] != x["hash"] or y["svgs"] != x["svgs"] or y["rows"] != x["rows"] or y["errors"]:
            return f"{v} renders differently"
        if y["used"]["hash"] != x["used"]["hash"] or y["used"]["marks"] != x["used"]["marks"] or y["used"]["errors"]:
            return f"{v} behaves differently when used"
    return None


def raw_consts(text: str) -> dict:
    """Large constants written as String.raw text (JSON parsed on demand), with the empty document that stands in for each."""
    out = {}
    for m in re.finditer(r"^  const ([A-Za-z_$][\w$]*) = String\.raw`(.)", text, flags=re.M):
        end = text.index("`;", m.end())
        if end - m.start() > 20_000:
            out[m.group(1)] = "[]" if m.group(2) == "[" else "{}"
    return out


def used_by_core(names: list[str], texts: dict) -> str | None:
    """The first core module (other than the boot list) that mentions one of these names. A code file is a candidate
    only if no core module refers to anything it declares: rendering the same is necessary, not sufficient, because a
    button the probe did not press could call a function that had become a stand-in."""
    for k in sorted(KEEP - {"boot.js"}):
        if k.startswith("snap") or k not in texts:
            continue
        for nm in names:
            if re.search(r"(?<![\w$.])" + re.escape(nm) + r"(?![\w$])", texts[k]):
                return f"{k} uses {nm}"
    return None


def main(argv: list[str]) -> int:
    texts = {n: (A.SRC / n).read_text() for n in A.SCRIPTS}
    base = probe(A.assemble(core=True, stubs={}))
    assert not base["errs"], base["errs"][:3]
    stubs = json.loads(OUT.read_text())["stubs"] if OUT.exists() and "--fresh" not in argv else {}
    stubs = {k: v for k, v in stubs.items() if k in texts}
    if stubs and same(base, probe(A.assemble(core=True, stubs=stubs))):
        print("the stored list no longer holds; starting over")
        stubs = {}

    def attempt(n: str, d: dict, label: str, size: int) -> None:
        why = same(base, probe(A.assemble(core=True, stubs={**stubs, n: d})))
        if why is None:
            stubs[n] = d
        print(f"{label:34s} {size // 1024:6d} KB  {'LEFT OUT' if why is None else 'kept: ' + why}", flush=True)

    # 1. large raw-text constants, one at a time, wherever they live
    for n in A.SCRIPTS:
        if n in stubs:
            continue
        got = {}
        for name, empty in raw_consts(texts[n]).items():
            before = dict(got)
            got[name] = empty
            why = same(base, probe(A.assemble(core=True, stubs={**stubs, n: {"raw": got}})))
            print(f"{n + ': ' + name:34s} {'':6s}     {'LEFT OUT' if why is None else 'kept: ' + why}", flush=True)
            if why is not None:
                got = before
        if got:
            stubs[n] = {"raw": got}
    # 2. whole snapshots, 3. modules no core module refers to
    cands = [n for n in A.SCRIPTS if n.startswith("snap") and n not in KEEP]
    if "--code" in argv:
        cands += [n for n in A.SCRIPTS if not n.startswith("snap") and n not in KEEP]
    cands.sort(key=lambda n: -len(texts[n]))
    for n in cands:
        if n in stubs:
            continue
        d = declared(texts[n])
        if d is None or not (d["consts"] or d["funcs"]):
            print(f"{n:34s} {len(texts[n]) // 1024:6d} KB  kept: declarations this cannot stand in for", flush=True)
            continue
        if not n.startswith("snap"):
            u = used_by_core(d["consts"] + d["funcs"], texts)
            if u:
                print(f"{n:34s} {len(texts[n]) // 1024:6d} KB  kept: {u}", flush=True)
                continue
        attempt(n, d, n, len(texts[n]))
    OUT.write_text(json.dumps({"note": "written by scripts/prune_core.py; do not edit", "stubs": stubs}, indent=1) + "\n")
    core = A.assemble(core=True)
    print(f"core page {len(core):,} bytes with {len(stubs)} files left out; full page {len(A.assemble()):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
