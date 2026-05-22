from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from docifer_backend.config.paths import display_path, resolve_project_path
from docifer_backend.retrieval.visuals.schemas import VisualEvidence


_FIGURE_LABEL_RE = re.compile(
    r"\b(Figure|Fig\.?|Chart|Diagram|Exhibit)\s*(\d+)",
    re.IGNORECASE,
)
_PAGE_MARKER_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->", re.IGNORECASE)


@dataclass(frozen=True)
class _ExtractionContext:
    canonical: dict
    canonical_path: str
    document_id: str
    content_hash: str
    filename: str
    source_path: str
    source_artifact_path: str
    artifact_dir: str


def extract_visual_evidence_from_canonical(
    canonical_path: str | Path,
    *,
    document_id: str | None = None,
) -> list[VisualEvidence]:
    canonical_path = resolve_project_path(canonical_path)
    canonical = _read_json(canonical_path)
    document = canonical["document"]
    content_hash = str(document["content_hash"])
    resolved_document_id = document_id or ""
    artifact_dir = str(canonical.get("artifacts", {}).get("directory") or "")

    context = _ExtractionContext(
        canonical=canonical,
        canonical_path=display_path(canonical_path),
        document_id=resolved_document_id,
        content_hash=content_hash,
        filename=str(document["filename"]),
        source_path=str(document["source_path"]),
        source_artifact_path=display_path(canonical_path),
        artifact_dir=artifact_dir,
    )

    docling = _read_optional_json(canonical.get("artifacts", {}).get("docling_json"))
    markdown = _read_optional_text(canonical.get("artifacts", {}).get("markdown")) or ""
    page_count = int(canonical.get("parse", {}).get("page_count") or 0)
    figure_count = int(canonical.get("parse", {}).get("figure_count") or 0)

    page_texts = _split_page_texts(markdown, page_count)
    section_headings = _docling_section_headings(docling) if docling else []

    evidence: list[VisualEvidence] = []

    pictures_extracted: set[int] = set()
    if docling:
        pictures = _extract_docling_pictures(context, docling, page_texts, section_headings)
        evidence.extend(pictures)
        pictures_extracted = {p.page_start for p in pictures if p.page_start is not None}

    evidence.extend(
        _extract_page_render_records(context, page_count, page_texts, section_headings)
    )

    has_docling_pictures = bool(pictures_extracted)
    if figure_count > 0 and not has_docling_pictures:
        evidence.extend(
            _extract_figure_candidates(context, markdown, page_texts, section_headings, start_index=len(evidence))
        )

    return evidence


def _extract_docling_pictures(
    context: _ExtractionContext,
    docling: dict,
    page_texts: dict[int, str],
    section_headings: list[tuple[int | None, str]],
) -> list[VisualEvidence]:
    ref_text = _docling_text_ref_map(docling)
    records: list[VisualEvidence] = []
    for picture_index, picture in enumerate(docling.get("pictures") or []):
        page_no = _page_from_prov(picture)
        caption = _caption_from_refs(picture, ref_text)
        figure_label = _extract_figure_label(caption or "")
        nearby_text = _nearby_page_text(page_texts, page_no)
        heading = _nearest_section_heading(section_headings, page_no)
        readiness = "good" if caption else "weak"
        artifact_path = _page_artifact_path(context.artifact_dir, page_no) if page_no else None
        span_hash = _sha256(f"{context.content_hash}:picture:{picture_index}")
        records.append(
            VisualEvidence(
                visual_id=f"{context.content_hash[:12]}:picture:{picture_index:04d}",
                visual_index=picture_index,
                document_id=context.document_id,
                content_hash=context.content_hash,
                canonical_path=context.canonical_path,
                filename=context.filename,
                source_path=context.source_path,
                source_artifact_path=context.source_artifact_path,
                visual_type="docling_picture",
                source_kind="docling_picture",
                page_start=page_no,
                page_end=page_no,
                artifact_path=artifact_path,
                caption=caption,
                section_heading=heading,
                nearby_text=nearby_text,
                figure_label=figure_label,
                visual_readiness=readiness,
                extraction_method="docling_picture",
                source_chunk_ids=[],
                span_hash=span_hash,
            )
        )
    return records


def _extract_page_render_records(
    context: _ExtractionContext,
    page_count: int,
    page_texts: dict[int, str],
    section_headings: list[tuple[int | None, str]],
) -> list[VisualEvidence]:
    records: list[VisualEvidence] = []
    for page_no in range(1, page_count + 1):
        nearby_text = _nearby_page_text(page_texts, page_no)
        heading = _nearest_section_heading(section_headings, page_no)
        artifact_path = _page_artifact_path(context.artifact_dir, page_no)
        records.append(
            VisualEvidence(
                visual_id=f"{context.content_hash[:12]}:page:{page_no:04d}",
                visual_index=page_no - 1,
                document_id=context.document_id,
                content_hash=context.content_hash,
                canonical_path=context.canonical_path,
                filename=context.filename,
                source_path=context.source_path,
                source_artifact_path=context.source_artifact_path,
                visual_type="page_render",
                source_kind="page_render",
                page_start=page_no,
                page_end=page_no,
                artifact_path=artifact_path,
                caption=None,
                section_heading=heading,
                nearby_text=nearby_text,
                figure_label=None,
                visual_readiness="weak",
                extraction_method="page_render",
                source_chunk_ids=[],
                span_hash=None,
            )
        )
    return records


