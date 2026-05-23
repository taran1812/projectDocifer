from datetime import datetime, timezone

from fastapi.testclient import TestClient

import docifer_backend.api.documents as documents_api
from docifer_backend.documents.service import (
    DocumentRegistryAmbiguousError,
    DocumentRegistryNotFoundError,
)
from docifer_backend.main import create_app
from docifer_backend.schemas.documents import (
    ArtifactReference,
    DocumentArtifactsResponse,
    DocumentAuditResponse,
    DocumentDetailResponse,
    DocumentIndexStatusResponse,
    DocumentListResponse,
    DocumentModalitiesResponse,
    DocumentSummaryResponse,
    ModalityIndexStatus,
)


def test_document_endpoints_expose_typed_registry_and_lookup_routes(monkeypatch):
    service = FakeDocumentRegistryService()
    monkeypatch.setattr(documents_api, "DocumentRegistryService", lambda: service)
    client = TestClient(create_app())

    listing = client.get("/documents?table_status=not_available&limit=10")
    by_doc_id = client.get("/documents/by-doc-id/DOC-005")
    by_hash = client.get(f"/documents/by-content-hash/{'a' * 64}")
    detail = client.get("/documents/worldbank")
    indexes = client.get("/documents/worldbank/indexes")
    audit = client.get("/documents/worldbank/audit")
    artifacts = client.get("/documents/worldbank/artifacts")

    assert listing.status_code == 200
    assert listing.json()["documents"][0]["modalities"]["table"]["status"] == "not_available"
    assert service.list_kwargs["table_status"] == "not_available"
    assert service.list_kwargs["limit"] == 10
    assert by_doc_id.status_code == 200
    assert by_doc_id.json()["doc_id"] == "DOC-005"
    assert by_hash.status_code == 200
    assert detail.status_code == 200
    assert indexes.json()["modalities"]["text"]["status"] == "indexed"
    assert audit.json()["latest_audit"] is None
    assert artifacts.json()["artifacts"][0]["source"] == "latest_ingestion_job"
    assert service.calls[:2] == ["list", "by-doc-id:DOC-005"]


def test_document_endpoint_converts_missing_document_to_404(monkeypatch):
    monkeypatch.setattr(
        documents_api,
        "DocumentRegistryService",
        lambda: MissingDocumentRegistryService(),
    )

    response = TestClient(create_app()).get("/documents/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found."


def test_document_endpoint_converts_ambiguous_lookup_to_409(monkeypatch):
    monkeypatch.setattr(
        documents_api,
        "DocumentRegistryService",
        lambda: AmbiguousDocumentRegistryService(),
    )

    response = TestClient(create_app()).get("/documents/by-doc-id/DOC-005")

    assert response.status_code == 409
    assert response.json()["detail"] == "Document lookup is ambiguous."


def test_document_endpoint_returns_stable_500_for_registry_failure(monkeypatch):
    monkeypatch.setattr(
        documents_api,
        "DocumentRegistryService",
        lambda: BrokenDocumentRegistryService(),
    )

    response = TestClient(create_app(), raise_server_exceptions=False).get("/documents")

    assert response.status_code == 500
    assert response.json()["detail"] == "Unable to load document registry state."


class FakeDocumentRegistryService:
    def __init__(self):
        self.calls: list[str] = []
        self.list_kwargs: dict = {}

    def list_documents(self, **kwargs) -> DocumentListResponse:
        self.calls.append("list")
        self.list_kwargs = kwargs
        return DocumentListResponse(documents=[_summary()], total=1, limit=kwargs["limit"], offset=0)

    def get_by_doc_id(self, doc_id: str) -> DocumentDetailResponse:
        self.calls.append(f"by-doc-id:{doc_id}")
        return _detail()

    def get_by_content_hash(self, content_hash: str) -> DocumentDetailResponse:
        self.calls.append(f"by-content-hash:{content_hash}")
        return _detail()

    def get_document(self, document_id: str) -> DocumentDetailResponse:
        self.calls.append(f"document:{document_id}")
        return _detail()

    def get_indexes(self, document_id: str) -> DocumentIndexStatusResponse:
        self.calls.append(f"indexes:{document_id}")
        return DocumentIndexStatusResponse(
            document_id="worldbank",
            doc_id="DOC-005",
            content_hash="a" * 64,
            modalities=_modalities(),
        )

    def get_audit(self, document_id: str) -> DocumentAuditResponse:
        self.calls.append(f"audit:{document_id}")
        return DocumentAuditResponse(
            document_id="worldbank",
            doc_id="DOC-005",
            content_hash="a" * 64,
            latest_audit=None,
            warning="No parse quality audit found for this document.",
        )

    def get_artifacts(self, document_id: str) -> DocumentArtifactsResponse:
        self.calls.append(f"artifacts:{document_id}")
        return DocumentArtifactsResponse(
            document_id="worldbank",
            doc_id="DOC-005",
            content_hash="a" * 64,
            artifacts=[
                ArtifactReference(
                    path="datasets/processed/worldbank/canonical.json",
                    exists=True,
                    source="latest_ingestion_job",
                    generated_by="ingestion",
                    artifact_type="canonical_json",
                )
            ],
            visual_artifacts=[],
        )


class MissingDocumentRegistryService(FakeDocumentRegistryService):
    def get_document(self, document_id: str) -> DocumentDetailResponse:
        raise DocumentRegistryNotFoundError("Document not found.")


class AmbiguousDocumentRegistryService(FakeDocumentRegistryService):
    def get_by_doc_id(self, doc_id: str) -> DocumentDetailResponse:
        raise DocumentRegistryAmbiguousError("Document lookup is ambiguous.")


class BrokenDocumentRegistryService(FakeDocumentRegistryService):
    def list_documents(self, **kwargs) -> DocumentListResponse:
        raise RuntimeError("database unavailable")


def _status(status: str, count: int) -> ModalityIndexStatus:
    return ModalityIndexStatus(status=status, count=count)


def _modalities() -> DocumentModalitiesResponse:
    return DocumentModalitiesResponse(
        text=_status("indexed", 2),
        table=_status("not_available", 0),
        visual=_status("not_indexed", 0),
    )


def _summary() -> DocumentSummaryResponse:
    return DocumentSummaryResponse(
        document_id="worldbank",
        doc_id="DOC-005",
        content_hash="a" * 64,
        filename="Worldbank2024.pdf",
        source_path="datasets/raw_pdfs/Worldbank2024.pdf",
        parser_name="docling",
        latest_ingestion_status="parsed",
        quality_status="good",
        modalities=_modalities(),
    )


def _detail() -> DocumentDetailResponse:
    return DocumentDetailResponse(
        document_id="worldbank",
        doc_id="DOC-005",
        content_hash="a" * 64,
        filename="Worldbank2024.pdf",
        source_path="datasets/raw_pdfs/Worldbank2024.pdf",
        file_size_bytes=100,
        latest_ingestion=None,
        modalities=_modalities(),
        latest_audit=None,
        artifacts=[],
    )
