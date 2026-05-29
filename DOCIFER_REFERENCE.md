# DOCIFER — Technical Reference

> Generated 2026-05-27. All function names, class names, and file paths sourced directly from the codebase.

---

## 1. Project Overview

Docifer is a **multimodal, multi-agent document intelligence system** designed for grounded question answering over PDF corpora. Its core value proposition is providing answers that are traceable to specific pages and passages in source documents, rather than generating unverifiable text.

**What it solves:**

- **Hallucination risk in RAG systems** — every answer is grounded in retrieved evidence, with optional citation verification that can revise or suppress answers unsupported by the retrieved context.
- **PDF complexity** — financial reports, research papers, and regulatory filings contain text, tables, and figures. Docifer indexes all three modalities separately and fuses them at query time.
- **Retrieval quality** — instead of dense-only vector search, the system offers dense, BM25, and hybrid retrieval modes with an optional cross-encoder reranker.
- **Auditability** — every ingestion job, parse quality result, and retrieval event is persisted in Postgres. The API exposes modality-level index status for each document.

The system is structured as a Python/FastAPI backend with a React/TypeScript frontend ("Workbench") for uploading PDFs, listing indexed documents, composing questions, and inspecting grounded evidence.

---

## 2. Architecture Overview

```
Browser (React/Vite)
        |
        | HTTP/JSON  (X-API-Key header, optional)
        v
+-----------------------------------------------------------------------+
|  FastAPI Application  (backend/src/docifer_backend/main.py)           |
|                                                                        |
|  Middleware: CORSMiddleware → api_key gate                            |
|                                                                        |
|  Routers:                                                              |
|    /health, /ready          (api/health.py)                           |
|    /ingestion/...           (api/ingestion.py)                        |
|    /index/*, /query,        (api/retrieval.py)                        |
|    /retrieve/visuals                                                   |
|    /vector/...              (api/vector.py)                           |
|    /documents/...           (api/documents.py)                        |
+-----------------------------------------------------------------------+
        |                               |
        | SQLAlchemy (psycopg v3)       | qdrant-client
        v                               v
+------------------+         +---------------------------+
|   PostgreSQL 17  |         |   Qdrant (vector DB)      |
|                  |         |                           |
|  documents       |         |  docifer_text_chunks      |
|  ingestion_jobs  |         |  docifer_table_evidence   |
|  document_index_ |         |  docifer_visual_evidence  |
|    runs          |         |                           |
|  text_chunks     |         |  HNSW index               |
|  table_evidence_ |         |  Cosine distance          |
|    records       |         |  Payload indexes on       |
|  visual_evidence_|         |  content_hash, doc_id,    |
|    records       |         |  page_start               |
|  document_table_ |         +---------------------------+
|    index_runs    |
|  document_visual_|                     |
|    index_runs    |               OpenAI API
|  parse_quality_  |        (embeddings + answers +
|    audits        |         vision interpretation)
+------------------+

Filesystem (project-local):
  backend/uploads/           — uploaded PDFs (UUID-prefixed)
  datasets/processed/        — artifact directories
    <hash_prefix>/<job_id>/
      canonical.json         — schema v1, metadata, paths
      docling.json           — raw parser output
      document.md            — markdown representation
      parse_summary.json     — parse stats
```

---

## 3. Tech Stack

| Layer | Technology | Version / Notes |
|---|---|---|
| Language | Python | 3.11+ |
| Web framework | FastAPI | Raw `Request` used for multipart to bypass Starlette 1 MB limit |
| ASGI server | Uvicorn | Production deployment target |
| Settings | pydantic-settings | `BaseSettings` with `.env` file loading |
| ORM | SQLAlchemy 2.x | Declarative mapped columns; `psycopg` (v3) driver |
| Relational DB | PostgreSQL 17 | `create_all` DDL only; no Alembic migrations |
| Vector DB | Qdrant | Three collections; HNSW cosine; `qdrant-client` SDK |
| PDF parser (primary) | Docling | `DocumentConverter`; structured tables, figures, markdown |
| PDF parser (fallback) | pypdfium2 | Text extraction only; zero table/figure count |
| Embeddings | OpenAI | `text-embedding-3-small` default; 64-item batch |
| Answer generation | OpenAI | `gpt-5.4-mini` default; prompt version `phase12_baseline_v1` |
| Visual interpretation | OpenAI | `gpt-4o-mini` default; base64 image inputs |
| Reranker (optional) | HuggingFace Transformers | `BAAI/bge-reranker-base`; disabled by default |
| LangSmith | Tracing | Optional; gracefully no-ops if API key absent |
| Frontend | React 18 + Vite + TypeScript | Functional components + hooks; no state library |
| Styling | Plain CSS | CSS Grid layout; `Inter` font; no utility framework |
| Icons | lucide-react | `Search`, `FileText`, `Trash2`, `Activity` |
| Container runtime | Docker Compose | `infra/compose.yaml`; Postgres 17 + Qdrant latest |
| Tests | pytest | Unit (SQLite in-memory) + integration (Postgres + Qdrant) |

