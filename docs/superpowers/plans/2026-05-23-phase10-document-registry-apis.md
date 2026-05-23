# Phase 10 Document Registry and Index Status APIs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add typed document registry APIs that expose identity, modality readiness, parse audit state, and artifact provenance for the existing corpus.

**Architecture:** Keep `DocumentScopeResolver` as the authoritative `doc_id` identity layer and place registry aggregation in a new `documents/service.py` module. The service reads existing SQLAlchemy records and filesystem existence metadata, while a new FastAPI router presents typed Pydantic responses without affecting query retrieval behavior.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, pytest.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/src/docifer_backend/retrieval/document_registry.py` | Expose the existing corpus-ID mapping for registry consumers without duplicating it. |
| `backend/src/docifer_backend/schemas/documents.py` | Public typed response contracts for document APIs. |
| `backend/src/docifer_backend/documents/service.py` | Document aggregation, modality status calculation, audit selection, artifact references, and lookup errors. |
| `backend/src/docifer_backend/documents/__init__.py` | Documents package marker. |
| `backend/src/docifer_backend/api/documents.py` | `/documents` API routes and HTTP error conversion. |
| `backend/src/docifer_backend/main.py` | Register the documents router. |
| `backend/tests/test_document_registry_service.py` | Service tests for identity, status, audit, and artifact behavior. |
| `backend/tests/test_document_registry_api.py` | Endpoint, typed-output, route-ordering, and error tests. |
| `docs/phase10-document-registry-apis.md` | User-facing API and validation documentation. |
| `docs/session-changes-2026-05-20.md` | Phase/session implementation record once verified. |

### Task 1: Shared Identity and Typed Contracts

**Files:**
- Modify: `backend/src/docifer_backend/retrieval/document_registry.py`
- Create: `backend/src/docifer_backend/schemas/documents.py`
- Test: `backend/tests/test_document_registry_service.py`

- [x] **Step 1: Write failing schema and identity reuse tests**

```python
def test_doc_id_for_document_reuses_phase9_mapping():
    document = Document(
        id="document-5",
        filename="Worldbank2024.pdf",
        source_path="datasets/raw_pdfs/Worldbank2024.pdf",
        content_hash="a" * 64,
        file_size_bytes=10,
    )
    assert doc_id_for_document(document) == "DOC-005"


def test_modality_schema_accepts_explicit_unavailable_state():
    status = ModalityIndexStatus(
        status="not_available",
        count=0,
        latest_status="no_table_evidence",
    )
    assert status.status == "not_available"
```

- [x] **Step 2: Verify the tests fail because public identity/schema APIs do not exist**

Run:

```powershell
uv run --project backend pytest backend/tests/test_document_registry_service.py -q
```

Expected: collection/import failure for `doc_id_for_document` and document schemas.

- [x] **Step 3: Add the minimal public mapping function and typed models**

Expose a public identity function from the Phase 9 resolver module:

```python
def doc_id_for_document(document: Document) -> str | None:
    ...
```

Add typed Pydantic models including:

```python
class ModalityIndexStatus(BaseModel):
    status: Literal["indexed", "not_indexed", "not_available", "failed", "unknown"]
    count: int
    latest_status: str | None = None
    collection_name: str | None = None
    latest_indexed_at: datetime | None = None
```

- [x] **Step 4: Run the focused tests until green**

Run:

```powershell
uv run --project backend pytest backend/tests/test_document_registry_service.py -q
```

Expected: the identity/schema tests pass.

### Task 2: Registry Service Aggregation

**Files:**
- Create: `backend/src/docifer_backend/documents/__init__.py`
- Create: `backend/src/docifer_backend/documents/service.py`
- Modify: `backend/tests/test_document_registry_service.py`

- [x] **Step 1: Add failing service tests for summary status, identity lookup, and audit state**

Seed SQLAlchemy records for one indexed document and one document whose table
run status is `no_table_evidence`. Assert:

```python
summaries = service.list_documents(limit=50, offset=0).documents
assert summaries[0].modalities.text.status == "indexed"
assert summaries[1].modalities.table.status == "not_available"
assert service.get_by_doc_id("DOC-005").doc_id == "DOC-005"
assert service.get_by_content_hash("b" * 64).content_hash == "b" * 64
assert service.get_audit(document_id).latest_audit.quality_status == "good"
```

- [x] **Step 2: Verify red behavior**

Run:

```powershell
uv run --project backend pytest backend/tests/test_document_registry_service.py -q
```

Expected: failure because `DocumentRegistryService` does not exist.

- [x] **Step 3: Implement bounded aggregation and status mapping**

Implement:

```python
class DocumentRegistryService:
    def list_documents(... ) -> DocumentListResponse: ...
    def get_document(self, document_id: str) -> DocumentDetailResponse: ...
    def get_by_doc_id(self, doc_id: str) -> DocumentDetailResponse: ...
    def get_by_content_hash(self, content_hash: str) -> DocumentDetailResponse: ...
    def get_indexes(self, document_id: str) -> DocumentIndexStatusResponse: ...
    def get_audit(self, document_id: str) -> DocumentAuditResponse: ...
    def get_artifacts(self, document_id: str) -> DocumentArtifactsResponse: ...
