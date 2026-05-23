# Session Changes — 2026-05-23

## Summary

Completed Phase 10 (document registry APIs) commit and implemented Phase 11 (real Postgres/Qdrant integration tests) end-to-end, including debug and green run.

---

## Phase 10 commit (620b2a6)

Phase 10 code was already written but uncommitted. Staged and committed:

- `backend/src/docifer_backend/api/documents.py` — 7 REST endpoints for document registry
- `backend/src/docifer_backend/documents/service.py` — `DocumentRegistryService` with `list_documents`, `get_document`, `get_by_content_hash`, `get_indexes`, `get_audit`, `get_artifacts`
- `backend/src/docifer_backend/schemas/documents.py` — Pydantic response models
- `backend/tests/test_document_registry_api.py` — unit tests for HTTP layer
- `backend/tests/test_document_registry_service.py` — unit tests for service layer
- `docs/phase10-document-registry-apis.md` — phase notes

Backend suite at Phase 10 commit: **134 passed, 1 xfailed**

---

## Phase 11 — Real Postgres/Qdrant Integration Tests

**Goal:** Replace all test-layer mocks with opt-in tests that run against real Postgres and Qdrant services. Existing unit tests unchanged.

### Architecture

Tests live in `backend/tests/integration/`. Skipped by default; opt-in via `RUN_INTEGRATION_TESTS=true`.

Key design decisions:
- `FakeIntegrationProvider` — SHA-256-seeded 16-dim deterministic embeddings, no real OpenAI calls
- All services injected directly (`session_factory`, `qdrant_client`) — no lru_cache globals touched
- `helpers.py` — shared constants, fixture data, `make_canonical_fixture`, `make_tiny_pdf` (real pypdfium2-renderable PDF with dynamically computed xref offsets)
- Safety guard: `assert "test" in url` before any `drop_all/create_all`
- Collection prefix `test_docifer_` — never pollutes dev collections

### Test modules (34 tests total)

| Module | Tests | Result |
|--------|-------|--------|
| `test_postgres_schema.py` | 7 | ✅ pass |
| `test_qdrant_collections.py` | 5 | ✅ pass |
| `test_text_indexing_integration.py` | 3 | ✅ pass |
| `test_table_indexing_integration.py` | 3 | ✅ pass |
| `test_visual_indexing_integration.py` | 3 | ✅ pass |
| `test_query_integration.py` | 2 | ✅ pass |
| `test_document_registry_integration.py` | 5 | ✅ pass |
| `test_fastapi_smoke.py` | 6 | ✅ pass |

**Final result: 34/34 passed**

### Bugs found and fixed during test run

| Bug | Fix |
|-----|-----|
| `from conftest import ...` resolved to root `backend/conftest.py` (pre-cached in `sys.modules`) | Extracted constants to `helpers.py`; added `tests/integration` to `pythonpath` |
| `TableIndexOutcome.table_count` — wrong attribute | Corrected to `table_evidence_count` |
| FK violation on fixture teardown (Document deleted before child records) | Wrapped teardown deletes in try/except; `pg_engine.drop_all` handles cleanup at module end |
| `search_text_chunks` kwarg was `content_hash_filter` in plan — actual kwarg is `content_hash` | Fixed before first commit |

### Commits

| Commit | Description |
|--------|-------------|
| `e309bd2` | pytest marker + integration package skeleton |
| `7170fb8` | conftest.py — skip guard, Postgres+Qdrant fixtures, FakeIntegrationProvider, canonical fixture factory |
| `6eb7de7` | Postgres schema and Qdrant indexing tests (Tasks 5–8) |
| `64d27c3` | Visual, query, registry, and FastAPI smoke tests (Tasks 9–12) |
| `b8f1675` | Phase 11 docs and README section |
| `97965c4` | Fix import collision, FK teardown errors, table_count attribute |

### Infrastructure setup

Postgres running in Docker (`docifer-postgres`, `postgres:17`). Created test user and DB:

```powershell
docker exec docifer-postgres psql -U docifer_user -d docifer -c "CREATE USER docifer WITH PASSWORD 'docifer';"
docker exec docifer-postgres psql -U docifer_user -d docifer -c "CREATE DATABASE docifer_test OWNER docifer;"
docker exec docifer-postgres psql -U docifer_user -d docifer -c "GRANT ALL PRIVILEGES ON DATABASE docifer_test TO docifer;"
```

Qdrant running in Docker (`docifer-qdrant`, `qdrant/qdrant:latest`, port 6333).

### Environment variables for integration tests

```powershell
$env:RUN_INTEGRATION_TESTS = "true"
# Optionally override defaults:
$env:DOCIFER_TEST_DATABASE_URL = "postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test"
$env:DOCIFER_TEST_QDRANT_URL = "http://localhost:6333"
```

---

## Status after session

- Phases 1–11: **Complete**
- Phase 12 (Final Ablation and Benchmark Report): **Next**
- Phase 13 (Frontend MVP and Portfolio Packaging): **Final**
