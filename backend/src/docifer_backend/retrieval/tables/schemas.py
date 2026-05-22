from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableEvidence:
    table_id: str
    table_index: int
    document_id: str
    content_hash: str
    canonical_path: str
    filename: str
    source_path: str
    source_artifact_path: str
    table_type: str
    source_kind: str
    page_start: int | None
    page_end: int | None
    title: str | None
    caption: str | None
    section_heading: str | None
    raw_text: str
    markdown_table: str | None
    structured_json: dict | None
    row_count: int | None
    column_count: int | None
    has_header: bool
    empty_cell_ratio: float | None
    table_readiness: str
    extraction_method: str
    risk_flags: list[str]
    source_chunk_id: str | None
    span_hash: str | None


@dataclass(frozen=True)
class TableIndexOutcome:
    document_id: str
    content_hash: str
    status: str
    table_evidence_count: int
    structured_table_count: int
    markdown_table_count: int
    table_like_text_count: int
    collection_name: str
    reused_existing: bool


@dataclass(frozen=True)
class TableQueryResult:
    table_id: str
    score: float
    dense_score: float | None
    lexical_score: float | None
    hybrid_score: float | None
    retrieval_mode: str
    table_type: str
    source_kind: str
    page_start: int | None
    page_end: int | None
    raw_text: str
    markdown_table: str | None
    structured_json: dict | None
    section_heading: str | None
    table_readiness: str
    document_id: str
    content_hash: str
    filename: str
    source_path: str
    source_artifact_path: str
    source_chunk_id: str | None


@dataclass(frozen=True)
class TableCitation:
    citation_id: str
    evidence_type: str
    table_id: str
    source_path: str
    source_artifact_path: str
    page_start: int | None
    page_end: int | None
    table_type: str
    table_readiness: str
    score: float
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None


def format_table_evidence_for_embedding(table: TableEvidence | TableQueryResult) -> str:
    page = _format_page_range(table.page_start, table.page_end)
    evidence_type = "structured table" if table.table_type == "structured" else "table-like text"
    lines = [
        f"Document: {table.filename}",
        f"Page: {page}",
        f"Section: {table.section_heading or ''}",
        f"Evidence Type: {evidence_type}",
        f"Readiness: {table.table_readiness}",
    ]
    title = getattr(table, "title", None)
    caption = getattr(table, "caption", None)
    if title:
        lines.append(f"Table Title: {title}")
    if caption:
        lines.append(f"Caption: {caption}")

    if table.structured_json:
        headers = table.structured_json.get("headers") or []
        rows = table.structured_json.get("rows") or []
        if headers:
            lines.append(f"Headers: {', '.join(str(header) for header in headers)}")
        if rows:
            lines.append("Rows:")
            lines.extend(" | ".join(str(cell) for cell in row) for row in rows[:80])
    else:
        lines.append("Detected table-like text:")
        lines.append(table.raw_text)
    return "\n".join(lines).strip()


def _format_page_range(page_start: int | None, page_end: int | None) -> str:
    if page_start and page_end and page_start != page_end:
        return f"{page_start}-{page_end}"
    if page_start:
        return str(page_start)
    return "unknown"
