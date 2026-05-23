# Phase 11 – Real Postgres/Qdrant Integration Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove Docifer works against real Postgres and Qdrant services — not only in-memory SQLite and in-memory Qdrant fixtures.

**Architecture:** Service-level tests inject real engines and clients directly via constructor injection (which all services already support). A shared `conftest.py` manages schema reset, collection cleanup, a fake AI provider, and canonical fixture factories. FastAPI smoke tests use `monkeypatch` to redirect cached globals to test infrastructure. Synthetic canonical.json fixtures are built in `tmp_path` at test time — no static JSON files needed.

**Tech Stack:** pytest, SQLAlchemy (real Postgres), qdrant-client (real Qdrant), FastAPI TestClient, pypdfium2 (real 1-page PDF render for visual tests)

---

## Design Notes (read before implementing)

### lru_cache problem
`get_settings()`, `get_database_engine()`, `get_session_factory()`, `get_qdrant_client()` are all `@lru_cache`'d. Setting env vars at test time doesn't affect already-cached values. Solution: bypass the cached globals entirely — all services (TextIndexingService, TableIndexingService, VisualIndexingService, TextQueryService, DocumentRegistryService) accept injected `session_factory` and `qdrant_client` via constructor. Use injection for all service-level tests. For FastAPI smoke tests, use `monkeypatch.setattr` on the imported function references in each module.

### Fake provider dimension
FakeIntegrationProvider returns `dim=16` vectors. All three collection types (`ensure_text_collection`, `ensure_table_collection`, `ensure_visual_collection`) derive `vector_size` from the first embedding batch — so as long as the collection is created fresh (prefix cleanup guarantees this), dim=16 works cleanly.

### Canonical fixture paths
`build_text_chunks_from_canonical` calls `resolve_project_path()` on `canonical["artifacts"]["docling_json"]`. `resolve_project_path` returns absolute paths as-is. All fixture paths are written as absolute paths using `tmp_path` — no static JSON files.

### Visual indexing requires a real PDF
`VisualIndexingService` calls `render_pdf_pages(source_path, pages_dir)` via pypdfium2. The fixture builds a valid minimal 1-page PDF via `_make_tiny_pdf()` which computes xref offsets dynamically in Python — no magic constants.

### TextQueryService.query() signature
Verify the exact call signature in `backend/src/docifer_backend/retrieval/query.py` before implementing Task 10. The method likely accepts a `QueryRequest` dataclass or keyword args. Adjust test calls accordingly.

### Table extraction reads TextChunkRecords
`extract_table_evidence_from_canonical` calls `_load_text_chunks(content_hash, session_factory)` to find existing text chunk rows for context matching. Run `TextIndexingService.index_canonical_document()` before `TableIndexingService.index_canonical_document()` on the same document if chunk-context matching is needed. For Phase 11, table fixtures have enough docling table data to extract without chunk context.

---

## File Map

**New files:**
- `backend/tests/integration/__init__.py`
- `backend/tests/integration/conftest.py`
- `backend/tests/integration/test_postgres_schema.py`
- `backend/tests/integration/test_qdrant_collections.py`
- `backend/tests/integration/test_text_indexing_integration.py`
- `backend/tests/integration/test_table_indexing_integration.py`
- `backend/tests/integration/test_visual_indexing_integration.py`
- `backend/tests/integration/test_query_integration.py`
- `backend/tests/integration/test_document_registry_integration.py`
- `backend/tests/integration/test_fastapi_smoke.py`
- `docs/phase11-real-integration-tests.md`

**Modified files:**
- `backend/pyproject.toml` — add `integration` marker
- `backend/README.md` — add integration test commands section

---

### Task 1: Pytest marker + integration package skeleton

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/integration/__init__.py`

- [ ] **Step 1: Add the integration marker to pyproject.toml**

Replace the existing `[tool.pytest.ini_options]` block:

```toml
[tool.pytest.ini_options]
tmp_path_retention_policy = "failed"
pythonpath = ["src"]
markers = [
    "integration: tests that require real Postgres and Qdrant services (set RUN_INTEGRATION_TESTS=true)",
]
```

- [ ] **Step 2: Create the integration package**

Create `backend/tests/integration/__init__.py` as an empty file.

- [ ] **Step 3: Verify unit suite still passes**

```powershell
uv run --project backend pytest backend/tests --basetemp backend/.pytest_tmp -q
```

Expected: `134 passed, 1 xfailed`

- [ ] **Step 4: Commit**

```
git add backend/pyproject.toml backend/tests/integration/__init__.py
git commit -m "test(integration): add integration test package and pytest marker"
```

---

### Task 2: conftest.py — skip guard + Postgres fixtures

**Files:**
- Create: `backend/tests/integration/conftest.py`

- [ ] **Step 1: Write conftest.py**

Create `backend/tests/integration/conftest.py`:

```python
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ── Skip guard ─────────────────────────────────────────────────────────────────

