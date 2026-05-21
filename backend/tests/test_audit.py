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


# ── metrics tests ──────────────────────────────────────────────────────────────

from docifer_backend.audit.metrics import (
    AUDIT_VERSION,
    AuditSummary,
    AuditVerdicts,
    compute_summary,
    compute_verdicts,
    detect_fallback,
)


def _make_canonical(
    *,
    parser_name: str = "docling",
    parser_version: str = "2.94.0",
    page_count: int = 10,
    table_count: int = 2,
    figure_count: int = 1,
    errors: list | None = None,
    schema_version: str = "docifer.canonical_document.v1",
    docling_json_path: str | None = "datasets/processed/abc/job1/docling.json",
) -> dict:
    return {
        "schema_version": schema_version,
        "document": {"content_hash": "a" * 64, "filename": "test.pdf"},
        "parser": {"name": parser_name, "version": parser_version},
        "artifacts": {"docling_json": docling_json_path, "markdown": "datasets/processed/abc/job1/document.md"},
        "parse": {
            "page_count": page_count,
            "table_count": table_count,
            "figure_count": figure_count,
            "errors": errors or [],
        },
        "structures": {"tables": {"count": table_count}, "figures": {"count": figure_count}},
    }


def _make_docling(*, tables: list | None = None, pictures: list | None = None) -> dict:
    return {
        "schema_name": "DoclingDocument",
        "tables": tables or [],
        "pictures": pictures or [],
        "texts": [],
    }


def _make_good_table(num_rows: int = 5, num_cols: int = 3, page_no: int = 2) -> dict:
    cells = [
        {"text": f"H{c}", "column_header": True, "row_header": False,
         "start_row_offset_idx": 0, "start_col_offset_idx": c}
        for c in range(num_cols)
    ]
    return {
        "label": "table",
        "prov": [{"page_no": page_no}],
        "data": {"num_rows": num_rows, "num_cols": num_cols, "table_cells": cells},
    }


def _make_picture(caption: str | None = None, page_no: int = 3) -> dict:
    captions = [{"text": caption}] if caption else []
    return {"label": "picture", "prov": [{"page_no": page_no}], "captions": captions}


# ── fallback detection ──────────────────────────────────────────────────────────


def test_detect_fallback_docling_is_false():
    canonical = _make_canonical(parser_name="docling")
    fallback_used, reason = detect_fallback(canonical)
    assert fallback_used is False
    assert reason is None


def test_detect_fallback_size_threshold():
    canonical = _make_canonical(
        parser_name="pypdfium2-text",
        errors=[{"type": "parser_selection", "message": "file too large"}],
    )
    fallback_used, reason = detect_fallback(canonical)
    assert fallback_used is True
    assert reason == "size_threshold"


def test_detect_fallback_docling_failed():
    canonical = _make_canonical(
        parser_name="pypdfium2-text",
        errors=[{"type": "RuntimeError", "message": "crash", "stage": "docling_primary_parser"}],
    )
    fallback_used, reason = detect_fallback(canonical)
    assert fallback_used is True
    assert reason == "docling_failed"


def test_detect_fallback_manual_backend():
    canonical = _make_canonical(parser_name="pypdfium2-text", errors=[])
    fallback_used, reason = detect_fallback(canonical)
    assert fallback_used is True
    assert reason == "manual_backend"


# ── compute_summary ─────────────────────────────────────────────────────────────


def test_compute_summary_docling_canonical():
    canonical = _make_canonical(page_count=10, table_count=2, figure_count=1)
    markdown = "\n\n".join(
        f"<!-- page {i} -->\n\n{'Some text on this page. ' * 20}" for i in range(1, 11)
    )
    docling = _make_docling(
        tables=[_make_good_table()],
        pictures=[_make_picture(caption="Figure 1. Revenue chart")],
    )
    summary = compute_summary(canonical, markdown, docling)

    assert summary.page_count == 10
    assert summary.table_count == 2
    assert summary.figure_count == 1
    assert summary.table_candidate_count >= 1
    assert summary.figure_candidate_count >= 1
    assert summary.text_chars_total > 0
    assert summary.avg_chars_per_page > 0
    assert summary.empty_page_count == 0
    assert summary.parse_error_count == 0


def test_compute_summary_fallback_canonical_empty_pages():
    canonical = _make_canonical(parser_name="pypdfium2-text", page_count=4, table_count=0, figure_count=0)
    markdown = "<!-- page 1 -->\n\nSome text.\n\n<!-- page 2 -->\n\n\n\n<!-- page 3 -->\n\nMore text.\n\n<!-- page 4 -->\n\n"
    summary = compute_summary(canonical, markdown, None)

    assert summary.page_count == 4
    assert summary.table_count == 0
    assert summary.figure_count == 0
    assert summary.empty_page_count >= 1


# ── compute_verdicts ────────────────────────────────────────────────────────────


def test_text_readiness_good():
    summary = AuditSummary(
        page_count=10, table_count=2, table_candidate_count=2, table_like_page_count=2,
        figure_count=1, figure_candidate_count=1, caption_candidate_count=1,
        empty_page_count=0, text_chars_total=30000, avg_chars_per_page=3000,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=False)
    assert verdicts.text_readiness == "good"


def test_text_readiness_poor_high_empty_ratio():
    summary = AuditSummary(
        page_count=10, table_count=0, table_candidate_count=0, table_like_page_count=0,
        figure_count=0, figure_candidate_count=0, caption_candidate_count=0,
        empty_page_count=4, text_chars_total=100, avg_chars_per_page=10,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=False)
    assert verdicts.text_readiness == "poor"


