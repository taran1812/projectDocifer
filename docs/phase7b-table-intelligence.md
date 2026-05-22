# Phase 7B Table Intelligence

Phase 7B adds table evidence extraction, indexing, retrieval, and query integration. It treats tables as evidence objects instead of relying on generic prose chunks.

## What Changed

- Added `table_evidence_records` and `document_table_index_runs`.
- Added `QDRANT_TABLE_COLLECTION`, defaulting to `docifer_table_evidence`.
- Added structured Docling table extraction.
- Added Markdown pipe-table extraction.
- Added fallback table-like text span extraction for large text-parser PDFs.
- Added `TableIndexingService` and `POST /index/tables`.
- Added dense, BM25, and hybrid table retrieval.
- Weighted table hybrid retrieval toward BM25/lexical scoring for table QA.
- Added `evidence_mode` to `/query`: `text`, `table`, or `auto`.
- Added `table_top_k` to `/query`.
- Added table citation IDs such as `[T1]`.
- Added separate response fields: `table_citations`, `table_evidence`, and `unused_table_evidence`.
- Extended citation verification to evaluate table evidence through the existing `GroundingEvidence` adapter.

## API Usage

Index table evidence:

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

Use auto mode when the question may need both prose and table evidence:

```json
{
  "question": "Which segment had the highest 2025 net income?",
  "content_hash": "2a3ee9733eafd01e7667c5540fbd797c4cc688d14f00638a877f5623d1316d9d",
  "retrieval_mode": "hybrid",
  "evidence_mode": "auto",
  "table_top_k": 4,
  "verify_citations": true
}
```

## Real Validation

Table evidence was indexed for:

| Document | Content hash prefix | Result |
|---|---|---:|
| World Bank | `8109582811fe` | 3 table evidence objects |
| JPMorgan | `2a3ee9733eaf` | 445 fallback table spans |

Target JPMorgan query:

```text
Which segment had the highest 2025 net income?
```

Validated result:

```text
Commercial & Investment Bank had the highest 2025 net income at $27,761 million.
```

The table-only query returned table citations and the citation verifier returned `supported`.

## Test Validation

Run from the repo root:

```powershell
uv run --project backend pytest --basetemp backend/.pytest_tmp
```

Validated result:

```text
53 passed, 1 xfailed
```

## Notes

Phase 7B improves retrieval and evidence packaging for table questions. It does not yet implement deterministic table computation or SQL-style analytics. That remains deferred to a later reasoning phase.
