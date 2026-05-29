import io
from types import SimpleNamespace
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
    with patch("docifer_backend.api.ingestion._ingest_pdf", return_value=_fake_outcome()), \
         patch("docifer_backend.api.ingestion._index_all"):
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
    assert body["status"] == "indexed"
    assert body["reused_existing"] is False
    assert body["error_message"] is None
    saved = list(tmp_path.glob("*.pdf"))
    assert len(saved) == 1
    assert saved[0].name.endswith("_annual_report.pdf")
    assert not saved[0].name.endswith(".pdf.pdf")
    assert saved[0].read_bytes() == b"%PDF-1.4"


def test_upload_rejects_file_above_upload_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "docifer_backend.api.ingestion._get_uploads_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "docifer_backend.api.ingestion.get_settings",
        lambda: SimpleNamespace(
            docling_max_file_size_bytes=1,
            upload_max_file_size_bytes=16,
        ),
    )
    with patch(
        "docifer_backend.api.ingestion._ingest_pdf",
        return_value=_fake_outcome(),
    ) as ingest_pdf:
        client = _make_client()
        response = client.post(
            "/ingestion/upload",
            files={
                "file": (
                    "large.pdf",
                    io.BytesIO(b"%PDF-1.4" + b"0" * 32),
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 413
    assert "exceeds" in response.json()["detail"].lower()
    ingest_pdf.assert_not_called()
    assert list(tmp_path.glob("*.pdf")) == []


def test_upload_allows_file_above_docling_threshold_when_under_upload_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "docifer_backend.api.ingestion._get_uploads_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "docifer_backend.api.ingestion.get_settings",
        lambda: SimpleNamespace(
            docling_max_file_size_bytes=1,
            upload_max_file_size_bytes=1024,
        ),
    )
    with patch("docifer_backend.api.ingestion._ingest_pdf", return_value=_fake_outcome()) as ingest_pdf, \
         patch("docifer_backend.api.ingestion._index_all"):
        client = _make_client()
        response = client.post(
            "/ingestion/upload",
            files={
                "file": (
                    "large.pdf",
                    io.BytesIO(b"%PDF-1.4" + b"0" * 32),
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 202
    ingest_pdf.assert_called_once()


def test_upload_returns_400_when_ingestion_raises_value_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "docifer_backend.api.ingestion._get_uploads_dir",
        lambda: tmp_path,
    )
    with patch(
        "docifer_backend.api.ingestion._ingest_pdf",
        side_effect=ValueError("invalid pdf structure"),
    ):
        client = _make_client()
        response = client.post(
            "/ingestion/upload",
            files={"file": ("bad.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
    assert response.status_code == 400
    assert list(tmp_path.glob("*.pdf")) == []
