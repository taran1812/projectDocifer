# Phase 7B — Table Intelligence: Design Spec

**Date:** 2026-05-21
**Phase:** 7B
**Status:** Approved
**Depends on:** Phase 7A (Parse Quality Audit)
**Deliverable:** Table evidence extraction, indexing, retrieval, and query integration that improves table QA beyond generic text retrieval.

---

## 1. Why Phase 7B Exists

Phase 6.5 showed hybrid text retrieval works at scale but fails table reasoning at low retrieval depth. JPMorgan QA-008 (segment net income comparison) succeeded at `top_k=8` but failed at `top_k=4` — the correct table content was indexed as fragmented text chunks, not as coherent table evidence.

Phase 7A confirmed the root cause: only the small Docling-parsed World Bank document has usable structured table output. Microsoft, JPMorgan, and OECD were parsed through `pypdfium2-text`, giving good text readiness but poor structured table readiness.

Phase 7B must handle both cases:
- **Structured path** — Docling-parsed tables with headers and rows
- **Fallback path** — table-like text spans from `document.md` for large fallback-parsed documents

The fallback path is not a degraded mode. It is the primary path for the largest documents in the corpus.

---

## 2. Goals

- Discover and store table evidence from all indexed documents
- Support both structured Docling tables and fallback table-like text spans
- Add table-specific retrieval (hybrid dense + lexical)
- Return table-aware citations separate from text citations
- Expose table intent detection and debug information
- Evaluate improvement on known weak table QA cases (JPMorgan QA-008)

---

## 3. Out of Scope

- `reasoning.py` structured observation step — **deferred to Phase 7C or later**
- Full spreadsheet analytics engine
- Complex multi-page table reconstruction
- OCR table recovery for scanned PDFs
- SQL over document tables
- Visual table detection from page images
- Chart/figure interpretation
- Frontend table viewer
- `--all-ingested` CLI flag

---

## 4. Design Principle

**Tables are evidence objects, not text chunks.**

A table evidence object preserves document identity, page range, title/caption, rows/columns when structured, raw text when unstructured, source parser, confidence level, and citation metadata. This is distinct from a text chunk, which is a fixed-size prose fragment.

---

## 5. Module Structure

```
docifer_backend/
  retrieval/
    tables/
      __init__.py
      models.py        # TableEvidenceRecord + DocumentTableIndexRun SQLAlchemy models
      extraction.py    # structured (docling.json) + fallback (document.md) extraction
      indexing.py      # TableIndexingService
      retriever.py     # table dense / bm25 / hybrid retrieval
      schemas.py       # TableEvidence dataclass, TableIndexOutcome, TableQueryResult, TableCitation
      utils.py         # OPTIONAL: add only if extraction.py accumulates shared helpers
                       #   (numeric-pattern detection, stable ID generation, markdown span utils)
```

`query.py` is extended (not replaced). `reasoning.py` is not created in Phase 7B.

---

## 6. Data Model

### 6.1 `table_evidence_records`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | FK → documents | |
| `content_hash` | str(64) | |
| `canonical_path` | str | artifact used for this extraction |
| `table_id` | str(128) | stable deterministic ID; unique+indexed |
| `table_index` | int | position within document |
| `table_type` | str | `structured` \| `table_like_text` |
| `source_kind` | str | `docling_table` \| `markdown_table` \| `text_pattern` |
| `page_start` | int \| null | |
| `page_end` | int \| null | |
| `title` | str \| null | |
| `caption` | str \| null | |
| `section_heading` | str \| null | nearest heading above table in docling/markdown |
| `raw_text` | text | always populated |
| `markdown_table` | text \| null | markdown representation when available |
| `structured_json` | JSON \| null | `{"headers": [...], "rows": [[...]]}` |
| `row_count` | int \| null | |
| `column_count` | int \| null | |
| `has_header` | bool | |
| `empty_cell_ratio` | float \| null | |
| `table_readiness` | str | `good` \| `weak` \| `poor` |
| `extraction_method` | str | `docling` \| `markdown_regex` \| `table_like_text` |
| `risk_flags_json` | JSON | e.g. `["missing_header", "single_row_table", "fallback_parser_used"]` |
| `source_chunk_id` | str \| null | nearest `TextChunkRecord.chunk_id` by page overlap; structured tables → null |
| `span_hash` | str(64) \| null | SHA-256 of `raw_text`; durable identity for fallback spans |
| `qdrant_point_id` | str(36) \| null | null until Qdrant upsert succeeds |
| `indexed_at` | datetime \| null | set when Qdrant upsert completes |
| `created_at` | datetime | |

