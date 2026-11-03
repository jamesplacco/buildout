"""Validation of every price pull before it becomes a return: it reports, it never edits a price.

Fatal (the result's "ok" is False):
  duplicate_dates      the same date twice
  non_monotonic        a date earlier than the one before it
  nonpositive_close    a close that is zero, negative or missing
  stale                the last date is more than `stale_bdays` US business days before `asof`
  empty / missing_columns   no rows, or no close column at all

Warnings (kind prefixed "warn_", "ok" stays True):
  warn_gap             more than `max_gap_bdays` US business days between two consecutive dates
  warn_ohlc            high below low, or the close outside [low, high]
  warn_jump            |close / previous close - 1| above `jump` on a day with no split recorded; the ratio is named
                       (2:1, 3:1, 4:1, 10:1, 1:10 reverse) when it matches a standard split, which is the signature of
                       an unadjusted split the vendor did not record

Information (kind prefixed "info_"): every split recorded in the split column, named, and whether the close moved by
the ratio that day (the series is unadjusted there) or not (the series is split-adjusted).

Business days are US weekdays less the NYSE's full-day holidays (an approximation from the standard rules; a gap of
a day or two from a one-off closure never reaches the default five-day threshold).

    python -m buildout.data.validate --pickle PATH [--asof YYYY-MM-DD] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay, USMartinLutherKingJr,
                                    USMemorialDay, USPresidentsDay, USThanksgivingDay, nearest_workday,
                                    sunday_to_monday)

FATAL = {"empty", "missing_columns", "duplicate_dates", "non_monotonic", "nonpositive_close", "stale", "yield_range"}
N_DATES = 5                                     # dates listed per issue
OHLC_TOL = 1e-6                                 # relative slack for prices rounded to the cent


class _NYSE(AbstractHolidayCalendar):
    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-06-19", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


@lru_cache(maxsize=1)
def _holidays() -> np.ndarray:
    return np.array(_NYSE().holidays("1970-01-01", "2040-12-31").values.astype("datetime64[D]"))


def bdays_between(a, b) -> int:
    """US business days after `a` up to and including `b` (1 for consecutive sessions, 0 for the same day)."""
    one = np.timedelta64(1, "D")
    a64, b64 = np.datetime64(pd.Timestamp(a).date(), "D"), np.datetime64(pd.Timestamp(b).date(), "D")
    return int(np.busday_count(a64 + one, b64 + one, holidays=_holidays()))


def _ds(d) -> str:
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def _issue(kind: str, detail: str, dates=(), **extra) -> dict:
    ds = [_ds(d) for d in dates]
    out = {"kind": kind, "detail": detail, "dates": ds[:N_DATES], "count": len(ds)}
    out.update(extra)
    return out


def _result(name: str, rows: int, first, last, issues: list[dict]) -> dict:
    return {"name": name, "ok": not any(i["kind"] in FATAL for i in issues), "rows": int(rows),
            "first": _ds(first) if first is not None else None, "last": _ds(last) if last is not None else None,
            "issues": issues}


def split_name(factor: float) -> str:
    """'4:1' for a factor of 4 (four new shares for one), '3:2' for 1.5, '1:10' for a 0.1 reverse split."""
    f = float(factor)
    if not math.isfinite(f) or f <= 0:
        return f"{factor}"
    k, reverse = (1 / f, True) if f < 1 else (f, False)
    if abs(k - round(k)) < 1e-6 * k:
        s = f"{int(round(k))}:1"
    elif abs(2 * k - round(2 * k)) < 1e-6 * k:
        s = f"{int(round(2 * k))}:2"
    else:
        s = f"{k:.4g}:1"
    if reverse:
        a, b = s.split(":")
        s = f"{b}:{a}"
    return s


FORWARD = [1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 30, 40, 50, 100]
REVERSE = [2, 3, 4, 5, 8, 10, 15, 20, 25, 30, 40, 50, 100]      # reverse splits are whole numbers: 1:10, never 2:3


def match_split(ratio: float, tol: float = 0.06) -> str | None:
    """The standard split a close-to-close ratio (close / previous close) looks like, or None. A 4:1 split moves the
    close to a quarter (ratio 0.25); a 1:10 reverse split moves it to ten times (ratio 10). The tolerance leaves room
    for the day's own move on top of the split."""
    if not math.isfinite(ratio) or ratio <= 0:
        return None
    k = 1 / ratio if ratio < 1 else ratio
    for c in (FORWARD if ratio < 1 else REVERSE):
        if abs(k / c - 1) < tol:
            return split_name(c if ratio < 1 else 1 / c)
    return None


