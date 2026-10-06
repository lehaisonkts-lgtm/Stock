from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


PRICE_PERIODS = {
    "1M": pd.DateOffset(months=1),
    "3M": pd.DateOffset(months=3),
    "6M": pd.DateOffset(months=6),
    "1Y": pd.DateOffset(years=1),
    "3Y": pd.DateOffset(years=3),
    "5Y": pd.DateOffset(years=5),
}


def period_dates(period: str, end: date | pd.Timestamp | None = None) -> tuple[str, str]:
    end_ts = pd.Timestamp(end or date.today()).normalize()
    if period == "MAX":
        start_ts = pd.Timestamp("2000-01-01")
    else:
        start_ts = end_ts - PRICE_PERIODS.get(period, pd.DateOffset(years=1))
    return start_ts.strftime("%Y-%m-%d"), end_ts.strftime("%Y-%m-%d")


def normalize_ohlcv(df: pd.DataFrame | None) -> pd.DataFrame:
    """Normalize common Vnstock/market provider OHLCV schemas."""
    cols = ["date", "open", "high", "low", "close", "volume"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    work = df.copy()
    aliases = {
        "date": ["date", "time", "trading_date", "tradingdate", "datetime", "timestamp"],
        "open": ["open", "open_price", "openprice", "price_open"],
        "high": ["high", "high_price", "highprice", "price_high"],
        "low": ["low", "low_price", "lowprice", "price_low"],
        "close": ["close", "close_price", "closeprice", "price_close", "match_price"],
        "volume": ["volume", "match_volume", "total_volume", "trading_volume", "vol"],
    }

    normalized_names = {str(c).strip().lower().replace(" ", "_"): c for c in work.columns}
    selected: dict[str, Any] = {}
    for target, choices in aliases.items():
        for choice in choices:
            key = choice.strip().lower().replace(" ", "_")
            if key in normalized_names:
                selected[target] = normalized_names[key]
                break

    missing = [c for c in cols if c not in selected]
    if missing:
        return pd.DataFrame(columns=cols)

    out = work[[selected[c] for c in cols]].copy()
    out.columns = cols
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for c in ["open", "high", "low", "close", "volume"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    out["volume"] = out["volume"].fillna(0.0).clip(lower=0)
    out = out.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    return out


def add_price_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        return out
    out["ma20"] = out["close"].rolling(20, min_periods=1).mean()
    out["ma50"] = out["close"].rolling(50, min_periods=1).mean()
    out["vol_ma20"] = out["volume"].rolling(20, min_periods=1).mean()
    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            (out["high"] - out["low"]).abs(),
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr14"] = tr.rolling(14, min_periods=1).mean()
    return out


def price_snapshot(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty:
        return {}
    work = add_price_indicators(df)
    last = work.iloc[-1]
    prev = work.iloc[-2] if len(work) >= 2 else None
    close = float(last["close"])
    change = close - float(prev["close"]) if prev is not None else np.nan
    change_pct = change / float(prev["close"]) if prev is not None and float(prev["close"]) != 0 else np.nan
    tail_252 = work.tail(252)
    avg_vol20 = float(work["volume"].tail(20).mean()) if len(work) else np.nan
    vol_ratio = float(last["volume"]) / avg_vol20 if avg_vol20 and not np.isnan(avg_vol20) else np.nan
    return {
        "date": pd.Timestamp(last["date"]),
        "open": float(last["open"]),
        "high": float(last["high"]),
        "low": float(last["low"]),
        "close": close,
        "volume": float(last["volume"]),
        "change": change,
        "change_pct": change_pct,
        "high_52w": float(tail_252["high"].max()) if not tail_252.empty else np.nan,
        "low_52w": float(tail_252["low"].min()) if not tail_252.empty else np.nan,
        "avg_vol20": avg_vol20,
        "vol_ratio20": vol_ratio,
        "ma20": float(last["ma20"]),
        "ma50": float(last["ma50"]),
        "atr14": float(last["atr14"]),
    }


def candlestick_volume_figure(
    df: pd.DataFrame,
    ticker: str,
    show_ma20: bool = True,
    show_ma50: bool = True,
    show_vol_ma20: bool = True,
) -> go.Figure:
    work = add_price_indicators(df)
    if work.empty:
        return go.Figure()

    up = work["close"] >= work["open"]
    volume_colors = np.where(up, "#18A66A", "#D84A4A")

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.74, 0.26],
        specs=[[{"type": "candlestick"}], [{"type": "bar"}]],
    )
    fig.add_trace(
        go.Candlestick(
            x=work["date"],
            open=work["open"],
            high=work["high"],
            low=work["low"],
            close=work["close"],
            name=ticker,
            increasing_line_color="#18A66A",
            decreasing_line_color="#D84A4A",
            increasing_fillcolor="#18A66A",
            decreasing_fillcolor="#D84A4A",
            whiskerwidth=0.25,
        ),
        row=1,
        col=1,
    )
    if show_ma20:
        fig.add_trace(
            go.Scatter(x=work["date"], y=work["ma20"], mode="lines", name="MA20", line=dict(width=1.4)),
            row=1,
            col=1,
        )
    if show_ma50:
        fig.add_trace(
            go.Scatter(x=work["date"], y=work["ma50"], mode="lines", name="MA50", line=dict(width=1.4)),
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Bar(x=work["date"], y=work["volume"], name="Khối lượng", marker_color=volume_colors, opacity=0.88),
        row=2,
        col=1,
    )
    if show_vol_ma20:
        fig.add_trace(
            go.Scatter(x=work["date"], y=work["vol_ma20"], mode="lines", name="KL TB20", line=dict(width=1.3)),
            row=2,
            col=1,
        )

    fig.update_layout(
        height=720,
        margin=dict(l=12, r=12, t=42, b=16),
        title=dict(text=f"{ticker} · Nến ngày & khối lượng", x=0.01, xanchor="left", font=dict(size=18)),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        xaxis_rangeslider_visible=False,
        bargap=0.18,
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(20, 40, 70, .07)",
        rangebreaks=[dict(bounds=["sat", "mon"])],
        row=1,
        col=1,
    )
    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(20, 40, 70, .07)",
        rangebreaks=[dict(bounds=["sat", "mon"])],
        row=2,
        col=1,
    )
    fig.update_yaxes(title_text="Giá", showgrid=True, gridcolor="rgba(20, 40, 70, .07)", row=1, col=1)
    fig.update_yaxes(title_text="Khối lượng", showgrid=True, gridcolor="rgba(20, 40, 70, .07)", row=2, col=1)
    return fig
