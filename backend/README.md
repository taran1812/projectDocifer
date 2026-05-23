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
- `POST /index/visuals`
- `POST /retrieve/visuals`
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

## Phase 7D visual evidence retrieval

Phase 7D adds retrieval-only visual evidence support. PDFs are rendered into inspectable JPEG page artifacts, and visual evidence records are indexed into a dedicated Qdrant collection:

```text
docifer_visual_evidence
```

Visual evidence types:

- `page_render`: one rendered page JPEG per PDF page
- `docling_picture`: Docling picture metadata linked to the rendered source page
- `figure_candidate`: text-detected figure/chart references when structured pictures are unavailable

Index visual evidence for a parsed document:

```json
{
  "canonical_path": "datasets/processed/8109582811fe/55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff/canonical.json",
  "force_reindex": false
}
```

Retrieve visual candidates without image interpretation:

```json
{
  "question": "Which figure shows economic growth?",
  "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
  "top_k": 5,
  "retrieval_mode": "visual_hybrid",
  "debug": true
}
```

`/retrieve/visuals` returns candidate visual records with artifact paths, page metadata, captions or nearby text, and `dense_score`, `lexical_score`, and `hybrid_score`. Phase 7D deliberately does not perform multimodal interpretation.

Detailed notes are in:

```text
docs/phase7d-visual-evidence-retrieval.md
```

Validated Phase 7D result:

```text
Worldbank2024.pdf
page_render_count = 4
figure_candidate_count = 0
visual_record_count = 7
retrieved visual candidates = 5
```

All returned visual candidate artifact paths pointed to existing rendered JPEG files. Phase 7D is merged on `master` at commit `5333eeb`.

## Phase 7E structured multimodal interpretation

Phase 7E adds narrow, schema-driven interpretation of retrieved visual evidence. It uses Phase 7D candidates as input, sends only selected rendered artifacts to the vision provider, and returns structured observations plus visual citations.

Configuration:

```text
OPENAI_VISION_MODEL=gpt-4o-mini
```

`/query` now supports:

```text
evidence_mode="visual"
visual_top_k=3
```

Example:

```json
{
  "question": "Which chart shows the main findings?",
  "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
  "evidence_mode": "visual",
  "visual_top_k": 3,
  "verify_citations": true
}
```

Visual answers cite retrieved artifacts with `[V1]`, `[V2]`, etc. Query responses include:

- `visual_citations`
- `visual_evidence`
- `visual_observations`
- `unused_visual_evidence`

The visual provider returns structured observations with extracted facts, visible entities, numeric values, confidence, limitations, and abstention reasons. If a chart is unclear or unreadable, the answer safely abstains instead of guessing.

Detailed notes are in:

```text
docs/phase7e-structured-multimodal-interpretation.md
```

## Phase 7G reliability hardening

Phase 7G and 7G.1 added:

- **Rate-limit retry/backoff** — all three OpenAI call sites (`generate_grounded_answer`, `verify_citation_grounding`, `interpret_visual_evidence`) retry up to 2 times on HTTP 429 with exponential backoff (~2s then ~4s). After max retries a `ProviderRateLimitError` is raised and the eval runner marks the result `status="provider_failed"` rather than `"failed"`.

- **Abstention-triggered text retry** — when the model abstains on a text/auto query but evidence was retrieved, one retry fires with `top_k * 2` (capped at 8) to give the model a broader evidence set. Debug fields: `abstention_retry_triggered`, `initial_top_k`, `retry_top_k`, `initial_answer_was_abstention`, `retry_answer_was_abstention`.

- **Table-mode retry** — when `evidence_mode="table"` and initial retrieval returns 0 results, one retry fires with `table_top_k * 2`.

- **Tighter abstention detection** — `_detect_abstention` now uses first-person/system-inability phrases only, normalises curly apostrophes before contraction expansion, and splits the eval metric into `true_abstention_accuracy` and `false_abstention_rate`.

- **Mixed Modality routing** — `resolve_evidence_mode` now checks `"mixed" in category` before visual/chart/figure terms so Mixed Modality questions route to `auto` mode correctly.

Current test suite: **103 passed, 1 xfailed**

Current full-corpus eval result (`phase7g1_full_40q`, 40/40 questions):

```json
{
  "abstention_correct_rate": 0.5,
  "true_abstention_accuracy": 0.75,
  "false_abstention_rate": 0.0556,
  "citation_presence_rate": 0.975,
  "average_expected_answer_token_recall": 0.6625,
  "failed": 0
}
```

## Phase 8 cross-encoder reranker

