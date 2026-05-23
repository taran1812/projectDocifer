from __future__ import annotations

import pytest
from sqlalchemy import select

from docifer_backend.ingestion.models import Document
from docifer_backend.documents.service import (
    DocumentRegistryService,
    DocumentRegistryNotFoundError,
)

from conftest import REGISTRY_HASH


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def registry_document(pg_session_factory):
    with pg_session_factory() as session:
        doc = Document(
            filename="registry_test.pdf",
            source_path="/tmp/registry_test.pdf",
            content_hash=REGISTRY_HASH,
            file_size_bytes=512,
        )
        session.add(doc)
        session.commit()
        doc_id = doc.id
    yield doc_id
    with pg_session_factory() as session:
        doc = session.scalar(select(Document).where(Document.content_hash == REGISTRY_HASH))
        if doc:
            session.delete(doc)
            session.commit()


def _make_svc(pg_session_factory):
    return DocumentRegistryService(session_factory=pg_session_factory)


def test_list_documents_includes_seeded_document(registry_document, pg_session_factory):
    response = _make_svc(pg_session_factory).list_documents()
    content_hashes = [d.content_hash for d in response.documents]
    assert REGISTRY_HASH in content_hashes


def test_get_document_returns_correct_metadata(registry_document, pg_session_factory):
    detail = _make_svc(pg_session_factory).get_document(registry_document)
    assert detail.document_id == registry_document
    assert detail.content_hash == REGISTRY_HASH
    assert detail.filename == "registry_test.pdf"


def test_get_by_content_hash_resolves_document(registry_document, pg_session_factory):
    detail = _make_svc(pg_session_factory).get_by_content_hash(REGISTRY_HASH)
    assert detail.document_id == registry_document
    assert detail.content_hash == REGISTRY_HASH


def test_get_indexes_returns_status_response(registry_document, pg_session_factory):
    status = _make_svc(pg_session_factory).get_indexes(registry_document)
    assert status.document_id == registry_document
    assert status.content_hash == REGISTRY_HASH


def test_get_by_content_hash_raises_for_unknown_hash(pg_session_factory):
    with pytest.raises(Exception):
        _make_svc(pg_session_factory).get_by_content_hash("0" * 64)
