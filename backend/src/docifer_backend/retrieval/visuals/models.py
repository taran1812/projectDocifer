from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from docifer_backend.ingestion.models import new_uuid, utc_now
from docifer_backend.storage.database import Base


class VisualEvidenceRecord(Base):
    __tablename__ = "visual_evidence_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    canonical_path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    visual_id: Mapped[str] = mapped_column(String, nullable=False, index=True, unique=True)
    visual_index: Mapped[int] = mapped_column(Integer, nullable=False)
    visual_type: Mapped[str] = mapped_column(String, nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    nearby_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    figure_label: Mapped[str | None] = mapped_column(String, nullable=True)
    visual_readiness: Mapped[str] = mapped_column(String, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String, nullable=False)
    source_chunk_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    span_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    qdrant_point_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("ix_visual_evidence_document_content", "document_id", "content_hash"),
    )


class DocumentVisualIndexRun(Base):
    __tablename__ = "document_visual_index_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    canonical_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    page_render_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    figure_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    visual_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    collection_name: Mapped[str] = mapped_column(String, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
