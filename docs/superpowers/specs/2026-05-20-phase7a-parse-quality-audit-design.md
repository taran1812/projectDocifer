# Phase 7A — Parse Quality Audit: Design Spec

**Date:** 2026-05-20
**Phase:** 7A
**Status:** Approved
**Deliverable:** Reusable `ParseQualityService` that audits canonical artifacts after ingestion and on demand, storing structured verdicts in Postgres and writing per-document audit artifacts.

---

## 1. Goals

- Assess parse quality for every indexed document automatically after ingestion
- Support manual re-audit via CLI with multiple identifier types
- Produce advisory readiness verdicts (text / table / visual) without blocking ingestion
- Preserve full audit history so heuristic improvements can be compared across versions
- Surface operational risk flags to inform Phase 7B (table QA) scope decisions

---

## 2. Module Structure

```
docifer_backend/
  audit/
    __init__.py
    models.py        # SQLAlchemy model: parse_quality_audits
    metrics.py       # stat extraction + heuristic verdict logic
    service.py       # ParseQualityService (orchestrator)
    reporting.py     # writes parse_audit.json + parse_audit.md
    cli.py           # manual re-run CLI commands
```

---

## 3. Database Schema

Table: `parse_quality_audits`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | FK → documents | |
| `content_hash` | str | durable identity |
| `canonical_path` | str | exact artifact used for this audit |
| `parser_name` | str | `docling` or `pypdfium2-text` |
| `parser_version` | str | from canonical metadata |
| `canonical_schema_version` | str \| null | schema version from canonical.json, if present |
| `fallback_used` | bool | True when pypdfium2-text was used |
| `fallback_reason` | str \| null | `docling_failed` \| `size_threshold` \| `manual_backend` \| `unknown` |
| `audit_version` | str | semver; bump when heuristic logic changes |
| `audit_run_id` | UUID | groups batch re-runs (e.g. `--all-indexed`) |
| `audit_status` | str | `completed` \| `failed` |
| `error_message` | str \| null | populated on failure |
| `failed_stage` | str \| null | `read_canonical` \| `read_markdown` \| `read_docling_json` \| `compute_metrics` \| `write_artifacts` \| `persist_db` |
| `is_latest` | bool | True for most recent audit per `content_hash` |
| `quality_status` | str | overall: `good` \| `weak` \| `poor` |
| `text_readiness` | str | `good` \| `weak` \| `poor` |
| `table_readiness` | str | `good` \| `weak` \| `poor` |
| `visual_readiness` | str | `good` \| `weak` \| `poor` |
| `risk_flags_json` | JSON | list of flag strings (see Section 6) |
| `summary_json` | JSON | raw counts: pages, tables, figures, empty pages, etc. |
| `artifact_json_path` | str \| null | path to `parse_audit.json`; null on write failure |
| `artifact_md_path` | str \| null | path to `parse_audit.md`; null on write failure |
| `elapsed_ms` | int \| null | wall-clock duration of audit run in milliseconds |
| `created_at` | datetime | |

---

## 4. Data Flow

### Auto-trigger (post-ingestion)

```
IngestionService.ingest(pdf_path)
  → parse PDF
  → write canonical.json
  → ingestion_status = "parsed"          ← never blocked by audit
  → ParseQualityService.audit(canonical_path, content_hash)
      → logs warning/error internally on failure
      → audit_status = "completed" | "failed"
      → error_message + failed_stage populated on failure
      → always attempts DB persist
  → ingestion continues regardless of audit outcome
```

### Manual re-run (CLI)

```bash
docifer audit --doc-id DOC-001
docifer audit --content-hash <sha256>
docifer audit --canonical-path /path/to/canonical.json
docifer audit --all-indexed [--audit-run-id <uuid>]
```

`--all-indexed` targets all documents with at least one successful `DocumentIndexRun` row or at least one persisted `TextChunkRecord`.

`--all-indexed` generates one shared `audit_run_id` UUID and processes each document in sequence.

### `is_latest` maintenance

On every new audit insert:
```sql
INSERT INTO parse_quality_audits (..., is_latest=True)
UPDATE parse_quality_audits SET is_latest = False
  WHERE content_hash = <hash> AND id != <new_id>
```

History is preserved. Latest row always queryable with `WHERE is_latest = True`.

---

## 5. Source Reading Priority

For each audit, read sources in this order:

1. **`canonical.json`** — parser name/version, page count, table/figure counts, parse errors, artifact paths
2. **`document.md`** — always read for text-density metrics (chars/page, empty page detection), regardless of parser
3. **`docling.json`** (when `canonical.artifacts.docling_json` is present) — rich table objects, figure objects with captions
4. **Fallback indicators** — when docling.json absent, derive table/visual metrics from canonical counts and text patterns only

---

## 6. Heuristic Verdicts (Advisory Only)

Verdicts never block ingestion or indexing. They inform Phase 7B scope decisions.

### Text Readiness

