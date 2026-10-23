"""`python -m buildout doctor`: is this installation healthy, and if not, exactly what is wrong.

Each check returns (status, name, detail) with status ok, warn or FAIL. The command exits 1 when anything fails, so the
daily Action can run it first and stop early with a readable reason instead of a stack trace twenty minutes in.

    environment   Python version; required and optional packages
    repository    package version, config files, private files kept out of git, no secret in tracked files
    knowledge     the mind graph (ids unique, links in range, signals resolve), the checked knowledge items, the
                  concepts' relations, the quotes' sources
    bonds         today's curve and the ETF facts, and that each fund's ladder reproduces its reported duration
    engine        the dependency graph has no cycle; contracts parse
    page          every snapshot the page needs exists and site/page.html is assembled from the current sources
    cache         the cache folder is writable and an entry round-trips
    network       (with --net) which data sources answer
"""
from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "buildout"


def _ok(name, detail=""):
    return ("ok", name, detail)


def _warn(name, detail):
    return ("warn", name, detail)


def _fail(name, detail):
    return ("FAIL", name, detail)


def environment() -> list:
    out = []
    v = sys.version_info
    out.append(_ok("python", f"{v.major}.{v.minor}.{v.micro}") if v >= (3, 10) else _fail("python", f"{v.major}.{v.minor}: needs 3.10 or newer"))
    for m in ("numpy", "pandas", "scipy", "sklearn"):
        try:
            mod = importlib.import_module(m)
            out.append(_ok(f"package {m}", getattr(mod, "__version__", "")))
        except ImportError as exc:
            out.append(_fail(f"package {m}", str(exc)))
    for m, why in (("databento", "Databento prices in the daily run"), ("playwright", "the browser stress test")):
        try:
            importlib.import_module(m)
            out.append(_ok(f"optional {m}"))
        except ImportError:
            out.append(_warn(f"optional {m}", f"not installed ({why})"))
    return out


def repository() -> list:
    from buildout import __version__
    out = [_ok("version", __version__)]
    pv = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M) if (ROOT / "pyproject.toml").exists() else None
    out.append(_ok("pyproject version") if pv and pv.group(1) == __version__ else _fail("pyproject version", f"{pv.group(1) if pv else 'missing'} != {__version__}"))
    out.append(_ok("config.toml") if (ROOT / "config.toml").exists() else _warn("config.toml", "missing; defaults apply"))
    ign = (ROOT / ".gitignore").read_text() if (ROOT / ".gitignore").exists() else ""
    out.append(_ok("private files ignored") if "config.private.toml" in ign and ".env" in ign else _fail("private files ignored", ".gitignore must list config.private.toml and .env"))
    try:
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.split()
    except (OSError, subprocess.SubprocessError):
        files = []
    leaks = []
    pat = re.compile(r"\bdb-[A-Za-z0-9]{20,}\b")
    for f in files:
        p = ROOT / f
        if p.suffix in (".py", ".js", ".toml", ".yml", ".yaml", ".md", ".json", ".el", ".vim", ".html") and p.exists() and p.stat().st_size < 12_000_000:
            if pat.search(p.read_text(errors="ignore")):
                leaks.append(f)
    out.append(_ok("no secrets in tracked files", f"{len(files)} files scanned") if not leaks else _fail("no secrets in tracked files", ", ".join(leaks[:5])))
    return out


def knowledge() -> list:
    out = []
    from buildout import mind, ontology, voices
    p = PKG / "assets" / "mind.json"
    try:
        G = json.loads(p.read_text())
        ids = [n["id"] for n in G["nodes"]]
        N = len(ids)
        bad_e = sum(1 for e in G["edges"] if not (0 <= e[0] < N and 0 <= e[1] < N and e[2] > 0))
        idset = set(ids)
        bad_s = [s["id"] for s in G["signals"] if s["id"] not in idset]
        if len(idset) != N or bad_e or bad_s:
            out.append(_fail("mind graph", f"{N - len(idset)} duplicate ids, {bad_e} bad links, {len(bad_s)} unresolved signals"))
        else:
            out.append(_ok("mind graph", f"{N:,} nodes, {len(G['edges']):,} links, {len(G['signals'])} signals"))
        m = mind.Mind(G)
        r = m.think("Should I buy long bonds?")
        out.append(_ok("mind thinks", f"{r.get('axis')}: {r.get('p', 0):.0%}") if r.get("found") else _fail("mind thinks", "no answer to a known question"))
    except Exception as exc:
        out.append(_fail("mind graph", f"{type(exc).__name__}: {exc}"[:160]))
    try:
        items = mind.load_knowledge()
        unchecked = [i["id"] for i in items if not str(i.get("checked", "")).startswith(("confirmed", "corrected"))]
        unsourced = [i["id"] for i in items if not str(i.get("source_url", "")).startswith("https://")]
        out.append(_ok("knowledge items", f"{len(items)} checked and sourced") if not unchecked and not unsourced
                   else _fail("knowledge items", f"{len(unchecked)} unchecked, {len(unsourced)} unsourced"))
    except Exception as exc:
        out.append(_fail("knowledge items", str(exc)[:160]))
    cs = ontology.concepts()
    known = {c["id"] for c in cs}
    dangling = [(c["id"], t) for c in cs for k, t in c["rel"] if ":" not in t and "c:" + t not in known]
    out.append(_ok("concepts", f"{len(cs):,} concepts, every relation resolves") if not dangling else _fail("concepts", f"{len(dangling)} relations point nowhere, e.g. {dangling[:2]}"))
    q = voices.load()
    badq = [x["id"] for x in q if not str(x.get("source_url", "")).startswith("https://")]
    out.append(_ok("quotes", f"{len(q)} verified quotes") if not badq else _fail("quotes", f"{len(badq)} without a source"))
    return out


