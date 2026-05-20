# Session Changes - 2026-05-20

This file summarizes the changes made during the Docifer Phase 3 and Phase 4 execution session.

## Summary

Implemented and validated:

- **Phase 3 - Document Ingestion**
- **Phase 4 - Text RAG Baseline**

The project now has a working ingestion pipeline that can:

- register PDFs as documents,
- track ingestion jobs in PostgreSQL,
- parse PDFs with Docling,
- write inspectable canonical artifacts,
- record parse failures,
- retry bounded failures,
- avoid duplicate parsing of already ingested PDFs,
- expose ingestion through both CLI and FastAPI.

## Committed Change Set

Committed as:

```text
5d20231 Implement phase 3 document ingestion
```

## Backend Dependencies

Updated `backend/pyproject.toml`:

- Added runtime dependency:
  - `docling>=2.94.0`
- Added dev dependency group:
  - `pytest>=9.0.3`

`docling` and `pytest` were installed into the backend virtual environment using `uv`.

## Ingestion Data Model

Added SQLAlchemy models in:

```text
backend/src/docifer_backend/ingestion/models.py
```

New tables:

- `documents`
- `ingestion_jobs`
- `document_index_runs`

Important behaviors:

- Documents are keyed by SHA-256 content hash.
- Ingestion jobs track source path, status, parser metadata, attempts, artifact path, timestamps, and structured errors.
- `document_index_runs` includes a uniqueness constraint to prevent accidental duplicate indexing in later phases.

## Ingestion Status Lifecycle

Added stable ingestion statuses in:

```text
backend/src/docifer_backend/ingestion/status.py
```

Statuses:

- `queued`
- `parsing`
- `parsed`
- `indexing`
- `indexed`
- `failed`

## File Inspection

Added PDF inspection and hashing in:

```text
backend/src/docifer_backend/ingestion/file_info.py
```

This validates that the source path exists, is a file, is a `.pdf`, and computes:

- filename,
- absolute source path,
- SHA-256 content hash,
- file size.

## Docling Parser Wrapper

Added parser abstraction in:

```text
backend/src/docifer_backend/ingestion/parser.py
```

This wraps Docling behind Docifer-owned types so future ingestion/retrieval code does not depend directly on Docling internals.

The parser exports:

- raw Docling JSON,
- Markdown rendering,
- parser name,
- parser version,
- Docling status,
- page count,
- table count,
- figure count,
- parse errors.

## Ingestion Service

Added the main ingestion workflow in:

```text
backend/src/docifer_backend/ingestion/service.py
```

Implemented:

- document creation/reuse by content hash,
- ingestion job creation,
- status transitions,
- bounded retries,
- failure recording,
- canonical artifact writing,
- idempotent reuse of existing successful parses.

Generated artifact layout:

```text
datasets/processed/<hash-prefix>/<job-id>/
  canonical.json
  docling.json
  document.md
  parse_summary.json
```

## Canonical Output

The canonical JSON schema currently includes:

- schema version,
- document metadata,
- ingestion job metadata,
- parser metadata,
- artifact paths,
- page list,
- Markdown character count,
- table and figure counts,
- parse status and errors.

Validated canonical output:

```text
datasets/processed/8109582811fe/55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff/canonical.json
```

## API Endpoints

Added ingestion API routes in:

```text
backend/src/docifer_backend/api/ingestion.py
backend/src/docifer_backend/schemas/ingestion.py
```

Registered the router in:

```text
backend/src/docifer_backend/main.py
```

New endpoints:

- `POST /ingestion/jobs`
- `GET /ingestion/jobs/{job_id}`

Example request:

```json
{
  "source_path": "datasets/raw_pdfs/Worldbank2024.pdf",
  "force_reprocess": false
}
```

Validated response:

```json
{
  "job_id": "55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff",
  "document_id": "30abbd45-a8d4-4585-82a7-326c7ab76786",
  "status": "parsed",
  "artifact_path": "datasets/processed/8109582811fe/55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff/canonical.json",
  "reused_existing": true,
  "error_message": null
}
```

## CLI

Added a local ingestion CLI:

```text
backend/src/docifer_backend/ingestion/cli.py
```

