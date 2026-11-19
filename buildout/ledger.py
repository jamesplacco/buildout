"""The call ledger (v0.38): every call the engine makes, written before the next bar and never edited.

ledger/calls.jsonl at the repository root holds one JSON object per line. Each entry carries the time it was
written (UTC), the date of the data it used, the first trading day it governs, the call itself (the size, the
binding limit, the two ends of the menu, the bond hedge), the engine version, a hash of the inputs, and a SHA-256
hash chain: each entry's hash covers its content and the previous entry's hash.

What the chain proves, and what it does not (v0.47). `verify` recomputes it, so an edit to a past line that does
not also rewrite every hash after it is caught, as are a torn line, a skipped number, a write time that goes
backwards or lies in the future, a data date that does not advance, and an effective date that is not an exchange
session. The chain is not keyed and not anchored: anyone who can write the file can change an entry and recompute
every hash after it, or cut entries off the end, and `verify` alone will pass. What catches that is outside this
file: the head published the day before (`continuity`, which the `live` command runs against the live.json it is
about to replace), git's history of the daily commits, and the external anchor the daily workflow writes. The
ledger is tamper-evident against a head someone else already holds; by itself it is not proof that its owner
never rewrote it.

When a call governs (v0.47). The live record marks close to close, so a call can only govern a day whose return
starts at a close that came after the call was written. `causal_effective` is that day: the session after the
first session whose close follows the write, and never earlier than the session after the data. New entries
store it. Entries written before v0.47 stored the session after the calendar day of writing, which for a call
written on a Saturday (or after the close) is one session early; they are never edited, and `governs_from`
returns the later of the stored date and the causal one. Everything that puts a call in force reads
`governs_from`, not the stored field.

    python -m buildout ledger append   # from the shipped snapshot (site/src/snap30.js) or a book.json
    python -m buildout ledger verify
    python -m buildout ledger show
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "ledger" / "calls.jsonl"
GENESIS = "0" * 64
REQUIRED = ("seq", "ts_utc", "effective_from", "data_asof", "call", "prev", "hash")
FUTURE_SKEW = timedelta(minutes=10)      # a write time this far ahead of the verifier's clock is reported
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _canon(o: dict) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _ts(s) -> datetime | None:
    """A ledger timestamp as an aware UTC datetime; None when it is not one."""
    try:
        return datetime.strptime(str(s), TS_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def entry_hash(e: dict) -> str:
    body = {k: v for k, v in e.items() if k != "hash"}
    return hashlib.sha256(_canon(body).encode()).hexdigest()


def read(path: Path | None = None) -> list[dict]:
    path = Path(path) if path else PATH
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


def verify(path: Path | None = None, now: datetime | None = None) -> dict:
    """Recompute the chain. ok is False if any entry's hash is wrong, any link is broken, the sequence skips, a field
    is missing, the write times go backwards or lie in the future (beyond FUTURE_SKEW of `now`), the data dates do
    not advance, or an effective date is not after the day of writing or is not an exchange session. Every problem
    is reported; a malformed entry is never an exception. See the module docstring for what a pass does not prove."""
    from . import sessions
    path = Path(path) if path else PATH
    try:
        rows = read(path)
    except LedgerError as exc:
        return {"ok": False, "entries": None, "head": None, "problems": [str(exc)]}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    prev, problems = GENESIS, []
    last_ts, last_asof = None, None
    for i, e in enumerate(rows):
        n = i + 1
        if not isinstance(e, dict):
            problems.append(f"entry {n}: not a JSON object")
            prev = None
            continue
        missing = [k for k in REQUIRED if k not in e]
        if missing:
            problems.append(f"entry {n}: missing {', '.join(missing)}")
        if e.get("seq") != n:
            problems.append(f"entry {n}: sequence number {e.get('seq')}")
        if e.get("prev") != prev:
            problems.append(f"entry {n}: previous hash does not match entry {i}")
        if entry_hash(e) != e.get("hash"):
            problems.append(f"entry {n}: content does not match its hash (edited after it was written)")
        ts = _ts(e.get("ts_utc"))
        if "ts_utc" in e and ts is None:
            problems.append(f"entry {n}: ts_utc {e.get('ts_utc')!r} is not a UTC timestamp ({TS_FORMAT})")
        if ts is not None:
            if last_ts is not None and ts < last_ts:
                problems.append(f"entry {n}: written before entry {i}")
            if ts > now + FUTURE_SKEW:
                problems.append(f"entry {n}: written in the future ({e['ts_utc']})")
            last_ts = ts
        eff = e.get("effective_from")
        if "effective_from" in e:
            try:
                eff_day = date.fromisoformat(str(eff))
            except ValueError:
                eff_day = None
                problems.append(f"entry {n}: effective_from {eff!r} is not a date")
            if eff_day is not None:
                if str(eff) <= str(e.get("ts_utc", ""))[:10]:
                    problems.append(f"entry {n}: effective on or before the day it was written (backdated)")
                if not sessions.is_session(eff_day):
                    problems.append(f"entry {n}: effective_from {eff} is not an exchange session")
        asof = e.get("data_asof")
        if "data_asof" in e:
            if last_asof is not None and str(asof) <= str(last_asof):
                problems.append(f"entry {n}: data date {asof} is not after entry {i}'s {last_asof}")
            last_asof = asof
        prev = e.get("hash")
    return {"ok": not problems, "entries": len(rows), "head": prev if rows else None, "problems": problems}


def head(path: Path | None = None) -> str | None:
    """The last entry's hash: the one value that pins the whole chain. None for an empty or unreadable ledger."""
    try:
        rows = read(path)
    except LedgerError:
        return None
    return rows[-1].get("hash") if rows and isinstance(rows[-1], dict) else None


