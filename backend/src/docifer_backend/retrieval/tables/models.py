from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from docifer_backend.ingestion.models import new_uuid, utc_now
from docifer_backend.storage.database import Base


class TableEvidenceRecord(Base):
    __tablename__ = "table_evidence_records"
    __table_args__ = (
        UniqueConstraint("table_id", name="uq_table_evidence_records_table_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    canonical_path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    table_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    table_index: Mapped[int] = mapped_column(Integer, nullable=False)
    table_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    markdown_table: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_header: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    empty_cell_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    table_readiness: Mapped[str] = mapped_column(String(16), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_flags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_chunk_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    span_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    qdrant_point_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DocumentTableIndexRun(Base):
    __tablename__ = "document_table_index_runs"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "content_hash",
            "collection_name",
            name="uq_document_table_index_runs_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    canonical_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    table_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    structured_table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    markdown_table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    table_like_text_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    collection_name: Mapped[str] = mapped_column(String(128), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
