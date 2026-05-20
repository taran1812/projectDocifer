from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from docifer_backend.config.paths import display_path, resolve_project_path


@dataclass(frozen=True)
class TextChunk:
    id: str
    chunk_id: str
    chunk_index: int
    content_hash: str
    filename: str
    source_path: str
    source_artifact_path: str
    text: str
    page_start: int | None
    page_end: int | None


@dataclass(frozen=True)
class TextBlock:
    text: str
    label: str
    page_no: int | None
    source_ref: str | None


SKIPPED_LABELS = {"page_header", "page_footer"}


def build_text_chunks_from_canonical(
    canonical_path: str | Path,
    *,
    max_chars: int = 1200,
) -> list[TextChunk]:
    canonical_path = resolve_project_path(canonical_path)
    canonical = _read_json(canonical_path)
    docling_path = resolve_project_path(canonical["artifacts"]["docling_json"])
    docling_document = _read_json(docling_path)

    blocks = _extract_text_blocks(docling_document)
    document = canonical["document"]
    content_hash = document["content_hash"]

    chunks: list[TextChunk] = []
    current_blocks: list[TextBlock] = []
    current_len = 0

    for block in blocks:
        for candidate in _split_long_block(block, max_chars=max_chars):
            candidate_len = len(candidate.text)
            if current_blocks and current_len + candidate_len + 2 > max_chars:
                chunks.append(
                    _make_chunk(
                        chunk_index=len(chunks),
                        blocks=current_blocks,
                        content_hash=content_hash,
                        filename=document["filename"],
                        source_path=document["source_path"],
                        source_artifact_path=display_path(canonical_path),
                    )
                )
                current_blocks = []
                current_len = 0

            current_blocks.append(candidate)
            current_len += candidate_len + 2

    if current_blocks:
        chunks.append(
            _make_chunk(
                chunk_index=len(chunks),
                blocks=current_blocks,
                content_hash=content_hash,
                filename=document["filename"],
                source_path=document["source_path"],
                source_artifact_path=display_path(canonical_path),
            )
        )

    return chunks


def _extract_text_blocks(docling_document: dict) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    for item in docling_document.get("texts", []):
        label = str(item.get("label") or "text")
        if label in SKIPPED_LABELS:
            continue

        text = _normalize_text(str(item.get("text") or ""))
        if not text:
            continue

        prov = item.get("prov") or []
        page_no = None
        if prov and isinstance(prov[0], dict):
            page_no = prov[0].get("page_no")

        blocks.append(
            TextBlock(
                text=text,
                label=label,
                page_no=page_no if isinstance(page_no, int) else None,
                source_ref=item.get("self_ref"),
            )
        )
    return blocks


def _split_long_block(block: TextBlock, *, max_chars: int) -> list[TextBlock]:
    if len(block.text) <= max_chars:
        return [block]

    words = block.text.split()
    parts: list[TextBlock] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        if current and current_len + len(word) + 1 > max_chars:
            parts.append(
                TextBlock(
                    text=" ".join(current),
                    label=block.label,
                    page_no=block.page_no,
                    source_ref=block.source_ref,
                )
            )
            current = []
            current_len = 0
        current.append(word)
        current_len += len(word) + 1

    if current:
        parts.append(
            TextBlock(
                text=" ".join(current),
                label=block.label,
                page_no=block.page_no,
                source_ref=block.source_ref,
            )
        )
    return parts


def _make_chunk(
    *,
    chunk_index: int,
    blocks: list[TextBlock],
    content_hash: str,
    filename: str,
    source_path: str,
    source_artifact_path: str,
) -> TextChunk:
    pages = [block.page_no for block in blocks if block.page_no is not None]
    chunk_id = f"{content_hash[:12]}:text:{chunk_index:04d}"
    point_id = str(uuid5(NAMESPACE_URL, chunk_id))
    text = "\n\n".join(_format_block(block) for block in blocks)

    return TextChunk(
        id=point_id,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        content_hash=content_hash,
        filename=filename,
        source_path=source_path,
        source_artifact_path=source_artifact_path,
        text=text,
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
    )


def _format_block(block: TextBlock) -> str:
    if block.label == "section_header":
        return f"## {block.text}"
    return block.text


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
