from __future__ import annotations

import pytest
from sqlalchemy import select

from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.tables.indexing import (
    TableIndexingService,
    TABLE_INDEX_STATUS_INDEXED,
    TABLE_INDEX_STATUS_NO_EVIDENCE,
)
from docifer_backend.retrieval.tables.models import TableEvidenceRecord

from helpers import (
    TABLE_COLLECTION,
    TABLE_CONTENT_HASH,
    DOCLING_TABLE,
    DOCLING_TEXT,
    make_canonical_fixture,
)


pytestmark = pytest.mark.integration

_NO_TABLE_HASH = "9" * 63 + "0"


def _cleanup(pg_session_factory, content_hash):
    with pg_session_factory() as session:
        doc = session.scalar(select(Document).where(Document.content_hash == content_hash))
        if doc:
            try:
                session.delete(doc)
                session.commit()
            except Exception:
                session.rollback()


@pytest.fixture(scope="module")
def table_canonical(tmp_path_factory, pg_session_factory):
    tmp = tmp_path_factory.mktemp("table_doc")
    path = make_canonical_fixture(
        tmp, name="table_doc", content_hash=TABLE_CONTENT_HASH,
        docling_data=DOCLING_TABLE, table_count=1,
    )
    with pg_session_factory() as session:
        session.add(Document(
            filename="table_doc.pdf",
            source_path=str(tmp / "table_doc" / "table_doc.pdf"),
            content_hash=TABLE_CONTENT_HASH, file_size_bytes=100,
        ))
        session.commit()
    yield path
    _cleanup(pg_session_factory, TABLE_CONTENT_HASH)


@pytest.fixture(scope="module")
def no_table_canonical(tmp_path_factory, pg_session_factory):
    tmp = tmp_path_factory.mktemp("no_table_doc")
    path = make_canonical_fixture(
        tmp, name="no_table_doc", content_hash=_NO_TABLE_HASH,
        docling_data=DOCLING_TEXT, table_count=0,
    )
    with pg_session_factory() as session:
        session.add(Document(
            filename="no_table_doc.pdf",
            source_path=str(tmp / "no_table_doc" / "no_table_doc.pdf"),
            content_hash=_NO_TABLE_HASH, file_size_bytes=100,
        ))
        session.commit()
    yield path
    _cleanup(pg_session_factory, _NO_TABLE_HASH)


def _make_svc(pg_session_factory, qdrant_client, fake_provider):
    return TableIndexingService(
        session_factory=pg_session_factory,
        ai_provider=fake_provider,
        qdrant_client=qdrant_client,
        collection_name=TABLE_COLLECTION,
        initialize_schema=False,
    )


def test_table_indexing_creates_evidence_records(
    table_canonical, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        table_canonical, force_reindex=True
    )
    assert outcome.status == TABLE_INDEX_STATUS_INDEXED
    assert outcome.table_evidence_count >= 1

    with pg_session_factory() as session:
        rows = list(session.scalars(
            select(TableEvidenceRecord).where(
                TableEvidenceRecord.content_hash == TABLE_CONTENT_HASH
            )
        ))
    assert len(rows) >= 1


def test_table_qdrant_points_carry_document_id(
    table_canonical, pg_session_factory, qdrant_client, fake_provider
):
    _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        table_canonical, force_reindex=True
    )
    results, _ = qdrant_client.scroll(
        collection_name=TABLE_COLLECTION,
        scroll_filter={
            "must": [{"key": "content_hash", "match": {"value": TABLE_CONTENT_HASH}}]
        },
        with_payload=True, limit=50,
    )
    assert results
    for point in results:
        assert point.payload.get("document_id"), f"Missing document_id on table point {point.id}"


def test_table_zero_evidence_returns_no_evidence_status(
    no_table_canonical, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        no_table_canonical, force_reindex=True
    )
    assert outcome.status == TABLE_INDEX_STATUS_NO_EVIDENCE
    assert outcome.table_evidence_count == 0