def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_INTEGRATION_TESTS") == "true":
        return
    skip = pytest.mark.skip(
        reason="Set RUN_INTEGRATION_TESTS=true to run integration tests"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


# ── Environment helpers ────────────────────────────────────────────────────────

def _pg_url() -> str:
    return os.environ.get(
        "DOCIFER_TEST_DATABASE_URL",
        "postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test",
    )


def _qdrant_url() -> str:
    return os.environ.get("DOCIFER_TEST_QDRANT_URL", "http://localhost:6333")


def _collection_prefix() -> str:
    return os.environ.get(
        "DOCIFER_TEST_QDRANT_COLLECTION_PREFIX", "test_docifer_"
    )


# ── Constants ─────────────────────────────────────────────────────────────────

TEXT_CONTENT_HASH = "a" * 63 + "1"
TABLE_CONTENT_HASH = "b" * 63 + "1"
VISUAL_CONTENT_HASH = "c" * 63 + "1"
QUERY_HASH_A = "d" * 63 + "1"
QUERY_HASH_B = "e" * 63 + "1"
QUERY_HASH_C = "f" * 63 + "1"
REGISTRY_HASH = "7" * 63 + "2"

TEST_EMBED_DIM = 16

TEXT_COLLECTION = _collection_prefix() + "text_chunks"
TABLE_COLLECTION = _collection_prefix() + "table_evidence"
VISUAL_COLLECTION = _collection_prefix() + "visual_evidence"
_ALL_TEST_COLLECTIONS = [TEXT_COLLECTION, TABLE_COLLECTION, VISUAL_COLLECTION]


# ── Postgres fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pg_engine():
    url = _pg_url()
    assert "test" in url, f"Refusing to use non-test database: {url}"

    import docifer_backend.ingestion.models  # noqa: F401
    import docifer_backend.retrieval.models  # noqa: F401
    import docifer_backend.retrieval.tables.models  # noqa: F401
    import docifer_backend.retrieval.visuals.models  # noqa: F401
    import docifer_backend.audit.models  # noqa: F401
    from docifer_backend.storage.database import Base

    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="module")
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
```

- [ ] **Step 2: Verify the conftest loads cleanly**

```powershell
uv run --project backend pytest backend/tests/integration --collect-only -q 2>&1 | Select-Object -First 10
```

Expected: no import errors, zero tests collected (files don't exist yet).

---

### Task 3: Qdrant fixtures + fake AI provider in conftest.py

**Files:**
- Modify: `backend/tests/integration/conftest.py` (append)

- [ ] **Step 1: Append Qdrant fixtures and FakeIntegrationProvider**

Append to `backend/tests/integration/conftest.py`:

```python
from qdrant_client import QdrantClient

from docifer_backend.providers.base import (
    CitationGroundingVerdict,
    GroundingEvidence,
    VisualEvidenceInput,
    VisualInterpretationResult,
    VisualObservation,
)


# ── Qdrant fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qdrant_client():
    client = QdrantClient(url=_qdrant_url())
    for name in _ALL_TEST_COLLECTIONS:
        if client.collection_exists(name):
            client.delete_collection(name)
    yield client
    for name in _ALL_TEST_COLLECTIONS:
        if client.collection_exists(name):
            client.delete_collection(name)


# ── Fake AI provider ───────────────────────────────────────────────────────────

def _fake_vector(text: str, dim: int = TEST_EMBED_DIM) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    return [(digest[i % len(digest)] / 127.5) - 1.0 for i in range(dim)]


class FakeIntegrationProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_fake_vector(t) for t in texts]

    def generate_grounded_answer(
        self, *, question: str, evidence: list[GroundingEvidence]
    ) -> str:
        if not evidence:
            return "I do not have enough evidence to answer this question."
        return f"Based on the evidence: {evidence[0].text[:80]} [{evidence[0].citation_id}]."

    def verify_citation_grounding(
        self, *, question: str, answer: str, evidence: list[GroundingEvidence]
    ) -> CitationGroundingVerdict:
        cids = [e.citation_id for e in evidence[:1]]
        return CitationGroundingVerdict(
            verdict="supported",
            supported_citation_ids=cids,
            weak_citation_ids=[],
            unsupported_claims=[],
            reasoning="Integration test fake verifier.",
            revised_answer=None,
        )

    def interpret_visual_evidence(
        self, *, question: str, visual_evidence: list[VisualEvidenceInput]
    ) -> VisualInterpretationResult:
        obs = [
            VisualObservation(
                citation_id=ve.citation_id,
                visual_id=ve.visual_id,
                observation_type="page_render",
                question_answered=True,
                extracted_facts=["Integration test observation."],
                visible_entities=[],
                numeric_values=[],
                confidence=0.9,
                limitations=[],
                abstain_reason="",
                supported=True,
                reasoning="Fake visual reasoning.",
            )
            for ve in visual_evidence
        ]
        return VisualInterpretationResult(
            status="interpreted",
            answer=f"Visual answer for: {question[:40]}",
            observations=obs,
            used_citation_ids=[ve.citation_id for ve in visual_evidence],
            abstain_reason="",
            reasoning="Fake visual reasoning.",
        )


@pytest.fixture(scope="module")
def fake_provider():
    return FakeIntegrationProvider()
```

---

### Task 4: Canonical fixture factory in conftest.py

**Files:**
- Modify: `backend/tests/integration/conftest.py` (append)

- [ ] **Step 1: Append fixture factories**

Append to `backend/tests/integration/conftest.py`:

```python
# ── Fixture data ───────────────────────────────────────────────────────────────

DOCLING_TEXT = {
    "texts": [
        {
            "text": "Middle-income countries need structural reforms to escape the middle-income trap.",
            "label": "text",
            "prov": [{"page_no": 1}],
            "self_ref": "#/texts/0",
        },
        {
            "text": "Institutional quality and investment in human capital are key factors for growth.",
            "label": "text",
            "prov": [{"page_no": 1}],
            "self_ref": "#/texts/1",
        },
    ],
    "tables": [],
    "pictures": [],
}

DOCLING_TABLE = {
    "texts": [
        {
            "text": "GDP growth rate comparison across regions.",
            "label": "text",
            "prov": [{"page_no": 1}],
            "self_ref": "#/texts/0",
        },
    ],
    "tables": [
        {
            "prov": [{"page_no": 1}],
            "data": {
                "grid": [
                    [
                        {"text": "Region", "column_header": True, "row_header": False, "row_section": False},
                        {"text": "Growth %", "column_header": True, "row_header": False, "row_section": False},
                    ],
                    [
                        {"text": "East Asia", "column_header": False, "row_header": False, "row_section": False},
                        {"text": "5.2", "column_header": False, "row_header": False, "row_section": False},
                    ],
                ]
            },
        }
    ],
    "pictures": [],
}

DOCLING_VISUAL = {
    "texts": [],
    "tables": [],
    "pictures": [],
}


# ── Tiny PDF builder ───────────────────────────────────────────────────────────