**Stable ID format:**
- Structured: `<content_hash[:12]>:table:<index:04d>` → `8109582811fe:table:0007`
- Fallback text: `<content_hash[:12]>:table_text:<chunk_idx:04d>:<span_idx:02d>` → `2a3ee9733eaf:table_text:0882:01`

**DB constraints:**
```sql
UNIQUE(table_id)
INDEX(content_hash)
INDEX(document_id, content_hash)
INDEX(qdrant_point_id)
```

**Idempotency (three cases):**
- `force_reindex=False` + successful existing run + records exist → **reuse** (no extraction)
- `force_reindex=False` + no successful run → **index fresh**
- `force_reindex=True` → **delete old records + reindex from scratch**

---

### 6.2 `document_table_index_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | FK → documents | |
| `content_hash` | str(64) | |
| `canonical_path` | str | |
| `status` | str | `indexing` \| `indexed` \| `no_table_evidence` \| `failed` |
| `table_evidence_count` | int | |
| `structured_table_count` | int | |
| `markdown_table_count` | int | |
| `table_like_text_count` | int | |
| `collection_name` | str | |
| `error_message` | str \| null | |
| `created_at` | datetime | |
| `completed_at` | datetime \| null | |

---

## 7. Extraction Strategy

### 7.1 Source reading order

1. `canonical.json` — parser name, page count, table/figure counts, artifact paths
2. `docling.json` (when present) → structured table extraction
3. `document.md` → markdown table detection + fallback table-like text detection
4. Latest `parse_quality_audits` row (if available) → **signal only** — populates risk flags and informs readiness labels; never used as a hard skip

> **Critical rule:** Phase 7A audit marking a document as `table_readiness=poor` does NOT prevent Phase 7B from attempting extraction. The audit reflects parser metadata, not actual text-span content. JPMorgan is fallback-parsed and audit-poor, yet its segment-results table exists as table-like text. Only skip extraction if `document.md` is missing or `text_chars_total ≈ 0`.

### 7.2 Structured Docling tables

Source: `docling.json["tables"]`

- Extract headers using heuristic: text-heavy first row → `has_header=True`; numeric-heavy or empty first row → `has_header=False`
- Serialize to `structured_json = {"headers": [...], "rows": [...]}`
- Page from `table["prov"][0]["page_no"]`
- `section_heading`: walk backward through `docling.json["texts"]` to find last `section_header` before this table's page
- Readiness: `good` if `has_header=True` AND `row_count >= 2` AND `column_count >= 2`; else `weak`
- `extraction_method = "docling"`, `source_kind = "docling_table"`, `source_chunk_id = null`

### 7.3 Markdown tables

Source: `document.md`

- Detect `| col |` patterns with separator row `|---|`
- Parse into structured representation if valid
- Dedup: skip if `span_hash` matches an already-extracted Docling table record (hash overlap), not page alone — a page may contain multiple tables
- `extraction_method = "markdown_regex"`, `source_kind = "markdown_table"`

### 7.4 Fallback table-like text spans

Source: `document.md` — always attempted regardless of audit verdict

**Page splitting:** Split on `<!-- page N -->` or `<!-- Page N -->` or `# Page N`. If no markers found: scan whole document, set `page_start=null`, `page_end=null`, add `risk_flags += ["missing_page_markers"]`.

