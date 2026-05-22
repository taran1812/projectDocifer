# Phase 7D - Visual Evidence Retrieval

Phase 7D adds visual evidence indexing and retrieval without multimodal interpretation. The goal is to retrieve the right rendered page, figure, chart, or visual candidate first. Image understanding is intentionally deferred to a later phase.

## Scope

Implemented capabilities:

- Render parsed PDF pages into JPEG artifacts under each processed document directory.
- Extract visual evidence records from page renders, Docling pictures, and fallback text references.
- Persist visual evidence metadata in SQL tables.
- Index visual records into the dedicated Qdrant collection `docifer_visual_evidence`.
- Retrieve visual candidates with dense, BM25, or hybrid scoring.
- Expose retrieval-only API endpoints for indexing and candidate search.

Out of scope for this phase:

- Multimodal interpretation of images.
- Chart value extraction.
- Figure caption rewriting.
- ColQwen or other heavy visual embedding providers as a completion dependency.

## New API Endpoints

### `POST /index/visuals`

Indexes visual evidence for an existing canonical parse artifact.

```json
{
  "canonical_path": "datasets/processed/<hash>/<job-id>/canonical.json",
  "force_reindex": false
}
```

Response fields:

- `document_id`
- `content_hash`
- `status`
- `page_render_count`
- `figure_candidate_count`
- `visual_record_count`
- `collection_name`
- `reused_existing`

### `POST /retrieve/visuals`

Retrieves visual candidates only. It does not generate an answer.

```json
{
  "question": "Which figure shows economic growth?",
  "content_hash": "<optional-content-hash>",
  "top_k": 5,
  "retrieval_mode": "visual_hybrid",
  "debug": true
}
```

Supported retrieval modes:

- `visual_dense`
- `visual_bm25`
- `visual_hybrid`

Candidate responses include:

- `visual_id`
- `document_id`
- `content_hash`
- `visual_type`
- `source_kind`
- `artifact_path`
- `page_start`
- `page_end`
- `caption`
- `section_heading`
- `nearby_text`
- `figure_label`
- `visual_readiness`
- `source_path`
- `source_artifact_path`
- `dense_score`
- `lexical_score`
- `hybrid_score`

## Visual Evidence Types

`page_render` records are created for every page. These provide the reliable fallback path when a PDF does not expose clean figure structure.

`docling_picture` records use Docling picture metadata and caption references when available. In Phase 7D, they link to the rendered page artifact rather than cropped figure images.

`figure_candidate` records are fallback text-detected references such as `Figure 1`, `Chart 2`, or `Exhibit 3` when structured pictures are unavailable.

## Artifact Layout

Rendered page artifacts are written beside the canonical parse outputs:

```text
datasets/processed/<hash-prefix>/<job-id>/visuals/pages/page_0001.jpg
datasets/processed/<hash-prefix>/<job-id>/visuals/pages/page_0002.jpg
```

The API returns these paths so candidates can be inspected directly during debugging and later frontend work.

## Storage

Phase 7D adds two SQL tables:

- `visual_evidence_records`
- `document_visual_index_runs`

The Qdrant collection is:

```text
docifer_visual_evidence
```

The corresponding environment setting is:

```text
QDRANT_VISUAL_COLLECTION=docifer_visual_evidence
```

## Validation

Focused tests cover:

- visual settings,
- visual schemas,
- database persistence,
- Qdrant visual upsert/search/delete,
- PDF page rendering,
- Docling picture extraction,
- page-render evidence creation,
- fallback figure candidates,
- visual indexing idempotency,
- dense/BM25/hybrid retrieval,
- `/index/visuals`,
- `/retrieve/visuals`.

The Phase 7D gate is satisfied when these tests pass and a real parsed PDF can be visually indexed and queried with returned candidates pointing to existing JPEG page artifacts.
