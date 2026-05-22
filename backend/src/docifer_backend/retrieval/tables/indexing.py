from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.config.settings import get_settings
from docifer_backend.ingestion.models import Document, utc_now
from docifer_backend.providers.base import AIProvider
from docifer_backend.providers.factory import get_ai_provider
from docifer_backend.retrieval.tables.extraction import extract_table_evidence_from_canonical
from docifer_backend.retrieval.tables.models import DocumentTableIndexRun, TableEvidenceRecord
from docifer_backend.retrieval.tables.schemas import (
    TableEvidence,
    TableIndexOutcome,
    format_table_evidence_for_embedding,
)
from docifer_backend.retrieval.vector_store import (
    delete_table_evidence_by_content_hash,
    upsert_table_evidence,
)
from docifer_backend.storage.database import create_database_schema, get_session_factory
from docifer_backend.storage.qdrant import get_qdrant_client


TABLE_INDEX_STATUS_INDEXING = "indexing"
TABLE_INDEX_STATUS_INDEXED = "indexed"
TABLE_INDEX_STATUS_NO_EVIDENCE = "no_table_evidence"
TABLE_INDEX_STATUS_FAILED = "failed"


class TableIndexingService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
        ai_provider: AIProvider | None = None,
        qdrant_client: QdrantClient | None = None,
        collection_name: str | None = None,
        initialize_schema: bool = True,
    ) -> None:
        if session_factory is None and initialize_schema:
            create_database_schema()

        settings = get_settings()
        self.session_factory = session_factory or get_session_factory()
        self.ai_provider = ai_provider or get_ai_provider()
        self.qdrant_client = qdrant_client or get_qdrant_client()
        self.collection_name = collection_name or settings.qdrant_table_collection
        self.qdrant_upsert_batch_size = settings.qdrant_upsert_batch_size

    def index_canonical_document(
        self,
        canonical_path: str | Path,
        *,
        force_reindex: bool = False,
    ) -> TableIndexOutcome:
        canonical_path = Path(canonical_path)
        canonical = _read_canonical(canonical_path)
        content_hash = str(canonical["document"]["content_hash"])

        with self.session_factory() as session:
            document = session.scalar(select(Document).where(Document.content_hash == content_hash))
            if document is None:
                raise ValueError(f"No document row found for content hash: {content_hash}")

            existing_run = self._find_index_run(session, document.id, content_hash)
            existing_count = self._table_record_count(session, document.id, content_hash)
            needs_stale_cleanup = bool(existing_run and existing_count > 0)
            if existing_run and not force_reindex:
                if existing_run.status == TABLE_INDEX_STATUS_INDEXED and existing_count > 0:
                    return self._outcome_from_run(existing_run, reused_existing=True)
                if existing_run.status == TABLE_INDEX_STATUS_NO_EVIDENCE and existing_count == 0:
                    return self._outcome_from_run(existing_run, reused_existing=True)
            document_id = document.id

        if force_reindex or needs_stale_cleanup:
            self._delete_existing(document_id, content_hash)

        tables = extract_table_evidence_from_canonical(
            canonical_path,
            document_id=document_id,
            session_factory=self.session_factory,
        )
        index_run = self._start_index_run(
            document_id=document_id,
            content_hash=content_hash,
            canonical_path=str(canonical_path),
        )

        if not tables:
            self._complete_index_run(
                document_id=document_id,
                content_hash=content_hash,
                status=TABLE_INDEX_STATUS_NO_EVIDENCE,
                table_evidence_count=0,
                structured_table_count=0,
                markdown_table_count=0,
                table_like_text_count=0,
            )
            return TableIndexOutcome(
                document_id=document_id,
                content_hash=content_hash,
                status=TABLE_INDEX_STATUS_NO_EVIDENCE,
                table_evidence_count=0,
                structured_table_count=0,
                markdown_table_count=0,
                table_like_text_count=0,
                collection_name=self.collection_name,
                reused_existing=False,
            )

        point_ids = [str(uuid5(NAMESPACE_URL, table.table_id)) for table in tables]
        try:
            self._insert_table_records(tables)
            embeddings = self.ai_provider.embed_texts(
                [format_table_evidence_for_embedding(table) for table in tables]
            )
            upsert_table_evidence(
                self.qdrant_client,
                collection_name=self.collection_name,
                tables=tables,
                embeddings=embeddings,
                point_ids=point_ids,
                batch_size=self.qdrant_upsert_batch_size,
            )
            self._mark_records_indexed(tables, point_ids)
            counts = _counts(tables)
            self._complete_index_run(
                document_id=document_id,
                content_hash=content_hash,
                status=TABLE_INDEX_STATUS_INDEXED,
                table_evidence_count=len(tables),
                structured_table_count=counts["structured"],
                markdown_table_count=counts["markdown_table"],
                table_like_text_count=counts["table_like_text"],
            )
        except Exception as exc:
            self._mark_index_failed(index_run.document_id, index_run.content_hash, str(exc))
            raise

        counts = _counts(tables)
        return TableIndexOutcome(
            document_id=document_id,
            content_hash=content_hash,
            status=TABLE_INDEX_STATUS_INDEXED,
            table_evidence_count=len(tables),
            structured_table_count=counts["structured"],
            markdown_table_count=counts["markdown_table"],
            table_like_text_count=counts["table_like_text"],
            collection_name=self.collection_name,
            reused_existing=False,
        )

    def _delete_existing(self, document_id: str, content_hash: str) -> None:
        delete_table_evidence_by_content_hash(
            self.qdrant_client,
            collection_name=self.collection_name,
            content_hash=content_hash,
        )
        with self.session_factory() as session:
            session.execute(
                delete(TableEvidenceRecord)
                .where(TableEvidenceRecord.document_id == document_id)
                .where(TableEvidenceRecord.content_hash == content_hash)
            )
            session.commit()

    def _insert_table_records(self, tables: list[TableEvidence]) -> None:
        with self.session_factory() as session:
            session.add_all(
                [
                    TableEvidenceRecord(
                        document_id=table.document_id,
                        content_hash=table.content_hash,
                        canonical_path=table.canonical_path,
                        filename=table.filename,
                        source_path=table.source_path,
                        source_artifact_path=table.source_artifact_path,
                        table_id=table.table_id,
                        table_index=table.table_index,
                        table_type=table.table_type,
                        source_kind=table.source_kind,
                        page_start=table.page_start,
                        page_end=table.page_end,
                        title=table.title,
                        caption=table.caption,
                        section_heading=table.section_heading,
                        raw_text=table.raw_text,
                        markdown_table=table.markdown_table,
                        structured_json=table.structured_json,
                        row_count=table.row_count,
                        column_count=table.column_count,
                        has_header=table.has_header,
                        empty_cell_ratio=table.empty_cell_ratio,
                        table_readiness=table.table_readiness,
                        extraction_method=table.extraction_method,
                        risk_flags_json=table.risk_flags,
                        source_chunk_id=table.source_chunk_id,
                        span_hash=table.span_hash,
                        qdrant_point_id=None,
                        indexed_at=None,
                    )
                    for table in tables
                ]
            )
            session.commit()

    def _mark_records_indexed(self, tables: list[TableEvidence], point_ids: list[str]) -> None:
        indexed_at = utc_now()
        with self.session_factory() as session:
            for table, point_id in zip(tables, point_ids, strict=True):
                record = session.scalar(
                    select(TableEvidenceRecord).where(TableEvidenceRecord.table_id == table.table_id)
                )
                if record:
                    record.qdrant_point_id = point_id
                    record.indexed_at = indexed_at
            session.commit()

    def _start_index_run(
        self,
        *,
        document_id: str,
        content_hash: str,
        canonical_path: str,
    ) -> DocumentTableIndexRun:
        with self.session_factory() as session:
            index_run = self._find_index_run(session, document_id, content_hash) or DocumentTableIndexRun(
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=canonical_path,
                collection_name=self.collection_name,
                status=TABLE_INDEX_STATUS_INDEXING,
            )
            index_run.status = TABLE_INDEX_STATUS_INDEXING
            index_run.canonical_path = canonical_path
            index_run.table_evidence_count = 0
            index_run.structured_table_count = 0
            index_run.markdown_table_count = 0
            index_run.table_like_text_count = 0
            index_run.error_message = None
            index_run.completed_at = None
            session.add(index_run)
            session.commit()
            return index_run

    def _complete_index_run(
        self,
        *,
        document_id: str,
        content_hash: str,
        status: str,
        table_evidence_count: int,
        structured_table_count: int,
        markdown_table_count: int,
        table_like_text_count: int,
    ) -> None:
        with self.session_factory() as session:
            index_run = self._find_index_run(session, document_id, content_hash)
            if index_run is None:
                raise RuntimeError("Table index run disappeared before completion.")
            index_run.status = status
            index_run.table_evidence_count = table_evidence_count
            index_run.structured_table_count = structured_table_count
            index_run.markdown_table_count = markdown_table_count
            index_run.table_like_text_count = table_like_text_count
            index_run.completed_at = utc_now()
            session.commit()

    def _mark_index_failed(self, document_id: str, content_hash: str, error_message: str) -> None:
        with self.session_factory() as session:
            index_run = self._find_index_run(session, document_id, content_hash)
            if index_run:
                index_run.status = TABLE_INDEX_STATUS_FAILED
                index_run.error_message = error_message[:4000]
                index_run.completed_at = utc_now()
                session.commit()

    def _find_index_run(
        self,
        session: Session,
        document_id: str,
        content_hash: str,
    ) -> DocumentTableIndexRun | None:
        return session.scalar(
            select(DocumentTableIndexRun)
            .where(DocumentTableIndexRun.document_id == document_id)
            .where(DocumentTableIndexRun.content_hash == content_hash)
            .where(DocumentTableIndexRun.collection_name == self.collection_name)
        )

    def _table_record_count(self, session: Session, document_id: str, content_hash: str) -> int:
        return int(
            session.scalar(
                select(func.count())
                .select_from(TableEvidenceRecord)
                .where(TableEvidenceRecord.document_id == document_id)
                .where(TableEvidenceRecord.content_hash == content_hash)
            )
            or 0
        )

    def _outcome_from_run(
        self,
        run: DocumentTableIndexRun,
        *,
        reused_existing: bool,
    ) -> TableIndexOutcome:
        return TableIndexOutcome(
            document_id=run.document_id,
            content_hash=run.content_hash,
            status=run.status,
            table_evidence_count=run.table_evidence_count,
            structured_table_count=run.structured_table_count,
            markdown_table_count=run.markdown_table_count,
            table_like_text_count=run.table_like_text_count,
            collection_name=run.collection_name,
            reused_existing=reused_existing,
        )


def _counts(tables: list[TableEvidence]) -> dict[str, int]:
    return {
        "structured": sum(1 for table in tables if table.table_type == "structured"),
        "markdown_table": sum(1 for table in tables if table.source_kind == "markdown_table"),
        "table_like_text": sum(1 for table in tables if table.table_type == "table_like_text"),
    }


def _read_canonical(canonical_path: Path) -> dict:
    from docifer_backend.config.paths import resolve_project_path
    import json

    return json.loads(resolve_project_path(canonical_path).read_text(encoding="utf-8"))