def _make_tiny_pdf() -> bytes:
    """Construct a minimal valid 1-page PDF that pypdfium2 can render."""
    obj1 = b"1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n"
    obj2 = b"2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n"
    obj3 = b"3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>\nendobj\n"
    header = b"%PDF-1.4\n"

    off1 = len(header)
    off2 = off1 + len(obj1)
    off3 = off2 + len(obj2)
    xref_start = off3 + len(obj3)

    body = header + obj1 + obj2 + obj3
    xref = (
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        + f"{off1:010d} 00000 n \n".encode()
        + f"{off2:010d} 00000 n \n".encode()
        + f"{off3:010d} 00000 n \n".encode()
        + b"trailer\n<</Size 4/Root 1 0 R>>\nstartxref\n"
        + f"{xref_start}\n%%EOF".encode()
    )
    return body + xref


# ── Canonical fixture factory ──────────────────────────────────────────────────

def make_canonical_fixture(
    base_dir: Path,
    *,
    name: str,
    content_hash: str,
    docling_data: dict,
    page_count: int = 1,
    table_count: int = 0,
    figure_count: int = 0,
    with_pdf: bool = False,
) -> Path:
    """Create canonical.json + docling.json + document.md in base_dir/name/."""
    doc_dir = base_dir / name
    doc_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = doc_dir / f"{name}.pdf"
    pdf_path.write_bytes(_make_tiny_pdf() if with_pdf else b"%PDF-1.4 placeholder")

    docling_path = doc_dir / "docling.json"
    docling_path.write_text(json.dumps(docling_data), encoding="utf-8")

    md_content = "# Integration Test Document\n\nMiddle-income countries need reforms.\n"
    if table_count:
        md_content += "\n<!-- page 1 -->\n| Region | Growth % |\n|---|---|\n| East Asia | 5.2 |\n"
    md_path = doc_dir / "document.md"
    md_path.write_text(md_content, encoding="utf-8")

    canonical = {
        "schema_version": "docifer.canonical_document.v1",
        "document": {
            "filename": f"{name}.pdf",
            "source_path": str(pdf_path),
            "content_hash": content_hash,
        },
        "parse": {
            "page_count": page_count,
            "table_count": table_count,
            "figure_count": figure_count,
        },
        "parser": {"name": "docling", "version": "test"},
        "content": {"markdown_char_count": len(md_content)},
        "artifacts": {
            "directory": str(doc_dir),
            "docling_json": str(docling_path),
            "markdown": str(md_path),
        },
    }
    canonical_path = doc_dir / "canonical.json"
    canonical_path.write_text(json.dumps(canonical), encoding="utf-8")
    return canonical_path
```

- [ ] **Step 2: Commit conftest.py**

```
git add backend/tests/integration/conftest.py
git commit -m "test(integration): add shared conftest with fixtures, fake provider, and canonical factory"
```

---

### Task 5: Postgres schema tests

**Files:**
- Create: `backend/tests/integration/test_postgres_schema.py`

- [ ] **Step 1: Write schema tests**

Create `backend/tests/integration/test_postgres_schema.py`:

```python
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
```

- [ ] **Step 2: Run and confirm 7 passed**

```powershell
$env:RUN_INTEGRATION_TESTS="true"
$env:DOCIFER_TEST_DATABASE_URL="postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test"
uv run --project backend pytest backend/tests/integration/test_postgres_schema.py -m integration -v --basetemp backend/.pytest_tmp
```

Expected: `7 passed`

- [ ] **Step 3: Commit**

```
git add backend/tests/integration/test_postgres_schema.py
git commit -m "test(integration): add Postgres schema integration tests"
```

---

### Task 6: Qdrant collection tests

**Files:**
- Create: `backend/tests/integration/test_qdrant_collections.py`

- [ ] **Step 1: Write collection tests**

Create `backend/tests/integration/test_qdrant_collections.py`:

```python
import pytest

from docifer_backend.retrieval.vector_store import (
    TEXT_PAYLOAD_INDEXES,
    TABLE_PAYLOAD_INDEXES,
    ensure_text_collection,
    ensure_table_collection,
)
from docifer_backend.storage.qdrant import get_vector_collection_stats

# constants imported directly — pytest adds conftest dir to sys.path
from conftest import TEXT_COLLECTION, TABLE_COLLECTION, TEST_EMBED_DIM


pytestmark = pytest.mark.integration


def test_text_collection_can_be_created(qdrant_client):
    ensure_text_collection(
        qdrant_client, collection_name=TEXT_COLLECTION, vector_size=TEST_EMBED_DIM
    )
    assert qdrant_client.collection_exists(TEXT_COLLECTION)


def test_table_collection_can_be_created(qdrant_client):
    ensure_table_collection(
        qdrant_client, collection_name=TABLE_COLLECTION, vector_size=TEST_EMBED_DIM
    )
    assert qdrant_client.collection_exists(TABLE_COLLECTION)


def test_collection_stats_return_correct_vector_size(qdrant_client):
    ensure_text_collection(
        qdrant_client, collection_name=TEXT_COLLECTION, vector_size=TEST_EMBED_DIM
    )
    stats = get_vector_collection_stats(
        collection_name=TEXT_COLLECTION, client=qdrant_client
    )
    assert stats["collection_name"] == TEXT_COLLECTION
    assert stats["vector_size"] == TEST_EMBED_DIM
    assert stats["status"] in ("green", "yellow", "grey", "red")


def test_text_payload_indexes_are_registered(qdrant_client):
    ensure_text_collection(
        qdrant_client, collection_name=TEXT_COLLECTION, vector_size=TEST_EMBED_DIM
    )
    stats = get_vector_collection_stats(
        collection_name=TEXT_COLLECTION, client=qdrant_client
    )
    for field in TEXT_PAYLOAD_INDEXES:
        assert field in stats["payload_indexes"], f"Missing payload index: {field}"