def test_table_readiness_good_requires_docling_with_real_tables():
    summary = AuditSummary(
        page_count=10, table_count=3, table_candidate_count=3, table_like_page_count=2,
        figure_count=0, figure_candidate_count=0, caption_candidate_count=0,
        empty_page_count=0, text_chars_total=20000, avg_chars_per_page=2000,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=False)
    assert verdicts.table_readiness == "good"


def test_table_readiness_poor_fallback_no_candidates():
    summary = AuditSummary(
        page_count=10, table_count=0, table_candidate_count=0, table_like_page_count=0,
        figure_count=0, figure_candidate_count=0, caption_candidate_count=0,
        empty_page_count=0, text_chars_total=20000, avg_chars_per_page=2000,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=True)
    assert verdicts.table_readiness == "poor"


def test_table_readiness_weak_fallback_with_table_like_text():
    summary = AuditSummary(
        page_count=10, table_count=0, table_candidate_count=3, table_like_page_count=3,
        figure_count=0, figure_candidate_count=0, caption_candidate_count=0,
        empty_page_count=0, text_chars_total=20000, avg_chars_per_page=2000,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=True)
    assert verdicts.table_readiness == "weak"


def test_quality_status_all_good():
    summary = AuditSummary(
        page_count=10, table_count=2, table_candidate_count=2, table_like_page_count=2,
        figure_count=1, figure_candidate_count=1, caption_candidate_count=1,
        empty_page_count=0, text_chars_total=30000, avg_chars_per_page=3000,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=False)
    assert verdicts.quality_status == "good"


def test_quality_status_weak_when_any_weak():
    # [good text, weak table (no tables), weak visual (no figures, no fallback)] → weak
    summary = AuditSummary(
        page_count=10, table_count=0, table_candidate_count=0, table_like_page_count=0,
        figure_count=1, figure_candidate_count=1, caption_candidate_count=0,
        empty_page_count=0, text_chars_total=30000, avg_chars_per_page=3000,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=False)
    assert verdicts.quality_status == "weak"


def test_quality_status_poor_when_two_or_more_poor():
    # text=good, table=poor (fallback, no candidates), visual=poor (fallback) → 2 poor → overall poor
    summary = AuditSummary(
        page_count=10, table_count=0, table_candidate_count=0, table_like_page_count=0,
        figure_count=0, figure_candidate_count=0, caption_candidate_count=0,
        empty_page_count=0, text_chars_total=30000, avg_chars_per_page=3000,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=True)
    assert verdicts.table_readiness == "poor"
    assert verdicts.visual_readiness == "poor"
    assert verdicts.text_readiness == "good"
    assert verdicts.quality_status == "poor"


def test_quality_status_poor_when_text_poor():
    summary = AuditSummary(
        page_count=10, table_count=0, table_candidate_count=0, table_like_page_count=0,
        figure_count=0, figure_candidate_count=0, caption_candidate_count=0,
        empty_page_count=4, text_chars_total=50, avg_chars_per_page=5,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=False)
    assert verdicts.quality_status == "poor"


def test_risk_flags_include_fallback_and_large_doc():
    summary = AuditSummary(
        page_count=300, table_count=0, table_candidate_count=0, table_like_page_count=0,
        figure_count=0, figure_candidate_count=0, caption_candidate_count=0,
        empty_page_count=0, text_chars_total=50000, avg_chars_per_page=166,
        parse_error_count=0, chunk_count=1200,
    )
    verdicts = compute_verdicts(summary, fallback_used=True)
    assert "fallback_parser_used" in verdicts.risk_flags
    assert "no_structured_tables" in verdicts.risk_flags
    assert "no_figures" in verdicts.risk_flags
    assert "large_document" in verdicts.risk_flags
    assert "high_chunk_count" in verdicts.risk_flags


def test_detect_fallback_unknown_case():
    # pypdfium2-text with errors that match neither parser_selection nor docling_primary_parser
    canonical = _make_canonical(
        parser_name="pypdfium2-text",
        errors=[{"type": "SomeOtherError", "message": "unexpected"}],
    )
    fallback_used, reason = detect_fallback(canonical)
    assert fallback_used is True
    assert reason == "unknown"


def test_risk_flag_parse_errors_present():
    summary = AuditSummary(
        page_count=10, table_count=1, table_candidate_count=1, table_like_page_count=1,
        figure_count=0, figure_candidate_count=0, caption_candidate_count=0,
        empty_page_count=0, text_chars_total=20000, avg_chars_per_page=2000,
        parse_error_count=2, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=False)
    assert "parse_errors_present" in verdicts.risk_flags


def test_risk_flag_low_text_density():
    summary = AuditSummary(
        page_count=10, table_count=0, table_candidate_count=0, table_like_page_count=0,
        figure_count=0, figure_candidate_count=0, caption_candidate_count=0,
        empty_page_count=0, text_chars_total=800, avg_chars_per_page=80,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=False)
    assert "low_text_density" in verdicts.risk_flags


def test_risk_flag_high_empty_page_ratio():
    summary = AuditSummary(
        page_count=10, table_count=0, table_candidate_count=0, table_like_page_count=0,
        figure_count=0, figure_candidate_count=0, caption_candidate_count=0,
        empty_page_count=2, text_chars_total=5000, avg_chars_per_page=500,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=False)
    assert "high_empty_page_ratio" in verdicts.risk_flags


def test_risk_flag_missing_docling_json():
    summary = AuditSummary(
        page_count=10, table_count=2, table_candidate_count=2, table_like_page_count=2,
        figure_count=1, figure_candidate_count=1, caption_candidate_count=1,
        empty_page_count=0, text_chars_total=20000, avg_chars_per_page=2000,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=False, docling_missing=True)
    assert "missing_docling_json" in verdicts.risk_flags
