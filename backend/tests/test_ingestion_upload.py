import io
from unittest.mock import patch

from fastapi.testclient import TestClient

from docifer_backend.ingestion.service import IngestionOutcome
from docifer_backend.main import create_app


def _make_client() -> TestClient:
    return TestClient(create_app())


def _fake_outcome() -> IngestionOutcome:
    return IngestionOutcome(
        job_id="test-job-123",
        document_id="doc-456",
        status="completed",
        artifact_path="datasets/processed/abc/def",
        reused_existing=False,
        error_message=None,
    )


def test_upload_rejects_non_pdf_extension():
    client = _make_client()
    response = client.post(
        "/ingestion/upload",
        files={"file": ("report.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 400
    assert "pdf" in response.json()["detail"].lower()


def test_upload_rejects_non_pdf_content_type():
    client = _make_client()
    response = client.post(
        "/ingestion/upload",
        files={"file": ("report.pdf", io.BytesIO(b"%PDF fake"), "text/plain")},
    )
    assert response.status_code == 400


def test_upload_saves_file_and_returns_job_response(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "docifer_backend.api.ingestion._get_uploads_dir",
        lambda: tmp_path,
    )
    with patch(
        "docifer_backend.api.ingestion._ingest_pdf",
        return_value=_fake_outcome(),
    ):
        client = _make_client()
        response = client.post(
            "/ingestion/upload",
            files={
                "file": (
                    "annual_report.pdf",
                    io.BytesIO(b"%PDF-1.4"),
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] == "test-job-123"
    assert body["document_id"] == "doc-456"
    assert body["status"] == "completed"
    assert body["reused_existing"] is False
    assert body["error_message"] is None
    saved = list(tmp_path.glob("*.pdf"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"%PDF-1.4"
