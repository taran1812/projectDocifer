# PDF Upload and Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators upload PDF files from the browser, trigger backend ingestion, poll for progress, and see the new document in the rail when indexing completes.

**Architecture:** Add `POST /ingestion/upload` to the FastAPI backend (saves file to `backend/uploads/`, runs existing `IngestionService.ingest_pdf` in a thread, returns `IngestionJobResponse`). Add `UploadPanel` React component above `DocumentList` in the left rail; it uploads via FormData, polls `/ingestion/jobs/{job_id}` every 2 s until terminal status, then refreshes the document list.

**Tech Stack:** FastAPI `UploadFile`, Python `asyncio.to_thread`, React 18, TypeScript, `setInterval` polling, `lucide-react` icons.

---

## File Structure

Backend changes:
```
backend/src/docifer_backend/api/ingestion.py   ← add POST /ingestion/upload
backend/tests/test_ingestion_upload.py          ← new: 3 TDD tests
.gitignore                                       ← add backend/uploads/
```

Frontend changes:
```
frontend/src/types/api.ts                        ← add IngestionJobResponse
frontend/src/lib/api.ts                          ← add uploadPdf, ingestionJob
frontend/src/components/UploadPanel.tsx          ← new component
frontend/src/components/DocumentList.tsx         ← remove aside wrapper (moved to App)
frontend/src/App.tsx                             ← add aside wrapper + UploadPanel
frontend/src/styles.css                          ← add upload panel styles
```

---

## Task 1: Backend Upload Endpoint

**Files:**
- Modify: `backend/src/docifer_backend/api/ingestion.py`
- Create: `backend/tests/test_ingestion_upload.py`
- Modify: `.gitignore`

---

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ingestion_upload.py`:

```python
import io
from unittest.mock import patch

from fastapi.testclient import TestClient

from docifer_backend.ingestion.service import IngestionOutcome
from docifer_backend.main import create_app


def _make_client() -> TestClient:
    return TestClient(create_app())


def _fake_outcome() -> IngestionOutcome:
    return IngestionOutcome(
        job_id="test-job-123",
        document_id="doc-456",
        status="completed",
        artifact_path="datasets/processed/abc/def",
        reused_existing=False,
        error_message=None,
    )


