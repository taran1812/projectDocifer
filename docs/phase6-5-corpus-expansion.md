# Phase 6.5 Corpus Expansion Validation

Phase 6.5 expanded the indexed text corpus before starting Phase 7. The goal was to test whether the Phase 6 hybrid retrieval and citation-grounding design still behaves well once more than one PDF is indexed.

## Scope

Indexed additional golden-eval documents:

| Doc ID | PDF | Parser | Chunks |
|---|---|---|---:|
| DOC-001 | `2025_AnnualReport.pdf` | `pypdfium2-text` | 226 |
| DOC-003 | `JPChaseannualreport-2025.pdf` | `pypdfium2-text` | 1235 |
| DOC-007 | `OECD.pdf` | `pypdfium2-text` | 1627 |

Existing indexed document retained:

| Doc ID | PDF | Parser | Chunks |
|---|---|---|---:|
| DOC-005 | `Worldbank2024.pdf` | `docling` | 5 |

## Ingestion Finding

The default Docling parser path was not robust enough for larger local PDFs in this environment. Early Phase 6.5 attempts against Microsoft and JPMorgan reports produced native `std::bad_alloc` failures during Docling preprocessing.

To keep the text RAG track moving, ingestion now has an automatic text-first fallback:

- small PDFs continue through Docling by default,
- PDFs above the local Docling size threshold use `pypdfium2` native text extraction,
- page-level provenance is still preserved for citations,
- canonical artifacts keep the same shape expected by chunking and indexing.

## Implementation Changes

Updated:

- `backend/src/docifer_backend/ingestion/parser.py`
- `backend/src/docifer_backend/ingestion/service.py`
- `backend/src/docifer_backend/config/settings.py`
- `backend/src/docifer_backend/providers/openai_provider.py`
- `backend/src/docifer_backend/retrieval/indexing.py`
- `backend/src/docifer_backend/retrieval/vector_store.py`
- `backend/src/docifer_backend/evaluation/metrics.py`
- `backend/pyproject.toml`
- `backend/uv.lock`
- `backend/tests/test_ingestion_parser.py`

Added or improved:

- `AutoPdfParser`
- `PdfiumTextParser`
- parser backend settings
- direct `pypdfium2` dependency
- OpenAI embedding batching
- Qdrant upsert batching
- broader abstention phrase detection in eval metrics
- parser selection tests

## Evaluation Runs

Primary run:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase6_5_expanded_corpus_hybrid --doc-id DOC-001 --doc-id DOC-003 --doc-id DOC-005 --doc-id DOC-007 --top-k 4 --retrieval-mode hybrid --verify-citations
```

Result:

```json
{
  "evaluated": 15,
  "failed": 0,
  "skipped": 25,
  "citation_presence_rate": 0.8667,
  "average_expected_answer_token_recall": 0.6566,
  "abstention_correct_rate": 0.75,
  "latency_ms_p50": 3018.58,
  "latency_ms_p95": 6406.1
}
```

Top-k ablation:

```powershell
backend\.venv\Scripts\python.exe -m docifer_backend.evaluation.runner --run-name phase6_5_expanded_corpus_hybrid_top8 --doc-id DOC-001 --doc-id DOC-003 --doc-id DOC-005 --doc-id DOC-007 --top-k 8 --retrieval-mode hybrid --verify-citations
```

Result:

```json
{
  "evaluated": 15,
  "failed": 0,
  "skipped": 25,
  "citation_presence_rate": 0.8,
  "average_expected_answer_token_recall": 0.6846,
  "abstention_correct_rate": 1.0,
  "latency_ms_p50": 3049.2,
  "latency_ms_p95": 4486.17
}
```

Run artifacts:

- `evals/runs/phase6_5_expanded_corpus_hybrid/`
- `evals/runs/phase6_5_expanded_corpus_hybrid_top8/`

## Key Result

The Phase 6 design held up well on the expanded text corpus:

- 15 golden questions evaluated,
- 0 eval failures,
- hybrid retrieval worked across four documents,
- citation verification produced supported verdicts for grounded answers,
- unsupported questions were generally handled as abstentions,
- indexed evidence retained page and source metadata.

The main retrieval weakness was table reasoning at `top_k=4`. QA-008 missed the exact JPMorgan segment-results table even though the correct chunk was indexed. The `top_k=8` run retrieved the table and answered correctly:

```text
Commercial & Investment Bank had the highest 2025 net income among the three reportable business segments, at $27,761 million.
```

## Phase 6.5 Verdict

Phase 6.5 is valid as a corpus-expansion checkpoint.

The system is strong enough to proceed toward Phase 7, with two important lessons:

- large-PDF ingestion needs a robust text fallback before deeper layout/table work,
- table reasoning benefits from larger retrieval depth and should be revisited with table-specific retrieval, reranking, or both.