**Span detection per page section:**
- Score lines for table-likeness: numeric density, multi-column alignment, financial keywords, currency values, year patterns, percentage values
- Group consecutive high-scoring lines into spans (min 3 lines)
- `max_chars_per_span = 10,000` — prevents large noisy page sections becoming one evidence object

**Dedup:** use `span_hash = SHA256(raw_text)` — skip if identical span already extracted from another path.

**`source_chunk_id`:** match nearest `TextChunkRecord` by `(content_hash, page_start, page overlap)` — null if no match found.

- `extraction_method = "table_like_text"`, `source_kind = "text_pattern"`, `table_readiness = "weak"`
- `risk_flags += ["fallback_parser_used"]` when applicable

### 7.5 Embedding text format

```
Document: <filename>
Page: <page_start>[-<page_end>]
Section: <section_heading or "">
Evidence Type: structured table | table-like text
Readiness: good | weak | poor
Table Title: <title or "">
Headers: <col1, col2, ...>
Rows:
<row1>
<row2>
...
```

For fallback: replace headers/rows block with:
```
Detected table-like text:
<raw_text>
```

---

## 8. Indexing Service

### 8.1 `TableIndexingService.index_canonical_document(canonical_path, *, force_reindex=False) -> TableIndexOutcome`

**Flow:**

```
1. If force_reindex=False AND successful DocumentTableIndexRun exists
   AND table_evidence_records exist for (document_id, content_hash):
     → return TableIndexOutcome(reused_existing=True)

2. Run extraction → list[TableEvidence]

3. Create DocumentTableIndexRun(status="indexing")

4. If zero evidence:
     → mark run status="no_table_evidence", table_evidence_count=0
     → return TableIndexOutcome(table_evidence_count=0)

5. If force_reindex=True:
     → delete Qdrant points for content_hash from docifer_table_evidence using
       `delete_table_evidence_by_content_hash(client, collection_name, content_hash)`
       — this function must be added to vector_store.py (uses qdrant_client.delete with FieldCondition filter)
     → delete existing table_evidence_records for (document_id, content_hash)

6. Compute deterministic point IDs: pre_computed_id[i] = uuid5(NAMESPACE_URL, table_id)
   Insert new table_evidence_records
     → qdrant_point_id = null  (not yet confirmed uploaded)
     → indexed_at = null

7. Embed table evidence texts in batches (OPENAI_EMBEDDING_BATCH_SIZE)

8. Upsert to docifer_table_evidence in batches (QDRANT_UPSERT_BATCH_SIZE)
     → use pre_computed_id as Qdrant point ID (deterministic — safe to upsert repeatedly)

9. Update each record: qdrant_point_id = pre_computed_id + indexed_at = now()

10. Mark DocumentTableIndexRun status="indexed" with counts + completed_at

11. On failure at any step:
      → mark run status="failed", error_message set
      → preserve any already-inserted DB records
      → records with qdrant_point_id=null are NOT served by retriever
```

### 8.2 Qdrant collection

Collection: `QDRANT_TABLE_COLLECTION=docifer_table_evidence` (settings, separate from text collection)

Payload per point:
```json
{
  "table_id": "...",
  "content_hash": "...",
  "document_id": "...",
  "canonical_path": "...",
  "page_start": 308,
  "page_end": 308,
  "table_type": "table_like_text",
  "source_kind": "text_pattern",
  "section_heading": "Segment Results",
  "table_readiness": "weak",
  "evidence_type": "table-like text",
  "extraction_method": "table_like_text",
  "span_hash": "...",
  "source_chunk_id": "...",
  "source_path": "...",
  "source_artifact_path": "..."
}
```

### 8.3 Settings additions

```
QDRANT_TABLE_COLLECTION=docifer_table_evidence
```

Reuse existing `QDRANT_UPSERT_BATCH_SIZE` and `OPENAI_EMBEDDING_BATCH_SIZE`.

