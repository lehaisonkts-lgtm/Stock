import pandas as pd

from src.repository import LocalRepository


def test_pipeline_roundtrip(tmp_path):
    repo = LocalRepository(tmp_path / "db.sqlite")
    repo.upsert_pipeline(
        "abc",
        {
            "status": "Theo dõi",
            "priority": 1,
            "thesis": "Test thesis",
            "target_price": 12345,
        },
    )
    row = repo.pipeline_for("ABC")
    assert row is not None
    assert row["ticker"] == "ABC"
    assert row["status"] == "Theo dõi"
    assert row["priority"] == 1
    assert row["target_price"] == 12345

    df = repo.load_pipeline()
    assert list(df["ticker"]) == ["ABC"]


def test_pipeline_save_normalizes(tmp_path):
    repo = LocalRepository(tmp_path / "db.sqlite")
    df = pd.DataFrame([
        {"ticker": "xyz", "status": "invalid", "priority": 9},
    ])
    repo.save_pipeline(df)
    row = repo.pipeline_for("XYZ")
    assert row["status"] == "Ứng viên"
    assert row["priority"] == 5


def test_price_history_cache_roundtrip(tmp_path):
    repo = LocalRepository(tmp_path / "test.db")
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-10-01", "2026-10-02"]),
            "open": [10.0, 11.0],
            "high": [12.0, 13.0],
            "low": [9.0, 10.0],
            "close": [11.0, 12.0],
            "volume": [1000.0, 1500.0],
        }
    )
    repo.save_price_history("VEA", df, source="test")
    out = repo.load_price_history("VEA", "2026-10-01", "2026-10-31")
    assert len(out) == 2
    assert out.iloc[-1]["close"] == 12.0
    status = repo.market_cache_status(["VEA"])
    assert status.iloc[0]["latest_date"] == "2026-10-02"
