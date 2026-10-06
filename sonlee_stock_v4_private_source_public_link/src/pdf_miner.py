from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd
from pypdf import PdfReader

from .utils import normalize_text


@dataclass(frozen=True)
class HiddenAssetRule:
    category: str
    label: str
    patterns: tuple[str, ...]
    weight: float


RULES: tuple[HiddenAssetRule, ...] = (
    HiddenAssetRule(
        "land_property",
        "Đất / quyền sử dụng đất / BĐS đầu tư",
        (
            r"quy[eề]n\s+s[ửu]\s+d[ụu]ng\s+[đd][ấa]t",
            r"b[ấa]t\s+[đd][ộo]ng\s+s[ảa]n\s+[đd][ầa]u\s+t[ưư]",
            r"ti[eề]n\s+thu[eê]\s+[đd][ấa]t",
            r"gi[aá]\s+tr[ịi]\s+quy[eề]n\s+s[ửu]\s+d[ụu]ng\s+[đd][ấa]t",
        ),
        2.5,
    ),
    HiddenAssetRule(
        "fully_depreciated_assets",
        "Tài sản đã khấu hao nhiều/hết nhưng vẫn khai thác",
        (
            r"kh[ấa]u\s+hao\s+h[eế]t",
            r"[đd][aã]\s+kh[ấa]u\s+hao\s+h[eế]t",
            r"v[aẫ]n\s+[đd]ang\s+s[ửu]\s+d[ụu]ng",
        ),
        1.5,
    ),
    HiddenAssetRule(
        "investments",
        "Khoản đầu tư / công ty con / liên kết có thể bị ghi nhận theo giá gốc",
        (
            r"[đd][ầa]u\s+t[ưư]\s+v[aà]o\s+c[oô]ng\s+ty\s+con",
            r"c[oô]ng\s+ty\s+li[eê]n\s+k[eế]t",
            r"[đd][ầa]u\s+t[ưư]\s+t[aà]i\s+ch[ií]nh\s+d[aà]i\s+h[aạ]n",
            r"gi[aá]\s+g[oố]c\s+kho[ảa]n\s+[đd][ầa]u\s+t[ưư]",
        ),
        1.5,
    ),
    HiddenAssetRule(
        "provisions",
        "Dự phòng có khả năng hoàn nhập / tài sản bị ghi giảm",
        (
            r"d[ựu]\s+ph[oò]ng\s+gi[ảa]m\s+gi[aá]",
            r"d[ựu]\s+ph[oò]ng\s+t[ổo]n\s+th[ấa]t",
            r"ho[aà]n\s+nh[ậa]p\s+d[ựu]\s+ph[oò]ng",
        ),
        1.0,
    ),
    HiddenAssetRule(
        "long_term_prepaid",
        "Chi phí trả trước dài hạn / quyền khai thác dài hạn",
        (
            r"chi\s+ph[ií]\s+tr[ảa]\s+tr[ưư][ớo]c\s+d[aà]i\s+h[aạ]n",
            r"quy[eề]n\s+khai\s+th[aá]c",
            r"nh[ưư][ợo]ng\s+quy[eề]n",
        ),
        0.8,
    ),
    HiddenAssetRule(
        "mineral_resource",
        "Tài nguyên / mỏ / giấy phép khai thác",
        (
            r"m[ỏo]\s+khai\s+th[aá]c",
            r"tr[ữu]\s+l[ưư][ợo]ng",
            r"gi[ấa]y\s+ph[eé]p\s+khai\s+th[aá]c",
            r"t[aà]i\s+nguy[eê]n\s+kho[aá]ng\s+s[ảa]n",
        ),
        1.2,
    ),
)

AMOUNT_RE = re.compile(
    r"(?P<amount>\d{1,3}(?:[\.\s,]\d{3})+(?:[\.,]\d+)?|\d+(?:[\.,]\d+)?)\s*(?P<unit>tỷ|triệu|nghìn|đồng|vnd)",
    flags=re.IGNORECASE,
)


def extract_pdf_pages(file_bytes: bytes) -> list[dict[str, Any]]:
    reader = PdfReader(io.BytesIO(file_bytes))
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append({"page": index, "text": text})
    return pages


def analyze_hidden_assets_pages(pages: list[dict[str, Any]], context_chars: int = 230) -> pd.DataFrame:
    findings: list[dict[str, Any]] = []
    for page in pages:
        page_no = int(page.get("page", 0))
        text = str(page.get("text", ""))
        if not text.strip():
            continue
        for rule in RULES:
            matched_spans: list[tuple[int, int, str]] = []
            for pattern in rule.patterns:
                for m in re.finditer(pattern, text, flags=re.IGNORECASE):
                    matched_spans.append((m.start(), m.end(), m.group(0)))
            # Deduplicate overlapping hits from similar patterns.
            matched_spans.sort(key=lambda x: x[0])
            kept: list[tuple[int, int, str]] = []
            for span in matched_spans:
                if kept and span[0] <= kept[-1][1] + 20:
                    continue
                kept.append(span)
            for start, end, hit in kept:
                left = max(0, start - context_chars)
                right = min(len(text), end + context_chars)
                context = re.sub(r"\s+", " ", text[left:right]).strip()
                amount_hints = [f"{m.group('amount')} {m.group('unit')}" for m in AMOUNT_RE.finditer(context)]
                findings.append(
                    {
                        "category": rule.category,
                        "label": rule.label,
                        "page": page_no,
                        "keyword": hit,
                        "context": context,
                        "amount_hints": "; ".join(amount_hints[:8]),
                        "weight": rule.weight,
                    }
                )
    return pd.DataFrame(findings)


def hidden_asset_score(findings: pd.DataFrame) -> float:
    if findings is None or findings.empty:
        return 0.0
    # Category diversity matters more than repeated keyword hits.
    category_max = findings.groupby("category")["weight"].max().sum()
    amount_bonus = min(2.0, 0.25 * findings["amount_hints"].astype(str).str.len().gt(0).sum())
    page_bonus = min(1.0, 0.10 * findings["page"].nunique())
    return round(min(10.0, category_max + amount_bonus + page_bonus), 2)


def pdf_hidden_asset_audit(file_bytes: bytes) -> tuple[pd.DataFrame, dict[str, Any]]:
    pages = extract_pdf_pages(file_bytes)
    findings = analyze_hidden_assets_pages(pages)
    extracted_chars = sum(len(str(p.get("text", ""))) for p in pages)
    summary = {
        "pages": len(pages),
        "extracted_chars": extracted_chars,
        "finding_count": len(findings),
        "hidden_asset_score": hidden_asset_score(findings),
        "text_quality": "ok" if extracted_chars >= max(1000, len(pages) * 100) else "low_or_scanned_pdf",
    }
    return findings, summary
