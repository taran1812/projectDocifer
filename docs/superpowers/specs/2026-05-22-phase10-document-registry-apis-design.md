# Phase 10 - Document Registry and Index Status APIs Design

## Status

Approved design refinements captured before implementation.

## Goal

Phase 10 adds backend inspection APIs so Docifer can reliably answer:

- Which documents are present in the system?
- Which user-facing corpus ID maps to which internal document and content hash?
- Which evidence modalities are indexed, unavailable, failed, or not yet indexed?
- What is the latest parse-quality assessment?
- Which generated artifacts exist and where did their metadata come from?

Phase 9 made multi-document retrieval available through `single`, `doc_ids`, and
`all` query scopes. Phase 10 provides the document visibility and status model
needed to operate that capability safely and expose it to a future frontend.

## Scope

### In Scope

- Shared document identity lookup based on the existing Phase 9 resolver.
- Typed document list and detail API responses.
- First-class lookup endpoints for `doc_id` and `content_hash`.
- Text, table, and visual modality statuses with evidence counts.
- Latest parse-quality audit visibility.
- Artifact metadata with existence checks and provenance.
- Search, filtering, pagination, tests, and documentation.
- Validation against all 12 documents in the current corpus.

### Out of Scope

- Frontend implementation.
- Background ingestion or indexing job orchestration.
- New retrieval, reranking, or generation algorithms.
- Moving `doc_id` into a new persisted database column.
- Exposing raw artifact file contents.
- Cloud deployment or distributed storage behavior.

## Locked Decisions

### 1. Phase 9 Resolver Is the Identity Source

Phase 10 must not introduce a parallel identity mapping implementation.

The current Phase 9 resolver in
`backend/src/docifer_backend/retrieval/document_registry.py` already resolves:

```text
doc_id -> document_id -> content_hash -> filename/source_path
```

Phase 10 should reuse or promote that implementation into a shared service
boundary. Both `/query` scope resolution and the new `/documents` APIs must
delegate to the same identity behavior.

For v1:

| Identifier | Meaning | Source |
|---|---|---|
| `document_id` | Internal API path identifier and database UUID | Database |
| `content_hash` | Durable document content identity | Database |
| `doc_id` | User-facing corpus identity such as `DOC-005` | Phase 9/starter corpus resolver |
| `filename` | Display value only | Database |
| `source_path` | Source location metadata | Database |

`filename` must never be accepted as a primary document identifier because it
is not guaranteed to be unique.

### 2. Modality State Is Explicit, Not Boolean-Only

Phase 10 must not represent index readiness solely as `count > 0` booleans.
A completed table or visual indexing run may correctly produce no evidence.

All modality responses use:

```text
indexed
not_indexed
not_available
failed
unknown
```

Semantics:

| Status | Meaning |
|---|---|
| `indexed` | Latest usable modality state has one or more retrievable evidence records. |
| `not_indexed` | No completed indexing attempt exists for this modality. |
| `not_available` | An indexing attempt completed successfully, but the document has no evidence of that modality. |
| `failed` | The latest relevant indexing attempt failed and no newer usable result supersedes it. |
| `unknown` | Existing records cannot be interpreted consistently or legacy data lacks enough state. |

Every modality status also exposes a count and its latest underlying run
status when available. This separates the question "was it processed?" from
"is evidence available?"

Example:

```json
{
  "modalities": {
    "text": {
      "status": "indexed",
      "count": 1235,
      "latest_status": "indexed"
    },
    "table": {
      "status": "not_available",
      "count": 0,
      "latest_status": "no_evidence"
    },
    "visual": {
      "status": "indexed",
      "count": 44,
      "latest_status": "indexed"
    }
  }
}
```

### 3. Field Provenance Is Part of the Contract

Phase 10 responses must distinguish database truth from values derived from
generated files or resolver mapping.

| Field | Source |
|---|---|
| `document_id`, `content_hash`, `filename`, `source_path`, `file_size_bytes` | Database `documents` row |
| `doc_id` | Shared Phase 9/starter corpus resolver |
| `latest_ingestion_status`, parser metadata, ingestion artifact root | Latest ingestion job row |
| `text_chunk_count` | Text evidence database records |
| `table_evidence_count` | Table evidence database records |
| `visual_record_count` | Visual evidence database records |
| `quality_status`, readiness, risk flags, audit summary | Latest parse-quality audit row |
| `canonical_json`, `document_md`, `docling_json`, `parse_summary_json` | Latest ingestion artifact metadata/path convention |
| `parse_audit_json`, `parse_audit_md` | Latest audit metadata/path convention |
| `artifact_exists` | Filesystem check at request time |
| Visual page artifact metadata | Visual evidence records plus filesystem check |

