# Phase 8 - Cross-Encoder Reranker

Phase 8 adds an optional text-only reranking layer after dense, BM25, or hybrid retrieval.

The default retrieval path is unchanged. When reranking is enabled, Docifer retrieves a larger candidate pool, scores each question/chunk pair with a local cross-encoder model, and sends only the reranked final `top_k` evidence to answer generation.

## Configuration

```text
RERANKER_ENABLED=false
RERANKER_MODEL=BAAI/bge-reranker-base
RERANKER_CANDIDATE_TOP_N=20
RERANKER_DEVICE=auto
RERANKER_BATCH_SIZE=8
RERANKER_MAX_LENGTH=512
```

Recommended fallback model if the default is too slow or heavy:

```text
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
```

The model is loaded lazily only when reranking is requested. If model loading or inference fails, `/query` falls back to the original retrieval order and records the failure in `debug`.

## Query Usage

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

Rules:

- `rerank=false` or omitted keeps the existing retrieval flow.
- `rerank=true` retrieves `rerank_top_n` candidates, reranks them, and returns the final `top_k`.
- `rerank_top_n` must be greater than or equal to `top_k`.
- `rerank_top_n` is capped at 50.

## Response Metadata

Text evidence and text citations may include:

- `rerank_score`
- `pre_rerank_rank`
- `post_rerank_rank`
- `reranker_model`

Debug output includes:

- `rerank_requested`
- `rerank_used`
- `reranker_status`
- `reranker_model`
- `rerank_candidate_top_n`
- `rerank_candidate_count`
- `rerank_latency_ms`
- `pre_rerank_top_chunk_ids`
- `post_rerank_top_chunk_ids`
- `rerank_error`

## Evaluation

Baseline:

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner `
  --run-name phase8_baseline_hybrid `
  --top-k 4 `
  --retrieval-mode hybrid `
  --evidence-mode category `
  --verify-citations
```

Reranked:

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner `
  --run-name phase8_hybrid_reranker `
  --top-k 4 `
  --retrieval-mode hybrid `
  --evidence-mode category `
  --verify-citations `
  --rerank `
  --rerank-top-n 20
```

Compare:

- `average_expected_answer_token_recall`
- `citation_presence_rate`
- `true_abstention_accuracy`
- `false_abstention_rate`
- `latency_ms_p50`
- `latency_ms_p95`
- category-level recall in `report.md`

## Success Criteria

Phase 8 is valid if:

- hard failures stay at `0`,
- `citation_presence_rate >= 0.95`,
- expected-answer token recall improves over the Phase 7G.1 baseline of `0.6625`,
- false abstention rate stays at or below `0.08`,
- reranker failures fall back safely.

If recall does not improve, the reranker should remain optional and the eval result should be documented honestly.

## Validation Results

Baseline from Phase 7G.1:

```json
{
  "run_name": "phase7g1_full_40q",
  "evaluated": 40,
  "failed": 0,
  "average_expected_answer_token_recall": 0.6625,
  "citation_presence_rate": 0.975,
  "false_abstention_rate": 0.0556,
  "true_abstention_accuracy": 0.75,
  "latency_ms_p50": 3327.75,
  "latency_ms_p95": 12144.3
}
```

Primary reranker run:

```json
{
  "run_name": "phase8_hybrid_reranker",
  "model": "BAAI/bge-reranker-base",
  "evaluated": 40,
  "failed": 0,
  "average_expected_answer_token_recall": 0.6883,
  "citation_presence_rate": 0.95,
  "false_abstention_rate": 0.0556,
  "true_abstention_accuracy": 1.0,
  "latency_ms_p50": 8172.52,
  "latency_ms_p95": 17959.53
}
```

Fallback reranker run:

```json
{
  "run_name": "phase8_hybrid_reranker_minilm",
  "model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
  "evaluated": 40,
  "failed": 0,
  "average_expected_answer_token_recall": 0.675,
  "citation_presence_rate": 0.95,
  "false_abstention_rate": 0.0556,
  "true_abstention_accuracy": 1.0,
  "latency_ms_p50": 4508.78,
  "latency_ms_p95": 13809.0
}
```

## Verdict

Phase 8 is valid as an optional backend improvement:

- both reranker runs evaluated all 40 questions with `failed = 0`,
- both improved expected-answer token recall over `0.6625`,
- both kept citation presence at the `0.95` acceptance floor,
- both kept false abstentions unchanged at `0.0556`,
- both improved true abstention accuracy to `1.0`.

The reranker should remain disabled by default because the recall gain is modest and latency increases. `BAAI/bge-reranker-base` is the better quality model; `cross-encoder/ms-marco-MiniLM-L-6-v2` is the faster fallback.
