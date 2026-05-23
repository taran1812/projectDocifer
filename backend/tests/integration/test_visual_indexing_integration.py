from __future__ import annotations

import pytest
from sqlalchemy import select

from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.visuals.indexing import (
    VisualIndexingService,
    VISUAL_INDEX_STATUS_INDEXED,
    VISUAL_INDEX_STATUS_NO_EVIDENCE,
)
from docifer_backend.retrieval.visuals.models import VisualEvidenceRecord

from conftest import (
    VISUAL_COLLECTION,
    VISUAL_CONTENT_HASH,
    DOCLING_VISUAL,
    make_canonical_fixture,
)


pytestmark = pytest.mark.integration

_ZERO_PAGE_HASH = "8" * 63 + "0"


@pytest.fixture(scope="module")
def visual_canonical(tmp_path_factory, pg_session_factory):
    tmp = tmp_path_factory.mktemp("visual_doc")
    path = make_canonical_fixture(
        tmp, name="visual_doc", content_hash=VISUAL_CONTENT_HASH,
        docling_data=DOCLING_VISUAL, page_count=1, with_pdf=True,
    )
    with pg_session_factory() as session:
        session.add(Document(
            filename="visual_doc.pdf",
            source_path=str(tmp / "visual_doc" / "visual_doc.pdf"),
            content_hash=VISUAL_CONTENT_HASH, file_size_bytes=100,
        ))
        session.commit()
    yield path
    with pg_session_factory() as session:
        doc = session.scalar(select(Document).where(Document.content_hash == VISUAL_CONTENT_HASH))
        if doc:
            session.delete(doc)
            session.commit()


@pytest.fixture(scope="module")
def zero_page_canonical(tmp_path_factory, pg_session_factory):
    tmp = tmp_path_factory.mktemp("zero_page_doc")
    path = make_canonical_fixture(
        tmp, name="zero_page_doc", content_hash=_ZERO_PAGE_HASH,
        docling_data=DOCLING_VISUAL, page_count=0, with_pdf=True,
    )
    with pg_session_factory() as session:
        session.add(Document(
            filename="zero_page_doc.pdf",
            source_path=str(tmp / "zero_page_doc" / "zero_page_doc.pdf"),
            content_hash=_ZERO_PAGE_HASH, file_size_bytes=100,
        ))
        session.commit()
    yield path
    with pg_session_factory() as session:
        doc = session.scalar(select(Document).where(Document.content_hash == _ZERO_PAGE_HASH))
        if doc:
            session.delete(doc)
            session.commit()


def _make_svc(pg_session_factory, qdrant_client, fake_provider):
    return VisualIndexingService(
        session_factory=pg_session_factory,
        ai_provider=fake_provider,
        qdrant_client=qdrant_client,
        collection_name=VISUAL_COLLECTION,
        initialize_schema=False,
    )


def test_visual_indexing_creates_evidence_records(
    visual_canonical, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        visual_canonical, force_reindex=True
    )
    assert outcome.status == VISUAL_INDEX_STATUS_INDEXED
    assert outcome.visual_record_count >= 1

    with pg_session_factory() as session:
        rows = list(session.scalars(
            select(VisualEvidenceRecord).where(
                VisualEvidenceRecord.content_hash == VISUAL_CONTENT_HASH
            )
        ))
    assert len(rows) >= 1


def test_visual_qdrant_points_carry_document_id(
    visual_canonical, pg_session_factory, qdrant_client, fake_provider
):
    _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        visual_canonical, force_reindex=True
    )
    results, _ = qdrant_client.scroll(
        collection_name=VISUAL_COLLECTION,
        scroll_filter={
            "must": [{"key": "content_hash", "match": {"value": VISUAL_CONTENT_HASH}}]
        },
        with_payload=True, limit=50,
    )
    assert results
    for point in results:
        assert point.payload.get("document_id"), f"Missing document_id on visual point {point.id}"


def test_visual_zero_pages_returns_no_evidence_status(
    zero_page_canonical, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        zero_page_canonical, force_reindex=True
    )
    assert outcome.status == VISUAL_INDEX_STATUS_NO_EVIDENCE
    assert outcome.visual_record_count == 0
