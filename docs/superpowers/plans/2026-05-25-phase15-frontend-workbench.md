# Phase 15 Frontend Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Docifer's first usable frontend workbench for document selection, grounded querying, citations, evidence inspection, and backend readiness.

**Architecture:** Add a Vite React TypeScript app under `frontend/` and keep it as a single-page operator workbench. Add minimal backend CORS support so the Vite dev server can call the FastAPI API. Keep frontend state local to `App.tsx` for Phase 15 and split rendering into focused components.

**Tech Stack:** FastAPI, Pydantic settings, pytest, Vite, React, TypeScript, CSS modules via a single `src/styles.css`, browser smoke testing with Playwright or the in-app browser.

---

## File Structure

Backend changes:

```text
backend/src/docifer_backend/config/settings.py
backend/src/docifer_backend/main.py
backend/tests/test_cors.py
.env.example
```

Frontend files:

```text
frontend/package.json
frontend/index.html
frontend/vite.config.ts
frontend/tsconfig.json
frontend/tsconfig.node.json
frontend/src/main.tsx
frontend/src/App.tsx
frontend/src/styles.css
frontend/src/types/api.ts
frontend/src/lib/api.ts
frontend/src/components/AnswerPanel.tsx
frontend/src/components/DocumentList.tsx
frontend/src/components/EvidencePanel.tsx
frontend/src/components/QueryComposer.tsx
frontend/src/components/StatusStrip.tsx
```

Documentation:

```text
README.md
backend/README.md
docs/session-changes-2026-05-25.md
```

---

## Task 1: Backend CORS Configuration

**Files:**
- Modify: `backend/src/docifer_backend/config/settings.py`
- Modify: `backend/src/docifer_backend/main.py`
- Modify: `.env.example`
- Create: `backend/tests/test_cors.py`

- [ ] **Step 1: Write the failing CORS settings and middleware tests**

Create `backend/tests/test_cors.py`:

```python
from fastapi.testclient import TestClient

from docifer_backend.config.settings import Settings
from docifer_backend.main import create_app


def test_settings_parse_cors_origins_from_comma_separated_string():
    settings = Settings(cors_allowed_origins="http://localhost:5173,http://127.0.0.1:5173")

    assert settings.parsed_cors_allowed_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_cors_preflight_allows_local_vite_origin(monkeypatch):
    monkeypatch.setattr(
        "docifer_backend.main.get_settings",
        lambda: Settings(cors_allowed_origins=["http://localhost:5173"]),
    )
    client = TestClient(create_app())

    response = client.options(
        "/documents",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
```

- [ ] **Step 2: Run the CORS tests and verify they fail**

Run:

```powershell
uv run --project backend pytest backend/tests/test_cors.py -v
```

Expected: fail because `Settings` has no `cors_allowed_origins` field, no parsed CORS origin helper, and the app does not add `CORSMiddleware`.

- [ ] **Step 3: Add CORS settings**

Add this field after `app_port`:

```python
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
```

Add this property before `_validate_chunk_settings`:

```python
    @property
    def parsed_cors_allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]
```

- [ ] **Step 4: Register CORS middleware**

In `backend/src/docifer_backend/main.py`, add:

```python
from fastapi.middleware.cors import CORSMiddleware
```

Inside `create_app()`, after the `FastAPI(...)` call and before routers:

```python
    cors_origins = settings.parsed_cors_allowed_origins
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
```

- [ ] **Step 5: Add `.env.example` entry**

Add near the app settings in `.env.example`:

```text
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

- [ ] **Step 6: Run CORS tests**

Run:

```powershell
uv run --project backend pytest backend/tests/test_cors.py -v
```

Expected: `2 passed`.

- [ ] **Step 7: Run backend suite**

Run:

```powershell
uv run --project backend pytest --basetemp backend/.pytest_tmp
```

Expected: all non-integration tests pass, integration tests skipped by default.

- [ ] **Step 8: Commit backend CORS**

Run:

```powershell
git add backend/src/docifer_backend/config/settings.py backend/src/docifer_backend/main.py backend/tests/test_cors.py .env.example
git commit -m "feat(frontend): allow local workbench CORS"
```

---

## Task 2: Frontend Project Scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`

- [ ] **Step 1: Create frontend package metadata**

Create `frontend/package.json`:

```json
{
  "name": "docifer-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 5173",
    "build": "tsc -b && vite build",
    "typecheck": "tsc -b",
    "preview": "vite preview --host 127.0.0.1 --port 4173"
  },
  "dependencies": {
    "lucide-react": "latest",
    "react": "latest",
    "react-dom": "latest"
  },
  "devDependencies": {
    "@types/react": "latest",
    "@types/react-dom": "latest",
    "@vitejs/plugin-react": "latest",
    "typescript": "latest",
    "vite": "latest"
  }
}
```

