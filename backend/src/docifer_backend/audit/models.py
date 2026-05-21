from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from docifer_backend.ingestion.models import new_uuid, utc_now
from docifer_backend.storage.database import Base


class ParseQualityAudit(Base):
    __tablename__ = "parse_quality_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    canonical_path: Mapped[str] = mapped_column(Text, nullable=False)

    parser_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    audit_version: Mapped[str] = mapped_column(String(32), nullable=False)
    audit_run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    audit_status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    quality_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    text_readiness: Mapped[str | None] = mapped_column(String(16), nullable=True)
    table_readiness: Mapped[str | None] = mapped_column(String(16), nullable=True)
    visual_readiness: Mapped[str | None] = mapped_column(String(16), nullable=True)

    risk_flags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    artifact_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_md_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