### 8.4 API

```
POST /index/tables
{
  "canonical_path": "datasets/processed/.../canonical.json",
  "force_reindex": false
}
```

Response:
```json
{
  "document_id": "...",
  "content_hash": "...",
  "status": "indexed",
  "table_evidence_count": 12,
  "structured_table_count": 2,
  "markdown_table_count": 0,
  "table_like_text_count": 10,
  "collection_name": "docifer_table_evidence",
  "reused_existing": false
}
```

---

## 9. Table Retrieval

### 9.1 `TableRetriever`

Supports modes: `table_dense`, `table_bm25`, `table_hybrid`

v1 primary mode: `table_hybrid`

**Guard:** only return records where `qdrant_point_id IS NOT NULL` (failed-index records excluded).

**`content_hash` filter:** always applied when provided — scopes results to one document.
When `content_hash=null`, table retrieval searches all indexed documents (global scope). Debug output must include `"content_hash_scope": "all"` in this case. Phase 7B validation tests should use a specific `content_hash` to keep results controlled.

### 9.2 Boosting rules

Boost table candidates when question contains:
- Exact year match (e.g. `2025`, `2024`)
- Financial terms: `net income`, `revenue`, `segment`, `assets`, `liabilities`
- Row labels matching section headings

### 9.2b BM25 lexical corpus text

BM25 scores over the following concatenated field per record:

```
{title} {caption} {section_heading} {raw_text} {markdown_table}
```

Null fields omitted. Do not score over `structured_json` directly — serialize rows to plain text first if included.

### 9.3 `TableQueryResult` schema

```python
@dataclass(frozen=True)
class TableQueryResult:
    table_id: str
    score: float
    dense_score: float | None
    lexical_score: float | None
    table_type: str           # "structured" | "table_like_text"
    source_kind: str
    page_start: int | None
    page_end: int | None
    raw_text: str
    section_heading: str | None
    table_readiness: str
    document_id: str
    content_hash: str
    source_path: str                  # raw PDF source path
    source_artifact_path: str         # canonical.json path
    source_chunk_id: str | None
```

---

## 10. Query Integration

### 10.1 Updated request schema

```json
{
  "question": "...",
  "content_hash": null,
  "top_k": 4,
  "retrieval_mode": "hybrid",
  "evidence_mode": "text",
  "table_top_k": 4,
  "verify_citations": false
}
```

**`evidence_mode` is the sole authority:**
- `"text"` — text retrieval only (default; preserves existing behaviour)
- `"table"` — table retrieval only
- `"auto"` — text always; table retrieval added when table intent detected

**`table_top_k`:** clamped to 1–10 (Pydantic `ge=1, le=10`), default 4.

### 10.2 Table intent detection

Run table retrieval when:
- Explicit `table`, `row`, or `column` keyword present, **OR**
- Numeric/year/currency term present (`20\d\d`, `\$`, `billion`, `million`, `%`) **AND** financial/comparison term present (`net income`, `revenue`, `segment`, `total`, `assets`, `highest`, `lowest`, `compare`)

**Not triggered by single non-numeric terms** (e.g. `"which"` alone, `"total message"` without numeric context).

Debug output includes:
```json
{
  "table_intent_detected": true,
  "table_intent_score": 4,
  "table_intent_matches": ["net income", "segment", "2025", "highest"],
  "content_hash_scope": "specific",
  "table_retrieval_latency_ms": 123,
  "table_indexed_collection": "docifer_table_evidence",
  "table_retrieved_count": 4
}
```

### 10.3 Evidence aggregation (auto mode)

1. Text retrieval (always)
2. Table intent detection
3. If intent detected: table retrieval
4. Merged evidence → answer generation prompt:

```
Text evidence:
[C1] <text chunk>
[C2] <text chunk>

Table evidence:
[T1] <table evidence>
[T2] <table evidence>
```

