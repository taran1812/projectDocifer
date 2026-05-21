from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from docifer_backend.audit.models import ParseQualityAudit
from docifer_backend.ingestion.models import Document
from docifer_backend.storage.database import Base


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def document(session_factory):
    with session_factory() as session:
        doc = Document(
            filename="test.pdf",
            source_path="/tmp/test.pdf",
            content_hash="a" * 64,
            file_size_bytes=1000,
        )
        session.add(doc)
        session.commit()
        return doc.id, doc.content_hash


def test_is_latest_flips_on_second_audit(session_factory, document):
    doc_id, content_hash = document
    with session_factory() as session:
        first = ParseQualityAudit(
            document_id=doc_id,
            content_hash=content_hash,
            canonical_path="datasets/processed/abc/job1/canonical.json",
            parser_name="docling",
            fallback_used=False,
            audit_version="0.1.0",
            audit_run_id="run-1",
            audit_status="completed",
            is_latest=True,
            quality_status="good",
            text_readiness="good",
            table_readiness="good",
            visual_readiness="good",
            risk_flags_json=[],
            summary_json={"page_count": 10},
        )
        session.add(first)
        session.commit()
        first_id = first.id

    with session_factory() as session:
        second = ParseQualityAudit(
            document_id=doc_id,
            content_hash=content_hash,
            canonical_path="datasets/processed/abc/job1/canonical.json",
            parser_name="docling",
            fallback_used=False,
            audit_version="0.1.0",
            audit_run_id="run-2",
            audit_status="completed",
            is_latest=True,
            quality_status="weak",
            text_readiness="good",
            table_readiness="weak",
            visual_readiness="weak",
            risk_flags_json=[],
            summary_json={"page_count": 10},
        )
        session.add(second)
        session.flush()
        session.execute(
            ParseQualityAudit.__table__.update()
            .where(ParseQualityAudit.content_hash == content_hash)
            .where(ParseQualityAudit.id != second.id)
            .values(is_latest=False)
        )
        session.commit()

    with session_factory() as session:
        rows = session.scalars(
            select(ParseQualityAudit)
            .where(ParseQualityAudit.content_hash == content_hash)
            .order_by(ParseQualityAudit.audit_run_id)
        ).all()

    assert len(rows) == 2, "Both audit rows must be preserved (history not deleted)"
    assert rows[0].id == first_id
    assert rows[0].is_latest is False
    assert rows[1].is_latest is True
