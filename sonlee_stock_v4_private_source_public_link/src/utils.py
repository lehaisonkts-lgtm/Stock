from __future__ import annotations

import io
import math
import re
import unicodedata
from typing import Any, Iterable, Optional

import pandas as pd


def normalize_text(value: Any) -> str:
    """Lowercase, remove accents and collapse whitespace for fuzzy matching."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "n/a", "na", "-"}:
        return default
    text = text.replace("%", "").replace(" ", "")
    # Vietnamese-style formatting: 1.234,56 -> 1234.56
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts[-1]) <= 2:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    try:
        return float(text)
    except Exception:
        return default


def pct_to_fraction(value: Any) -> Optional[float]:
    """Accept either 0-1 fractions or 0-100 percentages and return a 0-1 fraction."""
    num = safe_float(value)
    if num is None:
        return None
    if abs(num) > 1.5:
        return num / 100.0
    return num


def fraction_to_pct(value: Any) -> Optional[float]:
    num = safe_float(value)
    if num is None:
        return None
    return num * 100.0


def first_existing_col(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    if df is None or df.empty:
        return None
    by_norm = {normalize_text(col): col for col in df.columns}
    for candidate in candidates:
        target = normalize_text(candidate)
        if target in by_norm:
            return by_norm[target]
    # Flexible contains match.
    for candidate in candidates:
        target = normalize_text(candidate)
        for norm, original in by_norm.items():
            if target and (target in norm or norm in target):
                return original
    return None


def find_first_value(record: dict[str, Any], candidates: Iterable[str], default: Any = None) -> Any:
    if not record:
        return default
    norm_map = {normalize_text(k): v for k, v in record.items()}
    for candidate in candidates:
        key = normalize_text(candidate)
        if key in norm_map:
            return norm_map[key]
    for candidate in candidates:
        key = normalize_text(candidate)
        for existing, value in norm_map.items():
            if key and (key in existing or existing in key):
                return value
    return default


def parse_period_label(label: Any) -> tuple[int, int] | None:
    """Return (year, quarter), quarter=0 for annual labels."""
    text = normalize_text(label).replace(" ", "")
    m = re.search(r"(20\d{2})[-_/]?q([1-4])", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"q([1-4])[-_/]?(20\d{2})", text)
    if m:
        return int(m.group(2)), int(m.group(1))
    m = re.search(r"([1-4])q[-_/]?(20\d{2})", text)
    if m:
        return int(m.group(2)), int(m.group(1))
    m = re.fullmatch(r"(20\d{2})", text)
    if m:
        return int(m.group(1)), 0
    return None


def dataframe_to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, df in sheets.items():
            safe_name = str(name)[:31] or "Sheet1"
            df.to_excel(writer, sheet_name=safe_name, index=False)
            ws = writer.book[safe_name]
            ws.freeze_panes = "A2"
            for column_cells in ws.columns:
                max_len = max((len(str(cell.value)) if cell.value is not None else 0) for cell in column_cells)
                ws.column_dimensions[column_cells[0].column_letter].width = min(max(max_len + 2, 10), 45)
    return bio.getvalue()


def nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return str(value).strip() != ""


def to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return default
        return value != 0
    text = normalize_text(value)
    if text in {"true", "1", "yes", "y", "x", "co", "có"}:
        return True
    if text in {"false", "0", "no", "n", "khong", "không", ""}:
        return False
    return default
