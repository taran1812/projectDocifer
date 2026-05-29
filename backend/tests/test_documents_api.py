from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import docifer_backend.api.documents as documents_module
from docifer_backend.documents.service import (
    DocumentRegistryForbiddenError,
    DocumentRegistryNotFoundError,
    DocumentRegistryService,
)
from docifer_backend.main import create_app
from docifer_backend.schemas.documents import DocumentDeleteResponse


DOCUMENT_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture()
def service_mock(monkeypatch):
    service = MagicMock(spec=DocumentRegistryService)
    monkeypatch.setattr(documents_module, "DocumentRegistryService", lambda: service)
    return service


def test_delete_uploaded_document_returns_deleted_response(service_mock):
    service_mock.delete_uploaded_document.return_value = DocumentDeleteResponse(
        document_id=DOCUMENT_ID,
        filename="uploaded.pdf",
        deleted=True,
    )

    response = TestClient(create_app()).delete(f"/documents/{DOCUMENT_ID}")

    assert response.status_code == 200
    assert response.json() == {
        "document_id": DOCUMENT_ID,
        "filename": "uploaded.pdf",
        "deleted": True,
    }


def test_delete_unknown_document_returns_404(service_mock):
    service_mock.delete_uploaded_document.side_effect = DocumentRegistryNotFoundError(
        "Document not found."
    )

    response = TestClient(create_app()).delete(f"/documents/{DOCUMENT_ID}")

    assert response.status_code == 404


def test_delete_builtin_document_returns_403(service_mock):
    service_mock.delete_uploaded_document.side_effect = DocumentRegistryForbiddenError(
        "Only browser-uploaded documents can be removed."
    )

    response = TestClient(create_app()).delete(f"/documents/{DOCUMENT_ID}")

    assert response.status_code == 403
