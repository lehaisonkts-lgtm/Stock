from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .config import ScreeningConfig
from .utils import pct_to_fraction, safe_float, to_bool


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _ratio_score(value: float | None, floor: float, full: float) -> float:
    if value is None or math.isnan(value):
        return 0.0
    if full <= floor:
        return 1.0 if value >= full else 0.0
    return _clamp((value - floor) / (full - floor))


def _management_score(metrics: dict[str, Any]) -> float:
    """0-1 management score built from auditable proxies.

    ROE / capital efficiency: 40%
    Officer ownership: 30%
    Core-business focus (manual/evidence-backed): 20%
    Governance / shareholder alignment (manual/evidence-backed): 10%
    """
    roe = pct_to_fraction(metrics.get("roe_3y_median"))
    officer = pct_to_fraction(metrics.get("officer_ownership_pct"))
    core = safe_float(metrics.get("core_focus_score"), 5.0)
    gov = safe_float(metrics.get("governance_score"), 5.0)

    roe_component = _ratio_score(roe, 0.08, 0.25)
    officer_component = _ratio_score(officer, 0.00, 0.15)
    core_component = _clamp((core or 0.0) / 10.0)
    gov_component = _clamp((gov or 0.0) / 10.0)
    return 0.40 * roe_component + 0.30 * officer_component + 0.20 * core_component + 0.10 * gov_component


def _growth_profitability_score(metrics: dict[str, Any], config: ScreeningConfig) -> float:
    rev_g = pct_to_fraction(metrics.get("revenue_growth_yoy"))
    profit_g = pct_to_fraction(metrics.get("profit_growth_yoy"))
    margin = pct_to_fraction(metrics.get("annual_margin"))
    benchmark = pct_to_fraction(metrics.get("industry_margin_benchmark"))

    rev_score = _ratio_score(rev_g, 0.0, 0.30)
    profit_score = _ratio_score(profit_g, 0.0, 0.30)
    margin_score = _ratio_score(margin, 0.15, 0.50)

    if benchmark is None or margin is None:
        outperform_score = 0.0
    elif benchmark <= 0:
        outperform_score = 1.0 if margin > benchmark else 0.0
    else:
        outperform_score = _clamp((margin / benchmark - 0.90) / 0.60)

    return 0.20 * rev_score + 0.35 * profit_score + 0.25 * margin_score + 0.20 * outperform_score


def _dividend_score(metrics: dict[str, Any], config: ScreeningConfig) -> float:
    years_paid = safe_float(metrics.get("dividend_years_paid"), 0.0) or 0.0
    lookback = max(config.dividend_lookback_years, 1)
    consistency = _clamp(years_paid / lookback)
    dy = pct_to_fraction(metrics.get("dividend_yield"))
    yield_score = _ratio_score(dy, 0.0, 0.06)
    return 0.70 * consistency + 0.30 * yield_score