Usage:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.ingestion.cli datasets\raw_pdfs\Worldbank2024.pdf
```

Use `--force` to force a fresh parse instead of reusing an existing successful job.

## Database Utilities

Expanded:

```text
backend/src/docifer_backend/storage/database.py
```

Added:

- SQLAlchemy declarative base,
- session factory,
- `session_scope`,
- local schema creation helper.

## Path Utilities

Added:

```text
backend/src/docifer_backend/config/paths.py
```

This centralizes project-root-relative path resolution and display paths for artifacts.

## Tests

Added ingestion tests:

```text
backend/tests/test_ingestion_service.py
```

Covered:

- successful ingestion creates a parsed job and canonical artifact,
- rerunning the same PDF reuses the existing parsed job,
- parser failures are retried and persisted as `failed`,
- duplicate index runs are blocked by a database uniqueness constraint.

Validated result:

```text
4 passed
```

## Documentation

Updated:

```text
backend/README.md
```

Added:

- Phase 3 ingestion usage,
- API endpoint list,
- sample request body,
- test command.

Added:

```text
docs/phase3-ingestion.md
```

Documents:

- implemented Phase 3 components,
- first validated PDF,
- artifact path,
- parse counts,
- first-run Docling/RapidOCR model download note.

## Local Runtime Changes

Copied the starter PDFs from:

```text
dataPDFS/
```

into the canonical raw PDF folder:

```text
datasets/raw_pdfs/
```

These files are ignored by git through the existing `.gitignore`.

Started local Docker services:

```text
postgres
qdrant
```

Validated readiness:

```json
{
  "status": "ready",
  "checks": {
    "postgres": "ok",
    "qdrant": "ok"
  }
}
```

## Real PDF Validation

Validated ingestion on:

```text
datasets/raw_pdfs/Worldbank2024.pdf
```

Successful job:

```text
55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff
```

Document ID:

```text
30abbd45-a8d4-4585-82a7-326c7ab76786
```

Content hash:

```text
8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8
```

Parsed artifact summary:

- 4 pages
- 1 table
- 3 figures
- Docling status `success`
- no parse errors

## Failure Path Observed

The first real Docling attempt failed inside the sandbox because Python could not read a package schema file from the virtual environment.

That failure was persisted as an ingestion job with:

- status `failed`,
- attempt count `2`,
- structured error message.

The approved real run succeeded afterward. This incident also validated that Phase 3 records parser failures instead of hiding them.

## Verification Commands Run

```powershell
backend\.venv\Scripts\pytest.exe backend\tests
```

```powershell
backend\.venv\Scripts\python.exe -m compileall -q backend\src backend\tests
```

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.ingestion.cli datasets\raw_pdfs\Worldbank2024.pdf
```

```powershell
backend\.venv\Scripts\python.exe -c "from docifer_backend.main import app; from fastapi.testclient import TestClient; c=TestClient(app); print(c.get('/health').json()); r=c.get('/ready'); print(r.status_code, r.json())"
```

## Phase 3 Gate Status

Phase 3 is considered complete and valid.

Satisfied:

- PDFs are in the canonical dataset location.
- Each PDF can receive a stable document record keyed by content hash.
- PostgreSQL stores ingestion jobs and status transitions.
- Failures are recorded with useful error details.
- Re-running the same PDF is idempotent.
- Duplicate indexing protection exists for future indexing phases.
- Docling parsed one real PDF successfully.
- Canonical JSON output is saved and inspectable.
- Tests validate the core ingestion behavior.

Phase 3 unlocked the next phase:

```text
Phase 4 - Text RAG Baseline
```

---

# Phase 4 Changes - Text RAG Baseline

Phase 4 added the first answerable text-only RAG path over parsed Docifer artifacts.

## Phase 4 Backend Dependencies

Updated:

```text
backend/pyproject.toml
```

Added runtime dependency:

```text
openai>=2.37.0
```

The OpenAI Python SDK was installed into the backend virtual environment using `uv`.

## Phase 4 Configuration

Updated:

```text
backend/src/docifer_backend/config/settings.py
.env.example
```

Added:

```text
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_ANSWER_MODEL=gpt-5.4-mini
QDRANT_TEXT_COLLECTION=docifer_text_chunks
```

The real `OPENAI_API_KEY` remains in `.env` and was not committed.

## Provider Layer

Added:

```text
backend/src/docifer_backend/providers/base.py
backend/src/docifer_backend/providers/factory.py
backend/src/docifer_backend/providers/openai_provider.py
```

Implemented:

- provider protocol for embeddings and grounded answer generation,
- OpenAI-backed embeddings,
- OpenAI-backed baseline answer generation through the Responses API,
- provider factory keyed by `LLM_PROVIDER`.

The OpenAI SDK import is lazy so tests with fake providers do not require importing or calling OpenAI.

## Text Chunking

Added:

```text
backend/src/docifer_backend/retrieval/chunking.py
```

Implemented:

- chunk creation from Docling text blocks,
- skip logic for repeated page headers and footers,
- text normalization,
- chunk IDs based on document content hash,
- stable UUID point IDs for Qdrant,
- page range metadata per chunk,
- source PDF and canonical artifact metadata.

For the validated World Bank artifact, Phase 4 produced:

```text
5 text chunks
```

## Text Chunk Metadata Table

Added:

```text
backend/src/docifer_backend/retrieval/models.py
```

New table:

```text
text_chunks
```

Tracked per chunk:

- document ID,
- content hash,
- chunk ID,
- chunk index,
- text,
- page start and page end,
- source PDF path,
- canonical artifact path,
- Qdrant point ID.

