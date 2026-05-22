# Docifer Evaluations

Evaluation run outputs are written locally under:

```text
evals/runs/<run-name>/
```

Each run contains:

- `results.jsonl`
- `summary.json`
- `report.md`
- `ragas_input.jsonl`

The `evals/runs/` directory is ignored by git because it contains generated local results and may include model outputs. Commit curated reports under `docs/` when a baseline needs to be preserved.

## Phase 7B table checks

Phase 7B table retrieval is validated through focused backend tests and targeted real queries before adding a broader table-category eval runner. The current gate question is the JPMorgan segment net income case:

```text
Which segment had the highest 2025 net income?
```

Validated configuration:

```json
{
  "evidence_mode": "table",
  "table_top_k": 4,
  "verify_citations": true
}
```

The successful Phase 7B validation returns table citations from the JPMorgan fallback table evidence and a supported citation-grounding verdict.

## Phase 7C table reasoning checks

Phase 7C keeps the same gate question but adds deterministic observation extraction before answer generation.

Expected result:

```text
Commercial & Investment Bank had the highest 2025 net income at $27,761 million.
```

The successful Phase 7C validation returns:

- one table citation,
- `table_reasoning_status = supported`,
- selected observation `Commercial & Investment Bank`,
- selected value `$27,761 million`,
- verifier verdict `supported`.

## Phase 7D visual retrieval checks

Phase 7D validates visual retrieval before multimodal interpretation. The current checks focus on whether the system can render page artifacts, persist visual evidence records, index them into `docifer_visual_evidence`, and retrieve relevant candidates for chart/figure/page questions.

Expected `/retrieve/visuals` behavior:

- returns visual candidates, not generated answers,
- includes `artifact_path` values that point to rendered page JPEGs,
- separates dense, BM25 lexical, and hybrid scores,
- exposes source metadata such as `document_id`, `content_hash`, source path, canonical artifact path, page range, caption, figure label, and nearby text,
- supports `visual_dense`, `visual_bm25`, and `visual_hybrid` retrieval modes.

Phase 7D is complete when a real parsed PDF can be visually indexed and queried through the API with inspectable rendered artifacts in `datasets/processed/<hash>/<job>/visuals/pages/`.
