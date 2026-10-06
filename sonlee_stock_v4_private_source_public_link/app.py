from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from src.config import ScreeningConfig
from src.data_provider import VnstockProvider, VnstockUnavailable
from src.demo import load_demo_candidates
from src.pdf_miner import pdf_hidden_asset_audit
from src.market_chart import candlestick_volume_figure, period_dates, price_snapshot
from src.repository import LocalRepository, PIPELINE_STATUSES
from src.scoring import apply_batch_industry_benchmarks, score_dataframe
from src.ui import (
    criterion_table,
    fmt_num,
    fmt_pct,
    info_callout,
    inject_app_style,
    page_header,
    score_bar,
    score_component_frame,
    score_radar,
    status_pill,
)
from src.utils import dataframe_to_excel_bytes, normalize_text, pct_to_fraction, safe_float


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "stock_selector.db"
TAILWIND_PATH = DATA_DIR / "tailwind_rules.csv"
STATE_REGISTRY_PATH = DATA_DIR / "state_parent_registry.csv"
BENCHMARK_TEMPLATE_PATH = DATA_DIR / "industry_benchmarks_template.csv"
PRIORITY_TICKERS_PATH = DATA_DIR / "priority_tickers.csv"

st.set_page_config(
    page_title="SONLEE STOCK | Vietnam State Value",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_app_style()
repo = LocalRepository(DB_PATH)


def _secret(name: str, default: str = "") -> str:
    """Read a server-side Streamlit secret without exposing it to viewers."""
    try:
        value = st.secrets.get(name, default)
        return str(value) if value is not None else default
    except Exception:
        return default


def is_admin() -> bool:
    return bool(st.session_state.get("sonlee_admin", False))

def require_admin(action: str = "Tác vụ này") -> bool:
    if is_admin():
        return True
    st.warning(f"{action} chỉ dành cho Admin. Mở khóa Quản trị ở thanh bên.")
    return False


# -------------------------
# Helpers
# -------------------------
def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def get_provider() -> VnstockProvider:
    return VnstockProvider(
        state_registry=read_csv(STATE_REGISTRY_PATH),
        tailwind_rules=read_csv(TAILWIND_PATH),
    )


@st.cache_data(ttl=900, show_spinner=False)
def fetch_live_daily_ohlcv(ticker: str, start: str, end: str, refresh_token: int = 0) -> tuple[pd.DataFrame, str]:
    """Fetch daily candles; refresh_token is intentionally part of the cache key."""
    provider = get_provider()
    df = provider.get_daily_ohlcv(ticker, start, end)
    return df, str(df.attrs.get("source", "vnstock"))


def priority_tickers() -> list[str]:
    df = read_csv(PRIORITY_TICKERS_PATH)
    if df.empty or "ticker" not in df.columns:
        return ["CKA", "KSV", "CSV", "VEA", "TMB", "CST", "HU4", "HUD", "HD8", "L14", "CLM", "FT1", "FOX"]
    return [str(x).upper().strip() for x in df["ticker"].tolist() if str(x).strip()]


def parse_tickers(text: str) -> list[str]:
    raw = text.replace(";", ",").replace("\n", ",").replace(" ", ",").split(",")
    out: list[str] = []
    for item in raw:
        ticker = item.strip().upper()
        if ticker and ticker not in out:
            out.append(ticker)
    return out


def load_benchmark_upload(uploaded) -> pd.DataFrame:
    if uploaded is None:
        return pd.DataFrame()
    name = uploaded.name.lower()
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(uploaded)
    return pd.read_csv(uploaded)


def apply_uploaded_benchmarks(df: pd.DataFrame, benchmarks: pd.DataFrame, margin_kind: str) -> pd.DataFrame:
    out = df.copy()
    if benchmarks is None or benchmarks.empty:
        return out
    industry_col = next((c for c in benchmarks.columns if normalize_text(c) in {"industry", "nganh", "ten nganh"}), None)
    benchmark_col = next(
        (c for c in benchmarks.columns if normalize_text(c) in {"benchmark", "industry_margin_benchmark", "bien loi nhuan nganh"}),
        None,
    )
    kind_col = next((c for c in benchmarks.columns if normalize_text(c) in {"margin_kind", "loai bien"}), None)
    if industry_col is None or benchmark_col is None:
        return out
    b = benchmarks.copy()
    if kind_col:
        b = b[(b[kind_col].astype(str).str.lower() == margin_kind.lower()) | b[kind_col].isna()]
    mapping: dict[str, float] = {}
    for _, row in b.iterrows():
        key = normalize_text(row.get(industry_col, ""))
        val = pct_to_fraction(row.get(benchmark_col))
        if key and val is not None:
            mapping[key] = val
    if "industry_margin_benchmark" not in out.columns:
        out["industry_margin_benchmark"] = np.nan
    if "industry_benchmark_source" not in out.columns:
        out["industry_benchmark_source"] = "missing"
    for idx, row in out.iterrows():
        key = normalize_text(row.get("industry", ""))
        if key in mapping:
            out.at[idx, "industry_margin_benchmark"] = mapping[key]
            out.at[idx, "industry_benchmark_source"] = "uploaded_benchmark"
    return out


def build_config(prefix: str = "screen", expanded: bool = False) -> ScreeningConfig:
    with st.expander("Bộ tiêu chí & ngưỡng lọc", expanded=expanded):
        a, b, c = st.columns(3)
        with a:
            tailwind_min = st.slider("Thiên thời tối thiểu", 0.0, 10.0, 7.0, 0.5, key=f"{prefix}_tailwind")
            hidden_min = st.slider("Tài sản ẩn tối thiểu", 0.0, 10.0, 5.0, 0.5, key=f"{prefix}_hidden")
        with b:
            growth_min = st.number_input("Tăng trưởng quý tối thiểu (%)", 0.0, 200.0, 10.0, 1.0, key=f"{prefix}_growth")
            margin_min = st.number_input("Biên lợi nhuận năm tối thiểu (%)", 0.0, 100.0, 30.0, 1.0, key=f"{prefix}_margin")
        with c:
            growth_label = st.selectbox("Chỉ tiêu tăng trưởng", ["LNST YoY", "Doanh thu YoY", "Cả hai"], key=f"{prefix}_growth_kind")
            margin_label = st.selectbox("Định nghĩa biên lợi nhuận", ["Biên gộp", "Biên ròng"], key=f"{prefix}_margin_kind")
        require_industry = st.checkbox("Bắt buộc biên lợi nhuận > benchmark ngành", value=True, key=f"{prefix}_industry")
        require_hidden = st.checkbox("Bắt buộc có bằng chứng tài sản ẩn", value=True, key=f"{prefix}_hidden_gate")
        st.caption("Điều kiện sở hữu được khóa cứng: Nhà nước/đơn vị Nhà nước phải chi phối >50%; đúng 50% vẫn không đạt.")

    growth_map = {"LNST YoY": "profit", "Doanh thu YoY": "revenue", "Cả hai": "both"}
    margin_map = {"Biên gộp": "gross", "Biên ròng": "net"}
    return ScreeningConfig(
        state_control_min=0.50,
        tailwind_min_score=tailwind_min,
        hidden_asset_min_score=hidden_min,
        quarterly_growth_min=growth_min / 100.0,
        annual_margin_min=margin_min / 100.0,
        growth_metric=growth_map[growth_label],
        margin_kind=margin_map[margin_label],
        require_industry_outperformance=require_industry,
        require_hidden_asset_gate=require_hidden,
    )


def default_demo_scored() -> pd.DataFrame:
    raw = load_demo_candidates(BASE_DIR)
    return score_dataframe(raw, ScreeningConfig())


def current_screening_or_demo() -> tuple[pd.DataFrame, str]:
    df = st.session_state.get("last_screening")
    if isinstance(df, pd.DataFrame) and not df.empty:
        return df, "Kết quả gần nhất"
    return default_demo_scored(), "Demo minh họa"


def screening_table(df: pd.DataFrame) -> None:
    view = df.copy()
    pct_cols = [
        "confidence", "state_control_pct", "roe_3y_median", "officer_ownership_pct",
        "profit_growth_yoy", "annual_margin", "industry_margin_benchmark", "dividend_yield",
    ]
    for col in pct_cols:
        if col in view.columns:
            view[col] = view[col].map(lambda x: (pct_to_fraction(x) * 100.0) if pct_to_fraction(x) is not None else np.nan)
    cols = [
        "ticker",
        "company_name",
        "industry",
        "pass_hard_filter",
        "total_score",
        "confidence",
        "state_control_pct",
        "theme_score",
        "roe_3y_median",
        "officer_ownership_pct",
        "hidden_asset_score",
        "profit_growth_yoy",
        "annual_margin",
        "industry_margin_benchmark",
        "dividend_years_paid",
        "dividend_yield",
        "fail_reasons",
    ]
    cols = [c for c in cols if c in view.columns]
    st.dataframe(
        view[cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "ticker": st.column_config.TextColumn("Mã", width="small"),
            "company_name": st.column_config.TextColumn("Doanh nghiệp", width="large"),
            "industry": st.column_config.TextColumn("Ngành"),
            "pass_hard_filter": st.column_config.CheckboxColumn("Qua lọc"),
            "total_score": st.column_config.ProgressColumn("Điểm", min_value=0, max_value=100, format="%.1f"),
            "confidence": st.column_config.ProgressColumn("Độ tin cậy", min_value=0, max_value=100, format="%.0f%%"),
            "state_control_pct": st.column_config.NumberColumn("NN chi phối", format="%.1f%%"),
            "theme_score": st.column_config.NumberColumn("Thiên thời", format="%.1f"),
            "roe_3y_median": st.column_config.NumberColumn("ROE 3Y", format="%.1f%%"),
            "officer_ownership_pct": st.column_config.NumberColumn("LĐ sở hữu", format="%.1f%%"),
            "hidden_asset_score": st.column_config.NumberColumn("TS ẩn", format="%.1f"),
            "profit_growth_yoy": st.column_config.NumberColumn("LNST YoY", format="%.1f%%"),
            "annual_margin": st.column_config.NumberColumn("Biên LN", format="%.1f%%"),
            "industry_margin_benchmark": st.column_config.NumberColumn("Benchmark", format="%.1f%%"),
            "dividend_yield": st.column_config.NumberColumn("Dividend yield", format="%.1f%%"),
            "fail_reasons": st.column_config.TextColumn("Điểm cần xử lý", width="large"),
        },
    )


def add_candidate_to_pipeline(ticker: str, row: dict[str, Any] | None = None) -> None:
    if not require_admin("Thêm mã vào Watchlist gốc"):
        return
    ticker = ticker.upper().strip()
    if not ticker:
        return
    updates: dict[str, Any] = {"status": "Ứng viên"}
    if row:
        score = safe_float(row.get("total_score"))
        updates["thesis"] = (
            f"Điểm sàng lọc {score:.1f}/100. " if score is not None else ""
        ) + str(row.get("theme_rationale") or row.get("theme_name") or "")
        updates["entry_price"] = safe_float(row.get("current_price"))
    repo.upsert_pipeline(ticker, updates)


def render_single_company(row: dict[str, Any]) -> None:
    passed = bool(row.get("pass_hard_filter"))
    pill = status_pill("QUA BỘ LỌC CỨNG" if passed else "CHƯA QUA BỘ LỌC", "pass" if passed else "fail")
    st.markdown(
        f"### {row.get('ticker', '')} — {row.get('company_name', '')} &nbsp; {pill}",
        unsafe_allow_html=True,
    )
    st.caption(f"Ngành: {row.get('industry', '—')} · Dữ liệu: {row.get('data_source', '—')} · Bên chi phối: {row.get('state_controller', '—')}")

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Điểm tổng", f"{safe_float(row.get('total_score'), 0):.1f}/100")
    k2.metric("Độ tin cậy", fmt_pct(row.get("confidence"), 0))
    k3.metric("Nhà nước chi phối", fmt_pct(row.get("state_control_pct")))
    k4.metric("LNST YoY", fmt_pct(row.get("profit_growth_yoy")))
    k5.metric("Biên lợi nhuận", fmt_pct(row.get("annual_margin")))

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Luận điểm & 6 tiêu chí",
        "Điểm thành phần",
        "Tài sản ẩn & NAV",
        "Quản trị & cổ tức",
        "Dữ liệu gốc",
    ])

    with tab1:
        c1, c2 = st.columns([1.25, 1])
        with c1:
            st.subheader("Checklist đầu tư")
            st.dataframe(criterion_table(row), hide_index=True, use_container_width=True)
            fail = str(row.get("fail_reasons") or "").strip()
            if fail:
                st.warning(f"Điểm cần xử lý trước khi xem xét đầu tư: {fail}")
            else:
                st.success("Không có hard-gate nào bị loại theo dữ liệu hiện có.")
        with c2:
            st.subheader("Luận điểm chính")
            st.write(f"**Thiên thời:** {row.get('theme_name', '—')} — {row.get('theme_rationale', 'Chưa có mô tả')}")
            st.write(f"**Sở hữu Nhà nước:** {fmt_pct(row.get('state_control_pct'))} — {row.get('state_controller', '—')}")
            st.write(f"**Tài sản ẩn:** {row.get('hidden_asset_evidence', 'Chưa có bằng chứng được lưu') or 'Chưa có bằng chứng được lưu'}")
            st.write(f"**Cổ tức:** {fmt_num(row.get('dividend_years_paid'), 0)} năm trong kỳ theo dõi; yield {fmt_pct(row.get('dividend_yield'))}.")
            if st.button("Thêm/cập nhật vào Watchlist", key=f"watch_{row.get('ticker', '')}", use_container_width=True):
                add_candidate_to_pipeline(str(row.get("ticker", "")), row)
                st.success("Đã đưa mã vào Watchlist & luận điểm.")

    with tab2:
        c1, c2 = st.columns([1, 1.2])
        with c1:
            st.plotly_chart(score_radar(row), use_container_width=True)
        with c2:
            comp = score_component_frame(row)
            st.dataframe(
                comp,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Điểm": st.column_config.NumberColumn(format="%.1f"),
                    "Tối đa": st.column_config.NumberColumn(format="%.0f"),
                    "Mức đạt (%)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
                },
            )
            st.caption("Điểm tổng là công cụ ưu tiên nghiên cứu, không thay thế việc định giá và kiểm chứng tài liệu gốc.")

    with tab3:
        st.subheader("Adjusted NAV — mô phỏng phần giá trị chưa phản ánh")
        bvps = safe_float(row.get("book_value_per_share"))
        price = safe_float(row.get("current_price"))
        total_shares = safe_float(row.get("total_shares"))
        default_book = safe_float(row.get("hidden_asset_book_bn"), 0.0) or 0.0
        default_market = safe_float(row.get("hidden_asset_market_bn"), 0.0) or 0.0
        a, b = st.columns(2)
        book_bn = a.number_input("Giá trị sổ sách tài sản ẩn (tỷ VND)", min_value=0.0, value=float(default_book), step=100.0, key=f"book_{row.get('ticker')}")
        market_bn = b.number_input("Ước tính giá trị thị trường (tỷ VND)", min_value=0.0, value=float(default_market), step=100.0, key=f"market_{row.get('ticker')}")
        surplus = max(market_bn - book_bn, 0.0)
        if bvps and total_shares and total_shares > 0:
            adjusted_nav = bvps + surplus * 1e9 / total_shares
            upside = adjusted_nav / price - 1 if price and price > 0 else None
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("BVPS", f"{bvps:,.0f}")
            m2.metric("Giá trị tăng thêm", f"{surplus:,.0f} tỷ")
            m3.metric("Adjusted NAV/cp", f"{adjusted_nav:,.0f}")
            m4.metric("Upside vs giá", "—" if upside is None else f"{upside*100:.1f}%")
        else:
            st.info("Cần có BVPS và số cổ phiếu lưu hành để tính Adjusted NAV/cp.")
        if st.button("Lưu giả định NAV", key=f"save_nav_{row.get('ticker')}"):
            repo.upsert_override(str(row.get("ticker", "")), {"hidden_asset_book_bn": book_bn, "hidden_asset_market_bn": market_bn})
            st.success("Đã lưu giả định tài sản ẩn.")

    with tab4:
        g1, g2 = st.columns(2)
        with g1:
            st.subheader("Quản trị & hiệu quả vốn")
            q = pd.DataFrame([
                {"Chỉ tiêu": "ROE trung vị 3 năm", "Giá trị": fmt_pct(row.get("roe_3y_median"))},
                {"Chỉ tiêu": "Tỷ lệ sở hữu của lãnh đạo", "Giá trị": fmt_pct(row.get("officer_ownership_pct"))},
                {"Chỉ tiêu": "Tập trung ngành chính", "Giá trị": f"{safe_float(row.get('core_focus_score'), 5):.1f}/10"},
                {"Chỉ tiêu": "Quản trị/quyền lợi cổ đông", "Giá trị": f"{safe_float(row.get('governance_score'), 5):.1f}/10"},
            ])
            st.dataframe(q, hide_index=True, use_container_width=True)
        with g2:
            st.subheader("Cổ tức")
            d = pd.DataFrame([
                {"Chỉ tiêu": "Số năm có chi trả", "Giá trị": fmt_num(row.get("dividend_years_paid"), 0)},
                {"Chỉ tiêu": "Dividend yield", "Giá trị": fmt_pct(row.get("dividend_yield"))},
                {"Chỉ tiêu": "Tiêu chí ưu tiên", "Giá trị": "Đạt" if row.get("C6_co_tuc_deu") is True else "Chưa đạt"},
            ])
            st.dataframe(d, hide_index=True, use_container_width=True)

    with tab5:
        raw_display = pd.DataFrame([row]).T.reset_index()
        raw_display.columns = ["Trường dữ liệu", "Giá trị"]
        st.dataframe(raw_display, hide_index=True, use_container_width=True, height=520)


