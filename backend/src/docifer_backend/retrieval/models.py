from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from docifer_backend.ingestion.models import utc_now
from docifer_backend.storage.database import Base


class TextChunkRecord(Base):
    __tablename__ = "text_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "content_hash",
            "chunk_id",
            name="uq_text_chunks_document_hash_chunk",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    qdrant_point_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
