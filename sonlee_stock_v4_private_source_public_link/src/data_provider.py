from __future__ import annotations

import math
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .market_chart import normalize_ohlcv
from .utils import (
    find_first_value,
    first_existing_col,
    nonempty,
    normalize_text,
    parse_period_label,
    pct_to_fraction,
    safe_float,
    to_bool,
)


REVENUE_LABELS = [
    "Doanh thu thuần",
    "Doanh thu bán hàng và cung cấp dịch vụ",
    "Net revenue",
    "Revenue",
    "Tổng thu nhập hoạt động",
]
NET_PROFIT_LABELS = [
    "Lợi nhuận sau thuế của cổ đông công ty mẹ",
    "Lợi nhuận sau thuế thu nhập doanh nghiệp",
    "Lợi nhuận sau thuế",
    "Net profit after tax",
    "Profit after tax",
]
GROSS_PROFIT_LABELS = [
    "Lợi nhuận gộp về bán hàng và cung cấp dịch vụ",
    "Lợi nhuận gộp",
    "Gross profit",
]
EQUITY_LABELS = [
    "Vốn chủ sở hữu",
    "Nguồn vốn chủ sở hữu",
    "Owners' equity",
    "Equity",
]


class VnstockUnavailable(RuntimeError):
    pass


class VnstockProvider:
    """Thin compatibility layer around vnstock >=4.x Unified UI.

    All imports are lazy so the rest of the project can be tested offline.
    """

    def __init__(self, state_registry: pd.DataFrame | None = None, tailwind_rules: pd.DataFrame | None = None):
        try:
            from vnstock import Fundamental, Market, Reference, Vnstock  # type: ignore
        except Exception as exc:
            raise VnstockUnavailable(
                "Không import được vnstock. Chạy: pip install -r requirements.txt"
            ) from exc
        self.Reference = Reference
        self.Fundamental = Fundamental
        self.Market = Market
        self.Vnstock = Vnstock
        self.ref = Reference()
        self.fun = Fundamental()
        self.mkt = Market()
        self.state_registry = state_registry if state_registry is not None else pd.DataFrame()
        self.tailwind_rules = tailwind_rules if tailwind_rules is not None else pd.DataFrame()
        self._industry_cache: pd.DataFrame | None = None

    @staticmethod
    def _as_df(value: Any) -> pd.DataFrame:
        if value is None:
            return pd.DataFrame()
        if isinstance(value, pd.DataFrame):
            return value.copy()
        try:
            return pd.DataFrame(value)
        except Exception:
            return pd.DataFrame()

    def list_equities(self) -> pd.DataFrame:
        try:
            df = self._as_df(self.ref.equity.list_by_exchange())
        except Exception:
            df = self._as_df(self.ref.equity.list())
        if "symbol" in df.columns:
            df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
        return df

    def industry_map(self) -> pd.DataFrame:
        if self._industry_cache is not None:
            return self._industry_cache.copy()
        try:
            df = self._as_df(self.ref.industry.sectors())
        except Exception:
            df = pd.DataFrame()
        if not df.empty and "symbol" in df.columns:
            df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
        self._industry_cache = df
        return df.copy()

    def _company_frames(self, ticker: str) -> dict[str, pd.DataFrame]:
        company = self.ref.company(ticker)
        out: dict[str, pd.DataFrame] = {}
        calls = {
            "info": lambda: company.info(),
            "shareholders_detailed": lambda: company.shareholders(mode="detailed"),
            "shareholders_summary": lambda: company.shareholders(mode="summary"),
            "officers": lambda: company.officers(),
            "events": lambda: company.events(),
            "subsidiaries": lambda: company.subsidiaries(),
        }
        for key, fn in calls.items():
            try:
                out[key] = self._as_df(fn())
            except Exception:
                out[key] = pd.DataFrame()
        return out

    def _financial_frames(self, ticker: str) -> dict[str, pd.DataFrame]:
        equity = self.fun.equity(ticker)
        out: dict[str, pd.DataFrame] = {}
        calls = {
            "income_quarter": lambda: equity.income_statement(period="quarter", orient="report"),
            "income_year": lambda: equity.income_statement(period="year", orient="report"),
            "balance_year": lambda: equity.balance_sheet(period="year", orient="report"),
            "ratio_year_ts": lambda: equity.ratio(period="year", orient="time_series"),
            "ratio_quarter_ts": lambda: equity.ratio(period="quarter", orient="time_series"),
        }
        for key, fn in calls.items():
            try:
                out[key] = self._as_df(fn())
            except Exception:
                out[key] = pd.DataFrame()
        return out

    def _market_frames(self, ticker: str) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        try:
            out["quote"] = self._as_df(self.mkt.equity(ticker).quote())
        except Exception:
            out["quote"] = pd.DataFrame()
        return out

    def get_daily_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """Fetch daily OHLCV with a current Market-layer call and a legacy VCI fallback.

        Returned columns are normalized to: date, open, high, low, close, volume.
        """
        ticker = str(ticker).upper().strip()
        if not ticker:
            raise ValueError("Ticker is required")

        errors: list[str] = []
        raw = pd.DataFrame()
        source = "vnstock.Market"
        try:
            raw = self._as_df(
                self.mkt.equity(ticker).ohlcv(start=start, end=end, interval="1D")
            )
        except Exception as exc:
            errors.append(f"Market: {exc}")

        if raw.empty:
            source = "vnstock.VCI fallback"
            try:
                stock = self.Vnstock().stock(symbol=ticker, source="VCI")
                raw = self._as_df(
                    stock.quote.history(start=start, end=end, interval="1D")
                )
            except Exception as exc:
                errors.append(f"VCI fallback: {exc}")

        out = normalize_ohlcv(raw)
        if out.empty:
            detail = " | ".join(errors[-2:]) if errors else "Không có bản ghi OHLCV."
            raise RuntimeError(f"Không lấy được dữ liệu nến ngày cho {ticker}. {detail}")
        out.attrs["source"] = source
        out.attrs["ticker"] = ticker
        return out

    @staticmethod
    def _first_record(df: pd.DataFrame) -> dict[str, Any]:
        if df is None or df.empty:
            return {}
        return df.iloc[0].to_dict()

    @staticmethod
    def _match_report_row(df: pd.DataFrame, labels: Iterable[str]) -> pd.Series | None:
        if df is None or df.empty:
            return None
        item_col = first_existing_col(df, ["item", "item_en", "chỉ tiêu", "chi tieu", "name"])
        if item_col is None:
            return None
        normalized_labels = [normalize_text(x) for x in labels]
        best_idx = None
        best_score = -1
        for idx, value in df[item_col].items():
            text = normalize_text(value)
            score = 0
            for label in normalized_labels:
                if text == label:
                    score = max(score, 100)
                elif label in text or text in label:
                    score = max(score, 70)
                else:
                    tokens = set(label.split())
                    if tokens:
                        overlap = len(tokens & set(text.split())) / len(tokens)
                        score = max(score, int(overlap * 50))
            if score > best_score:
                best_score = score
                best_idx = idx
        if best_idx is None or best_score < 35:
            return None
        return df.loc[best_idx]

    @staticmethod
    def _report_period_values(df: pd.DataFrame, labels: Iterable[str]) -> dict[tuple[int, int], float]:
        row = VnstockProvider._match_report_row(df, labels)
        if row is None:
            return {}
        metadata = {
            "item", "item_en", "unit", "ticker", "symbol", "name", "chỉ tiêu", "chi tieu",
            "group", "category", "code", "level"
        }
        out: dict[tuple[int, int], float] = {}
        for col, value in row.items():
            if normalize_text(col) in {normalize_text(x) for x in metadata}:
                continue
            period = parse_period_label(col)
            number = safe_float(value)
            if period and number is not None:
                out[period] = number
        return out

    @staticmethod
    def _latest_and_yoy(values: dict[tuple[int, int], float]) -> tuple[float | None, float | None, str]:
        if not values:
            return None, None, "missing"
        quarters = [p for p in values if p[1] in {1, 2, 3, 4}]
        if not quarters:
            return None, None, "missing_quarter_period"
        latest = max(quarters)
        latest_val = values.get(latest)
        prior = (latest[0] - 1, latest[1])
        prior_val = values.get(prior)
        if latest_val is None:
            return None, None, "missing"
        if prior_val is not None and prior_val != 0:
            return latest_val, latest_val / prior_val - 1.0, f"YoY {latest[0]}Q{latest[1]} vs {prior[0]}Q{prior[1]}"
        # fallback to previous quarter, clearly labelled QoQ
        prev_q = (latest[0] - 1, 4) if latest[1] == 1 else (latest[0], latest[1] - 1)
        prev_val = values.get(prev_q)
        if prev_val is not None and prev_val != 0:
            return latest_val, latest_val / prev_val - 1.0, f"QoQ fallback {latest[0]}Q{latest[1]}"
        return latest_val, None, "missing_comparison_period"

    @staticmethod
    def _latest_annual_ratio(numerator: dict[tuple[int, int], float], denominator: dict[tuple[int, int], float]) -> tuple[float | None, str]:
        annual_periods = sorted(set(numerator) & set(denominator), reverse=True)
        annual_periods = [p for p in annual_periods if p[1] == 0]
        for period in annual_periods:
            den = denominator.get(period)
            num = numerator.get(period)
            if den not in (None, 0) and num is not None:
                return num / den, str(period[0])
        return None, "missing"

    @staticmethod
    def _latest_ratio_record(df: pd.DataFrame) -> dict[str, Any]:
        if df is None or df.empty:
            return {}
        sort_cols = [c for c in df.columns if normalize_text(c) in {"year", "quarter", "period", "report_period", "date"}]
        work = df.copy()
        if sort_cols:
            for c in sort_cols:
                work[c] = work[c].astype(str)
            try:
                work = work.sort_values(sort_cols, ascending=False)
            except Exception:
                pass
        return work.iloc[0].to_dict()

    @staticmethod
    def _extract_company_name(info: dict[str, Any], ticker: str) -> str:
        return str(find_first_value(info, ["organ_name", "company_name", "name", "short_name", "organ_short_name"], ticker))

    def _extract_industry(self, ticker: str, info: dict[str, Any]) -> tuple[str, str]:
        direct = find_first_value(
            info,
            ["icb_name_lv2", "icb_name_lv3", "icb_name_lv4", "industry", "industry_name", "icb_name"],
        )
        if nonempty(direct):
            return str(direct), "company_info"
        industries = self.industry_map()
        if industries.empty or "symbol" not in industries.columns:
            return "Chưa phân loại", "missing"
        rows = industries[industries["symbol"] == ticker]
        if rows.empty:
            return "Chưa phân loại", "missing"
        level_col = first_existing_col(rows, ["icb_level"])
        if level_col is not None:
            rows = rows.copy()
            rows[level_col] = pd.to_numeric(rows[level_col], errors="coerce")
            # Level 2 is a practical benchmark level; otherwise take the deepest available.
            lvl2 = rows[rows[level_col] == 2]
            if not lvl2.empty:
                rows = lvl2
            else:
                rows = rows.sort_values(level_col, ascending=False)
        name_col = first_existing_col(rows, ["icb_name", "industry_name", "name"])
        if name_col is None:
            return "Chưa phân loại", "missing"
        return str(rows.iloc[0][name_col]), "industry_map"

    @staticmethod
    def _match_state_entity(name: str, registry: pd.DataFrame) -> tuple[bool, str]:
        if registry is None or registry.empty:
            return False, ""
        name_norm = normalize_text(name)
        pattern_col = first_existing_col(registry, ["pattern", "name_pattern", "regex"])
        label_col = first_existing_col(registry, ["entity", "label", "state_entity"])
        if pattern_col is None:
            return False, ""
        for _, row in registry.iterrows():
            pattern = str(row.get(pattern_col, "")).strip()
            if not pattern:
                continue
            try:
                matched = re.search(pattern, name, flags=re.IGNORECASE) is not None
            except re.error:
                matched = normalize_text(pattern) in name_norm
            if matched:
                label = str(row.get(label_col, pattern)) if label_col else pattern
                return True, label
        return False, ""

    def _detect_state_control(self, summary: pd.DataFrame, detailed: pd.DataFrame) -> dict[str, Any]:
        candidates: list[tuple[float, str, str]] = []
        if summary is not None and not summary.empty:
            # VCI summary: single row with state_percentage.
            if "state_percentage" in summary.columns:
                val = pct_to_fraction(summary.iloc[0]["state_percentage"])
                if val is not None:
                    candidates.append((val, "Nhà nước (tổng hợp)", "shareholders.summary.state_percentage"))
            # KBS summary: one row per owner_type.
            type_col = first_existing_col(summary, ["owner_type", "ownership_type", "name"])
            pct_col = first_existing_col(summary, ["ownership_percentage", "rate", "percentage"])
            if type_col and pct_col:
                for _, row in summary.iterrows():
                    owner_type = normalize_text(row.get(type_col))
                    if "nha nuoc" in owner_type or "state" in owner_type:
                        val = pct_to_fraction(row.get(pct_col))
                        if val is not None:
                            candidates.append((val, "Nhà nước (tổng hợp)", "shareholders.summary.owner_type"))

        if detailed is not None and not detailed.empty:
            name_col = first_existing_col(detailed, ["name", "shareholder", "owner_name"])
            pct_col = first_existing_col(detailed, ["rate", "ownership_percentage", "percentage"])
            if name_col and pct_col:
                for _, row in detailed.iterrows():
                    holder = str(row.get(name_col, ""))
                    rate = pct_to_fraction(row.get(pct_col))
                    if rate is None:
                        continue
                    is_state, label = self._match_state_entity(holder, self.state_registry)
                    if is_state:
                        candidates.append((rate, holder or label, "shareholders.detailed.state_parent_registry"))

        if not candidates:
            return {
                "state_control_pct": None,
                "state_controller": "",
                "state_detection_method": "missing",
            }
        best = max(candidates, key=lambda x: x[0])
        return {
            "state_control_pct": best[0],
            "state_controller": best[1],
            "state_detection_method": best[2],
        }

    @staticmethod
    def _officer_ownership(officers: pd.DataFrame) -> float | None:
        if officers is None or officers.empty:
            return None
        name_col = first_existing_col(officers, ["name", "officer_name"])
        pct_col = first_existing_col(officers, ["rate", "ownership_percentage", "percentage"])
        if name_col is None or pct_col is None:
            return None
        values: dict[str, float] = {}
        for _, row in officers.iterrows():
            name = normalize_text(row.get(name_col))
            pct = pct_to_fraction(row.get(pct_col))
            if not name or pct is None:
                continue
            values[name] = max(values.get(name, 0.0), pct)
        return sum(values.values()) if values else None

    @staticmethod
    def _dividend_metrics(events: pd.DataFrame, lookback: int = 5) -> dict[str, Any]:
        if events is None or events.empty:
            return {"dividend_years_paid": 0, "cash_dividend_ps_lookback": 0.0, "dividend_event_count": 0}
        current_year = date.today().year
        min_year = current_year - lookback + 1
        years: set[int] = set()
        total_cash = 0.0
        count = 0
        for _, row in events.iterrows():
            blob = " | ".join(str(v) for v in row.values if v is not None)
            norm = normalize_text(blob)
            if "co tuc" not in norm and "dividend" not in norm:
                continue
            year = None
            for key in ["exright_date", "record_date", "public_date", "display_date1", "date"]:
                if key in row.index and nonempty(row.get(key)):
                    m = re.search(r"(20\d{2})", str(row.get(key)))
                    if m:
                        year = int(m.group(1))
                        break
            if year is None:
                m = re.search(r"(20\d{2})", blob)
                if m:
                    year = int(m.group(1))
            if year is not None and min_year <= year <= current_year:
                years.add(year)
                count += 1
                cash = find_first_value(row.to_dict(), ["value_per_share", "value", "cash_dividend", "dividend"])
                cash_num = safe_float(cash, 0.0) or 0.0
                if cash_num > 0:
                    total_cash += cash_num
        return {
            "dividend_years_paid": len(years),
            "cash_dividend_ps_lookback": total_cash,
            "dividend_event_count": count,
        }

    def _tailwind_match(self, industry: str, company_name: str) -> dict[str, Any]:
        if self.tailwind_rules is None or self.tailwind_rules.empty:
            return {
                "theme_score": 5.0,
                "theme_name": "Chưa cấu hình",
                "theme_rationale": "Cần cập nhật bảng thiên thời.",
                "theme_source": "",
                "decline_flag": False,
            }
        pattern_col = first_existing_col(self.tailwind_rules, ["pattern", "industry_regex", "regex"])
        score_col = first_existing_col(self.tailwind_rules, ["score", "theme_score"])
        theme_col = first_existing_col(self.tailwind_rules, ["theme", "theme_name"])
        rationale_col = first_existing_col(self.tailwind_rules, ["rationale", "reason"])
        source_col = first_existing_col(self.tailwind_rules, ["source", "source_url"])
        decline_col = first_existing_col(self.tailwind_rules, ["decline_flag", "declining"])
        priority_col = first_existing_col(self.tailwind_rules, ["priority"])
        rules = self.tailwind_rules.copy()
        if priority_col:
            rules[priority_col] = pd.to_numeric(rules[priority_col], errors="coerce").fillna(999)
            rules = rules.sort_values(priority_col)
        haystack = f"{industry} | {company_name}"
        for _, row in rules.iterrows():
            pattern = str(row.get(pattern_col, "")).strip() if pattern_col else ""
            if not pattern:
                continue
            try:
                matched = re.search(pattern, haystack, flags=re.IGNORECASE) is not None
            except re.error:
                matched = normalize_text(pattern) in normalize_text(haystack)
            if matched:
                return {
                    "theme_score": safe_float(row.get(score_col), 5.0) if score_col else 5.0,
                    "theme_name": str(row.get(theme_col, "Thiên thời")) if theme_col else "Thiên thời",
                    "theme_rationale": str(row.get(rationale_col, "")) if rationale_col else "",
                    "theme_source": str(row.get(source_col, "")) if source_col else "",
                    "decline_flag": to_bool(row.get(decline_col, False), False) if decline_col else False,
                }
        return {
            "theme_score": 5.0,
            "theme_name": "Chưa phân loại",
            "theme_rationale": "Không khớp quy tắc thiên thời hiện có.",
            "theme_source": "",
            "decline_flag": False,
        }

    @staticmethod
    def _latest_price(quote: pd.DataFrame) -> float | None:
        if quote is None or quote.empty:
            return None
        row = quote.iloc[0].to_dict()
        for key in ["match_price", "price", "last_price", "close", "last", "matched_price"]:
            val = find_first_value(row, [key])
            num = safe_float(val)
            if num is not None and num > 0:
                return num
        return None

    @staticmethod
    def _ratio_metrics(ratio_df: pd.DataFrame) -> dict[str, Any]:
        if ratio_df is None or ratio_df.empty:
            return {}
        # Try to compute median ROE over up to 3 latest annual rows.
        columns = {normalize_text(c): c for c in ratio_df.columns}
        aliases = {
            "roe": ["roe", "return_on_equity"],
            "roa": ["roa", "return_on_assets"],
            "pe": ["pe", "priceToEarning", "price_to_earnings"],
            "pb": ["pb", "priceToBook", "price_to_book"],
            "dividend_yield": ["dividend_yield", "dividendYield"],
            "book_value_per_share": ["book_value_per_share", "bvps"],
        }
        out: dict[str, Any] = {}
        for target, keys in aliases.items():
            col = None
            for key in keys:
                norm = normalize_text(key)
                if norm in columns:
                    col = columns[norm]
                    break
                for n, original in columns.items():
                    if norm in n or n in norm:
                        col = original
                        break
                if col:
                    break
            if col:
                vals = pd.to_numeric(ratio_df[col], errors="coerce").dropna()
                if not vals.empty:
                    if target == "roe":
                        normalized = [pct_to_fraction(v) for v in vals.head(3).tolist()]
                        normalized = [v for v in normalized if v is not None]
                        if normalized:
                            out["roe_3y_median"] = float(np.median(normalized))
                    else:
                        val = safe_float(vals.iloc[0])
                        if target == "dividend_yield":
                            val = pct_to_fraction(val)
                        out[target] = val
        return out

    @staticmethod
    def _total_shares(info: dict[str, Any]) -> float | None:
        value = find_first_value(
            info,
            ["outstanding_shares", "shares_outstanding", "total_shares", "issue_share", "listed_share", "listed_shares"],
        )
        num = safe_float(value)
        if num is not None and num > 0:
            return num
        return None

    @staticmethod
    def apply_manual_override(snapshot: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
        if not override:
            return snapshot
        out = dict(snapshot)
        # Only non-empty fields override live data.
        for key, value in override.items():
            if key in {"ticker", "updated_at"}:
                continue
            if value is None or (isinstance(value, float) and math.isnan(value)) or str(value).strip() == "":
                continue
            if key == "state_control_pct":
                out[key] = pct_to_fraction(value)
                out["state_detection_method"] = "manual_override"
            elif key in {"theme_score", "core_focus_score", "governance_score", "hidden_asset_score", "hidden_asset_book_bn", "hidden_asset_market_bn"}:
                out[key] = safe_float(value)
            elif key == "industry_margin_benchmark":
                out[key] = pct_to_fraction(value)
                out["industry_benchmark_source"] = "manual_override"
            elif key == "decline_flag":
                out[key] = to_bool(value, False)
            else:
                out[key] = value
        return out

    def get_snapshot(
        self,
        ticker: str,
        margin_kind: str = "gross",
        dividend_lookback_years: int = 5,
        override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ticker = ticker.upper().strip()
        company_frames = self._company_frames(ticker)
        financial = self._financial_frames(ticker)
        market = self._market_frames(ticker)

        info = self._first_record(company_frames["info"])
        company_name = self._extract_company_name(info, ticker)
        industry, industry_source = self._extract_industry(ticker, info)
        tailwind = self._tailwind_match(industry, company_name)
        state = self._detect_state_control(company_frames["shareholders_summary"], company_frames["shareholders_detailed"])
        officer_ownership = self._officer_ownership(company_frames["officers"])
        dividends = self._dividend_metrics(company_frames["events"], dividend_lookback_years)

        q_income = financial["income_quarter"]
        y_income = financial["income_year"]
        revenue_q = self._report_period_values(q_income, REVENUE_LABELS)
        profit_q = self._report_period_values(q_income, NET_PROFIT_LABELS)
        _, revenue_growth, revenue_basis = self._latest_and_yoy(revenue_q)
        _, profit_growth, profit_basis = self._latest_and_yoy(profit_q)

        revenue_y = self._report_period_values(y_income, REVENUE_LABELS)
        if margin_kind == "net":
            profit_y = self._report_period_values(y_income, NET_PROFIT_LABELS)
            annual_margin, margin_period = self._latest_annual_ratio(profit_y, revenue_y)
        else:
            gross_y = self._report_period_values(y_income, GROSS_PROFIT_LABELS)
            annual_margin, margin_period = self._latest_annual_ratio(gross_y, revenue_y)

        ratio_metrics = self._ratio_metrics(financial["ratio_year_ts"])
        current_price = self._latest_price(market["quote"])
        total_shares = self._total_shares(info)

        snapshot: dict[str, Any] = {
            "ticker": ticker,
            "company_name": company_name,
            "industry": industry,
            "industry_source": industry_source,
            **tailwind,
            **state,
            "officer_ownership_pct": officer_ownership,
            "core_focus_score": 5.0,  # deliberate neutral default; user should validate evidence
            "governance_score": 5.0,  # deliberate neutral default
            "hidden_asset_score": 0.0,  # only raised by PDF/manual evidence
            "hidden_asset_book_bn": None,
            "hidden_asset_market_bn": None,
            "hidden_asset_evidence": "",
            "revenue_growth_yoy": revenue_growth,
            "profit_growth_yoy": profit_growth,
            "revenue_growth_basis": revenue_basis,
            "profit_growth_basis": profit_basis,
            "annual_margin": annual_margin,
            "margin_kind": margin_kind,
            "margin_period": margin_period,
            "industry_margin_benchmark": None,
            "industry_benchmark_source": "missing",
            **ratio_metrics,
            **dividends,
            "current_price": current_price,
            "total_shares": total_shares,
            "data_asof": date.today().isoformat(),
            "data_source": "vnstock",
        }

        # If dividend yield is missing from ratios, derive a rough lookback yield from average annual cash dividend.
        if snapshot.get("dividend_yield") is None and current_price and current_price > 0 and dividends["dividend_years_paid"]:
            avg_cash = dividends["cash_dividend_ps_lookback"] / max(dividend_lookback_years, 1)
            snapshot["dividend_yield"] = avg_cash / current_price if current_price else None

        # Adjusted NAV proxy if PB & price available.
        pb = safe_float(snapshot.get("pb"))
        if snapshot.get("book_value_per_share") is None and pb and pb > 0 and current_price:
            snapshot["book_value_per_share"] = current_price / pb

        snapshot = self.apply_manual_override(snapshot, override)
        return snapshot

    def get_state_snapshot(self, ticker: str) -> dict[str, Any]:
        """Fast ownership-only fetch for building a state-controlled universe."""
        ticker = ticker.upper().strip()
        company = self.ref.company(ticker)
        try:
            info_df = self._as_df(company.info())
        except Exception:
            info_df = pd.DataFrame()
        try:
            summary = self._as_df(company.shareholders(mode="summary"))
        except Exception:
            summary = pd.DataFrame()
        try:
            detailed = self._as_df(company.shareholders(mode="detailed"))
        except Exception:
            detailed = pd.DataFrame()
        info = self._first_record(info_df)
        company_name = self._extract_company_name(info, ticker)
        industry, _ = self._extract_industry(ticker, info)
        state = self._detect_state_control(summary, detailed)
        return {
            "ticker": ticker,
            "company_name": company_name,
            "industry": industry,
            **state,
        }

    def get_raw_detail(self, ticker: str) -> dict[str, pd.DataFrame]:
        ticker = ticker.upper().strip()
        return {**self._company_frames(ticker), **self._financial_frames(ticker), **self._market_frames(ticker)}


def load_csv_if_exists(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)
