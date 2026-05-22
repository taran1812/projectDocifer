from __future__ import annotations

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.config.paths import resolve_project_path
from docifer_backend.config.settings import get_settings
from docifer_backend.ingestion.models import Document, utc_now
from docifer_backend.providers.base import AIProvider
from docifer_backend.providers.factory import get_ai_provider
from docifer_backend.retrieval.vector_store import (
    delete_visual_evidence_by_content_hash,
    upsert_visual_evidence,
)
from docifer_backend.retrieval.visuals.extraction import extract_visual_evidence_from_canonical
from docifer_backend.retrieval.visuals.models import DocumentVisualIndexRun, VisualEvidenceRecord
from docifer_backend.retrieval.visuals.rendering import render_pdf_pages
from docifer_backend.retrieval.visuals.schemas import (
    VisualEvidence,
    VisualIndexOutcome,
    format_visual_evidence_for_embedding,
)
from docifer_backend.storage.database import create_database_schema, get_session_factory
from docifer_backend.storage.qdrant import get_qdrant_client


VISUAL_INDEX_STATUS_INDEXING = "indexing"
VISUAL_INDEX_STATUS_INDEXED = "indexed"
VISUAL_INDEX_STATUS_NO_EVIDENCE = "no_visual_evidence"
VISUAL_INDEX_STATUS_FAILED = "failed"