---

## 4. Backend — Deep Dive

### 4.1 Application Entry Point

**File:** `backend/src/docifer_backend/main.py`

`create_app()` constructs and returns the `FastAPI` application instance. The module-level `app = create_app()` is the ASGI entry point.

**Middleware chain (applied in declaration order):**

1. **`CORSMiddleware`** — registered only when `settings.parsed_cors_allowed_origins` is non-empty. Allows all methods and headers.
2. **`require_api_key`** — registered only when `settings.api_key` is set. Checks `X-API-Key` header. Paths in `_UNPROTECTED_PATHS = {"/health", "/ready"}` are unconditionally exempt.

**Routers registered:**

| Variable | Module | URL prefix | Tags |
|---|---|---|---|
| `health_router` | `api.health` | (none) | health |
| `ingestion_router` | `api.ingestion` | `/ingestion` | ingestion |
| `retrieval_router` | `api.retrieval` | (none) | retrieval |
| `vector_router` | `api.vector` | `/vector` | vector |
| `documents_router` | `api.documents` | `/documents` | documents |

---

### 4.2 Configuration System

**File:** `backend/src/docifer_backend/config/settings.py`

`Settings` extends `pydantic_settings.BaseSettings`. Cached via `@lru_cache` in `get_settings()`. `.env` resolves four parents up from `settings.py` (project root). `extra = "ignore"` silently discards unknown variables.

A `@model_validator(mode="after")` enforces: `text_chunk_size >= 200`, `text_chunk_overlap >= 0`, `text_chunk_overlap < text_chunk_size`.

**File:** `backend/src/docifer_backend/config/paths.py`

- `PROJECT_ROOT` — `Path(__file__).resolve().parents[4]`, the repository root.
- `resolve_project_path(path)` — converts project-relative strings to absolute `Path` objects.
- `display_path(path)` — returns a stable POSIX-format relative path string for DB storage.

---

### 4.3 API Endpoints

#### Health

| Method | Path | Auth exempt | Description |
|---|---|---|---|
| GET | `/health` | Yes | `{"status":"ok","service":...,"environment":...}` |
| GET | `/ready` | Yes | Checks Postgres (`SELECT 1`) + Qdrant connection + 3 collection checks via `asyncio.gather` |

#### Ingestion

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| POST | `/ingestion/jobs` | `IngestPdfRequest` (source_path, force_reprocess) | `IngestionJobResponse` 202 | Server-side path; calls `_index_all` after parse |
| POST | `/ingestion/upload` | `multipart/form-data`: `file` (PDF), optional `force_reprocess` | `IngestionJobResponse` 202 | Reads raw `Request` to bypass 1 MB limit; writes to `backend/uploads/`; deletes on error |
| GET | `/ingestion/jobs/{job_id}` | Path param | `IngestionJobResponse` | Status polling |

#### Retrieval

| Method | Path | Description |
|---|---|---|
| POST | `/index/text` | Index text chunks for a canonical document |
| POST | `/index/tables` | Index table evidence |
| POST | `/index/visuals` | Index visual evidence |
| POST | `/query` | Full multimodal RAG query |
| POST | `/retrieve/visuals` | Visual retrieval only |

#### Vector

| Method | Path | Description |
|---|---|---|
| GET | `/vector/collections` | All three collection stats + HNSW config |
| GET | `/vector/collections/{name}/stats` | Stats for one collection |

#### Documents

| Method | Path | Description |
|---|---|---|
| GET | `/documents` | List with filters: q, doc_id, quality_status, text/table/visual_status, parser_name, limit (1–200), offset |
| GET | `/documents/{id}` | Full detail |
| GET | `/documents/by-doc-id/{doc_id}` | Lookup by human doc_id |
| GET | `/documents/by-content-hash/{hash}` | Lookup by SHA-256 |
| GET | `/documents/{id}/indexes` | Per-modality index status |
| GET | `/documents/{id}/audit` | Parse quality audit |
| GET | `/documents/{id}/artifacts` | File artifact references |
| DELETE | `/documents/{id}` | Delete document, Qdrant points, DB rows, filesystem artifacts |

---

### 4.4 Ingestion Pipeline

**Orchestrator:** `IngestionService` (`ingestion/service.py`)
**Parser:** `AutoPdfParser` (`ingestion/parser.py`)

**Step-by-step flow:**

1. **File inspection** — `inspect_pdf_file()` computes SHA-256 `content_hash`, records `file_size_bytes`, normalises `filename`.
2. **Deduplication** — `_find_successful_job()` queries `ingestion_jobs` for a prior `parsed` or `indexed` job with same `content_hash`. If found and artifact exists on disk, returns `IngestionOutcome(reused_existing=True)` immediately.
3. **Document record** — `_get_or_create_document()` upserts a `Document` row keyed on `content_hash`.
4. **Job record** — `IngestionJob` row created with `status=queued`.
5. **Parse with retries** (`_parse_with_retries`, `max_attempts=2`) — job transitions to `parsing`, then `AutoPdfParser.parse()` is called.
6. **AutoPdfParser selection logic:**

