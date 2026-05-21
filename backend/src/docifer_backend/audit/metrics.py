from __future__ import annotations

import re
from dataclasses import dataclass, field

AUDIT_VERSION = "0.1.0"

_TABLE_LINE_RE = re.compile(r"\S+(?:[ \t]{2,}|\t)\S+")
_FIGURE_REF_RE = re.compile(r"\b(?:figure|fig\.?|chart|diagram|exhibit)\b", re.IGNORECASE)
_CAPTION_RE = re.compile(r"\b(?:figure|fig\.?|chart|exhibit)\s*\d+", re.IGNORECASE)


@dataclass(frozen=True)
class AuditSummary:
    page_count: int
    table_count: int
    table_candidate_count: int
    table_like_page_count: int
    figure_count: int
    figure_candidate_count: int
    caption_candidate_count: int
    empty_page_count: int
    text_chars_total: int
    avg_chars_per_page: float
    parse_error_count: int
    chunk_count: int


@dataclass(frozen=True)
class AuditVerdicts:
    text_readiness: str
    table_readiness: str
    visual_readiness: str
    quality_status: str
    risk_flags: list[str] = field(default_factory=list)


def detect_fallback(canonical: dict) -> tuple[bool, str | None]:
    """Return (fallback_used, fallback_reason) based on parser metadata in canonical.json."""
    if canonical.get("parser", {}).get("name") != "pypdfium2-text":
        return False, None
    errors = canonical.get("parse", {}).get("errors", [])
    for error in errors:
        if error.get("type") == "parser_selection":
            return True, "size_threshold"
        if error.get("stage") == "docling_primary_parser":
            return True, "docling_failed"
    return True, "manual_backend" if not errors else "unknown"


def compute_summary(
    canonical: dict,
    markdown_text: str,
    docling: dict | None,
    chunk_count: int = 0,
) -> AuditSummary:
    """Extract raw stats from available artifact sources."""
    parse = canonical.get("parse", {})
    page_count = parse.get("page_count", 0)
    table_count = parse.get("table_count", 0)
    figure_count = parse.get("figure_count", 0)
    parse_error_count = len(parse.get("errors", []))

    text_chars_total, empty_page_count, avg_chars_per_page = _text_stats(markdown_text, page_count)

    if docling is not None:
        table_candidate_count, table_like_page_count = _table_stats_from_docling(docling)
        figure_candidate_count, caption_candidate_count = _figure_stats_from_docling(docling)
    else:
        table_candidate_count, table_like_page_count = _table_stats_from_text(markdown_text)
        figure_candidate_count, caption_candidate_count = _figure_stats_from_text(markdown_text)

    return AuditSummary(
        page_count=page_count,
        table_count=table_count,
        table_candidate_count=table_candidate_count,
        table_like_page_count=table_like_page_count,
        figure_count=figure_count,
        figure_candidate_count=figure_candidate_count,
        caption_candidate_count=caption_candidate_count,
        empty_page_count=empty_page_count,
        text_chars_total=text_chars_total,
        avg_chars_per_page=round(avg_chars_per_page, 1),
        parse_error_count=parse_error_count,
        chunk_count=chunk_count,
    )


def compute_verdicts(
    summary: AuditSummary,
    *,
    fallback_used: bool,
    docling_missing: bool = False,
) -> AuditVerdicts:
    """Compute advisory readiness verdicts and risk flags from summary stats."""
    text_readiness = _text_readiness(summary)
    table_readiness = _table_readiness(summary, fallback_used=fallback_used)
    visual_readiness = _visual_readiness(summary, fallback_used=fallback_used)
    quality_status = _quality_status(text_readiness, table_readiness, visual_readiness)
    risk_flags = _risk_flags(summary, fallback_used=fallback_used, docling_missing=docling_missing)
    return AuditVerdicts(
        text_readiness=text_readiness,
        table_readiness=table_readiness,
        visual_readiness=visual_readiness,
        quality_status=quality_status,
        risk_flags=risk_flags,
    )


# ── private helpers ──────────────────────────────────────────────────────────


