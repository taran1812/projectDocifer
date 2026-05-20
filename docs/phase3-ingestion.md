# Phase 3 Ingestion Gate

Phase 3 is complete when Docifer can take a local PDF, track the ingestion job in PostgreSQL, parse it through Docling, and emit inspectable canonical artifacts without duplicate processing.

## Implemented components

- SQLAlchemy tables for `documents`, `ingestion_jobs`, and future duplicate-safe `document_index_runs`.
- Stable ingestion statuses: `queued`, `parsing`, `parsed`, `indexing`, `indexed`, `failed`.
- SHA-256 content hashing for document identity.
- Idempotent reprocessing behavior for already parsed PDFs.
- Bounded parse retries with persisted error type, message, and traceback.
- Docling parser wrapper hidden behind a local parser protocol.
- Canonical JSON output plus raw Docling JSON, Markdown, and parse summary artifacts.
- CLI and FastAPI entry points.

## First validated PDF

`datasets/raw_pdfs/Worldbank2024.pdf`

Validated output:

`datasets/processed/8109582811fe/55e8b2a2-0406-4aed-8a9e-da81ef6ef0ff/canonical.json`

The parsed artifact reports:

- 4 pages
- 1 table
- 3 figures
- Docling status `success`
- no parse errors

## First-run note

Docling/RapidOCR may download OCR and layout model weights on first real parse. After the first run, repeated ingestion of the same PDF reuses the successful job unless `--force` is passed.