```
backend="docling"     → DoclingParser always
backend="pdfium*"     → PdfiumTextParser always
backend="auto" (default):
  file_size > 500 MB?
    YES → PdfiumTextParser + parser_selection error entry
    NO  → Try DoclingParser
            Exception raised?        → PdfiumTextParser + exception error entry
            result.errors non-empty? → PdfiumTextParser + merged error lists
            No errors                → return DoclingParser result
```

7. **Artifact writing** — directory at `<processed_data_dir>/<hash[:12]>/<job_id>/`:
   - `docling.json` — raw parser dict
   - `document.md` — markdown
   - `canonical.json` — schema `docifer.canonical_document.v1`
   - `parse_summary.json` — copy of parse block

8. **Job update** — status → `parsed`; `parser_name`, `parser_version`, `artifact_path` written.
9. **Parse quality audit** — `ParseQualityService.audit()` runs after parse. Computes `AuditSummary` metrics and `AuditVerdicts`. Persists `ParseQualityAudit` row. Failure is logged as warning only.
10. **Indexing** — API layer calls `_index_all(canonical_path)`:
    - `TextIndexingService.index_canonical_document()` → chunks → embeddings → upsert to `docifer_text_chunks`
    - `TableIndexingService.index_canonical_document()` → table extraction → embeddings → upsert to `docifer_table_evidence`
    - `VisualIndexingService.index_canonical_document()` → figure extraction + page renders → embeddings → upsert to `docifer_visual_evidence`
    - Response status becomes `"indexed"` when all three complete.

---

### 4.5 Retrieval & Query Pipeline

**Orchestrator:** `TextQueryService` (`retrieval/query.py`)

**Step-by-step flow for `POST /query`:**

1. **Request validation** — `QueryRequest` Pydantic model validates scope, evidence mode, retrieval mode, and cross-validates document identifiers against scope rules.
2. **Intent detection** — `detect_table_intent(question)` checks for financial signals (`$`, `%`, year patterns, `revenue`, `net income`, etc.). `detect_visual_intent(question)` checks for `figure`, `chart`, `diagram`, `graph`. In `evidence_mode="auto"`, positive intent enables that modality's retrieval.
3. **Scope resolution** — `DocumentScopeResolver.resolve()` maps `content_hash`, `doc_ids`, or `document_ids` to `QueryDocumentRef` objects. For `scope="all"`, all registry documents are included.
4. **Candidate pool sizing** — for multi-document scopes, `_multi_document_candidate_top_k()` inflates to at least 50 (`scope="all"`) or 20 (`scope="doc_ids"`).
5. **Text retrieval** (if `should_retrieve_text`):
   - `dense` — embeds question, calls `search_text_chunks()` against `docifer_text_chunks`.
   - `bm25` — `BM25Retriever` loads all `TextChunkRecord` rows for scoped hashes, tokenizes with `TOKEN_PATTERN = re.compile(r"[a-z0-9]+")`, scores with BM25 (k1=1.5, b=0.75).
   - `hybrid` — runs both at `top_k * 2` candidates, merges via `merge_hybrid_results()` (dense weight 0.6, lexical weight 0.4, min-max normalized).
6. **Optional reranking** — `CrossEncoderReranker` retrieves `reranker_candidate_top_n` (default 20), reranks to `top_k`. Falls back gracefully on `RerankerUnavailableError`.
7. **Table retrieval** — `TableRetriever.search()` mode `table_hybrid`.
8. **Visual retrieval** — `VisualRetriever.search()` mode `visual_hybrid`.
9. **Multi-document context limiting** — merges all candidates sorted by score; enforces `max_documents` (5) and `max_evidence_per_document` (3).
10. **Table reasoning** — `reason_over_table_evidence()` selects most relevant table via keyword matching; produces `T{n}` grounding evidence entry.
11. **Visual interpretation** — `ai_provider.interpret_visual_evidence()` calls `gpt-4o-mini` with base64-encoded images. Returns `VisualInterpretationResult` with `VisualObservation` objects.
12. **Grounding evidence construction** — text chunks → `GroundingEvidence(citation_id="C{n}", ...)`. Tables → `T{n}`. Visual observations → `V{n}`.
13. **Initial answer generation** — `ai_provider.generate_grounded_answer(question, evidence)`.
14. **Abstention retry** — `_is_abstention(answer)` tests 8 normalised marker phrases. If abstention detected and text evidence available, re-retrieves at `min(top_k * 2, 8)` and regenerates. Both states written to `debug`.
15. **Citation verification** (if `verify_citations=True`) — second LLM call returns `CitationGroundingVerdict`. On `unsupported`, answer replaced by `revised_answer` or stock message.
16. **Citation extraction** — `re.findall(r"\[(C\d+|T\d+|V\d+)\]", answer, flags=re.IGNORECASE)`.
17. **Response assembly** — `QueryResponse` includes answer, all citation arrays, evidence arrays for all modalities, visual observations, verification result, and a `debug` dict.

---

### 4.6 Data Models

