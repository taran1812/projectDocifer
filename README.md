# Docifer

[![CI](https://github.com/taran1812/projectDocifer/actions/workflows/ci.yml/badge.svg)](https://github.com/taran1812/projectDocifer/actions/workflows/ci.yml)

**Multimodal document intelligence** — upload a PDF, get grounded answers with citations from text, tables, and figures.

---

## What it does

- **Ingest**: PDF → Docling parse → canonical artifact → text chunks + table evidence + visual evidence indexed in Qdrant
- **Retrieve**: hybrid dense/BM25 retrieval across any combination of indexed documents, with cross-encoder reranking
- **Answer**: LLM answer grounded on retrieved evidence, with citation verification and abstention when evidence is insufficient
- **Workbench**: React frontend for uploading documents, composing queries, and inspecting cited evidence

---

## Architecture

```
Browser (React + Vite)
    │  upload PDF, query, browse documents
    ▼
FastAPI backend (Python 3.12)
    ├── /ingestion/upload     → IngestionService → DoclingParser / PdfiumParser (fallback)
    │                                            → TextIndexingService
    │                                            → TableIndexingService
    │                                            → VisualIndexingService
    ├── /query                → QueryService → Qdrant (text + table + visual)
    │                                        → cross-encoder reranker (optional)
    │                                        → OpenAI answer + citation verifier
    └── /documents            → DocumentRegistryService → PostgreSQL
```

**Storage:**
- PostgreSQL — document registry, ingestion job tracking
- Qdrant — 3 collections: `docifer_text_chunks`, `docifer_table_evidence`, `docifer_visual_evidence`
- Local disk — raw uploads, canonical parse artifacts

---

## Quick Start

**One command (Docker):**

```bash
cp .env.example .env   # fill in OPENAI_API_KEY
docker compose up --build
# Open http://localhost:5173
```

> First build takes ~10 min (downloads ~2.5 GB of ML deps). Subsequent starts are instant.

**Manual (dev with hot-reload):**

```powershell
# Infrastructure
docker run -d -p 5432:5432 -e POSTGRES_DB=docifer -e POSTGRES_USER=docifer_user -e POSTGRES_PASSWORD=docifer_password postgres:15
docker run -d -p 6333:6333 qdrant/qdrant

# Backend
uv run --project backend uvicorn docifer_backend.main:app --reload --host 127.0.0.1 --port 8000

# Frontend
Set-Location frontend; npm install; npm run dev
# Open http://127.0.0.1:5173
```

See [docs/runbook.md](docs/runbook.md) for full setup, env vars, and production hardening.

---

## Demo

1. `docker compose up --build` (or manual setup — see Quick Start)
2. Upload a PDF via the workbench drag-drop zone
3. Wait for "is ready to query" (~5–30s depending on PDF size)
4. Type a question — the answer includes inline citations linking back to source pages

**Example questions:**
- "What was net revenue in Q4 2025?"
- "Summarize the risk factors"
- "What tables are on page 12?"

---

## Benchmark Results (68-question eval corpus, 8 documents)

| Metric | Score |
|---|---|
| Answer correctness | 83.8% |
| Citation grounding | 91.2% |
| Abstention rate (unanswerable) | 94.1% |
| Retrieval recall@8 | 88.2% |

Config: hybrid retrieval, category evidence mode, citation verification enabled, top-k=12.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy, Pydantic v2 |
| PDF parsing | Docling (primary), pypdfium2 (fallback) |
| Embeddings | OpenAI `text-embedding-3-small` |
| LLM | OpenAI `gpt-5.4-mini` (answers), `gpt-4o-mini` (vision) |
| Vector store | Qdrant |
| Database | PostgreSQL + psycopg3 |
| Frontend | React 19, TypeScript, Vite |
| CI | GitHub Actions |

---

## Project Structure

```
docker-compose.yml      One-command local stack
backend/
  Dockerfile            python:3.12-slim + uv
  src/docifer_backend/
    api/                FastAPI routers
    ingestion/          PDF parse → canonical artifact
    retrieval/          Qdrant query, reranker, answer LLM
    documents/          Document registry service
    evaluation/         Eval runner and harness
  tests/                Unit + integration tests

frontend/
  Dockerfile            node:20 build → nginx:alpine serve
  src/
    components/         DocumentList, QueryComposer, UploadPanel
    lib/api.ts          Typed API client
    types/api.ts        Shared API types

docs/
  runbook.md            Setup, env vars, production checklist
  DOCIFER_REFERENCE.md  Full technical reference with benchmarks
```

---

## Key Documentation

- [docs/runbook.md](docs/runbook.md) — setup, deployment, troubleshooting
- [DOCIFER_REFERENCE.md](DOCIFER_REFERENCE.md) — full technical reference with benchmarks
- [backend/README.md](backend/README.md) — backend API details and phase notes
