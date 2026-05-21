from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docifer_backend.config.paths import display_path, resolve_project_path
from docifer_backend.config.settings import get_settings
from docifer_backend.ingestion.file_info import PdfFileInfo, inspect_pdf_file
from docifer_backend.ingestion.models import Document, IngestionJob, utc_now
from docifer_backend.ingestion.parser import AutoPdfParser, DocumentParser, ParsedDocument
from docifer_backend.ingestion.status import IngestionStatus
from docifer_backend.storage.database import create_database_schema, get_session_factory


@dataclass(frozen=True)
class IngestionOutcome:
    job_id: str
    document_id: str
    status: str
    artifact_path: str | None
    reused_existing: bool
    error_message: str | None = None


class IngestionService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
        parser: DocumentParser | None = None,
        processed_data_dir: str | Path | None = None,
        max_attempts: int = 2,
        initialize_schema: bool = True,
    ) -> None:
        if session_factory is None and initialize_schema:
            create_database_schema()

        settings = get_settings()
        self.session_factory = session_factory or get_session_factory()
        self.parser = parser or AutoPdfParser(
            backend=settings.pdf_parser_backend,
            docling_max_file_size_bytes=settings.docling_max_file_size_bytes,
        )
        self.processed_data_dir = resolve_project_path(
            processed_data_dir or settings.processed_data_dir
        )
        self.max_attempts = max_attempts

    def ingest_pdf(
        self,
        source_path: str | Path,
        *,
        force_reprocess: bool = False,
    ) -> IngestionOutcome:
        file_info = inspect_pdf_file(resolve_project_path(source_path))

        with self.session_factory() as session:
            document = self._get_or_create_document(session, file_info)
            if not force_reprocess:
                existing_job = self._find_successful_job(session, file_info.content_hash)
                if existing_job and existing_job.artifact_path:
                    artifact = resolve_project_path(existing_job.artifact_path)
                    if artifact.exists():
                        return IngestionOutcome(
                            job_id=existing_job.id,
                            document_id=existing_job.document_id,
                            status=existing_job.status,
                            artifact_path=existing_job.artifact_path,
                            reused_existing=True,
                        )

            job = IngestionJob(
                document_id=document.id,
                source_path=str(file_info.path),
                content_hash=file_info.content_hash,
                status=IngestionStatus.QUEUED.value,
                max_attempts=self.max_attempts,
            )
            session.add(job)
            session.flush()
            document.latest_job_id = job.id
            session.commit()

            return self._parse_with_retries(job.id, file_info)

    def get_job(self, job_id: str) -> IngestionOutcome | None:
        with self.session_factory() as session:
            job = session.get(IngestionJob, job_id)
            if job is None:
                return None
            return _outcome_from_job(job, reused_existing=False)

    def _parse_with_retries(self, job_id: str, file_info: PdfFileInfo) -> IngestionOutcome:
        last_error: str | None = None
        for attempt in range(1, self.max_attempts + 1):
            with self.session_factory() as session:
                job = session.get(IngestionJob, job_id)
                if job is None:
                    raise RuntimeError(f"Ingestion job disappeared: {job_id}")
                job.status = IngestionStatus.PARSING.value
                job.attempt_count = attempt
                job.started_at = job.started_at or utc_now()
                job.error_type = None
                job.error_message = None
                job.error_detail = None
                session.commit()

            try:
                parsed_document = self.parser.parse(file_info.path)
                artifact_path = self._write_artifacts(job_id, file_info, parsed_document)
                with self.session_factory() as session:
                    job = session.get(IngestionJob, job_id)
                    if job is None:
                        raise RuntimeError(f"Ingestion job disappeared: {job_id}")
                    job.status = IngestionStatus.PARSED.value
                    job.parser_name = parsed_document.parser_name
                    job.parser_version = parsed_document.parser_version
                    job.artifact_path = display_path(artifact_path)
                    job.completed_at = utc_now()
                    session.commit()
                    return _outcome_from_job(job, reused_existing=False)
            except Exception as exc:
                last_error = str(exc)
                with self.session_factory() as session:
                    job = session.get(IngestionJob, job_id)
                    if job is None:
                        raise RuntimeError(f"Ingestion job disappeared: {job_id}")
                    job.error_type = type(exc).__name__
                    job.error_message = str(exc)
                    job.error_detail = {
                        "attempt": attempt,
                        "traceback": traceback.format_exc(),
                    }
                    if attempt == self.max_attempts:
                        job.status = IngestionStatus.FAILED.value
                        job.completed_at = utc_now()
                    session.commit()

        with self.session_factory() as session:
            job = session.get(IngestionJob, job_id)
            if job is None:
                raise RuntimeError(f"Ingestion job disappeared: {job_id}")
            return _outcome_from_job(job, reused_existing=False, error_message=last_error)

    def _get_or_create_document(self, session: Session, file_info: PdfFileInfo) -> Document:
        document = session.scalar(
            select(Document).where(Document.content_hash == file_info.content_hash)
        )
        if document:
            document.filename = file_info.filename
            document.source_path = str(file_info.path)
            document.file_size_bytes = file_info.file_size_bytes
            session.commit()
            return document

        document = Document(
            filename=file_info.filename,
            source_path=str(file_info.path),
            content_hash=file_info.content_hash,
            file_size_bytes=file_info.file_size_bytes,
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        return document

    def _find_successful_job(self, session: Session, content_hash: str) -> IngestionJob | None:
        return session.scalar(
            select(IngestionJob)
            .where(IngestionJob.content_hash == content_hash)
            .where(IngestionJob.status.in_([IngestionStatus.PARSED.value, IngestionStatus.INDEXED.value]))
            .order_by(IngestionJob.completed_at.desc().nullslast())
        )

    def _write_artifacts(
        self,
        job_id: str,
        file_info: PdfFileInfo,
        parsed_document: ParsedDocument,
    ) -> Path:
        artifact_dir = (
            self.processed_data_dir
            / file_info.content_hash[:12]
            / job_id
        )
        artifact_dir.mkdir(parents=True, exist_ok=True)

        docling_path = artifact_dir / "docling.json"
        markdown_path = artifact_dir / "document.md"
        canonical_path = artifact_dir / "canonical.json"
        summary_path = artifact_dir / "parse_summary.json"

        _write_json(docling_path, parsed_document.raw_document)
        markdown_path.write_text(parsed_document.markdown, encoding="utf-8")

        canonical = _build_canonical_document(
            file_info=file_info,
            job_id=job_id,
            parsed_document=parsed_document,
            artifact_dir=artifact_dir,
            docling_path=docling_path,
            markdown_path=markdown_path,
        )
        _write_json(canonical_path, canonical)
        _write_json(summary_path, canonical["parse"])

        return canonical_path


def _build_canonical_document(
    *,
    file_info: PdfFileInfo,
    job_id: str,
    parsed_document: ParsedDocument,
    artifact_dir: Path,
    docling_path: Path,
    markdown_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": "docifer.canonical_document.v1",
        "document": {
            "filename": file_info.filename,
            "source_path": display_path(file_info.path),
            "content_hash": file_info.content_hash,
            "file_size_bytes": file_info.file_size_bytes,
        },
        "ingestion": {
            "job_id": job_id,
            "status": IngestionStatus.PARSED.value,
        },
        "parser": {
            "name": parsed_document.parser_name,
            "version": parsed_document.parser_version,
            "docling_status": parsed_document.docling_status,
        },
        "artifacts": {
            "directory": display_path(artifact_dir),
            "canonical_json": display_path(artifact_dir / "canonical.json"),
            "docling_json": display_path(docling_path),
            "markdown": display_path(markdown_path),
        },
        "pages": [
            {"page_number": page_number}
            for page_number in range(1, parsed_document.page_count + 1)
        ],
        "content": {
            "markdown_char_count": len(parsed_document.markdown),
        },
        "structures": {
            "tables": {"count": parsed_document.table_count},
            "figures": {"count": parsed_document.figure_count},
        },
        "parse": {
            "status": parsed_document.docling_status,
            "page_count": parsed_document.page_count,
            "table_count": parsed_document.table_count,
            "figure_count": parsed_document.figure_count,
            "errors": parsed_document.errors,
        },
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _outcome_from_job(
    job: IngestionJob,
    *,
    reused_existing: bool,
    error_message: str | None = None,
) -> IngestionOutcome:
    return IngestionOutcome(
        job_id=job.id,
        document_id=job.document_id,
        status=job.status,
        artifact_path=job.artifact_path,
        reused_existing=reused_existing,
        error_message=error_message or job.error_message,
    )
