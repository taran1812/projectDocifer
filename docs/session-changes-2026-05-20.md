# Session Changes - 2026-05-20

This file summarizes the changes made during the Docifer Phase 3 and Phase 4 execution session.

## Summary

Implemented and validated:

- **Phase 3 - Document Ingestion**
- **Phase 4 - Text RAG Baseline**
- **Phase 5 - Evaluation v1 and Early LangSmith**
- **Phase 6 - Retrieval Quality Upgrades and Citation Grounding**

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

## Phase 4 Commit

Committed as:

```text
bd3f6d5 Implement phase 4 text RAG baseline
```

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

Phase 4 is committed.

Phase 4 unlocked the next phase:

```text
Phase 5 - Evaluation v1 and Early LangSmith
```

---

# Phase 5 Changes - Evaluation v1 and Early LangSmith

Phase 5 added a repeatable measurement harness for the current text RAG baseline. This phase measures the baseline without changing retrieval behavior.

## Phase 5 Backend Dependencies

Updated:

```text
backend/pyproject.toml
```

Added runtime dependency:

```text
langsmith>=0.8.5
```

The LangSmith Python SDK was installed into the backend virtual environment using `uv`.

## Phase 5 Configuration

Updated:

```text
backend/src/docifer_backend/config/settings.py
.env.example
```

Added:

```text
GOLDEN_EVAL_PATH=docifer_phase1_corpus_and_golden_eval_v1.xlsx
EVAL_RUNS_DIR=evals/runs
```

Verified existing key configuration:

```text
OPENAI_API_KEY present: true
LANGSMITH_API_KEY present: true
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=docifer-dev
```

## Golden Dataset Loader

Added:

```text
backend/src/docifer_backend/evaluation/dataset.py
```

Implemented:

- loader for the `QA Evaluation Template` sheet,
- loader for the `Starter Corpus` sheet,
- typed `GoldenQuestion` records,
- typed `CorpusDocument` records,
- parsing for abstention flags and optional fields.

Validated workbook:

```text
docifer_phase1_corpus_and_golden_eval_v1.xlsx
```

Current seeded QA count:

```text
40 questions
```

Distribution:

- Text Factual: 14
- Text Synthesis: 6
- Table Lookup: 5
- Table Reasoning: 4
- Chart / Visual: 5
- Mixed Modality: 2
- Unsupported / Abstention: 4

## Document Registry

Added:

```text
backend/src/docifer_backend/evaluation/registry.py
```

Implemented:

- DOC ID to local PDF filename mapping,
- lookup of ingested documents in Postgres,
- lookup of indexed text chunk counts,
- explicit indexed/unindexed status for each document.

This lets the eval runner distinguish actual failures from documents that have not been indexed yet.

## Custom Metrics

Added:

```text
backend/src/docifer_backend/evaluation/metrics.py
```

Implemented baseline metrics:

- answer present,
- citation count,
- citation presence,
- retrieved evidence count,
- expected-answer token recall,
- expected-answer string similarity,
- abstention detection,
- abstention correctness where applicable,
- top retrieval score.

These are deterministic local metrics. RAGAS-style scoring is prepared through export but not treated as the source of truth yet.

## LangSmith Trace Wrapper

Added:

```text
backend/src/docifer_backend/observability/langsmith.py
```

Implemented:

- LangSmith trace context for evaluated questions,
- project selection from settings,
- tags and metadata for Phase 5 eval runs,
- no-op behavior when tracing is disabled.

Evaluated questions are traced when:

```text
LANGSMITH_TRACING=true
LANGSMITH_API_KEY is set
```

## Evaluation Reporting

Added:

```text
backend/src/docifer_backend/evaluation/reporting.py
```

Implemented writers for:

```text
results.jsonl
summary.json
report.md
ragas_input.jsonl
```

The `ragas_input.jsonl` export includes question, answer, retrieved contexts, and ground truth for later RAGAS scoring.

## Evaluation Runner

Added:

```text
backend/src/docifer_backend/evaluation/runner.py
```

Implemented CLI:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase5_current_indexed_baseline --top-k 3
```

Supported options:

- `--run-name`
- `--doc-id`
- `--limit`
- `--top-k`
- `--no-trace`
- `--dataset`
- `--output-root`

The runner:

- loads the golden questions,
- resolves each question's document,
- skips unindexed documents explicitly,
- runs the Phase 4 text query service for indexed documents,
- records LangSmith traces,
- computes metrics,
- writes run artifacts.

## Evaluation Tests

Added:

```text
backend/tests/test_evaluation.py
```

Covered:

- golden dataset loader reads the 40 seeded rows,
- metrics detect answer/citation/evidence behavior,
- runner writes results, summary, report, and RAGAS export,
- runner skips unindexed docs correctly.

Tests use:

- fake query service,
- fake document registry,
- no LangSmith calls.

## Evaluation Run Artifacts

Generated local eval runs under:

```text
evals/runs/
```

Runs created:

```text
phase5_doc005_baseline
phase5_current_indexed_baseline
```

Each run contains:

```text
results.jsonl
summary.json
report.md
ragas_input.jsonl
```

Generated run outputs are ignored by git through:

```text
evals/runs/
```

## Evaluation Documentation

Added:

```text
docs/phase5-evaluation.md
evals/README.md
```

Updated:

```text
backend/README.md
.gitignore
```

Documented:

- Phase 5 purpose,
- configuration,
- golden dataset shape,
- runner commands,
- output files,
- current baseline metrics,
- validation commands,
- gate status.

## Current Phase 5 Baseline

Run:

```text
phase5_current_indexed_baseline
```

Current coverage:

```text
40 questions seen
3 evaluated
37 skipped_not_indexed
0 failed
```

The 3 evaluated rows are the `DOC-005` World Development Report questions because that is the only document indexed in the current text baseline.

Metrics:

```json
{
  "answer_present_rate": 1.0,
  "citation_presence_rate": 1.0,
  "average_expected_answer_token_recall": 0.7917,
  "abstention_correct_rate": null,
  "latency_ms_p50": 1848.61,
  "latency_ms_p95": 10847.39
}
```

Report path:

```text
evals/runs/phase5_current_indexed_baseline/report.md
```

## Phase 5 Validation

Commands run:

```powershell
backend\.venv\Scripts\pytest.exe backend\tests
```

Result:

```text
10 passed
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

Real LangSmith/OpenAI-backed validation was run for:

- golden dataset loading,
- indexed-document baseline evaluation,
- OpenAI query execution,
- LangSmith tracing,
- artifact writing.

## Phase 5 Commit

Committed as:

```text
6775bea Implement phase 5 evaluation harness
```

## Phase 5 Gate Status

Phase 5 is valid for the currently indexed baseline.

Satisfied:

- the golden QA dataset is loaded,
- runnable indexed questions are evaluated,
- unindexed documents are explicitly skipped,
- metrics are computed and summarized,
- evaluation artifacts are saved,
- RAGAS-ready inputs are exported,
- LangSmith traces are emitted for evaluated questions,
- tests validate the core evaluation behavior.

Phase 5 is committed.

Phase 5 unlocked the next phase:

```text
Phase 6 - Retrieval Quality Upgrades + Citation-Grounding Verifier
```

---

# Phase 6 Changes - Retrieval Quality Upgrades and Citation Grounding

Phase 6 upgraded the text RAG baseline with BM25-style retrieval, hybrid ranking, cleaner citation semantics, and a citation-grounding verifier.

## Phase 6 Retrieval Modes

Updated:

```text
backend/src/docifer_backend/retrieval/query.py
backend/src/docifer_backend/schemas/retrieval.py
backend/src/docifer_backend/api/retrieval.py
```

The `/query` endpoint now supports:

```text
dense
bm25
hybrid
```

`dense` preserves the Phase 4 OpenAI embedding + Qdrant baseline.

`bm25` runs local lexical retrieval over persisted `text_chunks`.

`hybrid` combines normalized dense and BM25 scores.

## BM25 Retrieval

Added:

```text
backend/src/docifer_backend/retrieval/bm25.py
```

Implemented:

- tokenizer,
- document frequency tracking,
- BM25 scoring,
- top-k lexical retrieval,
- optional content-hash filtering,
- conversion back into shared `RetrievedChunk` evidence objects.

No new external package was required for BM25.

## Hybrid Ranking

Added:

```text
backend/src/docifer_backend/retrieval/hybrid.py
```

Implemented:

- dense result normalization,
- lexical result normalization,
- weighted score fusion,
- combined ranked evidence output.

Evidence now exposes:

- `dense_score`,
- `lexical_score`,
- `hybrid_score`,
- `retrieval_mode`.

## Citation Semantics Cleanup

Updated query output so final citations are no longer just every retrieved chunk.

The response now separates:

- `retrieved_evidence`,
- `answer_citations`,
- `unused_retrieved_evidence`.

The existing `citations` and `evidence` fields remain for compatibility:

- `citations` now mirrors final answer citations,
- `evidence` mirrors retrieved evidence.

This fixes the Phase 4 issue where retrieved but unused chunks appeared as final citations.

## Citation-Grounding Verifier

Updated provider contracts:

```text
backend/src/docifer_backend/providers/base.py
backend/src/docifer_backend/providers/openai_provider.py
```

Added:

```text
CitationGroundingVerdict
verify_citation_grounding(...)
```

When `verify_citations` is true, Docifer sends the question, answer, and retrieved evidence to an OpenAI-backed verifier.

Verifier output includes:

- `verdict`,
- `supported_citation_ids`,
- `weak_citation_ids`,
- `unsupported_claims`,
- `reasoning`,
- optional `revised_answer`.

If the verifier returns `unsupported`, Docifer replaces the answer with a revised answer or an abstention message.

## API Schema Additions

Updated:

```text
backend/src/docifer_backend/schemas/retrieval.py
```

Request additions:

```json
{
  "retrieval_mode": "hybrid",
  "verify_citations": true
}
```

Response additions:

```text
answer_citations
retrieved_evidence
unused_retrieved_evidence
citation_verification
dense_score
lexical_score
hybrid_score
retrieval_mode
```

## Evaluation Runner Updates

Updated:

```text
backend/src/docifer_backend/evaluation/runner.py
docs/phase5-evaluation.md
```

Added CLI options:

```text
--retrieval-mode dense|bm25|hybrid
--verify-citations
```

This allows Phase 5/6 comparisons without changing the evaluation harness.

## Phase 6 Tests

Updated:

```text
backend/tests/test_text_retrieval.py
backend/tests/test_evaluation.py
```

Added coverage for:

- BM25 lexical retrieval,
- hybrid retrieval score breakdown,
- citation verifier plumbing,
- unused retrieved evidence counts,
- evaluation runner compatibility with retrieval modes.

## Phase 6 Documentation

Added:

```text
docs/phase6-retrieval-grounding.md
```

Updated:

```text
backend/README.md
docs/phase5-evaluation.md
docs/session-changes-2026-05-20.md
```

Documented:

- retrieval modes,
- API schema changes,
- verifier behavior,
- evaluation comparison commands,
- cross-encoder reranker decision,
- validation results.

## Cross-Encoder Reranker Decision

A heavyweight cross-encoder or BGE-style reranker was not installed in this pass.

Reason:

- current indexed coverage is only one small document and three runnable golden questions,
- the extra model dependency and first-run download cost are not justified by this slice,
- BM25 + hybrid retrieval already gives the project a measurable retrieval-quality upgrade without adding a large local model dependency.

This is an explicit Phase 6 v1 decision. A cross-encoder reranker should be reconsidered after more documents are indexed and the eval harness has enough examples to measure the tradeoff.

## Real Phase 6 Validation

BM25 query validated:

```text
Question: Which strategy does the report recommend for upper-middle-income countries?
Answer: For upper-middle-income countries, the report recommends shifting to the “3 i” strategy: investment + infusion + innovation. [C2]
```

Hybrid + verifier query validated:

```text
Question: What three actions does the report associate with successful transitions from middle- to high-income status?
Verifier verdict: supported
```

FastAPI `/query` schema validated with:

```json
{
  "retrieval_mode": "hybrid",
  "verify_citations": true
}
```

Validated response included:

- final answer,
- one answer citation,
- three retrieved evidence items,
- two unused retrieved evidence items,
- verifier verdict `supported`,
- dense/lexical/hybrid score breakdowns.

## Phase 6 Evaluation Comparisons

Runs created:

```text
phase6_doc005_dense
phase6_doc005_bm25
phase6_doc005_hybrid_verifier
```

Current results:

| Mode | Evaluated | Citation Presence | Avg Token Recall | P50 Latency ms | P95 Latency ms |
|---|---:|---:|---:|---:|---:|
| dense | 3 | 1.0 | 0.875 | 2095.07 | 3566.15 |
| bm25 | 3 | 1.0 | 0.7917 | 1145.56 | 2434.81 |
| hybrid + verifier | 3 | 1.0 | 0.875 | 3858.13 | 4137.9 |

Interpretation:

- dense remains strong on the current small text slice,
- BM25 is faster and useful for exact lexical matches,
- hybrid + verifier preserves answer quality while adding semantic grounding verdicts,
- broader conclusions require more indexed documents.

## Phase 6 Validation Commands

Tests:

```powershell
backend\.venv\Scripts\pytest.exe backend\tests
```

Result:

```text
12 passed
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

- BM25 retrieval answer generation,
- hybrid retrieval answer generation,
- citation-grounding verification,
- FastAPI `/query` schema,
- dense / BM25 / hybrid-verifier eval comparisons.

## Phase 6 Browser/API Inspection

The FastAPI server had stopped when the user tried to open:

```text
http://127.0.0.1:8000/docs
```

The backend was restarted outside the sandbox so it stays available to the in-app browser.

Validated:

```text
GET /health -> 200
GET /docs -> 200
```

Running processes included:

```text
uvicorn.exe
python.exe
```

Recommended Phase 6 inspection request in Swagger UI:

```json
{
  "question": "Which strategy does the report recommend for upper-middle-income countries?",
  "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
  "top_k": 3,
  "retrieval_mode": "hybrid",
  "verify_citations": true
}
```

Fields to inspect:

- `answer`
- `answer_citations`
- `retrieved_evidence`
- `unused_retrieved_evidence`
- `citation_verification`
- `debug.retrieval_mode`
- `debug.unused_retrieved_count`
- `dense_score`
- `lexical_score`
- `hybrid_score`

## Phase 6 Gate Status

Phase 6 is valid for the currently indexed text baseline.

Satisfied:

- dense baseline remains runnable,
- BM25 retrieval works,
- hybrid retrieval works,
- answer citations are separated from retrieved evidence,
- unused retrieved evidence is exposed,
- citation-grounding verifier works,
- evaluation runner compares retrieval modes,
- cross-encoder reranker decision is documented with rationale.

Phase 6 was committed as:

```text
5f38a46 Implement phase 6 retrieval grounding upgrades
```

Phase 6 unlocked the corpus-expansion checkpoint:

```text
Phase 6.5 - Expanded Corpus Validation
```

---

# Phase 6.5 Changes - Expanded Corpus Validation

Phase 6.5 expanded the indexed corpus before Phase 7 to check whether the Phase 6 hybrid retrieval and citation-grounding path still behaves well beyond the single World Bank PDF.

## Phase 6.5 Ingestion Finding

The first attempts to ingest larger annual-report PDFs through the default Docling path exposed a local robustness issue:

```text
Stage preprocess failed ... std::bad_alloc
```

This happened during Docling preprocessing on the Microsoft and JPMorgan reports. The affected failed jobs were recorded in PostgreSQL instead of being hidden.

## Phase 6.5 Parser Fallback

Updated:

```text
backend/src/docifer_backend/ingestion/parser.py
backend/src/docifer_backend/ingestion/service.py
backend/src/docifer_backend/config/settings.py
backend/pyproject.toml
backend/uv.lock
```

Added:

- `AutoPdfParser`
- `PdfiumTextParser`
- parser backend settings:
  - `PDF_PARSER_BACKEND=auto`
  - `DOCLING_MAX_FILE_SIZE_BYTES=1000000`
- direct runtime dependency:
  - `pypdfium2>=5.8.0`

Behavior:

- small PDFs continue to use Docling by default,
- larger PDFs use native `pypdfium2` text extraction,
- page-level provenance is preserved for citations,
- canonical artifacts remain compatible with existing chunking and indexing.

## Phase 6.5 Indexing Robustness

Updated:

```text
backend/src/docifer_backend/providers/openai_provider.py
backend/src/docifer_backend/retrieval/indexing.py
backend/src/docifer_backend/retrieval/vector_store.py
backend/src/docifer_backend/config/settings.py
```

Added:

- OpenAI embedding batching via `OPENAI_EMBEDDING_BATCH_SIZE=64`,
- Qdrant upsert batching via `QDRANT_UPSERT_BATCH_SIZE=128`.

Reason:

- JPMorgan produced 1235 chunks,
- a single large Qdrant upsert timed out,
- batched Qdrant writes fixed the issue.

## Phase 6.5 Eval Metric Adjustment

Updated:

```text
backend/src/docifer_backend/evaluation/metrics.py
```

Expanded abstention detection for valid phrases such as:

- `does not include`
- `does not provide`
- `no evidence`
- `not available`
- `not found`
- `not mention`

This fixed an eval false negative where a valid abstention was phrased differently from the original marker list.

## Phase 6.5 Tests

Added:

```text
backend/tests/test_ingestion_parser.py
```

Covered:

- large PDFs route to the text parser,
- Docling failures fall back to text extraction,
- invalid parser backend settings are rejected.

Validated full test suite:

```text
15 passed
```

## Phase 6.5 Indexed Corpus

Indexed additional documents:

| Doc ID | PDF | Parser | Chunks |
|---|---|---|---:|
| DOC-001 | `2025_AnnualReport.pdf` | `pypdfium2-text` | 226 |
| DOC-003 | `JPChaseannualreport-2025.pdf` | `pypdfium2-text` | 1235 |
| DOC-007 | `OECD.pdf` | `pypdfium2-text` | 1627 |

Existing indexed document retained:

| Doc ID | PDF | Parser | Chunks |
|---|---|---|---:|
| DOC-005 | `Worldbank2024.pdf` | `docling` | 5 |

## Phase 6.5 Evaluation Runs

Primary hybrid-verifier run:

```text
phase6_5_expanded_corpus_hybrid
```

Command:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase6_5_expanded_corpus_hybrid --doc-id DOC-001 --doc-id DOC-003 --doc-id DOC-005 --doc-id DOC-007 --top-k 4 --retrieval-mode hybrid --verify-citations
```

Result:

```json
{
  "evaluated": 15,
  "failed": 0,
  "skipped": 25,
  "citation_presence_rate": 0.8667,
  "average_expected_answer_token_recall": 0.6566,
  "abstention_correct_rate": 0.75,
  "latency_ms_p50": 3018.58,
  "latency_ms_p95": 6406.1
}
```

Top-k ablation:

```text
phase6_5_expanded_corpus_hybrid_top8
```

