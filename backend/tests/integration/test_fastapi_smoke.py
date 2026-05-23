from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from docifer_backend.documents.service import (
    DocumentRegistryNotFoundError,
    DocumentRegistryService,
)
from docifer_backend.main import create_app
from docifer_backend.schemas.documents import (
    DocumentDetailResponse,
    DocumentIndexStatusResponse,
    DocumentListResponse,
    DocumentModalitiesResponse,
    ModalityIndexStatus,
)

import docifer_backend.api.documents as docs_module
import docifer_backend.api.health as health_module


pytestmark = pytest.mark.integration

_FAKE_DOC_ID = "00000000-0000-0000-0000-000000000001"
_FAKE_HASH = "aaaa" + "0" * 60


def _fake_modality() -> ModalityIndexStatus:
    return ModalityIndexStatus(status="not_indexed", count=0)


def _fake_modalities() -> DocumentModalitiesResponse:
    return DocumentModalitiesResponse(
        text=_fake_modality(), table=_fake_modality(), visual=_fake_modality()
    )


def _fake_detail() -> DocumentDetailResponse:
    return DocumentDetailResponse(
        document_id=_FAKE_DOC_ID,
        doc_id=None,
        content_hash=_FAKE_HASH,
        filename="smoke_test.pdf",
        source_path="/tmp/smoke_test.pdf",
        file_size_bytes=100,
        latest_ingestion=None,
        modalities=_fake_modalities(),
        latest_audit=None,
        artifacts=[],
    )


def _fake_list() -> DocumentListResponse:
    return DocumentListResponse(documents=[], total=0, limit=50, offset=0)


def _fake_index_status() -> DocumentIndexStatusResponse:
    return DocumentIndexStatusResponse(
        document_id=_FAKE_DOC_ID,
        doc_id=None,
        content_hash=_FAKE_HASH,
        modalities=_fake_modalities(),
    )


@pytest.fixture()
def client(monkeypatch):
    mock_svc = MagicMock(spec=DocumentRegistryService)
    mock_svc.list_documents.return_value = _fake_list()
    mock_svc.get_document.return_value = _fake_detail()
    mock_svc.get_by_content_hash.return_value = _fake_detail()
    mock_svc.get_indexes.return_value = _fake_index_status()
    monkeypatch.setattr(docs_module, "DocumentRegistryService", lambda: mock_svc)
    monkeypatch.setattr(health_module, "check_database_connection", lambda: True)
    monkeypatch.setattr(health_module, "check_qdrant_connection", lambda: True)
    monkeypatch.setattr(health_module, "get_qdrant_collection_checks", lambda: {})
    return TestClient(create_app())


@pytest.fixture()
def client_not_found(monkeypatch):
    mock_svc = MagicMock(spec=DocumentRegistryService)
    mock_svc.get_document.side_effect = DocumentRegistryNotFoundError("not found")
    monkeypatch.setattr(docs_module, "DocumentRegistryService", lambda: mock_svc)
    return TestClient(create_app())


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_ready_returns_200_when_services_up(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_list_documents_returns_200(client):
    resp = client.get("/documents")
    assert resp.status_code == 200
    body = resp.json()
    assert "documents" in body
    assert "total" in body


def test_get_document_returns_200(client):
    resp = client.get(f"/documents/{_FAKE_DOC_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == _FAKE_DOC_ID
    assert body["content_hash"] == _FAKE_HASH


def test_get_document_returns_404_for_unknown(client_not_found):
    resp = client_not_found.get(f"/documents/{_FAKE_DOC_ID}")
    assert resp.status_code == 404


def test_get_document_indexes_returns_200(client):
    resp = client.get(f"/documents/{_FAKE_DOC_ID}/indexes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == _FAKE_DOC_ID