If an ingestion count such as page, table, or figure count is not stored in a
database row, it may be exposed only as a nullable artifact- or audit-derived
field with clear provenance. It must not be presented as persisted ingestion
job state.

### 4. Artifact Existence and Provenance Are Required in v1

Artifact responses return metadata only, never raw file contents. Each
artifact reference includes the path, current filesystem existence, source,
producer, and artifact type.

```json
{
  "path": "datasets/processed/.../canonical.json",
  "exists": true,
  "source": "latest_ingestion_job",
  "generated_by": "ingestion",
  "artifact_type": "canonical_json"
}
```

Visual artifacts use the same trust model:

```json
{
  "visual_id": "...",
  "visual_type": "page_render",
  "page_start": 1,
  "artifact_path": "datasets/processed/.../visuals/pages/page_0001.jpg",
  "exists": true,
  "source": "visual_evidence_records"
}
```

The API must make absent artifact paths and known-but-missing files
distinguishable.

## Required Endpoints

Add a router at:

```text
backend/src/docifer_backend/api/documents.py
```

Register it in:

```text
backend/src/docifer_backend/main.py
```

The following endpoints are required for Phase 10:

```text
GET /documents
GET /documents/{document_id}
GET /documents/by-doc-id/{doc_id}
GET /documents/by-content-hash/{content_hash}
GET /documents/{document_id}/indexes
GET /documents/{document_id}/audit
GET /documents/{document_id}/artifacts
```

Route ordering must ensure `/documents/by-doc-id/...` and
`/documents/by-content-hash/...` cannot be consumed by the
`/{document_id}` route.

## Endpoint Contracts

### `GET /documents`

Lists ingested documents, including documents without available evidence.
Index state is presented in the summary instead of being used to silently
exclude records.

Supported query parameters:

```text
q
doc_id
quality_status
text_status
table_status
visual_status
parser_name
limit
offset
```

Defaults and limits:

```text
limit = 50
offset = 0
maximum limit = 200
```

For v1, `doc_id` filtering is resolved through the shared identity service
before database filtering. `q` may search database-backed filename,
source-path, and content-hash values; corpus-ID matching may be applied through
the resolver for the small starter corpus.

Example response:

```json
{
  "documents": [
    {
      "document_id": "30abbd45-a8d4-4585-82a7-326c7ab76786",
      "doc_id": "DOC-005",
      "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
      "filename": "Worldbank2024.pdf",
      "source_path": "datasets/raw_pdfs/Worldbank2024.pdf",
      "latest_ingestion_status": "parsed",
      "quality_status": "good",
      "modalities": {
        "text": {"status": "indexed", "count": 5, "latest_status": "indexed"},
        "table": {"status": "indexed", "count": 1, "latest_status": "indexed"},
        "visual": {"status": "indexed", "count": 7, "latest_status": "indexed"}
      }
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### `GET /documents/{document_id}`

Returns document identity, persisted metadata, latest ingestion metadata,
modality summary, latest audit summary, and compact artifact references.

Any derived parse counts must be nullable and labeled through their response
model or documented source; this endpoint must not imply that artifact-derived
values are columns of the ingestion job.

### `GET /documents/by-doc-id/{doc_id}`

Returns the same detail contract as `GET /documents/{document_id}`, resolving
the user-facing corpus ID through the shared Phase 9 identity source.

### `GET /documents/by-content-hash/{content_hash}`

Returns the same detail contract as `GET /documents/{document_id}`, resolving
the durable content identity through database-backed lookup.

### `GET /documents/{document_id}/indexes`

Returns modality statuses, counts, latest run state, collection metadata where
applicable, and latest indexing timestamp where available.

```json
{
  "document_id": "30abbd45-a8d4-4585-82a7-326c7ab76786",
  "doc_id": "DOC-005",
  "content_hash": "8109582811fe1ec5812a857c9f5d1f3112771b3ce2c810c1161e3303193ea3a8",
  "modalities": {
    "text": {
      "status": "indexed",
      "count": 5,
      "latest_status": "indexed",
      "collection_name": "docifer_text_chunks",
      "latest_indexed_at": "..."
    },
    "table": {
      "status": "not_available",
      "count": 0,
      "latest_status": "no_evidence",
      "collection_name": "docifer_table_evidence",
      "latest_indexed_at": "..."
    },
    "visual": {
      "status": "indexed",
      "count": 7,
      "latest_status": "indexed",
      "collection_name": "docifer_visual_evidence",
      "latest_indexed_at": "..."
    }
  }
}
```

### `GET /documents/{document_id}/audit`

Returns the latest parse-quality audit or `null` when no audit exists.

The response uses a typed audit model containing quality status, modality
readiness, risk flags, derived summary counts where present, artifact
references, and timestamp metadata.

### `GET /documents/{document_id}/artifacts`

Returns typed references for known ingestion, audit, and visual artifacts.
Every returned path includes its existence status and provenance. Missing
artifacts are normal inspectable state, not an API failure.

## Typed Response Models

Public API response models belong in:

```text
backend/src/docifer_backend/schemas/documents.py
```

No public response should use `dict[str, Any]` for modality state, audit
details, or artifact records.

Recommended public models:

```python
class ModalityIndexStatus(BaseModel):
    status: Literal["indexed", "not_indexed", "not_available", "failed", "unknown"]
    count: int
    latest_status: str | None = None
    collection_name: str | None = None
    latest_indexed_at: datetime | None = None


