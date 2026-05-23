from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.audit.models import ParseQualityAudit
from docifer_backend.config.paths import resolve_project_path
from docifer_backend.config.settings import get_settings
from docifer_backend.ingestion.models import Document, DocumentIndexRun, IngestionJob
from docifer_backend.ingestion.status import IngestionStatus
from docifer_backend.retrieval.document_registry import (
    AmbiguousDocumentIdentityError,
    DocumentScopeResolver,
    doc_id_for_document,
)
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.retrieval.tables.indexing import TABLE_INDEX_STATUS_NO_EVIDENCE
from docifer_backend.retrieval.tables.models import DocumentTableIndexRun, TableEvidenceRecord
from docifer_backend.retrieval.visuals.indexing import VISUAL_INDEX_STATUS_NO_EVIDENCE
from docifer_backend.retrieval.visuals.models import DocumentVisualIndexRun, VisualEvidenceRecord
from docifer_backend.schemas.documents import (
    ArtifactReference,
    DocumentArtifactsResponse,
    DocumentAuditResponse,
    DocumentAuditSummaryResponse,
    DocumentDetailResponse,
    DocumentIndexStatusResponse,
    DocumentListResponse,
    DocumentModalitiesResponse,
    DocumentSummaryResponse,
    LatestIngestionResponse,
    ModalityIndexStatus,
    ParseAuditMetricsResponse,
    VisualArtifactReference,
)
from docifer_backend.storage.database import create_database_schema, get_session_factory


class DocumentRegistryNotFoundError(LookupError):
    """Raised when a requested document identity is absent."""


class DocumentRegistryAmbiguousError(LookupError):
    """Raised when a requested identity maps to more than one document."""


@dataclass(frozen=True)
class _RegistryContext:
    latest_jobs: dict[str, IngestionJob]
    latest_audits: dict[str, ParseQualityAudit]
    text_counts: dict[str, int]
    table_counts: dict[str, int]
    visual_counts: dict[str, int]
    text_runs: dict[str, DocumentIndexRun]
    table_runs: dict[str, DocumentTableIndexRun]
    visual_runs: dict[str, DocumentVisualIndexRun]


