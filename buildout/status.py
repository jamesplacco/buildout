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

FRESH_WEEKDAYS = 3          # data older than this many weekdays is flagged stale
QUARTER_LAG_DAYS = 140      # one quarter (92 days) plus the 10-Q filing window and a margin


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


def _get(obj, path: str):
    for k in path.split("."):
        if not isinstance(obj, dict) or k not in obj:
            return None
        obj = obj[k]
    return obj


def build_status(out_dir: str | Path, now: datetime | None = None) -> dict:
    out, now = Path(out_dir), now or datetime.now(timezone.utc)
    files, checks = {}, []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

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
                       "bytes": p.stat().st_size, "weekdays_old": weekdays_since(as_of, now)}
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
        age = files["macro.json"]["weekdays_old"]
        check(f"FRED data is at most {FRESH_WEEKDAYS} weekdays old", age is not None and age <= FRESH_WEEKDAYS,
              f"as of {lat.get('as_of')}, {age} weekdays")
        failed = macro.get("failed_series") or {}
        check("Every FRED series downloaded", not failed, ", ".join(sorted(failed)) if failed else "")
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
        age = files["report.json"]["weekdays_old"]
        check(f"Book data is at most {FRESH_WEEKDAYS} weekdays old", age is not None and age <= FRESH_WEEKDAYS,
              f"as of {s.get('as_of')}, {age} weekdays")

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
            check("Capex to cash flow ratios are plausible", not bad, ", ".join(bad))

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
            check("Research data ends within the last 120 days", days <= 120, f"ends {end}, {days} days ago")

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
        check("Feed scraper read at least half its sources", n_ok >= n_bad, f"{n_ok} read, {n_bad} failed or skipped")
        check("Feed items are links, not markup", all(str(it.get("url", "")).startswith(("https://", "http://", "")) and "<" not in str(it.get("title", ""))
                                                    for it in feeds.get("items") or []))

    return {
        "generated_utc": now.isoformat(timespec="seconds"),
        "commit": (os.environ.get("GITHUB_SHA") or "")[:7] or None,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "python": platform.python_version(),
        "files": files,
        "checks": checks,
        "ok": all(c["ok"] for c in checks) if checks else False,
    }
