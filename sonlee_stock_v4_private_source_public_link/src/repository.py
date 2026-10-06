from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import to_bool


OVERRIDE_COLUMNS = [
    "ticker",
    "state_control_pct",
    "state_controller",
    "state_evidence",
    "theme_score",
    "theme_name",
    "theme_rationale",
    "decline_flag",
    "core_focus_score",
    "governance_score",
    "hidden_asset_score",
    "hidden_asset_book_bn",
    "hidden_asset_market_bn",
    "hidden_asset_evidence",
    "industry_margin_benchmark",
    "notes",
    "updated_at",
]

PIPELINE_COLUMNS = [
    "ticker",
    "status",
    "priority",
    "thesis",
    "key_risk",
    "entry_price",
    "target_price",
    "stop_loss",
    "next_review",
    "notes",
    "updated_at",
]

PIPELINE_STATUSES = [
    "Ứng viên",
    "Cần kiểm chứng",
    "Theo dõi",
    "Sẵn sàng xem xét",
    "Loại",
]


class LocalRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS overrides (
                    ticker TEXT PRIMARY KEY,
                    state_control_pct REAL,
                    state_controller TEXT,
                    state_evidence TEXT,
                    theme_score REAL,
                    theme_name TEXT,
                    theme_rationale TEXT,
                    decline_flag INTEGER,
                    core_focus_score REAL,
                    governance_score REAL,
                    hidden_asset_score REAL,
                    hidden_asset_book_bn REAL,
                    hidden_asset_market_bn REAL,
                    hidden_asset_evidence TEXT,
                    industry_margin_benchmark REAL,
                    notes TEXT,
                    updated_at TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS screening_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    row_count INTEGER NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS screening_results (
                    run_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES screening_runs(run_id)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS candidate_pipeline (
                    ticker TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'Ứng viên',
                    priority INTEGER NOT NULL DEFAULT 3,
                    thesis TEXT,
                    key_risk TEXT,
                    entry_price REAL,
                    target_price REAL,
                    stop_loss REAL,
                    next_review TEXT,
                    notes TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS market_ohlcv (
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    source TEXT,
                    refreshed_at TEXT NOT NULL,
                    PRIMARY KEY (ticker, date)
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_market_ohlcv_ticker_date ON market_ohlcv(ticker, date)"
            )
            con.commit()

    def load_overrides(self) -> pd.DataFrame:
        with self._connect() as con:
            df = pd.read_sql_query("SELECT * FROM overrides ORDER BY ticker", con)
        if df.empty:
            return pd.DataFrame(columns=OVERRIDE_COLUMNS)
        for col in OVERRIDE_COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df[OVERRIDE_COLUMNS]

    def override_for(self, ticker: str) -> dict[str, Any] | None:
        ticker = ticker.upper().strip()
        with self._connect() as con:
            row = con.execute("SELECT * FROM overrides WHERE ticker = ?", (ticker,)).fetchone()
        return dict(row) if row else None

    def save_overrides(self, df: pd.DataFrame) -> None:
        work = df.copy()
        if "ticker" not in work.columns:
            raise ValueError("Override table must contain ticker")
        for col in OVERRIDE_COLUMNS:
            if col not in work.columns:
                work[col] = None
        work["ticker"] = work["ticker"].astype(str).str.upper().str.strip()
        work = work[work["ticker"] != ""].copy()
        work["updated_at"] = datetime.now().isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute("DELETE FROM overrides")
            for _, row in work[OVERRIDE_COLUMNS].iterrows():
                values = []
                for col in OVERRIDE_COLUMNS:
                    value = row[col]
                    if pd.isna(value):
                        value = None
                    if col == "decline_flag" and value is not None:
                        value = int(to_bool(value, False))
                    values.append(value)
                placeholders = ",".join(["?"] * len(OVERRIDE_COLUMNS))
                con.execute(
                    f"INSERT OR REPLACE INTO overrides ({','.join(OVERRIDE_COLUMNS)}) VALUES ({placeholders})",
                    values,
                )
            con.commit()

    def upsert_override(self, ticker: str, updates: dict[str, Any]) -> None:
        ticker = ticker.upper().strip()
        current = self.override_for(ticker) or {col: None for col in OVERRIDE_COLUMNS}
        current["ticker"] = ticker
        current.update(updates)
        current["updated_at"] = datetime.now().isoformat(timespec="seconds")
        df = self.load_overrides()
        if ticker in set(df["ticker"].astype(str)):
            idx = df.index[df["ticker"].astype(str) == ticker][0]
            for key, value in current.items():
                if key in df.columns:
                    df.at[idx, key] = value
        else:
            df = pd.concat([df, pd.DataFrame([current])], ignore_index=True)
        self.save_overrides(df)

    def save_screening_run(self, df: pd.DataFrame, settings: dict[str, Any]) -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        settings_json = json.dumps(settings, ensure_ascii=False, default=str)
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO screening_runs(created_at, settings_json, row_count) VALUES (?, ?, ?)",
                (created_at, settings_json, int(len(df))),
            )
            run_id = int(cur.lastrowid)
            for _, row in df.iterrows():
                payload = json.dumps(row.to_dict(), ensure_ascii=False, default=str)
                ticker = str(row.get("ticker", ""))
                con.execute(
                    "INSERT INTO screening_results(run_id, ticker, result_json) VALUES (?, ?, ?)",
                    (run_id, ticker, payload),
                )
            con.commit()
        return run_id

    def list_runs(self, limit: int = 30) -> pd.DataFrame:
        with self._connect() as con:
            return pd.read_sql_query(
                "SELECT run_id, created_at, row_count, settings_json FROM screening_runs ORDER BY run_id DESC LIMIT ?",
                con,
                params=(int(limit),),
            )

    def load_run(self, run_id: int) -> pd.DataFrame:
        with self._connect() as con:
            rows = con.execute(
                "SELECT result_json FROM screening_results WHERE run_id = ? ORDER BY ticker",
                (int(run_id),),
            ).fetchall()
        payloads = [json.loads(row["result_json"]) for row in rows]
        return pd.DataFrame(payloads)

    def load_pipeline(self) -> pd.DataFrame:
        with self._connect() as con:
            df = pd.read_sql_query(
                "SELECT * FROM candidate_pipeline ORDER BY priority ASC, updated_at DESC, ticker ASC",
                con,
            )
        if df.empty:
            return pd.DataFrame(columns=PIPELINE_COLUMNS)
        for col in PIPELINE_COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df[PIPELINE_COLUMNS]

    def pipeline_for(self, ticker: str) -> dict[str, Any] | None:
        ticker = ticker.upper().strip()
        with self._connect() as con:
            row = con.execute("SELECT * FROM candidate_pipeline WHERE ticker = ?", (ticker,)).fetchone()
        return dict(row) if row else None

    def save_pipeline(self, df: pd.DataFrame) -> None:
        work = df.copy()
        if "ticker" not in work.columns:
            raise ValueError("Pipeline table must contain ticker")
        for col in PIPELINE_COLUMNS:
            if col not in work.columns:
                work[col] = None
        work["ticker"] = work["ticker"].astype(str).str.upper().str.strip()
        work = work[work["ticker"] != ""].copy()
        work["status"] = work["status"].fillna("Ứng viên").astype(str)
        work.loc[~work["status"].isin(PIPELINE_STATUSES), "status"] = "Ứng viên"
        work["priority"] = pd.to_numeric(work["priority"], errors="coerce").fillna(3).clip(1, 5).astype(int)
        work["updated_at"] = datetime.now().isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute("DELETE FROM candidate_pipeline")
            for _, row in work[PIPELINE_COLUMNS].iterrows():
                values = []
                for col in PIPELINE_COLUMNS:
                    value = row[col]
                    if pd.isna(value):
                        value = None
                    values.append(value)
                placeholders = ",".join(["?"] * len(PIPELINE_COLUMNS))
                con.execute(
                    f"INSERT OR REPLACE INTO candidate_pipeline ({','.join(PIPELINE_COLUMNS)}) VALUES ({placeholders})",
                    values,
                )
            con.commit()

    def upsert_pipeline(self, ticker: str, updates: dict[str, Any] | None = None) -> None:
        ticker = ticker.upper().strip()
        if not ticker:
            return
        current = self.pipeline_for(ticker) or {col: None for col in PIPELINE_COLUMNS}
        current.update(
            {
                "ticker": ticker,
                "status": current.get("status") or "Ứng viên",
                "priority": current.get("priority") or 3,
            }
        )
        if updates:
            current.update(updates)
        current["updated_at"] = datetime.now().isoformat(timespec="seconds")
        with self._connect() as con:
            cols = PIPELINE_COLUMNS
            values = [current.get(col) for col in cols]
            placeholders = ",".join(["?"] * len(cols))
            con.execute(
                f"INSERT OR REPLACE INTO candidate_pipeline ({','.join(cols)}) VALUES ({placeholders})",
                values,
            )
            con.commit()

    def remove_pipeline(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        with self._connect() as con:
            con.execute("DELETE FROM candidate_pipeline WHERE ticker = ?", (ticker,))
            con.commit()

    def save_price_history(self, ticker: str, df: pd.DataFrame, source: str = "vnstock") -> int:
        ticker = str(ticker).upper().strip()
        if not ticker or df is None or df.empty:
            return 0
        required = {"date", "open", "high", "low", "close", "volume"}
        if not required.issubset(set(df.columns)):
            raise ValueError(f"OHLCV thiếu cột: {sorted(required - set(df.columns))}")
        work = df.copy()
        work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        work = work.dropna(subset=["date"])
        refreshed_at = datetime.now().isoformat(timespec="seconds")
        count = 0
        with self._connect() as con:
            for _, row in work.iterrows():
                con.execute(
                    """
                    INSERT INTO market_ohlcv(ticker, date, open, high, low, close, volume, source, refreshed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ticker, date) DO UPDATE SET
                        open=excluded.open, high=excluded.high, low=excluded.low,
                        close=excluded.close, volume=excluded.volume, source=excluded.source,
                        refreshed_at=excluded.refreshed_at
                    """,
                    (
                        ticker, row["date"], float(row["open"]), float(row["high"]),
                        float(row["low"]), float(row["close"]), float(row.get("volume", 0) or 0),
                        source, refreshed_at,
                    ),
                )
                count += 1
            con.commit()
        return count

    def load_price_history(self, ticker: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        ticker = str(ticker).upper().strip()
        where = ["ticker = ?"]
        params: list[Any] = [ticker]
        if start:
            where.append("date >= ?")
            params.append(str(start))
        if end:
            where.append("date <= ?")
            params.append(str(end))
        query = (
            "SELECT date, open, high, low, close, volume, source, refreshed_at "
            "FROM market_ohlcv WHERE " + " AND ".join(where) + " ORDER BY date"
        )
        with self._connect() as con:
            df = pd.read_sql_query(query, con, params=params)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df

    def market_cache_status(self, tickers: list[str] | None = None) -> pd.DataFrame:
        where = ""
        params: list[Any] = []
        if tickers:
            cleaned = [str(t).upper().strip() for t in tickers if str(t).strip()]
            placeholders = ",".join(["?"] * len(cleaned))
            where = f"WHERE ticker IN ({placeholders})"
            params.extend(cleaned)
        query = f"""
            SELECT ticker, MAX(date) AS latest_date, COUNT(*) AS sessions, MAX(refreshed_at) AS refreshed_at
            FROM market_ohlcv
            {where}
            GROUP BY ticker
            ORDER BY ticker
        """
        with self._connect() as con:
            return pd.read_sql_query(query, con, params=params)
