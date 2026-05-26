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