def _frame(df: pd.DataFrame) -> pd.DataFrame:
    """A copy with the date as a tz-naive datetime column named 'date' and positional index, in the order given."""
    d = df.copy()
    if "date" not in d.columns:
        d = d.rename_axis("date").reset_index() if d.index.name in (None, "date") else d.reset_index().rename(columns={d.index.name: "date"})
    d["date"] = pd.to_datetime(d["date"])
    if getattr(d["date"].dt, "tz", None) is not None:
        d["date"] = d["date"].dt.tz_localize(None)
    return d.reset_index(drop=True)


def validate_prices(df: pd.DataFrame, name: str, *, max_gap_bdays: int = 5, jump: float = 0.40, asof=None,
                    stale_bdays: int = 5) -> dict:
    """Every check on one symbol's daily bars. See the module docstring for the kinds and which ones fail."""
    if df is None or len(df) == 0:
        return _result(name, 0, None, None, [_issue("empty", "no rows")])
    d = _frame(df)
    issues: list[dict] = []
    if "close" not in d.columns:
        return _result(name, len(d), d["date"].min(), d["date"].max(), [_issue("missing_columns", "no close column")])
    lacking = [c for c in ("open", "high", "low", "volume") if c not in d.columns]
    if lacking:
        issues.append(_issue("warn_columns", "missing " + ", ".join(lacking)))

    dates = d["date"]
    dup = dates[dates.duplicated(keep="first")]
    if len(dup):
        issues.append(_issue("duplicate_dates", f"{len(dup)} rows repeat an earlier date", sorted(dup.unique())))
    back = dates[dates < dates.cummax().shift(1)]
    if len(back):
        issues.append(_issue("non_monotonic", f"{len(back)} dates come before a date above them", list(back)))

    close = pd.to_numeric(d["close"], errors="coerce")
    miss, nonpos = d.loc[close.isna(), "date"], d.loc[close <= 0, "date"]
    if len(miss) or len(nonpos):
        issues.append(_issue("nonpositive_close", f"{len(nonpos)} non-positive and {len(miss)} missing closes",
                             sorted(list(miss) + list(nonpos))))

    # the remaining checks run on the series in date order, one row a date (the last one kept), valid closes only
    s = d.assign(close=close).sort_values("date", kind="stable").drop_duplicates("date", keep="last")
    s = s[s["close"] > 0].reset_index(drop=True)

    if "high" in s.columns and "low" in s.columns:
        hi, lo = pd.to_numeric(s["high"], errors="coerce"), pd.to_numeric(s["low"], errors="coerce")
        tol = OHLC_TOL * s["close"]
        inv = (hi < lo - tol) & hi.notna() & lo.notna()
        out = ((s["close"] > hi + tol) | (s["close"] < lo - tol)) & hi.notna() & lo.notna()
        if inv.any() or out.any():
            issues.append(_issue("warn_ohlc", f"{int(inv.sum())} bars with high below low, {int(out.sum())} with the close outside [low, high]",
                                 list(s.loc[inv | out, "date"])))

    if len(s) >= 2:
        prev = s["date"].shift(1)
        gaps = [(p, c, bdays_between(p, c)) for p, c in zip(prev.iloc[1:], s["date"].iloc[1:])]
        long = [(p, c, n) for p, c, n in gaps if n > max_gap_bdays]
        if long:
            worst = max(long, key=lambda g: g[2])
            issues.append(_issue("warn_gap", f"{len(long)} gaps above {max_gap_bdays} business days; the longest {worst[2]} "
                                 f"({_ds(worst[0])} to {_ds(worst[1])})", [c for _, c, _ in long],
                                 gaps=[{"from": _ds(p), "to": _ds(c), "bdays": n} for p, c, n in long[:N_DATES]]))

        split = pd.to_numeric(s["split"], errors="coerce") if "split" in s.columns else pd.Series(np.nan, index=s.index)
        recorded = split.notna() & (split > 0) & ((split - 1).abs() > 1e-9)
        ratio = s["close"] / s["close"].shift(1)
        big = ((ratio - 1).abs() > jump) & ~recorded & ratio.notna()
        if big.any():
            ev = [{"date": _ds(s.at[i, "date"]), "change": float(ratio[i] - 1), "ratio": float(ratio[i]),
                   "looks_like": match_split(float(ratio[i]))} for i in s.index[big]]
            named = [f"{e['date']} {e['change']:+.0%}" + (f" (a {e['looks_like']} split?)" if e["looks_like"] else "") for e in ev]
            issues.append(_issue("warn_jump", f"{len(ev)} moves above {jump:.0%} with no split recorded: " + "; ".join(named[:N_DATES]),
                                 [e["date"] for e in ev], events=ev[:N_DATES]))
        if recorded.any():
            ev = []
            for i in s.index[recorded]:
                f, r = float(split[i]), float(ratio[i]) if pd.notna(ratio[i]) else float("nan")
                adjusted = not (math.isfinite(r) and abs(r * f - 1) < 0.15)
                ev.append({"date": _ds(s.at[i, "date"]), "factor": f, "split": split_name(f),
                           "change": r - 1 if math.isfinite(r) else None, "adjusted": adjusted})
            text = "; ".join(f"{e['split']} on {e['date']} ({'adjusted' if e['adjusted'] else 'unadjusted, the close moved by the ratio'})" for e in ev)
            issues.append(_issue("info_split", f"{len(ev)} splits recorded: {text}", [e["date"] for e in ev], events=ev))

    first, last = (s["date"].iloc[0], s["date"].iloc[-1]) if len(s) else (dates.min(), dates.max())
    if asof is not None and last is not None:
        n = bdays_between(last, asof)
        if n > stale_bdays:
            issues.append(_issue("stale", f"last date {_ds(last)} is {n} business days before {_ds(asof)} (limit {stale_bdays})", [last]))
    return _result(name, len(d), first, last, issues)


