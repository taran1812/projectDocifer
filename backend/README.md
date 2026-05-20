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
