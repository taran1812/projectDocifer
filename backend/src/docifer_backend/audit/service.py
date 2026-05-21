from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.audit.metrics import (
    AUDIT_VERSION,
    AuditSummary,
    AuditVerdicts,
    compute_summary,
    compute_verdicts,
    detect_fallback,
)
from docifer_backend.audit.models import ParseQualityAudit
from docifer_backend.audit.reporting import write_audit_artifacts
from docifer_backend.config.paths import display_path, resolve_project_path
from docifer_backend.ingestion.models import Document, IngestionJob, new_uuid
from docifer_backend.ingestion.status import IngestionStatus
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.storage.database import get_session_factory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParseQualityReport:
    audit_id: str
    content_hash: str
    audit_status: str
    quality_status: str | None
    text_readiness: str | None
    table_readiness: str | None
    visual_readiness: str | None
    risk_flags: list[str] = field(default_factory=list)
    elapsed_ms: int | None = None
    error_message: str | None = None
    failed_stage: str | None = None


class ParseQualityService:
    def __init__(self, *, session_factory: sessionmaker[Session] | None = None) -> None:
        self.session_factory = session_factory or get_session_factory()

    def audit(
        self,
        canonical_path: str | Path,
        content_hash: str,
        *,
        audit_run_id: str | None = None,
    ) -> ParseQualityReport:
        """Audit a canonical artifact. Never raises — failures are recorded in DB."""
        run_id = audit_run_id or str(uuid4())
        audit_id = new_uuid()
        canonical_path = Path(canonical_path)
        start_ms = int(time.monotonic() * 1000)

        try:
            document_id = self._get_document_id(content_hash)
        except Exception as exc:
            logger.error("DB lookup failed for content_hash %s: %s", content_hash[:12], exc)
            return ParseQualityReport(
                audit_id=audit_id,
                content_hash=content_hash,
                audit_status="failed",
                quality_status=None,
                text_readiness=None,
                table_readiness=None,
                visual_readiness=None,
                elapsed_ms=int(time.monotonic() * 1000) - start_ms,
                error_message=str(exc),
                failed_stage="read_canonical",
            )

        summary: AuditSummary | None = None
        verdicts: AuditVerdicts | None = None
        fallback_used = False
        fallback_reason: str | None = None
        parser_name = "unknown"
        parser_version: str | None = None
        canonical_schema_version: str | None = None

        # Stage: read_canonical
        try:
            canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return self._persist_failed(
                audit_id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=str(canonical_path),
                run_id=run_id,
                failed_stage="read_canonical",
                error_message=str(exc),
                elapsed_ms=int(time.monotonic() * 1000) - start_ms,
            )

        canonical_schema_version = canonical.get("schema_version")
        parser_name = canonical.get("parser", {}).get("name", "unknown")
        parser_version = canonical.get("parser", {}).get("version")
        fallback_used, fallback_reason = detect_fallback(canonical)

        # Stage: read_markdown
        md_path_str = canonical.get("artifacts", {}).get("markdown", "")
        try:
            markdown_text = resolve_project_path(md_path_str).read_text(encoding="utf-8")
        except Exception as exc:
            return self._persist_failed(
                audit_id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=display_path(canonical_path),
                run_id=run_id,
                failed_stage="read_markdown",
                error_message=str(exc),
                elapsed_ms=int(time.monotonic() * 1000) - start_ms,
                parser_name=parser_name,
                parser_version=parser_version,
                canonical_schema_version=canonical_schema_version,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )

        # Stage: read_docling_json (optional — failure is non-fatal)
        docling: dict | None = None
        docling_missing = False
        docling_path_str = canonical.get("artifacts", {}).get("docling_json", "")
        if docling_path_str:
            try:
                docling_path = resolve_project_path(docling_path_str)
                if docling_path.exists():
                    docling = json.loads(docling_path.read_text(encoding="utf-8"))
                else:
                    docling_missing = True
            except Exception as exc:
                logger.warning("Could not read docling.json: %s", exc)
                docling_missing = True

        # Fetch chunk count before compute stage — failure silently defaults to 0
        # (chunk count is supplementary; a DB error here should not fail the audit)
        try:
            chunk_count = self._get_chunk_count(content_hash)
        except Exception as exc:
            logger.warning("Could not fetch chunk count for %s: %s", content_hash[:12], exc)
            chunk_count = 0

        # Stage: compute_metrics
        try:
            summary = compute_summary(canonical, markdown_text, docling, chunk_count=chunk_count)
            verdicts = compute_verdicts(summary, fallback_used=fallback_used, docling_missing=docling_missing)
        except Exception as exc:
            return self._persist_failed(
                audit_id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=display_path(canonical_path),
                run_id=run_id,
                failed_stage="compute_metrics",
                error_message=str(exc),
                elapsed_ms=int(time.monotonic() * 1000) - start_ms,
                parser_name=parser_name,
                parser_version=parser_version,
                canonical_schema_version=canonical_schema_version,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )

        elapsed_ms = int(time.monotonic() * 1000) - start_ms

        # Stage: write_artifacts
        artifact_json_path: str | None = None
        artifact_md_path: str | None = None
        write_failed = False
        write_error: str | None = None
        try:
            artifact_json_path, artifact_md_path = write_audit_artifacts(
                artifact_dir=canonical_path.parent,
                content_hash=content_hash,
                audit_run_id=run_id,
                audit_status="completed",
                summary=summary,
                verdicts=verdicts,
                elapsed_ms=elapsed_ms,
                fallback_used=fallback_used,
                parser_name=parser_name,
            )
        except Exception as exc:
            write_failed = True
            write_error = str(exc)
            logger.warning("Audit artifact write failed for %s: %s", content_hash[:12], exc)

        if write_failed:
            return self._persist_failed(
                audit_id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=display_path(canonical_path),
                run_id=run_id,
                failed_stage="write_artifacts",
                error_message=write_error,
                elapsed_ms=elapsed_ms,
                parser_name=parser_name,
                parser_version=parser_version,
                canonical_schema_version=canonical_schema_version,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                summary=summary,
                verdicts=verdicts,
            )

        # Stage: persist_db
        try:
            self._persist_completed(
                audit_id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=display_path(canonical_path),
                run_id=run_id,
                parser_name=parser_name,
                parser_version=parser_version,
                canonical_schema_version=canonical_schema_version,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                summary=summary,
                verdicts=verdicts,
                artifact_json_path=display_path(artifact_json_path) if artifact_json_path else None,
                artifact_md_path=display_path(artifact_md_path) if artifact_md_path else None,
                elapsed_ms=elapsed_ms,
            )
        except Exception as exc:
            logger.error("Audit DB persist failed for %s: %s", content_hash[:12], exc)
            return ParseQualityReport(
                audit_id=audit_id,
                content_hash=content_hash,
                audit_status="failed",
                quality_status=verdicts.quality_status if verdicts else None,
                text_readiness=verdicts.text_readiness if verdicts else None,
                table_readiness=verdicts.table_readiness if verdicts else None,
                visual_readiness=verdicts.visual_readiness if verdicts else None,
                risk_flags=list(verdicts.risk_flags) if verdicts else [],
                elapsed_ms=elapsed_ms,
                error_message=str(exc),
                failed_stage="persist_db",
            )

        return ParseQualityReport(
            audit_id=audit_id,
            content_hash=content_hash,
            audit_status="completed",
            quality_status=verdicts.quality_status,
            text_readiness=verdicts.text_readiness,
            table_readiness=verdicts.table_readiness,
            visual_readiness=verdicts.visual_readiness,
            risk_flags=list(verdicts.risk_flags),
            elapsed_ms=elapsed_ms,
        )

    def audit_by_content_hash(
        self,
        content_hash: str,
        *,
        audit_run_id: str | None = None,
    ) -> ParseQualityReport:
        """Resolve canonical path from DB then audit."""
        with self.session_factory() as session:
            job = session.scalar(
                select(IngestionJob)
                .where(IngestionJob.content_hash == content_hash)
                .where(
                    IngestionJob.status.in_([
                        IngestionStatus.PARSED.value,
                        IngestionStatus.INDEXED.value,
                    ])
                )
                .where(IngestionJob.artifact_path.isnot(None))
                .order_by(IngestionJob.completed_at.desc().nullslast())
            )
        if job is None:
            return ParseQualityReport(
                audit_id=new_uuid(),
                content_hash=content_hash,
                audit_status="failed",
                quality_status=None,
                text_readiness=None,
                table_readiness=None,
                visual_readiness=None,
                error_message=f"No completed ingestion job found for content_hash {content_hash[:12]}",
                failed_stage="read_canonical",
            )
        return self.audit(
            resolve_project_path(job.artifact_path),
            content_hash,
            audit_run_id=audit_run_id,
        )

    def audit_all_indexed(self, *, audit_run_id: str | None = None) -> list[ParseQualityReport]:
        """Audit all documents with at least one indexed text chunk."""
        run_id = audit_run_id or str(uuid4())
        rows = self._get_indexed_content_hashes_and_paths()
        results = []
        for content_hash, artifact_path in rows:
            report = self.audit(
                resolve_project_path(artifact_path),
                content_hash,
                audit_run_id=run_id,
            )
            results.append(report)
        return results

    # ── private ──────────────────────────────────────────────────────────────

    def _get_document_id(self, content_hash: str) -> str | None:
        with self.session_factory() as session:
            doc = session.scalar(
                select(Document).where(Document.content_hash == content_hash)
            )
            return doc.id if doc else None

    def _get_chunk_count(self, content_hash: str) -> int:
        from sqlalchemy import func
        with self.session_factory() as session:
            count = session.scalar(
                select(func.count())
                .select_from(TextChunkRecord)
                .where(TextChunkRecord.content_hash == content_hash)
            )
            return int(count or 0)

    def _get_indexed_content_hashes_and_paths(self) -> list[tuple[str, str]]:
        with self.session_factory() as session:
            rows = session.execute(
                select(Document.content_hash, IngestionJob.artifact_path)
                .join(
                    TextChunkRecord,
                    TextChunkRecord.content_hash == Document.content_hash,
                )
                .join(
                    IngestionJob,
                    (IngestionJob.content_hash == Document.content_hash)
                    & IngestionJob.artifact_path.isnot(None)
                    & IngestionJob.status.in_([
                        IngestionStatus.PARSED.value,
                        IngestionStatus.INDEXED.value,
                    ]),
                )
                .distinct()
            ).all()
            return [(row[0], row[1]) for row in rows]

    def _persist_failed(
        self,
        *,
        audit_id: str,
        document_id: str | None,
        content_hash: str,
        canonical_path: str,
        run_id: str,
        failed_stage: str,
        error_message: str,
        elapsed_ms: int,
        parser_name: str = "unknown",
        parser_version: str | None = None,
        canonical_schema_version: str | None = None,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
        summary: AuditSummary | None = None,
        verdicts: AuditVerdicts | None = None,
    ) -> ParseQualityReport:
        logger.warning(
            "Audit failed at stage=%s for content_hash=%s: %s",
            failed_stage, content_hash[:12], error_message,
        )
        if document_id is None:
            logger.error("Cannot persist audit row: no document_id for %s", content_hash[:12])
            return ParseQualityReport(
                audit_id=audit_id,
                content_hash=content_hash,
                audit_status="failed",
                quality_status=None,
                text_readiness=None,
                table_readiness=None,
                visual_readiness=None,
                elapsed_ms=elapsed_ms,
                error_message=error_message,
                failed_stage=failed_stage,
            )
        try:
            row = ParseQualityAudit(
                id=audit_id,
                document_id=document_id,
                content_hash=content_hash,
                canonical_path=canonical_path,
                parser_name=parser_name,
                parser_version=parser_version,
                canonical_schema_version=canonical_schema_version,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                audit_version=AUDIT_VERSION,
                audit_run_id=run_id,
                audit_status="failed",
                error_message=error_message,
                failed_stage=failed_stage,
                is_latest=True,
                quality_status=verdicts.quality_status if verdicts else None,
                text_readiness=verdicts.text_readiness if verdicts else None,
                table_readiness=verdicts.table_readiness if verdicts else None,
                visual_readiness=verdicts.visual_readiness if verdicts else None,
                risk_flags_json=list(verdicts.risk_flags) if verdicts else None,
                summary_json=_summary_to_dict(summary) if summary else None,
                artifact_json_path=None,
                artifact_md_path=None,
                elapsed_ms=elapsed_ms,
            )
            self._insert_with_is_latest_flip(row, content_hash)
        except Exception as exc:
            logger.error("Could not persist failed audit row: %s", exc)
        return ParseQualityReport(
            audit_id=audit_id,
            content_hash=content_hash,
            audit_status="failed",
            quality_status=verdicts.quality_status if verdicts else None,
            text_readiness=verdicts.text_readiness if verdicts else None,
            table_readiness=verdicts.table_readiness if verdicts else None,
            visual_readiness=verdicts.visual_readiness if verdicts else None,
            risk_flags=list(verdicts.risk_flags) if verdicts else [],
            elapsed_ms=elapsed_ms,
            error_message=error_message,
            failed_stage=failed_stage,
        )

    def _persist_completed(
        self,
        *,
        audit_id: str,
        document_id: str | None,
        content_hash: str,
        canonical_path: str,
        run_id: str,
        parser_name: str,
        parser_version: str | None,
        canonical_schema_version: str | None,
        fallback_used: bool,
        fallback_reason: str | None,
        summary: AuditSummary,
        verdicts: AuditVerdicts,
        artifact_json_path: str | None,
        artifact_md_path: str | None,
        elapsed_ms: int,
    ) -> None:
        if document_id is None:
            raise ValueError(f"No document_id for content_hash {content_hash[:12]}")
        row = ParseQualityAudit(
            id=audit_id,
            document_id=document_id,
            content_hash=content_hash,
            canonical_path=canonical_path,
            parser_name=parser_name,
            parser_version=parser_version,
            canonical_schema_version=canonical_schema_version,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            audit_version=AUDIT_VERSION,
            audit_run_id=run_id,
            audit_status="completed",
            error_message=None,
            failed_stage=None,
            is_latest=True,
            quality_status=verdicts.quality_status,
            text_readiness=verdicts.text_readiness,
            table_readiness=verdicts.table_readiness,
            visual_readiness=verdicts.visual_readiness,
            risk_flags_json=list(verdicts.risk_flags),
            summary_json=_summary_to_dict(summary),
            artifact_json_path=artifact_json_path,
            artifact_md_path=artifact_md_path,
            elapsed_ms=elapsed_ms,
        )
        self._insert_with_is_latest_flip(row, content_hash)

    def _insert_with_is_latest_flip(self, row: ParseQualityAudit, content_hash: str) -> None:
        # NOTE: is_latest maintenance assumes serial execution per content_hash.
        # Concurrent audits of the same document could produce multiple is_latest=True rows
        # (write-skew). Phase 7A runs audits serially via CLI or post-ingestion hook,
        # so this is acceptable. Add SELECT FOR UPDATE if concurrent access is needed.
        with self.session_factory() as session:
            session.add(row)
            session.flush()
            session.execute(
                ParseQualityAudit.__table__.update()
                .where(ParseQualityAudit.content_hash == content_hash)
                .where(ParseQualityAudit.id != row.id)
                .values(is_latest=False)
            )
            session.commit()


def _summary_to_dict(s: AuditSummary) -> dict:
    return {
        "page_count": s.page_count,
        "table_count": s.table_count,
        "table_candidate_count": s.table_candidate_count,
        "table_like_page_count": s.table_like_page_count,
        "figure_count": s.figure_count,
        "figure_candidate_count": s.figure_candidate_count,
        "caption_candidate_count": s.caption_candidate_count,
        "empty_page_count": s.empty_page_count,
        "text_chars_total": s.text_chars_total,
        "avg_chars_per_page": s.avg_chars_per_page,
        "parse_error_count": s.parse_error_count,
        "chunk_count": s.chunk_count,
    }