def test_upload_rejects_non_pdf_extension():
    client = _make_client()
    response = client.post(
        "/ingestion/upload",
        files={"file": ("report.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 400
    assert "pdf" in response.json()["detail"].lower()


def test_upload_rejects_non_pdf_content_type():
    client = _make_client()
    response = client.post(
        "/ingestion/upload",
        files={"file": ("report.pdf", io.BytesIO(b"%PDF fake"), "text/plain")},
    )
    assert response.status_code == 400


def test_upload_saves_file_and_returns_job_response(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "docifer_backend.api.ingestion._get_uploads_dir",
        lambda: tmp_path,
    )
    with patch(
        "docifer_backend.api.ingestion._ingest_pdf",
        return_value=_fake_outcome(),
    ):
        client = _make_client()
        response = client.post(
            "/ingestion/upload",
            files={
                "file": (
                    "annual_report.pdf",
                    io.BytesIO(b"%PDF-1.4"),
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] == "test-job-123"
    assert body["document_id"] == "doc-456"
    assert body["status"] == "completed"
    assert body["reused_existing"] is False
    assert body["error_message"] is None
    saved = list(tmp_path.glob("*.pdf"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"%PDF-1.4"
```

---

- [ ] **Step 2: Run tests — verify they fail**

```powershell
uv run --project backend pytest backend/tests/test_ingestion_upload.py -v
```

Expected: 3 failures — `POST /ingestion/upload` does not exist yet.

---

- [ ] **Step 3: Add the upload endpoint to `backend/src/docifer_backend/api/ingestion.py`**

Add these imports at the top of the file (after existing imports):

```python
import re
import uuid
from pathlib import Path

from fastapi import Form, UploadFile
```

Add this helper after the existing imports, before the router definition:

```python
def _get_uploads_dir() -> Path:
    return Path(__file__).parents[3] / "uploads"


def _sanitise_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w\-.]", "_", name)
    return name[:120]
```

Add this new route after the existing `create_ingestion_job` route:

```python
@router.post(
    "/upload",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_pdf(
    file: UploadFile,
    force_reprocess: bool = Form(False),
) -> IngestionJobResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must have a .pdf extension.",
        )
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Expected content-type application/pdf, got {file.content_type!r}.",
        )

    uploads_dir = _get_uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitise_filename(file.filename)
    dest = uploads_dir / f"{uuid.uuid4().hex}_{safe_name}"
    dest.write_bytes(await file.read())

    try:
        outcome = await asyncio.to_thread(
            _ingest_pdf,
            str(dest),
            force_reprocess=force_reprocess,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return IngestionJobResponse(**outcome.__dict__)
```

---

- [ ] **Step 4: Run tests — verify they pass**

```powershell
uv run --project backend pytest backend/tests/test_ingestion_upload.py -v
```

Expected: `3 passed`.

---

- [ ] **Step 5: Run full backend suite**

```powershell
uv run --project backend pytest --basetemp backend/.pytest_tmp -q
```

Expected: all non-integration tests pass, integration tests skipped.

---

- [ ] **Step 6: Add `backend/uploads/` to `.gitignore`**

In `.gitignore`, find the `# Local datasets and generated artifacts` section and add:

```
backend/uploads/
```

---

- [ ] **Step 7: Commit**

```powershell
git add backend/src/docifer_backend/api/ingestion.py backend/tests/test_ingestion_upload.py .gitignore
git commit -m "feat(backend): add POST /ingestion/upload endpoint"
```

---

## Task 2: Frontend Types and API Client

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/lib/api.ts`

---

- [ ] **Step 1: Add `IngestionJobResponse` type**

In `frontend/src/types/api.ts`, append at the end of the file:

```ts
export interface IngestionJobResponse {
  job_id: string;
  document_id: string;
  status: string;
  artifact_path: string | null;
  reused_existing: boolean;
  error_message: string | null;
}
```

---

- [ ] **Step 2: Add `uploadPdf` and `ingestionJob` to the API client**

In `frontend/src/lib/api.ts`:

Add `IngestionJobResponse` to the import at the top:

```ts
import type {
  DocumentListResponse,
  HealthResponse,
  IngestionJobResponse,
  QueryRequest,
  QueryResponse,
  ReadyResponse,
} from "../types/api";
```

Add an `uploadPdf` helper function after the `requestJson` function (before `dociferApi`):

```ts
async function uploadPdfFile(
  file: File,
  forceReprocess = false,
): Promise<IngestionJobResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("force_reprocess", String(forceReprocess));

  const response = await fetch(`${API_BASE_URL}/ingestion/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const rawDetails = await response.text();
    let details: unknown = rawDetails;
    if (rawDetails) {
      try {
        details = JSON.parse(rawDetails);
      } catch {
        details = rawDetails;
      }
    }
    throw new ApiError(
      `Request failed with status ${response.status}`,
      response.status,
      details,
    );
  }

  return response.json() as Promise<IngestionJobResponse>;
}
```

Add two entries to the `dociferApi` object:

```ts
export const dociferApi = {
  health: () => requestJson<HealthResponse>("/health"),
  ready: () => requestJson<ReadyResponse>("/ready"),
  documents: () => requestJson<DocumentListResponse>("/documents?limit=200"),
  query: (body: QueryRequest) =>
    requestJson<QueryResponse>("/query", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  uploadPdf: (file: File, forceReprocess = false) =>
    uploadPdfFile(file, forceReprocess),
  ingestionJob: (jobId: string) =>
    requestJson<IngestionJobResponse>(`/ingestion/jobs/${jobId}`),
};
```

---

- [ ] **Step 3: Run typecheck**

```powershell
cd frontend
npm run typecheck
```

Expected: zero errors.

---

- [ ] **Step 4: Commit**

```powershell
git add frontend/src/types/api.ts frontend/src/lib/api.ts
git commit -m "feat(frontend): add upload and ingestion job API client methods"
```

---

## Task 3: UploadPanel Component and Wiring

**Files:**
- Create: `frontend/src/components/UploadPanel.tsx`
- Modify: `frontend/src/components/DocumentList.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

---

- [ ] **Step 1: Create `frontend/src/components/UploadPanel.tsx`**

```tsx
import { AlertCircle, CheckCircle2, Loader2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ApiError, dociferApi } from "../lib/api";
import type { IngestionJobResponse } from "../types/api";

type UploadState = "idle" | "uploading" | "processing" | "done" | "failed";

interface UploadPanelProps {
  onIngestionComplete: () => void;
}

const POLL_INTERVAL_MS = 2_000;
const POLL_TIMEOUT_MS = 120_000;

export function UploadPanel({ onIngestionComplete }: UploadPanelProps) {
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function clearPoll() {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }

  useEffect(() => {
    return () => clearPoll();
  }, []);

  async function handleUpload(file: File) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setMessage("Only PDF files are supported.");
      setUploadState("failed");
      return;
    }

    setUploadState("uploading");
    setMessage(null);

    let job: IngestionJobResponse;
    try {
      job = await dociferApi.uploadPdf(file);
    } catch (err: unknown) {
      const detail =
        err instanceof ApiError && err.details && typeof err.details === "object"
          ? (err.details as { detail?: string }).detail ?? err.message
          : err instanceof Error
            ? err.message
            : "Upload failed.";
      setMessage(detail);
      setUploadState("failed");
      return;
    }

    setUploadState("processing");
    const started = Date.now();

    intervalRef.current = setInterval(() => {
      if (Date.now() - started > POLL_TIMEOUT_MS) {
        clearPoll();
        setMessage("Ingestion timed out after 120 s.");
        setUploadState("failed");
        return;
      }

      dociferApi
        .ingestionJob(job.job_id)
        .then((jobStatus) => {
          if (jobStatus.status === "completed") {
            clearPoll();
            setMessage(`${file.name} ready to query`);
            setUploadState("done");
            onIngestionComplete();
            setTimeout(() => {
              setUploadState("idle");
              setMessage(null);
            }, 3_000);
          } else if (jobStatus.status === "failed") {
            clearPoll();
            setMessage(jobStatus.error_message ?? "Ingestion failed.");
            setUploadState("failed");
          }
        })
        .catch(() => {
          // transient poll error — keep polling
        });
    }, POLL_INTERVAL_MS);
  }

  function handleFileInput(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) void handleUpload(file);
    event.target.value = "";
  }

  function handleDrop(event: React.DragEvent) {
    event.preventDefault();
    setIsDragOver(false);
    const file = event.dataTransfer.files[0];
    if (file) void handleUpload(file);
  }

  function handleDragOver(event: React.DragEvent) {
    event.preventDefault();
    setIsDragOver(true);
  }

  function handleDragLeave() {
    setIsDragOver(false);
  }

  function handleRetry() {
    setUploadState("idle");
    setMessage(null);
  }

  return (
    <div className="upload-panel">
      {uploadState === "idle" && (
        <div
          className={`upload-zone${isDragOver ? " is-drag-over" : ""}`}
          onClick={() => fileInputRef.current?.click()}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
          }}
        >
          <Upload size={15} />
          <span>Drop PDF or browse</span>
          <input
            accept=".pdf"
            onChange={handleFileInput}
            ref={fileInputRef}
            style={{ display: "none" }}
            type="file"
          />
        </div>
      )}

      {(uploadState === "uploading" || uploadState === "processing") && (
        <div className="upload-status">
          <Loader2 className="upload-spinner" size={15} />
          <span>{uploadState === "uploading" ? "Uploading…" : "Processing…"}</span>
        </div>
      )}

      {uploadState === "done" && (
        <div className="upload-status upload-done">
          <CheckCircle2 size={15} />
          <span>{message}</span>
        </div>
      )}

      {uploadState === "failed" && (
        <div className="upload-status upload-error">
          <AlertCircle size={15} />
          <span>{message ?? "Upload failed."}</span>
          <button onClick={handleRetry} type="button">
            Retry
          </button>
        </div>
      )}
    </div>
  );
}
```

---

- [ ] **Step 2: Remove `aside` wrapper from `DocumentList.tsx`**

The `<aside className="document-rail">` wrapper will be moved to `App.tsx` so `UploadPanel` and `DocumentList` can share the same rail container.

Replace the entire `DocumentList` component return with a fragment:

```tsx
export function DocumentList({ documents, selectedDocumentId, onSelect }: DocumentListProps) {
  return (
    <>
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
    </>
  );
}
```

---

- [ ] **Step 3: Update `App.tsx`**

Add the `UploadPanel` import at the top of the imports block:

```ts
import { UploadPanel } from "./components/UploadPanel";
```

Add a `refreshDocuments` callback before the `return` statement (after `runQuery`):

```ts
  function refreshDocuments() {
    dociferApi
      .documents()
      .then((result) => {
        setDocuments(result.documents);
      })
      .catch(() => {
        // refresh failure is non-fatal — existing list stays visible
      });
  }
```

Replace the `<DocumentList ... />` element in the render with an `<aside>` wrapper containing both components:

```tsx
        <aside className="document-rail">
          <UploadPanel onIngestionComplete={refreshDocuments} />
          <DocumentList
            documents={documents}
            onSelect={(document) => {
              setSelectedDocumentId(document.document_id);
              setScope("single");
            }}
            selectedDocumentId={selectedDocumentId}
          />
        </aside>
```

---

- [ ] **Step 4: Add upload panel styles to `frontend/src/styles.css`**

Append at the end of `frontend/src/styles.css`:

```css
.upload-panel {
  padding: 8px 10px;
  border-bottom: 1px solid #e3e8ec;
}

.upload-zone {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px dashed #cfd8df;
  border-radius: 8px;
  padding: 8px 12px;
  color: #62717c;
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  user-select: none;
}

.upload-zone:hover,
.upload-zone.is-drag-over {
  border-color: #32748a;
  background: #edf7fa;
  color: #154b5e;
}

.upload-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  font-size: 13px;
  color: #62717c;
}

.upload-spinner {
  animation: upload-spin 1s linear infinite;
  flex-shrink: 0;
}

@keyframes upload-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.upload-done {
  color: #226642;
}

.upload-error {
  color: #9b2c2c;
  flex-wrap: wrap;
  gap: 6px;
}

.upload-error button {
  border: 1px solid #e4a4a4;
  border-radius: 6px;
  background: #fae8e8;
  padding: 3px 8px;
  color: #9b2c2c;
  font-size: 12px;
}
```

---

- [ ] **Step 5: Run typecheck and build**

```powershell
cd frontend
npm run typecheck
npm run build
```

Expected: zero TypeScript errors, Vite build passes.

---

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/components/UploadPanel.tsx frontend/src/components/DocumentList.tsx frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat(frontend): add PDF upload panel with ingestion progress polling"
```

---

## Task 4: End-to-End Verification

**Files:** No code changes unless verification finds defects.

---

- [ ] **Step 1: Run full backend suite**

```powershell
uv run --project backend pytest --basetemp backend/.pytest_tmp -q
```

Expected: all non-integration tests pass (includes the 3 new upload tests).

---

- [ ] **Step 2: Run frontend build**

```powershell
cd frontend
npm run build
```

Expected: Vite build passes.

---

- [ ] **Step 3: Start backend and frontend**

In one terminal:

```powershell
uv run --project backend uvicorn docifer_backend.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm run dev
```

---

- [ ] **Step 4: Browser smoke test**

Open `http://127.0.0.1:5173`.

Verify:
- Upload panel appears at the top of the document rail with dashed border
- Drag a PDF onto the zone or click "Browse" → file picker opens
- Status transitions: "Uploading…" → "Processing…" → "Ready to query" (green tick)
- Document rail refreshes and the new document appears
- Uploading a `.txt` file shows "Only PDF files are supported." without calling backend
- After error, "Retry" button resets panel to idle

---

- [ ] **Step 5: Final commit if smoke fixes were needed**

If any defects were found and fixed during smoke testing:

```powershell
git add frontend/src backend/src backend/tests
git commit -m "fix(frontend): polish upload panel smoke test issues"
```
