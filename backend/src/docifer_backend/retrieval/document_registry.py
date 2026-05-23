from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.retrieval.tables.models import TableEvidenceRecord
from docifer_backend.retrieval.visuals.models import VisualEvidenceRecord
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
class QueryDocumentRef:
    doc_id: str | None
    document_id: str
    content_hash: str
    filename: str
    source_path: str

    def as_debug(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "document_id": self.document_id,
            "content_hash": self.content_hash,
            "filename": self.filename,
            "source_path": self.source_path,
        }


@dataclass(frozen=True)
class ScopeResolution:
    scope: str
    documents: list[QueryDocumentRef]
    content_hashes: list[str] | None

    @property
    def by_content_hash(self) -> dict[str, QueryDocumentRef]:
        return {document.content_hash: document for document in self.documents}


class DocumentScopeResolver:
    def __init__(self, *, session_factory: sessionmaker[Session] | None = None) -> None:
        self.session_factory = session_factory or get_session_factory()

    def resolve(
        self,
        *,
        scope: str,
        content_hash: str | None,
        doc_ids: list[str] | None,
        document_ids: list[str] | None,
        evidence_types: set[str],
    ) -> ScopeResolution:
        if scope == "single":
            return self._resolve_single(
                content_hash=content_hash,
                doc_ids=doc_ids,
                document_ids=document_ids,
            )
        if scope == "doc_ids":
            documents = self._resolve_selected(doc_ids=doc_ids, document_ids=document_ids)
            return ScopeResolution(
                scope=scope,
                documents=documents,
                content_hashes=[document.content_hash for document in documents],
            )
        if scope == "all":
            return ScopeResolution(
                scope=scope,
                documents=self._all_indexed(evidence_types=evidence_types),
                content_hashes=None,
            )
        raise ValueError(f"Unsupported query scope: {scope}")

    def _resolve_single(
        self,
        *,
        content_hash: str | None,
        doc_ids: list[str] | None,
        document_ids: list[str] | None,
    ) -> ScopeResolution:
        if content_hash:
            with self.session_factory() as session:
                document = session.scalar(
                    select(Document).where(Document.content_hash == content_hash)
                )
                documents = [self._to_ref(document)] if document else []
            return ScopeResolution(
                scope="single",
                documents=documents,
                content_hashes=[content_hash],
            )
        documents = self._resolve_selected(doc_ids=doc_ids, document_ids=document_ids)
        if len(documents) != 1:
            raise ValueError("scope='single' requires exactly one selected document.")
        return ScopeResolution(
            scope="single",
            documents=documents,
            content_hashes=[documents[0].content_hash],
        )

    def _resolve_selected(
        self,
        *,
        doc_ids: list[str] | None,
        document_ids: list[str] | None,
    ) -> list[QueryDocumentRef]:
        selected: list[QueryDocumentRef] = []
        with self.session_factory() as session:
            for doc_id in doc_ids or []:
                filename = LOCAL_CORPUS_FILENAMES.get(doc_id)
                if filename is None:
                    raise ValueError(f"Unknown doc_id: {doc_id}")
                document = session.scalar(
                    select(Document).where(Document.filename == filename)
                )
                if document is None:
                    document = session.scalar(
                        select(Document).where(Document.source_path.like(f"%{filename}"))
                    )
                if document is None:
                    raise ValueError(f"Document is not ingested for doc_id: {doc_id}")
                selected.append(self._to_ref(document, doc_id=doc_id))

            for document_id in document_ids or []:
                document = session.scalar(
                    select(Document).where(Document.id == document_id)
                )
                if document is None:
                    raise ValueError(f"Unknown document_id: {document_id}")
                selected.append(self._to_ref(document))

        return _dedupe_documents(selected)

    def _all_indexed(self, *, evidence_types: set[str]) -> list[QueryDocumentRef]:
        with self.session_factory() as session:
            documents = list(session.scalars(select(Document).order_by(Document.filename)))
            return [
                self._to_ref(document)
                for document in documents
                if self._has_evidence(
                    session,
                    document=document,
                    evidence_types=evidence_types,
                )
            ]

    def _has_evidence(
        self,
        session: Session,
        *,
        document: Document,
        evidence_types: set[str],
    ) -> bool:
        models = {
            "text": TextChunkRecord,
            "table": TableEvidenceRecord,
            "visual": VisualEvidenceRecord,
        }
        for evidence_type in evidence_types:
            model = models[evidence_type]
            count = session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.document_id == document.id)
                .where(model.content_hash == document.content_hash)
            )
            if count:
                return True
        return False

    def _to_ref(self, document: Document, *, doc_id: str | None = None) -> QueryDocumentRef:
        return QueryDocumentRef(
            doc_id=doc_id or _external_doc_id(document),
            document_id=document.id,
            content_hash=document.content_hash,
            filename=document.filename,
            source_path=document.source_path,
        )


def _external_doc_id(document: Document) -> str | None:
    filename = document.filename.lower()
    source_path = document.source_path.lower()
    for doc_id, expected_filename in LOCAL_CORPUS_FILENAMES.items():
        expected = expected_filename.lower()
        if filename == expected or source_path.endswith(expected):
            return doc_id
    return None


def _dedupe_documents(documents: list[QueryDocumentRef]) -> list[QueryDocumentRef]:
    deduped: list[QueryDocumentRef] = []
    seen: set[str] = set()
    for document in documents:
        if document.content_hash in seen:
            continue
        seen.add(document.content_hash)
        deduped.append(document)
    return deduped
