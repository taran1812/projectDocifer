from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from docifer_backend.audit.models import ParseQualityAudit
from docifer_backend.documents.service import (
    DocumentRegistryForbiddenError,
    DocumentRegistryAmbiguousError,
    DocumentRegistryNotFoundError,
    DocumentRegistryService,
)
from docifer_backend.ingestion.models import Document
from docifer_backend.ingestion.models import DocumentIndexRun, IngestionJob
from docifer_backend.ingestion.status import IngestionStatus
from docifer_backend.retrieval.document_registry import doc_id_for_document
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.retrieval.tables.indexing import TABLE_INDEX_STATUS_NO_EVIDENCE
from docifer_backend.retrieval.tables.models import DocumentTableIndexRun, TableEvidenceRecord
from docifer_backend.retrieval.visuals.indexing import VISUAL_INDEX_STATUS_INDEXED, VISUAL_INDEX_STATUS_NO_EVIDENCE
from docifer_backend.retrieval.visuals.models import DocumentVisualIndexRun, VisualEvidenceRecord
from docifer_backend.schemas.documents import ModalityIndexStatus
from docifer_backend.storage.database import Base


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_doc_id_for_document_reuses_phase9_mapping():
    document = Document(
        id="document-5",
        filename="Worldbank2024.pdf",
        source_path="datasets/raw_pdfs/Worldbank2024.pdf",
        content_hash="a" * 64,
        file_size_bytes=10,
    )

    assert doc_id_for_document(document) == "DOC-005"


def test_modality_schema_accepts_explicit_unavailable_state():
    status = ModalityIndexStatus(
        status="not_available",
        count=0,
        latest_status="no_table_evidence",
    )

    assert status.status == "not_available"


def test_service_lists_documents_and_distinguishes_unavailable_modalities(tmp_path, session_factory):
    doc_ids = _seed_registry_documents(tmp_path, session_factory)

    response = DocumentRegistryService(session_factory=session_factory).list_documents(
        limit=50,
        offset=0,
    )

    by_doc_id = {document.doc_id: document for document in response.documents}
    assert response.total == 2
    assert by_doc_id["DOC-005"].modalities.text.status == "indexed"
    assert by_doc_id["DOC-005"].modalities.text.count == 1
    assert by_doc_id["DOC-006"].modalities.table.status == "not_available"
    assert by_doc_id["DOC-006"].modalities.table.latest_status == TABLE_INDEX_STATUS_NO_EVIDENCE
    assert by_doc_id["DOC-006"].modalities.visual.status == "not_available"
    assert by_doc_id["DOC-006"].modalities.visual.latest_status == VISUAL_INDEX_STATUS_NO_EVIDENCE
    assert set(doc_ids) == {"worldbank", "bosib"}


def test_service_resolves_public_identities_and_latest_audit(tmp_path, session_factory):
    doc_ids = _seed_registry_documents(tmp_path, session_factory)
    service = DocumentRegistryService(session_factory=session_factory)

    by_doc_id = service.get_by_doc_id("DOC-005")
    by_hash = service.get_by_content_hash("b" * 64)
    audit = service.get_audit(doc_ids["worldbank"])
    missing_audit = service.get_audit(doc_ids["bosib"])

    assert by_doc_id.document_id == doc_ids["worldbank"]
    assert by_hash.doc_id == "DOC-006"
    assert audit.latest_audit is not None
    assert audit.latest_audit.quality_status == "good"
    assert audit.latest_audit.summary is not None
    assert audit.latest_audit.summary.page_count == 4
    assert missing_audit.latest_audit is None
    assert missing_audit.warning is not None


def test_service_artifacts_include_existence_and_provenance(tmp_path, session_factory):
    doc_ids = _seed_registry_documents(tmp_path, session_factory)

    response = DocumentRegistryService(session_factory=session_factory).get_artifacts(
        doc_ids["worldbank"]
    )

    by_type = {artifact.artifact_type: artifact for artifact in response.artifacts}
    assert by_type["canonical_json"].exists is True
    assert by_type["canonical_json"].source == "latest_ingestion_job"
    assert by_type["parse_summary_json"].exists is False
    assert response.visual_artifacts[0].exists is True
    assert response.visual_artifacts[0].source == "visual_evidence_records"


def test_service_raises_not_found_for_unknown_document(session_factory):
    service = DocumentRegistryService(session_factory=session_factory)

    with pytest.raises(DocumentRegistryNotFoundError):
        service.get_document("unknown")