```

Calculate state with the locked rules:

```python
if latest_status == "failed":
    status = "failed"
elif count > 0:
    status = "indexed"
elif latest_status in {"no_table_evidence", "no_visual_evidence"}:
    status = "not_available"
elif latest_status is None:
    status = "not_indexed"
else:
    status = "unknown"
```

Load documents and related rows in bounded batch queries; do not query each
document individually in the list loop.

- [x] **Step 4: Add failing artifact provenance/existence tests, then implement them**

Assert that a present canonical artifact returns `exists is True`, an absent
derived artifact returns `exists is False`, and visual artifacts identify
`source == "visual_evidence_records"`.

Use `resolve_project_path(path).exists()` only in detail/artifact requests.

- [x] **Step 5: Run the focused service test suite**

Run:

```powershell
uv run --project backend pytest backend/tests/test_document_registry_service.py -q
```

Expected: all registry service tests pass.

### Task 3: API Routes and Application Wiring

**Files:**
- Create: `backend/src/docifer_backend/api/documents.py`
- Modify: `backend/src/docifer_backend/main.py`
- Create: `backend/tests/test_document_registry_api.py`

- [x] **Step 1: Write failing API tests**

Create a fake document service and assert:

```python
assert client.get("/documents").status_code == 200
assert client.get("/documents/by-doc-id/DOC-005").json()["doc_id"] == "DOC-005"
assert client.get("/documents/by-content-hash/" + "a" * 64).status_code == 200
assert client.get("/documents/document-5/indexes").json()["modalities"]["text"]["status"] == "indexed"
assert client.get("/documents/missing").status_code == 404
```

Include a route-ordering assertion that `/documents/by-doc-id/DOC-005` invokes
the lookup route rather than the UUID detail route.

- [x] **Step 2: Verify the route tests fail before router implementation**

Run:

```powershell
uv run --project backend pytest backend/tests/test_document_registry_api.py -q
```

Expected: requests fail with `404 Not Found`.

- [x] **Step 3: Implement document routes and register the router**

Implement:

```python
router = APIRouter(prefix="/documents", tags=["documents"])

@router.get("", response_model=DocumentListResponse)
def list_documents(...): ...

@router.get("/by-doc-id/{doc_id}", response_model=DocumentDetailResponse)
def get_by_doc_id(doc_id: str): ...

@router.get("/by-content-hash/{content_hash}", response_model=DocumentDetailResponse)
def get_by_content_hash(content_hash: str): ...
```

Define lookup routes before `/{document_id}` and translate service not-found
and ambiguous errors into `404` and `409` responses.

- [x] **Step 4: Run API tests**

Run:

```powershell
uv run --project backend pytest backend/tests/test_document_registry_api.py -q
```

Expected: all API route tests pass.

### Task 4: Regression Verification and Documentation

**Files:**
- Create: `docs/phase10-document-registry-apis.md`
- Modify: `backend/README.md`
- Modify: `docs/session-changes-2026-05-20.md`

- [x] **Step 1: Run targeted and full backend verification**

Run:

```powershell
uv run --project backend pytest backend/tests/test_document_registry_service.py backend/tests/test_document_registry_api.py -q
uv run --project backend pytest --basetemp backend/.pytest_tmp
uv run --project backend python -m compileall -q backend/src backend/tests
```

Expected: all tests pass and compile check exits successfully.

- [x] **Step 2: Run the service against local indexed corpus data**

Start the API and request:

```text
GET /documents
GET /documents/by-doc-id/DOC-005
GET /documents/{document_id}/indexes
GET /documents/{document_id}/audit
GET /documents/{document_id}/artifacts
```

Confirm 12 corpus documents are visible and at least one missing table or
visual modality is returned as `not_available`, not hidden.

- [x] **Step 3: Document the verified API contract and measured outcome**

Record endpoints, identity rules, modality statuses, artifact provenance,
known v1 limitations, automated test output, and live corpus validation
results in the Phase 10 documentation and session log.

- [x] **Step 4: Refresh graph documentation**

Run:

```powershell
graphify update .
```

Expected: knowledge graph refresh completes after the new API/service files
are present.