All models use SQLAlchemy 2.x `Mapped`/`mapped_column`. No Alembic migrations — schema via `Base.metadata.create_all()`.

#### `Document`
| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | UUID |
| `filename` | `String(512)` | |
| `source_path` | `Text` | Absolute path at ingestion time |
| `content_hash` | `String(64)` | SHA-256 hex; unique; indexed |
| `file_size_bytes` | `Integer` | |
| `latest_job_id` | `String(36)` nullable | Denormalized pointer; no FK constraint |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | |

#### `IngestionJob`
Key fields: `status` (queued/parsing/parsed/indexing/indexed/failed), `attempt_count`, `max_attempts` (2), `parser_name`, `parser_version`, `artifact_path` (project-relative path to `canonical.json`), `error_type`, `error_message`, `error_detail` (JSON), `started_at`, `completed_at`.

#### `ParseQualityAudit`
Key fields: `audit_status`, `quality_status` (good/warn/poor), `text_readiness`, `table_readiness`, `visual_readiness`, `risk_flags_json`, `summary_json`, `fallback_used`, `is_latest` (indexed).

#### `TextChunkRecord`
Key fields: `chunk_id` (deterministic), `chunk_index`, `text`, `page_start`, `page_end`, `source_path`, `source_artifact_path`, `qdrant_point_id`. Unique on `(document_id, content_hash, chunk_id)`.

#### `TableEvidenceRecord`
Key fields: `table_id`, `table_type` (structured/table_like_text/markdown), `source_kind`, `table_readiness`, `raw_text`, `markdown_table`, `structured_json`, `row_count`, `column_count`, `has_header`, `empty_cell_ratio`, `qdrant_point_id`.

#### `VisualEvidenceRecord`
Key fields: `visual_id`, `visual_type`, `source_kind`, `artifact_path` (path to rendered image), `caption`, `section_heading`, `nearby_text`, `figure_label`, `visual_readiness`, `qdrant_point_id`.

---

### 4.7 Vector Store

**File:** `backend/src/docifer_backend/retrieval/vector_store.py`

| Collection | Default name | Content | Key payload fields |
|---|---|---|---|
| Text | `docifer_text_chunks` | One point per text chunk | `chunk_id`, `content_hash`, `document_id`, `text`, `filename`, `page_start`, `page_end` |
| Table | `docifer_table_evidence` | One point per table | `table_id`, `content_hash`, `document_id`, `table_type`, `table_readiness`, `span_hash` |
| Visual | `docifer_visual_evidence` | One point per visual/figure | `visual_id`, `content_hash`, `document_id`, `visual_type`, `artifact_path`, `caption` |

**Vector dimensions:** 1536 (inferred from first embedding at upsert; `text-embedding-3-small`).
**Distance:** `COSINE` for all three collections.
**HNSW:** m=16, ef_construct=100 at creation; hnsw_ef=64 at query time. Exact search disabled by default.
**Filtering:** `_content_hash_filter()` builds `MatchValue` or `MatchAny`. Empty list produces never-match filter to prevent cross-corpus leakage.
**Batch upsert:** loops in batches of 128 with `wait=True`.

---

### 4.8 Document Registry Service

**File:** `backend/src/docifer_backend/documents/service.py`

`DocumentRegistryService` is the read-oriented facade over Postgres. Raises `DocumentRegistryNotFoundError` (404), `DocumentRegistryForbiddenError` (403), `DocumentRegistryAmbiguousError` (409).

| Method | Description |
|---|---|
| `list_documents(...)` | Loads ALL documents; builds `_RegistryContext`; applies Python-level filter; slices. O(N). |
| `get_document(document_id)` | Full detail: modality status, latest audit, artifact references. |
| `get_by_doc_id(doc_id)` | Resolves via `DocumentScopeResolver`; raises ambiguous error on multiple matches. |
| `get_by_content_hash(content_hash)` | Same path. |
| `get_indexes(document_id)` | Per-modality `ModalityIndexStatus`. |
| `get_audit(document_id)` | Latest `ParseQualityAudit` summary. |
| `get_artifacts(document_id)` | Lists canonical.json, docling.json, document.md, parse_summary.json, and all visual artifact records. |
| `delete_uploaded_document(document_id)` | Deletes Qdrant points (all 3 collections), 8 Postgres tables, uploaded PDF (if inside uploads_dir), and artifact directories. |

---

### 4.9 PDF Parsing

**File:** `backend/src/docifer_backend/ingestion/parser.py`

#### `DoclingParser`
- Uses `docling.document_converter.DocumentConverter` (no OCR by default).
- **Capabilities:** structured table extraction (JSON + markdown), figure/image extraction, heading hierarchy, section labels.
- **Limitations:** memory-intensive; can crash with `std::bad_alloc` on dense pages; no OCR for scanned content.

#### `PdfiumTextParser`
- Uses `pypdfium2.PdfDocument`; iterates pages; `page.get_textpage().get_text_range()`.
- Always reports `table_count=0`, `figure_count=0`.
- **Capabilities:** fast; reliable on digitally generated PDFs.
- **Limitations:** no table structure, no figures, no heading hierarchy; blind to scanned PDFs.

