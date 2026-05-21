# Phase 7A — Parse Quality Audit: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable `ParseQualityService` that audits canonical artifacts after ingestion and on demand, storing heuristic readiness verdicts in Postgres and writing per-document audit artifacts.

**Architecture:** New `audit/` module following the existing service pattern. `ParseQualityService.audit()` reads `canonical.json` + `document.md` + `docling.json` (when available), computes text/table/visual readiness verdicts, writes `parse_audit.json` + `parse_audit.md` artifacts, and inserts a `parse_quality_audits` DB row with `is_latest` history tracking. `IngestionService` calls it automatically after a successful parse; a CLI supports manual re-runs.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (mapped_column / Mapped), pytest, argparse. No new dependencies.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `backend/src/docifer_backend/audit/__init__.py` | Package marker |
| Create | `backend/src/docifer_backend/audit/models.py` | `ParseQualityAudit` SQLAlchemy model |
| Create | `backend/src/docifer_backend/audit/metrics.py` | Stat extraction, fallback detection, heuristic verdicts |
| Create | `backend/src/docifer_backend/audit/reporting.py` | Write `parse_audit.json` + `parse_audit.md` |
| Create | `backend/src/docifer_backend/audit/service.py` | `ParseQualityService` orchestrator + `ParseQualityReport` |
| Create | `backend/src/docifer_backend/audit/cli.py` | `docifer audit` CLI command |
| Create | `backend/tests/test_audit.py` | All audit tests |
| Modify | `backend/src/docifer_backend/storage/database.py` | Import audit models in `create_database_schema()` |
| Modify | `backend/src/docifer_backend/ingestion/service.py` | Call `ParseQualityService.audit()` after successful parse |

---

## Task 1: DB Model

**Files:**
- Create: `backend/src/docifer_backend/audit/__init__.py`
- Create: `backend/src/docifer_backend/audit/models.py`
- Modify: `backend/src/docifer_backend/storage/database.py:53-60`
- Test: `backend/tests/test_audit.py`

- [ ] **Step 1.1: Write failing tests for the DB model**

Create `backend/tests/test_audit.py`:

```python
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
            .order_by(ParseQualityAudit.created_at)
        ).all()

    assert len(rows) == 2, "Both audit rows must be preserved (history not deleted)"
    assert rows[0].id == first_id
    assert rows[0].is_latest is False
    assert rows[1].is_latest is True
```

- [ ] **Step 1.2: Run test to confirm it fails**

```
cd backend
uv run pytest tests/test_audit.py -v
```

Expected: `ImportError: No module named 'docifer_backend.audit'`

- [ ] **Step 1.3: Create the package marker**

Create `backend/src/docifer_backend/audit/__init__.py` (empty file).

- [ ] **Step 1.4: Create the DB model**

Create `backend/src/docifer_backend/audit/models.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from docifer_backend.ingestion.models import new_uuid, utc_now
from docifer_backend.storage.database import Base


class ParseQualityAudit(Base):
    __tablename__ = "parse_quality_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id"), nullable=False, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    canonical_path: Mapped[str] = mapped_column(Text, nullable=False)

    parser_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    audit_version: Mapped[str] = mapped_column(String(32), nullable=False)
    audit_run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    audit_status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    quality_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    text_readiness: Mapped[str | None] = mapped_column(String(16), nullable=True)
    table_readiness: Mapped[str | None] = mapped_column(String(16), nullable=True)
    visual_readiness: Mapped[str | None] = mapped_column(String(16), nullable=True)

    risk_flags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    artifact_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_md_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
```

- [ ] **Step 1.5: Register audit models in `create_database_schema()`**

Edit `backend/src/docifer_backend/storage/database.py`. Find this block:

```python
def create_database_schema() -> None:
    """Create local development tables if they do not already exist."""

    # Import models here so their tables are registered on Base.metadata.
    import docifer_backend.ingestion.models  # noqa: F401
    import docifer_backend.retrieval.models  # noqa: F401

    Base.metadata.create_all(bind=get_database_engine())
```

Replace with:

```python
def create_database_schema() -> None:
    """Create local development tables if they do not already exist."""

    # Import models here so their tables are registered on Base.metadata.
    import docifer_backend.audit.models  # noqa: F401
    import docifer_backend.ingestion.models  # noqa: F401
    import docifer_backend.retrieval.models  # noqa: F401

    Base.metadata.create_all(bind=get_database_engine())
```

- [ ] **Step 1.6: Run the test and verify it passes**

```
cd backend
uv run pytest tests/test_audit.py::test_is_latest_flips_on_second_audit -v
```

Expected: `PASSED`

- [ ] **Step 1.7: Commit**

```bash
git add backend/src/docifer_backend/audit/__init__.py
git add backend/src/docifer_backend/audit/models.py
git add backend/src/docifer_backend/storage/database.py
git add backend/tests/test_audit.py
git commit -m "feat(audit): add ParseQualityAudit DB model and schema registration"
```

---

## Task 2: Metrics Computation

**Files:**
- Create: `backend/src/docifer_backend/audit/metrics.py`
- Test: `backend/tests/test_audit.py`

- [ ] **Step 2.1: Add metrics tests to `test_audit.py`**

Append to `backend/tests/test_audit.py`:

```python
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
    summary = AuditSummary(
        page_count=10, table_count=0, table_candidate_count=0, table_like_page_count=0,
        figure_count=0, figure_candidate_count=0, caption_candidate_count=0,
        empty_page_count=0, text_chars_total=30000, avg_chars_per_page=3000,
        parse_error_count=0, chunk_count=0,
    )
    verdicts = compute_verdicts(summary, fallback_used=False)
    assert verdicts.quality_status == "weak"


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
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```
cd backend
uv run pytest tests/test_audit.py -k "fallback or compute_summary or readiness or quality_status or risk_flags" -v
```

Expected: `ImportError: cannot import name 'AuditSummary' from 'docifer_backend.audit.metrics'`

- [ ] **Step 2.3: Create `metrics.py`**

Create `backend/src/docifer_backend/audit/metrics.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

AUDIT_VERSION = "0.1.0"

_TABLE_LINE_RE = re.compile(r"\S+(?:[ \t]{2,}|\t)\S+")
_FIGURE_REF_RE = re.compile(r"\b(?:figure|fig\.?|chart|diagram|exhibit)\b", re.IGNORECASE)
_CAPTION_RE = re.compile(r"\b(?:figure|fig\.?|chart|exhibit)\s*\d+", re.IGNORECASE)


@dataclass(frozen=True)
class AuditSummary:
    page_count: int
    table_count: int
    table_candidate_count: int
    table_like_page_count: int
    figure_count: int
    figure_candidate_count: int
    caption_candidate_count: int
    empty_page_count: int
    text_chars_total: int
    avg_chars_per_page: float
    parse_error_count: int
    chunk_count: int


@dataclass(frozen=True)
class AuditVerdicts:
    text_readiness: str
    table_readiness: str
    visual_readiness: str
    quality_status: str
    risk_flags: list[str] = field(default_factory=list)