5. Citation extraction regex: `\[(C\d+|T\d+)\]`
6. Citation verifier receives both text and table as `GroundingEvidence` objects

### 10.4 `GroundingEvidence` adapter for tables

Table evidence converted explicitly:
```python
GroundingEvidence(
    citation_id="T1",
    text=embedding_text,        # formatted table text
    source=f"table:{table_id}, {source_path}, page {page_start}"
)
```

No new verifier method needed — existing interface accepts this.

### 10.5 Extended `QueryOutcome`

```python
@dataclass(frozen=True)
class QueryOutcome:
    answer: str
    citations: list[QueryCitation]              # text citations (backward-compatible)
    table_citations: list[TableCitation]        # NEW
    evidence: list[RetrievedChunk]              # text evidence
    table_evidence: list[TableQueryResult]      # NEW
    unused_evidence: list[RetrievedChunk]
    unused_table_evidence: list[TableQueryResult]  # NEW
    citation_verification: CitationGroundingVerdict | None
    debug: dict
```

### 10.6 `TableCitation` schema

```python
@dataclass(frozen=True)
class TableCitation:
    citation_id: str          # "T1", "T2"
    evidence_type: str        # "table"
    table_id: str
    source_path: str
    source_artifact_path: str
    page_start: int | None
    page_end: int | None
    table_type: str
    table_readiness: str
    score: float
```

### 10.7 No-table-evidence safe abstention

When `evidence_mode="table"` and table retrieval returns empty:
```
answer = "I could not find table evidence in the indexed documents to answer this question."
table_citations = []
table_evidence = []
```

No hallucinated table citation.

---

## 11. Testing Plan

### Unit — extraction

- Structured Docling table → correct `TableEvidence`: headers, rows, `table_type=structured`, `source_kind=docling_table`
- Markdown table in `document.md` → `source_kind=markdown_table`, `has_header=True`
- Table-like text span detected → `table_type=table_like_text`, `table_readiness=weak`
- Fallback doc with no table-like lines → zero evidence or `poor` readiness
- Header detection: numeric-heavy first row → `has_header=False`
- Stable IDs deterministic: same input → same `table_id` + `span_hash`
- Dedup: Docling table and markdown table with same `span_hash` → only one record

### Unit — models

- `table_evidence_records` persists all fields including nullable
- `document_table_index_runs` status transitions: `indexing` → `indexed` / `no_table_evidence` / `failed`
- Reindex: old records deleted, new records inserted, `qdrant_point_id=null` until Qdrant step
- `qdrant_point_id = uuid5(NAMESPACE_URL, table_id)` is stable across runs

### Unit — retrieval

- Table BM25 retrieves exact financial term match
- Table hybrid combines dense + lexical scores, returns top-k
- `content_hash` filter scopes results to one document
- Records with `qdrant_point_id=null` not returned

### Unit — query

- `evidence_mode=text` → zero table retrieval calls
- `evidence_mode=table` → no text retrieval
- `evidence_mode=auto` + table-intent question → `table_intent_detected=True`
- `evidence_mode=auto` + non-table question → `table_intent_detected=False`
- **False positive test:** `"Which strategy does the report recommend for upper-middle-income countries?"` → `table_intent_detected=False`
- **Compound signal test:** `"Which segment had the highest 2025 net income?"` → `table_intent_matches` includes `["segment", "highest", "2025", "net income"]`
- Answer generation prompt has separate "Text evidence" / "Table evidence" sections
- `[T1]` parsed → `TableCitation`; `[C1]` → `QueryCitation`
- **Mixed citation test:** answer uses `[C1]` + `[T1]` → one `QueryCitation` + one `TableCitation`; unused evidence computed correctly
- **No-table-evidence test:** `evidence_mode=table` + empty retrieval → safe abstention, no hallucinated citation
- `unused_table_evidence` contains non-cited table chunks

### Unit — citation verifier

