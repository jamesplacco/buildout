"""Wrap site/core.html (the core page) and site/page.html (every desk: the library) into standalone pages for GitHub Pages.

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
    # v0.43: two pages from the same sources. index.html is the core page (the desks the call depends on); library.html
    # is the full page with every desk. A build without site/core.html (older checkouts) publishes the full page alone.
    full = document(Path(src, "page.html").read_text())
    core_src = Path(src, "core.html")
    dest = Path(out)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if core_src.exists():
        core = core_src.read_text()
        a, b = "  const BUILD_CORE = true;", '<a href="page.html" class="lib-link"'
        if core.count(a) != 1 or core.count(b) != 1:
            raise SystemExit("site/core.html is not a core page this script knows how to link to the library")
        core = core.replace(a, a + '\n  const BUILD_LIBRARY_HREF = "library.html";', 1).replace(b, '<a href="library.html" class="lib-link"', 1)
        (dest / "index.html").write_text(document(core))
        (dest / "library.html").write_text(full)
    else:
        (dest / "index.html").write_text(full)
    (dest / ".nojekyll").write_text("")
    pdf = Path(src, "tearsheet.pdf")
    if pdf.exists():                      # v0.38: the tear sheet the Home and Track record pages link to
        shutil.copy(pdf, dest / "tearsheet.pdf")
    data = Path(src, "data")
    if data.exists():                     # v0.47: never the debris of a killed run (dot-files, temporary files, last-good copies)
        shutil.copytree(data, dest / "data", ignore=shutil.ignore_patterns(".*", "*.tmp"))
    led = Path(src).resolve().parent / "ledger" / "calls.jsonl"
    if led.exists():                      # v0.39.1: the ledger, verified, so the published page shows every call logged since its build
        import sys as _sys
        _sys.path.insert(0, str(Path(src).resolve().parent))
        from buildout import ledger as _ledger
        (dest / "data").mkdir(parents=True, exist_ok=True)
        (dest / "data" / "calls.json").write_text(json.dumps({"verify": _ledger.verify(led),          # v0.47: each call with the session it governs from (ledger.governs_from)
                                                                "entries": [{**e, "governs_from": _ledger.governs_from(e)} for e in _ledger.read(led)]}))
    (dest / "data").mkdir(parents=True, exist_ok=True)
    dec = reconcile(dest, Path(src).resolve().parent)
    (dest / "data" / "manifest.json").write_text(json.dumps({**manifest(dest), "decision": dec}, indent=1))
    return dest / "index.html"


def document(page: str) -> str:
    """One standards-mode document (v0.42.5). site/page.html has carried the artifact viewer's own skeleton since
    v0.39 (a doctype, a head with a reset, an opened body), and this script went on wrapping it in a second one, so
    the published page opened two documents, one inside the other. Browsers recovered; it was still invalid. The
    page's own skeleton is taken off first, then its title and stylesheet go in the one head and the rest in the
    one body. A page without a skeleton (older builds) is wrapped as before."""
    low = page[:2000].lower()
    if low.lstrip().startswith("<!doctype"):
        i = low.index("<body>") + len("<body>")
        page = page[i:]
        end = page.rstrip()
        for tail in ("</html>", "</body>"):
            if end.lower().endswith(tail):
                end = end[: -len(tail)].rstrip()
        page = end + "\n"
    page = page.lstrip("\n")
    if page.lower().startswith('<meta charset="utf-8">'):          # the one head already declares it
        page = page[len('<meta charset="utf-8">'):].lstrip("\n")
    cut = page.index("</style>") + len("</style>")
    html = HEAD + page[:cut] + "\n</head>\n<body>\n" + page[cut:] + "\n</body>\n</html>\n"
    import re
    markup = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I).lower()      # what the parser reads as markup; script text is data
    n_doc, n_html = markup.count("<!doctype"), markup.count("<html")
    if n_doc != 1 or n_html != 1:
        raise SystemExit(f"the built page declares {n_doc} doctypes and opens {n_html} html elements; it must be one document")
    return html


def reconcile(dest: Path, root: Path) -> dict:
    """One decision across surfaces, checked at publication (v0.42.5). The call the page will show (data/book.json's
    menu) must be the call the ledger logged for the same data date, and no frontier row marked as meeting the limits
    may exceed one. The page quotes the ledger's entry, so a disagreement cannot reach a reader as two hedges; it
    is recorded in the manifest (agrees: false) with what the engine now computes. Returns the decision the
    deployment carries."""
    import sys as _sys
    _sys.path.insert(0, str(root))
    from buildout import ledger as _ledger
    bp = dest / "data" / "book.json"
    if not bp.exists():
        return {"checked": False, "why": "no book.json in this deployment"}
    book = json.loads(bp.read_text())
    L = book.get("limits") or {}
    eps = 1e-9
    from buildout import limits as _limits
    # v0.48: the evaluator the menu was built with (buildout/limits.py): every limit the file states, the two gross
    # rules by name, and a check that cannot be made is not a pass
    over = []
    for r in (book.get("frontier") or []):
        if r.get("meets"):
            ev = _limits.evaluate_row(r, L)
            if not ev["meets"]:
                r["meets"], r["over_limit"] = False, True
                r["constraints"] = {k: ev[k] for k in ("status", "failed", "unchecked", "required", "binding")}
                over.append(r)
    if over:                                    # an earlier build wrote this file: mark the rows, do not hide them
        bp.write_text(json.dumps(book, indent=1))
    rows = _ledger.read(root / "ledger" / "calls.jsonl") if (root / "ledger" / "calls.jsonl").exists() else []
    e = next((x for x in reversed(rows) if x.get("data_asof") == book.get("asof")), None)
    out = {"checked": True, "book_asof": book.get("asof"), "rows_marked_over_limit": len(over), "logged": bool(e)}
    if e:
        fr = [r for r in book.get("frontier") or [] if r.get("meets")]
        c = e["call"]
        same = bool(fr) and c.get("menu_low") and c.get("menu_high") and abs(round(fr[0]["gross"], 4) - c["menu_low"]["gross"]) < 1e-9 and abs(fr[0]["short"] - c["menu_low"]["short"]) < 1e-9 \
            and abs(round(fr[-1]["gross"], 4) - c["menu_high"]["gross"]) < 1e-9 and abs(fr[-1]["short"] - c["menu_high"]["short"]) < 1e-9 and abs(round(float(book["size"]), 4) - c["size"]) < 1e-9
        out.update({"decision_id": f"{e['seq']}-{str(e.get('hash', ''))[:8]}", "effective_from": e["effective_from"], "menu": {"low": c.get("menu_low"), "high": c.get("menu_high")}, "agrees": bool(same)})
        if not same:                              # the page quotes the logged entry; the engine's rerun of the same date is shown beside it
            out["engine_now"] = [[r["gross"], r["short"]] for r in fr[:1] + fr[-1:]]
            out["note"] = "the engine, rerun on this date, computes a different menu than the entry logged; the page shows the logged entry and states the difference"
    return out


# v0.47: where each file keeps the date of its data, tried in order, and where it keeps the time it was written. Before,
# only six top-level keys were tried, so twenty of thirty-two files had no date in the manifest, and a file that carried
# only its run day (technicals, statements, capex) was listed as that fresh.
DATA_DATE_PATHS = ("asof", "as_of", "summary.as_of", "latest.as_of", "last_mark", "marks_asof", "panel.end", "latest.month", "now.date", "end",
                   "notes.end", "today.notes.date", "curve_meta.as_of", "data.shiller_to", "state.eq.month", "date")
RUN_TIME_PATHS = ("generated_utc", "computed_utc", "run_at", "built", "checked")


def _dig(d, path: str):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d if isinstance(d, str) and d else None


def data_date(d) -> str | None:
    """The date of a file's data (not of the run that wrote it), or None when the file states none."""
    return next((v for v in (_dig(d, p) for p in DATA_DATE_PATHS) if v), None)


def run_time(d) -> str | None:
    return next((v for v in (_dig(d, p) for p in RUN_TIME_PATHS) if v), None)


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
        asof, written = data_date(d), run_time(d)
        files[p.name] = {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16], "asof": asof if asof is not None else written,
                         "asof_kind": "data" if asof is not None else ("written" if written is not None else None), "written": written}
    page = dest / "index.html"
    return {"source_commit": sha, "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "page_bytes": page.stat().st_size if page.exists() else None,
            "library_bytes": (dest / "library.html").stat().st_size if (dest / "library.html").exists() else None, "data": files}


if __name__ == "__main__":
    print("built", build(*sys.argv[1:]))