def test_nonexistent_collection_stats_raises_key_error(qdrant_client):
    with pytest.raises(KeyError):
        get_vector_collection_stats(
            collection_name="nonexistent_xyzzy_99", client=qdrant_client
        )
```

- [ ] **Step 2: Run and confirm 5 passed**

```powershell
$env:RUN_INTEGRATION_TESTS="true"
$env:DOCIFER_TEST_DATABASE_URL="postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test"
$env:DOCIFER_TEST_QDRANT_URL="http://localhost:6333"
uv run --project backend pytest backend/tests/integration/test_qdrant_collections.py -m integration -v --basetemp backend/.pytest_tmp
```

Expected: `5 passed`

- [ ] **Step 3: Commit**

```
git add backend/tests/integration/test_qdrant_collections.py
git commit -m "test(integration): add Qdrant collection creation and stats tests"
```

---

### Task 7: Text indexing integration tests

**Files:**
- Create: `backend/tests/integration/test_text_indexing_integration.py`

- [ ] **Step 1: Write text indexing tests**

Create `backend/tests/integration/test_text_indexing_integration.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select

from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.indexing import TextIndexingService
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.retrieval.vector_store import search_text_chunks

from conftest import (
    TEXT_COLLECTION,
    TEXT_CONTENT_HASH,
    TEST_EMBED_DIM,
    DOCLING_TEXT,
    make_canonical_fixture,
)


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def text_canonical(tmp_path_factory, pg_session_factory):
    tmp = tmp_path_factory.mktemp("text_doc")
    canonical_path = make_canonical_fixture(
        tmp, name="text_doc", content_hash=TEXT_CONTENT_HASH, docling_data=DOCLING_TEXT
    )
    with pg_session_factory() as session:
        session.add(Document(
            filename="text_doc.pdf",
            source_path=str(tmp / "text_doc" / "text_doc.pdf"),
            content_hash=TEXT_CONTENT_HASH,
            file_size_bytes=100,
        ))
        session.commit()
    yield canonical_path
    with pg_session_factory() as session:
        doc = session.scalar(
            select(Document).where(Document.content_hash == TEXT_CONTENT_HASH)
        )
        if doc:
            session.delete(doc)
            session.commit()


def _make_svc(pg_session_factory, qdrant_client, fake_provider):
    return TextIndexingService(
        session_factory=pg_session_factory,
        ai_provider=fake_provider,
        qdrant_client=qdrant_client,
        collection_name=TEXT_COLLECTION,
        initialize_schema=False,
    )


def test_text_indexing_creates_chunk_records(
    text_canonical, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        text_canonical, force_reindex=True
    )
    assert outcome.status == "indexed"
    assert outcome.chunk_count >= 1

    with pg_session_factory() as session:
        rows = list(session.scalars(
            select(TextChunkRecord).where(TextChunkRecord.content_hash == TEXT_CONTENT_HASH)
        ))
    assert len(rows) >= 1


def test_text_qdrant_points_carry_document_id(
    text_canonical, pg_session_factory, qdrant_client, fake_provider
):
    _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        text_canonical, force_reindex=True
    )
    results, _ = qdrant_client.scroll(
        collection_name=TEXT_COLLECTION,
        scroll_filter={
            "must": [{"key": "content_hash", "match": {"value": TEXT_CONTENT_HASH}}]
        },
        with_payload=True,
        limit=50,
    )
    assert results, "No Qdrant text points found"
    for point in results:
        assert point.payload.get("document_id"), (
            f"Missing document_id on point {point.id}"
        )
        assert point.payload["content_hash"] == TEXT_CONTENT_HASH


def test_dense_search_retrieves_indexed_chunk(
    text_canonical, pg_session_factory, qdrant_client, fake_provider
):
    _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        text_canonical, force_reindex=True
    )
    query_vec = fake_provider.embed_texts(["middle-income trap reforms"])[0]
    hits = search_text_chunks(
        qdrant_client,
        collection_name=TEXT_COLLECTION,
        query_vector=query_vec,
        top_k=5,
        content_hash_filter=TEXT_CONTENT_HASH,
    )
    assert hits, "Dense search returned no results"
    assert hits[0].content_hash == TEXT_CONTENT_HASH
    assert hits[0].document_id is not None
```

- [ ] **Step 2: Verify `search_text_chunks` signature**

Open `backend/src/docifer_backend/retrieval/vector_store.py` and confirm that `search_text_chunks` accepts `content_hash_filter` as a keyword arg. If the parameter name differs, adjust the test call.

- [ ] **Step 3: Run and confirm 3 passed**

```powershell
$env:RUN_INTEGRATION_TESTS="true"
$env:DOCIFER_TEST_DATABASE_URL="postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test"
$env:DOCIFER_TEST_QDRANT_URL="http://localhost:6333"
uv run --project backend pytest backend/tests/integration/test_text_indexing_integration.py -m integration -v --basetemp backend/.pytest_tmp
```

Expected: `3 passed`

- [ ] **Step 4: Commit**

```
git add backend/tests/integration/test_text_indexing_integration.py
git commit -m "test(integration): add text indexing integration tests with Phase 9 document_id regression check"
```

---

### Task 8: Table indexing integration tests

**Files:**
- Create: `backend/tests/integration/test_table_indexing_integration.py`

- [ ] **Step 1: Write table indexing tests**

Create `backend/tests/integration/test_table_indexing_integration.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select

from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.tables.indexing import (
    TableIndexingService,
    TABLE_INDEX_STATUS_INDEXED,
    TABLE_INDEX_STATUS_NO_EVIDENCE,
)
from docifer_backend.retrieval.tables.models import TableEvidenceRecord

from conftest import (
    TABLE_COLLECTION,
    TABLE_CONTENT_HASH,
    DOCLING_TABLE,
    DOCLING_TEXT,
    make_canonical_fixture,
)


pytestmark = pytest.mark.integration

_NO_TABLE_HASH = "9" * 63 + "0"