def validate_curve(series: dict, name: str = "treasury_curve", *, max_gap_bdays: int = 5, asof=None,
                   stale_bdays: int = 5, lo: float = -1.0, hi: float = 25.0) -> dict:
    """A Treasury par curve keyed by tenor, each {date string: yield in percent}. Yields must lie strictly inside
    (lo, hi); missing values (FRED's '.') are counted as a warning; gaps and staleness are checked per tenor."""
    issues: list[dict] = []
    firsts, lasts, rows = [], [], 0
    if not series:
        return _result(name, 0, None, None, [_issue("empty", "no tenors")])
    for tenor, obs in series.items():
        items = list(obs.items()) if hasattr(obs, "items") else list(obs)
        if not items:
            issues.append(_issue("empty", f"{tenor}: no observations"))
            continue
        idx = pd.to_datetime([k for k, _ in items])
        v = pd.Series(pd.to_numeric(pd.Series([x for _, x in items], dtype="object"), errors="coerce").to_numpy(float), index=idx).sort_index()
        rows += len(v)
        nan = v[v.isna()]
        if len(nan):
            issues.append(_issue("warn_missing", f"{tenor}: {len(nan)} missing values", list(nan.index)))
        v = v.dropna()
        if v.empty:
            issues.append(_issue("empty", f"{tenor}: every value is missing"))
            continue
        bad = v[(v <= lo) | (v >= hi)]
        if len(bad):
            issues.append(_issue("yield_range", f"{tenor}: {len(bad)} yields outside ({lo:g}, {hi:g}) percent, e.g. {float(bad.iloc[0]):g}",
                                 list(bad.index)))
        d = v.index
        long = [(d[i - 1], d[i], n) for i in range(1, len(d)) if (n := bdays_between(d[i - 1], d[i])) > max_gap_bdays]
        if long:
            worst = max(long, key=lambda g: g[2])
            issues.append(_issue("warn_gap", f"{tenor}: {len(long)} gaps above {max_gap_bdays} business days; the longest {worst[2]} "
                                 f"({_ds(worst[0])} to {_ds(worst[1])})", [c for _, c, _ in long]))
        if asof is not None:
            n = bdays_between(d[-1], asof)
            if n > stale_bdays:
                issues.append(_issue("stale", f"{tenor}: last date {_ds(d[-1])} is {n} business days before {_ds(asof)} (limit {stale_bdays})", [d[-1]]))
        firsts.append(d[0])
        lasts.append(d[-1])
    return _result(name, rows, min(firsts) if firsts else None, max(lasts) if lasts else None, issues)


