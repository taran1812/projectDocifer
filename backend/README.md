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
