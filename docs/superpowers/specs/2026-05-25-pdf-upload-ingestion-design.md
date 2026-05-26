# PDF Upload and Ingestion Design

**Date:** 2026-05-25
**Goal:** Let operators upload PDF files from the browser, trigger backend ingestion, and see progress before querying.

---

## Scope

- Backend: one new endpoint `POST /ingestion/upload`
- Frontend: `UploadPanel` component, two new API client methods, one new type, wired into `App.tsx`
- No changes to existing ingestion logic, query pipeline, or document registry

---

## Flow

```
User selects PDF in browser
  → POST /ingestion/upload (multipart/form-data)
  → Backend saves file to backend/uploads/, runs IngestionService.ingest_pdf()
  → Returns IngestionJobResponse (202 Accepted)
  → Frontend polls GET /ingestion/jobs/{job_id} every 2s
  → Shows progress states: uploading → processing → done / failed
  → On done: refreshes document list
```

---

## Backend

### New endpoint

**File:** `backend/src/docifer_backend/api/ingestion.py`

```
POST /ingestion/upload
Content-Type: multipart/form-data
Fields:
  file          - PDF file (UploadFile, required)
  force_reprocess - bool (Form field, default false)

Response 202: IngestionJobResponse
Response 400: filename not .pdf or content-type not application/pdf
Response 500: ingestion failure
```

**Behaviour:**
1. Validate file extension is `.pdf` and `content_type` is `application/pdf` — raise `HTTP 400` otherwise
2. Create `backend/uploads/` directory if it does not exist
3. Save file to `backend/uploads/<uuid4>_<sanitised_original_filename>.pdf`
4. Call existing `IngestionService().ingest_pdf(saved_path, force_reprocess=force_reprocess)` inside `asyncio.to_thread`
5. Return `IngestionJobResponse` (same schema as existing `/ingestion/jobs` endpoint)

**Filename sanitisation:** strip path components, replace non-alphanumeric (except `-_.`) with `_`, truncate to 120 chars.

**No new schema** — reuses `IngestionJobResponse`:

```python
class IngestionJobResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    artifact_path: str | None
    reused_existing: bool
    error_message: str | None = None
```

### Tests

Add to `backend/tests/test_ingestion_upload.py`:

- `test_upload_rejects_non_pdf_extension` — POST `.txt` file → 400
- `test_upload_rejects_non_pdf_content_type` — POST with wrong content-type → 400
- `test_upload_saves_file_and_returns_job_response` — POST valid PDF bytes → 202, `IngestionJobResponse` fields present (mock `IngestionService.ingest_pdf`)

### `.gitignore`

Add `backend/uploads/` to `.gitignore`.

---

## Frontend

### New type (`frontend/src/types/api.ts`)

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

### New API methods (`frontend/src/lib/api.ts`)

```ts
uploadPdf: (file: File, forceReprocess = false) =>
  // POST /ingestion/upload as FormData
  // returns Promise<IngestionJobResponse>

ingestionJob: (jobId: string) =>
  // GET /ingestion/jobs/{jobId}
  // returns Promise<IngestionJobResponse>
```

`uploadPdf` uses `FormData` — no `Content-Type` header set manually (browser sets multipart boundary automatically).

### New component (`frontend/src/components/UploadPanel.tsx`)

**Props:**
```ts
interface UploadPanelProps {
  onIngestionComplete: () => void;
}
```

**States:**
```
idle → uploading → processing → done | failed
```

**UI:**
- `idle`: drag-and-drop zone with dashed border + "Drop a PDF or browse" label + hidden `<input type="file" accept=".pdf">`
- `uploading`: spinner + "Uploading…"
- `processing`: spinner + "Processing…" + polls every 2s
- `done`: green tick + filename + "Ready to query" — resets to `idle` after 3s
- `failed`: red alert + `error_message` from response or generic fallback

**Polling:**
- `setInterval` at 2000ms after upload returns `job_id`
- Clears interval on `done`, `failed`, or component unmount
- After 120s (60 polls) with no terminal status: auto-fail with "Ingestion timed out"

**Drag-and-drop:**
- `onDragOver` prevents default, adds visual hover class
- `onDrop` extracts first `.pdf` file and triggers upload
- Non-PDF drop: shows inline error "Only PDF files are supported"

### `App.tsx` changes

- Add `UploadPanel` at top of `document-rail` aside, above `DocumentList`
- Pass `onIngestionComplete={() => dociferApi.documents().then(r => { setDocuments(r.documents); })}` as prop

### CSS additions (`frontend/src/styles.css`)

New classes: `.upload-panel`, `.upload-zone`, `.upload-zone.is-drag-over`, `.upload-spinner`, `.upload-done`, `.upload-error`

---

## File Changeset

| File | Action |
|---|---|
| `backend/src/docifer_backend/api/ingestion.py` | Add `POST /ingestion/upload` |
| `backend/tests/test_ingestion_upload.py` | Create (3 tests) |
| `.gitignore` | Add `backend/uploads/` |
| `frontend/src/types/api.ts` | Add `IngestionJobResponse` |
| `frontend/src/lib/api.ts` | Add `uploadPdf`, `ingestionJob` |
| `frontend/src/components/UploadPanel.tsx` | Create |
| `frontend/src/styles.css` | Add upload panel styles |
| `frontend/src/App.tsx` | Wire `UploadPanel` |

---

## Success Criteria

- Upload a real PDF → document appears in document rail after indexing completes
- Upload non-PDF → frontend shows "Only PDF files are supported" without calling backend
- Upload with wrong content-type → backend returns 400, frontend shows error
- Ingestion failure → `error_message` shown in upload panel
- Component unmount during polling does not leak interval
- All 3 backend tests pass
- `npm run typecheck` passes