def continuity(previous, path: Path | None = None) -> str | None:
    """Is the chain at `path` a continuation of the one a published file recorded? `previous` is that file's content
    or its path (live.json: `ledger_head`, or `ledger.head` before v0.47). Returns None when the recorded head is
    still one of the chain's hashes (or nothing was recorded), else the reason: the chain was rewritten or cut
    short after that file was published. verify() cannot see this; a head held elsewhere can."""
    if isinstance(previous, (str, Path)):
        p = Path(previous)
        if not p.exists():
            return None
        try:
            previous = json.loads(p.read_text())
        except (OSError, ValueError):
            return None                                   # an unreadable earlier file recorded nothing to hold the chain to
    if not isinstance(previous, dict):
        return None
    was = previous.get("ledger_head") or (previous.get("ledger") or {}).get("head")
    if not was:
        return None
    try:
        hashes = {e.get("hash") for e in read(path) if isinstance(e, dict)}
    except LedgerError as exc:
        return str(exc)
    if was in hashes:
        return None
    return (f"the ledger no longer contains the head {str(was)[:12]} that was published before: entries were rewritten or "
            "removed after publication")


def next_trading_day(d: str) -> str:
    """The next New York Stock Exchange session after d (buildout/sessions.py, standard library: the site build
    imports this module and installs nothing). v0.42.5: before, this skipped weekends only, so a call written the
    day before a holiday took effect on a day with no session. Entries already in the ledger keep the effective date
    they were written with."""
    from . import sessions
    return sessions.next_session(d).isoformat()


def causal_effective(ts_utc: str, data_asof: str | None = None) -> str:
    """The first session a call written at ts_utc can govern in a close-to-close record (v0.47): the session after
    the first session whose close comes after the write (the position can be put on at that close, not at one that
    had already passed), and never earlier than the session after the data's date."""
    from . import sessions
    ts = _ts(ts_utc)
    if ts is None:
        raise ValueError(f"{ts_utc!r} is not a UTC timestamp ({TS_FORMAT})")
    floor = sessions.session_of_close_after(ts)
    if data_asof:
        floor = max(floor, date.fromisoformat(str(data_asof)[:10]))
    return sessions.next_session(floor).isoformat()


def governs_from(entry: dict) -> str:
    """The first session an entry governs: the later of the date it stored and the causal date its write time allows.
    The stored field is never edited; an entry written before v0.47 on a Saturday, a holiday or after the close
    stored a session whose return began before the call existed, and governs from the session after it."""
    stored = str(entry.get("effective_from") or "")
    try:
        return max(stored, causal_effective(entry.get("ts_utc"), entry.get("data_asof")))
    except (TypeError, ValueError):
        return stored