@pytest.fixture(scope="module")
def table_canonical(tmp_path_factory, pg_session_factory):
    tmp = tmp_path_factory.mktemp("table_doc")
    path = make_canonical_fixture(
        tmp, name="table_doc", content_hash=TABLE_CONTENT_HASH,
        docling_data=DOCLING_TABLE, table_count=1,
    )
    with pg_session_factory() as session:
        session.add(Document(
            filename="table_doc.pdf",
            source_path=str(tmp / "table_doc" / "table_doc.pdf"),
            content_hash=TABLE_CONTENT_HASH, file_size_bytes=100,
        ))
        session.commit()
    yield path
    with pg_session_factory() as session:
        doc = session.scalar(select(Document).where(Document.content_hash == TABLE_CONTENT_HASH))
        if doc:
            session.delete(doc); session.commit()


@pytest.fixture(scope="module")
def no_table_canonical(tmp_path_factory, pg_session_factory):
    tmp = tmp_path_factory.mktemp("no_table_doc")
    path = make_canonical_fixture(
        tmp, name="no_table_doc", content_hash=_NO_TABLE_HASH,
        docling_data=DOCLING_TEXT, table_count=0,
    )
    with pg_session_factory() as session:
        session.add(Document(
            filename="no_table_doc.pdf",
            source_path=str(tmp / "no_table_doc" / "no_table_doc.pdf"),
            content_hash=_NO_TABLE_HASH, file_size_bytes=100,
        ))
        session.commit()
    yield path
    with pg_session_factory() as session:
        doc = session.scalar(select(Document).where(Document.content_hash == _NO_TABLE_HASH))
        if doc:
            session.delete(doc); session.commit()


def _make_svc(pg_session_factory, qdrant_client, fake_provider):
    return TableIndexingService(
        session_factory=pg_session_factory,
        ai_provider=fake_provider,
        qdrant_client=qdrant_client,
        collection_name=TABLE_COLLECTION,
        initialize_schema=False,
    )


def test_table_indexing_creates_evidence_records(
    table_canonical, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        table_canonical, force_reindex=True
    )
    assert outcome.status == TABLE_INDEX_STATUS_INDEXED
    assert outcome.table_count >= 1

    with pg_session_factory() as session:
        rows = list(session.scalars(
            select(TableEvidenceRecord).where(
                TableEvidenceRecord.content_hash == TABLE_CONTENT_HASH
            )
        ))
    assert len(rows) >= 1


def test_table_qdrant_points_carry_document_id(
    table_canonical, pg_session_factory, qdrant_client, fake_provider
):
    _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        table_canonical, force_reindex=True
    )
    results, _ = qdrant_client.scroll(
        collection_name=TABLE_COLLECTION,
        scroll_filter={
            "must": [{"key": "content_hash", "match": {"value": TABLE_CONTENT_HASH}}]
        },
        with_payload=True, limit=50,
    )
    assert results
    for point in results:
        assert point.payload.get("document_id"), f"Missing document_id on table point {point.id}"


def test_table_zero_evidence_returns_no_evidence_status(
    no_table_canonical, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        no_table_canonical, force_reindex=True
    )
    assert outcome.status == TABLE_INDEX_STATUS_NO_EVIDENCE
    assert outcome.table_count == 0
```

- [ ] **Step 2: Run and confirm 3 passed**

```powershell
$env:RUN_INTEGRATION_TESTS="true"
$env:DOCIFER_TEST_DATABASE_URL="postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test"
$env:DOCIFER_TEST_QDRANT_URL="http://localhost:6333"
uv run --project backend pytest backend/tests/integration/test_table_indexing_integration.py -m integration -v --basetemp backend/.pytest_tmp
```

Expected: `3 passed`

- [ ] **Step 3: Commit**

```
git add backend/tests/integration/test_table_indexing_integration.py
git commit -m "test(integration): add table indexing integration tests including zero-evidence status"
```

---

### Task 9: Visual indexing integration tests

**Files:**
- Create: `backend/tests/integration/test_visual_indexing_integration.py`

- [ ] **Step 1: Write visual indexing tests**

Create `backend/tests/integration/test_visual_indexing_integration.py`:

```python
from __future__ import annotations
from pathlib import Path

import pytest
from sqlalchemy import select

from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.visuals.indexing import (
    VisualIndexingService,
    VISUAL_INDEX_STATUS_INDEXED,
)
from docifer_backend.retrieval.visuals.models import VisualEvidenceRecord

from conftest import (
    VISUAL_COLLECTION,
    VISUAL_CONTENT_HASH,
    DOCLING_VISUAL,
    make_canonical_fixture,
)


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def visual_canonical(tmp_path_factory, pg_session_factory):
    tmp = tmp_path_factory.mktemp("visual_doc")
    path = make_canonical_fixture(
        tmp, name="visual_doc", content_hash=VISUAL_CONTENT_HASH,
        docling_data=DOCLING_VISUAL, page_count=1, with_pdf=True,
    )
    with pg_session_factory() as session:
        session.add(Document(
            filename="visual_doc.pdf",
            source_path=str(tmp / "visual_doc" / "visual_doc.pdf"),
            content_hash=VISUAL_CONTENT_HASH, file_size_bytes=100,
        ))
        session.commit()
    yield path
    with pg_session_factory() as session:
        doc = session.scalar(select(Document).where(Document.content_hash == VISUAL_CONTENT_HASH))
        if doc:
            session.delete(doc); session.commit()


def _make_svc(pg_session_factory, qdrant_client, fake_provider):
    return VisualIndexingService(
        session_factory=pg_session_factory,
        ai_provider=fake_provider,
        qdrant_client=qdrant_client,
        collection_name=VISUAL_COLLECTION,
        initialize_schema=False,
    )


