from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VisualEvidence:
    visual_id: str
    visual_index: int
    document_id: str
    content_hash: str
    canonical_path: str
    filename: str
    source_path: str
    source_artifact_path: str
    visual_type: str   # page_render | docling_picture | figure_candidate
    source_kind: str   # page_render | docling_picture | text_reference
    page_start: int | None
    page_end: int | None
    artifact_path: str | None  # path to rendered JPEG
    caption: str | None
    section_heading: str | None
    nearby_text: str | None
    figure_label: str | None   # e.g. "Figure 3"
    visual_readiness: str      # good | weak | poor
    extraction_method: str     # page_render | docling_picture | text_reference
    source_chunk_ids: list[str]
    span_hash: str | None


@dataclass(frozen=True)
class VisualIndexOutcome:
    document_id: str
    content_hash: str
    status: str
    page_render_count: int
    figure_candidate_count: int
    visual_record_count: int
    collection_name: str
    reused_existing: bool


@dataclass(frozen=True)
class VisualQueryResult:
    visual_id: str
    score: float
    dense_score: float | None
    lexical_score: float | None
    hybrid_score: float | None
    retrieval_mode: str
    visual_type: str
    source_kind: str
    page_start: int | None
    page_end: int | None
    artifact_path: str | None
    caption: str | None
    section_heading: str | None
    nearby_text: str | None
    figure_label: str | None
    visual_readiness: str
    document_id: str
    content_hash: str
    filename: str
    source_path: str
    source_artifact_path: str
    doc_id: str | None = None


@dataclass(frozen=True)
class VisualCitation:
    citation_id: str
    evidence_type: str
    visual_id: str
    source_path: str
    source_artifact_path: str
    artifact_path: str | None
    page_start: int | None
    page_end: int | None
    visual_type: str
    visual_readiness: str
    score: float
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None
    doc_id: str | None = None
    document_id: str | None = None
    content_hash: str | None = None
    filename: str | None = None


def format_visual_evidence_for_embedding(visual: VisualEvidence | VisualQueryResult) -> str:
    page = _format_page_range(visual.page_start, visual.page_end)
    lines = [
        f"Document: {visual.filename}",
        f"Page: {page}",
        f"Visual Type: {visual.visual_type}",
        f"Section: {visual.section_heading or ''}",
    ]
    figure_label = getattr(visual, "figure_label", None)
    caption = getattr(visual, "caption", None)
    nearby_text = getattr(visual, "nearby_text", None)
    if figure_label:
        lines.append(f"Figure Label: {figure_label}")
    if caption:
        lines.append(f"Caption: {caption}")
    if nearby_text:
        lines.append(f"Nearby Text: {nearby_text[:500]}")
    return "\n".join(lines).strip()


def _format_page_range(page_start: int | None, page_end: int | None) -> str:
    if page_start and page_end and page_start != page_end:
        return f"{page_start}-{page_end}"
    if page_start:
        return str(page_start)
    return "unknown"


def format_visual_query_result_for_interpretation(visual: VisualQueryResult) -> str:
    page = _format_page_range(visual.page_start, visual.page_end)
    lines = [
        f"Document: {visual.filename}",
        f"Page: {page}",
        f"Visual ID: {visual.visual_id}",
        f"Visual Type: {visual.visual_type}",
        f"Readiness: {visual.visual_readiness}",
        f"Section: {visual.section_heading or ''}",
    ]
    if visual.figure_label:
        lines.append(f"Figure Label: {visual.figure_label}")
    if visual.caption:
        lines.append(f"Caption: {visual.caption}")
    if visual.nearby_text:
        lines.append(f"Nearby Text: {visual.nearby_text[:800]}")
    return "\n".join(lines).strip()