def test_service_flags_uploaded_documents(tmp_path, session_factory):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    uploaded_pdf = uploads_dir / "uploaded.pdf"
    uploaded_pdf.write_bytes(b"%PDF")
    _seed_uploaded_document(tmp_path, session_factory, uploaded_pdf)

    response = DocumentRegistryService(
        session_factory=session_factory,
        uploads_dir=uploads_dir,
    ).list_documents(limit=50, offset=0)

    by_id = {document.document_id: document for document in response.documents}
    assert by_id["uploaded"].is_uploaded is True


def test_service_deletes_uploaded_document_records_vectors_and_files(tmp_path, session_factory):
    uploads_dir = tmp_path / "uploads"
    processed_dir = tmp_path / "processed"
    uploads_dir.mkdir()
    processed_dir.mkdir()
    uploaded_pdf = uploads_dir / "uploaded.pdf"
    uploaded_pdf.write_bytes(b"%PDF")
    canonical_path = _seed_uploaded_document(tmp_path, session_factory, uploaded_pdf)
    qdrant_client = FakeDeleteQdrantClient(existing_collections={
        "docifer_text_chunks",
        "docifer_table_evidence",
        "docifer_visual_evidence",
    })

    response = DocumentRegistryService(
        session_factory=session_factory,
        qdrant_client=qdrant_client,
        uploads_dir=uploads_dir,
        processed_dir=processed_dir,
    ).delete_uploaded_document("uploaded")

    assert response.deleted is True
    assert response.document_id == "uploaded"
    assert not uploaded_pdf.exists()
    assert not canonical_path.parent.exists()
    assert qdrant_client.deleted_collections == [
        "docifer_text_chunks",
        "docifer_table_evidence",
        "docifer_visual_evidence",
    ]
    with session_factory() as session:
        assert session.scalar(select(Document).where(Document.id == "uploaded")) is None
        assert session.query(TextChunkRecord).count() == 0
        assert session.query(TableEvidenceRecord).count() == 0
        assert session.query(VisualEvidenceRecord).count() == 0
        assert session.query(IngestionJob).count() == 0
        assert session.query(ParseQualityAudit).count() == 0


def test_service_allows_delete_for_builtin_document(tmp_path, session_factory):
    doc_ids = _seed_registry_documents(tmp_path, session_factory)
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()

    result = DocumentRegistryService(
        session_factory=session_factory,
        uploads_dir=uploads_dir,
    ).delete_uploaded_document(doc_ids["worldbank"])
    assert result.deleted is True


def test_service_rejects_ambiguous_public_doc_id(tmp_path, session_factory):
    _seed_registry_documents(tmp_path, session_factory)
    with session_factory() as session:
        session.add(
            Document(
                id="second-worldbank",
                filename="worldbank2024.pdf",
                source_path="alternate/worldbank2024.pdf",
                content_hash="c" * 64,
                file_size_bytes=100,
            )
        )
        session.commit()

    with pytest.raises(DocumentRegistryAmbiguousError):
        DocumentRegistryService(session_factory=session_factory).get_by_doc_id("DOC-005")


def test_service_initializes_schema_when_using_default_database(monkeypatch):
    import docifer_backend.documents.service as service_module

    initialized: list[bool] = []
    service_module._ensure_database_schema.cache_clear()
    monkeypatch.setattr(service_module, "create_database_schema", lambda: initialized.append(True))
    monkeypatch.setattr(service_module, "get_session_factory", lambda: "default-session-factory")

    service = service_module.DocumentRegistryService(identity_resolver=object())
    service_module.DocumentRegistryService(identity_resolver=object())

    assert service.session_factory == "default-session-factory"
    assert initialized == [True]
    service_module._ensure_database_schema.cache_clear()


class FakeDeleteQdrantClient:
    def __init__(self, *, existing_collections: set[str]):
        self.existing_collections = existing_collections
        self.deleted_collections: list[str] = []

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.existing_collections

    def delete(self, *, collection_name: str, points_selector, wait: bool) -> None:
        self.deleted_collections.append(collection_name)


