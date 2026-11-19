"""A screen on prices before they become returns. It flags; it never edits a price.

  spikes      a one-day move above `k` robust standard deviations (1.4826 x MAD of the symbol's returns) that
              mostly reverses the next day: the signature of a bad print, not of news. The move has to be the
              symbol's own (v0.42.2): measured against the day's median move across the universe as well, so a day the
              whole market fell and bounced (March 12 and 13, 2020) is not a bad print in every name
  stale runs  five or more identical closes in a row while the rest of the universe moved: a frozen feed
  gaps        missing closes inside a symbol's trading history (before its first and after its last price is fine);
              gap_runs lists the longest runs of missing dates, so a gap can be traced to its cause
  unconfirmed (v0.47) the newest day cannot be a spike by the rule above: there is no next day to reverse it. A move
              on the newest day that is as large as a spike and the symbol's own is reported as unconfirmed, with its
              size. It is a warning: the symbol stays ok and nothing is rejected, because a genuine large move looks
              exactly the same until tomorrow. The numbers built on that day should be read with it in mind
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def screen(prices: pd.DataFrame, k: float = 8.0, reverse: float = 0.7, stale_len: int = 5) -> dict:
    rets = prices.pct_change(fill_method=None)
    market_moved = rets.abs().gt(0).sum(axis=1) >= max(2, prices.shape[1] // 2)
    own = rets.sub(rets.median(axis=1, skipna=True), axis=0) if prices.shape[1] >= 3 else None
    out, flagged = {}, 0
    unconfirmed: list[str] = []
    for c in prices.columns:
        px = prices[c]
        first, last = px.first_valid_index(), px.last_valid_index()
        if first is None:
            out[c] = {"spikes": [], "stale_runs": [], "gaps": 0, "ok": False, "note": "no prices"}
            flagged += 1
            continue
        r = rets[c].loc[first:last]
        last_day = None
        med = r.median()
        sd = 1.4826 * float((r - med).abs().median())
        spikes = []
        if sd > 0:
            nxt = r.shift(-1)
            cand = r.abs() > k * sd
            if own is not None:                     # the move must also stand out from the day's median move
                cand &= own[c].loc[first:last].abs() > k * sd
            rev = (np.sign(nxt) == -np.sign(r)) & (nxt.abs() >= reverse * r.abs() / (1 + r.abs()))
            spikes = [d.strftime("%Y-%m-%d") for d in r.index[(cand & rev).fillna(False)]]
            if len(r) and bool(cand.fillna(False).iloc[-1]):          # the newest day: as large as a spike, not yet confirmable
                last_day = {"date": r.index[-1].strftime("%Y-%m-%d"), "change": float(r.iloc[-1]), "robust_sds": float(abs(r.iloc[-1]) / sd)}
        same = px.loc[first:last].diff().eq(0) & market_moved.loc[first:last]
        runs, n = [], 0
        for d, v in same.items():
            n = n + 1 if v else 0
            if n == stale_len - 1:
                runs.append(d.strftime("%Y-%m-%d"))
        missing = px.loc[first:last].isna()
        gaps = int(missing.sum())
        ok = not spikes and not runs and gaps == 0
        flagged += 0 if ok else 1
        out[c] = {"spikes": spikes, "stale_runs": runs, "gaps": gaps, "ok": ok, "robust_sd": sd}
        if last_day is not None and last == prices.index[-1]:      # only when the symbol's newest day is the panel's
            out[c]["unconfirmed"] = last_day
            unconfirmed.append(c)
        if gaps:
            out[c]["gap_runs"] = gap_runs(missing)
    return {"symbols": out, "flagged": flagged, "unconfirmed": unconfirmed, "rule": f"spike: |r| > {k:g} robust sd, reversed >= {reverse:.0%} next day; stale: {stale_len}+ unchanged closes while the market moved"}


def gap_runs(missing: pd.Series, top: int = 5) -> list[dict]:
    """The longest runs of consecutive missing dates: [{from, to, days}], longest first."""
    runs, start, prev, n = [], None, None, 0
    for d, m in missing.items():
        if m:
            start, n = (d, 1) if start is None else (start, n + 1)
            prev = d
        elif start is not None:
            runs.append({"from": start.strftime("%Y-%m-%d"), "to": prev.strftime("%Y-%m-%d"), "days": n})
            start, n = None, 0
    if start is not None:
        runs.append({"from": start.strftime("%Y-%m-%d"), "to": prev.strftime("%Y-%m-%d"), "days": n})
    return sorted(runs, key=lambda r: -r["days"])[:top]