| Verdict | Rule |
|---|---|
| `good` | chars/page > 200 AND < 5% empty pages |
| `weak` | fallback parser used, OR sparse pages (5–30% empty), OR low text density |
| `poor` | > 30% empty pages OR near-zero extracted text |

### Table Readiness

| Verdict | Rule |
|---|---|
| `good` | Docling parsed AND ≥1 table with header + ≥2 rows + ≥2 cols |
| `weak` | table-like content found but weak structure (missing headers, single row/col, partial extraction), OR fallback parser with table-like text patterns detected |
| `poor` | fallback parser with no structured tables AND no table-like text evidence |

### Visual Readiness

| Verdict | Rule |
|---|---|
| `good` | Docling parsed AND ≥1 figure with caption ≥ 10 chars |
| `weak` | figures found but no/short captions (< 10 chars) |
| `poor` | fallback parser OR zero figures OR no visual metadata |

### Overall Quality Status

Derived from the three readiness signals:
- `good` — all three readiness values are `good`
- `weak` — no `poor` values, but at least one `weak`
- `poor` — `text_readiness` is `poor`, OR two or more signals are `poor`

---

## 7. Risk Flags

Additive list stored in `risk_flags_json`:

| Flag | Condition |
|---|---|
| `fallback_parser_used` | `fallback_used = True` |
| `no_structured_tables` | 0 tables in docling output or fallback parser |
| `no_figures` | 0 figures detected |
| `high_empty_page_ratio` | > 10% empty pages |
| `parse_errors_present` | parse error count > 0 in canonical |
| `low_text_density` | average chars/page < 100 |
| `large_document` | page count > 200 |
| `high_chunk_count` | chunk count > 1000 (from TextChunkRecord if available) |
| `table_like_text_without_structure` | text patterns suggest tabular data but no structured tables extracted |
| `missing_docling_json` | canonical references docling_json artifact path but file not found |

---

## 8. Artifacts

Written to the same directory as `canonical.json`:

**`parse_audit.json`** — machine-readable:
```json
{
  "audit_version": "0.1.0",
  "audit_run_id": "<uuid>",
  "audit_status": "completed",
  "content_hash": "...",
  "parser_name": "docling",
  "fallback_used": false,
  "quality_status": "weak",
  "text_readiness": "good",
  "table_readiness": "weak",
  "visual_readiness": "weak",
  "risk_flags": ["no_structured_tables"],
  "elapsed_ms": 312,
  "summary": {
    "page_count": 42,
    "table_count": 3,
    "table_candidate_count": 5,
    "table_like_page_count": 7,
    "figure_count": 1,
    "figure_candidate_count": 2,
    "caption_candidate_count": 1,
    "empty_page_count": 2,
    "text_chars_total": 84000,
    "avg_chars_per_page": 2000
  }
}
```

**`parse_audit.md`** — human-readable report with per-document verdict table, risk flag list, and per-table / per-figure breakdown when docling.json is available.

If the artifact directory is missing or unwritable:
- `artifact_json_path = null`
- `artifact_md_path = null`
- `audit_status = failed`
- `failed_stage = write_artifacts`
- `summary_json` persisted in DB if metrics were already computed

---

## 9. Error Handling

Audit failure is never surfaced to the ingestion caller. Internally:

1. Log at `WARNING` or `ERROR` level with `failed_stage` and `error_message`
2. Always attempt to persist a DB row with `audit_status = failed`
3. Include partial `summary_json` if metrics were computed before failure
4. Set `artifact_json_path = null` and `artifact_md_path = null` on write failure

---

## 10. Testing Plan

- Unit test each heuristic verdict in isolation (`metrics.py`) with fixture canonical/docling JSON
- Unit test `quality_status` derivation: all-good → `good`; mixed weak → `weak`; any poor → `poor`
- Unit test `is_latest` flip logic: second audit on same content_hash sets first row `is_latest=False`; **assert both rows still exist** (history preserved, not deleted)
- Unit test fallback-parser path: no docling.json → table/visual readiness degrades correctly; `fallback_reason` populated
- Unit test `failed_stage` capture: mock each read stage to raise, assert correct stage recorded in DB
- Unit test artifact write failure: mock artifact directory as unwritable → assert `audit_status=failed`, `failed_stage=write_artifacts`, `artifact_json_path=null`, `artifact_md_path=null`, **`summary_json` still populated** (metrics completed before write)
- Integration test (in-memory SQLite + tmp_path): full audit run on fixture canonical → DB row + artifact files + `elapsed_ms` present
- CLI test: `--canonical-path` and `--all-indexed` with fixture data

---

## 11. Out of Scope (Phase 7A)

- `--all-ingested` CLI flag — deferred
- API endpoint (`GET /audit/<doc_id>`) — deferred to Phase 7B
- Cross-document aggregate report — deferred (reporting.py structure designed to support it later)
- Gating Phase 7B indexing on audit verdicts — Phase 7A verdicts are advisory only
