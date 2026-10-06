from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.data_provider import VnstockProvider
from src.market_chart import period_dates, price_snapshot
from src.repository import LocalRepository


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "stock_selector.db"
PRIORITY_PATH = DATA_DIR / "priority_tickers.csv"
TAILWIND_PATH = DATA_DIR / "tailwind_rules.csv"
STATE_REGISTRY_PATH = DATA_DIR / "state_parent_registry.csv"


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def main() -> int:
    repo = LocalRepository(DB_PATH)
    provider = VnstockProvider(
        state_registry=read_csv(STATE_REGISTRY_PATH),
        tailwind_rules=read_csv(TAILWIND_PATH),
    )
    priority = read_csv(PRIORITY_PATH)
    tickers = priority.get("ticker", pd.Series(dtype=str)).astype(str).str.upper().str.strip().tolist()
    pipeline = repo.load_pipeline()
    if not pipeline.empty:
        tickers += pipeline["ticker"].astype(str).str.upper().str.strip().tolist()
    tickers = list(dict.fromkeys([t for t in tickers if t]))

    start, end = period_dates("3Y", date.today())
    ok = 0
    failed = 0
    print(f"Daily OHLCV update: {len(tickers)} tickers | {start} -> {end}")
    for i, ticker in enumerate(tickers, start=1):
        try:
            df = provider.get_daily_ohlcv(ticker, start, end)
            source = str(df.attrs.get("source", "vnstock"))
            repo.save_price_history(ticker, df, source=source)
            snap = price_snapshot(df)
            latest = snap.get("date")
            print(f"[{i:02d}/{len(tickers):02d}] {ticker}: OK | {latest:%Y-%m-%d} | close={snap.get('close')} | {source}")
            ok += 1
        except Exception as exc:
            print(f"[{i:02d}/{len(tickers):02d}] {ticker}: ERROR | {exc}")
            failed += 1
    print(f"Done. OK={ok}, failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
