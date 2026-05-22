from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.config.paths import display_path, resolve_project_path
from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.retrieval.tables.schemas import TableEvidence


PAGE_MARKER_PATTERN = re.compile(
    r"^\s*(?:<!--\s*page\s+(\d+)\s*-->|#\s*Page\s+(\d+))\s*$",
    flags=re.IGNORECASE,
)
MARKDOWN_SEPARATOR_PATTERN = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
NUMBER_PATTERN = re.compile(r"(?:\$?\(?-?\d[\d,]*(?:\.\d+)?\)?%?)|(?:20\d\d)")
YEAR_PATTERN = re.compile(r"\b20\d\d\b")
FINANCIAL_TERMS = {
    "assets",
    "banking",
    "capital",
    "corporate",
    "equity",
    "expense",
    "income",
    "liabilities",
    "loss",
    "managed",
    "margin",
    "net income",
    "net interest",
    "noninterest",
    "provision",
    "ratio",
    "revenue",
    "segment",
    "wealth",
}


@dataclass(frozen=True)
class MarkdownPage:
    page_no: int | None
    lines: list[str]
    missing_page_markers: bool = False


def extract_table_evidence_from_canonical(
    canonical_path: str | Path,
    *,
    document_id: str | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> list[TableEvidence]:
    canonical_path = resolve_project_path(canonical_path)
    canonical = _read_json(canonical_path)
    document = canonical["document"]
    content_hash = str(document["content_hash"])
    resolved_document_id = document_id or _lookup_document_id(content_hash, session_factory)
    if resolved_document_id is None:
        resolved_document_id = ""

    docling = _read_optional_json(canonical.get("artifacts", {}).get("docling_json"))
    markdown = _read_optional_text(canonical.get("artifacts", {}).get("markdown"))
    chunks = _load_text_chunks(content_hash, session_factory)
    fallback_used = str(canonical.get("parser", {}).get("name") or "").lower() != "docling"

    context = _ExtractionContext(
        canonical=canonical,
        canonical_path=display_path(canonical_path),
        document_id=resolved_document_id,
        content_hash=content_hash,
        filename=str(document["filename"]),
        source_path=str(document["source_path"]),
        source_artifact_path=display_path(canonical_path),
        chunks=chunks,
        fallback_used=fallback_used,
    )

    evidence: list[TableEvidence] = []
    seen_span_hashes: set[str] = set()
    if docling:
        evidence.extend(_extract_docling_tables(context, docling, seen_span_hashes))
    if markdown:
        evidence.extend(_extract_markdown_tables(context, markdown, seen_span_hashes, start_index=len(evidence)))
        evidence.extend(_extract_table_like_spans(context, markdown, seen_span_hashes, start_index=len(evidence)))
    return evidence


@dataclass(frozen=True)
class _ExtractionContext:
    canonical: dict
    canonical_path: str
    document_id: str
    content_hash: str
    filename: str
    source_path: str
    source_artifact_path: str
    chunks: list[TextChunkRecord]
    fallback_used: bool


def _extract_docling_tables(
    context: _ExtractionContext,
    docling: dict,
    seen_span_hashes: set[str],
) -> list[TableEvidence]:
    ref_text = _docling_text_ref_map(docling)
    section_headings = _docling_section_headings(docling)
    records: list[TableEvidence] = []
    for table_index, table in enumerate(docling.get("tables") or []):
        grid = _docling_grid(table)
        if not grid:
            continue
        raw_text = _rows_to_text(grid)
        span_hash = _sha256(raw_text)
        if span_hash in seen_span_hashes:
            continue
        seen_span_hashes.add(span_hash)

        has_header = _has_header_row(grid, table)
        headers = grid[0] if has_header else []
        rows = grid[1:] if has_header else grid
        row_count = len(rows)
        column_count = max((len(row) for row in grid), default=0)
        empty_ratio = _empty_cell_ratio(grid)
        page_no = _page_from_prov(table)
        caption = _caption_from_refs(table, ref_text)
        risk_flags = _risk_flags(
            has_header=has_header,
            row_count=row_count,
            column_count=column_count,
            empty_cell_ratio=empty_ratio,
        )
        readiness = "good" if has_header and row_count >= 2 and column_count >= 2 else "weak"
        records.append(
            TableEvidence(
                table_id=f"{context.content_hash[:12]}:table:{len(records):04d}",
                table_index=len(records),
                document_id=context.document_id,
                content_hash=context.content_hash,
                canonical_path=context.canonical_path,
                filename=context.filename,
                source_path=context.source_path,
                source_artifact_path=context.source_artifact_path,
                table_type="structured",
                source_kind="docling_table",
                page_start=page_no,
                page_end=page_no,
                title=caption,
                caption=caption,
                section_heading=_nearest_section_heading(section_headings, page_no),
                raw_text=raw_text,
                markdown_table=_rows_to_markdown(headers, rows) if headers else None,
                structured_json={"headers": headers, "rows": rows},
                row_count=row_count,
                column_count=column_count,
                has_header=has_header,
                empty_cell_ratio=empty_ratio,
                table_readiness=readiness,
                extraction_method="docling",
                risk_flags=risk_flags,
                source_chunk_id=None,
                span_hash=span_hash,
            )
        )
    return records


def _extract_markdown_tables(
    context: _ExtractionContext,
    markdown: str,
    seen_span_hashes: set[str],
    *,
    start_index: int,
) -> list[TableEvidence]:
    records: list[TableEvidence] = []
    for page in _split_markdown_pages(markdown):
        lines = page.lines
        index = 0
        while index < len(lines):
            if index + 1 >= len(lines) or "|" not in lines[index] or not MARKDOWN_SEPARATOR_PATTERN.match(lines[index + 1]):
                index += 1
                continue

            start = index
            end = index + 2
            while end < len(lines) and "|" in lines[end] and lines[end].strip():
                end += 1

            table_lines = lines[start:end]
            raw_text = "\n".join(table_lines).strip()
            span_hash = _sha256(raw_text)
            if span_hash in seen_span_hashes:
                index = end
                continue
            seen_span_hashes.add(span_hash)

            headers, rows = _parse_markdown_table(table_lines)
            if not headers and not rows:
                index = end
                continue
            table_index = start_index + len(records)
            column_count = max([len(headers), *(len(row) for row in rows)] or [0])
            empty_ratio = _empty_cell_ratio([headers, *rows])
            source_chunk_id = _nearest_chunk_id(context.chunks, page.page_no, page.page_no)
            risk_flags = _risk_flags(
                has_header=bool(headers),
                row_count=len(rows),
                column_count=column_count,
                empty_cell_ratio=empty_ratio,
            )
            if page.missing_page_markers:
                risk_flags.append("missing_page_markers")
            if context.fallback_used:
                risk_flags.append("fallback_parser_used")
            records.append(
                TableEvidence(
                    table_id=f"{context.content_hash[:12]}:table:{table_index:04d}",
                    table_index=table_index,
                    document_id=context.document_id,
                    content_hash=context.content_hash,
                    canonical_path=context.canonical_path,
                    filename=context.filename,
                    source_path=context.source_path,
                    source_artifact_path=context.source_artifact_path,
                    table_type="structured",
                    source_kind="markdown_table",
                    page_start=page.page_no,
                    page_end=page.page_no,
                    title=_heading_before(lines, start),
                    caption=None,
                    section_heading=_heading_before(lines, start),
                    raw_text=raw_text,
                    markdown_table=raw_text,
                    structured_json={"headers": headers, "rows": rows},
                    row_count=len(rows),
                    column_count=column_count,
                    has_header=bool(headers),
                    empty_cell_ratio=empty_ratio,
                    table_readiness="good" if headers and len(rows) >= 1 and column_count >= 2 else "weak",
                    extraction_method="markdown_regex",
                    risk_flags=sorted(set(risk_flags)),
                    source_chunk_id=source_chunk_id,
                    span_hash=span_hash,
                )
            )
            index = end
    return records


def _extract_table_like_spans(
    context: _ExtractionContext,
    markdown: str,
    seen_span_hashes: set[str],
    *,
    start_index: int,
    max_chars_per_span: int = 10_000,
) -> list[TableEvidence]:
    records: list[TableEvidence] = []
    fallback_span_counts: dict[int, int] = {}
    for page_section_index, page in enumerate(_split_markdown_pages(markdown)):
        spans = _find_table_like_line_spans(page.lines)
        for _, (start, end) in enumerate(spans):
            expanded_start = _expand_span_start(page.lines, start)
            raw_text = "\n".join(page.lines[expanded_start:end]).strip()
            if len(raw_text) > max_chars_per_span:
                raw_text = raw_text[:max_chars_per_span].rstrip()
            if len(raw_text.splitlines()) < 3:
                continue
            span_hash = _sha256(raw_text)
            if span_hash in seen_span_hashes:
                continue
            seen_span_hashes.add(span_hash)

            source_chunk_id = _nearest_chunk_id(context.chunks, page.page_no, page.page_no)
            chunk_index = _chunk_index_from_id(source_chunk_id)
            if chunk_index is None:
                chunk_index = page.page_no if page.page_no is not None else page_section_index
            span_index = fallback_span_counts.get(chunk_index, 0)
            fallback_span_counts[chunk_index] = span_index + 1
            table_index = start_index + len(records)
            risk_flags = ["fallback_parser_used" if context.fallback_used else "fallback_text_span"]
            if page.missing_page_markers:
                risk_flags.append("missing_page_markers")
            records.append(
                TableEvidence(
                    table_id=f"{context.content_hash[:12]}:table_text:{chunk_index:04d}:{span_index:02d}",
                    table_index=table_index,
                    document_id=context.document_id,
                    content_hash=context.content_hash,
                    canonical_path=context.canonical_path,
                    filename=context.filename,
                    source_path=context.source_path,
                    source_artifact_path=context.source_artifact_path,
                    table_type="table_like_text",
                    source_kind="text_pattern",
                    page_start=page.page_no,
                    page_end=page.page_no,
                    title=_heading_before(page.lines, expanded_start),
                    caption=None,
                    section_heading=_heading_before(page.lines, expanded_start),
                    raw_text=raw_text,
                    markdown_table=None,
                    structured_json=None,
                    row_count=len(raw_text.splitlines()),
                    column_count=None,
                    has_header=False,
                    empty_cell_ratio=None,
                    table_readiness="weak",
                    extraction_method="table_like_text",
                    risk_flags=sorted(set(risk_flags)),
                    source_chunk_id=source_chunk_id,
                    span_hash=span_hash,
                )
            )
    return records


def _find_table_like_line_spans(lines: list[str]) -> list[tuple[int, int]]:
    high_score_indexes = {index for index, line in enumerate(lines) if _table_line_score(line) >= 3}
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(lines):
        if index not in high_score_indexes:
            index += 1
            continue
        start = index
        end = index + 1
        gap_count = 0
        high_count = 1
        while end < len(lines):
            if end in high_score_indexes:
                gap_count = 0
                high_count += 1
                end += 1
                continue
            if lines[end].strip() and gap_count < 1:
                gap_count += 1
                end += 1
                continue
            break
        while end > start and end - 1 not in high_score_indexes:
            end -= 1
        if high_count >= 2 and end - start >= 3:
            spans.append((start, end))
        index = max(end, index + 1)
    return spans


def _table_line_score(line: str) -> int:
    normalized = line.strip().lower()
    if not normalized:
        return 0
    numbers = NUMBER_PATTERN.findall(normalized)
    years = YEAR_PATTERN.findall(normalized)
    score = 0
    if len(numbers) >= 3:
        score += 3
    elif len(numbers) >= 1:
        score += 1
    if len(years) >= 2:
        score += 2
    if "$" in normalized or "%" in normalized or "billion" in normalized or "million" in normalized:
        score += 1
    if any(term in normalized for term in FINANCIAL_TERMS):
        score += 2
    if re.search(r"\d\s{2,}\d", line):
        score += 1
    return score


def _split_markdown_pages(markdown: str) -> list[MarkdownPage]:
    pages: list[MarkdownPage] = []
    current_page: int | None = None
    current_lines: list[str] = []
    marker_found = False
    for line in markdown.splitlines():
        match = PAGE_MARKER_PATTERN.match(line)
        if match:
            marker_found = True
            if current_lines:
                pages.append(MarkdownPage(page_no=current_page, lines=current_lines))
            current_page = int(match.group(1) or match.group(2))
            current_lines = []
        else:
            current_lines.append(line.rstrip())
    if current_lines:
        pages.append(MarkdownPage(page_no=current_page, lines=current_lines, missing_page_markers=not marker_found))
    if not pages and markdown.strip():
        return [MarkdownPage(page_no=None, lines=markdown.splitlines(), missing_page_markers=True)]
    if not marker_found:
        return [MarkdownPage(page_no=None, lines=markdown.splitlines(), missing_page_markers=True)]
    return pages


def _docling_grid(table: dict) -> list[list[str]]:
    grid = table.get("data", {}).get("grid")
    if isinstance(grid, list):
        rows = [
            [_normalize_cell(cell.get("text") if isinstance(cell, dict) else cell) for cell in row]
            for row in grid
            if isinstance(row, list)
        ]
        return [row for row in rows if any(row)]

    cells = table.get("data", {}).get("table_cells") or []
    if not isinstance(cells, list):
        return []
    row_count = 0
    col_count = 0
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        row_count = max(row_count, int(cell.get("end_row_offset_idx") or 0))
        col_count = max(col_count, int(cell.get("end_col_offset_idx") or 0))
    rows = [["" for _ in range(col_count)] for _ in range(row_count)]
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        row = int(cell.get("start_row_offset_idx") or 0)
        col = int(cell.get("start_col_offset_idx") or 0)
        if row < row_count and col < col_count:
            rows[row][col] = _normalize_cell(cell.get("text"))
    return [row for row in rows if any(row)]


def _has_header_row(grid: list[list[str]], table: dict) -> bool:
    data_grid = table.get("data", {}).get("grid") or []
    if data_grid and isinstance(data_grid, list) and isinstance(data_grid[0], list):
        if any(isinstance(cell, dict) and cell.get("column_header") for cell in data_grid[0]):
            return True

    first_row = grid[0] if grid else []
    if not first_row:
        return False
    nonempty = [cell for cell in first_row if cell.strip()]
    if not nonempty:
        return False
    numeric_cells = sum(1 for cell in nonempty if NUMBER_PATTERN.search(cell))
    text_cells = sum(1 for cell in nonempty if re.search(r"[A-Za-z]", cell))
    return text_cells >= max(1, numeric_cells)


def _rows_to_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(cell.strip() for cell in row).strip() for row in rows).strip()