class DocumentModalitiesResponse(BaseModel):
    text: ModalityIndexStatus
    table: ModalityIndexStatus
    visual: ModalityIndexStatus


class ArtifactReference(BaseModel):
    path: str | None
    exists: bool
    source: str
    generated_by: str
    artifact_type: str


class VisualArtifactReference(BaseModel):
    visual_id: str
    visual_type: str
    page_start: int | None
    artifact_path: str
    exists: bool
    source: str


class DocumentSummaryResponse(BaseModel):
    document_id: str
    doc_id: str | None
    content_hash: str
    filename: str
    source_path: str
    latest_ingestion_status: str | None
    quality_status: str | None
    modalities: DocumentModalitiesResponse


class DocumentDetailResponse(BaseModel):
    document_id: str
    doc_id: str | None
    content_hash: str
    filename: str
    source_path: str
    file_size_bytes: int | None
    latest_ingestion: LatestIngestionResponse | None
    modalities: DocumentModalitiesResponse
    latest_audit: DocumentAuditSummaryResponse | None
    artifacts: list[ArtifactReference]


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummaryResponse]
    total: int
    limit: int
    offset: int


class DocumentIndexStatusResponse(BaseModel):
    document_id: str
    doc_id: str | None
    content_hash: str
    modalities: DocumentModalitiesResponse


class DocumentAuditResponse(BaseModel):
    document_id: str
    doc_id: str | None
    content_hash: str
    latest_audit: DocumentAuditSummaryResponse | None
    warning: str | None = None


class DocumentArtifactsResponse(BaseModel):
    document_id: str
    doc_id: str | None
    content_hash: str
    artifacts: list[ArtifactReference]
    visual_artifacts: list[VisualArtifactReference]