def n_warnings(result: dict) -> int:
    return sum(1 for i in result["issues"] if i["kind"].startswith("warn_"))


def validate_all(frames: dict, asof=None, **kw) -> dict:
    """validate_prices on every frame, and a summary: which failed and how many warnings in all."""
    results = [validate_prices(df, str(k), asof=asof, **kw) for k, df in frames.items()]
    failed = [r["name"] for r in results if not r["ok"]]
    return {"ok": not failed, "n": len(results), "failed": failed, "warnings": sum(n_warnings(r) for r in results),
            "asof": _ds(asof) if asof is not None else None, "results": results}


def line(r: dict) -> str:
    """One line a symbol: status, span, then the fatal issues, the warnings and the splits recorded."""
    head = f"{'OK  ' if r['ok'] else 'FAIL'} {r['name']:<10} {r['rows']:>6} rows {r['first']} to {r['last']}"
    fatal = [i["detail"] for i in r["issues"] if i["kind"] in FATAL]
    warn = [i["kind"][5:] + ": " + i["detail"] for i in r["issues"] if i["kind"].startswith("warn_")]
    splits = [e["split"] + " " + e["date"] for i in r["issues"] if i["kind"] == "info_split" for e in i.get("events", [])]
    parts = ([("failed: " + "; ".join(fatal))] if fatal else []) + warn + ([("splits " + ", ".join(splits))] if splits else [])
    return head + ("  |  " + "  |  ".join(parts) if parts else "")


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (pd.Timestamp, date)):
        return _ds(o)
    raise TypeError(type(o).__name__)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m buildout.data.validate", description="Validate every price frame in a pickle.")
    p.add_argument("--pickle", required=True, help='a pickled dict whose "prices" maps a name to a DataFrame')
    p.add_argument("--asof", default=None, help="YYYY-MM-DD; data whose last date is too far before it fails as stale")
    p.add_argument("--json", default=None, help="write the full results here")
    p.add_argument("--max-gap-bdays", type=int, default=5)
    p.add_argument("--jump", type=float, default=0.40)
    p.add_argument("--stale-bdays", type=int, default=5)
    a = p.parse_args(argv)
    with open(a.pickle, "rb") as fh:          # a pickle runs code on load: only pass files this engine wrote
        data = pickle.load(fh)
    frames = data.get("prices") if isinstance(data, dict) else None
    if not isinstance(frames, dict):
        print(f"::error::{a.pickle} has no 'prices' dict", file=sys.stderr)
        return 1
    asof = pd.Timestamp(a.asof) if a.asof else None
    summary = validate_all(frames, asof=asof, max_gap_bdays=a.max_gap_bdays, jump=a.jump, stale_bdays=a.stale_bdays)
    for r in summary["results"]:
        print(line(r))
    print(f"{summary['n']} frames, {len(summary['failed'])} failed" + (f" ({', '.join(summary['failed'])})" if summary["failed"] else "")
          + f", {summary['warnings']} warnings")
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(summary, indent=1, default=_default))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