Also updated:

```text
backend/src/docifer_backend/storage/database.py
```

so retrieval models are registered during local schema creation.

## Qdrant Vector Store

Added:

```text
backend/src/docifer_backend/retrieval/vector_store.py
```

Implemented:

- Qdrant collection creation,
- dense vector upsert,
- text chunk payload storage,
- top-k vector search,
- optional content-hash filtering.

Collection used:

```text
docifer_text_chunks
```

## Text Indexing Service

Added:

```text
backend/src/docifer_backend/retrieval/indexing.py
```

Implemented:

- canonical artifact indexing,
- OpenAI embedding calls for chunks,
- Qdrant upsert,
- Postgres `text_chunks` persistence,
- `document_index_runs` status tracking,
- idempotent reuse of already indexed documents.

Validated index response:

```json
{
  "document_id": "30abbd45-a8d4-4585-82a7-326c7ab76786",
  "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
  "status": "indexed",
  "chunk_count": 5,
  "collection_name": "docifer_text_chunks",
  "reused_existing": true
}
```

## Text Query Service

Added:

```text
backend/src/docifer_backend/retrieval/query.py
```

Implemented:

- question embedding,
- top-k retrieval from Qdrant,
- optional content-hash filtering,
- grounded evidence formatting,
- baseline answer generation,
- citation objects,
- debug metadata.

Validated question:

```text
What do middle-income countries need to do to escape the middle-income trap?
```

Validated behavior:

- retrieved 3 chunks,
- generated a grounded answer,
- returned citations with chunk IDs, page metadata, retrieval scores, source PDF path, and canonical artifact path.

## API Endpoints

Added:

```text
backend/src/docifer_backend/api/retrieval.py
backend/src/docifer_backend/schemas/retrieval.py
```

Updated:

```text
backend/src/docifer_backend/main.py
backend/README.md
```

New endpoints:

```text
POST /index/text
POST /query
```

Example indexing request:

```json
{
  "canonical_path": "datasets/processed/8109582811fe/55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff/canonical.json",
  "force_reindex": false
}
```

Example query request:

```json
{
  "question": "What do middle-income countries need to do to escape the middle-income trap?",
  "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
  "top_k": 3
}
```

## Phase 4 Tests

Added:

```text
backend/tests/test_text_retrieval.py
```

Covered:

- chunking preserves page metadata,
- text indexing is idempotent,
- query returns answer, citations, evidence, and debug metadata.

Tests use:

- fake embeddings,
- fake grounded answer generation,
- in-memory Qdrant,
- in-memory SQLite.

## Phase 4 Documentation

Added:

```text
docs/phase4-text-rag.md
```

Updated:

```text
backend/README.md
```

Documented:

- configuration,
- indexing endpoint,
- query endpoint,
- validated artifact paths,
- validation commands,
- Phase 4 gate status.

## Phase 4 Validation

Commands run:

```powershell
backend\.venv\Scripts\pytest.exe backend\tests
```

Result:

```text
7 passed
```

Compile check:

```powershell
backend\.venv\Scripts\python.exe -m compileall -q backend\src backend\tests
```

Readiness check:

```json
{
  "status": "ready",
  "checks": {
    "postgres": "ok",
    "qdrant": "ok"
  }
}
```

Real OpenAI-backed validation was run for:

- text indexing,
- query embedding,
- answer generation,
- FastAPI `/index/text`,
- FastAPI `/query`.

## Phase 4 Gate Status

Phase 4 text baseline is valid for the first ingested document.

Satisfied:

- text chunks are created from parsed Docling output,
- document and page metadata are preserved,
- OpenAI embeddings are generated,
- chunks are stored in Qdrant,
- chunk metadata is persisted in Postgres,
- indexing is idempotent,
- `/query` retrieves evidence and returns a cited answer,
- tests cover the core baseline behavior.

Phase 4 is not yet committed.

Current uncommitted Phase 4 files include:

```text
.env.example
backend/README.md
backend/pyproject.toml
backend/src/docifer_backend/config/settings.py
backend/src/docifer_backend/main.py
backend/src/docifer_backend/storage/database.py
backend/src/docifer_backend/api/retrieval.py
backend/src/docifer_backend/providers/base.py
backend/src/docifer_backend/providers/factory.py
backend/src/docifer_backend/providers/openai_provider.py
backend/src/docifer_backend/retrieval/chunking.py
backend/src/docifer_backend/retrieval/indexing.py
backend/src/docifer_backend/retrieval/models.py
backend/src/docifer_backend/retrieval/query.py
backend/src/docifer_backend/retrieval/vector_store.py
backend/src/docifer_backend/schemas/retrieval.py
backend/tests/test_text_retrieval.py
docs/phase4-text-rag.md
docs/session-changes-2026-05-20.md
```

Next phase remains locked until explicitly started:

```text
Phase 5 - Evaluation v1 and Early LangSmith
```