```

The implementation plan must define the nested
`LatestIngestionResponse` and `DocumentAuditSummaryResponse` fields directly
from the existing model columns and supported derived values.

## Service Boundary

Use a focused documents service while preserving the Phase 9 resolver as the
single identity source.

Expected files:

```text
backend/src/docifer_backend/documents/__init__.py
backend/src/docifer_backend/documents/service.py
backend/src/docifer_backend/schemas/documents.py
backend/src/docifer_backend/api/documents.py
backend/src/docifer_backend/main.py
```

Responsibilities:

| File | Responsibility |
|---|---|
| `retrieval/document_registry.py` or promoted shared equivalent | Existing authoritative `doc_id`/scope identity resolution used by both query and document API paths. |
| `documents/service.py` | Database aggregation, latest-run selection, modality state calculation, artifact metadata and existence checks. |
| `schemas/documents.py` | Typed request/response contracts for public document APIs. |
| `api/documents.py` | Routes, dependency wiring, query validation, HTTP error conversion. |
| `main.py` | Router registration only. |

If the resolver is moved into a neutral shared module, the move must preserve
Phase 9 query behavior and avoid keeping duplicate mappings behind.

## Data Aggregation Rules

The service should combine existing data from:

```text
documents
ingestion_jobs
document_index_runs
text_chunks
table_evidence_records
document_table_index_runs
visual_evidence_records
document_visual_index_runs
parse_quality_audits
```

The list endpoint should avoid per-document query multiplication. It should
load document rows with grouped evidence counts and latest status/audit
summaries using bounded aggregate queries suitable for pagination. Artifact
filesystem checks belong in detail/artifacts endpoints, not as an expensive
requirement for the full document list.

## Error Handling

| Condition | HTTP Status | Detail |
|---|---:|---|
| Unknown `document_id` | 404 | `Document not found.` |
| Unknown `doc_id` | 404 | `No document is mapped to doc_id DOC-999.` |
| Unknown `content_hash` | 404 | `Document not found for content hash.` |
| Ambiguous resolver match | 409 | `Document lookup is ambiguous.` |
| Registry aggregation/data failure | 500 | `Unable to load document registry state.` |

Missing audits and missing files are successful API responses with explicit
`null` or `exists: false` values, not server errors.

## Implementation Sequence

1. Reuse or promote the Phase 9 identity resolver without introducing a
   parallel mapping.
2. Add typed document registry API models.
3. Implement `GET /documents`.
4. Implement `GET /documents/{document_id}`.
5. Implement `GET /documents/by-doc-id/{doc_id}`.
6. Implement `GET /documents/by-content-hash/{content_hash}`.
7. Implement `/indexes` with modality statuses and counts.
8. Implement `/audit` with typed latest-audit output.
9. Implement `/artifacts` with existence and provenance metadata.
10. Add document service tests.
11. Add document API tests and backward compatibility tests.
12. Validate against all 12 indexed corpus documents.
13. Update backend and session documentation with actual validation results.

## Testing Requirements

### Service Tests

Tests must cover:

- `doc_id`, `document_id`, and `content_hash` all resolve through the shared
  identity behavior.
- Summary aggregation includes counts and typed modality states.
- Completed zero-evidence table or visual runs produce `not_available`, not
  `not_indexed`.
- Failed latest run state is exposed as `failed`.
- Missing run information produces `not_indexed` or `unknown` according to the
  available database state.
- Latest audit selection is deterministic.
- No-audit documents return `null` audit state.
- Artifact paths report `exists: true` and `exists: false` correctly.
- Visual artifact provenance is returned from visual evidence metadata.
- Unknown and ambiguous identities raise the service errors converted by the
  API layer.

### API Tests

Tests must cover:

- Pagination and supported filters for `GET /documents`.
- Documents with no table or visual evidence remain visible.
- Detail retrieval by UUID, `doc_id`, and `content_hash`.
- Typed modality status output from `/indexes`.
- Null-audit response behavior from `/audit`.
- Artifact provenance and file-existence output from `/artifacts`.
- Correct `404`, `409`, and validation responses.
- Route ordering for the two lookup endpoints.

### Regression Tests

Existing endpoints must continue to work:

```text
GET /health
GET /ready
POST /query
POST /index/text
POST /index/tables
POST /index/visuals
```

In particular, Phase 9 `scope="single"`, `scope="doc_ids"`, and
`scope="all"` behavior must remain unchanged after shared resolver reuse or
promotion.

## Real Validation Gate

After implementation:

```powershell
uv run --project backend pytest --basetemp backend/.pytest_tmp
uv run --project backend python -m compileall -q backend/src backend/tests
```

Start the current backend and smoke test:

```text
GET /documents
GET /documents/by-doc-id/DOC-005
GET /documents/by-content-hash/{content_hash}
GET /documents/{document_id}
GET /documents/{document_id}/indexes
GET /documents/{document_id}/audit
GET /documents/{document_id}/artifacts
```

Validate all 12 corpus documents, not only a document with full evidence. The
validation must explicitly include documents with absent table or visual
evidence and confirm they are represented as `not_available` rather than
hidden or mislabeled.

Expected existing-data baseline:

```text
12 corpus documents visible through the registry
text-index state available for all previously reindexed text documents
document identity agrees with Phase 9 multi-document query resolution
table and visual modality status varies truthfully by document
missing audits or artifacts are represented without API failure
```

## Documentation Deliverables

After implementation, add or update:

```text
docs/phase10-document-registry-apis.md
backend/README.md
docs/session-changes-2026-05-20.md
```

Documentation should contain endpoint examples, identity semantics, modality
status definitions, artifact provenance behavior, limitations of mapped
`doc_id` values in v1, and recorded validation results.

## Success Criteria

Phase 10 is complete only when:

- All seven required document endpoints are implemented with typed responses.
- Phase 9 identity behavior is reused rather than duplicated.
- Modality state distinguishes indexed, not indexed, unavailable, failed, and
  unknown conditions.
- Artifact responses expose path existence and provenance.
- Lookup by `doc_id` and `content_hash` works as a supported public API.
- Full backend tests and compile validation pass.
- Existing `/query` multi-document scopes have no regression.
- Real validation confirms correct registry state across all 12 corpus
  documents, including missing table/visual cases.
- Documentation records the implemented contract and validation results.

## Next Phase Boundary

Phase 10 remains a backend inspectability phase. It does not introduce a
frontend or alter retrieval quality. Once its validation gate passes, later
work may use these stable registry contracts for integration tests, benchmark
reporting, and a user-facing application.
