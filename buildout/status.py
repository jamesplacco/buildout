"""Run status for the page: which outputs exist, how fresh each one is, and the sanity checks it passed.

Written last by the daily run (even when an earlier step failed), so the page can say "the data is
three days old" or "the book run did not finish" instead of silently showing stale numbers.
"""
from __future__ import annotations

import json
import os
import platform
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

FRESH_WEEKDAYS = 3          # the page's own rule (weekdaysSince): kept for the weekdays_old it shows
QUARTER_LAG_DAYS = 140      # one quarter (92 days) plus the 10-Q filing window and a margin
# v0.47: freshness is counted in New York Stock Exchange sessions (buildout/sessions.py), against the session before
# today in New York: the newest close a run on any hour of that day can have. Before, it was weekdays, so a holiday
# counted as a day of staleness, and three weekdays of slack let a book two sessions old pass.
PRICE_SESSIONS_BEHIND = 0   # the book's prices (Databento, the mirror): the last completed session, exactly
RECORD_SESSIONS_BEHIND = 1  # the calls marked to market and the paper account: built from those prices
FRED_SESSIONS_BEHIND = 2    # FRED publishes Treasury yields a day late (one session behind), and a bond-market holiday
                            # the stock exchange does not keep (Columbus Day, Veterans Day) adds one more
WARN, FAIL = "warn", "fail"
# The writer rounds every number to six decimals (jsonout.clean), so seven probabilities that sum to one can be read
# back summing to 0.999999 or 1.000001. The old tolerance of 1e-6 sat on that rounding and failed about half the time.
POSTERIOR_TOL = 1e-4


def weekdays_since(as_of: str | None, now: datetime) -> int | None:
    """Weekdays strictly after `as_of` up to and including today (matches weekdaysSince in the page)."""
    if not as_of:
        return None
    s = str(as_of)[:10]
    try:
        if len(s) == 7:                       # a month ("2026-09"): monthly data runs to the month's last day
            y, m = int(s[:4]), int(s[5:7])
            d = date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1)
        else:
            d = date.fromisoformat(s)
    except ValueError:
        return None
    one = np.timedelta64(1, "D")
    return int(np.busday_count(np.datetime64(d, "D") + one, np.datetime64(now.date(), "D") + one))


def sessions_behind(as_of: str | None, now: datetime) -> int | None:
    """Exchange sessions between `as_of` and the session before today in New York: 0 when the data is from the last
    completed session (or newer), 1 when it misses one, and so on. None for a month ("2026-09") or no date."""
    if not as_of or len(str(as_of)[:10]) < 10:
        return None
    try:
        d = date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return None
    from . import sessions
    aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return sessions.sessions_between(d, sessions.prev_session(aware.astimezone(sessions.NY).date()))


def _get(obj, path: str):
    for k in path.split("."):
        if not isinstance(obj, dict) or k not in obj:
            return None
        obj = obj[k]
    return obj


def _ledger_tail(path: Path) -> tuple[dict | None, int, str | None]:
    """The ledger's newest entry, its number of entries, and a problem if the file cannot be read. Read here as plain
    JSON lines (ledger.verify, run by the workflow step before this one, is the check of the chain itself)."""
    try:
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        return (json.loads(lines[-1]) if lines else None), len(lines), None
    except (OSError, ValueError) as exc:
        return None, 0, f"{type(exc).__name__}: {exc}"[:160]


