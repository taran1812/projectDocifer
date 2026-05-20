# Phase 5 Evaluation v1 and Early LangSmith

Phase 5 adds a repeatable evaluation harness for the current text RAG baseline.

## Implemented Components

- Golden QA spreadsheet loader.
- Corpus document metadata loader.
- Local DOC ID to PDF filename registry.
- Indexed-document lookup against Postgres text chunk records.
- Custom baseline metrics.
- LangSmith trace wrapper for evaluated questions.
- Evaluation runner CLI.
- JSONL, JSON, Markdown, and RAGAS-ready output writers.
- Tests for dataset loading, metrics, and the runner.

## Configuration

Environment variables:

```text
OPENAI_API_KEY=
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=docifer-dev
GOLDEN_EVAL_PATH=docifer_phase1_corpus_and_golden_eval_v1.xlsx
EVAL_RUNS_DIR=evals/runs
```

## Golden Dataset

Source workbook:

```text
docifer_phase1_corpus_and_golden_eval_v1.xlsx
```

The loader reads the `QA Evaluation Template` sheet.

Current seeded QA count:

```text
40 questions
```

Distribution:

- Text Factual: 14
- Text Synthesis: 6
- Table Lookup: 5
- Table Reasoning: 4
- Chart / Visual: 5
- Mixed Modality: 2
- Unsupported / Abstention: 4

## Evaluation Runner

Run all questions, evaluating indexed documents and marking the rest as skipped:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase5_current_indexed_baseline --top-k 3
```

Run only `DOC-005`:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase5_doc005_baseline --doc-id DOC-005 --top-k 3
```

Compare retrieval modes:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase6_doc005_bm25 --doc-id DOC-005 --top-k 3 --retrieval-mode bm25
```

Run hybrid retrieval with citation verification:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase6_doc005_hybrid_verifier --doc-id DOC-005 --top-k 3 --retrieval-mode hybrid --verify-citations
```

Disable LangSmith tracing:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name local_no_trace --top-k 3 --no-trace
```

## Output Files

Each run writes:

```text
evals/runs/<run-name>/
  results.jsonl
  summary.json
  report.md
  ragas_input.jsonl
```

`ragas_input.jsonl` exports question, answer, contexts, and ground truth in a shape that can be consumed by a later RAGAS scoring pass.

## Current Baseline Run

Run:

```text
phase5_current_indexed_baseline
```

Current corpus indexing coverage:

- 40 questions seen
- 3 evaluated
- 37 skipped as not indexed
- 0 failed

The evaluated rows are the three `DOC-005` World Development Report questions because that is the only document indexed in the current text baseline.

Metrics:

```json
{
  "answer_present_rate": 1.0,
  "citation_presence_rate": 1.0,
  "average_expected_answer_token_recall": 0.7917,
  "abstention_correct_rate": null,
  "latency_ms_p50": 1848.61,
  "latency_ms_p95": 10847.39
}
```

## Notes

- Phase 5 measures the current baseline; it does not improve retrieval.
- The 37 skipped questions are expected until more PDFs are ingested and indexed.
- LangSmith traces are emitted for evaluated questions when tracing is enabled.
- The current custom metrics are simple and deterministic. RAGAS-style LLM-judge scoring is prepared through export, but not yet treated as the source of truth.

## Validation

Commands run:

```powershell
backend\.venv\Scripts\pytest.exe backend\tests
```

Result:

```text
10 passed
```

Compile check:

```powershell
backend\.venv\Scripts\python.exe -m compileall -q backend\src backend\tests
```

Readiness check:

```json
{
  "status": "ready",
  "checks": {
    "postgres": "ok",
    "qdrant": "ok"
  }
}
```

## Phase 5 Gate Status

Phase 5 is valid for the currently indexed text baseline.

Satisfied:

- the golden QA dataset is loaded,
- runnable questions are evaluated,
- unindexed documents are explicitly skipped,
- metrics are computed and summarized,
- eval artifacts are saved,
- RAGAS-ready inputs are exported,
- LangSmith traces are emitted for evaluated questions,
- tests validate the core evaluation behavior.