Phase 8 adds an optional text-only reranker after dense, BM25, or hybrid retrieval. The default `/query` path is unchanged unless reranking is requested.

Configuration:

```text
RERANKER_ENABLED=false
RERANKER_MODEL=BAAI/bge-reranker-base
RERANKER_CANDIDATE_TOP_N=20
RERANKER_DEVICE=auto
RERANKER_BATCH_SIZE=8
RERANKER_MAX_LENGTH=512
```

Example reranked query:

```json
{
  "question": "What do middle-income countries need to do to escape the middle-income trap?",
  "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
  "top_k": 4,
  "retrieval_mode": "hybrid",
  "evidence_mode": "text",
  "verify_citations": true,
  "rerank": true,
  "rerank_top_n": 20
}
```

When enabled, Docifer retrieves `rerank_top_n` text candidates, reranks them with the local cross-encoder, and sends only the final `top_k` to answer generation. If the model is unavailable or inference fails, the query falls back to the original retrieval order and records the failure in `debug`.

Reranker diagnostics include:

- `rerank_used`
- `reranker_status`
- `rerank_candidate_count`
- `rerank_latency_ms`
- `pre_rerank_top_chunk_ids`
- `post_rerank_top_chunk_ids`

Validated Phase 8 eval results:

```text
Phase 7G.1 baseline recall:          0.6625
BAAI/bge-reranker-base recall:       0.6883
MiniLM fallback recall:              0.6750
```

Both reranker runs kept `failed = 0`, `false_abstention_rate = 0.0556`, and `citation_presence_rate = 0.95`. Reranking remains disabled by default because the quality gain is real but latency increases.

Detailed notes are in:

```text
docs/phase8-cross-encoder-reranker.md
```

## Phase 8.5 vector search optimization

Phase 8.5 adds Qdrant search controls and collection observability. Docifer already uses Qdrant ANN search; these settings let you compare ANN, exact search, and higher-HNSW-EF search behavior.

Configuration:

```text
QDRANT_EXACT_SEARCH=false
QDRANT_SEARCH_EF=64
QDRANT_HNSW_M=16
QDRANT_HNSW_EF_CONSTRUCT=100
QDRANT_CREATE_PAYLOAD_INDEXES=true
```

New endpoints:

```text
GET /vector/collections
GET /vector/collections/{collection_name}/stats
```

`/ready` now reports nonfatal collection-level checks for text, table, and visual vector collections. `/query` debug includes `vector_search_exact`, `vector_search_ef`, and `vector_collection`.

Detailed notes are in:

```text
docs/phase8-5-vector-search-optimization.md
```

## Phase 9 multi-document query mode

`POST /query` now supports explicit query scope:

- `scope="single"`: existing default; requires `content_hash` or exactly one document identifier.
- `scope="doc_ids"`: searches selected starter-corpus IDs such as `DOC-005` and `DOC-007`.
- `scope="all"`: explicitly searches every indexed document eligible for the requested evidence type.

Selected-document query:

```json
{
  "question": "Compare the growth strategies in these reports.",
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

Multi-document responses expose document identity on evidence and citations, plus `documents_searched`, `documents_used`, and `evidence_by_document` in `debug`.

Existing text documents should be reindexed with `force_reindex=true` so prior Qdrant points receive the new `document_id` payload field. Detailed notes are in:

```text
docs/phase9-multi-document-query.md
```

Validated corpus state: all 12 indexed text documents were force-reindexed, with `10,113` Qdrant text points carrying `document_id`. Selected-document and explicit all-document validation queries both returned supported citations from `DOC-005` and `DOC-007`.

## Phase 10 document registry APIs

Phase 10 exposes typed inspection APIs for the Phase 9 document identity and
index state:

```text
GET /documents
GET /documents/{document_id}
GET /documents/by-doc-id/{doc_id}
GET /documents/by-content-hash/{content_hash}
GET /documents/{document_id}/indexes
GET /documents/{document_id}/audit
GET /documents/{document_id}/artifacts
```

The document API reuses the Phase 9 `DOC-001` through `DOC-012` identity
mapping. Text, table, and visual readiness is represented with explicit
statuses: `indexed`, `not_indexed`, `not_available`, `failed`, and `unknown`.
Artifact responses include filesystem existence and provenance metadata rather
than raw file contents.

Validated current-corpus result:

```text
Documents visible: 12
Text status: indexed for 12
Table status: indexed for 10, not_indexed for 2
Visual status: indexed for 9, not_indexed for 3
Backend suite: 134 passed, 1 xfailed
```

Detailed endpoint and validation notes are in:

```text
docs/phase10-document-registry-apis.md
```
