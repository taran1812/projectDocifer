from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qdrant_client import QdrantClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.config.settings import get_settings
from docifer_backend.ingestion.models import Document, DocumentIndexRun, utc_now
from docifer_backend.ingestion.status import IngestionStatus
from docifer_backend.providers.base import AIProvider
from docifer_backend.providers.factory import get_ai_provider
from docifer_backend.retrieval.chunking import TextChunk, build_text_chunks_from_canonical
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.retrieval.vector_store import upsert_text_chunks
from docifer_backend.storage.database import create_database_schema, get_session_factory
from docifer_backend.storage.qdrant import get_qdrant_client


TEXT_INDEX_VERSION = "text-rag-baseline-v1"


@dataclass(frozen=True)
class TextIndexOutcome:
    document_id: str
    content_hash: str
    status: str
    chunk_count: int
    collection_name: str
    reused_existing: bool


class TextIndexingService:
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
        self.collection_name = collection_name or settings.qdrant_text_collection
        self.qdrant_upsert_batch_size = settings.qdrant_upsert_batch_size

    def index_canonical_document(
        self,
        canonical_path: str | Path,
        *,
        force_reindex: bool = False,
    ) -> TextIndexOutcome:
        chunks = build_text_chunks_from_canonical(canonical_path)
        if not chunks:
            raise ValueError("No text chunks were produced from the canonical document.")

        content_hash = chunks[0].content_hash
        with self.session_factory() as session:
            document = session.scalar(
                select(Document).where(Document.content_hash == content_hash)
            )
            if document is None:
                raise ValueError(f"No document row found for content hash: {content_hash}")

            existing_run = self._find_index_run(session, document.id, content_hash)
            if (
                existing_run
                and existing_run.status == IngestionStatus.INDEXED.value
                and not force_reindex
            ):
                chunk_count = session.scalar(
                    select(func.count())
                    .select_from(TextChunkRecord)
                    .where(TextChunkRecord.document_id == document.id)
                    .where(TextChunkRecord.content_hash == content_hash)
                )
                return TextIndexOutcome(
                    document_id=document.id,
                    content_hash=content_hash,
                    status=existing_run.status,
                    chunk_count=int(chunk_count or 0),
                    collection_name=self.collection_name,
                    reused_existing=True,
                )

            index_run = existing_run or DocumentIndexRun(
                document_id=document.id,
                content_hash=content_hash,
                index_name=self.collection_name,
                index_version=TEXT_INDEX_VERSION,
                status=IngestionStatus.INDEXING.value,
            )
            index_run.status = IngestionStatus.INDEXING.value
            index_run.completed_at = None
            session.add(index_run)
            session.commit()
            document_id = document.id

        try:
            embeddings = self.ai_provider.embed_texts([chunk.text for chunk in chunks])
            upsert_text_chunks(
                self.qdrant_client,
                collection_name=self.collection_name,
                chunks=chunks,
                embeddings=embeddings,
                batch_size=self.qdrant_upsert_batch_size,
            )
            self._replace_chunk_records(document_id, chunks)
        except Exception:
            self._mark_index_failed(document_id, content_hash)
            raise

        return TextIndexOutcome(
            document_id=document_id,
            content_hash=content_hash,
            status=IngestionStatus.INDEXED.value,
            chunk_count=len(chunks),
            collection_name=self.collection_name,
            reused_existing=False,
        )

    def _replace_chunk_records(self, document_id: str, chunks: list[TextChunk]) -> None:
        content_hash = chunks[0].content_hash
        with self.session_factory() as session:
            session.execute(
                delete(TextChunkRecord)
                .where(TextChunkRecord.document_id == document_id)
                .where(TextChunkRecord.content_hash == content_hash)
            )
            session.add_all(
                [
                    TextChunkRecord(
                        id=chunk.id,
                        document_id=document_id,
                        content_hash=chunk.content_hash,
                        chunk_id=chunk.chunk_id,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        source_path=chunk.source_path,
                        source_artifact_path=chunk.source_artifact_path,
                        qdrant_point_id=chunk.id,
                    )
                    for chunk in chunks
                ]
            )
            index_run = self._find_index_run(session, document_id, content_hash)
            if index_run is None:
                raise RuntimeError("Text index run disappeared before completion.")
            index_run.status = IngestionStatus.INDEXED.value
            index_run.completed_at = utc_now()
            session.commit()

    def _mark_index_failed(self, document_id: str, content_hash: str) -> None:
        with self.session_factory() as session:
            index_run = self._find_index_run(session, document_id, content_hash)
            if index_run:
                index_run.status = IngestionStatus.FAILED.value
                index_run.completed_at = utc_now()
                session.commit()

    def _find_index_run(
        self,
        session: Session,
        document_id: str,
        content_hash: str,
    ) -> DocumentIndexRun | None:
        return session.scalar(
            select(DocumentIndexRun)
            .where(DocumentIndexRun.document_id == document_id)
            .where(DocumentIndexRun.content_hash == content_hash)
            .where(DocumentIndexRun.index_name == self.collection_name)
            .where(DocumentIndexRun.index_version == TEXT_INDEX_VERSION)
        )