def _seed_uploaded_document(tmp_path: Path, session_factory, uploaded_pdf: Path) -> Path:
    artifact_dir = tmp_path / "processed" / "uploaded-run"
    artifact_dir.mkdir(parents=True)
    canonical_path = artifact_dir / "canonical.json"
    canonical_path.write_text("{}", encoding="utf-8")
    visual_path = artifact_dir / "visuals" / "pages" / "page_0001.jpg"
    visual_path.parent.mkdir(parents=True)
    visual_path.write_bytes(b"jpg")

    with session_factory() as session:
        document = Document(
            id="uploaded",
            filename="uploaded.pdf",
            source_path=str(uploaded_pdf),
            content_hash="u" * 64,
            file_size_bytes=uploaded_pdf.stat().st_size,
            latest_job_id="job-uploaded",
        )
        session.add(document)
        session.add(
            IngestionJob(
                id="job-uploaded",
                document_id=document.id,
                source_path=document.source_path,
                content_hash=document.content_hash,
                status=IngestionStatus.PARSED.value,
                parser_name="docling",
                artifact_path=str(canonical_path),
            )
        )
        session.add(
            DocumentIndexRun(
                document_id=document.id,
                content_hash=document.content_hash,
                index_name="docifer_text_chunks",
                index_version="v1",
                status=IngestionStatus.INDEXED.value,
            )
        )
        session.add(
            TextChunkRecord(
                id="text-uploaded",
                document_id=document.id,
                content_hash=document.content_hash,
                chunk_id="uploaded:text:0000",
                chunk_index=0,
                text="Uploaded text evidence.",
                page_start=1,
                page_end=1,
                source_path=document.source_path,
                source_artifact_path=str(canonical_path),
                qdrant_point_id="point-uploaded",
            )
        )
        session.add(
            TableEvidenceRecord(
                id="table-record",
                document_id=document.id,
                content_hash=document.content_hash,
                canonical_path=str(canonical_path),
                filename=document.filename,
                source_path=document.source_path,
                source_artifact_path=str(canonical_path),
                table_id="uploaded:table:0000",
                table_index=0,
                table_type="table_like_text",
                source_kind="text_pattern",
                raw_text="table evidence",
                has_header=False,
                table_readiness="weak",
                extraction_method="text_pattern",
                risk_flags_json=[],
            )
        )
        session.add(
            VisualEvidenceRecord(
                id="visual-uploaded",
                document_id=document.id,
                content_hash=document.content_hash,
                canonical_path=str(canonical_path),
                filename=document.filename,
                source_path=document.source_path,
                source_artifact_path=str(canonical_path),
                visual_id="uploaded:page:0001",
                visual_index=0,
                visual_type="page_render",
                source_kind="rendered_page",
                page_start=1,
                page_end=1,
                artifact_path=str(visual_path),
                visual_readiness="good",
                extraction_method="rendered_page",
            )
        )
        session.add(
            DocumentTableIndexRun(
                document_id=document.id,
                content_hash=document.content_hash,
                canonical_path=str(canonical_path),
                status=IngestionStatus.INDEXED.value,
                table_evidence_count=1,
                collection_name="docifer_table_evidence",
            )
        )
        session.add(
            DocumentVisualIndexRun(
                document_id=document.id,
                content_hash=document.content_hash,
                canonical_path=str(canonical_path),
                status=VISUAL_INDEX_STATUS_INDEXED,
                visual_record_count=1,
                collection_name="docifer_visual_evidence",
            )
        )
        session.add(
            ParseQualityAudit(
                id="audit-uploaded",
                document_id=document.id,
                content_hash=document.content_hash,
                canonical_path=str(canonical_path),
                parser_name="docling",
                audit_version="v1",
                audit_run_id="audit-uploaded-run",
                audit_status="completed",
                is_latest=True,
                quality_status="good",
                text_readiness="good",
                table_readiness="good",
                visual_readiness="good",
                risk_flags_json=[],
                summary_json={"page_count": 1},
            )
        )
        session.commit()

    return canonical_path


