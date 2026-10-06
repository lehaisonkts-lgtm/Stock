import pandas as pd

from src.market_chart import normalize_ohlcv, period_dates, price_snapshot


def test_normalize_ohlcv_vnstock_schema():
    raw = pd.DataFrame(
        {
            "time": ["2026-10-01", "2026-10-02"],
            "open": [10, 11],
            "high": [12, 13],
            "low": [9, 10],
            "close": [11, 12],
            "volume": [1000, 1500],
        }
    )
    out = normalize_ohlcv(raw)
    assert list(out.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(out) == 2
    assert out.iloc[-1]["close"] == 12


def test_price_snapshot_change_and_range():
    raw = pd.DataFrame(
        {
            "date": pd.date_range("2026-09-01", periods=30, freq="B"),
            "open": range(10, 40),
            "high": range(11, 41),
            "low": range(9, 39),
            "close": range(10, 40),
            "volume": [1000] * 30,
        }
    )
    snap = price_snapshot(raw)
    assert snap["close"] == 39
    assert snap["change"] == 1
    assert snap["high_52w"] == 40
    assert snap["low_52w"] == 9
    assert snap["vol_ratio20"] == 1


def test_period_dates_1y():
    start, end = period_dates("1Y", pd.Timestamp("2026-10-06"))
    assert start == "2025-10-06"
    assert end == "2026-10-06"