def test_visual_indexing_renders_and_upserts(
    visual_canonical, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        visual_canonical, force_reindex=True
    )
    assert outcome.status == VISUAL_INDEX_STATUS_INDEXED
    assert outcome.page_render_count == 1
    assert outcome.visual_record_count >= 1

    with pg_session_factory() as session:
        rows = list(session.scalars(
            select(VisualEvidenceRecord).where(
                VisualEvidenceRecord.content_hash == VISUAL_CONTENT_HASH
            )
        ))
    assert len(rows) >= 1


def test_visual_qdrant_points_carry_document_id(
    visual_canonical, pg_session_factory, qdrant_client, fake_provider
):
    _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        visual_canonical, force_reindex=True
    )
    results, _ = qdrant_client.scroll(
        collection_name=VISUAL_COLLECTION,
        scroll_filter={
            "must": [{"key": "content_hash", "match": {"value": VISUAL_CONTENT_HASH}}]
        },
        with_payload=True, limit=50,
    )
    assert results, "No visual Qdrant points found"
    for point in results:
        assert point.payload.get("document_id"), f"Missing document_id on visual point {point.id}"


def test_rendered_page_artifact_exists_on_disk(
    visual_canonical, pg_session_factory, qdrant_client, fake_provider
):
    _make_svc(pg_session_factory, qdrant_client, fake_provider).index_canonical_document(
        visual_canonical, force_reindex=True
    )
    with pg_session_factory() as session:
        rows = list(session.scalars(
            select(VisualEvidenceRecord).where(
                VisualEvidenceRecord.content_hash == VISUAL_CONTENT_HASH
            )
        ))
    render_rows = [r for r in rows if r.artifact_path and "page_" in r.artifact_path]
    assert render_rows, "No page render records with artifact_path"
    for row in render_rows:
        assert Path(row.artifact_path).exists(), f"Rendered page not found: {row.artifact_path}"
```

> **If pypdfium2 rejects the minimal PDF:** open `_make_tiny_pdf()` in conftest.py and print the bytes to verify xref offsets. Alternatively, copy a small real PDF from `datasets/raw_pdfs/` into the fixture `tmp` dir and point `source_path` at it — the test logic is identical.

- [ ] **Step 2: Run and confirm 3 passed**

```powershell
$env:RUN_INTEGRATION_TESTS="true"
$env:DOCIFER_TEST_DATABASE_URL="postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test"
$env:DOCIFER_TEST_QDRANT_URL="http://localhost:6333"
uv run --project backend pytest backend/tests/integration/test_visual_indexing_integration.py -m integration -v --basetemp backend/.pytest_tmp
```

Expected: `3 passed`

- [ ] **Step 3: Commit**

```
git add backend/tests/integration/test_visual_indexing_integration.py
git commit -m "test(integration): add visual indexing integration tests with real pypdfium2 render"
```

---

### Task 10: Query integration tests

**Files:**
- Create: `backend/tests/integration/test_query_integration.py`

- [ ] **Step 1: Write query tests**

`TextQueryService.query()` (verified at `query.py:179`) takes keyword args directly — no `QueryRequest` wrapper.

Signature:
```python
def query(
    self, *, question, scope="single", content_hash=None, doc_ids=None,
    document_ids=None, max_documents=5, max_evidence_per_document=3,
    top_k=4, retrieval_mode="dense", evidence_mode="text",
    table_top_k=4, visual_top_k=3, verify_citations=False,
    rerank=None, rerank_top_n=None,
) -> QueryOutcome
```

Create `backend/tests/integration/test_query_integration.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select

from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.indexing import TextIndexingService
from docifer_backend.retrieval.query import TextQueryService

from conftest import (
    TEXT_COLLECTION,
    QUERY_HASH_A,
    QUERY_HASH_B,
    QUERY_HASH_C,
    DOCLING_TEXT,
    make_canonical_fixture,
)


pytestmark = pytest.mark.integration

# Non-existent collection — table/visual retrieval returns empty without error
_EMPTY = "__integration_test_empty_collection__"


def _seed_and_index(base, content_hash, name, pg_sf, qdrant_client, fake_provider):
    canonical = make_canonical_fixture(
        base, name=name, content_hash=content_hash, docling_data=DOCLING_TEXT
    )
    with pg_sf() as session:
        session.add(Document(
            filename=f"{name}.pdf",
            source_path=str(base / name / f"{name}.pdf"),
            content_hash=content_hash,
            file_size_bytes=100,
        ))
        session.commit()
    TextIndexingService(
        session_factory=pg_sf,
        ai_provider=fake_provider,
        qdrant_client=qdrant_client,
        collection_name=TEXT_COLLECTION,
        initialize_schema=False,
    ).index_canonical_document(canonical, force_reindex=True)


@pytest.fixture(scope="module")
def three_indexed_docs(tmp_path_factory, pg_session_factory, qdrant_client, fake_provider):
    tmp = tmp_path_factory.mktemp("query_docs")
    _seed_and_index(tmp, QUERY_HASH_A, "qa", pg_session_factory, qdrant_client, fake_provider)
    _seed_and_index(tmp, QUERY_HASH_B, "qb", pg_session_factory, qdrant_client, fake_provider)
    _seed_and_index(tmp, QUERY_HASH_C, "qc", pg_session_factory, qdrant_client, fake_provider)
    yield
    for h in [QUERY_HASH_A, QUERY_HASH_B, QUERY_HASH_C]:
        with pg_session_factory() as session:
            doc = session.scalar(select(Document).where(Document.content_hash == h))
            if doc:
                session.delete(doc); session.commit()


def _make_svc(pg_session_factory, qdrant_client, fake_provider):
    return TextQueryService(
        session_factory=pg_session_factory,
        ai_provider=fake_provider,
        qdrant_client=qdrant_client,
        collection_name=TEXT_COLLECTION,
        table_collection_name=_EMPTY,
        visual_collection_name=_EMPTY,
    )


def test_single_doc_query_returns_answer(
    three_indexed_docs, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).query(
        question="What reforms do middle-income countries need?",
        content_hash=QUERY_HASH_A,
        top_k=3,
        retrieval_mode="dense",
        evidence_mode="text",
    )
    assert outcome.answer
    assert outcome.citations


