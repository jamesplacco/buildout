"""Parquet cache so paid data is pulled once and reused."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd


class Cache:
    def __init__(self, root: str | Path = ".cache"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:80]
        digest = hashlib.sha1(key.encode()).hexdigest()[:10]
        return self.root / f"{safe}_{digest}.parquet"

    def get(self, key: str) -> pd.DataFrame | None:
        p = self._path(key)
        return pd.read_parquet(p) if p.exists() else None

    def put(self, key: str, df: pd.DataFrame) -> None:
        df.to_parquet(self._path(key))
