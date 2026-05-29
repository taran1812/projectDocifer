# Docifer — Deployment & Runbook

## Prerequisites

| Dependency | Version | Notes |
|---|---|---|
| Python | 3.12+ | via `uv` recommended |
| Node.js | 20+ | for frontend |
| PostgreSQL | 15+ | document registry |
| Qdrant | latest | vector store (Docker recommended) |
| OpenAI API key | — | embedding + answer + vision models |

---

## Local Development Setup

### 1. Clone and configure environment

```bash
git clone <repo>
cd projectDOCIFER
cp .env.example .env
# Edit .env — fill in OPENAI_API_KEY, DATABASE_URL, QDRANT_URL at minimum
```

### 2. Start infrastructure (Docker)

```powershell
# PostgreSQL
docker run -d --name docifer-postgres \
  -e POSTGRES_DB=docifer \
  -e POSTGRES_USER=docifer_user \
  -e POSTGRES_PASSWORD=docifer_password \
  -p 5432:5432 \
  postgres:15

# Qdrant
docker run -d --name docifer-qdrant \
  -p 6333:6333 \
  qdrant/qdrant
```

### 3. Install backend dependencies

```powershell
uv sync --project backend
```

### 4. Start the backend

```powershell
uv run --project backend uvicorn docifer_backend.main:app --reload --host 127.0.0.1 --port 8000
```

The API starts at `http://127.0.0.1:8000`.

### 5. Install and start the frontend

```powershell
Set-Location frontend
npm install
npm run dev
```

The workbench opens at `http://127.0.0.1:5173`.

---

## Environment Variables

### Required

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key for embeddings, answers, and vision |
| `DATABASE_URL` | PostgreSQL connection string |
| `QDRANT_URL` | Qdrant HTTP endpoint (e.g. `http://localhost:6333`) |

### Security

| Variable | Default | Description |
|---|---|---|
| `DOCIFER_API_KEY` | *(empty)* | Static API key. When set, all endpoints require `X-API-Key` header. `/health` and `/ready` remain unprotected. Docs are hidden when set. |
| `CORS_ALLOWED_ORIGINS` | *(empty)* | Comma-separated origins. Must be set for browser clients. |

### Frontend (`.env` in `frontend/`)

| Variable | Default | Description |
|---|---|---|
| `VITE_DOCIFER_API_URL` | `http://127.0.0.1:8000` | Backend base URL |
| `VITE_DOCIFER_API_KEY` | *(empty)* | Must match `DOCIFER_API_KEY` on the backend |

### Models

| Variable | Default | Description |
|---|---|---|
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Used for vector indexing and retrieval |
| `OPENAI_ANSWER_MODEL` | `gpt-5.4-mini` | Used for grounded answer generation |
| `OPENAI_VISION_MODEL` | `gpt-4o-mini` | Used for visual evidence observation |

---

## Running Tests

### Backend unit tests

```powershell
uv run --project backend pytest tests/ --ignore=tests/integration -q
```

### Backend integration tests (requires running Postgres + Qdrant)

```powershell
$env:RUN_INTEGRATION_TESTS = "true"
uv run --project backend pytest backend/tests/integration -v
```

### Frontend tests

```powershell
Set-Location frontend
npm test -- --run
```

### Frontend typecheck

```powershell
Set-Location frontend
npm run typecheck
```

---

## Ingesting a Document

### Via the workbench UI

1. Open `http://127.0.0.1:5173`
2. Click or drag a PDF onto the upload zone
3. Wait for "is ready to query" — the document is indexed

### Via the API

```bash
curl -X POST http://127.0.0.1:8000/ingestion/upload \
  -H "X-API-Key: <your-key>" \
  -F "file=@/path/to/document.pdf"
```

Response includes a `job_id`. Poll until status is `indexed`:

```bash
curl http://127.0.0.1:8000/ingestion/jobs/<job_id> \
  -H "X-API-Key: <your-key>"
```

---

## Querying Documents

```bash
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-key>" \
  -d '{
    "question": "What was Q4 2025 net sales?",
    "scope": "all",
    "max_documents": 3,
    "max_evidence_per_document": 8,
    "top_k": 8,
    "retrieval_mode": "hybrid",
    "evidence_mode": "category",
    "table_top_k": 5,
    "visual_top_k": 3,
    "verify_citations": true
  }'
```

---

## Health Checks

```bash
curl http://127.0.0.1:8000/health   # {"status":"ok"}
curl http://127.0.0.1:8000/ready    # {"status":"ok","checks":{...}}
```

---

## Removing a Document

```bash
curl -X DELETE http://127.0.0.1:8000/documents/<document_id> \
  -H "X-API-Key: <your-key>"
```

This deletes the document from the registry, removes it from all Qdrant collections, and deletes any uploaded file from disk.

---

## Production Hardening Checklist

- [ ] Set `DOCIFER_API_KEY` to a strong random value (e.g. `openssl rand -hex 32`)
- [ ] Set `CORS_ALLOWED_ORIGINS` to your frontend origin only
- [ ] Set `APP_ENV=production`
- [ ] Place behind a reverse proxy (nginx/Caddy) with TLS
- [ ] Add rate limiting — the `/query` endpoint calls OpenAI on every request
- [ ] Set up log aggregation (the backend logs warnings on startup when auth or rate limits are missing)
- [ ] Use managed Postgres and Qdrant (not Docker on the same host)
- [ ] Pin `OPENAI_EMBEDDING_MODEL` — changing this invalidates all existing vector indexes

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Upload stuck at "Uploading..." | Backend not running or CORS not configured | Check `APP_HOST` and `CORS_ALLOWED_ORIGINS` |
| `401 Unauthorized` from frontend | `VITE_DOCIFER_API_KEY` not set or mismatched | Set matching key in `frontend/.env` |
| Query returns no evidence | Document not indexed, or Qdrant empty | Check `/ready` and re-ingest |
| OOM during ingestion | Dense PDF with Docling | AutoPdfParser falls back to pdfium — check logs for fallback message |
| Docs UI hidden | `DOCIFER_API_KEY` is set | Expected — use `/health` to confirm server is up |