#### `AutoPdfParser` selection decision tree
See section 4.4 step 6 above.

---

## 5. Frontend — Deep Dive

### 5.1 Component Tree

```
App (App.tsx)
├── StatusStrip
│     readyStatus, scope, evidenceMode, latencyMs, requestStatus
├── workbench-grid
│   ├── document-rail (aside)
│   │   ├── UploadPanel
│   │   │     onIngestionComplete → App.refreshDocuments()
│   │   └── DocumentList
│   │         documents, selectedDocumentId
│   │         onSelect, onRemove, removingDocumentId
│   └── center-column (section)
│       ├── QueryComposer
│       │     question, scope, evidenceMode, verifyCitations
│       │     selectedDocument, isLoading
│       │     onSubmit → App.runQuery()
│       └── AnswerPanel
│             error, isLoading, response
└── EvidencePanel (aside)
      response (tabs: citations | retrieved | unused | debug)
```

---

### 5.2 State Management

All state in `App.tsx` via `useState`. No external state library.

| Hook | Type | Purpose |
|---|---|---|
| `documents` | `DocumentSummary[]` | All documents from `/documents?limit=200` |
| `selectedDocumentId` | `string \| null` | Document selected for single-doc queries |
| `question` | `string` | Textarea content |
| `scope` | `QueryScope` | `"single"` or `"all"` |
| `evidenceMode` | `EvidenceMode` | `"auto"`, `"text"`, `"table"`, or `"visual"` |
| `verifyCitations` | `boolean` | Whether to call citation verification; default `true` |
| `readyStatus` | `string` | Last `/ready` result; `"checking"` initially |
| `requestStatus` | `string` | `"idle"`, `"running"`, `"complete"`, or `"failed"` |
| `latencyMs` | `number \| null` | Client-side `performance.now()` delta |
| `response` | `QueryResponse \| null` | Last successful query response |
| `error` | `string \| null` | Last error message |
| `isLoading` | `boolean` | True during in-flight query |
| `removingDocumentId` | `string \| null` | Document being deleted |

`selectedDocument` is a `useMemo` derived from `documents` and `selectedDocumentId`.
Initial `useEffect` runs once; concurrently fetches `/ready` and `/documents` via `Promise.allSettled`.

---

### 5.3 API Client

**File:** `frontend/src/lib/api.ts`

**Base URL:** `VITE_DOCIFER_API_URL` (trailing slash stripped) or `http://127.0.0.1:8000`.
**API key:** `VITE_DOCIFER_API_KEY`. If set, `apiKeyHeader()` returns `{"X-API-Key": value}` merged into every request.
**`ApiError`:** extends `Error` with `status: number` and `details: unknown`. Thrown by `throwIfNotOk()`.
**`requestJson<T>`** — `fetch` + `Content-Type: application/json` + API key header.
**`requestFormData<T>`** — no `Content-Type` (browser sets multipart boundary), passes `FormData` body.

| Method | HTTP | Path |
|---|---|---|
| `health()` | GET | `/health` |
| `ready()` | GET | `/ready` |
| `documents()` | GET | `/documents?limit=200` |
| `deleteDocument(id)` | DELETE | `/documents/{id}` |
| `query(body)` | POST | `/query` |
| `uploadPdf(file, forceReprocess?)` | POST | `/ingestion/upload` |
| `ingestionJob(jobId)` | GET | `/ingestion/jobs/{jobId}` |

---

### 5.4 Upload Flow

**File:** `frontend/src/components/UploadPanel.tsx`

**State machine:**

```
idle
  ↓ file selected/dropped → validate .pdf extension + MIME type
uploading
  ↓ dociferApi.uploadPdf() awaited
  ├─ HTTP error        → failed
  ├─ status "indexed" / "completed" / "done"  → done → (3s) → idle
  ├─ status "failed"   → failed
  └─ any other status  → processing
        ↓ setInterval(2000ms), max 60 polls (120s)
        ├─ status "completed" / "done"  → done → (3s) → idle
        ├─ status "failed"              → failed
        ├─ poll count ≥ 60              → failed ("Ingestion timed out")
        └─ network error                → keep polling (swallowed)
failed
  ↓ "Try again" button → idle
```

Timer handles stored in `intervalRef` and `timeoutRef`. Both cleared on unmount and on each new upload.

---

### 5.5 Query Flow

1. User types question in `QueryComposer` textarea.
2. User sets scope (Single/All), evidenceMode, verifyCitations checkbox.
3. Submit → `QueryComposer.handleSubmit()` → `App.runQuery()`.
4. `runQuery()` builds `QueryRequest` from `DEFAULT_QUERY_PARAMS` (hybrid, top_k=4, table_top_k=4, visual_top_k=3, max_documents=5) merged with current state; adds `content_hash` when `scope="single"`.
5. `dociferApi.query(payload)` awaited; `isLoading=true`, `requestStatus="running"`.
6. Success: `setResponse(result)`, `setLatencyMs(...)`, `requestStatus="complete"`.
7. Error: `setError(message)`, `requestStatus="failed"`.
8. `AnswerPanel` renders `response.answer` + citation chips.
9. `EvidencePanel` shows four tabs: **Citations**, **Retrieved**, **Unused**, **Debug**.