- Table evidence converted to `GroundingEvidence` correctly
- Supported numeric table claim → verdict `supported`
- Unsupported numeric claim → verdict `unsupported`

### Unit — Qdrant failure path

- Qdrant upsert fails → DB records remain with `qdrant_point_id=null`
- `document_table_index_runs.status = "failed"`, `error_message` set
- Retrieval query excludes `qdrant_point_id=null` records

### Integration (in-memory SQLite + tmp_path)

- Index one Docling structured table doc → DB records + Qdrant points + `indexed_at` set
- Index one fallback doc → `table_like_text` records, `table_readiness=weak`
- Query with JPMorgan-style segment fixture → table citation present in response
- Force reindex → old Postgres records replaced; verify stale Qdrant points removed via `delete_table_evidence_by_content_hash`

### Evaluation

- Run Phase 6.5 baseline (`evidence_mode=text`, hybrid) vs Phase 7B (`evidence_mode=auto`) on table-category golden questions
- Track: answer correctness, citation presence, `table_citation` present, verifier verdict, latency P50/P95
- **Gate:** JPMorgan QA-008 succeeds at `table_top_k=4`

---

## 12. Exit Criteria

Phase 7B is complete when:

- `POST /index/tables` works for at least one Docling-structured doc and one fallback-parsed doc
- `table_evidence_records` and `document_table_index_runs` persist correctly
- Table evidence indexed in `docifer_table_evidence` Qdrant collection
- `/query` with `evidence_mode=table` or `evidence_mode=auto` returns table citations
- `table_citations` separate from `citations` in response
- Citation verifier evaluates table-supported claims
- JPMorgan QA-008 succeeds at `table_top_k=4`
- All tests pass
- `docs/phase7b-table-intelligence.md` written

---

## 13. Execution Order

| Task | Deliverable |
|---|---|
| 1 — DB models | `table_evidence_records` + `document_table_index_runs` + schema registration + tests |
| 2 — Extraction | Structured Docling + markdown + fallback table-like text + stable IDs + tests |
| 3 — Indexing | `TableIndexingService` + `POST /index/tables` + idempotency + `delete_table_evidence_by_content_hash` in `vector_store.py` + tests |
| 4 — Retrieval | `TableRetriever` dense/bm25/hybrid + `qdrant_point_id=null` guard + tests |
| 5 — Query integration | `evidence_mode`, intent detection, merged evidence, `TableCitation`, abstention + tests |
| 6 — Citation verifier | `GroundingEvidence` adapter for table evidence + verifier tests |
| 7 — Evaluation | Benchmark table-category questions, compare Phase 6.5 vs 7B, document results |

---

## 14. Phase 7B Scope Framing

Phase 7B improves **retrieval and evidence packaging**, not deterministic table computation. `reasoning.py` is deferred.

If JPMorgan QA-008 succeeds, the correct framing is:

> "The correct table evidence is retrieved at lower table depth and the LLM can answer from it."

Not: "Docifer computes over tables." That distinction matters — success depends on retrieval quality delivering the right evidence to the model, not on structured computation.

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| Fallback text spans are noisy | Lexical boosting; preserve raw evidence; mark readiness `weak`; rely on citation verifier |
| Structured Docling tables limited to one corpus document | Fallback path is first-class, not degraded |
| Table intent over-triggers | Compound signal requirement; false-positive test coverage |
| Latency increases | Table retrieval only on intent-detected questions; cap `table_top_k`; debug timing |
| Overbuilding into analytics engine | No SQL, no complex calculations, only benchmark-driven table QA; `reasoning.py` deferred |
| Stale Qdrant vectors after reindex | `delete_table_evidence_by_content_hash` on force reindex; retriever guards on `qdrant_point_id IS NOT NULL` as secondary safety |

---

## 15. Documentation Plan

Create: `docs/phase7b-table-intelligence.md`

Update:
- `backend/README.md`
- `evals/README.md`
- `docs/session-changes-2026-05-20.md`
