from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_demo_candidates(base_dir: str | Path) -> pd.DataFrame:
    path = Path(base_dir) / "data" / "demo_candidates.csv"
    return pd.read_csv(path)