def _seed_registry_documents(tmp_path: Path, session_factory) -> dict[str, str]:
    artifact_dir = tmp_path / "processed" / "worldbank"
    artifact_dir.mkdir(parents=True)
    canonical_path = artifact_dir / "canonical.json"
    canonical_path.write_text("{}", encoding="utf-8")
    visual_path = artifact_dir / "visuals" / "pages" / "page_0001.jpg"
    visual_path.parent.mkdir(parents=True)
    visual_path.write_bytes(b"jpg")

    with session_factory() as session:
        worldbank = Document(
            id="worldbank",
            filename="Worldbank2024.pdf",
            source_path="datasets/raw_pdfs/Worldbank2024.pdf",
            content_hash="a" * 64,
            file_size_bytes=100,
            latest_job_id="job-worldbank",
        )
        bosib = Document(
            id="bosib",
            filename="BOSIB13bdde89d07f1b3711dd8e86adb477.pdf",
            source_path="datasets/raw_pdfs/BOSIB13bdde89d07f1b3711dd8e86adb477.pdf",
            content_hash="b" * 64,
            file_size_bytes=200,
            latest_job_id="job-bosib",
        )
        session.add_all([worldbank, bosib])
        session.add_all(
            [
                IngestionJob(
                    id="job-worldbank",
                    document_id=worldbank.id,
                    source_path=worldbank.source_path,
                    content_hash=worldbank.content_hash,
                    status=IngestionStatus.PARSED.value,
                    parser_name="docling",
                    artifact_path=str(canonical_path),
                ),
                IngestionJob(
                    id="job-bosib",
                    document_id=bosib.id,
                    source_path=bosib.source_path,
                    content_hash=bosib.content_hash,
                    status=IngestionStatus.PARSED.value,
                    parser_name="docling",
                ),
            ]
        )
        session.add_all(
            [
                DocumentIndexRun(
                    document_id=worldbank.id,
                    content_hash=worldbank.content_hash,
                    index_name="docifer_text_chunks",
                    index_version="v1",
                    status=IngestionStatus.INDEXED.value,
                ),
                DocumentIndexRun(
                    document_id=bosib.id,
                    content_hash=bosib.content_hash,
                    index_name="docifer_text_chunks",
                    index_version="v1",
                    status=IngestionStatus.INDEXED.value,
                ),
                TextChunkRecord(
                    id="text-worldbank",
                    document_id=worldbank.id,
                    content_hash=worldbank.content_hash,
                    chunk_id="worldbank:text:0000",
                    chunk_index=0,
                    text="Text evidence.",
                    page_start=1,
                    page_end=1,
                    source_path=worldbank.source_path,
                    source_artifact_path=str(canonical_path),
                    qdrant_point_id="point-worldbank",
                ),
                TextChunkRecord(
                    id="text-bosib",
                    document_id=bosib.id,
                    content_hash=bosib.content_hash,
                    chunk_id="bosib:text:0000",
                    chunk_index=0,
                    text="Text evidence.",
                    page_start=1,
                    page_end=1,
                    source_path=bosib.source_path,
                    source_artifact_path="datasets/processed/bosib/canonical.json",
                    qdrant_point_id="point-bosib",
                ),
                DocumentTableIndexRun(
                    document_id=bosib.id,
                    content_hash=bosib.content_hash,
                    canonical_path="datasets/processed/bosib/canonical.json",
                    status=TABLE_INDEX_STATUS_NO_EVIDENCE,
                    collection_name="docifer_table_evidence",
                ),
                DocumentVisualIndexRun(
                    document_id=bosib.id,
                    content_hash=bosib.content_hash,
                    canonical_path="datasets/processed/bosib/canonical.json",
                    status=VISUAL_INDEX_STATUS_NO_EVIDENCE,
                    collection_name="docifer_visual_evidence",
                ),
                DocumentVisualIndexRun(
                    document_id=worldbank.id,
                    content_hash=worldbank.content_hash,
                    canonical_path=str(canonical_path),
                    status=VISUAL_INDEX_STATUS_INDEXED,
                    visual_record_count=1,
                    collection_name="docifer_visual_evidence",
                ),
                VisualEvidenceRecord(
                    id="visual-record",
                    document_id=worldbank.id,
                    content_hash=worldbank.content_hash,
                    canonical_path=str(canonical_path),
                    filename=worldbank.filename,
                    source_path=worldbank.source_path,
                    source_artifact_path=str(canonical_path),
                    visual_id="worldbank:page:0001",
                    visual_index=0,
                    visual_type="page_render",
                    source_kind="rendered_page",
                    page_start=1,
                    page_end=1,
                    artifact_path=str(visual_path),
                    visual_readiness="good",
                    extraction_method="rendered_page",
                ),
                ParseQualityAudit(
                    id="audit-worldbank",
                    document_id=worldbank.id,
                    content_hash=worldbank.content_hash,
                    canonical_path=str(canonical_path),
                    parser_name="docling",
                    audit_version="v1",
                    audit_run_id="audit-run",
                    audit_status="completed",
                    is_latest=True,
                    quality_status="good",
                    text_readiness="good",
                    table_readiness="good",
                    visual_readiness="good",
                    risk_flags_json=[],
                    summary_json={"page_count": 4, "table_count": 1, "figure_count": 2},
                ),
            ]
        )
        session.commit()

    return {"worldbank": worldbank.id, "bosib": bosib.id}