class VisualIndexingService:
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
        self.collection_name = collection_name or settings.qdrant_visual_collection
        self.qdrant_upsert_batch_size = settings.qdrant_upsert_batch_size

    def index_canonical_document(
        self,
        canonical_path: str | Path,
        *,
        force_reindex: bool = False,
    ) -> VisualIndexOutcome:
        canonical_path = Path(canonical_path)
        canonical = _read_canonical(canonical_path)
        content_hash = str(canonical["document"]["content_hash"])

        with self.session_factory() as session:
            document = session.scalar(select(Document).where(Document.content_hash == content_hash))
            if document is None:
                raise ValueError(f"No document row found for content hash: {content_hash}")

            existing_run = self._find_index_run(session, document.id, content_hash)
            existing_count = self._record_count(session, document.id, content_hash)
            needs_stale_cleanup = bool(existing_run and existing_count > 0)
            if existing_run and not force_reindex:
                if existing_run.status == VISUAL_INDEX_STATUS_INDEXED and existing_count > 0:
                    return self._outcome_from_run(existing_run, reused_existing=True)
                if existing_run.status == VISUAL_INDEX_STATUS_NO_EVIDENCE and existing_count == 0:
                    return self._outcome_from_run(existing_run, reused_existing=True)
            document_id = document.id

        if force_reindex or needs_stale_cleanup:
            self._delete_existing(document_id, content_hash)

        source_path = resolve_project_path(canonical["document"]["source_path"])
        artifact_dir = resolve_project_path(
            canonical.get("artifacts", {}).get("directory") or canonical_path.parent
        )
        pages_dir = artifact_dir / "visuals" / "pages"
        rendered = render_pdf_pages(source_path, pages_dir)
        page_render_count = len(rendered)

        visuals = extract_visual_evidence_from_canonical(
            canonical_path,
            document_id=document_id,
        )

        self._start_index_run(
            document_id=document_id,
            content_hash=content_hash,
            canonical_path=str(canonical_path),
        )

        figure_candidate_count = sum(1 for v in visuals if v.visual_type == "figure_candidate")

        if not visuals:
            self._complete_index_run(
                document_id=document_id,
                content_hash=content_hash,
                status=VISUAL_INDEX_STATUS_NO_EVIDENCE,
                page_render_count=page_render_count,
                figure_candidate_count=0,
                visual_record_count=0,
            )
            return VisualIndexOutcome(
                document_id=document_id,
                content_hash=content_hash,
                status=VISUAL_INDEX_STATUS_NO_EVIDENCE,
                page_render_count=page_render_count,
                figure_candidate_count=0,
                visual_record_count=0,
                collection_name=self.collection_name,
                reused_existing=False,
            )

        point_ids = [str(uuid5(NAMESPACE_URL, visual.visual_id)) for visual in visuals]
        try:
            self._insert_records(visuals)
            embeddings = self.ai_provider.embed_texts(
                [format_visual_evidence_for_embedding(visual) for visual in visuals]
            )
            upsert_visual_evidence(
                self.qdrant_client,
                collection_name=self.collection_name,
                visuals=visuals,
                embeddings=embeddings,
                point_ids=point_ids,
                batch_size=self.qdrant_upsert_batch_size,
            )
            self._mark_records_indexed(visuals, point_ids)
            self._complete_index_run(
                document_id=document_id,
                content_hash=content_hash,
                status=VISUAL_INDEX_STATUS_INDEXED,
                page_render_count=page_render_count,
                figure_candidate_count=figure_candidate_count,
                visual_record_count=len(visuals),
            )
        except Exception as exc:
            self._mark_index_failed(document_id, content_hash, str(exc))
            raise

        return VisualIndexOutcome(
            document_id=document_id,
            content_hash=content_hash,
            status=VISUAL_INDEX_STATUS_INDEXED,
            page_render_count=page_render_count,
            figure_candidate_count=figure_candidate_count,
            visual_record_count=len(visuals),
            collection_name=self.collection_name,
            reused_existing=False,
        )

    def _delete_existing(self, document_id: str, content_hash: str) -> None:
        delete_visual_evidence_by_content_hash(
            self.qdrant_client,
            collection_name=self.collection_name,
            content_hash=content_hash,
        )
        with self.session_factory() as session:
            session.execute(
                delete(VisualEvidenceRecord)
                .where(VisualEvidenceRecord.document_id == document_id)
                .where(VisualEvidenceRecord.content_hash == content_hash)
            )
            session.commit()

    def _insert_records(self, visuals: list[VisualEvidence]) -> None:
        with self.session_factory() as session:
            session.add_all([
                VisualEvidenceRecord(
                    document_id=visual.document_id,
                    content_hash=visual.content_hash,
                    canonical_path=visual.canonical_path,
                    filename=visual.filename,
                    source_path=visual.source_path,
                    source_artifact_path=visual.source_artifact_path,
                    visual_id=visual.visual_id,
                    visual_index=visual.visual_index,
                    visual_type=visual.visual_type,
                    source_kind=visual.source_kind,
                    page_start=visual.page_start,
                    page_end=visual.page_end,
                    artifact_path=visual.artifact_path,
                    caption=visual.caption,
                    section_heading=visual.section_heading,
                    nearby_text=visual.nearby_text,
                    figure_label=visual.figure_label,
                    visual_readiness=visual.visual_readiness,
                    extraction_method=visual.extraction_method,
                    source_chunk_ids_json=visual.source_chunk_ids,
                    span_hash=visual.span_hash,
                    qdrant_point_id=None,
                    indexed_at=None,
                )
                for visual in visuals
            ])
            session.commit()

    def _mark_records_indexed(self, visuals: list[VisualEvidence], point_ids: list[str]) -> None:
        indexed_at = utc_now()
        with self.session_factory() as session:
            for visual, point_id in zip(visuals, point_ids, strict=True):
                record = session.scalar(
                    select(VisualEvidenceRecord).where(VisualEvidenceRecord.visual_id == visual.visual_id)
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
    ) -> DocumentVisualIndexRun:
        with self.session_factory() as session:
            index_run = self._find_index_run(session, document_id, content_hash)
            if index_run is None:
                index_run = DocumentVisualIndexRun(
                    document_id=document_id,
                    content_hash=content_hash,
                    canonical_path=canonical_path,
                    collection_name=self.collection_name,
                    status=VISUAL_INDEX_STATUS_INDEXING,
                )
            index_run.status = VISUAL_INDEX_STATUS_INDEXING
            index_run.canonical_path = canonical_path
            index_run.page_render_count = 0
            index_run.figure_candidate_count = 0
            index_run.visual_record_count = 0
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
        page_render_count: int,
        figure_candidate_count: int,
        visual_record_count: int,
    ) -> None:
        with self.session_factory() as session:
            index_run = self._find_index_run(session, document_id, content_hash)
            if index_run is None:
                raise RuntimeError("Visual index run disappeared before completion.")
            index_run.status = status
            index_run.page_render_count = page_render_count
            index_run.figure_candidate_count = figure_candidate_count
            index_run.visual_record_count = visual_record_count
            index_run.completed_at = utc_now()
            session.commit()

    def _mark_index_failed(self, document_id: str, content_hash: str, error_message: str) -> None:
        with self.session_factory() as session:
            index_run = self._find_index_run(session, document_id, content_hash)
            if index_run:
                index_run.status = VISUAL_INDEX_STATUS_FAILED
                index_run.error_message = error_message[:4000]
                index_run.completed_at = utc_now()
                session.commit()

    def _find_index_run(
        self,
        session: Session,
        document_id: str,
        content_hash: str,
    ) -> DocumentVisualIndexRun | None:
        return session.scalar(
            select(DocumentVisualIndexRun)
            .where(DocumentVisualIndexRun.document_id == document_id)
            .where(DocumentVisualIndexRun.content_hash == content_hash)
            .where(DocumentVisualIndexRun.collection_name == self.collection_name)
        )

    def _record_count(self, session: Session, document_id: str, content_hash: str) -> int:
        return int(
            session.scalar(
                select(func.count())
                .select_from(VisualEvidenceRecord)
                .where(VisualEvidenceRecord.document_id == document_id)
                .where(VisualEvidenceRecord.content_hash == content_hash)
            )
            or 0
        )

    def _outcome_from_run(
        self,
        run: DocumentVisualIndexRun,
        *,
        reused_existing: bool,
    ) -> VisualIndexOutcome:
        return VisualIndexOutcome(
            document_id=run.document_id,
            content_hash=run.content_hash,
            status=run.status,
            page_render_count=run.page_render_count,
            figure_candidate_count=run.figure_candidate_count,
            visual_record_count=run.visual_record_count,
            collection_name=run.collection_name,
            reused_existing=reused_existing,
        )


def _read_canonical(canonical_path: Path) -> dict:
    return json.loads(resolve_project_path(canonical_path).read_text(encoding="utf-8"))
