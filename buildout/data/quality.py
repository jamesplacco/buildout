"""A screen on prices before they become returns. It flags; it never edits a price.

  spikes      a one-day move above `k` robust standard deviations (1.4826 x MAD of the symbol's returns) that
              mostly reverses the next day: the signature of a bad print, not of news
  stale runs  five or more identical closes in a row while the rest of the universe moved: a frozen feed
  gaps        missing closes inside a symbol's trading history (before its first and after its last price is fine)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def screen(prices: pd.DataFrame, k: float = 8.0, reverse: float = 0.7, stale_len: int = 5) -> dict:
    rets = prices.pct_change(fill_method=None)
    market_moved = rets.abs().gt(0).sum(axis=1) >= max(2, prices.shape[1] // 2)
    out, flagged = {}, 0
    for c in prices.columns:
        px = prices[c]
        first, last = px.first_valid_index(), px.last_valid_index()
        if first is None:
            out[c] = {"spikes": [], "stale_runs": [], "gaps": 0, "ok": False, "note": "no prices"}
            flagged += 1
            continue
        r = rets[c].loc[first:last]
        med = r.median()
        sd = 1.4826 * float((r - med).abs().median())
        spikes = []
        if sd > 0:
            nxt = r.shift(-1)
            cand = r.abs() > k * sd
            rev = (np.sign(nxt) == -np.sign(r)) & (nxt.abs() >= reverse * r.abs() / (1 + r.abs()))
            spikes = [d.strftime("%Y-%m-%d") for d in r.index[(cand & rev).fillna(False)]]
        same = px.loc[first:last].diff().eq(0) & market_moved.loc[first:last]
        runs, n = [], 0
        for d, v in same.items():
            n = n + 1 if v else 0
            if n == stale_len - 1:
                runs.append(d.strftime("%Y-%m-%d"))
        gaps = int(px.loc[first:last].isna().sum())
        ok = not spikes and not runs and gaps == 0
        flagged += 0 if ok else 1
        out[c] = {"spikes": spikes, "stale_runs": runs, "gaps": gaps, "ok": ok, "robust_sd": sd}
    return {"symbols": out, "flagged": flagged, "rule": f"spike: |r| > {k:g} robust sd, reversed >= {reverse:.0%} next day; stale: {stale_len}+ unchanged closes while the market moved"}
