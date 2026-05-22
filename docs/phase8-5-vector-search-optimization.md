# Phase 8.5 - ANN / Vector Search Optimization

Phase 8.5 adds controls and observability for Qdrant vector search. Docifer already uses Qdrant ANN search; this phase makes the exact-vs-ANN tradeoff measurable and debuggable.

## Configuration

```text
QDRANT_EXACT_SEARCH=false
QDRANT_SEARCH_EF=64
QDRANT_HNSW_M=16
QDRANT_HNSW_EF_CONSTRUCT=100
QDRANT_CREATE_PAYLOAD_INDEXES=true
```

Meaning:

| Setting | Purpose |
|---|---|
| `QDRANT_EXACT_SEARCH` | Toggle exact vector search for diagnostic ablations. |
| `QDRANT_SEARCH_EF` | Runtime HNSW beam size. Higher can improve recall at higher latency. |
| `QDRANT_HNSW_M` | HNSW graph connectivity for newly created collections. |
| `QDRANT_HNSW_EF_CONSTRUCT` | HNSW build-time quality for newly created collections. |
| `QDRANT_CREATE_PAYLOAD_INDEXES` | Create filter payload indexes during collection ensure/indexing. |

Runtime search params apply to text, table, and visual dense retrieval paths.

## Payload Indexes

Text collection:

- `content_hash`
- `document_id`
- `source_path`
- `page_start`

Table collection:

- `content_hash`
- `document_id`
- `table_type`
- `table_readiness`
- `page_start`

Visual collection:

- `content_hash`
- `document_id`
- `visual_type`
- `source_kind`
- `page_start`

Payload indexes are ensured during indexing. Existing collections are not recreated automatically; run an indexing path against existing collections to create any missing indexes.

## API Observability

List configured vector collections:

```text
GET /vector/collections
```

Inspect one collection:

```text
GET /vector/collections/{collection_name}/stats
```

Stats response fields include:

- `collection_name`
- `points_count`
- `indexed_vectors_count`
- `vector_size`
- `distance`
- `payload_indexes`
- `status`
- `hnsw_m`
- `hnsw_ef_construct`

`/ready` now includes nonfatal collection-level checks:

```json
{
  "status": "ready",
  "checks": {
    "postgres": "ok",
    "qdrant": "ok",
    "text_collection": "ok",
    "table_collection": "missing",
    "visual_collection": "missing"
  }
}
```

Missing collections do not make `/ready` fail because fresh local environments may not have all indexes yet.

## Query Debug

Text `/query` debug now includes:

- `vector_search_exact`
- `vector_search_ef`
- `vector_collection`

`/retrieve/visuals` includes the same vector search fields when `debug=true`.

## Ablation Commands

ANN default:

```powershell
$env:QDRANT_EXACT_SEARCH="false"
$env:QDRANT_SEARCH_EF="64"
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase8_5_ann_default --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations
```

Exact search:

```powershell
$env:QDRANT_EXACT_SEARCH="true"
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase8_5_exact_search --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations
```

Higher EF:

```powershell
$env:QDRANT_EXACT_SEARCH="false"
$env:QDRANT_SEARCH_EF="128"
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase8_5_ann_ef128 --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations
```

Compare:

- expected-answer token recall,
- citation presence,
- false abstention rate,
- P50/P95 latency,
- category-level recall.

## Validation

Automated validation:

```text
Phase 8.5 focused tests: 6 passed
Full backend suite: 115 passed, 1 xfailed
Compile check: passed
```

Local in-memory Qdrant emits a warning that payload indexes have no effect locally. That is expected; payload indexes matter when using the Qdrant server.
