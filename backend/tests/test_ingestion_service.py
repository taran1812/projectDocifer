import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from docifer_backend.ingestion.models import Document, DocumentIndexRun, IngestionJob
from docifer_backend.ingestion.parser import ParsedDocument
from docifer_backend.ingestion.service import IngestionService
from docifer_backend.ingestion.status import IngestionStatus
from docifer_backend.storage.database import Base


class FakeParser:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, source_path: Path) -> ParsedDocument:
        self.calls += 1
        return ParsedDocument(
            parser_name="fake-docling",
            parser_version="0.0-test",
            docling_status="success",
            raw_document={"pages": {"1": {"size": [612, 792]}}, "texts": []},
            markdown="# Parsed\n\nHello from Docifer.",
            page_count=1,
            table_count=0,
            figure_count=0,
            errors=[],
        )


class FailingParser:
    def parse(self, source_path: Path) -> ParsedDocument:
        raise RuntimeError("parse exploded")


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def write_pdf(path: Path) -> None:
    path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")


def test_ingest_pdf_creates_job_and_canonical_artifact(tmp_path, session_factory):
    pdf_path = tmp_path / "sample.pdf"
    write_pdf(pdf_path)
    parser = FakeParser()
    service = IngestionService(
        session_factory=session_factory,
        parser=parser,
        processed_data_dir=tmp_path / "processed",
        initialize_schema=False,
    )

    outcome = service.ingest_pdf(pdf_path)

    assert outcome.status == IngestionStatus.PARSED.value
    assert outcome.reused_existing is False
    assert parser.calls == 1
    canonical_path = Path(outcome.artifact_path)
    assert canonical_path.exists()

    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert canonical["schema_version"] == "docifer.canonical_document.v1"
    assert canonical["parse"]["page_count"] == 1
    assert canonical["content"]["markdown_char_count"] > 0


def test_ingest_pdf_reuses_existing_successful_job(tmp_path, session_factory):
    pdf_path = tmp_path / "sample.pdf"
    write_pdf(pdf_path)
    parser = FakeParser()
    service = IngestionService(
        session_factory=session_factory,
        parser=parser,
        processed_data_dir=tmp_path / "processed",
        initialize_schema=False,
    )

    first = service.ingest_pdf(pdf_path)
    second = service.ingest_pdf(pdf_path)

    assert second.reused_existing is True
    assert second.job_id == first.job_id
    assert parser.calls == 1


def test_ingest_pdf_records_failure_after_bounded_retries(tmp_path, session_factory):
    pdf_path = tmp_path / "sample.pdf"
    write_pdf(pdf_path)
    service = IngestionService(
        session_factory=session_factory,
        parser=FailingParser(),
        processed_data_dir=tmp_path / "processed",
        max_attempts=2,
        initialize_schema=False,
    )

    outcome = service.ingest_pdf(pdf_path)

    assert outcome.status == IngestionStatus.FAILED.value
    assert outcome.error_message == "parse exploded"
    with session_factory() as session:
        job = session.get(IngestionJob, outcome.job_id)
        assert job is not None
        assert job.attempt_count == 2
        assert job.error_type == "RuntimeError"


def test_document_index_runs_prevent_duplicate_indexing(session_factory):
    with session_factory() as session:
        document = Document(
            filename="sample.pdf",
            source_path="sample.pdf",
            content_hash="a" * 64,
            file_size_bytes=123,
        )
        session.add(document)
        session.commit()

        first_run = DocumentIndexRun(
            document_id=document.id,
            content_hash=document.content_hash,
            index_name="text_chunks",
            index_version="v1",
            status=IngestionStatus.INDEXING.value,
        )
        duplicate_run = DocumentIndexRun(
            document_id=document.id,
            content_hash=document.content_hash,
            index_name="text_chunks",
            index_version="v1",
            status=IngestionStatus.INDEXING.value,
        )
        session.add(first_run)
        session.commit()
        session.add(duplicate_run)

        with pytest.raises(IntegrityError):
            session.commit()