Command:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase6_5_expanded_corpus_hybrid_top8 --doc-id DOC-001 --doc-id DOC-003 --doc-id DOC-005 --doc-id DOC-007 --top-k 8 --retrieval-mode hybrid --verify-citations
```

Result:

```json
{
  "evaluated": 15,
  "failed": 0,
  "skipped": 25,
  "citation_presence_rate": 0.8,
  "average_expected_answer_token_recall": 0.6846,
  "abstention_correct_rate": 1.0,
  "latency_ms_p50": 3049.2,
  "latency_ms_p95": 4486.17
}
```

Run artifacts:

```text
evals/runs/phase6_5_expanded_corpus_hybrid/
evals/runs/phase6_5_expanded_corpus_hybrid_top8/
```

## Phase 6.5 Key Finding

Hybrid retrieval plus citation verification works across the expanded four-document text corpus.

The main observed weakness is table reasoning at low retrieval depth. At `top_k=4`, QA-008 missed the exact JPMorgan segment-results table even though that table was indexed. At `top_k=8`, the correct table entered the evidence set and the system answered correctly:

```text
Commercial & Investment Bank had the highest 2025 net income among the three reportable business segments, at $27,761 million.
```

## Phase 6.5 Documentation

Added:

```text
docs/phase6-5-corpus-expansion.md
```

## Phase 6.5 Gate Status

Phase 6.5 is valid as a corpus-expansion checkpoint.

Satisfied:

- local services were resumed,
- API health was restored,
- larger PDFs now ingest through a robust text fallback,
- expanded corpus indexing works,
- embedding and vector-store writes are batched,
- eval harness runs across four indexed documents,
- hybrid retrieval and citation verification remain functional,
- a clear table-retrieval weakness is identified for Phase 7.

Next phase remains locked until explicitly started:

```text
Phase 7 - Tables + Visual Retrieval
```

---

# Phase 7A Planning and Partial Implementation (2026-05-20/21)

## Project Evaluation

Before starting Phase 7A, an independent code review of the full project was conducted. Key findings:

- Architecture and code quality: solid. Clean module separation, dependency injection, frozen dataclasses, consistent SQLAlchemy 2 patterns.
- Test coverage: thin. 15 tests on tiny synthetic fixture data. No integration tests against real Postgres/Qdrant.
- Frontend: does not exist. `ls frontend` returns empty.
- Evaluation corpus: only 15/40 golden questions evaluated, over 4 documents.
- Self-reported `PROJECT_EVALUATION.md` was noted as optimistic; honest assessment was B- engineering, C on production readiness.

## Phase 7A Design

### Brainstorming Session

Phase 7A was designed through a structured brainstorming session with the following decisions:

| Decision | Choice |
|---|---|
| Lifecycle | Reusable ingestion check (auto after ingest + re-runnable) |
| Output | Report file (`parse_audit.json` + `parse_audit.md`) + DB record |
| Trigger | Auto after ingest + re-runnable via CLI |
| Verdicts | Stats + heuristic verdicts (advisory, never block ingestion) |

### Architecture (Option A chosen)

New `ParseQualityService` post-ingestion service. Reads `canonical.json` → `document.md` → `docling.json` (optional), computes stats, assigns heuristic verdicts, writes artifacts, upserts DB row.

### Design Spec

Written and committed:

```text
docs/superpowers/specs/2026-05-20-phase7a-parse-quality-audit-design.md
```

Key design decisions from spec:

- `quality_status = "good"` only when ALL THREE readiness values are `good`
- `quality_status = "weak"` when no `poor` but at least one `weak`
- `quality_status = "poor"` when `text_readiness == "poor"` OR 2+ signals are `poor`
- Fallback parser → `visual_readiness = "poor"`, `table_readiness` depends on text patterns
- Insert new row per audit run; set `is_latest = False` on previous rows (history preserved)
- `audit_status`, `failed_stage`, `error_message` captured on failure; audit failure never blocks ingestion
- `fallback_reason`: `size_threshold` | `docling_failed` | `manual_backend` | `unknown`

### DB Schema: `parse_quality_audits`

Key columns added:

```text
id, document_id (nullable FK), content_hash, canonical_path
parser_name, parser_version, canonical_schema_version
fallback_used (bool), fallback_reason
audit_version, audit_run_id, audit_status, error_message, failed_stage, is_latest
quality_status, text_readiness, table_readiness, visual_readiness
risk_flags_json, summary_json
artifact_json_path, artifact_md_path, elapsed_ms
created_at
```

### Risk Flags

```text
fallback_parser_used, no_structured_tables, table_like_text_without_structure
no_figures, high_empty_page_ratio, parse_errors_present, low_text_density
large_document (>200 pages), high_chunk_count (>1000), missing_docling_json
```

### Implementation Plan

Written and committed:

```text
docs/superpowers/plans/2026-05-20-phase7a-parse-quality-audit.md
```

6 tasks, full TDD, complete code in every step.

---

## Phase 7A Implementation — Tasks Completed

### New Module Structure

```text
backend/src/docifer_backend/audit/
  __init__.py
  models.py         Task 1 — ParseQualityAudit SQLAlchemy model
  metrics.py        Task 2 — stat extraction + heuristic verdicts
  reporting.py      Task 3 — parse_audit.json + parse_audit.md writers
  service.py        Task 4 — ParseQualityService orchestrator
```

### Task 1: DB Model

**Commit:** `ed367bd` + fix `4b66d03`

Files created/modified:
- `backend/src/docifer_backend/audit/__init__.py`
- `backend/src/docifer_backend/audit/models.py`
- `backend/src/docifer_backend/storage/database.py` (audit models registered in `create_database_schema()`)
- `backend/tests/test_audit.py` (started)

Fix applied after review: `document_id` changed to `Mapped[str | None]` + `nullable=True` to match service contract. Test ordering changed from `created_at` to `audit_run_id` for deterministic results.

### Task 2: Metrics Computation

**Commit:** `e765bcb` + fix `8787770`

File created:
- `backend/src/docifer_backend/audit/metrics.py`

Public interface:
- `AUDIT_VERSION = "0.1.0"`
- `AuditSummary` (frozen dataclass, 12 fields)
- `AuditVerdicts` (frozen dataclass)
- `detect_fallback(canonical) -> tuple[bool, str | None]`
- `compute_summary(canonical, markdown_text, docling, chunk_count) -> AuditSummary`
- `compute_verdicts(summary, *, fallback_used, docling_missing) -> AuditVerdicts`

Two bugs found and fixed in provided spec code:
1. `_text_stats`: leading empty fragment from `re.split` was counted as an empty page
2. `_quality_status`: was triggering "poor" when any signal was poor; fixed to require `text=="poor"` OR `poor_count >= 2`

Fix commit added tests for: `detect_fallback` "unknown" case, `quality_status` 2+ poor path, `missing_docling_json` flag, `parse_errors_present`, `low_text_density`, `high_empty_page_ratio`.

### Task 3: Artifact Reporting

**Commit:** `4f2fe2a` + fix `1c6ee57`

File created:
- `backend/src/docifer_backend/audit/reporting.py`

Also added by implementer (accepted):
- `backend/conftest.py` — redirects `tmp_path` basetemp on Windows permission issues
- `backend/pyproject.toml` — `tmp_path_retention_policy = "failed"`

Fixes applied after review:
- Added `.pytest_tmp/` to `.gitignore`
- `if error_message is not None:` (was `if error_message:` — would silently drop empty string)
- `pytest.raises(OSError)` (was bare `Exception`)
- Removed inline `import json as json_mod` (top-level `json` already imported)

### Task 4: ParseQualityService Orchestrator

**Commit:** `3218dc8` + fix `ad48036`

File created:
- `backend/src/docifer_backend/audit/service.py`

`ParseQualityReport` frozen dataclass returned by all audit methods.

`ParseQualityService.audit()` pipeline:
1. `read_canonical` — JSON parse; failure → persist failed row
2. `read_markdown` — text read; failure → persist failed row
3. `read_docling_json` — optional, non-fatal; missing or corrupt → sets `docling_missing=True`, continues
4. `compute_metrics` — pure computation; failure → persist failed row
5. `write_artifacts` — file write; failure → persist failed row WITH partial `summary_json` preserved
6. `persist_db` — DB insert + is_latest flip; failure → return failed report without DB row

Fixes applied after review:
- `_get_document_id` wrapped in try/except (DB down → returns failed report, not raise)
- `resolve_project_path(docling_path_str)` moved inside try/except for docling stage
- `_get_chunk_count` moved out of `compute_metrics` try block; failure silently defaults to 0 with warning
- Added serial-execution comment on `_insert_with_is_latest_flip` (concurrent write-skew known limitation)
- Added `is_latest is True` assertions to two test paths (failed + fallback)
- Removed unused `utc_now` import

### Test Count Progress

| After | Tests |
|---|---|
| Task 1 | 1 passed |
| Task 2 | 16 passed |
| Task 3 | 23 passed, 1 xfailed (Windows chmod) |
| Task 4 | 26 passed, 1 xfailed |

---

## Phase 7A Completion Update

Tasks 5 and 6 are now completed:

| Task | File | Description |
|---|---|---|
| 5 | `audit/cli.py` | Added `--canonical-path`, `--content-hash`, `--doc-id`, `--all-indexed` CLI |
| 6 | `ingestion/service.py` | Wired `ParseQualityService.audit()` into post-parse hook |

### Task 5: CLI Completed

Created:

```text
backend/src/docifer_backend/audit/cli.py
```

Supported commands:

```text
--canonical-path
--content-hash
--doc-id
--all-indexed
--audit-run-id
```

The CLI prints JSON reports and returns nonzero when an audit fails.

### Task 6: Ingestion Hook Completed

Updated:

```text
backend/src/docifer_backend/ingestion/service.py
```

Behavior:

- fresh successful parses call `ParseQualityService.audit(...)`,
- the audit runs outside the ingestion session,
- audit crashes or failed audit reports are logged,
- audit failures do not block successful ingestion.

### Additional Phase 7A Hardening

Updated:

```text
backend/src/docifer_backend/audit/service.py
.gitignore
backend/README.md
backend/tests/test_audit.py
```

Added:

- schema initialization when `ParseQualityService()` is constructed without an injected session factory,
- post-commit `is_latest` cleanup so concurrent manual audits converge back to one latest row per content hash,
- `--all-indexed` selection now audits one latest completed artifact per indexed content hash,
- CLI tests,
- ingestion-hook tests,
- generated `backend/tmp_pytest/` ignore rule,
- README usage for manual and automatic parse audits.

### Phase 7A Validation

Full test suite:

```text
47 passed, 1 xfailed
```

Compile check:

```text
backend\.venv\Scripts\python.exe -m compileall -q backend\src backend\tests
```

Real local validation:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.audit.cli --all-indexed --audit-run-id phase7a_validation_all_indexed_final
```