def detect_fallback(canonical: dict) -> tuple[bool, str | None]:
    """Return (fallback_used, fallback_reason) based on parser metadata in canonical.json."""
    if canonical.get("parser", {}).get("name") != "pypdfium2-text":
        return False, None
    errors = canonical.get("parse", {}).get("errors", [])
    for error in errors:
        if error.get("type") == "parser_selection":
            return True, "size_threshold"
        if error.get("stage") == "docling_primary_parser":
            return True, "docling_failed"
    return True, "manual_backend" if not errors else "unknown"


def compute_summary(
    canonical: dict,
    markdown_text: str,
    docling: dict | None,
    chunk_count: int = 0,
) -> AuditSummary:
    """Extract raw stats from available artifact sources."""
    parse = canonical.get("parse", {})
    page_count = parse.get("page_count", 0)
    table_count = parse.get("table_count", 0)
    figure_count = parse.get("figure_count", 0)
    parse_error_count = len(parse.get("errors", []))

    text_chars_total, empty_page_count, avg_chars_per_page = _text_stats(markdown_text, page_count)

    if docling is not None:
        table_candidate_count, table_like_page_count = _table_stats_from_docling(docling)
        figure_candidate_count, caption_candidate_count = _figure_stats_from_docling(docling)
    else:
        table_candidate_count, table_like_page_count = _table_stats_from_text(markdown_text)
        figure_candidate_count, caption_candidate_count = _figure_stats_from_text(markdown_text)

    return AuditSummary(
        page_count=page_count,
        table_count=table_count,
        table_candidate_count=table_candidate_count,
        table_like_page_count=table_like_page_count,
        figure_count=figure_count,
        figure_candidate_count=figure_candidate_count,
        caption_candidate_count=caption_candidate_count,
        empty_page_count=empty_page_count,
        text_chars_total=text_chars_total,
        avg_chars_per_page=round(avg_chars_per_page, 1),
        parse_error_count=parse_error_count,
        chunk_count=chunk_count,
    )


def compute_verdicts(summary: AuditSummary, *, fallback_used: bool) -> AuditVerdicts:
    """Compute advisory readiness verdicts and risk flags from summary stats."""
    text_readiness = _text_readiness(summary)
    table_readiness = _table_readiness(summary, fallback_used=fallback_used)
    visual_readiness = _visual_readiness(summary, fallback_used=fallback_used)
    quality_status = _quality_status(text_readiness, table_readiness, visual_readiness)
    risk_flags = _risk_flags(summary, fallback_used=fallback_used)
    return AuditVerdicts(
        text_readiness=text_readiness,
        table_readiness=table_readiness,
        visual_readiness=visual_readiness,
        quality_status=quality_status,
        risk_flags=risk_flags,
    )


# ── private helpers ──────────────────────────────────────────────────────────


def _text_stats(markdown: str, page_count: int) -> tuple[int, int, float]:
    pages = re.split(r"<!--\s*page\s+\d+\s*-->", markdown)
    pages = [p.strip() for p in pages]
    content_pages = [p for p in pages if p]

    if not content_pages:
        total = len(markdown.strip())
        return total, 0, total / max(page_count, 1)

    total = sum(len(p) for p in content_pages)
    empty = sum(1 for p in pages if not p)
    avg = total / max(len(content_pages), 1)
    return total, empty, avg


def _table_stats_from_docling(docling: dict) -> tuple[int, int]:
    """Returns (table_candidate_count, table_like_page_count) from structured docling data."""
    tables = docling.get("tables", [])
    pages: set[int] = set()
    for table in tables:
        for prov in table.get("prov", []):
            if prov.get("page_no"):
                pages.add(prov["page_no"])
    return len(tables), len(pages)


def _figure_stats_from_docling(docling: dict) -> tuple[int, int]:
    """Returns (figure_candidate_count, caption_candidate_count) from structured docling data."""
    pictures = docling.get("pictures", [])
    captions_with_text = sum(
        1 for pic in pictures if any(c.get("text", "") for c in pic.get("captions", []))
    )
    return len(pictures), captions_with_text


