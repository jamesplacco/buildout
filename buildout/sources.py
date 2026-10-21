"""Every data source the engine and the page read, in one registry (python -m buildout sources --out site/data).

The page's Engine desk renders this list. Counting sources honestly: a FRED series is one source, a feed is one source,
a public dataset is one source, whatever the number of fields read from it.
"""
from __future__ import annotations

from pathlib import Path

from . import feeds, macro, research

FIXED = [
    ("SEC EDGAR XBRL", "api", "Capex, cash flow, debt, depreciation, stock compensation from 10-K and 10-Q filings", "quarterly", "free; contact email"),
    ("Databento", "api", "Daily bars, corporate actions, CME Treasury futures for the model book", "daily", "pay as you go"),
    ("Kalshi", "api", "Prediction-market odds on the Fed path, CPI and recession", "daily", "free"),
    ("IEA Oil Market Report", "manual", "Dated Brent against futures, Hormuz flows, inventories", "monthly", "free summaries"),
    ("PJM capacity auctions", "manual", "Capacity clearing prices and the reliability shortfall", "yearly", "free"),
    ("Cboe volume briefings", "manual", "Off-exchange share, 0DTE share, retail activity", "monthly", "free"),
]


def registry(feeds_path: str | Path = "feeds.toml") -> list[dict]:
    rows = [{"name": f"FRED {sid}", "kind": "series", "what": sid, "cadence": "daily or as published", "cost": "free"} for sid in macro.FRED_IDS]
    rows += [{"name": f"GitHub dataset: {k}", "kind": "dataset", "what": path, "cadence": "monthly", "cost": "free"} for k, path in research.SOURCES.items()]
    rows += [{"name": n, "kind": k, "what": w, "cadence": c, "cost": cost} for n, k, w, c, cost in FIXED]
    try:
        cfg = feeds.load_config(feeds_path)
        rows += [{"name": s["name"], "kind": s["platform"], "what": s.get("url") or s.get("channel") or s.get("handle") or s.get("sub") or "",
                  "cadence": "every run", "cost": "free" if s["platform"] != "x" else "X API token"} for s in cfg.get("source", [])]
        rows += [{"name": f"Google News: {t['name']}", "kind": "news", "what": t["query"], "cadence": "every run", "cost": "free"} for t in cfg.get("theme", [])]
    except (OSError, ValueError):
        pass
    return rows


def run(feeds_path: str | Path = "feeds.toml") -> dict:
    rows = registry(feeds_path)
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    return {"schema": 1, "count": len(rows), "by_kind": kinds, "sources": rows}
