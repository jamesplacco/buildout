"""JSON helpers shared by every report the page reads."""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


def series(s: pd.Series, freq: str | None = "W-FRI") -> dict:
    """Date/value arrays, resampled (weekly by default) to keep the page payload small."""
    s = s.dropna()
    if freq:
        s = s.resample(freq).last().dropna()
    return {"dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [round(float(v), 6) for v in s]}


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, pd.DataFrame):
        return clean(o.reset_index().to_dict(orient="records"))
    if isinstance(o, pd.Series):
        return clean(o.to_dict())
    if isinstance(o, (np.floating, float)):
        if not np.isfinite(o):
            return None
        x = float(o)
        return round(x, 6) if x == 0 or abs(x) >= 1e-4 else float(f"{x:.4g}")   # keep tiny probabilities (1.84e-06) significant
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, pd.Interval):
        return str(o)
    return o


SCHEMA = 2   # bump when a field the page reads changes meaning or moves


def write(obj: dict, out_dir: str | Path, name: str) -> Path:
    """Write JSON atomically: a crash mid-write never leaves a truncated file for the page to choke on."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    payload = json.dumps(clean({"schema": SCHEMA, **obj}), indent=1, allow_nan=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload)
    os.replace(tmp, path)
    return path
