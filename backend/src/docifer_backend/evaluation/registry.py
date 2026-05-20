from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.storage.database import get_session_factory


LOCAL_CORPUS_FILENAMES = {
    "DOC-001": "2025_AnnualReport.pdf",
    "DOC-002": "NVIDIA-2025-Annual-Report.pdf",
    "DOC-003": "JPChaseannualreport-2025.pdf",
    "DOC-004": "COSTco-Annual-Report-2025.pdf",
    "DOC-005": "Worldbank2024.pdf",
    "DOC-006": "BOSIB13bdde89d07f1b3711dd8e86adb477.pdf",
    "DOC-007": "OECD.pdf",
    "DOC-008": "WSPR_2024_EN_WEB_1.pdf",
    "DOC-009": "2025-03-12-NASA-HDBK-1009A.pdf",
    "DOC-010": "NIST.SP.800-53r5.pdf",
    "DOC-011": "amtg_handbook.pdf",
    "DOC-012": "9789240115569-eng.pdf",
}


@dataclass(frozen=True)
class IndexedDocumentRef:
    doc_id: str
    filename: str
    document_id: str | None
    content_hash: str | None
    indexed_chunk_count: int

    @property
    def is_indexed(self) -> bool:
        return bool(self.content_hash and self.indexed_chunk_count > 0)


class DocumentRegistry:
    def __init__(self, *, session_factory: sessionmaker[Session] | None = None) -> None:
        self.session_factory = session_factory or get_session_factory()

    def resolve(self, doc_id: str) -> IndexedDocumentRef:
        filename = LOCAL_CORPUS_FILENAMES.get(doc_id)
        if not filename:
            return IndexedDocumentRef(
                doc_id=doc_id,
                filename="",
                document_id=None,
                content_hash=None,
                indexed_chunk_count=0,
            )

        with self.session_factory() as session:
            document = session.scalar(
                select(Document).where(Document.source_path.like(f"%{filename}"))
            )
            if document is None:
                return IndexedDocumentRef(
                    doc_id=doc_id,
                    filename=filename,
                    document_id=None,
                    content_hash=None,
                    indexed_chunk_count=0,
                )

            chunk_count = session.scalar(
                select(func.count())
                .select_from(TextChunkRecord)
                .where(TextChunkRecord.document_id == document.id)
                .where(TextChunkRecord.content_hash == document.content_hash)
            )
            return IndexedDocumentRef(
                doc_id=doc_id,
                filename=filename,
                document_id=document.id,
                content_hash=document.content_hash,
                indexed_chunk_count=int(chunk_count or 0),
            )