def _text_stats(markdown: str, page_count: int) -> tuple[int, int, float]:
    parts = re.split(r"<!--\s*page\s+\d+\s*-->", markdown)
    # Drop the leading fragment that appears before the first page marker (not a real page)
    if parts and not parts[0].strip():
        parts = parts[1:]
    pages = [p.strip() for p in parts]
    content_pages = [p for p in pages if p]

    if not content_pages:
        total = len(markdown.strip())
        return total, 0, total / max(page_count, 1)

    total = sum(len(p) for p in content_pages)
    empty = sum(1 for p in pages if not p)
    avg = total / max(len(content_pages), 1)
    return total, empty, avg


def _table_stats_from_docling(docling: dict) -> tuple[int, int]:
    """Returns (table_candidate_count, table_like_page_count) from structured docling data."""
    tables = docling.get("tables", [])
    pages: set[int] = set()
    for table in tables:
        for prov in table.get("prov", []):
            if prov.get("page_no"):
                pages.add(prov["page_no"])
    return len(tables), len(pages)


def _figure_stats_from_docling(docling: dict) -> tuple[int, int]:
    """Returns (figure_candidate_count, caption_candidate_count) from structured docling data."""
    pictures = docling.get("pictures", [])
    captions_with_text = sum(
        1 for pic in pictures if any(c.get("text", "") for c in pic.get("captions", []))
    )
    return len(pictures), captions_with_text


def _table_stats_from_text(markdown: str) -> tuple[int, int]:
    """Estimate table presence from text patterns when docling.json is unavailable."""
    pages = re.split(r"<!--\s*page\s+\d+\s*-->", markdown)
    table_like_pages = 0
    for page in pages:
        lines = [l for l in page.splitlines() if l.strip()]
        table_lines = sum(1 for l in lines if _TABLE_LINE_RE.search(l))
        if table_lines >= 3:
            table_like_pages += 1
    candidate_count = max(table_like_pages // 2, 1) if table_like_pages > 0 else 0
    return candidate_count, table_like_pages


def _figure_stats_from_text(markdown: str) -> tuple[int, int]:
    """Estimate figure references from text when docling.json is unavailable."""
    refs = len(_FIGURE_REF_RE.findall(markdown))
    captions = len(_CAPTION_RE.findall(markdown))
    return refs, captions


def _text_readiness(s: AuditSummary) -> str:
    empty_ratio = s.empty_page_count / max(s.page_count, 1)
    if empty_ratio > 0.30 or s.avg_chars_per_page < 50:
        return "poor"
    if empty_ratio > 0.05 or s.avg_chars_per_page < 200:
        return "weak"
    return "good"


def _table_readiness(s: AuditSummary, *, fallback_used: bool) -> str:
    if not fallback_used:
        if s.table_count >= 1 and s.table_candidate_count >= 1:
            return "good"
        return "weak"
    if s.table_candidate_count > 0 or s.table_like_page_count > 0:
        return "weak"
    return "poor"


def _visual_readiness(s: AuditSummary, *, fallback_used: bool) -> str:
    if fallback_used:
        return "poor"
    if s.figure_count >= 1 and s.caption_candidate_count >= 1:
        return "good"
    if s.figure_count >= 1:
        return "weak"
    return "poor"


def _quality_status(text: str, table: str, visual: str) -> str:
    statuses = [text, table, visual]
    if all(s == "good" for s in statuses):
        return "good"
    poor_count = statuses.count("poor")
    if text == "poor" or poor_count >= 2:
        return "poor"
    return "weak"


def _risk_flags(
    s: AuditSummary,
    *,
    fallback_used: bool,
    docling_missing: bool = False,
) -> list[str]:
    flags: list[str] = []
    if fallback_used:
        flags.append("fallback_parser_used")
    if s.table_count == 0 and s.table_candidate_count == 0:
        flags.append("no_structured_tables")
    elif s.table_count == 0 and s.table_candidate_count > 0:
        flags.append("table_like_text_without_structure")
    if s.figure_count == 0 and s.figure_candidate_count == 0:
        flags.append("no_figures")
    if s.empty_page_count / max(s.page_count, 1) > 0.10:
        flags.append("high_empty_page_ratio")
    if s.parse_error_count > 0:
        flags.append("parse_errors_present")
    if s.avg_chars_per_page < 100:
        flags.append("low_text_density")
    if s.page_count > 200:
        flags.append("large_document")
    if s.chunk_count > 1000:
        flags.append("high_chunk_count")
    if docling_missing:
        flags.append("missing_docling_json")
    return flags
