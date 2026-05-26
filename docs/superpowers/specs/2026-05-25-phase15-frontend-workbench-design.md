# Phase 15 Frontend Workbench Design

## Goal

Build Docifer's first frontend as a real operator workbench with portfolio-grade polish. The first screen should be the usable document QA app, not a marketing landing page.

## Product Shape

The frontend is a single-page workbench backed by the existing FastAPI API.

Primary layout:

- Left rail: indexed documents from `GET /documents`
- Center workspace: query composer, submitted question, answer, and loading/error states
- Right panel: selected document readiness, citations, retrieved evidence, unused evidence, verification, and debug
- Top status strip: backend health/readiness, active scope, evidence mode, and request latency

The default workflow is:

1. User opens the app.
2. App checks backend health/readiness.
3. App loads indexed documents.
4. User selects a document or switches to corpus-wide mode.
5. User asks a question.
6. App sends `/query`.
7. App renders answer, citations, evidence, and diagnostics.

## Architecture

Use Vite + React + TypeScript in the existing empty `frontend/` directory.

Recommended file map:

```text
frontend/
  package.json
  index.html
  vite.config.ts
  tsconfig.json
  src/
    main.tsx
    App.tsx
    styles.css
    types/api.ts
    lib/api.ts
    components/
      AnswerPanel.tsx
      DocumentList.tsx
      EvidencePanel.tsx
      QueryComposer.tsx
      StatusStrip.tsx
```

Backend prep:

- Add CORS settings to backend configuration.
- Register `CORSMiddleware` in `docifer_backend.main`.
- Default local allowed origin should include Vite's dev server: `http://127.0.0.1:5173` and `http://localhost:5173`.
- Document the backend/frontend run commands.

## UI Behavior

### Document List

The left rail shows all indexed documents from `GET /documents`.

Each document item shows:

- public `doc_id` when available
- filename
- latest ingestion status
- text/table/visual modality badges
- quality status when available

Selecting a document sets query scope to `single` using its `content_hash`.

### Query Composer

The query composer supports:

- question text
- scope: selected document or all documents
- evidence mode: `text`, `table`, `visual`, or `auto`
- retrieval mode: `hybrid` by default
- top-k with a conservative default of `4`
- verify citations toggle, default on

The composer should prevent invalid requests:

- single-document scope requires a selected document
- corpus-wide scope sends `scope="all"` and no document filters
- empty question cannot submit

### Answer Panel

The answer panel renders:

- answer text
- final answer citations
- visual/table citation badges where present
- request latency
- clear loading and error states

It should preserve citation IDs like `[C1]`, `[T1]`, and `[V1]` in the answer text.

### Evidence Panel

The right panel uses tabs:

- Citations
- Retrieved Evidence
- Unused Evidence
- Debug

Citations and evidence items show:

- citation ID
- document/file identity
- page range
- score fields when available
- text/table/visual snippet

Debug is intentionally expandable and not the default tab. The response payload can be large, so the default view should stay readable.

### Status Strip

The top strip shows:

- backend health/readiness
- selected scope
- selected evidence mode
- latest latency
- error count or latest request status

## Visual Style

The UI should feel like a careful operational tool:

- restrained palette with strong contrast
- dense but readable panels
- no marketing hero as the first screen
- no decorative card piles
- clear tabs, badges, buttons, and loading states
- cards only for repeated items such as documents and evidence records

Avoid oversized landing-page typography. The user should immediately understand that this is the working Docifer app.

## Error Handling

The frontend should handle:

- backend unavailable
- `/documents` load failure
- validation errors from `/query`
- query timeout or network failure
- empty document list
- answer with no citations
- abstention answer

Errors should be visible and actionable without hiding the rest of the app.

## Testing And Validation

Minimum validation:

- frontend typecheck passes
- frontend production build passes
- backend test suite passes after CORS changes
- browser smoke test loads the app
- browser smoke test confirms documents render from the backend
- browser smoke test submits a real query and renders answer/citations or a clear backend error

Manual run commands should be documented in `README.md` and `backend/README.md`.

## Out Of Scope For Phase 15

- authentication
- user accounts
- file upload UI
- live ingestion workflow
- deployment to a hosted environment
- full portfolio landing page
- chart rendering from visual artifacts
- editing or annotating source documents

Those can follow once the workbench exists and proves the end-to-end product path.

## Success Criteria

Phase 15 is valid when:

- `frontend/` contains a working Vite React TypeScript app.
- The app can load real documents from the backend.
- The app can submit a query to `/query`.
- Answers, citations, evidence, and errors are readable.
- Local backend/frontend run instructions are documented.
- Backend CORS allows the local frontend dev server.
- Automated build/typecheck and backend tests pass.