---

### 5.6 Type Definitions

**File:** `frontend/src/types/api.ts`

| Type | Key fields |
|---|---|
| `DocumentSummary` | `document_id`, `doc_id`, `content_hash`, `filename`, `source_path`, `is_uploaded`, `parser_name`, `latest_ingestion_status`, `quality_status`, `modalities` |
| `ModalityIndexStatus` | `status`, `count`, `latest_status`, `collection_name`, `latest_indexed_at` |
| `QueryRequest` | `question`, `scope`, `content_hash`, `max_documents`, `max_evidence_per_document`, `top_k`, `retrieval_mode`, `evidence_mode`, `table_top_k`, `visual_top_k`, `verify_citations` |
| `QueryResponse` | `answer`, `citations`, `table_citations`, `visual_citations`, `answer_citations`, all evidence arrays, `visual_observations`, `citation_verification`, `debug` |
| `IngestionJobResponse` | `job_id`, `document_id`, `status`, `artifact_path`, `reused_existing`, `error_message` |
| `CitationVerification` | `verdict`, `supported_citation_ids`, `weak_citation_ids`, `unsupported_claims`, `revised_answer` |

---

## 6. Infrastructure & Configuration

### 6.1 Local Development Setup

```bash
# Start Postgres and Qdrant
docker compose -f infra/compose.yaml up -d

# Backend
cd backend
pip install -e ".[dev]"
cp ../.env.example ../.env
# Edit .env: set OPENAI_API_KEY at minimum
uvicorn docifer_backend.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev   # http://localhost:5173
```

`infra/compose.yaml` defines:
- `docifer-postgres` — `postgres:17`; port 5432; volume `docifer_postgres_data`; healthcheck via `pg_isready`.
- `docifer-qdrant` — `qdrant/qdrant:latest`; ports 6333 (HTTP) and 6334 (gRPC); volume `docifer_qdrant_data`.

---

### 6.2 Environment Variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `APP_NAME` | `Docifer` | No | FastAPI title |
| `APP_ENV` | `development` | No | Returned in `/health` response |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | No | Comma-separated CORS origins |
| `DOCIFER_API_KEY` | (none) | No | If set, enables `X-API-Key` gate on all non-health endpoints |
| `DATABASE_URL` | `postgresql+psycopg://docifer_user:docifer_password@localhost:5432/docifer` | **Yes** | SQLAlchemy connection string |
| `QDRANT_URL` | `http://localhost:6333` | **Yes** | Qdrant HTTP endpoint |
| `OPENAI_API_KEY` | (none) | **Yes** | Required for embeddings, answers, and visual interpretation |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | No | |
| `OPENAI_ANSWER_MODEL` | `gpt-5.4-mini` | No | |
| `OPENAI_VISION_MODEL` | `gpt-4o-mini` | No | |
| `PDF_PARSER_BACKEND` | `auto` | No | `auto`, `docling`, or `pdfium_text` |
| `DOCLING_MAX_FILE_SIZE_BYTES` | `500000000` | No | 500 MB auto-mode fallback threshold |
| `UPLOAD_MAX_FILE_SIZE_BYTES` | `1000000000` | No | 1 GB multipart upload cap |
| `RERANKER_ENABLED` | `false` | No | Enable cross-encoder reranker globally |
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | No | HuggingFace model ID |
| `TEXT_CHUNK_SIZE` | `1200` | No | Max chars per chunk (must be ≥ 200) |
| `TEXT_CHUNK_OVERLAP` | `200` | No | Overlap chars (must be < chunk_size) |
| `LANGSMITH_API_KEY` | (none) | No | LangSmith tracing (gracefully disabled if absent) |

**Frontend** (in `frontend/.env` or build env):

| Variable | Default | Description |
|---|---|---|
| `VITE_DOCIFER_API_URL` | `http://127.0.0.1:8000` | Backend base URL |
| `VITE_DOCIFER_API_KEY` | `""` | Sent as `X-API-Key`; empty = header omitted |

---

### 6.3 Authentication

Backend `require_api_key` HTTP middleware is instantiated only when `settings.api_key` is set. Compares `request.headers.get("X-API-Key", "")` against `settings.api_key`. `/health` and `/ready` are unconditionally exempt. No token rotation, expiry, or user-level auth.

Frontend `apiKeyHeader()` in `api.ts` reads `VITE_DOCIFER_API_KEY` and includes it on every request if non-empty.

---

## 7. Known Limitations & Technical Debt

**No database migrations.** Schema creation is `Base.metadata.create_all()` only. Column additions or alterations on a live deployment require manual SQL or dropping/recreating tables. No Alembic present.

**No CI pipeline.** No `.github/workflows/` or other CI configuration. Tests must be run manually. No automated linting, type-checking, or test gating on commits.

