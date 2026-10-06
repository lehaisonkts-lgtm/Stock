from __future__ import annotations

import html
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .utils import pct_to_fraction, safe_float


BRAND = {
    "navy": "#0B1F33",
    "blue": "#1F5E8C",
    "green": "#167A5B",
    "amber": "#A76B00",
    "red": "#B93C3C",
    "ink": "#17212B",
    "muted": "#667085",
    "line": "#E4E7EC",
    "surface": "#F7F9FC",
}


def inject_app_style() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
          --svs-navy: {BRAND['navy']};
          --svs-blue: {BRAND['blue']};
          --svs-green: {BRAND['green']};
          --svs-amber: {BRAND['amber']};
          --svs-red: {BRAND['red']};
          --svs-line: {BRAND['line']};
          --svs-surface: {BRAND['surface']};
        }}
        .stApp {{ background: #FFFFFF; }}
        .block-container {{ max-width: 1500px; padding-top: 1.15rem; padding-bottom: 4rem; }}
        [data-testid="stSidebar"] {{ border-right: 1px solid var(--svs-line); }}
        [data-testid="stSidebar"] .block-container {{ padding-top: 1.2rem; }}
        h1, h2, h3 {{ color: var(--svs-navy); letter-spacing: -0.02em; }}
        h1 {{ font-size: 2rem !important; margin-bottom: .25rem !important; }}
        h2 {{ font-size: 1.45rem !important; }}
        h3 {{ font-size: 1.1rem !important; }}
        .svs-brand {{
          border: 1px solid var(--svs-line); border-radius: 16px; padding: 14px 14px 12px 14px;
          background: linear-gradient(145deg, #FFFFFF 0%, #F4F7FB 100%); margin-bottom: 14px;
        }}
        .svs-brand-title {{ font-weight: 800; color: var(--svs-navy); font-size: 1.02rem; }}
        .svs-brand-sub {{ color: #667085; font-size: .76rem; margin-top: 2px; line-height: 1.35; }}
        .svs-eyebrow {{ color: var(--svs-blue); font-weight: 800; font-size: .74rem; letter-spacing: .11em; text-transform: uppercase; }}
        .svs-subtitle {{ color: #667085; font-size: .95rem; margin-top: -.2rem; margin-bottom: 1.05rem; max-width: 980px; }}
        .svs-panel {{
          border: 1px solid var(--svs-line); border-radius: 16px; padding: 16px 18px;
          background: #FFFFFF; box-shadow: 0 1px 2px rgba(16,24,40,.03);
        }}
        .svs-callout {{
          border: 1px solid #D5DEE9; border-left: 4px solid var(--svs-blue); border-radius: 12px;
          padding: 11px 13px; background: #F8FBFF; color: #344054; font-size: .88rem;
        }}
        .svs-pill {{ display:inline-block; padding: 4px 9px; border-radius:999px; font-weight:700; font-size:.75rem; border:1px solid; }}
        .svs-pill-pass {{ color:#086C4E; background:#ECFDF3; border-color:#ABEFC6; }}
        .svs-pill-fail {{ color:#B42318; background:#FEF3F2; border-color:#FECDCA; }}
        .svs-pill-warn {{ color:#8A4B00; background:#FFFAEB; border-color:#FEDF89; }}
        .svs-pill-info {{ color:#175CD3; background:#EFF8FF; border-color:#B2DDFF; }}
        div[data-testid="stMetric"] {{
          border: 1px solid var(--svs-line); padding: 12px 14px; border-radius: 14px; background:#FFFFFF;
          box-shadow: 0 1px 2px rgba(16,24,40,.025);
        }}
        div[data-testid="stMetric"] label {{ color:#667085 !important; font-weight:600 !important; }}
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {{ color:var(--svs-navy); font-weight:800; }}
        [data-testid="stDataFrame"] {{ border: 1px solid var(--svs-line); border-radius: 12px; overflow: hidden; }}
        [data-testid="stTabs"] button {{ font-weight: 700; }}
        .stButton > button[kind="primary"] {{ font-weight: 800; border-radius: 10px; }}
        .stButton > button {{ border-radius: 10px; }}
        .stDownloadButton > button {{ border-radius: 10px; }}
        .small-note {{ color:#667085; font-size:.82rem; }}
        .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
        @media (max-width: 780px) {{
          .block-container {{ padding: .75rem .75rem 3rem .75rem; }}
          h1 {{ font-size: 1.55rem !important; }}
          h2 {{ font-size: 1.25rem !important; }}
          .svs-subtitle {{ font-size:.88rem; }}
          div[data-testid="stMetric"] {{ padding: 10px 11px; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str, eyebrow: str = "SONLEE STOCK") -> None:
    st.markdown(f'<div class="svs-eyebrow">{html.escape(eyebrow)}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<div class="svs-subtitle">{html.escape(subtitle)}</div>', unsafe_allow_html=True)


def info_callout(text: str) -> None:
    st.markdown(f'<div class="svs-callout">{html.escape(text)}</div>', unsafe_allow_html=True)


def status_pill(label: str, kind: str = "info") -> str:
    kind = kind if kind in {"pass", "fail", "warn", "info"} else "info"
    return f'<span class="svs-pill svs-pill-{kind}">{html.escape(label)}</span>'


def fmt_pct(value: Any, digits: int = 1) -> str:
    val = pct_to_fraction(value)
    if val is None:
        return "—"
    return f"{val * 100:.{digits}f}%"


def fmt_num(value: Any, digits: int = 1, suffix: str = "") -> str:
    val = safe_float(value)
    if val is None:
        return "—"
    return f"{val:,.{digits}f}{suffix}"


def criterion_table(row: dict[str, Any]) -> pd.DataFrame:
    items = [
        ("C1", "Ngành có thiên thời", row.get("C1_thien_thoi"), f"Điểm chủ đề {safe_float(row.get('theme_score'), 0):.1f}/10"),
        ("C2", "Nhà nước/đơn vị Nhà nước chi phối >50%", row.get("C2_nha_nuoc_chi_phoi"), fmt_pct(row.get("state_control_pct"))),
        ("C3", "Lãnh đạo & hiệu quả vốn", row.get("C3_lanh_dao"), f"ROE 3Y {fmt_pct(row.get('roe_3y_median'))}"),
        ("C4", "Có bằng chứng tài sản ẩn", row.get("C4_tai_san_an"), f"Điểm {safe_float(row.get('hidden_asset_score'), 0):.1f}/10"),
        ("C5", "Tăng trưởng + biên lợi nhuận", row.get("C5_tang_truong_bien_loi_nhuan"), f"LNST YoY {fmt_pct(row.get('profit_growth_yoy'))} | Biên {fmt_pct(row.get('annual_margin'))}"),
        ("C6", "Cổ tức đều đặn", row.get("C6_co_tuc_deu"), f"{safe_float(row.get('dividend_years_paid'), 0):.0f} năm | Yield {fmt_pct(row.get('dividend_yield'))}"),
    ]
    records = []
    for code, name, passed, evidence in items:
        if passed is True:
            status = "Đạt"
        elif passed is False:
            status = "Chưa đạt"
        else:
            status = "Không bắt buộc"
        records.append({"Mã": code, "Tiêu chí": name, "Trạng thái": status, "Dữ liệu": evidence})
    return pd.DataFrame(records)


def score_component_frame(row: dict[str, Any]) -> pd.DataFrame:
    specs = [
        ("Thiên thời", "score_tailwind", 20.0),
        ("Nhà nước", "score_state_control", 15.0),
        ("Lãnh đạo", "score_management", 20.0),
        ("Tài sản ẩn", "score_hidden_assets", 15.0),
        ("Tăng trưởng", "score_growth_profitability", 20.0),
        ("Cổ tức", "score_dividend", 10.0),
    ]
    rows = []
    for label, col, max_score in specs:
        value = safe_float(row.get(col), 0.0) or 0.0
        rows.append({"Thành phần": label, "Điểm": value, "Tối đa": max_score, "Mức đạt (%)": (value / max_score * 100.0) if max_score else 0.0})
    return pd.DataFrame(rows)


def score_radar(row: dict[str, Any]) -> go.Figure:
    df = score_component_frame(row)
    theta = df["Thành phần"].tolist()
    r = df["Mức đạt (%)"].tolist()
    theta_closed = theta + [theta[0]]
    r_closed = r + [r[0]]
    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=r_closed,
            theta=theta_closed,
            fill="toself",
            name="Mức đạt",
            hovertemplate="%{theta}: %{r:.0f}%<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=30, r=30, t=35, b=25),
        height=340,
        showlegend=False,
        polar=dict(radialaxis=dict(visible=True, range=[0, 100], ticksuffix="%")),
    )
    return fig


def score_bar(df: pd.DataFrame, limit: int = 15) -> go.Figure:
    work = df.head(limit).copy()
    fig = go.Figure(
        go.Bar(
            x=pd.to_numeric(work.get("total_score"), errors="coerce"),
            y=work.get("ticker", pd.Series(dtype=str)).astype(str),
            orientation="h",
            customdata=work[[c for c in ["company_name", "fail_reasons"] if c in work.columns]].to_numpy() if any(c in work.columns for c in ["company_name", "fail_reasons"]) else None,
        )
    )
    fig.update_layout(
        height=max(320, 34 * len(work) + 90),
        margin=dict(l=15, r=15, t=35, b=20),
        xaxis_title="Điểm / 100",
        yaxis_title=None,
        yaxis=dict(autorange="reversed"),
    )
    return fig