def test_all_scope_query_searches_multiple_docs(
    three_indexed_docs, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).query(
        question="What reforms do middle-income countries need?",
        scope="all",
        top_k=4,
        retrieval_mode="dense",
        evidence_mode="text",
        max_documents=3,
        max_evidence_per_document=2,
    )
    assert outcome.debug.get("documents_searched_count", 0) >= 2
    assert outcome.answer


def test_query_evidence_carries_document_id(
    three_indexed_docs, pg_session_factory, qdrant_client, fake_provider
):
    outcome = _make_svc(pg_session_factory, qdrant_client, fake_provider).query(
        question="Institutional quality and human capital.",
        content_hash=QUERY_HASH_A,
        top_k=3,
        retrieval_mode="dense",
        evidence_mode="text",
    )
    for chunk in outcome.evidence:
        assert chunk.document_id, f"Evidence chunk missing document_id: {chunk.chunk_id}"
```

- [ ] **Step 3: Run and confirm 3 passed**

```powershell
$env:RUN_INTEGRATION_TESTS="true"
$env:DOCIFER_TEST_DATABASE_URL="postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test"
$env:DOCIFER_TEST_QDRANT_URL="http://localhost:6333"
uv run --project backend pytest backend/tests/integration/test_query_integration.py -m integration -v --basetemp backend/.pytest_tmp
```

Expected: `3 passed`

- [ ] **Step 4: Commit**

```
git add backend/tests/integration/test_query_integration.py
git commit -m "test(integration): add query integration tests for single-doc and all-scope modes"
```

---

### Task 11: Document registry integration tests

**Files:**
- Create: `backend/tests/integration/test_document_registry_integration.py`

- [ ] **Step 1: Write registry tests**

Create `backend/tests/integration/test_document_registry_integration.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select

from docifer_backend.documents.service import (
    DocumentRegistryService,
    DocumentRegistryNotFoundError,
)
from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.indexing import TextIndexingService

from conftest import (
    TEXT_COLLECTION,
    REGISTRY_HASH,
    DOCLING_TEXT,
    make_canonical_fixture,
)


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def registry_doc(tmp_path_factory, pg_session_factory, qdrant_client, fake_provider):
    tmp = tmp_path_factory.mktemp("registry_doc")
    canonical = make_canonical_fixture(
        tmp, name="registry_doc", content_hash=REGISTRY_HASH, docling_data=DOCLING_TEXT
    )
    with pg_session_factory() as session:
        session.add(Document(
            filename="registry_doc.pdf",
            source_path=str(tmp / "registry_doc" / "registry_doc.pdf"),
            content_hash=REGISTRY_HASH,
            file_size_bytes=100,
        ))
        session.commit()
    TextIndexingService(
        session_factory=pg_session_factory,
        ai_provider=fake_provider,
        qdrant_client=qdrant_client,
        collection_name=TEXT_COLLECTION,
        initialize_schema=False,
    ).index_canonical_document(canonical, force_reindex=True)
    yield
    with pg_session_factory() as session:
        doc = session.scalar(select(Document).where(Document.content_hash == REGISTRY_HASH))
        if doc:
            session.delete(doc); session.commit()


def _svc(pg_session_factory):
    return DocumentRegistryService(session_factory=pg_session_factory)


def test_list_documents_includes_seeded_doc(registry_doc, pg_session_factory):
    result = _svc(pg_session_factory).list_documents(limit=200)
    hashes = [d.content_hash for d in result.documents]
    assert REGISTRY_HASH in hashes


def test_get_by_content_hash_resolves_correct_doc(registry_doc, pg_session_factory):
    doc = _svc(pg_session_factory).get_by_content_hash(REGISTRY_HASH)
    assert doc.content_hash == REGISTRY_HASH
    assert doc.filename == "registry_doc.pdf"


def test_get_index_status_shows_text_indexed(registry_doc, pg_session_factory):
    svc = _svc(pg_session_factory)
    detail = svc.get_by_content_hash(REGISTRY_HASH)
    idx = svc.get_index_status(detail.document_id)
    assert idx.text.status == "indexed"
    assert idx.text.count >= 1


def test_get_by_content_hash_unknown_raises_not_found(pg_session_factory):
    with pytest.raises(DocumentRegistryNotFoundError):
        _svc(pg_session_factory).get_by_content_hash("0" * 64)


def test_list_documents_returns_valid_total(pg_session_factory):
    result = _svc(pg_session_factory).list_documents(limit=200)
    assert isinstance(result.total, int)
    assert result.total >= 0
```

> **Note:** Verify that `DocumentRegistryService` exposes `get_by_content_hash` and `get_index_status` — check `backend/src/docifer_backend/documents/service.py` for the actual method names and adjust if needed.

- [ ] **Step 2: Run and confirm 5 passed**

```powershell
$env:RUN_INTEGRATION_TESTS="true"
$env:DOCIFER_TEST_DATABASE_URL="postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test"
$env:DOCIFER_TEST_QDRANT_URL="http://localhost:6333"
uv run --project backend pytest backend/tests/integration/test_document_registry_integration.py -m integration -v --basetemp backend/.pytest_tmp
```

Expected: `5 passed`

- [ ] **Step 3: Commit**

```
git add backend/tests/integration/test_document_registry_integration.py
git commit -m "test(integration): add document registry integration tests protecting Phase 10 behavior"
```

---

### Task 12: FastAPI smoke tests

**Files:**
- Create: `backend/tests/integration/test_fastapi_smoke.py`

These tests monkeypatch module-level imported function references so the app uses the test Postgres and Qdrant for the duration of each test. Scope is `function` (not `module`) so cache state doesn't bleed across tests.

- [ ] **Step 1: Write FastAPI smoke tests**

Create `backend/tests/integration/test_fastapi_smoke.py`:

```python
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from docifer_backend.storage.database import Base


