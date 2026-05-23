# Phase 11 — Real Postgres/Qdrant Integration Tests

## Goal

Replace all remaining test-layer mocks with integration tests that run against real Postgres and Qdrant services. Existing unit tests are unchanged and remain fast. The integration suite is opt-in and skipped by default.

## Architecture

Tests live in `backend/tests/integration/` as a self-contained package.

```
backend/tests/integration/
  __init__.py
  conftest.py                          # skip guard, fixtures, fake provider
  test_postgres_schema.py              # Task 5 — ORM table existence
  test_qdrant_collections.py           # Task 6 — Qdrant collection lifecycle
  test_text_indexing_integration.py    # Task 7 — TextIndexingService
  test_table_indexing_integration.py   # Task 8 — TableIndexingService
  test_visual_indexing_integration.py  # Task 9 — VisualIndexingService
  test_query_integration.py            # Task 10 — TextQueryService
  test_document_registry_integration.py # Task 11 — DocumentRegistryService
  test_fastapi_smoke.py               # Task 12 — FastAPI HTTP routes
```

### Key design decisions

**No OpenAI calls.** `FakeIntegrationProvider` uses SHA-256-seeded 16-dimensional deterministic embeddings. All embedding, grounding, and visual interpretation calls go through the fake.

**No lru_cache pollution.** All services accept injected `session_factory` and `qdrant_client` directly. Cached globals are never called.

**Safe against production databases.** The Postgres fixture asserts `"test" in url` before any `DROP TABLE`. The Qdrant fixture uses a `test_docifer_` collection prefix and deletes all test collections on teardown.

**Real pypdfium2 rendering.** Visual indexing tests use `with_pdf=True` in `make_canonical_fixture`, which writes a valid minimal PDF constructed with dynamically computed xref offsets. This lets pypdfium2 render actual page rasters.

**Canonical fixtures are fully in-memory.** All paths are written as absolute paths via `tmp_path`. No static JSON files on disk.

**FastAPI smoke tests monkeypatch the service layer.** Route smoke tests patch `DocumentRegistryService` in `docifer.api.documents` and dependency check functions in `docifer.api.health` — they test the HTTP routing layer, not the service layer.

## Environment variables

| Variable | Default |
|----------|---------|
| `RUN_INTEGRATION_TESTS` | *(unset — tests are skipped)* |
| `DOCIFER_TEST_DATABASE_URL` | `postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test` |
| `DOCIFER_TEST_QDRANT_URL` | `http://localhost:6333` |
| `DOCIFER_TEST_QDRANT_COLLECTION_PREFIX` | `test_docifer_` |

## Running the tests

```powershell
$env:RUN_INTEGRATION_TESTS = "true"
backend\.venv\Scripts\pytest.exe backend\tests\integration -v
```

Run a single module:

```powershell
$env:RUN_INTEGRATION_TESTS = "true"
backend\.venv\Scripts\pytest.exe backend\tests\integration\test_text_indexing_integration.py -v
```

Run only integration-marked tests across the full suite:

```powershell
$env:RUN_INTEGRATION_TESTS = "true"
backend\.venv\Scripts\pytest.exe backend\tests -m integration -v
```

## Test coverage summary

### test_postgres_schema.py

- All six ORM tables exist: `documents`, `ingestion_jobs`, `text_chunks`, `table_evidence_records`, `visual_evidence_records`, `parse_quality_audits`
- Document insert, select, and delete round-trip

### test_qdrant_collections.py

- Text and table collections can be created
- Collection stats return correct vector size and status
- Payload indexes are registered for text collection
- Non-existent collection stats raise `KeyError`

### test_text_indexing_integration.py

- `TextIndexingService.index_canonical_document` creates `TextChunkRecord` rows in Postgres
- Qdrant text points carry `document_id` and `content_hash` payloads
- Dense search via `search_text_chunks` retrieves indexed chunks filtered by `content_hash`

### test_table_indexing_integration.py

- `TableIndexingService.index_canonical_document` creates `TableEvidenceRecord` rows in Postgres
- Qdrant table points carry `document_id` payload
- Documents with zero tables return `TABLE_INDEX_STATUS_NO_EVIDENCE` and `table_count=0`

### test_visual_indexing_integration.py

- `VisualIndexingService.index_canonical_document` creates `VisualEvidenceRecord` rows via page render extraction (requires real PDF, uses pypdfium2)
- Qdrant visual points carry `document_id` payload
- Documents with zero pages return `VISUAL_INDEX_STATUS_NO_EVIDENCE` and `visual_record_count=0`

### test_query_integration.py

- End-to-end: index text chunks → query via `TextQueryService` → non-empty answer string
- `scope="single"` with `content_hash` filter: all retrieved evidence matches the expected `content_hash`

### test_document_registry_integration.py

- `list_documents()` includes seeded documents
- `get_document(document_id)` returns correct metadata
- `get_by_content_hash(content_hash)` resolves to the correct document
- `get_indexes(document_id)` returns `DocumentIndexStatusResponse` with correct fields
- Unknown content hash raises an exception

### test_fastapi_smoke.py

- `GET /health` → 200, `{"status": "ok"}`
- `GET /ready` → 200, `{"status": "ready"}` (monkeypatched dependency checks)
- `GET /documents` → 200, response contains `documents` and `total` fields
- `GET /documents/{id}` → 200, response contains `document_id` and `content_hash`
- `GET /documents/{unknown_id}` → 404
- `GET /documents/{id}/indexes` → 200, response contains `document_id`

## Known limitations

- Visual integration tests require a functional `pypdfium2` installation. Environments without a display server still work; pypdfium2 renders headlessly.
- Query integration tests do not test table or visual retrieval paths — those are covered in the dedicated indexing tests.
- The `test_fastapi_smoke.py` tests do not exercise real database state; they verify HTTP routing and error mapping only.

## Commit history

| Commit | Description |
|--------|-------------|
| `e309bd2` | pytest marker + integration package skeleton |
| `7170fb8` | conftest.py — skip guard, Postgres+Qdrant fixtures, FakeIntegrationProvider, canonical fixture factory |
| `6eb7de7` | Postgres schema and Qdrant indexing tests (Tasks 5–8) |
| `64d27c3` | Visual, query, registry, and FastAPI smoke tests (Tasks 9–12) |