Result:

| Hash Prefix | Status | Overall | Text | Tables | Visual |
|---|---|---|---|---|---|
| `8109582811fe` | completed | weak | good | good | weak |
| `0f0dae0b8baa` | completed | poor | good | poor | poor |
| `2a3ee9733eaf` | completed | poor | good | poor | poor |
| `53df3e6ad1c2` | completed | poor | good | poor | poor |

Additional CLI modes validated:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.audit.cli --doc-id DOC-005 --audit-run-id phase7a_validation_doc_id
backend\.venv\Scripts\python.exe -m docifer_backend.audit.cli --content-hash 8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8 --audit-run-id phase7a_validation_content_hash
```

After final validation, the local database has one latest audit row per indexed content hash:

```text
audit_rows: 11
latest_rows: 4
```

Generated artifact files:

```text
parse_audit.json
parse_audit.md
```

were written under each indexed document's processed artifact directory.

### Phase 7A Gate Verdict

Phase 7A is complete and valid.

The audit confirms the key Phase 7B planning risk:

- Docling-parsed World Bank has usable table structure.
- Larger fallback-parsed documents have good text extraction but poor table and visual readiness.
- Phase 7B should not assume structured tables exist for fallback-parsed PDFs; it needs either table-specific extraction, targeted Docling retry options, or a table-like-text strategy.

## Phase 7A Commits This Session

```text
ed367bd feat(audit): add ParseQualityAudit DB model and schema registration
4b66d03 fix(audit): document_id nullable=True, stable test ordering by audit_run_id
e765bcb feat(audit): add metrics computation and heuristic verdicts
8787770 fix(audit): remove unused import, add missing test coverage for all risk flags and quality_status branches
4f2fe2a feat(audit): add artifact reporting (parse_audit.json + parse_audit.md)
1c6ee57 fix(audit): .gitignore pytest_tmp, error_message is not None, pytest.raises(OSError)
3218dc8 feat(audit): add ParseQualityService orchestrator
ad48036 fix(audit): guard _get_document_id, fix docling stage try-scope, chunk_count default 0, is_latest test assertions, serial-execution note
```

Phase 7A completion work was committed as:

```text
9b5ee39 feat(audit): complete Phase 7A parse quality audit
```

Untracked user-side files intentionally left out of the commit:

```text
.claude/
PROJECT_EVALUATION.md
```

Also committed earlier this session:

```text
4f073e9 Add Phase 7A parse quality audit design spec
772def3 Add Phase 7A implementation plan
```

---

# Phase 7B Changes - Table Intelligence

Phase 7B implemented table evidence extraction, indexing, retrieval, and query integration.

## Phase 7B Backend Model

Added:

```text
backend/src/docifer_backend/retrieval/tables/models.py
```

New tables:

- `table_evidence_records`
- `document_table_index_runs`

`create_database_schema()` now registers the table models.

## Phase 7B Extraction

Added:

```text
backend/src/docifer_backend/retrieval/tables/extraction.py
backend/src/docifer_backend/retrieval/tables/schemas.py
```

Implemented:

- structured Docling table extraction from `docling.json["tables"]`,
- Markdown pipe-table extraction from `document.md`,
- fallback table-like text span extraction from `document.md`,
- deterministic table IDs,
- span hashes for deduplication,
- table readiness and risk flags,
- source page and source chunk metadata where available.

## Phase 7B Indexing

Added:

```text
backend/src/docifer_backend/retrieval/tables/indexing.py
```

Updated:

```text
backend/src/docifer_backend/retrieval/vector_store.py
backend/src/docifer_backend/config/settings.py
.env.example
```

Implemented:

- `TableIndexingService.index_canonical_document(...)`,
- `QDRANT_TABLE_COLLECTION=docifer_table_evidence`,
- deterministic Qdrant point IDs via `uuid5(NAMESPACE_URL, table_id)`,
- batched table evidence upserts,
- force reindex cleanup for stale Qdrant points and DB records,
- idempotent reuse of successful table index runs.

## Phase 7B Retrieval

Added:

```text
backend/src/docifer_backend/retrieval/tables/retriever.py
```

Implemented table retrieval modes:

- `table_dense`
- `table_bm25`
- `table_hybrid`

Table hybrid retrieval is intentionally weighted toward BM25/lexical scoring to support exact financial/table questions.

## Phase 7B Query Integration

Updated:

```text
backend/src/docifer_backend/retrieval/query.py
backend/src/docifer_backend/providers/openai_provider.py
backend/src/docifer_backend/api/retrieval.py
backend/src/docifer_backend/schemas/retrieval.py
```

Added:

- `POST /index/tables`,
- `/query.evidence_mode`: `text`, `table`, `auto`,
- `/query.table_top_k`,
- table intent detection,
- table citations using `[T1]`, `[T2]`, etc.,
- separate `table_citations`, `table_evidence`, and `unused_table_evidence`,
- table evidence support in citation-grounding verification.

## Phase 7B Documentation

Added:

```text
docs/phase7b-table-intelligence.md
```

Updated:

```text
backend/README.md
evals/README.md
docs/session-changes-2026-05-20.md
```

## Phase 7B Tests

Added:

```text
backend/tests/test_table_retrieval.py
```

Covered:

- structured Docling table extraction,
- Markdown table extraction,
- fallback table-like text extraction,
- table indexing idempotency,
- Qdrant point ID persistence,
- hybrid table retrieval,
- table-only query citations,
- table-intent false positive guard,
- compound signal detection for `segment`, `highest`, `2025`, `net income`.

Full suite validation:

```text
53 passed, 1 xfailed
```

Command:

```powershell
uv run --project backend pytest --basetemp backend/.pytest_tmp
```

## Phase 7B Real Validation

Real table indexing was run for:

| Document | Hash Prefix | Evidence Count | Notes |
|---|---|---:|---|
| World Bank | `8109582811fe` | 3 | structured + markdown + fallback |
| JPMorgan | `2a3ee9733eaf` | 445 | fallback table-like text spans |

Validated target query:

```text
Which segment had the highest 2025 net income?
```

With:

```json
{
  "evidence_mode": "table",
  "table_top_k": 4,
  "verify_citations": true
}
```

Result:

```text
Commercial & Investment Bank had the highest 2025 net income at $27,761 million.
```

The answer returned table citations and the verifier returned:

```text
supported
```

Auto mode was also validated with `retrieval_mode="hybrid"` and returned table citations with a supported verifier verdict.

The updated FastAPI server was restarted and `/openapi.json` confirmed:

```text
/index/tables present: true
/query present: true
```

An HTTP `POST /query` table-mode request returned:

```text
Commercial & Investment Bank had the highest 2025 net income at $27,761 million.
```

with 2 table citations and verifier verdict `supported`.

## Phase 7B Gate Status

Phase 7B is complete and valid as a table retrieval and evidence-packaging phase.

It improves retrieval for table QA, but does not yet implement deterministic table computation or SQL-style analytics. That remains deferred to a later reasoning phase.

---

# Phase 7C Changes - Table Reasoning

Phase 7C added a lightweight deterministic reasoning layer after table retrieval and before grounded answer generation.

## Phase 7C Reasoning Module

Added:

```text
backend/src/docifer_backend/retrieval/tables/reasoning.py
```

Updated:

```text
backend/src/docifer_backend/retrieval/tables/schemas.py
backend/src/docifer_backend/retrieval/tables/retriever.py
```

New dataclasses:

- `TableQuestionIntent`
- `TableObservation`
- `TableReasoningResult`

Implemented:

- metric/year/operation/entity intent parsing,
- numeric parsing for currency, percentages, commas, and parenthesized negatives,
- structured table reasoning over headers and rows,
- fallback table-like text reasoning over segment/year/metric matrix spans,
- segment-specific candidate filtering so segment questions do not accidentally select whole-firm totals,
- unit inference that prefers explicit `in millions` / `in billions` table context.

## Phase 7C Query Integration

Updated:

```text
backend/src/docifer_backend/retrieval/query.py
backend/src/docifer_backend/providers/openai_provider.py
```

Behavior:

- table retrieval runs as in Phase 7B,
- retrieved tables are passed into the Phase 7C reasoner,
- when reasoning is supported, answer generation receives the computed table observation and only the selected supporting table evidence,
- citation verification uses the same selected table evidence,
- debug includes `table_reasoning_used`, `table_reasoning_status`, and full `table_reasoning` details.

This reduced the validated JPMorgan answer from multiple table citations to one selected table citation.

## Phase 7C Tests

Updated:

```text
backend/tests/test_table_retrieval.py
```

Added coverage for:

- question intent parsing,
- numeric value parsing,
- structured table reasoning using caption metric context,
- fallback JPMorgan-style segment matrix reasoning,
- ignoring whole-firm totals when a segment-level answer is requested,
- `/query` table reasoning debug and selected citation behavior.

Full suite validation:

```text
56 passed, 1 xfailed
```

Compile check also passed:

```text
python -m compileall backend/src/docifer_backend backend/tests
```

## Phase 7C Real Validation

The FastAPI server was restarted with the Phase 7C code and validated through HTTP `POST /query`.

Table mode request:

```json
{
  "question": "Which segment had the highest 2025 net income?",
  "content_hash": "2a3ee9733eafd01e7667c5540fbd797c4cc688d14f00638a877f5623d1316d9d",
  "evidence_mode": "table",
  "table_top_k": 4,
  "verify_citations": true
}
```

Validated result:

```text
Commercial & Investment Bank had the highest 2025 net income at $27,761 million. [T3]
```

Returned:

- `table_citation_count = 1`
- `table_reasoning_status = supported`
- `selected_label = Commercial & Investment Bank`
- `selected_value = $27,761 million`
- `citation_verification.verdict = supported`

Auto mode with `retrieval_mode="hybrid"` was also validated and returned the same selected observation with a supported verifier verdict.

## Phase 7C Documentation

Added:

```text
docs/phase7c-table-reasoning.md
```

Updated:

```text
backend/README.md
evals/README.md
docs/session-changes-2026-05-20.md
```

## Phase 7C Gate Status

Phase 7C is complete and valid for the benchmark-driven table reasoning target.

It is still intentionally not a full spreadsheet analytics engine or SQL-over-tables layer. It is a narrow, inspectable table observation layer for retrieved evidence.

---

# Phase 7D Changes - Visual Evidence Retrieval

Phase 7D adds retrieval-only visual evidence support. The system now finds relevant rendered pages, Docling picture records, and fallback figure references without attempting multimodal image interpretation.

## Phase 7D Configuration

Updated:

```text
backend/src/docifer_backend/config/settings.py
.env.example
```

Added:

```text
QDRANT_VISUAL_COLLECTION=docifer_visual_evidence
```

The default database URL was also aligned with the installed PostgreSQL driver:

```text
postgresql+psycopg://docifer_user:docifer_password@localhost:5432/docifer
```

## Phase 7D Data Model

Added:

```text
backend/src/docifer_backend/retrieval/visuals/models.py
```

New tables:

- `visual_evidence_records`
- `document_visual_index_runs`

`create_database_schema()` now registers the visual models.

## Phase 7D Rendering And Extraction

Added:

```text
backend/src/docifer_backend/retrieval/visuals/rendering.py
backend/src/docifer_backend/retrieval/visuals/extraction.py
backend/src/docifer_backend/retrieval/visuals/schemas.py
```

Implemented:

- PDF page rendering to JPEG via `pypdfium2`,
- first-class `page_render` evidence records,
- `docling_picture` evidence from Docling picture metadata,
- fallback `figure_candidate` records from text references like Figure, Chart, Diagram, and Exhibit,
- visual metadata formatting for embedding and BM25 retrieval.

Rendered artifacts are written under:

```text
datasets/processed/<hash-prefix>/<job-id>/visuals/pages/page_0001.jpg
```

## Phase 7D Indexing And Retrieval

Added:

```text
backend/src/docifer_backend/retrieval/visuals/indexing.py
backend/src/docifer_backend/retrieval/visuals/retriever.py
```

Updated:

```text
backend/src/docifer_backend/retrieval/vector_store.py
```

Implemented:

- `VisualIndexingService.index_canonical_document(...)`,
- idempotent visual index runs,
- forced reindex cleanup of stale visual records and Qdrant points,
- Qdrant upsert/search/delete helpers for `docifer_visual_evidence`,
- retrieval modes `visual_dense`, `visual_bm25`, and `visual_hybrid`,
- score diagnostics: `dense_score`, `lexical_score`, and `hybrid_score`.

## Phase 7D API

Updated:

```text
backend/src/docifer_backend/api/retrieval.py
backend/src/docifer_backend/schemas/retrieval.py
```

New endpoints:

```text
POST /index/visuals
POST /retrieve/visuals
```

`/retrieve/visuals` returns visual candidates only. It does not generate an answer and does not interpret the image.

Candidate responses include:

- `visual_id`
- `document_id`
- `content_hash`
- `visual_type`
- `source_kind`
- `artifact_path`
- page metadata
- caption, figure label, section heading, and nearby text when available
- dense, lexical, and hybrid scores

## Phase 7D Documentation

Added:

```text
docs/phase7d-visual-evidence-retrieval.md
```

Updated:

```text
backend/README.md
evals/README.md
docs/session-changes-2026-05-20.md
```

## Phase 7D Tests

Added and updated:

```text
backend/tests/test_visual_retrieval.py
backend/tests/test_visual_schemas.py
```

Coverage includes:

- visual settings,
- visual dataclasses and API schemas,
- SQL model persistence,
- Qdrant visual upsert/search/delete,
- PDF page rendering,
- Docling picture extraction,
- page-render evidence records,
- fallback figure candidates,
- visual indexing idempotency,
- dense/BM25/hybrid visual retrieval,
- `/index/visuals`,
- `/retrieve/visuals`.

The one-off `backend/tests/test_visual_settings.py` file was consolidated into `backend/tests/test_visual_retrieval.py`.

## Phase 7D Validation

Visual-focused suite:

```text
22 passed
```

Full backend suite:

```text
78 passed, 1 xfailed
```

Compile check:

```text
python -m compileall backend/src/docifer_backend backend/tests
```

Real local validation was run against the existing World Bank canonical artifact:

```text
datasets/processed/8109582811fe/55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff/canonical.json
```

Result:

- `status = indexed`
- `page_render_count = 4`
- `figure_candidate_count = 0`
- `visual_record_count = 7`
- `collection_name = docifer_visual_evidence`
- retrieved 5 visual candidates for `Which figure shows economic growth?`
- returned candidates included `page_render` and `docling_picture` records
- all returned candidate `artifact_path` values pointed to existing rendered JPEG files

The real validation used a fake embedding provider to avoid external API calls while still exercising real PDF rendering, SQL persistence, Qdrant indexing, and visual retrieval.

## Phase 7D Gate Status

Phase 7D is complete as a retrieval-only visual evidence baseline.

It intentionally does not interpret charts or figures yet. The next visual phase can add multimodal interpretation on top of these retrieved, inspectable visual candidates.

## Phase 7D Commit And Merge

Phase 7D was committed and merged into `master`.

Latest `master` commit:

```text
5333eeb feat(visuals): complete Phase 7D visual retrieval
```

Phase 7D commit stack now on `master`:

```text
a72993c feat(config): add qdrant_visual_collection setting
25e90f1 feat(visuals): add VisualEvidence schemas and embedding formatter
0de1bc7 feat(visuals): add VisualEvidenceRecord and DocumentVisualIndexRun ORM models
19e8d00 feat(visuals): add visual evidence Qdrant helpers to vector_store
1b3167a feat(visuals): add PDF page rendering service using pypdfium2
8c3ef2c feat(visuals): add visual evidence extraction from canonical artifacts
8977bba feat(visuals): add VisualIndexingService with rendering, extraction, and Qdrant upsert
715aad1 feat(visuals): add VisualRetriever with dense, BM25, and hybrid search
f6b315c feat(visuals): add VisualIndexRequest/Response and VisualRetrieveRequest/Response schemas
5333eeb feat(visuals): complete Phase 7D visual retrieval
```

Final tracked-file status after merge:

```text
master clean for tracked files
```

Untracked local files such as `.claude/`, `.codex/`, graphify outputs, and project notes were intentionally left untouched.

---

# Phase 7E Changes - Structured Multimodal Interpretation

Phase 7E adds schema-driven interpretation of retrieved visual evidence. It builds on Phase 7D visual retrieval and stays intentionally narrow: retrieved visual candidates are interpreted into structured observations, cited with `[V1]` style citations, and safely abstained when unclear.

## Phase 7E Configuration

Updated:

```text
backend/src/docifer_backend/config/settings.py
.env.example
```

Added:

```text
OPENAI_VISION_MODEL=gpt-4o-mini
```

The setting is configurable so a different vision-capable OpenAI model can be used later.

## Phase 7E Provider Layer

Updated:

```text
backend/src/docifer_backend/providers/base.py
backend/src/docifer_backend/providers/openai_provider.py
```

Added provider-facing dataclasses:

- `VisualEvidenceInput`
- `VisualObservation`
- `VisualInterpretationResult`

Added provider method:

```text
interpret_visual_evidence(question, visual_evidence)
```

The OpenAI implementation uses the Responses API with:

- `input_image` content items for rendered visual artifacts,
- base64 data URLs for local JPEG artifacts,
- strict JSON-schema structured output,
- safe abstention if no readable artifact is available or if output parsing fails.

## Phase 7E Visual Interpretation

Added:

```text
backend/src/docifer_backend/retrieval/visuals/interpretation.py
```

Updated:

```text
backend/src/docifer_backend/retrieval/visuals/schemas.py
```

Implemented:

- visual evidence inputs from Phase 7D candidates,
- structured observation formatting,
- visual grounding evidence conversion,
- `VisualCitation`,
- visual interpretation debug serialization.

## Phase 7E Query Integration

Updated:

```text
backend/src/docifer_backend/retrieval/query.py
backend/src/docifer_backend/api/retrieval.py
backend/src/docifer_backend/schemas/retrieval.py
```

Added:

- `evidence_mode="visual"`,
- `visual_top_k`,
- visual intent detection for auto mode,
- visual retrieval through `VisualRetriever`,
- provider-backed visual interpretation,
- `[V1]`, `[V2]` citation extraction,
- `visual_citations`,
- `visual_evidence`,
- `visual_observations`,
- `unused_visual_evidence`,
- visual debug fields.

Safe abstention is supported for unclear visuals:

```text
I cannot determine this from the retrieved visual evidence because the labels are unreadable. [V1]
```

## Phase 7E Evaluation

Updated:

```text
backend/src/docifer_backend/evaluation/runner.py
evals/README.md
```

Added:

- `--evidence-mode category|text|table|visual|auto`,
- default category routing for golden questions,
- chart/visual/figure/image/graph questions route to `visual`,
- table questions route to `table`,
- mixed questions route to `auto`,
- text questions route to `text`,
- visual IDs and table IDs in evaluation result records,
- combined citation and retrieval score accounting across modalities.

## Phase 7E Tests

Added:

```text
backend/tests/test_openai_provider.py
```

Updated:

```text
backend/tests/test_visual_retrieval.py
backend/tests/test_evaluation.py
```

Coverage includes:

- OpenAI vision structured output parsing without network calls,
- base64 image payload creation for `input_image`,
- safe provider abstention when an artifact is missing,
- visual intent detection,
- `/query` visual mode returns `[V1]` citations and structured observations,
- auto mode triggers visual retrieval for visual intent,
- visual-mode abstention,
- visual response schemas,
- evaluation category routing for visual/table/text questions.

## Phase 7E Validation

Focused validation:

```text
28 passed
```

Full backend suite:

```text
86 passed, 1 xfailed
```

Compile check:

```text
python -m compileall backend/src/docifer_backend backend/tests
```

Live OpenAI vision calls were not run during this implementation pass. The provider path is covered by no-network tests and uses the official Responses API image-input and structured-output shapes.

## Phase 7E Gate Status

Phase 7E is implemented as a structured visual interpretation baseline.

It is ready for live validation with an OpenAI vision-capable model and indexed visual evidence. It deliberately avoids arbitrary image reasoning and chart analytics beyond the structured observation schema.

---

# Phase 7E Live Validation and Corpus Expansion (2026-05-22)

## Server Restart

The FastAPI server was restarted with Phase 7D/7E code loaded. Routes confirmed:

```text
POST /index/visuals
POST /retrieve/visuals
```

## Live Vision Validation

World Bank visual evidence (7 records, already indexed from Phase 7D) was used for the first live call:

```text
Question: What does the figure show about transitions across growth strategies?
```

Request:

```json
{
  "evidence_mode": "visual",
  "visual_top_k": 3,
  "verify_citations": false
}
```

Result:

- `visual_interpretation_status = supported`
- `confidence = 0.9`
- `answer_visual_citation_count = 1`
- Answer included `[V1]` citation
- `observation_type = explanation`, `question_answered = true`
- 4 extracted facts about investment → infusion → innovation ladder

Phase 7E live validation passed.

## Corpus Expansion — Visual Question Docs

The 5 golden chart/visual questions are on DOC-002, DOC-004, DOC-008, DOC-012. These were not previously indexed.

Ingested, text-indexed, table-indexed, and visual-indexed all 4:

| Doc ID | PDF | Text Chunks | Table Evidence | Visual Records |
|---|---|---:|---:|---:|
| DOC-002 | `NVIDIA-2025-Annual-Report.pdf` | 645 | 156 | 181 |
| DOC-004 | `COSTco-Annual-Report-2025.pdf` | 234 | 56 | 76 |
| DOC-008 | `WSPR_2024_EN_WEB_1.pdf` | 1141 | 193 | 386 |
| DOC-012 | `9789240115569-eng.pdf` | 902 | 61 | 342 |

Visual indexing initially failed with:

```text
Vector dimension error: expected dim: 4, got 1536
```

Root cause: `docifer_visual_evidence` Qdrant collection was created with dimension 4 during test runs (fake embeddings). Deleted the collection; indexing service recreated it at dimension 1536.

## Citation Bug Fix

Initial category-mode eval showed:

```text
Chart / Visual: avg_recall=0.98, citation_present=0.00
```

Visual answers were correct but contained no `[V1]` markers.

### Root Cause Investigation

Two bugs found:

**Bug 1 — query.py:** When `verify_citations=True`, the verifier's `revised_answer` replaced the visual interpretation answer even when verdict was `supported`. The verifier-generated `revised_answer` did not include `[V1]` markers, stripping them from the final answer.

Fix: Only replace answer with `revised_answer` when verdict is `unsupported` or `partially_supported`. A `supported` answer is not replaced.

**Bug 2 — openai_provider.py:** GPT-4o-mini did not reliably include `[V1]` in the JSON `answer` field even when the prompt requested it. The `_parse_visual_interpretation_payload` function stored the citation-free answer as-is.

Fix: Post-processing step appends the first `used_citation_id` to the answer if status is `supported`, the answer is non-empty, and no citation marker is present.

Additionally hardened the verifier prompt to instruct: "If you do provide a revised_answer, preserve all citation markers ([C1], [T1], [V1], etc.) from the original answer."

### Verification

After fix, live query with `verify_citations=True`:

```text
VISUAL_CITES: ['V1']
VERDICT: supported
```

Test suite: `86 passed, 1 xfailed`

Committed as:

```text
281a76e fix(visuals): guarantee [V1] citation in visual answers
```

## Final Eval — phase7e_full_final

Run across all 8 indexed docs with category routing:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner \
  --run-name phase7e_full_final \
  --doc-id DOC-001 --doc-id DOC-002 --doc-id DOC-003 --doc-id DOC-004 \
  --doc-id DOC-005 --doc-id DOC-007 --doc-id DOC-008 --doc-id DOC-012 \
  --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations
```