# -------------------------
# Navigation
# -------------------------
PUBLIC_PAGES = [
    "Tổng quan",
    "Sàng lọc & xếp hạng",
    "Quét sở hữu Nhà nước",
    "Biểu đồ giá & khối lượng",
    "Phân tích doanh nghiệp",
]
ADMIN_PAGES = [
    "Soi BCTC & tài sản ẩn",
    "Watchlist & luận điểm",
    "Dữ liệu & cấu hình",
    "Lịch sử & mô hình",
]

with st.sidebar:
    st.markdown(
        """
        <div class="svs-brand">
          <div class="svs-brand-title">SONLEE STOCK</div>
          <div class="svs-brand-sub">Vietnam State Value · Hidden assets · Growth · Dividend</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    admin_password = _secret("ADMIN_PASSWORD")
    with st.expander("Quản trị", expanded=False):
        if is_admin():
            st.success("Đang ở chế độ Admin")
            if st.button("Khóa Admin", use_container_width=True):
                st.session_state["sonlee_admin"] = False
                st.rerun()
        elif admin_password:
            typed = st.text_input("Mật khẩu Admin", type="password", key="sonlee_admin_password")
            if st.button("Mở khóa", type="primary", use_container_width=True):
                import hmac
                if hmac.compare_digest(typed, admin_password):
                    st.session_state["sonlee_admin"] = True
                    st.rerun()
                else:
                    st.error("Mật khẩu chưa đúng")
        else:
            st.caption("Chế độ public/read-only. Đặt ADMIN_PASSWORD trong Streamlit Secrets để mở quyền quản trị.")

    pages = PUBLIC_PAGES + (ADMIN_PAGES if is_admin() else [])
    page = st.radio("Điều hướng", pages, label_visibility="collapsed", key="nav_page")
    st.divider()
    if is_admin():
        pipeline_count = len(repo.load_pipeline())
        runs_count = len(repo.list_runs(1000))
        st.caption(f"ADMIN · Watchlist: {pipeline_count} mã · Lịch sử: {runs_count} lần chạy")
    else:
        st.caption("VIEWER · Chỉ xem và phân tích; không sửa dữ liệu gốc")
    st.caption(f"Mã giá bắt buộc: {len(priority_tickers())} mã")
    st.caption("Công cụ nghiên cứu, không tự động đặt lệnh. Mọi kết quả cần kiểm chứng trước khi ra quyết định.")


# -------------------------
# Dashboard
# -------------------------
if page == "Tổng quan":
    page_header(
        "Trung tâm lựa chọn cổ phiếu",
        "Một màn hình để theo dõi cơ hội, chất lượng dữ liệu, các mã đang nghiên cứu và những việc còn thiếu trước khi ra quyết định.",
    )
    df, source_label = current_screening_or_demo()
    pipeline = repo.load_pipeline()
    passed = int(df.get("pass_hard_filter", pd.Series(dtype=bool)).fillna(False).sum())
    avg_conf = pd.to_numeric(df.get("confidence", pd.Series(dtype=float)), errors="coerce").mean()
    top_score = pd.to_numeric(df.get("total_score", pd.Series(dtype=float)), errors="coerce").max()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Universe đang xem", len(df), source_label)
    k2.metric("Qua bộ lọc cứng", passed)
    k3.metric("Điểm cao nhất", "—" if pd.isna(top_score) else f"{top_score:.1f}/100")
    k4.metric("Độ tin cậy TB", "—" if pd.isna(avg_conf) else f"{avg_conf*100:.0f}%")
    k5.metric("Watchlist", len(pipeline))

    info_callout("Quy trình khuyến nghị: Quét sở hữu Nhà nước → Sàng lọc 6 tiêu chí → Đào BCTC/tài sản ẩn → Phân tích một mã → đưa vào Watchlist và ghi luận điểm/rủi ro.")
    st.write("")

    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("Top cơ hội theo điểm")
        screening_table(df.head(8))
        st.plotly_chart(score_bar(df, 10), use_container_width=True)
    with right:
        st.subheader("Tình trạng nghiên cứu")
        if pipeline.empty:
            st.info("Chưa có mã trong Watchlist. Từ trang Sàng lọc hoặc Phân tích doanh nghiệp, thêm các mã cần nghiên cứu sâu.")
        else:
            counts = pipeline["status"].value_counts().reindex(PIPELINE_STATUSES, fill_value=0).reset_index()
            counts.columns = ["Trạng thái", "Số mã"]
            fig = px.bar(counts, x="Số mã", y="Trạng thái", orientation="h", text="Số mã")
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=20), yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(
                pipeline[[c for c in ["ticker", "status", "priority", "next_review", "target_price"] if c in pipeline.columns]].head(10),
                hide_index=True,
                use_container_width=True,
            )

    st.subheader("Các điểm cần ưu tiên xử lý")
    tasks = []
    if "confidence" in df.columns:
        low = df[pd.to_numeric(df["confidence"], errors="coerce") < 0.7]
        if len(low):
            tasks.append({"Ưu tiên": "Cao", "Việc cần làm": "Bổ sung dữ liệu còn thiếu", "Số mã": len(low), "Mục tiêu": "Độ tin cậy ≥70%"})
    if "C4_tai_san_an" in df.columns:
        miss_hidden = df[df["C4_tai_san_an"] != True]
        if len(miss_hidden):
            tasks.append({"Ưu tiên": "Cao", "Việc cần làm": "Đào thuyết minh BCTC để kiểm chứng tài sản ẩn", "Số mã": len(miss_hidden), "Mục tiêu": "Có bằng chứng theo trang"})
    if "C3_lanh_dao" in df.columns:
        weak_mgmt = df[df["C3_lanh_dao"] != True]
        if len(weak_mgmt):
            tasks.append({"Ưu tiên": "Trung bình", "Việc cần làm": "Rà lại quản trị, ROE, sở hữu lãnh đạo và đầu tư ngoài ngành", "Số mã": len(weak_mgmt), "Mục tiêu": "Điểm lãnh đạo đạt gate"})
    if tasks:
        st.dataframe(pd.DataFrame(tasks), hide_index=True, use_container_width=True)
    else:
        st.success("Không có hạng mục dữ liệu trọng yếu bị thiếu trong tập đang xem.")


# -------------------------
# Screener
# -------------------------
elif page == "Sàng lọc & xếp hạng":
    page_header(
        "Sàng lọc & xếp hạng",
        "Chấm điểm theo 6 tiêu chí, áp hard-gate cho 5 tiêu chí cốt lõi và ưu tiên cổ tức. Kết quả được lưu lịch sử để có thể so sánh giữa các lần chạy.",
    )
    config = build_config("screen", expanded=False)
    top1, top2 = st.columns([1.35, 1])
    with top1:
        source_mode = st.radio("Nguồn dữ liệu", ["Live vnstock", "Demo ngoại tuyến"], horizontal=True, key="screen_source")
        ticker_text = st.text_area(
            "Danh sách mã",
            value=st.session_state.get("state_candidate_tickers", ""),
            placeholder="Nhập mã cách nhau bằng dấu phẩy, khoảng trắng hoặc xuống dòng",
            height=110,
        )
    with top2:
        benchmark_mode = st.radio("Benchmark ngành", ["File benchmark đã xác minh", "Trung vị nhóm đang phân tích"], key="bench_mode")
        benchmark_upload = None
        if benchmark_mode == "File benchmark đã xác minh":
            benchmark_upload = st.file_uploader("CSV/XLSX benchmark ngành", type=["csv", "xlsx", "xls"], key="bench_upload")
        else:
            st.caption("Fallback nhanh. Không nên xem trung vị của một nhóm nhỏ là trung bình toàn ngành.")

    if st.button("CHẠY SÀNG LỌC", type="primary", use_container_width=True):
        if source_mode == "Demo ngoại tuyến":
            raw = load_demo_candidates(BASE_DIR)
        else:
            tickers = parse_tickers(ticker_text)
            if not tickers:
                st.error("Chưa có mã để phân tích. Hãy nhập mã hoặc quét universe Nhà nước trước.")
                st.stop()
            try:
                provider = get_provider()
            except VnstockUnavailable as exc:
                st.error(str(exc))
                st.stop()
            rows = []
            bar = st.progress(0.0, text="Đang lấy dữ liệu doanh nghiệp...")
            status = st.empty()
            for i, ticker in enumerate(tickers, start=1):
                status.caption(f"{ticker} · {i}/{len(tickers)}")
                try:
                    rows.append(
                        provider.get_snapshot(
                            ticker,
                            margin_kind=config.margin_kind,
                            dividend_lookback_years=config.dividend_lookback_years,
                            override=repo.override_for(ticker),
                        )
                    )
                except Exception as exc:
                    rows.append({"ticker": ticker, "data_source": "error", "error": str(exc)})
                bar.progress(i / max(len(tickers), 1), text=f"Đã xử lý {i}/{len(tickers)} mã")
            status.empty()
            raw = pd.DataFrame(rows)

        if raw.empty:
            st.warning("Không có dữ liệu để chấm điểm.")
            st.stop()

        if benchmark_mode == "File benchmark đã xác minh":
            raw = apply_uploaded_benchmarks(raw, load_benchmark_upload(benchmark_upload), config.margin_kind)
            for idx, r in raw.iterrows():
                ov = repo.override_for(str(r.get("ticker", "")))
                if ov and safe_float(ov.get("industry_margin_benchmark")) is not None:
                    raw.at[idx, "industry_margin_benchmark"] = pct_to_fraction(ov.get("industry_margin_benchmark"))
                    raw.at[idx, "industry_benchmark_source"] = "manual_override"
        else:
            raw = apply_batch_industry_benchmarks(raw, min_peers=2)

        scored = score_dataframe(raw, config)
        st.session_state["last_screening"] = scored
        st.session_state["last_run_id"] = repo.save_screening_run(
            scored,
            {"source_mode": source_mode, "benchmark_mode": benchmark_mode, "config": config.__dict__},
        )

    scored = st.session_state.get("last_screening")
    if isinstance(scored, pd.DataFrame) and not scored.empty:
        passed_df = scored[scored["pass_hard_filter"] == True].copy() if "pass_hard_filter" in scored.columns else pd.DataFrame()
        low_conf = int((pd.to_numeric(scored.get("confidence"), errors="coerce") < 0.7).sum()) if "confidence" in scored.columns else 0
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Đã phân tích", len(scored))
        q2.metric("Qua hard-gate", len(passed_df))
        q3.metric("Điểm cao nhất", f"{pd.to_numeric(scored['total_score'], errors='coerce').max():.1f}/100")
        q4.metric("Cần bổ sung dữ liệu", low_conf)

        t1, t2, t3, t4 = st.tabs(["Bảng xếp hạng", "Chỉ mã đạt", "So sánh điểm", "Xuất & Watchlist"])
        with t1:
            screening_table(scored)
        with t2:
            if passed_df.empty:
                st.info("Chưa có mã nào vượt toàn bộ hard-gate.")
            else:
                screening_table(passed_df)
        with t3:
            st.plotly_chart(score_bar(scored, 20), use_container_width=True)
            comp_cols = [
                "ticker", "score_tailwind", "score_state_control", "score_management",
                "score_hidden_assets", "score_growth_profitability", "score_dividend", "total_score",
            ]
            comp_cols = [c for c in comp_cols if c in scored.columns]
            st.dataframe(scored[comp_cols], hide_index=True, use_container_width=True)
        with t4:
            c1, c2 = st.columns(2)
            export = dataframe_to_excel_bytes({"Xep_hang": scored, "Dat_bo_loc": passed_df})
            c1.download_button("Tải Excel kết quả", export, "state_value_screener_results.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            c2.download_button("Tải CSV kết quả", scored.to_csv(index=False).encode("utf-8-sig"), "state_value_screener_results.csv", "text/csv", use_container_width=True)
            st.divider()
            ticker_choices = scored["ticker"].dropna().astype(str).tolist() if "ticker" in scored.columns else []
            if ticker_choices:
                selected = st.selectbox("Thêm nhanh vào Watchlist", ticker_choices)
                if st.button("Thêm mã đã chọn vào Watchlist", use_container_width=True):
                    r = scored[scored["ticker"].astype(str) == selected].iloc[0].to_dict()
                    add_candidate_to_pipeline(selected, r)
                    st.success(f"Đã thêm {selected} vào Watchlist.")

        st.caption("Confidence phản ánh độ đầy đủ dữ liệu đầu vào; điểm cao nhưng confidence thấp vẫn phải xác minh tài liệu gốc.")


# -------------------------
# State ownership universe
# -------------------------
elif page == "Quét sở hữu Nhà nước":
    page_header(
        "Quét sở hữu Nhà nước",
        "Tạo universe ban đầu theo điều kiện bắt buộc: Nhà nước hoặc doanh nghiệp Nhà nước nắm quyền chi phối phải lớn hơn 50%.",
    )
    info_callout("Trang này nên là bước đầu tiên khi mở rộng universe. Quét theo lô để tránh gọi quá nhiều API đồng thời và giúp kiểm soát lỗi dữ liệu.")
    try:
        provider = get_provider()
    except VnstockUnavailable as exc:
        st.error(str(exc))
        st.stop()

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Nạp danh sách cổ phiếu niêm yết", type="primary", use_container_width=True):
            with st.spinner("Đang nạp universe..."):
                st.session_state["listed_equities"] = provider.list_equities()
    with c2:
        prev = st.session_state.get("state_scan_batch")
        st.metric("Kết quả lô gần nhất", 0 if not isinstance(prev, pd.DataFrame) else len(prev))

    listed = st.session_state.get("listed_equities")
    if isinstance(listed, pd.DataFrame) and not listed.empty:
        exchange_col = next((c for c in listed.columns if normalize_text(c) == "exchange"), None)
        symbol_col = next((c for c in listed.columns if normalize_text(c) in {"symbol", "ticker", "code"}), "symbol")
        universe = listed.copy()
        if exchange_col:
            exchanges = sorted(universe[exchange_col].dropna().astype(str).unique().tolist())
            selected_ex = st.multiselect("Sàn giao dịch", exchanges, default=exchanges)
            universe = universe[universe[exchange_col].astype(str).isin(selected_ex)].copy()

        a, b = st.columns(2)
        start = a.number_input("Vị trí bắt đầu", min_value=0, max_value=max(len(universe) - 1, 0), value=0, step=25)
        batch_size = b.slider("Số mã mỗi lô", 5, 100, 25, 5)
        st.caption(f"Universe đang chọn: {len(universe):,} mã")

        if st.button("QUÉT LÔ NÀY", type="primary", use_container_width=True):
            subset = universe.iloc[int(start): int(start) + int(batch_size)]
            rows = []
            bar = st.progress(0.0)
            for i, (_, item) in enumerate(subset.iterrows(), start=1):
                ticker = str(item.get(symbol_col, "")).upper().strip()
                if not ticker:
                    continue
                try:
                    rows.append(provider.get_state_snapshot(ticker))
                except Exception as exc:
                    rows.append({"ticker": ticker, "error": str(exc)})
                bar.progress(i / max(len(subset), 1))
            st.session_state["state_scan_batch"] = pd.DataFrame(rows)

        batch_df = st.session_state.get("state_scan_batch")
        if isinstance(batch_df, pd.DataFrame) and not batch_df.empty:
            pct_series = pd.to_numeric(batch_df.get("state_control_pct"), errors="coerce")
            eligible = batch_df[pct_series > 0.50].copy()
            m1, m2, m3 = st.columns(3)
            m1.metric("Đã quét", len(batch_df))
            m2.metric("Chi phối >50%", len(eligible))
            m3.metric("Tỷ lệ đạt", f"{len(eligible)/max(len(batch_df),1)*100:.1f}%")
            batch_display = batch_df.copy()
            if "state_control_pct" in batch_display.columns:
                batch_display["state_control_pct"] = batch_display["state_control_pct"].map(
                    lambda x: (pct_to_fraction(x) * 100.0) if pct_to_fraction(x) is not None else np.nan
                )
            st.dataframe(
                batch_display,
                hide_index=True,
                use_container_width=True,
                column_config={"state_control_pct": st.column_config.NumberColumn("Tỷ lệ chi phối", format="%.1f%%")},
            )
            if not eligible.empty:
                tickers = ", ".join(eligible["ticker"].astype(str).tolist())
                st.session_state["state_candidate_tickers"] = tickers
                st.success("Danh sách mã đạt đã được chuẩn bị sẵn cho trang Sàng lọc & xếp hạng.")
                st.download_button("Tải danh sách ứng viên >50%", eligible.to_csv(index=False).encode("utf-8-sig"), "state_controlled_candidates.csv", "text/csv")


# -------------------------
# Daily candlestick + volume
# -------------------------
elif page == "Biểu đồ giá & khối lượng":
    page_header(
        "Biểu đồ giá & khối lượng",
        "Nến Nhật ngày (OHLC) và khối lượng giao dịch. Dữ liệu live được lưu cache cục bộ để vẫn xem được khi nguồn thị trường tạm thời gián đoạn.",
    )
    required = priority_tickers()
    pipeline = repo.load_pipeline()
    pipeline_tickers = pipeline["ticker"].astype(str).str.upper().tolist() if not pipeline.empty else []
    screening, _ = current_screening_or_demo()
    screening_tickers = screening["ticker"].astype(str).str.upper().tolist() if "ticker" in screening.columns else []
    ticker_options = list(dict.fromkeys(required + pipeline_tickers + screening_tickers))

    top_a, top_b, top_c = st.columns([1.1, 1, 1])
    with top_a:
        selected = st.selectbox(
            "Mã cổ phiếu",
            ticker_options,
            index=0 if ticker_options else None,
            help="13 mã anh yêu cầu luôn được ghim ở đầu danh sách.",
        ) if ticker_options else ""
        custom = st.text_input("Hoặc nhập mã khác", placeholder="Ví dụ: GVR, ACV, VGC...").upper().strip()
        ticker = custom or selected
    with top_b:
        period = st.radio("Khoảng thời gian", ["1M", "3M", "6M", "1Y", "3Y", "5Y", "MAX"], index=3, horizontal=True)
    with top_c:
        st.write("**Lớp hiển thị**")
        show_ma20 = st.checkbox("MA20", value=True)
        show_ma50 = st.checkbox("MA50", value=True)
        show_vol_ma20 = st.checkbox("Khối lượng TB20", value=True)

    ctl1, ctl2, ctl3 = st.columns([1, 1, 2])
    refresh_clicked = ctl1.button("CẬP NHẬT DỮ LIỆU", type="primary", use_container_width=True)
    use_cache_only = ctl2.checkbox("Chỉ dùng cache", value=False, help="Dùng khi không có Internet hoặc muốn xem nhanh dữ liệu đã lưu.")
    ctl3.caption("Nguồn chính: vnstock Market OHLCV 1D; fallback VCI. Cache app được lưu trong SQLite.")

    if ticker:
        start, end = period_dates(period)
        token_key = f"market_refresh_{ticker}"
        if refresh_clicked:
            st.session_state[token_key] = int(st.session_state.get(token_key, 0)) + 1
        refresh_token = int(st.session_state.get(token_key, 0))

        df_market = pd.DataFrame()
        source = "Cache cục bộ"
        live_error = None
        if not use_cache_only:
            try:
                with st.spinner(f"Đang nạp nến ngày {ticker}..."):
                    df_market, source = fetch_live_daily_ohlcv(ticker, start, end, refresh_token)
                repo.save_price_history(ticker, df_market, source=source)
            except Exception as exc:
                live_error = str(exc)

        if df_market.empty:
            df_market = repo.load_price_history(ticker, start, end)
            source = "Cache cục bộ"

        if live_error and not df_market.empty:
            st.warning(f"Nguồn live đang lỗi nên app dùng dữ liệu cache. Chi tiết: {live_error}")
        elif live_error:
            st.error(live_error)

        if not df_market.empty:
            snap = price_snapshot(df_market)
            latest_date = snap.get("date")
            st.caption(
                f"{ticker} · Phiên mới nhất trong dữ liệu: **{latest_date.strftime('%d/%m/%Y') if latest_date is not None else '—'}** · "
                f"Nguồn: **{source}** · {len(df_market):,} phiên trong khung đang xem."
            )

            k1, k2, k3, k4, k5, k6 = st.columns(6)
            close = snap.get("close")
            change_pct = snap.get("change_pct")
            k1.metric("Đóng cửa", "—" if close is None else f"{close:,.2f}", None if pd.isna(change_pct) else f"{change_pct*100:+.2f}%")
            k2.metric("Mở cửa", f"{snap.get('open', 0):,.2f}")
            k3.metric("Cao / thấp", f"{snap.get('high', 0):,.2f} / {snap.get('low', 0):,.2f}")
            k4.metric("Khối lượng", f"{snap.get('volume', 0):,.0f}")
            vr = snap.get("vol_ratio20")
            k5.metric("KL / TB20", "—" if vr is None or pd.isna(vr) else f"{vr:.2f}x")
            k6.metric("52W cao / thấp", f"{snap.get('high_52w', 0):,.2f} / {snap.get('low_52w', 0):,.2f}")

            fig = candlestick_volume_figure(
                df_market, ticker, show_ma20=show_ma20, show_ma50=show_ma50, show_vol_ma20=show_vol_ma20
            )
            st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True})

            d1, d2, d3, d4 = st.columns(4)
            d1.metric("MA20", f"{snap.get('ma20', 0):,.2f}")
            d2.metric("MA50", f"{snap.get('ma50', 0):,.2f}")
            d3.metric("ATR14", f"{snap.get('atr14', 0):,.2f}")
            d4.metric("KL TB20", f"{snap.get('avg_vol20', 0):,.0f}")

            with st.expander("Dữ liệu OHLCV chi tiết & tải xuống", expanded=False):
                display_df = df_market.copy()
                display_df["date"] = pd.to_datetime(display_df["date"]).dt.strftime("%d/%m/%Y")
                st.dataframe(display_df, use_container_width=True, hide_index=True, height=420)
                st.download_button(
                    f"Tải CSV {ticker}",
                    display_df.to_csv(index=False).encode("utf-8-sig"),
                    f"{ticker}_OHLCV_1D.csv",
                    "text/csv",
                )
        else:
            st.info("Chưa có dữ liệu giá cho mã này. Hãy bật kết nối Internet và bấm CẬP NHẬT DỮ LIỆU.")

    st.divider()
    st.subheader("13 mã bắt buộc theo dõi")
    st.caption("CKA, KSV, CSV, VEA, TMB, CST, HU4, HUD, HD8, L14, CLM, FT1, FOX luôn nằm trong danh sách ưu tiên và không phụ thuộc kết quả sàng lọc cơ bản.")
    b1, b2 = st.columns([1, 2])
    if b1.button("CẬP NHẬT 13 MÃ BẮT BUỘC", use_container_width=True):
        start_batch, end_batch = period_dates("3Y")
        rows = []
        bar = st.progress(0.0)
        try:
            provider = get_provider()
        except Exception as exc:
            provider = None
            st.error(f"Không khởi tạo được nguồn dữ liệu: {exc}")
        for i, code in enumerate(required, start=1):
            try:
                if provider is None:
                    raise RuntimeError("Nguồn dữ liệu chưa sẵn sàng")
                hist = provider.get_daily_ohlcv(code, start_batch, end_batch)
                source_name = str(hist.attrs.get("source", "vnstock"))
                repo.save_price_history(code, hist, source=source_name)
                snap = price_snapshot(hist)
                rows.append({
                    "ticker": code,
                    "latest_date": snap.get("date"),
                    "close": snap.get("close"),
                    "change_pct": snap.get("change_pct"),
                    "volume": snap.get("volume"),
                    "status": "OK",
                })
            except Exception as exc:
                rows.append({"ticker": code, "status": f"Lỗi: {exc}"})
            bar.progress(i / len(required))
        st.session_state["required_market_update"] = pd.DataFrame(rows)

    required_update = st.session_state.get("required_market_update")
    cache_status = repo.market_cache_status(required)
    if isinstance(required_update, pd.DataFrame) and not required_update.empty:
        upd = required_update.copy()
        if "change_pct" in upd.columns:
            upd["change_pct"] = pd.to_numeric(upd["change_pct"], errors="coerce") * 100
        st.dataframe(
            upd, hide_index=True, use_container_width=True,
            column_config={
                "ticker": st.column_config.TextColumn("Mã"),
                "latest_date": st.column_config.DatetimeColumn("Phiên mới nhất", format="DD/MM/YYYY"),
                "close": st.column_config.NumberColumn("Đóng cửa", format="%.2f"),
                "change_pct": st.column_config.NumberColumn("Thay đổi", format="%+.2f%%"),
                "volume": st.column_config.NumberColumn("Khối lượng", format="%.0f"),
                "status": st.column_config.TextColumn("Trạng thái"),
            },
        )
    elif not cache_status.empty:
        st.dataframe(cache_status, hide_index=True, use_container_width=True)
    else:
        st.info("Cache 13 mã đang trống. Bấm CẬP NHẬT 13 MÃ BẮT BUỘC để nạp dữ liệu lần đầu.")


# -------------------------
# Single-company research
# -------------------------
elif page == "Phân tích doanh nghiệp":
    page_header(
        "Phân tích doanh nghiệp",
        "Mổ xẻ một mã theo checklist đầu tư, điểm thành phần, quản trị, cổ tức và mô phỏng Adjusted NAV cho tài sản ẩn.",
    )
    config = build_config("single", expanded=False)
    mode = st.radio("Nguồn dữ liệu", ["Live vnstock", "Demo ngoại tuyến"], horizontal=True, key="single_mode")
    if mode == "Demo ngoại tuyến":
        demo = load_demo_candidates(BASE_DIR)
        options = demo["ticker"].astype(str).tolist()
        ticker = st.selectbox("Mã minh họa", options)
    else:
        ticker = st.text_input("Mã cổ phiếu", placeholder="Ví dụ: ABC").upper().strip()

    if st.button("PHÂN TÍCH MÃ", type="primary", use_container_width=True) and ticker:
        if mode == "Demo ngoại tuyến":
            row = demo[demo["ticker"].astype(str) == ticker].iloc[0].to_dict()
            scored = score_dataframe(pd.DataFrame([row]), config)
            st.session_state["single_analysis"] = scored.iloc[0].to_dict()
        else:
            try:
                provider = get_provider()
                snapshot = provider.get_snapshot(
                    ticker,
                    margin_kind=config.margin_kind,
                    dividend_lookback_years=config.dividend_lookback_years,
                    override=repo.override_for(ticker),
                )
                scored = score_dataframe(pd.DataFrame([snapshot]), config)
                st.session_state["single_analysis"] = scored.iloc[0].to_dict()
            except Exception as exc:
                st.error(str(exc))

    row = st.session_state.get("single_analysis")
    if isinstance(row, dict) and row:
        render_single_company(row)

        if mode == "Live vnstock":
            st.divider()
            with st.expander("Xem bảng dữ liệu gốc từ nhà cung cấp", expanded=False):
                if st.button("Nạp BCTC/cổ đông/lãnh đạo gốc", key="load_raw_detail"):
                    try:
                        provider = get_provider()
                        st.session_state["single_raw_detail"] = provider.get_raw_detail(str(row.get("ticker", "")))
                    except Exception as exc:
                        st.error(str(exc))
                details = st.session_state.get("single_raw_detail")
                if isinstance(details, dict):
                    tabs = st.tabs(list(details.keys()))
                    for tab, (name, frame) in zip(tabs, details.items()):
                        with tab:
                            if isinstance(frame, pd.DataFrame) and not frame.empty:
                                st.dataframe(frame, use_container_width=True, hide_index=True, height=420)
                            else:
                                st.caption("Không có dữ liệu.")


# -------------------------
# Hidden assets / PDF audit
# -------------------------
elif page == "Soi BCTC & tài sản ẩn":
    page_header(
        "Soi BCTC & tài sản ẩn",
        "Đọc thuyết minh PDF, tìm các điểm đáng đào sâu và lưu bằng chứng theo file/trang vào hồ sơ cổ phiếu.",
    )
    info_callout("Công cụ chỉ phát hiện dấu hiệu cần kiểm chứng; không tự kết luận tài sản bị định giá thấp. PDF scan ảnh nên OCR trước để tránh bỏ sót.")
    ticker = st.text_input("Mã cổ phiếu để gắn kết quả", key="pdf_ticker").upper().strip()
    files = st.file_uploader("Tải BCTC/thuyết minh PDF", type=["pdf"], accept_multiple_files=True)

    if st.button("QUÉT TÀI SẢN ẨN", type="primary", use_container_width=True) and files:
        all_findings = []
        summaries = []
        for file in files:
            findings, summary = pdf_hidden_asset_audit(file.getvalue())
            if not findings.empty:
                findings.insert(0, "file", file.name)
                all_findings.append(findings)
            summaries.append({"file": file.name, **summary})
        st.session_state["pdf_findings"] = pd.concat(all_findings, ignore_index=True) if all_findings else pd.DataFrame()
        st.session_state["pdf_summaries"] = pd.DataFrame(summaries)

    summary_df = st.session_state.get("pdf_summaries")
    findings_df = st.session_state.get("pdf_findings")
    if isinstance(summary_df, pd.DataFrame) and not summary_df.empty:
        overall_score = min(10.0, float(pd.to_numeric(summary_df["hidden_asset_score"], errors="coerce").sum()))
        total_hits = int(pd.to_numeric(summary_df.get("finding_count", 0), errors="coerce").fillna(0).sum()) if "finding_count" in summary_df.columns else 0
        a, b, c = st.columns(3)
        a.metric("Điểm gợi ý tài sản ẩn", f"{overall_score:.1f}/10")
        b.metric("Số phát hiện", total_hits)
        c.metric("Số PDF", len(summary_df))
        st.dataframe(summary_df, use_container_width=True, hide_index=True)
        if "text_quality" in summary_df.columns and (summary_df["text_quality"] == "low_or_scanned_pdf").any():
            st.warning("Có PDF scan/ít text. Hãy OCR trước khi dùng kết quả để giảm nguy cơ bỏ sót.")

    if isinstance(findings_df, pd.DataFrame) and not findings_df.empty:
        st.subheader("Danh sách bằng chứng cần kiểm chứng")
        st.dataframe(findings_df, use_container_width=True, hide_index=True, height=470)
        export = dataframe_to_excel_bytes({"Findings": findings_df, "Summary": summary_df})
        st.download_button("Tải Excel findings", export, "hidden_asset_findings.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if ticker:
            evidence = "; ".join(f"{r['file']} tr.{r['page']}: {r['label']}" for _, r in findings_df.head(20).iterrows())
            if st.button("Lưu điểm & bằng chứng vào hồ sơ mã", use_container_width=True):
                overall_score = min(10.0, float(pd.to_numeric(summary_df["hidden_asset_score"], errors="coerce").sum()))
                repo.upsert_override(ticker, {"hidden_asset_score": overall_score, "hidden_asset_evidence": evidence})
                repo.upsert_pipeline(ticker, {"status": "Cần kiểm chứng"})
                st.success(f"Đã lưu kết quả cho {ticker} và đưa vào trạng thái Cần kiểm chứng.")


# -------------------------
# Watchlist / research pipeline
# -------------------------
elif page == "Watchlist & luận điểm":
    page_header(
        "Watchlist & luận điểm",
        "Quản lý pipeline nghiên cứu: trạng thái, mức ưu tiên, luận điểm đầu tư, rủi ro chính và các mức giá do người dùng tự thiết lập.",
    )
    pipeline = repo.load_pipeline()
    if pipeline.empty:
        st.info("Watchlist đang trống. Có thể thêm mã từ trang Sàng lọc hoặc Phân tích doanh nghiệp.")
        seed = st.text_input("Hoặc thêm mã thủ công")
        if st.button("Thêm mã") and seed.strip():
            repo.upsert_pipeline(seed.strip().upper(), {"status": "Ứng viên"})
            st.rerun()
    else:
        counts = pipeline["status"].value_counts().reindex(PIPELINE_STATUSES, fill_value=0)
        cols = st.columns(5)
        for col, status in zip(cols, PIPELINE_STATUSES):
            col.metric(status, int(counts.get(status, 0)))

        st.subheader("Bảng điều phối nghiên cứu")
        edited = st.data_editor(
            pipeline,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="pipeline_editor",
            column_config={
                "ticker": st.column_config.TextColumn("Mã", required=True, width="small"),
                "status": st.column_config.SelectboxColumn("Trạng thái", options=PIPELINE_STATUSES, required=True),
                "priority": st.column_config.NumberColumn("Ưu tiên", min_value=1, max_value=5, step=1, help="1 = ưu tiên cao nhất"),
                "thesis": st.column_config.TextColumn("Luận điểm đầu tư", width="large"),
                "key_risk": st.column_config.TextColumn("Rủi ro chính", width="large"),
                "entry_price": st.column_config.NumberColumn("Giá tham chiếu", format="%.0f"),
                "target_price": st.column_config.NumberColumn("Mục tiêu", format="%.0f"),
                "stop_loss": st.column_config.NumberColumn("Stop-loss", format="%.0f"),
                "next_review": st.column_config.TextColumn("Ngày rà soát tiếp", help="YYYY-MM-DD"),
                "updated_at": st.column_config.TextColumn("Cập nhật", disabled=True),
            },
        )
        c1, c2 = st.columns(2)
        if c1.button("Lưu Watchlist", type="primary", use_container_width=True):
            repo.save_pipeline(edited)
            st.success("Đã lưu Watchlist.")
        c2.download_button("Xuất Watchlist CSV", edited.to_csv(index=False).encode("utf-8-sig"), "state_value_watchlist.csv", "text/csv", use_container_width=True)

        st.subheader("Risk / Reward do người dùng đặt")
        calc = edited.copy()
        for col in ["entry_price", "target_price", "stop_loss"]:
            calc[col] = pd.to_numeric(calc[col], errors="coerce")
        calc["Upside %"] = np.where(calc["entry_price"] > 0, (calc["target_price"] / calc["entry_price"] - 1) * 100, np.nan)
        calc["Downside %"] = np.where(calc["entry_price"] > 0, (calc["stop_loss"] / calc["entry_price"] - 1) * 100, np.nan)
        calc["R/R"] = np.where(calc["Downside %"] < 0, calc["Upside %"] / calc["Downside %"].abs(), np.nan)
        st.dataframe(
            calc[["ticker", "status", "entry_price", "target_price", "stop_loss", "Upside %", "Downside %", "R/R"]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "Upside %": st.column_config.NumberColumn(format="%.1f%%"),
                "Downside %": st.column_config.NumberColumn(format="%.1f%%"),
                "R/R": st.column_config.NumberColumn(format="%.2f"),
            },
        )
        st.caption("Các mức giá trong Watchlist là giả định do người dùng nhập, không phải tín hiệu mua/bán tự động của app.")


# -------------------------
# Data & settings
# -------------------------
elif page == "Dữ liệu & cấu hình":
    page_header(
        "Dữ liệu & cấu hình",
        "Quản lý các dữ liệu có tính bằng chứng: override từng mã, rule thiên thời, registry đơn vị Nhà nước và benchmark ngành.",
    )
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Override theo mã",
        "Thiên thời",
        "Registry Nhà nước",
        "Benchmark ngành",
        "Mã bắt buộc",
        "Sao lưu dữ liệu",
    ])

    with tab1:
        overrides = repo.load_overrides()
        edited = st.data_editor(overrides, num_rows="dynamic", use_container_width=True, hide_index=True, key="override_editor")
        if st.button("Lưu override", type="primary"):
            repo.save_overrides(edited)
            st.success("Đã lưu dữ liệu định tính/ghi đè.")
        st.download_button("Xuất override CSV", edited.to_csv(index=False).encode("utf-8-sig"), "manual_overrides.csv", "text/csv")

    with tab2:
        rules = read_csv(TAILWIND_PATH)
        edited_rules = st.data_editor(rules, num_rows="dynamic", use_container_width=True, hide_index=True, key="tailwind_editor")
        if st.button("Lưu quy tắc thiên thời"):
            save_csv(edited_rules, TAILWIND_PATH)
            st.success("Đã lưu rule thiên thời.")

    with tab3:
        registry = read_csv(STATE_REGISTRY_PATH)
        edited_registry = st.data_editor(registry, num_rows="dynamic", use_container_width=True, hide_index=True, key="state_registry_editor")
        if st.button("Lưu registry Nhà nước"):
            save_csv(edited_registry, STATE_REGISTRY_PATH)
            st.success("Đã lưu registry.")

    with tab4:
        benchmark = read_csv(BENCHMARK_TEMPLATE_PATH)
        st.write("Template chuẩn cho benchmark ngành. Nên điền nguồn và ngày cập nhật để truy vết.")
        edited_bench = st.data_editor(benchmark, num_rows="dynamic", use_container_width=True, hide_index=True, key="bench_editor")
        if st.button("Lưu benchmark template"):
            save_csv(edited_bench, BENCHMARK_TEMPLATE_PATH)
            st.success("Đã lưu benchmark.")
        st.download_button("Tải template benchmark", edited_bench.to_csv(index=False).encode("utf-8-sig"), "industry_benchmarks.csv", "text/csv")

    with tab5:
        st.write("Danh sách mã luôn được ghim ở trang Biểu đồ giá, không phụ thuộc kết quả sàng lọc.")
        priority_df = read_csv(PRIORITY_TICKERS_PATH)
        edited_priority = st.data_editor(priority_df, num_rows="dynamic", use_container_width=True, hide_index=True, key="priority_editor")
        if st.button("Lưu danh sách mã bắt buộc"):
            if "ticker" in edited_priority.columns:
                edited_priority["ticker"] = edited_priority["ticker"].astype(str).str.upper().str.strip()
                edited_priority = edited_priority[edited_priority["ticker"] != ""].drop_duplicates("ticker")
            save_csv(edited_priority, PRIORITY_TICKERS_PATH)
            st.success("Đã lưu danh sách mã bắt buộc.")

    with tab6:
        st.write("Cơ sở dữ liệu SQLite chứa override, lịch sử sàng lọc, Watchlist và cache OHLCV.")
        if DB_PATH.exists():
            st.download_button("Tải bản sao SQLite", DB_PATH.read_bytes(), "stock_selector_backup.db", "application/octet-stream")
        data_files = [TAILWIND_PATH, STATE_REGISTRY_PATH, BENCHMARK_TEMPLATE_PATH, PRIORITY_TICKERS_PATH]
        manifest = pd.DataFrame([
            {"Tệp": p.name, "Tồn tại": p.exists(), "Kích thước (KB)": round(p.stat().st_size / 1024, 1) if p.exists() else 0}
            for p in data_files
        ])
        st.dataframe(manifest, hide_index=True, use_container_width=True)


# -------------------------
# History & scoring model
# -------------------------
elif page == "Lịch sử & mô hình":
    page_header(
        "Lịch sử & mô hình chấm điểm",
        "Xem lại các lần chạy, đối chiếu kết quả cũ và hiểu rõ cách mỗi tiêu chí đóng góp vào điểm tổng.",
    )
    runs = repo.list_runs(50)
    if runs.empty:
        st.info("Chưa có lần sàng lọc nào được lưu.")
    else:
        st.subheader("Các lần chạy gần nhất")
        st.dataframe(runs[["run_id", "created_at", "row_count"]], use_container_width=True, hide_index=True)
        run_id = st.selectbox("Mở lần chạy", runs["run_id"].tolist())
        if run_id:
            old = repo.load_run(int(run_id))
            if not old.empty:
                screening_table(old)
                st.plotly_chart(score_bar(old, 15), use_container_width=True)
                settings = runs.loc[runs["run_id"] == run_id, "settings_json"].iloc[0]
                with st.expander("Thiết lập của lần chạy"):
                    try:
                        st.json(json.loads(settings))
                    except Exception:
                        st.code(settings)

    st.subheader("Mô hình 100 điểm")
    model = pd.DataFrame([
        {"Tiêu chí": "Thiên thời", "Trọng số": 20, "Hard-gate": "Có", "Ý nghĩa": "Ngành còn dư địa, không suy thoái/bão hòa"},
        {"Tiêu chí": "Nhà nước chi phối", "Trọng số": 15, "Hard-gate": "Có", "Ý nghĩa": "Bắt buộc tỷ lệ >50%"},
        {"Tiêu chí": "Lãnh đạo", "Trọng số": 20, "Hard-gate": "Có", "Ý nghĩa": "ROE, sở hữu lãnh đạo, tập trung ngành chính, quản trị"},
        {"Tiêu chí": "Tài sản ẩn", "Trọng số": 15, "Hard-gate": "Có thể bật/tắt", "Ý nghĩa": "Bằng chứng từ thuyết minh và định giá lại"},
        {"Tiêu chí": "Tăng trưởng & biên LN", "Trọng số": 20, "Hard-gate": "Có", "Ý nghĩa": "Tăng trưởng quý, biên năm và benchmark ngành"},
        {"Tiêu chí": "Cổ tức", "Trọng số": 10, "Hard-gate": "Không", "Ý nghĩa": "Ưu tiên tính đều đặn và dividend yield"},
    ])
    st.dataframe(model, hide_index=True, use_container_width=True)
    st.warning("App là hệ thống sàng lọc, quản trị bằng chứng và tổ chức quy trình nghiên cứu; không phải hệ thống đảm bảo lợi nhuận hay lệnh giao dịch tự động.")
