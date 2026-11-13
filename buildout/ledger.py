"""The call ledger (v0.38): every call the engine makes, written before the next bar and never edited.

ledger/calls.jsonl at the repository root holds one JSON object per line. Each entry carries the time it was
written (UTC), the date of the data it used, the first trading day it governs, the call itself (the size, the
binding limit, the two ends of the menu, the bond hedge), the engine version, a hash of the inputs, and a SHA-256
hash chain: each entry's hash covers its content and the previous entry's hash, so changing or deleting any past
line breaks every hash after it. `verify` recomputes the chain; the daily run appends one entry per new data date
and commits it, so git's history is a second, independent timestamp.

    python -m buildout ledger append   # from the shipped snapshot (site/src/snap30.js) or a book.json
    python -m buildout ledger verify
    python -m buildout ledger show
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "ledger" / "calls.jsonl"
GENESIS = "0" * 64


def _canon(o: dict) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def entry_hash(e: dict) -> str:
    body = {k: v for k, v in e.items() if k != "hash"}
    return hashlib.sha256(_canon(body).encode()).hexdigest()


def read(path: Path = PATH) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:            # a torn or edited line: verify() reports it, read() never guesses
            raise LedgerError(f"line {n} of {path.name} is not valid JSON") from exc
    return out


class LedgerError(ValueError):
    pass


def verify(path: Path = PATH) -> dict:
    """Recompute the chain. ok is False if any entry's hash is wrong, any link is broken, the sequence skips, or the
    write times go backwards."""
    try:
        rows = read(path)
    except LedgerError as exc:
        return {"ok": False, "entries": None, "head": None, "problems": [str(exc)]}
    prev, problems = GENESIS, []
    for i, e in enumerate(rows):
        if e.get("seq") != i + 1:
            problems.append(f"entry {i + 1}: sequence number {e.get('seq')}")
        if e.get("prev") != prev:
            problems.append(f"entry {i + 1}: previous hash does not match entry {i}")
        if entry_hash(e) != e.get("hash"):
            problems.append(f"entry {i + 1}: content does not match its hash (edited after it was written)")
        if i and e["ts_utc"] < rows[i - 1]["ts_utc"]:
            problems.append(f"entry {i + 1}: written before entry {i}")
        if e.get("effective_from", "") <= e.get("ts_utc", "")[:10]:
            problems.append(f"entry {i + 1}: effective on or before the day it was written (backdated)")
        prev = e.get("hash")
    return {"ok": not problems, "entries": len(rows), "head": prev if rows else None, "problems": problems}


def next_trading_day(d: str) -> str:
    """The next New York Stock Exchange session after d (buildout/sessions.py, standard library: the site build
    imports this module and installs nothing). v0.42.5: before, this skipped weekends only, so a call written the
    day before a holiday took effect on a day with no session. Entries already in the ledger keep the effective date
    they were written with."""
    from . import sessions
    return sessions.next_session(d).isoformat()


def make_entry(book: dict, version: str, prev: dict | None, ts: str | None = None, source: str = "snapshot") -> dict:
    fr = [r for r in (book.get("frontier") or []) if r.get("meets")]
    call = {"size": round(float(book["size"]), 4), "binding": book["binding"],
            "menu_low": {"gross": round(fr[0]["gross"], 4), "short": fr[0]["short"]} if fr else None,
            "menu_high": {"gross": round(fr[-1]["gross"], 4), "short": fr[-1]["short"]} if fr else None,
            "bond_hedge": "off" if (book.get("hedges", {}).get("policies", {}).get("bond_when_it_hedges", {}).get("variance_cut", 0) or 0) < 0.1 else "on",
            "vol_rule_reads": (book.get("vol_rule") or {}).get("book", {}).get("headline", {}).get("exposure_now")}
    # a call governs from the first trading day after it was written, never from the day after its data: a call
    # logged late is not backdated
    ts = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    effective = next_trading_day(max(book["asof"], ts[:10]))
    inputs = hashlib.sha256(_canon({k: book.get(k) for k in ("asof", "from", "sizes", "tail", "risk", "exposure")}).encode()).hexdigest()
    e = {"seq": (prev["seq"] + 1) if prev else 1, "ts_utc": ts, "effective_from": effective,
         "data_asof": book["asof"], "call": call,
         "engine": version, "source": source, "inputs_sha256": inputs, "prev": prev["hash"] if prev else GENESIS}
    e["hash"] = entry_hash(e)
    return e


def append(book: dict, version: str, path: Path = PATH, ts: str | None = None, source: str = "snapshot") -> dict:
    """Append one entry if the data date is new. Never rewrites the file: opens it in append mode only. Refuses if
    the existing chain does not verify."""
    v = verify(path)
    if not v["ok"]:
        raise RuntimeError("the ledger does not verify; refusing to append: " + "; ".join(v["problems"][:3]))
    rows = read(path)
    last = rows[-1] if rows else None
    if last and last["data_asof"] >= book["asof"]:
        return {"appended": False, "reason": f"already logged data through {last['data_asof']}", "entry": last}
    e = make_entry(book, version, last, ts, source)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(_canon(e) + "\n")
    return {"appended": True, "entry": e}


def _snap_book() -> dict:
    s = (ROOT / "site" / "src" / "snap30.js").read_text()
    i = s.index("const SNAP30 = ")
    return json.loads(s[i + 15:s.index(";\n", i)].replace("<\\/", "</"))["book"]


def main(argv: list[str]) -> int:
    from . import __version__
    cmd = argv[0] if argv else "verify"
    if cmd == "append":
        src = argv[argv.index("--book") + 1] if "--book" in argv else None
        book = json.loads(Path(src).read_text()) if src else _snap_book()
        r = append(book, __version__, source="book.json" if src else "snapshot")
        print(("appended entry " + str(r["entry"]["seq"])) if r["appended"] else r["reason"], r["entry"]["hash"][:12])
        return 0
    if cmd == "verify":
        v = verify()
        print(("ok" if v["ok"] else "BROKEN"), v["entries"], "entries", (v["head"] or "")[:12])
        for p in v["problems"]:
            print("  ", p)
        return 0 if v["ok"] else 1
    if cmd == "show":
        for e in read():
            c = e["call"]
            print(f"{e['seq']:4d} {e['ts_utc']} data {e['data_asof']} from {e['effective_from']}  size {c['size']:.2f} ({c['binding']})  {e['hash'][:12]}")
        return 0
    print("usage: ledger append [--book book.json] | verify | show")
    return 2