Result:

```json
{
  "evaluated": 26,
  "failed": 1,
  "citation_presence_rate": 0.9231,
  "average_expected_answer_token_recall": 0.6885,
  "abstention_correct_rate": 0.6667,
  "latency_ms_p50": 2841.07,
  "latency_ms_p95": 8877.92
}
```

Per-category breakdown:

| Category | n | Avg Recall | Citation % | Mode |
|---|---|---:|---:|---|
| Chart / Visual | 4 | 1.00 | 100% | visual |
| Text Factual | 8 | 0.87 | 100% | text |
| Table Lookup | 4 | 0.64 | 100% | table |
| Text Synthesis | 4 | 0.50 | 100% | text |
| Table Reasoning | 3 | 0.46 | 67% | table |
| Unsupported / Abstention | 3 | 0.32 | 67% | text |

Visual question results:

| QA ID | Document | Recall | [Vn] |
|---|---|---:|---|
| QA-006 | NVIDIA Blackwell infographic | 1.00 | [V1] ✓ |
| QA-012 | Costco projected locations map | 1.00 | [V1] ✓ |
| QA-023 | WSPR Figure 4.35 pension share | 1.00 | [V2] ✓ |
| QA-024 | WSPR Figure 3.13 financing gap | 1.00 | [V1] ✓ |
| QA-036 | WHO SEAHEARTS figure | rate limited | — |

