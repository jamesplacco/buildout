"""CSV fallback: a wide file of adjusted closes (first column date, one column per ticker)."""
from __future__ import annotations

import pandas as pd


def load_prices(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    return df.apply(pd.to_numeric, errors="coerce")