def evaluate_candidate(metrics: dict[str, Any], config: ScreeningConfig | None = None) -> dict[str, Any]:
    config = config or ScreeningConfig()
    config.validate()

    tailwind_score = safe_float(metrics.get("theme_score"), 0.0) or 0.0
    decline_flag = to_bool(metrics.get("decline_flag", False), False)
    state_control = pct_to_fraction(metrics.get("state_control_pct"))
    hidden_score = safe_float(metrics.get("hidden_asset_score"), 0.0) or 0.0
    revenue_growth = pct_to_fraction(metrics.get("revenue_growth_yoy"))
    profit_growth = pct_to_fraction(metrics.get("profit_growth_yoy"))
    annual_margin = pct_to_fraction(metrics.get("annual_margin"))
    industry_margin = pct_to_fraction(metrics.get("industry_margin_benchmark"))

    criteria: dict[str, bool | None] = {}
    criteria["C1_thien_thoi"] = (tailwind_score >= config.tailwind_min_score) and not decline_flag
    criteria["C2_nha_nuoc_chi_phoi"] = state_control is not None and state_control > config.state_control_min

    management_fraction = _management_score(metrics)
    # Management is scored, but not a hard quantitative gate because "tam/tam" is partly qualitative.
    criteria["C3_lanh_dao"] = management_fraction >= 0.55

    if config.require_hidden_asset_gate:
        criteria["C4_tai_san_an"] = hidden_score >= config.hidden_asset_min_score
    else:
        criteria["C4_tai_san_an"] = None

    if config.growth_metric == "profit":
        growth_ok = profit_growth is not None and profit_growth > config.quarterly_growth_min
    elif config.growth_metric == "revenue":
        growth_ok = revenue_growth is not None and revenue_growth > config.quarterly_growth_min
    else:
        growth_ok = (
            revenue_growth is not None
            and profit_growth is not None
            and revenue_growth > config.quarterly_growth_min
            and profit_growth > config.quarterly_growth_min
        )

    margin_ok = annual_margin is not None and annual_margin > config.annual_margin_min
    if config.require_industry_outperformance:
        industry_ok = industry_margin is not None and annual_margin is not None and annual_margin > industry_margin
    else:
        industry_ok = True
    criteria["C5_tang_truong_bien_loi_nhuan"] = bool(growth_ok and margin_ok and industry_ok)

    # User said dividend is preferred, not mandatory.
    dividend_years = safe_float(metrics.get("dividend_years_paid"), 0.0) or 0.0
    criteria["C6_co_tuc_deu"] = dividend_years >= max(3, config.dividend_lookback_years - 1)

    tailwind_fraction = _clamp(tailwind_score / 10.0)
    state_fraction = 1.0 if (state_control is not None and state_control > config.state_control_min) else 0.0
    hidden_fraction = _clamp(hidden_score / 10.0)
    growth_fraction = _growth_profitability_score(metrics, config)
    dividend_fraction = _dividend_score(metrics, config)

    components = {
        "tailwind": tailwind_fraction * config.weights["tailwind"],
        "state_control": state_fraction * config.weights["state_control"],
        "management": management_fraction * config.weights["management"],
        "hidden_assets": hidden_fraction * config.weights["hidden_assets"],
        "growth_profitability": growth_fraction * config.weights["growth_profitability"],
        "dividend": dividend_fraction * config.weights["dividend"],
    }
    total_score = sum(components.values())

    # Hard gates: 1,2,3,4,5. Dividend stays preference/score only.
    hard_keys = ["C1_thien_thoi", "C2_nha_nuoc_chi_phoi", "C3_lanh_dao", "C5_tang_truong_bien_loi_nhuan"]
    if config.require_hidden_asset_gate:
        hard_keys.append("C4_tai_san_an")
    pass_hard = all(criteria[k] is True for k in hard_keys)

    critical_fields = [
        "theme_score",
        "state_control_pct",
        "roe_3y_median",
        "officer_ownership_pct",
        "hidden_asset_score",
        "profit_growth_yoy" if config.growth_metric != "revenue" else "revenue_growth_yoy",
        "annual_margin",
        "industry_margin_benchmark",
        "dividend_years_paid",
    ]
    available = 0
    for field in critical_fields:
        value = metrics.get(field)
        if value is not None and not (isinstance(value, float) and np.isnan(value)) and str(value).strip() != "":
            available += 1
    confidence = available / len(critical_fields)

    fail_reasons: list[str] = []
    labels = {
        "C1_thien_thoi": "Ngành chưa đạt ngưỡng thiên thời / bị đánh dấu suy giảm",
        "C2_nha_nuoc_chi_phoi": "Tỷ lệ Nhà nước/đơn vị Nhà nước chi phối chưa >50% hoặc thiếu bằng chứng",
        "C3_lanh_dao": "Điểm quản trị/lãnh đạo dưới ngưỡng 55%",
        "C4_tai_san_an": "Chưa có đủ bằng chứng tài sản ẩn",
        "C5_tang_truong_bien_loi_nhuan": "Tăng trưởng/biên lợi nhuận chưa đạt hoặc chưa vượt benchmark ngành",
    }
    for key in hard_keys:
        if criteria.get(key) is not True:
            fail_reasons.append(labels[key])

    return {
        **criteria,
        "pass_hard_filter": pass_hard,
        "total_score": round(total_score, 2),
        "confidence": round(confidence, 3),
        "fail_reasons": "; ".join(fail_reasons),
        **{f"score_{k}": round(v, 2) for k, v in components.items()},
    }


def apply_batch_industry_benchmarks(df: pd.DataFrame, min_peers: int = 2) -> pd.DataFrame:
    """Fallback benchmark: median annual margin among analyzed peers in the same industry.

    This is not a full-market industry average; the UI labels it explicitly as a fallback.
    """
    out = df.copy()
    if "industry" not in out.columns or "annual_margin" not in out.columns:
        out["industry_margin_benchmark"] = np.nan
        out["industry_benchmark_source"] = "missing"
        return out

    out["annual_margin"] = pd.to_numeric(out["annual_margin"], errors="coerce")
    counts = out.groupby("industry")["annual_margin"].transform("count")
    medians = out.groupby("industry")["annual_margin"].transform("median")
    out["industry_margin_benchmark"] = np.where(counts >= min_peers, medians, np.nan)
    out["industry_benchmark_source"] = np.where(counts >= min_peers, "batch_median", "insufficient_peers")
    return out


def score_dataframe(df: pd.DataFrame, config: ScreeningConfig | None = None) -> pd.DataFrame:
    config = config or ScreeningConfig()
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        metrics = row.to_dict()
        rows.append({**metrics, **evaluate_candidate(metrics, config)})
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["pass_hard_filter", "total_score", "confidence"], ascending=[False, False, False])
    return out.reset_index(drop=True)