def restated(rows: list[dict] | None = None) -> list[dict]:
    """The entries whose governing session differs from the effective date they stored, for disclosure."""
    out = []
    for e in (read() if rows is None else rows):
        g = governs_from(e)
        if g != e.get("effective_from"):
            out.append({"seq": e.get("seq"), "ts_utc": e.get("ts_utc"), "data_asof": e.get("data_asof"),
                        "effective_from": e.get("effective_from"), "governs_from": g,
                        "why": "written after the close that begins the stored effective day's return"})
    return out


def bond_call(book: dict) -> dict:
    """The bond hedge as today's regime reads (v0.47): on only when the stock-bond correlation state is "hedging"
    and today's minimum-variance bond ratio is positive. Before, the flag read the whole history's variance cut and
    neither of today's readings, so it stayed off in a hedging regime. The state and the ratio are logged with it."""
    state = (book.get("correlation") or {}).get("state")
    ratio = ((book.get("hedges") or {}).get("now") or {}).get("bond_ratio")
    ratio = float(ratio) if isinstance(ratio, (int, float)) and not isinstance(ratio, bool) and ratio == ratio else None
    return {"bond_hedge": "on" if state == "hedging" and ratio is not None and ratio > 0 else "off",
            "bond_state": state, "bond_ratio": round(ratio, 4) if ratio is not None else None}


def make_entry(book: dict, version: str, prev: dict | None, ts: str | None = None, source: str = "snapshot") -> dict:
    fr = [r for r in (book.get("frontier") or []) if r.get("meets")]
    call = {"size": round(float(book["size"]), 4), "binding": book["binding"],
            "menu_low": {"gross": round(fr[0]["gross"], 4), "short": fr[0]["short"]} if fr else None,
            "menu_high": {"gross": round(fr[-1]["gross"], 4), "short": fr[-1]["short"]} if fr else None,
            **bond_call(book),
            "vol_rule_reads": (book.get("vol_rule") or {}).get("book", {}).get("headline", {}).get("exposure_now")}
    # a call governs from the session after the first close that follows its writing, never from the day after its
    # data: a call logged late is not backdated, and one logged after a close does not govern the return that began there
    ts = ts or datetime.now(timezone.utc).strftime(TS_FORMAT)
    effective = causal_effective(ts, book["asof"])
    inputs = hashlib.sha256(_canon({k: book.get(k) for k in ("asof", "from", "sizes", "tail", "risk", "exposure")}).encode()).hexdigest()
    e = {"seq": (prev["seq"] + 1) if prev else 1, "ts_utc": ts, "effective_from": effective,
         "data_asof": book["asof"], "call": call,
         "engine": version, "source": source, "inputs_sha256": inputs, "prev": prev["hash"] if prev else GENESIS}
    e["hash"] = entry_hash(e)
    return e


def _ends_without_newline(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open("rb") as f:
        f.seek(-1, 2)
        return f.read(1) != b"\n"


def append(book: dict, version: str, path: Path | None = None, ts: str | None = None, source: str = "snapshot") -> dict:
    """Append one entry if the data date is new. Never rewrites the file: opens it in append mode only. Refuses if
    the existing chain does not verify. A file whose last line has no newline (an editor, a merge) gets one first,
    so the new entry never lands on the end of the old one."""
    path = Path(path) if path else PATH
    v = verify(path)
    if not v["ok"]:
        raise RuntimeError("the ledger does not verify; refusing to append: " + "; ".join(v["problems"][:3]))
    rows = read(path)
    last = rows[-1] if rows else None
    if last and last["data_asof"] >= book["asof"]:
        return {"appended": False, "reason": f"already logged data through {last['data_asof']}", "entry": last}
    e = make_entry(book, version, last, ts, source)
    path.parent.mkdir(parents=True, exist_ok=True)
    lead = "\n" if _ends_without_newline(path) else ""
    with path.open("a") as f:
        f.write(lead + _canon(e) + "\n")
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
            g = governs_from(e)
            print(f"{e['seq']:4d} {e['ts_utc']} data {e['data_asof']} from {g}" + ("*" if g != e["effective_from"] else " ")
                  + f" size {c['size']:.2f} ({c['binding']})  {e['hash'][:12]}")
        if any(governs_from(e) != e["effective_from"] for e in read()):
            print("   * governs one session later than the date stored: written after the close that begins the stored day")
        return 0
    print("usage: ledger append [--book book.json] | verify | show")
    return 2
