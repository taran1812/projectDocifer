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

Current validated Phase 7D result:

```text
Visual suite: 22 passed
Full backend suite: 78 passed, 1 xfailed
Worldbank2024.pdf visual_record_count: 7
Worldbank2024.pdf retrieved visual candidates: 5
```

This validates the retrieval substrate only. Chart reading and image-grounded answer generation remain deferred to the next phase.

## Phase 7E visual interpretation checks

Phase 7E routes chart/visual golden questions through structured visual interpretation.

The evaluation runner now supports:

```text
--evidence-mode category|text|table|visual|auto
```

Default `category` routing sends:

- chart/visual/figure/image/graph questions to `visual`,
- table questions to `table`,
- mixed questions to `auto`,
- text questions to `text`.

Visual metrics use combined citation and retrieval counts across text, table, and visual evidence. Visual contexts exported for later scoring come from structured visual observations, not free-form image narration.

Suggested Phase 7E visual run:

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase7e_visual_questions --evidence-mode visual --retrieval-mode hybrid --verify-citations
```

Automated validation completed during implementation:

```text
Visual + eval focused tests: 28 passed
Full backend suite: 86 passed, 1 xfailed
```

## Phase 7F — First Full 40-Question Eval

After indexing all 12 corpus documents, the eval can run against all 40 golden questions with no skips.

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase7f_full_40q --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations
```

Result: `40 evaluated, 0 failed, recall=0.647, citation=0.925, abstention_correct=0.375`

## Phase 7G / 7G.1 — Abstention Hardening

Phase 7G added rate-limit retry/backoff, tighter abstention detection (contractions, curly apostrophes), Mixed Modality routing fix, and abstention-triggered evidence expansion retry.

Phase 7G.1 refined the marker list (removed broad phrases like "does not include" that appear in valid answers), split the abstention metric into `true_abstention_accuracy` and `false_abstention_rate`, and added table-mode retry.

Latest eval run: `phase7g1_full_40q`

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase7g1_full_40q --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations
```

Result:

```json
{
  "evaluated": 40,
  "failed": 0,
  "abstention_correct_rate": 0.5,
  "true_abstention_accuracy": 0.75,
  "false_abstention_rate": 0.0556,
  "citation_presence_rate": 0.975,
  "average_expected_answer_token_recall": 0.6625
}
```

The summary JSON now includes `true_abstention_accuracy` and `false_abstention_rate` as separate metrics in addition to the combined `abstention_correct_rate`.

## Phase 8 - Cross-Encoder Reranker Checks

Phase 8 adds optional text reranking. The baseline path remains unchanged unless `--rerank` is used.

Baseline run:

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase8_baseline_hybrid --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations
```

Reranked run:

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase8_hybrid_reranker --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations --rerank --rerank-top-n 20
```

Compare the reranked run against `phase7g1_full_40q`:

- `average_expected_answer_token_recall`
- `citation_presence_rate`
- `true_abstention_accuracy`
- `false_abstention_rate`
- `latency_ms_p50`
- `latency_ms_p95`
- category-level recall in `report.md`

Reranker failures should not create failed eval rows. They should fall back to original retrieval and appear in query debug as `reranker_status = "unavailable"` or `"failed"`.

Validated Phase 8 results:

| Run | Model | Recall | Citation | False Abstention | True Abstention | P50 Latency | P95 Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| `phase7g1_full_40q` | none | 0.6625 | 0.975 | 0.0556 | 0.75 | 3327.75 | 12144.30 |
| `phase8_hybrid_reranker` | `BAAI/bge-reranker-base` | 0.6883 | 0.950 | 0.0556 | 1.00 | 8172.52 | 17959.53 |
| `phase8_hybrid_reranker_minilm` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 0.6750 | 0.950 | 0.0556 | 1.00 | 4508.78 | 13809.00 |

Phase 8 is valid as optional. Keep `RERANKER_ENABLED=false` by default until reranking can reach the `0.70+` recall target with acceptable latency.

## Phase 8.5 - Vector Search Ablations

Phase 8.5 measures Qdrant ANN/exact behavior. The goal is not to replace Qdrant, but to make vector search settings visible and comparable.

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

- `average_expected_answer_token_recall`
- `citation_presence_rate`
- `false_abstention_rate`
- `latency_ms_p50`
- `latency_ms_p95`
- category-level recall

Use `GET /vector/collections` and `GET /vector/collections/{collection_name}/stats` to confirm point counts and payload index status before interpreting eval results.