class DocumentRegistryService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
        identity_resolver: DocumentScopeResolver | None = None,
    ) -> None:
        if session_factory is None:
            _ensure_database_schema()
        self.session_factory = session_factory or get_session_factory()
        self.identity_resolver = identity_resolver or DocumentScopeResolver(
            session_factory=self.session_factory
        )
        settings = get_settings()
        self.text_collection = settings.qdrant_text_collection
        self.table_collection = settings.qdrant_table_collection
        self.visual_collection = settings.qdrant_visual_collection

    def list_documents(
        self,
        *,
        q: str | None = None,
        doc_id: str | None = None,
        quality_status: str | None = None,
        text_status: str | None = None,
        table_status: str | None = None,
        visual_status: str | None = None,
        parser_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DocumentListResponse:
        with self.session_factory() as session:
            documents = list(session.scalars(select(Document).order_by(Document.filename)))
            context = self._load_context(session, documents)

        summaries = [self._summary(document, context) for document in documents]
        summaries = [
            summary
            for summary in summaries
            if self._matches_filters(
                summary,
                q=q,
                doc_id=doc_id,
                quality_status=quality_status,
                text_status=text_status,
                table_status=table_status,
                visual_status=visual_status,
                parser_name=parser_name,
            )
        ]
        total = len(summaries)
        return DocumentListResponse(
            documents=summaries[offset : offset + limit],
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_document(self, document_id: str) -> DocumentDetailResponse:
        document, context = self._document_and_context(document_id)
        audit = context.latest_audits.get(document.id)
        job = context.latest_jobs.get(document.id)
        return DocumentDetailResponse(
            document_id=document.id,
            doc_id=doc_id_for_document(document),
            content_hash=document.content_hash,
            filename=document.filename,
            source_path=document.source_path,
            file_size_bytes=document.file_size_bytes,
            latest_ingestion=self._ingestion_response(job),
            modalities=self._modalities(document.id, context),
            latest_audit=self._audit_summary(audit),
            artifacts=self._artifact_references(job, audit),
        )

    def get_by_doc_id(self, doc_id: str) -> DocumentDetailResponse:
        try:
            resolution = self.identity_resolver.resolve(
                scope="doc_ids",
                content_hash=None,
                doc_ids=[doc_id],
                document_ids=None,
                evidence_types={"text"},
            )
        except AmbiguousDocumentIdentityError as exc:
            raise DocumentRegistryAmbiguousError("Document lookup is ambiguous.") from exc
        except ValueError as exc:
            raise DocumentRegistryNotFoundError(
                f"No document is mapped to doc_id {doc_id}."
            ) from exc
        if len(resolution.documents) != 1:
            raise DocumentRegistryAmbiguousError("Document lookup is ambiguous.")
        return self.get_document(resolution.documents[0].document_id)

    def get_by_content_hash(self, content_hash: str) -> DocumentDetailResponse:
        resolution = self.identity_resolver.resolve(
            scope="single",
            content_hash=content_hash,
            doc_ids=None,
            document_ids=None,
            evidence_types={"text"},
        )
        if not resolution.documents:
            raise DocumentRegistryNotFoundError("Document not found for content hash.")
        if len(resolution.documents) != 1:
            raise DocumentRegistryAmbiguousError("Document lookup is ambiguous.")
        return self.get_document(resolution.documents[0].document_id)

    def get_indexes(self, document_id: str) -> DocumentIndexStatusResponse:
        document, context = self._document_and_context(document_id)
        return DocumentIndexStatusResponse(
            document_id=document.id,
            doc_id=doc_id_for_document(document),
            content_hash=document.content_hash,
            modalities=self._modalities(document.id, context),
        )

    def get_audit(self, document_id: str) -> DocumentAuditResponse:
        document, context = self._document_and_context(document_id)
        audit = self._audit_summary(context.latest_audits.get(document.id))
        return DocumentAuditResponse(
            document_id=document.id,
            doc_id=doc_id_for_document(document),
            content_hash=document.content_hash,
            latest_audit=audit,
            warning=None if audit else "No parse quality audit found for this document.",
        )

    def get_artifacts(self, document_id: str) -> DocumentArtifactsResponse:
        document, context = self._document_and_context(document_id)
        job = context.latest_jobs.get(document.id)
        audit = context.latest_audits.get(document.id)
        with self.session_factory() as session:
            visual_records = list(
                session.scalars(
                    select(VisualEvidenceRecord)
                    .where(VisualEvidenceRecord.document_id == document.id)
                    .where(VisualEvidenceRecord.content_hash == document.content_hash)
                    .order_by(VisualEvidenceRecord.visual_index)
                )
            )
        return DocumentArtifactsResponse(
            document_id=document.id,
            doc_id=doc_id_for_document(document),
            content_hash=document.content_hash,
            artifacts=self._artifact_references(job, audit),
            visual_artifacts=[
                VisualArtifactReference(
                    visual_id=record.visual_id,
                    visual_type=record.visual_type,
                    page_start=record.page_start,
                    artifact_path=_stable_path(record.artifact_path),
                    exists=_path_exists(record.artifact_path),
                    source="visual_evidence_records",
                )
                for record in visual_records
            ],
        )

    def _document_and_context(self, document_id: str) -> tuple[Document, _RegistryContext]:
        with self.session_factory() as session:
            document = session.scalar(select(Document).where(Document.id == document_id))
            if document is None:
                raise DocumentRegistryNotFoundError("Document not found.")
            context = self._load_context(session, [document])
        return document, context

    def _load_context(
        self,
        session: Session,
        documents: list[Document],
    ) -> _RegistryContext:
        document_ids = [document.id for document in documents]
        if not document_ids:
            return _RegistryContext({}, {}, {}, {}, {}, {}, {}, {})

        jobs = list(
            session.scalars(
                select(IngestionJob)
                .where(IngestionJob.document_id.in_(document_ids))
                .order_by(IngestionJob.created_at.desc())
            )
        )
        fallback_jobs = _latest_rows_by_document(jobs)
        jobs_by_id = {job.id: job for job in jobs}
        latest_jobs = {
            document.id: (
                jobs_by_id.get(document.latest_job_id) or fallback_jobs.get(document.id)
            )
            for document in documents
            if jobs_by_id.get(document.latest_job_id) or fallback_jobs.get(document.id)
        }
        audits = list(
            session.scalars(
                select(ParseQualityAudit)
                .where(ParseQualityAudit.document_id.in_(document_ids))
                .where(ParseQualityAudit.is_latest.is_(True))
                .order_by(ParseQualityAudit.created_at.desc())
            )
        )
        text_runs = list(
            session.scalars(
                select(DocumentIndexRun)
                .where(DocumentIndexRun.document_id.in_(document_ids))
                .order_by(DocumentIndexRun.created_at.desc())
            )
        )
        table_runs = list(
            session.scalars(
                select(DocumentTableIndexRun)
                .where(DocumentTableIndexRun.document_id.in_(document_ids))
                .order_by(DocumentTableIndexRun.created_at.desc())
            )
        )
        visual_runs = list(
            session.scalars(
                select(DocumentVisualIndexRun)
                .where(DocumentVisualIndexRun.document_id.in_(document_ids))
                .order_by(DocumentVisualIndexRun.created_at.desc())
            )
        )
        return _RegistryContext(
            latest_jobs=latest_jobs,
            latest_audits=_latest_rows_by_document(audits),
            text_counts=_record_counts(session, TextChunkRecord, document_ids),
            table_counts=_record_counts(session, TableEvidenceRecord, document_ids),
            visual_counts=_record_counts(session, VisualEvidenceRecord, document_ids),
            text_runs=_latest_rows_by_document(text_runs),
            table_runs=_latest_rows_by_document(table_runs),
            visual_runs=_latest_rows_by_document(visual_runs),
        )

    def _summary(
        self,
        document: Document,
        context: _RegistryContext,
    ) -> DocumentSummaryResponse:
        job = context.latest_jobs.get(document.id)
        audit = context.latest_audits.get(document.id)
        return DocumentSummaryResponse(
            document_id=document.id,
            doc_id=doc_id_for_document(document),
            content_hash=document.content_hash,
            filename=document.filename,
            source_path=document.source_path,
            parser_name=job.parser_name if job else None,
            latest_ingestion_status=job.status if job else None,
            quality_status=audit.quality_status if audit else None,
            modalities=self._modalities(document.id, context),
        )

    def _modalities(
        self,
        document_id: str,
        context: _RegistryContext,
    ) -> DocumentModalitiesResponse:
        text_run = context.text_runs.get(document_id)
        table_run = context.table_runs.get(document_id)
        visual_run = context.visual_runs.get(document_id)
        return DocumentModalitiesResponse(
            text=_modality_status(
                count=context.text_counts.get(document_id, 0),
                latest_status=text_run.status if text_run else None,
                collection_name=text_run.index_name if text_run else self.text_collection,
                latest_indexed_at=text_run.completed_at if text_run else None,
                no_evidence_statuses=set(),
            ),
            table=_modality_status(
                count=context.table_counts.get(document_id, 0),
                latest_status=table_run.status if table_run else None,
                collection_name=(
                    table_run.collection_name if table_run else self.table_collection
                ),
                latest_indexed_at=table_run.completed_at if table_run else None,
                no_evidence_statuses={TABLE_INDEX_STATUS_NO_EVIDENCE},
            ),
            visual=_modality_status(
                count=context.visual_counts.get(document_id, 0),
                latest_status=visual_run.status if visual_run else None,
                collection_name=(
                    visual_run.collection_name if visual_run else self.visual_collection
                ),
                latest_indexed_at=visual_run.completed_at if visual_run else None,
                no_evidence_statuses={VISUAL_INDEX_STATUS_NO_EVIDENCE},
            ),
        )

    def _ingestion_response(
        self,
        job: IngestionJob | None,
    ) -> LatestIngestionResponse | None:
        if job is None:
            return None
        return LatestIngestionResponse(
            job_id=job.id,
            status=job.status,
            parser_name=job.parser_name,
            parser_version=job.parser_version,
            artifact_path=_stable_path(job.artifact_path),
            created_at=job.created_at,
            completed_at=job.completed_at,
        )

    def _audit_summary(
        self,
        audit: ParseQualityAudit | None,
    ) -> DocumentAuditSummaryResponse | None:
        if audit is None:
            return None
        return DocumentAuditSummaryResponse(
            audit_id=audit.id,
            audit_status=audit.audit_status,
            quality_status=audit.quality_status,
            text_readiness=audit.text_readiness,
            table_readiness=audit.table_readiness,
            visual_readiness=audit.visual_readiness,
            risk_flags=list(audit.risk_flags_json or []),
            summary=(
                ParseAuditMetricsResponse.model_validate(audit.summary_json)
                if audit.summary_json is not None
                else None
            ),
            artifact_json=(
                _artifact_reference(
                    audit.artifact_json_path,
                    source="latest_parse_quality_audit",
                    generated_by="audit",
                    artifact_type="parse_audit_json",
                )
                if audit.artifact_json_path
                else None
            ),
            artifact_md=(
                _artifact_reference(
                    audit.artifact_md_path,
                    source="latest_parse_quality_audit",
                    generated_by="audit",
                    artifact_type="parse_audit_md",
                )
                if audit.artifact_md_path
                else None
            ),
            created_at=audit.created_at,
        )

    def _artifact_references(
        self,
        job: IngestionJob | None,
        audit: ParseQualityAudit | None,
    ) -> list[ArtifactReference]:
        references: list[ArtifactReference] = []
        if job and job.artifact_path:
            canonical_path = Path(job.artifact_path)
            references.extend(
                [
                    _artifact_reference(
                        canonical_path,
                        source="latest_ingestion_job",
                        generated_by="ingestion",
                        artifact_type="canonical_json",
                    ),
                    _artifact_reference(
                        canonical_path.with_name("docling.json"),
                        source="latest_ingestion_job",
                        generated_by="ingestion",
                        artifact_type="docling_json",
                    ),
                    _artifact_reference(
                        canonical_path.with_name("document.md"),
                        source="latest_ingestion_job",
                        generated_by="ingestion",
                        artifact_type="document_md",
                    ),
                    _artifact_reference(
                        canonical_path.with_name("parse_summary.json"),
                        source="latest_ingestion_job",
                        generated_by="ingestion",
                        artifact_type="parse_summary_json",
                    ),
                ]
            )
        if audit and audit.artifact_json_path:
            references.append(
                _artifact_reference(
                    audit.artifact_json_path,
                    source="latest_parse_quality_audit",
                    generated_by="audit",
                    artifact_type="parse_audit_json",
                )
            )
        if audit and audit.artifact_md_path:
            references.append(
                _artifact_reference(
                    audit.artifact_md_path,
                    source="latest_parse_quality_audit",
                    generated_by="audit",
                    artifact_type="parse_audit_md",
                )
            )
        return references

    @staticmethod
    def _matches_filters(
        summary: DocumentSummaryResponse,
        *,
        q: str | None,
        doc_id: str | None,
        quality_status: str | None,
        text_status: str | None,
        table_status: str | None,
        visual_status: str | None,
        parser_name: str | None,
    ) -> bool:
        if doc_id and summary.doc_id != doc_id:
            return False
        if quality_status and summary.quality_status != quality_status:
            return False
        if parser_name and summary.parser_name != parser_name:
            return False
        if text_status and summary.modalities.text.status != text_status:
            return False
        if table_status and summary.modalities.table.status != table_status:
            return False
        if visual_status and summary.modalities.visual.status != visual_status:
            return False
        if q:
            value = q.lower()
            searchable = " ".join(
                filter(
                    None,
                    [
                        summary.doc_id,
                        summary.filename,
                        summary.source_path,
                        summary.content_hash,
                    ],
                )
            ).lower()
            return value in searchable
        return True


def _latest_rows_by_document(rows: list) -> dict[str, object]:
    latest: dict[str, object] = {}
    for row in rows:
        latest.setdefault(row.document_id, row)
    return latest


def _record_counts(session: Session, model, document_ids: list[str]) -> dict[str, int]:
    return {
        document_id: int(count)
        for document_id, count in session.execute(
            select(model.document_id, func.count())
            .where(model.document_id.in_(document_ids))
            .group_by(model.document_id)
        ).all()
    }


def _modality_status(
    *,
    count: int,
    latest_status: str | None,
    collection_name: str,
    latest_indexed_at,
    no_evidence_statuses: set[str],
) -> ModalityIndexStatus:
    if latest_status == IngestionStatus.FAILED.value:
        status = "failed"
    elif count > 0:
        status = "indexed"
    elif latest_status in no_evidence_statuses:
        status = "not_available"
    elif latest_status is None:
        status = "not_indexed"
    else:
        status = "unknown"
    return ModalityIndexStatus(
        status=status,
        count=count,
        latest_status=latest_status,
        collection_name=collection_name,
        latest_indexed_at=latest_indexed_at,
    )


def _artifact_reference(
    path: str | Path,
    *,
    source: str,
    generated_by: str,
    artifact_type: str,
) -> ArtifactReference:
    return ArtifactReference(
        path=_stable_path(path),
        exists=_path_exists(path),
        source=source,
        generated_by=generated_by,
        artifact_type=artifact_type,
    )


def _path_exists(path: str | Path | None) -> bool:
    return bool(path and resolve_project_path(path).exists())


def _stable_path(path: str | Path | None) -> str | None:
    return Path(path).as_posix() if path is not None else None


@lru_cache(maxsize=1)
def _ensure_database_schema() -> None:
    create_database_schema()
