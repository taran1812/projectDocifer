import pytest
from sqlalchemy import inspect


pytestmark = pytest.mark.integration


def test_documents_table_exists(pg_engine):
    assert "documents" in inspect(pg_engine).get_table_names()


def test_ingestion_jobs_table_exists(pg_engine):
    assert "ingestion_jobs" in inspect(pg_engine).get_table_names()


def test_text_chunks_table_exists(pg_engine):
    assert "text_chunks" in inspect(pg_engine).get_table_names()


def test_table_evidence_records_table_exists(pg_engine):
    assert "table_evidence_records" in inspect(pg_engine).get_table_names()


def test_visual_evidence_records_table_exists(pg_engine):
    assert "visual_evidence_records" in inspect(pg_engine).get_table_names()


def test_parse_quality_audits_table_exists(pg_engine):
    assert "parse_quality_audits" in inspect(pg_engine).get_table_names()


def test_document_insert_select_roundtrip(pg_engine, pg_session_factory):
    from docifer_backend.ingestion.models import Document

    with pg_session_factory() as session:
        doc = Document(
            filename="schema_test.pdf",
            source_path="/tmp/schema_test.pdf",
            content_hash="schema" + "0" * 58,
            file_size_bytes=42,
        )
        session.add(doc)
        session.commit()
        fetched = session.get(Document, doc.id)
        assert fetched is not None
        assert fetched.filename == "schema_test.pdf"
        session.delete(fetched)
        session.commit()
