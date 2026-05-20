# Phase 4 Text RAG Baseline

Phase 4 adds the first answerable text-only RAG path over parsed Docifer artifacts.

## Implemented components

- Text chunking from Docling text blocks.
- Page-aware chunk metadata.
- OpenAI embedding provider using the configured `OPENAI_API_KEY`.
- Qdrant text collection for dense retrieval.
- PostgreSQL `text_chunks` records for indexed chunk metadata.
- Idempotent text indexing through `document_index_runs`.
- Baseline grounded answer generation through OpenAI.
- FastAPI endpoints for text indexing and querying.

## Configuration

Environment variables:

```text
OPENAI_API_KEY=
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_ANSWER_MODEL=gpt-5.4-mini
QDRANT_TEXT_COLLECTION=docifer_text_chunks
```

The OpenAI API key stays in `.env` and is not committed.

## Indexing

Endpoint:

```text
POST /index/text
```

Example body:

```json
{
  "canonical_path": "datasets/processed/8109582811fe/55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff/canonical.json",
  "force_reindex": false
}
```

Validated response:

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

## Querying

Endpoint:

```text
POST /query
```

Example body:

```json
{
  "question": "What do middle-income countries need to do to escape the middle-income trap?",
  "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
  "top_k": 3
}
```

Validated behavior:

- query embedding is generated,
- top text chunks are retrieved from Qdrant,
- the answer is generated only from retrieved evidence,
- citations map back to chunk IDs, source PDF path, canonical artifact path, page metadata, and retrieval scores.

## Validated Document

Source PDF:

```text
datasets/raw_pdfs/Worldbank2024.pdf
```

Canonical artifact:

```text
datasets/processed/8109582811fe/55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff/canonical.json
```

Index result:

- 5 text chunks
- Qdrant collection `docifer_text_chunks`
- status `indexed`
- idempotent rerun returns `reused_existing: true`

## Validation

Commands run:

```powershell
backend\.venv\Scripts\pytest.exe backend\tests
```

```powershell
backend\.venv\Scripts\python.exe -m compileall -q backend\src backend\tests
```

Real OpenAI-backed validation was run for:

- `/index/text`
- `/query`

## Phase 4 Gate Status

Phase 4 text baseline is valid for the first ingested document.

Satisfied:

- chunks preserve document and page metadata,
- chunks are embedded and indexed in Qdrant,
- indexing is idempotent,
- `/query` retrieves evidence and returns a cited answer,
- tests cover chunking, indexing reuse, duplicate-index protection, and query output.

Remaining future-phase work:

- hybrid retrieval,
- reranking,
- citation-grounding verifier,
- broader golden-set evaluation.