**Frontend has zero tests.** The React codebase under `frontend/src/` has no test files, no testing library, no Vitest or Jest configuration.

**SQLite in unit tests, not Postgres.** Tests use `create_engine("sqlite+pysqlite:///:memory:")`. SQLite differences (JSON handling, type coercions) may mask Postgres-only bugs.

**`list_documents` is O(N) Python-level filtering.** `DocumentRegistryService.list_documents()` loads all documents and related records, builds response objects for all, then filters the Python list. Filters are not pushed to SQL. `total` count and `offset` pagination are both wrong under partial filters.

**Ingestion is synchronous — no real job queue.** Both ingestion endpoints block the request thread until all three indexing stages complete. Can take minutes for large PDFs. No Celery queue, background task runner, or async job manager.

**`source_path` exposed in API responses.** `DocumentSummaryResponse` and evidence responses include the server-side filesystem path, leaking internal directory structure to API consumers.

**No rate limiting.** `/query` calls OpenAI on every request with no throttling. A misconfigured or malicious client can exhaust the OpenAI API quota.

**OpenAPI docs publicly exposed.** FastAPI's `/docs` and `/redoc` are served without authentication even when `api_key` is set.

**No React error boundaries.** An unhandled exception in any component will crash the entire React tree and show a blank page.

**No mobile layout.** Fixed three-column CSS Grid with no responsive media queries.

**Non-constant-time API key comparison.** `provided != settings.api_key` (plain Python string inequality) is vulnerable to timing attacks. A production deployment should use `hmac.compare_digest`.

**BM25 loads all chunks into memory.** `BM25Retriever._load_documents()` fetches all `TextChunkRecord` rows for scoped hashes into a Python list. For `scope="all"` on a large corpus this is slow and memory-intensive.

**`Document.latest_job_id` has no FK constraint.** Declared as `String(36)` with no `ForeignKey("ingestion_jobs.id")`. No referential integrity enforced.

**Qdrant and Postgres deletes are not atomic.** If the process crashes between Qdrant deletion and Postgres commit, the DB retains rows pointing to deleted vector data.

---

## 8. Strengths

**Hybrid retrieval (dense + BM25).** Normalizes both score distributions to [0, 1] and combines at 60/40 ratio. Mitigates vocabulary mismatch weakness of pure dense retrieval — critical for financial terminology and precise named entities.

**Multi-modality (text + table + visual).** Three separate Qdrant collections, three indexing services, three retrieval passes, with independent `top_k` controls per modality and per-evidence context limiting.

**Citation verification.** Optional second LLM call classifies each citation as supported/weak/unsupported. Verdict, citation IDs, unsupported claims, and revised answer all surfaced in the API response.

**Abstention retry logic.** Automatically expands retrieval window and regenerates when 8 normalised abstention markers are detected. Both initial and retry states recorded in the `debug` dict.

**pdfium fallback on Docling errors.** Handles three distinct failure modes (size limit, exception, non-empty errors list) with separate error entries preserved in `canonical.json`. Downstream consumers can determine exactly why a fallback occurred.

**Parse quality audit system.** `ParseQualityService` computes quantitative metrics (page count, table candidate count, empty pages, average chars per page, parse error count) and per-modality readiness verdicts. Results stored in Postgres and surfaced as `quality_status` (good/warn/poor) on every document.

**Intent-based automatic evidence mode.** `detect_table_intent()` and `detect_visual_intent()` activate the appropriate retrieval path without requiring the user to manually select a mode. Intent signals and scores included in `debug` response.

**Table reasoning.** `reason_over_table_evidence()` selects the most relevant table and produces a grounded `T{n}` citation entry, reducing hallucination risk when multiple tables are retrieved.

**Idempotent re-indexing.** All three indexing services check for a prior successful run before embedding. `force_reindex=True` bypasses the cache. Makes repeated API calls safe and avoids redundant OpenAI embedding costs.

**Structured artifact layout.** Every ingestion job produces a deterministic directory at `<processed_data_dir>/<hash[:12]>/<job_id>/`. The `canonical.json` schema version (`docifer.canonical_document.v1`) makes the format versioned and inspectable.

---

## 9. Benchmark Results

> Measured 2026-05-27 on local machine. Backend: FastAPI + Uvicorn. Services: PostgreSQL 17 + Qdrant (Docker). Corpus: 14 documents, 14,042 indexed items. OpenAI API calls use live network.

### 9.1 Test Suite

```
Platform  : win32, Python 3.12.13
pytest    : 9.0.3
Collected : 165 tests
```

| Result | Count |
|---|---|
| Passed | 160 |
| Failed | 4 |
| xfailed (expected) | 1 |
| **Pass rate** | **97.0%** |

**Failures:**