def _rows_to_markdown(headers: list[str], rows: list[list[str]]) -> str:
    if not headers:
        return _rows_to_text(rows)
    separator = ["---" for _ in headers]
    markdown_rows = [headers, separator, *rows]
    return "\n".join("| " + " | ".join(row) + " |" for row in markdown_rows)


def _parse_markdown_table(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    if len(lines) < 2:
        return [], []
    headers = _split_markdown_row(lines[0])
    rows = [_split_markdown_row(line) for line in lines[2:]]
    return headers, [row for row in rows if any(cell.strip() for cell in row)]


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [_normalize_cell(cell) for cell in stripped.split("|")]


def _docling_text_ref_map(docling: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in docling.get("texts") or []:
        if not isinstance(item, dict):
            continue
        ref = item.get("self_ref")
        if ref:
            mapping[str(ref)] = _normalize_cell(item.get("text"))
    return mapping


def _docling_section_headings(docling: dict) -> list[tuple[int | None, str]]:
    headings: list[tuple[int | None, str]] = []
    for item in docling.get("texts") or []:
        if not isinstance(item, dict) or item.get("label") != "section_header":
            continue
        headings.append((_page_from_prov(item), _normalize_cell(item.get("text"))))
    return headings


def _nearest_section_heading(headings: list[tuple[int | None, str]], page_no: int | None) -> str | None:
    if not headings:
        return None
    if page_no is None:
        return headings[-1][1]
    candidates = [heading for heading_page, heading in headings if heading_page is None or heading_page <= page_no]
    return candidates[-1] if candidates else None


def _caption_from_refs(table: dict, ref_text: dict[str, str]) -> str | None:
    captions: list[str] = []
    for item in table.get("captions") or []:
        if isinstance(item, dict) and item.get("$ref") in ref_text:
            captions.append(ref_text[item["$ref"]])
    return " ".join(caption for caption in captions if caption).strip() or None


def _page_from_prov(item: dict) -> int | None:
    prov = item.get("prov") or []
    if prov and isinstance(prov[0], dict) and isinstance(prov[0].get("page_no"), int):
        return int(prov[0]["page_no"])
    return None


def _heading_before(lines: list[str], start_index: int) -> str | None:
    for index in range(start_index - 1, max(-1, start_index - 10), -1):
        candidate = lines[index].strip().strip("#").strip()
        if not candidate:
            continue
        if len(candidate) <= 120 and not NUMBER_PATTERN.search(candidate):
            return candidate
    return None


def _expand_span_start(lines: list[str], start_index: int) -> int:
    expanded = start_index
    for index in range(start_index - 1, max(-1, start_index - 8), -1):
        candidate = lines[index].strip()
        if not candidate:
            break
        if len(candidate) <= 140 or any(term in candidate.lower() for term in FINANCIAL_TERMS):
            expanded = index
            continue
        break
    return expanded


def _nearest_chunk_id(
    chunks: list[TextChunkRecord],
    page_start: int | None,
    page_end: int | None,
) -> str | None:
    if page_start is None and page_end is None:
        return None
    page_start = page_start or page_end
    page_end = page_end or page_start
    if page_start is None or page_end is None:
        return None
    best: tuple[int, TextChunkRecord] | None = None
    for chunk in chunks:
        if chunk.page_start is None or chunk.page_end is None:
            continue
        overlap = max(0, min(page_end, chunk.page_end) - max(page_start, chunk.page_start) + 1)
        distance = 0 if overlap > 0 else min(abs(page_start - chunk.page_end), abs(page_end - chunk.page_start))
        if best is None or distance < best[0]:
            best = (distance, chunk)
    return best[1].chunk_id if best else None


def _chunk_index_from_id(chunk_id: str | None) -> int | None:
    if not chunk_id:
        return None
    match = re.search(r":text:(\d+)$", chunk_id)
    return int(match.group(1)) if match else None


def _empty_cell_ratio(rows: list[list[str]]) -> float | None:
    total = sum(len(row) for row in rows)
    if total == 0:
        return None
    empty = sum(1 for row in rows for cell in row if not cell.strip())
    return empty / total


def _risk_flags(
    *,
    has_header: bool,
    row_count: int,
    column_count: int,
    empty_cell_ratio: float | None,
) -> list[str]:
    flags: list[str] = []
    if not has_header:
        flags.append("missing_header")
    if row_count <= 1:
        flags.append("single_row_table")
    if column_count < 2:
        flags.append("single_column_table")
    if empty_cell_ratio is not None and empty_cell_ratio > 0.35:
        flags.append("many_empty_cells")
    return flags


def _normalize_cell(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_json(path_value: str | None) -> dict | None:
    if not path_value:
        return None
    path = resolve_project_path(path_value)
    if not path.exists():
        return None
    return _read_json(path)


def _read_optional_text(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = resolve_project_path(path_value)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    return text if text.strip() else None


def _load_text_chunks(
    content_hash: str,
    session_factory: sessionmaker[Session] | None,
) -> list[TextChunkRecord]:
    if session_factory is None:
        return []
    with session_factory() as session:
        return list(
            session.scalars(
                select(TextChunkRecord)
                .where(TextChunkRecord.content_hash == content_hash)
                .order_by(TextChunkRecord.chunk_index)
            )
        )


def _lookup_document_id(
    content_hash: str,
    session_factory: sessionmaker[Session] | None,
) -> str | None:
    if session_factory is None:
        return None
    with session_factory() as session:
        document = session.scalar(select(Document).where(Document.content_hash == content_hash))
        return document.id if document else None
