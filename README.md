# Docifer

Docifer is a document intelligence backend for PDF ingestion, multimodal evidence indexing, grounded retrieval, citation verification, and corpus-level evaluation.

The project currently centers on the FastAPI backend in `backend/`, with phase notes and session history in `docs/`.

## Current Status

- Ingestion parses PDFs into canonical artifacts under `datasets/processed/`.
- Text, table, and visual evidence can be indexed into Qdrant.
- `/query` supports single-document, selected-document, and corpus-wide retrieval scopes.
- Evidence responses preserve citations, scores, debug metadata, and citation-grounding verdicts.
- Document registry APIs expose document identity, modality readiness, audit status, and artifacts.
- Phase 15A hardened async API routes and pytest configuration before frontend work.

## Common Commands

Run the backend API:

```powershell
uv run --project backend uvicorn docifer_backend.main:app --reload --host 127.0.0.1 --port 8000
```

Run the unit test suite from the repository root:

```powershell
uv run --project backend pytest --basetemp backend/.pytest_tmp
```

Run real Postgres/Qdrant integration tests when Docker services are available:

```powershell
$env:RUN_INTEGRATION_TESTS = "true"
uv run --project backend pytest backend/tests/integration -v --basetemp backend/.pytest_integration_tmp
```

Run the current 68-question regression evaluation:

```powershell
uv run --project backend python -m docifer_backend.evaluation.runner `
  --run-name phase15a_async_hardening_68q `
  --top-k 12 `
  --retrieval-mode hybrid `
  --evidence-mode category `
  --verify-citations `
  --no-trace
```

## Key Documentation

- `backend/README.md` - backend API, phase notes, and validation commands.
- `docs/session-changes-2026-05-24.md` - latest session outcomes.
- `docs/phase12-final-ablation-benchmark.md` - retrieval ablation benchmark and recommended query configuration.
- `docs/phase10-document-registry-apis.md` - document registry API notes.
