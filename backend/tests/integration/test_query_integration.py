from __future__ import annotations

import pytest
from sqlalchemy import select

from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.indexing import TextIndexingService
from docifer_backend.retrieval.query import TextQueryService

from helpers import (
    TEXT_COLLECTION,
    TABLE_COLLECTION,
    VISUAL_COLLECTION,
    QUERY_HASH_A,
    DOCLING_TEXT,
    make_canonical_fixture,
)


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def query_canonical(tmp_path_factory, pg_session_factory, qdrant_client, fake_provider):
    tmp = tmp_path_factory.mktemp("query_doc")
    path = make_canonical_fixture(
        tmp, name="query_doc", content_hash=QUERY_HASH_A, docling_data=DOCLING_TEXT
    )
    with pg_session_factory() as session:
        session.add(Document(
            filename="query_doc.pdf",
            source_path=str(tmp / "query_doc" / "query_doc.pdf"),
            content_hash=QUERY_HASH_A, file_size_bytes=100,
        ))
        session.commit()
    TextIndexingService(
        session_factory=pg_session_factory,
        ai_provider=fake_provider,
        qdrant_client=qdrant_client,
        collection_name=TEXT_COLLECTION,
        initialize_schema=False,
    ).index_canonical_document(path, force_reindex=True)
    yield path
    with pg_session_factory() as session:
        doc = session.scalar(select(Document).where(Document.content_hash == QUERY_HASH_A))
        if doc:
            try:
                session.delete(doc)
                session.commit()
            except Exception:
                session.rollback()


def _make_svc(pg_session_factory, qdrant_client, fake_provider):
    return TextQueryService(
        session_factory=pg_session_factory,
        ai_provider=fake_provider,
        qdrant_client=qdrant_client,
        collection_name=TEXT_COLLECTION,
        table_collection_name=TABLE_COLLECTION,
        visual_collection_name=VISUAL_COLLECTION,
    )


def test_query_returns_answer(
    query_canonical, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).query(
        question="What reforms help countries escape the middle-income trap?",
        scope="single",
        content_hash=QUERY_HASH_A,
        evidence_mode="text",
        verify_citations=False,
    )
    assert outcome.answer
    assert len(outcome.answer) > 10


def test_query_single_scope_retrieves_relevant_evidence(
    query_canonical, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).query(
        question="institutional quality and human capital",
        scope="single",
        content_hash=QUERY_HASH_A,
        evidence_mode="text",
        top_k=5,
        verify_citations=False,
    )
    assert outcome.evidence or outcome.unused_evidence, "Expected at least some retrieved evidence"
    all_evidence = list(outcome.evidence) + list(outcome.unused_evidence)
    for chunk in all_evidence:
        assert chunk.content_hash == QUERY_HASH_A
