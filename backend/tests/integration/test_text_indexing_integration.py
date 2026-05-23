from __future__ import annotations

import pytest
from sqlalchemy import select

from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.indexing import TextIndexingService
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.retrieval.vector_store import search_text_chunks

from helpers import (
    TEXT_COLLECTION,
    TEXT_CONTENT_HASH,
    DOCLING_TEXT,
    make_canonical_fixture,
)


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def text_canonical(tmp_path_factory, pg_session_factory):
    tmp = tmp_path_factory.mktemp("text_doc")
    canonical_path = make_canonical_fixture(
        tmp, name="text_doc", content_hash=TEXT_CONTENT_HASH, docling_data=DOCLING_TEXT
    )
    with pg_session_factory() as session:
        session.add(Document(
            filename="text_doc.pdf",
            source_path=str(tmp / "text_doc" / "text_doc.pdf"),
            content_hash=TEXT_CONTENT_HASH,
            file_size_bytes=100,
        ))
        session.commit()
    yield canonical_path
    with pg_session_factory() as session:
        doc = session.scalar(
            select(Document).where(Document.content_hash == TEXT_CONTENT_HASH)
        )
        if doc:
            try:
                session.delete(doc)
                session.commit()
            except Exception:
                session.rollback()


def _make_svc(pg_session_factory, qdrant_client, fake_provider):
    return TextIndexingService(
        session_factory=pg_session_factory,
        ai_provider=fake_provider,
        qdrant_client=qdrant_client,
        collection_name=TEXT_COLLECTION,
        initialize_schema=False,
    )


def test_text_indexing_creates_chunk_records(
    text_canonical, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        text_canonical, force_reindex=True
    )
    assert outcome.status == "indexed"
    assert outcome.chunk_count >= 1

    with pg_session_factory() as session:
        rows = list(session.scalars(
            select(TextChunkRecord).where(TextChunkRecord.content_hash == TEXT_CONTENT_HASH)
        ))
    assert len(rows) >= 1


def test_text_qdrant_points_carry_document_id(
    text_canonical, pg_session_factory, qdrant_client, fake_provider
):
    _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        text_canonical, force_reindex=True
    )
    results, _ = qdrant_client.scroll(
        collection_name=TEXT_COLLECTION,
        scroll_filter={
            "must": [{"key": "content_hash", "match": {"value": TEXT_CONTENT_HASH}}]
        },
        with_payload=True,
        limit=50,
    )
    assert results, "No Qdrant text points found"
    for point in results:
        assert point.payload.get("document_id"), (
            f"Missing document_id on point {point.id}"
        )
        assert point.payload["content_hash"] == TEXT_CONTENT_HASH


def test_dense_search_retrieves_indexed_chunk(
    text_canonical, pg_session_factory, qdrant_client, fake_provider
):
    _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        text_canonical, force_reindex=True
    )
    query_vec = fake_provider.embed_texts(["middle-income trap reforms"])[0]
    hits = search_text_chunks(
        qdrant_client,
        collection_name=TEXT_COLLECTION,
        query_vector=query_vec,
        top_k=5,
        content_hash=TEXT_CONTENT_HASH,
    )
    assert hits, "Dense search returned no results"
    assert hits[0].content_hash == TEXT_CONTENT_HASH
    assert hits[0].document_id is not None