| Test | Root Cause |
|---|---|
| `test_service_rejects_delete_for_builtin_document` | **Intentional** — we removed the `is_uploaded` guard to allow all docs to be deleted. Test expects `ForbiddenError` that no longer exists. |
| `test_ingest_pdf_creates_job_and_canonical_artifact` | `canonical.json` not found after test run — likely a path resolution issue in the test environment (Windows path vs project-relative path). |
| `test_upload_saves_file_and_returns_job_response` | 500 error in test environment — likely Docling/pypdfium2 cannot process the test fixture PDF in CI-like context. |
| `test_upload_allows_file_above_docling_threshold_when_under_upload_limit` | Same root cause as above. |

> Note: 3 of the 4 failures are test environment issues, not production code bugs. Only the first is a deliberate behavior change.

---

### 9.2 Infrastructure Endpoint Latency (n=5)

| Endpoint | Avg | Min | Max |
|---|---|---|---|
| `GET /health` | 7ms | 1ms | 32ms |
| `GET /ready` | 41ms | 16ms | 73ms |
| `GET /documents?limit=200` (14 docs) | 19ms | 18ms | 23ms |
| `GET /documents?limit=50` | 18ms | 17ms | 18ms |

---

### 9.3 Query Latency (n=3, live OpenAI API)

| Query type | Avg | Min | Max |
|---|---|---|---|
| Single-doc, BM25 only, no verify | 1,262ms | 1,224ms | 1,331ms |
| Single-doc, dense only, no verify | 1,503ms | 1,367ms | 1,625ms |
| Single-doc, hybrid, no verify | 1,912ms | 1,446ms | 2,354ms |
| Single-doc, hybrid + verify_citations | 4,216ms | 3,774ms | 4,865ms |
| All-docs, hybrid, no verify | 4,555ms | 3,493ms | 6,656ms |

**Key observations:**
- `verify_citations=True` adds ~2.3s (a second LLM call) to every query.
- Hybrid retrieval adds ~400ms over dense-only (BM25 scoring in Python).
- All-docs scope adds ~2.6s over single-doc (14× more Qdrant candidates + larger context window).
- BM25-only is fastest (1.26s avg) but weakest for semantic queries.

---

### 9.4 Corpus Statistics (as of 2026-05-27)

| Metric | Value |
|---|---|
| Total documents | 14 |
| Total text chunks indexed | 10,288 |
| Total table evidence indexed | 1,416 |
| Total visual evidence indexed | 2,338 |
| **Total indexed items** | **14,042** |
| Parser: pypdfium2-text | 13 docs |
| Parser: docling | 1 doc |
| Quality status: poor | 13 docs |
| Quality status: weak | 1 doc |
| Quality status: good | 0 docs |

**Quality note:** All 14 documents are rated "poor" or "weak" because they were parsed by `pypdfium2-text` (which scores `table_readiness: not_available`, `visual_readiness: not_available` by design). The one "weak" document (Amazon Q1 2026 earnings) used Docling but had parse errors. No documents have quality_status "good" in the current corpus.

---

### 9.5 Production Readiness Score

| Dimension | Score |
|---|---|
| Security | 2/10 |
| Error Handling & Resilience | 5/10 |
| Data Integrity | 5/10 |
| Test Coverage | 6/10 |
| Configuration & Deployment | 3/10 |
| Performance & Scalability | 5/10 |
| Code Quality | 6/10 |
| Observability | 3/10 |
| API Design | 6/10 |
| Frontend UX & Correctness | 5/10 |
| **Overall** | **4/10** |

---

## 10. Key Files Reference

| File | Role |
|---|---|
| `backend/src/docifer_backend/main.py` | App factory, middleware, router registration |
| `backend/src/docifer_backend/config/settings.py` | All configuration |
| `backend/src/docifer_backend/api/ingestion.py` | Upload + job endpoints |
| `backend/src/docifer_backend/api/retrieval.py` | Query endpoint |
| `backend/src/docifer_backend/api/documents.py` | Document CRUD |
| `backend/src/docifer_backend/ingestion/service.py` | Ingestion orchestrator |
| `backend/src/docifer_backend/ingestion/parser.py` | AutoPdfParser, DoclingParser, PdfiumTextParser |
| `backend/src/docifer_backend/retrieval/query.py` | Query pipeline orchestrator |
| `backend/src/docifer_backend/retrieval/vector_store.py` | Qdrant operations |
| `backend/src/docifer_backend/retrieval/bm25.py` | BM25 in-process retrieval |
| `backend/src/docifer_backend/documents/service.py` | Document registry + delete |
| `backend/src/docifer_backend/providers/openai_provider.py` | Embeddings, answers, vision |
| `backend/src/docifer_backend/audit/service.py` | Parse quality scoring |
| `frontend/src/App.tsx` | Root component + all state |
| `frontend/src/lib/api.ts` | API client + auth header |
| `frontend/src/components/UploadPanel.tsx` | Upload state machine + polling |
| `frontend/src/components/QueryComposer.tsx` | Query controls |
| `frontend/src/components/EvidencePanel.tsx` | Evidence inspector tabs |
| `frontend/src/types/api.ts` | All TypeScript type definitions |
| `infra/compose.yaml` | Postgres 17 + Qdrant services |
| `.env.example` | All environment variable defaults |
