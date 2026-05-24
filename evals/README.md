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

Validated Phase 8.5 results:

| Run | Search config | Recall | Citation | False Abstention | True Abstention | P50 Latency | P95 Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| `phase7g1_full_40q` | baseline | 0.6625 | 0.975 | 0.0556 | 0.75 | 3327.75 | 12144.30 |
| `phase8_5_ann_default` | ANN, `ef=64` | 0.6604 | 0.950 | 0.0556 | 0.75 | 3716.98 | 14899.56 |
| `phase8_5_exact_search` | exact | 0.6554 | 0.950 | 0.0278 | 1.00 | 3470.52 | 14539.56 |
| `phase8_5_ann_ef128` | ANN, `ef=128` | 0.6670 | 0.975 | 0.0556 | 1.00 | 3338.74 | 16271.60 |

Recommendation: keep ANN `ef=64` as the default. Use ANN `ef=128` as a quality experiment when higher P95 latency is acceptable. Use exact search as a diagnostic, not as the default retrieval path.

## Phase 9 - Multi-Document Query Checks

The normal golden run remains single-document by default. Run it after Phase 9 as a regression check:

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase9_single_doc_regression --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations
```

Run explicit corpus-wide retrieval over an indexed evaluation slice:

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase9_all_docs_smoke --scope all --doc-id DOC-005 --doc-id DOC-007 --top-k 4 --retrieval-mode hybrid --evidence-mode category --verify-citations --max-documents 5 --max-evidence-per-document 3
```

Run selected-document scope:

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner --run-name phase9_selected_docs_smoke --scope doc_ids --doc-id DOC-005 --doc-id DOC-007 --top-k 4 --retrieval-mode hybrid --evidence-mode text --verify-citations --max-documents 2 --max-evidence-per-document 2
```

Before interpreting document metadata in existing text results, reindex the selected canonical artifacts through `POST /index/text` with `force_reindex=true`.

## Phase 12 — Final Ablation Benchmark

Phase 12 ran systematic ablations on top_k, chunk size, citation verification, answer prompt, query decomposition, and reranker pool size. All ablations used `retrieval_mode=hybrid`, `evidence_mode=category`, `verify_citations=True` unless stated.

**Note:** Visual questions require `datasets/processed/` (not git-tracked). Run any eval containing visual questions from the main repo, not a git worktree.

### Recommended Phase 12 config

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner `
  --run-name phase12_final `
  --top-k 12 `
  --retrieval-mode hybrid `
  --evidence-mode category `
  --verify-citations `
  --no-trace
```

Environment:

```powershell
$env:TEXT_CHUNK_SIZE = "1200"
$env:TEXT_CHUNK_OVERLAP = "200"
$env:QDRANT_SEARCH_EF = "64"
```

### Ablation results summary (40-question original dataset)

| Ablation | Winner | Key finding |
|----------|--------|-------------|
| top_k | 12 | +8.5pp text recall over top_k=8; top_k=8 regressed vs baseline |
| verify_citations | true | citation 97.5% → 92.5% without; P95 worsens without |
| chunk_size | 1200/200 | +11.8pp text recall over 800/150; best citation rate |
| answer prompt | baseline | completeness rules regressed recall −0.8pp, citation −2.6pp |
| query decomposition | skipped | gap 0.104 < 0.12 threshold |
| reranker pool=20 | disabled | +1.6pp recall < +3pp gate; P50 3.2× slower, P95 +11.6s |
| reranker pool=30 | disabled | −10.9pp recall regression; 17% false abstentions |

### Phase 12 final results

**40-question original dataset (`phase12_chunks1200_topk12`):**

```json
{
  "answer_recall_text": 0.8255,
  "answer_recall_all": 0.7170,
  "average_retrieved_evidence_token_recall": 0.8395,
  "average_evidence_answer_gap": 0.1038,
  "citation_presence_rate": 0.975,
  "false_abstention_rate": 0.056,
  "true_abstention_accuracy": 0.50,
  "latency_ms_p50": 3632,
  "latency_ms_p95": 16397
}
```

**68-question expanded dataset (`phase12_expanded_68q_final`, run from main repo):**

```json
{
  "average_answer_token_recall": 0.6259,
  "average_retrieved_evidence_token_recall": 0.766,
  "average_evidence_answer_gap": 0.1401,
  "citation_presence_rate": 0.9104,
  "false_abstention_rate": 0.0755,
  "true_abstention_accuracy": 0.8571,
  "latency_ms_p50": 3758,
  "latency_ms_p95": 19506
}
```

Gate verdict: **COMPLETE** — text stretch target met (0.8255 ≥ 0.78). Overall 0.7170 is 0.003 below gate due to table/visual routing issues, not text regression.

### Known issues (deferred to Phase 13)

- QA-041, 042, 045, 046, 048, 050: category=Table but answer is in text — routing mismatch causes abstention
- 3 table questions: expected_answer in billions, system answers in millions — format mismatch depresses token recall
- Evidence-answer synthesis gap ~0.10 consistent across configs — LLM does not cite all retrieved facts

Full ablation notes: `docs/phase12-final-ablation-benchmark.md`