def bonds() -> list:
    from buildout import bondlab, mind
    try:
        curve, facts, meta = bondlab.from_knowledge(mind.load_knowledge())
        if "10y" not in curve or "30y" not in curve:
            return [_fail("bond curve", "no 10-year or 30-year in the knowledge base")]
        F = bondlab.setup(curve, facts)
        off = {t: abs(F[t]["duration"] - facts[t]["duration"]) for t in F if facts.get(t, {}).get("duration") and not F[t]["zero"]}
        worst = max(off.values()) if off else 0.0
        res = [_ok("bond curve", f"{meta.get('as_of')}: 10-year {curve['10y']:.2%}, 30-year {curve['30y']:.2%}")]
        res.append(_ok("bond ladders", f"{len(off)} funds match their reported duration (worst {worst:.1e} years)") if worst < 1e-3
                   else _fail("bond ladders", f"a ladder misses its reported duration by {worst:.3f} years"))
        return res
    except Exception as exc:
        return [_fail("bond lab", f"{type(exc).__name__}: {exc}"[:160])]


def engine() -> list:
    from buildout.core import contracts, runner
    from buildout.engine import tasks
    try:
        lv = runner.levels(tasks())
        out = [_ok("engine graph", f"{sum(len(x) for x in lv)} engines in {len(lv)} levels, no cycle")]
    except runner.CycleError as exc:
        out = [_fail("engine graph", str(exc))]
    out.append(_ok("contracts", f"{len(contracts.CONTRACTS)} output files have contracts"))
    return out


def page() -> list:
    out = []
    src = ROOT / "site" / "src"
    need = ["snap14.js", "snap15.js", "snap16.js", "snap17.js", "snap19.js", "snap20.js", "snap21.js", "snap22.js"]
    miss = [n for n in need if not (src / n).exists()]
    out.append(_ok("snapshots", ", ".join(need)) if not miss else _fail("snapshots", "missing " + ", ".join(miss)))
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import assemble_page
        cur = (ROOT / "site" / "page.html").read_text() if (ROOT / "site" / "page.html").exists() else ""
        out.append(_ok("page assembled", f"{len(cur) / 1e6:.1f} MB") if cur == assemble_page.assemble() else _warn("page assembled", "site/page.html is older than its sources: run python scripts/assemble_page.py"))
    except Exception as exc:
        out.append(_warn("page assembled", f"could not check ({exc})"[:160]))
    return out


def cache_check() -> list:
    from buildout.core import cache
    key = cache.digest("doctor", "probe")
    ok = cache.put(key, {"probe": 1}) and cache.get(key) == (True, {"probe": 1})
    i = cache.info()
    return [_ok("cache", f"{i['entries']} entries, {i['bytes'] / 1e6:.1f} MB in {i['dir']}") if ok else
            (_warn("cache", "disabled by BUILDOUT_NO_CACHE") if not cache.enabled() else _fail("cache", f"cannot write {i['dir']}"))]


def network() -> list:
    from buildout import datahub
    rows = datahub.check(timeout=6)
    return [(("ok" if r.get("reachable") else "warn"), f"source {r.get('source')}", (f"{r['ms']} ms" if r.get("ms") else "") + (" " + r["note"] if r.get("note") else "")) for r in rows]


def run(net: bool = False) -> list:
    out = []
    for name, fn in (("environment", environment), ("repository", repository), ("knowledge", knowledge), ("bonds", bonds),
                     ("engine", engine), ("page", page), ("cache", cache_check)) + ((("network", network),) if net else ()):
        try:
            out += [(s, f"{name}: {n}", d) for s, n, d in fn()]
        except Exception as exc:
            out.append(("FAIL", name, f"{type(exc).__name__}: {exc}"[:200]))
    return out