def build_status(out_dir: str | Path, now: datetime | None = None, ledger_path: str | Path | None = None) -> dict:
    out, now = Path(out_dir), now or datetime.now(timezone.utc)
    if ledger_path is None:                     # the repository's ledger, when the folder checked is the repository's
        root = Path(__file__).resolve().parents[1]
        cand = root / "ledger" / "calls.jsonl"
        ledger_path = cand if cand.exists() and root in out.resolve().parents else None
    files, checks = {}, []

    def check(name: str, ok: bool, detail: str = "", level: str = FAIL) -> None:
        # level "fail": the daily run goes red and the issue is opened. level "warn": reported, the run stays green.
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "level": level})

    def fresh(name: str, what: str, limit: int, as_of) -> None:
        n = files[name].get("sessions_behind")
        if limit == 0:
            label = f"{what} from the last completed session"
        else:
            label = f"{what} at most {limit} session{'s' if limit != 1 else ''} behind the last completed one"
        check(label, n is not None and n <= limit, f"as of {as_of}, {n} session{'s' if n != 1 else ''} behind")

    def load(name: str, as_of_path: str | None):
        p = out / name
        if not p.exists():
            files[name] = {"present": False}
            return None
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError) as exc:
            files[name] = {"present": True, "valid": False, "error": str(exc)[:160]}
            check(f"{name} is valid JSON", False, str(exc)[:120])
            return None
        as_of = _get(data, as_of_path) if as_of_path else None
        files[name] = {"present": True, "valid": True, "schema": data.get("schema"), "as_of": as_of,
                       "bytes": p.stat().st_size, "weekdays_old": weekdays_since(as_of, now), "sessions_behind": sessions_behind(as_of, now),
                       "written_utc": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
        return data

    macro = load("macro.json", "latest.as_of")
    if macro is not None:
        lat = macro.get("latest", {})
        c63, c252 = lat.get("corr63"), lat.get("corr252")
        check("Correlations are within -1 and 1", all(isinstance(c, (int, float)) and -1 <= c <= 1 for c in (c63, c252)),
              f"{c63}, {c252}")
        hr = [lat.get("hedge_ratio_gated"), lat.get("hedge_ratio_minvar")]
        check("Hedge ratios are within 0 and 1", all(isinstance(h, (int, float)) and 0 <= h <= 1 for h in hr), f"{hr}")
        pts = _get(macro, "rates.curves.latest.points") or []
        check("Treasury curve has at least 8 tenors", len(pts) >= 8, f"{len(pts)} tenors")
        ys = [p.get("yield") for p in pts]
        check("Yields are plausible (-1% to 25%)", bool(ys) and all(isinstance(y, (int, float)) and -1 < y < 25 for y in ys))
        fresh("macro.json", "FRED data is", FRED_SESSIONS_BEHIND, lat.get("as_of"))
        failed = macro.get("failed_series") or {}
        check("Every FRED series downloaded", not failed, ", ".join(sorted(failed)) if failed else "", WARN)
        stand_ins = macro.get("fallbacks") or {}
        if stand_ins:                           # v0.47: a series FRED refused, taken from its stand-in, is said here
            check("Every FRED series came from FRED", False, "; ".join(f"{k}: {v}" for k, v in sorted(stand_ins.items()))[:300], WARN)
        check("Episode atlas computed", len(macro.get("episodes") or []) >= 10, f"{len(macro.get('episodes') or [])} episodes")
        # unit checks: a units mix-up (millions read as billions) shows up as an impossible number
        nv = _get(macro, "vol.latest.ndx.implied")
        if nv is not None:
            check("Nasdaq-100 implied volatility is plausible (1 to 150 points)", isinstance(nv, (int, float)) and 1 <= nv <= 150, f"{nv}")
        nl = _get(macro, "liquidity.latest.net.value")
        if nl is not None:
            check("Net liquidity is plausible ($1T to $15T)", isinstance(nl, (int, float)) and 1 <= nl <= 15, f"{nl}")
        gap = _get(macro, "liquidity.latest.funding.gap_bp")
        if gap is not None:
            check("SOFR minus IORB is within 100bp", isinstance(gap, (int, float)) and abs(gap) <= 100, f"{gap}")

    report = load("report.json", "summary.as_of")
    if report is not None:
        s = report.get("summary", {})
        check("Book run used market data, not the synthetic test market", s.get("data") not in (None, "synthetic"), str(s.get("data")))
        g, cap = s.get("recommended_gross"), _get(s, "limits.max_gross") or 3.0
        check("Recommended gross is within the gross limit", isinstance(g, (int, float)) and 0 <= g <= cap + 1e-9, f"{g} vs {cap}")
        v = s.get("var99_fhs")
        check("One-day VaR is positive and below 50%", isinstance(v, (int, float)) and 0 < v < 0.5, f"{v}")
        dq = report.get("data_quality") or {}
        if isinstance(dq.get("symbols"), dict):
            bad = [k for k, v in dq["symbols"].items() if isinstance(v, dict) and not v.get("ok", True)]
            check("No bad prints, frozen prices or gaps in the book's prices", not bad, ", ".join(bad), WARN)
            unconf = {k: v["unconfirmed"] for k, v in dq["symbols"].items() if isinstance(v, dict) and isinstance(v.get("unconfirmed"), dict)}
            if "unconfirmed" in dq:             # v0.47: a spike-sized move on the newest day cannot be confirmed or refuted until tomorrow
                check("No spike-sized move on the newest day is waiting to be confirmed", not unconf,
                      "; ".join(f"{k} {v.get('change', 0):+.1%} on {v.get('date')}" for k, v in sorted(unconf.items())), WARN)
        adj = s.get("adjustments") if isinstance(s.get("adjustments"), dict) else {}
        dropped = (adj.get("cleaning") or {}).get("final_bar_dropped") if isinstance(adj.get("cleaning"), dict) else None
        if isinstance(adj.get("cleaning"), dict) and "final_bar_dropped" in adj["cleaning"]:
            check("The newest bar the vendor sent was a full session", not dropped, (dropped or {}).get("note", "") if isinstance(dropped, dict) else str(dropped or ""), WARN)
        if adj.get("rates_fallbacks") or adj.get("rates_error"):
            check("The book run's rates came from FRED", False, str(adj.get("rates_error") or adj.get("rates_fallbacks"))[:300], WARN)
        fresh("report.json", "Book data is", PRICE_SESSIONS_BEHIND, s.get("as_of"))

    capex = load("capex.json", None)
    if capex is not None:
        cos = capex.get("companies") or {}
        check("SEC fundamentals cover at least one company", len(cos) > 0, f"{len(cos)} companies")
        last = [rows[-1].get("quarter_end") for rows in cos.values() if rows and isinstance(rows[-1], dict)]
        last = [q for q in last if isinstance(q, str) and len(q) >= 10]
        files["capex.json"]["cadence"] = "quarterly"
        if last:
            newest = max(last)
            files["capex.json"]["as_of"] = newest
            # a 10-Q lands up to 40 days after the quarter ends (45 for smaller filers), so the newest
            # quarter should never be more than one quarter plus that lag behind today
            days = (now.date() - date.fromisoformat(newest[:10])).days
            check(f"SEC filings include a quarter ended in the last {QUARTER_LAG_DAYS} days", days <= QUARTER_LAG_DAYS,
                  f"latest quarter ended {newest}, {days} days ago")

        ttm = capex.get("ttm") or {}
        if ttm:
            bad = [t for t, m in ttm.items() if isinstance(m, dict) and isinstance(m.get("capex_to_ocf"), (int, float))
                   and not (-5 < m["capex_to_ocf"] < 20)]
            check("Capex to cash flow ratios are plausible", not bad, ", ".join(bad), WARN)

    research = load("research.json", "panel.end")
    if research is not None:
        rows = _get(research, "hedge.rows") or []
        check("Long-history research covers at least 1,500 months", (_get(research, "panel.months") or 0) >= 1500,
              f"{_get(research, 'panel.months')} months")
        check("Hedge-line table has every inflation bucket", len(rows) >= 5, f"{len(rows)} buckets")
        files["research.json"]["cadence"] = "monthly"
        end = _get(research, "panel.end")
        if isinstance(end, str) and len(end) >= 7:
            days = (now.date() - date.fromisoformat(end[:7] + "-01")).days
            check("Research data ends within the last 120 days", days <= 120, f"ends {end}, {days} days ago", WARN)

    brain = load("brain.json", None)
    if brain is not None:
        regs = brain.get("regimes") or {}
        ws = [e.get("w") for r in regs.values() for e in (r.get("edges") or {}).values()]
        check("Brain weights are finite and below 1.5 in size", bool(ws) and all(isinstance(w, (int, float)) and abs(w) < 1.5 for w in ws),
              f"{len(ws)} edges in {len(regs)} regimes")
        files["brain.json"]["cadence"] = "monthly"

    buy = load("buyside.json", "latest.month")
    if buy is not None:
        files["buyside.json"]["cadence"] = "monthly"
        t = buy.get("tail") or {}
        check("Fat-tail shortfall: Student-t at least the normal", isinstance(t.get("student_t"), (int, float)) and isinstance(t.get("normal"), (int, float))
              and t["student_t"] >= t["normal"], f"{t.get('student_t')} vs {t.get('normal')}")

    feeds = load("feeds.json", "generated_utc")
    if feeds is not None:
        src = feeds.get("sources") or {}
        n_ok, n_bad = len(src.get("ok") or []), len(src.get("failed") or [])
        check("Feed scraper read at least half its sources", n_ok >= n_bad, f"{n_ok} read, {n_bad} failed or skipped", WARN)
        check("Feed items are links, not markup", all(str(it.get("url", "")).startswith(("https://", "http://", "")) and "<" not in str(it.get("title", ""))
                                                    for it in feeds.get("items") or []))

    reason = load("reason.json", None)
    if reason is not None:
        post = (reason.get("posterior") or {}).get("posterior") or []
        check("Reasoner posterior is a probability distribution", bool(post) and all(isinstance(p, (int, float)) and 0 <= p <= 1 for p in post)
              and abs(sum(post) - 1) < POSTERIOR_TOL, f"{len(post)} scenarios, sum {sum(post) if all(isinstance(p, (int, float)) for p in post) else 'n/a'}")
        opt = (reason.get("alternatives") or {}).get("optimal") or {}
        check("Reasoner's optimal portfolio respects the loss limit", opt.get("feasible") is True, str(opt.get("port")))
    # ---- v0.47: the call itself. Before, nothing here looked at book.json, the ledger, the marked record, the paper
    # account or the decision package: the files the front page is made of could be missing or a week old and every
    # check above would still pass.
    book = load("book.json", "asof")
    if book is not None:
        fresh("book.json", "The call's prices are", PRICE_SESSIONS_BEHIND, book.get("asof"))
        sz = book.get("size")
        check("The call's size is a number within the gross limit", isinstance(sz, (int, float)) and 0 <= sz <= 3.0 and bool(book.get("binding")), f"{sz} ({book.get('binding')})")
        val = book.get("validation")
        if isinstance(val, dict):               # written by book.download from v0.47
            check("The call's prices passed validation", val.get("ok") is True, ", ".join(val.get("failed") or []))
            notes = [str(w) for w in (val.get("notes") or [])]
            check("Price validation raised no warnings", not notes, "; ".join(notes)[:400], WARN)
            cc = val.get("cross_check") if isinstance(val.get("cross_check"), dict) else {}
            st = cc.get("status")
            check("A second source agrees with the call's newest closes", st == "ok",
                  f"{st}: {cc.get('detail', '')}"[:300], FAIL if st == "disagrees" else WARN)
        if ledger_path is not None:
            last, n, problem = _ledger_tail(Path(ledger_path))
            if problem or last is None:
                check("The call ledger can be read", False, problem or "no entries")
            else:
                check("The ledger's newest call is for the book's data date", last.get("data_asof") == book.get("asof"),
                      f"ledger {last.get('data_asof')} (entry {last.get('seq')}), book {book.get('asof')}")
                c = last.get("call") or {}
                same = isinstance(sz, (int, float)) and isinstance(c.get("size"), (int, float)) and abs(c["size"] - round(float(sz), 4)) < 5e-4 and c.get("binding") == book.get("binding")
                if last.get("data_asof") == book.get("asof"):      # a rerun of a logged date on changed code or data: reported, the logged call stands
                    check("The logged call matches the book as computed now", same, f"logged {c.get('size')} ({c.get('binding')}), book {sz} ({book.get('binding')})", WARN)
    live = load("live.json", "last_mark")
    if live is not None:
        fresh("live.json", "The calls marked to market are", RECORD_SESSIONS_BEHIND, live.get("last_mark"))
        if ledger_path is not None:
            last, n, problem = _ledger_tail(Path(ledger_path))
            led = live.get("ledger") or {}
            check("The marked record was built from the current ledger", not problem and led.get("ok") is True and led.get("entries") == n
                  and (last is None or led.get("head") == last.get("hash")), f"live.json: {led.get('entries')} entries; ledger: {n}")
    paper = load("paper.json", "marks_asof")
    if paper is not None:
        fresh("paper.json", "The paper account's marks are", RECORD_SESSIONS_BEHIND, paper.get("marks_asof"))
        eq = paper.get("equity")
        check("The paper account's equity is a positive number", isinstance(eq, (int, float)) and eq > 0, f"{eq}")
    track = load("track.json", "asof")         # v0.47: the walk-forward record, rebuilt by the daily run
    if track is not None:
        fresh("track.json", "The walk-forward record is", RECORD_SESSIONS_BEHIND, track.get("asof"))
        mem = track.get("members") if isinstance(track.get("members"), dict) else {}
        newest = mem.get(max(mem)) if mem else None
        call = (((track.get("pit") or {}).get("policies") or {}).get("call") or {}).get("net") or {}
        check("The walk-forward record ranks nine names and carries the call's row", isinstance(newest, list) and len(newest) == 9
              and isinstance(call.get("sharpe"), (int, float)), f"{len(newest) if isinstance(newest, list) else 'no'} names; Sharpe {call.get('sharpe')}")
    dec = load("decision.json", "end")
    if dec is not None:
        files["decision.json"]["cadence"] = "monthly"
        end = dec.get("end")
        n_now = dec.get("now") if isinstance(dec.get("now"), dict) else {}
        check("The decision package carries a decision", isinstance(n_now.get("exposure"), (int, float)) and 0 <= n_now["exposure"] <= 3.0, f"{n_now.get('exposure')}")
        if isinstance(end, str) and len(end) >= 7:
            try:
                days = (now.date() - date.fromisoformat(end[:7] + "-01")).days
                check("Decision engine data ends within the last 120 days", days <= 120, f"ends {end}, {days} days ago", WARN)
            except ValueError:
                check("Decision engine data ends within the last 120 days", False, f"ends {end!r}", WARN)
        y10 = _get(dec, "now.inputs.notes.y10")
        if isinstance(y10, dict) and "assumed" in y10:
            check("The decision engine read today's 10-year yield", y10.get("assumed") is False, str(y10.get("source")), WARN)
    tech = load("technicals.json", "as_of")
    if tech is not None and "fallback" in tech:           # written by datahub.market from v0.47
        names = tech.get("fallback_names") or []
        check("Technical analysis used the configured price source", not tech.get("fallback"),
              (f"configured {tech.get('configured_source')}; from another source: {', '.join(names)}" + (f"; {tech.get('batch_error')}" if tech.get("batch_error") else ""))[:400] if names else "")
        check("Every name has price data for technical analysis", not tech.get("missing"), ", ".join(tech.get("missing") or []))
    # files written on different days must not silently form one decision: flag the spread of their dates
    stamps = sorted(v["written_utc"][:10] for v in files.values() if v.get("written_utc"))
    if stamps:
        check("Every file comes from the same run day", stamps[0] == stamps[-1], f"{stamps[0]} to {stamps[-1]}")
    # v0.44.1: in CI every file carries the checkout's time, so the dates above always agree. A file this run did not
    # rewrite still has that time; the checkout's time is read from a file no step writes.
    if os.environ.get("GITHUB_ACTIONS"):
        root = Path(__file__).resolve().parents[1]
        refs = [root / n for n in ("pyproject.toml", "README.md", "site/page.html", "site/core.html", "site/src/body.html")]
        refs = [r for r in refs if r.exists()]          # a checkout takes seconds: the latest of several files no step writes
        if refs:
            t0 = max(r.stat().st_mtime for r in refs) + 1.0
            stale = sorted(n for n, v in files.items() if v.get("present") and (out / n).exists() and (out / n).stat().st_mtime <= t0)
            check("Every file was rewritten by this run", not stale, ", ".join(stale) + " kept from an earlier run" if stale else "")

    return {
        "generated_utc": now.isoformat(timespec="seconds"),
        "commit": (os.environ.get("GITHUB_SHA") or "")[:7] or None,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "python": platform.python_version(),
        "files": files,
        "checks": checks,
        # ok: every check that can fail the run passed. Warnings are counted beside it, never hidden inside it.
        "ok": all(c["ok"] for c in checks if c["level"] == FAIL) if checks else False,
        "failed": sum(1 for c in checks if not c["ok"] and c["level"] == FAIL),
        "warnings": sum(1 for c in checks if not c["ok"] and c["level"] == WARN),
    }
