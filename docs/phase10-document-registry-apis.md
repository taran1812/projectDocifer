# Phase 10 - Document Registry and Index Status APIs

## Goal

Phase 10 makes document identity and evidence readiness inspectable through a
typed backend API. It builds on Phase 9 multi-document query scope without
changing retrieval or generation behavior.

## Endpoints

```text
GET /documents
GET /documents/{document_id}
GET /documents/by-doc-id/{doc_id}
GET /documents/by-content-hash/{content_hash}
GET /documents/{document_id}/indexes
GET /documents/{document_id}/audit
GET /documents/{document_id}/artifacts
```

`doc_id` values such as `DOC-005` are resolved through the same Phase 9
starter-corpus mapping used by multi-document queries. `document_id` is the
internal database UUID and `content_hash` is the durable content identity.
If a mapped public ID would resolve to multiple ingested documents, the lookup
returns `409` rather than selecting one arbitrarily.

## Modality Status

Each document exposes separate text, table, and visual readiness records:

| Status | Meaning |
|---|---|
| `indexed` | Evidence records are available for retrieval. |
| `not_indexed` | No completed index result is recorded for this modality. |
| `not_available` | Indexing completed successfully but found no evidence of the modality. |
| `failed` | The latest indexing attempt failed. |
| `unknown` | Stored records and run state do not form a known usable outcome. |

Each modality also includes `count`, `latest_status`, `collection_name`, and
`latest_indexed_at` where available.

## Artifact Metadata

`GET /documents/{document_id}/artifacts` exposes metadata rather than raw
artifact contents. Ingestion and audit references include:

```json
{
  "path": "datasets/processed/.../canonical.json",
  "exists": true,
  "source": "latest_ingestion_job",
  "generated_by": "ingestion",
  "artifact_type": "canonical_json"
}
```

Visual evidence artifacts include their visual identifier, type, page, path,
existence flag, and `source="visual_evidence_records"`.

## Example Inspection

Open Swagger UI at:

```text
http://127.0.0.1:8000/docs
```

Useful first calls:

```text
GET /documents?limit=20
GET /documents/by-doc-id/DOC-005
GET /documents/30abbd45-a8d4-4585-82a7-326c7ab76786/indexes
GET /documents/30abbd45-a8d4-4585-82a7-326c7ab76786/audit
GET /documents/30abbd45-a8d4-4585-82a7-326c7ab76786/artifacts
```

## Validation

Automated validation:

```text
Phase 10 focused tests: 12 passed
Full backend suite: 134 passed, 1 xfailed
Compile check: passed
```

Live validation was run through the current API on port `8000`:

```text
Documents returned: 12
Text status: indexed for 12 documents
Table status: indexed for 10, not_indexed for 2
Visual status: indexed for 9, not_indexed for 3
```

`DOC-005` resolved successfully to its stored UUID/content hash and returned:

```text
text evidence count: 5
table evidence count: 3
visual evidence count: 7
core artifacts returned: 6, all existing
visual artifact records returned: 7
latest audit quality: weak
```

Unit coverage validates the distinct `not_available` outcome for completed
zero-evidence table and visual index runs. In the current real corpus, the
documents without table or visual evidence runs are presently `not_indexed`,
which correctly distinguishes unprocessed modalities from processed documents
with no evidence.

## Known v1 Limitation

`doc_id` is derived from the current starter-corpus mapping rather than stored
as a first-class database field. A future document-registration phase may
persist public identifiers once corpus management expands beyond the fixed
evaluation set.