def _extract_figure_candidates(
    context: _ExtractionContext,
    markdown: str,
    page_texts: dict[int, str],
    section_headings: list[tuple[int | None, str]],
    *,
    start_index: int,
) -> list[VisualEvidence]:
    records: list[VisualEvidence] = []
    seen_labels: set[str] = set()
    for match in _FIGURE_LABEL_RE.finditer(markdown):
        label = f"{match.group(1).capitalize()} {match.group(2)}"
        if label in seen_labels:
            continue
        seen_labels.add(label)
        page_no = _page_from_position(markdown, match.start())
        nearby_text = _context_around_match(markdown, match.start(), chars=300)
        heading = _nearest_section_heading(section_headings, page_no)
        artifact_path = _page_artifact_path(context.artifact_dir, page_no) if page_no else None
        candidate_index = start_index + len(records)
        records.append(
            VisualEvidence(
                visual_id=f"{context.content_hash[:12]}:figcand:{candidate_index:04d}",
                visual_index=candidate_index,
                document_id=context.document_id,
                content_hash=context.content_hash,
                canonical_path=context.canonical_path,
                filename=context.filename,
                source_path=context.source_path,
                source_artifact_path=context.source_artifact_path,
                visual_type="figure_candidate",
                source_kind="text_reference",
                page_start=page_no,
                page_end=page_no,
                artifact_path=artifact_path,
                caption=None,
                section_heading=heading,
                nearby_text=nearby_text,
                figure_label=label,
                visual_readiness="poor",
                extraction_method="text_reference",
                source_chunk_ids=[],
                span_hash=_sha256(f"{context.content_hash}:figcand:{label}"),
            )
        )
    return records


def _split_page_texts(markdown: str, page_count: int) -> dict[int, str]:
    page_texts: dict[int, str] = {}
    parts = _PAGE_MARKER_RE.split(markdown)
    i = 1
    while i < len(parts) - 1:
        try:
            page_no = int(parts[i])
            page_text = parts[i + 1] if i + 1 < len(parts) else ""
            page_texts[page_no] = page_text.strip()
        except (ValueError, IndexError):
            pass
        i += 2
    return page_texts


def _nearby_page_text(page_texts: dict[int, str], page_no: int | None) -> str | None:
    if page_no is None:
        return None
    text = page_texts.get(page_no, "")
    return text[:800] if text else None


def _page_from_position(markdown: str, position: int) -> int | None:
    last_page: int | None = None
    for match in _PAGE_MARKER_RE.finditer(markdown):
        if match.start() > position:
            break
        try:
            last_page = int(match.group(1))
        except ValueError:
            pass
    return last_page


def _context_around_match(markdown: str, position: int, *, chars: int = 300) -> str:
    start = max(0, position - chars // 2)
    end = min(len(markdown), position + chars // 2)
    return markdown[start:end].strip()


def _docling_text_ref_map(docling: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in docling.get("texts") or []:
        if not isinstance(item, dict):
            continue
        ref = item.get("self_ref")
        if ref:
            mapping[str(ref)] = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
    return mapping


def _docling_section_headings(docling: dict) -> list[tuple[int | None, str]]:
    headings: list[tuple[int | None, str]] = []
    for item in docling.get("texts") or []:
        if not isinstance(item, dict) or item.get("label") != "section_header":
            continue
        headings.append((_page_from_prov(item), re.sub(r"\s+", " ", str(item.get("text") or "")).strip()))
    return headings


def _nearest_section_heading(headings: list[tuple[int | None, str]], page_no: int | None) -> str | None:
    if not headings:
        return None
    if page_no is None:
        return headings[-1][1]
    candidates = [h for hp, h in headings if hp is None or hp <= page_no]
    return candidates[-1] if candidates else None


def _caption_from_refs(picture: dict, ref_text: dict[str, str]) -> str | None:
    captions: list[str] = []
    for item in picture.get("captions") or []:
        if isinstance(item, dict) and item.get("$ref") in ref_text:
            captions.append(ref_text[item["$ref"]])
    return " ".join(c for c in captions if c).strip() or None


def _page_from_prov(item: dict) -> int | None:
    prov = item.get("prov") or []
    if prov and isinstance(prov[0], dict) and isinstance(prov[0].get("page_no"), int):
        return int(prov[0]["page_no"])
    return None


def _page_artifact_path(artifact_dir: str, page_no: int | None) -> str | None:
    if not artifact_dir or page_no is None:
        return None
    base = artifact_dir.replace("\\", "/").rstrip("/")
    return f"{base}/visuals/pages/page_{page_no:04d}.jpg"


def _extract_figure_label(text: str) -> str | None:
    match = _FIGURE_LABEL_RE.search(text)
    if match:
        return f"{match.group(1).capitalize()} {match.group(2)}"
    return None


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