- [ ] **Step 2: Create Vite HTML entry**

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Docifer Workbench</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 3: Create Vite config**

Create `frontend/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
});
```

- [ ] **Step 4: Create TypeScript configs**

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: Create minimal React shell**

Create `frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

Create `frontend/src/App.tsx`:

```tsx
export default function App() {
  return (
    <main className="app-shell">
      <section className="empty-state">
        <p className="eyebrow">Docifer</p>
        <h1>Workbench loading</h1>
        <p>Document intelligence frontend scaffold is ready.</p>
      </section>
    </main>
  );
}
```

Create `frontend/src/styles.css`:

```css
:root {
  font-family:
    Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI",
    sans-serif;
  color: #1b1f23;
  background: #f5f7f8;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
}

button,
input,
select,
textarea {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
}

.empty-state {
  width: min(520px, calc(100vw - 32px));
  border: 1px solid #d8dee4;
  border-radius: 8px;
  background: #ffffff;
  padding: 32px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #5f6b76;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

h1,
p {
  margin-top: 0;
}
```

- [ ] **Step 6: Install dependencies**

Run:

```powershell
Set-Location frontend
npm install
```

Expected: `node_modules/` and `package-lock.json` are created.

- [ ] **Step 7: Build scaffold**

Run:

```powershell
npm run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 8: Commit scaffold**

Run from repo root:

```powershell
git add frontend
git commit -m "feat(frontend): scaffold React workbench"
```

---

## Task 3: Typed API Client

**Files:**
- Create: `frontend/src/types/api.ts`
- Create: `frontend/src/lib/api.ts`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add backend API types**

Create `frontend/src/types/api.ts`:

```ts
export type ModalityStatusValue =
  | "indexed"
  | "not_indexed"
  | "not_available"
  | "failed"
  | "unknown";

export interface ModalityIndexStatus {
  status: ModalityStatusValue;
  count: number;
  latest_status?: string | null;
  collection_name?: string | null;
  latest_indexed_at?: string | null;
}

export interface DocumentModalities {
  text: ModalityIndexStatus;
  table: ModalityIndexStatus;
  visual: ModalityIndexStatus;
}

export interface DocumentSummary {
  document_id: string;
  doc_id?: string | null;
  content_hash: string;
  filename: string;
  source_path: string;
  parser_name?: string | null;
  latest_ingestion_status?: string | null;
  quality_status?: string | null;
  modalities: DocumentModalities;
}

export interface DocumentListResponse {
  documents: DocumentSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface HealthResponse {
  status: string;
}

export interface ReadyResponse {
  status: string;
  checks: Record<string, string>;
}

export type EvidenceMode = "text" | "table" | "visual" | "auto";
export type RetrievalMode = "dense" | "bm25" | "hybrid";
export type QueryScope = "single" | "all";

export interface QueryRequest {
  question: string;
  scope: QueryScope;
  content_hash?: string;
  max_documents: number;
  max_evidence_per_document: number;
  top_k: number;
  retrieval_mode: RetrievalMode;
  evidence_mode: EvidenceMode;
  table_top_k: number;
  visual_top_k: number;
  verify_citations: boolean;
}

export interface Citation {
  citation_id: string;
  source_path: string;
  source_artifact_path: string;
  page_start?: number | null;
  page_end?: number | null;
  score: number;
  doc_id?: string | null;
  document_id?: string | null;
  filename?: string | null;
  content_hash?: string | null;
}

export interface Evidence {
  citation_id: string;
  score: number;
  retrieval_mode: string;
  text?: string;
  raw_text?: string;
  markdown_table?: string | null;
  visual_type?: string;
  source_kind?: string;
  artifact_path?: string | null;
  doc_id?: string | null;
  filename?: string | null;
  source_path: string;
  page_start?: number | null;
  page_end?: number | null;
}

export interface CitationVerification {
  verdict: string;
  supported_citation_ids: string[];
  weak_citation_ids: string[];
  unsupported_claims: string[];
  reasoning: string;
  revised_answer?: string | null;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  table_citations: Citation[];
  visual_citations: Citation[];
  answer_citations: Citation[];
  evidence: Evidence[];
  table_evidence: Evidence[];
  visual_evidence: Evidence[];
  retrieved_evidence: Evidence[];
  unused_retrieved_evidence: Evidence[];
  unused_table_evidence: Evidence[];
  unused_visual_evidence: Evidence[];
  citation_verification?: CitationVerification | null;
  debug: Record<string, unknown>;
}
```

- [ ] **Step 2: Add API client**

Create `frontend/src/lib/api.ts`:

```ts
import type {
  DocumentListResponse,
  HealthResponse,
  QueryRequest,
  QueryResponse,
  ReadyResponse,
} from "../types/api";

const API_BASE_URL =
  import.meta.env.VITE_DOCIFER_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  details: unknown;

  constructor(message: string, status: number, details: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let details: unknown = null;
    try {
      details = await response.json();
    } catch {
      details = await response.text();
    }
    throw new ApiError(`Request failed with status ${response.status}`, response.status, details);
  }

  return response.json() as Promise<T>;
}

export const dociferApi = {
  health: () => requestJson<HealthResponse>("/health"),
  ready: () => requestJson<ReadyResponse>("/ready"),
  documents: () => requestJson<DocumentListResponse>("/documents?limit=200"),
  query: (body: QueryRequest) =>
    requestJson<QueryResponse>("/query", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
```

- [ ] **Step 3: Wire a smoke API call in `App.tsx`**

Replace `frontend/src/App.tsx` with:

```tsx
import { useEffect, useState } from "react";

import { dociferApi } from "./lib/api";
import type { DocumentSummary } from "./types/api";

export default function App() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dociferApi
      .documents()
      .then((response) => setDocuments(response.documents))
      .catch((requestError: unknown) => {
        setError(requestError instanceof Error ? requestError.message : "Unable to load documents");
      });
  }, []);

  return (
    <main className="app-shell">
      <section className="empty-state">
        <p className="eyebrow">Docifer</p>
        <h1>Workbench loading</h1>
        <p>{error ?? `${documents.length} documents available`}</p>
      </section>
    </main>
  );
}
```

- [ ] **Step 4: Run frontend typecheck**

Run:

```powershell
Set-Location frontend
npm run typecheck
```

Expected: TypeScript passes.

- [ ] **Step 5: Commit API client**

Run from repo root:

```powershell
git add frontend/src
git commit -m "feat(frontend): add typed Docifer API client"
```

---

## Task 4: Workbench Components

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`
- Create: `frontend/src/components/DocumentList.tsx`
- Create: `frontend/src/components/StatusStrip.tsx`
- Create: `frontend/src/components/QueryComposer.tsx`
- Create: `frontend/src/components/AnswerPanel.tsx`
- Create: `frontend/src/components/EvidencePanel.tsx`

- [ ] **Step 1: Create document list component**

Create `frontend/src/components/DocumentList.tsx`:

```tsx
import { FileText } from "lucide-react";

import type { DocumentSummary, ModalityIndexStatus } from "../types/api";

interface DocumentListProps {
  documents: DocumentSummary[];
  selectedDocumentId: string | null;
  onSelect: (document: DocumentSummary) => void;
}

function ModalityBadge({ label, status }: { label: string; status: ModalityIndexStatus }) {
  return (
    <span className={`modality-badge modality-${status.status}`}>
      {label}
      <strong>{status.count}</strong>
    </span>
  );
}

export function DocumentList({ documents, selectedDocumentId, onSelect }: DocumentListProps) {
  return (
    <aside className="document-rail">
      <div className="panel-heading">
        <FileText size={18} />
        <div>
          <h2>Documents</h2>
          <p>{documents.length} indexed sources</p>
        </div>
      </div>
      <div className="document-list">
        {documents.map((document) => (
          <button
            className={`document-item ${
              selectedDocumentId === document.document_id ? "is-selected" : ""
            }`}
            key={document.document_id}
            onClick={() => onSelect(document)}
            type="button"
          >
            <span className="document-id">{document.doc_id ?? "DOC"}</span>
            <span className="document-name">{document.filename}</span>
            <span className="document-status">{document.latest_ingestion_status ?? "unknown"}</span>
            <span className="modality-row">
              <ModalityBadge label="Text" status={document.modalities.text} />
              <ModalityBadge label="Table" status={document.modalities.table} />
              <ModalityBadge label="Visual" status={document.modalities.visual} />
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}
```

- [ ] **Step 2: Create status strip component**

Create `frontend/src/components/StatusStrip.tsx`:

```tsx
import { Activity, Database, Timer } from "lucide-react";

import type { EvidenceMode, QueryScope } from "../types/api";

interface StatusStripProps {
  readyStatus: string;
  scope: QueryScope;
  evidenceMode: EvidenceMode;
  latencyMs: number | null;
  requestStatus: string;
}

export function StatusStrip({
  readyStatus,
  scope,
  evidenceMode,
  latencyMs,
  requestStatus,
}: StatusStripProps) {
  return (
    <header className="status-strip">
      <div className="brand-block">
        <span className="brand-mark">D</span>
        <div>
          <h1>Docifer Workbench</h1>
          <p>Grounded document intelligence</p>
        </div>
      </div>
      <div className="status-items">
        <span className={`status-pill status-${readyStatus}`}>
          <Activity size={15} />
          {readyStatus}
        </span>
        <span className="status-pill">
          <Database size={15} />
          {scope} / {evidenceMode}
        </span>
        <span className="status-pill">
          <Timer size={15} />
          {latencyMs === null ? "no query yet" : `${Math.round(latencyMs)} ms`}
        </span>
        <span className="status-pill">{requestStatus}</span>
      </div>
    </header>
  );
}
```

- [ ] **Step 3: Create query composer**

Create `frontend/src/components/QueryComposer.tsx`:

```tsx
import { Search } from "lucide-react";
import type { FormEvent } from "react";

import type { DocumentSummary, EvidenceMode, QueryScope } from "../types/api";

interface QueryComposerProps {
  question: string;
  setQuestion: (value: string) => void;
  scope: QueryScope;
  setScope: (value: QueryScope) => void;
  evidenceMode: EvidenceMode;
  setEvidenceMode: (value: EvidenceMode) => void;
  verifyCitations: boolean;
  setVerifyCitations: (value: boolean) => void;
  selectedDocument: DocumentSummary | null;
  isLoading: boolean;
  onSubmit: () => void;
}

export function QueryComposer({
  question,
  setQuestion,
  scope,
  setScope,
  evidenceMode,
  setEvidenceMode,
  verifyCitations,
  setVerifyCitations,
  selectedDocument,
  isLoading,
  onSubmit,
}: QueryComposerProps) {
  const disabled = isLoading || question.trim().length === 0 || (scope === "single" && !selectedDocument);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!disabled) {
      onSubmit();
    }
  }

  return (
    <form className="query-composer" onSubmit={handleSubmit}>
      <div className="composer-context">
        <span>{scope === "single" ? selectedDocument?.filename ?? "Select a document" : "All indexed documents"}</span>
        <button
          className={scope === "single" ? "segmented-active" : ""}
          onClick={() => setScope("single")}
          type="button"
        >
          Single
        </button>
        <button
          className={scope === "all" ? "segmented-active" : ""}
          onClick={() => setScope("all")}
          type="button"
        >
          All
        </button>
      </div>
      <textarea
        aria-label="Question"
        onChange={(event) => setQuestion(event.target.value)}
        placeholder="Ask a grounded question about the selected document or corpus..."
        value={question}
      />
      <div className="composer-controls">
        <label>
          Evidence
          <select
            onChange={(event) => setEvidenceMode(event.target.value as EvidenceMode)}
            value={evidenceMode}
          >
            <option value="auto">Auto</option>
            <option value="text">Text</option>
            <option value="table">Table</option>
            <option value="visual">Visual</option>
          </select>
        </label>
        <label className="toggle-control">
          <input
            checked={verifyCitations}
            onChange={(event) => setVerifyCitations(event.target.checked)}
            type="checkbox"
          />
          Verify citations
        </label>
        <button className="primary-action" disabled={disabled} type="submit">
          <Search size={17} />
          {isLoading ? "Querying" : "Ask"}
        </button>
      </div>
    </form>
  );
}
```

- [ ] **Step 4: Create answer panel**

Create `frontend/src/components/AnswerPanel.tsx`:

```tsx
import { AlertCircle, CheckCircle2 } from "lucide-react";

import type { QueryResponse } from "../types/api";

interface AnswerPanelProps {
  response: QueryResponse | null;
  error: string | null;
  isLoading: boolean;
}

export function AnswerPanel({ response, error, isLoading }: AnswerPanelProps) {
  if (isLoading) {
    return <section className="answer-panel loading-panel">Retrieving evidence and generating answer...</section>;
  }

  if (error) {
    return (
      <section className="answer-panel error-panel">
        <AlertCircle size={20} />
        <div>
          <h2>Request failed</h2>
          <p>{error}</p>
        </div>
      </section>
    );
  }

  if (!response) {
    return (
      <section className="answer-panel empty-answer">
        <h2>Ask a question to inspect grounded evidence</h2>
        <p>Answers will appear here with citations and evidence diagnostics.</p>
      </section>
    );
  }

  return (
    <section className="answer-panel">
      <div className="answer-heading">
        <CheckCircle2 size={20} />
        <div>
          <h2>Answer</h2>
          <p>{response.answer_citations.length} final citations</p>
        </div>
      </div>
      <p className="answer-text">{response.answer}</p>
      <div className="citation-row">
        {[...response.answer_citations, ...response.table_citations, ...response.visual_citations].map(
          (citation) => (
            <span className="citation-chip" key={`${citation.citation_id}-${citation.source_path}`}>
              {citation.citation_id}
              <small>
                {citation.filename ?? citation.doc_id ?? "source"} p.
                {citation.page_start ?? "?"}
              </small>
            </span>
          ),
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Create evidence panel**

Create `frontend/src/components/EvidencePanel.tsx`:

```tsx
import { useState } from "react";

import type { Evidence, QueryResponse } from "../types/api";

type Tab = "citations" | "retrieved" | "unused" | "debug";

interface EvidencePanelProps {
  response: QueryResponse | null;
}

function EvidenceItem({ item }: { item: Evidence }) {
  const snippet = item.text ?? item.raw_text ?? item.markdown_table ?? item.visual_type ?? "No snippet available";
  return (
    <article className="evidence-item">
      <div className="evidence-meta">
        <strong>{item.citation_id}</strong>
        <span>{item.filename ?? item.doc_id ?? "source"}</span>
        <span>score {item.score.toFixed(3)}</span>
      </div>
      <p>{snippet}</p>
    </article>
  );
}

export function EvidencePanel({ response }: EvidencePanelProps) {
  const [tab, setTab] = useState<Tab>("citations");

  const retrieved = response
    ? [...response.retrieved_evidence, ...response.table_evidence, ...response.visual_evidence]
    : [];
  const unused = response
    ? [
        ...response.unused_retrieved_evidence,
        ...response.unused_table_evidence,
        ...response.unused_visual_evidence,
      ]
    : [];

  return (
    <aside className="evidence-panel">
      <div className="tab-row">
        <button className={tab === "citations" ? "tab-active" : ""} onClick={() => setTab("citations")} type="button">
          Citations
        </button>
        <button className={tab === "retrieved" ? "tab-active" : ""} onClick={() => setTab("retrieved")} type="button">
          Retrieved
        </button>
        <button className={tab === "unused" ? "tab-active" : ""} onClick={() => setTab("unused")} type="button">
          Unused
        </button>
        <button className={tab === "debug" ? "tab-active" : ""} onClick={() => setTab("debug")} type="button">
          Debug
        </button>
      </div>

      {!response ? <p className="panel-empty">Run a query to inspect evidence.</p> : null}

      {response && tab === "citations" ? (
        <div className="evidence-stack">
          {[...response.answer_citations, ...response.table_citations, ...response.visual_citations].map((citation) => (
            <article className="evidence-item" key={`${citation.citation_id}-${citation.source_path}`}>
              <div className="evidence-meta">
                <strong>{citation.citation_id}</strong>
                <span>{citation.filename ?? citation.doc_id ?? "source"}</span>
              </div>
              <p>
                Page {citation.page_start ?? "?"}
                {citation.page_end && citation.page_end !== citation.page_start ? `-${citation.page_end}` : ""}
              </p>
            </article>
          ))}
        </div>
      ) : null}

      {response && tab === "retrieved" ? (
        <div className="evidence-stack">{retrieved.map((item) => <EvidenceItem item={item} key={item.citation_id} />)}</div>
      ) : null}

      {response && tab === "unused" ? (
        <div className="evidence-stack">{unused.map((item) => <EvidenceItem item={item} key={item.citation_id} />)}</div>
      ) : null}

      {response && tab === "debug" ? (
        <pre className="debug-block">{JSON.stringify(response.debug, null, 2)}</pre>
      ) : null}
    </aside>
  );
}
```

- [ ] **Step 6: Replace `App.tsx` with workbench state**

Replace `frontend/src/App.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";

import { AnswerPanel } from "./components/AnswerPanel";
import { DocumentList } from "./components/DocumentList";
import { EvidencePanel } from "./components/EvidencePanel";
import { QueryComposer } from "./components/QueryComposer";
import { StatusStrip } from "./components/StatusStrip";
import { ApiError, dociferApi } from "./lib/api";
import type {
  DocumentSummary,
  EvidenceMode,
  QueryRequest,
  QueryResponse,
  QueryScope,
} from "./types/api";

export default function App() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [scope, setScope] = useState<QueryScope>("single");
  const [evidenceMode, setEvidenceMode] = useState<EvidenceMode>("auto");
  const [verifyCitations, setVerifyCitations] = useState(true);
  const [readyStatus, setReadyStatus] = useState("checking");
  const [requestStatus, setRequestStatus] = useState("idle");
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [response, setResponse] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const selectedDocument = useMemo(
    () => documents.find((document) => document.document_id === selectedDocumentId) ?? null,
    [documents, selectedDocumentId],
  );

  useEffect(() => {
    dociferApi
      .ready()
      .then((result) => setReadyStatus(result.status))
      .catch(() => setReadyStatus("offline"));

    dociferApi
      .documents()
      .then((result) => {
        setDocuments(result.documents);
        setSelectedDocumentId(result.documents[0]?.document_id ?? null);
      })
      .catch((loadError: unknown) => {
        setError(loadError instanceof Error ? loadError.message : "Unable to load documents");
      });
  }, []);

  async function runQuery() {
    if (!question.trim()) {
      return;
    }
    if (scope === "single" && !selectedDocument) {
      setError("Select a document before running a single-document query.");
      return;
    }

    const payload: QueryRequest = {
      question: question.trim(),
      scope,
      max_documents: 5,
      max_evidence_per_document: 3,
      top_k: 4,
      retrieval_mode: "hybrid",
      evidence_mode: evidenceMode,
      table_top_k: 4,
      visual_top_k: 3,
      verify_citations: verifyCitations,
      ...(scope === "single" && selectedDocument
        ? { content_hash: selectedDocument.content_hash }
        : {}),
    };

    setIsLoading(true);
    setError(null);
    setRequestStatus("running");
    const started = performance.now();
    try {
      const result = await dociferApi.query(payload);
      setResponse(result);
      setLatencyMs(performance.now() - started);
      setRequestStatus("complete");
    } catch (queryError: unknown) {
      const message =
        queryError instanceof ApiError
          ? `${queryError.message}: ${JSON.stringify(queryError.details)}`
          : queryError instanceof Error
            ? queryError.message
            : "Query failed";
      setError(message);
      setRequestStatus("failed");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="workbench">
      <StatusStrip
        evidenceMode={evidenceMode}
        latencyMs={latencyMs}
        readyStatus={readyStatus}
        requestStatus={requestStatus}
        scope={scope}
      />
      <div className="workbench-grid">
        <DocumentList
          documents={documents}
          onSelect={(document) => {
            setSelectedDocumentId(document.document_id);
            setScope("single");
          }}
          selectedDocumentId={selectedDocumentId}
        />
        <section className="center-column">
          <QueryComposer
            evidenceMode={evidenceMode}
            isLoading={isLoading}
            onSubmit={runQuery}
            question={question}
            scope={scope}
            selectedDocument={selectedDocument}
            setEvidenceMode={setEvidenceMode}
            setQuestion={setQuestion}
            setScope={setScope}
            setVerifyCitations={setVerifyCitations}
            verifyCitations={verifyCitations}
          />
          <AnswerPanel error={error} isLoading={isLoading} response={response} />
        </section>
        <EvidencePanel response={response} />
      </div>
    </main>
  );
}
```

- [ ] **Step 7: Replace CSS with workbench layout**

Replace `frontend/src/styles.css` with the complete workbench stylesheet:

```css
:root {
  font-family:
    Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI",
    sans-serif;
  color: #182026;
  background: #eef2f4;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
}

button,
input,
select,
textarea {
  font: inherit;
}

button {
  cursor: pointer;
}

.workbench {
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr;
}

.status-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  min-height: 72px;
  padding: 12px 20px;
  border-bottom: 1px solid #cfd8df;
  background: #ffffff;
}

.brand-block,
.status-items,
.panel-heading,
.answer-heading,
.composer-controls,
.composer-context,
.modality-row,
.evidence-meta,
.citation-row {
  display: flex;
  align-items: center;
}

.brand-block {
  gap: 12px;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 8px;
  background: #12343f;
  color: #ffffff;
  font-weight: 800;
}

h1,
h2,
h3,
p {
  margin-top: 0;
}

.brand-block h1,
.panel-heading h2,
.answer-panel h2 {
  margin-bottom: 2px;
  font-size: 16px;
  letter-spacing: 0;
}

.brand-block p,
.panel-heading p,
.answer-heading p {
  margin: 0;
  color: #62717c;
  font-size: 13px;
}

.status-items {
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  border: 1px solid #d5dde3;
  border-radius: 999px;
  padding: 5px 10px;
  background: #f8fafb;
  color: #3b4852;
  font-size: 13px;
}

.status-ready {
  border-color: #9ac7ad;
  color: #226642;
}

.status-offline {
  border-color: #e4a4a4;
  color: #9b2c2c;
}

.workbench-grid {
  display: grid;
  grid-template-columns: minmax(260px, 320px) minmax(420px, 1fr) minmax(320px, 420px);
  gap: 16px;
  min-height: 0;
  padding: 16px;
}

.document-rail,
.center-column,
.evidence-panel {
  min-height: 0;
}

.document-rail,
.evidence-panel,
.query-composer,
.answer-panel {
  border: 1px solid #d5dde3;
  border-radius: 8px;
  background: #ffffff;
}

.document-rail,
.evidence-panel {
  overflow: hidden;
}

.panel-heading {
  gap: 10px;
  padding: 16px;
  border-bottom: 1px solid #e3e8ec;
}

.document-list {
  display: grid;
  gap: 8px;
  max-height: calc(100vh - 138px);
  overflow: auto;
  padding: 10px;
}

.document-item {
  display: grid;
  gap: 6px;
  width: 100%;
  border: 1px solid #e0e6eb;
  border-radius: 8px;
  background: #fbfcfd;
  padding: 10px;
  text-align: left;
}

.document-item.is-selected {
  border-color: #32748a;
  background: #edf7fa;
}

.document-id,
.document-status {
  color: #62717c;
  font-size: 12px;
  font-weight: 700;
}

.document-name {
  color: #1d2730;
  font-size: 14px;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.modality-row {
  flex-wrap: wrap;
  gap: 5px;
}

.modality-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 999px;
  padding: 3px 7px;
  background: #eef2f4;
  color: #495762;
  font-size: 11px;
}

.modality-indexed {
  background: #e7f5ec;
  color: #236842;
}

.modality-failed {
  background: #fae8e8;
  color: #9b2c2c;
}

.center-column {
  display: grid;
  grid-template-rows: auto 1fr;
  gap: 16px;
}

.query-composer {
  display: grid;
  gap: 12px;
  padding: 16px;
}

.composer-context {
  justify-content: space-between;
  gap: 8px;
}

.composer-context span {
  min-width: 0;
  color: #51606b;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-context button,
.tab-row button {
  border: 1px solid #d5dde3;
  border-radius: 6px;
  background: #f8fafb;
  padding: 6px 10px;
  color: #394750;
}

.composer-context .segmented-active,
.tab-row .tab-active {
  border-color: #32748a;
  background: #e5f3f7;
  color: #154b5e;
}

textarea {
  width: 100%;
  min-height: 128px;
  resize: vertical;
  border: 1px solid #cfd8df;
  border-radius: 8px;
  padding: 12px;
  color: #182026;
}

.composer-controls {
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 12px;
}

.composer-controls label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #495762;
  font-size: 13px;
}

select {
  border: 1px solid #cfd8df;
  border-radius: 6px;
  background: #ffffff;
  padding: 6px 8px;
}

.primary-action {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 0;
  border-radius: 7px;
  background: #12343f;
  color: #ffffff;
  padding: 9px 14px;
  font-weight: 700;
}

.primary-action:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.answer-panel {
  min-height: 320px;
  padding: 18px;
}

.answer-heading {
  gap: 10px;
  margin-bottom: 16px;
}

.answer-text {
  color: #202b33;
  font-size: 16px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.loading-panel,
.empty-answer,
.error-panel {
  display: grid;
  place-content: center;
  gap: 8px;
  color: #62717c;
  text-align: center;
}

.error-panel {
  color: #9b2c2c;
}

.citation-row {
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.citation-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border-radius: 999px;
  background: #e9f1f4;
  padding: 6px 10px;
  color: #174c5d;
  font-weight: 800;
}

.citation-chip small {
  color: #55717b;
  font-weight: 600;
}

.tab-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  padding: 10px;
  border-bottom: 1px solid #e3e8ec;
}

.panel-empty {
  padding: 16px;
  color: #62717c;
}

.evidence-stack {
  display: grid;
  gap: 10px;
  max-height: calc(100vh - 138px);
  overflow: auto;
  padding: 10px;
}

.evidence-item {
  border: 1px solid #e0e6eb;
  border-radius: 8px;
  background: #fbfcfd;
  padding: 10px;
}

.evidence-meta {
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
  color: #62717c;
  font-size: 12px;
}

.evidence-meta strong {
  color: #174c5d;
}

.evidence-item p {
  margin-bottom: 0;
  color: #25313a;
  font-size: 13px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.debug-block {
  max-height: calc(100vh - 138px);
  overflow: auto;
  margin: 0;
  padding: 12px;
  color: #25313a;
  font-size: 12px;
  white-space: pre-wrap;
}

@media (max-width: 1120px) {
  .workbench-grid {
    grid-template-columns: 280px 1fr;
  }

  .evidence-panel {
    grid-column: 1 / -1;
  }
}

@media (max-width: 760px) {
  .status-strip,
  .workbench-grid {
    display: block;
  }

  .status-strip,
  .document-rail,
  .center-column,
  .evidence-panel {
    margin-bottom: 12px;
  }

  .document-list,
  .evidence-stack,
  .debug-block {
    max-height: 420px;
  }
}
```

- [ ] **Step 8: Typecheck and build**

Run:

```powershell
Set-Location frontend
npm run typecheck
npm run build
```

Expected: both commands pass.

- [ ] **Step 9: Commit workbench UI**

Run from repo root:

```powershell
git add frontend/src
git commit -m "feat(frontend): build document query workbench"
```

---

## Task 5: Documentation And Local Run Instructions

**Files:**
- Modify: `README.md`
- Modify: `backend/README.md`
- Create: `docs/session-changes-2026-05-25.md`

- [ ] **Step 1: Update root README**

Add this `Frontend Workbench` section to `README.md`:

````markdown
## Frontend Workbench

Run the backend:

```powershell
uv run --project backend uvicorn docifer_backend.main:app --reload --host 127.0.0.1 --port 8000
```

Run the frontend:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

The frontend expects the backend at `http://127.0.0.1:8000` by default. Override with:

```text
VITE_DOCIFER_API_URL=http://127.0.0.1:8000
```
````

- [ ] **Step 2: Update backend README**

Add this note under Phase 15A or after it:

````markdown
## Phase 15 frontend workbench

The frontend runs separately through Vite on port `5173`. The backend allows local frontend origins through `CORS_ALLOWED_ORIGINS`.

```powershell
uv run --project backend uvicorn docifer_backend.main:app --reload --host 127.0.0.1 --port 8000
Set-Location frontend
npm run dev
```
````

- [ ] **Step 3: Add session log**

Create `docs/session-changes-2026-05-25.md`:

```markdown
# Session Changes - 2026-05-25

## Phase 15 Frontend Workbench

Built the first Docifer frontend as a Vite React TypeScript operator workbench.

### Changes

- Added backend CORS support for the local frontend dev server.
- Added typed frontend API client for health, readiness, documents, and query.
- Added document rail, query composer, answer panel, evidence/debug panel, and status strip.
- Added local run instructions for backend plus frontend.

### Validation

- Backend tests: `uv run --project backend pytest --basetemp backend/.pytest_tmp`
- Frontend typecheck: `npm run typecheck`
- Frontend production build: `npm run build`
- Browser smoke test: open `http://127.0.0.1:5173`, load documents, submit a query, inspect citations/evidence.
```

- [ ] **Step 4: Commit docs**

Run:

```powershell
git add README.md backend/README.md docs/session-changes-2026-05-25.md
git commit -m "docs(frontend): document workbench runbook"
```

---

## Task 6: End-To-End Verification

**Files:**
- No code changes unless verification finds defects.

- [ ] **Step 1: Run backend tests**

Run:

```powershell
uv run --project backend pytest --basetemp backend/.pytest_tmp
```

Expected: all non-integration tests pass.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
Set-Location frontend
npm run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 3: Start backend**

Run in a terminal:

```powershell
uv run --project backend uvicorn docifer_backend.main:app --reload --host 127.0.0.1 --port 8000
```

Expected: backend serves `http://127.0.0.1:8000/docs`.

- [ ] **Step 4: Start frontend**

Run in another terminal:

```powershell
Set-Location frontend
npm run dev
```

Expected: frontend serves `http://127.0.0.1:5173`.

- [ ] **Step 5: Browser smoke test**

Open `http://127.0.0.1:5173`.

Verify:

- status strip does not show permanent offline state when backend is running
- document rail lists indexed documents
- selecting a document updates query context
- asking a simple question returns an answer or a clear backend error
- citations/evidence/debug panel renders without overlap
- mobile/narrow viewport does not overlap text

- [ ] **Step 6: Run graphify update**

Run:

```powershell
graphify update .
```

Expected: graph rebuild completes.

- [ ] **Step 7: Final commit if smoke fixes were needed**

If verification required fixes, inspect the changed files, then commit the known Phase 15 worktree paths:

```powershell
git status --short
git add frontend README.md backend/README.md docs/session-changes-2026-05-25.md backend/src/docifer_backend/config/settings.py backend/src/docifer_backend/main.py backend/tests/test_cors.py .env.example
git commit -m "fix(frontend): polish workbench smoke test issues"
```

---

## Implementation Notes

- Keep frontend defaults conservative: `retrieval_mode="hybrid"`, `evidence_mode="auto"`, `top_k=4`, `verify_citations=true`.
- Do not add authentication, upload, hosted deployment, or a marketing landing page in Phase 15.
- If `npm install` fails due network restrictions, request permission for network access and rerun it.
- If backend queries are slow, keep the UI responsive with loading states; do not lower backend quality defaults without a separate decision.
- If the visual companion remains unavailable because WSL is not installed, use the in-app browser or normal browser smoke testing against the Vite dev server.