pytestmark = pytest.mark.integration


def _pg_url() -> str:
    return os.environ.get(
        "DOCIFER_TEST_DATABASE_URL",
        "postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test",
    )


def _qdrant_url() -> str:
    return os.environ.get("DOCIFER_TEST_QDRANT_URL", "http://localhost:6333")


@pytest.fixture
def real_app(monkeypatch):
    from qdrant_client import QdrantClient

    pg_url = _pg_url()
    assert "test" in pg_url, f"Refusing non-test DB: {pg_url}"

    engine = create_engine(pg_url, pool_pre_ping=True)
    import docifer_backend.ingestion.models  # noqa: F401
    import docifer_backend.retrieval.models  # noqa: F401
    import docifer_backend.retrieval.tables.models  # noqa: F401
    import docifer_backend.retrieval.visuals.models  # noqa: F401
    import docifer_backend.audit.models  # noqa: F401
    Base.metadata.create_all(engine)

    test_sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    test_qdrant = QdrantClient(url=_qdrant_url())

    # Patch each module's imported reference — module-level import means
    # patching the source module alone is insufficient.
    monkeypatch.setattr(
        "docifer_backend.documents.service.get_session_factory", lambda: test_sf
    )
    monkeypatch.setattr(
        "docifer_backend.storage.database.get_session_factory", lambda: test_sf
    )
    monkeypatch.setattr(
        "docifer_backend.storage.qdrant.get_qdrant_client", lambda: test_qdrant
    )
    monkeypatch.setattr(
        "docifer_backend.storage.database.check_database_connection", lambda: True
    )

    from docifer_backend.main import create_app
    app = create_app()
    yield TestClient(app)
    engine.dispose()


def test_health_returns_ok(real_app):
    resp = real_app.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_ready_reports_postgres_ok(real_app):
    resp = real_app.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["checks"]["postgres"] == "ok"


def test_list_documents_returns_200(real_app):
    resp = real_app.get("/documents?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert "documents" in body
    assert "total" in body


def test_vector_collections_returns_list(real_app):
    resp = real_app.get("/vector/collections")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```

- [ ] **Step 2: Run and confirm 4 passed**

```powershell
$env:RUN_INTEGRATION_TESTS="true"
$env:DOCIFER_TEST_DATABASE_URL="postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test"
$env:DOCIFER_TEST_QDRANT_URL="http://localhost:6333"
uv run --project backend pytest backend/tests/integration/test_fastapi_smoke.py -m integration -v --basetemp backend/.pytest_tmp
```

Expected: `4 passed`

- [ ] **Step 3: Commit**

```
git add backend/tests/integration/test_fastapi_smoke.py
git commit -m "test(integration): add FastAPI smoke tests against real infrastructure"
```

---

### Task 13: Full validation + docs

**Files:**
- Create: `docs/phase11-real-integration-tests.md`
- Modify: `backend/README.md`

- [ ] **Step 1: Run full unit suite — confirm no regressions**

```powershell
uv run --project backend pytest backend/tests --basetemp backend/.pytest_tmp -q
```

Expected: `134 passed, 1 xfailed` (integration tests auto-skipped, no regressions)

- [ ] **Step 2: Run full integration suite**

```powershell
$env:RUN_INTEGRATION_TESTS="true"
$env:DOCIFER_TEST_DATABASE_URL="postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test"
$env:DOCIFER_TEST_QDRANT_URL="http://localhost:6333"
$env:DOCIFER_TEST_QDRANT_COLLECTION_PREFIX="test_docifer_"
uv run --project backend pytest backend/tests/integration -m integration -v --basetemp backend/.pytest_tmp
```

Expected: all integration tests passed

- [ ] **Step 3: Compile check**

```powershell
uv run --project backend python -m compileall -q backend/src backend/tests
```

Expected: no output (no errors)

- [ ] **Step 4: Create docs/phase11-real-integration-tests.md**

Use the spec sections as the base. Add a Validation section at the end with the actual test counts from Step 2.

- [ ] **Step 5: Append integration test section to backend/README.md**

```markdown
## Integration tests

Integration tests require real Postgres and Qdrant services and are skipped by default.

Start local services:

```powershell
docker start docifer-postgres docifer-qdrant
```

Run integration suite:

```powershell
$env:RUN_INTEGRATION_TESTS="true"
$env:DOCIFER_TEST_DATABASE_URL="postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test"
$env:DOCIFER_TEST_QDRANT_URL="http://localhost:6333"
$env:DOCIFER_TEST_QDRANT_COLLECTION_PREFIX="test_docifer_"
uv run --project backend pytest backend/tests/integration -m integration -v --basetemp backend/.pytest_tmp
```

Integration tests use:
- Dedicated `docifer_test` database — refuses any URL not containing `"test"`
- Qdrant collections prefixed `test_docifer_` — cleaned before and after each module
- Fake deterministic embeddings (dim=16) — no OpenAI calls
- Synthetic canonical fixtures in `tmp_path` — no real PDF parsing
- A real 1-page PDF rendered by pypdfium2 for visual indexing tests only
```

- [ ] **Step 6: Commit**

```
git add docs/phase11-real-integration-tests.md backend/README.md
git commit -m "docs(phase11): add integration test documentation and README section"
```

---

## Success Criteria

| Check | Expected |
|---|---|
| Unit suite | 134 passed, 1 xfailed |
| Integration suite | all passed |
| Compile check | clean |
| Real Postgres schema created | ✓ |
| Real Qdrant collections created with payload indexes | ✓ |
| Text points carry `document_id` | ✓ (Phase 9 regression guard) |
| Table zero-evidence returns `no_table_evidence` status | ✓ (Phase 10 modality status guard) |
| Visual page rendered to disk by real pypdfium2 | ✓ |
| No real OpenAI calls in any integration test | ✓ |
| No writes to `docifer_text_chunks` / `docifer_table_evidence` / `docifer_visual_evidence` | ✓ (prefix guard) |