QA-036 was validated manually in a separate call:

```text
Answer: As of December 2024, 48 million people are placed on protocol-based management
for hypertension and/or diabetes. [V1]
Verdict: supported
```

The one failure is a gpt-4o-mini TPM rate limit, not a system bug.

## Indexed Corpus State (end of session)

| Doc ID | PDF | Text ✓ | Tables ✓ | Visuals ✓ |
|---|---|---|---|---|
| DOC-001 | `2025_AnnualReport.pdf` (Microsoft) | 226 chunks | ✓ | ✓ |
| DOC-002 | `NVIDIA-2025-Annual-Report.pdf` | 645 chunks | 156 | 181 |
| DOC-003 | `JPChaseannualreport-2025.pdf` | 1235 chunks | 445 | ✓ |
| DOC-004 | `COSTco-Annual-Report-2025.pdf` | 234 chunks | 56 | 76 |
| DOC-005 | `Worldbank2024.pdf` | 5 chunks | 3 | 7 |
| DOC-007 | `OECD.pdf` | 1627 chunks | ✓ | ✓ |
| DOC-008 | `WSPR_2024_EN_WEB_1.pdf` | 1141 chunks | 193 | 386 |
| DOC-012 | `9789240115569-eng.pdf` | 902 chunks | 61 | 342 |

## Session Commits

```text
849b5db feat(visuals): complete Phase 7E structured multimodal interpretation
281a76e fix(visuals): guarantee [V1] citation in visual answers
```