def _table_stats_from_text(markdown: str) -> tuple[int, int]:
    """Estimate table presence from text patterns when docling.json is unavailable."""
    pages = re.split(r"<!--\s*page\s+\d+\s*-->", markdown)
    table_like_pages = 0
    for page in pages:
        lines = [l for l in page.splitlines() if l.strip()]
        table_lines = sum(1 for l in lines if _TABLE_LINE_RE.search(l))
        if table_lines >= 3:
            table_like_pages += 1
    candidate_count = max(table_like_pages // 2, 1) if table_like_pages > 0 else 0
    return candidate_count, table_like_pages


def _figure_stats_from_text(markdown: str) -> tuple[int, int]:
    """Estimate figure references from text when docling.json is unavailable."""
    refs = len(_FIGURE_REF_RE.findall(markdown))
    captions = len(_CAPTION_RE.findall(markdown))
    return refs, captions


def _text_readiness(s: AuditSummary) -> str:
    empty_ratio = s.empty_page_count / max(s.page_count, 1)
    if empty_ratio > 0.30 or s.avg_chars_per_page < 50:
        return "poor"
    if empty_ratio > 0.05 or s.avg_chars_per_page < 200:
        return "weak"
    return "good"


def _table_readiness(s: AuditSummary, *, fallback_used: bool) -> str:
    if not fallback_used:
        if s.table_count >= 1 and s.table_candidate_count >= 1:
            return "good"
        return "weak"
    if s.table_candidate_count > 0 or s.table_like_page_count > 0:
        return "weak"
    return "poor"


def _visual_readiness(s: AuditSummary, *, fallback_used: bool) -> str:
    if fallback_used:
        return "poor"
    if s.figure_count >= 1 and s.caption_candidate_count >= 1:
        return "good"
    if s.figure_count >= 1:
        return "weak"
    return "poor"


def _quality_status(text: str, table: str, visual: str) -> str:
    statuses = [text, table, visual]
    if all(s == "good" for s in statuses):
        return "good"
    if "poor" not in statuses:
        return "weak"
    return "poor"


def _risk_flags(s: AuditSummary, *, fallback_used: bool) -> list[str]:
    flags: list[str] = []
    if fallback_used:
        flags.append("fallback_parser_used")
    if s.table_count == 0 and s.table_candidate_count == 0:
        flags.append("no_structured_tables")
    elif s.table_count == 0 and s.table_candidate_count > 0:
        flags.append("table_like_text_without_structure")
    if s.figure_count == 0 and s.figure_candidate_count == 0:
        flags.append("no_figures")
    if s.empty_page_count / max(s.page_count, 1) > 0.10:
        flags.append("high_empty_page_ratio")
    if s.parse_error_count > 0:
        flags.append("parse_errors_present")
    if s.avg_chars_per_page < 100:
        flags.append("low_text_density")
    if s.page_count > 200:
        flags.append("large_document")
    if s.chunk_count > 1000:
        flags.append("high_chunk_count")
    return flags
```

- [ ] **Step 2.4: Run metrics tests**

```
cd backend
uv run pytest tests/test_audit.py -k "fallback or compute_summary or readiness or quality_status or risk_flags" -v
```

Expected: all pass.

- [ ] **Step 2.5: Commit**

```bash
git add backend/src/docifer_backend/audit/metrics.py backend/tests/test_audit.py
git commit -m "feat(audit): add metrics computation and heuristic verdicts"
```

---

## Task 3: Artifact Reporting

**Files:**
- Create: `backend/src/docifer_backend/audit/reporting.py`
- Test: `backend/tests/test_audit.py`

- [ ] **Step 3.1: Add reporting tests**

Append to `backend/tests/test_audit.py`:

```python
# ── reporting tests ─────────────────────────────────────────────────────────────

from docifer_backend.audit.metrics import AuditSummary, AuditVerdicts
from docifer_backend.audit.reporting import write_audit_artifacts


def _make_summary() -> AuditSummary:
    return AuditSummary(
        page_count=10, table_count=2, table_candidate_count=2, table_like_page_count=2,
        figure_count=1, figure_candidate_count=1, caption_candidate_count=1,
        empty_page_count=0, text_chars_total=20000, avg_chars_per_page=2000,
        parse_error_count=0, chunk_count=0,
    )


def _make_verdicts() -> AuditVerdicts:
    return AuditVerdicts(
        text_readiness="good",
        table_readiness="good",
        visual_readiness="weak",
        quality_status="weak",
        risk_flags=["no_figures"],
    )


def test_write_audit_artifacts_creates_files(tmp_path):
    json_path, md_path = write_audit_artifacts(
        artifact_dir=tmp_path,
        content_hash="b" * 64,
        audit_run_id="run-abc",
        audit_status="completed",
        summary=_make_summary(),
        verdicts=_make_verdicts(),
        elapsed_ms=250,
        fallback_used=False,
        parser_name="docling",
    )
    assert json_path is not None
    assert md_path is not None
    assert (tmp_path / "parse_audit.json").exists()
    assert (tmp_path / "parse_audit.md").exists()

    import json as json_mod
    payload = json_mod.loads((tmp_path / "parse_audit.json").read_text())
    assert payload["audit_status"] == "completed"
    assert payload["elapsed_ms"] == 250
    assert "table_candidate_count" in payload["summary"]
    assert payload["verdicts"]["text_readiness"] == "good"


def test_write_audit_artifacts_unwritable_dir(tmp_path):
    unwritable = tmp_path / "locked"
    unwritable.mkdir()
    unwritable.chmod(0o444)
    try:
        with pytest.raises(Exception):
            write_audit_artifacts(
                artifact_dir=unwritable,
                content_hash="c" * 64,
                audit_run_id="run-xyz",
                audit_status="completed",
                summary=_make_summary(),
                verdicts=_make_verdicts(),
                elapsed_ms=100,
                fallback_used=False,
                parser_name="docling",
            )
    finally:
        unwritable.chmod(0o755)
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```
cd backend
uv run pytest tests/test_audit.py -k "write_audit" -v
```

Expected: `ImportError: cannot import name 'write_audit_artifacts'`

- [ ] **Step 3.3: Create `reporting.py`**

Create `backend/src/docifer_backend/audit/reporting.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from docifer_backend.audit.metrics import AUDIT_VERSION, AuditSummary, AuditVerdicts


def write_audit_artifacts(
    *,
    artifact_dir: Path,
    content_hash: str,
    audit_run_id: str,
    audit_status: str,
    summary: AuditSummary | None,
    verdicts: AuditVerdicts | None,
    elapsed_ms: int | None,
    fallback_used: bool,
    parser_name: str,
    error_message: str | None = None,
) -> tuple[str, str]:
    """Write parse_audit.json and parse_audit.md to artifact_dir.

    Raises OSError if the directory is unwritable.
    Returns (json_path_str, md_path_str).
    """
    json_path = artifact_dir / "parse_audit.json"
    md_path = artifact_dir / "parse_audit.md"

    payload = _build_json_payload(
        content_hash=content_hash,
        audit_run_id=audit_run_id,
        audit_status=audit_status,
        summary=summary,
        verdicts=verdicts,
        elapsed_ms=elapsed_ms,
        fallback_used=fallback_used,
        parser_name=parser_name,
        error_message=error_message,
    )
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    md_path.write_text(_build_md_report(payload), encoding="utf-8")

    return str(json_path), str(md_path)


def _build_json_payload(
    *,
    content_hash: str,
    audit_run_id: str,
    audit_status: str,
    summary: AuditSummary | None,
    verdicts: AuditVerdicts | None,
    elapsed_ms: int | None,
    fallback_used: bool,
    parser_name: str,
    error_message: str | None,
) -> dict:
    payload: dict = {
        "audit_version": AUDIT_VERSION,
        "audit_run_id": audit_run_id,
        "audit_status": audit_status,
        "content_hash": content_hash,
        "parser_name": parser_name,
        "fallback_used": fallback_used,
        "elapsed_ms": elapsed_ms,
    }
    if error_message:
        payload["error_message"] = error_message
    if verdicts is not None:
        payload["verdicts"] = {
            "quality_status": verdicts.quality_status,
            "text_readiness": verdicts.text_readiness,
            "table_readiness": verdicts.table_readiness,
            "visual_readiness": verdicts.visual_readiness,
            "risk_flags": verdicts.risk_flags,
        }
    if summary is not None:
        payload["summary"] = {
            "page_count": summary.page_count,
            "table_count": summary.table_count,
            "table_candidate_count": summary.table_candidate_count,
            "table_like_page_count": summary.table_like_page_count,
            "figure_count": summary.figure_count,
            "figure_candidate_count": summary.figure_candidate_count,
            "caption_candidate_count": summary.caption_candidate_count,
            "empty_page_count": summary.empty_page_count,
            "text_chars_total": summary.text_chars_total,
            "avg_chars_per_page": summary.avg_chars_per_page,
            "parse_error_count": summary.parse_error_count,
            "chunk_count": summary.chunk_count,
        }
    return payload


def _build_md_report(payload: dict) -> str:
    lines = [
        "# Parse Quality Audit Report",
        "",
        f"**Status:** {payload['audit_status']}",
        f"**Content Hash:** `{payload['content_hash'][:16]}...`",
        f"**Parser:** {payload['parser_name']} (fallback: {payload['fallback_used']})",
        f"**Elapsed:** {payload.get('elapsed_ms', 'n/a')} ms",
        "",
    ]
    if "verdicts" in payload:
        v = payload["verdicts"]
        lines += [
            "## Readiness Verdicts",
            "",
            "| Dimension | Verdict |",
            "|---|---|",
            f"| Overall | **{v['quality_status']}** |",
            f"| Text | {v['text_readiness']} |",
            f"| Tables | {v['table_readiness']} |",
            f"| Visual | {v['visual_readiness']} |",
            "",
        ]
        if v["risk_flags"]:
            lines += ["## Risk Flags", ""]
            lines += [f"- `{flag}`" for flag in v["risk_flags"]]
            lines.append("")
    if "summary" in payload:
        s = payload["summary"]
        lines += [
            "## Summary",
            "",
            f"- Pages: {s['page_count']} ({s['empty_page_count']} empty)",
            f"- Tables: {s['table_count']} structured, {s['table_candidate_count']} candidates",
            f"- Figures: {s['figure_count']} structured, {s['figure_candidate_count']} candidates",
            f"- Text: {s['text_chars_total']:,} chars, {s['avg_chars_per_page']:.0f} avg/page",
            "",
        ]
    if "error_message" in payload:
        lines += ["## Error", "", payload["error_message"], ""]
    return "\n".join(lines)
```

- [ ] **Step 3.4: Run reporting tests**

```
cd backend
uv run pytest tests/test_audit.py -k "write_audit" -v
```

Expected: both pass (note: the unwritable-dir test may be skipped on Windows where chmod 0o444 is not enforced — that is acceptable).

- [ ] **Step 3.5: Commit**

```bash
git add backend/src/docifer_backend/audit/reporting.py backend/tests/test_audit.py
git commit -m "feat(audit): add artifact reporting (parse_audit.json + parse_audit.md)"
```

---

## Task 4: ParseQualityService

**Files:**
- Create: `backend/src/docifer_backend/audit/service.py`
- Test: `backend/tests/test_audit.py`

- [ ] **Step 4.1: Add service tests**

Append to `backend/tests/test_audit.py`:

```python
# ── service tests ───────────────────────────────────────────────────────────────

from docifer_backend.audit.service import ParseQualityReport, ParseQualityService
from docifer_backend.ingestion.models import Document


def _write_canonical(path: Path, *, parser_name: str = "docling", errors: list | None = None) -> None:
    docling_path = path.parent / "docling.json"
    md_path = path.parent / "document.md"
    docling_path.write_text(
        json.dumps(
            {
                "schema_name": "DoclingDocument",
                "tables": [
                    {
                        "label": "table",
                        "prov": [{"page_no": 2}],
                        "data": {
                            "num_rows": 4,
                            "num_cols": 3,
                            "table_cells": [
                                {"text": "H1", "column_header": True, "row_header": False,
                                 "start_row_offset_idx": 0, "start_col_offset_idx": 0},
                            ],
                        },
                    }
                ],
                "pictures": [
                    {
                        "label": "picture",
                        "prov": [{"page_no": 3}],
                        "captions": [{"text": "Figure 1. Revenue over time."}],
                    }
                ],
                "texts": [],
            }
        ),
        encoding="utf-8",
    )
    md_path.write_text(
        "\n\n".join(
            f"<!-- page {i} -->\n\n{'Financial data and analysis. ' * 30}" for i in range(1, 11)
        ),
        encoding="utf-8",
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": "docifer.canonical_document.v1",
                "document": {"content_hash": "a" * 64, "filename": "test.pdf"},
                "parser": {"name": parser_name, "version": "2.94.0"},
                "artifacts": {
                    "docling_json": str(docling_path),
                    "markdown": str(md_path),
                },
                "parse": {
                    "page_count": 10,
                    "table_count": 1,
                    "figure_count": 1,
                    "errors": errors or [],
                },
                "structures": {"tables": {"count": 1}, "figures": {"count": 1}},
            }
        ),
        encoding="utf-8",
    )


def _seed_document(session_factory, content_hash: str = "a" * 64) -> str:
    with session_factory() as session:
        doc = Document(
            filename="test.pdf",
            source_path="/tmp/test.pdf",
            content_hash=content_hash,
            file_size_bytes=5000,
        )
        session.add(doc)
        session.commit()
        return doc.id


def test_service_full_audit_run(tmp_path, session_factory):
    canonical_path = tmp_path / "canonical.json"
    _write_canonical(canonical_path)
    doc_id = _seed_document(session_factory)

    service = ParseQualityService(session_factory=session_factory)
    report = service.audit(canonical_path, "a" * 64)

    assert report.audit_status == "completed"
    assert report.quality_status is not None
    assert report.text_readiness is not None
    assert report.elapsed_ms is not None
    assert report.error_message is None
    assert report.failed_stage is None

    with session_factory() as session:
        row = session.scalar(
            select(ParseQualityAudit).where(ParseQualityAudit.content_hash == "a" * 64)
        )
    assert row is not None
    assert row.audit_status == "completed"
    assert row.is_latest is True
    assert (tmp_path / "parse_audit.json").exists()
    assert (tmp_path / "parse_audit.md").exists()


def test_service_failed_stage_read_canonical(tmp_path, session_factory):
    _seed_document(session_factory)
    missing_path = tmp_path / "nonexistent_canonical.json"

    service = ParseQualityService(session_factory=session_factory)
    report = service.audit(missing_path, "a" * 64)

    assert report.audit_status == "failed"
    assert report.failed_stage == "read_canonical"
    assert report.error_message is not None

    with session_factory() as session:
        row = session.scalar(
            select(ParseQualityAudit).where(ParseQualityAudit.content_hash == "a" * 64)
        )
    assert row is not None
    assert row.audit_status == "failed"
    assert row.failed_stage == "read_canonical"


def test_service_artifact_write_failure_persists_db_row(tmp_path, session_factory):
    canonical_path = tmp_path / "canonical.json"
    _write_canonical(canonical_path)
    _seed_document(session_factory)

    locked_dir = tmp_path / "locked"
    locked_dir.mkdir()
    locked_dir.chmod(0o444)

    try:
        locked_canonical = locked_dir / "canonical.json"
        import shutil
        shutil.copy(canonical_path, locked_canonical)
        locked_md = locked_dir / "document.md"
        locked_md_src = canonical_path.parent / "document.md"
        shutil.copy(locked_md_src, locked_md)
        locked_docling = locked_dir / "docling.json"
        shutil.copy(canonical_path.parent / "docling.json", locked_docling)

        import json as _json
        locked_canonical_data = _json.loads(locked_canonical.read_text())
        locked_canonical_data["artifacts"]["markdown"] = str(locked_md)
        locked_canonical_data["artifacts"]["docling_json"] = str(locked_docling)
        locked_canonical.chmod(0o644)
        locked_canonical.write_text(_json.dumps(locked_canonical_data), encoding="utf-8")
        locked_canonical.chmod(0o444)

        service = ParseQualityService(session_factory=session_factory)
        report = service.audit(locked_canonical, "a" * 64)

        assert report.audit_status == "failed"
        assert report.failed_stage == "write_artifacts"

        with session_factory() as session:
            row = session.scalar(
                select(ParseQualityAudit).where(ParseQualityAudit.content_hash == "a" * 64)
            )
        assert row is not None, "DB row must be persisted even when artifact write fails"
        assert row.audit_status == "failed"
        assert row.summary_json is not None, "summary_json must be populated despite write failure"
        assert row.artifact_json_path is None
        assert row.artifact_md_path is None
    finally:
        locked_dir.chmod(0o755)
        for f in locked_dir.iterdir():
            f.chmod(0o644)


def test_service_fallback_parser_path(tmp_path, session_factory):
    canonical_path = tmp_path / "canonical.json"
    _write_canonical(
        canonical_path,
        parser_name="pypdfium2-text",
        errors=[{"type": "parser_selection", "message": "file too large"}],
    )
    _seed_document(session_factory)

    service = ParseQualityService(session_factory=session_factory)
    report = service.audit(canonical_path, "a" * 64)

    assert report.audit_status == "completed"

    with session_factory() as session:
        row = session.scalar(
            select(ParseQualityAudit).where(ParseQualityAudit.content_hash == "a" * 64)
        )
    assert row.fallback_used is True
    assert row.fallback_reason == "size_threshold"
    assert "fallback_parser_used" in row.risk_flags_json
```

- [ ] **Step 4.2: Run to confirm tests fail**

```
cd backend
uv run pytest tests/test_audit.py -k "service_" -v
```

Expected: `ImportError: cannot import name 'ParseQualityService'`

- [ ] **Step 4.3: Create `service.py`**

Create `backend/src/docifer_backend/audit/service.py`:

```python
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.audit.metrics import (
    AUDIT_VERSION,
    AuditSummary,
    AuditVerdicts,
    compute_summary,
    compute_verdicts,
    detect_fallback,
)
from docifer_backend.audit.models import ParseQualityAudit
from docifer_backend.audit.reporting import write_audit_artifacts
from docifer_backend.config.paths import display_path, resolve_project_path
from docifer_backend.ingestion.models import Document, IngestionJob, new_uuid, utc_now
from docifer_backend.ingestion.status import IngestionStatus
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.storage.database import get_session_factory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParseQualityReport:
    audit_id: str
    content_hash: str
    audit_status: str
    quality_status: str | None
    text_readiness: str | None
    table_readiness: str | None
    visual_readiness: str | None
    risk_flags: list[str] = field(default_factory=list)
    elapsed_ms: int | None = None
    error_message: str | None = None
    failed_stage: str | None = None


class ParseQualityService:
    def __init__(self, *, session_factory: sessionmaker[Session] | None = None) -> None:
        self.session_factory = session_factory or get_session_factory()

    def audit(
        self,
        canonical_path: str | Path,
        content_hash: str,
        *,
        audit_run_id: str | None = None,
    ) -> ParseQualityReport:
        """Audit a canonical artifact. Never raises — failures are recorded in DB."""
        run_id = audit_run_id or str(uuid4())
        audit_id = new_uuid()
        canonical_path = Path(canonical_path)
        start_ms = int(time.monotonic() * 1000)

        document_id = self._get_document_id(content_hash)

        summary: AuditSummary | None = None
        verdicts: AuditVerdicts | None = None
        fallback_used = False
        fallback_reason: str | None = None
        parser_name = "unknown"
        parser_version: str | None = None
        canonical_schema_version: str | None = None

        # Stage: read_canonical
        try:
            canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return self._persist_failed(
                audit_id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=str(canonical_path),
                run_id=run_id,
                failed_stage="read_canonical",
                error_message=str(exc),
                elapsed_ms=int(time.monotonic() * 1000) - start_ms,
            )

        canonical_schema_version = canonical.get("schema_version")
        parser_name = canonical.get("parser", {}).get("name", "unknown")
        parser_version = canonical.get("parser", {}).get("version")
        fallback_used, fallback_reason = detect_fallback(canonical)

        # Stage: read_markdown
        md_path_str = canonical.get("artifacts", {}).get("markdown", "")
        try:
            markdown_text = resolve_project_path(md_path_str).read_text(encoding="utf-8")
        except Exception as exc:
            return self._persist_failed(
                audit_id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=display_path(canonical_path),
                run_id=run_id,
                failed_stage="read_markdown",
                error_message=str(exc),
                elapsed_ms=int(time.monotonic() * 1000) - start_ms,
                parser_name=parser_name,
                parser_version=parser_version,
                canonical_schema_version=canonical_schema_version,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )

        # Stage: read_docling_json (optional — failure is non-fatal)
        docling: dict | None = None
        docling_path_str = canonical.get("artifacts", {}).get("docling_json", "")
        if docling_path_str:
            docling_path = resolve_project_path(docling_path_str)
            if docling_path.exists():
                try:
                    docling = json.loads(docling_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.warning("Could not read docling.json: %s", exc)

        # Stage: compute_metrics
        try:
            chunk_count = self._get_chunk_count(content_hash)
            summary = compute_summary(canonical, markdown_text, docling, chunk_count=chunk_count)
            verdicts = compute_verdicts(summary, fallback_used=fallback_used)
        except Exception as exc:
            return self._persist_failed(
                audit_id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=display_path(canonical_path),
                run_id=run_id,
                failed_stage="compute_metrics",
                error_message=str(exc),
                elapsed_ms=int(time.monotonic() * 1000) - start_ms,
                parser_name=parser_name,
                parser_version=parser_version,
                canonical_schema_version=canonical_schema_version,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )

        elapsed_ms = int(time.monotonic() * 1000) - start_ms

        # Stage: write_artifacts
        artifact_json_path: str | None = None
        artifact_md_path: str | None = None
        write_failed = False
        write_error: str | None = None
        try:
            artifact_json_path, artifact_md_path = write_audit_artifacts(
                artifact_dir=canonical_path.parent,
                content_hash=content_hash,
                audit_run_id=run_id,
                audit_status="completed",
                summary=summary,
                verdicts=verdicts,
                elapsed_ms=elapsed_ms,
                fallback_used=fallback_used,
                parser_name=parser_name,
            )
        except Exception as exc:
            write_failed = True
            write_error = str(exc)
            logger.warning("Audit artifact write failed for %s: %s", content_hash[:12], exc)

        if write_failed:
            return self._persist_failed(
                audit_id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=display_path(canonical_path),
                run_id=run_id,
                failed_stage="write_artifacts",
                error_message=write_error,
                elapsed_ms=elapsed_ms,
                parser_name=parser_name,
                parser_version=parser_version,
                canonical_schema_version=canonical_schema_version,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                summary=summary,
                verdicts=verdicts,
            )

        # Stage: persist_db
        try:
            self._persist_completed(
                audit_id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=display_path(canonical_path),
                run_id=run_id,
                parser_name=parser_name,
                parser_version=parser_version,
                canonical_schema_version=canonical_schema_version,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                summary=summary,
                verdicts=verdicts,
                artifact_json_path=display_path(artifact_json_path) if artifact_json_path else None,
                artifact_md_path=display_path(artifact_md_path) if artifact_md_path else None,
                elapsed_ms=elapsed_ms,
            )
        except Exception as exc:
            logger.error("Audit DB persist failed for %s: %s", content_hash[:12], exc)
            return ParseQualityReport(
                audit_id=audit_id,
                content_hash=content_hash,
                audit_status="failed",
                quality_status=verdicts.quality_status if verdicts else None,
                text_readiness=verdicts.text_readiness if verdicts else None,
                table_readiness=verdicts.table_readiness if verdicts else None,
                visual_readiness=verdicts.visual_readiness if verdicts else None,
                risk_flags=list(verdicts.risk_flags) if verdicts else [],
                elapsed_ms=elapsed_ms,
                error_message=str(exc),
                failed_stage="persist_db",
            )

        return ParseQualityReport(
            audit_id=audit_id,
            content_hash=content_hash,
            audit_status="completed",
            quality_status=verdicts.quality_status,
            text_readiness=verdicts.text_readiness,
            table_readiness=verdicts.table_readiness,
            visual_readiness=verdicts.visual_readiness,
            risk_flags=list(verdicts.risk_flags),
            elapsed_ms=elapsed_ms,
        )

    def audit_by_content_hash(
        self,
        content_hash: str,
        *,
        audit_run_id: str | None = None,
    ) -> ParseQualityReport:
        """Resolve canonical path from DB then audit."""
        with self.session_factory() as session:
            job = session.scalar(
                select(IngestionJob)
                .where(IngestionJob.content_hash == content_hash)
                .where(
                    IngestionJob.status.in_([
                        IngestionStatus.PARSED.value,
                        IngestionStatus.INDEXED.value,
                    ])
                )
                .where(IngestionJob.artifact_path.isnot(None))
                .order_by(IngestionJob.completed_at.desc().nullslast())
            )
        if job is None:
            return ParseQualityReport(
                audit_id=new_uuid(),
                content_hash=content_hash,
                audit_status="failed",
                quality_status=None,
                text_readiness=None,
                table_readiness=None,
                visual_readiness=None,
                error_message=f"No completed ingestion job found for content_hash {content_hash[:12]}",
                failed_stage="read_canonical",
            )
        return self.audit(
            resolve_project_path(job.artifact_path),
            content_hash,
            audit_run_id=audit_run_id,
        )

    def audit_all_indexed(self, *, audit_run_id: str | None = None) -> list[ParseQualityReport]:
        """Audit all documents with at least one indexed text chunk."""
        run_id = audit_run_id or str(uuid4())
        rows = self._get_indexed_content_hashes_and_paths()
        results = []
        for content_hash, artifact_path in rows:
            report = self.audit(
                resolve_project_path(artifact_path),
                content_hash,
                audit_run_id=run_id,
            )
            results.append(report)
        return results

    # ── private ──────────────────────────────────────────────────────────────

    def _get_document_id(self, content_hash: str) -> str | None:
        with self.session_factory() as session:
            doc = session.scalar(
                select(Document).where(Document.content_hash == content_hash)
            )
            return doc.id if doc else None

    def _get_chunk_count(self, content_hash: str) -> int:
        with self.session_factory() as session:
            from sqlalchemy import func
            count = session.scalar(
                select(func.count())
                .select_from(TextChunkRecord)
                .where(TextChunkRecord.content_hash == content_hash)
            )
            return int(count or 0)

    def _get_indexed_content_hashes_and_paths(self) -> list[tuple[str, str]]:
        with self.session_factory() as session:
            rows = session.execute(
                select(Document.content_hash, IngestionJob.artifact_path)
                .join(
                    TextChunkRecord,
                    TextChunkRecord.content_hash == Document.content_hash,
                )
                .join(
                    IngestionJob,
                    (IngestionJob.content_hash == Document.content_hash)
                    & IngestionJob.artifact_path.isnot(None)
                    & IngestionJob.status.in_([
                        IngestionStatus.PARSED.value,
                        IngestionStatus.INDEXED.value,
                    ]),
                )
                .distinct()
            ).all()
            return [(row[0], row[1]) for row in rows]

    def _persist_failed(
        self,
        *,
        audit_id: str,
        document_id: str | None,
        content_hash: str,
        canonical_path: str,
        run_id: str,
        failed_stage: str,
        error_message: str,
        elapsed_ms: int,
        parser_name: str = "unknown",
        parser_version: str | None = None,
        canonical_schema_version: str | None = None,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
        summary: AuditSummary | None = None,
        verdicts: AuditVerdicts | None = None,
    ) -> ParseQualityReport:
        logger.warning(
            "Audit failed at stage=%s for content_hash=%s: %s",
            failed_stage, content_hash[:12], error_message,
        )
        if document_id is None:
            logger.error("Cannot persist audit row: no document_id for %s", content_hash[:12])
            return ParseQualityReport(
                audit_id=audit_id,
                content_hash=content_hash,
                audit_status="failed",
                quality_status=None,
                text_readiness=None,
                table_readiness=None,
                visual_readiness=None,
                elapsed_ms=elapsed_ms,
                error_message=error_message,
                failed_stage=failed_stage,
            )
        try:
            row = ParseQualityAudit(
                id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=canonical_path,
                parser_name=parser_name,
                parser_version=parser_version,
                canonical_schema_version=canonical_schema_version,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                audit_version=AUDIT_VERSION,
                audit_run_id=run_id,
                audit_status="failed",
                error_message=error_message,
                failed_stage=failed_stage,
                is_latest=True,
                quality_status=verdicts.quality_status if verdicts else None,
                text_readiness=verdicts.text_readiness if verdicts else None,
                table_readiness=verdicts.table_readiness if verdicts else None,
                visual_readiness=verdicts.visual_readiness if verdicts else None,
                risk_flags_json=list(verdicts.risk_flags) if verdicts else None,
                summary_json=_summary_to_dict(summary) if summary else None,
                artifact_json_path=None,
                artifact_md_path=None,
                elapsed_ms=elapsed_ms,
            )
            self._insert_with_is_latest_flip(row, content_hash)
        except Exception as exc:
            logger.error("Could not persist failed audit row: %s", exc)
        return ParseQualityReport(
            audit_id=audit_id,
            content_hash=content_hash,
            audit_status="failed",
            quality_status=verdicts.quality_status if verdicts else None,
            text_readiness=verdicts.text_readiness if verdicts else None,
            table_readiness=verdicts.table_readiness if verdicts else None,
            visual_readiness=verdicts.visual_readiness if verdicts else None,
            risk_flags=list(verdicts.risk_flags) if verdicts else [],
            elapsed_ms=elapsed_ms,
            error_message=error_message,
            failed_stage=failed_stage,
        )

    def _persist_completed(
        self,
        *,
        audit_id: str,
        document_id: str | None,
        content_hash: str,
        canonical_path: str,
        run_id: str,
        parser_name: str,
        parser_version: str | None,
        canonical_schema_version: str | None,
        fallback_used: bool,
        fallback_reason: str | None,
        summary: AuditSummary,
        verdicts: AuditVerdicts,
        artifact_json_path: str | None,
        artifact_md_path: str | None,
        elapsed_ms: int,
    ) -> None:
        if document_id is None:
            raise ValueError(f"No document_id for content_hash {content_hash[:12]}")
        row = ParseQualityAudit(
            id=audit_id,
            document_id=document_id,
            content_hash=content_hash,
            canonical_path=canonical_path,
            parser_name=parser_name,
            parser_version=parser_version,
            canonical_schema_version=canonical_schema_version,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            audit_version=AUDIT_VERSION,
            audit_run_id=run_id,
            audit_status="completed",
            error_message=None,
            failed_stage=None,
            is_latest=True,
            quality_status=verdicts.quality_status,
            text_readiness=verdicts.text_readiness,
            table_readiness=verdicts.table_readiness,
            visual_readiness=verdicts.visual_readiness,
            risk_flags_json=list(verdicts.risk_flags),
            summary_json=_summary_to_dict(summary),
            artifact_json_path=artifact_json_path,
            artifact_md_path=artifact_md_path,
            elapsed_ms=elapsed_ms,
        )
        self._insert_with_is_latest_flip(row, content_hash)

    def _insert_with_is_latest_flip(self, row: ParseQualityAudit, content_hash: str) -> None:
        with self.session_factory() as session:
            session.add(row)
            session.flush()
            session.execute(
                ParseQualityAudit.__table__.update()
                .where(ParseQualityAudit.content_hash == content_hash)
                .where(ParseQualityAudit.id != row.id)
                .values(is_latest=False)
            )
            session.commit()


def _summary_to_dict(s: AuditSummary) -> dict:
    return {
        "page_count": s.page_count,
        "table_count": s.table_count,
        "table_candidate_count": s.table_candidate_count,
        "table_like_page_count": s.table_like_page_count,
        "figure_count": s.figure_count,
        "figure_candidate_count": s.figure_candidate_count,
        "caption_candidate_count": s.caption_candidate_count,
        "empty_page_count": s.empty_page_count,
        "text_chars_total": s.text_chars_total,
        "avg_chars_per_page": s.avg_chars_per_page,
        "parse_error_count": s.parse_error_count,
        "chunk_count": s.chunk_count,
    }
```

- [ ] **Step 4.4: Run service tests**

```
cd backend
uv run pytest tests/test_audit.py -k "service_" -v
```

Expected: all pass (note: `test_service_artifact_write_failure_persists_db_row` may be skipped on Windows — that is acceptable; the DB-persist-on-failure path is still covered by the `_persist_failed` method called when `write_failed=True`).

- [ ] **Step 4.5: Run all audit tests so far**

```
cd backend
uv run pytest tests/test_audit.py -v
```

Expected: all pass.

- [ ] **Step 4.6: Commit**

```bash
git add backend/src/docifer_backend/audit/service.py backend/tests/test_audit.py
git commit -m "feat(audit): add ParseQualityService orchestrator"
```

---

## Task 5: CLI

**Files:**
- Create: `backend/src/docifer_backend/audit/cli.py`
- Test: `backend/tests/test_audit.py`

- [ ] **Step 5.1: Add CLI tests**

Append to `backend/tests/test_audit.py`:

```python
# ── CLI tests ───────────────────────────────────────────────────────────────────

from docifer_backend.audit.cli import main as audit_main


def test_cli_canonical_path(tmp_path, session_factory, monkeypatch):
    canonical_path = tmp_path / "canonical.json"
    _write_canonical(canonical_path)
    _seed_document(session_factory, content_hash="a" * 64)

    captured = []
    monkeypatch.setattr("docifer_backend.audit.cli._build_service", lambda: ParseQualityService(session_factory=session_factory))

    import io, sys
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)

    exit_code = audit_main(["--canonical-path", str(canonical_path)])
    assert exit_code == 0
    output = out.getvalue()
    assert "audit_status" in output


def test_cli_all_indexed_no_indexed_docs(session_factory, monkeypatch):
    monkeypatch.setattr("docifer_backend.audit.cli._build_service", lambda: ParseQualityService(session_factory=session_factory))
    import io, sys
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)

    exit_code = audit_main(["--all-indexed"])
    assert exit_code == 0
```

- [ ] **Step 5.2: Run tests to confirm they fail**

```
cd backend
uv run pytest tests/test_audit.py -k "cli_" -v
```

Expected: `ImportError: cannot import name 'main' from 'docifer_backend.audit.cli'`

- [ ] **Step 5.3: Create `cli.py`**

Create `backend/src/docifer_backend/audit/cli.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from docifer_backend.audit.service import ParseQualityReport, ParseQualityService
from docifer_backend.evaluation.registry import DocumentRegistry


def _build_service() -> ParseQualityService:
    return ParseQualityService()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run parse quality audit on Docifer documents.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--doc-id", help="Corpus doc ID (e.g. DOC-001)")
    group.add_argument("--content-hash", help="SHA-256 content hash")
    group.add_argument("--canonical-path", type=Path, help="Absolute path to canonical.json")
    group.add_argument("--all-indexed", action="store_true", help="Audit all indexed documents")
    parser.add_argument("--audit-run-id", help="Optional shared UUID for batch runs")
    args = parser.parse_args(argv)

    service = _build_service()
    run_id = args.audit_run_id or str(uuid4())

    if args.all_indexed:
        reports = service.audit_all_indexed(audit_run_id=run_id)
        print(json.dumps([_report_to_dict(r) for r in reports], indent=2))
        failed = sum(1 for r in reports if r.audit_status == "failed")
        return 1 if failed > 0 else 0

    if args.canonical_path:
        canonical = args.canonical_path.resolve()
        import json as _json
        canonical_data = _json.loads(canonical.read_text(encoding="utf-8"))
        content_hash = canonical_data["document"]["content_hash"]
        report = service.audit(canonical, content_hash, audit_run_id=run_id)
    elif args.content_hash:
        report = service.audit_by_content_hash(args.content_hash, audit_run_id=run_id)
    else:
        registry = DocumentRegistry()
        ref = registry.resolve(args.doc_id)
        if not ref.content_hash:
            print(f"ERROR: doc_id {args.doc_id!r} not found or not indexed", file=sys.stderr)
            return 1
        report = service.audit_by_content_hash(ref.content_hash, audit_run_id=run_id)

    print(json.dumps(_report_to_dict(report), indent=2))
    return 0 if report.audit_status == "completed" else 1


def _report_to_dict(r: ParseQualityReport) -> dict:
    return {
        "audit_id": r.audit_id,
        "content_hash": r.content_hash,
        "audit_status": r.audit_status,
        "quality_status": r.quality_status,
        "text_readiness": r.text_readiness,
        "table_readiness": r.table_readiness,
        "visual_readiness": r.visual_readiness,
        "risk_flags": r.risk_flags,
        "elapsed_ms": r.elapsed_ms,
        "error_message": r.error_message,
        "failed_stage": r.failed_stage,
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 5.4: Run CLI tests**

```
cd backend
uv run pytest tests/test_audit.py -k "cli_" -v
```

Expected: both pass.

- [ ] **Step 5.5: Commit**

```bash
git add backend/src/docifer_backend/audit/cli.py backend/tests/test_audit.py
git commit -m "feat(audit): add CLI for manual re-runs (--canonical-path, --content-hash, --doc-id, --all-indexed)"
```

---

## Task 6: Integrate with IngestionService

**Files:**
- Modify: `backend/src/docifer_backend/ingestion/service.py`
- Test: `backend/tests/test_audit.py`

- [ ] **Step 6.1: Add integration test**

Append to `backend/tests/test_audit.py`:

```python
# ── ingestion integration test ──────────────────────────────────────────────────

from docifer_backend.ingestion.service import IngestionService
from docifer_backend.ingestion.parser import AutoPdfParser, ParsedDocument


class FakeParser:
    def parse(self, source_path):
        return ParsedDocument(
            parser_name="docling",
            parser_version="2.0.0",
            docling_status="success",
            raw_document={
                "schema_name": "DoclingDocument",
                "pages": {"1": {"page_no": 1}},
                "texts": [{"label": "text", "text": "Hello world.", "prov": [{"page_no": 1}]}],
                "tables": [],
                "pictures": [],
            },
            markdown="<!-- page 1 -->\n\nHello world.",
            page_count=1,
            table_count=0,
            figure_count=0,
            errors=[],
        )


def test_ingestion_triggers_audit(tmp_path, session_factory):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake content for hashing purposes")

    service = IngestionService(
        session_factory=session_factory,
        parser=FakeParser(),
        processed_data_dir=tmp_path / "processed",
        initialize_schema=False,
        quality_service=ParseQualityService(session_factory=session_factory),
    )
    outcome = service.ingest_pdf(pdf_path)
    assert outcome.status in ("parsed", "indexed")

    with session_factory() as session:
        audit_row = session.scalar(
            select(ParseQualityAudit)
            .where(ParseQualityAudit.content_hash == outcome.document_id)
        )

    # The audit is triggered automatically — look up by the document's content_hash
    with session_factory() as session:
        from docifer_backend.ingestion.models import Document
        doc = session.scalar(
            select(Document).where(Document.id == outcome.document_id)
        )
        audit_row = session.scalar(
            select(ParseQualityAudit)
            .where(ParseQualityAudit.content_hash == doc.content_hash)
        )
    assert audit_row is not None, "IngestionService must trigger ParseQualityService.audit()"
    assert audit_row.audit_status == "completed"
```

- [ ] **Step 6.2: Run test to confirm it fails**

```
cd backend
uv run pytest tests/test_audit.py::test_ingestion_triggers_audit -v
```

Expected: `TypeError: IngestionService.__init__() got an unexpected keyword argument 'quality_service'`

- [ ] **Step 6.3: Modify `IngestionService` to accept and call `ParseQualityService`**

Edit `backend/src/docifer_backend/ingestion/service.py`.

Add import at top (after existing imports):

```python
from docifer_backend.audit.service import ParseQualityService
```

Change `IngestionService.__init__` signature to accept `quality_service`:

```python
def __init__(
    self,
    *,
    session_factory: sessionmaker[Session] | None = None,
    parser: DocumentParser | None = None,
    processed_data_dir: str | Path | None = None,
    max_attempts: int = 2,
    initialize_schema: bool = True,
    quality_service: ParseQualityService | None = None,
) -> None:
    if session_factory is None and initialize_schema:
        create_database_schema()

    settings = get_settings()
    self.session_factory = session_factory or get_session_factory()
    self.parser = parser or AutoPdfParser(
        backend=settings.pdf_parser_backend,
        docling_max_file_size_bytes=settings.docling_max_file_size_bytes,
    )
    self.processed_data_dir = resolve_project_path(
        processed_data_dir or settings.processed_data_dir
    )
    self.max_attempts = max_attempts
    self.quality_service = quality_service or ParseQualityService(session_factory=self.session_factory)
```

In `_parse_with_retries`, after the successful parse block that sets `job.status = IngestionStatus.PARSED.value` and calls `session.commit()`, add the audit call:

Find this block:

```python
                    job.status = IngestionStatus.PARSED.value
                    job.parser_name = parsed_document.parser_name
                    job.parser_version = parsed_document.parser_version
                    job.artifact_path = display_path(artifact_path)
                    job.completed_at = utc_now()
                    session.commit()
                    return _outcome_from_job(job, reused_existing=False)
```

Replace with:

```python
                    job.status = IngestionStatus.PARSED.value
                    job.parser_name = parsed_document.parser_name
                    job.parser_version = parsed_document.parser_version
                    job.artifact_path = display_path(artifact_path)
                    job.completed_at = utc_now()
                    session.commit()
                    job_snapshot = _outcome_from_job(job, reused_existing=False)

                self.quality_service.audit(artifact_path, file_info.content_hash)
                return job_snapshot
```

Note: the `self.quality_service.audit()` call is outside the `with self.session_factory() as session:` block to avoid nested session conflicts.

- [ ] **Step 6.4: Run integration test**

```
cd backend
uv run pytest tests/test_audit.py::test_ingestion_triggers_audit -v
```

Expected: `PASSED`

- [ ] **Step 6.5: Run full test suite**

```
cd backend
uv run pytest tests/ -v
```

Expected: all existing tests still pass, all new audit tests pass.

- [ ] **Step 6.6: Commit**

```bash
git add backend/src/docifer_backend/ingestion/service.py backend/tests/test_audit.py
git commit -m "feat(audit): wire ParseQualityService into IngestionService post-parse hook"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by task |
|---|---|
| Module structure (`audit/` with 5 files + cli) | Tasks 1–5 |
| DB schema — all columns including `failed_stage`, `fallback_reason`, `canonical_schema_version`, `elapsed_ms`, `is_latest` | Task 1 |
| `is_latest` flip + history preservation | Task 1 (test asserts both rows exist) |
| Auto-trigger post-ingestion | Task 6 |
| Manual re-run: `--canonical-path`, `--content-hash`, `--doc-id`, `--all-indexed` | Task 5 |
| Source reading: canonical → markdown → docling (optional) | Task 4 (`service.py`) |
| Text/table/visual readiness verdicts | Task 2 (`metrics.py`) |
| `quality_status` derivation (all-good → good; any-weak → weak; any-poor → poor) | Task 2 |
| Risk flags including `large_document`, `high_chunk_count`, `table_like_text_without_structure`, `missing_docling_json` | Task 2 |
| `fallback_used` + `fallback_reason` detection | Task 2 |
| Artifact JSON + MD write | Task 3 |
| `summary_json` fields including `table_candidate_count`, `figure_candidate_count`, etc. | Tasks 3–4 |
| Failure handling: `audit_status=failed`, `failed_stage`, `error_message` | Task 4 |
| Artifact write failure still persists DB row with `summary_json` | Task 4 (test + `_persist_failed` called with `summary=`) |
| `--all-indexed` = documents with TextChunkRecord entries | Task 4 (`_get_indexed_content_hashes_and_paths`) |
| `--all-ingested` deferred | Not implemented ✓ |
| API endpoint deferred | Not implemented ✓ |

**Note on `missing_docling_json` risk flag:** The spec lists this as a risk flag but `metrics.py` doesn't emit it — the service handles the missing docling.json case by passing `docling=None` to `compute_summary`, which uses text-based fallback heuristics. Add this flag emission to `_risk_flags` in `metrics.py`:

In `metrics.py`, `_risk_flags` should also accept a `docling_missing: bool` parameter. Add to `compute_verdicts` signature:

```python
def compute_verdicts(
    summary: AuditSummary,
    *,
    fallback_used: bool,
    docling_missing: bool = False,
) -> AuditVerdicts:
```

And in `_risk_flags`:
```python
def _risk_flags(s: AuditSummary, *, fallback_used: bool, docling_missing: bool = False) -> list[str]:
    ...
    if docling_missing:
        flags.append("missing_docling_json")
    return flags
```

Update `service.py` to pass `docling_missing` to `compute_verdicts` when docling.json path was referenced in canonical but file was not found.

Add this to `service.py` in the `read_docling_json` stage:

```python
docling_missing = False
if docling_path_str:
    docling_path = resolve_project_path(docling_path_str)
    if docling_path.exists():
        try:
            docling = json.loads(docling_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read docling.json: %s", exc)
            docling_missing = True
    else:
        docling_missing = True
```

And update the `compute_verdicts` call:
```python
verdicts = compute_verdicts(summary, fallback_used=fallback_used, docling_missing=docling_missing)
```

Commit this fix as part of Task 2 or Task 4 — it is a small addendum.
