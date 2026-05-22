# Docifer Backend

FastAPI service for Docifer's document ingestion, retrieval, and agentic workflows.

## Phase 3 ingestion

Raw PDFs live in the repository-level `datasets/raw_pdfs` directory. Parsed outputs are written under `datasets/processed` and are intentionally ignored by git.

Run one local PDF through the ingestion pipeline:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.ingestion.cli datasets\raw_pdfs\Worldbank2024.pdf
```

The command creates or reuses:

- a `documents` row keyed by PDF content hash,
- an `ingestion_jobs` row with status transitions,
- a canonical artifact at `datasets/processed/<hash-prefix>/<job-id>/canonical.json`,
- the full Docling export at `docling.json`,
- an inspection-friendly Markdown rendering at `document.md`,
- a compact parse summary at `parse_summary.json`.

Running the same PDF again without `--force` reuses the existing successful job and does not parse or index a duplicate.

## API endpoints

- `GET /health`
- `GET /ready`
- `POST /ingestion/jobs`
- `GET /ingestion/jobs/{job_id}`
- `POST /index/text`
- `POST /index/tables`
- `POST /query`

Example request body:

```json
{
  "source_path": "datasets/raw_pdfs/Worldbank2024.pdf",
  "force_reprocess": false
}
```

## Validation

Run the backend test suite:

```powershell
backend\.venv\Scripts\pytest.exe backend\tests
```

## Phase 4 text RAG baseline

Index a parsed canonical artifact into Qdrant:

```json
{
  "canonical_path": "datasets/processed/8109582811fe/55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff/canonical.json",
  "force_reindex": false
}
```

Ask a baseline text question:

```json
{
  "question": "What do middle-income countries need to do to escape the middle-income trap?",
  "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
  "top_k": 3
}
```

The response includes a grounded answer, citations, retrieved text chunks, and debug metadata.

## Phase 5 evaluation baseline

Run the current indexed-document evaluation baseline:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase5_current_indexed_baseline --top-k 3
```

Run only the validated World Development Report slice:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase5_doc005_baseline --doc-id DOC-005 --top-k 3
```

Evaluation outputs are written under `evals/runs/<run-name>/` and include `results.jsonl`, `summary.json`, `report.md`, and `ragas_input.jsonl`.

## Phase 6 retrieval upgrades

The `/query` endpoint supports retrieval modes:

- `dense`
- `bm25`
- `hybrid`

Example hybrid query with citation verification:

```json
{
  "question": "Which strategy does the report recommend for upper-middle-income countries?",
  "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
  "top_k": 3,
  "retrieval_mode": "hybrid",
  "verify_citations": true
}
```

The response separates `retrieved_evidence`, `answer_citations`, and `unused_retrieved_evidence`, and includes a citation-grounding verdict when verification is enabled.

## Phase 6.5 expanded-corpus validation

Phase 6.5 added a text-first fallback parser for larger PDFs and batched indexing writes so the text RAG path can handle more than one starter document.

Current expanded indexed slice:

- `DOC-001` Microsoft annual report
- `DOC-003` JPMorgan annual report
- `DOC-005` World Bank report
- `DOC-007` OECD report

Run the expanded hybrid evaluation:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase6_5_expanded_corpus_hybrid_top8 --doc-id DOC-001 --doc-id DOC-003 --doc-id DOC-005 --doc-id DOC-007 --top-k 8 --retrieval-mode hybrid --verify-citations
```

The Phase 6.5 notes are in:

```text
docs/phase6-5-corpus-expansion.md
```

## Phase 7A parse quality audit

Phase 7A audits parse artifacts and writes advisory readiness reports for text, table, and visual readiness.

Manual audit commands:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.audit.cli --canonical-path datasets\processed\8109582811fe\55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff\canonical.json
```

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.audit.cli --content-hash 8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8
```

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.audit.cli --all-indexed
```

Each successful audit writes:

```text
parse_audit.json
parse_audit.md
```

New ingestions automatically trigger the audit after a successful parse. Audit failures are advisory and do not block ingestion.

## Phase 7B table intelligence

Phase 7B adds table evidence objects beside text chunks. It indexes structured Docling tables, Markdown tables, and fallback table-like text spans into the Qdrant collection:

```text
docifer_table_evidence
```

Index table evidence for a parsed document:

```json
{
  "canonical_path": "datasets/processed/2a3ee9733eaf/e8351c2d-49a0-425e-a76b-e781487001d5/canonical.json",
  "force_reindex": false
}
```

Ask a table-only question:

```json
{
  "question": "Which segment had the highest 2025 net income?",
  "content_hash": "2a3ee9733eafd01e7667c5540fbd797c4cc688d14f00638a877f5623d1316d9d",
  "evidence_mode": "table",
  "table_top_k": 4,
  "verify_citations": true
}
```

`/query` now supports:

- `evidence_mode="text"`: existing text-only behavior
- `evidence_mode="table"`: table evidence only
- `evidence_mode="auto"`: text retrieval plus table retrieval when table intent is detected

Table evidence responses are returned separately as `table_evidence`, `table_citations`, and `unused_table_evidence`.

## Phase 7C table reasoning

Phase 7C adds deterministic table observations between table retrieval and answer generation. For supported table questions, `/query` now extracts the metric, year, operation, and candidate values from retrieved table evidence before the LLM writes the final answer.

The public request shape is unchanged from Phase 7B. The debug payload includes:

```text
table_reasoning_used
table_reasoning_status
table_reasoning
```

Validated target question:

```text
Which segment had the highest 2025 net income?
```

Validated answer:

```text
Commercial & Investment Bank had the highest 2025 net income at $27,761 million.
```

Detailed notes are in:

```text
docs/phase7c-table-reasoning.md
```
