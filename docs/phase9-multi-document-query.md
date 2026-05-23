# Phase 9 - Multi-Document Query Mode

## Goal

Phase 9 adds explicit document scope to `/query` so a question can search one document, selected documents, or every indexed document with relevant evidence.

The default remains single-document retrieval. Corpus-wide search must be requested explicitly.

## Request Contract

New `/query` fields:

```json
{
  "scope": "single",
  "doc_ids": null,
  "document_ids": null,
  "max_documents": 5,
  "max_evidence_per_document": 3
}
```

Scope rules:

- `scope="single"` requires `content_hash` or exactly one `doc_id`/`document_id`.
- `scope="doc_ids"` requires at least one `doc_id` or `document_id`.
- `scope="all"` must be explicit and cannot be combined with a document filter.
- `doc_ids` use starter-corpus identifiers such as `DOC-005`.
- `document_ids` are internal document UUIDs.
- `max_documents` and `max_evidence_per_document` limit final answer context, not the corpus search set.

Selected-document example:

```json
{
  "question": "Compare the growth strategies discussed in these reports.",
  "scope": "doc_ids",
  "doc_ids": ["DOC-005", "DOC-007"],
  "top_k": 4,
  "retrieval_mode": "hybrid",
  "evidence_mode": "text",
  "max_documents": 2,
  "max_evidence_per_document": 2,
  "verify_citations": true
}
```

Corpus-wide example:

```json
{
  "question": "Which indexed reports discuss institutional reform?",
  "scope": "all",
  "top_k": 4,
  "retrieval_mode": "hybrid",
  "evidence_mode": "text",
  "max_documents": 5,
  "max_evidence_per_document": 3,
  "verify_citations": true
}
```

## Implemented Changes

- Added a retrieval-side document scope resolver using the starter corpus `DOC-001` through `DOC-012` mapping for v1.
- Added multi-content-hash filters to dense and BM25 text, table, and visual retrieval.
- Added `document_id` to new text Qdrant payloads and to text retrieval results.
- Enriched text, table, and visual evidence/citations with `doc_id`, `document_id`, `filename`, and `content_hash`.
- Added bounded, cross-modal final context selection for multi-document scopes.
- Added a bounded broader candidate pull before final context selection: selected-document scope considers at least 20 candidates and corpus-wide scope considers up to 50 candidates so one document cannot crowd out relevant evidence prematurely.
- Added debug fields:
  - `scope`
  - `documents_searched`
  - `documents_searched_count`
  - `documents_used`
  - `documents_used_count`
  - `candidate_pool_top_k`
  - `evidence_by_document`
- Added evaluator flags: `--scope`, `--max-documents`, and `--max-evidence-per-document`.

## Reindex Requirement

Existing text points created before Phase 9 do not contain `document_id` in their Qdrant payload. Reindex already parsed documents through `POST /index/text` with `force_reindex=true` before validating document-aware text responses against an existing collection.

Table and visual records already carried internal document identity before Phase 9.

## Validation

Automated validation:

```text
Focused multi-document/table/visual regression tests: 40 passed
Full backend suite: 122 passed, 1 xfailed
Compile check: passed
```

## Live Corpus Validation

All 12 existing canonical text documents were force-reindexed through the current API on May 22, 2026:

```text
Documents reindexed: 12
Text points/chunks reindexed: 10,113
Qdrant payload audit: 10,113 scanned, 12 distinct document_id values, 0 missing document_id values
```

The first corpus-wide probe surfaced a valid retrieval quality issue: the initial small candidate pool allowed OECD evidence to crowd out an independently relevant World Bank result. The bounded broader-pool change above corrected that before final validation.

Supported composite validation question:

```text
What are the 1i, 2i, and 3i strategies in the World Development Report, and what share of young adults in OECD countries now complete tertiary education?
```

Results:

| Scope | Documents searched | Documents used | Candidate pool | Answer citations | Verifier |
|---|---:|---:|---:|---|---|
| `doc_ids` with `DOC-005`, `DOC-007` | 2 | 2 | 20 | `DOC-007` and `DOC-005` | `supported` |
| `all` | 12 | 2 | 50 | `DOC-007` and `DOC-005` | `supported` |

The live responses returned:

- `DOC-005` / `Worldbank2024.pdf` with `document_id=30abbd45-a8d4-4585-82a7-326c7ab76786` for the `1i`, `2i`, and `3i` statement.
- `DOC-007` / `OECD.pdf` with `document_id=88a8f590-6813-449f-b9a7-9829b41d0787` for the `48%` tertiary education statement.

## Phase Status

Phase 9 is code-complete, test-valid, and live corpus validated for selected-document and explicit all-document text retrieval. A broader multi-document golden evaluation remains useful as a later measurement pass, but it is no longer blocking this phase gate.
